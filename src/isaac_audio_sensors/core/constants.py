"""Shared constants for the pure audio-sensor core."""

from __future__ import annotations

COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"
DEFAULT_SAMPLE_RATE_HZ = 48_000
DEFAULT_SPEED_OF_SOUND_MPS = 343.0
RUNTIME_PROFILES = ("training_features", "waveform_fidelity")
DEFAULT_RUNTIME_PROFILE = "waveform_fidelity"
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
FRAME_SCHEMA_VERSION = "ias.audio_sensor_frame.v3"

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

OPTIONAL_FRAME_UNIT_KEYS: tuple[str, ...] = ()

FRAME_TOP_LEVEL_FIELDS = (
    "schema_version",
    "frame_id",
    "frame_name",
    "timestamp_ms",
    "start_time_s",
    "end_time_s",
    "sample_rate_hz",
    "frame_index",
    "producer_id",
    "array_id",
    "channel_validity",
    "array_pose",
    "coordinate_convention",
    "units",
    "provenance",
    "max_observations",
    "observations",
    "aggregate_per_mic_rms",
    "waveform_paths",
    "diagnostics",
)

OBSERVATION_FIELDS = (
    "observation_id",
    "origin",
    "detector_id",
    "detection_score",
    "doa",
    "diagnostics",
)

OPTIONAL_OBSERVATION_FIELDS: tuple[str, ...] = ()

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

OPTIONAL_DOA_FIELDS: tuple[str, ...] = ()

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

ACOUSTIC_ENVIRONMENT_KINDS = frozenset(
    {"free_field", "half_space", "shoebox", "polygon_prism", "surface_set"}
)
ACOUSTIC_SURFACE_ROLES = frozenset({"floor", "wall", "ceiling"})

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
