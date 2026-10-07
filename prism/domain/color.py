from __future__ import annotations

import colorsys
from dataclasses import dataclass

from .errors import ValidationError

_CHANNEL_MAX = 255


def _clamp_channel(value: float) -> int:
    """Round a channel value into the range a LED accepts.

    @param value: a channel value that may have drifted out of range.
    @return: the nearest whole value between 0 and 255.
    """
    return max(0, min(_CHANNEL_MAX, round(value)))


@dataclass(frozen=True, slots=True)
class Color:
    """An RGB colour as the LEDs see it, one byte per channel."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for channel in (self.red, self.green, self.blue):
            if not 0 <= channel <= _CHANNEL_MAX:
                raise ValidationError(f"colour channel {channel} is outside 0-255")

    @classmethod
    def from_hex(cls, text: str) -> Color:
        """Read a colour written the way people write them, such as "#ff2800".

        @param text: six hex digits, with or without a leading hash.
        @return: the colour.
        @raise ValidationError: if the text is not a six digit hex colour.
        """
        digits = text.strip().removeprefix("#")
        if len(digits) != 6:
            raise ValidationError(f"{text!r} is not a six digit hex colour")
        try:
            value = int(digits, 16)
        except ValueError as error:
            raise ValidationError(f"{text!r} is not a six digit hex colour") from error
        return cls(value >> 16, (value >> 8) & 0xFF, value & 0xFF)

    @classmethod
    def from_hsv(cls, hue: float, saturation: float = 1.0, value: float = 1.0) -> Color:
        """Build a colour from a position on the colour wheel, which is how rainbows are drawn.

        @param hue: the angle around the wheel as a fraction, wrapped into 0-1.
        @param saturation: 0 for grey through to 1 for a pure colour.
        @param value: 0 for black through to 1 for full brightness.
        @return: the colour.
        """
        red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
        return cls(
            _clamp_channel(red * _CHANNEL_MAX),
            _clamp_channel(green * _CHANNEL_MAX),
            _clamp_channel(blue * _CHANNEL_MAX),
        )

    @property
    def hex(self) -> str:
        """The colour as "#rrggbb", the form it is stored and shown in."""
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    def scaled(self, factor: float) -> Color:
        """Dim or brighten the colour without changing its hue.

        @param factor: 0 for black, 1 for unchanged.
        @return: the scaled colour, clamped to the valid range.
        """
        return Color(
            _clamp_channel(self.red * factor),
            _clamp_channel(self.green * factor),
            _clamp_channel(self.blue * factor),
        )

    def blend(self, other: Color, amount: float) -> Color:
        """Mix towards another colour, used for fades and gradients.

        @param other: the colour to move towards.
        @param amount: 0 keeps this colour, 1 gives the other one.
        @return: the mixed colour.
        """
        amount = max(0.0, min(1.0, amount))
        return Color(
            _clamp_channel(self.red + (other.red - self.red) * amount),
            _clamp_channel(self.green + (other.green - self.green) * amount),
            _clamp_channel(self.blue + (other.blue - self.blue) * amount),
        )


BLACK = Color(0, 0, 0)
WHITE = Color(255, 255, 255)
