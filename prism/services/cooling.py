from __future__ import annotations

from collections.abc import Mapping

from ..domain.cooling import FanSetting, PumpMode
from ..domain.errors import DeviceError
from .registry import DeviceRegistry

FAILSAFE_DUTY = 80
STEP_DOWN = 4
KEEPALIVE = 30.0


class CoolingController:
    """Keeps every fan at the duty its setting asks for, safely.

    Fans rise at once but fall a few percent at a time, so a brief dip in
    temperature does not make them hunt up and down. A fan whose sensor stops
    reporting is run fast, because running hot silently is the worse failure.
    A fan the profile does not mention follows the fallback setting, so how a
    fan behaves never depends on which profile happened to run before.
    """

    def __init__(self, registry: DeviceRegistry, floor: int, fallback: FanSetting) -> None:
        """@param fallback: the setting for fans a profile leaves out."""
        self._registry = registry
        self._floor = floor
        self._fallback = fallback
        self._settings: dict[str, FanSetting] = {}
        self._pump: PumpMode | None = None
        self._pump_applied: PumpMode | None = None
        self._duties: dict[str, int] = {}
        self._written_at: dict[str, float] = {}

    @property
    def duties(self) -> Mapping[str, int]:
        """The duty each fan was last given, keyed by fan id."""
        return dict(self._duties)

    def set_floor(self, floor: int) -> None:
        """@param floor: the lowest duty any fan may be given."""
        self._floor = floor

    def apply(self, settings: Mapping[str, FanSetting], pump: PumpMode | None) -> None:
        """Take on a profile's cooling, replacing the last profile's.

        @param settings: the setting for each fan, keyed by fan id.
        @param pump: the pump mode, or None to leave the pump as it is.
        """
        self._settings = dict(settings)
        if pump is not None:
            self._pump = pump

    def refresh(self) -> None:
        """Forget what was sent, so everything is sent again to devices that reconnected."""
        self._duties.clear()
        self._written_at.clear()
        self._pump_applied = None

    def tick(self, readings: Mapping[str, float], now: float) -> None:
        """Move every fan towards its target duty and make sure the pump mode is set.

        Duties are resent now and then even when unchanged, in case a
        controller lost them without Prism noticing.

        @param readings: the latest sensor values.
        @param now: the monotonic time.
        """
        for fan in self._registry.fans():
            setting = self._settings.get(fan.id, self._fallback)
            target = setting.target(readings)
            floor = max(self._floor, fan.minimum_duty)
            self._drive(fan.id, max(floor, FAILSAFE_DUTY if target is None else target), now)
        self._apply_pump()

    def hand_off(self, duty: int) -> None:
        """Leave every fan at a safe fixed duty, for when nothing will be adjusting them.

        @param duty: the duty, raised to the floor if below it.
        """
        for fan in self._registry.fans():
            self._write(fan.id, max(duty, self._floor, fan.minimum_duty), 0.0)

    def _drive(self, fan_id: str, target: int, now: float) -> None:
        """Step a fan towards its target, rising at once and falling slowly.

        @param fan_id: the fan.
        @param target: the duty it should end up at.
        @param now: the monotonic time.
        """
        current = self._duties.get(fan_id)
        duty = target if current is None or target >= current else max(target, current - STEP_DOWN)
        stale = now - self._written_at.get(fan_id, now) >= KEEPALIVE
        if duty != current or stale:
            self._write(fan_id, duty, now)

    def _write(self, fan_id: str, duty: int, now: float) -> None:
        """Send a duty, taking the device offline if it does not answer.

        @param fan_id: the fan.
        @param duty: the duty.
        @param now: the monotonic time.
        """
        device = self._registry.fans_for(fan_id)
        if device is None:
            return
        try:
            device.set_duty(fan_id, duty)
        except DeviceError as error:
            self._registry.fail(device, error)
            return
        self._duties[fan_id] = duty
        self._written_at[fan_id] = now

    def _apply_pump(self) -> None:
        """Send the pump mode once per change or reconnect."""
        if self._pump is None or self._pump is self._pump_applied:
            return
        for pump in self._registry.pumps():
            try:
                pump.set_pump(self._pump)
            except DeviceError as error:
                self._registry.fail(pump, error)
                return
        self._pump_applied = self._pump
