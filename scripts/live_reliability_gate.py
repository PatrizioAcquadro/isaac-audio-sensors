#!/usr/bin/env python3
"""Pure-Python S2.9 reliability gate for session recording and recovery."""

from __future__ import annotations

import argparse
import errno
import json
import selectors
import shutil
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors.core.dataset import (
    FilesystemSeam,
    SessionDataset,
    SessionRecorder,
    SessionRecorderError,
    classify_session_lifecycle,
    resume,
    validate_dataset,
    validate_session_layout,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.types import AudioSensorFrame

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.9/reliability_gate.json"
)
DEFAULT_WORK_ROOT = (
    REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.9/reliability_sessions"
)
SCENARIOS = (
    "cancellation_restart",
    "simulator_replacement",
    "dependency_removal",
    "disk_failure",
    "resume",
)


def _configuration(
    *,
    dataset_id: str,
    backend_id: str = "tdoa_synthetic",
    shard_max_frames: int = 4,
) -> dict[str, Any]:
    return {
        "backend_id": backend_id,
        "channel_order": ["front", "rear"],
        "dataset_id": dataset_id,
        "dtype": "float32",
        "hop_sample_count": 4,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 48_000,
        "session_seed": 2_026_072,
        "shard_episode_aligned": False,
        "shard_max_frames": shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": 8,
    }


