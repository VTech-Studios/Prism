from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from prism.domain.cooling import FanMode, FanSetting
from prism.domain.effects import EffectKind
from prism.domain.errors import ValidationError
from prism.domain.profile import Profile
from prism.domain.rendering import Renderer
from prism.services.loop import Command
from prism.services.state import PrismState
from prism.ui.client import PrismClient
from prism.ui.main_window import MainWindow
from prism.ui.pages.automation import AutomationPage, RuleDialog
from prism.ui.pages.cooling import CoolingPage, preset_name
from prism.ui.pages.dashboard import DashboardPage
from prism.ui.pages.lighting import LightingPage
from prism.ui.pages.profiles import ProfilesPage, summary
from prism.ui.pages.settings import SettingsPage
from prism.ui.theme import Palette, stylesheet
from prism.ui.tray import Tray
from tests.rig import Rig, showroom


class Detectors:
    def __init__(self, off: bool = False, fail: bool = False) -> None:
        self.off = off
        self.fail = fail

    def is_off(self) -> bool:
        return self.off

    def turn_off(self) -> None:
        if self.fail:
            raise ValidationError("no config")
        self.off = True


class Files:
    def __init__(self) -> None:
        self.exported: list[tuple[str, Path]] = []

    def export(self, profile: Profile, path: Path) -> None:
        self.exported.append((profile.name, path))

    def read(self, path: Path) -> Profile:
        return Profile("Imported")


@dataclass
class Ui:
    rig: Rig
    client: PrismClient

    def state(self) -> PrismState:
        assert self.client.state is not None
        return self.client.state

    def chosen(self) -> Profile:
        profile = self.state().profile(self.state().chosen)
        assert profile is not None
        return profile


@pytest.fixture
def ui(qtbot: QtBot) -> Ui:
    rig = showroom()
    client: PrismClient

    def submit(command: Command) -> None:
        command(rig.core)
        client.publish(rig.core.state())

    client = PrismClient(submit)
    client.publish(rig.core.state())
    return Ui(rig, client)


def window(ui: Ui, qtbot: QtBot) -> MainWindow:
    palette = Palette()
    pages = [
        ("dashboard", "Dashboard", DashboardPage(palette)),
        ("lighting", "Lighting", LightingPage(ui.client, Renderer(), palette)),
        ("cooling", "Cooling", CoolingPage(ui.client, palette)),
        ("profiles", "Profiles", ProfilesPage(ui.client, Files())),
        ("automation", "Automation", AutomationPage(ui.client)),
        ("settings", "Settings", SettingsPage(ui.client, Detectors())),
    ]
    main = MainWindow(ui.client, pages, palette, hide_on_close=True)
    main.setStyleSheet(stylesheet(palette))
    qtbot.addWidget(main)
    main.refresh(ui.state())
    return main


def test_every_page_draws_from_a_real_looking_state(ui: Ui, qtbot: QtBot) -> None:
    main = window(ui, qtbot)
    main.show()
    for index in range(6):
        main._stack.setCurrentIndex(index)
        main.refresh(ui.state())
        main.grab()
    assert main._profiles.currentText() == "Default"


def test_dashboard_tracks_readings(ui: Ui, qtbot: QtBot) -> None:
    page = DashboardPage(Palette())
    qtbot.addWidget(page)
    page.refresh(ui.state())
    ui.rig.sensors.readings["cpu.temp"] = 71.0
    ui.rig.advance(1)
    page.refresh(ui.rig.core.state())
    assert page._sensor_cards["cpu.temp"]._value.text() == "71"
    assert "RPM" in page._fan_rows["cpro:fan1"]._speed.text()


def test_lighting_edits_the_chosen_profile(ui: Ui, qtbot: QtBot) -> None:
    page = LightingPage(ui.client, Renderer(), Palette())
    qtbot.addWidget(page)
    page.refresh(ui.state())
    page._editor._chip_buttons[EffectKind.COLOR_WAVE].click()
    effect = ui.chosen().lighting["cpro:led1"]
    assert effect.kind is EffectKind.COLOR_WAVE
    page._editor._speed.changed.emit(effect.speed.__class__("fast"))
    assert ui.chosen().lighting["cpro:led1"].speed.value == "fast"
    page._apply_everywhere()
    lighting = ui.chosen().lighting
    assert lighting["orgb:ram"].kind is EffectKind.COLOR_WAVE
    assert lighting["orgb:gpu"].kind is EffectKind.BREATHING
    page._unset()
    assert "cpro:led1" not in ui.chosen().lighting
    page._select("orgb:gpu")
    assert set(page._editor._chip_buttons) == {EffectKind.STATIC, EffectKind.BREATHING}


