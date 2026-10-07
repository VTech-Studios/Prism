import pytest

from prism.domain.color import Color
from prism.domain.cooling import PumpMode
from prism.domain.effects import Effect, EffectKind
from prism.domain.errors import DeviceError
from prism.infrastructure.hydro_platinum import HydroPlatinum
from tests.fakes import FakeLiquidctl


def make() -> tuple[HydroPlatinum, FakeLiquidctl]:
    driver = FakeLiquidctl()
    return HydroPlatinum(lambda: driver, led_count=16), driver


def test_initialises_in_balanced_and_finds_its_fans() -> None:
    cooler, driver = make()
    assert driver.calls == [("initialize", "balanced")]
    assert [fan.id for fan in cooler.fans()] == ["aio:fan1", "aio:fan2"]
    assert cooler.speeds() == {"aio:fan1": 900, "aio:fan2": 920}
    assert cooler.name == "Corsair H115i Platinum"


def test_lighting_plays_fixed_and_draws_per_led() -> None:
    cooler, driver = make()
    zone = cooler.zones()[0]
    assert (zone.id, zone.led_count) == ("aio:led", 16)
    assert zone.hardware_effects == {EffectKind.OFF, EffectKind.STATIC}
    cooler.play("aio:led", Effect(EffectKind.STATIC, (Color(200, 100, 0),), brightness=0.5))
    cooler.play("aio:led", Effect.off())
    cooler.draw("aio:led", (Color(1, 2, 3),) * 2)
    assert driver.calls[1:] == [
        ("color", "led", "fixed", [(100, 50, 0)]),
        ("color", "led", "fixed", [(0, 0, 0)]),
        ("color", "led", "super-fixed", [(1, 2, 3), (1, 2, 3)]),
    ]


def test_fans_and_pump() -> None:
    cooler, driver = make()
    cooler.set_duty("aio:fan2", 55)
    cooler.set_pump(PumpMode.EXTREME)
    assert driver.calls[-2:] == [("speed", "fan2", 55), ("initialize", "extreme")]


def test_reads_coolant_and_tolerates_a_dropped_cooler() -> None:
    cooler, driver = make()
    assert cooler.read() == {"liquid.temp": 31.5}
    assert [sensor.id for sensor in cooler.sensors()] == ["liquid.temp"]
    driver.fail = True
    assert cooler.read() == {}
    with pytest.raises(DeviceError):
        cooler.draw("aio:led", (Color(0, 0, 0),))


def test_a_missing_cooler_raises() -> None:
    def missing() -> FakeLiquidctl:
        raise DeviceError("not found")

    with pytest.raises(DeviceError):
        HydroPlatinum(missing)


def test_close_disconnects() -> None:
    cooler, driver = make()
    cooler.close()
    assert driver.calls[-1] == ("disconnect",)
