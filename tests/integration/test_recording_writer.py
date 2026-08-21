"""Black-box recorder lifecycle tests."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    SessionDataset,
    SessionRecorder,
    validate_dataset,
)


def _configuration(*, aligned: bool, dataset_id: str = "recording_test") -> dict:
    return {
        "backend_id": "tdoa_synthetic",
        "channel_order": ["front", "rear"],
        "dataset_id": dataset_id,
        "dtype": "float32",
        "hop_sample_count": 4,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 48_000,
        "session_seed": 22,
        "shard_episode_aligned": aligned,
        "shard_max_frames": 3,
        "split_grouping_key": "scene_id",
        "window_sample_count": 6,
    }


def _kwargs() -> dict:
    return {
        "creation": CreationProvenance(
            tool_name="recording_test",
            tool_version="1",
            backend_id="tdoa_synthetic",
            estimator_id="test",
        ),
        "device": DeviceProvenance(
            device_id="host",
            device_type="synthetic",
            platform="test",
            compute_device="cpu",
        ),
        "license": "CC0-1.0",
        "source": "recording test",
        "coordinate_frames": ("world", "array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1_767_225_600_000,
    }


def _frame(global_index: int, local_index: int) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"producer_{local_index}",
        frame_name=f"frame_{global_index}",
        timestamp_ms=local_index,
        start_time_s=local_index / 1_000,
        end_time_s=local_index / 1_000 + 0.001,
        sample_rate_hz=48_000,
        frame_index=local_index,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        aggregate_per_mic_rms={"front": 0.1, "rear": 0.1},
        diagnostics={"index": global_index},
    )


def _audio(index: int) -> np.ndarray:
    return np.full((2, 6), index / 32, dtype=np.float32)


def _record(root: Path, *, aligned: bool) -> None:
    recorder = SessionRecorder(root, _configuration(aligned=aligned), **_kwargs())
    global_index = 0
    for episode, count in enumerate((2, 2, 3)):
        scene = "scene"
        recorder.begin_episode(scene, f"env_{episode}", scene)
        for local_index in range(count):
            assert recorder.append_frame(
                _frame(global_index, local_index),
                _audio(global_index),
                is_reset=local_index == 0,
            ).accepted
            global_index += 1
        recorder.end_episode()
    recorder.finalize()


@pytest.mark.parametrize("aligned", (False, True))
def test_recording_is_deterministic_and_loadable(tmp_path, aligned):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _record(first, aligned=aligned)
    _record(second, aligned=aligned)

    def files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    assert files(first) == files(second)
    assert len(list(SessionDataset.open(first).iter_records())) == 7
    assert validate_dataset(first).status == "passed"


def test_cancel_publishes_only_verified_shards(tmp_path):
    recorder = SessionRecorder(
        tmp_path / "cancel", _configuration(aligned=False), **_kwargs()
    )
    recorder.begin_episode("scene", "env", "scene")
    for index in range(4):
        assert recorder.append_frame(_frame(index, index), _audio(index)).accepted
    manifest = recorder.cancel()

    assert manifest.completion_state == "incomplete"
    assert all(shard.completion_state == "complete" for shard in manifest.shards)
    assert (
        validate_dataset(tmp_path / "cancel", allow_incomplete=True).status == "passed"
    )


def test_resume_after_process_crash_matches_control(tmp_path):
    crashed = tmp_path / "crashed"
    script = textwrap.dedent(
        """
        import os, sys
        from isaac_audio_sensors.recording import SessionRecorder
        from tests.integration.test_recording_writer import (
            _audio, _configuration, _frame, _kwargs
        )
        root = sys.argv[1]
        recorder = SessionRecorder(root, _configuration(aligned=False), **_kwargs())
        recorder.begin_episode('scene', 'env', 'scene')
        for i in range(4):
            recorder.append_frame(_frame(i, i), _audio(i))
        os._exit(0)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(crashed)],
        env={"PYTHONPATH": "src"},
        check=False,
    )
    assert completed.returncode == 0

    recorder = SessionRecorder.resume(
        crashed, _configuration(aligned=False), **_kwargs()
    )
    assert recorder.next_dataset_frame_index == 3
    for index in range(3, 5):
        assert recorder.append_frame(_frame(index, index), _audio(index)).accepted
    recorder.end_episode()
    recorder.finalize()
    assert [
        item.frame.frame_id for item in SessionDataset.open(crashed).iter_records()
    ] == [f"producer_{index}" for index in range(5)]


def test_finalization_recovery_never_exposes_false_complete(tmp_path, monkeypatch):
    root = tmp_path / "recover"
    recorder = SessionRecorder(root, _configuration(aligned=False), **_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    for index in range(3):
        recorder.append_frame(_frame(index, index), _audio(index))
    recorder.end_episode()

    import isaac_audio_sensors.recording.recorder as recorder_module

    real_write = recorder_module.write_json_atomic

    def fail_manifest(path, payload):
        if Path(path).name == "manifest.json":
            raise OSError("simulated finalization interruption")
        return real_write(path, payload)

    monkeypatch.setattr(recorder_module, "write_json_atomic", fail_manifest)
    with pytest.raises(OSError, match="interruption"):
        recorder.finalize()
    assert not (root / "manifest.json").exists()
    monkeypatch.setattr(recorder_module, "write_json_atomic", real_write)

    manifest = SessionRecorder.recover_finalization(root)
    assert manifest.completion_state == "complete"
    assert validate_dataset(root).status == "passed"
