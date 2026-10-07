from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ValidationError

DEFAULT_PROFILE = "Default"


@dataclass(frozen=True, slots=True)
class Settings:
    """The user's preferences, kept between runs.

    @ivar active_profile: the profile chosen by hand, which rules fall back to.
    @ivar automation: whether rules may switch profiles.
    @ivar prefer_hardware: let devices play effects themselves where they can, so lighting
        keeps going after Prism exits. Off means Prism draws everything, which keeps
        every device in step.
    @ivar fan_floor: the lowest duty any fan is ever given.
    @ivar handoff_duty: the duty fans are left at when Prism exits, since nothing will adjust them after.
    @ivar frame_rate: frames per second for effects Prism draws.
    @ivar channel_leds: LEDs on each Commander Pro lighting channel, keyed by channel number.
    @ivar openrgb_excluded: names of OpenRGB devices Prism drives itself and must not touch twice.
    """

    active_profile: str = DEFAULT_PROFILE
    automation: bool = True
    prefer_hardware: bool = True
    start_hidden: bool = False
    fan_floor: int = 20
    handoff_duty: int = 50
    frame_rate: int = 30
    openrgb_host: str = "127.0.0.1"
    openrgb_port: int = 6742
    launch_openrgb: bool = True
    channel_leds: dict[int, int] = field(default_factory=lambda: {1: 72, 2: 0})
    openrgb_excluded: tuple[str, ...] = ("Commander Pro", "H115i", "Hydro")

    def __post_init__(self) -> None:
        if not 0 <= self.fan_floor <= 60:
            raise ValidationError("the fan floor must be between 0 and 60")
        if not self.fan_floor <= self.handoff_duty <= 100:
            raise ValidationError("the exit duty must be between the fan floor and 100")
        if not 1 <= self.frame_rate <= 60:
            raise ValidationError("the frame rate must be between 1 and 60")
