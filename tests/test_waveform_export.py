"""Waveform export, mixture, and sample-accurate scheduling tests."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest
from test_isaac_audio_backends import (
    _FakeShoeBox,
    _install_fake_pyroom,
    _room_scene_with_sources,
    _source,
    _window,
)

from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    _resample_waveform,
    _scheduled_window_signal,
)
from isaac_audio_sensors.core.io.traces import (
    append_frame_jsonl,
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.io.waveforms import (
    ContinuousWaveformWriter,
    FrameWaveformWriter,
    WaveformWriteResult,
    waveform_safe_filename,
    write_multichannel_wav,
)
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import AudioSourceSpec

SAMPLE_RATE_HZ = 48_000


class _CaptureSink:
    """In-memory waveform sink for dependency-free mixture assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def write_frame_mixture(
        self,
        *,
        frame_id,
        mixture,
        sample_rate_hz,
        mic_ids,
        window_sample_count,
    ) -> WaveformWriteResult:
        self.calls.append(
            {
                "frame_id": frame_id,
                "mixture": np.array(mixture),
                "sample_rate_hz": sample_rate_hz,
                "mic_ids": mic_ids,
                "window_sample_count": window_sample_count,
            }
        )
        return WaveformWriteResult(
            paths=(f"stub://{frame_id}.wav",),
            diagnostics={"mode": "stub"},
        )

    def close(self) -> None:
        self.closed = True


def _tone_source(
    source_id: str,
    position: tuple[float, float, float],
    *,
    start_time_s: float = 0.0,
    duration_s: float | None = 1.0,
) -> AudioSourceSpec:
    return _source(
        source_id,
        position,
        audio_asset_path=None,
        start_time_s=start_time_s,
        duration_s=duration_s,
    )


def _seeded_frequency_hz(source_id: str) -> float:
    seed = int(hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:8], 16)
    return 550.0 + float(seed % 700)


def _quad_array():
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )


def test_room_acoustics_simulates_all_sources_in_one_room(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        _tone_source("tone_high", (0.0, 3.0, 0.0)),
        array=array,
    )

    frame = RoomAcousticsBackend().simulate(scene, array, _window())

    assert len(_FakeShoeBox.instances) == 1
    assert len(_FakeShoeBox.instances[-1].sources) == 2
    assert len(frame.detections) == 2
    assert frame.diagnostics["window_sample_count"] == SAMPLE_RATE_HZ


def test_two_source_mixture_spectrum_contains_both_sources(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        _tone_source("tone_high", (0.0, 3.0, 0.0)),
        array=array,
    )
    sink = _CaptureSink()

    frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
        scene, array, _window()
    )

    assert frame.waveform_paths and frame.waveform_paths[0].startswith("stub://")
    assert frame.diagnostics["waveform"] == {"mode": "stub"}
    assert len(sink.calls) == 1
    mixture = sink.calls[0]["mixture"]
    assert mixture.shape[0] == 4
    assert mixture.shape[1] >= SAMPLE_RATE_HZ

    channel = mixture[0, :SAMPLE_RATE_HZ]
    spectrum = np.abs(np.fft.rfft(channel))
    median_magnitude = float(np.median(spectrum))
    for source_id in ("tone_low", "tone_high"):
        bin_index = int(round(_seeded_frequency_hz(source_id)))
        peak = float(np.max(spectrum[bin_index - 2 : bin_index + 3]))
        assert peak > 10.0 * median_magnitude, (
            f"{source_id} fundamental missing from mixture spectrum"
        )


def test_aggregate_rms_matches_mixture(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        _tone_source("tone_high", (0.0, 3.0, 0.0)),
        array=array,
    )
    sink = _CaptureSink()

    frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
        scene, array, _window()
    )

    mixture = sink.calls[0]["mixture"]
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    for mic_index, mic_id in enumerate(mic_ids):
        expected = float(np.sqrt(np.mean(mixture[mic_index] ** 2)))
        assert frame.aggregate_per_mic_rms[mic_id] == pytest.approx(expected)


def test_no_active_sources_writes_window_length_silence(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("future", (3.0, 0.0, 0.0), start_time_s=5.0),
        array=array,
    )
    sink = _CaptureSink()

    frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
        scene, array, _window()
    )

    assert frame.detections == ()
    assert frame.waveform_paths
    mixture = sink.calls[0]["mixture"]
    assert mixture.shape == (4, SAMPLE_RATE_HZ)
    assert not np.any(mixture)
    assert all(value == 0.0 for value in frame.aggregate_per_mic_rms.values())


