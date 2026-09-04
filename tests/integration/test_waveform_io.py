from __future__ import annotations

import builtins

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.io.traces import append_frame_jsonl, frame_from_trace_dict
from isaac_audio_sensors.core.io.waveforms import (
    ContinuousWaveformWriter,
    FrameWaveformWriter,
    waveform_safe_filename,
)
from isaac_audio_sensors.core.types import AudioTimeWindow, MicrophoneSignalBlock
from tests.helpers import (
    CaptureSink,
    install_fake_pyroom,
    quad_array,
    room_scene,
    run_frame_pipeline,
    source,
    time_window,
)


def test_room_backend_exports_mixture_and_trace_path(monkeypatch, tmp_path):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    sink = CaptureSink()
    frame, block = run_frame_pipeline(
        AnalyticAcoustics(),
        room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array),
        array.array_id,
        time_window(),
        waveform_sink=sink,
    )

    trace_path = append_frame_jsonl(frame, tmp_path / "frames.jsonl")
    restored = frame_from_trace_dict(__import__("json").loads(trace_path.read_text()))

    assert sink.calls[0]["mixture"].shape[0] == 4
    assert sink.calls[0]["block"] is block
    assert restored.waveform_paths == frame.waveform_paths


def test_waveform_filename_is_portable():
    assert waveform_safe_filename("a/b\\c:d e") == "a_b_c_d_e"


def test_continuous_writer_close_does_not_append_beyond_exact_block(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    samples = np.asarray([[0.1, 0.2, 0.3, 0.4]], dtype=np.float32)
    block = MicrophoneSignalBlock(
        samples=samples,
        microphone_ids=("mic",),
        array_id="rig",
        sample_rate_hz=4,
        time_window=AudioTimeWindow(
            start_time_s=0.0, end_time_s=1.0, frame_index=0
        ),
        channel_validity=(True,),
        producer_id="analytic_acoustics",
        provenance="synthetic/core",
    )
    writer = ContinuousWaveformWriter(tmp_path / "continuous.wav")

    writer.write_signal_block(frame_id="frame", block=block)
    writer.close()

    observed, sample_rate = soundfile.read(
        tmp_path / "continuous.wav", dtype="float32", always_2d=True
    )
    assert sample_rate == 4
    assert observed.shape == (4, 1)
    np.testing.assert_array_equal(observed[:, 0], samples[0])


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
