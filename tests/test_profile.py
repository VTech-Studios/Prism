import pytest

from prism.domain.color import Color
from prism.domain.cooling import FanSetting, PumpMode
from prism.domain.effects import Effect
from prism.domain.errors import ValidationError
from prism.domain.profile import Profile
from prism.domain.settings import Settings

RED = Effect.static(Color(255, 0, 0))


def test_profiles_are_immutable_copies() -> None:
    lighting = {"fans": RED}
    profile = Profile("Default", lighting=lighting)
    lighting["ram"] = RED
    assert "ram" not in profile.lighting
    with pytest.raises(TypeError):
        profile.lighting["ram"] = RED  # type: ignore[index]


def test_with_helpers_return_changed_copies() -> None:
    base = Profile("Default")
    changed = (
        base.with_effect("fans", RED)
        .with_effect_everywhere(["ram", "gpu"], Effect.off())
        .with_fan("fan1", FanSetting.fixed(40))
        .with_pump(PumpMode.QUIET)
        .renamed("Night")
    )
    assert base == Profile("Default")
    assert changed.name == "Night"
    assert changed.lighting == {"fans": RED, "ram": Effect.off(), "gpu": Effect.off()}
    assert changed.cooling == {"fan1": FanSetting.fixed(40)}
    assert changed.pump is PumpMode.QUIET


def test_profiles_need_a_name() -> None:
    with pytest.raises(ValidationError):
        Profile("  ")


@pytest.mark.parametrize(
    "overrides",
    [{"fan_floor": 70}, {"fan_floor": 30, "handoff_duty": 20}, {"frame_rate": 0}],
)
def test_settings_validate(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)  # type: ignore[arg-type]
