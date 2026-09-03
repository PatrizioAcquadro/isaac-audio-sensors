from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.backends import AnalyticAcoustics
from isaac_audio_sensors.core.backends._analytic import signals
from isaac_audio_sensors.core.directivity import (
    DirectivityPattern,
    evaluate_polar_pattern,
    pair_directivity_gain,
)
from isaac_audio_sensors.core.effects import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSpec,
    SourceOcclusion,
)
from tests.helpers import CaptureSink, install_fake_pyroom, run_frame_pipeline

DB_DOUBLE = 20.0 * math.log10(2.0)
IDENTITY = (0.0, 0.0, 0.0, 1.0)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (DirectivityPattern.OMNI, (1.0, 1.0, 1.0)),
        (DirectivityPattern.CARDIOID, (1.0, 0.5, 0.0)),
        (DirectivityPattern.SUPERCARDIOID, (1.0, 0.37, -0.26)),
        (DirectivityPattern.FIGURE_EIGHT, (1.0, 0.0, -1.0)),
    ],
)
def test_all_directivity_patterns_have_canonical_front_side_rear_values(
    pattern: DirectivityPattern,
    expected: tuple[float, float, float],
) -> None:
    observed = tuple(
        evaluate_polar_pattern(
            pattern,
            orientation_xyzw=IDENTITY,
            direction=direction,
        )
        for direction in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
    )
    assert observed == pytest.approx(expected)
    assert tuple(abs(value) for value in observed) == pytest.approx(
        tuple(abs(value) for value in expected)
    )


@pytest.mark.parametrize(
    "value",
    [True, False, "0", None, math.nan, math.inf, -math.inf, 10_000.0, -10_000.0],
)
def test_db_to_amplitude_gain_rejects_invalid_or_unrepresentable_values(value) -> None:
    with pytest.raises(ValueError):
        db_to_amplitude_gain(value)


def test_db_to_amplitude_gain_uses_relative_amplitude_semantics() -> None:
    assert db_to_amplitude_gain(0.0) == 1.0
    assert db_to_amplitude_gain(DB_DOUBLE) == pytest.approx(2.0)
    assert db_to_amplitude_gain(-DB_DOUBLE) == pytest.approx(0.5)


def test_entity_records_resolve_directivity_and_require_orientation() -> None:
    source = _source(directivity="cardioid", orientation=IDENTITY)
    microphone = MicrophoneSpec(
        mic_id="mic",
        relative_position_m=(0.0, 0.0, 0.0),
        relative_orientation_quat=IDENTITY,
        directivity="figure_eight",
    )
    assert source.directivity is DirectivityPattern.CARDIOID
    assert microphone.directivity is DirectivityPattern.FIGURE_EIGHT
    with pytest.raises(ValueError, match="directivity"):
        _source(directivity="unknown", orientation=IDENTITY)
    with pytest.raises(ValueError, match="orientation_world_quat"):
        _source(directivity="cardioid")
    with pytest.raises(ValueError, match="relative_orientation_quat"):
        MicrophoneSpec(
            mic_id="mic",
            relative_position_m=(0.0, 0.0, 0.0),
            directivity="supercardioid",
        )


@pytest.mark.parametrize("gain_db,expected", [(DB_DOUBLE, 2.0), (-DB_DOUBLE, 0.5)])
def test_analytic_source_and_microphone_gain_ratios(
    monkeypatch,
    gain_db,
    expected,
) -> None:
    install_fake_pyroom(monkeypatch)
    baseline_array = _array()
    source_baseline = _source()
    source_changed = replace(source_baseline, gain_db=gain_db)
    assert _frame_rms(AnalyticAcoustics(), source_changed, baseline_array) / (
        _frame_rms(AnalyticAcoustics(), source_baseline, baseline_array)
    ) == pytest.approx(expected)

    changed_array = replace(
        baseline_array,
        microphones=tuple(
            replace(microphone, gain_db=gain_db)
            if microphone.mic_id == "front"
            else microphone
            for microphone in baseline_array.microphones
        ),
    )
    assert _frame_rms(AnalyticAcoustics(), source_baseline, changed_array) / (
        _frame_rms(AnalyticAcoustics(), source_baseline, baseline_array)
    ) == pytest.approx(expected)


