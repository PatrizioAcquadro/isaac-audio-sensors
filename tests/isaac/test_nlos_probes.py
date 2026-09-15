"""Real native automatic-probe/search controls independent of producer admission."""

import ctypes as C

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene._paths import ProbeRoutes, RouteFilter
from isaac_audio_sensors.isaac.acoustic_scene.steam import (
    Handle,
    Material,
    MeshSettings,
    SceneSettings,
)
from tests.isaac.test_native_pathing import native_filter  # noqa: F401


@pytest.fixture
def probe_scenes(native_filter):  # noqa: F811
    renderer, context = native_filter
    lib = renderer.lib
    p = C.POINTER
    for name, result, args in (
        ("iplEmbreeDeviceCreate", C.c_int, [Handle, Handle, p(Handle)]),
        ("iplEmbreeDeviceRelease", None, [p(Handle)]),
        ("iplSceneCreate", C.c_int, [Handle, p(SceneSettings), p(Handle)]),
        ("iplSceneRelease", None, [p(Handle)]),
        ("iplStaticMeshCreate", C.c_int, [Handle, p(MeshSettings), p(Handle)]),
        ("iplStaticMeshRelease", None, [p(Handle)]),
        ("iplStaticMeshAdd", None, [Handle, Handle]),
        ("iplSceneCommit", None, [Handle]),
    ):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
    device, scenes, meshes = Handle(), [], []
    assert lib.iplEmbreeDeviceCreate(context, C.byref(C.c_byte()), C.byref(device)) == 0

    def make(blocker=0, *, faces=None):
        scene = Handle()
        assert (
            lib.iplSceneCreate(
                context, C.byref(SceneSettings(type=1, embree=device)), C.byref(scene)
            )
            == 0
        )
        scenes.append(scene)
        if faces is None:
            faces = [[[-3, 0, -3], [3, 0, -3], [3, 0, 3], [-3, 0, 3]]]
        if blocker:
            faces.append(
                [[0, 0, -blocker], [0, 3, -blocker], [0, 3, blocker], [0, 0, blocker]]
            )
        vertices = np.array(faces, np.float32).reshape(-1, 3)
        triangles = np.array(
            [[4 * i, 4 * i + 1, 4 * i + 2] for i in range(len(faces))]
            + [[4 * i, 4 * i + 2, 4 * i + 3] for i in range(len(faces))],
            np.int32,
        )
        indices = np.zeros(len(triangles), np.int32)
        material = Material()
        settings = MeshSettings(
            len(vertices),
            len(triangles),
            1,
            vertices.ctypes.data,
            triangles.ctypes.data,
            indices.ctypes.data,
            C.pointer(material),
        )
        mesh = Handle()
        assert lib.iplStaticMeshCreate(scene, C.byref(settings), C.byref(mesh)) == 0
        meshes.append(mesh)
        lib.iplStaticMeshAdd(mesh, scene)
        lib.iplSceneCommit(scene)
        return scene

    try:
        yield lib, context, make
    finally:
        for mesh in meshes:
            lib.iplStaticMeshRelease(C.byref(mesh))
        for scene in scenes:
            lib.iplSceneRelease(C.byref(scene))
        lib.iplEmbreeDeviceRelease(C.byref(device))


def test_automatic_native_paths_visibility_timing_and_coverage(probe_scenes):
    lib, context, make = probe_scenes
    floor, screen, closed = make(0), make(0.6), make(4)
    paths = ProbeRoutes(lib, floor, [[-3, 0, -3], [3, 3, 3]], 0.5, 1.2, 512)
    renderer = RouteFilter(lib, context)
    try:
        assert paths.count > 20
        source, mic = (2, 1.2, 0), (-2, 1.2, 0)
        assert paths.find(floor, source, mic) == ((), "los")
        routes, state = paths.find(screen, source, mic)
        assert state == "selected" and routes
        assert sum(r.weight for r in routes) <= 1.00001
        assert any(np.max(r.points[1:-1, 2]) > 0.6 for r in routes)
        assert any(np.min(r.points[1:-1, 2]) < -0.6 for r in routes)
        # Any path around this screen is at least two diagonal legs.
        lower_bound = 2 * np.sqrt(2**2 + 0.6**2)
        for route in routes:
            assert route.length_m >= lower_bound - 1e-5
            impulse = renderer.impulse(route)
            eq = renderer.equalizer(route.eq)
            expected = route.length_m / 343 * 16000 + np.argmax(abs(eq))
            assert abs(np.argmax(abs(impulse)) - expected) <= 1
        assert paths.find(closed, source, mic) == ((), "no_selected_route")
        restored, _ = paths.find(screen, source, mic)
        for a, b in zip(routes, restored, strict=True):
            np.testing.assert_array_equal(a.points, b.points)
            assert (a.weight, a.eq) == (b.weight, b.eq)
        with pytest.raises(RuntimeError, match="outside probe coverage"):
            paths.find(closed, (8, 1.2, 0), mic)
    finally:
        renderer.close()
        paths.close()
        paths.close()


def test_probe_capacity_fails_before_unbounded_bake(probe_scenes):
    lib, _, make = probe_scenes
    with pytest.raises(RuntimeError, match="capacity"):
        ProbeRoutes(lib, make(0), [[-3, 0, -3], [3, 3, 3]], 0.01, 1.2, 512)


@pytest.mark.parametrize("spacing", [1.0, 0.5, 0.25])
def test_corridor_probe_refinement_preserves_weights_and_detour(probe_scenes, spacing):
    lib, _, make = probe_scenes
    # L-shaped free space; coordinates below are Steam Y-up metres.
    polygon = [(0, 0), (8, 0), (8, 8), (6, 8), (6, 2), (0, 2)]
    faces = [
        [[0, 0, 0], [8, 0, 0], [8, 0, 2], [0, 0, 2]],
        [[6, 0, 2], [8, 0, 2], [8, 0, 8], [6, 0, 8]],
    ]
    for (x, z), (u, v) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        faces.append([[x, 0, z], [u, 0, v], [u, 3, v], [x, 3, z]])
    scene = make(faces=faces)
    paths = ProbeRoutes(lib, scene, [[0, 0, 0], [8, 3, 8]], spacing, 1.2, 1024)
    try:
        # Include both maintained apertures, the raised microphone and a source
        # exactly aligned with an old lattice point (previous near-total dropout).
        offsets = [
            (-0.033, -0.033, 0),
            (-0.033, 0.033, 0),
            (0.033, 0.033, 0),
            (0.033, -0.033, 0),
            (-0.03, -0.03, 0),
            (-0.03, 0.03, 0),
            (0.03, 0.03, 0),
            (0.03, -0.03, 0),
            (0, 0, 0.04),
        ]
        for dx, dz, dy in offsets:
            source = np.array([7, 1.2, 6])
            mic = np.array([1 + dx, 1.2 + dy, 1 + dz])
            routes, state = paths.find(scene, source, mic)
            assert state == "selected"
            assert sum(r.weight for r in routes) == pytest.approx(1, abs=2e-6)
            corner = np.array([6, 1.2, 2])
            lower = np.linalg.norm(source - corner) + np.linalg.norm(
                (mic - corner)[[0, 2]]
            )
            assert all(r.length_m >= lower - 1e-5 for r in routes)
    finally:
        paths.close()
