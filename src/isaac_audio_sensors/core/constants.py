"""Shared constants for the pure audio-sensor core."""

from __future__ import annotations

COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"
DEFAULT_SAMPLE_RATE_HZ = 48_000
DEFAULT_SPEED_OF_SOUND_MPS = 343.0
EPSILON = 1e-9
FRAME_SCHEMA_VERSION = "ias.audio_sensor_frame.v1"

FRAME_UNITS = {
    "position": "m",
    "orientation": "quaternion_xyzw",
    "bearing": "deg_clockwise_from_array_forward",
    "distance": "m",
    "time": "s",
    "timestamp": "ms",
    "sample_rate": "Hz",
    "rms": "linear",
    "gain": "dB",
}

FRAME_TOP_LEVEL_FIELDS = (
    "schema_version",
    "frame_id",
    "frame_name",
    "timestamp_ms",
    "start_time_s",
    "end_time_s",
    "sample_rate_hz",
    "frame_index",
    "backend_id",
    "array_id",
    "array_pose",
    "coordinate_convention",
    "units",
    "provenance",
    "max_events",
    "detections",
    "aggregate_per_mic_rms",
    "waveform_paths",
    "diagnostics",
)

DETECTION_FIELDS = (
    "detection_id",
    "source_id",
    "class_label",
    "detection_mode",
    "timestamp_ms",
    "ground_truth_bearing_deg",
    "source_distance_m",
    "doa",
    "source_pose",
    "per_mic_delay_s",
    "per_mic_rms",
    "audio_asset_path",
    "occluded",
    "diagnostics",
)

# Additive v1 detection fields: always serialized by current writers but kept
# out of the JSON schema's required list so pre-existing v1 traces stay valid.
OPTIONAL_DETECTION_FIELDS = ("occluded",)

DOA_FIELDS = (
    "estimated_bearing_deg",
    "candidate_bearing_deg",
    "bearing_sector",
    "bearing_confidence",
    "ambiguity_class",
    "ambiguity_reason",
)

POSE3D_FIELDS = (
    "position_m",
    "orientation_xyzw",
    "frame",
    "coordinate_convention",
)

FRAME_PROVENANCE_VALUES = frozenset(
    {
        "synthetic/core",
        "room_acoustics",
        "isaac_live",
        "replay/trace",
    }
)

STABLE_DIAGNOSTIC_NAMESPACES = (
    "stage_snapshot",
    "stage_binding",
    "entity_binding",
)

DETECTION_MODES = frozenset(
    {
        "scheduled_known_source",
        "external_metadata",
        "signal_energy",
        "manual_annotation",
    }
)

KNOWN_BACKENDS = frozenset({"geometry_only", "tdoa_synthetic", "room_acoustics"})

TDOA_AMBIGUITY_POLICIES = frozenset({"none", "front_hemisphere"})

SECTOR_ORDER = (
    "straight",
    "straight_right",
    "right",
    "behind_right",
    "behind",
    "behind_left",
    "left",
    "straight_left",
)
