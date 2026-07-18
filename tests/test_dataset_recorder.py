"""Integration coverage for the S2.2 session recorder and memory harness."""

from __future__ import annotations

import errno
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.dataset import (
    CancellationToken,
    CancelledWrite,
    FilesystemSeam,
    SessionRecorder,
    SessionRecorderError,
    classify_session_lifecycle,
    resume,
    validate_session_layout,
)
from isaac_audio_sensors.core.dataset.layout import (
    MAX_STREAMING_WARNINGS_PER_SHARD,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.types import AudioSensorFrame

REPO_ROOT = Path(__file__).resolve().parents[1]
_CANCEL_FRAMES = tuple(
    sorted(np.random.default_rng(2217).choice(np.arange(3, 9), size=3, replace=False))
)


def _configuration(
    *,
    aligned: bool,
    shard_max_frames: int,
    dataset_id: str = "recorder_test",
) -> dict[str, object]:
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
        "shard_max_frames": shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": 6,
    }


def _recorder_kwargs() -> dict[str, object]:
    return {
        "creation": CreationProvenance(
            tool_name="recorder_test",
            tool_version="1.0",
            backend_id="tdoa_synthetic",
            estimator_id="test_estimator",
        ),
        "device": DeviceProvenance(
            device_id="test_host",
            device_type="synthetic",
            platform="test",
            compute_device="cpu",
        ),
        "license": "CC0-1.0",
        "source": "deterministic recorder integration test",
        "coordinate_frames": ("world", "array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1_767_225_600_000,
    }


def _frame(index: int, *, episode_frame: int | None = None) -> AudioSensorFrame:
    local = index if episode_frame is None else episode_frame
    return AudioSensorFrame(
        frame_id=f"producer_{local}",
        frame_name=f"frame_{index}",
        timestamp_ms=local,
        start_time_s=local / 1000.0,
        end_time_s=local / 1000.0 + 0.001,
        sample_rate_hz=48_000,
        frame_index=local,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        aggregate_per_mic_rms={"front": 0.1, "rear": 0.1},
        diagnostics={"deterministic": True},
    )


def _audio(index: int) -> np.ndarray:
    values = np.arange(16, dtype=np.float32).reshape(2, 8)
    return values / np.float32(32.0) + np.float32(index / 128.0)


def _rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS is absent from /proc/self/status")


def _record_session(
    root: Path,
    *,
    aligned: bool,
    shard_max_frames: int,
    episode_sizes: tuple[int, ...] = (7,),
) -> None:
    recorder = SessionRecorder(
        root,
        _configuration(aligned=aligned, shard_max_frames=shard_max_frames),
        **_recorder_kwargs(),
    )
    global_index = 0
    for episode_ordinal, episode_size in enumerate(episode_sizes):
        scene = "scene_a" if episode_ordinal < 2 else "scene_b"
        recorder.begin_episode(scene, f"environment_{episode_ordinal}", scene)
        for local_index in range(episode_size):
            result = recorder.append_frame(
                _frame(global_index, episode_frame=local_index),
                _audio(global_index),
                local_index,
                is_reset=local_index == 0,
            )
            assert result.accepted
            global_index += 1
        recorder.end_episode()
    recorder.finalize()


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _concatenated_audio(root: Path) -> np.ndarray:
    layout = validate_session_layout(root)
    return np.concatenate(
        [read_wav(item.shard_dir / "audio.wav").samples for item in layout.shards],
        axis=1,
    )


def test_aligned_session_validates_and_is_byte_identical(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _record_session(first, aligned=True, shard_max_frames=4, episode_sizes=(2, 2, 3))
    _record_session(second, aligned=True, shard_max_frames=4, episode_sizes=(2, 2, 3))

    result = validate_session_layout(first)
    assert result.lifecycle_state == "complete"
    assert result.warnings == ()
    assert _file_bytes(first) == _file_bytes(second)


@pytest.mark.parametrize(
    ("aligned", "episode_sizes"),
    [(False, (9,)), (True, (9,))],
)
def test_rotation_concatenation_equivalence(tmp_path, aligned, episode_sizes):
    single = tmp_path / "single"
    rotated = tmp_path / "rotated"
    _record_session(
        single,
        aligned=aligned,
        shard_max_frames=100,
        episode_sizes=episode_sizes,
    )
    _record_session(
        rotated,
        aligned=aligned,
        shard_max_frames=3,
        episode_sizes=episode_sizes,
    )

    single_audio = _concatenated_audio(single)
    rotated_audio = _concatenated_audio(rotated)
    np.testing.assert_array_equal(rotated_audio, single_audio)
    single_layout = validate_session_layout(single)
    rotated_layout = validate_session_layout(rotated)
    rotated_samples = sum(
        item.marker["audio"]["sample_count"] for item in rotated_layout.shards
    )
    assert rotated_samples == single_layout.shards[0].marker["audio"]["sample_count"]
    assert all(item.marker["tail_samples"] == 0 for item in rotated_layout.shards[:-1])


def test_resume_after_sigkill_replays_from_published_boundary(tmp_path):
    crashed = tmp_path / "crashed"
    control = tmp_path / "control"
    script = textwrap.dedent(
        """
        import sys, time
        from pathlib import Path
        import numpy as np
        from isaac_audio_sensors.core.dataset import SessionRecorder
        from isaac_audio_sensors.core.dataset_manifest import (
            CreationProvenance,
            DeviceProvenance,
        )
        from isaac_audio_sensors.core.types import AudioSensorFrame

        root = Path(sys.argv[1])
        cfg = json.loads(sys.argv[2])
        kwargs = dict(
            creation=CreationProvenance(
                tool_name='recorder_test',
                tool_version='1.0',
                backend_id='tdoa_synthetic',
                estimator_id='test_estimator',
            ),
            device=DeviceProvenance(
                device_id='test_host',
                device_type='synthetic',
                platform='test',
                compute_device='cpu',
            ),
            license='CC0-1.0',
            source='deterministic recorder integration test',
            coordinate_frames=('world','array'),
            time_base='simulation_time',
            creation_timestamp_ms=1767225600000,
        )
        recorder = SessionRecorder(root, cfg, **kwargs)
        recorder.begin_episode('scene_a', 'environment_0', 'scene_a')
        values = np.arange(16, dtype=np.float32).reshape(2, 8)
        for index in range(3):
            frame = AudioSensorFrame(
                frame_id=f'producer_{index}',
                frame_name=f'frame_{index}',
                timestamp_ms=index,
                start_time_s=index/1000,
                end_time_s=index/1000+0.001,
                sample_rate_hz=48000,
                frame_index=index,
                backend_id='tdoa_synthetic',
                array_id='array',
                provenance='synthetic/core',
                aggregate_per_mic_rms={'front':0.1,'rear':0.1},
                diagnostics={'deterministic': True},
            )
            block = values / np.float32(32.0) + np.float32(index/128.0)
            recorder.append_frame(
                frame, block, index, is_reset=index == 0
            )
        print('READY', flush=True)
        time.sleep(30)
        """
    )
    script = "import json\n" + script
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(crashed),
            json.dumps(_configuration(aligned=False, shard_max_frames=2)),
        ],
        cwd=REPO_ROOT,
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

    assert classify_session_lifecycle(crashed) == "in-progress-or-aborted"
    recorder = resume(
        crashed,
        _configuration(aligned=False, shard_max_frames=2),
        **_recorder_kwargs(),
    )
    assert recorder.next_dataset_frame_index == 2
    for index in range(2, 5):
        recorder.append_frame(_frame(index), _audio(index), index)
    recorder.end_episode()
    recorder.finalize()

    _record_session(control, aligned=False, shard_max_frames=2, episode_sizes=(5,))
    assert _file_bytes(crashed) == _file_bytes(control)
    resumed_result = validate_session_layout(crashed)
    control_result = validate_session_layout(control)
    assert resumed_result.manifest == control_result.manifest
    assert [item.marker for item in resumed_result.shards] == [
        item.marker for item in control_result.shards
    ]


@pytest.mark.parametrize("cancel_frame", _CANCEL_FRAMES)
def test_seeded_cancellation_never_false_completes(tmp_path, cancel_frame):
    token = CancellationToken()
    root = tmp_path / f"cancel_{cancel_frame}"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=2),
        cancellation_token=token,
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    for index in range(cancel_frame):
        recorder.append_frame(_frame(index), _audio(index), index, is_reset=index == 0)
    token.cancel()
    with pytest.raises(CancelledWrite):
        recorder.append_frame(_frame(cancel_frame), _audio(cancel_frame), cancel_frame)

    result = validate_session_layout(root)
    assert result.lifecycle_state == "finalized-incomplete"
    for shard_dir in (root / "shards").iterdir():
        assert (shard_dir / "shard.complete.json").is_file()


