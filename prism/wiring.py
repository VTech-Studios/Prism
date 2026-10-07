from __future__ import annotations

import shutil
import time
from dataclasses import dataclass

from .config import Paths
from .domain.automation import RuleEvaluator
from .domain.cooling import FALLBACK
from .domain.rendering import Renderer
from .domain.settings import Settings
from .infrastructure.autostart import XdgAutostart
from .infrastructure.commander_pro import PRODUCT_ID, REPORT_SIZE, VENDOR_ID, CommanderPro
from .infrastructure.hid import HidapiTransport
from .infrastructure.hwmon import HwmonFans, find_hwmon
from .infrastructure.hydro_platinum import HydroPlatinum, find_liquidctl
from .infrastructure.openrgb import OpenRgbDetectors, OpenRgbLighting, OpenRgbServer
from .infrastructure.process import SubprocessRunner
from .infrastructure.sensors import BackgroundSensors, CpuSensors, NvidiaSensors, PsutilProcesses
from .infrastructure.sleep import BootClockSleepWatch
from .infrastructure.stores import (
    JsonFile,
    JsonProfileFiles,
    JsonProfileStore,
    JsonRuleStore,
    JsonSettingsStore,
)
from .ports import SensorSource
from .services.automation import AutomationService
from .services.cooling import CoolingController
from .services.core import PrismCore
from .services.lighting import LightingEngine
from .services.loop import RuntimeLoop
from .services.profiles import ProfileLibrary
from .services.registry import Connector, DeviceRegistry
from .services.telemetry import Telemetry
from .ui.client import PrismClient
from .ui.main_window import MainWindow
from .ui.pages.automation import AutomationPage
from .ui.pages.cooling import CoolingPage
from .ui.pages.dashboard import DashboardPage
from .ui.pages.lighting import LightingPage
from .ui.pages.profiles import ProfilesPage
from .ui.pages.settings import SettingsPage
from .ui.theme import Palette


@dataclass(frozen=True)
class Application:
    window: MainWindow
    client: PrismClient
    loop: RuntimeLoop
    settings: Settings


def connectors(settings: Settings) -> list[Connector]:
    """Describe how to reach each supported device.

    One OpenRGB server handle is shared by every attempt, so it is only ever
    started once. Its detection can reset the Corsair devices, but its arrival
    bumps the registry's generation and everything is sent again.

    @param settings: the user's settings, for the LED layout and OpenRGB server.
    @return: one connector per device.
    """
    server = OpenRgbServer(settings.openrgb_host, settings.openrgb_port, settings.launch_openrgb)
    return [
        Connector(
            "Corsair Commander Pro",
            lambda: CommanderPro(
                HidapiTransport(VENDOR_ID, PRODUCT_ID, REPORT_SIZE),
                HwmonFans(find_hwmon("corsaircpro")),
                settings.channel_leds,
            ),
        ),
        Connector("Corsair Hydro Platinum AIO", lambda: HydroPlatinum(lambda: find_liquidctl("Platinum"))),
        Connector(
            "OpenRGB",
            lambda: OpenRgbLighting(server.connect(), settings.openrgb_excluded),
        ),
    ]


def sensor_sources() -> list[SensorSource]:
    """@return: the sensors that do not belong to a device: the CPU, and the GPU when nvidia-smi exists."""
    sources: list[SensorSource] = [CpuSensors()]
    if shutil.which("nvidia-smi"):
        sources.append(BackgroundSensors(NvidiaSensors(SubprocessRunner())))
    return sources


def build_core(paths: Paths, settings_store: JsonSettingsStore) -> PrismCore:
    """Wire the core to the real devices, sensors and files.

    @param paths: where files live.
    @param settings_store: the settings, already read once for the hardware layout.
    @return: the core, not yet started.
    """
    settings = settings_store.load()
    registry = DeviceRegistry(connectors(settings))
    return PrismCore(
        registry=registry,
        lighting=LightingEngine(registry, Renderer(), settings.prefer_hardware),
        cooling=CoolingController(registry, settings.fan_floor, FALLBACK),
        telemetry=Telemetry(registry, sensor_sources(), PsutilProcesses()),
        library=ProfileLibrary(JsonProfileStore(JsonFile(paths.profiles))),
        automation=AutomationService(JsonRuleStore(JsonFile(paths.rules)), RuleEvaluator()),
        settings_store=settings_store,
        autostart=XdgAutostart(),
        sleep=BootClockSleepWatch(),
        clock=time.monotonic,
    )


def build(paths: Paths, hide_on_close: bool) -> Application:
    """Wire the whole application.

    @param paths: where files live.
    @param hide_on_close: whether closing the window hides it to the tray.
    @return: the application, with the runtime loop not yet started.
    """
    settings_store = JsonSettingsStore(JsonFile(paths.settings))
    core = build_core(paths, settings_store)
    loop = RuntimeLoop(core)
    client = PrismClient(loop.submit)
    loop.subscribe(client.publish)
    palette = Palette()
    renderer = Renderer()
    pages = [
        ("dashboard", "Dashboard", DashboardPage(palette)),
        ("lighting", "Lighting", LightingPage(client, renderer, palette)),
        ("cooling", "Cooling", CoolingPage(client, palette)),
        ("profiles", "Profiles", ProfilesPage(client, JsonProfileFiles())),
        ("automation", "Automation", AutomationPage(client)),
        ("settings", "Settings", SettingsPage(client, OpenRgbDetectors())),
    ]
    window = MainWindow(client, pages, palette, hide_on_close)
    return Application(window, client, loop, core.settings)
