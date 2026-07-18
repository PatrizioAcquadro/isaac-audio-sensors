#!/usr/bin/env python3
"""Run the live Isaac S3.2 pause/resume and piecewise-motion gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs/isaac_audio_sensors/S3/S3.2"
SUMMARY_NAME = "live_throttled_capture_summary.json"
FRAMES_NAME = "live_throttled_capture_frames.jsonl"
AUDIO_NAME = "live_throttled_capture_audio.wav"
LOG_NAME = "live_throttled_capture.log"
STAGE_NAME = "live_throttled_capture_stage.usda"
ENVIRONMENT_NAME = "live_time_motion_environment.json"

ARRAY_PRIM_PATH = "/World/AudioRig"
SOURCE_PRIM_PATH = "/World/ActiveSource"
ARRAY_ID = "s3_2_static_quad"
SOURCE_ID = "s3_2_continuous_source"
ARRAY_POSITION = (0.0, 0.0, 1.2)
SOURCE_STATIC_POSITION = (4.0, 0.0, 1.2)
SOURCE_MOTION_START = (4.0, -0.5, 1.2)
SOURCE_MOTION_END = (6.0, -0.5, 1.2)

SAMPLE_RATE_HZ = 48_000
CAPTURE_PERIOD_S = 0.05
WINDOW_SAMPLE_COUNT = 4_800
HOP_SAMPLE_COUNT = 2_400
WINDOW_DURATION_S = WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ
SEGMENTS_PER_WINDOW = 8
CAPTURE_STARTS_S = (0.0, 0.05, 0.45)
EXPECTED_GAP_SAMPLES = 16_800
EXPECTED_GAP_SPAN = (4_800, 21_600)
EXPECTED_RECORD_RANGES = ((0, 4_800), (2_400, 7_200), (21_600, 26_400))
EXPECTED_STREAM_SAMPLES = 26_400
TIMELINE_DRIFT_TOLERANCE_S = 0.1 * HOP_SAMPLE_COUNT / SAMPLE_RATE_HZ
CONTINUITY_BOUND = 2e-6
PHASE2_PRIME_TIME_S = 1.0
PHASE2_RENDER_TIME_S = PHASE2_PRIME_TIME_S + WINDOW_DURATION_S


class LivePrerequisiteError(RuntimeError):
    """A required live-runtime capability is unavailable."""

    def __init__(self, message: str, *, simulation_app: Any | None = None) -> None:
        super().__init__(message)
        self.simulation_app = simulation_app


class GateAssertionError(RuntimeError):
    """The live runtime ran, but an S3.2 assertion failed."""


class _CapturingWaveformSink:
    """Retain float64 backend mixtures while writing real per-frame WAVs."""

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self.mixtures: dict[str, Any] = {}

    def write_frame_mixture(self, **kwargs: Any) -> Any:
        import numpy as np

        frame_id = str(kwargs["frame_id"])
        self.mixtures[frame_id] = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        return self._writer.write_frame_mixture(**kwargs)

    def close(self) -> None:
        self._writer.close()


class _MemoryWaveformSink:
    """Capture one room mixture without creating another evidence file."""

    def __init__(self, result_type: Any) -> None:
        self._result_type = result_type
        self.mixture: Any | None = None

    def write_frame_mixture(self, **kwargs: Any) -> Any:
        import numpy as np

        self.mixture = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        return self._result_type(paths=())

    def close(self) -> None:
        return None


class _KitCaptureSubscription:
    """A pauseable Kit update subscription dedicated to sensor capture."""

    def __init__(
        self,
        app: Any,
        timeline: Any,
        callback: Callable[[float, float, int], None],
    ) -> None:
        self._stream = app.get_update_event_stream()
        self._timeline = timeline
        self._callback = callback
        self._subscription: Any | None = None
        self._armed_lattice_time_s: float | None = None
        self._tick: int | None = None
        self.callback_error: BaseException | None = None

    @property
    def active(self) -> bool:
        return self._subscription is not None

    def resume(self) -> None:
        if self._subscription is not None:
            return

        def _on_update(_event: Any) -> None:
            lattice_time_s = self._armed_lattice_time_s
            if lattice_time_s is None or self.callback_error is not None:
                return
            try:
                reported_time_s = _timeline_time(self._timeline)
                if reported_time_s < lattice_time_s - TIMELINE_DRIFT_TOLERANCE_S:
                    return
                if self._tick is None:
                    raise RuntimeError("capture subscription has no current Kit tick")
                self._armed_lattice_time_s = None
                self._callback(reported_time_s, lattice_time_s, self._tick)
            except BaseException as exc:  # noqa: BLE001 - surfaced after Kit tick.
                self.callback_error = exc

        self._subscription = self._stream.create_subscription_to_pop(
            _on_update,
            name="isaac_audio_sensors.s3_2_live_capture",
        )

    def pause(self) -> None:
        self._armed_lattice_time_s = None
        self._subscription = None

    def arm(self, lattice_time_s: float) -> None:
        if self._subscription is None:
            raise RuntimeError("capture subscription is paused")
        if self._armed_lattice_time_s is not None:
            raise RuntimeError("capture subscription already has an armed tick")
        self._armed_lattice_time_s = float(lattice_time_s)

    def set_tick(self, tick: int) -> None:
        self._tick = tick

    @property
    def armed_lattice_time_s(self) -> float | None:
        return self._armed_lattice_time_s


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the S3.2 live Kit pause/resume time-gap gate."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the six spec-named live evidence artifacts.",
    )
    args = parser.parse_args()

    paths = _artifact_paths(args.out_dir)
    _initialize_artifacts(paths)
    environment = _initial_environment()
    summary: dict[str, Any] = {
        "status": "started",
        "scenario": "S3.2_live_kit_pause_resume_time_gaps",
        "spec": "docs/development/specs/s3_motion_policies.md sections 11-12.1",
        "headless": True,
        "output_directory": str(args.out_dir),
        "artifacts": {name: str(path) for name, path in paths.items()},
        "source_id": SOURCE_ID,
        "array_id": ARRAY_ID,
        "backend": "room_acoustics",
        "normalized_configuration": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "capture_period_s": CAPTURE_PERIOD_S,
            "window_sample_count": WINDOW_SAMPLE_COUNT,
            "hop_sample_count": HOP_SAMPLE_COUNT,
            "preserve_time_gaps": True,
            "waveform_mode": "per_frame",
            "phase2_segments_per_window": SEGMENTS_PER_WINDOW,
        },
        "frozen_expectations": {
            "capture_starts_s": list(CAPTURE_STARTS_S),
            "inserted_gap_samples": EXPECTED_GAP_SAMPLES,
            "gap_span": list(EXPECTED_GAP_SPAN),
            "record_ranges": [list(item) for item in EXPECTED_RECORD_RANGES],
            "stream_sample_count": EXPECTED_STREAM_SAMPLES,
            "continuity_bound_full_scale": CONTINUITY_BOUND,
        },
    }
    _write_json(paths["environment"], environment)
    _log(paths["log"], "gate_started", argv=sys.argv)

    simulation_app = None
    phase1_sensor = None
    phase2_sensor = None
    stage = None
    timeline = None
    subscription = None
    exit_code = 2
    try:
        _record_isaacsim_preflight(environment)
        _record_gpu(environment)
        _record_nvidia_smi(environment)
        _write_json(paths["environment"], environment)

        simulation_app = _ensure_isaac_runtime(environment)
        dependencies = _load_live_dependencies()
        _record_loaded_runtime(environment, dependencies)
        _record_gpu(environment)
        _validate_runtime(environment)
        _require_room_backend(dependencies)
        app, timeline = _require_timeline(dependencies)
        _write_json(paths["environment"], environment)

        stage = dependencies["Usd"].Stage.CreateInMemory(STAGE_NAME)
        source_prim = _author_stage(stage, dependencies)
        _export_stage(stage, paths["stage"])
        _log(paths["log"], "stage_authored", stage_path=str(paths["stage"]))

        with tempfile.TemporaryDirectory(prefix="ias_s3_2_live_") as directory:
            temporary_root = Path(directory)
            phase1 = _run_pause_resume_phase(
                stage=stage,
                source_prim=source_prim,
                app=app,
                timeline=timeline,
                temporary_root=temporary_root,
                paths=paths,
                dependencies=dependencies,
            )
            phase1_sensor = phase1.pop("sensor")
            subscription = phase1.pop("subscription")
            summary["phase1_pause_resume"] = phase1

            phase1_sensor.close()
            phase1_sensor = None
            subscription.pause()
            subscription = None

            phase2 = _run_piecewise_motion_phase(
                stage=stage,
                source_prim=source_prim,
                app=app,
                timeline=timeline,
                temporary_root=temporary_root,
                paths=paths,
                dependencies=dependencies,
            )
            phase2_sensor = phase2.pop("sensor")
            summary["phase2_piecewise_motion"] = phase2

        assertions = {
            "headless_kit": True,
            "one_continuously_active_source": True,
            "static_four_microphone_array": True,
            "capture_period_exactly_0_05_s": True,
            "independent_w4800_h2400": True,
            "capture_subscription_paused_while_timeline_continued": True,
            "capture_starts_within_frozen_drift_tolerance": True,
            "every_recorder_block_shape_4_by_4800_float32": True,
            "inserted_zero_input_samples_exactly_16800": True,
            "record_ranges_and_stream_length_exact": True,
            "carried_rir_tail_bit_exact_and_decaying": True,
            "post_tail_gap_exact_zero": True,
            "no_duplicate_frame": True,
            "published_shards_validator_clean": True,
            "phase2_pose_history_brackets_full_window": True,
            "phase2_segment_poses_and_factors_finite": True,
            "phase2_continuity_residual_within_2e_6": True,
        }
        _require(len(assertions) == 17, "internal assertion inventory changed")
        summary.update(
            {
                "status": "passed",
                "assertions": assertions,
                "assertion_count": len(assertions),
            }
        )
        exit_code = 0
        _export_stage(stage, paths["stage"])
        _log(paths["log"], "gate_passed", assertions=assertions)
    except BaseException as exc:  # noqa: BLE001 - exact gate evidence.
        if simulation_app is None and isinstance(exc, LivePrerequisiteError):
            simulation_app = exc.simulation_app
        status = "blocked" if isinstance(exc, LivePrerequisiteError) else "failed"
        summary.update(
            {
                "status": status,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "smallest_next_fix": _smallest_next_fix(exc),
            }
        )
        _log(
            paths["log"],
            "gate_not_passed",
            status=status,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
    finally:
        if subscription is not None:
            with suppress(Exception):
                subscription.pause()
        for sensor in (phase2_sensor, phase1_sensor):
            if sensor is not None:
                with suppress(Exception):
                    sensor.close()
        if timeline is not None:
            with suppress(Exception):
                timeline.pause()
        if stage is not None:
            try:
                _export_stage(stage, paths["stage"])
            except Exception as exc:  # noqa: BLE001 - best-effort failure artifact.
                summary["stage_export_close_error"] = f"{type(exc).__name__}: {exc}"

        environment["status"] = "recorded"
        environment["recorded_at_utc"] = _utc_now()
        if simulation_app is not None:
            environment["simulation_app_closed"] = False
        _write_json(paths["environment"], environment)
        summary["artifact_inventory"] = _artifact_inventory(paths, omit="summary")
        # The environment and verdict are durable before Kit teardown. A
        # crashing SimulationApp.close() therefore cannot erase the evidence.
        _write_json(paths["summary"], summary)
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        sys.stdout.flush()

        if simulation_app is not None:
            try:
                simulation_app.close()
                environment["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown evidence only.
                environment["simulation_app_close_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            with suppress(Exception):
                environment["recorded_at_utc"] = _utc_now()
                _write_json(paths["environment"], environment)
                summary["artifact_inventory"] = _artifact_inventory(
                    paths, omit="summary"
                )
                _write_json(paths["summary"], summary)

    return exit_code


def _run_pause_resume_phase(
    *,
    stage: Any,
    source_prim: Any,
    app: Any,
    timeline: Any,
    temporary_root: Path,
    paths: dict[str, Path],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    _set_source_pose_both_representations(
        source_prim, SOURCE_STATIC_POSITION, dependencies
    )
    timeline.pause()
    _set_timeline_time(timeline, 0.0)
    _update_kit_once(app)
    reset_reported_time_s = _timeline_time(timeline)
    _log(
        paths["log"],
        "phase1_timeline_reset",
        set_time_s=0.0,
        reported_time_s=reset_reported_time_s,
        tick=-1,
    )

    waveform_dir = temporary_root / "phase1_waveforms"
    sensor = (
        dependencies["IsaacAudioArraySensor"]
        .from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            source_prim_path=SOURCE_PRIM_PATH,
            backend="room_acoustics",
            update_period_s=CAPTURE_PERIOD_S,
            max_events=1,
            room=_room_spec(dependencies),
            waveform_dir=waveform_dir,
            waveform_mode="per_frame",
        )
        .start()
    )
    sink = _CapturingWaveformSink(dependencies["FrameWaveformWriter"](waveform_dir))
    sensor._waveform_sink = sink  # noqa: SLF001 - retain live float64 reference.

    session_root = temporary_root / "phase1_session"
    recorder = dependencies["SessionRecorder"](
        session_root,
        {
            "backend_id": "room_acoustics",
            "channel_order": [
                microphone.mic_id
                for microphone in dependencies["microphone_layout"]("quad_front")
            ],
            "dataset_id": "s3_2_live_throttled_capture",
            "dtype": "float32",
            "hop_sample_count": HOP_SAMPLE_COUNT,
            "preserve_time_gaps": True,
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "session_seed": 32,
            "shard_episode_aligned": False,
            "shard_max_frames": 100,
            "split_grouping_key": "scene_id",
            "window_sample_count": WINDOW_SAMPLE_COUNT,
        },
        creation=dependencies["CreationProvenance"](
            tool_name="run_s3_2_live_time_gaps",
            tool_version=dependencies["__version__"],
            backend_id="room_acoustics",
            estimator_id="tdoa_least_squares",
        ),
        device=dependencies["DeviceProvenance"](
            device_id="isaac_sim_headless",
            device_type="simulator",
            platform=sys.platform,
            compute_device="cuda",
        ),
        license="CC0-1.0",
        source="S3.2 live Kit pause/resume gate",
        coordinate_frames=("world", "array"),
        time_base="simulation_time",
    )
    recorder.begin_episode("s3_2_live", "kit_headless", "s3_2_live", seed=32)

    captured_frames: list[Any] = []
    recorder_blocks: list[Any] = []
    capture_events: list[dict[str, Any]] = []

    def _capture(
        reported_time_s: float, lattice_time_s: float, timeline_tick: int
    ) -> None:
        index = len(captured_frames)
        frame = sensor.capture(
            timestamp_ms=round(reported_time_s * 1000.0),
            start_time_s=reported_time_s,
            end_time_s=reported_time_s + WINDOW_DURATION_S,
            frame_index=index,
            max_events=1,
            usd_time_code=dependencies["Usd"].TimeCode.Default(),
            sim_time_s=reported_time_s,
        )
        scene = sensor._latest_scene  # noqa: SLF001 - live gate scene evidence.
        _require(scene is not None, f"capture {index} did not retain a live scene")
        array = scene.array_by_id(ARRAY_ID)
        _require(
            len(array.microphones) == 4
            and list(array.position_world) == list(ARRAY_POSITION),
            f"capture {index} array is not the static authored quad",
        )
        _require(
            frame.diagnostics.get("active_source_count") == 1
            and len(frame.detections) == 1
            and frame.detections[0].source_id == SOURCE_ID,
            f"capture {index} does not contain the one continuous source",
        )
        block = _guided_audio_block(frame, dependencies)
        _require(
            block.dtype == np.float32
            and block.shape == (4, WINDOW_SAMPLE_COUNT)
            and np.isfinite(block).all(),
            f"recorder block {index} has invalid dtype/shape/values: "
            f"{block.dtype} {block.shape}",
        )
        recording_frame = dependencies["replace"](frame, waveform_paths=())
        gap_diagnostic = recorder.plan_time_gap(recording_frame)
        diagnostics = dict(recording_frame.diagnostics)
        recording = dict(diagnostics.get("recording", {}))
        recording["time_gap"] = gap_diagnostic
        diagnostics["recording"] = recording
        diagnostics["s3_2_live"] = {
            "capture_subscription": "active",
            "capture_lattice_time_s": lattice_time_s,
            "capture_reported_time_s": reported_time_s,
            "capture_timeline_tick": timeline_tick,
            "capture_start_time_s": reported_time_s,
            "window_sample_count": WINDOW_SAMPLE_COUNT,
            "hop_sample_count": HOP_SAMPLE_COUNT,
            "audio_block_sha256": _array_sha256(block),
        }
        recording_frame = dependencies["replace"](
            recording_frame, diagnostics=diagnostics
        )
        result = recorder.append_frame(
            recording_frame,
            block,
            recording_frame.timestamp_ms,
            is_reset=index == 0,
        )
        _require(result.accepted, f"recorder rejected frame {index}: {result.reason}")
        captured_frames.append(recording_frame)
        recorder_blocks.append(block.copy())
        event = {
            "capture_index": index,
            "capture_lattice_time_s": lattice_time_s,
            "capture_reported_time_s": reported_time_s,
            "capture_timeline_tick": timeline_tick,
            "capture_start_time_s": reported_time_s,
            "capture_end_time_s": reported_time_s + WINDOW_DURATION_S,
            "frame_id": recording_frame.frame_id,
            "dataset_frame_index": result.dataset_frame_index,
            "gap_diagnostic": gap_diagnostic,
        }
        capture_events.append(event)
        _log(paths["log"], "phase1_frame_recorded", **event)

    subscription = _KitCaptureSubscription(app, timeline, _capture)
    subscription.resume()
    timeline_ticks: list[dict[str, Any]] = []
    subscription.arm(CAPTURE_STARTS_S[0])
    for tick in range(120):
        if tick == 1:
            timeline.play()
            subscription.arm(CAPTURE_STARTS_S[1])
        subscription.set_tick(tick)
        set_time_s = subscription.armed_lattice_time_s
        before = _timeline_time(timeline)
        active_during_update = subscription.active
        _update_kit_once(app)
        after = _timeline_time(timeline)
        if subscription.callback_error is not None:
            raise subscription.callback_error
        tick_evidence = {
            "tick": tick,
            "set_time_s": set_time_s,
            "reported_before_update_time_s": before,
            "reported_time_s": after,
            "capture_subscription_active": active_during_update,
        }
        timeline_ticks.append(tick_evidence)
        _log(paths["log"], "phase1_timeline_tick", **tick_evidence)

        if len(captured_frames) == 2 and subscription.active:
            subscription.pause()
            _log(
                paths["log"],
                "capture_subscription_paused",
                set_time_s=CAPTURE_STARTS_S[1],
                reported_time_s=after,
                tick=tick,
            )
        resume_time_s = CAPTURE_STARTS_S[2] - CAPTURE_PERIOD_S
        if (
            len(captured_frames) == 2
            and not subscription.active
            and after >= resume_time_s - TIMELINE_DRIFT_TOLERANCE_S
        ):
            _require(
                after < CAPTURE_STARTS_S[2],
                f"capture subscription did not resume before {CAPTURE_STARTS_S[2]}",
            )
            subscription.resume()
            subscription.arm(CAPTURE_STARTS_S[2])
            _log(
                paths["log"],
                "capture_subscription_resumed",
                set_time_s=CAPTURE_STARTS_S[2],
                reported_time_s=after,
                tick=tick,
            )
        if len(captured_frames) == len(CAPTURE_STARTS_S):
            break
    subscription.pause()
    timeline.pause()

    _require(
        len(captured_frames) == 3 and len(recorder_blocks) == 3,
        "capture subscription did not produce exactly three unique windows",
    )
    capture_times_s = [frame.start_time_s for frame in captured_frames]
    _require(
        all(
            abs(reported_time_s - lattice_time_s)
            <= TIMELINE_DRIFT_TOLERANCE_S
            for reported_time_s, lattice_time_s in zip(
                capture_times_s, CAPTURE_STARTS_S, strict=True
            )
        ),
        "captured frame starts exceed the frozen 0.1-hop drift tolerance: "
        f"{capture_times_s!r}",
    )
    _require(
        any(
            not tick["capture_subscription_active"]
            and tick["reported_time_s"] > capture_times_s[1]
            and tick["reported_time_s"] < CAPTURE_STARTS_S[2] - CAPTURE_PERIOD_S
            for tick in timeline_ticks
        ),
        "capture subscription was not paused while the timeline advanced",
    )
    _require(
        all(
            later["reported_time_s"] >= earlier["reported_time_s"]
            for earlier, later in zip(
                timeline_ticks, timeline_ticks[1:], strict=False
            )
        )
        and timeline_ticks[-1]["reported_time_s"]
        >= CAPTURE_STARTS_S[-1] - TIMELINE_DRIFT_TOLERANCE_S,
        "Kit timeline did not advance monotonically through the final crossing",
    )

    counters = recorder.time_gap_summary
    recorder.end_episode()
    recorder.finalize()
    validator_report = dependencies["validate_dataset"](session_root)
    # Live Isaac scenes emit warning-only diagnostics findings by the frozen
    # layout contract; clean means zero ERROR findings (S2.9 precedent).
    validator_error_count = sum(
        1
        for finding in validator_report.findings
        if getattr(finding, "severity", "error") == "error"
    )
    _require(
        validator_report.status in ("passed", "passed_with_warnings")
        and validator_error_count == 0,
        f"canonical dataset validator returned {validator_report.status!r} "
        f"with {validator_error_count} error findings",
    )
    _require(recorder.promoted_shard_count == 1, "session did not publish one shard")

    shard = session_root / "shards/shard_00000"
    _copy_fsync(shard / "frames.jsonl", paths["frames"])
    _copy_fsync(shard / "audio.wav", paths["audio"])
    records = [
        json.loads(line)
        for line in paths["frames"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    audio = dependencies["read_wav"](paths["audio"])
    samples = audio.samples
    ranges = [
        (record["audio_start_sample"], record["audio_end_sample"]) for record in records
    ]
    frame_ids = [record["frame"]["frame_id"] for record in records]

    _require(audio.sample_rate_hz == SAMPLE_RATE_HZ, "session WAV sample rate changed")
    _require(samples.shape == (4, EXPECTED_STREAM_SAMPLES), str(samples.shape))
    _require(ranges == list(EXPECTED_RECORD_RANGES), f"record ranges: {ranges!r}")
    _require(len(frame_ids) == len(set(frame_ids)) == 3, "duplicate frame published")
    _require(
        counters["inserted_silence_samples"] == EXPECTED_GAP_SAMPLES
        and counters["gap_event_count"] == 1,
        f"time-gap counters disagree: {counters!r}",
    )
    gap_diagnostics = [
        record["frame"]["diagnostics"]["recording"]["time_gap"] for record in records
    ]
    _require(
        [item["placement_sample"] for item in gap_diagnostics]
        == [0, HOP_SAMPLE_COUNT, EXPECTED_GAP_SPAN[1]],
        f"placement samples disagree: {gap_diagnostics!r}",
    )
    _require(
        gap_diagnostics[-1]["expected_start_time_s"] == 0.1
        and gap_diagnostics[-1]["delta_samples"] == EXPECTED_GAP_SAMPLES
        and gap_diagnostics[-1]["inserted_silence_samples"] == EXPECTED_GAP_SAMPLES,
        f"resumed gap diagnostic disagrees: {gap_diagnostics[-1]!r}",
    )

    carry = recorder_blocks[1][:, HOP_SAMPLE_COUNT:WINDOW_SAMPLE_COUNT]
    support = np.flatnonzero(np.any(carry != np.float32(0.0), axis=0))
    _require(support.size > 0, "second block recorder carry is empty")
    support_length = int(support[-1]) + 1
    _require(
        4 <= support_length <= HOP_SAMPLE_COUNT,
        f"carry support length is {support_length}",
    )
    _require(np.any(carry[:, 0] != 0.0), "carry begins with an all-zero vector")
    quarter = support_length // 4
    early_rms = float(np.sqrt(np.mean(carry[:, :quarter].astype(float) ** 2)))
    late_rms = float(
        np.sqrt(
            np.mean(
                carry[:, support_length - quarter : support_length].astype(float) ** 2
            )
        )
    )
    _require(
        math.isfinite(early_rms)
        and math.isfinite(late_rms)
        and early_rms > 0.0
        and late_rms > 0.0
        and late_rms < early_rms,
        f"carry is not a finite decaying RIR tail: early={early_rms}, late={late_rms}",
    )
    gap_start, gap_end = EXPECTED_GAP_SPAN
    _require(
        np.array_equal(
            samples[:, gap_start : gap_start + support_length],
            carry[:, :support_length],
        ),
        "decoded gap head is not bit-exact recorder carry",
    )
    _require(
        np.all(samples[:, gap_start + support_length : gap_end] == 0.0),
        "post-tail zero-input gap contains a nonzero sample",
    )
    _require(
        not _contains_nonfinite(records),
        "published live recorder trace contains NaN or infinity",
    )

    return {
        "sensor": sensor,
        "subscription": subscription,
        "capture_events": capture_events,
        "capture_starts_s": capture_times_s,
        "capture_lattice_drift_tolerance_s": TIMELINE_DRIFT_TOLERANCE_S,
        "timeline_tick_count": len(timeline_ticks),
        "timeline_requested_span_s": [CAPTURE_STARTS_S[0], CAPTURE_STARTS_S[-1]],
        "timeline_reported_span_s": [
            timeline_ticks[0]["reported_time_s"],
            timeline_ticks[-1]["reported_time_s"],
        ],
        "subscription_paused_interval_s": [0.05, 0.45],
        "simulation_time_paused": False,
        "recorder_block_shapes": [list(block.shape) for block in recorder_blocks],
        "recorder_block_dtypes": [str(block.dtype) for block in recorder_blocks],
        "time_gap_summary": counters,
        "gap_diagnostics": gap_diagnostics,
        "record_ranges": [list(item) for item in ranges],
        "stream_sample_count": int(samples.shape[1]),
        "audio_sha256": _file_sha256_or_unavailable(paths["audio"]),
        "carry": {
            "support_length_samples": support_length,
            "first_sample_vector": carry[:, 0].tolist(),
            "early_quarter_rms": early_rms,
            "late_quarter_rms": late_rms,
            "float32_sha256": _array_sha256(carry),
            "gap_head_bit_exact": True,
            "post_tail_exact_zero": True,
        },
        "duplicate_frame_count": len(frame_ids) - len(set(frame_ids)),
        "published_shard_count": recorder.promoted_shard_count,
        "validator_status": validator_report.status,
        "validator_findings": [
            {
                "code": finding.code,
                "severity": finding.severity,
                "location": finding.location,
                "detail": finding.detail,
            }
            for finding in validator_report.findings
        ],
    }


def _run_piecewise_motion_phase(
    *,
    stage: Any,
    source_prim: Any,
    app: Any,
    timeline: Any,
    temporary_root: Path,
    paths: dict[str, Path],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    waveform_dir = temporary_root / "phase2_waveforms"
    _set_source_pose_both_representations(
        source_prim, SOURCE_MOTION_START, dependencies
    )
    _set_timeline_time(timeline, PHASE2_PRIME_TIME_S)
    _update_kit_once(app)

    effects = dependencies["EffectsConfig"](
        motion=dependencies["MotionEffectsConfig"](
            derive_velocity_from_poses=True,
            segments_per_window=SEGMENTS_PER_WINDOW,
        )
    )
    sensor = (
        dependencies["IsaacAudioArraySensor"]
        .from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            source_prim_path=SOURCE_PRIM_PATH,
            backend="room_acoustics",
            update_period_s=WINDOW_DURATION_S,
            max_events=1,
            room=_room_spec(dependencies),
            waveform_dir=waveform_dir,
            waveform_mode="per_frame",
            effects=effects,
        )
        .start()
    )
    sink = _CapturingWaveformSink(dependencies["FrameWaveformWriter"](waveform_dir))
    sensor._waveform_sink = sink  # noqa: SLF001 - live reference before f32 export.

    _set_source_pose_both_representations(source_prim, SOURCE_MOTION_END, dependencies)
    _set_timeline_time(timeline, PHASE2_RENDER_TIME_S)
    _update_kit_once(app)
    _require(
        sensor._last_update_time_s == PHASE2_PRIME_TIME_S,  # noqa: SLF001
        "phase-2 pose history mutated between its prime and rendered update",
    )
    frame = sensor.update(
        sim_time_s=PHASE2_RENDER_TIME_S,
        timestamp_ms=round(PHASE2_PRIME_TIME_S * 1000.0),
        usd_time_code=dependencies["Usd"].TimeCode.Default(),
        force=True,
    )
    trace = dependencies["frame_to_trace_dict"](frame)
    _require(not _contains_nonfinite(trace), "phase-2 frame has NaN or infinity")
    _require(
        frame.start_time_s == PHASE2_PRIME_TIME_S
        and frame.end_time_s == PHASE2_RENDER_TIME_S,
        f"phase-2 window is [{frame.start_time_s}, {frame.end_time_s})",
    )

    motion = frame.diagnostics.get("motion", {})
    rows = motion.get("segments", [])
    _require(
        motion.get("segments_per_window") == SEGMENTS_PER_WINDOW
        and len(rows) == SEGMENTS_PER_WINDOW,
        "phase-2 frame did not retain eight segment diagnostics",
    )
    expected_boundaries = list(range(0, WINDOW_SAMPLE_COUNT + 1, 600))
    _require(
        [row["start_sample"] for row in rows] == expected_boundaries[:-1]
        and [row["end_sample"] for row in rows] == expected_boundaries[1:],
        "phase-2 segment boundaries do not account for exactly W samples",
    )
    _require(
        all(_finite_segment_row(row) for row in rows),
        "phase-2 segment pose/factor diagnostic is non-finite",
    )
    first_source = rows[0]["entities"][SOURCE_ID]
    last_source = rows[-1]["entities"][SOURCE_ID]
    _require(
        list(first_source["start_position_world_m"]) == list(SOURCE_MOTION_START)
        and list(last_source["end_position_world_m"]) == list(SOURCE_MOTION_END),
        "phase-2 pose history does not bracket the complete rendered window",
    )
    _require(
        all(row["entities"][SOURCE_ID]["velocity_source"] == "derived" for row in rows),
        "phase-2 source motion was not continuously derived",
    )
    _require(
        frame.diagnostics.get("active_source_count") == 1
        and len(frame.detections) == 1
        and frame.detections[0].source_id == SOURCE_ID,
        "phase-2 frame does not contain the one continuous source",
    )
    _require(
        all(
            list(row["entities"][ARRAY_ID][position_name]) == list(ARRAY_POSITION)
            for row in rows
            for position_name in (
                "start_position_world_m",
                "mid_position_world_m",
                "end_position_world_m",
            )
        ),
        "phase-2 microphone array moved within the rendered window",
    )

    factors = tuple(float(row["doppler_factor_by_source"][SOURCE_ID]) for row in rows)
    lengths = tuple(int(row["end_sample"] - row["start_sample"]) for row in rows)
    scene = sensor._latest_scene  # noqa: SLF001 - retained live scene evidence.
    _require(scene is not None, "phase-2 live scene was not retained")
    source = next(item for item in scene.sources if item.source_id == SOURCE_ID)
    window = dependencies["AudioTimeWindow"](
        start_time_s=PHASE2_PRIME_TIME_S,
        end_time_s=PHASE2_RENDER_TIME_S,
        timestamp_ms=round(PHASE2_PRIME_TIME_S * 1000.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
        max_events=1,
    )
    scheduled = dependencies["_scheduled_window_signal"](source, time_window=window)
    observed_source = dependencies["_piecewise_phase_signal"](
        scheduled.signal,
        factors=factors,
        segment_lengths=lengths,
    )
    reference_source = _phase_cursor_reference(
        scheduled.signal, factors=factors, segment_lengths=lengths
    )
    continuity_rows = _boundary_residuals(
        "source", observed_source, reference_source, expected_boundaries[1:-1]
    )

    mixture = sink.mixtures.get(frame.frame_id)
    _require(mixture is not None, "phase-2 float64 backend mixture was not retained")
    decoded = dependencies["read_wav"](frame.waveform_paths[-1]).samples
    reference_sink = _MemoryWaveformSink(dependencies["WaveformWriteResult"])
    sensor_spec = scene.array_by_id(ARRAY_ID)
    reference_plan = sensor._build_window_motion(  # noqa: SLF001
        scene, sensor_spec, window
    )
    room_module = dependencies["room_acoustics_module"]
    production_phase_signal = room_module._piecewise_phase_signal
    try:
        room_module._piecewise_phase_signal = _phase_cursor_reference
        dependencies["RoomAcousticsBackend"](
            effects=effects,
            window_motion=reference_plan,
            waveform_writer=reference_sink,
        ).simulate(scene, sensor_spec, window)
    finally:
        room_module._piecewise_phase_signal = production_phase_signal
    reference_mixture = reference_sink.mixture
    _require(
        reference_mixture is not None,
        "phase-2 independently phased room mixture was not retained",
    )
    _require(
        mixture.shape[0] == decoded.shape[0] == 4
        and mixture.shape[1] >= WINDOW_SAMPLE_COUNT
        and decoded.shape[1] >= WINDOW_SAMPLE_COUNT,
        f"phase-2 rendered waveform shapes disagree: {mixture.shape}, {decoded.shape}",
    )
    _require(
        reference_mixture.shape[0] == 4
        and reference_mixture.shape[1] >= WINDOW_SAMPLE_COUNT,
        f"phase-2 reference waveform shape disagrees: {reference_mixture.shape}",
    )
    for microphone in range(4):
        continuity_rows.extend(
            _boundary_residuals(
                f"microphone_{microphone}",
                decoded[microphone, :WINDOW_SAMPLE_COUNT].astype(float),
                reference_mixture[microphone, :WINDOW_SAMPLE_COUNT],
                expected_boundaries[1:-1],
            )
        )
    maximum_residual = max(item["residual_full_scale"] for item in continuity_rows)
    _require(
        math.isfinite(maximum_residual) and maximum_residual <= CONTINUITY_BOUND,
        f"phase-2 continuity residual {maximum_residual} exceeds {CONTINUITY_BOUND}",
    )
    _log(
        paths["log"],
        "phase2_piecewise_frame_rendered",
        frame=trace,
        prime_time_s=PHASE2_PRIME_TIME_S,
        render_time_s=PHASE2_RENDER_TIME_S,
        continuity_maximum_residual_full_scale=maximum_residual,
    )

    return {
        "sensor": sensor,
        "prime": {
            "time_s": PHASE2_PRIME_TIME_S,
            "source_position_world_m": list(SOURCE_MOTION_START),
            "emitted_backend_frame": False,
        },
        "rendered_window": {
            "start_time_s": frame.start_time_s,
            "end_time_s": frame.end_time_s,
            "sample_count": WINDOW_SAMPLE_COUNT,
            "frame_id": frame.frame_id,
            "source_position_world_m": list(SOURCE_MOTION_END),
            "waveform_float32_sha256": _file_sha256_or_unavailable(
                Path(frame.waveform_paths[-1])
            ),
        },
        "prime_to_render_seconds": PHASE2_RENDER_TIME_S - PHASE2_PRIME_TIME_S,
        "segments_per_window": SEGMENTS_PER_WINDOW,
        "segment_lengths": list(lengths),
        "doppler_factors": list(factors),
        "segments": rows,
        "continuity": {
            "reference": (
                "independent float64 cumulative phase cursor rerendered through "
                "the same retained per-segment room geometry and RIR assembly"
            ),
            "boundary_count_per_signal": SEGMENTS_PER_WINDOW - 1,
            "signal_count": 5,
            "maximum_boundary_jump_residual_full_scale": maximum_residual,
            "bound_full_scale": CONTINUITY_BOUND,
            "passed": True,
            "rows": continuity_rows,
        },
        "frame_trace": trace,
    }


def _guided_audio_block(frame: Any, dependencies: dict[str, Any]) -> Any:
    """Mirror ExtensionController._guided_audio_block_for_frame exactly."""

    import numpy as np

    paths = tuple(str(path) for path in (frame.waveform_paths or ()))
    _require(bool(paths), f"room frame {frame.frame_id} has no waveform path")
    data = dependencies["read_wav"](paths[-1])
    _require(data.sample_rate_hz == SAMPLE_RATE_HZ, "frame WAV sample rate changed")
    _require(data.channel_count == 4, "frame WAV channel count changed")
    samples = data.samples
    if samples.shape[1] > WINDOW_SAMPLE_COUNT:
        samples = samples[:, -WINDOW_SAMPLE_COUNT:]
    return np.ascontiguousarray(samples, dtype=np.float32)


def _phase_cursor_reference(
    signal: Any,
    *,
    factors: tuple[float, ...],
    segment_lengths: tuple[int, ...],
) -> Any:
    import numpy as np

    source = np.asarray(signal, dtype=np.float64)
    output = np.zeros(sum(segment_lengths), dtype=np.float64)
    cursor = 0.0
    offset = 0
    for factor, length in zip(factors, segment_lengths, strict=True):
        for local_index in range(length):
            lower = math.floor(cursor)
            fraction = cursor - lower
            first = source[lower] if lower < source.size else 0.0
            second = source[lower + 1] if lower + 1 < source.size else 0.0
            output[offset + local_index] = first + fraction * (second - first)
            cursor += factor
        offset += length
    return output


def _boundary_residuals(
    signal_id: str,
    observed: Any,
    reference: Any,
    boundaries: list[int],
) -> list[dict[str, Any]]:
    import numpy as np

    observed_values = np.asarray(observed, dtype=np.float64)
    reference_values = np.asarray(reference, dtype=np.float64)
    peak = float(
        max(
            np.max(np.abs(observed_values)),
            np.max(np.abs(reference_values)),
        )
    )
    _require(math.isfinite(peak) and peak > 0.0, f"{signal_id} is silent/non-finite")
    observed_values = observed_values / peak
    reference_values = reference_values / peak
    return [
        {
            "signal_id": signal_id,
            "boundary_sample": boundary,
            "residual_full_scale": float(
                abs(
                    (observed_values[boundary] - observed_values[boundary - 1])
                    - (reference_values[boundary] - reference_values[boundary - 1])
                )
            ),
        }
        for boundary in boundaries
    ]


def _finite_segment_row(row: dict[str, Any]) -> bool:
    factors = row.get("doppler_factor_by_source")
    entities = row.get("entities")
    if not isinstance(factors, dict) or not isinstance(entities, dict):
        return False
    if not factors or not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0.0
        for value in factors.values()
    ):
        return False
    for entity in entities.values():
        if not isinstance(entity, dict):
            return False
        for name in (
            "start_position_world_m",
            "end_position_world_m",
            "mid_position_world_m",
        ):
            value = entity.get(name)
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                return False
            if not all(math.isfinite(float(component)) for component in value):
                return False
        velocity = entity.get("velocity_world_mps")
        if velocity is not None and (
            not isinstance(velocity, (list, tuple))
            or len(velocity) != 3
            or not all(math.isfinite(float(component)) for component in velocity)
        ):
            return False
    return not _contains_nonfinite(row)


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "summary": output_dir / SUMMARY_NAME,
        "frames": output_dir / FRAMES_NAME,
        "audio": output_dir / AUDIO_NAME,
        "log": output_dir / LOG_NAME,
        "stage": output_dir / STAGE_NAME,
        "environment": output_dir / ENVIRONMENT_NAME,
    }


def _initialize_artifacts(paths: dict[str, Path]) -> None:
    next(iter(paths.values())).parent.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        with suppress(FileNotFoundError):
            path.unlink()
    _write_bytes_fsync(paths["frames"], b"")
    _write_bytes_fsync(paths["audio"], b"")
    _write_bytes_fsync(paths["log"], b"")
    _write_bytes_fsync(
        paths["stage"],
        b'#usda 1.0\n(\n    documentation = "Live stage was not authored."\n)\n',
    )


def _initial_environment() -> dict[str, Any]:
    extension_manifest = ROOT / "exts/isaac_audio_sensors.omni/config/extension.toml"
    package_init = ROOT / "src/isaac_audio_sensors/__init__.py"
    repository_revision = _git_output("rev-parse", "HEAD")
    return {
        "status": "started",
        "headless": True,
        "started_at_utc": _utc_now(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "implementation": platform.python_implementation(),
        },
        "platform": platform.platform(),
        "display": {
            "DISPLAY": os.environ.get("DISPLAY"),
            "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
        },
        "repository": {
            "root": str(ROOT),
            "revision": repository_revision,
            "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
        },
        "extension": {
            "id": "isaac_audio_sensors.omni",
            "manifest": str(extension_manifest),
            "manifest_sha256": _file_sha256_or_unavailable(extension_manifest),
            "manifest_version": _manifest_version(extension_manifest),
            "repository_revision": repository_revision,
        },
        "package": {
            "name": "isaac-audio-sensors",
            "source_init": str(package_init),
            "source_init_sha256": _file_sha256_or_unavailable(package_init),
            "distribution_versions": _distribution_versions(),
        },
    }


def _record_isaacsim_preflight(environment: dict[str, Any]) -> None:
    spec = importlib.util.find_spec("isaacsim")
    if spec is None or spec.origin is None:
        environment["isaac_sim_preflight"] = {"package": "not_found"}
        return
    package_dir = Path(spec.origin).resolve().parent
    environment["isaac_sim_preflight"] = {
        "package": str(package_dir),
        "module_origin": str(spec.origin),
        "version_file": _read_first_line(package_dir / "VERSION"),
        "eula_environment_set": os.environ.get("OMNI_KIT_ACCEPT_EULA") is not None,
    }


def _record_gpu(environment: dict[str, Any]) -> None:
    try:
        import torch  # type: ignore

        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if available else 0
        environment["gpu"] = {
            "probe": "torch.cuda",
            "visible": available and count > 0,
            "device_count": count,
            "device_names": [torch.cuda.get_device_name(i) for i in range(count)],
            "torch_version": str(getattr(torch, "__version__", "unavailable")),
            "torch_cuda_version": str(getattr(torch.version, "cuda", "unavailable")),
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
        }
    except Exception as exc:  # noqa: BLE001 - prerequisite evidence.
        environment["gpu"] = {
            "probe": "torch.cuda",
            "visible": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _record_nvidia_smi(environment: dict[str, Any]) -> None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        environment["nvidia_smi"] = {"path": None, "status": "not_found"}
        return
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,uuid,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        environment["nvidia_smi"] = {
            "path": executable,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - prerequisite evidence.
        environment["nvidia_smi"] = {
            "path": executable,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _ensure_isaac_runtime(environment: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        if app is not None:
            environment["simulation_app_bootstrap"] = "attached_existing_kit_app"
            _record_kit(environment, app)
            return None
    except Exception as exc:  # noqa: BLE001 - bootstrap diagnostic.
        environment["kit_prebootstrap_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from isaacsim import SimulationApp  # type: ignore

        simulation_app = SimulationApp({"headless": True})
    except Exception as exc:  # noqa: BLE001 - missing live runtime is blocked.
        raise LivePrerequisiteError(
            "Could not start isaacsim.SimulationApp in headless mode."
        ) from exc

    try:
        import omni.kit.app  # type: ignore
    except ImportError as exc:
        raise LivePrerequisiteError(
            "SimulationApp started, but omni.kit.app could not be imported.",
            simulation_app=simulation_app,
        ) from exc
    app = omni.kit.app.get_app()
    if app is None:
        raise LivePrerequisiteError(
            "SimulationApp started, but omni.kit.app.get_app() is unavailable.",
            simulation_app=simulation_app,
        )
    environment["simulation_app_bootstrap"] = "created"
    _record_kit(environment, app)
    return simulation_app


def _load_live_dependencies() -> dict[str, Any]:
    try:
        from dataclasses import replace

        import omni  # type: ignore
        import omni.kit.app  # type: ignore
        import omni.timeline  # type: ignore
        from pxr import Gf, Usd  # type: ignore

        from isaac_audio_sensors import __version__
        from isaac_audio_sensors.core.backends import room_acoustics as room_module
        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
            _piecewise_phase_signal,
            _scheduled_window_signal,
        )
        from isaac_audio_sensors.core.dataset import SessionRecorder, validate_dataset
        from isaac_audio_sensors.core.dataset_manifest import (
            CreationProvenance,
            DeviceProvenance,
        )
        from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
        from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
        from isaac_audio_sensors.core.io.wave_read import read_wav
        from isaac_audio_sensors.core.io.waveforms import (
            FrameWaveformWriter,
            WaveformWriteResult,
        )
        from isaac_audio_sensors.core.microphone_array import microphone_layout
        from isaac_audio_sensors.core.types import AudioTimeWindow, RoomAcousticsSpec
        from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
        from isaac_audio_sensors.isaac.stage_audio import (
            attach_microphone_array_attrs,
            attach_sound_source_attrs,
            create_sound_prim,
            set_prim_xform_pose,
        )
    except ImportError as exc:
        raise LivePrerequisiteError(
            "Isaac/USD or isaac_audio_sensors imports are incomplete in this runtime."
        ) from exc

    return {
        "AudioTimeWindow": AudioTimeWindow,
        "CreationProvenance": CreationProvenance,
        "DeviceProvenance": DeviceProvenance,
        "EffectsConfig": EffectsConfig,
        "FrameWaveformWriter": FrameWaveformWriter,
        "Gf": Gf,
        "IsaacAudioArraySensor": IsaacAudioArraySensor,
        "MotionEffectsConfig": MotionEffectsConfig,
        "RoomAcousticsBackend": RoomAcousticsBackend,
        "RoomAcousticsSpec": RoomAcousticsSpec,
        "SessionRecorder": SessionRecorder,
        "Usd": Usd,
        "WaveformWriteResult": WaveformWriteResult,
        "__version__": __version__,
        "_piecewise_phase_signal": _piecewise_phase_signal,
        "_scheduled_window_signal": _scheduled_window_signal,
        "attach_microphone_array_attrs": attach_microphone_array_attrs,
        "attach_sound_source_attrs": attach_sound_source_attrs,
        "create_sound_prim": create_sound_prim,
        "frame_to_trace_dict": frame_to_trace_dict,
        "microphone_layout": microphone_layout,
        "omni": omni,
        "omni_kit_app": omni.kit.app,
        "omni_timeline": omni.timeline,
        "read_wav": read_wav,
        "replace": replace,
        "room_acoustics_module": room_module,
        "set_prim_xform_pose": set_prim_xform_pose,
        "validate_dataset": validate_dataset,
    }


def _record_loaded_runtime(
    environment: dict[str, Any], dependencies: dict[str, Any]
) -> None:
    omni = dependencies["omni"]
    Usd = dependencies["Usd"]
    package_module = sys.modules["isaac_audio_sensors"]
    environment["isaac_sim_loaded"] = {
        name: _module_identity(name) for name in ("isaacsim", "omni", "pxr")
    }
    environment["usd_version"] = str(Usd.GetVersion())
    environment["omni_module"] = str(getattr(omni, "__file__", "built-in"))
    environment["package"].update(
        {
            "version": dependencies["__version__"],
            "module_file": str(getattr(package_module, "__file__", "unavailable")),
            "repository_revision": environment["repository"]["revision"],
        }
    )


def _record_kit(environment: dict[str, Any], app: Any) -> None:
    kit: dict[str, Any] = {"available": True}
    for method_name in ("get_app_version", "get_build_version", "get_version"):
        method = getattr(app, method_name, None)
        if not callable(method):
            kit[method_name] = "unavailable"
            continue
        try:
            kit[method_name] = str(method())
        except Exception as exc:  # noqa: BLE001 - identity evidence only.
            kit[method_name] = f"unavailable: {type(exc).__name__}: {exc}"
    environment["kit"] = kit


def _validate_runtime(environment: dict[str, Any]) -> None:
    if not environment.get("kit", {}).get("available"):
        raise LivePrerequisiteError("No running Kit app is available.")
    if not environment.get("gpu", {}).get("visible"):
        raise LivePrerequisiteError("No CUDA GPU is visible to the Isaac runtime.")


def _require_room_backend(dependencies: dict[str, Any]) -> None:
    if not dependencies["RoomAcousticsBackend"].is_available():
        raise LivePrerequisiteError(
            "pyroomacoustics is unavailable; the live room waveform gate cannot run."
        )


def _require_timeline(dependencies: dict[str, Any]) -> tuple[Any, Any]:
    app = dependencies["omni_kit_app"].get_app()
    timeline = dependencies["omni_timeline"].get_timeline_interface()
    if app is None or not hasattr(app, "get_update_event_stream"):
        raise LivePrerequisiteError("Kit update event stream is unavailable.")
    if timeline is None or not (
        hasattr(timeline, "set_current_time")
        and (
            hasattr(timeline, "get_current_time")
            or hasattr(timeline, "get_current_time_seconds")
        )
        and hasattr(timeline, "play")
        and hasattr(timeline, "pause")
    ):
        raise LivePrerequisiteError("Kit timeline control is unavailable.")
    return app, timeline


def _author_stage(stage: Any, dependencies: dict[str, Any]) -> Any:
    world = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(world)
    stage.SetStartTimeCode(0.0)
    stage.SetEndTimeCode(PHASE2_RENDER_TIME_S)
    stage.SetTimeCodesPerSecond(100.0)

    microphones = dependencies["microphone_layout"]("quad_front")
    _require(len(microphones) == 4, "quad_front did not resolve exactly four mics")
    array_prim = stage.DefinePrim(ARRAY_PRIM_PATH, "Xform")
    dependencies["attach_microphone_array_attrs"](
        array_prim,
        array_id=ARRAY_ID,
        sample_rate_hz=SAMPLE_RATE_HZ,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=ARRAY_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphone_relative_offsets_m=tuple(
            microphone.relative_position_m for microphone in microphones
        ),
        microphone_ids=tuple(microphone.mic_id for microphone in microphones),
    )
    dependencies["set_prim_xform_pose"](
        array_prim,
        position=ARRAY_POSITION,
        orientation=(0.0, 0.0, 0.0, 1.0),
    )

    dependencies["create_sound_prim"](
        stage,
        prim_path=SOURCE_PRIM_PATH,
        audio_asset_path="generated://deterministic_pulse",
        spatial=True,
        loop=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    source_prim = stage.GetPrimAtPath(SOURCE_PRIM_PATH)
    dependencies["attach_sound_source_attrs"](
        source_prim,
        source_id=SOURCE_ID,
        class_label="continuous_two_tone",
        position_world=SOURCE_STATIC_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        audio_asset_path="generated://deterministic_pulse",
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        directivity="omni",
    )
    dependencies["set_prim_xform_pose"](
        source_prim,
        position=SOURCE_STATIC_POSITION,
        orientation=(0.0, 0.0, 0.0, 1.0),
    )
    return source_prim


def _room_spec(dependencies: dict[str, Any]) -> Any:
    return dependencies["RoomAcousticsSpec"](
        room_id="s3_2_live_reverberant_room",
        dimensions_m=(12.0, 7.0, 3.5),
        absorption=0.45,
        max_order=2,
        air_absorption=False,
        ray_tracing=False,
        origin_m=(-2.0, -3.5, 0.0),
    )


def _set_source_pose_both_representations(
    prim: Any,
    position: tuple[float, float, float],
    dependencies: dict[str, Any],
) -> None:
    attr = prim.GetAttribute("ias:position_world")
    _require(attr.IsValid(), "source has no ias:position_world attribute")
    attr.Set(dependencies["Gf"].Vec3d(*position))
    # stage_audio authors xform ops before reading their values; writing both
    # representations avoids the set_prim_xform_pose stale-ias-attr gotcha.
    dependencies["set_prim_xform_pose"](prim, position=position)


def _timeline_time(timeline: Any) -> float:
    if hasattr(timeline, "get_current_time"):
        return float(timeline.get_current_time())
    return float(timeline.get_current_time_seconds())


def _set_timeline_time(timeline: Any, time_s: float) -> None:
    timeline.set_current_time(float(time_s))


def _update_kit_once(app: Any) -> None:
    if app is None or not hasattr(app, "update"):
        raise LivePrerequisiteError("Kit app update() is unavailable.")
    app.update()


def _export_stage(stage: Any, path: Path) -> None:
    if not stage.GetRootLayer().Export(str(path.resolve())):
        raise RuntimeError(f"USD root layer export failed for {path}")
    _fsync_path(path)


def _contains_nonfinite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(
            _contains_nonfinite(item)
            for key, item in value.items()
            # USD serializes Usd.TimeCode.Default() as NaN in stage snapshot
            # diagnostics. It is a sentinel, not a measured numeric result.
            if key != "time_code"
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateAssertionError(message)


def _artifact_inventory(paths: dict[str, Path], *, omit: str) -> dict[str, Any]:
    return {
        name: {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": _file_sha256_or_unavailable(path),
        }
        for name, path in paths.items()
        if name != omit
    }


def _log(path: Path, event: str, **fields: Any) -> None:
    record = {"timestamp_utc": _utc_now(), "event": event, **fields}
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        output.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _write_bytes_fsync(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _copy_fsync(source: Path, destination: Path) -> None:
    with source.open("rb") as input_stream, destination.open("wb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream)
        output_stream.flush()
        os.fsync(output_stream.fileno())


def _fsync_path(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _array_sha256(array: Any) -> str:
    import numpy as np

    return hashlib.sha256(
        np.ascontiguousarray(array, dtype="<f4").tobytes(order="C")
    ).hexdigest()


def _module_identity(module_name: str) -> dict[str, str]:
    module = sys.modules.get(module_name)
    return {
        "version": str(getattr(module, "__version__", "unavailable")),
        "file": str(getattr(module, "__file__", "built-in")),
    }


def _distribution_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in (
        "isaac-audio-sensors",
        "isaacsim",
        "isaac-sim",
        "numpy",
        "pyroomacoustics",
        "soundfile",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    return versions


def _manifest_version(path: Path) -> str:
    if not path.is_file():
        return "unavailable"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"')
    return "unavailable"


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return completed.stdout.strip()
    except Exception as exc:  # noqa: BLE001 - environment evidence only.
        return f"unavailable: {type(exc).__name__}: {exc}"


def _file_sha256_or_unavailable(path: Path) -> str:
    if not path.is_file():
        return "unavailable"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_first_line(path: Path) -> str:
    if not path.is_file():
        return ""
    with suppress(OSError, UnicodeDecodeError, IndexError):
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    return ""


def _smallest_next_fix(exc: BaseException) -> str:
    message = str(exc)
    if "SimulationApp" in message or "Isaac/USD" in message:
        return "Run the target with ISAAC_SIM_COMMAND set to Isaac Sim Python."
    if "CUDA GPU" in message:
        return "Expose an NVIDIA GPU and CUDA driver to the Isaac Sim runtime."
    if "pyroomacoustics" in message:
        return "Install the supported room-acoustics dependency in Isaac Sim Python."
    if "timeline" in message or "update event stream" in message:
        return "Run inside a Kit build with omni.timeline and update events enabled."
    return "Inspect live_throttled_capture.log and rerun the exact live target."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
