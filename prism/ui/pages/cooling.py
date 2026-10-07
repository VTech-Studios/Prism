from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ...domain.cooling import PRESET_CURVES, FanCurve, FanMode, FanSetting, PumpMode
from ...domain.devices import FanChannel
from ...services.core import PrismState
from ...services.presets import LIQUID_CURVES
from ..client import PrismClient
from ..theme import Palette
from ..widgets.basics import Card, Segmented, button, label
from ..widgets.charts import CurveEditor
from .base import Page, clear, sensor_name, sensor_unit

CUSTOM = "Custom"
FAN_COLUMNS = 3


class FanCard(QFrame):
    """A selectable card with a fan's live speed and its setting at a glance."""

    clicked = Signal(str)

    def __init__(self, fan: FanChannel) -> None:
        super().__init__()
        self.fan_id = fan.id
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(label(fan.name))
        layout.addWidget(label(fan.device, "faint"))
        self._speed = label("", "big")
        self._detail = label("", "dim")
        layout.addWidget(self._speed)
        layout.addWidget(self._detail)

    def set_selected(self, selected: bool) -> None:
        """@param selected: whether this is the fan being edited."""
        self.setObjectName("cardSelected" if selected else "card")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_values(self, rpm: int | None, duty: int | None, setting: FanSetting | None) -> None:
        """@param rpm: measured speed. @param duty: duty last set. @param setting: its setting, if any."""
        self._speed.setText(f"{rpm}" if rpm is not None else "--")
        what = (
            "Untouched"
            if setting is None
            else f"Fixed {setting.duty}%"
            if setting.mode is FanMode.FIXED
            else "Curve"
        )
        self._detail.setText(f"RPM  ·  {what}" + (f"  ·  now {duty}%" if duty is not None else ""))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Select this fan."""
        self.clicked.emit(self.fan_id)


def preset_name(curve: FanCurve | None) -> str:
    """@return: the preset the curve matches, or Custom."""
    for presets in (PRESET_CURVES, LIQUID_CURVES):
        for name, preset in presets.items():
            if preset == curve:
                return name
    return CUSTOM


class FanEditor(Card):
    """Edits one fan's setting: a fixed duty, or a curve following a sensor."""

    edited = Signal(object)

    def __init__(self, palette: Palette) -> None:
        super().__init__("Fan speed")
        self._setting = FanSetting.fixed(50)
        self._mode = Segmented([("Fixed speed", FanMode.FIXED), ("Follow a sensor", FanMode.CURVE)])
        self._mode.changed.connect(self._change_mode)
        self.body.addWidget(self._mode)

        self._fixed = QWidget()
        fixed_row = QHBoxLayout(self._fixed)
        fixed_row.setContentsMargins(0, 8, 0, 0)
        self._duty = QSlider(Qt.Orientation.Horizontal)
        self._duty.setRange(0, 100)
        self._duty_label = label("", "big")
        self._duty_label.setMinimumWidth(90)
        self._duty.valueChanged.connect(lambda value: self._duty_label.setText(f"{value}%"))
        self._duty.sliderReleased.connect(lambda: self._emit(replace(self._setting, duty=self._duty.value())))
        fixed_row.addWidget(self._duty, 1)
        fixed_row.addWidget(self._duty_label)
        self.body.addWidget(self._fixed)

        self._curve_box = QWidget()
        curve_layout = QVBoxLayout(self._curve_box)
        curve_layout.setContentsMargins(0, 8, 0, 0)
        pickers = QHBoxLayout()
        self._sensor = QComboBox()
        self._preset = QComboBox()
        self._sensor.activated.connect(
            lambda _: self._emit(replace(self._setting, sensor=self._sensor.currentData()))
        )
        self._preset.activated.connect(lambda _: self._pick_preset())
        pickers.addWidget(label("Sensor", "dim"))
        pickers.addWidget(self._sensor, 2)
        pickers.addWidget(label("Preset", "dim"))
        pickers.addWidget(self._preset, 1)
        curve_layout.addLayout(pickers)
        self._chart = CurveEditor(palette)
        self._chart.curveChanged.connect(lambda curve: self._emit(replace(self._setting, curve=curve)))
        curve_layout.addWidget(self._chart)
        curve_layout.addWidget(label("Drag the points to shape the curve.", "faint"))
        self.body.addWidget(self._curve_box)

    def show_setting(self, setting: FanSetting | None, state: PrismState) -> None:
        """Load a fan's setting without emitting edits.

        @param setting: the setting, or None if the profile leaves the fan alone.
        @param state: the latest state, for sensors and readings.
        """
        self._setting = setting or FanSetting.fixed(50)
        self._mode.set_value(self._setting.mode if setting else None)
        self._fixed.setVisible(setting is not None and setting.mode is FanMode.FIXED)
        self._curve_box.setVisible(setting is not None and setting.mode is FanMode.CURVE)
        if not self._duty.isSliderDown():
            self._duty.setValue(self._setting.duty)
        self._show_sensors(state)
        self._show_presets()
        if self._setting.curve is not None:
            sensor = self._setting.sensor
            self._chart.set_curve(self._setting.curve, state.readings.get(sensor), sensor_unit(state, sensor))

    def _show_sensors(self, state: PrismState) -> None:
        """@param state: the latest state, whose temperature sensors fill the picker."""
        ids = [sensor.id for sensor in state.sensors if sensor.unit == "°C"]
        if self._setting.sensor not in ids:
            ids.append(self._setting.sensor)
        self._sensor.blockSignals(True)
        self._sensor.clear()
        for sensor_id in ids:
            self._sensor.addItem(sensor_name(state, sensor_id), sensor_id)
        self._sensor.setCurrentIndex(ids.index(self._setting.sensor))
        self._sensor.blockSignals(False)

    def _show_presets(self) -> None:
        """Offer the coolant presets for the coolant sensor and the CPU ones otherwise."""
        presets = LIQUID_CURVES if self._setting.sensor == "liquid.temp" else PRESET_CURVES
        self._preset.blockSignals(True)
        self._preset.clear()
        self._preset.addItems([*presets, CUSTOM])
        self._preset.setCurrentText(preset_name(self._setting.curve))
        self._preset.blockSignals(False)

    def _pick_preset(self) -> None:
        """Replace the curve with the chosen preset."""
        presets = LIQUID_CURVES if self._setting.sensor == "liquid.temp" else PRESET_CURVES
        curve = presets.get(self._preset.currentText())
        if curve is not None:
            self._emit(replace(self._setting, curve=curve))

    def _change_mode(self, mode: FanMode) -> None:
        """@param mode: fixed or curve."""
        if mode is FanMode.CURVE:
            curve = self._setting.curve or PRESET_CURVES["Balanced"]
            self._emit(FanSetting.following(self._setting.sensor, curve))
        else:
            self._emit(FanSetting.fixed(self._setting.duty))

    def _emit(self, setting: FanSetting) -> None:
        """@param setting: the edited setting."""
        self._setting = setting
        self.edited.emit(setting)


