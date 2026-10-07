from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ..domain.automation import Rule
from ..domain.profile import Profile
from ..domain.settings import Settings
from ..services.loop import Command
from ..services.state import PrismState


class PrismClient(QObject):
    """The window's only way to reach the core: commands go out, fresh state comes back.

    State arrives on the runtime thread and is re-emitted as a Qt signal, which
    Qt delivers on the window's thread.
    """

    stateChanged = Signal(object)

    def __init__(self, submit: Callable[[Command], None]) -> None:
        """@param submit: queues a command on the runtime loop."""
        super().__init__()
        self._submit = submit
        self.state: PrismState | None = None
        self.stateChanged.connect(self._remember)

    def publish(self, state: PrismState) -> None:
        """Hand over a state from the runtime thread.

        @param state: the latest state.
        """
        self.stateChanged.emit(state)

    def choose_profile(self, name: str) -> None:
        """@param name: the profile to show when no rule applies."""
        self._submit(lambda core: core.choose_profile(name))

    def edit_profile(self, name: str, change: Callable[[Profile], Profile]) -> None:
        """Change a profile; the change is applied to its latest version on the runtime thread.

        @param name: the profile.
        @param change: makes the edited profile from the current one.
        """
        self._submit(lambda core: core.edit_profile(name, change))

    def edit_chosen(self, change: Callable[[Profile], Profile]) -> None:
        """Edit the chosen profile, resolved on the runtime thread so a profile switch in flight is respected.

        @param change: makes the edited profile from the chosen one.
        """
        self._submit(lambda core: core.edit_chosen(change))

    def create_profile(self, name: str) -> None:
        """@param name: the new profile's name."""
        self._submit(lambda core: core.create_profile(name))

    def duplicate_profile(self, name: str) -> None:
        """@param name: the profile to copy."""
        self._submit(lambda core: core.duplicate_profile(name))

    def rename_profile(self, old: str, new: str) -> None:
        """@param old: the current name. @param new: the new name."""
        self._submit(lambda core: core.rename_profile(old, new))

    def delete_profile(self, name: str) -> None:
        """@param name: the profile to delete."""
        self._submit(lambda core: core.delete_profile(name))

    def import_profile(self, profile: Profile) -> None:
        """@param profile: a profile read from a file."""
        self._submit(lambda core: core.import_profile(profile))

    def save_rule(self, rule: Rule, replacing: str | None) -> None:
        """@param replacing: the name of the rule being edited, or None for a new one."""
        self._submit(lambda core: core.save_rule(rule, replacing))

    def delete_rule(self, name: str) -> None:
        """@param name: the rule to delete."""
        self._submit(lambda core: core.delete_rule(name))

    def move_rule(self, name: str, offset: int) -> None:
        """@param offset: -1 to raise the rule's priority, +1 to lower it."""
        self._submit(lambda core: core.move_rule(name, offset))

    def update_settings(self, change: Callable[[Settings], Settings]) -> None:
        """@param change: makes the new settings from the current ones."""
        self._submit(lambda core: core.update_settings(change(core.settings)))

    def set_autostart(self, enabled: bool) -> None:
        """@param enabled: whether Prism starts at login."""
        self._submit(lambda core: core.set_autostart(enabled))

    def notify(self, message: str) -> None:
        """@param message: a message to show, routed through the core so it reaches every view."""
        self._submit(lambda core: core.notify(message))

    def _remember(self, state: PrismState) -> None:
        """@param state: the state to keep for synchronous reads."""
        self.state = state
