#!/usr/bin/env python3
"""Live Isaac Sim S2.9 endurance capture and bounded-resource gate."""

from __future__ import annotations

import argparse
import json
import math
import platform
import shutil
import sys
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from types import MethodType
from typing import Any

from isaac_audio_sensors.core.config import load_audio_config
from isaac_audio_sensors.core.dataset import (
    classify_session_lifecycle,
    validate_dataset,
)
from isaac_audio_sensors.core.types import RoomAcousticsSpec
from isaac_audio_sensors.isaac.extension_ui import CurrentStageContext
from isaac_audio_sensors.isaac.headless_workflow import HeadlessGuidedSession

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = REPO_ROOT / "configs/isaac_audio_sensors_demo.toml"
DEFAULT_OUT = REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.9/endurance_gate.json"
DEFAULT_SESSION = (
    REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.9/endurance_session"
)
RATIFIED_DEFINITION = (
    REPO_ROOT
    / "outputs/isaac_audio_sensors/S2/S2.9/ratified_capture_definition.json"
)
SAMPLE_PERIOD_S = 5.0
RSS_LIMIT_BYTES = 128 * 1024 * 1024
FD_LIMIT = 16
MIN_ACCEPTANCE_MINUTES = 30.0
SHARD_SIMULATED_SECONDS = 5 * 60


def _read_rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS is absent from /proc/self/status")


def _read_fd_count() -> int:
    return sum(1 for _ in Path("/proc/self/fd").iterdir())


class _TelemetryMonitor:
    """Frozen VmRSS/fd sampling with periodic and forced observations."""

    def __init__(self, period_s: float = SAMPLE_PERIOD_S) -> None:
        self.period_s = period_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._origin = time.monotonic()
        self._thread: threading.Thread | None = None
        self.samples: list[dict[str, Any]] = []

    def sample(self, reason: str) -> dict[str, Any]:
        row = {
            "elapsed_s": time.monotonic() - self._origin,
            "rss_bytes": _read_rss_bytes(),
            "fd_count": _read_fd_count(),
            "reason": reason,
        }
        with self._lock:
            self.samples.append(row)
        return row

    def baseline(self) -> tuple[float, float]:
        rows = [self.sample("baseline") for _ in range(3)]
        return (
            sum(row["rss_bytes"] for row in rows) / 3.0,
            sum(row["fd_count"] for row in rows) / 3.0,
        )

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="s2-9-endurance-telemetry",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.period_s):
            self.sample("periodic")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.sample("sampling_end")


def compute_shard_max_frames(update_period_s: float) -> int:
    """Return the nearest whole frame count for five simulated minutes."""

    if not math.isfinite(update_period_s) or update_period_s <= 0.0:
        raise ValueError("update_period_s must be positive and finite")
    frames = int(round(SHARD_SIMULATED_SECONDS / update_period_s))
    if frames <= 0:
        raise ValueError("computed shard_max_frames must be positive")
    return frames


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION)
    return parser


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_owned_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _select_backend() -> tuple[str, dict[str, Any] | None]:
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsBackend,
    )

    if RoomAcousticsBackend.is_available():
        return "room_acoustics", None
    return (
        "tdoa_synthetic",
        {
            "requested": "room_acoustics",
            "actual": "tdoa_synthetic",
            "reason": "pyroomacoustics is not importable on the Isaac runner",
        },
    )


def _bind_demo_room(controller: Any, config: Any) -> None:
    room = config.room
    if room is None:
        raise RuntimeError("demo config has no room definition")

    def room_from_demo(self: Any, _stage: Any) -> RoomAcousticsSpec:
        exact = RoomAcousticsSpec(
            room_id=room.room_id,
            dimensions_m=room.dimensions_m,
            absorption=room.absorption,
            max_order=room.max_order,
            origin_m=room.origin_m,
            out_of_bounds=room.out_of_bounds,
        )
        self.state.latest_room_summary = {
            "room_id": exact.room_id,
            "dimensions_m": exact.dimensions_m,
            "origin_m": exact.origin_m,
            "absorption": exact.absorption,
            "absorption_provenance": "configs/isaac_audio_sensors_demo.toml",
            "max_order": exact.max_order,
            "out_of_bounds": exact.out_of_bounds,
            "anchor_prim_path": exact.anchor_prim_path,
        }
        return exact

    controller._room_spec_or_none = MethodType(room_from_demo, controller)


