from __future__ import annotations

import re
from pathlib import Path

HWMON_ROOT = Path("/sys/class/hwmon")

_FAN_LABEL = re.compile(r"fan(\d+)_label")


def find_hwmon(name: str, root: Path = HWMON_ROOT) -> Path | None:
    """Find the hwmon directory a kernel driver registered.

    @param name: the driver's hwmon name, such as "corsaircpro".
    @param root: where hwmon devices are listed.
    @return: the directory, or None if the driver is not loaded.
    """
    for directory in sorted(root.glob("hwmon*")):
        name_file = directory / "name"
        if name_file.is_file() and name_file.read_text().strip() == name:
            return directory
    return None


class HwmonFans:
    """Reads fan speeds the kernel already polls, so Prism never competes with it for the device."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def connected(self) -> list[int]:
        """List the fan headers with a fan on them.

        The kernel only labels headers that have a fan plugged in.

        @return: the header numbers, counting from 1.
        """
        found = (_FAN_LABEL.fullmatch(path.name) for path in self._directory.glob("fan*_label"))
        return sorted(int(match.group(1)) for match in found if match)

    def rpm(self, header: int) -> int | None:
        """Read one fan's speed.

        @param header: the header number, counting from 1.
        @return: the speed in RPM, or None if it could not be read.
        """
        try:
            return int((self._directory / f"fan{header}_input").read_text().strip())
        except (OSError, ValueError):
            return None
