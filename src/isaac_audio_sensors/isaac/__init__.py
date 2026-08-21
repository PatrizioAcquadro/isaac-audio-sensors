"""Isaac Sim and Omniverse-facing helpers with lazy optional imports."""

from __future__ import annotations

from isaac_audio_sensors.isaac.discovery import (
    DiscoveredAudioArray,
    DiscoveredAudioSource,
    IsaacAudioDiscoveryCfg,
    IsaacAudioDiscoveryResult,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    StagePose,
    resolve_world_pose,
)
from isaac_audio_sensors.isaac.replicator import (
    AudioSensorReplicatorRecorder,
    ReplicatorIntegrationError,
    ReplicatorRecorderStatus,
    audio_sensor_frame_replicator_payload,
    require_replicator_core,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    create_listener_prim,
    create_sound_prim,
    require_isaac_usd,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot

__all__ = [
    "AudioSensorReplicatorRecorder",
    "DiscoveredAudioArray",
    "DiscoveredAudioSource",
    "IsaacAudioArraySensor",
    "IsaacAudioDiscoveryCfg",
    "IsaacAudioDiscoveryResult",
    "IsaacAudioSceneBindingCfg",
    "IsaacStagePoseResolver",
    "ReplicatorIntegrationError",
    "ReplicatorRecorderStatus",
    "StagePose",
    "audio_sensor_frame_replicator_payload",
    "attach_microphone_array_attrs",
    "attach_microphone_attrs",
    "attach_sound_source_attrs",
    "build_stage_snapshot",
    "create_listener_prim",
    "create_sound_prim",
    "discover_stage_audio",
    "require_isaac_usd",
    "require_replicator_core",
    "resolve_world_pose",
]
