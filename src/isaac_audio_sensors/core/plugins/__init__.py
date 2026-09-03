"""Public plugin protocols, declarations, adapters, and registry."""

from __future__ import annotations

from isaac_audio_sensors.core.plugins.adapters import (
    GccPhatLeastSquaresEstimator,
    SrpPhatEstimator,
)
from isaac_audio_sensors.core.plugins.declarations import (
    PLUGIN_KINDS,
    SUPPORTED_PLUGIN_DEVICES,
    PluginDeclaration,
)
from isaac_audio_sensors.core.plugins.protocols import (
    ActivityDetector,
    AudioFeatureExtractor,
    DoaEstimator,
    PropagationBackend,
)
from isaac_audio_sensors.core.plugins.registry import (
    PluginAvailability,
    PluginFactory,
    PluginRegistry,
    get_default_registry,
)

__all__ = [
    "PLUGIN_KINDS",
    "SUPPORTED_PLUGIN_DEVICES",
    "ActivityDetector",
    "AudioFeatureExtractor",
    "DoaEstimator",
    "GccPhatLeastSquaresEstimator",
    "PluginAvailability",
    "PluginDeclaration",
    "PluginFactory",
    "PluginRegistry",
    "PropagationBackend",
    "SrpPhatEstimator",
    "get_default_registry",
]