class CoolingPage(Page):
    """Fan speeds and pump mode for the chosen profile, with live speeds."""

    def __init__(self, client: PrismClient, palette: Palette) -> None:
        super().__init__("Cooling", "Fan curves and pump mode, saved into the chosen profile.")
        self._client = client
        self._selected: str | None = None
        self._fans_key: tuple[FanChannel, ...] = ()
        self._cards: dict[str, FanCard] = {}
        self._state: PrismState | None = None

        self._grid = QGridLayout()
        self._grid.setSpacing(12)
        self.body.addLayout(self._grid)

        self._editor = FanEditor(palette)
        self._editor.edited.connect(self._edited)
        self.body.addWidget(self._editor)
        actions = QHBoxLayout()
        actions.addWidget(button("Use on every fan", self._apply_everywhere))
        actions.addWidget(button("Leave this fan alone", self._unset))
        actions.addStretch()
        self.body.addLayout(actions)

        self._pump_card = Card("AIO pump")
        self._pump = Segmented(
            [
                ("Leave as is", None),
                ("Quiet", PumpMode.QUIET),
                ("Balanced", PumpMode.BALANCED),
                ("Extreme", PumpMode.EXTREME),
            ]
        )
        self._pump.changed.connect(
            lambda pump: self._client.edit_chosen(lambda profile: profile.with_pump(pump))
        )
        self._pump_card.body.addWidget(self._pump)
        self._pump_card.body.addWidget(
            label("Extreme keeps the coolant coolest; Quiet is best when the machine is idle.", "faint")
        )
        self.body.addWidget(self._pump_card)

        self._empty = label(
            "No fan controllers are connected. Check the dashboard for devices that are offline.", "dim"
        )
        self.body.addWidget(self._empty)
        self.body.addStretch()

    def refresh(self, state: PrismState) -> None:
        """@param state: the latest state."""
        self._state = state
        if state.fans != self._fans_key:
            self._fans_key = state.fans
            self._rebuild(state)
        profile = state.profile(state.chosen)
        cooling = profile.cooling if profile else {}
        for fan_id, card in self._cards.items():
            card.update_values(state.speeds.get(fan_id), state.duties.get(fan_id), cooling.get(fan_id))
        self._empty.setVisible(not state.fans)
        self._editor.setVisible(self._selected is not None)
        if self._selected is not None:
            self._editor.show_setting(cooling.get(self._selected), state)
        self._pump_card.setVisible(state.has_pump)
        self._pump.set_value(profile.pump if profile else None)

    def _rebuild(self, state: PrismState) -> None:
        """@param state: the latest state, whose fans become cards."""
        clear(self._grid)
        self._cards = {}
        for index, fan in enumerate(state.fans):
            card = FanCard(fan)
            card.clicked.connect(self._select)
            self._cards[fan.id] = card
            self._grid.addWidget(card, index // FAN_COLUMNS, index % FAN_COLUMNS)
        if self._selected not in self._cards:
            self._selected = state.fans[0].id if state.fans else None
        self._mark_selected()

    def _select(self, fan_id: str) -> None:
        """@param fan_id: the fan clicked."""
        self._selected = fan_id
        self._mark_selected()
        if self._state is not None:
            self.refresh(self._state)

    def _mark_selected(self) -> None:
        """Highlight the selected fan's card."""
        for fan_id, card in self._cards.items():
            card.set_selected(fan_id == self._selected)

    def _edited(self, setting: FanSetting) -> None:
        """@param setting: the selected fan's new setting."""
        fan_id = self._selected
        if fan_id is not None:
            self._client.edit_chosen(lambda profile: profile.with_fan(fan_id, setting))

    def _apply_everywhere(self) -> None:
        """Give every fan the selected fan's setting."""
        state = self._client.state
        profile = state.profile(state.chosen) if state else None
        setting = profile.cooling.get(self._selected or "") if profile else None
        if state is None or setting is None:
            return
        fan_ids = [fan.id for fan in state.fans]
        self._client.edit_chosen(
            lambda current: replace(current, cooling={**current.cooling, **dict.fromkeys(fan_ids, setting)})
        )

    def _unset(self) -> None:
        """Remove the selected fan from the profile, so it keeps whatever speed it has."""
        fan_id = self._selected
        if fan_id is not None:
            self._client.edit_chosen(
                lambda profile: replace(
                    profile, cooling={key: value for key, value in profile.cooling.items() if key != fan_id}
                )
            )