def test_backend_without_sink_keeps_empty_waveform_paths(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        array=array,
    )

    frame = RoomAcousticsBackend().simulate(scene, array, _window())

    assert frame.waveform_paths == ()
    assert "waveform" not in frame.diagnostics


def test_waveform_paths_round_trip_through_jsonl(monkeypatch, tmp_path):
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        array=array,
    )
    frame = RoomAcousticsBackend(waveform_writer=_CaptureSink()).simulate(
        scene, array, _window()
    )

    trace_path = tmp_path / "frames.jsonl"
    append_frame_jsonl(frame, trace_path)
    payload = frame_to_trace_dict(frame)
    restored = frame_from_trace_dict(payload)

    assert restored.waveform_paths == frame.waveform_paths
    assert restored.waveform_paths != ()


def test_scheduled_signal_pads_mid_window_start():
    source = _tone_source("tone_low", (3.0, 0.0, 0.0), start_time_s=0.1)
    scheduled = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.0, end_time_s=1.0),
    )

    offset = int(round(0.1 * SAMPLE_RATE_HZ))
    assert scheduled.start_offset_samples == offset
    assert not np.any(scheduled.signal[:offset])
    assert np.any(scheduled.signal[offset : offset + 1_000])
    assert scheduled.content_sample_count == SAMPLE_RATE_HZ - offset


def test_scheduled_signal_truncates_at_source_end():
    source = _tone_source("tone_low", (3.0, 0.0, 0.0), duration_s=0.03)
    scheduled = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.0, end_time_s=1.0),
    )

    assert scheduled.start_offset_samples == 0
    assert scheduled.content_sample_count == int(round(0.03 * SAMPLE_RATE_HZ))
    assert scheduled.signal.size == scheduled.content_sample_count


def test_scheduled_signal_is_phase_continuous_across_windows():
    source = _tone_source("tone_low", (3.0, 0.0, 0.0), duration_s=None)

    full = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.0, end_time_s=0.1),
    ).signal
    first = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.0, end_time_s=0.05),
    ).signal
    second = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.05, end_time_s=0.1),
    ).signal

    np.testing.assert_allclose(np.concatenate([first, second]), full, atol=1e-12)


def test_scheduled_signal_emits_impulse_spike_exactly_once():
    source = _source(
        "knock",
        (3.0, 0.0, 0.0),
        audio_asset_path="generated://impulse",
        duration_s=None,
    )

    first = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.0, end_time_s=0.05),
    ).signal
    second = _scheduled_window_signal(
        source,
        time_window=_window(start_time_s=0.05, end_time_s=0.1),
    ).signal

    bed_ceiling = 0.2 / 1.2 + 1e-9
    assert float(np.max(np.abs(first))) > 0.5
    assert float(np.max(np.abs(second))) <= bed_ceiling
    spike_index = int(np.argmax(np.abs(first)))
    assert spike_index == max(1, int(round(0.004 * SAMPLE_RATE_HZ)))


def test_resample_waveform_scales_length():
    pytest.importorskip("scipy")
    time_s = np.arange(8_000, dtype=float) / 8_000.0
    tone = np.sin(2.0 * math.pi * 440.0 * time_s)

    resampled = _resample_waveform(tone, from_hz=8_000, to_hz=48_000)

    assert resampled.size == tone.size * 6
    spectrum = np.abs(np.fft.rfft(resampled))
    assert int(np.argmax(spectrum)) == pytest.approx(440, abs=1)


