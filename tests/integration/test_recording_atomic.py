"""Atomic writer fault and determinism tests."""

from __future__ import annotations

import errno
import hashlib
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording import (
    CancellationToken,
    CancelledWrite,
    CarryState,
    DatasetLayoutError,
    FilesystemSeam,
    JsonlShardFile,
    StagedFile,
    StreamingWavShardWriter,
    build_dataset_frame_record,
    build_shard_completion,
    publish_file,
    serialize_dataset_frame_record,
    verify_shard_completion,
    write_json_atomic,
)


def _enospc_at(operation: str, index: int):
    def hook(actual_operation: str, actual_index: int) -> None:
        if (actual_operation, actual_index) == (operation, index):
            raise OSError(errno.ENOSPC, "injected disk full")

    return hook


def _record_line(index: int = 0, *, audio_end_sample: int = 4) -> str:
    frame = AudioSensorFrame(
        frame_id=f"producer_{index}",
        timestamp_ms=index,
        backend_id="tdoa_synthetic",
        array_id="array",
        sample_rate_hz=48_000,
        frame_index=index,
        provenance="synthetic/core",
    )
    record = build_dataset_frame_record(
        dataset_frame_index=index,
        episode_id_value="episode_00000",
        audio_start_sample=0,
        audio_end_sample=audio_end_sample,
        frame=frame,
    )
    return serialize_dataset_frame_record(record)


def _write_assets(root: Path, *, seam: FilesystemSeam | None = None) -> Path:
    staging = root / "_staging/shard_00000"
    final = root / "shards/shard_00000"
    jsonl = JsonlShardFile(staging, seam=seam)
    jsonl.append(_record_line())
    wav = StreamingWavShardWriter(
        staging,
        channels=2,
        sample_rate_hz=48_000,
        seam=seam,
    )
    wav.append(np.arange(8, dtype=np.float32).reshape(2, 4))
    wav.finalize(flush_carry=False)
    jsonl.publish(final / "frames.jsonl")
    wav.publish(final / "audio.wav")
    return final


def _write_complete_shard(root: Path) -> Path:
    final = _write_assets(root)
    marker = build_shard_completion(
        final,
        shard_id_value="shard_00000",
        start_frame=0,
        episode_ids=("episode_00000",),
        writer_tool_version="test",
    )
    write_json_atomic(final / "shard.complete.json", marker)
    verify_shard_completion(final)
    return final


def test_enospc_staged_payload_never_reaches_final(tmp_path):
    seam = FilesystemSeam(operation_hook=_enospc_at("write", 1))
    staged = StagedFile(tmp_path / "_staging", "payload.bin", seam=seam)

    with pytest.raises(OSError) as error:
        staged.append(b"payload")
    assert error.value.errno == errno.ENOSPC
    with pytest.raises(RuntimeError, match="failed"):
        publish_file(staged, tmp_path / "final/payload.bin")
    staged.abort()

    assert not (tmp_path / "final/payload.bin").exists()


def test_enospc_wav_header_patch_never_reaches_final(tmp_path):
    seam = FilesystemSeam(operation_hook=_enospc_at("write", 3))
    writer = StreamingWavShardWriter(
        tmp_path / "_staging", channels=2, sample_rate_hz=48_000, seam=seam
    )
    writer.append(np.ones((2, 4), dtype=np.float32))

    with pytest.raises(OSError) as error:
        writer.finalize(flush_carry=False)
    assert error.value.errno == errno.ENOSPC
    with pytest.raises(RuntimeError, match="finalized"):
        writer.publish(tmp_path / "final/audio.wav")
    writer.abort()

    assert not (tmp_path / "final/audio.wav").exists()


def test_enospc_publish_replace_preserves_atomic_visibility(tmp_path):
    seam = FilesystemSeam(operation_hook=_enospc_at("replace", 1))
    jsonl = JsonlShardFile(tmp_path / "_staging", seam=seam)
    line = _record_line()
    jsonl.append(line)

    with pytest.raises(OSError) as error:
        jsonl.publish(tmp_path / "final/frames.jsonl")
    assert error.value.errno == errno.ENOSPC
    assert not (tmp_path / "final/frames.jsonl").exists()
    assert jsonl.path.read_bytes() == line.encode("utf-8")
    jsonl.abort()


