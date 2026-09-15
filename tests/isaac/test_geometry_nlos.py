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


def test_nlos_microphone_gain_polarity_and_delay_apply_once(prepared_nlos):
    from isaac_audio_sensors.core.effects import (
        ChannelResponseConfig,
        ChannelResponseMicConfig,
        EffectsConfig,
    )
    from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain

    backend, _, snapshot = prepared_nlos
    plain = backend.propagate(snapshot, "array", window()).samples
    backend.reset()
    first = snapshot.arrays[0].microphones[0].mic_id
    backend.effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                first: ChannelResponseMicConfig(
                    delay_s=2 / 16000, gain_db=6.0, polarity=-1
                )
            },
        )
    )
    backend.chain = ChannelEffectsChain(backend.effects)
    result = backend.propagate(snapshot, "array", window()).samples
    np.testing.assert_allclose(result[0, 2:], -(10**0.3) * plain[0, :-2], atol=1e-7)
    np.testing.assert_allclose(result[0, :2], 0, atol=1e-7)
    np.testing.assert_allclose(result[1:], plain[1:], atol=1e-7)


def test_structural_rebake_preserves_already_emitted_arrivals(prepared_nlos):
    backend, session, snapshot = prepared_nlos
    snapshot = replace(
        snapshot, sources=(replace(snapshot.sources[0], duration_s=0.001),)
    )
    reference = backend.propagate(snapshot, "array", window()).samples
    backend.reset()
    first = backend.propagate(snapshot, "array", window(0, 0.002)).samples
    # Change static bounds/probe IDs after emission, before any NLOS arrival.
    outside = UsdGeom.Cube.Define(session.stage, "/Outside")
    outside.CreateSizeAttr(0.2)
    outside.AddTranslateOp().Set((4, 0, 1.5))
    second = backend.propagate(snapshot, "array", window(0.002, 0.1))
    assert not second.discontinuity and backend.nlos.bakes == 2
    assert np.max(abs(second.samples)) > 1e-5
    np.testing.assert_allclose(
        np.concatenate([first, second.samples], axis=1), reference, atol=1e-7
    )


def test_geometry_epochs_are_independent_of_pcm_subdivision(prepared_nlos):
    backend, session, snapshot = prepared_nlos
    door = session.stage.GetPrimAtPath("/Screen").GetAttribute("xformOp:translate")

    def render(cuts):
        door.Set((0, 0, 1.5))
        backend.reset()
        output = []
        for a, b in zip(cuts[:-1], cuts[1:], strict=True):
            if a == 0.04:
                door.Set((0, 5, 1.5))
            if a == 0.08:
                door.Set((0, 0, 1.5))
            output.append(backend.propagate(snapshot, "array", window(a, b)).samples)
        return np.concatenate(output, axis=1)

    reference = render([0, 0.04, 0.08, 0.12])
    split = render([0, 0.003, 0.017, 0.04, 0.041, 0.069, 0.08, 0.113, 0.12])
    np.testing.assert_allclose(split, reference, atol=1e-7)
    assert [e[0] for e in backend.nlos.history.epochs] == [0.0, 0.04, 0.08]


@pytest.mark.parametrize("opening", [0.002, 0.006])
def test_native_opening_recovers_only_emissions_that_cross_after_opening(
    prepared_nlos, opening
):
    backend, session, snapshot = prepared_nlos
    snapshot = replace(
        snapshot, sources=(replace(snapshot.sources[0], duration_s=0.001),)
    )
    gate = UsdGeom.Cube.Define(session.stage, "/Gate")
    gate.CreateSizeAttr(1.0)
    position = gate.AddTranslateOp()
    position.Set((1, 10, 1.5))
    gate.AddScaleOp().Set((0.02, 8, 3))
    gate.GetPrim().CreateAttribute(DYNAMIC, Sdf.ValueTypeNames.Token).Set("dynamic")
    reference = backend.propagate(snapshot, "array", window()).samples
    backend.reset()
    position.Set((1, 0, 1.5))
    first = backend.propagate(snapshot, "array", window(0, opening)).samples
    assert set(
        backend.streams[(snapshot.stage_id, "array")]["nlos"].states["tone"]
    ) == {"no_selected_route"}
    position.Set((1, 10, 1.5))
    second = backend.propagate(snapshot, "array", window(opening, 0.1)).samples
    result = np.concatenate([first, second], axis=1)
    if opening == 0.002:
        assert np.max(abs(result)) > 1e-5
        np.testing.assert_allclose(result, reference, atol=1e-7)
    else:
        np.testing.assert_allclose(result, 0, atol=1e-7)


def test_nlos_delay_horizon_fails_before_silent_history_retirement(prepared_nlos):
    backend, _, snapshot = prepared_nlos
    backend.config = replace(backend.config, max_delay_s=0.012)
    with pytest.raises(ValueError, match="NLOS route exceeds"):
        backend.propagate(snapshot, "array", window(0, 0.001))
