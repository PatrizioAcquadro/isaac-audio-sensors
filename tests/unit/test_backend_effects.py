from __future__ import annotations

import json
import math

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    FrequencyResponsePointConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from tests.helpers import (
    SAMPLE_RATE_HZ,
    CaptureSink,
    install_fake_pyroom,
    quad_array,
    room_scene,
    source,
    time_window,
)


def _array():
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _scene(array) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="channel_response_l1",
        timestamp_ms=0,
        sources=(
            AudioSourceSpec(
                source_id="speaker",
                prim_path="/World/Speaker",
                class_label="Speech",
                audio_asset_path=None,
                position_world=(3.0, 1.0, 0.0),
                orientation_world_quat=None,
                start_time_s=0.0,
                duration_s=1.0,
                gain_db=-6.0,
            ),
        ),
        arrays=(array,),
    )


def _time_window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
    )


def _effects(
    mic_ids: tuple[str, ...],
    *,
    gain_db: float | None = None,
    delay_s: float | None = None,
    polarity: int | None = None,
) -> EffectsConfig:
    return EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                mic_id: ChannelResponseMicConfig(
                    gain_db=gain_db,
                    delay_s=delay_s,
                    polarity=polarity,
                )
                for mic_id in mic_ids
            },
        )
    )


@pytest.mark.parametrize(
    "stress",
    [
        {},
        {
            "noise_std_s": 1e-6,
            "clock_jitter_s": 2e-6,
            "gain_mismatch_db": 2.0,
            "seed": 33,
        },
    ],
)
def test_l1_gain_and_delay_adapter_is_difference_of_matching_baselines(stress):
    array = _array()
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    scene = _scene(array)
    window = _time_window()
    gain_db = -3.0
    delay_s = 12.5e-6
    baseline = TdoaSyntheticBackend(**stress).simulate(scene, array.array_id, window)
    effected = TdoaSyntheticBackend(
        effects=_effects(mic_ids, gain_db=gain_db, delay_s=delay_s),
        **stress,
    ).simulate(scene, array.array_id, window)

    base_detection = baseline.detections[0]
    effected_detection = effected.detections[0]
    for mic_id in mic_ids:
        recovered_gain = 20.0 * math.log10(
            effected_detection.per_mic_rms[mic_id] / base_detection.per_mic_rms[mic_id]
        )
        recovered_delay = (
            effected_detection.per_mic_delay_s[mic_id]
            - base_detection.per_mic_delay_s[mic_id]
        )
        assert abs(recovered_gain - gain_db) <= 0.05
        assert recovered_delay == pytest.approx(delay_s, abs=1e-12)
    diagnostics = effected.diagnostics["effects"]["channel_response"]
    assert diagnostics["gain_delta_db"] == dict.fromkeys(mic_ids, gain_db)
    assert diagnostics["delay_s"] == dict.fromkeys(mic_ids, delay_s)


def test_l1_polarity_is_honest_metadata_only_and_leaves_observables_exact():
    array = _array()
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    scene = _scene(array)
    window = _time_window()
    baseline = TdoaSyntheticBackend().simulate(scene, array.array_id, window)
    effected = TdoaSyntheticBackend(effects=_effects(mic_ids, polarity=-1)).simulate(
        scene, array.array_id, window
    )

    assert effected.detections[0].per_mic_rms == baseline.detections[0].per_mic_rms
    assert (
        effected.detections[0].per_mic_delay_s == baseline.detections[0].per_mic_delay_s
    )
    assert effected.diagnostics["effects"]["channel_response"]["polarity"] == (
        dict.fromkeys(mic_ids, -1)
    )


