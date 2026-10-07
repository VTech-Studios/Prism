from __future__ import annotations

import copy
import json
import re
import socket
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

from ..domain.color import BLACK, Color
from ..domain.devices import DeviceKind, LightingZone
from ..domain.effects import Direction, Effect, EffectKind, Speed
from ..domain.errors import DeviceError
from ..domain.rendering import Frame

NAME = "OpenRGB"
CORSAIR_DETECTORS = ("Corsair Commander Pro", "Corsair Hydro H100i Platinum", "Corsair Hydro H115i Platinum")
CONFIG_PATH = Path.home() / ".config" / "OpenRGB" / "OpenRGB.json"

MODE_NAMES: Mapping[EffectKind, tuple[str, ...]] = {
    EffectKind.STATIC: ("static",),
    EffectKind.OFF: ("off",),
    EffectKind.BREATHING: ("breathing",),
    EffectKind.SPECTRUM: ("spectrum cycle", "color cycle", "colour cycle"),
    EffectKind.RAINBOW_WAVE: ("rainbow wave", "rainbow"),
    EffectKind.COLOR_WAVE: ("color wave", "colour wave", "wave"),
    EffectKind.MARQUEE: ("marquee", "chase"),
    EffectKind.BLINK: ("flashing", "blink", "strobe"),
}

_KINDS = {0: DeviceKind.MOTHERBOARD, 1: DeviceKind.MEMORY, 2: DeviceKind.GPU, 3: DeviceKind.COOLER}
_DIRECT = ("direct", "custom")
_HAS_SPEED = 1 << 0
_HAS_DIRECTION_LR = 1 << 1
_HAS_BRIGHTNESS = 1 << 4
_MODE_SPECIFIC = 2
_PER_LED = 1
_SPEED_SHARE = {Speed.SLOW: 0.15, Speed.MEDIUM: 0.5, Speed.FAST: 0.85}


def slug(text: str) -> str:
    """Turn a device name into part of a stable zone id.

    @param text: the device name.
    @return: lower case words joined by dashes.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def find_mode(modes: Sequence[Any], names: Iterable[str]) -> Any | None:
    """Find the first of a device's modes that goes by one of the given names.

    @param modes: the device's modes.
    @param names: acceptable names, best first, lower case.
    @return: the mode, or None if the device has none of them.
    """
    by_name = {mode.name.lower(): mode for mode in modes}
    return next((by_name[name] for name in names if name in by_name), None)


def tune_mode(mode: Any, effect: Effect) -> Any:
    """Copy a device mode and set its speed, direction, brightness and colours from an effect.

    @param mode: one of the device's modes, left untouched.
    @param effect: the effect to express.
    @return: the adjusted copy, ready to send.
    """
    tuned = copy.copy(mode)
    if tuned.flags & _HAS_SPEED and tuned.speed_min is not None and tuned.speed_max is not None:
        span = tuned.speed_max - tuned.speed_min
        tuned.speed = round(tuned.speed_min + span * _SPEED_SHARE[effect.speed])
    if tuned.flags & _HAS_DIRECTION_LR:
        tuned.direction = 1 if effect.direction is Direction.FORWARD else 0
    if tuned.flags & _HAS_BRIGHTNESS and tuned.brightness_max is not None:
        low = tuned.brightness_min or 0
        tuned.brightness = round(low + (tuned.brightness_max - low) * effect.brightness)
    if tuned.color_mode == _MODE_SPECIFIC and tuned.colors_max:
        tuned.colors = _mode_colors(effect, tuned.colors_min or 1, tuned.colors_max)
    return tuned


def _mode_colors(effect: Effect, fewest: int, most: int) -> list[Any]:
    """Fit an effect's colours into the number of slots a mode has.

    @param effect: the effect.
    @param fewest: the mode's minimum number of colours.
    @param most: the mode's maximum number of colours.
    @return: OpenRGB colours, repeating the last one if the mode wants more.
    """
    colors = list(effect.colors[:most]) or [BLACK]
    colors += [colors[-1]] * (fewest - len(colors))
    return [_rgb(color) for color in colors]


def _rgb(color: Color) -> Any:
    """@return: the colour as openrgb-python's colour type."""
    return RGBColor(color.red, color.green, color.blue)


