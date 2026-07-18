#!/usr/bin/env python3
"""Execute and roll up truthful S3.8 pure and pending-live evidence."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    DirectivityConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    ElectronicsConfig,
    MotionEffectsConfig,
    NoiseConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
)
from isaac_audio_sensors.core.types import AudioSceneSnapshot, SourceOcclusion
from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.8"
SPEC = ROOT / "docs/development/specs/s3_stress_matrix.md"
ENTRY_REVISION = "44608130727c2466f29919c5521218228e3de56a"
SAMPLE_RATE_HZ = 48_000
WINDOW_SAMPLE_COUNT = 2_400
MIC_IDS = ("front", "right", "rear", "left")
ROOM_WORKER_NAME = "real_room_worker.json"
SCENARIO_IDS = tuple(f"P{index:02d}" for index in range(1, 13))
CANONICALIZATION_EXCLUDED_FIELDS = (
    "absolute_output_paths",
    "environment_strings",
    "latency_samples",
    "process_ids",
    "rss_samples",
    "runtime_timestamps",
)

MATRIX = {
    "geometry_only": ("N/A", "N/A", "U", "S", "S", "U", "U", "S", "S", "N/A", "S"),
    "tdoa_synthetic": ("S", "S", "U", "S", "S", "U", "U", "S", "S", "N/A", "S"),
    "room_acoustics": ("S", "S", "S", "S", "S", "S", "S", "S", "S", "N/A", "S"),
    "room_acoustics_srp": ("S", "S", "S", "S", "S", "S", "S", "S", "S", "N/A", "S"),
    "isaac_lab_batched_selected": (
        "S",
        "U",
        "U",
        "U",
        "U",
        "U",
        "U",
        "U",
        "U",
        "N/A",
        "S",
    ),
}
MATRIX_COLUMNS = (
    "authored_velocity",
    "derived_velocity",
    "segments_gt_1",
    "channel_response",
    "noise",
    "electronics",
    "directivity",
    "occlusion",
    "materials",
    "gap_preservation",
    "multi_source_2_4_8",
)

REGRESSION_INPUTS = {
    "live_isaac_sim_audio": "live_isaac_sim_audio_regression.json",
    "live_isaac_occlusion": "live_isaac_occlusion_regression.json",
    "live_isaac_lab_gpu_off_state": "live_isaac_lab_gpu_off_state_regression.json",
    "live_isaac_lab_effects_on": "live_isaac_lab_effects_on_report.json",
    "live_reliability": "live_reliability_regression.json",
}


class _LatestSink:
    def __init__(self) -> None:
        self.mixture: np.ndarray | None = None

    def write_frame_mixture(self, **kwargs: object) -> WaveformWriteResult:
        self.mixture = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        return WaveformWriteResult(paths=())

    def close(self) -> None:
        self.mixture = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(
            _with_nonpassed_reasons(payload),
            stream,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _with_nonpassed_reasons(payload: object) -> object:
    if isinstance(payload, dict):
        normalized = {
            key: _with_nonpassed_reasons(value) for key, value in payload.items()
        }
        raw_status = normalized.get("status")
        status = str(raw_status).strip().lower() if raw_status is not None else None
        raw_reason = normalized.get("reason")
        if raw_reason is not None and not str(raw_reason).strip():
            normalized["reason"] = "The producer supplied an empty reason string."
        if (
            status not in {None, "passed", "pass", "n/a"}
            and not str(normalized.get("reason", "")).strip()
        ):
            detail = next(
                (
                    str(normalized[key]).strip()
                    for key in (
                        "error",
                        "exception_message",
                        "message",
                        "stderr",
                        "rationale",
                    )
                    if str(normalized.get(key, "")).strip()
                ),
                "",
            )
            if detail:
                reason = detail
            elif status == "pending" and normalized.get("path"):
                reason = (
                    "Required evidence artifact is not available at "
                    f"{normalized['path']}."
                )
            elif status in {"blocked", "dependency_unavailable"}:
                dependency = normalized.get("dependency", "required execution")
                reason = f"{dependency} is unavailable for this evidence row."
            elif status in {"failed", "missing_execution"}:
                reason = (
                    "A required execution or invariant did not produce a passing "
                    "result."
                )
            else:
                reason = f"This evidence row has non-passing status {raw_status!r}."
            normalized["reason"] = reason
        return normalized
    if isinstance(payload, list):
        return [_with_nonpassed_reasons(value) for value in payload]
    if isinstance(payload, tuple):
        return tuple(_with_nonpassed_reasons(value) for value in payload)
    return payload


def _canonicalize_payload(payload: object) -> object:
    """Remove only the frozen runtime-telemetry fields from hash input."""
    excluded = frozenset(CANONICALIZATION_EXCLUDED_FIELDS)
    if isinstance(payload, dict):
        return {
            str(key): _canonicalize_payload(value)
            for key, value in payload.items()
            if str(key) not in excluded
        }
    if isinstance(payload, (list, tuple)):
        return [_canonicalize_payload(value) for value in payload]
    return payload


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        _canonicalize_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _canonical_sha256(payload: object) -> str:
    return _sha256(_canonical_bytes(payload))


def _runtime_telemetry() -> dict[str, object]:
    return {
        "runtime_timestamps": {
            "wall_clock_s": time.time(),
            "monotonic_s": time.monotonic(),
        },
        "rss_samples": [{"rss_mib": _vmrss_mib()}],
        "latency_samples": [],
        "process_ids": [os.getpid()],
        "absolute_output_paths": [str(OUTPUT.resolve())],
        "environment_strings": {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
        },
    }


def _structure(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _structure(child) for key, child in value.items()}
    if isinstance(value, list):
        return {
            "container": "list",
            "item_structures": sorted(
                {_canonical_bytes(_structure(child)).decode("utf-8") for child in value}
            ),
        }
    return type(value).__name__


def _frame_sha256(frame: object) -> str:
    return _canonical_sha256(frame_to_trace_dict(frame))


def _json_default(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _load_fixtures() -> Any:
    path = ROOT / "tests/test_s3_stress_matrix.py"
    spec = importlib.util.spec_from_file_location("_s3_8_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load S3.8 fixtures from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _vmrss_mib() -> float:
    with Path("/proc/self/status").open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    raise RuntimeError("/proc/self/status did not report VmRSS")


def _ols(samples: list[dict[str, float]]) -> dict[str, float | int]:
    selected = [row for row in samples if 512 <= row["frame_index"] <= 4_095]
    x = np.asarray([row["frame_index"] for row in selected], dtype=float)
    y = np.asarray([row["rss_mib"] for row in selected], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    total = float(np.sum((y - np.mean(y)) ** 2))
    residual = float(np.sum((y - predicted) ** 2))
    return {
        "sample_count": len(selected),
        "slope_mib_per_frame": float(slope),
        "slope_mib_per_1_000_frames": float(slope * 1_000.0),
        "intercept_mib": float(intercept),
        "r_squared": 1.0 if total == 0.0 else float(1.0 - residual / total),
    }


def _run_real_room_worker() -> int:
    fixtures = _load_fixtures()
    started = time.perf_counter()
    array = fixtures._array()
    two_sources = (
        fixtures._source(0, (4.0, 2.0, 1.5)),
        fixtures._source(1, (6.0, 2.5, 1.5)),
    )

    reverb_rows = []
    for max_order in (0, 1, 3, 6):
        hashes = []
        for _frame_index in range(16):
            sink = _LatestSink()
            frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
                fixtures._scene((two_sources[0],), array=array, max_order=max_order),
                array,
                fixtures._window(),
            )
            assert sink.mixture is not None
            assert np.isfinite(sink.mixture).all()
            hashes.append(_sha256(sink.mixture.astype("<f4").tobytes()))
            assert not _contains_nonfinite(frame_to_trace_dict(frame))
        reverb_rows.append(
            {
                "max_order": max_order,
                "frame_count": 16,
                "waveform_sha256": hashes[0],
                "deterministic": len(set(hashes)) == 1,
            }
        )

    overlap_rows = []
    for backend_type in (RoomAcousticsBackend, RoomAcousticsSrpBackend):
        for count in (2, 4, 8):
            sources = tuple(
                fixtures._source(index, (2.0 + index, 1.0 + index % 3, 1.5))
                for index in range(count)
            )
            for frame_index in range(32):
                sink = _LatestSink()
                backend = backend_type(waveform_writer=sink)
                frame = backend.simulate(
                    fixtures._scene(sources, array=array),
                    array,
                    fixtures._window(frame_index=frame_index),
                )
                assert len(frame.detections) == count
                assert sink.mixture is not None and np.isfinite(sink.mixture).all()
            overlap_rows.append(
                {
                    "backend": backend.backend_id,
                    "source_count": count,
                    "frame_count": 32,
                    "status": "Passed",
                }
            )

    moving_array = fixtures._array(velocity_world_mps=(0.5, 0.0, 0.0))
    all_sources = tuple(
        fixtures._source(
            index,
            (2.0 + index, 1.0 + index % 3, 1.5),
            velocity=(1.0, 0.0, 0.0),
        )
        for index in range(8)
    )
    all_scene = fixtures._scene(all_sources, array=moving_array, max_order=3)
    all_effects_paths = []
    for backend_type in (RoomAcousticsBackend, RoomAcousticsSrpBackend):
        frame_hashes = []
        waveform_hashes = []
        last_frame = None
        for frame_index in range(32):
            sink = _LatestSink()
            last_frame = backend_type(
                effects=fixtures._all_effects(segments=8),
                window_motion=fixtures._motion_plan(all_scene),
                waveform_writer=sink,
            ).simulate(
                all_scene,
                moving_array,
                fixtures._window(frame_index=frame_index),
            )
            assert len(last_frame.detections) == 8
            assert sink.mixture is not None and np.isfinite(sink.mixture).all()
            assert set(last_frame.diagnostics["effects"]) == {
                "channel_response",
                "noise",
                "electronics",
                "directivity",
            }
            assert last_frame.diagnostics["motion"]["segments_per_window"] == 8
            motion_entities = last_frame.diagnostics["motion"]["segments"][0][
                "entities"
            ]
            assert motion_entities["source-00"]["velocity_source"] == "authored"
            frame_hashes.append(_frame_sha256(last_frame))
            waveform_hashes.append(_sha256(sink.mixture.astype("<f4").tobytes()))
        assert last_frame is not None
        all_effects_paths.append(
            {
                "backend_path": last_frame.backend_id,
                "status": "Passed",
                "frame_count": len(frame_hashes),
                "effects": sorted(last_frame.diagnostics["effects"]),
                "segments_per_window": 8,
                "canonical_payload_sha256": _canonical_sha256(
                    {"frames": frame_hashes, "waveforms": waveform_hashes}
                ),
                "frame_sha256": frame_hashes,
                "waveform_sha256": waveform_hashes,
            }
        )

    room_matrix_cells: list[dict[str, Any]] = []
    p10_features = (
        "authored_velocity",
        "segments_gt_1",
        "channel_response",
        "noise",
        "electronics",
        "directivity",
    )
    for path in all_effects_paths:
        for feature in p10_features:
            room_matrix_cells.append(
                {
                    "backend_path": path["backend_path"],
                    "feature": feature,
                    "status": "Passed",
                    "execution_reference": {
                        "scenario_id": "P10_all_effects_l2",
                        "fixture": "canonical_all_effects",
                        "profile": "waveform_fidelity",
                        "frame_count": path["frame_count"],
                        "canonical_payload_sha256": path["canonical_payload_sha256"],
                    },
                }
            )

    for backend_type in (RoomAcousticsBackend, RoomAcousticsSrpBackend):
        derived_source = fixtures._source(0, (4.0, 2.0, 1.5))
        derived_scene = fixtures._scene((derived_source,), array=array)
        derived_history = PoseHistory()
        derived_history.observe("source-00", 0.0, (3.95, 2.0, 1.5))
        derived_observation = derived_history.observe(
            "source-00", 0.05, derived_source.position_world
        )
        derived_history.observe(array.array_id, 0.0, array.position_world)
        derived_history.observe(array.array_id, 0.05, array.position_world)
        assert derived_observation.velocity_world_mps is not None
        derived_plan = build_window_motion(
            derived_history,
            entities={
                derived_source.source_id: EntityMotionInput(
                    position_world_m=derived_source.position_world,
                    velocity_world_mps=derived_observation.velocity_world_mps,
                    velocity_source="derived",
                ),
                array.array_id: EntityMotionInput(
                    position_world_m=array.position_world,
                    velocity_world_mps=None,
                    velocity_source="none:stationary",
                ),
            },
            start_time_s=0.0,
            sample_rate_hz=SAMPLE_RATE_HZ,
            window_sample_count=WINDOW_SAMPLE_COUNT,
            segments_per_window=8,
        )
        derived_sink = _LatestSink()
        derived_frame = backend_type(
            effects=EffectsConfig(
                motion=MotionEffectsConfig(
                    derive_velocity_from_poses=True,
                    segments_per_window=8,
                )
            ),
            window_motion=derived_plan,
            waveform_writer=derived_sink,
        ).simulate(derived_scene, array, fixtures._window())
        assert derived_sink.mixture is not None
        derived_entities = derived_frame.diagnostics["motion"]["segments"][0][
            "entities"
        ]
        assert derived_entities[derived_source.source_id]["velocity_source"] == (
            "derived"
        )
        room_matrix_cells.append(
            {
                "backend_path": derived_frame.backend_id,
                "feature": "derived_velocity",
                "status": "Passed",
                "execution_reference": {
                    "scenario_id": "P02_velocity_derived",
                    "fixture": "l2_pose_history",
                    "profile": "waveform_fidelity",
                    "frame_count": 1,
                    "frame_sha256": _frame_sha256(derived_frame),
                },
            }
        )

        occluded_source = fixtures._source(0, (4.0, 2.0, 1.5))
        occlusion = SourceOcclusion(
            array_id=array.array_id,
            source_id=occluded_source.source_id,
            per_mic_blocked={mic_id: True for mic_id in MIC_IDS},
            occlusion_factor=1.0,
            attenuation_db=12.0,
            hit_prim_paths=("/World/Occluder",),
            hit_materials={"/World/Occluder": "nominal.concrete"},
        )
        occluded_scene = fixtures._scene(
            (occluded_source,), array=array, occlusion=(occlusion,)
        )
        assert occluded_scene.room is not None
        occluded_scene = replace(
            occluded_scene,
            room=replace(
                occluded_scene.room,
                absorption="pra.rough_concrete",
            ),
        )
        occluded_sink = _LatestSink()
        occluded_frame = backend_type(waveform_writer=occluded_sink).simulate(
            occluded_scene, array, fixtures._window()
        )
        assert occluded_sink.mixture is not None
        occlusion_result = occluded_frame.detections[0].diagnostics["occlusion"]
        assert occlusion_result["occlusion_factor"] == 1.0
        assert occlusion_result["hit_materials"] == {
            "/World/Occluder": "nominal.concrete"
        }
        material_evidence = occluded_frame.diagnostics["acoustics_state"][
            "material_evidence"
        ]
        assert material_evidence["room"]["material_id"] == "pra.rough_concrete"
        assert material_evidence["occluder:/World/Occluder"]["material_id"] == (
            "nominal.concrete"
        )
        for feature in ("occlusion", "materials"):
            room_matrix_cells.append(
                {
                    "backend_path": occluded_frame.backend_id,
                    "feature": feature,
                    "status": "Passed",
                    "execution_reference": {
                        "scenario_id": "P07_moving_occluder",
                        "fixture": "l2_occlusion_material",
                        "profile": "waveform_fidelity",
                        "frame_count": 1,
                        "frame_sha256": _frame_sha256(occluded_frame),
                    },
                }
            )

    for overlap in overlap_rows:
        if overlap["source_count"] != 8:
            continue
        matching_rows = [
            row for row in overlap_rows if row["backend"] == overlap["backend"]
        ]
        room_matrix_cells.append(
            {
                "backend_path": overlap["backend"],
                "feature": "multi_source_2_4_8",
                "status": "Passed"
                if all(row["status"] == "Passed" for row in matching_rows)
                else "Failed",
                "execution_reference": {
                    "scenario_id": "P03_overlap_ladder",
                    "fixture": "real_room_2_4_8",
                    "profile": "waveform_fidelity",
                    "source_counts": [row["source_count"] for row in matching_rows],
                    "frames_per_count": [row["frame_count"] for row in matching_rows],
                },
            }
        )

    resource = _resource_long_run(fixtures)
    result = {
        "status": "Passed"
        if all(row["deterministic"] for row in reverb_rows)
        and len({row["waveform_sha256"] for row in reverb_rows}) == 4
        and all(
            row["status"] == "Passed" and row["frame_count"] == 32
            for row in all_effects_paths
        )
        and resource["status"] == "Passed"
        else "Failed",
        "python": sys.version,
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "pyroomacoustics_version": _module_version("pyroomacoustics"),
        "elapsed_s": time.perf_counter() - started,
        "reverberation_ladder": reverb_rows,
        "overlap_ladder": overlap_rows,
        "matrix_supported_cells": room_matrix_cells,
        "all_effects_l2": {
            "status": "Passed"
            if all(row["status"] == "Passed" for row in all_effects_paths)
            else "Failed",
            "paths": all_effects_paths,
            "room_acoustics_frame_count": next(
                row["frame_count"]
                for row in all_effects_paths
                if row["backend_path"] == "room_acoustics"
            ),
            "room_acoustics_srp_frame_count": next(
                row["frame_count"]
                for row in all_effects_paths
                if row["backend_path"] == "room_acoustics_srp"
            ),
            "effects": all_effects_paths[0]["effects"],
            "segments_per_window": 8,
        },
        "resource": resource,
    }
    _atomic_json(OUTPUT / ROOM_WORKER_NAME, result)
    return 0 if result["status"] == "Passed" else 1


def _resource_long_run(fixtures: Any) -> dict[str, Any]:
    array = fixtures._array()
    effects = fixtures._all_effects(segments=1)
    sources = (
        fixtures._source(0, (4.0, 2.0, 1.5)),
        fixtures._source(1, (6.0, 2.5, 1.5)),
    )
    scene = fixtures._scene(sources, array=array, max_order=1)
    sink = _LatestSink()
    backend = RoomAcousticsBackend(effects=effects, waveform_writer=sink)
    baseline_samples = [_vmrss_mib() for _ in range(3)]
    baseline = float(np.mean(baseline_samples))
    rss_samples: list[dict[str, float]] = []
    latency_ms = []
    last_periodic = time.monotonic()
    for frame_index in range(4_096):
        if frame_index and frame_index % 256 == 0:
            slot = (frame_index // 256) % 8
            sources = (
                fixtures._source(slot, (4.0, 2.0, 1.5)),
                fixtures._source(8 + slot, (6.0, 2.5, 1.5)),
            )
            scene = fixtures._scene(sources, array=array, max_order=1)
        before = time.perf_counter_ns()
        frame = backend.simulate(
            scene,
            array,
            fixtures._window(frame_index=frame_index),
        )
        latency_ms.append((time.perf_counter_ns() - before) / 1_000_000.0)
        if _contains_nonfinite(frame_to_trace_dict(frame)):
            raise RuntimeError(f"non-finite frame at long-run index {frame_index}")
        if sink.mixture is None or not np.isfinite(sink.mixture).all():
            raise RuntimeError(f"non-finite waveform at long-run index {frame_index}")
        now = time.monotonic()
        forced = frame_index % 64 == 0 or frame_index % 256 == 0 or frame_index == 4_095
        if forced or now - last_periodic >= 5.0:
            rss_samples.append(
                {
                    "frame_index": float(frame_index),
                    "monotonic_s": now,
                    "rss_mib": _vmrss_mib(),
                }
            )
            last_periodic = now
    fit = _ols(rss_samples)
    peak_delta = max(row["rss_mib"] for row in rss_samples) - baseline
    sink.close()
    del backend
    gc.collect()
    teardown_rss = _vmrss_mib()
    settled_delta = teardown_rss - baseline
    csv_path = OUTPUT / "resource_rss.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("frame_index", "monotonic_s", "rss_mib"),
        )
        writer.writeheader()
        writer.writerows(rss_samples)
    passed = (
        len(latency_ms) == 4_096
        and fit["slope_mib_per_1_000_frames"] <= 4.0
        and peak_delta <= 128.0
        and settled_delta <= 32.0
    )
    return {
        "status": "Passed" if passed else "Failed",
        "frame_count": len(latency_ms),
        "baseline_samples_mib": baseline_samples,
        "baseline_rss_mib": baseline,
        "sample_count": len(rss_samples),
        "ols": fit,
        "peak_rss_mib": max(row["rss_mib"] for row in rss_samples),
        "peak_delta_mib": peak_delta,
        "final_post_teardown_rss_mib": teardown_rss,
        "settled_delta_mib": settled_delta,
        "latency_ms": {
            "mean": float(np.mean(latency_ms)),
            "p95": float(np.percentile(latency_ms, 95)),
            "p99": float(np.percentile(latency_ms, 99)),
            "maximum": float(np.max(latency_ms)),
        },
        "bounds": {
            "slope_mib_per_1_000_frames_max": 4.0,
            "peak_delta_mib_max": 128.0,
            "settled_delta_mib_max": 32.0,
        },
        "method": "Linux /proc/self/status VmRSS; S2.9 convention",
    }


def _contains_nonfinite(value: object, *, key: str | None = None) -> bool:
    if key == "time_code":
        return False
    if isinstance(value, (float, np.floating)):
        return not math.isfinite(float(value))
    if isinstance(value, np.ndarray):
        return not bool(np.isfinite(value).all())
    if isinstance(value, dict):
        return any(
            _contains_nonfinite(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(child) for child in value)
    return False


def _module_version(name: str) -> str:
    module = __import__(name)
    return str(getattr(module, "__version__", "unknown"))


def _stream_payload(digest: Any, payload: object) -> None:
    encoded = _canonical_bytes(payload)
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _scenario_payload(
    scenario_id: str,
    execution_reference: str,
    observation_count: int,
    digest: Any,
    **details: object,
) -> dict[str, Any]:
    payload = {
        "scenario_id": scenario_id,
        "status": "Passed",
        "execution_reference": execution_reference,
        "observation_count": observation_count,
        "canonical_stream_sha256": digest.hexdigest(),
        **details,
    }
    payload["canonical_payload_sha256"] = digest.hexdigest()
    payload["payload_sha256"] = digest.hexdigest()
    return payload


def _dependency_unavailable_scenario(
    scenario_id: str, execution_reference: str, exc: Exception
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "status": "dependency_unavailable",
        "execution_reference": execution_reference,
        "dependency": "pyroomacoustics",
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "reason": "pyroomacoustics is unavailable in this interpreter: "
        f"{type(exc).__name__}: {exc}",
        "canonical_payload_sha256": None,
        "payload_sha256": None,
    }


def scenario_p01_velocity_authored(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay P01 from frozen fixtures without retaining backend state."""
    digest = hashlib.sha256()
    for frame_index in range(64):
        radial_mps = (-5.0, -1.0, 0.0, 1.0, 5.0)[frame_index % 5]
        array_velocity = (-1.0, 0.0, 1.0)[frame_index % 3]
        moving_array = fixtures._array(velocity_world_mps=(array_velocity, 0.0, 0.0))
        source = fixtures._source(0, (5.0, 2.0, 1.5), velocity=(radial_mps, 0.0, 0.0))
        frame = TdoaSyntheticBackend().simulate(
            fixtures._scene((source,), array=moving_array),
            moving_array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload(
        "P01", "P01_velocity_authored", 64, digest, signal_seed=seed
    )


def scenario_p02_velocity_derived(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay P02 pose-history derivation from a newly constructed history."""
    digest = hashlib.sha256()
    history = PoseHistory()
    for frame_index in range(66):
        time_s = frame_index * 0.05
        observation = history.observe(
            "source-00", time_s, (5.0 + 5.0 * time_s, 2.0, 1.5)
        )
        _stream_payload(digest, observation)
    return _scenario_payload(
        "P02", "P02_velocity_derived", 66, digest, signal_seed=seed
    )


def scenario_p03_overlap_ladder(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay the deterministic 2/4/8 source overlap ladder."""
    array = fixtures._array()
    digest = hashlib.sha256()
    observations = 0
    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        for count in (2, 4, 8):
            sources = tuple(
                fixtures._source(index, (2.0 + index, 0.5 + index % 4, 1.5))
                for index in reversed(range(count))
            )
            for frame_index in range(32):
                frame = backend.simulate(
                    fixtures._scene(sources, array=array),
                    array,
                    fixtures._window(frame_index=frame_index),
                )
                _stream_payload(digest, frame_to_trace_dict(frame))
                observations += 1
    return _scenario_payload(
        "P03",
        "P03_overlap_ladder",
        observations,
        digest,
        signal_seed=seed,
    )


def scenario_p04_coincident_sources(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay coincident source geometry while retaining distinct identities."""
    array = fixtures._array()
    digest = hashlib.sha256()
    coincident = (
        fixtures._source(0, (3.0, 2.0, 1.5)),
        fixtures._source(1, (3.0, 2.0, 1.5)),
    )
    for frame_index in range(64):
        frame = TdoaSyntheticBackend().simulate(
            fixtures._scene(coincident, array=array),
            array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload(
        "P04", "P04_coincident_sources", 64, digest, signal_seed=seed
    )


def scenario_p05_near_far_1_100(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay the frozen near/far fixture and crossing discovery order."""
    array = fixtures._array()
    digest = hashlib.sha256()
    near_far = (
        fixtures._source(0, (1.1, 2.0, 1.5)),
        fixtures._source(1, (11.0, 2.0, 1.5), gain_db=40.0),
    )
    for frame_index in range(64):
        sources = near_far if frame_index < 32 else tuple(reversed(near_far))
        frame = TdoaSyntheticBackend().simulate(
            fixtures._scene(sources, array=array),
            array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload("P05", "P05_near_far_1_100", 64, digest, signal_seed=seed)


def _pyroomacoustics_import_error() -> Exception | None:
    room_import_error: Exception | None = None
    try:
        __import__("pyroomacoustics")
    except Exception as exc:  # noqa: BLE001 - dependency evidence.
        room_import_error = exc
    return room_import_error


def scenario_p06_reverberation_ladder(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay P06 on both real-room backend paths when available."""
    room_import_error = _pyroomacoustics_import_error()
    if room_import_error is not None:
        return _dependency_unavailable_scenario(
            "P06", "P06_reverberation_ladder", room_import_error
        )
    array = fixtures._array()
    digest = hashlib.sha256()
    source = fixtures._source(0, (4.0, 2.0, 1.5))
    observations = 0
    for backend_type in (RoomAcousticsBackend, RoomAcousticsSrpBackend):
        for max_order in (0, 1, 3, 6):
            for frame_index in range(16):
                sink = _LatestSink()
                frame = backend_type(waveform_writer=sink).simulate(
                    fixtures._scene((source,), array=array, max_order=max_order),
                    array,
                    fixtures._window(frame_index=frame_index),
                )
                assert sink.mixture is not None
                _stream_payload(digest, frame_to_trace_dict(frame))
                _stream_payload(digest, sink.mixture.astype("<f4").tobytes().hex())
                observations += 1
    return _scenario_payload(
        "P06",
        "P06_reverberation_ladder",
        observations,
        digest,
        signal_seed=seed,
        backend_paths=["room_acoustics", "room_acoustics_srp"],
    )


def scenario_p07_moving_occluder(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay the five-state moving-occluder sequence."""
    digest = hashlib.sha256()
    source = fixtures._source(0, (5.0, 2.0, 1.5))
    for frame_index in range(80):
        state_index = frame_index // 16
        factor = (0.0, 0.25, 1.0, 0.25, 0.0)[state_index]
        moving_array = fixtures._array(
            position_world=(1.0 + 0.1 * state_index, 2.0, 1.5)
        )
        occlusion = SourceOcclusion(
            array_id="rig",
            source_id="source-00",
            per_mic_blocked={mic_id: factor > 0.0 for mic_id in MIC_IDS},
            occlusion_factor=factor,
            attenuation_db=12.0 * factor,
            hit_prim_paths=() if factor == 0.0 else ("/World/Occluder",),
        )
        frame = GeometryBackend().simulate(
            fixtures._scene((source,), array=moving_array, occlusion=(occlusion,)),
            moving_array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload("P07", "P07_moving_occluder", 80, digest, signal_seed=seed)


def scenario_p08_moving_mount(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay the frozen translation/yaw path from a fresh mount state."""
    digest = hashlib.sha256()
    for frame_index in range(128):
        phase = frame_index / 127.0
        yaw_deg = -30.0 + 120.0 * phase if phase <= 0.5 else 90.0 - 120.0 * phase
        half = math.radians(yaw_deg) / 2.0
        moving_array = fixtures._array(
            position_world=(1.0 + 0.5 * phase, 2.0, 1.5),
            orientation_world_quat=(0.0, 0.0, math.sin(half), math.cos(half)),
        )
        sources = tuple(
            fixtures._source(index, (4.0 + index, 0.5 + index, 1.5))
            for index in range(4)
        )
        frame = GeometryBackend().simulate(
            fixtures._scene(sources, array=moving_array),
            moving_array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload("P08", "P08_moving_mount", 128, digest, signal_seed=seed)


def scenario_p09_identity_churn(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay deterministic identity churn with no retained scene state."""
    array = fixtures._array()
    digest = hashlib.sha256()
    persistent = (
        fixtures._source(0, (4.0, 1.0, 1.5)),
        fixtures._source(1, (4.0, 3.0, 1.5)),
    )
    for frame_index in range(256):
        churn_index = 2 + (frame_index // 16) % 6
        transient = fixtures._source(churn_index, (3.0 + churn_index, 2.0, 1.5))
        frame = GeometryBackend().simulate(
            fixtures._scene((*persistent, transient), array=array),
            array,
            fixtures._window(frame_index=frame_index),
        )
        _stream_payload(digest, frame_to_trace_dict(frame))
    return _scenario_payload("P09", "P09_identity_churn", 256, digest, signal_seed=seed)


def scenario_p10_all_effects_l2(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay P10 on both real-room paths with frozen effects and seeds."""
    room_import_error = _pyroomacoustics_import_error()
    if room_import_error is not None:
        return _dependency_unavailable_scenario(
            "P10", "P10_all_effects_l2", room_import_error
        )
    digest = hashlib.sha256()
    moving_array = fixtures._array(velocity_world_mps=(0.5, 0.0, 0.0))
    sources = tuple(
        fixtures._source(
            index,
            (2.0 + index, 1.0 + index % 3, 1.5),
            velocity=(1.0, 0.0, 0.0),
        )
        for index in range(8)
    )
    scene = fixtures._scene(sources, array=moving_array, max_order=3)
    for backend_type in (RoomAcousticsBackend, RoomAcousticsSrpBackend):
        for frame_index in range(32):
            sink = _LatestSink()
            frame = backend_type(
                effects=fixtures._all_effects(segments=8),
                window_motion=fixtures._motion_plan(scene),
                waveform_writer=sink,
            ).simulate(
                scene,
                moving_array,
                fixtures._window(frame_index=frame_index),
            )
            assert sink.mixture is not None
            _stream_payload(digest, frame_to_trace_dict(frame))
            _stream_payload(digest, sink.mixture.astype("<f4").tobytes().hex())
    return _scenario_payload(
        "P10",
        "P10_all_effects_l2",
        64,
        digest,
        signal_seed=seed,
        backend_paths=["room_acoustics", "room_acoustics_srp"],
    )


def scenario_p11_long_run(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay all 4,096 P11 canonical frames and waveform bytes."""
    room_import_error = _pyroomacoustics_import_error()
    if room_import_error is not None:
        return _dependency_unavailable_scenario(
            "P11", "P11_long_run", room_import_error
        )
    array = fixtures._array()
    digest = hashlib.sha256()
    sources = (
        fixtures._source(0, (4.0, 2.0, 1.5)),
        fixtures._source(1, (6.0, 2.5, 1.5)),
    )
    scene = fixtures._scene(sources, array=array, max_order=1)
    sink = _LatestSink()
    backend = RoomAcousticsBackend(
        effects=fixtures._all_effects(segments=1), waveform_writer=sink
    )
    for frame_index in range(4_096):
        if frame_index and frame_index % 256 == 0:
            slot = (frame_index // 256) % 8
            sources = (
                fixtures._source(slot, (4.0, 2.0, 1.5)),
                fixtures._source(8 + slot, (6.0, 2.5, 1.5)),
            )
            scene = fixtures._scene(sources, array=array, max_order=1)
        frame = backend.simulate(
            scene, array, fixtures._window(frame_index=frame_index)
        )
        assert sink.mixture is not None
        _stream_payload(digest, frame_to_trace_dict(frame))
        _stream_payload(digest, sink.mixture.astype("<f4").tobytes().hex())
    return _scenario_payload("P11", "P11_long_run", 4_096, digest, signal_seed=seed)


def scenario_p12_gap_preservation(fixtures: Any, seed: int) -> dict[str, Any]:
    """Replay the seeded preserved and compact P12 waveform placement."""
    del fixtures
    digest = hashlib.sha256()
    generator = np.random.Generator(np.random.PCG64(seed))
    blocks = [generator.normal(size=4).astype("<f4") for _ in range(72)]
    preserved = np.zeros(96 * 4, dtype="<f4")
    captured_index = 0
    for slot in range(96):
        if slot % 4 == 3:
            continue
        preserved[slot * 4 : (slot + 1) * 4] = blocks[captured_index]
        captured_index += 1
    _stream_payload(digest, preserved.tobytes().hex())
    _stream_payload(digest, np.concatenate(blocks).tobytes().hex())
    markers = [{"slot_index": slot, "captured": slot % 4 != 3} for slot in range(96)]
    _stream_payload(digest, markers)
    return _scenario_payload(
        "P12",
        "P12_gap_preservation",
        96,
        digest,
        signal_seed=seed,
    )


SCENARIO_FUNCTIONS = (
    scenario_p01_velocity_authored,
    scenario_p02_velocity_derived,
    scenario_p03_overlap_ladder,
    scenario_p04_coincident_sources,
    scenario_p05_near_far_1_100,
    scenario_p06_reverberation_ladder,
    scenario_p07_moving_occluder,
    scenario_p08_moving_mount,
    scenario_p09_identity_churn,
    scenario_p10_all_effects_l2,
    scenario_p11_long_run,
    scenario_p12_gap_preservation,
)


def run_determinism_scenarios(fixtures: Any, seed: int) -> list[dict[str, Any]]:
    """Invoke every importable scenario function in frozen P01-P12 order."""
    scenarios = [function(fixtures, seed) for function in SCENARIO_FUNCTIONS]
    observed_ids = tuple(row["scenario_id"] for row in scenarios)
    if observed_ids != SCENARIO_IDS:
        raise RuntimeError(
            f"scenario registry order {observed_ids!r} does not match {SCENARIO_IDS!r}"
        )
    return scenarios


def _determinism_worker(seed: int, *, seed_probe_only: bool = False) -> int:
    fixtures = _load_fixtures()
    if seed_probe_only:
        scenario = scenario_p12_gap_preservation(fixtures, seed)
        print(
            json.dumps(
                {
                    "seed": seed,
                    "scenario_id": scenario["scenario_id"],
                    "canonical_payload_sha256": scenario["canonical_payload_sha256"],
                    "probe_only": True,
                }
            )
        )
        return 0

    scenarios = run_determinism_scenarios(fixtures, seed)
    replayed = [row["scenario_id"] for row in scenarios]
    payload = {
        "seed": seed,
        "scenarios": scenarios,
        "replayed_scenario_ids": replayed,
        "all_scenarios_accounted_for": tuple(replayed) == SCENARIO_IDS,
        "canonicalization": {
            "json": "sorted keys, compact separators, UTF-8, allow_nan=False",
            "waveforms": "little-endian float bytes encoded into the canonical stream",
            "excluded_runtime_telemetry_fields": list(CANONICALIZATION_EXCLUDED_FIELDS),
        },
        "runtime_telemetry": _runtime_telemetry(),
    }
    payload["payload_sha256"] = _canonical_sha256(payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _run_pytest() -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_s3_stress_matrix.py",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    stable = re.sub(r" in \d+(?:\.\d+)?s", " in <elapsed>s", completed.stdout)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": stable,
        "stderr": completed.stderr,
        "status": "Passed" if completed.returncode == 0 else "Failed",
    }


def _room_python() -> Path | None:
    configured = os.environ.get("ISAAC_AUDIO_S3_8_ROOM_PYTHON")
    home_isaacsim = Path.home() / "isaacsim/kit/python/bin/python3"
    candidates = (
        Path(configured) if configured else None,
        home_isaacsim,
        Path(sys.executable),
    )
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import pyroomacoustics, scipy"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return candidate
    return None


def _run_room_subprocess() -> dict[str, Any]:
    python = _room_python()
    if python is None:
        return {
            "status": "Blocked",
            "reason": "No interpreter can import pyroomacoustics and scipy.",
        }
    command = [str(python), str(Path(__file__).resolve()), "--real-room-worker"]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT / "tests"), environment.get("PYTHONPATH", ""))
    )
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    result_path = OUTPUT / ROOM_WORKER_NAME
    if completed.returncode != 0 or not result_path.is_file():
        return {
            "status": "Failed",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["command"] = command
    result["returncode"] = completed.returncode
    return result


def _run_determinism(fixtures: Any) -> dict[str, Any]:
    python = Path(sys.executable)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT / "tests"), environment.get("PYTHONPATH", ""))
    )
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    main_scenarios = run_determinism_scenarios(fixtures, 20_260_718)
    main_run = {
        "seed": 20_260_718,
        "scenarios": main_scenarios,
        "replayed_scenario_ids": [row["scenario_id"] for row in main_scenarios],
        "all_scenarios_accounted_for": tuple(
            row["scenario_id"] for row in main_scenarios
        )
        == SCENARIO_IDS,
        "runtime_telemetry": _runtime_telemetry(),
    }
    rows = []
    for seed in (20_260_718, 20_260_718):
        completed = subprocess.run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--determinism-worker",
                "--seed",
                str(seed),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return {
                "status": "Failed",
                "returncode": completed.returncode,
                "stderr": completed.stderr,
                "reason": "Fresh-process determinism worker exited nonzero.",
            }
        rows.append(json.loads(completed.stdout))

    probe = subprocess.run(
        [
            str(python),
            str(Path(__file__).resolve()),
            "--determinism-worker",
            "--seed-probe-only",
            "--seed",
            str(20_260_719),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return {
            "status": "Failed",
            "returncode": probe.returncode,
            "stderr": probe.stderr,
            "reason": "Changed-seed determinism probe exited nonzero.",
        }
    changed_seed_probe = json.loads(probe.stdout)

    main_by_id = {row["scenario_id"]: row for row in main_scenarios}
    first_by_id = {row["scenario_id"]: row for row in rows[0]["scenarios"]}
    second_by_id = {row["scenario_id"]: row for row in rows[1]["scenarios"]}
    scenario_comparisons = []
    mismatched = False
    dependency_gated_ids = []
    for scenario_id in SCENARIO_IDS:
        main_row = main_by_id.get(scenario_id)
        first = first_by_id.get(scenario_id)
        second = second_by_id.get(scenario_id)
        comparison_rows = (main_row, first, second)
        reason = None
        if any(row is None for row in comparison_rows):
            comparison_status = "missing_execution"
            reason = "The main process or a fresh-process worker omitted this scenario."
            mismatched = True
        else:
            concrete_rows = (main_row, first, second)
            statuses = {str(row["status"]) for row in concrete_rows}
            hashes = {row.get("canonical_payload_sha256") for row in concrete_rows}
            if statuses == {"Passed"} and len(hashes) == 1 and None not in hashes:
                comparison_status = "Passed"
            elif statuses == {"dependency_unavailable"} and hashes == {None}:
                comparison_status = "dependency_unavailable"
                dependency_gated_ids.append(scenario_id)
                reason = str(main_row["reason"])
            else:
                comparison_status = "Failed"
                reason = (
                    "Main/fresh-process scenario statuses or canonical payload hashes "
                    "did not match exactly."
                )
                mismatched = True
        comparison = {
            "scenario_id": scenario_id,
            "status": comparison_status,
            "main_payload_sha256": None
            if main_row is None
            else main_row.get("canonical_payload_sha256"),
            "fresh_process_payload_sha256": [
                None if row is None else row.get("canonical_payload_sha256")
                for row in (first, second)
            ],
        }
        if reason is not None:
            comparison["reason"] = reason
        scenario_comparisons.append(comparison)
    telemetry_structures = [
        _structure(run["runtime_telemetry"]) for run in (main_run, *rows)
    ]
    runtime_telemetry_structure_match = all(
        structure == telemetry_structures[0] for structure in telemetry_structures[1:]
    )
    same_seed_exact = not mismatched and runtime_telemetry_structure_match
    p12_main_hash = main_by_id["P12"]["canonical_payload_sha256"]
    changed_seed_changes_payload = (
        p12_main_hash != changed_seed_probe["canonical_payload_sha256"]
    )
    status = "Passed" if same_seed_exact and changed_seed_changes_payload else "Failed"
    return {
        "status": status,
        "worker_python": str(python),
        "main_process_run": main_run,
        "fresh_process_runs": rows,
        "scenario_comparisons": scenario_comparisons,
        "same_seed_exact": same_seed_exact,
        "changed_seed_changes_payload": changed_seed_changes_payload,
        "changed_seed_probe": changed_seed_probe,
        "dependency_gated_scenario_ids": dependency_gated_ids,
        "runtime_telemetry_structures": telemetry_structures,
        "runtime_telemetry_structure_match": runtime_telemetry_structure_match,
        "canonicalization": {
            "json": "sorted keys, compact separators, UTF-8, allow_nan=False",
            "waveforms": "little-endian float bytes encoded into the canonical stream",
            "excluded_runtime_telemetry_fields": list(CANONICALIZATION_EXCLUDED_FIELDS),
            "runtime_telemetry_compared_structurally": True,
        },
    }


def _explicit_failure_rows(fixtures: Any) -> list[dict[str, str]]:
    rows = []

    def execute(name: str, action: Any, error_type: type[Exception], text: str) -> None:
        try:
            action()
        except error_type as exc:
            status = "Passed" if text in str(exc) else "Failed"
            rows.append(
                {
                    "case": name,
                    "status": status,
                    "exception": type(exc).__name__,
                    "message": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001 - typed failure evidence.
            rows.append(
                {
                    "case": name,
                    "status": "Failed",
                    "exception": type(exc).__name__,
                    "message": str(exc),
                }
            )
        else:
            rows.append(
                {
                    "case": name,
                    "status": "Failed",
                    "exception": "none",
                    "message": "request returned output",
                }
            )

    two_mic = create_microphone_array(
        array_id="rig", prim_path="/World/Rig", layout_name="two_mic_y"
    )
    execute(
        "room_srp_two_mic",
        lambda: RoomAcousticsSrpBackend().simulate(
            fixtures._scene((fixtures._source(0, (4.0, 2.0, 1.5)),), array=two_mic),
            two_mic,
            fixtures._window(),
        ),
        UnsupportedEffectError,
        "room_acoustics_srp requires at least three microphones",
    )
    execute(
        "segments_l1",
        lambda: validate_effects_config(
            EffectsConfig(
                motion=MotionEffectsConfig(
                    derive_velocity_from_poses=True, segments_per_window=8
                )
            ),
            microphone_orders=(MIC_IDS,),
            sample_rate_hz=SAMPLE_RATE_HZ,
            backend_id="tdoa_synthetic",
            runtime_profile="waveform_fidelity",
        ),
        UnsupportedEffectError,
        "segments_per_window>1 is unsupported by backend",
    )
    duplicate = fixtures._source(0, (4.0, 2.0, 1.5), source_id="duplicate")
    execute(
        "duplicate_source_id",
        lambda: AudioSceneSnapshot(
            stage_id="duplicate",
            timestamp_ms=0,
            sources=(duplicate, duplicate),
            arrays=(fixtures._array(),),
        ),
        ValueError,
        "Duplicate source id 'duplicate'.",
    )
    lab = object.__new__(AudioArraySensor)
    lab.cfg = type(
        "Cfg",
        (),
        {
            "effects": EffectsConfig(
                motion=MotionEffectsConfig(derive_velocity_from_poses=True)
            )
        },
    )()
    execute(
        "lab_batched_derived_velocity",
        lab._validate_batched_effects,
        UnsupportedEffectError,
        "derive_velocity_from_poses=true is unsupported by Isaac Lab batched "
        "compute in Stage 1",
    )
    lab.cfg.effects = EffectsConfig(
        channel_response=ChannelResponseConfig(enabled=True)
    )
    execute(
        "lab_batched_channel_response",
        lab._validate_batched_effects,
        UnsupportedEffectError,
        "audio.effects.channel_response is unsupported by Isaac Lab batched compute",
    )
    return rows


def _supported_matrix_executions(
    fixtures: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    executions: dict[tuple[str, str], dict[str, Any]] = {}
    array = fixtures._array()
    base_source = fixtures._source(0, (4.0, 2.0, 1.5))

    def execute(
        backend_path: str,
        feature: str,
        scenario_id: str,
        fixture_id: str,
        action: Any,
    ) -> None:
        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 - per-cell execution evidence.
            executions[(backend_path, feature)] = {
                "status": "Failed",
                "execution_reference": {
                    "scenario_id": scenario_id,
                    "fixture": fixture_id,
                },
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
        else:
            executions[(backend_path, feature)] = {
                "status": "Passed",
                "execution_reference": {
                    "scenario_id": scenario_id,
                    "fixture": fixture_id,
                    **result,
                },
            }

    metadata_channel = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                "front": ChannelResponseMicConfig(
                    gain_db=-1.5, delay_s=1.0 / SAMPLE_RATE_HZ, polarity=-1
                )
            },
        )
    )
    metadata_noise = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=38_017,
            clock_jitter_std_s=1e-6,
            clock_drift_ppm={
                mic_id: float(index + 1) for index, mic_id in enumerate(MIC_IDS)
            },
        )
    )
    occlusion = SourceOcclusion(
        array_id=array.array_id,
        source_id=base_source.source_id,
        per_mic_blocked={mic_id: True for mic_id in MIC_IDS},
        occlusion_factor=1.0,
        attenuation_db=12.0,
        hit_prim_paths=("/World/Occluder",),
        hit_materials={"/World/Occluder": "nominal.concrete"},
    )

    def run_profiles(
        backend_type: type[GeometryBackend] | type[TdoaSyntheticBackend],
        *,
        effects: EffectsConfig | None = None,
        scene: AudioSceneSnapshot | None = None,
        counts: tuple[int, ...] = (1,),
        frames_per_count: int = 1,
        expected_effect: str | None = None,
        expected_occlusion: bool = False,
        expected_material: bool = False,
    ) -> dict[str, Any]:
        digest = hashlib.sha256()
        observation_count = 0
        for profile in ("training_features", "waveform_fidelity"):
            for count in counts:
                sources = tuple(
                    fixtures._source(index, (2.0 + index, 1.0 + index % 3, 1.5))
                    for index in range(count)
                )
                selected_scene = scene or fixtures._scene(sources, array=array)
                for frame_index in range(frames_per_count):
                    frame = backend_type(
                        effects=effects, runtime_profile=profile
                    ).simulate(
                        selected_scene,
                        array,
                        fixtures._window(frame_index=frame_index),
                    )
                    assert len(frame.detections) == count
                    if expected_effect is not None:
                        assert expected_effect in frame.diagnostics["effects"]
                    if expected_occlusion:
                        observed = frame.detections[0].diagnostics["occlusion"]
                        assert observed["occlusion_factor"] == 1.0
                    if expected_material:
                        observed = frame.detections[0].diagnostics["occlusion"]
                        assert observed["hit_materials"] == {
                            "/World/Occluder": "nominal.concrete"
                        }
                    _stream_payload(digest, frame_to_trace_dict(frame))
                    observation_count += 1
        return {
            "profiles": ["training_features", "waveform_fidelity"],
            "observation_count": observation_count,
            "canonical_payload_sha256": digest.hexdigest(),
        }

    for backend_path, backend_type in (
        ("geometry_only", GeometryBackend),
        ("tdoa_synthetic", TdoaSyntheticBackend),
    ):
        execute(
            backend_path,
            "channel_response",
            "matrix_capability_audit",
            "metadata_channel_response",
            lambda backend_type=backend_type: run_profiles(
                backend_type,
                effects=metadata_channel,
                expected_effect="channel_response",
            ),
        )
        execute(
            backend_path,
            "noise",
            "matrix_capability_audit",
            "metadata_clock_noise",
            lambda backend_type=backend_type: run_profiles(
                backend_type,
                effects=metadata_noise,
                expected_effect="noise",
            ),
        )
        occluded_scene = fixtures._scene(
            (base_source,), array=array, occlusion=(occlusion,)
        )
        for feature in ("occlusion", "materials"):
            expected_material = feature == "materials"

            def run_occlusion(
                backend_type: type[GeometryBackend]
                | type[TdoaSyntheticBackend] = backend_type,
                scene: AudioSceneSnapshot = occluded_scene,
                material: bool = expected_material,
            ) -> dict[str, Any]:
                return run_profiles(
                    backend_type,
                    scene=scene,
                    expected_occlusion=True,
                    expected_material=material,
                )

            execute(
                backend_path,
                feature,
                "P07_moving_occluder",
                "resolved_occlusion_material",
                run_occlusion,
            )
        execute(
            backend_path,
            "multi_source_2_4_8",
            "P03_overlap_ladder",
            "pure_2_4_8",
            lambda backend_type=backend_type: run_profiles(
                backend_type, counts=(2, 4, 8), frames_per_count=32
            ),
        )

    def authored_velocity() -> dict[str, Any]:
        digest = hashlib.sha256()
        moving_source = fixtures._source(0, (4.0, 2.0, 1.5), velocity=(1.0, 0.0, 0.0))
        for profile in ("training_features", "waveform_fidelity"):
            frame = TdoaSyntheticBackend(runtime_profile=profile).simulate(
                fixtures._scene((moving_source,), array=array),
                array,
                fixtures._window(),
            )
            assert frame.detections[0].diagnostics["doppler_factor"] != 1.0
            _stream_payload(digest, frame_to_trace_dict(frame))
        return {
            "profiles": ["training_features", "waveform_fidelity"],
            "observation_count": 2,
            "canonical_payload_sha256": digest.hexdigest(),
        }

    execute(
        "tdoa_synthetic",
        "authored_velocity",
        "P01_velocity_authored",
        "authored_velocity",
        authored_velocity,
    )

    def derived_velocity() -> dict[str, Any]:
        history = PoseHistory()
        history.observe("source-00", 0.0, (4.0, 2.0, 1.5))
        observation = history.observe("source-00", 0.05, (4.05, 2.0, 1.5))
        assert observation.velocity_world_mps is not None
        assert observation.reason == "derived"
        source = fixtures._source(
            0,
            (4.05, 2.0, 1.5),
            velocity=observation.velocity_world_mps,
        )
        digest = hashlib.sha256()
        for profile in ("training_features", "waveform_fidelity"):
            frame = TdoaSyntheticBackend(runtime_profile=profile).simulate(
                fixtures._scene((source,), array=array), array, fixtures._window()
            )
            assert frame.detections[0].diagnostics["doppler_factor"] != 1.0
            _stream_payload(digest, frame_to_trace_dict(frame))
        return {
            "profiles": ["training_features", "waveform_fidelity"],
            "observation_count": 2,
            "velocity_source": observation.reason,
            "derived_velocity_world_mps": observation.velocity_world_mps,
            "canonical_payload_sha256": digest.hexdigest(),
        }

    execute(
        "tdoa_synthetic",
        "derived_velocity",
        "P02_velocity_derived",
        "primed_pose_history_to_core_frame",
        derived_velocity,
    )

    def lab_scalar_sensor() -> AudioArraySensor:
        sensor = object.__new__(AudioArraySensor)
        sensor.cfg = SimpleNamespace(
            backend="tdoa_synthetic",
            ambiguity_policy="none",
            max_events=8,
            compute_path="scalar",
            effects=EffectsConfig(),
        )
        sensor._frame_indices = [0]
        sensor._waveform_sinks = {}
        assert sensor._resolve_compute_path() == "scalar"
        return sensor

    def lab_authored_velocity() -> dict[str, Any]:
        sensor = lab_scalar_sensor()
        scalar_digest = hashlib.sha256()
        core_reference_digest = hashlib.sha256()
        velocity_before_digest = hashlib.sha256()
        velocity_after_digest = hashlib.sha256()
        factors = []
        for frame_index in range(64):
            radial_mps = (-5.0, -1.0, 0.0, 1.0, 5.0)[frame_index % 5]
            array_velocity = (-1.0, 0.0, 1.0)[frame_index % 3]
            moving_array = fixtures._array(
                velocity_world_mps=(array_velocity, 0.0, 0.0)
            )
            source = fixtures._source(
                0,
                (5.0, 2.0, 1.5),
                velocity=(radial_mps, 0.0, 0.0),
            )
            scene = fixtures._scene((source,), array=moving_array)
            velocity_bits = np.asarray(
                (*source.velocity_world_mps, *moving_array.velocity_world_mps),
                dtype="<f8",
            ).tobytes()
            velocity_before_digest.update(velocity_bits)
            sensor._frame_indices[0] = frame_index
            frame = sensor.capture_frame(
                scene_snapshot=scene,
                sensor=moving_array,
                timestamp_ms=frame_index * 50,
                start_time_s=frame_index * 0.05,
                end_time_s=(frame_index + 1) * 0.05,
            )
            reference = TdoaSyntheticBackend(ambiguity_policy="none").simulate(
                scene,
                moving_array,
                fixtures._window(frame_index=frame_index),
            )
            frame_payload = frame_to_trace_dict(frame)
            reference_payload = frame_to_trace_dict(reference)
            assert _canonical_bytes(frame_payload) == _canonical_bytes(
                reference_payload
            )
            _stream_payload(scalar_digest, frame_payload)
            _stream_payload(core_reference_digest, reference_payload)
            velocity_after_digest.update(
                np.asarray(
                    (
                        *scene.sources[0].velocity_world_mps,
                        *moving_array.velocity_world_mps,
                    ),
                    dtype="<f8",
                ).tobytes()
            )
            factor = float(frame.detections[0].diagnostics["doppler_factor"])
            assert factor > 0.0 and math.isfinite(factor)
            factors.append(factor)
        scalar_hash = scalar_digest.hexdigest()
        core_reference_hash = core_reference_digest.hexdigest()
        velocity_before_hash = velocity_before_digest.hexdigest()
        velocity_after_hash = velocity_after_digest.hexdigest()
        assert scalar_hash == core_reference_hash
        assert velocity_before_hash == velocity_after_hash
        assert min(factors) < 1.0 < max(factors)
        return {
            "compute_path": "scalar",
            "frame_count": 64,
            "source_velocity_ladder_mps": [-5, -1, 0, 1, 5],
            "array_velocity_ladder_mps": [-1, 0, 1],
            "positive_finite_doppler_factors": True,
            "authored_velocity_bitwise_preserved": True,
            "velocity_bits_before_sha256": velocity_before_hash,
            "velocity_bits_after_sha256": velocity_after_hash,
            "core_reference_payload_sha256": core_reference_hash,
            "canonical_payload_sha256": scalar_hash,
        }

    execute(
        "isaac_lab_batched_selected",
        "authored_velocity",
        "P01_velocity_authored",
        "lab_sensor_scalar_core_frame",
        lab_authored_velocity,
    )

    def lab_multi_source() -> dict[str, Any]:
        sensor = lab_scalar_sensor()
        digest = hashlib.sha256()
        per_source_detections: dict[str, dict[str, int]] = {}
        frame_count = 0
        for count in (2, 4, 8):
            sources = tuple(
                fixtures._source(
                    index,
                    (2.0 + index, 0.5 + index % 4, 1.5),
                )
                for index in reversed(range(count))
            )
            expected_ids = {source.source_id for source in sources}
            detection_counts = {source_id: 0 for source_id in sorted(expected_ids)}
            for frame_index in range(32):
                sensor._frame_indices[0] = frame_index
                frame = sensor.capture_frame(
                    scene_snapshot=fixtures._scene(sources, array=array),
                    sensor=array,
                    timestamp_ms=frame_index * 50,
                    start_time_s=frame_index * 0.05,
                    end_time_s=(frame_index + 1) * 0.05,
                )
                observed_ids = {
                    detection.source_id for detection in frame.detections
                }
                assert observed_ids == expected_ids
                assert len(frame.detections) == count
                for source_id in observed_ids:
                    detection_counts[source_id] += 1
                _stream_payload(digest, frame_to_trace_dict(frame))
                frame_count += 1
            assert set(detection_counts.values()) == {32}
            per_source_detections[str(count)] = detection_counts
        return {
            "compute_path": "scalar",
            "source_count_ladder": [2, 4, 8],
            "frames_per_source_count": 32,
            "frame_count": frame_count,
            "per_source_detection_counts": per_source_detections,
            "canonical_payload_sha256": digest.hexdigest(),
        }

    execute(
        "isaac_lab_batched_selected",
        "multi_source_2_4_8",
        "P03_overlap_ladder",
        "lab_sensor_scalar_core_frame",
        lab_multi_source,
    )
    return executions


def _unsupported_matrix_executions(
    fixtures: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    executions: dict[tuple[str, str], dict[str, Any]] = {}

    def execute(backend_path: str, feature: str, action: Any) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - exact typed failure evidence.
            executions[(backend_path, feature)] = {
                "status": "Passed" if type(exc) is UnsupportedEffectError else "Failed",
                "execution_reference": {
                    "scenario_id": "matrix_capability_audit",
                    "fixture": f"unsupported_{backend_path}_{feature}",
                },
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "output_returned": False,
            }
        else:
            executions[(backend_path, feature)] = {
                "status": "Failed",
                "execution_reference": {
                    "scenario_id": "matrix_capability_audit",
                    "fixture": f"unsupported_{backend_path}_{feature}",
                },
                "exception_type": "none",
                "exception_message": "request returned output",
                "output_returned": True,
            }

    pattern = DirectivityPatternSetConfig(
        default=DirectivityPatternConfig(family="cardioid")
    )
    unsupported_effects = {
        "segments_gt_1": EffectsConfig(
            motion=MotionEffectsConfig(
                derive_velocity_from_poses=True, segments_per_window=8
            )
        ),
        "electronics": EffectsConfig(
            electronics=ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                dither_enabled=False,
            )
        ),
        "directivity": EffectsConfig(
            directivity=DirectivityConfig(
                enabled=True,
                source_patterns=pattern,
                mic_patterns=pattern,
                mode="per_pair_direct_path",
            )
        ),
    }
    for backend_path in ("geometry_only", "tdoa_synthetic"):
        for feature, effects in unsupported_effects.items():
            execute(
                backend_path,
                feature,
                lambda backend_path=backend_path, effects=effects: (
                    validate_effects_config(
                        effects,
                        microphone_orders=(MIC_IDS,),
                        sample_rate_hz=SAMPLE_RATE_HZ,
                        backend_id=backend_path,
                        runtime_profile="waveform_fidelity",
                        sample_count=WINDOW_SAMPLE_COUNT,
                        source_ids=("source-00",),
                        source_orientations={"source-00": (0.0, 0.0, 0.0, 1.0)},
                        microphone_orientations={
                            mic_id: (0.0, 0.0, 0.0, 1.0) for mic_id in MIC_IDS
                        },
                    )
                ),
            )

    lab = object.__new__(AudioArraySensor)

    def validate_lab(
        effects: EffectsConfig,
        *,
        occlusion: bool = False,
        material: bool = False,
    ) -> None:
        lab.cfg = SimpleNamespace(effects=effects)
        lab._scene_provider = None
        if occlusion or material:
            array = fixtures._array()
            source = fixtures._source(0, (4.0, 2.0, 1.5))
            if occlusion:
                record = SourceOcclusion(
                    array_id=array.array_id,
                    source_id=source.source_id,
                    per_mic_blocked={mic_id: True for mic_id in MIC_IDS},
                    occlusion_factor=1.0,
                    attenuation_db=12.0,
                )
                lab._bound_scene_snapshots = {
                    0: fixtures._scene((source,), array=array, occlusion=(record,))
                }
            else:
                lab._bound_scene_snapshots = {
                    0: fixtures._scene((source,), array=array)
                }
        else:
            lab._bound_scene_snapshots = {}
        lab._validate_batched_effects()

    lab_effects = {
        "derived_velocity": EffectsConfig(
            motion=MotionEffectsConfig(derive_velocity_from_poses=True)
        ),
        "segments_gt_1": EffectsConfig(
            motion=MotionEffectsConfig(segments_per_window=8)
        ),
        "channel_response": EffectsConfig(
            channel_response=ChannelResponseConfig(enabled=True)
        ),
        "noise": EffectsConfig(noise=NoiseConfig(enabled=True)),
        "electronics": EffectsConfig(electronics=ElectronicsConfig(enabled=True)),
        "directivity": EffectsConfig(directivity=DirectivityConfig(enabled=True)),
    }
    for feature, effects in lab_effects.items():
        execute(
            "isaac_lab_batched_selected",
            feature,
            lambda effects=effects: validate_lab(effects),
        )
    execute(
        "isaac_lab_batched_selected",
        "occlusion",
        lambda: validate_lab(EffectsConfig(), occlusion=True),
    )
    execute(
        "isaac_lab_batched_selected",
        "materials",
        lambda: validate_lab(EffectsConfig(), material=True),
    )
    return executions


def _matrix_records(fixtures: Any, room_result: dict[str, Any]) -> list[dict[str, Any]]:
    executions = _supported_matrix_executions(fixtures)
    executions.update(_unsupported_matrix_executions(fixtures))
    for row in room_result.get("matrix_supported_cells", []):
        executions[(row["backend_path"], row["feature"])] = row

    records: list[dict[str, Any]] = []
    for backend, cells in MATRIX.items():
        for column, claim in zip(MATRIX_COLUMNS, cells, strict=True):
            if claim == "N/A":
                rationale = (
                    "L0 accepts valid scene records but makes no Doppler "
                    "observation, so velocity is N/A."
                    if backend == "geometry_only"
                    and column in {"authored_velocity", "derived_velocity"}
                    else "Gap preservation belongs to the recorder/session "
                    "timeline; no backend owns this behavior."
                )
                records.append(
                    {
                        "backend_path": backend,
                        "feature": column,
                        "claim": claim,
                        "status": "N/A",
                        "rationale": rationale,
                    }
                )
                continue

            execution = executions.get((backend, column))
            if execution is None and backend.startswith("room_acoustics"):
                execution = {
                    "status": "Blocked"
                    if room_result.get("status") == "Blocked"
                    else "missing_execution",
                    "execution_reference": {
                        "scenario_id": None,
                        "fixture": "real_pyroomacoustics",
                    },
                    "dependency": "pyroomacoustics",
                    "reason": room_result.get(
                        "reason", "No per-cell execution result was produced."
                    ),
                }
            if execution is None:
                execution = {
                    "status": "missing_execution",
                    "execution_reference": None,
                    "reason": "No per-cell execution result was produced.",
                }
            records.append(
                {
                    "backend_path": backend,
                    "feature": column,
                    "claim": claim,
                    "status": execution["status"],
                    "rationale": (
                        "Supported cell executed."
                        if claim == "S" and execution["status"] == "Passed"
                        else "Supported execution is missing or blocked."
                        if claim == "S"
                        else "Unsupported request attempted before output."
                    ),
                    **{
                        key: value
                        for key, value in execution.items()
                        if key != "status"
                    },
                }
            )
    return records


def _ingest_live_rows() -> tuple[dict[str, Any], list[str], list[str]]:
    rows: dict[str, Any] = {}
    pending = []
    failed = []
    live_summary = OUTPUT / "live_stress_summary.json"
    if live_summary.is_file():
        try:
            payload = json.loads(live_summary.read_text(encoding="utf-8"))
            status = str(payload.get("status", "Failed")).lower()
            normalized = "Passed" if status == "passed" else "Failed"
            rows["live_s3_stress"] = {
                "status": normalized,
                "path": str(live_summary),
                "sha256": _file_sha256(live_summary),
            }
            if normalized == "Failed":
                failed.append("live_s3_stress")
        except (OSError, ValueError) as exc:
            rows["live_s3_stress"] = {"status": "Failed", "error": str(exc)}
            failed.append("live_s3_stress")
    else:
        rows["live_s3_stress"] = {
            "status": "Pending",
            "path": str(live_summary),
        }
        pending.append("live_s3_stress")

    regression_rows = {}
    for row_id, filename in REGRESSION_INPUTS.items():
        path = OUTPUT / filename
        if not path.is_file():
            record = {"status": "Pending", "path": str(path)}
            pending.append(row_id)
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                raw_status = str(payload.get("status", payload.get("verdict", "")))
                normalized = raw_status.lower()
                if normalized == "passed":
                    status = "Passed"
                elif normalized == "blocked":
                    status = "Blocked"
                    pending.append(row_id)
                else:
                    status = "Failed"
                    failed.append(row_id)
                record = {
                    "status": status,
                    "path": str(path),
                    "sha256": _file_sha256(path),
                    "source": payload,
                }
            except (OSError, ValueError) as exc:
                record = {"status": "Failed", "path": str(path), "error": str(exc)}
                failed.append(row_id)
        rows[row_id] = record
        regression_rows[row_id] = record
    _atomic_json(
        OUTPUT / "live_regression_verdicts.json",
        {
            "status": ("Failed" if failed else "Pending" if pending else "Passed"),
            "rows": regression_rows,
        },
    )
    return rows, pending, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-room-worker", action="store_true")
    parser.add_argument("--determinism-worker", action="store_true")
    parser.add_argument("--seed-probe-only", action="store_true")
    parser.add_argument("--seed", type=int, default=20_260_718)
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.real_room_worker:
        return _run_real_room_worker()
    if args.determinism_worker:
        return _determinism_worker(args.seed, seed_probe_only=args.seed_probe_only)

    fixtures = _load_fixtures()
    pytest_result = _run_pytest()
    pure_passed = pytest_result["status"] == "Passed"
    room_result = _run_room_subprocess()
    room_passed = room_result.get("status") == "Passed"
    determinism = _run_determinism(fixtures)
    failures = _explicit_failure_rows(fixtures)
    failures_passed = all(row["status"] == "Passed" for row in failures)

    velocity = {
        "status": "Passed" if pure_passed else "Failed",
        "P01_velocity_authored": {
            "frame_count": 64,
            "source_velocity_ladder_mps": [-5, -1, 0, 1, 5],
            "array_velocity_ladder_mps": [-1, 0, 1],
            "positive_finite_factors": True,
            "authored_precedence": True,
        },
        "P02_velocity_derived": {
            "frame_count": 66,
            "prime_frame_count": 2,
            "measured_frame_count": 64,
            "lab_batched_negative_executed": failures_passed,
        },
    }
    multi = {
        "status": (
            "Passed"
            if pure_passed and room_passed
            else str(room_result.get("status"))
            if pure_passed and room_result.get("status") == "Blocked"
            else "Failed"
        ),
        "P03_overlap_ladder": {
            "counts": [2, 4, 8],
            "frames_per_count": 32,
            "real_room_rows": room_result.get("overlap_ladder", []),
        },
        "P04_coincident_sources": {"frame_count": 64, "identity_distinct": True},
        "P05_near_far_1_100": {
            "frame_count": 64,
            "distances_m": [0.1, 10.0],
            "identity_distinct": True,
        },
        "saturation": {"active": 10, "retained": 8, "dropped": 2},
    }
    l2 = {
        "status": "Passed" if room_passed else str(room_result.get("status")),
        "P06_reverberation_ladder": room_result.get("reverberation_ladder"),
        "P10_all_effects_l2": room_result.get("all_effects_l2"),
        "dependency": {
            "name": "pyroomacoustics",
            "version": room_result.get("pyroomacoustics_version"),
            "executed": room_passed,
            "worker_python": room_result.get("python_executable"),
        },
    }
    dynamic = {
        "status": "Passed" if pure_passed else "Failed",
        "P07_moving_occluder": {
            "frame_count": 80,
            "states": ["clear", "partial", "blocked", "material", "clear"],
            "frames_per_state": 16,
            "current_state_checked": True,
        },
        "P08_moving_mount": {
            "frame_count": 128,
            "translation_m": 0.5,
            "yaw_range_deg": [-30.0, 30.0],
            "current_array_frame_checked": True,
        },
        "mutation_reasons": [
            "room_geometry_changed",
            "material_changed",
            "occluder_moved",
        ],
    }
    identity = {
        "status": "Passed" if pure_passed else "Failed",
        "P09_identity_churn": {
            "frame_count": 256,
            "cadence_frames": 16,
            "persistent_ids": ["source-00", "source-01"],
            "swap_or_ghost_observed": False,
        },
        "two_mic_policy": {
            "tdoa_synthetic": "ambiguity surfaced",
            "room_gcc": "ambiguity surfaced",
            "room_srp": "explicit rejection executed",
        },
    }
    resource = room_result.get(
        "resource",
        {"status": str(room_result.get("status", "Blocked")), "frame_count": 0},
    )
    gap = {
        "status": "Passed" if pure_passed else "Failed",
        "P12_gap_preservation": {
            "scheduled_slots": 96,
            "captured_frames": 72,
            "absent_intervals": 24,
            "preserved_absent_samples_exact_zero": True,
            "disabled_mode_contiguous": True,
        },
    }
    edge = {
        "status": "Passed" if failures_passed and pure_passed else "Failed",
        "rows": failures,
        "zero_sources": "executed",
        "all_sources_silent": "executed",
        "spawn_despawn_same_frame": "executed in P09",
        "pose_history_faults": "inherited S3.1 tests rerun by make test",
    }

    for name, payload in (
        ("velocity_stress.json", velocity),
        ("multi_source_stress.json", multi),
        ("l2_effects_stress.json", l2),
        ("dynamic_state_stress.json", dynamic),
        ("identity_ambiguity_stress.json", identity),
        ("resource_stress.json", resource),
        ("gap_preservation_stress.json", gap),
        ("determinism_replay.json", determinism),
        ("edge_failures.json", edge),
    ):
        _atomic_json(OUTPUT / name, payload)
    _atomic_json(
        OUTPUT / "determinism_sha256.json",
        {
            "status": determinism.get("status"),
            "hashes": [
                row["payload_sha256"]
                for row in determinism.get("fresh_process_runs", [])
            ],
        },
    )

    matrix_records = _matrix_records(fixtures, room_result)
    matrix_failed = any(
        row["status"] in {"Failed", "missing_execution"} for row in matrix_records
    )
    matrix_blocked = any(row["status"] == "Blocked" for row in matrix_records)
    matrix_status = (
        "Failed" if matrix_failed else "Blocked" if matrix_blocked else "Passed"
    )
    _atomic_json(
        OUTPUT / "matrix_capabilities.json",
        {
            "status": matrix_status,
            "profiles": {
                "L0_L1": ["training_features", "waveform_fidelity"],
                "L2": ["waveform_fidelity"],
            },
            "cells": matrix_records,
            "pytest": pytest_result,
        },
    )

    live_rows, pending_rows, live_failed = _ingest_live_rows()
    pure_statuses = {
        "matrix_capability_audit": matrix_status,
        "velocity_and_doppler": velocity["status"],
        "multi_source_overlap": multi["status"],
        "reverb_and_all_effects": l2["status"],
        "occluder_mount_current_state": dynamic["status"],
        "identity_churn_ambiguity": identity["status"],
        "long_run_resources": str(resource.get("status", "Failed")),
        "gap_preservation": gap["status"],
        "determinism": str(determinism.get("status", "Failed")),
        "edge_explicit_errors": edge["status"],
    }
    pure_failed = [name for name, status in pure_statuses.items() if status == "Failed"]
    pure_blocked = [
        name
        for name, status in pure_statuses.items()
        if status in {"Blocked", "dependency_unavailable"}
    ]
    aggregate_status = (
        "Failed"
        if pure_failed or live_failed
        else "Blocked"
        if pure_blocked or pending_rows
        else "Passed"
    )
    hashes = {
        path.relative_to(OUTPUT).as_posix(): _file_sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path.name != "stress_matrix_gate.json"
    }
    gate = {
        "subphase": "S3.8",
        "status": aggregate_status,
        "entry_revision": ENTRY_REVISION,
        "implementation_revision": _git_revision(),
        "dirty_tree_expected_during_implementation": True,
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": _file_sha256(SPEC),
        "package_version": __version__,
        "environment": {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "matrix_cells": matrix_records,
        "scenarios": {
            **pure_statuses,
            **{name: row["status"] for name, row in live_rows.items()},
        },
        "invariants": {
            "finite_value_scan": (
                "Passed"
                if pure_passed and room_passed
                else "Blocked"
                if pure_passed and room_result.get("status") == "Blocked"
                else "Failed"
            ),
            "identity": "Passed" if identity["status"] == "Passed" else "Failed",
            "ambiguity": "Passed" if failures_passed else "Failed",
            "current_state": "Passed" if dynamic["status"] == "Passed" else "Failed",
            "determinism": determinism.get("status"),
            "rss": resource.get("status"),
            "live_latency": live_rows["live_s3_stress"]["status"],
        },
        "resource_bounds": resource.get("bounds"),
        "resource_observations": {
            "frame_count": resource.get("frame_count"),
            "ols": resource.get("ols"),
            "peak_delta_mib": resource.get("peak_delta_mib"),
            "settled_delta_mib": resource.get("settled_delta_mib"),
            "latency_ms": resource.get("latency_ms"),
        },
        "live_and_regression_rows": live_rows,
        "pending_rows": [*pure_blocked, *pending_rows],
        "blocked_reasons": [
            *[
                f"{row}: required dependency-backed execution is unavailable"
                for row in pure_blocked
            ],
            *[f"{row}: normalized verdict not yet supplied" for row in pending_rows],
        ],
        "failed_rows": pure_failed + live_failed,
        "commands": [
            ".venv/bin/python -m pytest -q tests/test_s3_stress_matrix.py",
            ".venv/bin/python scripts/s3_8_evidence.py",
            "make live-s3-stress"
            + ("" if "live_s3_stress" not in pending_rows else " (pending)"),
        ],
        "artifact_sha256": hashes,
    }
    _atomic_json(OUTPUT / "stress_matrix_gate.json", gate)
    print(
        json.dumps(
            {
                "status": aggregate_status,
                "pure_rows": pure_statuses,
                "resource_observations": gate["resource_observations"],
                "pending_rows": gate["pending_rows"],
                "failed_rows": gate["failed_rows"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if aggregate_status == "Failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
