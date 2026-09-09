"""Physical arrival times must not depend on the caller's block partition."""

from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.types import AudioTimeWindow
from tests.integration.test_analytic_acoustics import _array, _scene, _source


def window(start, end, index=0):
    return AudioTimeWindow(start_time_s=start, end_time_s=end, frame_index=index)


@pytest.mark.parametrize("distance", [2.0, 10.0, 40.0])
@pytest.mark.parametrize("hop", [0.01, 0.05, 0.1])
def test_static_arrivals_and_stop_are_partition_independent(distance, hop):
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(_source((distance, 0.0, 1.0)), duration_s=0.12),
    )
    whole = AnalyticAcoustics().propagate(scene, "rig", window(0.0, 0.5)).samples
    backend = AnalyticAcoustics()
    pieces = [
        backend.propagate(scene, "rig", window(i * hop, (i + 1) * hop, i)).samples
        for i in range(round(0.5 / hop))
    ]
    np.testing.assert_allclose(
        np.concatenate(pieces, axis=1), whole, atol=1e-9, rtol=1e-6
    )
    arrival_end = round((0.12 + distance / 343) * 48000)
    assert np.any(whole[:, 5760:arrival_end])
    assert np.max(np.abs(whole[:, arrival_end + 50 :])) < 1e-9


def test_room_reverberant_tail_survives_source_stop():
    pytest.importorskip("pyroomacoustics")
    scene = _scene(
        shoebox_environment(environment_id="room", dimensions_m=(15.0, 8.0, 3.0)),
        array=_array(position_world=(1.0, 1.0, 1.0)),
        source=replace(_source((11.0, 1.0, 1.0)), duration_s=0.12),
    )
    whole = (
        AnalyticAcoustics(max_order=2).propagate(scene, "rig", window(0.0, 0.5)).samples
    )
    backend = AnalyticAcoustics(max_order=2)
    pieces = [
        backend.propagate(scene, "rig", window(i * 0.05, (i + 1) * 0.05, i)).samples
        for i in range(10)
    ]
    np.testing.assert_allclose(
        np.concatenate(pieces, axis=1), whole, atol=1e-8, rtol=1e-6
    )
    assert np.any(whole[:, 7200:9600])


@pytest.mark.parametrize(
    "source_velocity,receiver_velocity",
    [(-20.0, 0.0), (20.0, 0.0), (0.0, 10.0), (-10.0, 5.0)],
)
def test_retarded_motion_is_partition_independent(source_velocity, receiver_velocity):
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(
            _source((20.0, 0.0, 1.0)),
            duration_s=1.0,
            velocity_world_mps=(source_velocity, 0.0, 0.0),
        ),
        array=replace(_array(), velocity_world_mps=(receiver_velocity, 0.0, 0.0)),
    )
    whole = AnalyticAcoustics().propagate(scene, "rig", window(0.0, 0.4)).samples
    backend = AnalyticAcoustics()
    pieces = []
    for i in range(8):
        t = i * 0.05
        current = replace(
            scene,
            sources=(
                replace(
                    scene.sources[0],
                    position_world=(20.0 + source_velocity * t, 0.0, 1.0),
                ),
            ),
            arrays=(
                replace(
                    scene.arrays[0], position_world=(receiver_velocity * t, 0.0, 1.0)
                ),
            ),
        )
        pieces.append(backend.propagate(current, "rig", window(t, t + 0.05, i)).samples)
    np.testing.assert_allclose(
        np.concatenate(pieces, axis=1), whole, atol=1e-8, rtol=2e-5
    )


def test_removed_emitter_drains_and_explicit_reset_discards_history():
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(_source((40.0, 0.0, 1.0)), duration_s=None),
    )
    backend = AnalyticAcoustics()
    backend.propagate(scene, "rig", window(0.0, 0.1))
    removed = replace(scene, sources=())
    block = backend.propagate(removed, "rig", window(0.1, 0.2, 1))
    assert np.any(block.samples)
    backend.reset()
    assert not np.any(backend.propagate(removed, "rig", window(0.2, 0.3, 2)).samples)


