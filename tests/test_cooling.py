import pytest

from prism.domain.cooling import PRESET_CURVES, CurvePoint, FanCurve, FanMode, FanSetting
from prism.domain.errors import ValidationError

CURVE = FanCurve.of([(30, 20), (50, 40), (70, 100)])


def test_curve_interpolates_and_holds_its_ends() -> None:
    assert CURVE.duty_at(10) == 20
    assert CURVE.duty_at(40) == 30
    assert CURVE.duty_at(60) == 70
    assert CURVE.duty_at(95) == 100


@pytest.mark.parametrize(
    "pairs",
    [[(30, 20)], [(50, 20), (40, 30)], [(30, 20), (30, 30)], [(30, 20), (40, 120)]],
)
def test_rejects_bad_curves(pairs: list[tuple[float, int]]) -> None:
    with pytest.raises(ValidationError):
        FanCurve.of(pairs)


def test_moving_a_point_keeps_it_between_its_neighbours() -> None:
    moved = CURVE.moved(1, CurvePoint(90, 150))
    assert moved.points[1] == CurvePoint(69, 100)
    assert CURVE.moved(0, CurvePoint(-5, -5)).points[0] == CurvePoint(0, 0)


def test_settings_give_a_target_duty() -> None:
    assert FanSetting.fixed(60).target({}) == 60
    following = FanSetting.following("cpu.temp", CURVE)
    assert following.mode is FanMode.CURVE
    assert following.target({"cpu.temp": 40}) == 30
    assert following.target({}) is None


def test_settings_validate() -> None:
    with pytest.raises(ValidationError):
        FanSetting.fixed(101)
    with pytest.raises(ValidationError):
        FanSetting(FanMode.CURVE)


def test_presets_are_valid_and_rise() -> None:
    for curve in PRESET_CURVES.values():
        duties = [point.duty for point in curve.points]
        assert duties == sorted(duties)
