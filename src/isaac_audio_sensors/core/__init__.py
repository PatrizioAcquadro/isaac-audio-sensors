"""Simulator-independent audio sensor contracts."""

from __future__ import annotations

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSpec,
    Pose3D,
    RoomAcousticsSpec,
    SourceOcclusion,
)

__all__ = [
    "AudioDetection",
    "AudioSceneSnapshot",
    "AudioSensorFrame",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "DirectivityPattern",
    "DoaEstimate",
    "MicrophoneArraySpec",
    "MicrophoneSpec",
    "Pose3D",
    "RoomAcousticsSpec",
    "SourceOcclusion",
]