def test_l0_gain_adapter_and_effect_offset_diagnostics_do_not_reclassify_doa():
    array = _array()
    scene = _scene(array)
    window = _time_window()
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    baseline = GeometryBackend().simulate(scene, array.array_id, window)
    effected = GeometryBackend(
        effects=_effects(mic_ids, gain_db=6.0, delay_s=10e-6, polarity=-1)
    ).simulate(scene, array.array_id, window)

    for mic_id in mic_ids:
        ratio_db = 20.0 * math.log10(
            effected.detections[0].per_mic_rms[mic_id]
            / baseline.detections[0].per_mic_rms[mic_id]
        )
        assert ratio_db == pytest.approx(6.0, abs=1e-12)
    assert effected.detections[0].doa == baseline.detections[0].doa
    assert effected.detections[0].per_mic_delay_s == {}
    assert effected.diagnostics["effects"]["channel_response"]["delay_s"] == (
        dict.fromkeys(mic_ids, 10e-6)
    )


@pytest.mark.parametrize("backend_type", [GeometryBackend, TdoaSyntheticBackend])
def test_waveform_frequency_response_fails_typed_on_l0_l1_without_partial_frame(
    backend_type,
):
    array = _array()
    points = (
        FrequencyResponsePointConfig(frequency_hz=100.0, magnitude_db=-1.0),
        FrequencyResponsePointConfig(frequency_hz=1_000.0, magnitude_db=0.0),
    )
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"front": ChannelResponseMicConfig(frequency_response=points)},
        )
    )

    with pytest.raises(UnsupportedEffectError, match="waveform-only"):
        backend_type(effects=effects).simulate(
            _scene(array), array.array_id, _time_window()
        )


def _serialized_frame_bytes(frame) -> bytes:
    return (
        json.dumps(
            frame_to_trace_dict(frame),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def test_room_backend_off_state_matches_pristine_reference(
    monkeypatch,
):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    scene = room_scene(
        source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )
    baseline_sink = CaptureSink()
    disabled_sink = CaptureSink()

    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, array.array_id, time_window()
    )
    disabled = RoomAcousticsBackend(
        waveform_writer=disabled_sink,
        effects=EffectsConfig(),
    ).simulate(scene, array.array_id, time_window())

    baseline_frame = _serialized_frame_bytes(baseline)
    disabled_frame = _serialized_frame_bytes(disabled)
    baseline_waveform = baseline_sink.calls[0]["mixture"].tobytes(order="C")
    disabled_waveform = disabled_sink.calls[0]["mixture"].tobytes(order="C")
    assert baseline_frame == disabled_frame
    assert baseline_waveform == disabled_waveform
    assert baseline.diagnostics["directivity"]["mode"] == ("per_pair_direct_path")
    assert "effects" not in disabled.diagnostics


def test_room_backend_effected_premix_drives_detection_aggregate_and_export(
    monkeypatch,
):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    scene = room_scene(
        source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )
    baseline_sink = CaptureSink()
    effected_sink = CaptureSink()
    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, array.array_id, time_window()
    )
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"front": ChannelResponseMicConfig(gain_db=-6.0)},
        )
    )
    effected = RoomAcousticsBackend(
        waveform_writer=effected_sink,
        effects=effects,
    ).simulate(scene, array.array_id, time_window())

    baseline_detection = baseline.detections[0]
    effected_detection = effected.detections[0]
    observed_db = 20.0 * math.log10(
        effected_detection.per_mic_rms["front"]
        / baseline_detection.per_mic_rms["front"]
    )
    assert observed_db == pytest.approx(-6.0, abs=0.05)
    assert effected_detection.per_mic_rms["right"] == pytest.approx(
        baseline_detection.per_mic_rms["right"]
    )
    mixture = effected_sink.calls[0]["mixture"]
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    for mic_index, mic_id in enumerate(mic_ids):
        expected_rms = float(np.sqrt(np.mean(mixture[mic_index] ** 2)))
        assert effected.aggregate_per_mic_rms[mic_id] == pytest.approx(expected_rms)
    assert effected.diagnostics["effects"]["channel_response"] == {
        "applied_mic_ids": ("front",),
        "gain_delta_db": {"front": -6.0},
        "delay_s": {},
        "polarity": {},
    }
    assert "effects" not in effected_detection.diagnostics
