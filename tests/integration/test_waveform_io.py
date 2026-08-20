from __future__ import annotations

import builtins

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    _scheduled_window_signal,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.io.traces import append_frame_jsonl, frame_from_trace_dict
from isaac_audio_sensors.core.io.waveforms import (
    FrameWaveformWriter,
    waveform_safe_filename,
)
from tests.helpers import (
    CaptureSink,
    install_fake_pyroom,
    quad_array,
    room_scene,
    source,
    time_window,
)


def test_room_backend_exports_mixture_and_trace_path(monkeypatch, tmp_path):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    sink = CaptureSink()
    frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
        room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array),
        array,
        time_window(),
    )

    trace_path = append_frame_jsonl(frame, tmp_path / "frames.jsonl")
    restored = frame_from_trace_dict(__import__("json").loads(trace_path.read_text()))

    assert sink.calls[0]["mixture"].shape[0] == 4
    assert restored.waveform_paths == frame.waveform_paths


def test_scheduled_signal_respects_window_boundaries():
    active = source("pulse", (1.0, 0.0, 0.0), start_time_s=0.02, duration_s=0.01)
    signal = _scheduled_window_signal(
        active,
        time_window=time_window(start_time_s=0.0, end_time_s=0.05),
    ).signal

    assert np.count_nonzero(signal[:960]) == 0
    assert np.count_nonzero(signal[960:1440]) > 0
    assert np.count_nonzero(signal[1440:]) == 0


def test_waveform_filename_is_portable():
    assert waveform_safe_filename("a/b\\c:d e") == "a_b_c_d_e"


def test_writer_reports_missing_optional_codec(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "soundfile":
            raise ImportError("soundfile unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    monkeypatch.delitem(__import__("sys").modules, "soundfile", raising=False)

    with pytest.raises(OptionalDependencyUnavailable, match="room"):
        FrameWaveformWriter(tmp_path / "waves")
