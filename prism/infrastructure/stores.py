from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..domain.automation import Rule
from ..domain.errors import PrismError, ValidationError
from ..domain.profile import Profile
from ..domain.settings import Settings
from .codec import (
    decode_profile,
    decode_rule,
    decode_settings,
    encode_profile,
    encode_rule,
    encode_settings,
)

_LOG = logging.getLogger(__name__)


class JsonFile:
    """One JSON document on disk, written atomically so a crash never leaves half a file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self, default: Any) -> Any:
        """Read the document.

        A damaged file is moved aside rather than overwritten, so nothing the
        user made is lost.

        @param default: returned when there is no usable file.
        @return: the parsed document, or the default.
        """
        if not self._path.exists():
            return default
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            _LOG.warning("%s is unreadable, keeping it as .damaged and starting fresh", self._path)
            self._path.replace(self._path.with_suffix(".damaged"))
            return default

    def write(self, document: Any) -> None:
        """Replace the document.

        @param document: plain JSON values.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False))
        temporary.replace(self._path)


def _decode_each[T](items: Sequence[Any], decode: Callable[[Any], T], what: str) -> list[T]:
    """Decode a list of saved items, skipping any that no longer make sense.

    @param items: the saved items.
    @param decode: turns one item back into a domain object.
    @param what: what the items are, for the log.
    @return: every item that decoded.
    """
    decoded = []
    for item in items:
        try:
            decoded.append(decode(item))
        except (PrismError, KeyError, TypeError, ValueError) as error:
            _LOG.warning("skipping a saved %s that cannot be read: %s", what, error)
    return decoded


class JsonProfileStore:
    def __init__(self, file: JsonFile) -> None:
        self._file = file

    def load(self) -> list[Profile]:
        """@return: every saved profile, or an empty list on first run."""
        return _decode_each(self._file.read([]), decode_profile, "profile")

    def save(self, profiles: Sequence[Profile]) -> None:
        """@param profiles: every profile to keep."""
        self._file.write([encode_profile(profile) for profile in profiles])


class JsonRuleStore:
    def __init__(self, file: JsonFile) -> None:
        self._file = file

    def load(self) -> list[Rule]:
        """@return: every saved rule, highest priority first."""
        return _decode_each(self._file.read([]), decode_rule, "rule")

    def save(self, rules: Sequence[Rule]) -> None:
        """@param rules: every rule, highest priority first."""
        self._file.write([encode_rule(rule) for rule in rules])


class JsonProfileFiles:
    """Profiles as standalone JSON files, in the same format Prism saves them in."""

    def export(self, profile: Profile, path: Path) -> None:
        """@raise ValidationError: if the file cannot be written."""
        try:
            JsonFile(path).write(encode_profile(profile))
        except OSError as error:
            raise ValidationError(f"cannot write {path.name}: {error}") from error

    def read(self, path: Path) -> Profile:
        """@raise ValidationError: if the file is missing or is not a profile."""
        try:
            return decode_profile(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValidationError(f"{path.name} is not a Prism profile") from error


class JsonSettingsStore:
    def __init__(self, file: JsonFile) -> None:
        self._file = file

    def load(self) -> Settings:
        """@return: the saved settings, or the defaults if there are none or they are invalid."""
        try:
            return decode_settings(self._file.read({}))
        except (PrismError, TypeError, ValueError) as error:
            _LOG.warning("saved settings cannot be used, using defaults: %s", error)
            return Settings()

    def save(self, settings: Settings) -> None:
        """@param settings: the settings."""
        self._file.write(encode_settings(settings))
