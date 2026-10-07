from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """One reading of the machine, taken together so rules judge a consistent moment.

    @ivar readings: sensor values keyed by sensor id, such as "cpu.temp" or "gpu.load".
    @ivar processes: the names of running programs, lower case.
    """

    readings: Mapping[str, float] = field(default_factory=dict)
    processes: frozenset[str] = frozenset()


class Condition(Protocol):
    kind: ClassVar[str]

    def holds(self, snapshot: SystemSnapshot) -> bool:
        """Test the condition against the machine's current state.

        @param snapshot: the latest reading.
        @return: True while the condition is met.
        """
        ...

    def describe(self) -> str:
        """@return: the condition in words, for the rules list."""
        ...


@dataclass(frozen=True, slots=True)
class ReadingAbove:
    """Met while a sensor reads above a threshold, such as CPU load over 80%."""

    kind: ClassVar[str] = "reading_above"
    sensor: str
    threshold: float
    label: str = ""

    def holds(self, snapshot: SystemSnapshot) -> bool:
        """@return: True while the sensor reads above the threshold."""
        reading = snapshot.readings.get(self.sensor)
        return reading is not None and reading > self.threshold

    def describe(self) -> str:
        """@return: for example "CPU load above 80"."""
        return f"{self.label or self.sensor} above {self.threshold:g}"


@dataclass(frozen=True, slots=True)
class ProcessRunning:
    """Met while a program with this name is running, such as a game."""

    kind: ClassVar[str] = "process_running"
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a program name is needed")
        object.__setattr__(self, "name", self.name.strip().lower())

    def holds(self, snapshot: SystemSnapshot) -> bool:
        """@return: True while the program is running."""
        return self.name in snapshot.processes

    def describe(self) -> str:
        """@return: for example "wow.exe is running"."""
        return f"{self.name} is running"


@dataclass(frozen=True, slots=True)
class Rule:
    """Switch to a profile while a condition holds.

    @ivar settle: seconds the condition must hold, and then stop holding, before the
        switch happens, so a brief spike does not flick the fans up and down.
    """

    name: str
    condition: Condition
    profile: str
    settle: float = 5.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a rule needs a name")
        if self.settle < 0:
            raise ValidationError("settle time cannot be negative")


class RuleEvaluator:
    """Decides which rule, if any, should be in charge, with settling on both edges.

    Rules are checked in order and the first active one wins, so order is priority.
    """

    def __init__(self) -> None:
        self._changed_at: dict[str, float] = {}
        self._active: set[str] = set()

    def decide(self, rules: Sequence[Rule], snapshot: SystemSnapshot, now: float) -> Rule | None:
        """Update every rule's state and pick the one in charge.

        @param rules: the rules, highest priority first.
        @param snapshot: the machine's current state.
        @param now: a monotonic time in seconds.
        @return: the first active rule, or None to fall back to the chosen profile.
        """
        self._forget_missing(rules)
        winner: Rule | None = None
        for rule in rules:
            active = self._update(rule, snapshot, now)
            if active and winner is None:
                winner = rule
        return winner

    def _update(self, rule: Rule, snapshot: SystemSnapshot, now: float) -> bool:
        """Advance one rule's state.

        @param rule: the rule.
        @param snapshot: the machine's current state.
        @param now: a monotonic time in seconds.
        @return: whether the rule is now active.
        """
        holds = rule.enabled and rule.condition.holds(snapshot)
        active = rule.name in self._active
        if holds == active:
            self._changed_at.pop(rule.name, None)
            return active
        since = self._changed_at.setdefault(rule.name, now)
        if now - since < rule.settle:
            return active
        self._changed_at.pop(rule.name, None)
        if holds:
            self._active.add(rule.name)
        else:
            self._active.discard(rule.name)
        return holds

    def _forget_missing(self, rules: Sequence[Rule]) -> None:
        """Drop state for rules that were deleted or renamed.

        @param rules: the current rules.
        """
        names = {rule.name for rule in rules}
        self._active &= names
        for name in set(self._changed_at) - names:
            del self._changed_at[name]
