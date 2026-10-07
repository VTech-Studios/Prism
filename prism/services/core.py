from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from ..domain.automation import Rule
from ..domain.devices import DeviceStatus, FanChannel, LightingZone, Sensor
from ..domain.profile import Profile
from ..domain.settings import Settings
from ..ports import Autostart, SettingsStore
from .automation import AutomationService
from .cooling import CoolingController
from .lighting import LightingEngine
from .presets import starter_profiles
from .profiles import ProfileLibrary
from .registry import DeviceRegistry
from .telemetry import Sample, Telemetry

SAMPLE_INTERVAL = 1.0
RECONNECT_INTERVAL = 10.0


@dataclass(frozen=True, slots=True)
class PrismState:
    """A consistent picture of everything the window shows, published after each change.

    @ivar chosen: the profile the user picked.
    @ivar showing: the profile actually applied, which a rule may have switched to.
    @ivar rule: the name of the rule in charge, if any.
    @ivar drawn: zones Prism draws itself, rather than the device playing the effect.
    @ivar has_pump: whether an AIO pump is connected.
    @ivar notice: the latest message for the user, paired with a counter so repeats still show.
    """

    settings: Settings
    profiles: tuple[Profile, ...]
    chosen: str
    showing: str
    rule: str | None
    rules: tuple[Rule, ...]
    zones: tuple[LightingZone, ...]
    fans: tuple[FanChannel, ...]
    sensors: tuple[Sensor, ...]
    readings: Mapping[str, float]
    speeds: Mapping[str, int]
    duties: Mapping[str, int]
    statuses: tuple[DeviceStatus, ...]
    drawn: frozenset[str]
    has_pump: bool
    autostart: bool
    notice: tuple[int, str] | None = field(default=None)

    def profile(self, name: str) -> Profile | None:
        """@return: the named profile, or None if it no longer exists."""
        return next((profile for profile in self.profiles if profile.name == name), None)


class PrismCore:
    """Runs the show: applies profiles, follows rules, drives fans and keeps devices connected.

    Every method runs on one thread, the runtime loop's, so nothing here needs locking.
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
        if now >= self._next_reconnect:
            self._next_reconnect = now + RECONNECT_INTERVAL
            self._registry.connect_offline()
        self._sync_devices()
        if now >= self._next_sample:
            self._next_sample = now + SAMPLE_INTERVAL
            self._measure(now)
        self._lighting.tick(now, self._sample.snapshot.readings)

    def shutdown(self) -> None:
        """Leave the fans at the exit duty and release every device."""
        self._cooling.hand_off(self._settings.handoff_duty)
        self._registry.close()

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
        self.changed = False
        zones = self._registry.zones()
        return PrismState(
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

    def _measure(self, now: float) -> None:
        """Take a sample, let the rules pick a profile, and drive the fans.

        @param now: the monotonic time.
        """
        self._sample = self._telemetry.sample(self._automation.watches_processes())
        if self._settings.automation:
            target, self._rule = self._automation.choose(
                self._sample.snapshot, now, self._settings.active_profile, self._library.names()
            )
            self._show(target)
        self._cooling.tick(self._sample.snapshot.readings)
        self.changed = True

    def _show(self, name: str, force: bool = False) -> None:
        """Apply a profile to every device.

        @param name: the profile.
        @param force: apply even if it is already showing, after it was edited.
        """
        if name == self._showing and not force:
            return
        profile = self._library.get(name)
        self._showing = name
        self._lighting.show(profile.lighting)
        self._cooling.apply(profile.cooling, profile.pump)
        self.changed = True

    def _sync_devices(self) -> None:
        """Resend everything after a device connects or drops off."""
        if self._registry.generation != self._generation:
            self._generation = self._registry.generation
            self._lighting.refresh()
            self._cooling.refresh()
            self.changed = True

    def _update_settings(self, settings: Settings) -> None:
        """Keep and save new settings.

        @param settings: the settings.
        """
        self._settings = settings
        self._settings_store.save(settings)
        self.changed = True
