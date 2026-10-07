from __future__ import annotations


class PrismError(Exception):
    """The base of every error Prism raises on purpose."""


class DeviceError(PrismError):
    """A device could not be reached or refused a command."""


class ValidationError(PrismError):
    """A value the user supplied cannot be used as given."""