@pytest.mark.parametrize(
    "source_speed,listener_speed",
    [(-20.0, 0.0), (20.0, 0.0), (0.0, 15.0), (-10.0, 5.0)],
)
def test_frequency_and_level_follow_the_same_retarded_path(
    tmp_path, monkeypatch, source_speed, listener_speed
):
    sf = pytest.importorskip("soundfile")
    scipy_signal = pytest.importorskip("scipy.signal")
    monkeypatch.chdir(tmp_path)
    fs = 48000
    sf.write(
        "tone.wav",
        0.5 * np.sin(2 * np.pi * 1000 * np.arange(2 * fs) / fs),
        fs,
        subtype="FLOAT",
    )
    source = replace(
        _source((20.0, 0.0, 1.0)),
        audio_asset_path="tone.wav",
        duration_s=2.0,
        velocity_world_mps=(source_speed, 0.0, 0.0),
    )
    array = replace(_array(), velocity_world_mps=(listener_speed, 0.0, 0.0))
    scene = _scene(
        free_field_environment(environment_id="free"), source=source, array=array
    )
    samples = AnalyticAcoustics().propagate(scene, "rig", window(0.0, 0.4)).samples[0]
    # Collinear closed form, including the microphone's offset from the array centre.
    t = np.arange(len(samples)) / fs
    mic_x = array.microphones[0].relative_position_m[0]
    tau = (20 - mic_x + (source_speed - listener_speed) * t) / (343 + source_speed)
    distance = 343 * tau
    expected = 0.5 * np.sin(2 * np.pi * 1000 * (t - tau)) / (4 * np.pi * distance)
    interior = slice(6000, 18000)
    np.testing.assert_allclose(
        samples[interior], expected[interior], atol=2e-5, rtol=0.004
    )
    phase = np.unwrap(np.angle(scipy_signal.hilbert(samples[interior])))
    measured = np.polyfit(np.arange(len(phase))[500:-500] / fs, phase[500:-500], 1)[
        0
    ] / (2 * np.pi)
    expected_frequency = 1000 * (343 + listener_speed) / (343 + source_speed)
    assert measured == pytest.approx(expected_frequency, abs=0.6)


@pytest.mark.parametrize(
    "kind", ["shoebox", "polygon_prism", "half_space", "banded_half_space"]
)
def test_moving_room_image_paths_keep_phase_between_blocks(kind):
    pytest.importorskip("pyroomacoustics")
    environment = {
        "shoebox": shoebox_environment(
            environment_id="r", dimensions_m=(15.0, 8.0, 3.0)
        ),
        "polygon_prism": polygon_prism_environment(
            environment_id="r",
            floor_vertices_local_m=(
                (0.0, 0.0, 0.0),
                (15.0, 0.0, 0.0),
                (15.0, 8.0, 0.0),
                (0.0, 8.0, 0.0),
            ),
            height_m=3.0,
        ),
        "half_space": half_space_environment(environment_id="r"),
        "banded_half_space": half_space_environment(
            environment_id="r", absorption={"125": 0.1, "1000": 0.5, "8000": 0.9}
        ),
    }[kind]
    scene = _scene(
        environment,
        array=_array(position_world=(1.0, 1.0, 1.0)),
        source=replace(_source((10.0, 2.0, 1.0)), velocity_world_mps=(-3.0, 0.0, 0.0)),
    )
    whole = (
        AnalyticAcoustics(max_order=1).propagate(scene, "rig", window(0.0, 0.4)).samples
    )
    backend = AnalyticAcoustics(max_order=1)
    pieces = []
    for i in range(8):
        t = i * 0.05
        current = replace(
            scene,
            sources=(
                replace(scene.sources[0], position_world=(10.0 - 3 * t, 2.0, 1.0)),
            ),
        )
        pieces.append(backend.propagate(current, "rig", window(t, t + 0.05, i)).samples)
    joined = np.concatenate(pieces, axis=1)
    # Provider image coordinates are float32; compare against their resolution.
    assert np.linalg.norm(joined - whole) / np.linalg.norm(whole) < 1e-4


