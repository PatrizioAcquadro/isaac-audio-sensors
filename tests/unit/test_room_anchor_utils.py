from __future__ import annotations

import pytest

from isaac_audio_sensors.core.acoustics.rooms import room_spec_from_bounds
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.usd_bounds import (
    resolve_room_absorption,
    world_aligned_bbox,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    build_debug_primitives,
    room_outline_points,
)
from tests.helpers import FakeUsdPrim

ROOM_MIN_WORLD = (2.0, 1.0, 0.0)
ROOM_MAX_WORLD = (8.0, 5.0, 3.0)


def _room():
    return room_spec_from_bounds(
        min_world=ROOM_MIN_WORLD,
        max_world=ROOM_MAX_WORLD,
        room_id="anchored_room",
        absorption=0.35,
        max_order=1,
        anchor_prim_path="/World/Room",
    )


def _array():
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        position_world=(4.0, 3.0, 1.5),
    )


def _source():
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Sources/speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=(6.0, 2.0, 1.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def test_room_bounds_and_policy_validation():
    room = _room()
    assert room.dimensions_m == (6.0, 4.0, 3.0)
    assert room.origin_m == ROOM_MIN_WORLD
    assert room.anchor_prim_path == "/World/Room"

    with pytest.raises(ValueError, match=r"/World/FlatRoom.*degenerate"):
        room_spec_from_bounds(
            min_world=(0.0, 0.0, 0.0),
            max_world=(4.0, 3.0, 0.0),
            room_id="flat",
            anchor_prim_path="/World/FlatRoom",
        )
    with pytest.raises(ValueError, match="out_of_bounds"):
        RoomAcousticsSpec(
            room_id="bad_policy",
            dimensions_m=(4.0, 4.0, 3.0),
            absorption=0.35,
            max_order=0,
            out_of_bounds="ignore",
        )


def test_world_aligned_bbox_fallbacks_and_missing_bounds():
    explicit = FakeUsdPrim(
        "/World/Room",
        "Xform",
        {
            "ias:room_min_world": ROOM_MIN_WORLD,
            "ias:room_max_world": ROOM_MAX_WORLD,
        },
    )
    centered = FakeUsdPrim(
        "/World/Room",
        "Xform",
        {
            "ias:position_world": (5.0, 3.0, 1.5),
            "ias:room_size_m": (6.0, 4.0, 3.0),
        },
    )

    assert world_aligned_bbox(explicit, prim_path=explicit.path) == (
        ROOM_MIN_WORLD,
        ROOM_MAX_WORLD,
    )
    assert world_aligned_bbox(centered, prim_path=centered.path) == (
        ROOM_MIN_WORLD,
        ROOM_MAX_WORLD,
    )
    with pytest.raises(ValueError, match="/World/Room"):
        world_aligned_bbox(
            FakeUsdPrim("/World/Room", "Xform"),
            prim_path="/World/Room",
        )


def test_room_absorption_precedence():
    table = {"concrete": 0.05, "carpet": 0.30}
    cases = (
        (
            {"ias:absorption": 0.6, "ias:material": "concrete"},
            (0.6, "attr:ias:absorption"),
        ),
        ({"ias:material": "Concrete"}, (0.05, "semantic:Concrete")),
        (
            {"semantic:Semantics:params:semanticData": "carpet"},
            (0.30, "semantic:carpet"),
        ),
        ({"ias:material": "marble"}, (0.35, "config")),
    )
    for attributes, expected in cases:
        prim = FakeUsdPrim("/World/Room", "Xform", attributes)
        assert (
            resolve_room_absorption(
                prim,
                semantic_absorption=table,
                default=0.35,
            )
            == expected
        )


def test_room_outline_and_debug_primitive():
    points = room_outline_points(
        origin_m=ROOM_MIN_WORLD,
        dimensions_m=(6.0, 4.0, 3.0),
    )
    assert len(points) == 16
    drawn_edges = {
        frozenset((start, end)) for start, end in zip(points, points[1:], strict=False)
    }
    corners = {(x, y, z) for x in (2.0, 8.0) for y in (1.0, 5.0) for z in (0.0, 3.0)}
    expected_edges = {
        frozenset((left, right))
        for left in corners
        for right in corners
        if sum(a != b for a, b in zip(left, right, strict=True)) == 1
    }
    assert expected_edges <= drawn_edges

    array = _array()
    scene = AudioSceneSnapshot(
        stage_id="room_anchor_test",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(array,),
        room=_room(),
    )
    frame = GeometryBackend().simulate(
        scene,
        array,
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=0.2,
            timestamp_ms=0,
            sample_rate_hz=48_000,
        ),
    )
    outlines = [
        primitive
        for primitive in build_debug_primitives(frame=frame, scene=scene, sensor=array)
        if primitive.kind == "room_outline"
    ]
    assert len(outlines) == 1
    assert outlines[0].label == "room:anchored_room"
    assert outlines[0].metadata["anchor_prim_path"] == "/World/Room"
