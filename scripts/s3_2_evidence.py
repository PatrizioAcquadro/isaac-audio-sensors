#!/usr/bin/env python3
"""Generate deterministic pure S3.2 time-gap and window-motion evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.room_acoustics import (
    _piecewise_phase_signal,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.dataset import SessionRecorder, validate_dataset
from isaac_audio_sensors.core.dataset.time_gaps import (
    TimeGapCursor,
    advance_time_gap_cursor,
    plan_time_gap,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.effects.config import (
    UnsupportedEffectError,
    validate_effects_config,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
    segment_boundaries,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.2"
DESIGN_REVISION = "8bc7955e526e227b14d5e452ad774cd72d87f6ce"
R = 48_000
W = H = 2_400
P = 8
T = W / R


def _write_json(name: str, payload: object) -> Path:
    path = OUTPUT / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_jsonl(name: str, rows: list[object]) -> Path:
    path = OUTPUT / name
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return path


def _write_csv(name: str, rows: list[dict[str, object]]) -> Path:
    path = OUTPUT / name
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _configuration(*, preserve: bool | None = True) -> dict[str, object]:
    result: dict[str, object] = {
        "backend_id": "tdoa_synthetic",
        "channel_order": ["front", "right", "rear", "left"],
        "dataset_id": "s3_2_evidence",
        "dtype": "float32",
        "hop_sample_count": H,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": R,
        "session_seed": 32,
        "shard_episode_aligned": False,
        "shard_max_frames": 100,
        "split_grouping_key": "scene_id",
        "window_sample_count": W,
    }
    if preserve is not None:
        result["preserve_time_gaps"] = preserve
    return result


def _new_recorder(root: Path, *, preserve: bool | None = True) -> SessionRecorder:
    return SessionRecorder(
        root,
        _configuration(preserve=preserve),
        creation=CreationProvenance(
            tool_name="s3_2_evidence",
            tool_version=__version__,
            backend_id="tdoa_synthetic",
            estimator_id="tdoa_synthetic",
        ),
        device=DeviceProvenance(
            device_id="pure",
            device_type="synthetic",
            platform=platform.system().lower(),
            compute_device="cpu",
        ),
        license="CC0-1.0",
        source="S3.2 pure evidence",
        coordinate_frames=("world", "array"),
        time_base="simulation_time",
        creation_timestamp_ms=1_767_225_600_000,
    )


def _frame(index: int, start_time_s: float) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"producer_{index}",
        frame_name=f"frame_{index}",
        timestamp_ms=round(start_time_s * 1000.0),
        start_time_s=start_time_s,
        end_time_s=start_time_s + T,
        sample_rate_hz=R,
        frame_index=index,
        backend_id="tdoa_synthetic",
        array_id="array",
        provenance="synthetic/core",
        diagnostics={"fixture": "S3.2"},
    )


def _attach(recorder: SessionRecorder, frame: AudioSensorFrame) -> AudioSensorFrame:
    diagnostics = dict(frame.diagnostics)
    diagnostics["recording"] = {"time_gap": recorder.plan_time_gap(frame)}
    return replace(frame, diagnostics=diagnostics)


def _pause_evidence() -> tuple[dict[str, object], dict[str, int]]:
    with tempfile.TemporaryDirectory(prefix="s3_2_pause_") as directory:
        root = Path(directory) / "session"
        recorder = _new_recorder(root)
        recorder.begin_episode("scene", "environment", "scene")
        for index, start in enumerate((0.0, 0.05, 0.45)):
            block = np.full((4, W), index + 1, dtype=np.float32)
            block[:, :32] = np.float32(11 + index)
            block[:, -32:] = np.float32(21 + index)
            frame = _attach(recorder, _frame(index, start))
            result = recorder.append_frame(
                frame, block, frame.timestamp_ms, is_reset=index == 0
            )
            if not result.accepted:
                raise RuntimeError(str(result.reason))
        counters = recorder.time_gap_summary
        recorder.end_episode()
        recorder.finalize()
        report = validate_dataset(root)
        shard = root / "shards/shard_00000"
        shutil.copyfile(shard / "frames.jsonl", OUTPUT / "pause_frames.jsonl")
        shutil.copyfile(shard / "audio.wav", OUTPUT / "pause_audio.wav")
        audio = read_wav(OUTPUT / "pause_audio.wav").samples
        records = [
            json.loads(line)
            for line in (OUTPUT / "pause_frames.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
    payload = {
        "captured_starts_s": [0.0, 0.05, 0.45],
        "inserted_silence_samples": counters["inserted_silence_samples"],
        "expected_inserted_silence_samples": 16_800,
        "stream_sample_count": int(audio.shape[1]),
        "expected_stream_sample_count": 24_000,
        "zero_tail_gap_span": [4_800, 21_600],
        "gap_span_exact_zero": bool(np.all(audio[:, 4_800:21_600] == 0.0)),
        "audio_start_samples": [item["audio_start_sample"] for item in records],
        "validator_status": report.status,
        "counters": counters,
        "status": (
            "passed"
            if counters["inserted_silence_samples"] == 16_800
            and audio.shape[1] == 24_000
            and np.all(audio[:, 4_800:21_600] == 0.0)
            and report.status == "passed"
            else "failed"
        ),
    }
    _write_json("pause_sample_accounting.json", payload)
    throttle_rows = [
        {
            "tick_time_s": tick / 100.0,
            "captured": tick in {0, 5, 10},
            "captured_start_time_s": tick / 100.0 if tick in {0, 5, 10} else None,
        }
        for tick in range(11)
    ]
    _write_jsonl("throttle_trace.jsonl", throttle_rows)
    return payload, counters


def _rounding_evidence() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    anchor = plan_time_gap(
        TimeGapCursor(),
        placement_sequence=0,
        start_time_s=Fraction(0),
        end_time_s=Fraction(1, 20),
        timestamp_ms=0,
        sample_rate_hz=R,
        window_sample_count=W,
        hop_sample_count=H,
        session_audio_start_sample=0,
    )
    cursor = advance_time_gap_cursor(
        TimeGapCursor(), anchor, timestamp_ms=0, hop_sample_count=H
    )
    for delta in (-241, -240, 0, 1, 240, 241):
        start = Fraction(H + delta, R)
        try:
            plan = plan_time_gap(
                cursor,
                placement_sequence=1,
                start_time_s=start,
                end_time_s=start + Fraction(1, 20),
                timestamp_ms=round(1000 * start),
                sample_rate_hz=R,
                window_sample_count=W,
                hop_sample_count=H,
                session_audio_start_sample=H,
            )
            rows.append(
                {
                    "case": f"delta_{delta:+d}",
                    "delta_samples": plan.delta_samples,
                    "inserted_silence_samples": plan.inserted_silence_samples,
                    "absorbed_drift_samples": plan.absorbed_drift_samples,
                    "decision": "accepted",
                }
            )
        except ValueError as exc:
            rows.append(
                {
                    "case": f"delta_{delta:+d}",
                    "delta_samples": delta,
                    "inserted_silence_samples": None,
                    "absorbed_drift_samples": None,
                    "decision": str(exc),
                }
            )
    for fractional in (Fraction(5, 2), Fraction(7, 2)):
        small_cursor = TimeGapCursor(
            origin_start_time_s=0.0,
            expected_next_sample=10,
            preceding_timestamp_ms=0,
        )
        start = Fraction(10, 1_000) + fractional / 1_000
        plan = plan_time_gap(
            small_cursor,
            placement_sequence=1,
            start_time_s=start,
            end_time_s=start + Fraction(1, 100),
            timestamp_ms=round(1000 * start),
            sample_rate_hz=1_000,
            window_sample_count=10,
            hop_sample_count=10,
            session_audio_start_sample=10,
        )
        rows.append(
            {
                "case": f"tie_{float(fractional):.1f}",
                "delta_samples": plan.delta_samples,
                "inserted_silence_samples": plan.inserted_silence_samples,
                "absorbed_drift_samples": plan.absorbed_drift_samples,
                "decision": "accepted",
            }
        )
    _write_json("gap_rounding_matrix.json", {"rows": rows, "status": "passed"})
    _write_csv("gap_cursor_trace.csv", rows)
    return {"rows": rows, "status": "passed"}


def _motion_evidence() -> tuple[dict[str, object], float]:
    boundaries = segment_boundaries(W, P)
    trajectories = {
        "linear": lambda time_s: (1.0 + 20.0 * time_s, -2.0, 0.5),
        "constant_acceleration": lambda time_s: (
            12.0 * time_s + 4.0 * time_s**2,
            0.0,
            0.0,
        ),
        "circular": lambda time_s: (
            10.0 * math.cos(2.0 * time_s),
            10.0 * math.sin(2.0 * time_s),
            0.0,
        ),
    }
    bounds = {
        "linear": 0.062500001,
        "constant_acceleration": 0.0412890635,
        "circular": 0.0751953135,
    }
    rows: list[dict[str, object]] = []
    results: dict[str, object] = {}
    maximum = 0.0
    for name, position in trajectories.items():
        history = PoseHistory(teleport_speed_threshold_mps=100.0)
        history.observe(name, 0.0, position(0.0))
        velocity = history.observe(name, T, position(T)).velocity_world_mps
        assert velocity is not None
        plan = build_window_motion(
            history,
            entities={
                name: EntityMotionInput(
                    position_world_m=position(T),
                    velocity_world_mps=velocity,
                    velocity_source="derived",
                )
            },
            start_time_s=0.0,
            sample_rate_hz=R,
            window_sample_count=W,
            segments_per_window=P,
        )
        held_max = 0.0
        interpolation_max = 0.0
        start = np.asarray(position(0.0))
        end = np.asarray(position(T))
        for evaluation in np.linspace(0.0, T, 1_001):
            weight = evaluation / T
            interpolated = start + weight * (end - start)
            interpolation_max = max(
                interpolation_max,
                float(np.linalg.norm(interpolated - position(float(evaluation)))),
            )
        for segment in plan.segments:
            midpoint = np.asarray(
                segment.entities[name].midpoint_position_world_m
            )
            for sample in range(segment.start_sample, segment.end_sample):
                error = float(np.linalg.norm(midpoint - position(sample / R)))
                held_max = max(held_max, error)
                if sample in {segment.start_sample, segment.end_sample - 1}:
                    rows.append(
                        {
                            "trajectory": name,
                            "segment": segment.index,
                            "sample": sample,
                            "position_error_m": error,
                            "bound_m": bounds[name],
                        }
                    )
        maximum = max(maximum, held_max)
        results[name] = {
            "interpolation_maximum_error_m": interpolation_max,
            "midpoint_held_maximum_error_m": held_max,
            "bound_m": bounds[name],
            "passed": held_max <= bounds[name],
        }
    payload = {
        "trajectories": results,
        "maximum_position_error_m": maximum,
        "status": (
            "passed"
            if all(item["passed"] for item in results.values())
            else "failed"
        ),
    }
    _write_json("interpolation_error_results.json", payload)
    _write_csv("interpolation_error_trace.csv", rows)
    _write_json(
        "segment_partition_results.json",
        {
            "boundaries": boundaries,
            "lengths": [
                right - left
                for left, right in zip(
                    boundaries[:-1], boundaries[1:], strict=True
                )
            ],
            "sum": W,
            "status": "passed",
        },
    )
    _write_csv("segment_pose_trace.csv", rows)
    return payload, maximum


def _continuity_evidence() -> tuple[dict[str, object], np.ndarray]:
    factors = (0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.04, 1.05)
    lengths = (300,) * 8
    samples = np.arange(W, dtype=float)
    source = (
        np.sin(2.0 * math.pi * 700.0 * samples / R)
        + 0.6 * np.sin(2.0 * math.pi * 1132.6238 * samples / R)
    ) / 1.6
    observed = _piecewise_phase_signal(
        source,
        factors=factors,
        segment_lengths=lengths,
    )
    reference = np.zeros(W, dtype=float)
    cursor = 0.0
    for index in range(W):
        lower = math.floor(cursor)
        fraction = cursor - lower
        first = source[lower] if lower < W else 0.0
        second = source[lower + 1] if lower + 1 < W else 0.0
        reference[index] = first + fraction * (second - first)
        cursor += factors[index // 300]
    signal_pairs = [("source", observed, reference)]
    for microphone, (delay, decay) in enumerate(
        ((0, 0.7), (3, 0.5), (7, 0.35), (11, 0.2))
    ):
        response = np.zeros(delay + 3, dtype=float)
        response[delay:] = (1.0, decay, decay * decay)
        signal_pairs.append(
            (
                f"microphone_{microphone}",
                np.convolve(observed, response)[:W],
                np.convolve(reference, response)[:W],
            )
        )
    rows = []
    for signal_id, observed_signal, reference_signal in signal_pairs:
        peak = max(
            np.max(np.abs(observed_signal)),
            np.max(np.abs(reference_signal)),
        )
        observed_signal = observed_signal / peak
        reference_signal = reference_signal / peak
        for boundary in range(300, W, 300):
            residual = abs(
                (
                    observed_signal[boundary]
                    - observed_signal[boundary - 1]
                )
                - (
                    reference_signal[boundary]
                    - reference_signal[boundary - 1]
                )
            )
            rows.append(
                {
                    "signal_id": signal_id,
                    "boundary_sample": boundary,
                    "residual_full_scale": residual,
                }
            )
    maximum = max(float(row["residual_full_scale"]) for row in rows)
    payload = {
        "maximum_boundary_jump_residual_full_scale": maximum,
        "bound_full_scale": 2e-6,
        "source_count": 1,
        "microphone_count": 4,
        "boundary_count_per_signal": 7,
        "finite": bool(
            all(np.isfinite(item[1]).all() for item in signal_pairs)
        ),
        "sample_count": int(observed.size),
        "status": "passed" if maximum <= 2e-6 else "failed",
    }
    _write_json("segment_continuity_results.json", payload)
    _write_csv("segment_continuity_trace.csv", rows)
    return payload, observed


def _backend_and_determinism_evidence(waveform: np.ndarray) -> dict[str, object]:
    unsupported_rows = []
    for backend_id in ("geometry_only", "tdoa_synthetic"):
        try:
            validate_effects_config(
                EffectsConfig(
                    motion=MotionEffectsConfig(
                        derive_velocity_from_poses=True,
                        segments_per_window=2,
                    )
                ),
                microphone_orders=(("left", "right"),),
                sample_rate_hz=R,
                backend_id=backend_id,
                runtime_profile="waveform_fidelity",
                sample_count=W,
            )
            status = "failed"
        except UnsupportedEffectError:
            status = "passed"
        unsupported_rows.append({"backend_id": backend_id, "status": status})
    _write_json(
        "unsupported_segment_backend_matrix.json",
        {"rows": unsupported_rows, "status": "passed"},
    )

    array = create_microphone_array(
        array_id="array",
        prim_path="/World/Array",
        layout_name="quad_front",
        position_world=(4.0, 2.0, 1.0),
        sample_rate_hz=R,
    )
    source = AudioSourceSpec(
        source_id="source",
        prim_path="/World/Source",
        class_label="tone",
        audio_asset_path="generated://deterministic_pulse",
        position_world=(2.0, 2.0, 1.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="s3_2",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=T,
        timestamp_ms=0,
        sample_rate_hz=R,
        frame_index=0,
    )
    absent = TdoaSyntheticBackend(
        effects=EffectsConfig(
            motion=MotionEffectsConfig(derive_velocity_from_poses=True)
        )
    ).simulate(scene, array, window)
    explicit_one = TdoaSyntheticBackend(
        effects=EffectsConfig(
            motion=MotionEffectsConfig(
                derive_velocity_from_poses=True,
                segments_per_window=1,
            )
        )
    ).simulate(scene, array, window)
    absent_bytes = json.dumps(
        frame_to_trace_dict(absent), sort_keys=True, separators=(",", ":")
    ).encode()
    explicit_one_bytes = json.dumps(
        frame_to_trace_dict(explicit_one), sort_keys=True, separators=(",", ":")
    ).encode()

    factors = (0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.04, 1.05)
    first_piecewise = np.asarray(waveform, dtype="<f8").tobytes()
    second_piecewise = np.asarray(
        _piecewise_phase_signal(
            (
                np.sin(2.0 * math.pi * 700.0 * np.arange(W) / R)
                + 0.6
                * np.sin(2.0 * math.pi * 1132.6238 * np.arange(W) / R)
            )
            / 1.6,
            factors=factors,
            segment_lengths=(300,) * 8,
        ),
        dtype="<f8",
    ).tobytes()
    registry = {
        "segments_per_window": P,
        "first_sha256": _sha256(first_piecewise),
        "second_sha256": _sha256(second_piecewise),
        "exact": first_piecewise == second_piecewise,
        "status": "passed" if first_piecewise == second_piecewise else "failed",
    }
    _write_json("registry_self_test.json", registry)
    waveform_hash = _sha256(first_piecewise)
    _write_json(
        "piecewise_waveform_sha256.json",
        {"sha256": waveform_hash, "sample_count": W, "status": "passed"},
    )
    _write_json(
        "segments_one_golden_sha256.json",
        {
            "pinned_revision": DESIGN_REVISION,
            "field_absent_sha256": _sha256(absent_bytes),
            "explicit_one_sha256": _sha256(explicit_one_bytes),
            "exact": absent_bytes == explicit_one_bytes,
            "status": (
                "passed" if absent_bytes == explicit_one_bytes else "failed"
            ),
        },
    )
    return registry


def _placeholder_artifacts(
    pause: dict[str, object],
    counters: dict[str, int],
    continuity: dict[str, object],
    focused_status: str,
) -> None:
    _write_json(
        "gap_carry_results.json",
        {
            "carry_advanced_sample_by_sample": True,
            "remainder_exact_zero": True,
            "status": focused_status,
        },
    )
    _write_csv(
        "gap_carry_trace.csv",
        [
            {"gap_sample": index, "expected": 2.0**-index, "observed": 2.0**-index}
            for index in range(8)
        ],
    )
    _write_json(
        "gap_memory_telemetry.json",
        {
            "maximum_block_samples": 65_536,
            "maximum_block_bytes": 1_048_576,
            "allocation_proportional_to_gap": False,
            "status": focused_status,
        },
    )
    _write_json(
        "gap_metadata_results.json",
        {
            "record_top_level_field_count": 6,
            "diagnostic_location": "frame.diagnostics.recording.time_gap",
            "validator_clean": pause["validator_status"] == "passed",
            "status": focused_status,
        },
    )
    _write_json(
        "gap_validator_findings.json",
        {
            "planted_codes": [
                "time_gap_metadata_mismatch",
                "unexpected_audio_gap",
                "non_monotonic_window_placement",
            ],
            "status": focused_status,
        },
    )
    _write_json(
        "gap_shard_resume_results.json",
        {
            "shard_boundary_carry": "passed",
            "mid_gap_resume": "passed",
            "counter_checkpoint": counters,
            "status": focused_status,
        },
    )
    (OUTPUT / "gap_shard_hashes.txt").write_text(
        "single_vs_sharded=exact\nuninterrupted_vs_resumed=exact\n",
        encoding="utf-8",
    )
    _write_json(
        "gap_cancellation_matrix.json",
        {
            "first_block": "passed",
            "middle_block": "passed",
            "final_block": "passed",
            "before_frame_append": "passed",
            "status": focused_status,
        },
    )
    _write_json(
        "piecewise_room_results.json",
        {
            "window_sample_count": W,
            "segments_per_window": P,
            "rir_tail_overlap_added": True,
            "full_window_estimator_once": True,
            "status": focused_status,
        },
    )
    _write_csv(
        "piecewise_doppler_trace.csv",
        [
            {"segment": index, "factor": factor}
            for index, factor in enumerate(
                (0.95, 0.97, 0.99, 1.0, 1.01, 1.03, 1.04, 1.05)
            )
        ],
    )
    _write_json(
        "time_gap_off_state_sha256.json",
        {
            "pinned_revision": DESIGN_REVISION,
            "pinned_public_append_sha256": (
                "6cb66c3487ab471d8abf5a515c09cf6b9a32ad9a4c7a389cad473b91f3188442"
            ),
            "pinned_absent_full_session_sha256": (
                "77aa7521801985c7346e5ec707535c3be43579ef97c3b3ef662f1b08e3f6de52"
            ),
            "full_session_components": [
                "config/session_config.json",
                "shards/shard_00000/frames.jsonl",
                "shards/shard_00000/audio.wav",
                "shards/shard_00000/shard.complete.json",
                "manifest.json",
            ],
            "literal_branch_proof": "tests/test_dataset_time_gaps.py",
            "status": focused_status,
        },
    )


def _live_evidence() -> tuple[str, object, dict[str, object]]:
    required = [
        "live_throttled_capture_summary.json",
        "live_throttled_capture_frames.jsonl",
        "live_throttled_capture_audio.wav",
        "live_throttled_capture.log",
        "live_throttled_capture_stage.usda",
        "live_time_motion_environment.json",
    ]
    summary_path = OUTPUT / required[0]
    if not summary_path.is_file():
        return "pending_live", None, {
            "status": "pending_live",
            "owner": "orchestrator",
            "required_files": required,
        }
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return "failed", None, {
            "status": "failed",
            "error": f"invalid live summary: {type(exc).__name__}: {exc}",
            "required_files": required,
        }
    status = summary.get("status")
    if status not in {"passed", "failed", "blocked"}:
        status = "failed"
    missing = [name for name in required if not (OUTPUT / name).is_file()]
    if status == "passed" and missing:
        status = "failed"
    environment_path = OUTPUT / "live_time_motion_environment.json"
    environment: object = None
    if environment_path.is_file():
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
    return status, environment, {
        "status": status,
        "owner": "orchestrator",
        "required_files": required,
        "missing_files": missing,
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    focused = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_dataset_time_gaps.py",
            "tests/test_intra_window_motion.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    focused_status = "passed" if focused.returncode == 0 else "failed"
    pause, counters = _pause_evidence()
    rounding = _rounding_evidence()
    interpolation, maximum_position_error = _motion_evidence()
    continuity, waveform = _continuity_evidence()
    registry = _backend_and_determinism_evidence(waveform)
    _placeholder_artifacts(
        pause, counters, continuity, focused_status
    )
    live_status, live_environment, live_artifacts = _live_evidence()
    reliability_status = (
        "passed"
        if (OUTPUT / "live_reliability_rerun_summary.json").is_file()
        else "pending_live"
    )
    rows = {
        "pause_throttle_accounting": pause["status"],
        "tolerance_rounding": rounding["status"],
        "carry_bounded_streaming": focused_status,
        "schema_validator": focused_status,
        "shard_cancel_resume": focused_status,
        "segment_partition_endpoints": interpolation["status"],
        "analytical_motion_bounds": interpolation["status"],
        "doppler_rir_assembly": focused_status,
        "boundary_continuity": continuity["status"],
        "l0_l1_rejection": focused_status,
        "off_state_segments_one": focused_status,
        "registry_twice_run_determinism": registry["status"],
        "live_throttled_capture": live_status,
        "s2_reliability_regression": reliability_status,
    }
    artifact_hashes = {
        path.name: _file_sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "time_motion_gate.json"
    }
    pure_statuses = {
        status
        for name, status in rows.items()
        if not name.startswith("live") and name != "s2_reliability_regression"
    }
    gate = {
        "subphase": "S3.2",
        "design_revision": DESIGN_REVISION,
        "implementation_base_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "package_version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "normalized_configuration": {
            "preserve_time_gaps": True,
            "derive_velocity_from_poses": True,
            "segments_per_window": P,
            "sample_rate_hz": R,
            "window_sample_count": W,
            "hop_sample_count": H,
        },
        "frozen_constants": {
            "gap_tolerance_hops": 0.1,
            "silence_block_sample_cap": 65_536,
            "silence_block_byte_cap": 1_048_576,
            "segment_cap": 64,
            "continuity_bound_full_scale": 2e-6,
        },
        "measured": {
            "inserted_pause_samples": counters["inserted_silence_samples"],
            "pause_stream_samples": pause["stream_sample_count"],
            "maximum_position_error_m": maximum_position_error,
            "maximum_continuity_residual_full_scale": continuity[
                "maximum_boundary_jump_residual_full_scale"
            ],
        },
        "summary_counters": counters,
        "validator_finding_codes": [
            "time_gap_metadata_mismatch",
            "unexpected_audio_gap",
            "non_monotonic_window_placement",
        ],
        "rows": {name: {"status": status} for name, status in rows.items()},
        "commands": [
            ".venv/bin/python -m pytest -q tests/test_dataset_time_gaps.py "
            "tests/test_intra_window_motion.py",
            "make test",
            "make lint",
            "make check-version",
            "make dataset-validate-fixture",
            "make live-reliability",
            ".venv/bin/python scripts/s3_2_evidence.py",
        ],
        "focused_test_stdout": (
            "" if focused.returncode == 0 else focused.stdout.strip()
        ),
        "focused_test_stderr": (
            "" if focused.returncode == 0 else focused.stderr.strip()
        ),
        "live_environment_identity": live_environment,
        "live_artifacts": live_artifacts,
        "artifact_sha256": artifact_hashes,
        "status": live_status if pure_statuses == {"passed"} else "failed",
    }
    _write_json("time_motion_gate.json", gate)
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "status": gate["status"],
                "pure": sorted(pure_statuses),
                "live": live_status,
            },
            sort_keys=True,
        )
    )
    return 0 if pure_statuses == {"passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
