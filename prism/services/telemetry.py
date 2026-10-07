from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..domain.automation import SystemSnapshot
from ..domain.devices import Sensor
from ..domain.errors import DeviceError
from ..ports import ProcessSource, SensorSource
from .registry import DeviceRegistry


@dataclass(frozen=True, slots=True)
class Sample:
    """Everything measured in one pass.

    @ivar speeds: fan RPM keyed by fan id.
    """

    snapshot: SystemSnapshot = field(default_factory=SystemSnapshot)
    speeds: Mapping[str, int] = field(default_factory=dict)


class Telemetry:
    """Gathers sensor readings, fan speeds and running programs into one sample."""

    def __init__(
        self, registry: DeviceRegistry, sources: Sequence[SensorSource], processes: ProcessSource
    ) -> None:
        """@param sources: sensors that are always there, such as the CPU. Devices add their own."""
        self._registry = registry
        self._sources = list(sources)
        self._processes = processes

    def sensors(self) -> list[Sensor]:
        """@return: every sensor currently available."""
        return [sensor for source in self._all_sources() for sensor in source.sensors()]

    def sample(self, with_processes: bool) -> Sample:
        """Measure everything.

        @param with_processes: whether to list running programs, which only rules need.
        @return: the sample.
        """
        readings: dict[str, float] = {}
        for source in self._all_sources():
            readings.update(source.read())
        speeds: dict[str, int] = {}
        for device in self._registry.fan_devices():
            try:
                speeds.update(device.speeds())
            except DeviceError as error:
                self._registry.fail(device, error)
        processes = self._processes.running() if with_processes else frozenset()
        return Sample(SystemSnapshot(readings, processes), speeds)

    def _all_sources(self) -> list[SensorSource]:
        """@return: the fixed sources followed by any connected devices that report sensors."""
        return self._sources + self._registry.sensor_sources()