def test_enospc_during_promotion_preserves_prior_shard(tmp_path):
    target_replace: int | None = None

    def fail_target(operation: str, index: int) -> None:
        if operation == "replace" and target_replace == index:
            raise OSError(errno.ENOSPC, "injected promotion disk full")

    seam = FilesystemSeam(operation_hook=fail_target)
    root = tmp_path / "enospc"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=2),
        seam=seam,
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    for index in range(3):
        recorder.append_frame(_frame(index), _audio(index), index, is_reset=index == 0)
    assert (root / "shards/shard_00000/shard.complete.json").is_file()
    target_replace = seam.operation_count("replace") + 4

    with pytest.raises(
        SessionRecorderError, match=r"shard shard_00001.*promotion failed"
    ):
        recorder.append_frame(_frame(3), _audio(3), 3)
        recorder.append_frame(_frame(4), _audio(4), 4)
    assert (root / "shards/shard_00000/shard.complete.json").is_file()
    assert not (root / "shards/shard_00001").exists()


def test_projection_failure_is_drop_accounted_without_index(tmp_path):
    root = tmp_path / "drop"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=2),
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    invalid = frame_to_trace_dict(_frame(99))
    invalid["waveform_paths"] = ["/absolute/not-portable.wav"]
    dropped = recorder.append_frame(invalid, _audio(99), 99)
    assert not dropped.accepted
    assert recorder.next_dataset_frame_index == 0
    for index in range(2):
        accepted = recorder.append_frame(
            _frame(index), _audio(index), index, is_reset=index == 0
        )
        assert accepted.dataset_frame_index == index
    recorder.end_episode()
    recorder.finalize()

    result = validate_session_layout(root)
    marker = result.shards[0].marker
    assert marker["dropped_frames"] == {
        "count": 1,
        "producer_frame_ids": ["producer_99"],
    }


