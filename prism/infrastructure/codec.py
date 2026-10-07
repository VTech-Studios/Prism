from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields
from typing import Any, cast

from ..domain.automation import Condition, ProcessRunning, ReadingAbove, Rule
from ..domain.color import Color
from ..domain.cooling import FanCurve, FanMode, FanSetting, PumpMode
from ..domain.effects import Direction, Effect, EffectKind, Gauge, Speed
from ..domain.errors import ValidationError
from ..domain.profile import Profile
from ..domain.settings import Settings

Json = dict[str, Any]


def encode_effect(effect: Effect) -> Json:
    """@return: the effect as plain JSON values."""
    data: Json = {
        "kind": effect.kind.value,
        "colors": [color.hex for color in effect.colors],
        "speed": effect.speed.value,
        "direction": effect.direction.value,
        "brightness": effect.brightness,
    }
    if effect.gauge:
        data["gauge"] = {"sensor": effect.gauge.sensor, "cool": effect.gauge.cool, "hot": effect.gauge.hot}
    return data


def decode_effect(data: Json) -> Effect:
    """@return: the effect read back from JSON."""
    gauge = data.get("gauge")
    return Effect(
        kind=EffectKind(data["kind"]),
        colors=tuple(Color.from_hex(text) for text in data.get("colors", [])),
        speed=Speed(data.get("speed", Speed.MEDIUM)),
        direction=Direction(data.get("direction", Direction.FORWARD)),
        brightness=float(data.get("brightness", 1.0)),
        gauge=Gauge(gauge["sensor"], float(gauge["cool"]), float(gauge["hot"])) if gauge else None,
    )


def encode_fan(setting: FanSetting) -> Json:
    """@return: the fan setting as plain JSON values."""
    data: Json = {"mode": setting.mode.value, "duty": setting.duty, "sensor": setting.sensor}
    if setting.curve:
        data["curve"] = [[point.temperature, point.duty] for point in setting.curve.points]
    return data


def decode_fan(data: Json) -> FanSetting:
    """@return: the fan setting read back from JSON."""
    curve = data.get("curve")
    return FanSetting(
        mode=FanMode(data["mode"]),
        duty=int(data.get("duty", 50)),
        curve=FanCurve.of([(float(t), int(d)) for t, d in curve]) if curve else None,
        sensor=data.get("sensor", "cpu.temp"),
    )


def encode_profile(profile: Profile) -> Json:
    """@return: the profile as plain JSON values."""
    return {
        "name": profile.name,
        "lighting": {zone: encode_effect(effect) for zone, effect in profile.lighting.items()},
        "cooling": {fan: encode_fan(setting) for fan, setting in profile.cooling.items()},
        "pump": profile.pump.value if profile.pump else None,
    }


def decode_profile(data: Json) -> Profile:
    """@return: the profile read back from JSON."""
    pump = data.get("pump")
    return Profile(
        name=data["name"],
        lighting={zone: decode_effect(effect) for zone, effect in data.get("lighting", {}).items()},
        cooling={fan: decode_fan(setting) for fan, setting in data.get("cooling", {}).items()},
        pump=PumpMode(pump) if pump else None,
    )


ConditionDecoder = Callable[[Json], Condition]

CONDITION_DECODERS: Mapping[str, ConditionDecoder] = {
    ReadingAbove.kind: lambda data: ReadingAbove(
        data["sensor"], float(data["threshold"]), data.get("label", "")
    ),
    ProcessRunning.kind: lambda data: ProcessRunning(data["name"]),
}


def encode_condition(condition: Condition) -> Json:
    """Write a condition with its kind, so it can be rebuilt as the right type.

    @param condition: a dataclass condition.
    @return: its fields plus a kind tag.
    """
    values = {field.name: getattr(condition, field.name) for field in fields(cast(Any, condition))}
    return {"kind": condition.kind, **values}


def decode_condition(data: Json) -> Condition:
    """@raise ValidationError: if the condition kind is unknown."""
    try:
        decoder = CONDITION_DECODERS[data["kind"]]
    except KeyError as error:
        raise ValidationError(f"unknown rule condition {data.get('kind')!r}") from error
    return decoder(data)


def encode_rule(rule: Rule) -> Json:
    """@return: the rule as plain JSON values."""
    return {
        "name": rule.name,
        "condition": encode_condition(rule.condition),
        "profile": rule.profile,
        "settle": rule.settle,
        "enabled": rule.enabled,
    }


def decode_rule(data: Json) -> Rule:
    """@return: the rule read back from JSON."""
    return Rule(
        name=data["name"],
        condition=decode_condition(data["condition"]),
        profile=data["profile"],
        settle=float(data.get("settle", 5.0)),
        enabled=bool(data.get("enabled", True)),
    )


def encode_settings(settings: Settings) -> Json:
    """@return: the settings as plain JSON values."""
    data = {name: getattr(settings, name) for name in settings.__dataclass_fields__}
    data["channel_leds"] = {str(channel): count for channel, count in settings.channel_leds.items()}
    data["openrgb_excluded"] = list(settings.openrgb_excluded)
    return data


def decode_settings(data: Json) -> Settings:
    """Read settings back, ignoring keys from other versions and filling in missing ones.

    @param data: the saved settings.
    @return: the settings.
    """
    known = {name: value for name, value in data.items() if name in Settings.__dataclass_fields__}
    if "channel_leds" in known:
        known["channel_leds"] = {int(channel): int(count) for channel, count in known["channel_leds"].items()}
    if "openrgb_excluded" in known:
        known["openrgb_excluded"] = tuple(known["openrgb_excluded"])
    return Settings(**known)
