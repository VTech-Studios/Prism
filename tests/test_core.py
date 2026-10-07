import threading
from dataclasses import replace

import pytest

from prism.domain.automation import ProcessRunning, ReadingAbove, Rule
from prism.domain.color import Color
from prism.domain.cooling import FanCurve, FanSetting
from prism.domain.effects import Effect
from prism.domain.errors import DeviceError, ValidationError
from prism.domain.profile import Profile
from prism.domain.rendering import Frame
from prism.domain.settings import Settings
from prism.services.cooling import FAILSAFE_DUTY
from prism.services.core import PrismCore
from prism.services.loop import RuntimeLoop
from prism.services.state import PrismState
from tests.fakes import FakeLights, FakeSensors, zone
from tests.rig import Rig

RED = Effect.static(Color(255, 0, 0))
BLUE = Effect.static(Color(0, 0, 255))


def test_first_run_seeds_profiles_and_shows_the_default() -> None:
    rig = Rig()
    rig.core.start()
    state = rig.core.state()
    assert [profile.name for profile in state.profiles] == ["Default", "Quiet", "Performance"]
    assert state.showing == "Default"
    rig.advance(0)
    assert rig.lights.drawn[0][0] == "fans"


def test_a_missing_chosen_profile_falls_back_to_the_first() -> None:
    rig = Rig([Profile("Mine").with_effect("fans", RED)])
    rig.settings.settings = Settings(active_profile="Gone")
    rig.core.start()
    assert rig.core.state().chosen == "Mine"
    assert rig.lights.played == [("fans", RED)]


def test_ticks_measure_and_drive_fans() -> None:
    rig = Rig([Profile("P", cooling={"fan1": FanSetting.fixed(55)})])
    rig.core.start()
    rig.advance(0)
    state = rig.core.state()
    assert state.readings == {"cpu.temp": 40.0, "cpu.load": 10.0}
    assert state.speeds == {"fan1": 1000, "fan2": 1000}
    assert state.duties == {"fan1": 55, "fan2": 35}
    assert rig.fans.duties == {"fan1": 55, "fan2": 35}


def test_choosing_and_editing_profiles_applies_them() -> None:
    rig = Rig([Profile("A").with_effect("fans", RED), Profile("B").with_effect("fans", BLUE)])
    rig.core.start()
    rig.core.choose_profile("B")
    assert rig.lights.played[-1] == ("fans", BLUE)
    assert rig.settings.settings.active_profile == "B"
    rig.core.save_profile(Profile("B").with_effect("fans", RED))
    assert rig.lights.played[-1] == ("fans", RED)
    played = len(rig.lights.played)
    rig.core.save_profile(Profile("A").with_effect("fans", BLUE))
    assert len(rig.lights.played) == played


def test_rules_switch_profiles_and_fall_back() -> None:
    rule = Rule("Busy", ReadingAbove("cpu.load", 80), "Hot", settle=0)
    rig = Rig([Profile("Calm").with_effect("fans", BLUE), Profile("Hot").with_effect("fans", RED)], [rule])
    rig.core.start()
    rig.sensors.readings["cpu.load"] = 95
    rig.advance(1)
    assert rig.core.state().showing == "Hot"
    assert rig.core.state().rule == "Busy"
    rig.core.choose_profile("Calm")
    assert rig.lights.played[-1] == ("fans", RED)
    rig.sensors.readings["cpu.load"] = 5
    rig.advance(1)
    assert rig.core.state().showing == "Calm"
    assert rig.lights.played[-1] == ("fans", BLUE)


def test_turning_automation_off_returns_to_the_chosen_profile() -> None:
    rule = Rule("Game", ProcessRunning("wow.exe"), "Hot", settle=0)
    rig = Rig([Profile("Calm"), Profile("Hot")], [rule])
    rig.processes.names = frozenset({"wow.exe"})
    rig.core.start()
    rig.advance(1)
    assert rig.core.state().showing == "Hot"
    rig.core.update_settings(replace(rig.core.settings, automation=False))
    assert rig.core.state().showing == "Calm"
    rig.advance(1)
    assert rig.core.state().showing == "Calm"


def test_profile_management_keeps_references_straight() -> None:
    rule = Rule("Game", ProcessRunning("wow.exe"), "A")
    rig = Rig([Profile("A"), Profile("B")], [rule])
    rig.core.start()
    rig.core.rename_profile("A", " Main ")
    state = rig.core.state()
    assert state.chosen == "Main" and state.showing == "Main"
    assert state.rules[0].profile == "Main"
    rig.core.create_profile("C")
    rig.core.duplicate_profile("C")
    rig.core.import_profile(Profile("C"))
    rig.core.delete_profile("Main")
    state = rig.core.state()
    assert [profile.name for profile in state.profiles] == ["B", "C", "C copy", "C 2"]
    assert state.chosen == "B"
    assert state.notice == (1, "Imported C 2")
    assert state.profile("C") == Profile("C")
    assert state.profile("Missing") is None


def test_rule_commands() -> None:
    rig = Rig([Profile("A")])
    rig.core.start()
    first = Rule("One", ProcessRunning("a"), "A")
    second = Rule("Two", ProcessRunning("b"), "A")
    rig.core.save_rule(first, None)
    rig.core.save_rule(second, None)
    rig.core.move_rule("Two", -1)
    rig.core.delete_rule("One")
    assert rig.core.state().rules == (second,)


