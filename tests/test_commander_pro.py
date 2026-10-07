from pathlib import Path

import pytest

from prism.domain.color import Color
from prism.domain.effects import Direction, Effect, EffectKind, Speed
from prism.domain.errors import DeviceError
from prism.infrastructure.commander_pro import (
    CommanderPro,
    effect_colors,
    effect_reports,
    frame_reports,
)
from prism.infrastructure.hwmon import HwmonFans, find_hwmon
from tests.fakes import FakeTransport

RED = Color(255, 0, 0)
BLUE = Color(0, 0, 255)


@pytest.fixture
def hwmon(tmp_path: Path) -> Path:
    directory = tmp_path / "hwmon2"
    directory.mkdir()
    (directory / "name").write_text("corsaircpro\n")
    for header, rpm in ((1, "1650"), (3, "1640"), (6, "oops")):
        (directory / f"fan{header}_label").write_text(f"fan{header} 4pin\n")
        (directory / f"fan{header}_input").write_text(rpm)
    return directory


def make(hwmon: Path, transport: FakeTransport | None = None) -> tuple[CommanderPro, FakeTransport]:
    transport = transport or FakeTransport()
    return CommanderPro(transport, HwmonFans(hwmon), {1: 72, 2: 0}), transport


def test_hardware_effect_spans_every_led_in_icue_order() -> None:
    effect = Effect(EffectKind.COLOR_WAVE, (RED, BLUE), speed=Speed.SLOW, direction=Direction.BACKWARD)
    reports = effect_reports(0, 72, effect)
    assert [report[0] for report in reports] == [0x37, 0x34, 0x38, 0x35, 0x33]
    assert reports[2] == bytes([0x38, 0, 0x01])
    assert reports[3] == bytes([0x35, 0, 0, 72, 0x03, 0x02, 0x00, 0x00, 0xFF, 255, 0, 0, 0, 0, 255])


def test_rainbows_let_the_controller_pick_colours() -> None:
    config = effect_reports(1, 72, Effect(EffectKind.RAINBOW_WAVE))[3]
    assert config[:9] == bytes([0x35, 1, 0, 72, 0x00, 0x01, 0x01, 0x01, 0xFF])
    assert len(config) == 9


def test_effect_colours_bake_in_brightness_and_pad_blink() -> None:
    assert effect_colors(Effect.off()) == (Color(0, 0, 0),)
    dim = Effect(EffectKind.STATIC, (RED,), brightness=0.5)
    assert effect_colors(dim) == (Color(128, 0, 0),)
    assert effect_colors(Effect(EffectKind.BLINK, (RED,))) == (RED, Color(0, 0, 0))


def test_frames_go_as_colour_planes_in_chunks_of_fifty() -> None:
    reports = frame_reports(0, (RED,) * 72)
    assert [report[0] for report in reports] == [0x32] * 6 + [0x33]
    assert reports[0][:5] == bytes([0x32, 0, 0, 50, 0])
    assert reports[0][5:] == bytes([255] * 50)
    assert reports[1][5:] == bytes(50)
    assert reports[3][:5] == bytes([0x32, 0, 50, 22, 0])


def test_zones_and_fans_come_from_the_layout_and_hwmon(hwmon: Path) -> None:
    device, _ = make(hwmon)
    zones = device.zones()
    assert [(z.id, z.led_count) for z in zones] == [("cpro:led1", 72)]
    assert EffectKind.RAINBOW_WAVE in zones[0].hardware_effects
    assert [fan.id for fan in device.fans()] == ["cpro:fan1", "cpro:fan3", "cpro:fan6"]
    assert device.speeds() == {"cpro:fan1": 1650, "cpro:fan3": 1640}
    assert device.name == "Corsair Commander Pro"


def test_play_and_draw_switch_the_port_mode(hwmon: Path) -> None:
    device, transport = make(hwmon)
    device.draw("cpro:led1", (RED,) * 72)
    device.draw("cpro:led1", (RED,) * 72)
    port_switches = [report for report in transport.reports if report[0] == 0x38]
    assert port_switches == [bytes([0x38, 0, 0x02])]
    device.play("cpro:led1", Effect.static(RED))
    device.draw("cpro:led1", (BLUE,) * 72)
    port_switches = [report for report in transport.reports if report[0] == 0x38]
    assert port_switches[-1] == bytes([0x38, 0, 0x02])


def test_set_duty_clamps_and_addresses_the_right_header(hwmon: Path) -> None:
    device, transport = make(hwmon)
    device.set_duty("cpro:fan6", 140)
    assert transport.reports == [bytes([0x23, 5, 100])]


def test_refused_and_unknown_commands_raise(hwmon: Path) -> None:
    device, _ = make(hwmon, FakeTransport(status=0xFF))
    with pytest.raises(DeviceError):
        device.set_duty("cpro:fan1", 50)
    with pytest.raises(DeviceError):
        device.play("cpro:led2", Effect.off())


def test_close_releases_the_transport(hwmon: Path) -> None:
    device, transport = make(hwmon)
    device.close()
    assert transport.closed


def test_find_hwmon(hwmon: Path) -> None:
    assert find_hwmon("corsaircpro", hwmon.parent) == hwmon
    assert find_hwmon("nothing", hwmon.parent) is None
