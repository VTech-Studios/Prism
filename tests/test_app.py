from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from prism.app import parse_args
from prism.config import Paths
from prism.domain.cooling import FanCurve
from prism.ui.single_instance import InstanceServer, already_running
from prism.ui.theme import Palette
from prism.ui.widgets.charts import CurveEditor
from prism.wiring import build, connectors, sensor_sources


def test_paths_follow_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    paths = Paths.from_environment()
    assert paths.settings == tmp_path / "config" / "prism" / "settings.json"
    assert paths.profiles.name == "profiles.json"
    assert paths.rules.name == "rules.json"
    assert paths.log == tmp_path / "state" / "prism" / "prism.log"


def test_arguments() -> None:
    assert parse_args(["--hidden"]).hidden
    assert not parse_args([]).debug


def test_build_wires_everything_without_touching_devices(qtbot: QtBot, tmp_path: Path) -> None:
    app = build(Paths(tmp_path / "config", tmp_path / "state"), hide_on_close=False)
    qtbot.addWidget(app.window)
    assert app.settings.active_profile == "Default"
    assert [connector.name for connector in connectors(app.settings)] == [
        "Corsair Commander Pro",
        "Corsair Hydro Platinum AIO",
        "OpenRGB",
    ]
    assert sensor_sources()


def test_a_second_launch_wakes_the_first(qtbot: QtBot) -> None:
    woken: list[bool] = []
    server = InstanceServer(lambda: woken.append(True), name="prism-test-instance")
    assert already_running("prism-test-instance")
    qtbot.waitUntil(lambda: bool(woken), timeout=2000)
    server.close()
    assert not already_running("prism-test-instance")


def test_curve_points_can_be_dragged(qtbot: QtBot) -> None:
    editor = CurveEditor(Palette())
    qtbot.addWidget(editor)
    editor.resize(600, 300)
    curve = FanCurve.of([(30, 30), (60, 60), (90, 100)])
    editor.set_curve(curve, 45.0)
    editor.show()
    start = editor._to_screen(60, 60).toPoint()
    end = editor._to_screen(60, 80).toPoint()
    with qtbot.waitSignal(editor.curveChanged) as changed:
        QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor, end)
        QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=end)
    moved = changed.args[0] if changed.args else None
    assert isinstance(moved, FanCurve)
    assert moved.points[1].duty == pytest.approx(80, abs=2)
    assert editor._to_point(QPointF(editor._to_screen(40, 50))).temperature == 40
    editor.grab()
