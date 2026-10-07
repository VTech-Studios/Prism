from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..services.core import PrismState
from .client import PrismClient
from .icons import app_icon


class Tray(QSystemTrayIcon):
    """The tray icon: switch profile, pause rules, open the window or quit, without opening Prism."""

    def __init__(
        self, client: PrismClient, show_window: Callable[[], None], quit_app: Callable[[], None]
    ) -> None:
        super().__init__(app_icon())
        self._client = client
        self._key: tuple[object, ...] = ()
        self._show_window = show_window
        self._quit = quit_app
        self.setToolTip("Prism")
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._clicked)
        client.stateChanged.connect(self.refresh)

    def refresh(self, state: PrismState) -> None:
        """Rebuild the menu when profiles or rules change.

        @param state: the latest state.
        """
        self.setToolTip(f"Prism · {state.showing}" + (f" (rule: {state.rule})" if state.rule else ""))
        key = (tuple(profile.name for profile in state.profiles), state.chosen, state.settings.automation)
        if key == self._key:
            return
        self._key = key
        self._menu.clear()
        self._menu.addAction("Open Prism", self._show_window)
        self._menu.addSeparator()
        group = QActionGroup(self._menu)
        for profile in state.profiles:
            action = QAction(profile.name, self._menu, checkable=True, checked=profile.name == state.chosen)
            action.triggered.connect(lambda _=False, name=profile.name: self._client.choose_profile(name))
            group.addAction(action)
            self._menu.addAction(action)
        self._menu.addSeparator()
        rules = QAction("Automatic switching", self._menu, checkable=True, checked=state.settings.automation)
        rules.toggled.connect(
            lambda on: self._client.update_settings(lambda settings: replace(settings, automation=on))
        )
        self._menu.addAction(rules)
        self._menu.addSeparator()
        self._menu.addAction("Quit", self._quit)

    def _clicked(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Open the window on a left click."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()