def _recorder_kwargs(backend_id: str = "tdoa_synthetic") -> dict[str, Any]:
    return {
        "creation": CreationProvenance(
            tool_name="live_reliability_gate",
            tool_version="1.0",
            backend_id=backend_id,
            estimator_id=backend_id,
        ),
        "device": DeviceProvenance(
            device_id="s2_9_synthetic_host",
            device_type="synthetic",
            platform=sys.platform,
            compute_device="cpu",
        ),
        "license": "CC0-1.0",
        "source": "S2.9 deterministic reliability gate",
        "coordinate_frames": ("world", "array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1_767_225_600_000,
    }


def _frame(index: int, *, backend_id: str = "tdoa_synthetic") -> AudioSensorFrame:
    timestamp_ms = index * 10
    return AudioSensorFrame(
        frame_id=f"producer_{index:09d}",
        frame_name=f"synthetic_{index:09d}",
        timestamp_ms=timestamp_ms,
        start_time_s=timestamp_ms / 1_000.0,
        end_time_s=timestamp_ms / 1_000.0 + 0.01,
        sample_rate_hz=48_000,
        frame_index=index,
        backend_id=backend_id,
        array_id="array",
        provenance="synthetic/core",
        aggregate_per_mic_rms={"front": 0.1, "rear": 0.1},
        diagnostics={"generator": "s2.9_reliability_gate", "index": index},
    )


def _audio(index: int) -> np.ndarray:
    values = np.arange(16, dtype=np.float32).reshape(2, 8)
    return values / np.float32(64.0) + np.float32((index % 17) / 256.0)


def _record_frames(
    recorder: SessionRecorder,
    start: int,
    stop: int,
    *,
    backend_id: str = "tdoa_synthetic",
) -> None:
    for index in range(start, stop):
        result = recorder.append_frame(
            _frame(index, backend_id=backend_id),
            _audio(index),
            index * 10,
            is_reset=index == 0,
        )
        if not result.accepted:
            raise AssertionError(f"frame {index} was rejected: {result.reason}")


def _new_recorder(
    root: Path,
    configuration: Mapping[str, Any],
    *,
    seam: FilesystemSeam | None = None,
) -> SessionRecorder:
    backend = str(configuration["backend_id"])
    recorder = SessionRecorder(
        root,
        configuration,
        seam=seam,
        **_recorder_kwargs(backend),
    )
    recorder.begin_episode("scene", "environment", "scene")
    return recorder


def _reset_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _validator_summary(root: Path, *, incomplete: bool = False) -> dict[str, Any]:
    report = validate_dataset(root, allow_incomplete=incomplete, deep_audio=True)
    if report.status != "passed" or report.error_count != 0:
        raise AssertionError(
            f"canonical validator failed for {root}: {report.to_dict()}"
        )
    return report.to_dict()


def _marker_drop_total(root: Path) -> int:
    return sum(
        int(item.marker["dropped_frames"]["count"])
        for item in validate_session_layout(root, retain_records=False).shards
    )


def _semantic_frames(root: Path, *, incomplete: bool = False) -> list[dict[str, Any]]:
    dataset = SessionDataset.open(root, allow_incomplete=incomplete)
    return [
        {
            "dataset_frame_index": item.dataset_frame_index,
            "episode_id": item.episode_id,
            "frame": frame_to_trace_dict(item.frame),
        }
        for item in dataset.iter_records()
    ]


def _assert_accounting(root: Path, expected_frames: int) -> dict[str, Any]:
    report = validate_dataset(root, allow_incomplete=True)
    statistics = report.statistics.to_dict()
    validator_frames = int(statistics["counts"]["frames"])
    validator_drops = int(statistics["dropped_frames"]["total"])
    marker_drops = _marker_drop_total(root)
    unreported = expected_frames - validator_frames - marker_drops
    if (
        report.status != "passed"
        or validator_frames != expected_frames
        or validator_drops != marker_drops
        or unreported != 0
    ):
        raise AssertionError(
            "frame accounting mismatch: "
            f"expected={expected_frames}, validator={validator_frames}, "
            f"marker_drops={marker_drops}, validator_drops={validator_drops}, "
            f"unreported={unreported}"
        )
    return {
        "producer_frames": expected_frames,
        "validator_frames": validator_frames,
        "marker_dropped_frames": marker_drops,
        "validator_dropped_frames": validator_drops,
        "unreported_frames": unreported,
    }


def _write_log(path: Path | None, lines: list[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _scenario(
    name: str,
    operation: Callable[[], dict[str, Any]],
    *,
    log_path: Path | None,
    log_lines: list[str],
) -> dict[str, Any]:
    try:
        detail = operation()
        record = {"scenario": name, "status": "passed", "detail": detail}
    except BaseException as exc:  # noqa: BLE001 - evidence retains exact failures.
        if isinstance(exc, KeyboardInterrupt):
            raise
        log_lines.append(traceback.format_exc())
        record = {
            "scenario": name,
            "status": "failed",
            "detail": {
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        }
    _write_log(log_path, log_lines + [json.dumps(record, sort_keys=True)])
    return record


def _read_worker_until(
    process: subprocess.Popen[str],
    predicate: Callable[[str], bool],
    *,
    timeout_s: float = 10.0,
) -> list[str]:
    if process.stdout is None:
        raise RuntimeError("worker stdout pipe is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_s
    lines: list[str] = []
    try:
        while time.monotonic() < deadline:
            ready = selector.select(timeout=min(0.25, deadline - time.monotonic()))
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            text = line.rstrip("\n")
            lines.append(text)
            if predicate(text):
                return lines
    finally:
        selector.close()
    stderr = ""
    if process.poll() is not None and process.stderr is not None:
        stderr = process.stderr.read()
    raise RuntimeError(
        f"worker did not reach the requested state; exit={process.poll()}, "
        f"stdout={lines!r}, stderr={stderr!r}"
    )


def _worker_command(
    kind: str,
    root: Path,
    *,
    frames: int,
    shard_max_frames: int,
    ready_after: int,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        kind,
        "--worker-root",
        str(root),
        "--worker-frames",
        str(frames),
        "--worker-shard-max-frames",
        str(shard_max_frames),
        "--worker-ready-after",
        str(ready_after),
    ]


def scenario_cancellation_restart(
    root: str | Path,
    *,
    frame_count: int = 18,
    shard_max_frames: int = 4,
    seed: int = 2_029,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Cancel a real subprocess by signal, resume, and reconcile all frames."""

    scenario_root = Path(root)
    log_lines: list[str] = []

    def run() -> dict[str, Any]:
        if frame_count < 2 * shard_max_frames + 3:
            raise ValueError("frame_count must leave a published and in-flight shard")
        _reset_path(scenario_root)
        control = scenario_root.parent / f"{scenario_root.name}_control"
        _reset_path(control)
        rng = np.random.default_rng(seed)
        cancel_after = int(
            rng.integers(shard_max_frames + 1, frame_count - 1, endpoint=False)
        )
        process = subprocess.Popen(
            _worker_command(
                "interruptible",
                scenario_root,
                frames=frame_count,
                shard_max_frames=shard_max_frames,
                ready_after=cancel_after,
            ),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            lines = _read_worker_until(
                process,
                lambda line: line == f"FRAME {cancel_after - 1}",
            )
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            lines.extend(stdout.splitlines())
            log_lines.extend(lines)
            if stderr:
                log_lines.append("STDERR:\n" + stderr)
            if process.returncode != 0:
                raise RuntimeError(f"signal worker exited {process.returncode}")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

        lifecycle_before = classify_session_lifecycle(scenario_root)
        if lifecycle_before != "in-progress-or-aborted":
            raise AssertionError(
                f"unexpected cancellation lifecycle {lifecycle_before}"
            )
        configuration = _configuration(
            dataset_id="s2_9_cancellation_restart",
            shard_max_frames=shard_max_frames,
        )
        recorder = resume(
            scenario_root,
            configuration,
            **_recorder_kwargs(),
        )
        restart_boundary = recorder.next_dataset_frame_index
        _record_frames(recorder, restart_boundary, frame_count)
        recorder.end_episode()
        recorder.finalize()
        validator = _validator_summary(scenario_root)
        accounting = _assert_accounting(scenario_root, frame_count)

        control_recorder = _new_recorder(control, configuration)
        _record_frames(control_recorder, 0, frame_count)
        control_recorder.end_episode()
        control_recorder.finalize()
        semantic_equal = _semantic_frames(scenario_root) == _semantic_frames(control)
        if not semantic_equal:
            raise AssertionError("restarted session differs from uninterrupted control")
        return {
            "seed": seed,
            "signal": "SIGTERM",
            "cancel_after_frame_count": cancel_after,
            "worker_exit_code": process.returncode,
            "classification_before_restart": lifecycle_before,
            "restart_published_boundary": restart_boundary,
            "semantic_equal_to_control": semantic_equal,
            "accounting": accounting,
            "validator": validator,
        }

    return _scenario(
        "cancellation_restart",
        run,
        log_path=log_path,
        log_lines=log_lines,
    )


def scenario_simulator_replacement(
    root: str | Path,
    *,
    frame_count: int = 8,
    shard_max_frames: int = 3,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Prove a backend replacement is rejected in-place and clean as a new session."""

    scenario_root = Path(root)
    log_lines: list[str] = []

    def run() -> dict[str, Any]:
        if frame_count < shard_max_frames + 2:
            raise ValueError("frame_count is too small for a multi-shard session")
        _reset_path(scenario_root)
        session_a = scenario_root / "session_a"
        session_b = scenario_root / "session_b"
        config_a = _configuration(
            dataset_id="s2_9_simulator_a",
            shard_max_frames=shard_max_frames,
        )
        recorder_a = _new_recorder(session_a, config_a)
        prefix = max(1, frame_count // 2)
        _record_frames(recorder_a, 0, prefix)
        changed = recorder_a.append_frame(
            _frame(prefix, backend_id="room_acoustics"),
            _audio(prefix),
            prefix * 10,
        )
        if changed.accepted or changed.reason is None:
            raise AssertionError("mid-session backend mutation was not rejected")
        if "backend_id disagrees with configuration" not in changed.reason:
            raise AssertionError(f"backend rejection was not located: {changed.reason}")
        _record_frames(recorder_a, prefix, frame_count)
        recorder_a.end_episode()
        recorder_a.finalize()

        config_b = _configuration(
            dataset_id="s2_9_simulator_b",
            backend_id="room_acoustics",
            shard_max_frames=shard_max_frames,
        )
        recorder_b = _new_recorder(session_b, config_b)
        _record_frames(
            recorder_b,
            0,
            frame_count,
            backend_id="room_acoustics",
        )
        recorder_b.end_episode()
        recorder_b.finalize()
        validator_a = _validator_summary(session_a)
        validator_b = _validator_summary(session_b)
        a_drops = _marker_drop_total(session_a)
        if a_drops != 1:
            raise AssertionError(f"rejected backend frame was not accounted: {a_drops}")
        return {
            "session_a_backend": "tdoa_synthetic",
            "mid_session_rejection": {
                "accepted": changed.accepted,
                "located_error": changed.reason,
                "reported_drop_count": a_drops,
            },
            "session_b_backend": "room_acoustics",
            "replacement_operation": "new_session",
            "session_a_validator": validator_a,
            "session_b_validator": validator_b,
        }

    return _scenario(
        "simulator_replacement",
        run,
        log_path=log_path,
        log_lines=log_lines,
    )


class _WavOpenFailureSeam(FilesystemSeam):
    def __init__(self, failed_shard: str) -> None:
        super().__init__()
        self.failed_shard = failed_shard
        self.inject = False
        self.triggered_path: str | None = None

    def open(self, path: str | Path, mode: str) -> BinaryIO:
        candidate = Path(path)
        if (
            self.inject
            and candidate.name == "audio.wav"
            and self.failed_shard in candidate.parts
        ):
            self.inject = False
            self.triggered_path = str(candidate)
            raise OSError(
                errno.EIO,
                f"dependency-removal WAV open unavailable at {candidate}",
            )
        return super().open(candidate, mode)


def scenario_dependency_removal(
    root: str | Path,
    *,
    frame_count: int = 8,
    shard_max_frames: int = 3,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Inject WAV-open unavailability after a durable published prefix."""

    scenario_root = Path(root)
    log_lines: list[str] = []

    def run() -> dict[str, Any]:
        if frame_count < shard_max_frames + 1:
            raise ValueError("frame_count must cross the first shard boundary")
        _reset_path(scenario_root)
        seam = _WavOpenFailureSeam("shard_00001")
        configuration = _configuration(
            dataset_id="s2_9_dependency_removal",
            shard_max_frames=shard_max_frames,
        )
        recorder = _new_recorder(scenario_root, configuration, seam=seam)
        _record_frames(recorder, 0, shard_max_frames)
        seam.inject = True
        error: str | None = None
        try:
            _record_frames(recorder, shard_max_frames, shard_max_frames + 1)
        except OSError as exc:
            error = str(exc)
        if error is None or seam.triggered_path is None:
            raise AssertionError("WAV-open dependency failure did not trigger")
        if str(scenario_root) not in error or "audio.wav" not in error:
            raise AssertionError(f"dependency failure was not located: {error}")
        manifest = recorder.finalize_incomplete()
        validator = _validator_summary(scenario_root, incomplete=True)
        failed_dir = scenario_root / "shards/shard_00001"
        if failed_dir.exists() or any(
            path.name == "shard.complete.json" for path in failed_dir.glob("**/*")
        ):
            raise AssertionError("dependency failure published a partial shard")
        if len(manifest.shards) != 1:
            raise AssertionError("dependency failure did not preserve its prior shard")
        return {
            "injection": "stdlib WAV open seam failure",
            "located_error": error,
            "triggered_path": seam.triggered_path,
            "completion_state": manifest.completion_state,
            "published_prefix_shards": len(manifest.shards),
            "failed_shard_marker_absent": True,
            "validator": validator,
        }

    return _scenario(
        "dependency_removal",
        run,
        log_path=log_path,
        log_lines=log_lines,
    )


def _disk_failure_phase(
    root: Path,
    *,
    phase: str,
    shard_max_frames: int,
) -> dict[str, Any]:
    target: dict[str, int | str | None] = {"operation": None, "index": None}
    triggered = False

    def inject(operation: str, index: int) -> None:
        nonlocal triggered
        if target["operation"] == operation and target["index"] == index:
            triggered = True
            target["operation"] = None
            raise OSError(
                errno.ENOSPC,
                f"injected {phase} ENOSPC at session {root} shard shard_00001",
            )

    seam = FilesystemSeam(operation_hook=inject)
    configuration = _configuration(
        dataset_id=f"s2_9_disk_{phase}",
        shard_max_frames=shard_max_frames,
    )
    recorder = _new_recorder(root, configuration, seam=seam)
    _record_frames(recorder, 0, shard_max_frames + 1)
    if recorder.promoted_shard_count != 1:
        raise AssertionError("disk failure setup did not publish one prefix shard")

    if phase == "payload":
        target.update(operation="write", index=seam.operation_count("write") + 1)
        trigger_index = shard_max_frames + 1
    else:
        _record_frames(recorder, shard_max_frames + 1, 2 * shard_max_frames)
        replace_offset = 4 if phase == "promotion" else 6
        target.update(
            operation="replace",
            index=seam.operation_count("replace") + replace_offset,
        )
        trigger_index = 2 * shard_max_frames

    error: str | None = None
    try:
        _record_frames(recorder, trigger_index, trigger_index + 1)
    except (OSError, SessionRecorderError) as exc:
        error = str(exc)
    if not triggered or error is None:
        raise AssertionError(f"{phase} ENOSPC did not trigger")
    if str(root) not in error or "shard_00001" not in error:
        raise AssertionError(f"{phase} ENOSPC was not located: {error}")
    manifest = recorder.finalize_incomplete()
    validator = _validator_summary(root, incomplete=True)
    failed_dir = root / "shards/shard_00001"
    failed_marker_absent = not (failed_dir / "shard.complete.json").exists()
    if len(manifest.shards) != 1 or not failed_marker_absent:
        raise AssertionError(f"{phase} did not preserve only the published prefix")
    return {
        "phase": phase,
        "errno": errno.ENOSPC,
        "located_error": error,
        "completion_state": manifest.completion_state,
        "published_prefix_shards": len(manifest.shards),
        "failed_shard_marker_absent": failed_marker_absent,
        "validator": validator,
    }


def scenario_disk_failure(
    root: str | Path,
    *,
    frame_count: int = 8,
    shard_max_frames: int = 3,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Inject ENOSPC at payload, promotion, and marker phases."""

    del frame_count  # Phase schedules are derived from the shard boundary.
    scenario_root = Path(root)
    log_lines: list[str] = []

    def run() -> dict[str, Any]:
        if shard_max_frames < 2:
            raise ValueError("shard_max_frames must be at least two")
        _reset_path(scenario_root)
        scenario_root.mkdir(parents=True)
        phases = [
            _disk_failure_phase(
                scenario_root / phase,
                phase=phase,
                shard_max_frames=shard_max_frames,
            )
            for phase in ("payload", "promotion", "marker")
        ]
        return {"phases": phases, "all_located": True, "all_prefixes_intact": True}

    return _scenario(
        "disk_failure",
        run,
        log_path=log_path,
        log_lines=log_lines,
    )


def scenario_resume(
    root: str | Path,
    *,
    frame_count: int = 12,
    shard_max_frames: int = 4,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """SIGKILL a worker mid-shard, resume, and compare with a control run."""

    scenario_root = Path(root)
    log_lines: list[str] = []

    def run() -> dict[str, Any]:
        if frame_count < shard_max_frames + 3:
            raise ValueError("frame_count must include a published and partial shard")
        _reset_path(scenario_root)
        control = scenario_root.parent / f"{scenario_root.name}_control"
        _reset_path(control)
        ready_after = shard_max_frames + max(1, shard_max_frames // 2)
        process = subprocess.Popen(
            _worker_command(
                "sigkill",
                scenario_root,
                frames=frame_count,
                shard_max_frames=shard_max_frames,
                ready_after=ready_after,
            ),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            lines = _read_worker_until(
                process, lambda line: "READY_FOR_KILL" in line
            )
            log_lines.extend(lines)
            process.kill()
            _, stderr = process.communicate(timeout=10)
            if stderr:
                log_lines.append("STDERR:\n" + stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if process.returncode != -signal.SIGKILL:
            raise AssertionError(f"worker was not SIGKILLed: {process.returncode}")
        lifecycle_before = classify_session_lifecycle(scenario_root)
        if lifecycle_before != "in-progress-or-aborted":
            raise AssertionError(f"unexpected killed lifecycle {lifecycle_before}")

        configuration = _configuration(
            dataset_id="s2_9_resume",
            shard_max_frames=shard_max_frames,
        )
        recorder = resume(
            scenario_root,
            configuration,
            **_recorder_kwargs(),
        )
        resume_boundary = recorder.next_dataset_frame_index
        _record_frames(recorder, resume_boundary, frame_count)
        recorder.end_episode()
        recorder.finalize()
        validator = _validator_summary(scenario_root)

        control_recorder = _new_recorder(control, configuration)
        _record_frames(control_recorder, 0, frame_count)
        control_recorder.end_episode()
        control_recorder.finalize()
        resumed_frames = _semantic_frames(scenario_root)
        control_frames = _semantic_frames(control)
        shared_prefix_equal = (
            resumed_frames[:resume_boundary] == control_frames[:resume_boundary]
        )
        full_semantic_equal = resumed_frames == control_frames
        if not shared_prefix_equal or not full_semantic_equal:
            raise AssertionError("resumed semantic frames differ from control")
        accounting = _assert_accounting(scenario_root, frame_count)
        return {
            "signal": "SIGKILL",
            "worker_exit_code": process.returncode,
            "killed_after_frame_count": ready_after,
            "classification_before_resume": lifecycle_before,
            "resume_published_boundary": resume_boundary,
            "shared_prefix_frames": resume_boundary,
            "shared_prefix_semantic_equal": shared_prefix_equal,
            "full_semantic_equal": full_semantic_equal,
            "accounting": accounting,
            "validator": validator,
        }

    return _scenario("resume", run, log_path=log_path, log_lines=log_lines)


def _worker(kind: str, args: argparse.Namespace) -> int:
    root = args.worker_root
    configuration = _configuration(
        dataset_id=(
            "s2_9_cancellation_restart" if kind == "interruptible" else "s2_9_resume"
        ),
        shard_max_frames=args.worker_shard_max_frames,
    )
    recorder = _new_recorder(root, configuration)
    stopping = False

    def handle_signal(_signum: int, _frame_obj: Any) -> None:
        nonlocal stopping
        stopping = True

    if kind == "interruptible":
        signal.signal(signal.SIGTERM, handle_signal)
    for index in range(args.worker_frames):
        if stopping:
            print("SIGNAL_OBSERVED", flush=True)
            return 0
        _record_frames(recorder, index, index + 1)
        if kind == "sigkill" and index + 1 == args.worker_ready_after:
            print(f"FRAME {index} READY_FOR_KILL", flush=True)
            time.sleep(30)
        else:
            print(f"FRAME {index}", flush=True)
        time.sleep(0.01)
    if kind == "interruptible":
        while not stopping:
            time.sleep(0.01)
        print("SIGNAL_OBSERVED", flush=True)
        return 0
    raise RuntimeError("SIGKILL worker was not terminated at its ready point")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--frames", type=int, default=18)
    parser.add_argument("--shard-max-frames", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2_029)
    parser.add_argument(
        "--worker",
        choices=("interruptible", "sigkill"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-frames", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--worker-shard-max-frames", type=int, default=0, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--worker-ready-after", type=int, default=0, help=argparse.SUPPRESS
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.worker is not None:
        if args.worker_root is None:
            parser.error("worker mode requires --worker-root")
        return _worker(args.worker, args)
    if args.frames < 2 * args.shard_max_frames + 3:
        parser.error("--frames must be at least 2 * --shard-max-frames + 3")
    if args.shard_max_frames < 2:
        parser.error("--shard-max-frames must be at least 2")

    args.work_root.mkdir(parents=True, exist_ok=True)
    logs = args.output.parent / "scenario_logs"
    helpers: tuple[Callable[..., dict[str, Any]], ...] = (
        scenario_cancellation_restart,
        scenario_simulator_replacement,
        scenario_dependency_removal,
        scenario_disk_failure,
        scenario_resume,
    )
    records = [
        helper(
            args.work_root / helper.__name__.removeprefix("scenario_"),
            frame_count=args.frames,
            shard_max_frames=args.shard_max_frames,
            log_path=logs / f"{helper.__name__.removeprefix('scenario_')}.stdout.log",
            **({"seed": args.seed} if helper is scenario_cancellation_restart else {}),
        )
        for helper in helpers
    ]
    passed = all(record["status"] == "passed" for record in records)
    evidence = {
        "schema_version": "ias.s2_9_reliability_gate.v1",
        "status": "passed" if passed else "failed",
        "parameters": {
            "frames": args.frames,
            "shard_max_frames": args.shard_max_frames,
            "seed": args.seed,
        },
        "scenarios": records,
        "scenario_logs": str(logs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "scenarios": {
                    item["scenario"]: item["status"] for item in records
                },
                "evidence": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
