from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from prism.domain.errors import DeviceError
from prism.infrastructure.process import SubprocessRunner
from prism.infrastructure.sensors import CpuSensors, NvidiaSensors, PsutilProcesses, _exe_names


class Runner:
    def __init__(self, output: str | None) -> None:
        self.output = output

    def run(self, args: Sequence[str], timeout: float = 5.0) -> str:
        if self.output is None:
            raise DeviceError("missing")
        return self.output


def probes(**chips: list[tuple[str, float]]) -> Any:
    readings = {
        chip: [SimpleNamespace(label=label, current=value) for label, value in entries]
        for chip, entries in chips.items()
    }
    return lambda: readings


def test_cpu_reads_package_temperature_and_load() -> None:
    sensors = CpuSensors(probes(coretemp=[("Core 0", 30.0), ("Package id 0", 35.0)]), lambda _: 12.5)
    assert sensors.read() == {"cpu.load": 12.5, "cpu.temp": 35.0}
    assert [sensor.id for sensor in sensors.sensors()] == ["cpu.temp", "cpu.load"]


def test_cpu_falls_back_to_amd_probes_and_tolerates_none() -> None:
    assert CpuSensors(probes(k10temp=[("Tctl", 50.0)]), lambda _: 0.0).read()["cpu.temp"] == 50.0
    assert "cpu.temp" not in CpuSensors(probes(), lambda _: 0.0).read()


def test_nvidia_parses_the_first_gpu() -> None:
    assert NvidiaSensors(Runner("55, 7\n60, 9\n")).read() == {"gpu.temp": 55.0, "gpu.load": 7.0}
    assert NvidiaSensors(Runner(None)).read() == {}
    assert NvidiaSensors(Runner("garbage")).read() == {}
    assert len(NvidiaSensors(Runner("")).sensors()) == 2


def test_exe_names_come_from_wine_command_lines() -> None:
    cmdline = ["wine", "C:\\Program Files\\World of Warcraft\\Wow.exe", "-d3d11", "/x/Launcher.EXE"]
    assert _exe_names(cmdline) == {"wow.exe", "launcher.exe"}


def test_processes_include_this_python() -> None:
    assert any(name.startswith("python") for name in PsutilProcesses().running())


def test_runner_returns_output_and_wraps_failures() -> None:
    assert SubprocessRunner().run(["echo", "hi"]) == "hi\n"
    with pytest.raises(DeviceError):
        SubprocessRunner().run(["false"])
    with pytest.raises(DeviceError):
        SubprocessRunner().run(["prism-no-such-program"])
