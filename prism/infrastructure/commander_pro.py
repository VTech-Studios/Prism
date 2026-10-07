from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import IntEnum

from ..domain.color import BLACK, Color
from ..domain.devices import DeviceKind, FanChannel, LightingZone
from ..domain.effects import Direction, Effect, EffectKind, Speed
from ..domain.errors import DeviceError
from ..domain.rendering import Frame
from ..ports import HidTransport
from .hwmon import HwmonFans

VENDOR_ID = 0x1B1C
PRODUCT_ID = 0x0C10
REPORT_SIZE = 64
REPLY_SIZE = 16
DIRECT_CHUNK = 50
NAME = "Corsair Commander Pro"


class Command(IntEnum):
    SET_FAN_DUTY = 0x23
    DIRECT = 0x32
    COMMIT = 0x33
    BEGIN_EFFECT = 0x34
    EFFECT = 0x35
    RESET_CHANNEL = 0x37
    PORT_STATE = 0x38


class PortState(IntEnum):
    HARDWARE = 0x01
    SOFTWARE = 0x02


HARDWARE_MODES: Mapping[EffectKind, int] = {
    EffectKind.OFF: 0x04,
    EffectKind.STATIC: 0x04,
    EffectKind.BREATHING: 0x02,
    EffectKind.SPECTRUM: 0x0A,
    EffectKind.RAINBOW_WAVE: 0x00,
    EffectKind.COLOR_WAVE: 0x03,
    EffectKind.MARQUEE: 0x07,
    EffectKind.BLINK: 0x08,
}

_SPEEDS = {Speed.FAST: 0x00, Speed.MEDIUM: 0x01, Speed.SLOW: 0x02}
_DIRECTIONS = {Direction.FORWARD: 0x01, Direction.BACKWARD: 0x00}
_EFFECT_COLORS = 3
HARDWARE_COLORS = 2


def effect_colors(effect: Effect) -> tuple[Color, ...]:
    """Pick the colours to send with a hardware effect, with brightness baked in.

    The controller has no brightness of its own for coloured effects, so
    dimming is done by sending darker colours.

    @param effect: the effect.
    @return: up to three colours, empty when the controller should choose them itself.
    """
    if effect.kind is EffectKind.OFF:
        return (BLACK,)
    if effect.kind is EffectKind.BLINK and len(effect.colors) == 1:
        return (effect.colors[0].scaled(effect.brightness), BLACK)
    return tuple(color.scaled(effect.brightness) for color in effect.colors[:_EFFECT_COLORS])


def command(code: Command, *payload: int) -> bytes:
    """Build one report.

    @param code: the command.
    @param payload: the bytes after the command.
    @return: the report, without a report id.
    """
    return bytes([code, *payload])


def effect_reports(channel: int, led_count: int, effect: Effect) -> list[bytes]:
    """Build the reports that hand an effect to the controller to play by itself.

    The order matches iCUE: reset the channel, open an effect, switch the port
    to hardware playback, describe the effect over every LED, then commit.

    @param channel: the lighting channel, counting from 0.
    @param led_count: LEDs on the channel, so the effect spans all of them.
    @param effect: an effect with a hardware mode.
    @return: the reports, in order.
    """
    colors = effect_colors(effect)
    flat = [value for color in colors for value in (color.red, color.green, color.blue)]
    config = command(
        Command.EFFECT,
        channel,
        0,
        led_count,
        HARDWARE_MODES[effect.kind],
        _SPEEDS[effect.speed],
        _DIRECTIONS[effect.direction],
        0x00 if colors else 0x01,
        0xFF,
        *flat,
    )
    return [
        command(Command.RESET_CHANNEL, channel),
        command(Command.BEGIN_EFFECT, channel),
        command(Command.PORT_STATE, channel, PortState.HARDWARE),
        config,
        command(Command.COMMIT, 0xFF),
    ]


def frame_reports(channel: int, frame: Frame) -> list[bytes]:
    """Build the reports that show one frame, sent as red, green and blue planes.

    @param channel: the lighting channel, counting from 0.
    @param frame: one colour per LED.
    @return: the reports, ending with a commit.
    """
    reports: list[bytes] = []
    for start in range(0, len(frame), DIRECT_CHUNK):
        chunk = frame[start : start + DIRECT_CHUNK]
        planes = (
            [color.red for color in chunk],
            [color.green for color in chunk],
            [color.blue for color in chunk],
        )
        reports.extend(
            command(Command.DIRECT, channel, start, len(chunk), plane, *values)
            for plane, values in enumerate(planes)
        )
    reports.append(command(Command.COMMIT, 0xFF))
    return reports


