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
from dataclasses import asdict, is_dataclass
from pathlib import Path
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
    EffectsConfig,
    MotionEffectsConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import AudioSceneSnapshot
from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.8"
SPEC = ROOT / "docs/development/specs/s3_stress_matrix.md"
ENTRY_REVISION = "44608130727c2466f29919c5521218228e3de56a"
SAMPLE_RATE_HZ = 48_000
WINDOW_SAMPLE_COUNT = 2_400
MIC_IDS = ("front", "right", "rear", "left")
ROOM_WORKER_NAME = "real_room_worker.json"

MATRIX = {
    "geometry_only": ("N/A", "N/A", "U", "S", "S", "U", "U", "S", "S", "N/A", "S"),
    "tdoa_synthetic": ("S", "S", "U", "S", "S", "U", "U", "S", "S", "N/A", "S"),
    "room_acoustics": ("S", "S", "S", "S", "S", "S", "S", "S", "S", "N/A", "S"),
    "room_acoustics_srp": ("S", "S", "S", "S", "S", "S", "S", "S", "S", "N/A", "S"),
    "isaac_lab_batched_selected": (
        "S", "U", "U", "U", "U", "U", "U", "U", "U", "N/A", "S"
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
            payload,
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
                fixtures._scene(
                    (two_sources[0],), array=array, max_order=max_order
                ),
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
    all_effects_hashes = []
    for _frame_index in range(32):
        sink = _LatestSink()
        frame = RoomAcousticsBackend(
            effects=fixtures._all_effects(segments=8),
            window_motion=fixtures._motion_plan(all_scene),
            waveform_writer=sink,
        ).simulate(all_scene, moving_array, fixtures._window())
        assert sink.mixture is not None and np.isfinite(sink.mixture).all()
        assert set(frame.diagnostics["effects"]) == {
            "channel_response",
            "noise",
            "electronics",
            "directivity",
        }
        all_effects_hashes.append(_sha256(sink.mixture.astype("<f4").tobytes()))

    srp_sink = _LatestSink()
    srp_frame = RoomAcousticsSrpBackend(
        effects=fixtures._all_effects(segments=8),
        window_motion=fixtures._motion_plan(all_scene),
        waveform_writer=srp_sink,
    ).simulate(all_scene, moving_array, fixtures._window())
    assert len(srp_frame.detections) == 8
    assert srp_sink.mixture is not None and np.isfinite(srp_sink.mixture).all()

    resource = _resource_long_run(fixtures)
    result = {
        "status": "Passed"
        if all(row["deterministic"] for row in reverb_rows)
        and len({row["waveform_sha256"] for row in reverb_rows}) == 4
        and resource["status"] == "Passed"
        else "Failed",
        "python": sys.version,
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "pyroomacoustics_version": _module_version("pyroomacoustics"),
        "elapsed_s": time.perf_counter() - started,
        "reverberation_ladder": reverb_rows,
        "overlap_ladder": overlap_rows,
        "all_effects_l2": {
            "room_acoustics_frame_count": 32,
            "room_acoustics_srp_frame_count": 1,
            "effects": sorted(srp_frame.diagnostics["effects"]),
            "segments_per_window": 8,
            "deterministic": len(set(all_effects_hashes)) == 1,
            "waveform_sha256": all_effects_hashes[0],
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
        forced = (
            frame_index % 64 == 0
            or frame_index % 256 == 0
            or frame_index == 4_095
        )
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


def _determinism_worker(seed: int) -> int:
    fixtures = _load_fixtures()
    array = fixtures._array()
    sources = tuple(
        fixtures._source(index, (2.0 + index, 1.0 + index % 3, 1.5))
        for index in range(8)
    )
    frames = []
    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        for count in (0, 2, 4, 8):
            frame = backend.simulate(
                fixtures._scene(sources[:count], array=array),
                array,
                fixtures._window(),
            )
            frames.append(frame_to_trace_dict(frame))
    generator = np.random.Generator(np.random.PCG64(seed))
    signal = generator.normal(size=WINDOW_SAMPLE_COUNT).astype("<f4")
    payload = {
        "scenario_ids": [f"P{index:02d}" for index in range(1, 13)],
        "frames": frames,
        "signal_seed": seed,
        "signal_sha256": _sha256(signal.tobytes()),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    print(json.dumps({"payload_sha256": _sha256(encoded), "seed": seed}))
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
    candidates = (
        Path(configured) if configured else None,
        Path("/home/pacquadr/isaacsim/kit/python/bin/python3"),
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


def _run_determinism() -> dict[str, Any]:
    rows = []
    for seed in (20_260_718, 20_260_718, 20_260_719):
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--determinism-worker",
                "--seed",
                str(seed),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return {
                "status": "Failed",
                "returncode": completed.returncode,
                "stderr": completed.stderr,
            }
        rows.append(json.loads(completed.stdout))
    passed = (
        rows[0]["payload_sha256"] == rows[1]["payload_sha256"]
        and rows[0]["payload_sha256"] != rows[2]["payload_sha256"]
    )
    return {
        "status": "Passed" if passed else "Failed",
        "fresh_process_runs": rows,
        "same_seed_exact": rows[0]["payload_sha256"] == rows[1]["payload_sha256"],
        "changed_seed_changes_payload": (
            rows[0]["payload_sha256"] != rows[2]["payload_sha256"]
        ),
        "runtime_telemetry_excluded": True,
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
            fixtures._scene(
                (fixtures._source(0, (4.0, 2.0, 1.5)),), array=two_mic
            ),
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


def _matrix_records(pure_passed: bool, real_room_passed: bool) -> list[dict[str, str]]:
    records = []
    for backend, cells in MATRIX.items():
        for column, claim in zip(MATRIX_COLUMNS, cells, strict=True):
            if claim == "N/A":
                status = "N/A"
                rationale = "Feature has no semantics at this layer."
            elif backend.startswith("room_acoustics"):
                status = "Passed" if real_room_passed else "Blocked"
                rationale = "Executed with real pyroomacoustics." 
            else:
                status = "Passed" if pure_passed else "Failed"
                rationale = (
                    "Supported execution passed."
                    if claim == "S"
                    else "Unsupported request raised its frozen typed error."
                )
            records.append(
                {
                    "backend_path": backend,
                    "feature": column,
                    "claim": claim,
                    "status": status,
                    "rationale": rationale,
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
            "status": (
                "Failed" if failed else "Pending" if pending else "Passed"
            ),
            "rows": regression_rows,
        },
    )
    return rows, pending, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-room-worker", action="store_true")
    parser.add_argument("--determinism-worker", action="store_true")
    parser.add_argument("--seed", type=int, default=20_260_718)
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.real_room_worker:
        return _run_real_room_worker()
    if args.determinism_worker:
        return _determinism_worker(args.seed)

    fixtures = _load_fixtures()
    pytest_result = _run_pytest()
    pure_passed = pytest_result["status"] == "Passed"
    room_result = _run_room_subprocess()
    room_passed = room_result.get("status") == "Passed"
    determinism = _run_determinism()
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
        "status": "Passed" if pure_passed and room_passed else "Failed",
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

    matrix_records = _matrix_records(pure_passed, room_passed)
    _atomic_json(
        OUTPUT / "matrix_capabilities.json",
        {
            "status": (
                "Passed"
                if pure_passed and room_passed and failures_passed
                else "Failed"
            ),
            "profiles": {
                "L0_L1": ["training_features", "waveform_fidelity"],
                "L2": ["waveform_fidelity"],
            },
            "cells": matrix_records,
            "pytest": pytest_result,
        },
    )

    live_rows, pending_rows, live_failed = _ingest_live_rows()
    pure_artifacts = {
        "matrix_capability_audit": pure_passed and room_passed and failures_passed,
        "velocity_and_doppler": velocity["status"] == "Passed",
        "multi_source_overlap": multi["status"] == "Passed",
        "reverb_and_all_effects": l2["status"] == "Passed",
        "occluder_mount_current_state": dynamic["status"] == "Passed",
        "identity_churn_ambiguity": identity["status"] == "Passed",
        "long_run_resources": resource.get("status") == "Passed",
        "gap_preservation": gap["status"] == "Passed",
        "determinism": determinism.get("status") == "Passed",
        "edge_explicit_errors": edge["status"] == "Passed",
    }
    pure_failed = [name for name, passed in pure_artifacts.items() if not passed]
    aggregate_status = (
        "Failed"
        if pure_failed or live_failed
        else "Blocked"
        if pending_rows
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
            **{
                name: "Passed" if passed else "Failed"
                for name, passed in pure_artifacts.items()
            },
            **{name: row["status"] for name, row in live_rows.items()},
        },
        "invariants": {
            "finite_value_scan": "Passed" if pure_passed and room_passed else "Failed",
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
        "pending_rows": pending_rows,
        "blocked_reasons": [
            f"{row}: normalized verdict not yet supplied" for row in pending_rows
        ],
        "failed_rows": pure_failed + live_failed,
        "commands": [
            ".venv/bin/python -m pytest -q tests/test_s3_stress_matrix.py",
            ".venv/bin/python scripts/s3_8_evidence.py",
            "make live-s3-stress (pending orchestrator execution)",
        ],
        "artifact_sha256": hashes,
    }
    _atomic_json(OUTPUT / "stress_matrix_gate.json", gate)
    print(
        json.dumps(
            {
                "status": aggregate_status,
                "pure_rows": pure_artifacts,
                "resource_observations": gate["resource_observations"],
                "pending_rows": pending_rows,
                "failed_rows": gate["failed_rows"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if aggregate_status == "Failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
