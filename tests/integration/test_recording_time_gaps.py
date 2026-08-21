"""Automatic time-gap placement tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    SessionDataset,
    SessionRecorder,
    validate_dataset,
)


def _configuration() -> dict:
    return {
        "backend_id": "tdoa_synthetic",
        "channel_order": ["mic"],
        "dataset_id": "time_gap_test",
        "dtype": "float32",
        "hop_sample_count": 4,
        "preserve_time_gaps": True,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 1_000,
        "session_seed": 1,
        "shard_episode_aligned": False,
        "shard_max_frames": 8,
        "split_grouping_key": "scene_id",
        "window_sample_count": 6,
    }


def _kwargs() -> dict:
    return {
        "creation": CreationProvenance(
            tool_name="time_gap_test",
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
        "license": "CC0",
        "source": "time gap test",
        "coordinate_frames": ("world", "array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1,
    }


def _frame(index: int, timestamp_ms: int) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"frame_{index}",
        frame_name=f"frame_{index}",
        timestamp_ms=timestamp_ms,
        start_time_s=timestamp_ms / 1_000,
        end_time_s=timestamp_ms / 1_000 + 0.006,
        sample_rate_hz=1_000,
        frame_index=index,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        aggregate_per_mic_rms={"mic": 0.1},
        diagnostics={},
    )


def _record(root: Path) -> SessionRecorder:
    recorder = SessionRecorder(root, _configuration(), **_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    for index, timestamp in enumerate((0, 4, 12)):
        assert recorder.append_frame(
            _frame(index, timestamp),
            np.ones((1, 6), dtype=np.float32),
            is_reset=index == 0,
        ).accepted
    recorder.end_episode()
    recorder.finalize()
    return recorder


def test_recorder_owns_gap_diagnostics_and_sample_placement(tmp_path):
    recorder = _record(tmp_path / "gaps")
    dataset = SessionDataset.open(tmp_path / "gaps")
    records = list(dataset.iter_records())
    diagnostics = [item.frame.diagnostics["recording"]["time_gap"] for item in records]

    assert [item["inserted_silence_samples"] for item in diagnostics] == [0, 0, 4]
    assert recorder.time_gap_summary == {
        "gap_event_count": 1,
        "inserted_silence_samples": 4,
        "absorbed_drift_count": 0,
        "absorbed_drift_samples_signed": 0,
    }
    assert validate_dataset(tmp_path / "gaps").status == "passed"


def test_reset_starts_a_new_time_lattice(tmp_path):
    root = tmp_path / "reset"
    recorder = SessionRecorder(root, _configuration(), **_kwargs())
    for episode in range(2):
        recorder.begin_episode("scene", f"env_{episode}", "scene")
        assert recorder.append_frame(
            _frame(episode, 0), np.ones((1, 6), np.float32), is_reset=True
        ).accepted
        recorder.end_episode()
    recorder.finalize()

    diagnostics = [
        item.frame.diagnostics["recording"]["time_gap"]
        for item in SessionDataset.open(root).iter_records()
    ]
    assert [item["expected_start_time_s"] for item in diagnostics] == [None, None]


def test_tampered_gap_diagnostic_is_detected(tmp_path):
    root = tmp_path / "tampered"
    _record(root)
    frames_path = root / "shards/shard_00000/frames.jsonl"
    lines = frames_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["frame"]["diagnostics"]["recording"]["time_gap"][
        "inserted_silence_samples"
    ] = 0
    lines[2] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    frames_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256(frames_path.read_bytes()).hexdigest()
    marker_path = frames_path.parent / "shard.complete.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    entry = next(item for item in marker["files"] if item["path"] == "frames.jsonl")
    entry["bytes"] = frames_path.stat().st_size
    entry["sha256"] = digest
    marker_path.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["shards"][0]["assets"][0]["sha256"] = digest
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report = validate_dataset(root)
    assert report.status == "failed"
    assert any(
        finding.code == "time_gap_metadata_mismatch" for finding in report.findings
    )