def test_channel_fir_and_delay_receive_real_history(tmp_path, monkeypatch):
    from isaac_audio_sensors.core.effects.config import (
        ChannelResponseConfig,
        ChannelResponseMicConfig,
        EffectsConfig,
        FrequencyResponsePointConfig,
    )

    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                "front": ChannelResponseMicConfig(
                    delay_s=0.0025,
                    frequency_response=(
                        FrequencyResponsePointConfig(frequency_hz=100, magnitude_db=-3),
                        FrequencyResponsePointConfig(frequency_hz=4000, magnitude_db=0),
                    ),
                )
            },
        )
    )
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(_source(), duration_s=None),
    )
    whole = (
        AnalyticAcoustics(effects=effects)
        .propagate(scene, "rig", window(0.0, 0.4))
        .samples
    )
    backend = AnalyticAcoustics(effects=effects)
    joined = np.concatenate(
        [
            backend.propagate(scene, "rig", window(i * 0.05, (i + 1) * 0.05, i)).samples
            for i in range(8)
        ],
        axis=1,
    )
    assert np.linalg.norm(joined - whole) / np.linalg.norm(whole) < 1e-4


def test_overlap_rewind_and_stream_isolation():
    scene = _scene(free_field_environment(environment_id="free"))
    backend = AnalyticAcoustics()
    first = backend.propagate(scene, "rig", window(0, 0.2))
    overlapping = backend.propagate(scene, "rig", window(0.1, 0.3, 1))
    np.testing.assert_array_equal(
        first.samples[:, 4800:], overlapping.samples[:, :4800]
    )
    assert not overlapping.discontinuity
    other = replace(scene, stage_id="other", sources=())
    assert not np.any(backend.propagate(other, "rig", window(0.3, 0.4)).samples)
    rewound = backend.propagate(scene, "rig", window(0, 0.2))
    assert rewound.discontinuity
    np.testing.assert_array_equal(first.samples, rewound.samples)
    backend.reset()
    assert backend.propagate(scene, "rig", window(0, 0.2)).discontinuity


def test_file_loops_and_delayed_start_keep_the_emission_clock(tmp_path, monkeypatch):
    sf = pytest.importorskip("soundfile")
    monkeypatch.chdir(tmp_path)
    dry = np.random.default_rng(5).normal(0, 0.1, 961)
    sf.write("loop.wav", dry, 48000, subtype="FLOAT")
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(
            _source((40.0, 0.0, 1.0)),
            audio_asset_path="loop.wav",
            start_time_s=0.013,
            duration_s=None,
            loop_count=3,
        ),
    )
    expected = AnalyticAcoustics().propagate(scene, "rig", window(0, 0.4)).samples
    backend = AnalyticAcoustics()
    actual = np.concatenate(
        [
            backend.propagate(scene, "rig", window(i * 0.01, (i + 1) * 0.01, i)).samples
            for i in range(40)
        ],
        axis=1,
    )
    np.testing.assert_array_equal(actual, expected)
    assert np.any(actual[:, 7000:9000])
    assert not np.any(actual[:, 11000:])


def test_pass_waveform_and_inter_microphone_arrivals(tmp_path, monkeypatch):
    sf = pytest.importorskip("soundfile")
    monkeypatch.chdir(tmp_path)
    fs = 48000
    sf.write(
        "tone.wav",
        0.1 * np.sin(2 * np.pi * 700 * np.arange(3 * fs) / fs),
        fs,
        subtype="FLOAT",
    )
    p0 = np.array([6.0, 3.0, 1.0])
    velocity = np.array([-6.0, 0.0, 0.0])
    scene = _scene(
        free_field_environment(environment_id="free"),
        source=replace(
            _source(tuple(p0)),
            audio_asset_path="tone.wav",
            duration_s=3.0,
            velocity_world_mps=tuple(velocity),
        ),
    )
    actual = AnalyticAcoustics().propagate(scene, "rig", window(0, 2)).samples
    t = np.arange(actual.shape[1]) / fs
    for mic, values in zip(scene.arrays[0].microphones, actual, strict=True):
        receiver = np.array(scene.arrays[0].position_world) + mic.relative_position_m
        q = receiver - p0 - t[:, None] * velocity
        qv = q @ velocity
        denominator = 343**2 - velocity @ velocity
        tau = (
            qv + np.sqrt(qv * qv + denominator * np.sum(q * q, axis=1))
        ) / denominator
        expected = 0.1 * np.sin(2 * np.pi * 700 * (t - tau)) / (4 * np.pi * 343 * tau)
        interior = t > 0.1
        assert (
            np.linalg.norm(values[interior] - expected[interior])
            / np.linalg.norm(expected[interior])
            < 0.002
        )


