from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QMessageBox

from ...domain.errors import PrismError
from ...domain.profile import Profile
from ...ports import ProfileFiles
from ...services.core import PrismState
from ..client import PrismClient
from ..widgets.basics import Card, button, label
from .base import Page, clear

COLUMNS = 2
FILTER = "Prism profile (*.json)"


def summary(profile: Profile) -> str:
    """@return: what a profile sets, in a few words."""
    parts = [f"{len(profile.lighting)} lighting zone{'s' if len(profile.lighting) != 1 else ''}"]
    parts.append(f"{len(profile.cooling)} fan{'s' if len(profile.cooling) != 1 else ''}")
    if profile.pump:
        parts.append(f"pump {profile.pump.value}")
    return "  ·  ".join(parts)


class ProfilesPage(Page):
    """Every saved profile, with switching, copying, renaming, sharing and deleting."""

    def __init__(self, client: PrismClient, files: ProfileFiles) -> None:
        super().__init__("Profiles", "Saved looks and fan setups. The chosen one shows when no rule applies.")
        self._client = client
        self._files = files
        self._key: tuple[object, ...] = ()
        actions = QHBoxLayout()
        actions.addWidget(button("New profile", self._create, "primary"))
        actions.addWidget(button("Import…", self._import))
        actions.addStretch()
        self.body.addLayout(actions)
        self._grid = QGridLayout()
        self._grid.setSpacing(16)
        self.body.addLayout(self._grid)
        self.body.addStretch()

    def refresh(self, state: PrismState) -> None:
        """Rebuild the cards only when profiles or which one is showing change.

        @param state: the latest state.
        """
        key = (state.profiles, state.chosen, state.showing)
        if key == self._key:
            return
        self._key = key
        clear(self._grid)
        for index, profile in enumerate(state.profiles):
            self._grid.addWidget(self._card(profile, state), index // COLUMNS, index % COLUMNS)

    def _card(self, profile: Profile, state: PrismState) -> Card:
        """Build one profile's card.

        @param profile: the profile.
        @param state: the latest state.
        @return: the card.
        """
        card = Card()
        top = QHBoxLayout()
        top.addWidget(label(profile.name, "big"))
        top.addStretch()
        if profile.name == state.chosen:
            top.addWidget(label("Chosen", "pillAccent"), alignment=Qt.AlignmentFlag.AlignVCenter)
        if profile.name == state.showing and state.rule:
            top.addWidget(label(f"Showing via {state.rule}", "pill"), alignment=Qt.AlignmentFlag.AlignVCenter)
        card.body.addLayout(top)
        card.body.addWidget(label(summary(profile), "dim"))
        row = QHBoxLayout()
        name = profile.name
        if name != state.chosen:
            row.addWidget(button("Use", lambda: self._client.choose_profile(name), "primary"))
        row.addWidget(button("Rename", lambda: self._rename(name)))
        row.addWidget(button("Duplicate", lambda: self._client.duplicate_profile(name)))
        row.addWidget(button("Export", lambda: self._export(profile)))
        row.addStretch()
        row.addWidget(button("Delete", lambda: self._delete(name), "danger"))
        card.body.addLayout(row)
        return card

    def _create(self) -> None:
        """Ask for a name and add an empty profile."""
        name, ok = QInputDialog.getText(self, "New profile", "Name:")
        if ok and name.strip():
            self._client.create_profile(name)

    def _rename(self, old: str) -> None:
        """@param old: the profile to rename."""
        new, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=old)
        if ok and new.strip():
            self._client.rename_profile(old, new)

    def _delete(self, name: str) -> None:
        """@param name: the profile to delete, after asking."""
        answer = QMessageBox.question(self, "Delete profile", f"Delete {name}? This cannot be undone.")
        if answer == QMessageBox.StandardButton.Yes:
            self._client.delete_profile(name)

    def _export(self, profile: Profile) -> None:
        """@param profile: the profile to write to a file the user picks."""
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", f"{profile.name}.json", FILTER)
        if path:
            try:
                self._files.export(profile, Path(path))
            except PrismError as error:
                self._client.notify(str(error))
                return
            self._client.notify(f"Exported {profile.name}")

    def _import(self) -> None:
        """Read a profile from a file the user picks."""
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", FILTER)
        if path:
            try:
                profile = self._files.read(Path(path))
            except PrismError as error:
                self._client.notify(str(error))
                return
            self._client.import_profile(profile)
