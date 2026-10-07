from __future__ import annotations

from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"

ENTRY = """[Desktop Entry]
Type=Application
Name=Prism
Comment=RGB lighting, fan speeds and cooling profiles
Exec=prism --hidden
Icon=prism
Terminal=false
X-GNOME-Autostart-enabled=true
"""


class XdgAutostart:
    """Starts Prism at login through an XDG autostart entry, which every desktop honours."""

    def __init__(self, directory: Path = AUTOSTART_DIR) -> None:
        self._entry = directory / "prism.desktop"

    def enabled(self) -> bool:
        """@return: whether the autostart entry exists."""
        return self._entry.exists()

    def set_enabled(self, enabled: bool) -> None:
        """Add or remove the autostart entry.

        @param enabled: whether Prism should start at login.
        """
        if enabled:
            self._entry.parent.mkdir(parents=True, exist_ok=True)
            self._entry.write_text(ENTRY)
        else:
            self._entry.unlink(missing_ok=True)
