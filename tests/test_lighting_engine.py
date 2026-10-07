from prism.domain.color import Color
from prism.domain.effects import Effect, EffectKind, Gauge
from prism.domain.rendering import Renderer
from prism.services.lighting import LightingEngine, can_play
from prism.services.registry import Connector, DeviceRegistry
from tests.fakes import FakeLights, zone

RED = Effect.static(Color(255, 0, 0))
RAINBOW = Effect(EffectKind.RAINBOW_WAVE)


def engine(lights: FakeLights, prefer_hardware: bool = True) -> LightingEngine:
    registry = DeviceRegistry([Connector("Lights", lambda: lights)])
    registry.connect_offline()
    return LightingEngine(registry, Renderer(), prefer_hardware)


def test_can_play_only_when_faithful() -> None:
    hardware = zone("z", hardware={EffectKind.STATIC, EffectKind.RAINBOW_WAVE, EffectKind.OFF})
    assert can_play(hardware, RED)
    assert can_play(hardware, RAINBOW)
    assert not can_play(hardware, Effect(EffectKind.RAINBOW_WAVE, brightness=0.5))
    assert can_play(hardware, Effect(EffectKind.STATIC, (Color(1, 1, 1),), brightness=0.5))
    assert can_play(hardware, Effect(EffectKind.OFF, brightness=0.1))
    assert not can_play(hardware, Effect(EffectKind.BREATHING, (Color(1, 1, 1),)))
    gauge = Effect(EffectKind.TEMPERATURE, (RED.colors[0],) * 3, gauge=Gauge("cpu.temp"))
    assert not can_play(zone("t", hardware={EffectKind.TEMPERATURE}), gauge)


def test_hardware_effects_are_handed_over_once() -> None:
    lights = FakeLights(zones=[zone("fans", hardware={EffectKind.STATIC})])
    lighting = engine(lights)
    lighting.show({"fans": RED})
    lighting.tick(0.0, {})
    assert lights.played == [("fans", RED)]
    assert lights.drawn == []
    assert not lighting.is_drawn("fans")


def test_other_effects_are_drawn_and_only_resent_when_needed() -> None:
    lights = FakeLights(zones=[zone("fans", leds=3)])
    lighting = engine(lights)
    lighting.show({"fans": RED})
    assert lighting.is_drawn("fans")
    lighting.tick(0.0, {})
    lighting.tick(0.5, {})
    assert len(lights.drawn) == 1
    lighting.tick(2.5, {})
    assert len(lights.drawn) == 2
    lighting.show({"fans": RAINBOW})
    lighting.tick(3.0, {})
    lighting.tick(3.1, {})
    assert len(lights.drawn) == 4


def test_preferring_software_draws_everything_that_streams() -> None:
    lights = FakeLights(
        zones=[
            zone("fans", hardware={EffectKind.STATIC}),
            zone("pump", hardware={EffectKind.STATIC}, streams=False),
        ]
    )
    lighting = engine(lights, prefer_hardware=False)
    lighting.show({"fans": RED, "pump": RED})
    assert lighting.is_drawn("fans")
    assert lights.played == [("pump", RED)]
    lighting.set_prefer_hardware(True)
    assert not lighting.is_drawn("fans")
    assert ("fans", RED) in lights.played


def test_unsupported_effects_are_skipped() -> None:
    lights = FakeLights(zones=[zone("gpu", hardware={EffectKind.STATIC}, streams=False)])
    lighting = engine(lights)
    lighting.show({"gpu": RAINBOW})
    lighting.tick(0, {})
    assert lights.played == []
    assert lights.drawn == []


def test_a_failing_device_is_taken_offline() -> None:
    lights = FakeLights(zones=[zone("a"), zone("b")])
    lighting = engine(lights)
    lighting.show({"a": RED, "b": RED})
    lights.fail = True
    lighting.tick(0, {})
    assert lights.closed
    assert not lighting.is_drawn("a")
    assert not lighting.is_drawn("b")
    hardware = FakeLights(zones=[zone("h", hardware={EffectKind.STATIC})])
    hardware.fail = True
    engine(hardware).show({"h": RED})
    assert hardware.closed