def test_enospc_marker_write_leaves_assets_unmarked(tmp_path):
    final = _write_assets(tmp_path)
    marker = build_shard_completion(
        final,
        shard_id_value="shard_00000",
        start_frame=0,
        episode_ids=("episode_00000",),
        writer_tool_version="test",
    )
    seam = FilesystemSeam(operation_hook=_enospc_at("write", 1))

    with pytest.raises(OSError) as error:
        write_json_atomic(final / "shard.complete.json", marker, seam=seam)
    assert error.value.errno == errno.ENOSPC
    assert not (final / "shard.complete.json").exists()
    with pytest.raises(DatasetLayoutError, match="missing completion marker"):
        verify_shard_completion(final)
    assert read_wav(final / "audio.wav").frame_count == 4
    assert (final / "frames.jsonl").read_text(encoding="utf-8") == _record_line()


@pytest.mark.parametrize("phase", ["mid_jsonl", "post_audio", "mid_promotion"])
def test_subprocess_sigkill_never_exposes_a_complete_shard(tmp_path, phase):
    script = textwrap.dedent(
        r"""
        import sys
        import time
        from pathlib import Path

        import numpy as np

        from isaac_audio_sensors.recording import (
            FilesystemSeam,
            JsonlShardFile,
            StreamingWavShardWriter,
        )

        root = Path(sys.argv[1])
        phase = sys.argv[2]
        line = sys.argv[3]
        staging = root / "_staging/shard_00000"
        final = root / "shards/shard_00000"

        if phase == "mid_jsonl":
            def truncate_and_pause(stream, data, index):
                if index == 1:
                    written = stream.write(data[: max(1, len(data) // 2)])
                    print("READY", flush=True)
                    time.sleep(30)
                    return written
                return None

            seam = FilesystemSeam(write_hook=truncate_and_pause)
            JsonlShardFile(staging, seam=seam).append(line)
        else:
            jsonl = JsonlShardFile(staging)
            jsonl.append(line)
            wav = StreamingWavShardWriter(
                staging, channels=2, sample_rate_hz=48000
            )
            wav.append(np.arange(8, dtype=np.float32).reshape(2, 4))
            wav.finalize(flush_carry=False)
            if phase == "mid_promotion":
                jsonl.publish(final / "frames.jsonl")
            print("READY", flush=True)
            time.sleep(30)
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), phase, _record_line()],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        process.kill()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    final = tmp_path / "shards/shard_00000"
    published = list(final.glob("*")) if final.exists() else []
    assert all(path.name == "frames.jsonl" for path in published)
    assert all(path.read_bytes().endswith(b"\n") for path in published)
    assert not (final / "shard.complete.json").exists()
    with pytest.raises(DatasetLayoutError, match="missing completion marker"):
        verify_shard_completion(final)


def test_partial_jsonl_line_cannot_publish_and_truncation_is_located(tmp_path):
    def truncate_then_fail(stream, data, index):
        if index == 1:
            stream.write(data[: len(data) // 2])
            raise OSError(errno.ENOSPC, "injected after partial line")
        return None

    seam = FilesystemSeam(write_hook=truncate_then_fail)
    writer = JsonlShardFile(tmp_path / "partial/_staging", seam=seam)
    with pytest.raises(OSError):
        writer.append(_record_line())
    with pytest.raises(RuntimeError, match="failed"):
        writer.publish(tmp_path / "partial/shards/shard_00000/frames.jsonl")
    writer.abort()
    assert not (tmp_path / "partial/shards/shard_00000/frames.jsonl").exists()

    final = _write_complete_shard(tmp_path / "published")
    frames_path = final / "frames.jsonl"
    frames_path.write_bytes(frames_path.read_bytes()[:-1])
    marker_path = final / "shard.complete.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    frames_entry = next(
        item for item in marker["files"] if item["path"] == "frames.jsonl"
    )
    frames_entry["bytes"] = frames_path.stat().st_size
    frames_entry["sha256"] = hashlib.sha256(frames_path.read_bytes()).hexdigest()
    marker_path.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(
        DatasetLayoutError,
        match=r"shard shard_00000 file frames\.jsonl: final line",
    ):
        verify_shard_completion(final)


@pytest.mark.parametrize(
    "line", ["{}", "{}\n{}\n", "\n", "{}\r\n", b"{}\n"]
)
def test_jsonl_rejects_non_single_line_text(tmp_path, line):
    writer = JsonlShardFile(tmp_path / "_staging")
    expected = TypeError if isinstance(line, bytes) else ValueError
    with pytest.raises(expected):
        writer.append(line)
    writer.abort()


def _deterministic_outputs(root: Path, seam: FilesystemSeam) -> tuple[bytes, bytes]:
    staging = root / "_staging"
    final = root / "final"
    jsonl = JsonlShardFile(staging, seam=seam)
    jsonl.append(_record_line())
    jsonl.publish(final / "frames.jsonl")
    wav = StreamingWavShardWriter(
        staging,
        channels=2,
        sample_rate_hz=48_000,
        seam=seam,
        checksum_chunk_size=13,
    )
    wav.append(np.linspace(-1.0, 1.0, 18, dtype=np.float32).reshape(2, 9))
    wav.finalize(flush_carry=False)
    wav.publish(final / "audio.wav")
    return (final / "frames.jsonl").read_bytes(), (final / "audio.wav").read_bytes()


def test_slow_writer_hook_preserves_deterministic_bytes(tmp_path):
    baseline = _deterministic_outputs(tmp_path / "baseline", FilesystemSeam())

    def delay(operation: str, index: int) -> None:
        del index
        if operation == "write":
            time.sleep(0.0001)

    throttled = _deterministic_outputs(
        tmp_path / "throttled", FilesystemSeam(delay_hook=delay)
    )
    assert throttled == baseline


def test_retry_and_short_write_match_no_failure_and_enospc_is_not_retried(tmp_path):
    payload = b"deterministic retry payload"
    baseline = StagedFile(tmp_path / "baseline", "payload.bin")
    baseline.append(payload)
    publish_file(baseline, tmp_path / "baseline-final/payload.bin")

    transient_calls = 0

    def transient(operation: str, index: int) -> None:
        nonlocal transient_calls
        if operation == "write":
            transient_calls += 1
            if index == 1:
                raise OSError(errno.EAGAIN, "injected transient error")

    retrying = StagedFile(
        tmp_path / "retry", "payload.bin", seam=FilesystemSeam(operation_hook=transient)
    )
    retrying.append(payload)
    publish_file(retrying, tmp_path / "retry-final/payload.bin")
    assert transient_calls == 2
    assert (tmp_path / "retry-final/payload.bin").read_bytes() == payload

    def short_write(stream, data, index):
        del stream
        if index == 1:
            return max(1, len(data) // 3)
        return None

    short = StagedFile(
        tmp_path / "short",
        "payload.bin",
        seam=FilesystemSeam(write_hook=short_write),
    )
    short.append(payload)
    publish_file(short, tmp_path / "short-final/payload.bin")
    assert (tmp_path / "short-final/payload.bin").read_bytes() == payload

    enospc_calls = 0

    def disk_full(operation: str, index: int) -> None:
        nonlocal enospc_calls
        del index
        if operation == "write":
            enospc_calls += 1
            raise OSError(errno.ENOSPC, "injected disk full")

    failed = StagedFile(
        tmp_path / "enospc",
        "payload.bin",
        seam=FilesystemSeam(operation_hook=disk_full),
    )
    with pytest.raises(OSError) as error:
        failed.append(payload)
    assert error.value.errno == errno.ENOSPC
    assert enospc_calls == 1
    failed.abort()


def test_cancellation_aborts_without_final_artifacts(tmp_path):
    token = CancellationToken()
    writer = JsonlShardFile(
        tmp_path / "_staging", cancellation_token=token
    )
    writer.append(_record_line())
    token.cancel()
    assert token.cancelled

    with pytest.raises(CancelledWrite):
        writer.append(_record_line(1))
    writer.abort()

    assert not writer.path.exists()
    assert not (tmp_path / "final/frames.jsonl").exists()


@pytest.mark.parametrize("flush_carry", [False, True])
def test_wav_finalize_is_bit_exact_and_reports_disk_reality(tmp_path, flush_carry):
    rng = np.random.default_rng(2217)
    block = rng.standard_normal((3, 17), dtype=np.float32)
    pending = rng.standard_normal((3, 5), dtype=np.float32)
    carry = CarryState(pending.copy())
    seam = FilesystemSeam()
    writer = StreamingWavShardWriter(
        tmp_path / "_staging",
        channels=3,
        sample_rate_hz=44_100,
        seam=seam,
        carry_state=carry,
        checksum_chunk_size=19,
    )
    writer.append(block[:, :7])
    writer.append(block[:, 7:])
    assert writer.sample_count == block.shape[1]

    result = writer.finalize(flush_carry=flush_carry)
    final_path = tmp_path / "final/audio.wav"
    writer.publish(final_path)
    wave = read_wav(final_path)
    expected = np.concatenate((block, pending), axis=1) if flush_carry else block

    assert wave.sample_rate_hz == 44_100
    np.testing.assert_array_equal(wave.samples, expected)
    assert result["sample_count"] == expected.shape[1]
    assert result["bytes"] == final_path.stat().st_size
    assert result["sha256"] == hashlib.sha256(final_path.read_bytes()).hexdigest()
    assert seam.operation_count("read") == (result["bytes"] + 18) // 19 + 1
    if flush_carry:
        assert carry.pending_samples.shape == (3, 0)
    else:
        np.testing.assert_array_equal(carry.take(), pending)
        assert carry.pending_samples.shape == (3, 0)
