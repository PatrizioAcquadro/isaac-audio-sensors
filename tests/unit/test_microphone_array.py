"""Tests for microphone layouts and array transforms."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    layout_rank_xy,
    layout_rank_xyz,
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec


def test_microphone_layouts_cover_supported_sizes_and_direct_custom_arrays():
    assert len(microphone_layout("mono")) == 1
    assert len(microphone_layout("stereo_y")) == 2
    assert len(microphone_layout("quad_front")) == 4

    array = _array(
        (
            ("a", (0.0, 0.0, 0.0)),
            ("b", (0.1, 0.0, 0.0)),
            ("c", (0.0, 0.1, 0.0)),
            ("d", (-0.1, 0.0, 0.0)),
            ("e", (0.0, -0.1, 0.0)),
        )
    )
    assert len(array.microphones) == 5
    assert microphone_world_positions(array)["b"] == pytest.approx((0.1, 0.0, 0.0))

    with pytest.raises(ValueError, match="Unknown microphone layout"):
        microphone_layout("missing")


def test_tetrahedral_layout_is_rank_three_with_requested_edge_length():
    spacing = 0.2
    microphones = microphone_layout("tetrahedral", spacing_m=spacing)
    positions = [microphone.relative_position_m for microphone in microphones]

    assert len(microphones) == 4
    for index, left in enumerate(positions):
        for right in positions[index + 1 :]:
            assert math.dist(left, right) == pytest.approx(spacing, abs=1e-12)

    array = MicrophoneArraySpec(
        array_id="tetra",
        prim_path="/World/Tetra",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=microphones,
    )
    assert layout_rank_xyz(array) == 3
    assert layout_rank_xy(array) == 2


@pytest.mark.parametrize(
    ("positions", "expected_rank"),
    [
        ((('a', (0.0, 0.0, 0.0)),), 0),
        ((('a', (0.0, 0.0, 0.0)), ('b', (0.0, 0.0, 0.0))), 0),
        ((('a', (0.0, 0.0, 0.0)), ('b', (0.0, 0.0, 0.2))), 1),
        (
            (
                ('a', (0.0, 0.0, 0.0)),
                ('b', (0.2, 0.0, 0.0)),
                ('c', (0.0, 0.0, 0.2)),
            ),
            2,
        ),
        (
            (
                ('a', (0.0, 0.0, 0.0)),
                ('b', (0.2, 0.0, 0.0)),
                ('c', (0.0, 0.2, 0.0)),
                ('d', (0.0, 0.0, 0.2)),
            ),
            3,
        ),
    ],
)
def test_layout_rank_xyz_detects_point_line_plane_and_volume(positions, expected_rank):
    assert layout_rank_xyz(_array(positions)) == expected_rank


def test_world_positions_derive_basis_from_normalized_quaternion():
    array = create_microphone_array(
        array_id="rotated",
        prim_path="/World/Rotated",
        layout_name="stereo_y",
        orientation_world_quat=tuple(
            value * 2.0 for value in quaternion_from_yaw_deg(90.0)
        ),
    )

    assert array.coordinate_convention == COORDINATE_CONVENTION
    positions = microphone_world_positions(array)
    assert positions["left"] == pytest.approx((0.08, 0.0, 0.0), abs=1e-9)
    assert positions["right"] == pytest.approx((-0.08, 0.0, 0.0), abs=1e-9)


def _array(positions) -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="custom",
        prim_path="/World/Custom",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=tuple(
            MicrophoneSpec(mic_id=mic_id, relative_position_m=position)
            for mic_id, position in positions
        ),
    )
