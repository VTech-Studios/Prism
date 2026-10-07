from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...domain.automation import Condition, ProcessRunning, ReadingAbove, Rule
from ...domain.errors import ValidationError
from ...services.core import PrismState
from ..client import PrismClient
from ..widgets.basics import Card, Toggle, button, label
from .base import Page, clear, sensor_unit

READING = 0
PROGRAM = 1


class RuleDialog(QDialog):
    """Asks for a rule: when a reading is high or a program runs, switch to a profile."""

    def __init__(self, state: PrismState, rule: Rule | None, parent: QWidget | None = None) -> None:
        """@param rule: the rule to edit, or None for a new one."""
        super().__init__(parent)
        self.setWindowTitle("Edit rule" if rule else "New rule")
        self.setMinimumWidth(460)
        self._state = state
        self.result_rule: Rule | None = None
        form = QFormLayout()
        form.setSpacing(12)
        self._name = QLineEdit(rule.name if rule else "")
        self._name.setPlaceholderText("Gaming, Heavy load…")
        form.addRow("Name", self._name)

        self._kind = QComboBox()
        self._kind.addItems(["A reading goes above", "A program is running"])
        form.addRow("When", self._kind)
        self._condition = QStackedWidget()
        self._condition.addWidget(self._reading_editor(rule))
        self._condition.addWidget(self._program_editor(rule))
        self._kind.currentIndexChanged.connect(self._condition.setCurrentIndex)
        self._kind.setCurrentIndex(
            PROGRAM if rule and isinstance(rule.condition, ProcessRunning) else READING
        )
        form.addRow("", self._condition)

        self._profile = QComboBox()
        self._profile.addItems([profile.name for profile in state.profiles])
        if rule:
            self._profile.setCurrentText(rule.profile)
        form.addRow("Switch to", self._profile)

        self._settle = QDoubleSpinBox()
        self._settle.setRange(0, 600)
        self._settle.setDecimals(0)
        self._settle.setSuffix(" s")
        self._settle.setValue(rule.settle if rule else 5)
        form.addRow("Settle time", self._settle)
        form.addRow("", label("How long the condition must hold, and then stop, before switching.", "faint"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._error = label("", "banner")
        self._error.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addWidget(buttons)
        self._enabled = rule.enabled if rule else True

    def _reading_editor(self, rule: Rule | None) -> QWidget:
        """@return: the sensor and threshold controls."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        self._sensor = QComboBox()
        for sensor in self._state.sensors:
            self._sensor.addItem(sensor.name, sensor.id)
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0, 1000)
        self._threshold.setDecimals(0)
        self._threshold.setValue(80)
        if rule and isinstance(rule.condition, ReadingAbove):
            index = self._sensor.findData(rule.condition.sensor)
            self._sensor.setCurrentIndex(max(0, index))
            self._threshold.setValue(rule.condition.threshold)
        self._sensor.currentIndexChanged.connect(self._update_unit)
        self._update_unit()
        row.addWidget(self._sensor, 2)
        row.addWidget(self._threshold, 1)
        return box

    def _program_editor(self, rule: Rule | None) -> QWidget:
        """@return: the program name control."""
        self._program = QLineEdit(
            rule.condition.name if rule and isinstance(rule.condition, ProcessRunning) else ""
        )
        self._program.setPlaceholderText("wow.exe, steam, blender…")
        return self._program

    def _update_unit(self) -> None:
        """Show the chosen sensor's unit after the threshold."""
        unit = sensor_unit(self._state, self._sensor.currentData() or "")
        self._threshold.setSuffix(f" {unit}" if unit else "")

    def _condition_value(self) -> Condition:
        """@return: the condition as entered."""
        if self._kind.currentIndex() == PROGRAM:
            return ProcessRunning(self._program.text())
        return ReadingAbove(self._sensor.currentData(), self._threshold.value(), self._sensor.currentText())

    def _accept(self) -> None:
        """Build the rule, or explain what is missing."""
        try:
            self.result_rule = Rule(
                name=self._name.text().strip(),
                condition=self._condition_value(),
                profile=self._profile.currentText(),
                settle=self._settle.value(),
                enabled=self._enabled,
            )
        except ValidationError as error:
            self._error.setText(str(error).capitalize())
            self._error.show()
            return
        self.accept()


class AutomationPage(Page):
    """Rules that switch profile by load, temperature or running program, in priority order."""

    def __init__(self, client: PrismClient) -> None:
        super().__init__(
            "Automation", "Switch profiles by themselves when the machine gets busy or a game starts."
        )
        self._client = client
        self._state: PrismState | None = None
        self._key: tuple[object, ...] = ()

        switch_card = Card()
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(label("Automatic switching"))
        self._status = label("", "dim")
        text.addWidget(self._status)
        row.addLayout(text, 1)
        self._toggle = Toggle()
        self._toggle.toggled.connect(
            lambda on: self._client.update_settings(lambda settings: replace(settings, automation=on))
        )
        row.addWidget(self._toggle)
        switch_card.body.addLayout(row)
        self.body.addWidget(switch_card)

        actions = QHBoxLayout()
        actions.addWidget(label("RULES", "section"))
        actions.addStretch()
        actions.addWidget(button("Add rule", lambda: self._edit(None), "primary"))
        self.body.addLayout(actions)
        self.body.addWidget(
            label("The first rule that applies wins, so put the most important at the top.", "faint")
        )
        self._list = QVBoxLayout()
        self._list.setSpacing(10)
        self.body.addLayout(self._list)
        self.body.addStretch()

    def refresh(self, state: PrismState) -> None:
        """@param state: the latest state."""
        self._state = state
        self._toggle.set_on(state.settings.automation)
        if not state.settings.automation:
            self._status.setText(f"Off. {state.chosen} stays on until you change it.")
        elif state.rule:
            self._status.setText(f"On. “{state.rule}” is showing {state.showing}.")
        else:
            self._status.setText(f"On. No rule applies, so {state.chosen} is showing.")
        key = (state.rules, state.rule)
        if key != self._key:
            self._key = key
            self._rebuild(state)

    def _rebuild(self, state: PrismState) -> None:
        """@param state: the latest state, whose rules become cards."""
        clear(self._list)
        if not state.rules:
            self._list.addWidget(label("No rules yet. Add one to switch profile when a game starts.", "dim"))
        for rule in state.rules:
            self._list.addWidget(self._card(rule, state))

    def _card(self, rule: Rule, state: PrismState) -> Card:
        """@return: one rule's card."""
        card = Card()
        row = QHBoxLayout()
        enabled = Toggle()
        enabled.set_on(rule.enabled)
        enabled.toggled.connect(lambda on: self._client.save_rule(replace(rule, enabled=on), rule.name))
        row.addWidget(enabled)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QHBoxLayout()
        title.addWidget(label(rule.name))
        if rule.name == state.rule:
            title.addWidget(label("Active", "pillAccent"))
        title.addStretch()
        text.addLayout(title)
        settle = f" for {rule.settle:g}s" if rule.settle else ""
        text.addWidget(label(f"When {rule.condition.describe()}{settle}, switch to {rule.profile}", "dim"))
        row.addLayout(text, 1)
        row.addWidget(button("↑", lambda: self._client.move_rule(rule.name, -1)))
        row.addWidget(button("↓", lambda: self._client.move_rule(rule.name, 1)))
        row.addWidget(button("Edit", lambda: self._edit(rule)))
        row.addWidget(button("Delete", lambda: self._client.delete_rule(rule.name), "danger"))
        card.body.addLayout(row)
        return card

    def _edit(self, rule: Rule | None) -> None:
        """@param rule: the rule to edit, or None to add one."""
        if self._state is None:
            return
        dialog = RuleDialog(self._state, rule, self)
        if dialog.exec() and dialog.result_rule is not None:
            self._client.save_rule(dialog.result_rule, rule.name if rule else None)
