from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .domain.automation import Rule
from .domain.cooling import PumpMode
from .domain.devices import FanChannel, LightingZone, Sensor
from .domain.effects import Effect
from .domain.profile import Profile
from .domain.rendering import Frame
from .domain.settings import Settings


class Device(Protocol):
    @property
    def name(self) -> str:
        """The device's name, as shown on the dashboard."""
        ...

    def close(self) -> None:
        """Release the device so another program can use it."""
        ...


@runtime_checkable
class LightingDevice(Device, Protocol):
    def zones(self) -> Sequence[LightingZone]:
        """@return: every lighting zone the device has."""
        ...

    def play(self, zone_id: str, effect: Effect) -> None:
        """Hand an effect to the device to play by itself.

        @param zone_id: the zone.
        @param effect: an effect listed in the zone's hardware effects.
        @raise DeviceError: if the device does not respond.
        """
        ...

    def draw(self, zone_id: str, frame: Frame) -> None:
        """Show one frame Prism has drawn.

        @param zone_id: the zone.
        @param frame: one colour per LED.
        @raise DeviceError: if the device does not respond.
        """
        ...


@runtime_checkable
class FanDevice(Device, Protocol):
    def fans(self) -> Sequence[FanChannel]:
        """@return: every fan the device can drive."""
        ...

    def set_duty(self, fan_id: str, duty: int) -> None:
        """Set a fan's speed.

        @param fan_id: the fan.
        @param duty: percent of full speed.
        @raise DeviceError: if the device does not respond.
        """
        ...

    def speeds(self) -> Mapping[str, int]:
        """@return: each fan's speed in RPM, keyed by fan id."""
        ...


@runtime_checkable
class PumpDevice(Device, Protocol):
    def set_pump(self, mode: PumpMode) -> None:
        """Change how hard the AIO pump works.

        @param mode: the pump mode.
        @raise DeviceError: if the device does not respond.
        """
        ...


@runtime_checkable
class SensorSource(Protocol):
    def sensors(self) -> Sequence[Sensor]:
        """@return: every value this source can read."""
        ...

    def read(self) -> Mapping[str, float]:
        """Read every sensor at once.

        @return: values keyed by sensor id. Sensors that failed this time are left out.
        """
        ...


class ProcessSource(Protocol):
    def running(self) -> frozenset[str]:
        """@return: the lower case names of every running program."""
        ...


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], timeout: float = 5.0) -> str:
        """Run a command to completion.

        @param args: the program and its arguments, never passed through a shell.
        @param timeout: seconds before the command is abandoned.
        @return: the command's standard output.
        @raise DeviceError: if the command is missing, times out, or fails.
        """
        ...


class HidTransport(Protocol):
    def exchange(self, report: bytes, reply_size: int) -> bytes:
        """Send one report and wait for the device's reply.

        @param report: the report, without the leading report id.
        @param reply_size: the length of the reply.
        @return: the reply.
        @raise DeviceError: if the device is gone or does not answer.
        """
        ...

    def close(self) -> None:
        """Release the device."""
        ...


class ProfileStore(Protocol):
    def load(self) -> list[Profile]:
        """@return: every saved profile, or an empty list on first run."""
        ...

    def save(self, profiles: Sequence[Profile]) -> None:
        """Replace the saved profiles.

        @param profiles: every profile to keep.
        """
        ...


class RuleStore(Protocol):
    def load(self) -> list[Rule]:
        """@return: every saved rule, highest priority first."""
        ...

    def save(self, rules: Sequence[Rule]) -> None:
        """Replace the saved rules.

        @param rules: every rule, highest priority first.
        """
        ...


class SettingsStore(Protocol):
    def load(self) -> Settings:
        """@return: the saved settings, or the defaults on first run."""
        ...

    def save(self, settings: Settings) -> None:
        """Keep the settings for next time.

        @param settings: the settings.
        """
        ...


class ProfileFiles(Protocol):
    def export(self, profile: Profile, path: Path) -> None:
        """Write a profile to a file, to back it up or share it.

        @param profile: the profile.
        @param path: where to write it.
        @raise PrismError: if the file cannot be written.
        """
        ...

    def read(self, path: Path) -> Profile:
        """Read a profile someone exported.

        @param path: the file.
        @return: the profile.
        @raise PrismError: if the file is missing or is not a profile.
        """
        ...


class DetectorSwitch(Protocol):
    def is_off(self) -> bool:
        """@return: whether OpenRGB already leaves the devices Prism drives alone."""
        ...

    def turn_off(self) -> None:
        """Stop OpenRGB detecting the devices Prism drives.

        @raise PrismError: if OpenRGB's configuration cannot be changed.
        """
        ...


class SleepWatch(Protocol):
    def woke(self) -> bool:
        """Say whether the machine has been suspended since the last call.

        @return: True once after each resume.
        """
        ...


class Autostart(Protocol):
    def enabled(self) -> bool:
        """@return: whether Prism starts when the user logs in."""
        ...

    def set_enabled(self, enabled: bool) -> None:
        """Start, or stop starting, Prism at login.

        @param enabled: whether it should start.
        """
        ...
