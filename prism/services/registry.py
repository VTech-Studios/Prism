from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ..domain.devices import DeviceStatus, FanChannel, LightingZone
from ..domain.errors import PrismError
from ..ports import Device, FanDevice, LightingDevice, PumpDevice, SensorSource

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Connector:
    """How to reach one device, kept so a device that drops off can be reached again.

    @ivar name: what to call the device while it is offline.
    @ivar connect: opens the device, raising DeviceError if it is not there.
    """

    name: str
    connect: Callable[[], Device]


@dataclass(slots=True)
class _Slot:
    connector: Connector
    device: Device | None = None
    error: str = "not connected yet"
    zones: list[LightingZone] = field(default_factory=list)
    fans: list[FanChannel] = field(default_factory=list)


class DeviceRegistry:
    """Keeps track of which devices are connected, what each one offers, and reconnects lost ones.

    Every change to the set of connected devices bumps the generation, so
    services can tell when to send their settings to a device that came back.
    """

    def __init__(self, connectors: Sequence[Connector]) -> None:
        self._slots = [_Slot(connector) for connector in connectors]
        self.generation = 0

    def connect_offline(self) -> None:
        """Try every device that is not connected, leaving the rest alone."""
        for slot in self._slots:
            if slot.device is None:
                self._connect(slot)

    def fail(self, device: Device, error: PrismError) -> None:
        """Take a device offline after it stopped responding, so it is retried later.

        @param device: the device.
        @param error: what went wrong, shown on the dashboard.
        """
        for slot in self._slots:
            if slot.device is device:
                _LOG.warning("%s went offline: %s", slot.connector.name, error)
                self._close(slot)
                slot.error = str(error)
                self.generation += 1

    def close(self) -> None:
        """Release every device."""
        for slot in self._slots:
            if slot.device is not None:
                self._close(slot)

    def zones(self) -> list[LightingZone]:
        """@return: every lighting zone on every connected device."""
        return [zone for slot in self._slots for zone in slot.zones]

    def fans(self) -> list[FanChannel]:
        """@return: every fan on every connected device."""
        return [fan for slot in self._slots for fan in slot.fans]

    def lighting_for(self, zone_id: str) -> LightingDevice | None:
        """@return: the connected device that owns a zone, or None."""
        for slot in self._slots:
            if isinstance(slot.device, LightingDevice) and any(zone.id == zone_id for zone in slot.zones):
                return slot.device
        return None

    def fans_for(self, fan_id: str) -> FanDevice | None:
        """@return: the connected device that drives a fan, or None."""
        for slot in self._slots:
            if isinstance(slot.device, FanDevice) and any(fan.id == fan_id for fan in slot.fans):
                return slot.device
        return None

    def fan_devices(self) -> list[FanDevice]:
        """@return: every connected device with fans."""
        return [slot.device for slot in self._slots if isinstance(slot.device, FanDevice)]

    def pumps(self) -> list[PumpDevice]:
        """@return: every connected AIO pump."""
        return [slot.device for slot in self._slots if isinstance(slot.device, PumpDevice)]

    def sensor_sources(self) -> list[SensorSource]:
        """@return: every connected device that also reports sensors, such as coolant temperature."""
        sources: list[SensorSource] = []
        for slot in self._slots:
            if isinstance(slot.device, SensorSource):
                sources.append(slot.device)
        return sources

    def statuses(self) -> list[DeviceStatus]:
        """@return: one line per device for the dashboard."""
        return [
            DeviceStatus(slot.device.name, True, self._summary(slot))
            if slot.device
            else DeviceStatus(slot.connector.name, False, slot.error)
            for slot in self._slots
        ]

    def _connect(self, slot: _Slot) -> None:
        """Open one device and record what it offers.

        @param slot: the device's slot.
        """
        try:
            device = slot.connector.connect()
            zones = list(device.zones()) if isinstance(device, LightingDevice) else []
            fans = list(device.fans()) if isinstance(device, FanDevice) else []
        except PrismError as error:
            slot.error = str(error)
            return
        slot.device, slot.zones, slot.fans, slot.error = device, zones, fans, ""
        self.generation += 1
        _LOG.info("%s connected", device.name)

    @staticmethod
    def _close(slot: _Slot) -> None:
        """Release a device, ignoring failures since it may already be gone.

        @param slot: the device's slot.
        """
        try:
            if slot.device is not None:
                slot.device.close()
        except (PrismError, OSError) as error:
            _LOG.debug("closing %s failed: %s", slot.connector.name, error)
        slot.device, slot.zones, slot.fans = None, [], []

    @staticmethod
    def _summary(slot: _Slot) -> str:
        """@return: what the device offers, such as "1 lighting zone, 4 fans"."""
        parts = []
        if slot.zones:
            parts.append(f"{len(slot.zones)} lighting zone{'s' if len(slot.zones) != 1 else ''}")
        if slot.fans:
            parts.append(f"{len(slot.fans)} fan{'s' if len(slot.fans) != 1 else ''}")
        return ", ".join(parts) or "connected"
