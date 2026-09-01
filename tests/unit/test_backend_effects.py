from __future__ import annotations

import json
import math

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.effects import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from tests.helpers import (
    CaptureSink,
    install_fake_pyroom,
    quad_array,
    room_scene,
    source,
    time_window,
)


def _serialized_frame_bytes(frame) -> bytes:
    return (
        json.dumps(frame_to_trace_dict(frame), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def test_analytic_off_state_matches_pristine_reference(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    scene = room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array)
    baseline_sink = CaptureSink()
    disabled_sink = CaptureSink()

    baseline = AnalyticAcoustics(waveform_writer=baseline_sink).simulate(
        scene, array.array_id, time_window()
    )
    disabled = AnalyticAcoustics(
        waveform_writer=disabled_sink,
        effects=EffectsConfig(),
    ).simulate(scene, array.array_id, time_window())

    assert _serialized_frame_bytes(baseline) == _serialized_frame_bytes(disabled)
    assert baseline_sink.calls[0]["mixture"].tobytes() == disabled_sink.calls[0][
        "mixture"
    ].tobytes()
    assert baseline.diagnostics["directivity"]["mode"] == "per_pair_direct_path"
    assert "effects" not in disabled.diagnostics


def test_analytic_effected_premix_drives_detection_aggregate_and_export(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    scene = room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array)
    baseline_sink = CaptureSink()
    effected_sink = CaptureSink()
    baseline = AnalyticAcoustics(waveform_writer=baseline_sink).simulate(
        scene, array.array_id, time_window()
    )
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"front": ChannelResponseMicConfig(gain_db=-6.0)},
        )
    )
    effected = AnalyticAcoustics(
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
