"""Pure Python core for Isaac audio sensor simulation."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.base import AudioSimulationBackend, get_backend
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import (
    AudioSensorConfig,
    build_scene_snapshot,
    load_audio_config,
    validate_audio_config,
)
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.schema import (
    audio_sensor_frame_json_schema,
    write_audio_sensor_frame_json_schema,
)
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
)

__all__ = [
    "AudioDetection",
    "AudioSceneSnapshot",
    "AudioSensorConfig",
    "AudioSensorFrame",
    "AudioSimulationBackend",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "DoaEstimate",
    "GeometryBackend",
    "MicrophoneArraySpec",
    "MicrophoneSpec",
    "Pose3D",
    "RoomAcousticsBackend",
    "RoomAcousticsSpec",
    "TdoaSyntheticBackend",
    "audio_sensor_frame_json_schema",
    "build_scene_snapshot",
    "create_microphone_array",
    "get_backend",
    "load_audio_config",
    "microphone_world_positions",
    "validate_audio_config",
    "write_audio_sensor_frame_json_schema",
]