class OpenRgbLighting:
    """Lighting on everything OpenRGB reaches over I2C and USB: RAM, GPU and motherboard.

    Each OpenRGB device is one zone, because device modes apply to the whole
    device. Devices Prism drives itself are skipped, so two programs never
    fight over the same LEDs.
    """

    def __init__(self, client: Any, excluded: Sequence[str]) -> None:
        """@param client: a connected openrgb-python client.
        @param excluded: device names, or parts of them, to leave alone.
        """
        self._client = client
        self._devices: dict[str, Any] = {}
        self._kinds: dict[str, DeviceKind] = {}
        self._drawing: set[str] = set()
        lowered = [name.lower() for name in excluded]
        for device in client.devices:
            if not any(name in device.name.lower() for name in lowered):
                self._add(device)

    @property
    def name(self) -> str:
        """The device's name."""
        return NAME

    def zones(self) -> Sequence[LightingZone]:
        """@return: one zone per OpenRGB device."""
        return [
            LightingZone(
                id=zone_id,
                name=device.name,
                device=NAME,
                kind=self._kinds[zone_id],
                led_count=len(device.leds),
                hardware_effects=frozenset(
                    kind for kind, names in MODE_NAMES.items() if find_mode(device.modes, names)
                ),
                streams=find_mode(device.modes, _DIRECT) is not None,
            )
            for zone_id, device in self._devices.items()
        ]

    def play(self, zone_id: str, effect: Effect) -> None:
        """Switch the device to its own version of the effect.

        @param zone_id: the zone.
        @param effect: an effect the device has a mode for.
        @raise DeviceError: if OpenRGB does not respond or the device lacks the mode.
        """
        device = self._device(zone_id)
        mode = find_mode(device.modes, MODE_NAMES[effect.kind])
        if mode is None:
            raise DeviceError(f"{device.name} has no {effect.kind.label} mode")
        tuned = tune_mode(mode, effect)
        self._call(lambda: device.set_mode(tuned))
        if tuned.color_mode == _PER_LED and effect.colors:
            color = _rgb(effect.colors[0].scaled(effect.brightness))
            self._call(lambda: device.set_color(color))
        self._drawing.discard(zone_id)

    def draw(self, zone_id: str, frame: Frame) -> None:
        """Show one frame, switching the device to direct mode the first time.

        @param zone_id: the zone.
        @param frame: one colour per LED.
        @raise DeviceError: if OpenRGB does not respond.
        """
        device = self._device(zone_id)
        if zone_id not in self._drawing:
            direct = find_mode(device.modes, _DIRECT)
            self._call(lambda: device.set_mode(direct))
            self._drawing.add(zone_id)
        colors = [_rgb(color) for color in frame]
        self._call(lambda: device.set_colors(colors, fast=True))

    def close(self) -> None:
        """Disconnect from OpenRGB. Devices keep their last mode."""
        self._call(self._client.disconnect)

    def _add(self, device: Any) -> None:
        """Register a device under a zone id that stays the same between runs.

        @param device: the OpenRGB device.
        """
        base = f"orgb:{slug(device.name)}"
        zone_id, number = base, 1
        while zone_id in self._devices:
            number += 1
            zone_id = f"{base}-{number}"
        self._devices[zone_id] = device
        self._kinds[zone_id] = _KINDS.get(int(device.type), DeviceKind.OTHER)

    def _device(self, zone_id: str) -> Any:
        """@raise DeviceError: if the zone is not one of OpenRGB's."""
        try:
            return self._devices[zone_id]
        except KeyError as error:
            raise DeviceError(f"{zone_id} is not an OpenRGB device") from error

    @staticmethod
    def _call(call: Callable[[], object]) -> None:
        """Run a client call, turning socket and protocol failures into one error.

        @param call: the call.
        @raise DeviceError: if it failed.
        """
        try:
            call()
        except (OSError, ValueError, TypeError) as error:
            raise DeviceError(f"OpenRGB stopped responding: {error}") from error