def _author_demo_scene(controller: Any, stage: Any, config: Any, backend: str) -> None:
    if controller.guided_apply_preset("xvf3800_quad_demo") is None:
        raise RuntimeError("could not apply the demo XVF3800 guided preset")
    state = controller.state
    array = config.arrays["rig_front"]
    state.backend = backend
    state.array_prim_path = array.prim_path
    state.array_id = array.array_id
    state.layout_name = "quad_front"
    state.sample_rate_hz = config.sample_rate_hz
    state.coordinate_convention = array.coordinate_convention
    state.update_period_s = float(config.lab["update_period"])
    state.ambiguity_policy = config.tdoa_ambiguity_policy
    state.trace_enabled = False
    state.waveform_enabled = backend == "room_acoustics"
    state.waveform_mode = "per_frame"
    if controller.author_array(stage=stage) is None:
        raise RuntimeError("could not author the demo four-channel array")

    for source in config.sources:
        state.source_prim_path = source.prim_path
        state.source_id = source.source_id
        state.source_class_label = source.class_label
        state.audio_asset_path = str(source.audio_asset_path or "generated://impulse")
        state.source_position_x_m = float(source.position_world[0])
        state.source_position_y_m = float(source.position_world[1])
        state.source_position_z_m = float(source.position_world[2])
        state.source_start_time_s = source.start_time_s
        state.source_duration_s = float(source.duration_s or 1.0)
        state.source_gain_db = source.gain_db
        state.source_directivity = source.directivity
        if controller.author_source(stage=stage) is None:
            raise RuntimeError(f"could not author demo source {source.source_id}")

    first = config.sources[0]
    state.source_prim_path = first.prim_path
    state.source_id = first.source_id
    state.source_class_label = first.class_label
    state.audio_asset_path = str(first.audio_asset_path or "generated://impulse")
    state.source_position_x_m = float(first.position_world[0])
    state.source_position_y_m = float(first.position_world[1])
    state.source_position_z_m = float(first.position_world[2])
    state.source_start_time_s = first.start_time_s
    state.source_duration_s = float(first.duration_s or 1.0)
    state.source_gain_db = first.gain_db
    state.source_directivity = first.directivity
    if backend == "room_acoustics":
        _bind_demo_room(controller, config)


def _capture_at_sim_time(controller: Any, sim_time_s: float) -> Any:
    sensor = controller.sensor
    if sensor is None:
        raise RuntimeError("guided sensor is unavailable during endurance capture")
    frame = sensor.update(sim_time_s=sim_time_s, force=True)
    controller._record_latest_frame(frame)
    return frame


def _in_flight_proof(
    session_dir: Path,
    *,
    promoted_shards: int,
    writer_frames: int,
    shard_max_frames: int,
) -> dict[str, Any]:
    staging_root = session_dir / "_staging"
    staged_shards = sorted(
        path
        for path in staging_root.glob("shard_*")
        if path.is_dir()
    )
    expected_id = f"shard_{promoted_shards:05d}"
    expected = staging_root / expected_id
    files = {
        path.name: path.stat().st_size
        for path in sorted(expected.iterdir())
        if path.is_file()
    } if expected.is_dir() else {}
    in_flight_frames = writer_frames - promoted_shards * shard_max_frames
    proof = {
        "expected_shard_id": expected_id,
        "staged_shard_directories": [path.name for path in staged_shards],
        "staged_files_bytes": files,
        "in_flight_frame_count": in_flight_frames,
        "staging_marker_absent": not (expected / "shard.complete.json").exists(),
        "published_marker_absent": not (
            session_dir / "shards" / expected_id / "shard.complete.json"
        ).exists(),
    }
    proof["passed"] = (
        staged_shards == [expected]
        and files.get("audio.wav", 0) >= 44
        and files.get("frames.jsonl", 0) > 0
        and in_flight_frames > 0
        and proof["staging_marker_absent"]
        and proof["published_marker_absent"]
    )
    return proof


def _published_markers(session_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((session_dir / "shards").glob("*/shard.complete.json"))
    ]


