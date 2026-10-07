from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .color import Color
from .errors import ValidationError


class EffectKind(StrEnum):
    OFF = "off"
    STATIC = "static"
    BREATHING = "breathing"
    SPECTRUM = "spectrum"
    RAINBOW_WAVE = "rainbow_wave"
    COLOR_WAVE = "color_wave"
    MARQUEE = "marquee"
    BLINK = "blink"
    TEMPERATURE = "temperature"

    @property
    def label(self) -> str:
        """The name shown in the window."""
        return _LABELS[self]

    @property
    def color_slots(self) -> tuple[int, int]:
        """How many colours the effect needs, as (fewest, most)."""
        return _COLOR_SLOTS[self]

    @property
    def animated(self) -> bool:
        """Whether the effect changes over time, so speed and direction mean something."""
        return self not in (EffectKind.OFF, EffectKind.STATIC, EffectKind.TEMPERATURE)


_LABELS = {
    EffectKind.OFF: "Off",
    EffectKind.STATIC: "Static",
    EffectKind.BREATHING: "Breathing",
    EffectKind.SPECTRUM: "Spectrum Cycle",
    EffectKind.RAINBOW_WAVE: "Rainbow Wave",
    EffectKind.COLOR_WAVE: "Colour Wave",
    EffectKind.MARQUEE: "Marquee",
    EffectKind.BLINK: "Blink",
    EffectKind.TEMPERATURE: "Temperature",
}

_COLOR_SLOTS = {
    EffectKind.OFF: (0, 0),
    EffectKind.STATIC: (1, 1),
    EffectKind.BREATHING: (1, 3),
    EffectKind.SPECTRUM: (0, 0),
    EffectKind.RAINBOW_WAVE: (0, 0),
    EffectKind.COLOR_WAVE: (2, 3),
    EffectKind.MARQUEE: (1, 1),
    EffectKind.BLINK: (1, 2),
    EffectKind.TEMPERATURE: (3, 3),
}


class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"

    @property
    def period(self) -> float:
        """Seconds one full cycle of an animation takes at this speed."""
        return {Speed.SLOW: 8.0, Speed.MEDIUM: 4.0, Speed.FAST: 2.0}[self]


class Direction(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"

    @property
    def sign(self) -> int:
        """+1 or -1, to flip which way an animation travels along the LEDs."""
        return 1 if self is Direction.FORWARD else -1


@dataclass(frozen=True, slots=True)
class Gauge:
    """Which sensor drives a temperature effect, and the range it is drawn over.

    The first colour shows at or below cool, the second halfway, and the last
    at or above hot, like the pump's coolant colour in iCUE.
    """

    sensor: str
    cool: float = 30.0
    hot: float = 45.0

    def __post_init__(self) -> None:
        if self.hot <= self.cool:
            raise ValidationError("the hot temperature must be above the cool one")

    def position(self, reading: float) -> float:
        """Place a reading on the gauge.

        @param reading: the sensor's current value.
        @return: 0 at or below cool, 1 at or above hot, linear between.
        """
        return max(0.0, min(1.0, (reading - self.cool) / (self.hot - self.cool)))


@dataclass(frozen=True, slots=True)
class Effect:
    """What one lighting zone should show, independent of the device drawing it."""

    kind: EffectKind
    colors: tuple[Color, ...] = ()
    speed: Speed = Speed.MEDIUM
    direction: Direction = Direction.FORWARD
    brightness: float = 1.0
    gauge: Gauge | None = None

    def __post_init__(self) -> None:
        fewest, most = self.kind.color_slots
        if not fewest <= len(self.colors) <= most:
            raise ValidationError(
                f"{self.kind.label} takes {fewest} to {most} colours, not {len(self.colors)}"
            )
        if not 0.0 <= self.brightness <= 1.0:
            raise ValidationError("brightness must be between 0 and 1")
        if self.kind is EffectKind.TEMPERATURE and self.gauge is None:
            raise ValidationError("a temperature effect needs a sensor to follow")

    @classmethod
    def off(cls) -> Effect:
        """Build the effect that turns a zone's LEDs off.

        @return: the off effect.
        """
        return cls(EffectKind.OFF)

    @classmethod
    def static(cls, color: Color) -> Effect:
        """Build a single unchanging colour.

        @param color: the colour to show.
        @return: the static effect.
        """
        return cls(EffectKind.STATIC, (color,))

    def with_kind(self, kind: EffectKind, palette: tuple[Color, ...]) -> Effect:
        """Switch to another effect while keeping as much of this one as fits.

        @param kind: the new effect.
        @param palette: colours to fall back on when this effect has too few.
        @return: a valid effect of the new kind.
        """
        fewest, most = kind.color_slots
        colors = (self.colors + palette)[: max(fewest, min(most, len(self.colors)))]
        gauge = self.gauge
        if kind is EffectKind.TEMPERATURE and gauge is None:
            gauge = Gauge("cpu.temp")
        return replace(
            self, kind=kind, colors=colors, gauge=gauge if kind is EffectKind.TEMPERATURE else None
        )

    def with_color(self, index: int, color: Color) -> Effect:
        """Replace one of the effect's colours.

        @param index: which colour slot to change.
        @param color: the new colour.
        @return: the changed effect.
        """
        colors = list(self.colors)
        colors[index] = color
        return replace(self, colors=tuple(colors))