class OpenRgbServer:
    """Finds the OpenRGB SDK server, starting a headless one once if none is running.

    Connecting never waits for OpenRGB: while the server it started is still
    detecting devices, which can take half a minute, connect simply fails and
    the registry tries again later. That keeps the fans being driven meanwhile,
    and means a slow start can never lead to a second server being launched.
    The server is left running when Prism exits.
    """

    def __init__(
        self,
        host: str,
        port: int,
        launch: bool,
        spawn: Callable[[list[str]], Any] | None = None,
        connect_client: Callable[[str, int], Any] | None = None,
    ) -> None:
        """@param spawn: starts a program in the background, swappable for tests.
        @param connect_client: opens an SDK client, swappable for tests.
        """
        self._host = host
        self._port = port
        self._launch = launch
        self._spawn = spawn or _spawn_detached
        self._connect_client = connect_client or (lambda host, port: OpenRGBClient(host, port, name="Prism"))
        self._started = False

    def connect(self) -> Any:
        """Connect to the server, starting it the first time it is missing.

        @return: a connected openrgb-python client.
        @raise DeviceError: if the server is not reachable yet.
        """
        if not self._listening():
            self._start_once()
            raise DeviceError("waiting for OpenRGB to finish detecting devices")
        try:
            return self._connect_client(self._host, self._port)
        except (OSError, ValueError) as error:
            raise DeviceError(f"cannot reach the OpenRGB server on port {self._port}: {error}") from error

    def _listening(self) -> bool:
        """@return: whether something accepts connections on the SDK port."""
        try:
            with socket.create_connection((self._host, self._port), timeout=0.5):
                return True
        except OSError:
            return False

    def _start_once(self) -> None:
        """Start a headless server, unless starting is off or one was already started.

        @raise DeviceError: if starting is off, or OpenRGB is not installed.
        """
        if not self._launch:
            raise DeviceError(f"no OpenRGB server on port {self._port}, and starting one is turned off")
        if self._started:
            return
        self._started = True
        try:
            self._spawn(["openrgb", "--server", "--server-port", str(self._port)])
        except OSError as error:
            raise DeviceError(f"cannot start OpenRGB: {error}") from error


def _spawn_detached(args: list[str]) -> subprocess.Popen[bytes]:
    """Start a program in its own session, so it outlives Prism and never shares its terminal.

    @param args: the program and its arguments.
    @return: the process.
    """
    return subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class OpenRgbDetectors:
    """Turns off OpenRGB's detection of devices Prism drives itself.

    Every time OpenRGB detects a Corsair controller it resets it, and the
    Hydro Platinum can drop off USB entirely, so the safest arrangement is for
    OpenRGB never to look at them.
    """

    def __init__(self, names: Sequence[str] = CORSAIR_DETECTORS, path: Path = CONFIG_PATH) -> None:
        """@param names: detector names exactly as OpenRGB lists them."""
        self._names = list(names)
        self._path = path

    def is_off(self) -> bool:
        """@return: whether every detector is already off, or False if OpenRGB has no configuration yet."""
        try:
            detectors = self._detectors(self._read())
        except DeviceError:
            return False
        return all(detectors.get(name) is False for name in self._names)

    def turn_off(self) -> None:
        """Turn the detectors off, keeping a copy of the old file beside it.

        @raise DeviceError: if the configuration cannot be read or written.
        """
        config = self._read()
        self._detectors(config).update(dict.fromkeys(self._names, False))
        try:
            self._path.with_suffix(".json.prism-backup").write_text(self._path.read_text())
            self._path.write_text(json.dumps(config, indent=4))
        except OSError as error:
            raise DeviceError(f"cannot write {self._path}: {error}") from error

    def _read(self) -> dict[str, Any]:
        """@raise DeviceError: if OpenRGB has never been run or the file is damaged."""
        try:
            data: dict[str, Any] = json.loads(self._path.read_text())
        except (OSError, ValueError) as error:
            raise DeviceError(f"cannot read {self._path}: {error}") from error
        return data

    @staticmethod
    def _detectors(config: dict[str, Any]) -> dict[str, Any]:
        """@return: the detector switches, created if missing."""
        section: dict[str, Any] = config.setdefault("Detectors", {}).setdefault("detectors", {})
        return section
