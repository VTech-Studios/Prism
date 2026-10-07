from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...domain.color import Color
from ...domain.devices import LightingZone
from ...domain.effects import Direction, Effect, EffectKind, Gauge, Speed
from ...domain.rendering import Renderer
from ...services.state import PrismState
from ..client import PrismClient
from ..theme import Palette
from ..widgets.basics import Card, CommitSlider, Segmented, Swatch, button, fill_combo, label
from ..widgets.charts import LedPreview
from .base import Page, clear, sensor_name

PALETTE = (Color.from_hex("#8b5cf6"), Color.from_hex("#22d3ee"), Color.from_hex("#ff2800"))
CHIP_COLUMNS = 3


class ZoneCard(QFrame):
    """A selectable card naming a lighting zone and who is playing its effect."""

    clicked = Signal(str)

    def __init__(self, zone: LightingZone) -> None:
        super().__init__()
        self.zone_id = zone.id
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.setSpacing(4)
        layout.addWidget(label(zone.name))
        layout.addWidget(label(f"{zone.device}  ·  {zone.led_count} LEDs", "faint"))
        self._badge = label("", "pill")
        layout.addWidget(self._badge)

    def set_selected(self, selected: bool) -> None:
        """@param selected: whether this is the zone being edited."""
        self.setObjectName("cardSelected" if selected else "card")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_badge(self, text: str) -> None:
        """@param text: who plays the effect, or that the zone is untouched."""
        self._badge.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Select this zone."""
        self.clicked.emit(self.zone_id)


class EffectEditor(Card):
    """Edits one zone's effect: kind, colours, speed, direction, brightness and sensor."""

    edited = Signal(object)

    def __init__(self, renderer: Renderer) -> None:
        super().__init__("Effect")
        self._zone: LightingZone | None = None
        self._effect: Effect | None = None
        self._readings: dict[str, float] = {}

        self._preview = LedPreview(renderer)
        self.body.addWidget(self._preview)

        self._chips = QGridLayout()
        self._chips.setSpacing(8)
        self.body.addLayout(self._chips)
        self._chip_buttons: dict[EffectKind, QPushButton] = {}

        self._colors_row = QHBoxLayout()
        self._colors_row.setSpacing(10)
        self._colors_box = self._labelled("Colours", self._colors_row)

        self._speed = Segmented([(speed.value.title(), speed) for speed in Speed])
        self._speed.changed.connect(lambda speed: self._emit(replace(self._current(), speed=speed)))
        self._speed_box = self._labelled("Speed", self._speed)

        self._direction = Segmented([("Forward", Direction.FORWARD), ("Backward", Direction.BACKWARD)])
        self._direction.changed.connect(
            lambda direction: self._emit(replace(self._current(), direction=direction))
        )
        self._direction_box = self._labelled("Direction", self._direction)

        self._brightness = CommitSlider(5, 100)
        self._brightness.valueChanged.connect(self._preview_brightness)
        self._brightness.committed.connect(self._commit_brightness)
        self._brightness_box = self._labelled("Brightness", self._brightness)

        gauge_row = QHBoxLayout()
        self._sensor = QComboBox()
        self._cool = self._degrees()
        self._hot = self._degrees()
        self._sensor.activated.connect(lambda _: self._commit_gauge())
        self._cool.editingFinished.connect(self._commit_gauge)
        self._hot.editingFinished.connect(self._commit_gauge)
        gauge_row.addWidget(self._sensor, 2)
        gauge_row.addWidget(label("cool at", "dim"))
        gauge_row.addWidget(self._cool)
        gauge_row.addWidget(label("hot at", "dim"))
        gauge_row.addWidget(self._hot)
        self._gauge_box = self._labelled("Follows", gauge_row)

    def show_zone(self, zone: LightingZone, effect: Effect | None, state: PrismState) -> None:
        """Load a zone into the editor without emitting edits.

        @param zone: the zone.
        @param effect: its effect in the chosen profile, or None if the profile leaves it alone.
        @param state: the latest state, for sensors and readings.
        """
        if self._zone != zone:
            self._zone = zone
            self._build_chips(zone)
        self._effect = effect
        self._readings = dict(state.readings)
        if effect is not None and self._brightness.busy():
            effect = replace(effect, brightness=self._brightness.value() / 100)
        self._preview.show_effect(effect, zone.led_count, self._readings)
        for kind, chip in self._chip_buttons.items():
            chip.setChecked(effect is not None and effect.kind is kind)
        self._show_controls(effect, state)

    def _show_controls(self, effect: Effect | None, state: PrismState) -> None:
        """Show only the controls the effect uses, set to its values.

        @param effect: the effect, or None.
        @param state: the latest state.
        """
        kind = effect.kind if effect else None
        self._colors_box.setVisible(bool(kind and kind.color_slots[1]))
        self._speed_box.setVisible(bool(kind and kind.animated))
        self._direction_box.setVisible(bool(kind and kind.animated))
        self._brightness_box.setVisible(kind not in (None, EffectKind.OFF))
        self._gauge_box.setVisible(kind is EffectKind.TEMPERATURE)
        if effect is None:
            return
        self._rebuild_swatches(effect)
        self._speed.set_value(effect.speed)
        self._direction.set_value(effect.direction)
        self._brightness.set_quietly(round(effect.brightness * 100))
        if effect.gauge:
            self._show_gauge(effect.gauge, state)

    def _show_gauge(self, gauge: Gauge, state: PrismState) -> None:
        """@param gauge: the gauge to show. @param state: the latest state, for sensor names."""
        temperatures = [sensor for sensor in state.sensors if sensor.unit == "°C"]
        ids = [sensor.id for sensor in temperatures]
        if gauge.sensor not in ids:
            ids.append(gauge.sensor)
        fill_combo(
            self._sensor, [(sensor_name(state, sensor_id), sensor_id) for sensor_id in ids], gauge.sensor
        )
        for spin, value in ((self._cool, gauge.cool), (self._hot, gauge.hot)):
            if not spin.hasFocus():
                spin.setValue(value)

    def _build_chips(self, zone: LightingZone) -> None:
        """@param zone: the zone whose supported effects become chips."""
        clear(self._chips)
        self._chip_buttons = {}
        for index, kind in enumerate(zone.effects):
            chip = QPushButton(kind.label)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, kind=kind: self._choose(kind))
            self._chip_buttons[kind] = chip
            self._chips.addWidget(chip, index // CHIP_COLUMNS, index % CHIP_COLUMNS)

    def _rebuild_swatches(self, effect: Effect) -> None:
        """@param effect: the effect whose colours become swatches."""
        if self._colors_row.count() == len(effect.colors):
            for index, color in enumerate(effect.colors):
                item = self._colors_row.itemAt(index)
                swatch = item.widget() if item else None
                if isinstance(swatch, Swatch):
                    swatch.set_color(color)
            return
        clear(self._colors_row)
        for index, color in enumerate(effect.colors):
            swatch = Swatch(color)
            swatch.picked.connect(
                lambda picked, index=index: self._emit(self._current().with_color(index, picked))
            )
            self._colors_row.addWidget(swatch)

    def _choose(self, kind: EffectKind) -> None:
        """@param kind: the effect chip clicked."""
        base = self._effect or Effect.static(PALETTE[0])
        self._emit(base.with_kind(kind, PALETTE))

    def _preview_brightness(self, value: int) -> None:
        """Show the new brightness in the preview while dragging, before it is saved."""
        if self._effect is not None and self._zone is not None:
            preview = replace(self._effect, brightness=value / 100)
            self._preview.show_effect(preview, self._zone.led_count, self._readings)

    def _commit_brightness(self, value: int) -> None:
        """@param value: the brightness the user settled on, in percent."""
        self._emit(replace(self._current(), brightness=value / 100))

    def _commit_gauge(self) -> None:
        """Save the sensor and range, ignoring a range that is the wrong way round."""
        sensor = self._sensor.currentData()
        if sensor and self._hot.value() > self._cool.value():
            self._emit(replace(self._current(), gauge=Gauge(sensor, self._cool.value(), self._hot.value())))

    def _current(self) -> Effect:
        """@return: the effect being edited, or a starting point if the zone has none."""
        return self._effect or Effect.static(PALETTE[0])

    def flush(self) -> None:
        """Save any slider change still settling, before the selection moves on."""
        self._brightness.flush()

    def _emit(self, effect: Effect) -> None:
        """Show an edit at once and report it.

        @param effect: the edited effect.
        """
        self._effect = effect
        if self._zone is not None:
            self._preview.show_effect(effect, self._zone.led_count, self._readings)
        self.edited.emit(effect)

    def _labelled(self, caption: str, content: QWidget | QHBoxLayout) -> QWidget:
        """Put a caption above a control, so the pair can be hidden together.

        @param caption: the caption.
        @param content: the control or row of controls.
        @return: the pair.
        """
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label(caption, "dim"))
        if isinstance(content, QWidget):
            layout.addWidget(content)
        else:
            layout.addLayout(content)
        self.body.addWidget(box)
        return box

    @staticmethod
    def _degrees() -> QDoubleSpinBox:
        """@return: a spin box for a temperature."""
        spin = QDoubleSpinBox()
        spin.setRange(0, 110)
        spin.setDecimals(0)
        spin.setSuffix(" °C")
        return spin


