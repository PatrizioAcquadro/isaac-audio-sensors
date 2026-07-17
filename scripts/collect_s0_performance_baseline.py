"""Aggregate raw S0.4 performance observations from live smoke evidence."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCENARIO_FIELDS = ("backend", "num_envs", "steps", "device", "compute_path")
STATISTIC_FIELDS = (
    "ms_per_step_mean",
    "ms_per_step_median",
    "ms_per_step_p95",
    "ms_per_step_worst",
)
MEMORY_FIELDS = (
    "cuda_max_memory_allocated_bytes",
    "cuda_max_memory_reserved_bytes",
    "cuda_total_memory_bytes",
)


def _sample_statistics(samples: Sequence[float]) -> dict[str, float]:
    ordered = sorted(samples)
    count = len(ordered)
    if count == 0:
        raise ValueError("cannot compute statistics from an empty sample list")
    return {
        "ms_per_step_mean": sum(ordered) / count,
        "ms_per_step_median": (ordered[(count - 1) // 2] + ordered[count // 2]) / 2,
        "ms_per_step_p95": ordered[min(count - 1, int(round(0.95 * count)) - 1)],
        "ms_per_step_worst": ordered[-1],
    }


def _finite_float(value: Any, *, field: str, run_file: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{run_file}: perf.{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{run_file}: perf.{field} must be finite")
    return result


def _read_perf(run_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(run_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {run_file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{run_file}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{run_file}: smoke evidence must be a JSON object")
    perf = payload.get("perf")
    if not isinstance(perf, dict):
        raise ValueError(f"{run_file}: missing 'perf' block")
    return perf


def _relative_mismatch(recorded: float, recomputed: float) -> bool:
    difference = abs(recorded - recomputed)
    if difference == 0.0:
        return False
    return difference / max(abs(recomputed), sys.float_info.min) > 1e-6


def aggregate_runs(run_files: Sequence[Path]) -> dict[str, Any]:
    """Return one informational S0.4 baseline from smoke-evidence JSON files."""

    if not run_files:
        raise ValueError("at least one run file is required")

    warnings: list[str] = []
    run_summaries: list[dict[str, Any]] = []
    pooled_samples: list[float] = []
    shared_scenario: dict[str, Any] | None = None

    for run_file in run_files:
        perf = _read_perf(run_file)
        missing_scenario = [field for field in SCENARIO_FIELDS if field not in perf]
        if missing_scenario:
            fields = ", ".join(f"perf.{field}" for field in missing_scenario)
            raise ValueError(f"{run_file}: missing scenario field(s): {fields}")
        scenario = {field: perf[field] for field in SCENARIO_FIELDS}
        if shared_scenario is None:
            shared_scenario = scenario
        elif scenario != shared_scenario:
            differences = [
                f"{field}: {shared_scenario[field]!r} != {scenario[field]!r}"
                for field in SCENARIO_FIELDS
                if shared_scenario[field] != scenario[field]
            ]
            raise ValueError(
                f"{run_file}: scenario mismatch ({'; '.join(differences)})"
            )

        raw_samples = perf.get("step_durations_ms")
        samples: list[float] = []
        if raw_samples is not None:
            if not isinstance(raw_samples, list):
                raise ValueError(f"{run_file}: perf.step_durations_ms must be a list")
            samples = [
                _finite_float(value, field="step_durations_ms", run_file=run_file)
                for value in raw_samples
            ]

        if samples:
            statistics = _sample_statistics(samples)
            pooled_samples.extend(samples)
            if len(samples) != perf["steps"]:
                warnings.append(
                    f"{run_file.name}: raw sample count {len(samples)} does not "
                    f"match recorded steps {perf['steps']!r}."
                )
            for field, recomputed in statistics.items():
                if field not in perf:
                    warnings.append(
                        f"{run_file.name}: {field} is missing; using the value "
                        "recomputed from raw samples."
                    )
                    continue
                recorded = _finite_float(perf[field], field=field, run_file=run_file)
                if _relative_mismatch(recorded, recomputed):
                    warnings.append(
                        f"{run_file.name}: recorded {field}={recorded!r} differs "
                        f"from recomputed value {recomputed!r} by more than 1e-6 "
                        "relative."
                    )
        else:
            missing_statistics = [
                field for field in STATISTIC_FIELDS if field not in perf
            ]
            if missing_statistics:
                fields = ", ".join(f"perf.{field}" for field in missing_statistics)
                raise ValueError(
                    f"{run_file}: no raw samples and missing statistic(s): {fields}"
                )
            statistics = {
                field: _finite_float(perf[field], field=field, run_file=run_file)
                for field in STATISTIC_FIELDS
            }
            warnings.append(
                f"{run_file.name}: no raw step durations; using recorded per-run "
                "statistics and excluding this run from pooled raw statistics."
            )

        summary: dict[str, Any] = {
            "run_file": run_file.name,
            "raw_samples_available": bool(samples),
            "sample_count": len(samples),
            **statistics,
        }
        for field in MEMORY_FIELDS:
            summary[field] = perf.get(field)
        if "memory_note" in perf:
            summary["memory_note"] = perf["memory_note"]
        run_summaries.append(summary)

    assert shared_scenario is not None
    if pooled_samples:
        pooled_statistics: dict[str, Any] = {
            "sample_count": len(pooled_samples),
            **_sample_statistics(pooled_samples),
        }
    else:
        pooled_statistics = {
            "sample_count": 0,
            **{field: None for field in STATISTIC_FIELDS},
        }

    return {
        "informational_only": True,
        "note": (
            "S0.4 performance baseline only; the 20 ms acceptance gate belongs "
            "to phase P1."
        ),
        "run_files": [run_file.name for run_file in run_files],
        "scenario": shared_scenario,
        "runs": run_summaries,
        "pooled_statistics": pooled_statistics,
        "warnings": warnings,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        nargs="+",
        required=True,
        type=Path,
        help="Smoke-evidence JSON files to aggregate.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Destination for the aggregate JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        aggregate = aggregate_runs(args.runs)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
