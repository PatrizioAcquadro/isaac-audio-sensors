"""Import-safe structural contracts for audio-sensor plugins."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from isaac_audio_sensors.core.types import (
    ActivityDecision,
    AudioSceneSnapshot,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneSignalBlock,
)


@runtime_checkable
class ActivityDetector(Protocol):
    """Detect generic activity from ordered valid-channel waveforms."""

    detector_id: str

    def detect(
        self,
        samples: np.ndarray,
        sample_rate_hz: int,
    ) -> ActivityDecision:
        """Return one bounded decision and update detector streaming state."""

    def reset(self) -> None:
        """Clear all temporal and event state at an explicit stream boundary."""


@runtime_checkable
class PropagationBackend(Protocol):
    """Scene-to-microphone-signal contract implemented by every backend."""

    backend_id: str

    def propagate(
        self,
        scene: AudioSceneSnapshot,
        array_id: str,
        time_window: AudioTimeWindow,
    ) -> MicrophoneSignalBlock:
        """Produce one snapshot-owned microphone-array signal block."""


@runtime_checkable
class DoaEstimator(Protocol):
    """Estimate direction from ordered ``[channel, sample]`` waveforms.

    Row ``i`` in ``samples`` corresponds to row ``i`` in
    ``microphone_positions_m``. Geometry is array-local XYZ in metres. The
    result uses the public array-local bearing/elevation convention and the
    diagnostics mapping contains estimator-specific scalar or structured data.
    ``DoaEstimate.bearing_confidence`` is an estimator-local reliability score,
    not a probability or a cross-estimator calibrated quantity.
    Scene sources, schedules, private stems, and producer diagnostics are not
    part of this contract.
    """

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        """Return a DOA estimate and estimator diagnostics."""


@runtime_checkable
class AudioFeatureExtractor(Protocol):
    """Extract a declared fixed-shape feature tensor from ordered samples.

    Input samples have shape ``[channel, sample]``. The returned NumPy tensor
    has the exact fixed shape and dtype in the plugin declaration's
    ``output_contract``; metadata is plugin-defined and must be a dictionary.
    """

    def extract(
        self,
        samples: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[np.ndarray, dict[str, object]]:
        """Return the fixed-shape feature tensor and metadata."""


__all__ = [
    "ActivityDetector",
    "AudioFeatureExtractor",
    "DoaEstimator",
    "PropagationBackend",
]
