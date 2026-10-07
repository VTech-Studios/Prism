from __future__ import annotations

import argparse
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__
from .config import Paths
from .ui.icons import app_icon
from .ui.single_instance import InstanceServer, already_running
from .ui.theme import Palette, stylesheet
from .ui.tray import Tray
from .wiring import build


def parse_args(argv: list[str]) -> argparse.Namespace:
    """@return: the command line options."""
    parser = argparse.ArgumentParser(
        prog="prism", description="RGB lighting, fan speeds and cooling profiles."
    )
    parser.add_argument("--hidden", action="store_true", help="start in the tray without opening the window")
    parser.add_argument("--debug", action="store_true", help="log device traffic and decisions")
    parser.add_argument("--version", action="version", version=f"prism {__version__}")
    return parser.parse_args(argv)


def configure_logging(paths: Paths, debug: bool) -> None:
    """Log to a small rotating file, and to the terminal when debugging.

    @param paths: where the log lives.
    @param debug: whether to log in detail.
    """
    paths.state.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(paths.log, maxBytes=1_000_000, backupCount=2)]
    if debug:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main(argv: list[str] | None = None) -> int:
    """Start Prism, or wake the copy that is already running.

    @param argv: the command line, without the program name.
    @return: the exit status.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Prism")
    app.setDesktopFileName("prism")
    app.setWindowIcon(app_icon())
    if already_running():
        return 0
    paths = Paths.from_environment()
    configure_logging(paths, args.debug)
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet(stylesheet(Palette()))
    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not has_tray)

    prism = build(paths, hide_on_close=has_tray)
    window = prism.window

    def show_window() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def quit_app() -> None:
        window.quitting = True
        app.quit()

    server = InstanceServer(show_window)
    tray = Tray(prism.client, show_window, quit_app) if has_tray else None
    if tray is not None:
        tray.show()
    app.aboutToQuit.connect(prism.loop.stop)
    signal.signal(signal.SIGINT, lambda *_: quit_app())
    signal.signal(signal.SIGTERM, lambda *_: quit_app())
    prism.loop.start()
    if not (args.hidden or prism.settings.start_hidden) or tray is None:
        show_window()
    status = app.exec()
    server.close()
    return status
