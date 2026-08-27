"""Scene-anchored room derivation, placement, and out-of-bounds policy."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.acoustics.rooms import room_spec_from_bounds
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.constants import ROOM_CLAMP_MARGIN_M
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from tests.helpers import (
    FakeShoeBox as _FakeShoeBox,
)
from tests.helpers import (
    install_fake_pyroom as _install_fake_pyroom,
)

ROOM_MIN_WORLD = (2.0, 1.0, 0.0)
ROOM_MAX_WORLD = (8.0, 5.0, 3.0)
ARRAY_POSITION = (4.0, 3.0, 1.5)
SOURCE_POSITION = (6.0, 2.0, 1.0)


def _array(position=ARRAY_POSITION):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        position_world=position,
    )


def _source(position=SOURCE_POSITION) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Sources/speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _anchored_room(*, out_of_bounds: str = "error") -> RoomAcousticsSpec:
    return room_spec_from_bounds(
        min_world=ROOM_MIN_WORLD,
        max_world=ROOM_MAX_WORLD,
        room_id="anchored_room",
        absorption=0.35,
        max_order=1,
        out_of_bounds=out_of_bounds,
        anchor_prim_path="/World/Room",
    )


def _scene(room: RoomAcousticsSpec, source=None) -> AudioSceneSnapshot:
    array = _array()
    return AudioSceneSnapshot(
        stage_id="room_anchor_test",
        timestamp_ms=0,
        sources=(source or _source(),),
        arrays=(array,),
        room=room,
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.2,
        timestamp_ms=0,
        sample_rate_hz=48_000,
    )


def test_room_anchored_mic_wall_distances_match_stage_geometry(monkeypatch):
    """Room-space positions must preserve true distances to the stage walls."""

    _install_fake_pyroom(monkeypatch)
    room = _anchored_room()
    array = _array()
    scene = _scene(room)

    frame = RoomAcousticsBackend().simulate(scene, array.array_id, _window())

    shoebox = _FakeShoeBox.instances[-1]
    assert tuple(shoebox.dimensions) == (6.0, 4.0, 3.0)
    detection = frame.detections[0]
    mic_room = detection.diagnostics["room_microphone_positions_m"]
    for mic_id, world in microphone_world_positions(array).items():
        for axis in range(3):
            room_position = mic_room[mic_id][axis]
            # The distance to the low/high wall on each axis must equal the
            # mic's true distance to the stage-authored bounding planes.
            assert room_position == pytest.approx(world[axis] - ROOM_MIN_WORLD[axis])
            assert room.dimensions_m[axis] - room_position == pytest.approx(
                ROOM_MAX_WORLD[axis] - world[axis]
            )
    source_room = detection.diagnostics["room_source_position_m"]
    for axis in range(3):
        assert source_room[axis] == pytest.approx(
            SOURCE_POSITION[axis] - ROOM_MIN_WORLD[axis]
        )
    for mic_id, world in microphone_world_positions(array).items():
        expected_delay = math.dist(SOURCE_POSITION, world) / 343.0
        assert detection.diagnostics["direct_path_delay_s"][mic_id] == (
            pytest.approx(expected_delay)
        )
    assert frame.diagnostics["room_clamped_position_ids"] == ()
    room_config = frame.diagnostics["room_config"]
    assert room_config["origin_m"] == ROOM_MIN_WORLD
    assert room_config["anchor_prim_path"] == "/World/Room"
    assert room_config["out_of_bounds"] == "error"


def test_room_out_of_bounds_error_names_offending_prim(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    scene = _scene(_anchored_room(), source=_source((9.0, 2.0, 1.0)))

    with pytest.raises(ValueError) as excinfo:
        RoomAcousticsBackend().simulate(scene, "rig", _window())

    message = str(excinfo.value)
    assert "source:speaker" in message
    assert "(9.0, 2.0, 1.0)" in message
    assert "anchored_room" in message
    assert "/World/Room" in message


def test_room_out_of_bounds_clamp_pulls_inside_and_reports(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    scene = _scene(
        _anchored_room(out_of_bounds="clamp"),
        source=_source((9.0, 2.0, 1.0)),
    )

    frame = RoomAcousticsBackend().simulate(scene, "rig", _window())

    assert frame.diagnostics["room_clamped_position_ids"] == ("source:speaker",)
    source_room = frame.detections[0].diagnostics["room_source_position_m"]
    assert source_room[0] == pytest.approx(6.0 - ROOM_CLAMP_MARGIN_M)
    assert source_room[1] == pytest.approx(1.0)
    assert source_room[2] == pytest.approx(1.0)
