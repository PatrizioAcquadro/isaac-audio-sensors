"""Import-safe UI state dataclasses and their (de)serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.isaac.microphone_rig_profiles import (
    MicrophoneRigProfile,
    default_microphone_rig_profiles,
)
from isaac_audio_sensors.isaac.replicator import (
    DEFAULT_REPLICATOR_ANNOTATOR_NAME,
    DEFAULT_REPLICATOR_WRITER_NAME,
)
from isaac_audio_sensors.isaac.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
)

from .constants import (
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_LATEST_FRAME_FILENAME,
    DEFAULT_REPLICATOR_DIRNAME,
    DEFAULT_TRACE_FILENAME,
)


class ExtensionActionError(RuntimeError):
    """User-facing extension action failure."""


@dataclass(frozen=True, slots=True)
class CurrentStageContext:
    """Current Omni stage and selected prim paths."""

    stage: Any | None
    selected_prim_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveredPrimSummary:
    """Compact discovered array/source record for UI and export."""

    id: str
    prim_path: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredMetadataSummary:
    """Record of metadata authored through the extension UI."""

    kind: str
    prim_path: str
    id: str
    attributes: Mapping[str, Any]


@dataclass(slots=True)
class ExtensionUiState:
    """Pure-Python state backing the reference extension UX."""

    guided_mode_enabled: bool = True
    guided_preset_id: str = ""
    guided_stage: str = "setup"
    guided_session_dir: str = "guided_dataset"
    guided_dataset_id: str = "guided_dataset"
    guided_shard_max_frames: int = 100
    guided_record_aligned: bool = False
    guided_scene_id: str = "guided_scene"
    guided_environment_id: str = "guided_environment"
    guided_split_group: str = "guided_scene"
    guided_session_seed: int = 0

    selected_prim_paths: tuple[str, ...] = ()
    stage_status: str = "No stage checked."
    status_message: str = "Ready."
    error_message: str | None = None

    array_prim_path: str = "/World/Rig/AudioArray"
    array_id: str = "rig_front"
    layout_name: str = "quad_front"
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    author_child_microphones: bool = True
    array_position_x_m: float = 0.0
    array_position_y_m: float = 0.0
    array_position_z_m: float = 0.0
    array_yaw_deg: float = 0.0
    array_pitch_deg: float = 0.0
    array_roll_deg: float = 0.0
    array_attached_to_object: bool = False
    attached_array_object_prim_path: str = ""
    array_local_offset_x_m: float = 0.0
    array_local_offset_y_m: float = 0.0
    array_local_offset_z_m: float = 0.0
    array_local_yaw_deg: float = 0.0
    array_local_pitch_deg: float = 0.0
    array_local_roll_deg: float = 0.0

    rig_profile_library: tuple[MicrophoneRigProfile, ...] = field(
        default_factory=default_microphone_rig_profiles
    )
    selected_rig_profile_id: str = "alex_head_quad"
    applied_array_rig_profile: dict[str, Any] = field(default_factory=dict)

    source_prim_path: str = "/World/Sources/SpeakerA"
    source_id: str = "speaker_a"
    source_class_label: str = "Speech"
    audio_asset_path: str = "generated://impulse"
    source_position_x_m: float = 2.0
    source_position_y_m: float = 0.0
    source_position_z_m: float = 0.0
    source_start_time_s: float = 0.0
    source_duration_s: float = 1.0
    source_gain_db: float = 0.0
    source_directivity: str = "omni"

    profile_library: tuple[SoundProfile, ...] = field(
        default_factory=default_sound_profiles
    )
    selected_profile_id: str = "speech_generic"
    object_profile_mappings: dict[str, str] = field(
        default_factory=default_object_profile_mappings
    )
    applied_source_profile: dict[str, Any] = field(default_factory=dict)

    object_prim_path: str = ""
    object_label: str = "none"
    source_attached_to_object: bool = False
    attached_object_prim_path: str = ""
    source_local_offset_x_m: float = 0.0
    source_local_offset_y_m: float = 0.0
    source_local_offset_z_m: float = 0.0

    robot_base_prim_path: str = ""
    discovery_roots_text: str = "/World"
    backend: str = "tdoa_synthetic"
    ambiguity_policy: str = "none"
    update_period_s: float = 0.05
    max_events: int = 8
    debug_overlay_enabled: bool = True
    occlusion_enabled: bool = False
    trace_enabled: bool = True
    jsonl_trace_path: str = DEFAULT_TRACE_FILENAME
    waveform_enabled: bool = False
    waveform_dir: str = "live_waveforms"
    waveform_mode: str = "per_frame"
    follow_viewport_selection: bool = False
    live_sync_array_pose: bool = False
    live_sync_source_pose: bool = False
    usd_debug_enabled: bool = False
    usd_debug_root: str = "/World/IasAudioDebug"
    room_anchor_prim_path: str = ""
    room_out_of_bounds: str = "error"
    latest_room_summary: dict[str, Any] | None = None
    latest_frame_export_path: str = DEFAULT_LATEST_FRAME_FILENAME
    config_export_path: str = DEFAULT_CONFIG_FILENAME
    config_import_path: str = DEFAULT_CONFIG_FILENAME

    replicator_enabled: bool = False
    replicator_output_dir: str = DEFAULT_REPLICATOR_DIRNAME
    replicator_writer_name: str = DEFAULT_REPLICATOR_WRITER_NAME
    replicator_annotator_name: str = DEFAULT_REPLICATOR_ANNOTATOR_NAME
    replicator_recording: bool = False
    replicator_status_message: str = "Replicator idle."
    replicator_write_count: int = 0
    replicator_flush_count: int = 0
    replicator_latest_write_path: str | None = None
    replicator_latest_jsonl_path: str | None = None
    replicator_latest_error: str | None = None
    replicator_output_artifacts: tuple[str, ...] = ()

    discovered_arrays: tuple[DiscoveredPrimSummary, ...] = ()
    discovered_sources: tuple[DiscoveredPrimSummary, ...] = ()
    discovered_objects: tuple[DiscoveredPrimSummary, ...] = ()
    authored_metadata: tuple[AuthoredMetadataSummary, ...] = ()

    sensor_running: bool = False
    latest_frame_id: str | None = None
    latest_detection_count: int = 0
    latest_backend: str | None = None
    latest_source_prim_path: str | None = None
    latest_source_position_m: tuple[float, float, float] | None = None
    latest_bearing_deg: float | None = None
    latest_sector: str | None = None
    latest_bearing_confidence: float | None = None
    latest_candidate_bearings: tuple[float, ...] = ()
    latest_occluded: bool | None = None
    latest_timestamp_ms: int | None = None
    latest_array_prim_path: str | None = None
    latest_array_position_m: tuple[float, float, float] | None = None
    latest_array_orientation_xyzw: tuple[float, float, float, float] | None = None
    latest_mic_world_positions: dict[str, tuple[float, float, float]] = field(
        default_factory=dict
    )
    latest_aggregate_rms: dict[str, float] = field(default_factory=dict)
    detection_history: list[dict[str, Any]] = field(default_factory=list)
    latest_waveform_paths: tuple[str, ...] = ()
    audition_status: str = "Audition idle."
    omnigraph_status: str = "OmniGraph node not registered."
    latest_usd_debug_prim_paths: tuple[str, ...] = ()
    latest_overlay_primitive_count: int = 0
    latest_overlay_labels: tuple[str, ...] = ()
    latest_overlay_status: str = "none"
    latest_overlay_error: str | None = None


def _jsonable_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_ready(value) for key, value in sorted(mapping.items())}


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(value[key]) for key in sorted(value)}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _authored_metadata_from_dict(value: Any) -> AuthoredMetadataSummary:
    if not isinstance(value, Mapping):
        raise ExtensionActionError("authored_metadata entries must be objects.")
    return AuthoredMetadataSummary(
        kind=str(value.get("kind", "")),
        prim_path=str(value.get("prim_path", "")),
        id=str(value.get("id", "")),
        attributes=_jsonable_mapping(dict(value.get("attributes", {}))),
    )


def _discovered_summary_from_dict(value: Any) -> DiscoveredPrimSummary:
    if not isinstance(value, Mapping):
        raise ExtensionActionError("discovered object entries must be objects.")
    return DiscoveredPrimSummary(
        id=str(value.get("id", "")),
        prim_path=str(value.get("prim_path", "")),
        reasons=tuple(str(reason) for reason in value.get("reasons", ())),
    )