def _telemetry_summary(
    monitor: _TelemetryMonitor,
    baseline_rss: float,
    baseline_fd: float,
) -> dict[str, Any]:
    samples = list(monitor.samples)
    peak_rss_delta = max(row["rss_bytes"] for row in samples) - baseline_rss
    peak_fd_delta = max(row["fd_count"] for row in samples) - baseline_fd
    rss_passed = peak_rss_delta <= RSS_LIMIT_BYTES
    fd_passed = peak_fd_delta <= FD_LIMIT
    return {
        "sampling_rule": {
            "source": "/proc/self/status VmRSS and /proc/self/fd",
            "period_seconds": SAMPLE_PERIOD_S,
            "forced_after_each_shard_promotion": True,
            "baseline_sample_count": 3,
            "baseline_timing": "after construction and before first recorded frame",
            "window_end": "after finalize_incomplete and before validation",
        },
        "baseline": {
            "rss_bytes_mean": baseline_rss,
            "fd_count_mean": baseline_fd,
        },
        "samples": samples,
        "peak_rss_delta_bytes": peak_rss_delta,
        "peak_fd_delta": peak_fd_delta,
        "frozen_limits": {
            "peak_rss_delta_bytes": RSS_LIMIT_BYTES,
            "peak_fd_delta": FD_LIMIT,
        },
        "limit_results": {
            "rss": "passed" if rss_passed else "failed",
            "fd": "passed" if fd_passed else "failed",
        },
        "status": "passed" if rss_passed and fd_passed else "failed",
    }


def _accounting(
    *,
    recording: dict[str, Any],
    markers: list[dict[str, Any]],
    validator: dict[str, Any],
    in_flight_frames: int,
    attempted_frames: int,
) -> dict[str, Any]:
    published_frames = sum(int(marker["frame_count"]) for marker in markers)
    marker_drops = sum(
        int(marker["dropped_frames"]["count"]) for marker in markers
    )
    validator_frames = int(validator["statistics"]["counts"]["frames"])
    validator_drops = int(validator["statistics"]["dropped_frames"]["total"])
    accepted_frames = int(recording["frames"])
    writer_drops = int(recording["dropped_frames"])
    unreported = attempted_frames - accepted_frames - writer_drops
    passed = (
        published_frames == validator_frames
        and marker_drops == validator_drops == writer_drops
        and accepted_frames == published_frames + in_flight_frames
        and attempted_frames == accepted_frames + writer_drops
        and unreported == 0
    )
    return {
        "producer_attempted_frames": attempted_frames,
        "writer_accepted_frames": accepted_frames,
        "writer_published_frames": published_frames,
        "deliberately_abandoned_in_flight_frames": in_flight_frames,
        "validator_published_frames": validator_frames,
        "writer_dropped_frames": writer_drops,
        "marker_dropped_frames": marker_drops,
        "validator_dropped_frames": validator_drops,
        "unreported_frames": unreported,
        "status": "passed" if passed else "failed",
    }


