from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLayout, QScrollArea, QVBoxLayout, QWidget

from ...services.core import PrismState
from ..widgets.basics import label


class Page(QWidget):
    """A titled, scrolling page. Subclasses fill in the body and redraw from each new state.

    Only the open page is redrawn, unless it keeps history that must not have gaps.
    """

    always_render = False

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(36, 28, 36, 36)
        self.body.setSpacing(18)
        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(label(title, "title"))
        header.addWidget(label(subtitle, "subtitle"))
        self.body.addLayout(header)

    def refresh(self, state: PrismState) -> None:
        """Bring the page up to date.

        @param state: the latest state.
        """
        raise NotImplementedError


def clear(layout: QLayout, keep: int = 0) -> None:
    """Remove and delete the widgets in a layout, before it is rebuilt.

    @param layout: the layout.
    @param keep: how many leading items to leave, such as a card's title.
    """
    while layout.count() > keep:
        item = layout.takeAt(keep)
        if item is None:
            return
        widget = item.widget()
        nested = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif nested is not None:
            clear(nested)


def sensor_name(state: PrismState, sensor_id: str) -> str:
    """@return: a sensor's display name, or its id if it is not connected."""
    return next((sensor.name for sensor in state.sensors if sensor.id == sensor_id), sensor_id)


def sensor_unit(state: PrismState, sensor_id: str) -> str:
    """@return: a sensor's unit, or nothing if it is not connected."""
    return next((sensor.unit for sensor in state.sensors if sensor.id == sensor_id), "")
