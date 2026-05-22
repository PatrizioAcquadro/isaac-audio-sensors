"""Shared constants for the pure audio-sensor core."""

from __future__ import annotations

COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"
DEFAULT_SAMPLE_RATE_HZ = 48_000
DEFAULT_SPEED_OF_SOUND_MPS = 343.0
EPSILON = 1e-9

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
