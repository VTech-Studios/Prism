from __future__ import annotations

import time
from collections.abc import Callable

SLEEP_THRESHOLD = 2.0


def _asleep_so_far() -> float:
    """@return: seconds the machine has spent suspended since boot."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


class BootClockSleepWatch:
    """Spots a resume from suspend by comparing the boot clock with the monotonic clock.

    The monotonic clock stops while the machine sleeps and the boot clock does
    not, so the gap between them grows by exactly the time spent asleep.
    """

    def __init__(self, asleep_so_far: Callable[[], float] = _asleep_so_far) -> None:
        """@param asleep_so_far: reads the time spent suspended, swappable for tests."""
        self._asleep_so_far = asleep_so_far
        self._last = asleep_so_far()

    def woke(self) -> bool:
        """@return: True once after each suspend longer than a couple of seconds."""
        current = self._asleep_so_far()
        slept = current - self._last > SLEEP_THRESHOLD
        self._last = current
        return slept
