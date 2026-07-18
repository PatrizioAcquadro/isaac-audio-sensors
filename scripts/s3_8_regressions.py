#!/usr/bin/env python3
"""Normalize the S3.8 live regression battery per the frozen spec §8.

Runs (or ingests) each required regression command, writes the normalized
records the S3.8 evidence generator consumes, and produces the effects-on
Lab timing companion report (measure-and-report, no budget verdict).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.8"
LOGS = OUTPUT / "regression_logs"

ROWS = {
    "live_isaac_sim_audio": {
        "command": ["make", "live-isaac-sim-audio"],
        "source": ROOT / "outputs/isaac_audio_sensors/isaac_sim_live_smoke.json",
        "normalized": "live_isaac_sim_audio_regression.json",
    },
    "live_isaac_occlusion": {
        "command": ["make", "live-isaac-occlusion"],
        "source": ROOT / "outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json",
        "normalized": "live_isaac_occlusion_regression.json",
    },
    "live_isaac_lab_gpu_off_state": {
        "command": ["make", "live-isaac-lab-audio-gpu"],
        "source": ROOT / "outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json",
        "normalized": "live_isaac_lab_gpu_off_state_regression.json",
    },
    "live_reliability": {
        "command": ["make", "live-reliability"],
        "source": ROOT / "outputs/isaac_audio_sensors/S2/S2.9/reliability_gate.json",
        "normalized": "live_reliability_regression.json",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run_row(row_id: str, spec: dict) -> dict:
    log_path = LOGS / f"{row_id}.log"
    started = _utc_now()
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            spec["command"],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    ended = _utc_now()
    source: Path = spec["source"]
    record: dict = {
        "row_id": row_id,
        "command": " ".join(spec["command"]),
        "started_utc": started,
        "ended_utc": ended,
        "return_code": completed.returncode,
        "closeout_revision": _revision(),
        "log": str(log_path.relative_to(ROOT)),
    }
    if not source.is_file():
        record.update({"status": "Blocked", "reason": f"missing {source}"})
        return record
    payload = json.loads(source.read_text(encoding="utf-8"))
    record.update(
        {
            "source_artifact": str(source.relative_to(ROOT)),
            "source_sha256": _sha256(source),
            "source_status": payload.get("status"),
            "parsed_assertions": {
                key: payload[key]
                for key in ("status", "scenarios", "perf", "perf_ms", "budget_ms")
                if key in payload
            },
        }
    )
    passed = completed.returncode == 0 and payload.get("status") == "passed"
    record["status"] = "passed" if passed else "failed"
    return record


def _lab_effects_on_companion() -> dict:
    """Time the effects-on L2 simulate path; report stats, no verdict."""

    import numpy as np

    sys.path.insert(0, str(ROOT / "src"))
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsBackend,
    )
    from isaac_audio_sensors.core.effects.config import parse_effects_config
    from isaac_audio_sensors.core.plugins.registry import _propagation_fixture

    scene, sensor, window = _propagation_fixture()
    effects = parse_effects_config(
        {
            "channel_response": {
                "enabled": True,
                "microphones": {
                    sensor.microphones[0].mic_id: {"gain_db": -1.5},
                },
            },
            "noise": {
                "enabled": True,
                "seed": 20260718,
                "self_noise": {"default": {"level_db": -60.0}},
            },
            "electronics": {
                "enabled": True,
                "full_scale": 1.0,
                "bit_depth": 16,
            },
        }
    )
    backend = RoomAcousticsBackend(effects=effects)
    if not backend.is_available():
        return {
            "status": "blocked",
            "reason": "pyroomacoustics unavailable on the Lab host interpreter",
        }
    warmup = 5
    timed = 60
    for _ in range(warmup):
        backend.simulate(scene, sensor, window)
    samples = []
    for _ in range(timed):
        start = time.perf_counter_ns()
        backend.simulate(scene, sensor, window)
        samples.append((time.perf_counter_ns() - start) / 1e6)
    arr = np.asarray(samples)
    return {
        "status": "passed",
        "verdict_semantics": "report_only_no_budget",
        "measured_path": (
            "L2 room_acoustics simulate with channel_response+noise+electronics "
            "enabled on the Lab host interpreter (Lab batched path rejects "
            "effects by the frozen matrix; this measures the supported scalar "
            "effects-on path on the same host)"
        ),
        "warmup_iterations": warmup,
        "timed_iterations": timed,
        "latency_ms": {
            "mean": float(arr.mean()),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(arr.max()),
        },
        "recorded_utc": _utc_now(),
        "closeout_revision": _revision(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--companion-only",
        action="store_true",
        help="Only write the Lab effects-on timing companion report.",
    )
    parser.add_argument(
        "--rows",
        nargs="*",
        default=sorted(ROWS),
        help="Regression row ids to run.",
    )
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    if args.companion_only:
        report = _lab_effects_on_companion()
        path = OUTPUT / "live_isaac_lab_effects_on_report.json"
        path.write_text(json.dumps(report, indent=1, sort_keys=True))
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0 if report["status"] in ("passed", "blocked") else 1

    failures = []
    for row_id in args.rows:
        record = _run_row(row_id, ROWS[row_id])
        path = OUTPUT / ROWS[row_id]["normalized"]
        path.write_text(json.dumps(record, indent=1, sort_keys=True))
        print(f"{row_id}: {record['status']}")
        if record["status"] != "passed":
            failures.append(row_id)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
