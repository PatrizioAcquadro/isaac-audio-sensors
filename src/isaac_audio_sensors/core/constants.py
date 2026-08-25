"""Shared constants for the pure audio-sensor core."""

from __future__ import annotations

COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"
DEFAULT_SAMPLE_RATE_HZ = 48_000
DEFAULT_SPEED_OF_SOUND_MPS = 343.0
RUNTIME_PROFILES = ("training_features", "waveform_fidelity")
DEFAULT_RUNTIME_PROFILE = "waveform_fidelity"
DIRECTIVITY_COEFFICIENTS = {
    "omni": 1.0,
    "cardioid": 0.5,
    "figure_eight": 0.0,
    "supercardioid": 0.37,
}

CALIBRATION_PROFILE_SCHEMA_VERSION = "ias.audio_calibration_profile.v1"

CALIBRATION_PROFILE_UNITS = {
    "position": "m",
    "position_uncertainty": "m",
    "gain": "dB",
    "delay": "s",
    "frequency": "Hz",
    "self_noise": "dB_SPL",
    "temperature": "deg_C",
    "speed_of_sound": "m/s",
}

# Octave-band centers shared by occlusion transmission-loss producers and the
# room backend's per-band attenuation filter.
OCCLUSION_BAND_CENTERS_HZ = (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0)
EPSILON = 1e-9
FRAME_SCHEMA_VERSION = "ias.audio_sensor_frame.v1"

FRAME_UNITS = {
    "position": "m",
    "orientation": "quaternion_xyzw",
    "bearing": "deg_clockwise_from_array_forward",
    "elevation": "deg_up_from_array_horizontal",
    "distance": "m",
    "time": "s",
    "timestamp": "ms",
    "sample_rate": "Hz",
    "rms": "linear",
    "gain": "dB",
}

# Additive v1 unit keys: emitted by current writers but tolerated as absent
# when reading frames or traces written before the key existed.
OPTIONAL_FRAME_UNIT_KEYS = ("elevation",)

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
    "ground_truth_elevation_deg",
    "source_pose",
    "per_mic_delay_s",
    "per_mic_rms",
    "audio_asset_path",
    "occluded",
    "diagnostics",
)

# Additive v1 detection fields: always serialized by current writers but kept
# out of the JSON schema's required list so pre-existing v1 traces stay valid.
OPTIONAL_DETECTION_FIELDS = ("occluded", "ground_truth_elevation_deg")

DOA_FIELDS = (
    "estimated_bearing_deg",
    "candidate_bearing_deg",
    "bearing_sector",
    "bearing_confidence",
    "ambiguity_class",
    "ambiguity_reason",
    "estimated_elevation_deg",
    "candidate_elevation_deg",
)

# Additive v1 DOA fields: serialized by current writers but kept out of the
# JSON schema's required list so pre-existing v1 traces stay valid.
OPTIONAL_DOA_FIELDS = ("estimated_elevation_deg", "candidate_elevation_deg")

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

DETECTION_MODES = frozenset(
    {
        "scheduled_known_source",
        "external_metadata",
        "signal_energy",
        "manual_annotation",
    }
)

ROOM_OUT_OF_BOUNDS_POLICIES = frozenset({"error", "clamp"})
# Clamped positions are pulled this far inside the walls so pyroomacoustics
# never receives a degenerate on-wall source/microphone.
ROOM_CLAMP_MARGIN_M = 0.05
# Anchored rooms thinner than this on any axis are authoring mistakes.
MIN_ROOM_EXTENT_M = 0.05

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
