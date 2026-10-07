from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

import psutil

from ..domain.devices import Sensor
from ..domain.errors import DeviceError
from ..ports import CommandRunner, SensorSource

CPU_TEMP = "cpu.temp"
CPU_LOAD = "cpu.load"
GPU_TEMP = "gpu.temp"
GPU_LOAD = "gpu.load"

STALE_AFTER = 3

_LOG = logging.getLogger(__name__)

_CPU_PROBES = (("coretemp", "Package id 0"), ("k10temp", "Tctl"), ("zenpower", "Tdie"))


class CpuSensors:
    """CPU package temperature and load, read through psutil."""

    def __init__(
        self, temperatures: Any = psutil.sensors_temperatures, load: Any = psutil.cpu_percent
    ) -> None:
        """@param temperatures: psutil's temperature reader, swappable for tests.
        @param load: psutil's load reader, swappable for tests.
        """
        self._temperatures = temperatures
        self._load = load
        self._load(None)

    def sensors(self) -> Sequence[Sensor]:
        """@return: the CPU temperature and load."""
        return [Sensor(CPU_TEMP, "CPU", "°C"), Sensor(CPU_LOAD, "CPU load", "%")]

    def read(self) -> Mapping[str, float]:
        """@return: the CPU load since the last read, and the package temperature if a probe is found."""
        readings = {CPU_LOAD: float(self._load(None))}
        temperature = self._package_temperature()
        if temperature is not None:
            readings[CPU_TEMP] = temperature
        return readings

    def _package_temperature(self) -> float | None:
        """Find the whole-package temperature among the kernel's probes.

        @return: degrees Celsius, or None if no known probe is present.
        """
        probes = self._temperatures()
        for chip, label in _CPU_PROBES:
            for entry in probes.get(chip, []):
                if entry.label == label:
                    return float(entry.current)
        return None


class NvidiaSensors:
    """GPU temperature and load from nvidia-smi."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def sensors(self) -> Sequence[Sensor]:
        """@return: the GPU temperature and load."""
        return [Sensor(GPU_TEMP, "GPU", "°C"), Sensor(GPU_LOAD, "GPU load", "%")]

    def read(self) -> Mapping[str, float]:
        """@return: the first GPU's temperature and load, or nothing if nvidia-smi failed."""
        query = ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"]
        try:
            first = self._runner.run(query).splitlines()[0]
            temperature, load = (float(value) for value in first.split(","))
        except (DeviceError, IndexError, ValueError):
            return {}
        return {GPU_TEMP: temperature, GPU_LOAD: load}


class PsutilProcesses:
    """Lists running programs by name, so rules can react to a game starting."""

    def running(self) -> frozenset[str]:
        """List running programs.

        Wine games show up under their .exe name, which is the name users know them by.

        @return: lower case program names.
        """
        names = set()
        for process in psutil.process_iter(["name", "cmdline"]):
            names.add((process.info.get("name") or "").lower())
            names.update(_exe_names(process.info.get("cmdline") or []))
        names.discard("")
        return frozenset(names)


def _exe_names(cmdline: Sequence[str]) -> set[str]:
    """Pull Windows program names out of a command line, for games run through Wine or Proton.

    @param cmdline: the process's arguments.
    @return: the lower case file names of any .exe arguments.
    """
    return {
        arg.replace("\\", "/").rsplit("/", 1)[-1].lower() for arg in cmdline if arg.lower().endswith(".exe")
    }


class BackgroundSensors:
    """Reads a slow sensor source on its own thread, so reading it never holds up a lighting frame.

    nvidia-smi can take several hundred milliseconds, far longer than a frame.
    Reads return the latest finished sample immediately.
    """

    def __init__(self, source: SensorSource, interval: float = 1.0) -> None:
        """@param source: the slow source. @param interval: seconds between samples."""
        self._source = source
        self._interval = interval
        self._latest: Mapping[str, float] = {}
        self._taken = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="prism-sensors", daemon=True)
        self._thread.start()

    def sensors(self) -> Sequence[Sensor]:
        """@return: the wrapped source's sensors."""
        return self._source.sensors()

    def read(self) -> Mapping[str, float]:
        """@return: the latest sample, or nothing if there is none recent enough to trust."""
        with self._lock:
            fresh = time.monotonic() - self._taken <= self._interval * STALE_AFTER
            return dict(self._latest) if fresh else {}

    def close(self) -> None:
        """Stop sampling."""
        self._stop.set()

    def _run(self) -> None:
        """Sample until closed."""
        while not self._stop.is_set():
            try:
                readings = self._source.read()
            except Exception:
                _LOG.exception("background sensor read failed")
            else:
                with self._lock:
                    self._latest, self._taken = readings, time.monotonic()
            self._stop.wait(self._interval)