def test_piecewise_paths_and_channel_history_share_one_clock():
    from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
    from isaac_audio_sensors.core.effects.config import (
        ChannelResponseConfig,
        ChannelResponseMicConfig,
    )
    from isaac_audio_sensors.core.motion.window_motion import (
        SegmentEntityMotion,
        WindowMotionPlan,
        WindowMotionSegment,
    )

    pytest.importorskip("pyroomacoustics")
    scene = _scene(
        shoebox_environment(environment_id="room", dimensions_m=(15.0, 8.0, 3.0)),
        array=_array(position_world=(1.0, 1.0, 1.0)),
        source=replace(_source((10.0, 2.0, 1.0)), velocity_world_mps=(-3.0, 0.0, 0.0)),
    )
    channel = ChannelResponseConfig(
        enabled=True, microphones={"front": ChannelResponseMicConfig(delay_s=0.0025)}
    )
    effects = EffectsConfig(channel_response=channel)
    expected = (
        AnalyticAcoustics(max_order=1, effects=effects)
        .propagate(scene, "rig", window(0, 0.4))
        .samples
    )
    backend = AnalyticAcoustics(
        max_order=1,
        effects=replace(
            effects,
            motion=MotionEffectsConfig(
                derive_velocity_from_poses=True, segments_per_window=2
            ),
        ),
    )
    pieces = []
    for i in range(8):
        start = i * 0.05
        segments = []
        for j in range(2):
            a = start + j * 0.025
            b = a + 0.025
            entities = {}
            for identifier, p, v in [
                ("speaker", np.array([10.0, 2.0, 1.0]), np.array([-3.0, 0.0, 0.0])),
                ("rig", np.array([1.0, 1.0, 1.0]), np.zeros(3)),
            ]:
                entities[identifier] = SegmentEntityMotion(
                    start_position_world_m=tuple(p + v * a),
                    end_position_world_m=tuple(p + v * b),
                    midpoint_position_world_m=tuple(p + v * (a + b) / 2),
                    velocity_world_mps=tuple(v),
                    velocity_source="authored",
                )
            segments.append(
                WindowMotionSegment(
                    index=j,
                    start_sample=j * 1200,
                    end_sample=(j + 1) * 1200,
                    start_time_s=a,
                    end_time_s=b,
                    entities=entities,
                )
            )
        backend.window_motion = WindowMotionPlan(
            sample_rate_hz=48000, window_sample_count=2400, segments=tuple(segments)
        )
        current = replace(
            scene,
            sources=(
                replace(scene.sources[0], position_world=(10.0 - 3 * start, 2.0, 1.0)),
            ),
        )
        pieces.append(
            backend.propagate(current, "rig", window(start, start + 0.05, i)).samples
        )
    actual = np.concatenate(pieces, axis=1)
    assert np.linalg.norm(actual - expected) / np.linalg.norm(expected) < 1e-4


def test_moving_and_stationary_room_sources_keep_linear_superposition():
    pytest.importorskip("pyroomacoustics")
    scene = _scene(
        shoebox_environment(environment_id="room", dimensions_m=(15.0, 8.0, 3.0)),
        array=_array(position_world=(1.0, 1.0, 1.0)),
        source=replace(_source((10.0, 2.0, 1.0)), velocity_world_mps=(-3.0, 0.0, 0.0)),
    )
    stationary = replace(_source((3.0, 5.0, 1.0)), source_id="other", gain_db=-6.0)
    combined = replace(scene, sources=scene.sources + (stationary,))
    interval = window(0, 0.2)
    actual = AnalyticAcoustics(max_order=1).propagate(combined, "rig", interval).samples
    expected = (
        AnalyticAcoustics(max_order=1).propagate(scene, "rig", interval).samples
        + AnalyticAcoustics(max_order=1)
        .propagate(replace(scene, sources=(stationary,)), "rig", interval)
        .samples
    )
    np.testing.assert_allclose(actual, expected, atol=2e-8, rtol=1e-5)
