"""Exception types used by optional extension layers."""

from __future__ import annotations


class IsaacAudioSensorsError(Exception):
    """Base exception for package-specific failures."""


class ConfigValidationError(IsaacAudioSensorsError, ValueError):
    """Raised when an audio-sensor config is invalid."""


class UnsupportedEffectError(ConfigValidationError):
    """Raised when an effect is outside the selected backend envelope."""


class OptionalDependencyUnavailable(IsaacAudioSensorsError, ImportError):
    """Raised when an optional backend or integration dependency is missing."""


class IsaacIntegrationUnavailable(OptionalDependencyUnavailable):
    """Raised when Isaac Sim or Omniverse modules are unavailable."""


class IsaacLabUnavailable(OptionalDependencyUnavailable):
    """Raised when Isaac Lab modules are unavailable."""
