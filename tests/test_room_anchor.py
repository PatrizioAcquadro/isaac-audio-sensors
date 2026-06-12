"""Scene-anchored room derivation, placement, and out-of-bounds policy."""

from __future__ import annotations

import math

import pytest
from test_isaac_audio_backends import _FakeShoeBox, _install_fake_pyroom

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.constants import ROOM_CLAMP_MARGIN_M
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.room_anchor import room_spec_from_bounds
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    build_debug_primitives,
    room_outline_points,
)
from isaac_audio_sensors.lab.stage_binding import (
    LabAudioStageBindingCfg,
    build_lab_stage_provider,
)
from isaac_audio_sensors.usd_bounds import (
    resolve_room_absorption,
    world_aligned_bbox,
)

ROOM_MIN_WORLD = (2.0, 1.0, 0.0)
ROOM_MAX_WORLD = (8.0, 5.0, 3.0)
ARRAY_POSITION = (4.0, 3.0, 1.5)
SOURCE_POSITION = (6.0, 2.0, 1.0)


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object],
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    identifier = "room_anchor_test_stage"

    def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
        self._prims = list(prims)

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)


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


def test_room_spec_from_bounds_sets_dimensions_and_origin():
    room = _anchored_room()

    assert room.dimensions_m == (6.0, 4.0, 3.0)
    assert room.origin_m == ROOM_MIN_WORLD
    assert room.anchor_prim_path == "/World/Room"
    assert room.out_of_bounds == "error"


def test_room_spec_from_bounds_rejects_degenerate_bounds():
    with pytest.raises(ValueError, match=r"/World/FlatRoom.*degenerate"):
        room_spec_from_bounds(
            min_world=(0.0, 0.0, 0.0),
            max_world=(4.0, 3.0, 0.0),
            room_id="flat",
            anchor_prim_path="/World/FlatRoom",
        )


def test_room_spec_rejects_unknown_out_of_bounds_policy():
    with pytest.raises(ValueError, match="out_of_bounds"):
        RoomAcousticsSpec(
            room_id="bad_policy",
            dimensions_m=(4.0, 4.0, 3.0),
            absorption=0.35,
            max_order=0,
            out_of_bounds="ignore",
        )


def test_room_anchored_mic_wall_distances_match_stage_geometry(monkeypatch):
    """Room-space positions must preserve true distances to the stage walls."""

    _install_fake_pyroom(monkeypatch)
    room = _anchored_room()
    array = _array()
    scene = _scene(room)

    frame = RoomAcousticsBackend().simulate(scene, array, _window())

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
        RoomAcousticsBackend().simulate(scene, _array(), _window())

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

    frame = RoomAcousticsBackend().simulate(scene, _array(), _window())

    assert frame.diagnostics["room_clamped_position_ids"] == ("source:speaker",)
    source_room = frame.detections[0].diagnostics["room_source_position_m"]
    assert source_room[0] == pytest.approx(6.0 - ROOM_CLAMP_MARGIN_M)
    assert source_room[1] == pytest.approx(1.0)
    assert source_room[2] == pytest.approx(1.0)


def test_world_aligned_bbox_from_explicit_attrs():
    prim = _FakePrim(
        "/World/Room",
        "Xform",
        {
            "ias:room_min_world": ROOM_MIN_WORLD,
            "ias:room_max_world": ROOM_MAX_WORLD,
        },
    )

    minimum, maximum = world_aligned_bbox(prim, prim_path="/World/Room")

    assert minimum == ROOM_MIN_WORLD
    assert maximum == ROOM_MAX_WORLD


def test_world_aligned_bbox_from_size_and_position():
    prim = _FakePrim(
        "/World/Room",
        "Xform",
        {
            "ias:position_world": (5.0, 3.0, 1.5),
            "ias:room_size_m": (6.0, 4.0, 3.0),
        },
    )

    minimum, maximum = world_aligned_bbox(prim, prim_path="/World/Room")

    assert minimum == (2.0, 1.0, 0.0)
    assert maximum == (8.0, 5.0, 3.0)