def test_room_waveform_keeps_signed_directivity_while_rms_uses_magnitude(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    omni = _source()
    figure_eight = replace(
        omni,
        directivity=DirectivityPattern.FIGURE_EIGHT,
        orientation_world_quat=IDENTITY,
    )
    omni_sink = CaptureSink()
    directional_sink = CaptureSink()
    omni_frame, _ = run_frame_pipeline(
        AnalyticAcoustics(),
        _scene(omni, array),
        array.array_id,
        _window(),
        waveform_sink=omni_sink,
    )
    directional_frame, _ = run_frame_pipeline(
        AnalyticAcoustics(),
        _scene(figure_eight, array),
        array.array_id,
        _window(),
        waveform_sink=directional_sink,
    )
    omni_waveforms = omni_sink.calls[0]["mixture"]
    directional_waveforms = directional_sink.calls[0]["mixture"]
    positions = microphone_world_positions(array)
    for index, microphone in enumerate(array.microphones):
        factor = pair_directivity_gain(
            source_pattern=figure_eight.directivity,
            microphone_pattern=microphone.directivity,
            source_position_world=figure_eight.position_world,
            source_orientation_world_xyzw=figure_eight.orientation_world_quat,
            microphone_position_world=positions[microphone.mic_id],
            microphone_orientation_world_xyzw=IDENTITY,
        )
        assert factor < 0.0
        assert directional_waveforms[index] == pytest.approx(
            omni_waveforms[index] * factor
        )
        assert directional_frame.aggregate_per_mic_rms[
            microphone.mic_id
        ] == pytest.approx(
            omni_frame.aggregate_per_mic_rms[microphone.mic_id] * abs(factor)
        )


def test_scheduler_applies_gain_once_without_normalizing_file_or_generated_assets(
    monkeypatch,
) -> None:
    base = np.asarray((0.2, -0.4, 0.8, -0.1), dtype=float)
    monkeypatch.setattr(
        signals,
        "_load_public_waveform",
        lambda _path, *, sample_rate_hz: (base.copy(), "file:test.wav"),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.004,
        frame_index=0,
    )
    file_source = _source(
        audio_asset_path="assets/test.wav",
        duration_s=0.004,
        position=(1.0, 0.0, 0.0),
    )
    assert signals._scheduled_window_signal(
        file_source,
        time_window=window,
        sample_rate_hz=1_000,
    ).signal == pytest.approx(base)
    assert signals._scheduled_window_signal(
        replace(file_source, gain_db=DB_DOUBLE),
        time_window=window,
        sample_rate_hz=1_000,
    ).signal == pytest.approx(base * 2.0)

    generated = replace(file_source, audio_asset_path="generated://impulse")
    generated_base = signals._scheduled_window_signal(
        generated,
        time_window=window,
        sample_rate_hz=1_000,
    )
    generated_double = signals._scheduled_window_signal(
        replace(generated, gain_db=DB_DOUBLE),
        time_window=window,
        sample_rate_hz=1_000,
    )
    assert generated_double.signal == pytest.approx(generated_base.signal * 2.0)


def test_pyroom_rir_is_the_only_room_distance_scaling(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    near = _source(position=(1.0, 0.0, 0.0))
    far = replace(near, position_world=(2.0, 0.0, 0.0))
    near_block = AnalyticAcoustics().propagate(
        _scene(near, array), array.array_id, _window()
    )
    far_block = AnalyticAcoustics().propagate(
        _scene(far, array), array.array_id, _window()
    )
    near_peak = float(np.max(np.abs(near_block.samples[0])))
    far_peak = float(np.max(np.abs(far_block.samples[0])))
    front_position = microphone_world_positions(array)["front"]
    near_distance = math.dist(near.position_world, front_position)
    far_distance = math.dist(far.position_world, front_position)
    assert near_peak / far_peak == pytest.approx(far_distance / near_distance)
    assert near_peak / far_peak != pytest.approx((far_distance / near_distance) ** 2)


def test_nominal_and_delta_gains_combine_once_with_distinct_diagnostics(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    base_array = _array()
    array = replace(
        base_array,
        microphones=tuple(
            replace(microphone, gain_db=DB_DOUBLE)
            if microphone.mic_id == "front"
            else microphone
            for microphone in base_array.microphones
        ),
    )
    source = _source(gain_db=DB_DOUBLE)
    occlusion = SourceOcclusion(
        array_id=array.array_id,
        source_id=source.source_id,
        per_mic_blocked={mic.mic_id: True for mic in array.microphones},
        per_mic_attenuation_db={mic.mic_id: 4.0 for mic in array.microphones},
    )
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                "front": ChannelResponseMicConfig(gain_db=-3.0),
            },
        )
    )
    backend = AnalyticAcoustics(effects=effects)
    scene = replace(
        _scene(source, array, occlusion=(occlusion,)),
        environment=free_field_environment(environment_id="gain_free_field"),
    )
    frame, _ = run_frame_pipeline(
        backend,
        scene,
        array.array_id,
        _window(),
    )
    repeated, _ = run_frame_pipeline(
        backend, scene, array.array_id, _window()
    )
    assert frame == repeated
    baseline_scene = replace(
        _scene(_source(), base_array),
        environment=free_field_environment(environment_id="gain_free_field"),
    )
    baseline, _ = run_frame_pipeline(
        AnalyticAcoustics(),
        baseline_scene,
        base_array.array_id,
        _window(),
    )
    expected_ratio = (
        2.0
        * 10.0 ** (-4.0 / 20.0)
        * 2.0
        * 10.0 ** (-3.0 / 20.0)
    )
    observed_ratio = (
        frame.aggregate_per_mic_rms["front"]
        / baseline.aggregate_per_mic_rms["front"]
    )
    assert observed_ratio == pytest.approx(expected_ratio)
    assert frame.observations == ()
    assert "channel_response" in frame.diagnostics["effect_stages"]


def _array() -> MicrophoneArraySpec:
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
    )


def _source(
    *,
    gain_db: float = 0.0,
    directivity: DirectivityPattern | str = DirectivityPattern.OMNI,
    orientation=None,
    audio_asset_path: str = "generated://impulse",
    duration_s: float = 0.05,
    position: tuple[float, float, float] = (3.0, 0.0, 0.0),
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=orientation,
        start_time_s=0.0,
        duration_s=duration_s,
        gain_db=gain_db,
        directivity=directivity,
    )


def _scene(
    source: AudioSourceSpec,
    array: MicrophoneArraySpec,
    *,
    occlusion: tuple[SourceOcclusion, ...] | None = None,
) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="gain_consistency",
        sources=(source,),
        arrays=(array,),
        occlusion=occlusion,
        environment=shoebox_environment(
            environment_id="room",
            dimensions_m=(6.0, 5.0, 3.0),
            position_world=(-1.0, -2.5, -1.5),
            absorption=0.35,
        ),
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.05,
        frame_index=0,
    )


def _frame_rms(backend, source: AudioSourceSpec, array: MicrophoneArraySpec):
    frame, _ = run_frame_pipeline(
        backend, _scene(source, array), array.array_id, _window()
    )
    return frame.aggregate_per_mic_rms["front"]
