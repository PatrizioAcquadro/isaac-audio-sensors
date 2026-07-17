"""Acceptance coverage for S2.3 checked incremental loading and replay."""

from __future__ import annotations

import gc
import hashlib
import json
import shutil
import weakref
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.constants import FRAME_UNITS
from isaac_audio_sensors.core.dataset import (
    DatasetLayoutError,
    SessionDataset,
    SessionRecorder,
    replay_session,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
)

REFERENCE = Path("examples/datasets/reference_session_v1")


def _configuration(
    *, aligned: bool, shard_max_frames: int, overlap: bool = True
) -> dict[str, object]:
    return {
        "backend_id": "tdoa_synthetic",
        "channel_order": ["left", "right"],
        "dataset_id": "loader_replay_test",
        "dtype": "float32",
        "hop_sample_count": 4 if overlap else 6,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 48_000,
        "session_seed": 731,
        "shard_episode_aligned": aligned,
        "shard_max_frames": shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": 6,
    }


def _recorder_kwargs() -> dict[str, object]:
    return {
        "creation": CreationProvenance(
            tool_name="loader_replay_test",
            tool_version="1.0",
            backend_id="tdoa_synthetic",
            estimator_id="deterministic_test",
        ),
        "device": DeviceProvenance(
            device_id="test_host",
            device_type="synthetic",
            platform="test",
            compute_device="cpu",
        ),
        "license": "CC0-1.0",
        "source": "S2.3 deterministic test",
        "coordinate_frames": ("world", "array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1_767_225_600_000,
    }


def _frame(global_index: int, local_index: int) -> AudioSensorFrame:
    detection = AudioDetection(
        detection_id=f"detection_{global_index}",
        source_id="source",
        class_label="tone",
        detection_mode="scheduled_known_source",
        timestamp_ms=local_index * 10,
        ground_truth_bearing_deg=float(global_index),
        source_distance_m=1.25,
        doa=DoaEstimate(
            estimated_bearing_deg=float(global_index),
            candidate_bearing_deg=(float(global_index), float(global_index + 180)),
            bearing_confidence=0.75,
        ),
        per_mic_delay_s={"left": 0.0, "right": 0.0001},
        per_mic_rms={"left": 0.25, "right": 0.5},
        diagnostics={"ordinal": global_index},
    )
    return AudioSensorFrame(
        frame_id=f"producer_{local_index}",
        frame_name=f"sensor_frame_{global_index}",
        timestamp_ms=local_index * 10,
        start_time_s=local_index / 100.0,
        end_time_s=local_index / 100.0 + 0.01,
        sample_rate_hz=48_000,
        frame_index=local_index,
        backend_id="tdoa_synthetic",
        array_id="array",
        units=dict(FRAME_UNITS),
        provenance="synthetic/core",
        detections=(detection,),
        aggregate_per_mic_rms={"left": 0.25, "right": 0.5},
        diagnostics={"global_index": global_index},
    )


def _audio(index: int) -> np.ndarray:
    base = np.arange(12, dtype=np.float32).reshape(2, 6)
    return base / np.float32(32.0) + np.float32(index / 64.0)


def _record_session(
    root: Path,
    *,
    aligned: bool = False,
    shard_max_frames: int = 2,
    episode_sizes: tuple[int, ...] = (3, 2),
    overlap: bool = True,
) -> tuple[AudioSensorFrame, ...]:
    recorder = SessionRecorder(
        root,
        _configuration(
            aligned=aligned,
            shard_max_frames=shard_max_frames,
            overlap=overlap,
        ),
        **_recorder_kwargs(),
    )
    frames: list[AudioSensorFrame] = []
    global_index = 0
    for episode_index, size in enumerate(episode_sizes):
        scene = "scene_a" if episode_index < 2 else "scene_b"
        recorder.begin_episode(scene, f"environment_{episode_index}", scene)
        for local_index in range(size):
            frame = _frame(global_index, local_index)
            result = recorder.append_frame(
                frame,
                _audio(global_index),
                frame.timestamp_ms,
                is_reset=local_index == 0,
            )
            assert result.accepted
            frames.append(frame)
            global_index += 1
        recorder.end_episode()
    recorder.finalize()
    return tuple(frames)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_pretty(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _refresh_frames_asset(root: Path, shard_id: str) -> None:
    shard_dir = root / "shards" / shard_id
    frames_path = shard_dir / "frames.jsonl"
    digest = hashlib.sha256(frames_path.read_bytes()).hexdigest()
    marker_path = shard_dir / "shard.complete.json"
    marker = _json(marker_path)
    entry = next(item for item in marker["files"] if item["path"] == "frames.jsonl")
    entry["bytes"] = frames_path.stat().st_size
    entry["sha256"] = digest
    _write_pretty(marker_path, marker)
    manifest_path = root / "manifest.json"
    manifest = _json(manifest_path)
    shard = next(item for item in manifest["shards"] if item["shard_id"] == shard_id)
    asset = next(
        item for item in shard["assets"] if item["kind"] == "frame_trace_jsonl"
    )
    asset["sha256"] = digest
    _write_pretty(manifest_path, manifest)


def _mutate_record(root: Path, shard_id: str, line_index: int, mutate) -> None:
    path = root / "shards" / shard_id / "frames.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[line_index])
    mutate(payload)
    lines[line_index] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _refresh_frames_asset(root, shard_id)


def _tree_snapshot(root: Path) -> tuple[tuple[str, bool, int, int], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.is_dir(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
    )


@pytest.mark.parametrize("aligned", [True, False])
def test_round_trip_preserves_typed_frames_boundaries_and_audio(tmp_path, aligned):
    root = tmp_path / ("aligned" if aligned else "unaligned")
    fed = _record_session(
        root,
        aligned=aligned,
        shard_max_frames=2,
        overlap=not aligned,
    )
    dataset = SessionDataset.open(root)
    loaded = list(dataset.iter_records())

    assert [item.dataset_frame_index for item in loaded] == list(range(len(fed)))
    for index, (expected, item) in enumerate(zip(fed, loaded, strict=True)):
        assert frame_to_trace_dict(item.frame) == frame_to_trace_dict(expected)
        assert type(item.frame.frame_index) is int
        assert item.frame.units == expected.units
        stored = read_wav(root / "shards" / item.shard_id / "audio.wav").samples
        np.testing.assert_array_equal(
            dataset.read_frame_audio(item),
            stored[:, item.audio_start_sample : item.audio_end_sample],
        )
        if aligned:
            np.testing.assert_array_equal(dataset.read_frame_audio(item), _audio(index))

    events = list(replay_session(root, with_audio=True))
    frame_events = [event for event in events if event.kind == "frame"]
    assert [event.frame.dataset_frame_index for event in frame_events] == list(range(5))
    assert [event.kind for event in events] == [
        "episode_start",
        "reset",
        "frame",
        "frame",
        "frame",
        "episode_end",
        "episode_start",
        "reset",
        "frame",
        "frame",
        "episode_end",
    ]
    assert [event.frame_index for event in events if event.kind == "reset"] == [0, 3]
    for event in frame_events:
        assert event.frame is not None and event.audio is not None
        np.testing.assert_array_equal(
            event.audio, dataset.read_frame_audio(event.frame)
        )


def test_reference_fixture_loads_replays_and_reads_empty_range():
    dataset = SessionDataset.open(REFERENCE)
    items = list(dataset.iter_records())
    assert [item.frame.frame_id for item in items] == [
        "producer_frame_0",
        "producer_frame_1",
        "producer_frame_0",
        "producer_frame_1",
        "producer_frame_0",
        "producer_frame_1",
        "producer_frame_2",
    ]
    assert [(item.audio_start_sample, item.audio_end_sample) for item in items] == [
        (0, 400),
        (240, 640),
        (640, 1040),
        (880, 1280),
        (0, 400),
        (240, 640),
        (640, 640),
    ]
    assert dataset.read_frame_audio(items[-1]).shape == (4, 0)
    events = list(replay_session(REFERENCE))
    assert sum(event.kind == "episode_start" for event in events) == 3
    assert sum(event.kind == "episode_end" for event in events) == 3
    assert sum(event.kind == "frame" for event in events) == 7


def _corrupt(root: Path, case: str) -> None:
    shard = root / "shards" / "shard_00000"
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
        _refresh_frames_asset(root, "shard_00000")
    elif case == "non_monotonic":
        _mutate_record(
            root, "shard_00000", 2, lambda p: p["frame"].__setitem__("timestamp_ms", 0)
        )
    elif case == "index_gap":
        _mutate_record(
            root, "shard_00000", 1, lambda p: p.__setitem__("dataset_frame_index", 7)
        )
    elif case == "record_version":
        _mutate_record(
            root,
            "shard_00000",
            0,
            lambda p: p.__setitem__("record_version", "ias.dataset_frame_record.v999"),
        )
    elif case == "marker_version":
        path = shard / "shard.complete.json"
        marker = _json(path)
        marker["marker_version"] = "ias.shard_completion.v999"
        _write_pretty(path, marker)
    elif case == "manifest_version":
        path = root / "manifest.json"
        manifest = _json(path)
        manifest["schema_version"] = "ias.audio_dataset_manifest.v999"
        _write_pretty(path, manifest)
    elif case == "audio_range":
        marker = _json(shard / "shard.complete.json")
        too_large = marker["audio"]["sample_count"] + 1
        _mutate_record(
            root,
            "shard_00000",
            0,
            lambda p: p.__setitem__("audio_end_sample", too_large),
        )
    elif case == "manifest_marker_sha":
        path = root / "manifest.json"
        manifest = _json(path)
        manifest["shards"][0]["assets"][0]["sha256"] = "0" * 64
        _write_pretty(path, manifest)
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing_audio", r"shard_00000.*audio\.wav"),
        ("missing_frames", r"shard_00000.*frames\.jsonl"),
        ("missing_marker", r"shard_00000.*shard\.complete\.json"),
        ("audio_checksum", r"shard_00000.*audio\.wav.*sha256 mismatch"),
        ("frames_checksum", r"shard_00000.*frames\.jsonl.*sha256 mismatch"),
        ("truncated_jsonl", r"shard_00000.*frames\.jsonl.*final line"),
        ("non_monotonic", r"episode_00000.*frame 2.*line 3"),
        ("index_gap", r"shard_00000.*line 2.*7 != 1"),
        ("record_version", r"shard_00000.*line 1.*v999"),
        ("marker_version", r"shard_00000.*shard\.complete\.json.*v999"),
        ("manifest_version", r"manifest\.json.*schema_version.*v999"),
        ("audio_range", r"shard_00000.*line 1.*sample_count"),
        ("manifest_marker_sha", r"shard_00000.*frames\.jsonl.*manifest/marker sha256"),
    ],
)
def test_corruption_matrix_has_location_context(tmp_path, case, expected):
    pristine = tmp_path / "pristine"
    _record_session(pristine, aligned=False, shard_max_frames=3, episode_sizes=(3,))
    root = tmp_path / case
    shutil.copytree(pristine, root)
    _corrupt(root, case)

    with pytest.raises(DatasetLayoutError, match=expected):
        dataset = SessionDataset.open(root)
        list(dataset.iter_records())


def test_range_read_rejects_beyond_marker_sample_count(tmp_path):
    root = tmp_path / "range"
    _record_session(root, episode_sizes=(2,))
    dataset = SessionDataset.open(root)
    marker = _json(root / "shards/shard_00000/shard.complete.json")
    count = marker["audio"]["sample_count"]
    with pytest.raises(
        DatasetLayoutError,
        match=r"shard shard_00000 file audio\.wav.*exceeds sample_count",
    ):
        dataset.read_shard_audio("shard_00000", count, count + 1)


def test_verify_checksums_false_keeps_structural_checks(tmp_path):
    root = tmp_path / "fast"
    _record_session(root, episode_sizes=(2,))
    path = root / "shards/shard_00000/audio.wav"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    assert (
        len(list(SessionDataset.open(root, verify_checksums=False).iter_records())) == 2
    )
    path.unlink()
    with pytest.raises(DatasetLayoutError, match=r"shard_00000.*audio\.wav"):
        list(SessionDataset.open(root, verify_checksums=False).iter_records())


def test_incomplete_is_opt_in_and_replays_only_complete_shards(tmp_path):
    root = tmp_path / "incomplete"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=2),
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    for index in range(3):
        frame = _frame(index, index)
        assert recorder.append_frame(
            frame, _audio(index), frame.timestamp_ms, is_reset=index == 0
        ).accepted
    recorder.finalize_incomplete()

    with pytest.raises(DatasetLayoutError, match="finalized-incomplete"):
        SessionDataset.open(root)
    dataset = SessionDataset.open(root, allow_incomplete=True)
    assert dataset.lifecycle_state == "finalized-incomplete"
    assert [item.dataset_frame_index for item in dataset.iter_records()] == [0, 1]
    assert (
        sum(
            event.kind == "frame"
            for event in replay_session(root, allow_incomplete=True)
        )
        == 2
    )


