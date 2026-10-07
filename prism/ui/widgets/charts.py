from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...domain.cooling import CurvePoint, FanCurve
from ...domain.effects import Effect
from ...domain.rendering import FrameContext, Renderer
from ..theme import Palette

FAN_LEDS = 12
MIN_SPREAD = 20


class Sparkline(QWidget):
    """A small trend line of recent readings, filled with the accent gradient."""

    def __init__(self, palette: Palette, capacity: int = 90) -> None:
        super().__init__()
        self._palette = palette
        self._values: deque[float] = deque(maxlen=capacity)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def add(self, value: float) -> None:
        """@param value: the newest reading."""
        self._values.append(value)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the line and the fill beneath it."""
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height() - 2
        low, high = min(self._values), max(self._values)
        span = max(high - low, 4.0)
        middle = (low + high) / 2
        step = width / (max(len(self._values), MIN_SPREAD) - 1)
        start = width - step * (len(self._values) - 1)
        points = [
            QPointF(start + index * step, 1 + height / 2 - (value - middle) / span * (height - 4))
            for index, value in enumerate(self._values)
        ]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        fill = QPainterPath(line)
        fill.lineTo(points[-1].x(), height + 2)
        fill.lineTo(points[0].x(), height + 2)
        gradient = self._palette.accent_gradient(0, 0, width, 0)
        faded = QColor(self._palette.accent)
        faded.setAlpha(40)
        painter.fillPath(fill, faded)
        painter.setPen(QPen(QBrush(gradient), 2))
        painter.drawPath(line)


class LedPreview(QWidget):
    """Shows what a zone's LEDs look like right now, drawn by the same renderer the devices use.

    Zones made of whole fans are drawn as rings of twelve, everything else as a strip.
    """

    def __init__(self, renderer: Renderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._effect: Effect | None = None
        self._count = 0
        self._readings: dict[str, float] = {}
        self._clock = 0.0
        self.setMinimumHeight(120)
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def show_effect(self, effect: Effect | None, count: int, readings: dict[str, float]) -> None:
        """Change what is previewed.

        @param effect: the effect, or None to show the LEDs dark.
        @param count: the zone's LED count.
        @param readings: sensor values for temperature effects.
        """
        self._effect, self._count, self._readings = effect, count, readings
        self.update()

    def _advance(self) -> None:
        """Move the preview clock on by one frame."""
        if self.isVisible():
            self._clock += self._timer.interval() / 1000
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the LEDs with a soft glow."""
        if self._effect is None or self._count == 0:
            return
        frame = self._renderer.render(self._effect, self._count, FrameContext(self._clock, self._readings))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rings = self._count // FAN_LEDS if self._count % FAN_LEDS == 0 else 0
        positions = self._ring_positions(rings) if rings else self._strip_positions()
        radius = self._led_radius(rings)
        for color, center in zip(frame, positions, strict=False):
            glow = QColor(color.red, color.green, color.blue, 60)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius * 2.0, radius * 2.0)
            painter.setBrush(QColor(color.red, color.green, color.blue))
            painter.drawEllipse(center, radius, radius)

    def _led_radius(self, rings: int) -> float:
        """@return: the LED dot size that fits the layout."""
        if rings:
            return max(2.5, min(self.width() / (rings * 2.8), self.height()) / 16)
        return max(2.0, min(6.0, self.width() / (self._count * 3.2)))

    def _ring_positions(self, rings: int) -> list[QPointF]:
        """@return: LED centres arranged as fans side by side."""
        cell = self.width() / rings
        size = min(cell, self.height()) * 0.36
        positions = []
        for ring in range(rings):
            center = QPointF(cell * (ring + 0.5), self.height() / 2)
            for led in range(FAN_LEDS):
                angle = 2 * math.pi * led / FAN_LEDS - math.pi / 2
                positions.append(center + QPointF(math.cos(angle) * size, math.sin(angle) * size))
        return positions

    def _strip_positions(self) -> list[QPointF]:
        """@return: LED centres in a line, wrapping into rows if there are many."""
        per_row = min(self._count, 40)
        rows = math.ceil(self._count / per_row)
        gap = self.width() / (per_row + 1)
        return [
            QPointF(gap * (index % per_row + 1), self.height() * (index // per_row + 1) / (rows + 1))
            for index in range(self._count)
        ]


class CurveEditor(QWidget):
    """A fan curve chart whose points can be dragged, with live markers for the current reading."""

    curveChanged = Signal(object)

    MIN_TEMP = 20.0
    MAX_TEMP = 100.0
    PAD = 34

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._curve: FanCurve | None = None
        self._reading: float | None = None
        self._unit = "°C"
        self._dragging: int | None = None
        self.setMinimumHeight(240)
        self.setMouseTracking(True)

    def set_curve(self, curve: FanCurve, reading: float | None, unit: str = "°C") -> None:
        """Show a curve, unless the user is dragging one of its points.

        @param curve: the curve.
        @param reading: the followed sensor's current value, marked on the chart.
        @param unit: the sensor's unit, for the axis.
        """
        self._reading, self._unit = reading, unit
        if self._dragging is None:
            self._curve = curve
        self.update()

    def _plot(self) -> QRectF:
        """@return: the area inside the axes."""
        return QRectF(self.PAD + 6, 12, self.width() - self.PAD - 34, self.height() - self.PAD - 12)

    def _to_screen(self, temperature: float, duty: float) -> QPointF:
        """@return: where a (temperature, duty) point sits on screen."""
        plot = self._plot()
        x = plot.left() + (temperature - self.MIN_TEMP) / (self.MAX_TEMP - self.MIN_TEMP) * plot.width()
        return QPointF(x, plot.bottom() - duty / 100 * plot.height())

    def _to_point(self, position: QPointF) -> CurvePoint:
        """@return: the (temperature, duty) under a screen position."""
        plot = self._plot()
        temperature = self.MIN_TEMP + (position.x() - plot.left()) / plot.width() * (
            self.MAX_TEMP - self.MIN_TEMP
        )
        duty = (plot.bottom() - position.y()) / plot.height() * 100
        return CurvePoint(round(temperature), round(duty))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Pick up the point under the cursor."""
        if self._curve is None:
            return
        for index, point in enumerate(self._curve.points):
            center = self._to_screen(point.temperature, point.duty)
            if (center - event.position()).manhattanLength() < 16:
                self._dragging = index
                return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move the held point, or show a hand over a point that can be dragged."""
        if self._curve is None:
            return
        if self._dragging is not None:
            self._curve = self._curve.moved(self._dragging, self._to_point(event.position()))
            self.update()
            return
        near = any(
            (self._to_screen(p.temperature, p.duty) - event.position()).manhattanLength() < 16
            for p in self._curve.points
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor if near else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Drop the point and report the new curve."""
        if self._dragging is not None and self._curve is not None:
            self._dragging = None
            self.curveChanged.emit(self._curve)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the grid, the curve with its fill, the points and the live markers."""
        if self._curve is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_grid(painter)
        points = [self._to_screen(p.temperature, p.duty) for p in self._curve.points]
        plot = self._plot()
        line = QPainterPath(QPointF(plot.left(), points[0].y()))
        for point in points:
            line.lineTo(point)
        line.lineTo(plot.right(), points[-1].y())
        fill = QPainterPath(line)
        fill.lineTo(plot.right(), plot.bottom())
        fill.lineTo(plot.left(), plot.bottom())
        shade = self._palette.accent_gradient(0, plot.top(), 0, plot.bottom())
        shade.setColorAt(0.0, QColor(139, 92, 246, 90))
        shade.setColorAt(1.0, QColor(34, 211, 238, 8))
        painter.fillPath(fill, QBrush(shade))
        painter.setPen(QPen(QBrush(self._palette.accent_gradient(plot.left(), 0, plot.right(), 0)), 2.5))
        painter.drawPath(line)
        self._draw_reading(painter)
        painter.setPen(QPen(QColor(self._palette.background), 2))
        painter.setBrush(QColor("white"))
        for point in points:
            painter.drawEllipse(point, 6, 6)

    def _draw_grid(self, painter: QPainter) -> None:
        """Draw faint grid lines with temperature and duty labels."""
        plot = self._plot()
        painter.setPen(QPen(QColor(self._palette.border), 1))
        dim = QColor(self._palette.faint)
        for duty in range(0, 101, 25):
            y = self._to_screen(self.MIN_TEMP, duty).y()
            painter.setPen(QPen(QColor(self._palette.border), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(dim)
            painter.drawText(QRectF(0, y - 8, self.PAD, 16), Qt.AlignmentFlag.AlignRight, f"{duty}%")
        for temperature in range(int(self.MIN_TEMP), int(self.MAX_TEMP) + 1, 20):
            x = self._to_screen(temperature, 0).x()
            painter.setPen(dim)
            painter.drawText(
                QRectF(x - 20, plot.bottom() + 6, 40, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{temperature}{self._unit}",
            )

    def _draw_reading(self, painter: QPainter) -> None:
        """Mark the current reading and the duty it gives."""
        if self._reading is None or self._curve is None:
            return
        temperature = max(self.MIN_TEMP, min(self.MAX_TEMP, self._reading))
        duty = self._curve.duty_at(self._reading)
        point = self._to_screen(temperature, duty)
        plot = self._plot()
        painter.setPen(QPen(QColor(self._palette.accent_end), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(point.x(), plot.top()), QPointF(point.x(), plot.bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._palette.accent_end))
        painter.drawEllipse(point, 5, 5)
        painter.setPen(QColor(self._palette.text))
        painter.drawText(point + QPointF(8, -8), f"{self._reading:.0f}{self._unit} → {duty}%")
