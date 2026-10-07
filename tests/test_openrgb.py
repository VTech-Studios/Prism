import json
from pathlib import Path

import pytest

from prism.domain.color import Color
from prism.domain.devices import DeviceKind
from prism.domain.effects import Direction, Effect, EffectKind, Speed
from prism.domain.errors import DeviceError
from prism.infrastructure.openrgb import OpenRgbDetectors, OpenRgbLighting, find_mode, slug, tune_mode
from tests.fakes import FakeMode, FakeOrgbClient, FakeOrgbDevice

ORANGE = Color(255, 40, 0)


def ram(name: str = "ENE DRAM") -> FakeOrgbDevice:
    return FakeOrgbDevice(
        name,
        1,
        [
            FakeMode("Direct", color_mode=1),
            FakeMode("Static", color_mode=1),
            FakeMode("Rainbow", flags=1 | 2, speed_min=0, speed_max=4),
            FakeMode(
                "Breathing",
                flags=1 | 16,
                speed_min=4,
                speed_max=0,
                brightness_max=100,
                colors_min=1,
                colors_max=2,
                color_mode=2,
            ),
        ],
    )


def gpu() -> FakeOrgbDevice:
    return FakeOrgbDevice("ASUS ROG STRIX GTX 1080", 2, [FakeMode("Static", color_mode=1)])


def lighting() -> tuple[OpenRgbLighting, FakeOrgbClient]:
    client = FakeOrgbClient([ram(), ram(), gpu(), FakeOrgbDevice("Corsair Commander Pro", 3, [])])
    return OpenRgbLighting(client, ["commander pro"]), client


def test_slug() -> None:
    assert slug("ASUS ROG STRIX GTX 1080!") == "asus-rog-strix-gtx-1080"


def test_zones_skip_excluded_devices_and_get_stable_ids() -> None:
    orgb, _ = lighting()
    zones = orgb.zones()
    assert [z.id for z in zones] == ["orgb:ene-dram", "orgb:ene-dram-2", "orgb:asus-rog-strix-gtx-1080"]
    assert zones[0].kind is DeviceKind.MEMORY
    assert zones[0].hardware_effects == {EffectKind.STATIC, EffectKind.RAINBOW_WAVE, EffectKind.BREATHING}
    assert zones[0].streams
    assert not zones[2].streams


def test_find_mode_prefers_earlier_names() -> None:
    modes = [FakeMode("Rainbow"), FakeMode("Rainbow Wave")]
    assert find_mode(modes, ["rainbow wave", "rainbow"]) is modes[1]
    assert find_mode(modes, ["off"]) is None


def test_tune_mode_maps_speed_direction_brightness_and_colours() -> None:
    breathing = ram().modes[3]
    effect = Effect(EffectKind.BREATHING, (ORANGE,), speed=Speed.FAST, brightness=0.5)
    tuned = tune_mode(breathing, effect)
    assert breathing.speed is None
    assert tuned.speed == 1
    assert tuned.brightness == 50
    assert tuned.colors is not None and len(tuned.colors) == 1
    rainbow = tune_mode(ram().modes[2], Effect(EffectKind.RAINBOW_WAVE, direction=Direction.BACKWARD))
    assert (rainbow.speed, rainbow.direction) == (2, 0)


def test_play_sets_the_mode_and_colours_per_led_modes() -> None:
    orgb, client = lighting()
    orgb.play("orgb:ene-dram", Effect.static(ORANGE))
    calls = client.devices[0].calls
    assert calls[0][0] == "mode" and calls[0][1].name == "Static"
    assert calls[1][0] == "color"
    with pytest.raises(DeviceError):
        orgb.play("orgb:asus-rog-strix-gtx-1080", Effect(EffectKind.RAINBOW_WAVE))


def test_draw_switches_to_direct_once() -> None:
    orgb, client = lighting()
    orgb.draw("orgb:ene-dram", (ORANGE,) * 8)
    orgb.draw("orgb:ene-dram", (ORANGE,) * 8)
    kinds = [call[0] for call in client.devices[0].calls]
    assert kinds == ["mode", "colors", "colors"]
    with pytest.raises(DeviceError):
        orgb.draw("orgb:missing", ())


def test_client_failures_become_device_errors() -> None:
    orgb, client = lighting()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ConnectionResetError("closed")

    client.devices[0].set_colors = broken  # type: ignore[method-assign]
    with pytest.raises(DeviceError):
        orgb.draw("orgb:ene-dram", (ORANGE,))
    orgb.close()
    assert client.disconnected


def test_detectors_are_switched_off_with_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "OpenRGB.json"
    path.write_text(json.dumps({"Detectors": {"detectors": {"Corsair Commander Pro": True, "ENE": True}}}))
    detectors = OpenRgbDetectors(["Corsair Commander Pro", "Corsair Hydro H115i Platinum"], path)
    assert not detectors.is_off()
    detectors.turn_off()
    saved = json.loads(path.read_text())["Detectors"]["detectors"]
    assert saved == {"Corsair Commander Pro": False, "ENE": True, "Corsair Hydro H115i Platinum": False}
    assert detectors.is_off()
    assert path.with_suffix(".json.prism-backup").exists()


def test_detectors_need_a_readable_config(tmp_path: Path) -> None:
    detectors = OpenRgbDetectors(["x"], tmp_path / "missing.json")
    assert not detectors.is_off()
    with pytest.raises(DeviceError):
        detectors.turn_off()
