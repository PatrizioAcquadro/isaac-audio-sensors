from __future__ import annotations

import pytest

from isaac_audio_sensors.core.acoustics.environments import (
    shoebox_environment_from_bounds,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from isaac_audio_sensors.isaac.usd_bounds import (
    resolve_environment_absorption,
    world_aligned_bbox,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    build_debug_primitives,
    environment_outline_points,
)
from tests.helpers import FakeUsdPrim, install_fake_pyroom

ENVIRONMENT_MIN_WORLD = (2.0, 1.0, 0.0)
ENVIRONMENT_MAX_WORLD = (8.0, 5.0, 3.0)


def _environment():
    return shoebox_environment_from_bounds(
        min_world=ENVIRONMENT_MIN_WORLD,
        max_world=ENVIRONMENT_MAX_WORLD,
        environment_id="anchored_environment",
        absorption=0.35,
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


def test_environment_bounds_validation() -> None:
    environment = _environment()
    assert environment.dimensions_m == (6.0, 4.0, 3.0)
    assert environment.world_pose.position_m == ENVIRONMENT_MIN_WORLD

    with pytest.raises(ValueError, match=r"flat.*degenerate"):
        shoebox_environment_from_bounds(
            min_world=(0.0, 0.0, 0.0),
            max_world=(4.0, 3.0, 0.0),
            environment_id="flat",
        )


def test_world_aligned_bbox_fallbacks_and_missing_bounds() -> None:
    explicit = FakeUsdPrim(
        "/World/Environment",
        "Xform",
        {
            "ias:environment_min_world": ENVIRONMENT_MIN_WORLD,
            "ias:environment_max_world": ENVIRONMENT_MAX_WORLD,
        },
    )
    centered = FakeUsdPrim(
        "/World/Environment",
        "Xform",
        {
            "ias:position_world": (5.0, 3.0, 1.5),
            "ias:environment_size_m": (6.0, 4.0, 3.0),
        },
    )

    assert world_aligned_bbox(explicit, prim_path=explicit.path) == (
        ENVIRONMENT_MIN_WORLD,
        ENVIRONMENT_MAX_WORLD,
    )
    assert world_aligned_bbox(centered, prim_path=centered.path) == (
        ENVIRONMENT_MIN_WORLD,
        ENVIRONMENT_MAX_WORLD,
    )
    with pytest.raises(ValueError, match="/World/Environment"):
        world_aligned_bbox(
            FakeUsdPrim("/World/Environment", "Xform"),
            prim_path="/World/Environment",
        )


def test_environment_absorption_precedence() -> None:
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
        prim = FakeUsdPrim("/World/Environment", "Xform", attributes)
        assert (
            resolve_environment_absorption(
                prim,
                semantic_absorption=table,
                default=0.35,
            )
            == expected
        )


def test_environment_outline_and_debug_primitive(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    environment = _environment()
    points = environment_outline_points(environment)
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
        stage_id="environment_anchor_test",
        sources=(_source(),),
        arrays=(array,),
        environment=environment,
    )
    frame = AnalyticAcoustics().simulate(
        scene,
        array.array_id,
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=0.2,
            frame_index=0,
        ),
    )
    outlines = [
        primitive
        for primitive in build_debug_primitives(frame=frame, scene=scene, sensor=array)
        if primitive.kind == "environment_outline"
    ]
    assert len(outlines) == 1
    assert outlines[0].label == "environment:anchored_environment"
    assert outlines[0].metadata["kind"] == "shoebox"
