import pytest

from prism.domain.color import BLACK, WHITE, Color
from prism.domain.errors import ValidationError


def test_reads_and_writes_hex() -> None:
    color = Color.from_hex("#FF2800")
    assert color == Color(255, 40, 0)
    assert color.hex == "#ff2800"
    assert Color.from_hex("00ff00") == Color(0, 255, 0)


@pytest.mark.parametrize("text", ["", "#fff", "#gggggg", "12345678"])
def test_rejects_bad_hex(text: str) -> None:
    with pytest.raises(ValidationError):
        Color.from_hex(text)


def test_rejects_out_of_range_channels() -> None:
    with pytest.raises(ValidationError):
        Color(256, 0, 0)


def test_hsv_wraps_around_the_wheel() -> None:
    assert Color.from_hsv(0.0) == Color(255, 0, 0)
    assert Color.from_hsv(1.0) == Color(255, 0, 0)
    assert Color.from_hsv(-2 / 3) == Color(0, 255, 0)


def test_scales_and_blends() -> None:
    assert WHITE.scaled(0.5) == Color(128, 128, 128)
    assert WHITE.scaled(3) == WHITE
    assert BLACK.blend(WHITE, 0.25) == Color(64, 64, 64)
    assert BLACK.blend(WHITE, 5) == WHITE
