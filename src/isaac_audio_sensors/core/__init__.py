"""Simulator-independent audio sensor contracts."""

from __future__ import annotations

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AcousticSurfaceSpec,
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
    Pose3D,
    SourceOcclusion,
)

__all__ = [
    "AcousticEnvironmentSpec",
    "AcousticSurfaceSpec",
    "AudioDetection",
    "AudioSceneSnapshot",
    "AudioSensorFrame",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "DirectivityPattern",
    "DoaEstimate",
    "MicrophoneArraySpec",
    "MicrophoneSignalBlock",
    "MicrophoneSpec",
    "Pose3D",
    "SourceOcclusion",
]