def test_world_aligned_bbox_errors_without_bounds():
    prim = _FakePrim("/World/Room", "Xform", {})

    with pytest.raises(ValueError, match="/World/Room"):
        world_aligned_bbox(prim, prim_path="/World/Room")


def test_room_absorption_precedence_attr_then_tag_then_default():
    semantic_table = {"concrete": 0.05, "carpet": 0.30}

    explicit = _FakePrim(
        "/World/Room",
        "Xform",
        {"ias:absorption": 0.6, "ias:material": "concrete"},
    )
    assert resolve_room_absorption(
        explicit,
        semantic_absorption=semantic_table,
        default=0.35,
    ) == (0.6, "attr:ias:absorption")

    material = _FakePrim("/World/Room", "Xform", {"ias:material": "Concrete"})
    assert resolve_room_absorption(
        material,
        semantic_absorption=semantic_table,
        default=0.35,
    ) == (0.05, "semantic:Concrete")

    semantic = _FakePrim(
        "/World/Room",
        "Xform",
        {"semantic:Semantics:params:semanticData": "carpet"},
    )
    assert resolve_room_absorption(
        semantic,
        semantic_absorption=semantic_table,
        default=0.35,
    ) == (0.30, "semantic:carpet")

    untagged = _FakePrim("/World/Room", "Xform", {"ias:material": "marble"})
    assert resolve_room_absorption(
        untagged,
        semantic_absorption=semantic_table,
        default=0.35,
    ) == (0.35, "config")


def _stage_with_rooms(*, env_count: int = 2) -> _FakeStage:
    prims: list[_FakePrim] = []
    for env_id in range(env_count):
        env_ns = f"/World/envs/env_{env_id}"
        offset = float(env_id) * 10.0
        prims.append(
            _FakePrim(
                f"{env_ns}/Robot/audio_array",
                "Xform",
                {
                    "ias:array_id": f"rig_{env_id}",
                    "ias:position_world": (offset + 4.0, 3.0, 1.5),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            )
        )
        prims.append(
            _FakePrim(
                f"{env_ns}/Sources/speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:position_world": (offset + 6.0, 2.0, 1.0),
                    "ias:source_id": f"speaker_{env_id}",
                    "ias:class_label": "Speech",
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 1.0,
                },
            )
        )
        prims.append(
            _FakePrim(
                f"{env_ns}/Room",
                "Xform",
                {
                    "ias:room_min_world": (offset + 2.0, 1.0, 0.0),
                    "ias:room_max_world": (offset + 8.0, 5.0, 3.0),
                    "ias:material": "concrete",
                },
            )
        )
    return _FakeStage(tuple(prims))


def _room_binding_cfg(**overrides) -> LabAudioStageBindingCfg:
    base = {
        "num_envs": 2,
        "env_namespace_pattern": "/World/envs/env_{env_id}",
        "array_prim_path": "Robot/audio_array",
        "source_prim_paths": ("Sources/speaker",),
        "microphone_layout": "quad_front",
        "room_prim_path": "Room",
        "room_max_order": 1,
    }
    base.update(overrides)
    return LabAudioStageBindingCfg(**base)


def test_stage_binding_anchors_room_per_env_to_prim_bbox():
    provider = build_lab_stage_provider(
        stage=_stage_with_rooms(),
        binding_cfg=_room_binding_cfg(),
    )

    bindings = provider([0, 1])

    for env_id in (0, 1):
        snapshot, _array_spec = bindings[env_id]
        room = snapshot.room
        offset = float(env_id) * 10.0
        assert room is not None
        assert room.room_id == f"stage_room_env_{env_id}"
        assert room.dimensions_m == (6.0, 4.0, 3.0)
        assert room.origin_m == (offset + 2.0, 1.0, 0.0)
        assert room.anchor_prim_path == f"/World/envs/env_{env_id}/Room"
        # ias:material tag resolved through the default semantic table.
        assert room.absorption == 0.05
        diagnostics = provider.last_diagnostics[env_id]["room"]
        assert diagnostics["absorption_provenance"] == "semantic:concrete"
        assert diagnostics["dimensions_m"] == room.dimensions_m
        assert diagnostics["origin_m"] == room.origin_m


