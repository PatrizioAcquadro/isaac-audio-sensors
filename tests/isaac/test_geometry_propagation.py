"""Native received-PCM correctness at the GeometryAcoustics boundary."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pxr")
from pxr import Usd, UsdGeom  # noqa: E402

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import AudioSceneSnapshot, AudioTimeWindow
from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene.propagation import (
    GeometryAcoustics,
    GeometryAcousticsConfig,
)
from tests.helpers import source

LIBRARY = (
    Path(__file__).resolve().parents[2]
    / "build/qualification/r9/steam-audio/core/build/r9-release/src/core/libphonon.so"
)


def window(start=0, end=0.1, index=0):
    return AudioTimeWindow(start_time_s=start, end_time_s=end, frame_index=index)


@pytest.fixture
def prepared():
    if not LIBRARY.exists():
        pytest.skip("Qualified optional Steam library is unavailable.")
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    marker = UsdGeom.Cube.Define(stage, "/RemoteGeometry")
    marker.AddTranslateOp().Set((1000, 1000, -1000))
    session = AcousticSceneSession(stage)
    yield session
    session.close()


def scene():
    array = create_microphone_array(
        array_id="array",
        prim_path="/Array",
        layout_name="quad_cross",
        sample_rate_hz=16000,
    )
    return AudioSceneSnapshot(
        stage_id="geometry-test",
        arrays=(array,),
        sources=(source("tone", (2, 0, 0), audio_asset_path="generated://tone"),),
        environment=free_field_environment(environment_id="free"),
    )


def backend(prepared, **kwargs):
    return GeometryAcoustics(
        acoustic_scene=prepared,
        geometry_config=GeometryAcousticsConfig(
            library_path=str(LIBRARY),
            specular_library_path=str(
                Path(__file__).resolve().parents[2] / "build/native/libias_specular.so"
            ),
            **kwargs,
        ),
    )


def test_direct_native_pcm_matches_analytic_and_split_blocks(prepared):
    snapshot = scene()
    geometry = backend(prepared, reflection_order=0)
    try:
        a = geometry.propagate(snapshot, "array", window()).samples
        expected = AnalyticAcoustics().propagate(snapshot, "array", window()).samples
        # Native filters settle at startup; compare physical amplitude and phase.
        assert_pcm_equivalent(a[:, 1000:], expected[:, 1000:])
        geometry.reset()
        pieces = [
            geometry.propagate(snapshot, "array", window(i / 16000, j / 16000, k))
            for k, (i, j) in enumerate(((0, 267), (267, 533), (533, 1600)))
        ]
        np.testing.assert_allclose(
            a, np.concatenate([p.samples for p in pieces], axis=1), atol=2e-8, rtol=2e-6
        )
        assert pieces[0].discontinuity
    finally:
        geometry.close()


def test_geometry_rejects_invalid_clock_and_closed_session(prepared):
    geometry = backend(prepared, reflection_order=0)
    geometry.propagate(scene(), "array", window())
    with pytest.raises(ValueError, match="backwards"):
        geometry.propagate(scene(), "array", window())
    geometry.close()
    with pytest.raises(RuntimeError, match="closed"):
        geometry.propagate(scene(), "array", window(0.1, 0.2, 1))


def test_native_reflections_and_blocked_direct(prepared):
    stage = prepared.stage
    # Six opaque box faces enclosing both endpoints, plus a direct-path blocker.
    for i, (pos, scale) in enumerate(
        (
            ((0, 0, -1), (10, 10, 0.1)),
            ((0, 0, 3), (10, 10, 0.1)),
            ((-5, 0, 1), (0.1, 10, 4)),
            ((5, 0, 1), (0.1, 10, 4)),
            ((0, -5, 1), (10, 0.1, 4)),
            ((0, 5, 1), (10, 0.1, 4)),
            ((1, 0, 0), (0.1, 1, 1)),
        )
    ):
        cube = UsdGeom.Cube.Define(stage, f"/Wall{i}")
        cube.GetSizeAttr().Set(1.0)
        cube.AddTranslateOp().Set(pos)
        cube.AddScaleOp().Set(scale)
    snapshot = scene()
    direct = backend(prepared, reflection_order=0)
    reflected = backend(prepared, reflection_order=2)
    try:
        d = direct.propagate(snapshot, "array", window(0, 0.3)).samples
        r = reflected.propagate(snapshot, "array", window(0, 0.3)).samples
        assert np.max(np.abs(d)) < 1e-7
        assert np.min(np.sqrt(np.mean(r * r, axis=1))) > 1e-5
    finally:
        direct.close()
        reflected.close()


def test_short_distance_native_gain(prepared):
    snapshot = scene()
    snapshot = replace(
        snapshot, sources=(replace(snapshot.sources[0], position_world=(0.4, 0, 0)),)
    )
    geometry = backend(prepared, reflection_order=0)
    try:
        a = geometry.propagate(snapshot, "array", window()).samples
        b = AnalyticAcoustics().propagate(snapshot, "array", window()).samples
        assert_pcm_equivalent(a[:, 1000:], b[:, 1000:])
    finally:
        geometry.close()


def assert_pcm_equivalent(actual, expected):
    # Different qualified fractional interpolators need not match at zero crossings.
    for a, b in zip(actual, expected, strict=True):
        assert np.corrcoef(a, b)[0, 1] >= 0.999
        assert abs(20 * np.log10(np.linalg.norm(a) / np.linalg.norm(b))) <= 0.2
        assert np.linalg.norm(a - b) / np.linalg.norm(b) <= 0.03


def test_slow_motion_received_phase_and_gain(prepared, tmp_path, monkeypatch):
    import soundfile as sf

    rate = 16000
    path = tmp_path / "tone.wav"
    sf.write(
        path,
        np.sin(2 * np.pi * 1200 * np.arange(rate * 2) / rate),
        rate,
        subtype="FLOAT",
    )
    monkeypatch.chdir(tmp_path)
    snapshot = scene()
    original = replace(
        snapshot.sources[0], audio_asset_path="tone.wav", duration_s=None
    )
    geometry = backend(prepared, reflection_order=0)
    rows = []
    try:
        for tick in range(60):
            start, end = round(tick * rate / 60), round((tick + 1) * rate / 60)
            moving = replace(
                snapshot,
                sources=(
                    replace(original, position_world=(2 + 0.1 * end / rate, 0, 0)),
                ),
            )
            rows.append(
                geometry.propagate(
                    moving, "array", window(start / rate, end / rate, tick)
                ).samples
            )
        actual = np.concatenate(rows, axis=1)
        from isaac_audio_sensors.core.microphone_array import microphone_world_positions

        positions = list(microphone_world_positions(snapshot.arrays[0]).values())
        times = np.arange(rate) / rate
        for row, point in zip(actual, positions, strict=True):
            delay = np.linalg.norm(np.array([2.0, 0, 0]) - point) / 343 * np.ones(rate)
            for _ in range(4):
                locations = np.column_stack(
                    (2 + 0.1 * (times - delay), np.zeros(rate), np.zeros(rate))
                )
                distance = np.linalg.norm(locations - point, axis=1)
                delay = distance / 343
            expected = np.sin(2 * np.pi * 1200 * (times - delay)) / (
                4 * np.pi * distance
            )
            assert np.corrcoef(row[1600:], expected[1600:])[0, 1] >= 0.999
            assert (
                np.linalg.norm(row[1600:] - expected[1600:])
                / np.linalg.norm(expected[1600:])
                < 0.04
            )
    finally:
        geometry.close()


def test_channel_response_partitioning_and_session_reset(prepared):
    from isaac_audio_sensors.core.effects import (
        ChannelResponseConfig,
        ChannelResponseMicConfig,
        EffectsConfig,
    )

    snapshot = scene()
    first_mic = snapshot.arrays[0].microphones[0].mic_id
    geometry = backend(prepared, reflection_order=0)
    geometry.effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                first_mic: ChannelResponseMicConfig(
                    delay_s=0.001, gain_db=-6.0, polarity=-1
                )
            },
        )
    )
    from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain

    geometry.chain = ChannelEffectsChain(geometry.effects)
    try:
        whole = geometry.propagate(snapshot, "array", window()).samples
        geometry.reset()
        split = np.concatenate(
            [
                geometry.propagate(
                    snapshot, "array", window(i / 16000, j / 16000)
                ).samples
                for i, j in [(0, 267), (267, 533), (533, 1600)]
            ],
            axis=1,
        )
        np.testing.assert_allclose(split, whole, atol=3e-8, rtol=2e-6)
        prepared.reset()
        restarted = geometry.propagate(snapshot, "array", window())
        assert restarted.discontinuity
        np.testing.assert_allclose(restarted.samples, whole, atol=3e-8, rtol=2e-6)
    finally:
        geometry.close()
