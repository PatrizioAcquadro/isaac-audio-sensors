"""Unit tests for persistent USD debug geometry authoring."""

from __future__ import annotations

from isaac_audio_sensors.isaac.viz.overlays import DebugPrimitive
from isaac_audio_sensors.isaac.viz.usd_debug import (
    DEFAULT_DEBUG_ROOT,
    UsdDebugGeometryAuthor,
)


class _FakePrim:
    def __init__(self, path: str, type_name: str) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes: dict[str, object] = {}

    def IsValid(self) -> bool:  # noqa: N802 - USD spelling
        return True

    def GetPath(self) -> str:  # noqa: N802 - USD spelling
        return self.path


class _FakeStage:
    def __init__(self) -> None:
        self.prims: dict[str, _FakePrim] = {}
        self.removed: list[str] = []

    def DefinePrim(self, path: str, type_name: str = "") -> _FakePrim:  # noqa: N802
        prim = _FakePrim(str(path), type_name)
        self.prims[str(path)] = prim
        return prim

    def GetPrimAtPath(self, path: str) -> _FakePrim | None:  # noqa: N802
        return self.prims.get(str(path))

    def RemovePrim(self, path: str) -> bool:  # noqa: N802
        self.removed.append(str(path))
        return self.prims.pop(str(path), None) is not None

    def Traverse(self):  # noqa: N802 - USD spelling
        return list(self.prims.values())


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
    stage = _FakeStage()
    author = UsdDebugGeometryAuthor()

    paths = author.author(stage, _primitives())

    assert len(paths) == 3
    assert all(path.startswith(DEFAULT_DEBUG_ROOT + "/") for path in paths)
    assert DEFAULT_DEBUG_ROOT in stage.prims  # Scope root

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

    # Re-author: same paths, updated values, nothing pruned.
    second = author.author(stage, _primitives(bearing_color=(0.95, 0.15, 0.1, 1.0)))
    assert second == paths
    assert stage.prims[paths[2]].attributes["primvars:displayColor"] == [
        (0.95, 0.15, 0.1)
    ]
    assert stage.removed == []


def test_author_writes_room_outline_as_basis_curves_polyline():
    from isaac_audio_sensors.isaac.viz.overlays import room_outline_points

    stage = _FakeStage()
    author = UsdDebugGeometryAuthor()
    points = room_outline_points(
        origin_m=(2.0, 1.0, 0.0),
        dimensions_m=(6.0, 4.0, 3.0),
    )

    paths = author.author(
        stage,
        (
            DebugPrimitive(
                kind="room_outline",
                label="room:anchored_room",
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
    assert outline.attributes["ias:debug:kind"] == "room_outline"


def test_author_prunes_stale_prims_when_primitives_shrink():
    stage = _FakeStage()
    author = UsdDebugGeometryAuthor()
    first = author.author(stage, _primitives())
    second = author.author(stage, _primitives()[:1])

    assert len(second) == 1
    for stale in set(first) - set(second):
        assert stale in stage.removed
        assert stale not in stage.prims


def test_clear_removes_whole_subtree_and_resets_paths():
    stage = _FakeStage()
    author = UsdDebugGeometryAuthor(root="/World/CustomDebug")
    author.author(stage, _primitives())
    assert author.authored_paths

    author.clear(stage)
    assert author.authored_paths == ()
    assert "/World/CustomDebug" in stage.removed