class CommanderPro:
    """Drives a Corsair Commander Pro's lighting channels and fan headers directly over USB.

    Unlike liquidctl, every effect is described over the channel's full LED
    count, which is what lets a hardware effect run across every fan on a
    Corsair RGB hub rather than only the first.
    """

    def __init__(
        self, transport: HidTransport, fan_readings: HwmonFans, channel_leds: Mapping[int, int]
    ) -> None:
        """@param channel_leds: LEDs wired to each lighting channel, keyed by channel number from 1."""
        self._transport = transport
        self._fan_readings = fan_readings
        self._channel_leds = {channel: count for channel, count in channel_leds.items() if count > 0}
        self._software_channels: set[int] = set()

    @property
    def name(self) -> str:
        """The device's name."""
        return NAME

    def zones(self) -> Sequence[LightingZone]:
        """@return: one zone per lighting channel with LEDs on it."""
        return [
            LightingZone(
                id=f"cpro:led{channel}",
                name=f"RGB channel {channel}",
                device=NAME,
                kind=DeviceKind.FAN_CONTROLLER,
                led_count=count,
                hardware_effects=frozenset(HARDWARE_MODES),
                hardware_colors=HARDWARE_COLORS,
            )
            for channel, count in sorted(self._channel_leds.items())
        ]

    def play(self, zone_id: str, effect: Effect) -> None:
        """Hand an effect to the controller, which keeps playing it after Prism exits.

        @param zone_id: the zone.
        @param effect: an effect with a hardware mode.
        @raise DeviceError: if the controller does not respond.
        """
        channel = self._channel(zone_id)
        self._send(effect_reports(channel - 1, self._channel_leds[channel], effect))
        self._software_channels.discard(channel)

    def draw(self, zone_id: str, frame: Frame) -> None:
        """Show one frame, switching the channel to software control the first time.

        @param zone_id: the zone.
        @param frame: one colour per LED.
        @raise DeviceError: if the controller does not respond.
        """
        channel = self._channel(zone_id)
        if channel not in self._software_channels:
            self._send([command(Command.PORT_STATE, channel - 1, PortState.SOFTWARE)])
            self._software_channels.add(channel)
        self._send(frame_reports(channel - 1, frame))

    def fans(self) -> Sequence[FanChannel]:
        """@return: one channel per header with a fan plugged in."""
        return [
            FanChannel(id=f"cpro:fan{header}", name=f"Fan {header}", device=NAME)
            for header in self._fan_readings.connected()
        ]

    def set_duty(self, fan_id: str, duty: int) -> None:
        """Set a fan's speed.

        @param fan_id: the fan.
        @param duty: percent of full speed.
        @raise DeviceError: if the controller does not respond.
        """
        header = int(fan_id.removeprefix("cpro:fan"))
        self._send([command(Command.SET_FAN_DUTY, header - 1, max(0, min(100, duty)))])

    def speeds(self) -> Mapping[str, int]:
        """@return: each connected fan's RPM, as the kernel last read it."""
        readings = {header: self._fan_readings.rpm(header) for header in self._fan_readings.connected()}
        return {f"cpro:fan{header}": rpm for header, rpm in readings.items() if rpm is not None}

    def close(self) -> None:
        """Release the controller. Hardware effects and fan duties stay as they are."""
        self._transport.close()

    def _channel(self, zone_id: str) -> int:
        """Turn a zone id back into its channel number.

        @param zone_id: the zone.
        @return: the channel, counting from 1.
        @raise DeviceError: if the zone is not one of this controller's.
        """
        channel = int(zone_id.removeprefix("cpro:led"))
        if channel not in self._channel_leds:
            raise DeviceError(f"{zone_id} is not a lighting channel on the Commander Pro")
        return channel

    def _send(self, reports: Sequence[bytes]) -> None:
        """Send reports one by one, failing on the first one the controller refuses.

        @param reports: the reports.
        @raise DeviceError: if the controller does not respond or reports an error.
        """
        for report in reports:
            reply = self._transport.exchange(report, REPLY_SIZE)
            if reply[0] != 0x00:
                raise DeviceError(f"the Commander Pro refused command 0x{report[0]:02x}")
