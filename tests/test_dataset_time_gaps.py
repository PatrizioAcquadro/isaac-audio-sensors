"""Frozen S3.2 recorder placement, gap streaming, resume, and validation tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.core.dataset.recorder as recorder_module
from isaac_audio_sensors.core.dataset import (
    CancelledWrite,
    SessionRecorder,
    validate_dataset,
)
from isaac_audio_sensors.core.dataset.time_gaps import (
    TimeGapCursor,
    advance_time_gap_cursor,
    plan_time_gap,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.types import AudioSensorFrame


def _configuration(
    *,
    aligned: bool = False,
    shard_max_frames: int = 100,
    preserve: bool | None = True,
    channels: int = 4,
    sample_rate_hz: int = 48_000,
    window_sample_count: int = 2_400,
    hop_sample_count: int = 2_400,
) -> dict[str, object]:
    result: dict[str, object] = {
        "backend_id": "tdoa_synthetic",
        "channel_order": [f"mic_{index}" for index in range(channels)],
        "dataset_id": "s3_2_time_gap_test",
        "dtype": "float32",
        "hop_sample_count": hop_sample_count,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": sample_rate_hz,
        "session_seed": 32,
        "shard_episode_aligned": aligned,
        "shard_max_frames": shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": window_sample_count,
    }
    if preserve is not None:
        result["preserve_time_gaps"] = preserve
    return result


def _recorder(
    root: Path,
    configuration: dict[str, object],
    **kwargs: object,
) -> SessionRecorder:
    return SessionRecorder(
        root,
        configuration,
        creation=CreationProvenance(
            tool_name="s3_2_test",
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
        source="S3.2 deterministic test",
        coordinate_frames=("world", "array"),
        time_base="simulation_time",
        creation_timestamp_ms=1_767_225_600_000,
        **kwargs,
    )


def _frame(
    index: int,
    start_time_s: float,
    *,
    duration_s: float = 0.05,
) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"producer_{index}",
        frame_name=f"frame_{index}",
        timestamp_ms=round(1000.0 * start_time_s),
        start_time_s=start_time_s,
        end_time_s=start_time_s + duration_s,
        sample_rate_hz=48_000,
        frame_index=index,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        aggregate_per_mic_rms={f"mic_{mic}": 0.1 for mic in range(4)},
        diagnostics={"fixture": "s3_2"},
    )


def _attach_plan(
    recorder: SessionRecorder, frame: AudioSensorFrame
) -> AudioSensorFrame:
    diagnostic = recorder.plan_time_gap(frame)
    diagnostics = dict(frame.diagnostics)
    recording = dict(diagnostics.get("recording", {}))
    recording["time_gap"] = diagnostic
    diagnostics["recording"] = recording
    return replace(frame, diagnostics=diagnostics)


def _append(
    recorder: SessionRecorder,
    frame: AudioSensorFrame,
    block: np.ndarray,
    *,
    reset: bool = False,
) -> None:
    planned = _attach_plan(recorder, frame)
    result = recorder.append_frame(
        planned,
        block,
        frame.timestamp_ms,
        is_reset=reset,
    )
    assert result.accepted, result.reason


def _concatenated_audio(root: Path) -> np.ndarray:
    return np.concatenate(
        [
            read_wav(path).samples
            for path in sorted((root / "shards").glob("*/audio.wav"))
        ],
        axis=1,
    )


def _records(root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted((root / "shards").glob("*/frames.jsonl")):
        result.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    return result


def test_pause_inserts_exact_16800_samples_and_validator_reconciles(tmp_path):
    root = tmp_path / "pause"
    recorder = _recorder(root, _configuration())
    recorder.begin_episode("scene", "environment", "scene")
    blocks = []
    for index, start in enumerate((0.0, 0.05, 0.45)):
        block = np.full((4, 2_400), index + 1, dtype=np.float32)
        block[:, :32] = np.float32(index + 11)
        block[:, -32:] = np.float32(index + 21)
        blocks.append(block)
        _append(recorder, _frame(index, start), block, reset=index == 0)
    assert recorder.time_gap_summary == {
        "gap_event_count": 1,
        "inserted_silence_samples": 16_800,
        "absorbed_drift_count": 0,
        "absorbed_drift_samples_signed": 0,
    }
    recorder.end_episode()
    recorder.finalize()

    audio = _concatenated_audio(root)
    assert audio.shape == (4, 24_000)
    np.testing.assert_array_equal(audio[:, :2_400], blocks[0])
    np.testing.assert_array_equal(audio[:, 2_400:4_800], blocks[1])
    np.testing.assert_array_equal(audio[:, 4_800:21_600], 0.0)
    np.testing.assert_array_equal(audio[:, 21_600:24_000], blocks[2])
    records = _records(root)
    assert [item["audio_start_sample"] for item in records] == [0, 2_400, 21_600]
    gap = records[2]["frame"]["diagnostics"]["recording"]["time_gap"]
    assert gap["inserted_silence_samples"] == 16_800
    assert gap["session_audio_start_sample"] == 21_600
    assert validate_dataset(root).status == "passed"


def test_throttle_capture_starts_have_zero_gap_and_exact_7200_samples(tmp_path):
    root = tmp_path / "throttle"
    recorder = _recorder(root, _configuration())
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    for index, start in enumerate((0.0, 0.05, 0.10)):
        _append(recorder, _frame(index, start), block, reset=index == 0)
    assert recorder.time_gap_summary["inserted_silence_samples"] == 0
    recorder.end_episode()
    recorder.finalize()
    assert _concatenated_audio(root).shape == (4, 7_200)


@pytest.mark.parametrize(
    ("delta", "inserted", "absorbed", "raises"),
    [
        (-241, None, None, True),
        (-240, 0, -240, False),
        (0, 0, 0, False),
        (1, 0, 1, False),
        (240, 0, 240, False),
        (241, 241, 0, False),
    ],
)
def test_gap_tolerance_is_inclusive_on_integer_lattice(
    delta, inserted, absorbed, raises
):
    anchor = plan_time_gap(
        TimeGapCursor(),
        placement_sequence=0,
        start_time_s=Fraction(0),
        end_time_s=Fraction(1, 20),
        timestamp_ms=0,
        sample_rate_hz=48_000,
        window_sample_count=2_400,
        hop_sample_count=2_400,
        session_audio_start_sample=0,
    )
    cursor = advance_time_gap_cursor(
        TimeGapCursor(), anchor, timestamp_ms=0, hop_sample_count=2_400
    )
    start = Fraction(2_400 + delta, 48_000)
    def call():
        return plan_time_gap(
            cursor,
            placement_sequence=1,
            start_time_s=start,
            end_time_s=start + Fraction(1, 20),
            timestamp_ms=round(1000 * start),
            sample_rate_hz=48_000,
            window_sample_count=2_400,
            hop_sample_count=2_400,
            session_audio_start_sample=2_400,
        )
    if raises:
        with pytest.raises(ValueError, match="overlapping window placement"):
            call()
    else:
        plan = call()
        assert plan.inserted_silence_samples == inserted
        assert plan.absorbed_drift_samples == absorbed


@pytest.mark.parametrize(("fractional_gap", "inserted"), [(2.5, 2), (3.5, 4)])
def test_round_half_even_is_frozen_for_exact_rational_gaps(
    fractional_gap, inserted
):
    cursor = TimeGapCursor(
        origin_start_time_s=0.0,
        expected_next_sample=10,
        preceding_timestamp_ms=0,
    )
    numerator = 25 if fractional_gap == 2.5 else 27
    start = Fraction(numerator, 2_000)
    plan = plan_time_gap(
        cursor,
        placement_sequence=1,
        start_time_s=start,
        end_time_s=start + Fraction(1, 100),
        timestamp_ms=round(1000 * start),
        sample_rate_hz=1_000,
        window_sample_count=10,
        hop_sample_count=10,
        session_audio_start_sample=10,
    )
    assert plan.inserted_silence_samples == inserted


def test_carry_advances_through_gap_then_remainder_is_exact_zero(tmp_path):
    root = tmp_path / "carry"
    config = _configuration(
        channels=1,
        sample_rate_hz=10,
        window_sample_count=4,
        hop_sample_count=2,
    )
    recorder = _recorder(root, config)
    recorder.begin_episode("scene", "environment", "scene")
    first = AudioSensorFrame(
        frame_id="first",
        timestamp_ms=0,
        start_time_s=0.0,
        end_time_s=0.4,
        sample_rate_hz=10,
        frame_index=0,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        diagnostics={},
    )
    second = replace(
        first,
        frame_id="second",
        timestamp_ms=1_000,
        start_time_s=1.0,
        end_time_s=1.4,
        frame_index=1,
    )
    _append(recorder, first, np.array([[1.0, 0.5, 0.25, 0.125]], np.float32))
    _append(recorder, second, np.zeros((1, 4), np.float32))
    recorder.end_episode()
    recorder.finalize()
    audio = _concatenated_audio(root)[0]
    np.testing.assert_array_equal(audio[:2], np.array([1.0, 0.5], np.float32))
    np.testing.assert_array_equal(audio[2:4], np.array([0.25, 0.125], np.float32))
    np.testing.assert_array_equal(audio[4:10], 0.0)


def test_episode_reset_never_bridges_elapsed_time(tmp_path):
    root = tmp_path / "episodes"
    recorder = _recorder(root, _configuration())
    block = np.ones((4, 2_400), dtype=np.float32)
    recorder.begin_episode("scene", "one", "scene")
    _append(recorder, _frame(0, 0.0), block, reset=True)
    recorder.end_episode()
    recorder.begin_episode("scene", "two", "scene")
    _append(recorder, _frame(1, 10.0), block, reset=True)
    assert recorder.time_gap_summary["inserted_silence_samples"] == 0
    recorder.end_episode()
    recorder.finalize()
    assert _concatenated_audio(root).shape == (4, 4_800)


@pytest.mark.parametrize("aligned", [False, True])
def test_aligned_and_unaligned_gap_plans_produce_identical_audio(tmp_path, aligned):
    root = tmp_path / str(aligned)
    recorder = _recorder(
        root,
        _configuration(aligned=aligned, shard_max_frames=3),
    )
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    _append(recorder, _frame(0, 0.0), block)
    _append(recorder, _frame(1, 0.45), block * 2.0)
    recorder.end_episode()
    recorder.finalize()
    assert validate_dataset(root).status == "passed"
    expected = np.concatenate(
        [block, np.zeros((4, 19_200), np.float32), block * 2.0], axis=1
    )
    np.testing.assert_array_equal(_concatenated_audio(root), expected)


def test_long_gap_allocations_obey_sample_and_one_mib_caps(tmp_path, monkeypatch):
    root = tmp_path / "bounded"
    config = _configuration(
        channels=4,
        sample_rate_hz=1_000,
        window_sample_count=10,
        hop_sample_count=10,
    )
    recorder = _recorder(root, config)
    recorder.begin_episode("scene", "environment", "scene")
    allocations = []
    original_zeros = recorder_module.np.zeros

    def zeros_spy(shape, *args, **kwargs):
        if isinstance(shape, tuple) and len(shape) == 2 and shape[0] == 4:
            allocations.append(shape)
        return original_zeros(shape, *args, **kwargs)

    monkeypatch.setattr(recorder_module.np, "zeros", zeros_spy)
    first = replace(
        _frame(0, 0.0, duration_s=0.01), sample_rate_hz=1_000
    )
    second = replace(
        _frame(1, 200.0, duration_s=0.01), sample_rate_hz=1_000
    )
    block = np.ones((4, 10), dtype=np.float32)
    _append(recorder, first, block)
    _append(recorder, second, block)
    gap_allocations = [shape for shape in allocations if shape[1] > 10]
    assert gap_allocations
    assert max(shape[1] for shape in gap_allocations) <= 65_536
    assert max(4 * shape[0] * shape[1] for shape in gap_allocations) <= 1_048_576


def test_missing_stale_conflicting_plan_and_wrong_shape_reject_before_mutation(
    tmp_path,
):
    root = tmp_path / "rejections"
    recorder = _recorder(root, _configuration())
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    first = _frame(0, 0.0)
    before = recorder.next_dataset_frame_index
    missing = recorder.append_frame(first, block, first.timestamp_ms)
    assert not missing.accepted
    assert "time-gap diagnostic mismatch" in str(missing.reason)
    assert recorder.next_dataset_frame_index == before

    planned = _attach_plan(recorder, first)
    wrong_shape = recorder.append_frame(
        planned, np.ones((4, 2_399), np.float32), first.timestamp_ms
    )
    assert not wrong_shape.accepted
    assert recorder.next_dataset_frame_index == before
    _append(recorder, first, block)

    stale_source = _frame(1, 0.05)
    stale_mapping = recorder.plan_time_gap(stale_source)
    _append(recorder, replace(stale_source, frame_id="other"), block)
    diagnostics = dict(stale_source.diagnostics)
    diagnostics["recording"] = {"time_gap": stale_mapping}
    stale = replace(
        stale_source,
        frame_id="stale",
        timestamp_ms=100,
        start_time_s=0.10,
        end_time_s=0.15,
        diagnostics=diagnostics,
    )
    result = recorder.append_frame(stale, block, stale.timestamp_ms)
    assert not result.accepted
    assert "time-gap diagnostic mismatch" in str(result.reason)
    assert recorder.next_dataset_frame_index == 2

    conflicting = replace(
        _frame(3, 0.10), diagnostics={"recording": {"time_gap": {}}}
    )
    with pytest.raises(ValueError, match="conflicting"):
        recorder.plan_time_gap(conflicting)


def test_non_monotonic_recorder_candidate_rejects_without_mutation(tmp_path):
    root = tmp_path / "non_monotonic"
    recorder = _recorder(root, _configuration())
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    _append(recorder, _frame(0, 0.10), block)
    before = recorder.next_dataset_frame_index
    candidate = _frame(1, 0.05)
    result = recorder.append_frame(candidate, block, candidate.timestamp_ms)
    assert not result.accepted
    assert "non-monotonic timestamp" in str(result.reason)
    assert recorder.next_dataset_frame_index == before


def test_absent_and_explicit_false_use_identical_public_append_bytes(tmp_path):
    hashes = []
    full_session_hashes = []
    for name, preserve in (("absent", None), ("false", False)):
        root = tmp_path / name
        config = _configuration(
            preserve=preserve,
            channels=1,
            sample_rate_hz=10,
            window_sample_count=4,
            hop_sample_count=2,
        )
        recorder = _recorder(root, config)
        recorder.begin_episode("scene", "environment", "scene")
        frame = AudioSensorFrame(
            frame_id="golden",
            timestamp_ms=0,
            start_time_s=0.0,
            end_time_s=0.4,
            sample_rate_hz=10,
            frame_index=0,
            backend_id="tdoa_synthetic",
            array_id="array",
            provenance="synthetic/core",
            diagnostics={},
        )
        result = recorder.append_frame(
            frame,
            np.array([[1.0, 0.5, 0.25, 0.125]], np.float32),
            0,
        )
        assert result.accepted
        recorder.end_episode()
        recorder.finalize()
        public = b"".join(
            (root / "shards/shard_00000" / filename).read_bytes()
            for filename in ("frames.jsonl", "audio.wav", "shard.complete.json")
        )
        hashes.append(hashlib.sha256(public).hexdigest())
        full_session = b"".join(
            path.read_bytes()
            for path in (
                root / "config/session_config.json",
                root / "shards/shard_00000/frames.jsonl",
                root / "shards/shard_00000/audio.wav",
                root / "shards/shard_00000/shard.complete.json",
                root / "manifest.json",
            )
        )
        full_session_hashes.append(hashlib.sha256(full_session).hexdigest())
    assert hashes[0] == hashes[1]
    assert hashes[0] == (
        "6cb66c3487ab471d8abf5a515c09cf6b9a32ad9a4c7a389cad473b91f3188442"
    )
    assert full_session_hashes[0] == (
        "77aa7521801985c7346e5ec707535c3be43579ef97c3b3ef662f1b08e3f6de52"
    )


class _CancelAfterChecks:
    def __init__(self, cancel_at: int) -> None:
        self.cancel_at = cancel_at
        self.check_count = 0

    def check(self) -> None:
        self.check_count += 1
        if self.check_count >= self.cancel_at:
            raise CancelledWrite("injected mid-gap cancellation")


def test_shard_boundary_gap_cancellation_resumes_from_checkpoint(tmp_path):
    config = _configuration(shard_max_frames=1)
    root = tmp_path / "resume"
    recorder = _recorder(root, config)
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    _append(recorder, _frame(0, 0.0), block)
    recorder._resolve_pending_boundary(mid_episode=True)
    candidate = _frame(1, 3.0)
    planned = _attach_plan(recorder, candidate)
    recorder.cancellation_token = _CancelAfterChecks(6)
    with pytest.raises(CancelledWrite):
        recorder.append_frame(planned, block, candidate.timestamp_ms)
    assert not (root / "manifest.json").exists()
    resumed = SessionRecorder.resume(root, config, **{
        "creation": recorder.creation,
        "device": recorder.device,
        "license": recorder.license,
        "source": recorder.source,
        "coordinate_frames": recorder.coordinate_frames,
        "time_base": recorder.time_base,
        "creation_timestamp_ms": recorder.creation_timestamp_ms,
    })
    replay = _attach_plan(resumed, candidate)
    result = resumed.append_frame(replay, block, candidate.timestamp_ms)
    assert result.accepted
    resumed.end_episode()
    resumed.finalize()
    assert resumed.time_gap_summary["gap_event_count"] == 1
    assert validate_dataset(root).status == "passed"


@pytest.mark.parametrize("cancelled_gap_block", [1, 2, 3])
def test_cancellation_at_each_gap_block_replays_byte_identically(
    tmp_path,
    monkeypatch,
    cancelled_gap_block,
):
    config = _configuration(shard_max_frames=1)
    block = np.ones((4, 2_400), dtype=np.float32)
    gap_samples = 3 * 65_536
    candidate_start_s = 0.05 + gap_samples / 48_000

    baseline_root = tmp_path / "baseline"
    baseline = _recorder(baseline_root, config)
    baseline.begin_episode("scene", "environment", "scene")
    _append(baseline, _frame(0, 0.0), block)
    baseline._resolve_pending_boundary(mid_episode=True)
    _append(baseline, _frame(1, candidate_start_s), block)
    baseline.end_episode()
    baseline.finalize()

    resumed_root = tmp_path / f"cancel_{cancelled_gap_block}"
    interrupted = _recorder(resumed_root, config)
    interrupted.begin_episode("scene", "environment", "scene")
    _append(interrupted, _frame(0, 0.0), block)
    interrupted._resolve_pending_boundary(mid_episode=True)
    candidate = _frame(1, candidate_start_s)
    planned = _attach_plan(interrupted, candidate)

    original_append = recorder_module.StreamingWavShardWriter.append_samples
    gap_block_count = 0
    armed = True

    def cancelling_append(writer, samples):
        nonlocal armed, gap_block_count
        if armed and np.asarray(samples).shape == (4, 65_536):
            gap_block_count += 1
            if gap_block_count == cancelled_gap_block:
                armed = False
                raise CancelledWrite("injected gap-block cancellation")
        return original_append(writer, samples)

    monkeypatch.setattr(
        recorder_module.StreamingWavShardWriter,
        "append_samples",
        cancelling_append,
    )
    with pytest.raises(CancelledWrite, match="gap-block cancellation"):
        interrupted.append_frame(planned, block, candidate.timestamp_ms)
    assert gap_block_count == cancelled_gap_block
    assert not (resumed_root / "manifest.json").exists()

    resumed = SessionRecorder.resume(
        resumed_root,
        config,
        creation=interrupted.creation,
        device=interrupted.device,
        license=interrupted.license,
        source=interrupted.source,
        coordinate_frames=interrupted.coordinate_frames,
        time_base=interrupted.time_base,
        creation_timestamp_ms=interrupted.creation_timestamp_ms,
    )
    replay = _attach_plan(resumed, candidate)
    result = resumed.append_frame(replay, block, candidate.timestamp_ms)
    assert result.accepted
    resumed.end_episode()
    resumed.finalize()

    for relative in (
        "manifest.json",
        "shards/shard_00000/audio.wav",
        "shards/shard_00000/frames.jsonl",
        "shards/shard_00000/shard.complete.json",
        "shards/shard_00001/audio.wav",
        "shards/shard_00001/frames.jsonl",
        "shards/shard_00001/shard.complete.json",
    ):
        assert (resumed_root / relative).read_bytes() == (
            baseline_root / relative
        ).read_bytes()
    assert validate_dataset(resumed_root).status == "passed"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mutate_frame_record(root: Path, mutate) -> None:
    shard_dir = root / "shards/shard_00000"
    frames_path = shard_dir / "frames.jsonl"
    lines = frames_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    mutate(payload)
    lines[-1] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    frames_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256(frames_path.read_bytes()).hexdigest()
    marker_path = shard_dir / "shard.complete.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    entry = next(item for item in marker["files"] if item["path"] == "frames.jsonl")
    entry["bytes"] = frames_path.stat().st_size
    entry["sha256"] = digest
    _write_json(marker_path, marker)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = next(
        asset
        for asset in manifest["shards"][0]["assets"]
        if asset["asset_id"].endswith("frames")
    )
    asset["sha256"] = digest
    _write_json(manifest_path, manifest)


def _validation_fixture(root: Path) -> None:
    recorder = _recorder(root, _configuration())
    recorder.begin_episode("scene", "environment", "scene")
    block = np.ones((4, 2_400), dtype=np.float32)
    _append(recorder, _frame(0, 0.0), block)
    _append(recorder, _frame(1, 0.45), block)
    recorder.end_episode()
    recorder.finalize()


@pytest.mark.parametrize(
    ("code", "mutate"),
    [
        (
            "time_gap_metadata_mismatch",
            lambda record: record["frame"]["diagnostics"]["recording"][
                "time_gap"
            ].__setitem__("inserted_silence_samples", 1),
        ),
        (
            "unexpected_audio_gap",
            lambda record: record.__setitem__(
                "audio_start_sample", record["audio_start_sample"] + 1
            ),
        ),
    ],
)
def test_validator_frozen_gap_finding_codes(tmp_path, code, mutate):
    root = tmp_path / code
    _validation_fixture(root)
    _mutate_frame_record(root, mutate)
    report = validate_dataset(root)
    assert code in report.finding_totals


def test_validator_non_monotonic_window_placement_code(tmp_path):
    root = tmp_path / "placement"
    _validation_fixture(root)

    def mutate(record):
        record["frame"]["timestamp_ms"] = -1

    _mutate_frame_record(root, mutate)
    report = validate_dataset(root)
    assert "non_monotonic_window_placement" in report.finding_totals
