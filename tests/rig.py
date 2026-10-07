from __future__ import annotations

from prism.domain.automation import ProcessRunning, Rule, RuleEvaluator
from prism.domain.devices import DeviceKind, LightingZone
from prism.domain.effects import EffectKind
from prism.domain.profile import Profile
from prism.domain.rendering import Renderer
from prism.services.automation import AutomationService
from prism.services.cooling import CoolingController
from prism.services.core import PrismCore
from prism.services.lighting import LightingEngine
from prism.services.profiles import ProfileLibrary
from prism.services.registry import Connector, DeviceRegistry
from prism.services.telemetry import Telemetry
from tests.fakes import (
    FakeAutostart,
    FakeFans,
    FakeLights,
    FakeProcesses,
    FakeSensors,
    MemoryProfileStore,
    MemoryRuleStore,
    MemorySettingsStore,
    zone,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Rig:
    """A core wired to fakes, with the clock under the test's control."""

    def __init__(
        self,
        profiles: list[Profile] | None = None,
        rules: list[Rule] | None = None,
        lights: FakeLights | None = None,
        fans: FakeFans | None = None,
        sensors: FakeSensors | None = None,
    ) -> None:
        self.lights = lights or FakeLights(zones=[zone("fans", hardware={EffectKind.STATIC})])
        self.fans = fans or FakeFans()
        self.sensors = sensors or FakeSensors({"cpu.temp": 40.0, "cpu.load": 10.0})
        self.processes = FakeProcesses()
        self.profiles = MemoryProfileStore(profiles)
        self.settings = MemorySettingsStore()
        self.autostart = FakeAutostart()
        self.clock = Clock()
        self.registry = registry = DeviceRegistry(
            [Connector("Lights", lambda: self.lights), Connector("Fans", lambda: self.fans)]
        )
        self.core = PrismCore(
            registry=registry,
            lighting=LightingEngine(registry, Renderer(), prefer_hardware=True),
            cooling=CoolingController(registry, floor=20),
            telemetry=Telemetry(registry, [self.sensors], self.processes),
            library=ProfileLibrary(self.profiles),
            automation=AutomationService(MemoryRuleStore(rules), RuleEvaluator()),
            settings_store=self.settings,
            autostart=self.autostart,
            clock=self.clock,
        )

    def advance(self, seconds: float) -> None:
        self.clock.now += seconds
        self.core.tick()


def showroom() -> Rig:
    """A rig dressed like a real machine: case fans, an AIO, RAM and a GPU, with live readings."""
    lights = FakeLights(
        "OpenRGB",
        zones=[
            LightingZone(
                "cpro:led1", "RGB channel 1", "Corsair Commander Pro", DeviceKind.FAN_CONTROLLER, 72
            ),
            LightingZone(
                "aio:led",
                "Pump head",
                "Corsair H115i Platinum",
                DeviceKind.COOLER,
                16,
                frozenset({EffectKind.STATIC, EffectKind.OFF}),
            ),
            LightingZone("orgb:ram", "ENE DRAM", "OpenRGB", DeviceKind.MEMORY, 8),
            LightingZone(
                "orgb:gpu",
                "ASUS ROG STRIX GTX 1080",
                "OpenRGB",
                DeviceKind.GPU,
                4,
                frozenset({EffectKind.STATIC, EffectKind.BREATHING}),
                streams=False,
            ),
        ]
    )
    names = {"cpro:fan1": "Fan 1", "cpro:fan2": "Fan 2", "cpro:fan3": "Fan 3"}
    names |= {"aio:fan1": "Radiator fan 1", "aio:fan2": "Radiator fan 2"}
    fans = FakeFans("Corsair Commander Pro", list(names), names)
    sensors = FakeSensors(
        {"cpu.temp": 46.0, "cpu.load": 18.0, "gpu.temp": 55.0, "gpu.load": 7.0, "liquid.temp": 31.5},
        {
            "cpu.temp": ("CPU", "°C"),
            "cpu.load": ("CPU load", "%"),
            "gpu.temp": ("GPU", "°C"),
            "gpu.load": ("GPU load", "%"),
            "liquid.temp": ("Coolant", "°C"),
        },
    )
    rule = Rule("Gaming", ProcessRunning("wow.exe"), "Performance", settle=3)
    rig = Rig(rules=[rule], lights=lights, fans=fans, sensors=sensors)
    rig.core.start()
    rig.advance(0)
    return rig
