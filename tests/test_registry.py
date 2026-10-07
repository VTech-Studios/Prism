from prism.domain.errors import DeviceError
from prism.ports import Device
from prism.services.registry import Connector, DeviceRegistry
from tests.fakes import FakeFans, FakeLights, FakeSensors


class Flaky:
    """A connector that fails until told the device is plugged in."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.plugged = False

    def __call__(self) -> Device:
        if not self.plugged:
            raise DeviceError("not on USB")
        return self.device


def test_connects_and_lists_what_devices_offer() -> None:
    lights, fans = FakeLights(), FakeFans()
    registry = DeviceRegistry([Connector("Lights", lambda: lights), Connector("Fans", lambda: fans)])
    registry.connect_offline()
    assert [zone.id for zone in registry.zones()] == ["fans"]
    assert [fan.id for fan in registry.fans()] == ["fan1", "fan2"]
    assert registry.lighting_for("fans") is lights
    assert registry.lighting_for("nope") is None
    assert registry.fans_for("fan2") is fans
    assert registry.fans_for("nope") is None
    assert registry.pumps() == [fans]
    assert registry.fan_devices() == [fans]
    assert registry.generation == 2
    assert [(s.name, s.online, s.detail) for s in registry.statuses()] == [
        ("Lights", True, "1 lighting zone"),
        ("Fans", True, "2 fans"),
    ]


def test_offline_devices_are_retried_and_reported() -> None:
    connector = Flaky(FakeLights())
    registry = DeviceRegistry([Connector("Lights", connector)])
    registry.connect_offline()
    assert registry.statuses()[0].online is False
    assert registry.statuses()[0].detail == "not on USB"
    assert registry.generation == 0
    connector.plugged = True
    registry.connect_offline()
    assert registry.statuses()[0].online
    assert registry.generation == 1


def test_failed_devices_go_offline_and_are_closed() -> None:
    lights = FakeLights()
    registry = DeviceRegistry([Connector("Lights", lambda: lights)])
    registry.connect_offline()
    registry.fail(lights, DeviceError("unplugged"))
    assert lights.closed
    assert registry.zones() == []
    assert registry.statuses()[0].detail == "unplugged"
    assert registry.generation == 2


def test_sensor_sources_and_close() -> None:
    sensors, fans = FakeSensors(), FakeFans()
    registry = DeviceRegistry([Connector("Fans", lambda: fans)])
    registry.connect_offline()
    assert registry.sensor_sources() == []
    assert sensors.read()
    registry.close()
    assert fans.closed
    assert registry.statuses()[0].online is False


def test_a_device_with_nothing_to_offer_still_shows() -> None:
    registry = DeviceRegistry([Connector("Bare", lambda: FakeLights(zones=[]))])
    registry.connect_offline()
    assert registry.statuses()[0].detail == "connected"
