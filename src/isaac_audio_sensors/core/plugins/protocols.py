"""Import-safe structural contracts for audio-sensor plugins."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
)


@runtime_checkable
class PropagationBackend(Protocol):
    """Scene-to-frame propagation contract implemented by every backend."""

    backend_id: str

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        """Simulate one ordered microphone-array observation frame."""


@runtime_checkable
class DoaEstimator(Protocol):
    """Estimate direction from ordered ``[channel, sample]`` waveforms.

    Row ``i`` in ``samples`` corresponds to row ``i`` in
    ``microphone_positions_m``. Geometry is array-local XYZ in metres. The
    result uses the public array-local bearing/elevation convention and the
    diagnostics mapping contains estimator-specific scalar or structured data.
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
    "AudioFeatureExtractor",
    "DoaEstimator",
    "PropagationBackend",
]
