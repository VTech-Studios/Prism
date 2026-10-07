from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .color import BLACK, Color
from .effects import Effect, EffectKind

Frame = tuple[Color, ...]


@dataclass(frozen=True, slots=True)
class FrameContext:
    """Everything an effect may depend on besides itself.

    @ivar elapsed: seconds since rendering started, so every zone shares one clock and stays in sync.
    @ivar readings: the latest sensor values, keyed by sensor id.
    """

    elapsed: float
    readings: Mapping[str, float]


EffectPainter = Callable[[Effect, int, FrameContext], Frame]


def _phase(effect: Effect, context: FrameContext) -> float:
    """Work out how far through its cycle an animation is.

    @param effect: the effect, whose speed sets the cycle length.
    @param context: the shared clock.
    @return: a fraction from 0 up to 1.
    """
    return (context.elapsed / effect.speed.period) % 1.0


def _fill(color: Color, count: int) -> Frame:
    """Give every LED the same colour.

    @param color: the colour.
    @param count: the number of LEDs.
    @return: the frame.
    """
    return (color,) * count


def _gradient(colors: tuple[Color, ...], position: float) -> Color:
    """Pick a colour from a looping gradient through the given colours.

    @param colors: the stops, spaced evenly and wrapping back to the first.
    @param position: where on the loop, as a fraction.
    @return: the colour at that position.
    """
    scaled = (position % 1.0) * len(colors)
    index = int(scaled)
    return colors[index % len(colors)].blend(colors[(index + 1) % len(colors)], scaled - index)


def paint_off(_effect: Effect, count: int, _context: FrameContext) -> Frame:
    """@return: every LED off."""
    return _fill(BLACK, count)


def paint_static(effect: Effect, count: int, _context: FrameContext) -> Frame:
    """@return: every LED in the effect's colour."""
    return _fill(effect.colors[0], count)


def paint_breathing(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Fade in and out, moving to the next colour on each breath.

    @return: the frame for this instant.
    """
    cycles = context.elapsed / effect.speed.period
    level = (1.0 - math.cos(2.0 * math.pi * (cycles % 1.0))) / 2.0
    color = effect.colors[int(cycles) % len(effect.colors)]
    return _fill(color.scaled(level), count)


def paint_spectrum(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Every LED moves through the colour wheel together.

    @return: the frame for this instant.
    """
    return _fill(Color.from_hsv(_phase(effect, context) * effect.direction.sign), count)


def paint_rainbow_wave(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Spread a full rainbow along the LEDs and send it travelling around them.

    @return: the frame for this instant.
    """
    phase = _phase(effect, context) * effect.direction.sign
    return tuple(Color.from_hsv(index / count - phase) for index in range(count))


def paint_color_wave(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Send a gradient through the chosen colours travelling around the LEDs.

    @return: the frame for this instant.
    """
    phase = _phase(effect, context) * effect.direction.sign
    return tuple(_gradient(effect.colors, index / count - phase) for index in range(count))


def paint_marquee(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Every third LED lit, stepping along like a theatre sign.

    @return: the frame for this instant.
    """
    step = int(_phase(effect, context) * 3 * 4) * effect.direction.sign
    return tuple(effect.colors[0] if (index - step) % 3 == 0 else BLACK for index in range(count))


def paint_blink(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Alternate between the colours, or between one colour and off.

    @return: the frame for this instant.
    """
    colors = effect.colors if len(effect.colors) > 1 else (effect.colors[0], BLACK)
    half_cycles = int(context.elapsed / (effect.speed.period / 4))
    return _fill(colors[half_cycles % 2], count)


def paint_temperature(effect: Effect, count: int, context: FrameContext) -> Frame:
    """Colour by a sensor: cool, warm, then hot as it climbs.

    Before the sensor has reported, the cool colour shows rather than nothing.

    @return: the frame for this instant.
    """
    gauge = effect.gauge
    reading = context.readings.get(gauge.sensor) if gauge else None
    if gauge is None or reading is None:
        return _fill(effect.colors[0], count)
    position = gauge.position(reading) * 2.0
    low, high = (
        (effect.colors[0], effect.colors[1]) if position <= 1.0 else (effect.colors[1], effect.colors[2])
    )
    return _fill(low.blend(high, position if position <= 1.0 else position - 1.0), count)


DEFAULT_PAINTERS: Mapping[EffectKind, EffectPainter] = {
    EffectKind.OFF: paint_off,
    EffectKind.STATIC: paint_static,
    EffectKind.BREATHING: paint_breathing,
    EffectKind.SPECTRUM: paint_spectrum,
    EffectKind.RAINBOW_WAVE: paint_rainbow_wave,
    EffectKind.COLOR_WAVE: paint_color_wave,
    EffectKind.MARQUEE: paint_marquee,
    EffectKind.BLINK: paint_blink,
    EffectKind.TEMPERATURE: paint_temperature,
}


class Renderer:
    """Turns an effect into the colours of each LED at a moment in time.

    Painters are looked up by effect kind, so a new effect is added by
    registering a painter rather than by changing this class.
    """

    def __init__(self, painters: Mapping[EffectKind, EffectPainter] = DEFAULT_PAINTERS) -> None:
        self._painters = dict(painters)

    def render(self, effect: Effect, count: int, context: FrameContext) -> Frame:
        """Draw one frame.

        @param effect: what to draw.
        @param count: how many LEDs the zone has.
        @param context: the shared clock and sensor readings.
        @return: one colour per LED, with the effect's brightness applied.
        """
        if count <= 0:
            return ()
        frame = self._painters[effect.kind](effect, count, context)
        if effect.brightness >= 1.0:
            return frame
        return tuple(color.scaled(effect.brightness) for color in frame)
