from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.state import PrismState
from .client import PrismClient
from .icons import app_icon, nav_icon
from .pages.base import Page
from .theme import Palette
from .widgets.basics import Toast, label


class MainWindow(QMainWindow):
    """A sidebar of pages beside the open page, with the profile picker always in reach.

    Closing the window hides it when a tray icon can bring it back, because
    Prism has to keep running for curves, drawn effects and rules to work.
    """

    def __init__(
        self,
        client: PrismClient,
        pages: Sequence[tuple[str, str, Page]],
        palette: Palette,
        hide_on_close: bool,
    ) -> None:
        """@param pages: (icon name, caption, page) for each sidebar entry, in order."""
        super().__init__()
        self._client = client
        self._pages = [page for _, _, page in pages]
        self._hide_on_close = hide_on_close
        self._last_notice = 0
        self._told_about_tray = False
        self.quitting = False
        self.setWindowTitle("Prism")
        self.setWindowIcon(app_icon())
        self.resize(1240, 820)
        self.setMinimumSize(980, 640)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._stack = QStackedWidget()
        layout.addWidget(self._sidebar(pages, palette))
        layout.addWidget(self._stack, 1)
        for page in self._pages:
            self._stack.addWidget(page)
        self.setCentralWidget(root)
        self._toast = Toast(root)
        self._stack.currentChanged.connect(self._page_opened)
        client.stateChanged.connect(self.refresh)

    def _sidebar(self, pages: Sequence[tuple[str, str, Page]], palette: Palette) -> QWidget:
        """Build the navigation column with the brand at the top and the profile picker at the bottom.

        @param pages: the sidebar entries.
        @param palette: the colours, for the icons.
        @return: the sidebar.
        """
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(16, 22, 16, 18)
        column.setSpacing(4)
        brand = QHBoxLayout()
        logo = label("")
        logo.setPixmap(app_icon().pixmap(34, 34))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Prism", "brand"))
        names.addWidget(label("LIGHT · AIR · FLOW", "brandTag"))
        brand.addLayout(names)
        brand.addStretch()
        column.addLayout(brand)
        column.addSpacing(24)

        group = QButtonGroup(self)
        for index, (icon, caption, _) in enumerate(pages):
            entry = QPushButton(f"  {caption}")
            entry.setObjectName("nav")
            entry.setCheckable(True)
            entry.setCursor(Qt.CursorShape.PointingHandCursor)
            entry.setIcon(nav_icon(icon, palette.dim, palette.text))
            group.addButton(entry, index)
            column.addWidget(entry)
        group.idClicked.connect(self._stack.setCurrentIndex)
        group.button(0).setChecked(True)
        column.addStretch()

        column.addWidget(label("PROFILE", "section"))
        self._profiles = QComboBox()
        self._profiles.activated.connect(lambda _: self._client.choose_profile(self._profiles.currentText()))
        column.addWidget(self._profiles)
        self._showing = label("", "faint")
        self._showing.setWordWrap(True)
        column.addWidget(self._showing)
        return sidebar

    def refresh(self, state: PrismState) -> None:
        """Update the profile picker, the open page and any new message.

        @param state: the latest state.
        """
        names = [profile.name for profile in state.profiles]
        if [self._profiles.itemText(index) for index in range(self._profiles.count())] != names:
            self._profiles.blockSignals(True)
            self._profiles.clear()
            self._profiles.addItems(names)
            self._profiles.blockSignals(False)
        if not self._profiles.view().isVisible():
            self._profiles.setCurrentText(state.chosen)
        self._showing.setText(f"Rule “{state.rule}” is showing {state.showing}" if state.rule else "")
        for page in self._pages:
            if page is self._stack.currentWidget() or page.always_render:
                page.refresh(state)
        if state.notice and state.notice[0] != self._last_notice:
            self._last_notice = state.notice[0]
            self._toast.show_message(state.notice[1])

    def _page_opened(self, index: int) -> None:
        """Draw a page from the latest state as it opens, rather than waiting for the next update.

        @param index: the page's position in the sidebar.
        """
        page = self._stack.widget(index)
        if isinstance(page, Page) and self._client.state is not None:
            page.refresh(self._client.state)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Hide to the tray rather than quit, unless quitting was asked for."""
        if self._hide_on_close and not self.quitting:
            event.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self._client.notify("Prism is still running in the tray")
            return
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the toast in the corner as the window resizes."""
        super().resizeEvent(event)
        if self._toast.isVisible():
            self._toast.move(
                self.width() - self._toast.width() - 24, self.height() - self._toast.height() - 24
            )
