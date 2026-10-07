from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .cooling import FanSetting, PumpMode
from .effects import Effect
from .errors import ValidationError


def _frozen[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    """Copy a mapping into a read-only view, so a profile cannot change under its owner.

    @param mapping: the entries.
    @return: a read-only copy.
    """
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class Profile:
    """A saved look and sound for the whole machine.

    @ivar lighting: the effect for each zone, keyed by zone id. Zones not listed are left alone.
    @ivar cooling: the setting for each fan, keyed by fan id. Fans not listed are left alone.
    @ivar pump: the AIO pump mode, or None to leave it as it is.
    """

    name: str
    lighting: Mapping[str, Effect] = field(default_factory=dict)
    cooling: Mapping[str, FanSetting] = field(default_factory=dict)
    pump: PumpMode | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a profile needs a name")
        object.__setattr__(self, "lighting", _frozen(self.lighting))
        object.__setattr__(self, "cooling", _frozen(self.cooling))

    def with_effect(self, zone_id: str, effect: Effect) -> Profile:
        """@return: a copy with one zone's effect changed."""
        return replace(self, lighting={**self.lighting, zone_id: effect})

    def with_effect_everywhere(self, zone_ids: list[str], effect: Effect) -> Profile:
        """@return: a copy with the same effect on every given zone, like iCUE's sync."""
        return replace(self, lighting={**self.lighting, **dict.fromkeys(zone_ids, effect)})

    def with_fan(self, fan_id: str, setting: FanSetting) -> Profile:
        """@return: a copy with one fan's setting changed."""
        return replace(self, cooling={**self.cooling, fan_id: setting})

    def with_pump(self, pump: PumpMode | None) -> Profile:
        """@return: a copy with the pump mode changed."""
        return replace(self, pump=pump)

    def renamed(self, name: str) -> Profile:
        """@return: a copy under a new name."""
        return replace(self, name=name)
