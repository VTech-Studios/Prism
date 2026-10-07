from prism.domain.cooling import FanCurve, FanSetting, PumpMode
from prism.services.cooling import FAILSAFE_DUTY, CoolingController
from prism.services.registry import Connector, DeviceRegistry
from tests.fakes import FakeFans

CURVE = FanCurve.of([(30, 30), (70, 70)])


def controller(fans: FakeFans, floor: int = 20) -> CoolingController:
    registry = DeviceRegistry([Connector("Fans", lambda: fans)])
    registry.connect_offline()
    return CoolingController(registry, floor)


def test_fixed_and_curve_settings_drive_the_fans() -> None:
    fans = FakeFans()
    cooling = controller(fans)
    cooling.apply({"fan1": FanSetting.fixed(60), "fan2": FanSetting.following("cpu.temp", CURVE)}, None)
    cooling.tick({"cpu.temp": 50})
    assert fans.duties == {"fan1": 60, "fan2": 50}
    assert cooling.duties == {"fan1": 60, "fan2": 50}


def test_fans_rise_at_once_and_fall_gently() -> None:
    fans = FakeFans(fan_ids=["fan1"])
    cooling = controller(fans)
    cooling.apply({"fan1": FanSetting.following("cpu.temp", CURVE)}, None)
    cooling.tick({"cpu.temp": 70})
    cooling.tick({"cpu.temp": 30})
    assert fans.duties["fan1"] == 66
    cooling.tick({"cpu.temp": 70})
    assert fans.duties["fan1"] == 70


def test_unchanged_duties_are_not_resent() -> None:
    fans = FakeFans(fan_ids=["fan1"])
    cooling = controller(fans)
    cooling.apply({"fan1": FanSetting.fixed(40)}, None)
    cooling.tick({})
    cooling.tick({})
    assert fans.history == [("fan1", 40)]
    cooling.refresh()
    cooling.tick({})
    assert len(fans.history) == 2


def test_floor_and_missing_sensor_failsafe() -> None:
    fans = FakeFans()
    cooling = controller(fans, floor=30)
    cooling.apply({"fan1": FanSetting.fixed(0), "fan2": FanSetting.following("gpu.temp", CURVE)}, None)
    cooling.tick({})
    assert fans.duties == {"fan1": 30, "fan2": FAILSAFE_DUTY}
    cooling.set_floor(40)
    cooling.tick({"gpu.temp": 30})
    assert fans.duties["fan1"] == 40


def test_fans_without_a_setting_are_left_alone() -> None:
    fans = FakeFans()
    cooling = controller(fans)
    cooling.tick({})
    assert fans.history == []


def test_hand_off_leaves_every_fan_safe() -> None:
    fans = FakeFans()
    cooling = controller(fans, floor=30)
    cooling.hand_off(10)
    assert fans.duties == {"fan1": 30, "fan2": 30}


def test_pump_mode_is_sent_once_per_change() -> None:
    fans = FakeFans()
    cooling = controller(fans)
    cooling.apply({}, PumpMode.EXTREME)
    cooling.tick({})
    assert fans.pump is PumpMode.EXTREME
    fans.pump = None
    cooling.tick({})
    assert fans.pump is None
    cooling.refresh()
    cooling.tick({})
    assert fans.pump is PumpMode.EXTREME


def test_failing_fans_go_offline() -> None:
    fans = FakeFans()
    cooling = controller(fans)
    fans.fail = True
    cooling.apply({"fan1": FanSetting.fixed(50)}, None)
    cooling.tick({})
    assert fans.closed
    assert cooling.duties == {}
