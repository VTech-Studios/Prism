from __future__ import annotations

from typing import Any

import hid

from ..domain.errors import DeviceError

_TIMEOUT_MS = 500


class HidapiTransport:
    """Talks to a USB HID device through hidraw, alongside any kernel driver bound to it.

    hidapi's hidraw backend is used so the kernel's own driver, and with it
    the hwmon fan readings, keep working while Prism has the device open.
    """

    def __init__(self, vendor: int, product: int, report_size: int) -> None:
        """@raise DeviceError: if no such device is plugged in or it cannot be opened."""
        matches = hid.enumerate(vendor, product)
        if not matches:
            raise DeviceError(f"no USB device {vendor:04x}:{product:04x} is connected")
        self._report_size = report_size
        self._device: Any = hid.device()
        try:
            self._device.open_path(matches[0]["path"])
        except OSError as error:
            raise DeviceError(f"cannot open {vendor:04x}:{product:04x}: {error}") from error

    def exchange(self, report: bytes, reply_size: int) -> bytes:
        """Send one report and wait for the device's reply.

        Replies left over from earlier commands are discarded first, so the
        reply returned always belongs to this report.

        @param report: the report, without the leading report id.
        @param reply_size: the length of the reply.
        @return: the reply.
        @raise DeviceError: if the device is gone or does not answer.
        """
        try:
            self._discard_queued()
            self._device.write(bytes([0]) + report.ljust(self._report_size, b"\x00"))
            reply = bytes(self._device.read(reply_size, _TIMEOUT_MS))
        except (OSError, ValueError) as error:
            raise DeviceError(f"the device stopped responding: {error}") from error
        if not reply:
            raise DeviceError("the device did not answer in time")
        return reply

    def close(self) -> None:
        """Release the device."""
        self._device.close()

    def _discard_queued(self) -> None:
        """Drain replies the kernel queued while nobody was reading."""
        self._device.set_nonblocking(True)
        while self._device.read(self._report_size):
            pass
        self._device.set_nonblocking(False)
