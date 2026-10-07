from __future__ import annotations

from collections.abc import Mapping

from ..domain.devices import LightingZone
from ..domain.effects import Effect, EffectKind
from ..domain.errors import DeviceError
from ..domain.rendering import Frame, FrameContext, Renderer
from .registry import DeviceRegistry

KEEPALIVE = 2.0


def can_play(zone: LightingZone, effect: Effect) -> bool:
    """Decide whether a device can play an effect by itself exactly as Prism would draw it.

    Effects that follow a sensor need Prism, and so do dimmed effects whose
    colours the device picks itself, since there is nothing to dim, and effects
    with more colours than the device can hold.

    @param zone: the zone.
    @param effect: the effect.
    @return: True if the device's own version is faithful.
    """
    if effect.kind not in zone.hardware_effects or effect.gauge is not None:
        return False
    if len(effect.colors) > zone.hardware_colors:
        return False
    return bool(effect.colors) or effect.brightness >= 1.0 or effect.kind is EffectKind.OFF


class LightingEngine:
    """Shows each zone's effect, either by handing it to the device or by drawing it frame by frame.

    Every drawn zone shares one clock, so effects on different devices stay in step.
    """

    def __init__(self, registry: DeviceRegistry, renderer: Renderer, prefer_hardware: bool) -> None:
        self._registry = registry
        self._renderer = renderer
        self._prefer_hardware = prefer_hardware
        self._effects: dict[str, Effect] = {}
        self._drawing: dict[str, LightingZone] = {}
        self._last_frames: dict[str, tuple[Frame, float]] = {}
        self._now = 0.0

    def show(self, effects: Mapping[str, Effect]) -> None:
        """Show a profile's effects, touching only zones whose effect changed.

        Resending an unchanged effect would restart its animation, so a fan
        curve edit or a switch between similar profiles leaves the lights alone.
        Zones without an effect keep what they have.

        @param effects: the effect for each zone, keyed by zone id.
        """
        changed = {
            zone_id: effect for zone_id, effect in effects.items() if self._effects.get(zone_id) != effect
        }
        self._effects.update(changed)
        for zone in self._registry.zones():
            if zone.id in changed:
                self._drawing.pop(zone.id, None)
                self._last_frames.pop(zone.id, None)
                self._route(zone, changed[zone.id])

    def set_prefer_hardware(self, prefer: bool) -> None:
        """Change who plays effects, and re-show everything the new way.

        @param prefer: True to let devices play effects themselves where they can.
        """
        if prefer != self._prefer_hardware:
            self._prefer_hardware = prefer
            self.refresh()

    def refresh(self) -> None:
        """Send every effect to its device again, after a reconnect or a settings change."""
        self._drawing.clear()
        self._last_frames.clear()
        for zone in self._registry.zones():
            effect = self._effects.get(zone.id)
            if effect is not None:
                self._route(zone, effect)

    def is_drawn(self, zone_id: str) -> bool:
        """@return: whether Prism draws this zone, rather than the device playing it."""
        return zone_id in self._drawing

    def tick(self, now: float, readings: Mapping[str, float]) -> None:
        """Draw the next frame on every zone Prism draws.

        Unchanged frames are only resent now and then, to keep devices that
        fall back to their own lighting when left alone from doing so.

        @param now: seconds on the shared clock.
        @param readings: the latest sensor values.
        """
        self._now = now
        context = FrameContext(now, readings)
        for zone in list(self._drawing.values()):
            frame = self._renderer.render(self._effects[zone.id], zone.led_count, context)
            last = self._last_frames.get(zone.id)
            if last is None or last[0] != frame or now - last[1] >= KEEPALIVE:
                self._send(zone, frame)

    def _route(self, zone: LightingZone, effect: Effect) -> None:
        """Hand an effect to the device, or start drawing it.

        @param zone: the zone.
        @param effect: the effect.
        """
        playable = can_play(zone, effect)
        if playable and (self._prefer_hardware or not zone.streams):
            device = self._registry.lighting_for(zone.id)
            if device is not None:
                try:
                    device.play(zone.id, effect)
                except DeviceError as error:
                    self._registry.fail(device, error)
        elif zone.streams:
            self._drawing[zone.id] = zone

    def _send(self, zone: LightingZone, frame: Frame) -> None:
        """Push one frame, taking the device offline if it does not answer.

        @param zone: the zone.
        @param frame: the colours.
        """
        device = self._registry.lighting_for(zone.id)
        if device is None:
            self._drawing.pop(zone.id, None)
            return
        try:
            device.draw(zone.id, frame)
        except DeviceError as error:
            self._registry.fail(device, error)
            self._drawing.pop(zone.id, None)
            return
        self._last_frames[zone.id] = (frame, self._now)
