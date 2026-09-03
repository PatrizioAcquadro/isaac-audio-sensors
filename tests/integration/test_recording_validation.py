"""Canonical recording validator and statistics tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.constants import FRAME_UNITS
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DatasetLayoutError,
    DeviceProvenance,
    SessionRecorder,
    validate_dataset,
)

REFERENCE = Path("tests/fixtures/recording/session")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _refresh_asset(root: Path, shard_id: str, name: str) -> None:
    shard_dir = root / "shards" / shard_id
    path = shard_dir / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    marker_path = shard_dir / "shard.complete.json"
    marker = _json(marker_path)
    marker_entry = next(item for item in marker["files"] if item["path"] == name)
    marker_entry["bytes"] = path.stat().st_size
    marker_entry["sha256"] = digest
    _write_json(marker_path, marker)
    manifest_path = root / "manifest.json"
    manifest = _json(manifest_path)
    shard = next(item for item in manifest["shards"] if item["shard_id"] == shard_id)
    suffix = "frames" if name == "frames.jsonl" else "audio"
    asset = next(item for item in shard["assets"] if item["asset_id"].endswith(suffix))
    asset["sha256"] = digest
    _write_json(manifest_path, manifest)


def _mutate_record(
    root: Path, line_index: int, mutate, *, shard_id: str = "shard_00000"
) -> None:
    path = root / "shards" / shard_id / "frames.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[line_index])
    mutate(payload)
    lines[line_index] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _refresh_asset(root, shard_id, "frames.jsonl")


def _frame(index: int, *, diagnostic_path_count: int = 0) -> AudioSensorFrame:
    diagnostics = {
        f"host_path_{path_index:03d}": (
            f"/var/tmp/validator/frame_{index:05d}/diagnostic_{path_index:03d}.log"
        )
        for path_index in range(diagnostic_path_count)
    }
    diagnostics["index"] = index
    return AudioSensorFrame(
        frame_id=f"producer_{index}",
        frame_name=f"frame_{index}",
        start_time_s=index / 100.0,
        end_time_s=index / 100.0 + 0.01,
        sample_rate_hz=48_000,
        frame_index=index,
        producer_id="tdoa_synthetic",
        array_id="array",
        channel_validity={"left": True, "right": True},
        units=dict(FRAME_UNITS),
        provenance="synthetic/core",
        aggregate_per_mic_rms={"left": 0.25, "right": 0.25},
        diagnostics=diagnostics,
    )


def _record_session(
    root: Path,
    *,
    aligned: bool,
    frame_count: int = 7,
    diagnostic_path_count: int = 0,
    shard_max_frames: int = 2,
) -> None:
    configuration = {
        "backend_id": "tdoa_synthetic",
        "channel_order": ["left", "right"],
        "dataset_id": "validator_test",
        "dtype": "float32",
        "hop_sample_count": 4,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 48_000,
        "session_seed": 17,
        "shard_episode_aligned": aligned,
        "shard_max_frames": shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": 6,
    }
    recorder = SessionRecorder(
        root,
        configuration,
        creation=CreationProvenance(
            tool_name="validator_test",
            tool_version="1.0",
            backend_id="tdoa_synthetic",
            estimator_id="test",
        ),
        device=DeviceProvenance(
            device_id="test",
            device_type="synthetic",
            platform="test",
            compute_device="cpu",
        ),
        license="CC0-1.0",
        source="validator acceptance",
        coordinate_frames=("world", "array"),
        time_base="simulation_time",
        creation_timestamp_ms=1_767_225_600_000,
    )
    recorder.begin_episode("scene", "environment", "scene")
    for index in range(frame_count):
        audio = np.full((2, 6), index / 32.0, dtype=np.float32)
        result = recorder.append_frame(
            _frame(index, diagnostic_path_count=diagnostic_path_count),
            audio,
            is_reset=index == 0,
        )
        assert result.accepted
    recorder.end_episode()
    recorder.finalize()


def test_reference_fixture_has_exact_statistics_and_no_findings():
    report = validate_dataset(REFERENCE)

    assert report.status == "passed"
    assert report.findings == ()
    assert report.error_count == report.warning_count == 0
    expected_statistics = {
        "audio": {
            "attributed_sample_count": 2160,
            "duration_seconds_by_shard": {
                "shard_00000": 1280 / 48000,
                "shard_00001": 880 / 48000,
            },
            "sample_count": 2160,
            "tail_sample_count": 0,
            "total_duration_seconds": 2160 / 48000,
        },
        "consistency": {
            "channel_count": 4,
            "channel_count_consistent": True,
            "observed_channel_counts": [4],
            "observed_sample_rates_hz": [48000],
            "sample_rate_consistent": True,
            "sample_rate_hz": 48000,
        },
        "counts": {"episodes": 3, "frames": 7, "observations": 0, "shards": 2},
        "dropped_frames": {"total": 0},
        "episodes": {
            "episode_00000": {"frame_count": 2, "timestamp_span_ms": 5},
            "episode_00001": {"frame_count": 2, "timestamp_span_ms": 5},
            "episode_00002": {"frame_count": 3, "timestamp_span_ms": 10},
        },
        "integrity": {
            "skipped_shards": 0,
            "verified_assets": 4,
            "verified_shards": 2,
        },
        "labels": {},
        "missingness": {
            "frames_with_empty_audio_range": 0,
            "frames_without_observations": 7,
        },
        "modalities": {
            "audio_ranges_empty": 0,
            "audio_ranges_nonempty": 7,
            "frames_with_observations": 0,
            "frames_with_waveform_paths": 0,
            "visual_sync_count": 0,
            "waveform_path_count": 0,
        },
    }
    statistics = report.statistics.to_dict()
    assert all(size > 0 for size in statistics.pop("asset_bytes").values())
    assert statistics == expected_statistics
    report_dict = report.to_dict()
    report_dict["statistics"].pop("asset_bytes")
    assert report_dict == {
        "error_count": 0,
        "finding_totals": {},
        "findings": [],
        "statistics": expected_statistics,
        "status": "passed",
        "truncated_codes": [],
        "warning_count": 0,
    }


@pytest.mark.parametrize("aligned", [True, False])
def test_recorder_sessions_validate_without_findings(tmp_path, aligned):
    root = tmp_path / str(aligned)
    _record_session(root, aligned=aligned)
    report = validate_dataset(root)
    assert report.status == "passed"
    assert report.findings == ()


def _corrupt(root: Path, case: str) -> None:
    shard = root / "shards/shard_00000"
    if case == "missing_audio":
        (shard / "audio.wav").unlink()
    elif case == "missing_frames":
        (shard / "frames.jsonl").unlink()
    elif case == "missing_marker":
        (shard / "shard.complete.json").unlink()
    elif case == "audio_checksum":
        path = shard / "audio.wav"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    elif case == "frames_checksum":
        path = shard / "frames.jsonl"
        data = bytearray(path.read_bytes())
        data[32] ^= 1
        path.write_bytes(data)
    elif case == "truncated_jsonl":
        path = shard / "frames.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
        _refresh_asset(root, "shard_00000", "frames.jsonl")
    elif case == "non_monotonic":
        _mutate_record(
            root,
            2,
            lambda payload: payload["frame"].update(
                timestamp_ms=0,
                start_time_s=0.0,
                end_time_s=400 / 48_000,
            ),
            shard_id="shard_00001",
        )
    elif case == "index_gap":
        _mutate_record(
            root, 1, lambda payload: payload.__setitem__("dataset_frame_index", 7)
        )
    elif case == "record_version":
        _mutate_record(
            root,
            0,
            lambda payload: payload.__setitem__(
                "record_version", "ias.dataset_frame_record.v999"
            ),
        )
    elif case == "marker_version":
        path = shard / "shard.complete.json"
        marker = _json(path)
        marker["marker_version"] = "ias.shard_completion.v999"
        _write_json(path, marker)
    elif case == "manifest_version":
        path = root / "manifest.json"
        manifest = _json(path)
        manifest["schema_version"] = "ias.audio_dataset_manifest.v999"
        _write_json(path, manifest)
    elif case == "audio_range":
        marker = _json(shard / "shard.complete.json")
        _mutate_record(
            root,
            0,
            lambda payload: payload.__setitem__(
                "audio_end_sample", marker["audio"]["sample_count"] + 1
            ),
        )
    elif case == "manifest_marker_sha":
        path = root / "manifest.json"
        manifest = _json(path)
        manifest["shards"][0]["assets"][0]["sha256"] = "0" * 64
        _write_json(path, manifest)
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    ("case", "code", "location"),
    [
        ("missing_audio", "missing_asset", "shard_00000"),
        ("missing_frames", "missing_asset", "shard_00000"),
        ("missing_marker", "missing_asset", "shard.complete.json"),
        ("audio_checksum", "checksum_mismatch", "audio.wav"),
        ("frames_checksum", "checksum_mismatch", "frames.jsonl"),
        ("truncated_jsonl", "truncated_record_file", "frames.jsonl"),
        ("non_monotonic", "non_monotonic_timestamp", "episode_00002"),
        ("index_gap", "index_gap", "frames.jsonl line 2"),
        ("record_version", "unknown_version", "frames.jsonl line 1"),
        ("marker_version", "unknown_version", "shard.complete.json"),
        ("manifest_version", "unknown_version", "manifest.json"),
        ("audio_range", "range_out_of_bounds", "frames.jsonl line 1"),
        (
            "manifest_marker_sha",
            "manifest_marker_disagreement",
            "frames.jsonl",
        ),
    ],
)
def test_corruption_matrix_has_only_intended_finding(tmp_path, case, code, location):
    root = tmp_path / case
    shutil.copytree(REFERENCE, root)
    _corrupt(root, case)

    report = validate_dataset(root)

    assert report.status == "failed"
    assert [finding.code for finding in report.findings] == [code]
    assert report.findings[0].severity == "error"
    assert location in report.findings[0].location


def test_split_group_crossing_is_one_located_error(tmp_path):
    root = tmp_path / "split"
    shutil.copytree(REFERENCE, root)
    path = root / "manifest.json"
    manifest = _json(path)
    manifest["episodes"][1]["scene_id"] = "scene_b"
    manifest["episodes"][1]["split_group"] = "scene_b"
    _write_json(path, manifest)

    report = validate_dataset(root)

    assert [finding.code for finding in report.findings] == [
        "split_group_crossing_shard"
    ]
    assert "shard_00000" in report.findings[0].location
    assert report.findings[0].severity == "error"


def test_absolute_diagnostic_is_only_a_portability_warning(tmp_path):
    root = tmp_path / "warning"
    shutil.copytree(REFERENCE, root)
    _mutate_record(
        root,
        0,
        lambda payload: payload["frame"]["diagnostics"].__setitem__(
            "host_log", "/var/tmp/capture.log"
        ),
    )

    report = validate_dataset(root)

    assert report.status == "passed_with_warnings"
    assert report.error_count == 0
    assert [finding.code for finding in report.findings] == ["portability_warning"]
    assert report.findings[0].severity == "warning"
    assert "diagnostics.host_log" in report.findings[0].location


def _wav_data_offset(data: bytes) -> int:
    offset = 12
    while offset + 8 <= len(data):
        chunk_id, size = struct.unpack_from("<4sI", data, offset)
        if chunk_id == b"data":
            return offset + 8
        offset += 8 + size + (size & 1)
    raise AssertionError("missing WAV data chunk")


def test_deep_audio_alone_detects_rehashed_nan_payload(tmp_path):
    root = tmp_path / "nan"
    shutil.copytree(REFERENCE, root)
    path = root / "shards/shard_00000/audio.wav"
    data = bytearray(path.read_bytes())
    offset = _wav_data_offset(data)
    data[offset : offset + 4] = struct.pack("<f", float("nan"))
    path.write_bytes(data)
    _refresh_asset(root, "shard_00000", "audio.wav")

    assert validate_dataset(root).findings == ()
    report = validate_dataset(root, deep_audio=True)

    assert [finding.code for finding in report.findings] == ["non_finite_audio"]
    assert report.findings[0].severity == "error"
    assert report.findings[0].location.endswith("shard_00000 file audio.wav")


def test_unsupported_inputs_raise_instead_of_becoming_findings(tmp_path):
    with pytest.raises(DatasetLayoutError, match="does not exist"):
        validate_dataset(tmp_path / "missing")

    file_path = tmp_path / "file"
    file_path.write_text("not a session", encoding="utf-8")
    with pytest.raises(DatasetLayoutError, match="not a directory"):
        validate_dataset(file_path)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DatasetLayoutError, match="not a finalized session"):
        validate_dataset(empty)

    root = tmp_path / "training"
    shutil.copytree(REFERENCE, root)
    path = root / "manifest.json"
    manifest = _json(path)
    manifest["runtime_profile"] = "training_features"
    _write_json(path, manifest)
    with pytest.raises(DatasetLayoutError, match="manifest.json.*unsupported"):
        validate_dataset(root)


def test_unreadable_manifest_is_one_fatal_content_finding(tmp_path):
    root = tmp_path / "bad_manifest"
    root.mkdir()
    (root / "manifest.json").write_text("{", encoding="utf-8")

    report = validate_dataset(root)

    assert report.status == "failed"
    assert [finding.code for finding in report.findings] == ["invalid_json"]
    assert report.statistics.to_dict() == report.statistics.empty().to_dict()
