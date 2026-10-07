from __future__ import annotations

from collections.abc import Sequence

from ..domain.errors import ValidationError
from ..domain.profile import Profile
from ..ports import ProfileStore


class ProfileLibrary:
    """The user's saved profiles, in the order they were made, saved after every change."""

    def __init__(self, store: ProfileStore) -> None:
        self._store = store
        self._profiles = store.load()

    @property
    def profiles(self) -> list[Profile]:
        """Every profile, in order."""
        return list(self._profiles)

    def names(self) -> list[str]:
        """@return: every profile's name, in order."""
        return [profile.name for profile in self._profiles]

    def get(self, name: str) -> Profile:
        """@raise ValidationError: if there is no profile by that name."""
        for profile in self._profiles:
            if profile.name == name:
                return profile
        raise ValidationError(f"there is no profile called {name!r}")

    def seed(self, starters: Sequence[Profile]) -> None:
        """Give a first run something to start from.

        @param starters: profiles to add if the library is empty.
        """
        if not self._profiles and starters:
            self._profiles = list(starters)
            self._persist()

    def save(self, profile: Profile) -> None:
        """Store a profile, replacing the one with the same name or adding it at the end.

        @param profile: the profile.
        """
        names = self.names()
        if profile.name in names:
            self._profiles[names.index(profile.name)] = profile
        else:
            self._profiles.append(profile)
        self._persist()

    def create(self, name: str) -> Profile:
        """Add an empty profile, which leaves every device as it is until edited.

        @param name: the new profile's name.
        @return: the new profile.
        @raise ValidationError: if the name is taken.
        """
        self._check_free(name)
        profile = Profile(name.strip())
        self.save(profile)
        return profile

    def duplicate(self, name: str) -> Profile:
        """Copy a profile under the first free name like "Gaming copy".

        @param name: the profile to copy.
        @return: the copy.
        """
        copy = self.get(name).renamed(self.free_name(f"{name} copy"))
        self.save(copy)
        return copy

    def rename(self, old: str, new: str) -> None:
        """@raise ValidationError: if the old profile is missing or the new name is taken."""
        if old == new.strip():
            return
        self._check_free(new)
        index = self.names().index(self.get(old).name)
        self._profiles[index] = self._profiles[index].renamed(new.strip())
        self._persist()

    def delete(self, name: str) -> None:
        """@raise ValidationError: if it is the last profile, since there must always be one to show."""
        if len(self._profiles) == 1:
            raise ValidationError("the last profile cannot be deleted")
        self._profiles.remove(self.get(name))
        self._persist()

    def add_imported(self, profile: Profile) -> Profile:
        """Add a profile from a file, renaming it if the name is taken.

        @param profile: the imported profile.
        @return: the profile as stored.
        """
        stored = profile.renamed(self.free_name(profile.name))
        self.save(stored)
        return stored

    def free_name(self, wanted: str) -> str:
        """@return: the wanted name, or it with a number added until it is unused."""
        names = set(self.names())
        candidate, number = wanted, 1
        while candidate in names:
            number += 1
            candidate = f"{wanted} {number}"
        return candidate

    def _check_free(self, name: str) -> None:
        """@raise ValidationError: if the name is blank or taken."""
        if not name.strip():
            raise ValidationError("a profile needs a name")
        if name.strip() in self.names():
            raise ValidationError(f"there is already a profile called {name.strip()!r}")

    def _persist(self) -> None:
        """Write every profile to the store."""
        self._store.save(self._profiles)
