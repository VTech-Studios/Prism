from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from ..domain.automation import Rule
from ..domain.profile import Profile
from ..domain.settings import Settings
from ..ports import Autostart, SettingsStore, SleepWatch
from .automation import AutomationService
from .cooling import CoolingController
from .lighting import LightingEngine
from .presets import starter_profiles
from .profiles import ProfileLibrary
from .registry import DeviceRegistry
from .state import PrismState
from .telemetry import Sample, Telemetry

SAMPLE_INTERVAL = 1.0
RECONNECT_INTERVAL = 10.0

_LOG = logging.getLogger(__name__)


class PrismCore:
    """Runs the show: applies profiles, follows rules, drives fans and keeps devices connected.

    Every method runs on one thread, the runtime loop's, so nothing here needs locking.
    Each step of a tick is isolated from the others, so a fault in lighting or a
    sensor can never stop the fans being driven.
    """

    def __init__(
        self,
        *,
        registry: DeviceRegistry,
        lighting: LightingEngine,
        cooling: CoolingController,
        telemetry: Telemetry,
        library: ProfileLibrary,
        automation: AutomationService,
        settings_store: SettingsStore,
        autostart: Autostart,
        sleep: SleepWatch,
        clock: Callable[[], float],
    ) -> None:
        self._registry = registry
        self._lighting = lighting
        self._cooling = cooling
        self._telemetry = telemetry
        self._library = library
        self._automation = automation
        self._settings_store = settings_store
        self._autostart = autostart
        self._sleep = sleep
        self._clock = clock
        self._settings = settings_store.load()
        self._showing = ""
        self._rule: Rule | None = None
        self._sample = Sample()
        self._generation = -1
        self._next_sample = 0.0
        self._next_reconnect = 0.0
        self._notice: tuple[int, str] | None = None
        self.changed = True

    @property
    def settings(self) -> Settings:
        """The current settings."""
        return self._settings

    def start(self) -> None:
        """Connect to every device, make the first-run profiles if needed, and show the chosen profile."""
        self._registry.connect_offline()
        self._next_reconnect = self._clock() + RECONNECT_INTERVAL
        self._library.seed(starter_profiles(self._registry.zones(), self._registry.fans()))
        if self._settings.active_profile not in self._library.names():
            self._settings = replace(self._settings, active_profile=self._library.names()[0])
        self._sync_devices()
        self._show(self._settings.active_profile, force=True)

    def tick(self) -> None:
        """Draw the next lighting frame, and once a second measure, follow rules and drive the fans."""
        now = self._clock()
        self._isolated("reconnecting devices", lambda: self._reconnect(now))
        self._isolated("resyncing devices", self._sync_devices)
        if now >= self._next_sample:
            self._next_sample = now + SAMPLE_INTERVAL
            self._isolated("measuring", lambda: self._measure(now), on_failure=self._forget_sample)
            self._isolated(
                "driving the fans", lambda: self._cooling.tick(self._sample.snapshot.readings, now)
            )
        self._isolated("drawing lighting", lambda: self._lighting.tick(now, self._sample.snapshot.readings))

    def shutdown(self) -> None:
        """Leave the fans at the exit duty and release every device, even if one step fails."""
        self._isolated("handing off the fans", lambda: self._cooling.hand_off(self._settings.handoff_duty))
        self._isolated("closing devices", self._registry.close)

    def notify(self, message: str) -> None:
        """Show the user a message, such as why a command was refused.

        @param message: the message.
        """
        number = self._notice[0] + 1 if self._notice else 1
        self._notice = (number, message)
        self.changed = True

    def choose_profile(self, name: str) -> None:
        """Make a profile the one shown when no rule applies.

        @param name: the profile.
        """
        self._library.get(name)
        self._update_settings(replace(self._settings, active_profile=name))
        if self._rule is None:
            self._show(name, force=True)

    def save_profile(self, profile: Profile) -> None:
        """Store a profile, and show the change at once if it is on screen.

        @param profile: the profile.
        """
        self._library.save(profile)
        if profile.name == self._showing:
            self._show(profile.name, force=True)
        self.changed = True

    def edit_chosen(self, change: Callable[[Profile], Profile]) -> None:
        """Change whichever profile is chosen at the moment the edit runs.

        @param change: makes the edited profile from the current one.
        """
        self.edit_profile(self._settings.active_profile, change)

    def edit_profile(self, name: str, change: Callable[[Profile], Profile]) -> None:
        """Change a profile based on its latest saved version, so quick edits never undo each other.

        @param name: the profile.
        @param change: makes the edited profile from the current one.
        """
        self.save_profile(change(self._library.get(name)))

    def create_profile(self, name: str) -> None:
        """@param name: the new, empty profile's name."""
        self._library.create(name)
        self.changed = True

    def duplicate_profile(self, name: str) -> None:
        """@param name: the profile to copy."""
        self._library.duplicate(name)
        self.changed = True

    def import_profile(self, profile: Profile) -> None:
        """@param profile: a profile read from a file."""
        stored = self._library.add_imported(profile)
        self.notify(f"Imported {stored.name}")

    def rename_profile(self, old: str, new: str) -> None:
        """Rename a profile and everything that refers to it.

        @param old: the current name.
        @param new: the new name.
        """
        self._library.rename(old, new)
        new = new.strip()
        self._automation.profile_renamed(old, new)
        if self._settings.active_profile == old:
            self._update_settings(replace(self._settings, active_profile=new))
        if self._showing == old:
            self._showing = new
        self.changed = True

    def delete_profile(self, name: str) -> None:
        """Delete a profile, falling back to the first remaining one if it was chosen.

        @param name: the profile.
        """
        self._library.delete(name)
        if self._settings.active_profile == name:
            self.choose_profile(self._library.names()[0])
        self.changed = True

    def save_rule(self, rule: Rule, replacing: str | None) -> None:
        """@param replacing: the name of the rule being edited, or None for a new one."""
        self._automation.save_rule(rule, replacing)
        self.changed = True

    def delete_rule(self, name: str) -> None:
        """@param name: the rule to remove."""
        self._automation.delete_rule(name)
        self.changed = True

    def move_rule(self, name: str, offset: int) -> None:
        """@param offset: -1 to raise the rule's priority, +1 to lower it."""
        self._automation.move_rule(name, offset)
        self.changed = True

    def update_settings(self, settings: Settings) -> None:
        """Save new settings and put them into effect.

        @param settings: the settings.
        """
        self._update_settings(settings)
        self._lighting.set_prefer_hardware(settings.prefer_hardware)
        self._cooling.set_floor(settings.fan_floor)
        if not settings.automation and self._rule is not None:
            self._rule = None
            self._show(settings.active_profile, force=True)

    def set_autostart(self, enabled: bool) -> None:
        """@param enabled: whether Prism should start at login."""
        self._autostart.set_enabled(enabled)
        self.changed = True

    def state(self) -> PrismState:
        """@return: a snapshot of everything the window shows."""
        zones = self._registry.zones()
        state = PrismState(
            settings=self._settings,
            profiles=tuple(self._library.profiles),
            chosen=self._settings.active_profile,
            showing=self._showing,
            rule=self._rule.name if self._rule else None,
            rules=tuple(self._automation.rules),
            zones=tuple(zones),
            fans=tuple(self._registry.fans()),
            sensors=tuple(self._telemetry.sensors()),
            readings=dict(self._sample.snapshot.readings),
            speeds=dict(self._sample.speeds),
            duties=self._cooling.duties,
            statuses=tuple(self._registry.statuses()),
            drawn=frozenset(zone.id for zone in zones if self._lighting.is_drawn(zone.id)),
            has_pump=bool(self._registry.pumps()),
            autostart=self._autostart.enabled(),
            notice=self._notice,
        )
        self.changed = False
        return state

    def _reconnect(self, now: float) -> None:
        """Retry offline devices now and then, and reopen everything after the machine wakes.

        Devices come back from suspend in their power-on state, so after a
        wake every device is reopened and given its settings again.

        @param now: the monotonic time.
        """
        if self._sleep.woke():
            _LOG.info("woke from suspend, reopening every device")
            self._registry.reopen()
        if now >= self._next_reconnect:
            self._next_reconnect = now + RECONNECT_INTERVAL
            self._registry.connect_offline()

    def _measure(self, now: float) -> None:
        """Take a sample and let the rules pick a profile.

        @param now: the monotonic time.
        """
        self._sample = self._telemetry.sample(self._automation.watches_processes())
        if self._settings.automation:
            target, self._rule = self._automation.choose(
                self._sample.snapshot, now, self._settings.active_profile, self._library.names()
            )
            self._show(target)
        self.changed = True

    def _forget_sample(self) -> None:
        """Drop the last sample, so fans run at their failsafe speed instead of on old readings."""
        self._sample = Sample()

    def _isolated(
        self, step: str, action: Callable[[], object], on_failure: Callable[[], None] | None = None
    ) -> None:
        """Run one step of a tick, logging any failure instead of letting it stop the next step.

        @param step: what the step does, for the log.
        @param action: the step.
        @param on_failure: what to do after the step fails, if anything.
        """
        try:
            action()
        except Exception:
            _LOG.exception("failed while %s", step)
            if on_failure is not None:
                on_failure()

    def _show(self, name: str, force: bool = False) -> None:
        """Apply a profile to every device.

        @param name: the profile.
        @param force: apply even if it is already showing, after it was edited.
        """
        if name == self._showing and not force:
            return
        profile = self._library.get(name)
        self._cooling.apply(profile.cooling, profile.pump)
        self._isolated("showing lighting", lambda: self._lighting.show(profile.lighting))
        self._showing = name
        self.changed = True

    def _sync_devices(self) -> None:
        """Resend everything after a device connects or drops off."""
        if self._registry.generation != self._generation:
            self._generation = self._registry.generation
            self._cooling.refresh()
            self._isolated("resending lighting", self._lighting.refresh)
            self.changed = True

    def _update_settings(self, settings: Settings) -> None:
        """Keep and save new settings.

        @param settings: the settings.
        """
        self._settings = settings
        self._settings_store.save(settings)
        self.changed = True