class LightingPage(Page):
    """Pick a zone on the left, shape its effect on the right; changes show on the hardware at once."""

    def __init__(self, client: PrismClient, renderer: Renderer, palette: Palette) -> None:
        super().__init__("Lighting", "Effects for every lighting zone, saved into the chosen profile.")
        self._client = client
        self._palette = palette
        self._selected: str | None = None
        self._zones_key: tuple[LightingZone, ...] = ()
        self._cards: dict[str, ZoneCard] = {}
        self._state: PrismState | None = None

        self._banner = label("", "banner")
        self._banner.setWordWrap(True)
        self.body.addWidget(self._banner)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        self._zone_list = QVBoxLayout()
        self._zone_list.setSpacing(10)
        left = QWidget()
        left.setLayout(self._zone_list)
        left.setFixedWidth(300)
        columns.addWidget(left, alignment=Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        self._editor = EffectEditor(renderer)
        self._editor.edited.connect(self._edited)
        right.addWidget(self._editor)
        actions = QHBoxLayout()
        actions.addWidget(button("Use on every zone", self._apply_everywhere))
        actions.addWidget(button("Leave this zone alone", self._unset))
        actions.addStretch()
        right.addLayout(actions)
        right.addStretch()
        columns.addLayout(right, 1)
        self.body.addLayout(columns)
        self._empty = label(
            "No lighting is connected yet. Check the dashboard for devices that are offline.", "dim"
        )
        self.body.addWidget(self._empty)
        self.body.addStretch()

    def refresh(self, state: PrismState) -> None:
        """@param state: the latest state."""
        self._state = state
        if state.zones != self._zones_key:
            self._zones_key = state.zones
            self._rebuild_list(state)
        self._empty.setVisible(not state.zones)
        self._editor.setVisible(bool(state.zones))
        self._banner.setVisible(state.showing != state.chosen)
        self._banner.setText(
            f"The rule “{state.rule}” is showing {state.showing}. "
            f"Edits here change {state.chosen}, which shows again when the rule ends."
        )
        profile = state.profile(state.chosen)
        for zone_id, card in self._cards.items():
            effect = profile.lighting.get(zone_id) if profile else None
            card.set_badge(self._badge(state, zone_id, effect))
        zone = next((zone for zone in state.zones if zone.id == self._selected), None)
        if zone is not None:
            self._editor.show_zone(zone, profile.lighting.get(zone.id) if profile else None, state)

    @staticmethod
    def _badge(state: PrismState, zone_id: str, effect: Effect | None) -> str:
        """@return: a short note on the zone's effect and who plays it."""
        if effect is None:
            return "Untouched"
        who = "Prism" if zone_id in state.drawn else "Device"
        return f"{effect.kind.label} · {who}"

    def _rebuild_list(self, state: PrismState) -> None:
        """@param state: the latest state, whose zones become cards."""
        clear(self._zone_list)
        self._cards = {}
        for zone in state.zones:
            card = ZoneCard(zone)
            card.clicked.connect(self._select)
            self._cards[zone.id] = card
            self._zone_list.addWidget(card)
        if self._selected not in self._cards:
            self._selected = state.zones[0].id if state.zones else None
        self._mark_selected()

    def _select(self, zone_id: str) -> None:
        """@param zone_id: the zone clicked."""
        self._editor.flush()
        self._selected = zone_id
        self._mark_selected()
        if self._state is not None:
            self.refresh(self._state)

    def _mark_selected(self) -> None:
        """Highlight the selected zone's card."""
        for zone_id, card in self._cards.items():
            card.set_selected(zone_id == self._selected)

    def _edited(self, effect: Effect) -> None:
        """@param effect: the selected zone's new effect."""
        zone_id = self._selected
        if zone_id is not None:
            self._client.edit_chosen(lambda profile: profile.with_effect(zone_id, effect))

    def _apply_everywhere(self) -> None:
        """Give every zone that supports it the selected zone's effect, like iCUE's lighting link."""
        state = self._client.state
        profile = state.profile(state.chosen) if state else None
        effect = profile.lighting.get(self._selected or "") if profile else None
        if state is None or effect is None:
            return
        zone_ids = [zone.id for zone in state.zones if zone.supports(effect.kind)]
        self._client.edit_chosen(lambda current: current.with_effect_everywhere(zone_ids, effect))

    def _unset(self) -> None:
        """Remove the selected zone from the profile, so switching to it leaves the zone as it is."""
        zone_id = self._selected
        if zone_id is not None:
            self._client.edit_chosen(
                lambda profile: replace(
                    profile,
                    lighting={key: value for key, value in profile.lighting.items() if key != zone_id},
                )
            )