def test_warning_heavy_finalize_retains_bounded_layout_examples(tmp_path):
    root = tmp_path / "warning_heavy_finalize"
    frame_count = 12
    paths_per_frame = MAX_STREAMING_WARNINGS_PER_SHARD // frame_count + 2
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=frame_count),
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    for index in range(frame_count):
        payload = frame_to_trace_dict(_frame(index))
        payload["diagnostics"] = {
            f"host_path_{path_index:02d}": (
                f"/var/tmp/recorder/frame_{index:03d}_{path_index:02d}.log"
            )
            for path_index in range(paths_per_frame)
        }
        result = recorder.append_frame(
            payload,
            _audio(index),
            index,
            is_reset=index == 0,
        )
        assert result.accepted
    recorder.end_episode()

    manifest = recorder.finalize()
    streamed = validate_session_layout(root, retain_records=False)
    expected_total = frame_count * paths_per_frame

    assert manifest.completion_state == "complete"
    assert len(streamed.shards) == 1
    assert len(streamed.shards[0].warnings) == MAX_STREAMING_WARNINGS_PER_SHARD
    assert streamed.shards[0].warning_count == expected_total
    assert streamed.total_warning_count == expected_total
    # A small-session RSS delta is allocator- and test-order-sensitive. The
    # retained result shape directly guards the finalize path's bounded object set.
    assert len(streamed.warnings) == MAX_STREAMING_WARNINGS_PER_SHARD


def test_memory_harness_scale_smoke(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from measure_writer_memory import run_memory_measurements

        result = run_memory_measurements(
            "W2",
            output_json=tmp_path / "telemetry.json",
            session_root=tmp_path / "sessions",
            scale=0.02,
        )
    finally:
        sys.path.pop(0)
    assert result["run_kind"] == "smoke"
    assert result["status_is_acceptance_evidence"] is False
    assert result["runs"]["W2"]["baseline"]["sample_count"] == 3
    assert result["runs"]["W2"]["samples"]
    assert result["runs"]["W2"]["validation"]["passed"]
    assert json.loads((tmp_path / "telemetry.json").read_text())["status"] == "passed"


def test_unaligned_multishard_recording_does_not_retain_frame_payloads(tmp_path):
    root = tmp_path / "bounded_recording"
    recorder = SessionRecorder(
        root,
        _configuration(aligned=False, shard_max_frames=400),
        **_recorder_kwargs(),
    )
    recorder.begin_episode("scene_a", "environment_0", "scene_a")
    diagnostic_blob = "x" * (16 * 1024)
    baseline = _rss_bytes()
    peak = baseline

    for index in range(1_600):
        payload = frame_to_trace_dict(_frame(index))
        payload["diagnostics"] = {"retention_guard": diagnostic_blob}
        result = recorder.append_frame(
            payload,
            _audio(index),
            index,
            is_reset=index == 0,
        )
        assert result.accepted
        peak = max(peak, _rss_bytes())
    recorder.end_episode()
    recorder.finalize()
    peak = max(peak, _rss_bytes())

    # Four retained 400-frame shards would keep at least 25 MiB of diagnostic
    # strings alone. 18 MiB leaves ample room for bounded writer bookkeeping
    # while remaining below that unavoidable pre-fix payload-retention floor.
    assert peak - baseline < 18 * 1024 * 1024
    assert recorder.promoted_shard_count == 4
    assert all(isinstance(marker, dict) for marker in recorder._published)
