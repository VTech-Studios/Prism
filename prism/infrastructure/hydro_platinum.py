from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from liquidctl import find_liquidctl_devices

from ..domain.cooling import PumpMode
from ..domain.devices import DeviceKind, FanChannel, LightingZone, Sensor
from ..domain.effects import Effect, EffectKind
from ..domain.errors import DeviceError
from ..domain.rendering import Frame

LIQUID_TEMP = "liquid.temp"
_FAN_SPEED = re.compile(r"Fan (\d+) speed")


class LiquidctlDriver(Protocol):
    description: str

    def connect(self) -> Any: ...

    def disconnect(self) -> None: ...

    def initialize(self, pump_mode: str) -> Any: ...

    def get_status(self) -> list[tuple[str, Any, str]]: ...

    def set_fixed_speed(self, channel: str, duty: int) -> None: ...

    def set_color(self, channel: str, mode: str, colors: list[tuple[int, int, int]]) -> None: ...


def find_liquidctl(match: str) -> LiquidctlDriver:
    """Find and connect to a liquidctl device.

    @param match: text the device's description must contain.
    @return: the connected driver.
    @raise DeviceError: if no such device is on the USB bus.
    """
    for found in find_liquidctl_devices(match=match):
        driver: LiquidctlDriver = found
        driver.connect()
        return driver
    raise DeviceError(f"no {match} found on USB; if its pump light is flashing, it has dropped off the bus")


class HydroPlatinum:
    """Drives a Corsair Hydro Platinum AIO: the pump's LEDs, its radiator fans and the pump mode.

    The cooler has no effects of its own beyond a fixed colour, so animated
    effects are drawn by Prism one frame at a time.
    """

    def __init__(self, connect: Callable[[], LiquidctlDriver], led_count: int = 24) -> None:
        """Connect and set the pump to balanced, which the cooler needs before it takes fan commands.

        @param connect: opens the liquidctl driver.
        @param led_count: LEDs on the pump head plus any RGB fans plugged into it.
        @raise DeviceError: if the cooler is not connected or refuses to start.
        """
        self._driver = self._guard(connect)
        self._led_count = led_count
        self._guard(lambda: self._driver.initialize(pump_mode=PumpMode.BALANCED.value))
        self._fan_numbers = sorted(
            int(match.group(1)) for key, _, _ in self._status() if (match := _FAN_SPEED.fullmatch(key))
        )

    @property
    def name(self) -> str:
        """The device's name."""
        return str(self._driver.description)

    def zones(self) -> Sequence[LightingZone]:
        """@return: the pump head's lighting."""
        return [
            LightingZone(
                id="aio:led",
                name="Pump head",
                device=self.name,
                kind=DeviceKind.COOLER,
                led_count=self._led_count,
                hardware_effects=frozenset({EffectKind.OFF, EffectKind.STATIC}),
            )
        ]

    def play(self, zone_id: str, effect: Effect) -> None:
        """Set a fixed colour, the only thing the cooler shows by itself.

        @param zone_id: the zone.
        @param effect: static or off.
        @raise DeviceError: if the cooler does not respond.
        """
        color = effect.colors[0].scaled(effect.brightness) if effect.colors else None
        rgb = [(color.red, color.green, color.blue)] if color else [(0, 0, 0)]
        self._guard(lambda: self._driver.set_color("led", "fixed", rgb))

    def draw(self, zone_id: str, frame: Frame) -> None:
        """Show one frame.

        @param zone_id: the zone.
        @param frame: one colour per LED.
        @raise DeviceError: if the cooler does not respond.
        """
        rgb = [(color.red, color.green, color.blue) for color in frame]
        self._guard(lambda: self._driver.set_color("led", "super-fixed", rgb))

    def fans(self) -> Sequence[FanChannel]:
        """@return: the radiator fans."""
        return [
            FanChannel(id=f"aio:fan{number}", name=f"Radiator fan {number}", device=self.name)
            for number in self._fan_numbers
        ]

    def set_duty(self, fan_id: str, duty: int) -> None:
        """Set a radiator fan's speed.

        @param fan_id: the fan.
        @param duty: percent of full speed.
        @raise DeviceError: if the cooler does not respond.
        """
        channel = fan_id.removeprefix("aio:")
        self._guard(lambda: self._driver.set_fixed_speed(channel, duty))

    def speeds(self) -> Mapping[str, int]:
        """@return: the radiator fans' RPM."""
        speeds = {}
        for key, value, _ in self._status():
            if match := _FAN_SPEED.fullmatch(key):
                speeds[f"aio:fan{match.group(1)}"] = int(value)
        return speeds

    def set_pump(self, mode: PumpMode) -> None:
        """Change the pump mode.

        @param mode: the pump mode.
        @raise DeviceError: if the cooler does not respond.
        """
        self._guard(lambda: self._driver.initialize(pump_mode=mode.value))

    def sensors(self) -> Sequence[Sensor]:
        """@return: the coolant temperature."""
        return [Sensor(LIQUID_TEMP, "Coolant", "°C")]

    def read(self) -> Mapping[str, float]:
        """@return: the coolant temperature, or nothing if the cooler did not answer."""
        try:
            status = self._status()
        except DeviceError:
            return {}
        temperatures = [float(value) for key, value, _ in status if key == "Liquid temperature"]
        return {LIQUID_TEMP: temperatures[0]} if temperatures else {}

    def close(self) -> None:
        """Release the cooler. It keeps its last colour and fan speeds."""
        self._driver.disconnect()

    def _status(self) -> list[tuple[str, Any, str]]:
        """@return: liquidctl's status lines."""
        return self._guard(self._driver.get_status)

    @staticmethod
    def _guard[T](call: Callable[[], T]) -> T:
        """Run a liquidctl call, turning its many failure types into one.

        @param call: the call.
        @return: what the call returned.
        @raise DeviceError: if the call failed for any reason.
        """
        try:
            return call()
        except DeviceError:
            raise
        except Exception as error:
            raise DeviceError(f"the AIO cooler stopped responding: {error}") from error
