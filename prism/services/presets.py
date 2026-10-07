from __future__ import annotations

from collections.abc import Sequence

from ..domain.color import Color
from ..domain.cooling import LIQUID_CURVES, PRESET_CURVES, FanSetting, PumpMode
from ..domain.devices import DeviceKind, FanChannel, LightingZone
from ..domain.effects import Effect, EffectKind, Gauge, Speed
from ..domain.profile import Profile
from ..domain.settings import DEFAULT_PROFILE

ORANGE = Color.from_hex("#ff2800")
COOLANT_COLORS = (Color.from_hex("#00ff00"), Color.from_hex("#ffa500"), Color.from_hex("#ff0000"))


def _lighting(zone: LightingZone, mood: str) -> Effect:
    """Choose a starter effect that suits what the zone is.

    @param zone: the zone.
    @param mood: "Default", "Quiet" or "Performance".
    @return: an effect the zone supports.
    """
    if mood == "Quiet":
        return Effect(EffectKind.STATIC, (Color.from_hex("#3a6bff"),), brightness=0.35)
    if zone.kind is DeviceKind.COOLER:
        return Effect(EffectKind.TEMPERATURE, COOLANT_COLORS, gauge=Gauge("liquid.temp", 30, 40))
    if zone.kind is DeviceKind.GPU:
        return Effect(EffectKind.BREATHING, (ORANGE,))
    speed = Speed.FAST if mood == "Performance" else Speed.MEDIUM
    return Effect(EffectKind.RAINBOW_WAVE, speed=speed)


def _supported(zone: LightingZone, effect: Effect) -> Effect:
    """Fall back to plainer effects on zones that cannot show the chosen one.

    @param zone: the zone.
    @param effect: the preferred effect.
    @return: the effect, a static orange, or off, whichever the zone supports first.
    """
    for candidate in (effect, Effect.static(ORANGE)):
        if zone.supports(candidate.kind):
            return candidate
    return Effect.off()


def _cooling(fan: FanChannel, mood: str) -> FanSetting:
    """Choose a starter curve: radiator fans follow the coolant, case fans the CPU.

    @param fan: the fan.
    @param mood: the preset curve to use.
    @return: the setting.
    """
    if fan.id.startswith("aio:"):
        return FanSetting.following("liquid.temp", LIQUID_CURVES[mood])
    return FanSetting.following("cpu.temp", PRESET_CURVES[mood])


def starter_profiles(zones: Sequence[LightingZone], fans: Sequence[FanChannel]) -> list[Profile]:
    """Build the profiles a first run starts with, fitted to the hardware that is connected.

    @param zones: the connected lighting zones.
    @param fans: the connected fans.
    @return: Default, Quiet and Performance profiles.
    """
    moods = {
        DEFAULT_PROFILE: ("Balanced", PumpMode.BALANCED),
        "Quiet": ("Quiet", PumpMode.QUIET),
        "Performance": ("Performance", PumpMode.EXTREME),
    }
    return [
        Profile(
            name,
            lighting={zone.id: _supported(zone, _lighting(zone, name)) for zone in zones},
            cooling={fan.id: _cooling(fan, curve) for fan in fans},
            pump=pump,
        )
        for name, (curve, pump) in moods.items()
    ]
