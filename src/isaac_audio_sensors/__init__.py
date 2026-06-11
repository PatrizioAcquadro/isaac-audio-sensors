"""Robotics-style audio sensor models for Isaac Sim and Isaac Lab workflows."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.base import AudioSimulationBackend
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.fidelity import (
    ACOUSTIC_FIDELITY_LADDER,
    AcousticFidelityLevel,
    AcousticFidelityMetadata,
    fidelity_level_for_backend,
)
from isaac_audio_sensors.core.schema import audio_sensor_frame_json_schema
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

__version__ = "1.4.0"

__all__ = [
    "__version__",
    "AudioDetection",
    "AudioSceneSnapshot",
    "AudioSensorFrame",
    "AudioSimulationBackend",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "ACOUSTIC_FIDELITY_LADDER",
    "AcousticFidelityLevel",
    "AcousticFidelityMetadata",
    "DoaEstimate",
    "GeometryBackend",
    "MicrophoneArraySpec",
    "MicrophoneSpec",
    "Pose3D",
    "RoomAcousticsBackend",
    "RoomAcousticsSpec",
    "SourceOcclusion",
    "TdoaSyntheticBackend",
    "audio_sensor_frame_json_schema",
    "fidelity_level_for_backend",
]
