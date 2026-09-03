"""Simulator-independent audio sensor contracts."""

from __future__ import annotations

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AcousticSurfaceSpec,
    AudioObservation,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
    ObservationOrigin,
    Pose3D,
    SourceOcclusion,
)

__all__ = [
    "AcousticEnvironmentSpec",
    "AcousticSurfaceSpec",
    "AudioObservation",
    "AudioPerceptionPipeline",
    "AudioSceneSnapshot",
    "AudioSensorFrame",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "DirectivityPattern",
    "DoaEstimate",
    "MicrophoneArraySpec",
    "MicrophoneSignalBlock",
    "MicrophoneSpec",
    "ObservationOrigin",
    "Pose3D",
    "SourceOcclusion",
]
