"""Optional real Steam selected-route filter checks (native CPU execution)."""

import ctypes as C
import os
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene._path_stream import SegmentQuery
from isaac_audio_sensors.isaac.acoustic_scene._paths import Route, RouteFilter
from isaac_audio_sensors.isaac.acoustic_scene.steam import (
    ContextSettings,
    Handle,
    Material,
    MeshSettings,
    SceneSettings,
)


@pytest.fixture
def native_filter():
    path = Path(os.environ.get("IAS_PATHING_LIBRARY", "build/native/libias_pathing.so"))
    if not path.is_file():
        pytest.skip("Experimental Steam selected-route build is not installed.")
    pytest.importorskip("pyroomacoustics")
    lib = C.CDLL(str(path.resolve()))
    lib.iplContextCreate.argtypes = [C.POINTER(ContextSettings), C.POINTER(Handle)]
    lib.iplContextRelease.argtypes = [C.POINTER(Handle)]
    context = Handle()
    assert (
        lib.iplContextCreate(
            C.byref(ContextSettings(version=0x040801)), C.byref(context)
        )
        == 0
    )
    renderer = RouteFilter(lib, context)
    try:
        yield renderer, context
    finally:
        renderer.close()
        lib.iplContextRelease(C.byref(context))


def test_native_route_delay_gain_weight_and_settling(native_filter):
    native_filter, _ = native_filter
    for distance in (5.706, 9.494):
        route = Route(
            (-1, 0, -2),
            np.array([[0, 0, 0], [distance / 2, 0, 0], [distance, 0, 0]]),
            distance,
            0.3,
            (1.0, 1.0, 1.0),
        )
        impulse = native_filter.impulse(route)
        assert abs(np.argmax(abs(impulse)) - distance / 343 * 16000) <= 1
        # Native finite interpolation/resampling filters have small passband ripple.
        np.testing.assert_allclose(
            np.sum(impulse), 0.3 / (4 * np.pi * distance), rtol=0.001
        )
        doubled = native_filter.impulse(route, gain=2.0)
        np.testing.assert_allclose(doubled, 2 * impulse, atol=1e-9)
        # A prior different EQ must not contaminate the next route's native state.
        native_filter.impulse(
            Route(route.probes, route.points, distance, 1.0, (0.3, 0.2, 0.1))
        )
        np.testing.assert_array_equal(native_filter.impulse(route), impulse)
    with pytest.raises(ValueError, match="horizon"):
        native_filter.impulse(route, max_delay_s=0.001)


def test_native_segment_query_half_open_boundary_and_visibility(native_filter):
    renderer, context = native_filter
    lib = renderer.lib
    p = C.POINTER
    specs = {
        "iplEmbreeDeviceCreate": (C.c_int, [Handle, Handle, p(Handle)]),
        "iplEmbreeDeviceRelease": (None, [p(Handle)]),
        "iplSceneCreate": (C.c_int, [Handle, p(SceneSettings), p(Handle)]),
        "iplSceneRelease": (None, [p(Handle)]),
        "iplSceneCommit": (None, [Handle]),
        "iplStaticMeshCreate": (C.c_int, [Handle, p(MeshSettings), p(Handle)]),
        "iplStaticMeshAdd": (None, [Handle, Handle]),
        "iplStaticMeshRelease": (None, [p(Handle)]),
    }
    for name, (restype, argtypes) in specs.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = restype, argtypes
    scene, device, mesh = Handle(), Handle(), Handle()
    try:
        assert (
            lib.iplEmbreeDeviceCreate(context, C.byref(C.c_byte()), C.byref(device))
            == 0
        )
        assert (
            lib.iplSceneCreate(
                context, C.byref(SceneSettings(type=1, embree=device)), C.byref(scene)
            )
            == 0
        )
        vertices = np.array(
            [[0, -2, -2], [0, 2, -2], [0, 2, 2], [0, -2, 2]], np.float32
        )
        triangles = np.array([[0, 1, 2], [0, 2, 3]], np.int32)
        indices = np.zeros(2, np.int32)
        material = Material()
        settings = MeshSettings(
            4,
            2,
            1,
            vertices.ctypes.data,
            triangles.ctypes.data,
            indices.ctypes.data,
            C.pointer(material),
        )
        assert lib.iplStaticMeshCreate(scene, C.byref(settings), C.byref(mesh)) == 0
        lib.iplStaticMeshAdd(mesh, scene)
        lib.iplSceneCommit(scene)
        query = SegmentQuery(lib, scene)
        starts = np.array([[1, 0, 0], [1, 0, 0], [0, 0, 0], [1, 3, 0]], float)
        ends = np.array([[-1, 0, 0], [0, 0, 0], [-1, 0, 0], [-1, 3, 0]], float)
        np.testing.assert_array_equal(query(starts, ends), [True, False, True, False])
        with pytest.raises(RuntimeError, match="failed"):
            query([[np.nan, 0, 0]], [[0, 0, 0]])
    finally:
        if mesh:
            lib.iplStaticMeshRelease(C.byref(mesh))
        if scene:
            lib.iplSceneRelease(C.byref(scene))
        if device:
            lib.iplEmbreeDeviceRelease(C.byref(device))