def _run_live(args: argparse.Namespace, evidence: dict[str, Any]) -> int:
    from isaac_audio_sensors_omni import Extension
    from live_isaac_sim_audio_smoke import (
        _ensure_isaac_runtime,
        _record_gpu_preflight,
        _record_isaacsim_preflight,
        _record_loaded_runtime_modules,
        _record_nvidia_smi,
        _update_kit_once,
    )
    from live_omniverse_extension_ux import (
        EXTENSION_ID,
        _author_minimal_stage,
        _create_stage,
        _enabled_extension_id,
        _try_enable_extension_manager,
    )

    simulation_app = None
    extension: Any | None = None
    monitor: _TelemetryMonitor | None = None
    exit_code = 0
    try:
        _record_isaacsim_preflight(evidence)
        _record_gpu_preflight(evidence)
        _record_nvidia_smi(evidence)
        simulation_app = _ensure_isaac_runtime(evidence)
        import omni  # type: ignore
        from pxr import Usd  # type: ignore

        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        _record_loaded_runtime_modules(evidence)
        evidence["kit_extension_manager"] = _try_enable_extension_manager(
            extension_id=EXTENSION_ID,
            extension_path=REPO_ROOT / "exts" / EXTENSION_ID,
        )
        stage, stage_mode = _create_stage(evidence)
        if stage is None:
            stage = Usd.Stage.CreateInMemory("s2_9_endurance_gate.usda")
            stage_mode = "pxr_usd_in_memory_fallback"
        evidence["stage_mode"] = stage_mode
        _author_minimal_stage(stage)
        _update_kit_once(evidence)

        config = load_audio_config(DEMO_CONFIG)
        update_period_s = float(config.lab["update_period"])
        shard_max_frames = compute_shard_max_frames(update_period_s)
        backend, substitution = _select_backend()
        evidence["capture_definition"].update(
            {
                "actual_backend": backend,
                "update_period_s": update_period_s,
                "shard_max_frames": shard_max_frames,
                "shard_max_frames_computation": (
                    f"round({SHARD_SIMULATED_SECONDS} / {update_period_s}) "
                    f"= {shard_max_frames}"
                ),
                "configured_source_count": len(config.sources),
                "configured_source_ids": [item.source_id for item in config.sources],
            }
        )
        if substitution is not None:
            evidence["backend_substitution"] = substitution

        extension = Extension()
        extension.on_startup(_enabled_extension_id(evidence) or EXTENSION_ID)
        controller = extension.controller
        controller.stage_context_provider = lambda: CurrentStageContext(stage, ())
        _author_demo_scene(controller, stage, config, backend)
        controller.state.guided_dataset_id = "s2_9_endurance_capture"
        controller.state.guided_shard_max_frames = shard_max_frames
        controller.state.guided_record_aligned = False
        controller.state.guided_scene_id = config.scene_id
        controller.state.guided_environment_id = "isaac_sim_headless"
        controller.state.guided_split_group = config.scene_id
        controller.state.guided_session_seed = 2_026_071_700
        controller.state.waveform_dir = str(args.out.parent / "endurance_waveforms")

        if not controller.guided_advance():
            raise RuntimeError("Setup could not advance to Validate")
        validation = controller.guided_validate()
        if not validation.ok:
            raise RuntimeError(f"guided Validate failed: {validation}")
        if controller.guided_start_run() is None:
            raise RuntimeError("guided Run could not start")
        headless = HeadlessGuidedSession(
            controller=controller,
            frame_stepper=lambda item, index: _capture_at_sim_time(
                item, index * update_period_s
            ),
        )
        first = headless.frame_stepper(controller, 0)
        if first is None:
            raise RuntimeError("guided Run produced no first frame")
        if not controller.guided_advance() or not controller.guided_mark_inspected():
            raise RuntimeError("guided Inspect could not complete")
        if not controller.guided_advance():
            raise RuntimeError("guided workflow could not enter Record")
        if controller.guided_start_recording(
            args.session_dir,
            controller.state.guided_dataset_id,
            shard_max_frames,
            False,
            scene_id=config.scene_id,
            environment_id="isaac_sim_headless",
            split_group=config.scene_id,
            session_seed=controller.state.guided_session_seed,
        ) is None:
            raise RuntimeError("guided Record could not start")

        monitor = _TelemetryMonitor()
        baseline_rss, baseline_fd = monitor.baseline()
        monitor.start()
        wall_target_s = args.minutes * 60.0
        capture_start = time.monotonic()
        frame_count = 0
        forced_promotions = 0
        previous_id: str | None = None
        previous_timestamp: int | None = None
        stale_frames = 0
        non_monotonic_frames = 0
        while True:
            due = capture_start + frame_count * update_period_s
            remaining = due - time.monotonic()
            if remaining > 0.0:
                time.sleep(remaining)
            if frame_count > 0 and time.monotonic() - capture_start >= wall_target_s:
                break
            frame = headless.frame_stepper(controller, frame_count + 1)
            frame_count += 1
            frame_id = str(frame.frame_id)
            timestamp = int(frame.timestamp_ms)
            stale_frames += int(frame_id == previous_id)
            non_monotonic_frames += int(
                previous_timestamp is not None and timestamp <= previous_timestamp
            )
            previous_id = frame_id
            previous_timestamp = timestamp
            promotions = len(controller.guided_recording_promotions)
            while forced_promotions < promotions:
                forced_promotions += 1
                monitor.sample(f"shard_promotion:{forced_promotions - 1}")

        recording = asdict(controller.guided_recording_status)
        if int(recording["frames"]) % shard_max_frames == 0:
            frame = headless.frame_stepper(controller, frame_count + 1)
            frame_count += 1
            stale_frames += int(str(frame.frame_id) == previous_id)
            non_monotonic_frames += int(
                previous_timestamp is not None
                and int(frame.timestamp_ms) <= previous_timestamp
            )
            promotions = len(controller.guided_recording_promotions)
            while forced_promotions < promotions:
                forced_promotions += 1
                monitor.sample(f"shard_promotion:{forced_promotions - 1}")
            recording = asdict(controller.guided_recording_status)
        wall_duration_s = time.monotonic() - capture_start
        monitor.sample("capture_end")
        promoted = len(controller.guided_recording_promotions)
        in_flight = _in_flight_proof(
            args.session_dir,
            promoted_shards=promoted,
            writer_frames=int(recording["frames"]),
            shard_max_frames=shard_max_frames,
        )
        if controller.guided_cancel_recording() is None:
            raise RuntimeError("finalize_incomplete returned no manifest")
        monitor.sample("finalize_incomplete")
        monitor.stop()
        telemetry = _telemetry_summary(monitor, baseline_rss, baseline_fd)
        monitor = None

        lifecycle = classify_session_lifecycle(args.session_dir)
        report = validate_dataset(args.session_dir, allow_incomplete=True)
        validator = report.to_dict()
        markers = _published_markers(args.session_dir)
        accounting = _accounting(
            recording=recording,
            markers=markers,
            validator=validator,
            in_flight_frames=int(in_flight["in_flight_frame_count"]),
            attempted_frames=frame_count,
        )
        duration_passed = wall_duration_s >= wall_target_s
        acceptance = evidence["run_kind"] == "acceptance"
        shard_count_passed = len(markers) >= 5 if acceptance else True
        validator_passed = (
            report.status == "passed"
            and report.error_count == 0
            and lifecycle == "finalized-incomplete"
        )
        stale_passed = stale_frames == 0 and non_monotonic_frames == 0
        passed = all(
            (
                duration_passed,
                shard_count_passed,
                bool(in_flight["passed"]),
                telemetry["status"] == "passed",
                validator_passed,
                accounting["status"] == "passed",
                stale_passed,
            )
        )
        evidence.update(
            {
                "duration": {
                    "requested_minutes": args.minutes,
                    "required_wall_seconds": wall_target_s,
                    "observed_wall_seconds": wall_duration_s,
                    "simulated_seconds": frame_count * update_period_s,
                    "status": "passed" if duration_passed else "failed",
                },
                "shards_published": len(markers),
                "published_shard_requirement": {
                    "minimum": 5,
                    "applies": acceptance,
                    "status": "passed" if shard_count_passed else "failed",
                },
                "in_flight_proof": in_flight,
                "telemetry_summary": telemetry,
                "validator_summary": validator,
                "lifecycle_state": lifecycle,
                "accounting": accounting,
                "freshness": {
                    "stale_frame_count": stale_frames,
                    "non_monotonic_timestamp_count": non_monotonic_frames,
                    "status": "passed" if stale_passed else "failed",
                },
                "recording_stats_before_finalize_incomplete": recording,
                "status": "passed" if passed else "failed",
                "status_is_acceptance_evidence": acceptance and passed,
            }
        )
        exit_code = 0 if passed else 1
    except BaseException as exc:  # noqa: BLE001 - live evidence retains blockers.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "failed",
                "status_is_acceptance_evidence": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        if monitor is not None:
            monitor.stop()
            evidence["partial_telemetry_samples"] = list(monitor.samples)
        if extension is not None:
            try:
                extension.on_shutdown()
                evidence["extension_shutdown"] = "ok"
            except Exception as exc:  # noqa: BLE001 - shutdown is diagnostic.
                evidence["extension_shutdown_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        if simulation_app is not None:
            try:
                simulation_app.close()
                evidence["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown is diagnostic.
                evidence["simulation_app_close_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.minutes) or args.minutes <= 0.0:
        parser.error("--minutes must be positive and finite")
    run_kind = (
        "acceptance" if args.minutes >= MIN_ACCEPTANCE_MINUTES else "smoke"
    )
    args.out = args.out.expanduser().resolve()
    args.session_dir = args.session_dir.expanduser().resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _remove_owned_tree(args.session_dir)
    waveform_dir = args.out.parent / "endurance_waveforms"
    _remove_owned_tree(waveform_dir)
    if args.out.exists():
        args.out.unlink()
    ratified = json.loads(RATIFIED_DEFINITION.read_text(encoding="utf-8"))
    evidence: dict[str, Any] = {
        "schema_version": "ias.s2_9_endurance_gate.v1",
        "status": "started",
        "run_kind": run_kind,
        "status_is_acceptance_evidence": False,
        "argv": sys.argv if argv is None else [str(Path(__file__)), *argv],
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "headless": True,
        "evidence_path": str(args.out),
        "session_dir": str(args.session_dir),
        "ratified_definition_path": str(RATIFIED_DEFINITION),
        "ratified_definition": ratified,
        "capture_definition": {
            "scene_config": str(DEMO_CONFIG),
            "requested_backend": "room_acoustics",
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": 48_000,
            "dtype": "float32 WAV",
            "shard_episode_aligned": False,
            "shard_simulated_seconds": SHARD_SIMULATED_SECONDS,
            "telemetry_period_s": SAMPLE_PERIOD_S,
        },
    }
    return _run_live(args, evidence)


if __name__ == "__main__":
    raise SystemExit(main())