def test_room_acoustics_resamples_mismatched_file_assets(monkeypatch, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    pytest.importorskip("scipy")
    _install_fake_pyroom(monkeypatch)
    monkeypatch.chdir(tmp_path)

    file_rate = 8_000
    time_s = np.arange(int(0.4 * file_rate), dtype=float) / file_rate
    soundfile.write(
        "fixture_tone.wav",
        0.5 * np.sin(2.0 * math.pi * 440.0 * time_s),
        file_rate,
    )
    array = _quad_array()
    source = _source(
        "speaker",
        (3.0, 0.0, 0.0),
        audio_asset_path="fixture_tone.wav",
        duration_s=0.4,
    )
    scene = _room_scene_with_sources(source, array=array)

    frame = RoomAcousticsBackend().simulate(scene, array, _window())

    detection = frame.detections[0]
    assert detection.diagnostics["source_waveform_mode"] == "file:fixture_tone.wav"
    assert detection.diagnostics["scheduled_content_sample_count"] == int(
        round(0.4 * SAMPLE_RATE_HZ)
    )
    assert all(value > 0.0 for value in detection.per_mic_rms.values())


def test_write_multichannel_wav_round_trips(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    rng = np.random.default_rng(11)
    samples = rng.standard_normal((3, 256))

    path = write_multichannel_wav(
        tmp_path / "nested" / "mixture.wav",
        samples,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )

    assert path.is_file()
    data, rate = soundfile.read(path, always_2d=True)
    assert rate == SAMPLE_RATE_HZ
    assert data.shape == (256, 3)
    np.testing.assert_allclose(data.T, samples, atol=1e-6)

    with pytest.raises(ValueError, match="n_channels, n_samples"):
        write_multichannel_wav(
            tmp_path / "bad.wav",
            samples[0],
            sample_rate_hz=SAMPLE_RATE_HZ,
        )


def test_frame_waveform_writer_round_trips(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    rng = np.random.default_rng(7)
    mixture = rng.standard_normal((3, 512))
    writer = FrameWaveformWriter(tmp_path / "waves")

    result = writer.write_frame_mixture(
        frame_id="room_acoustics_stage_rig_0_0",
        mixture=mixture,
        sample_rate_hz=SAMPLE_RATE_HZ,
        mic_ids=("front", "left", "right"),
        window_sample_count=512,
    )

    assert len(result.paths) == 1
    written = Path(result.paths[0])
    assert written.is_file()
    data, rate = soundfile.read(written, always_2d=True)
    assert rate == SAMPLE_RATE_HZ
    assert data.shape == (512, 3)
    np.testing.assert_allclose(data.T, mixture, atol=1e-6)
    assert result.diagnostics["mode"] == "per_frame"
    assert result.diagnostics["channel_mic_ids"] == ["front", "left", "right"]
    assert result.diagnostics["subtype"] == "FLOAT"

    writer.close()
    with pytest.raises(RuntimeError, match="closed"):
        writer.write_frame_mixture(
            frame_id="again",
            mixture=mixture,
            sample_rate_hz=SAMPLE_RATE_HZ,
            mic_ids=("front", "left", "right"),
            window_sample_count=512,
        )


def test_room_backend_writes_frame_wav(monkeypatch, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        _tone_source("tone_high", (0.0, 3.0, 0.0)),
        array=array,
    )
    writer = FrameWaveformWriter(tmp_path / "waves")

    frame = RoomAcousticsBackend(waveform_writer=writer).simulate(
        scene, array, _window()
    )

    assert frame.waveform_paths
    written = Path(frame.waveform_paths[0])
    assert written.is_file()
    data, rate = soundfile.read(written, always_2d=True)
    assert rate == SAMPLE_RATE_HZ
    assert data.shape[1] == 4
    assert data.shape[0] >= SAMPLE_RATE_HZ
    assert np.all(np.isfinite(data))
    mic_ids = [mic.mic_id for mic in array.microphones]
    assert frame.diagnostics["waveform"]["channel_mic_ids"] == mic_ids


def test_room_backend_waveform_output_is_deterministic(monkeypatch, tmp_path):
    pytest.importorskip("soundfile")
    _install_fake_pyroom(monkeypatch)
    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        array=array,
    )
    writer = FrameWaveformWriter(tmp_path / "waves")
    backend = RoomAcousticsBackend(waveform_writer=writer)

    first = backend.simulate(scene, array, _window())
    second = backend.simulate(scene, array, _window())

    assert first == second
    assert first.waveform_paths == second.waveform_paths
    assert len(list((tmp_path / "waves").glob("*.wav"))) == 1


def test_waveform_safe_filename_collapses_unsafe_characters():
    assert waveform_safe_filename("a/b\\c:d e") == "a_b_c_d_e"
    assert waveform_safe_filename("room_acoustics_stage_rig_0_0") == (
        "room_acoustics_stage_rig_0_0"
    )


def test_frame_waveform_writer_requires_soundfile(monkeypatch, tmp_path):
    import builtins

    real_import = builtins.__import__

    def _no_soundfile(name, *args, **kwargs):
        if name == "soundfile":
            raise ImportError("soundfile intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_soundfile)
    monkeypatch.delitem(__import__("sys").modules, "soundfile", raising=False)

    from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable

    with pytest.raises(OptionalDependencyUnavailable, match="room"):
        FrameWaveformWriter(tmp_path / "waves")


def test_isaac_sensor_writes_waveforms_when_configured(monkeypatch, tmp_path):
    pytest.importorskip("soundfile")
    _install_fake_pyroom(monkeypatch)
    from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor

    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        array=array,
    )
    sensor = IsaacAudioArraySensor(
        array_id="rig",
        backend="room_acoustics",
        stage_snapshot=scene,
        waveform_dir=tmp_path / "waves",
    )

    frame = sensor.capture(timestamp_ms=0, start_time_s=0.0, end_time_s=1.0)

    assert frame.waveform_paths
    written = Path(frame.waveform_paths[0])
    assert written.is_file()
    assert written.parent == tmp_path / "waves"
    sensor.close()
    assert sensor._waveform_sink is None


def test_lab_sensor_writes_waveforms_per_env(monkeypatch, tmp_path):
    pytest.importorskip("soundfile")
    pytest.importorskip("torch")
    _install_fake_pyroom(monkeypatch)
    from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor
    from isaac_audio_sensors.lab.audio_array_sensor_cfg import AudioArraySensorCfg

    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0)),
        array=array,
    )
    cfg = AudioArraySensorCfg(
        prim_path="/World/Rig/AudioArray",
        backend="room_acoustics",
        write_waveforms=True,
        waveform_dir=str(tmp_path / "lab_waves"),
    )
    sensor = AudioArraySensor(cfg, sensor=array, scene_snapshot=scene)

    frame = sensor.capture_frame(
        timestamp_ms=0,
        start_time_s=0.0,
        end_time_s=1.0,
    )

    assert frame.waveform_paths
    written = Path(frame.waveform_paths[0])
    assert written.is_file()
    assert written.parent == tmp_path / "lab_waves" / "env_0"


