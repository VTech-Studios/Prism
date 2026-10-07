import pytest

from prism.domain.color import BLACK, Color
from prism.domain.effects import Direction, Effect, EffectKind, Gauge, Speed
from prism.domain.errors import ValidationError
from prism.domain.rendering import FrameContext, Renderer

RED = Color(255, 0, 0)
GREEN = Color(0, 255, 0)
BLUE = Color(0, 0, 255)
PALETTE = (RED, GREEN, BLUE)


def at(elapsed: float, **readings: float) -> FrameContext:
    return FrameContext(elapsed, readings)


def test_effects_check_their_colour_count() -> None:
    with pytest.raises(ValidationError):
        Effect(EffectKind.STATIC)
    with pytest.raises(ValidationError):
        Effect(EffectKind.RAINBOW_WAVE, (RED,))


def test_temperature_needs_a_gauge() -> None:
    with pytest.raises(ValidationError):
        Effect(EffectKind.TEMPERATURE, PALETTE)


def test_gauge_must_rise() -> None:
    with pytest.raises(ValidationError):
        Gauge("cpu.temp", cool=50, hot=40)


def test_brightness_is_a_fraction() -> None:
    with pytest.raises(ValidationError):
        Effect(EffectKind.OFF, brightness=1.5)


def test_switching_kind_keeps_colours_and_tops_up_from_the_palette() -> None:
    wave = Effect.static(BLUE).with_kind(EffectKind.COLOR_WAVE, PALETTE)
    assert wave.colors == (BLUE, RED)
    assert wave.with_kind(EffectKind.RAINBOW_WAVE, PALETTE).colors == ()
    gauge = wave.with_kind(EffectKind.TEMPERATURE, PALETTE)
    assert gauge.gauge == Gauge("cpu.temp")
    assert gauge.with_kind(EffectKind.STATIC, PALETTE).gauge is None


def test_with_color_replaces_one_slot() -> None:
    assert Effect.static(RED).with_color(0, BLUE).colors == (BLUE,)


def test_animated_flag() -> None:
    assert EffectKind.RAINBOW_WAVE.animated
    assert not EffectKind.STATIC.animated


def test_renders_static_off_and_brightness() -> None:
    renderer = Renderer()
    assert renderer.render(Effect.static(RED), 3, at(0)) == (RED,) * 3
    assert renderer.render(Effect.off(), 2, at(0)) == (BLACK, BLACK)
    dim = Effect(EffectKind.STATIC, (RED,), brightness=0.5)
    assert renderer.render(dim, 1, at(0)) == (Color(128, 0, 0),)
    assert renderer.render(Effect.static(RED), 0, at(0)) == ()


def test_breathing_fades_and_moves_to_the_next_colour() -> None:
    renderer = Renderer()
    effect = Effect(EffectKind.BREATHING, (RED, BLUE), speed=Speed.FAST)
    assert renderer.render(effect, 1, at(0)) == (BLACK,)
    assert renderer.render(effect, 1, at(1)) == (RED,)
    assert renderer.render(effect, 1, at(3)) == (BLUE,)


def test_rainbow_wave_spreads_the_wheel_and_travels() -> None:
    renderer = Renderer()
    effect = Effect(EffectKind.RAINBOW_WAVE)
    frame = renderer.render(effect, 3, at(0))
    assert frame == (RED, GREEN, BLUE)
    assert renderer.render(effect, 3, at(4 / 3)) == (BLUE, RED, GREEN)
    backward = Effect(EffectKind.RAINBOW_WAVE, direction=Direction.BACKWARD)
    assert renderer.render(backward, 3, at(4 / 3)) == (GREEN, BLUE, RED)


def test_spectrum_moves_all_leds_together() -> None:
    frame = Renderer().render(Effect(EffectKind.SPECTRUM), 4, at(4 / 3))
    assert len(set(frame)) == 1


def test_colour_wave_runs_through_the_chosen_colours() -> None:
    frame = Renderer().render(Effect(EffectKind.COLOR_WAVE, (RED, BLUE)), 4, at(0))
    assert frame[0] == RED
    assert frame[2] == BLUE


def test_marquee_lights_every_third_led() -> None:
    frame = Renderer().render(Effect(EffectKind.MARQUEE, (RED,)), 6, at(0))
    assert frame == (RED, BLACK, BLACK, RED, BLACK, BLACK)


def test_blink_alternates() -> None:
    renderer = Renderer()
    effect = Effect(EffectKind.BLINK, (RED,), speed=Speed.SLOW)
    assert renderer.render(effect, 1, at(0)) == (RED,)
    assert renderer.render(effect, 1, at(2.5)) == (BLACK,)
    pair = Effect(EffectKind.BLINK, (RED, BLUE), speed=Speed.SLOW)
    assert renderer.render(pair, 1, at(2.5)) == (BLUE,)


def test_temperature_follows_its_sensor() -> None:
    renderer = Renderer()
    effect = Effect(EffectKind.TEMPERATURE, PALETTE, gauge=Gauge("liquid.temp", cool=30, hot=40))
    assert renderer.render(effect, 1, at(0)) == (RED,)
    assert renderer.render(effect, 1, at(0, **{"liquid.temp": 20})) == (RED,)
    assert renderer.render(effect, 1, at(0, **{"liquid.temp": 35})) == (GREEN,)
    assert renderer.render(effect, 1, at(0, **{"liquid.temp": 50})) == (BLUE,)


def test_painters_can_be_extended() -> None:
    renderer = Renderer({EffectKind.STATIC: lambda effect, count, context: (BLUE,) * count})
    assert renderer.render(Effect.static(RED), 2, at(0)) == (BLUE, BLUE)
