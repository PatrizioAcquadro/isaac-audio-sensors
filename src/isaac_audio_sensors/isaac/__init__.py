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
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    StagePose,
    resolve_world_pose,
)
from isaac_audio_sensors.isaac.source_registry import SourceRecord
from isaac_audio_sensors.isaac.stage_audio import (
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
    "SourceRecord",
    "StagePose",
    "build_stage_snapshot",
    "create_listener_prim",
    "create_sound_prim",
    "discover_stage_audio",
    "discover_microphone_arrays",
    "require_isaac_usd",
    "resolve_world_pose",
]