def _session_write(writer, mixture, *, window: int, frame_id: str = "frame"):
    return writer.write_frame_mixture(
        frame_id=frame_id,
        mixture=mixture,
        sample_rate_hz=SAMPLE_RATE_HZ,
        mic_ids=("front", "rear"),
        window_sample_count=window,
    )


def test_continuous_writer_overlap_adds_tails(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    rng = np.random.default_rng(3)
    window = 4
    first = rng.standard_normal((2, 6))
    second = rng.standard_normal((2, 7))
    writer = ContinuousWaveformWriter(tmp_path / "session.wav")

    result_one = _session_write(writer, first, window=window)
    result_two = _session_write(writer, second, window=window)
    writer.close()

    assert result_one.diagnostics["start_sample"] == 0
    assert result_one.diagnostics["end_sample"] == window
    assert result_two.diagnostics["start_sample"] == window
    assert result_two.diagnostics["end_sample"] == 2 * window
    assert result_one.paths == result_two.paths == (str(tmp_path / "session.wav"),)

    expected = np.zeros((2, 11))
    expected[:, :6] += first
    expected[:, 4:11] += second
    data, rate = soundfile.read(tmp_path / "session.wav", always_2d=True)
    assert rate == SAMPLE_RATE_HZ
    np.testing.assert_allclose(data.T, expected, atol=1e-6)


def test_continuous_writer_carries_tails_across_multiple_windows(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    rng = np.random.default_rng(5)
    window = 4
    long_mixture = rng.standard_normal((2, 14))
    silence = np.zeros((2, window))
    writer = ContinuousWaveformWriter(tmp_path / "session.wav")

    _session_write(writer, long_mixture, window=window)
    _session_write(writer, silence, window=window)
    _session_write(writer, silence, window=window)
    writer.close()

    expected = np.zeros((2, 14))
    expected[:, :14] = long_mixture
    data, _ = soundfile.read(tmp_path / "session.wav", always_2d=True)
    np.testing.assert_allclose(data.T, expected, atol=1e-6)


def test_continuous_writer_stream_matches_overlap_add_reference(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    rng = np.random.default_rng(9)
    window = 32
    mixtures = [rng.standard_normal((2, 32 + extra)) for extra in (0, 11, 5, 40)]
    writer = ContinuousWaveformWriter(tmp_path / "session.wav")

    for index, mixture in enumerate(mixtures):
        result = _session_write(
            writer, mixture, window=window, frame_id=f"frame_{index}"
        )
        assert result.diagnostics["start_sample"] == index * window
        assert result.diagnostics["end_sample"] == (index + 1) * window
    writer.close()

    total = len(mixtures) * window + max(
        mixture.shape[1] - window for mixture in mixtures
    )
    reference = np.zeros((2, max(total, len(mixtures) * window)))
    for index, mixture in enumerate(mixtures):
        start = index * window
        reference[:, start : start + mixture.shape[1]] += mixture
    data, _ = soundfile.read(tmp_path / "session.wav", always_2d=True)
    assert data.shape[0] >= len(mixtures) * window
    np.testing.assert_allclose(data.T, reference[:, : data.shape[0]], atol=1e-6)


def test_continuous_writer_rejects_session_parameter_changes(tmp_path):
    pytest.importorskip("soundfile")
    writer = ContinuousWaveformWriter(tmp_path / "session.wav")
    _session_write(writer, np.zeros((2, 4)), window=4)

    with pytest.raises(ValueError, match="session parameters"):
        writer.write_frame_mixture(
            frame_id="frame",
            mixture=np.zeros((3, 4)),
            sample_rate_hz=SAMPLE_RATE_HZ,
            mic_ids=("front", "rear", "left"),
            window_sample_count=4,
        )
    writer.close()
    with pytest.raises(RuntimeError, match="closed"):
        _session_write(writer, np.zeros((2, 4)), window=4)


def test_isaac_sensor_session_mode_streams_across_ticks(monkeypatch, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    _install_fake_pyroom(monkeypatch)
    from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor

    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0), duration_s=None),
        array=array,
    )
    sensor = IsaacAudioArraySensor(
        array_id="rig",
        backend="room_acoustics",
        stage_snapshot=scene,
        waveform_dir=tmp_path / "session",
        waveform_mode="session",
        update_period_s=0.05,
    ).start()

    window_samples = int(round(0.05 * SAMPLE_RATE_HZ))
    frames = [
        sensor.update(sim_time_s=0.00),
        sensor.update(sim_time_s=0.05),
        sensor.update(sim_time_s=0.10),
    ]
    throttled = sensor.update(sim_time_s=0.11)
    assert throttled is frames[-1]

    session_path = Path(frames[0].waveform_paths[0])
    for index, frame in enumerate(frames):
        waveform = frame.diagnostics["waveform"]
        assert waveform["mode"] == "session"
        assert Path(frame.waveform_paths[0]) == session_path
        assert waveform["start_sample"] == index * window_samples
        assert waveform["end_sample"] == (index + 1) * window_samples

    sensor.close()
    data, rate = soundfile.read(session_path, always_2d=True)
    assert rate == SAMPLE_RATE_HZ
    assert data.shape[1] == 4
    assert data.shape[0] >= 3 * window_samples
    assert np.any(data)


def test_isaac_sensor_reset_starts_new_waveform_session(monkeypatch, tmp_path):
    pytest.importorskip("soundfile")
    _install_fake_pyroom(monkeypatch)
    from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor

    array = _quad_array()
    scene = _room_scene_with_sources(
        _tone_source("tone_low", (3.0, 0.0, 0.0), duration_s=None),
        array=array,
    )
    sensor = IsaacAudioArraySensor(
        array_id="rig",
        backend="room_acoustics",
        stage_snapshot=scene,
        waveform_dir=tmp_path / "session",
        waveform_mode="session",
    ).start()

    sensor.update(sim_time_s=0.0)
    assert sensor._waveform_sink is not None
    sensor.reset()
    assert sensor._waveform_sink is None

    frame = sensor.update(sim_time_s=0.0)
    assert frame.diagnostics["waveform"]["start_sample"] == 0
    sensor.close()


def test_audio_config_parses_waveform_export_options():
    from isaac_audio_sensors.core.config import validate_audio_config

    raw = {
        "scene": {"scene_id": "waveform_cfg"},
        "audio": {
            "default_backend": "geometry_only",
            "write_waveforms": True,
            "waveform_dir": "outputs/custom_waves",
        },
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig/AudioArray",
                "microphones": [{"mic_id": "front"}],
            }
        },
    }

    config = validate_audio_config(raw)

    assert config.write_waveforms is True
    assert config.waveform_dir == "outputs/custom_waves"
