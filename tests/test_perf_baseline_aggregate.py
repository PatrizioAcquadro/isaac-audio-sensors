"""Tests for pure S0.4 performance-baseline aggregation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "collect_s0_performance_baseline.py"
)


def _perf_block(samples: list[float] | None, *, device: str = "cuda:0") -> dict:
    perf = {
        "backend": "tdoa_synthetic",
        "num_envs": 4096,
        "steps": 4,
        "device": device,
        "compute_path": "batched",
        "warmup_steps": 10,
        "ms_per_step_mean": 2.5,
        "ms_per_step_median": 2.5,
        "ms_per_step_p95": 4.0,
        "ms_per_step_worst": 4.0,
        "cuda_max_memory_allocated_bytes": 100,
        "cuda_max_memory_reserved_bytes": 200,
        "cuda_total_memory_bytes": 1_000,
    }
    if samples is not None:
        perf["step_durations_ms"] = samples
    return perf


def _write_run(path: Path, perf: dict | None) -> None:
    payload = {"status": "passed"}
    if perf is not None:
        payload["perf"] = perf
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_aggregator(
    run_files: list[Path], out_file: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--runs",
            *(str(path) for path in run_files),
            "--out",
            str(out_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_aggregates_three_runs_and_recomputes_raw_statistics(tmp_path):
    run_files = [tmp_path / f"run{index}.json" for index in range(1, 4)]
    _write_run(run_files[0], _perf_block([1.0, 2.0, 3.0, 4.0]))
    mismatched_summary = _perf_block([2.0, 2.0, 4.0, 4.0])
    mismatched_summary["ms_per_step_mean"] = 99.0
    _write_run(run_files[1], mismatched_summary)
    _write_run(run_files[2], _perf_block(None))
    out_file = tmp_path / "aggregate.json"

    completed = _run_aggregator(run_files, out_file)

    assert completed.returncode == 0, completed.stderr
    aggregate = json.loads(out_file.read_text(encoding="utf-8"))
    assert aggregate["informational_only"] is True
    assert "phase P1" in aggregate["note"]
    assert aggregate["run_files"] == ["run1.json", "run2.json", "run3.json"]
    assert aggregate["scenario"] == {
        "backend": "tdoa_synthetic",
        "num_envs": 4096,
        "steps": 4,
        "device": "cuda:0",
        "compute_path": "batched",
    }
    assert aggregate["runs"][0]["ms_per_step_median"] == 2.5
    assert aggregate["runs"][1]["ms_per_step_mean"] == 3.0
    assert aggregate["runs"][2]["raw_samples_available"] is False
    assert aggregate["runs"][0]["cuda_max_memory_reserved_bytes"] == 200
    assert aggregate["pooled_statistics"] == {
        "sample_count": 8,
        "ms_per_step_mean": 2.75,
        "ms_per_step_median": 2.5,
        "ms_per_step_p95": 4.0,
        "ms_per_step_worst": 4.0,
    }
    assert any(
        "more than 1e-6 relative" in warning for warning in aggregate["warnings"]
    )
    assert any("no raw step durations" in warning for warning in aggregate["warnings"])


def test_rejects_scenario_mismatch(tmp_path):
    run_files = [tmp_path / "run1.json", tmp_path / "run2.json"]
    _write_run(run_files[0], _perf_block([1.0, 2.0, 3.0, 4.0]))
    _write_run(
        run_files[1],
        _perf_block([1.0, 2.0, 3.0, 4.0], device="cuda:1"),
    )

    completed = _run_aggregator(run_files, tmp_path / "aggregate.json")

    assert completed.returncode != 0
    assert "scenario mismatch" in completed.stderr
    assert "device" in completed.stderr


def test_rejects_missing_perf_block(tmp_path):
    run_file = tmp_path / "run1.json"
    _write_run(run_file, None)

    completed = _run_aggregator([run_file], tmp_path / "aggregate.json")

    assert completed.returncode != 0
    assert "missing 'perf' block" in completed.stderr
