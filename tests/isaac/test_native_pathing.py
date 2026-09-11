"""Optional real Steam selected-route filter checks (native CPU execution)."""

import ctypes as C
import os
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene.steam import ContextSettings, Handle
from tools.native.pathing import Route, RouteFilter


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
        yield renderer
    finally:
        renderer.close()
        lib.iplContextRelease(C.byref(context))


def test_native_route_delay_gain_weight_and_settling(native_filter):
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
