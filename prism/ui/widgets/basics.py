from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...domain.color import Color

SETTLE_MS = 350


def label(text: str, name: str = "") -> QLabel:
    """Make a label with a style name.

    @param text: the text.
    @param name: the object name the stylesheet styles it by.
    @return: the label.
    """
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if name.startswith("pill"):
        widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return widget


def button(text: str, on_click: Callable[[], None], name: str = "") -> QPushButton:
    """Make a button wired to a handler.

    @param text: the caption.
    @param on_click: called when clicked.
    @param name: the object name the stylesheet styles it by.
    @return: the button.
    """
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(on_click)
    return widget


class Card(QFrame):
    """A rounded panel that groups related controls."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            self.body.addWidget(label(title.upper(), "section"))


class Segmented(QWidget):
    """A row of joined buttons where exactly one is chosen, like iOS's segmented control."""

    changed = Signal(object)

    def __init__(self, options: Sequence[tuple[str, object]], parent: QWidget | None = None) -> None:
        """@param options: (caption, value) pairs, in order."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._values = [value for _, value in options]
        for index, (caption, _) in enumerate(options):
            segment = QPushButton(caption)
            segment.setCheckable(True)
            segment.setCursor(Qt.CursorShape.PointingHandCursor)
            segment.setObjectName(
                "segmentFirst" if index == 0 else "segmentLast" if index == len(options) - 1 else "segment"
            )
            self._group.addButton(segment, index)
            layout.addWidget(segment)
        layout.addStretch()
        self._group.idClicked.connect(lambda index: self.changed.emit(self._values[index]))

    def set_value(self, value: object) -> None:
        """Select the segment for a value without emitting a change, or clear the selection.

        @param value: one of the option values, or anything else to select none.
        """
        if value in self._values:
            self._group.button(self._values.index(value)).setChecked(True)
            return
        self._group.setExclusive(False)
        for segment in self._group.buttons():
            segment.setChecked(False)
        self._group.setExclusive(True)


class CommitSlider(QSlider):
    """A slider that saves once the user settles on a value, however they moved it.

    Dragging, the keyboard, the mouse wheel and clicking the track all count,
    and a burst of changes is saved once, shortly after the last one.
    """

    committed = Signal(int)

    def __init__(self, low: int, high: int, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(low, high)
        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(lambda: self.committed.emit(self.value()))
        self.valueChanged.connect(self._changed)
        self.sliderReleased.connect(self._settle.start)

    def busy(self) -> bool:
        """@return: whether the user is mid-change, so outside updates should wait."""
        return self.isSliderDown() or self._settle.isActive()

    def set_quietly(self, value: int) -> None:
        """Show a value from outside without saving it, unless the user is mid-change.

        @param value: the value.
        """
        if not self.busy():
            self.blockSignals(True)
            self.setValue(value)
            self.blockSignals(False)

    def _changed(self) -> None:
        """Restart the settle timer, unless a drag is still going and release will start it."""
        if not self.isSliderDown():
            self._settle.start()


def fill_combo(combo: QComboBox, items: Sequence[tuple[str, object]], current: object) -> None:
    """Fill a combo box, leaving it alone if nothing changed or its list is open.

    Refilling on every update would close an open list under the user's cursor.

    @param combo: the combo box.
    @param items: (caption, value) pairs.
    @param current: the value to select.
    """
    if combo.view().isVisible():
        return
    existing = [(combo.itemText(index), combo.itemData(index)) for index in range(combo.count())]
    combo.blockSignals(True)
    if existing != list(items):
        combo.clear()
        for caption, value in items:
            combo.addItem(caption, value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


class Swatch(QPushButton):
    """A colour chip that opens a colour picker when clicked."""

    picked = Signal(object)

    def __init__(self, color: Color, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: Color) -> None:
        """@param color: the colour to show."""
        self._color = color
        self.setToolTip(color.hex)
        self.setStyleSheet(
            f"QPushButton {{ background: {color.hex}; border: 2px solid rgba(255,255,255,0.15);"
            f" border-radius: 12px; }} QPushButton:hover {{ border-color: white; }}"
        )

    def _pick(self) -> None:
        """Open the colour picker and report the choice."""
        chosen = QColorDialog.getColor(QColor(self._color.hex), self, "Choose a colour")
        if chosen.isValid():
            color = Color(chosen.red(), chosen.green(), chosen.blue())
            self.set_color(color)
            self.picked.emit(color)


class Toggle(QWidget):
    """An on/off switch, clearer than a checkbox for settings that take effect at once."""

    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = False

    def is_on(self) -> bool:
        """@return: whether the switch is on."""
        return self._on

    def set_on(self, on: bool) -> None:
        """Set the switch without emitting a change.

        @param on: the new position.
        """
        self._on = on
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Flip the switch and report it."""
        self.set_on(not self._on)
        self.toggled.emit(self._on)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the track and the knob."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#8b5cf6" if self._on else "#2b3242"))
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.setBrush(QColor("white"))
        knob = 24 if self._on else 4
        painter.drawEllipse(knob, 4, 16, 16)


class Toast(QLabel):
    """A short message that fades in at the bottom of the window and fades away by itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._hide_timer = QTimer(self, singleShot=True, interval=3500)
        self._hide_timer.timeout.connect(lambda: self._animate(0.0))
        self.hide()

    def show_message(self, message: str) -> None:
        """Show a message in the bottom right corner.

        @param message: the message.
        """
        self.setText(message)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)
        self.show()
        self.raise_()
        self._animate(1.0)
        self._hide_timer.start()

    def _animate(self, target: float) -> None:
        """@param target: the opacity to fade to."""
        self._fade.stop()
        self._fade.setDuration(220)
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(target)
        self._fade.start()
