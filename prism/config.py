from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Where Prism keeps its files, following the XDG base directory rules."""

    config: Path
    state: Path

    @classmethod
    def from_environment(cls) -> Paths:
        """@return: the paths, honouring XDG_CONFIG_HOME and XDG_STATE_HOME when set."""
        home = Path.home()
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "prism"
        state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state") / "prism"
        return cls(config, state)

    @property
    def settings(self) -> Path:
        """The settings file."""
        return self.config / "settings.json"

    @property
    def profiles(self) -> Path:
        """The profiles file."""
        return self.config / "profiles.json"

    @property
    def rules(self) -> Path:
        """The automation rules file."""
        return self.config / "rules.json"

    @property
    def log(self) -> Path:
        """The log file."""
        return self.state / "prism.log"