def test_settings_and_autostart() -> None:
    rig = Rig([Profile("A", lighting={"fans": RED})])
    rig.core.start()
    rig.core.update_settings(replace(rig.core.settings, prefer_hardware=False, fan_floor=35))
    rig.advance(0)
    assert rig.lights.drawn
    assert rig.settings.settings.fan_floor == 35
    rig.core.set_autostart(True)
    assert rig.core.state().autostart


def test_devices_that_return_get_their_settings_again() -> None:
    rig = Rig([Profile("A").with_effect("fans", RED)])
    rig.core.start()
    rig.registry.fail(rig.lights, DeviceError("gone"))
    rig.advance(1)
    assert rig.core.state().statuses[0].online is False
    played = len(rig.lights.played)
    rig.advance(10)
    assert rig.core.state().statuses[0].online
    assert len(rig.lights.played) == played + 1


def test_shutdown_hands_off_the_fans() -> None:
    rig = Rig([Profile("A")])
    rig.core.start()
    rig.core.shutdown()
    assert rig.fans.duties == {"fan1": 50, "fan2": 50}
    assert rig.fans.closed


def test_choosing_a_missing_profile_is_refused() -> None:
    rig = Rig([Profile("A")])
    rig.core.start()
    with pytest.raises(ValidationError):
        rig.core.choose_profile("Nope")


def crash(_core: PrismCore) -> None:
    raise RuntimeError("boom")


def test_the_loop_runs_commands_publishes_state_and_reports_refusals() -> None:
    rig = Rig([Profile("A"), Profile("B")])
    notices: list[str] = []
    refused, crashed = threading.Event(), threading.Event()

    def publish(state: PrismState) -> None:
        if state.notice and state.notice[1] not in notices:
            notices.append(state.notice[1])
            (refused if state.chosen == "B" and len(notices) == 1 else crashed).set()

    loop = RuntimeLoop(rig.core)
    loop.subscribe(publish)
    loop.start()
    loop.submit(lambda core: core.choose_profile("B"))
    loop.submit(lambda core: core.choose_profile("Nope"))
    assert refused.wait(5)
    loop.submit(crash)
    assert crashed.wait(5)
    loop.stop()
    assert rig.fans.closed
    assert notices == ["there is no profile called 'Nope'", "Something went wrong; see the log for details"]


class Exploding(FakeLights):
    """Lights whose driver fails in a way nobody planned for."""

    def draw(self, zone_id: str, frame: Frame) -> None:
        raise RuntimeError("driver bug")

    def play(self, zone_id: str, effect: Effect) -> None:
        raise RuntimeError("driver bug")


def test_a_broken_lighting_driver_never_stops_the_fans() -> None:
    lights = Exploding(zones=[zone("fans")])
    rig = Rig([Profile("A", lighting={"fans": RED}, cooling={"fan1": FanSetting.fixed(70)})], lights=lights)
    rig.core.start()
    rig.advance(1)
    assert rig.fans.duties["fan1"] == 70
    assert rig.core.state().showing == "A"


def test_waking_from_suspend_resends_everything() -> None:
    rig = Rig([Profile("A").with_effect("fans", RED)])
    rig.core.start()
    rig.advance(1)
    played, written = len(rig.lights.played), len(rig.fans.history)
    rig.sleep.slept = True
    rig.advance(1)
    assert len(rig.lights.played) == played + 1
    assert len(rig.fans.history) > written


def test_editing_fans_does_not_restart_the_lighting() -> None:
    rig = Rig([Profile("A").with_effect("fans", RED)])
    rig.core.start()
    played = len(rig.lights.played)
    rig.core.edit_chosen(lambda profile: profile.with_fan("fan1", FanSetting.fixed(80)))
    assert len(rig.lights.played) == played
    rig.core.edit_chosen(lambda profile: profile.with_effect("fans", BLUE))
    assert rig.lights.played[-1] == ("fans", BLUE)


def test_the_loop_still_hands_off_the_fans_when_publishing_fails() -> None:
    rig = Rig([Profile("A")])
    loop = RuntimeLoop(rig.core)
    published = threading.Event()

    def broken(state: PrismState) -> None:
        published.set()
        raise RuntimeError("listener bug")

    loop.subscribe(broken)
    loop.start()
    assert published.wait(5)
    loop.stop()
    assert rig.fans.closed
    assert rig.fans.duties == {"fan1": 50, "fan2": 50}


class BrokenSensors(FakeSensors):
    def read(self) -> dict[str, float]:
        raise RuntimeError("probe vanished")


def test_a_failing_sensor_sends_its_fans_to_failsafe_not_stale_readings() -> None:
    sensors = FakeSensors({"cpu.temp": 30.0})
    curve = FanSetting.following("cpu.temp", FanCurve.of([(30, 30), (90, 90)]))
    rig = Rig([Profile("A", cooling={"fan1": curve})], sensors=sensors)
    rig.core.start()
    rig.advance(1)
    assert rig.fans.duties["fan1"] == 30
    rig.sensors.read = BrokenSensors().read  # type: ignore[method-assign]
    rig.advance(1)
    assert rig.fans.duties["fan1"] == FAILSAFE_DUTY
