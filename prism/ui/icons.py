from __future__ import annotations

from importlib import resources

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "dashboard": "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
    "lighting": "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z",
    "cooling": "M12 12c0-3 1-6 4-7 2 3 0 6-4 7zm0 0c3 0 6 1 7 4-3 2-6 0-7-4zm0 0c0 3-1 6-4 7-2-3 0-6 4-7zm0 "
    "0c-3 0-6-1-7-4 3-2 6 0 7 4z",
    "profiles": "M12 3 3 8l9 5 9-5zM3 13l9 5 9-5M3 18l9 5 9-5",
    "automation": "M13 2 4 14h7l-1 8 9-12h-7z",
    "settings": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8"
    " 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5"
    " 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2"
    " 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7"
    " 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1"
    "-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7"
    " 1.7 0 0 0-1.5 1z",
}


def _svg(path: str, color: str) -> bytes:
    """Wrap a stroke path in an SVG document.

    @param path: SVG path data on a 24 unit grid.
    @param color: the stroke colour.
    @return: the document.
    """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="{path}"/></svg>'
    ).encode()


def _render(svg: bytes, size: int) -> QPixmap:
    """Draw an SVG document at a size, sharp on high density screens.

    @param svg: the document.
    @param size: the edge length in device independent pixels.
    @return: the image.
    """
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg)).render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def nav_icon(name: str, normal: str, active: str, size: int = 18) -> QIcon:
    """Build a navigation icon that brightens when its page is open.

    @param name: one of the keys in PATHS.
    @param normal: the colour when inactive.
    @param active: the colour when its page is open.
    @param size: the edge length.
    @return: the icon.
    """
    icon = QIcon()
    icon.addPixmap(_render(_svg(PATHS[name], normal), size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_render(_svg(PATHS[name], active), size), QIcon.Mode.Normal, QIcon.State.On)
    return icon


def app_icon() -> QIcon:
    """@return: Prism's logo, at sizes for the window, the taskbar and the tray."""
    svg = resources.files("prism.ui").joinpath("assets/prism.svg").read_bytes()
    icon = QIcon()
    for size in (16, 22, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(svg, size))
    return icon
