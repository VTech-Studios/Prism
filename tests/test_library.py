import pytest

from prism.domain.automation import ProcessRunning, ReadingAbove, Rule, RuleEvaluator, SystemSnapshot
from prism.domain.color import Color
from prism.domain.devices import DeviceKind, FanChannel, LightingZone
from prism.domain.effects import Effect, EffectKind
from prism.domain.errors import ValidationError
from prism.domain.profile import Profile
from prism.services.automation import AutomationService
from prism.services.presets import starter_profiles
from prism.services.profiles import ProfileLibrary
from tests.fakes import MemoryProfileStore, MemoryRuleStore, zone


def library(*names: str) -> tuple[ProfileLibrary, MemoryProfileStore]:
    store = MemoryProfileStore([Profile(name) for name in names])
    return ProfileLibrary(store), store


def test_seed_only_fills_an_empty_library() -> None:
    lib, store = library()
    lib.seed([Profile("A")])
    lib.seed([Profile("B")])
    assert lib.names() == ["A"]
    assert store.saves == 1


def test_save_replaces_in_place_or_appends() -> None:
    lib, store = library("A", "B")
    red = Profile("A").with_effect("fans", Effect.static(Color(255, 0, 0)))
    lib.save(red)
    lib.save(Profile("C"))
    assert lib.names() == ["A", "B", "C"]
    assert lib.get("A") == red
    assert store.profiles == lib.profiles


def test_create_duplicate_rename_and_delete() -> None:
    lib, _ = library("Gaming")
    lib.create(" Night ")
    assert lib.duplicate("Gaming").name == "Gaming copy"
    assert lib.duplicate("Gaming").name == "Gaming copy 2"
    lib.rename("Night", "Late")
    lib.rename("Late", "Late")
    lib.delete("Gaming copy 2")
    assert lib.names() == ["Gaming", "Late", "Gaming copy"]


@pytest.mark.parametrize(
    "action",
    [
        lambda lib: lib.create("A"),
        lambda lib: lib.create(" "),
        lambda lib: lib.rename("A", "B"),
        lambda lib: lib.get("Missing"),
    ],
)
def test_refuses_clashes_and_missing_profiles(action: object) -> None:
    lib, _ = library("A", "B")
    with pytest.raises(ValidationError):
        action(lib)  # type: ignore[operator]


def test_the_last_profile_stays() -> None:
    lib, _ = library("Only")
    with pytest.raises(ValidationError):
        lib.delete("Only")


def test_imports_are_renamed_on_clash() -> None:
    lib, _ = library("Gaming")
    assert lib.add_imported(Profile("Gaming")).name == "Gaming 2"


def rules(*items: Rule) -> AutomationService:
    return AutomationService(MemoryRuleStore(list(items)), RuleEvaluator())


GAME = Rule("Game", ProcessRunning("wow.exe"), "Gaming", settle=0)
BUSY = Rule("Busy", ReadingAbove("cpu.load", 80), "Performance", settle=0)


def test_rules_are_saved_edited_moved_and_deleted() -> None:
    service = rules(GAME)
    service.save_rule(BUSY)
    with pytest.raises(ValidationError):
        service.save_rule(Rule("Game", ProcessRunning("x"), "P"))
    renamed = Rule("Gaming", ProcessRunning("wow.exe"), "Gaming")
    service.save_rule(renamed, replacing="Game")
    assert [rule.name for rule in service.rules] == ["Gaming", "Busy"]
    service.move_rule("Busy", -1)
    service.move_rule("Busy", -1)
    service.move_rule("Missing", 1)
    assert [rule.name for rule in service.rules] == ["Busy", "Gaming"]
    service.delete_rule("Busy")
    assert service.rules == [renamed]


def test_only_process_rules_need_the_process_list() -> None:
    assert not rules(BUSY).watches_processes()
    assert rules(BUSY, GAME).watches_processes()


def test_profile_renames_follow_into_rules() -> None:
    service = rules(GAME, BUSY)
    service.profile_renamed("Gaming", "Play")
    assert [rule.profile for rule in service.rules] == ["Play", "Performance"]


def test_choose_falls_back_and_skips_rules_for_missing_profiles() -> None:
    service = rules(GAME, BUSY)
    playing = SystemSnapshot({"cpu.load": 99}, frozenset({"wow.exe"}))
    assert service.choose(playing, 0, "Default", ["Default", "Gaming", "Performance"]) == ("Gaming", GAME)
    assert service.choose(playing, 1, "Default", ["Default", "Performance"]) == ("Performance", BUSY)
    assert service.choose(SystemSnapshot(), 2, "Default", ["Default"]) == ("Default", None)


def test_starter_profiles_suit_each_device() -> None:
    zones = [
        LightingZone("cpro:led1", "Fans", "CP", DeviceKind.FAN_CONTROLLER, 72),
        LightingZone("aio:led", "Pump", "AIO", DeviceKind.COOLER, 16),
        LightingZone("orgb:gpu", "GPU", "OpenRGB", DeviceKind.GPU, 4),
        zone("plain", hardware=set(), streams=False),
        zone("static-only", hardware={EffectKind.STATIC}, streams=False),
    ]
    fans = [FanChannel("cpro:fan1", "Fan 1", "CP"), FanChannel("aio:fan1", "Rad 1", "AIO")]
    default, quiet, performance = starter_profiles(zones, fans)
    assert [default.name, quiet.name, performance.name] == ["Default", "Quiet", "Performance"]
    assert default.lighting["cpro:led1"].kind is EffectKind.RAINBOW_WAVE
    assert default.lighting["aio:led"].kind is EffectKind.TEMPERATURE
    assert default.lighting["orgb:gpu"].kind is EffectKind.BREATHING
    assert default.lighting["plain"].kind is EffectKind.OFF
    assert default.lighting["static-only"].kind is EffectKind.STATIC
    assert quiet.lighting["cpro:led1"].brightness < 1
    assert default.cooling["cpro:fan1"].sensor == "cpu.temp"
    assert default.cooling["aio:fan1"].sensor == "liquid.temp"
    assert performance.pump is not None and performance.pump.value == "extreme"
