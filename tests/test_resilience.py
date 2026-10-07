import threading
import time

import pytest

from prism.domain.color import Color
from prism.domain.effects import Effect, EffectKind
from prism.domain.errors import ValidationError
from prism.domain.settings import Settings
from prism.infrastructure.sensors import BackgroundSensors
from prism.infrastructure.sleep import BootClockSleepWatch
from prism.ports import Device
from prism.services.lighting import can_play
from prism.services.registry import Connector, DeviceRegistry
from tests.fakes import FakeLights, FakeSensors, zone


def test_sleep_is_spotted_once_per_resume() -> None:
    gap = [10.0]
    watch = BootClockSleepWatch(lambda: gap[0])
    assert not watch.woke()
    gap[0] = 11.0
    assert not watch.woke()
    gap[0] = 300.0
    assert watch.woke()
    assert not watch.woke()


def test_background_sensors_return_the_latest_sample_without_waiting() -> None:
    sampled = threading.Event()

    class Slow(FakeSensors):
        def read(self) -> dict[str, float]:
            sampled.set()
            return {"gpu.temp": 55.0}

    background = BackgroundSensors(Slow(), interval=0.01)
    assert sampled.wait(2)
    deadline = time.monotonic() + 2
    while not background.read() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert background.read() == {"gpu.temp": 55.0}
    assert [sensor.id for sensor in background.sensors()] == ["cpu.temp", "cpu.load"]
    background.close()


def test_reopen_closes_and_reconnects_every_device() -> None:
    lights = FakeLights()
    registry = DeviceRegistry([Connector("Lights", lambda: lights)])
    registry.connect_offline()
    before = registry.generation
    registry.reopen()
    assert lights.closed
    assert registry.statuses()[0].online
    assert registry.generation > before


def test_an_unexpected_connector_failure_does_not_stop_the_others() -> None:
    def broken() -> Device:
        raise KeyError("bug")

    registry = DeviceRegistry([Connector("Broken", broken), Connector("Lights", FakeLights)])
    registry.connect_offline()
    statuses = registry.statuses()
    assert statuses[0].online is False and "could not connect" in statuses[0].detail
    assert statuses[1].online


def test_effects_with_more_colours_than_the_device_holds_are_drawn() -> None:
    two = zone("fans", hardware={EffectKind.BREATHING})
    two = type(two)(**{**{f: getattr(two, f) for f in two.__slots__}, "hardware_colors": 2})
    colors = (Color(255, 0, 0), Color(0, 255, 0), Color(0, 0, 255))
    assert can_play(two, Effect(EffectKind.BREATHING, colors[:2]))
    assert not can_play(two, Effect(EffectKind.BREATHING, colors))


def test_channel_led_counts_are_checked() -> None:
    with pytest.raises(ValidationError):
        Settings(channel_leds={1: 300})


def test_background_sensors_go_quiet_when_their_thread_cannot_read() -> None:
    attempts = threading.Event()

    class Failing(FakeSensors):
        def read(self) -> dict[str, float]:
            attempts.set()
            raise RuntimeError("nvidia-smi crashed")

    background = BackgroundSensors(Failing(), interval=0.01)
    assert attempts.wait(2)
    assert background.read() == {}
    background.close()


def test_old_background_samples_are_not_trusted() -> None:
    background = BackgroundSensors(FakeSensors({"gpu.temp": 50.0}), interval=0.01)
    deadline = time.monotonic() + 2
    while not background.read() and time.monotonic() < deadline:
        time.sleep(0.01)
    background.close()
    time.sleep(0.1)
    assert background.read() == {}


def test_openrgb_with_no_devices_yet_is_not_ready() -> None:
    from prism.domain.errors import DeviceError
    from prism.infrastructure.openrgb import OpenRgbLighting
    from tests.fakes import FakeOrgbClient

    client = FakeOrgbClient([])
    with pytest.raises(DeviceError, match="not found any devices"):
        OpenRgbLighting(client, [])
    assert client.disconnected
