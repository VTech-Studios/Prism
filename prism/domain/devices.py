from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .effects import EffectKind


class DeviceKind(StrEnum):
    FAN_CONTROLLER = "fan_controller"
    COOLER = "cooler"
    MEMORY = "memory"
    GPU = "gpu"
    MOTHERBOARD = "motherboard"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LightingZone:
    """A run of LEDs that is given one effect, such as the case fans or a stick of RAM.

    @ivar id: a stable key that profiles use to remember the zone's effect.
    @ivar hardware_effects: effects the device can play by itself, which keep running after Prism exits.
    @ivar streams: whether Prism can draw frames on it, which allows every effect.
    """

    id: str
    name: str
    device: str
    kind: DeviceKind
    led_count: int
    hardware_effects: frozenset[EffectKind] = frozenset()
    streams: bool = True

    def supports(self, kind: EffectKind) -> bool:
        """Say whether the zone can show an effect one way or another.

        @param kind: the effect.
        @return: True if the device plays it or Prism can draw it.
        """
        return self.streams or kind in self.hardware_effects

    @property
    def effects(self) -> tuple[EffectKind, ...]:
        """Every effect the zone can show, in menu order."""
        return tuple(kind for kind in EffectKind if self.supports(kind))


@dataclass(frozen=True, slots=True)
class FanChannel:
    """One fan header Prism can set the speed of.

    @ivar minimum_duty: the lowest duty Prism will ever send, so a bad curve cannot stall the fan.
    """

    id: str
    name: str
    device: str
    minimum_duty: int = 20


@dataclass(frozen=True, slots=True)
class Sensor:
    """A value Prism can read, such as a temperature or a load.

    @ivar unit: shown after the value, for example "°C" or "%".
    """

    id: str
    name: str
    unit: str


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    """Whether a device is connected, for the dashboard.

    @ivar detail: why it is offline, or what it is when online.
    """

    name: str
    online: bool
    detail: str = ""
