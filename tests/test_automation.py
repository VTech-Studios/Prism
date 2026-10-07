import pytest

from prism.domain.automation import ProcessRunning, ReadingAbove, Rule, RuleEvaluator, SystemSnapshot
from prism.domain.errors import ValidationError

BUSY = SystemSnapshot({"cpu.load": 95.0})
IDLE = SystemSnapshot({"cpu.load": 5.0})
GAMING = SystemSnapshot({"cpu.load": 5.0}, frozenset({"wow.exe"}))

LOAD = Rule("Busy", ReadingAbove("cpu.load", 80, "CPU load"), "Performance", settle=5)
GAME = Rule("Game", ProcessRunning("WoW.exe"), "Gaming", settle=0)


def test_conditions_hold_and_describe_themselves() -> None:
    assert LOAD.condition.holds(BUSY)
    assert not LOAD.condition.holds(IDLE)
    assert not LOAD.condition.holds(SystemSnapshot())
    assert LOAD.condition.describe() == "CPU load above 80"
    assert ReadingAbove("gpu.temp", 70.5).describe() == "gpu.temp above 70.5"
    assert GAME.condition.holds(GAMING)
    assert GAME.condition.describe() == "wow.exe is running"


def test_rules_validate() -> None:
    with pytest.raises(ValidationError):
        Rule(" ", ProcessRunning("x"), "P")
    with pytest.raises(ValidationError):
        Rule("R", ProcessRunning("x"), "P", settle=-1)
    with pytest.raises(ValidationError):
        ProcessRunning("  ")


def test_a_rule_waits_to_settle_before_switching_on_and_off() -> None:
    evaluator = RuleEvaluator()
    assert evaluator.decide([LOAD], BUSY, 0) is None
    assert evaluator.decide([LOAD], BUSY, 4) is None
    assert evaluator.decide([LOAD], BUSY, 5) == LOAD
    assert evaluator.decide([LOAD], IDLE, 6) == LOAD
    assert evaluator.decide([LOAD], IDLE, 11) is None


def test_a_brief_spike_does_not_switch() -> None:
    evaluator = RuleEvaluator()
    evaluator.decide([LOAD], BUSY, 0)
    evaluator.decide([LOAD], IDLE, 2)
    assert evaluator.decide([LOAD], BUSY, 6) is None


def test_the_first_active_rule_wins() -> None:
    evaluator = RuleEvaluator()
    both = SystemSnapshot({"cpu.load": 95.0}, frozenset({"wow.exe"}))
    evaluator.decide([GAME, LOAD], both, 0)
    assert evaluator.decide([GAME, LOAD], both, 10) == GAME
    assert evaluator.decide([LOAD, GAME], both, 11) == LOAD


def test_disabled_and_deleted_rules_drop_out() -> None:
    evaluator = RuleEvaluator()
    assert evaluator.decide([GAME], GAMING, 0) == GAME
    off = Rule("Game", ProcessRunning("wow.exe"), "Gaming", settle=0, enabled=False)
    assert evaluator.decide([off], GAMING, 1) is None
    evaluator.decide([GAME], GAMING, 2)
    assert evaluator.decide([], GAMING, 3) is None
    assert evaluator.decide([LOAD], BUSY, 4) is None
