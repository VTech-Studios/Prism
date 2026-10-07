import json
from pathlib import Path

import pytest

from prism.domain.automation import ProcessRunning, ReadingAbove, Rule
from prism.domain.color import Color
from prism.domain.cooling import PRESET_CURVES, FanSetting, PumpMode
from prism.domain.effects import Direction, Effect, EffectKind, Gauge, Speed
from prism.domain.errors import ValidationError
from prism.domain.profile import Profile
from prism.domain.settings import Settings
from prism.infrastructure.autostart import XdgAutostart
from prism.infrastructure.codec import decode_condition
from prism.infrastructure.stores import JsonFile, JsonProfileStore, JsonRuleStore, JsonSettingsStore

PROFILE = Profile(
    "Gaming",
    lighting={
        "cpro:led1": Effect(
            EffectKind.COLOR_WAVE, (Color(255, 0, 0), Color(0, 0, 255)), Speed.FAST, Direction.BACKWARD
        ),
        "aio:led": Effect(
            EffectKind.TEMPERATURE,
            (Color(0, 255, 0), Color(255, 165, 0), Color(255, 0, 0)),
            gauge=Gauge("liquid.temp", 30, 40),
            brightness=0.8,
        ),
    },
    cooling={
        "cpro:fan1": FanSetting.fixed(70),
        "aio:fan1": FanSetting.following("liquid.temp", PRESET_CURVES["Quiet"]),
    },
    pump=PumpMode.EXTREME,
)


def test_profiles_round_trip(tmp_path: Path) -> None:
    store = JsonProfileStore(JsonFile(tmp_path / "profiles.json"))
    assert store.load() == []
    store.save([PROFILE, Profile("Empty")])
    assert store.load() == [PROFILE, Profile("Empty")]


def test_rules_round_trip(tmp_path: Path) -> None:
    store = JsonRuleStore(JsonFile(tmp_path / "rules.json"))
    rules = [
        Rule("Busy", ReadingAbove("cpu.load", 80, "CPU load"), "Performance", settle=10),
        Rule("WoW", ProcessRunning("wow.exe"), "Gaming", enabled=False),
    ]
    store.save(rules)
    assert store.load() == rules


def test_settings_round_trip_and_ignore_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = JsonSettingsStore(JsonFile(path))
    assert store.load() == Settings()
    settings = Settings(active_profile="Gaming", channel_leds={1: 48, 2: 12}, openrgb_excluded=("Foo",))
    store.save(settings)
    assert store.load() == settings
    data = json.loads(path.read_text())
    data["from_the_future"] = True
    path.write_text(json.dumps(data))
    assert store.load() == settings


def test_invalid_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"fan_floor": 99}))
    assert JsonSettingsStore(JsonFile(path)).load() == Settings()


def test_damaged_files_are_kept_aside(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not json")
    assert JsonProfileStore(JsonFile(path)).load() == []
    assert path.with_suffix(".damaged").read_text() == "{not json"


def test_unreadable_items_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([{"name": "Good"}, {"name": " "}, {"nope": 1}]))
    assert JsonProfileStore(JsonFile(path)).load() == [Profile("Good")]


def test_unknown_conditions_are_rejected() -> None:
    with pytest.raises(ValidationError):
        decode_condition({"kind": "moon_phase"})


def test_autostart_entry(tmp_path: Path) -> None:
    autostart = XdgAutostart(tmp_path / "autostart")
    assert not autostart.enabled()
    autostart.set_enabled(True)
    assert "Exec=prism --hidden" in (tmp_path / "autostart" / "prism.desktop").read_text()
    assert autostart.enabled()
    autostart.set_enabled(False)
    autostart.set_enabled(False)
    assert not autostart.enabled()
