from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace

from ..domain.automation import ProcessRunning, Rule, RuleEvaluator, SystemSnapshot
from ..domain.errors import ValidationError
from ..ports import RuleStore


class AutomationService:
    """The user's rules, kept in priority order, and the choice of which profile they call for."""

    def __init__(self, store: RuleStore, evaluator: RuleEvaluator) -> None:
        self._store = store
        self._evaluator = evaluator
        self._rules = store.load()

    @property
    def rules(self) -> list[Rule]:
        """Every rule, highest priority first."""
        return list(self._rules)

    def watches_processes(self) -> bool:
        """@return: whether any enabled rule needs the list of running programs, which is costly to read."""
        return any(rule.enabled and isinstance(rule.condition, ProcessRunning) for rule in self._rules)

    def save_rule(self, rule: Rule, replacing: str | None = None) -> None:
        """Add a rule at the end, or replace one in place.

        @param rule: the rule.
        @param replacing: the name of the rule being edited, or None for a new rule.
        @raise ValidationError: if another rule already has the name.
        """
        names = [existing.name for existing in self._rules]
        if rule.name in names and rule.name != replacing:
            raise ValidationError(f"there is already a rule called {rule.name!r}")
        if replacing in names:
            self._rules[names.index(replacing)] = rule
        else:
            self._rules.append(rule)
        self._persist()

    def delete_rule(self, name: str) -> None:
        """@param name: the rule to remove."""
        self._rules = [rule for rule in self._rules if rule.name != name]
        self._persist()

    def move_rule(self, name: str, offset: int) -> None:
        """Raise or lower a rule's priority.

        @param name: the rule.
        @param offset: -1 to move it up, +1 to move it down.
        """
        names = [rule.name for rule in self._rules]
        if name not in names:
            return
        index = names.index(name)
        target = max(0, min(len(self._rules) - 1, index + offset))
        self._rules.insert(target, self._rules.pop(index))
        self._persist()

    def profile_renamed(self, old: str, new: str) -> None:
        """Point rules at a profile's new name.

        @param old: the profile's old name.
        @param new: its new name.
        """
        if any(rule.profile == old for rule in self._rules):
            self._rules = [
                replace(rule, profile=new) if rule.profile == old else rule for rule in self._rules
            ]
            self._persist()

    def choose(
        self, snapshot: SystemSnapshot, now: float, chosen: str, profiles: Collection[str]
    ) -> tuple[str, Rule | None]:
        """Pick the profile that should be showing right now.

        Rules whose profile was deleted are skipped rather than switching to nothing.

        @param snapshot: the machine's current state.
        @param now: a monotonic time in seconds.
        @param chosen: the profile the user picked, used when no rule applies.
        @param profiles: the names of existing profiles.
        @return: the profile to show, and the rule that chose it if any.
        """
        usable = [rule for rule in self._rules if rule.profile in profiles]
        rule = self._evaluator.decide(usable, snapshot, now)
        return (rule.profile, rule) if rule else (chosen, None)

    def _persist(self) -> None:
        """Write every rule to the store."""
        self._store.save(self._rules)