def test_lighting_brightness_and_gauge(ui: Ui, qtbot: QtBot) -> None:
    page = LightingPage(ui.client, Renderer(), Palette())
    qtbot.addWidget(page)
    page.refresh(ui.state())
    page._select("aio:led")
    editor = page._editor
    editor._brightness.setValue(50)
    editor._commit_brightness()
    assert ui.chosen().lighting["aio:led"].brightness == 0.5
    editor._hot.setValue(50)
    editor._commit_gauge()
    gauge = ui.chosen().lighting["aio:led"].gauge
    assert gauge is not None and gauge.hot == 50


def test_cooling_switches_modes_and_presets(ui: Ui, qtbot: QtBot) -> None:
    page = CoolingPage(ui.client, Palette())
    qtbot.addWidget(page)
    page.refresh(ui.state())
    page._editor._mode.changed.emit(FanMode.FIXED)
    assert ui.chosen().cooling["cpro:fan1"] == FanSetting.fixed(50)
    page._editor._duty.setValue(70)
    page._editor._duty.sliderReleased.emit()
    assert ui.chosen().cooling["cpro:fan1"].duty == 70
    page._apply_everywhere()
    assert all(setting.duty == 70 for setting in ui.chosen().cooling.values())
    page._editor._mode.changed.emit(FanMode.CURVE)
    page._editor._preset.setCurrentText("Quiet")
    page._editor._pick_preset()
    assert preset_name(ui.chosen().cooling["cpro:fan1"].curve) == "Quiet"
    page._unset()
    assert "cpro:fan1" not in ui.chosen().cooling
    assert page._pump_card.isVisibleTo(page)


def test_profiles_page_actions(ui: Ui, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("/tmp/p.json", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("/tmp/p.json", ""))
    files = Files()
    page = ProfilesPage(ui.client, files)
    qtbot.addWidget(page)
    page.refresh(ui.state())
    assert page._grid.count() == 3
    performance = ui.state().profile("Performance")
    assert performance is not None
    page._export(performance)
    assert files.exported == [("Performance", Path("/tmp/p.json"))]
    page._import()
    assert ui.state().profile("Imported") is not None
    assert summary(performance).startswith("4 lighting zones")
    page.refresh(ui.state())
    assert page._grid.count() == 4


def test_automation_page_and_rule_dialog(ui: Ui, qtbot: QtBot) -> None:
    page = AutomationPage(ui.client)
    qtbot.addWidget(page)
    page.refresh(ui.state())
    assert "No rule applies" in page._status.text()
    page._toggle.toggled.emit(False)
    assert ui.state().settings.automation is False
    page.refresh(ui.state())
    assert page._status.text().startswith("Off")
    dialog = RuleDialog(ui.state(), ui.state().rules[0])
    qtbot.addWidget(dialog)
    dialog._name.setText("Raid night")
    dialog._accept()
    assert dialog.result_rule is not None and dialog.result_rule.name == "Raid night"
    empty = RuleDialog(ui.state(), None)
    qtbot.addWidget(empty)
    empty._accept()
    assert empty.result_rule is None
    assert not empty._error.isHidden()
    empty._name.setText("Busy")
    empty._kind.setCurrentIndex(0)
    empty._accept()
    assert empty.result_rule is not None
    assert empty.result_rule.condition.describe() == "CPU above 80"


def test_settings_page_writes_through_bindings(ui: Ui, qtbot: QtBot) -> None:
    detectors = Detectors()
    page = SettingsPage(ui.client, detectors)
    qtbot.addWidget(page)
    page.refresh(ui.state())
    toggle, _ = page._toggles[1]
    toggle.toggled.emit(False)
    assert ui.state().settings.prefer_hardware is False
    spin, _ = page._spins[1]
    spin.setValue(35)
    spin.editingFinished.emit()
    assert ui.state().settings.fan_floor == 35
    page._hide_corsair()
    assert detectors.off
    assert not page._detector_button.isEnabled()
    failing = SettingsPage(ui.client, Detectors(fail=True))
    qtbot.addWidget(failing)
    failing._hide_corsair()
    notice = ui.state().notice
    assert notice is not None and notice[1] == "no config"


def test_closing_hides_to_the_tray_and_shows_notices(ui: Ui, qtbot: QtBot) -> None:
    main = window(ui, qtbot)
    main.show()
    main.close()
    assert not main.isVisible()
    assert ui.state().notice is not None
    main.refresh(ui.state())
    assert main._toast.text() == "Prism is still running in the tray"
    main.quitting = True
    main.close()


def test_tray_menu_lists_profiles(ui: Ui, qtbot: QtBot) -> None:
    shown: list[bool] = []
    tray = Tray(ui.client, lambda: shown.append(True), lambda: None)
    tray.refresh(ui.state())
    captions = [action.text() for action in tray.contextMenu().actions()]
    assert captions[:1] == ["Open Prism"]
    assert {"Default", "Quiet", "Performance", "Automatic switching", "Quit"} <= set(captions)
    quiet = next(action for action in tray.contextMenu().actions() if action.text() == "Quiet")
    quiet.trigger()
    assert ui.state().chosen == "Quiet"
    tray._clicked(tray.ActivationReason.Trigger)
    assert shown == [True]
