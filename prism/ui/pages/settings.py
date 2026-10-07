from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QVBoxLayout, QWidget

from ...domain.errors import PrismError
from ...domain.settings import Settings
from ...ports import DetectorSwitch
from ...services.core import PrismState
from ..client import PrismClient
from ..widgets.basics import Card, Toggle, button, label
from .base import Page


@dataclass(frozen=True)
class Binding[T]:
    """Ties a control to one setting: how to read it, and how to make settings with a new value.

    @ivar read: gets the value from the settings.
    @ivar write: makes new settings holding a value.
    """

    read: Callable[[Settings], T]
    write: Callable[[Settings, T], Settings]


@dataclass(frozen=True)
class Range:
    low: int
    high: int
    suffix: str


def setting_row(title: str, detail: str, control: QWidget) -> QHBoxLayout:
    """Lay out a setting: its name and explanation on the left, its control on the right.

    @param title: the setting's name.
    @param detail: what it does, in a sentence.
    @param control: the toggle or box that changes it.
    @return: the row.
    """
    row = QHBoxLayout()
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    explanation = label(detail, "faint")
    explanation.setWordWrap(True)
    text.addWidget(explanation)
    row.addLayout(text, 1)
    row.addWidget(control)
    return row


def channel_binding(channel: int) -> Binding[int]:
    """@return: a binding to the LED count on one Commander Pro channel."""
    return Binding(
        read=lambda settings: settings.channel_leds.get(channel, 0),
        write=lambda settings, count: replace(
            settings, channel_leds={**settings.channel_leds, channel: count}
        ),
    )


class SettingsPage(Page):
    """Preferences: login, lighting, fan safety limits and hardware layout."""

    def __init__(self, client: PrismClient, detectors: DetectorSwitch) -> None:
        super().__init__("Settings", "How Prism starts, draws and keeps your fans safe.")
        self._client = client
        self._detectors = detectors
        self._toggles: list[tuple[Toggle, Binding[bool]]] = []
        self._spins: list[tuple[QSpinBox, Binding[int]]] = []

        general = Card("General")
        self._autostart = Toggle()
        self._autostart.toggled.connect(self._client.set_autostart)
        general.body.addLayout(
            setting_row("Start at login", "Prism starts hidden in the tray.", self._autostart)
        )
        general.body.addLayout(
            self._toggle_row(
                "Start hidden",
                "Open to the tray, not the window.",
                Binding(lambda s: s.start_hidden, lambda s, on: replace(s, start_hidden=on)),
            )
        )
        self.body.addWidget(general)

        lighting = Card("Lighting")
        lighting.body.addLayout(
            self._toggle_row(
                "Let devices play effects themselves",
                "Effects keep running after Prism closes. Turn off to have Prism draw everything in sync.",
                Binding(lambda s: s.prefer_hardware, lambda s, on: replace(s, prefer_hardware=on)),
            )
        )
        lighting.body.addLayout(
            self._spin_row(
                "Animation smoothness",
                "Frames per second for effects Prism draws.",
                Binding(lambda s: s.frame_rate, lambda s, value: replace(s, frame_rate=value)),
                Range(5, 60, " fps"),
            )
        )
        self.body.addWidget(lighting)

        cooling = Card("Fan safety")
        cooling.body.addLayout(
            self._spin_row(
                "Lowest fan speed",
                "No curve can take a fan below this.",
                Binding(lambda s: s.fan_floor, lambda s, value: replace(s, fan_floor=value)),
                Range(0, 60, " %"),
            )
        )
        cooling.body.addLayout(
            self._spin_row(
                "Speed when Prism closes",
                "Fans hold this until Prism runs again.",
                Binding(lambda s: s.handoff_duty, lambda s, value: replace(s, handoff_duty=value)),
                Range(0, 100, " %"),
            )
        )
        self.body.addWidget(cooling)
        self.body.addWidget(self._hardware_card())
        self.body.addStretch()

    def _hardware_card(self) -> Card:
        """@return: the card for LED layout and OpenRGB."""
        hardware = Card("Hardware")
        leds = Range(0, 204, " LEDs")
        hardware.body.addLayout(
            self._spin_row(
                "Commander Pro channel 1",
                "12 per Corsair RGB fan, so 72 for six fans.",
                channel_binding(1),
                leds,
            )
        )
        hardware.body.addLayout(
            self._spin_row("Commander Pro channel 2", "0 if nothing is plugged in.", channel_binding(2), leds)
        )
        hardware.body.addLayout(
            self._toggle_row(
                "Start OpenRGB when needed",
                "Runs a hidden OpenRGB server for the RAM and GPU lighting.",
                Binding(lambda s: s.launch_openrgb, lambda s, on: replace(s, launch_openrgb=on)),
            )
        )
        self._detector_button = button("Hide them", self._hide_corsair)
        hardware.body.addLayout(
            setting_row(
                "Keep OpenRGB away from Corsair devices",
                "Prism drives the Commander Pro and the AIO itself; OpenRGB detecting them resets them.",
                self._detector_button,
            )
        )
        if self._detectors.is_off():
            self._mark_hidden()
        hardware.body.addWidget(label("Hardware changes take effect the next time Prism starts.", "faint"))
        return hardware

    def refresh(self, state: PrismState) -> None:
        """@param state: the latest state."""
        self._autostart.set_on(state.autostart)
        for toggle, binding in self._toggles:
            toggle.set_on(binding.read(state.settings))
        for spin, spin_binding in self._spins:
            if not spin.hasFocus():
                spin.blockSignals(True)
                spin.setValue(spin_binding.read(state.settings))
                spin.blockSignals(False)

    def _toggle_row(self, title: str, detail: str, binding: Binding[bool]) -> QHBoxLayout:
        """@return: a row with a switch bound to a setting."""
        toggle = Toggle()
        toggle.toggled.connect(
            lambda on: self._client.update_settings(lambda settings: binding.write(settings, on))
        )
        self._toggles.append((toggle, binding))
        return setting_row(title, detail, toggle)

    def _spin_row(self, title: str, detail: str, binding: Binding[int], limits: Range) -> QHBoxLayout:
        """@return: a row with a number box bound to a setting."""
        spin = QSpinBox()
        spin.setRange(limits.low, limits.high)
        spin.setSuffix(limits.suffix)
        spin.setFixedWidth(120)
        spin.editingFinished.connect(
            lambda: self._client.update_settings(lambda settings: binding.write(settings, spin.value()))
        )
        self._spins.append((spin, binding))
        return setting_row(title, detail, spin)

    def _hide_corsair(self) -> None:
        """Switch off OpenRGB's Corsair detectors and say how it went."""
        try:
            self._detectors.turn_off()
        except PrismError as error:
            self._client.notify(str(error))
            return
        self._client.notify("OpenRGB will leave the Corsair devices alone from its next start")
        self._mark_hidden()

    def _mark_hidden(self) -> None:
        """Show that OpenRGB already leaves the Corsair devices alone."""
        self._detector_button.setEnabled(False)
        self._detector_button.setText("Done")
