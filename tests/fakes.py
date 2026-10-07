from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from prism.domain.automation import Rule
from prism.domain.cooling import PumpMode
from prism.domain.devices import DeviceKind, FanChannel, LightingZone, Sensor
from prism.domain.effects import Effect, EffectKind
from prism.domain.errors import DeviceError
from prism.domain.profile import Profile
from prism.domain.rendering import Frame
from prism.domain.settings import Settings


class FakeTransport:
    """Records every report and answers each with a success status, unless told to fail."""

    def __init__(self, status: int = 0x00) -> None:
        self.reports: list[bytes] = []
        self.status = status
        self.closed = False
        self.fail = False

    def exchange(self, report: bytes, reply_size: int) -> bytes:
        if self.fail:
            raise DeviceError("gone")
        self.reports.append(report)
        return bytes([self.status]) + bytes(reply_size - 1)

    def close(self) -> None:
        self.closed = True


class FakeLiquidctl:
    """Behaves like liquidctl's Hydro Platinum driver."""

    description = "Corsair H115i Platinum"

    def __init__(self, temperature: float = 31.5) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.temperature = temperature
        self.fail = False

    def connect(self) -> None:
        self.calls.append(("connect",))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def initialize(self, pump_mode: str) -> None:
        self.calls.append(("initialize", pump_mode))

    def get_status(self) -> list[tuple[str, Any, str]]:
        if self.fail:
            raise OSError("usb gone")
        return [
            ("Liquid temperature", self.temperature, "°C"),
            ("Fan 1 speed", 900, "rpm"),
            ("Fan 2 speed", 920, "rpm"),
            ("Pump speed", 2100, "rpm"),
        ]

    def set_fixed_speed(self, channel: str, duty: int) -> None:
        self.calls.append(("speed", channel, duty))

    def set_color(self, channel: str, mode: str, colors: list[tuple[int, int, int]]) -> None:
        if self.fail:
            raise ValueError("bad")
        self.calls.append(("color", channel, mode, colors))


@dataclass
class FakeMode:
    name: str
    flags: int = 0
    speed_min: int | None = None
    speed_max: int | None = None
    speed: int | None = None
    direction: int | None = None
    brightness_min: int | None = None
    brightness_max: int | None = None
    brightness: int | None = None
    colors_min: int | None = None
    colors_max: int | None = None
    color_mode: int = 0
    colors: list[Any] | None = None


@dataclass
class FakeOrgbDevice:
    name: str
    type: int
    modes: list[FakeMode]
    leds: list[int] = field(default_factory=lambda: [0] * 8)
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def set_mode(self, mode: FakeMode, force: bool = False) -> None:
        self.calls.append(("mode", mode))

    def set_color(self, color: Any) -> None:
        self.calls.append(("color", color))

    def set_colors(self, colors: list[Any], fast: bool = False) -> None:
        self.calls.append(("colors", colors))


class FakeOrgbClient:
    def __init__(self, devices: list[FakeOrgbDevice]) -> None:
        self.devices = devices
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


class FakeLights:
    """A lighting device that remembers what it was asked to play and draw."""

    def __init__(
        self,
        name: str = "Lights",
        zones: Sequence[LightingZone] | None = None,
    ) -> None:
        self._name = name
        self._zones = list(zones) if zones is not None else [zone("fans", hardware={EffectKind.STATIC})]
        self.played: list[tuple[str, Effect]] = []
        self.drawn: list[tuple[str, Frame]] = []
        self.fail = False
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    def zones(self) -> Sequence[LightingZone]:
        return self._zones

    def play(self, zone_id: str, effect: Effect) -> None:
        if self.fail:
            raise DeviceError("unplugged")
        self.played.append((zone_id, effect))

    def draw(self, zone_id: str, frame: Frame) -> None:
        if self.fail:
            raise DeviceError("unplugged")
        self.drawn.append((zone_id, frame))

    def close(self) -> None:
        self.closed = True


class FakeFans:
    """A fan controller with a pump, that remembers every duty it was given."""

    def __init__(self, name: str = "Fans", fan_ids: Sequence[str] = ("fan1", "fan2")) -> None:
        self._name = name
        self._fans = [FanChannel(fan_id, fan_id.title(), name) for fan_id in fan_ids]
        self.duties: dict[str, int] = {}
        self.history: list[tuple[str, int]] = []
        self.pump: PumpMode | None = None
        self.fail = False
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    def fans(self) -> Sequence[FanChannel]:
        return self._fans

    def set_duty(self, fan_id: str, duty: int) -> None:
        if self.fail:
            raise DeviceError("unplugged")
        self.duties[fan_id] = duty
        self.history.append((fan_id, duty))

    def speeds(self) -> Mapping[str, int]:
        return {fan.id: 1000 for fan in self._fans}

    def set_pump(self, mode: PumpMode) -> None:
        self.pump = mode

    def close(self) -> None:
        self.closed = True


class FakeSensors:
    def __init__(self, readings: dict[str, float] | None = None) -> None:
        self.readings = readings if readings is not None else {"cpu.temp": 40.0, "cpu.load": 10.0}

    def sensors(self) -> Sequence[Sensor]:
        return [Sensor(key, key, "") for key in self.readings]

    def read(self) -> Mapping[str, float]:
        return dict(self.readings)


class FakeProcesses:
    def __init__(self, names: frozenset[str] = frozenset()) -> None:
        self.names = names

    def running(self) -> frozenset[str]:
        return self.names


class MemoryProfileStore:
    def __init__(self, profiles: list[Profile] | None = None) -> None:
        self.profiles = list(profiles or [])
        self.saves = 0

    def load(self) -> list[Profile]:
        return list(self.profiles)

    def save(self, profiles: Sequence[Profile]) -> None:
        self.profiles = list(profiles)
        self.saves += 1


class MemoryRuleStore:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = list(rules or [])

    def load(self) -> list[Rule]:
        return list(self.rules)

    def save(self, rules: Sequence[Rule]) -> None:
        self.rules = list(rules)


class MemorySettingsStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def load(self) -> Settings:
        return self.settings

    def save(self, settings: Settings) -> None:
        self.settings = settings


class FakeAutostart:
    def __init__(self) -> None:
        self.on = False

    def enabled(self) -> bool:
        return self.on

    def set_enabled(self, enabled: bool) -> None:
        self.on = enabled


def zone(
    zone_id: str,
    leds: int = 4,
    hardware: set[EffectKind] | None = None,
    streams: bool = True,
) -> LightingZone:
    return LightingZone(
        id=zone_id,
        name=zone_id.title(),
        device="Lights",
        kind=DeviceKind.OTHER,
        led_count=leds,
        hardware_effects=frozenset(hardware or set()),
        streams=streams,
    )
