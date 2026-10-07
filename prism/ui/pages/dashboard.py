from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ...domain.devices import Sensor
from ...services.core import PrismState
from ..theme import Palette
from ..widgets.basics import Card, label
from ..widgets.charts import Sparkline
from .base import Page, clear

COLUMNS = 3


class DutyBar(QWidget):
    """A thin bar showing a fan's duty, filled with the accent gradient."""

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self._palette = palette
        self._duty = 0
        self.setFixedHeight(6)

    def set_duty(self, duty: int) -> None:
        """@param duty: percent of full speed."""
        self._duty = duty
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the track and the filled share."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._palette.raised))
        painter.drawRoundedRect(self.rect(), 3, 3)
        filled = QRectF(0, 0, self.width() * self._duty / 100, self.height())
        painter.setBrush(self._palette.accent_gradient(0, 0, self.width(), 0))
        painter.drawRoundedRect(filled, 3, 3)


class SensorCard(Card):
    """One sensor's value in large type, with its recent trend underneath."""

    def __init__(self, sensor: Sensor, palette: Palette) -> None:
        super().__init__(sensor.name)
        row = QHBoxLayout()
        row.setSpacing(4)
        self._value = label("--", "big")
        row.addWidget(self._value, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addWidget(label(sensor.unit, "unit"), alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        self.body.addLayout(row)
        self._trend = Sparkline(palette)
        self.body.addWidget(self._trend)

    def add(self, value: float | None) -> None:
        """@param value: the latest reading, or None if the sensor did not report."""
        if value is None:
            self._value.setText("--")
            return
        self._value.setText(f"{value:.0f}")
        self._trend.add(value)


class FanRow(QWidget):
    """A fan's name, speed and duty."""

    def __init__(self, name: str, palette: Palette) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(name))
        top.addStretch()
        self._speed = label("", "dim")
        top.addWidget(self._speed)
        layout.addLayout(top)
        self._bar = DutyBar(palette)
        layout.addWidget(self._bar)

    def update_values(self, rpm: int | None, duty: int | None) -> None:
        """@param rpm: the measured speed. @param duty: the duty Prism last set."""
        parts = [f"{rpm} RPM" if rpm is not None else "-- RPM"]
        if duty is not None:
            parts.append(f"{duty}%")
        self._speed.setText("  ·  ".join(parts))
        self._bar.set_duty(duty or 0)


class DashboardPage(Page):
    """Live readings, fan speeds, connected devices and the profile on show."""

    always_render = True

    def __init__(self, palette: Palette) -> None:
        super().__init__("Dashboard", "Everything Prism can see, live.")
        self._palette = palette
        self._layout_key: tuple[object, ...] = ()
        self._sensor_cards: dict[str, SensorCard] = {}
        self._fan_rows: dict[str, FanRow] = {}

        self._profile_card = Card("Now showing")
        self._profile_name = label("", "big")
        self._profile_detail = label("", "dim")
        self._profile_card.body.addWidget(self._profile_name)
        self._profile_card.body.addWidget(self._profile_detail)
        self.body.addWidget(self._profile_card)

        self._sensor_grid = QGridLayout()
        self._sensor_grid.setSpacing(16)
        self.body.addLayout(self._sensor_grid)

        lower = QHBoxLayout()
        lower.setSpacing(16)
        self._fans_card = Card("Fans")
        self._devices_card = Card("Devices")
        lower.addWidget(self._fans_card, 3)
        lower.addWidget(self._devices_card, 2)
        self.body.addLayout(lower)
        self.body.addStretch()

    def refresh(self, state: PrismState) -> None:
        """Rebuild the cards when the hardware changes, otherwise just update the numbers.

        @param state: the latest state.
        """
        key = (tuple(state.sensors), tuple(state.fans), tuple(state.statuses))
        if key != self._layout_key:
            self._layout_key = key
            self._rebuild(state)
        self._profile_name.setText(state.showing)
        if state.rule:
            detail = f"Switched by the rule “{state.rule}”. Your choice is {state.chosen}."
        elif state.settings.automation:
            detail = "Your chosen profile. Rules are watching and will switch when needed."
        else:
            detail = "Your chosen profile. Automatic switching is off."
        self._profile_detail.setText(detail)
        for sensor_id, card in self._sensor_cards.items():
            card.add(state.readings.get(sensor_id))
        for fan_id, row in self._fan_rows.items():
            row.update_values(state.speeds.get(fan_id), state.duties.get(fan_id))

    def _rebuild(self, state: PrismState) -> None:
        """Lay out a card per sensor, a row per fan and a line per device.

        @param state: the latest state.
        """
        clear(self._sensor_grid)
        self._sensor_cards = {}
        for index, sensor in enumerate(state.sensors):
            card = SensorCard(sensor, self._palette)
            self._sensor_cards[sensor.id] = card
            self._sensor_grid.addWidget(card, index // COLUMNS, index % COLUMNS)
        self._rebuild_fans(state)
        self._rebuild_devices(state)

    def _rebuild_fans(self, state: PrismState) -> None:
        """@param state: the latest state."""
        clear(self._fans_card.body, keep=1)
        self._fan_rows = {}
        for fan in state.fans:
            row = FanRow(f"{fan.name}  ·  {fan.device}", self._palette)
            self._fan_rows[fan.id] = row
            self._fans_card.body.addWidget(row)
        if not state.fans:
            self._fans_card.body.addWidget(label("No fan controllers are connected.", "dim"))
        self._fans_card.body.addStretch()

    def _rebuild_devices(self, state: PrismState) -> None:
        """@param state: the latest state."""
        clear(self._devices_card.body, keep=1)
        for status in state.statuses:
            row = QHBoxLayout()
            dot = label("●")
            dot.setStyleSheet(f"color: {self._palette.good if status.online else self._palette.bad};")
            row.addWidget(dot)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(label(status.name))
            detail = label(status.detail, "faint")
            detail.setWordWrap(True)
            text.addWidget(detail)
            row.addLayout(text, 1)
            self._devices_card.body.addLayout(row)
        self._devices_card.body.addStretch()