def test_in_progress_session_is_refused_with_lifecycle_context(tmp_path):
    root = tmp_path / "in_progress"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=2),
        **_recorder_kwargs(),
    )
    with pytest.raises(DatasetLayoutError, match="in-progress or aborted session"):
        SessionDataset.open(root)
    recorder.finalize_incomplete()


def test_iteration_retains_constant_loaded_frame_count(tmp_path):
    root = tmp_path / "bounded"
    _record_session(root, aligned=False, shard_max_frames=2, episode_sizes=(12,))
    references: list[weakref.ReferenceType] = []
    maximum_alive = 0
    for item in SessionDataset.open(root).iter_records():
        references.append(weakref.ref(item))
        gc.collect()
        maximum_alive = max(maximum_alive, sum(ref() is not None for ref in references))
    del item
    gc.collect()
    # The generator and caller can each own only the current yielded item; prior
    # JSONL records are never accumulated by SessionDataset.
    assert maximum_alive <= 2
    assert sum(ref() is not None for ref in references) == 0


def test_replay_is_read_only(tmp_path):
    root = tmp_path / "read_only"
    _record_session(root, aligned=False, shard_max_frames=2)
    before = _tree_snapshot(root)
    assert list(replay_session(root, with_audio=True))
    assert _tree_snapshot(root) == before
