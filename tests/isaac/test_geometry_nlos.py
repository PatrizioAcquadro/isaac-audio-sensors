"""Opt-in Geometry producer NLOS, native geometry updates and stream ownership."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pxr")
from pxr import Sdf, UsdGeom  # noqa: E402

from isaac_audio_sensors.isaac.acoustic_scene import (  # noqa: E402
    AcousticSceneSession,
    GeometryAcoustics,
    GeometryAcousticsConfig,
    SteamNLOSConfig,
)
from isaac_audio_sensors.isaac.acoustic_scene.session import DYNAMIC  # noqa: E402
from tests.isaac.geometry_helpers import (  # noqa: E402
    SPECULAR_LIBRARY,
    scene,
    stage,
    window,
)

LIBRARY = Path(__file__).resolve().parents[2] / "build/native/libias_pathing.so"


def fixture_scene():
    value = stage()
    for name, position, scale in (
        ("Floor", (0, 0, -0.05), (6, 6, 0.1)),
        ("Screen", (0, 0, 1.5), (0.02, 1.2, 3)),
    ):
        prim = UsdGeom.Cube.Define(value, f"/{name}")
        prim.GetSizeAttr().Set(1.0)
        prim.AddTranslateOp().Set(position)
        prim.AddScaleOp().Set(scale)
        if name == "Screen":
            prim.GetPrim().CreateAttribute(DYNAMIC, Sdf.ValueTypeNames.Token).Set(
                "dynamic"
            )
    snapshot = scene()
    snapshot = replace(
        snapshot,
        sources=(replace(snapshot.sources[0], position_world=(2, 0, 1.2)),),
        arrays=(replace(snapshot.arrays[0], position_world=(-2, 0, 1.2)),),
    )
    return value, snapshot


@pytest.fixture
def prepared_nlos():
    if not LIBRARY.exists() or not SPECULAR_LIBRARY.exists():
        pytest.skip("Optional qualified native providers are unavailable.")
    value, snapshot = fixture_scene()
    session = AcousticSceneSession(value)
    backend = GeometryAcoustics(
        acoustic_scene=session,
        geometry_config=GeometryAcousticsConfig(
            library_path=str(LIBRARY),
            specular_library_path=str(SPECULAR_LIBRARY),
            reflection_order=0,
            diagnostics=True,
            nlos=SteamNLOSConfig(probe_spacing_m=0.5),
        ),
    )
    try:
        yield backend, session, snapshot
    finally:
        backend.close()
        session.close()


def test_integrated_nlos_continuity_and_reset(prepared_nlos):
    backend, _, snapshot = prepared_nlos
    whole = backend.propagate(snapshot, "array", window(0, 0.2))
    assert np.min(np.max(abs(whole.samples), axis=1)) > 1e-4
    assert whole.diagnostics["geometry"]["nlos"]["probes"] > 20
    backend.reset()
    parts = [
        backend.propagate(snapshot, "array", window(a, b)).samples
        for a, b in [(0, 0.0060625), (0.0060625, 0.03125), (0.03125, 0.2)]
    ]
    np.testing.assert_allclose(np.concatenate(parts, axis=1), whole.samples, atol=1e-7)
    assert backend.nlos.bakes == 1


def test_closed_open_closed_and_retained_native_snapshot(prepared_nlos):
    backend, session, snapshot = prepared_nlos
    backend.propagate(snapshot, "array", window(0, 0.1))
    history = backend.nlos.history
    # Freeze the scene before moving the actual screen.
    original = history.epochs[0][1]
    a, b = np.array([[2.0, 0, 1.2]]), np.array([[-2.0, 0, 1.2]])
    assert original(a, b)[0]
    session.stage.GetPrimAtPath("/Screen").GetAttribute("xformOp:translate").Set(
        (0, 5, 1.5)
    )
    opened = backend.propagate(snapshot, "array", window(0.1, 0.2))
    assert not history.epochs[-1][1](a, b)[0]
    assert original(a, b)[0]
    assert set(opened.diagnostics["geometry"]["nlos"]["coverage"]["tone"]) == {"los"}
    session.stage.GetPrimAtPath("/Screen").GetAttribute("xformOp:translate").Set(
        (0, 0, 1.5)
    )
    closed = backend.propagate(snapshot, "array", window(0.2, 0.3))
    assert set(closed.diagnostics["geometry"]["nlos"]["coverage"]["tone"]) == {
        "selected"
    }
    assert backend.nlos.bakes == 1


@pytest.mark.parametrize("speed", [0.5, 1.5])
def test_moving_source_read_partition_equivalence(prepared_nlos, speed):
    backend, _, snapshot = prepared_nlos
    source = replace(snapshot.sources[0], velocity_world_mps=(0, speed, 0))
    moving = replace(snapshot, sources=(source,))
    whole = backend.propagate(moving, "array", window(0, 0.4)).samples
    backend.reset()
    cuts = np.array([0, 97, 501, 1703, 3200, 6400]) / 16000
    parts = []
    for a, b in zip(cuts[:-1], cuts[1:], strict=True):
        current = replace(
            moving, sources=(replace(source, position_world=(2, speed * a, 1.2)),)
        )
        parts.append(backend.propagate(current, "array", window(a, b)).samples)
    np.testing.assert_allclose(np.concatenate(parts, axis=1), whole, atol=2e-7)


def test_two_sources_and_two_arrays_are_independent(prepared_nlos):
    backend, _, snapshot = prepared_nlos
    solo = backend.propagate(snapshot, "array", window(0, 0.1)).samples
    backend.reset()
    two = replace(
        snapshot,
        sources=(
            snapshot.sources[0],
            replace(snapshot.sources[0], source_id="second", gain_db=-6),
        ),
        arrays=(snapshot.arrays[0], replace(snapshot.arrays[0], array_id="other")),
    )
    second = backend.propagate(
        replace(two, sources=(two.sources[1],)), "array", window(0, 0.1)
    ).samples
    backend.reset()
    combined = backend.propagate(two, "array", window(0, 0.1)).samples
    other = backend.propagate(two, "other", window(0, 0.1)).samples
    np.testing.assert_allclose(combined, solo + second, atol=1e-7)
    np.testing.assert_array_equal(combined, other)


def test_source_stop_retains_delayed_nlos(prepared_nlos):
    backend, _, snapshot = prepared_nlos
    snapshot = replace(
        snapshot, sources=(replace(snapshot.sources[0], duration_s=0.03),)
    )
    pcm = backend.propagate(snapshot, "array", window(0, 0.3)).samples
    assert np.max(abs(pcm[:, 500:650])) > 1e-4
    assert np.max(abs(pcm[:, 4000:])) < 1e-7
