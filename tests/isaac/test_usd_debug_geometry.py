from __future__ import annotations

from isaac_audio_sensors.core.acoustics import shoebox_environment
from isaac_audio_sensors.isaac.viz.overlays import DebugPrimitive
from isaac_audio_sensors.isaac.viz.usd_debug import (
    DEFAULT_DEBUG_ROOT,
    UsdDebugGeometryAuthor,
)
from tests.helpers import FakeUsdStage


def _primitives(bearing_color=(0.05, 0.9, 0.35, 1.0)):
    return (
        DebugPrimitive(
            kind="microphone",
            label="mic front",
            points_world=((0.1, 0.0, 0.5),),
            color_rgba=(0.1, 0.45, 1.0, 1.0),
            radius_m=0.035,
        ),
        DebugPrimitive(
            kind="source",
            label="source speaker_a",
            points_world=((2.0, 0.0, 0.5),),
            color_rgba=(1.0, 0.6, 0.05, 1.0),
            radius_m=0.06,
        ),
        DebugPrimitive(
            kind="bearing_ray",
            label="bearing speaker_a",
            points_world=((0.0, 0.0, 0.5), (2.0, 0.0, 0.5)),
            color_rgba=bearing_color,
            radius_m=0.01,
        ),
    )


def test_author_creates_spheres_and_curves_with_stable_paths():
    stage = FakeUsdStage()
    author = UsdDebugGeometryAuthor()

    paths = author.author(stage, _primitives())

    assert len(paths) == 3
    assert all(path.startswith(DEFAULT_DEBUG_ROOT + "/") for path in paths)
    assert DEFAULT_DEBUG_ROOT in stage.prims

    mic = stage.prims[paths[0]]
    assert mic.type_name == "Sphere"
    assert mic.attributes["radius"] == 0.035
    assert mic.attributes["xformOp:translate"] == (0.1, 0.0, 0.5)
    assert mic.attributes["ias:debug:kind"] == "microphone"

    ray = stage.prims[paths[2]]
    assert ray.type_name == "BasisCurves"
    assert ray.attributes["type"] == "linear"
    assert ray.attributes["curveVertexCounts"] == [2]
    assert ray.attributes["points"] == [(0.0, 0.0, 0.5), (2.0, 0.0, 0.5)]
    assert ray.attributes["primvars:displayColor"] == [(0.05, 0.9, 0.35)]

    second = author.author(stage, _primitives(bearing_color=(0.95, 0.15, 0.1, 1.0)))
    assert second == paths
    assert stage.prims[paths[2]].attributes["primvars:displayColor"] == [
        (0.95, 0.15, 0.1)
    ]
    assert stage.removed == []


def test_author_writes_environment_outline_as_basis_curves_polyline():
    from isaac_audio_sensors.isaac.viz.overlays import environment_outline_points

    stage = FakeUsdStage()
    author = UsdDebugGeometryAuthor()
    points = environment_outline_points(
        shoebox_environment(
            environment_id="anchored_environment",
            position_world=(2.0, 1.0, 0.0),
            dimensions_m=(6.0, 4.0, 3.0),
        )
    )

    paths = author.author(
        stage,
        (
            DebugPrimitive(
                kind="environment_outline",
                label="environment:anchored_environment",
                points_world=points,
                color_rgba=(0.95, 0.85, 0.1, 1.0),
                radius_m=0.02,
            ),
        ),
    )

    outline = stage.prims[paths[0]]
    assert outline.type_name == "BasisCurves"
    assert outline.attributes["curveVertexCounts"] == [16]
    assert outline.attributes["points"] == list(points)
    assert outline.attributes["ias:debug:kind"] == "environment_outline"


def test_author_writes_occlusion_ray_and_hit_through_existing_geometry_paths():
    stage = FakeUsdStage()
    author = UsdDebugGeometryAuthor()
    primitives = (
        DebugPrimitive(
            kind="occlusion_ray",
            label="occlusion:rig:source:front",
            points_world=((2.0, 0.0, 0.5), (1.0, 0.0, 0.5), (0.0, 0.0, 0.5)),
            color_rgba=(0.95, 0.15, 0.1, 0.85),
            radius_m=0.01,
        ),
        DebugPrimitive(
            kind="occlusion_hit",
            label="occlusion-hit:rig:source:front:0",
            points_world=((1.0, 0.0, 0.5),),
            color_rgba=(0.95, 0.15, 0.1, 1.0),
            radius_m=0.025,
        ),
    )

    paths = author.author(stage, primitives)

    ray = stage.prims[paths[0]]
    assert ray.type_name == "BasisCurves"
    assert ray.attributes["curveVertexCounts"] == [3]
    assert ray.attributes["ias:debug:kind"] == "occlusion_ray"
    hit = stage.prims[paths[1]]
    assert hit.type_name == "Sphere"
    assert hit.attributes["xformOp:translate"] == (1.0, 0.0, 0.5)
    assert hit.attributes["ias:debug:kind"] == "occlusion_hit"


def test_author_prunes_stale_prims_when_primitives_shrink():
    stage = FakeUsdStage()
    author = UsdDebugGeometryAuthor()
    first = author.author(stage, _primitives())
    second = author.author(stage, _primitives()[:1])

    assert len(second) == 1
    for stale in set(first) - set(second):
        assert stale in stage.removed
        assert stale not in stage.prims


def test_clear_removes_whole_subtree():
    stage = FakeUsdStage()
    author = UsdDebugGeometryAuthor(root="/World/CustomDebug")
    paths = author.author(stage, _primitives())
    assert all(path in stage.prims for path in paths)

    author.clear(stage)
    assert "/World/CustomDebug" in stage.removed
    assert all(path not in stage.prims for path in paths)
