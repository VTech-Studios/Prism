from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..domain.automation import Rule
from ..domain.devices import DeviceStatus, FanChannel, LightingZone, Sensor
from ..domain.profile import Profile
from ..domain.settings import Settings


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