def test_stage_binding_room_absorption_tags_can_be_disabled():
    provider = build_lab_stage_provider(
        stage=_stage_with_rooms(),
        binding_cfg=_room_binding_cfg(
            room_absorption_from_tags=False,
            room_absorption=0.42,
        ),
    )

    snapshot, _array_spec = provider([0])[0]

    assert snapshot.room is not None
    assert snapshot.room.absorption == 0.42
    assert provider.last_diagnostics[0]["room"]["absorption_provenance"] == "config"


def test_stage_binding_missing_room_prim_errors_with_path():
    stage = _stage_with_rooms()
    stage._prims = [prim for prim in stage._prims if not prim.path.endswith("/Room")]
    provider = build_lab_stage_provider(
        stage=stage,
        binding_cfg=_room_binding_cfg(),
    )

    with pytest.raises(ValueError, match="/World/envs/env_0/Room"):
        provider([0])


def test_stage_binding_without_room_prim_path_keeps_room_none():
    provider = build_lab_stage_provider(
        stage=_stage_with_rooms(),
        binding_cfg=_room_binding_cfg(room_prim_path=None),
    )

    snapshot, _array_spec = provider([0])[0]

    assert snapshot.room is None
    assert "room" not in provider.last_diagnostics[0]


def test_stage_binding_cfg_rejects_bad_room_policy():
    with pytest.raises(ValueError, match="room_out_of_bounds"):
        _room_binding_cfg(room_out_of_bounds="wrap")


def test_room_outline_polyline_covers_all_box_edges():
    origin = (2.0, 1.0, 0.0)
    dimensions = (6.0, 4.0, 3.0)

    points = room_outline_points(origin_m=origin, dimensions_m=dimensions)

    assert len(points) == 16
    drawn_edges = {
        frozenset((start, end)) for start, end in zip(points, points[1:], strict=False)
    }

    def corner(x_max: bool, y_max: bool, z_max: bool):
        return (
            origin[0] + (dimensions[0] if x_max else 0.0),
            origin[1] + (dimensions[1] if y_max else 0.0),
            origin[2] + (dimensions[2] if z_max else 0.0),
        )

    expected_edges = set()
    for z_max in (False, True):
        expected_edges.add(
            frozenset((corner(False, False, z_max), corner(True, False, z_max)))
        )
        expected_edges.add(
            frozenset((corner(True, False, z_max), corner(True, True, z_max)))
        )
        expected_edges.add(
            frozenset((corner(True, True, z_max), corner(False, True, z_max)))
        )
        expected_edges.add(
            frozenset((corner(False, True, z_max), corner(False, False, z_max)))
        )
    for x_max in (False, True):
        for y_max in (False, True):
            expected_edges.add(
                frozenset((corner(x_max, y_max, False), corner(x_max, y_max, True)))
            )
    assert len(expected_edges) == 12
    assert expected_edges <= drawn_edges


def test_debug_primitives_include_room_outline_only_with_room():
    array = _array()
    room_scene = _scene(_anchored_room())
    frame = GeometryBackend().simulate(room_scene, array, _window())

    primitives = build_debug_primitives(
        frame=frame,
        scene=room_scene,
        sensor=array,
    )

    outlines = [
        primitive for primitive in primitives if primitive.kind == "room_outline"
    ]
    assert len(outlines) == 1
    outline = outlines[0]
    assert outline.label == "room:anchored_room"
    assert len(outline.points_world) == 16
    assert outline.metadata == {
        "room_id": "anchored_room",
        "dimensions_m": (6.0, 4.0, 3.0),
        "origin_m": ROOM_MIN_WORLD,
        "anchor_prim_path": "/World/Room",
    }

    roomless_scene = AudioSceneSnapshot(
        stage_id="room_anchor_test",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(array,),
    )
    roomless_frame = GeometryBackend().simulate(roomless_scene, array, _window())
    roomless_primitives = build_debug_primitives(
        frame=roomless_frame,
        scene=roomless_scene,
        sensor=array,
    )
    assert all(primitive.kind != "room_outline" for primitive in roomless_primitives)
