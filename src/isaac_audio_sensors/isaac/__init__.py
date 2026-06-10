"""Isaac Sim and Omniverse-facing helpers with lazy optional imports."""

from __future__ import annotations

from isaac_audio_sensors.isaac.array_registry import (
    ArrayRecord,
    discover_microphone_arrays,
)
from isaac_audio_sensors.isaac.discovery import (
    DiscoveredAudioArray,
    DiscoveredAudioSource,
    IsaacAudioDiscoveryCfg,
    IsaacAudioDiscoveryResult,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.listener_registry import ListenerRecord
from isaac_audio_sensors.isaac.microphone_rig_profiles import (
    MicrophoneRigProfile,
    default_microphone_rig_profiles,
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
from isaac_audio_sensors.isaac.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
)
from isaac_audio_sensors.isaac.source_registry import SourceRecord
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
    "ArrayRecord",
    "DiscoveredAudioArray",
    "DiscoveredAudioSource",
    "IsaacAudioArraySensor",
    "IsaacAudioDiscoveryCfg",
    "IsaacAudioDiscoveryResult",
    "IsaacAudioSceneBindingCfg",
    "IsaacStagePoseResolver",
    "ListenerRecord",
    "MicrophoneRigProfile",
    "AudioSensorReplicatorRecorder",
    "ReplicatorIntegrationError",
    "ReplicatorRecorderStatus",
    "SoundProfile",
    "SourceRecord",
    "StagePose",
    "attach_microphone_array_attrs",
    "attach_microphone_attrs",
    "attach_sound_source_attrs",
    "build_stage_snapshot",
    "create_listener_prim",
    "create_sound_prim",
    "discover_stage_audio",
    "discover_microphone_arrays",
    "audio_sensor_frame_replicator_payload",
    "default_microphone_rig_profiles",
    "default_object_profile_mappings",
    "default_sound_profiles",
    "require_isaac_usd",
    "require_replicator_core",
    "resolve_world_pose",
]
