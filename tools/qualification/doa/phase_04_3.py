#!/usr/bin/env python3
"""Reproducible rolling-consumer qualification for Subphase 04.3."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.perception import _build_standard_perception_pipeline
from isaac_audio_sensors.core.types import (
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
)

SAMPLE_RATE_HZ = 16_000
UPDATE_RATE_HZ = 20
TICK_DURATION_S = 1.0 / UPDATE_RATE_HZ
TICK_SAMPLES = round(SAMPLE_RATE_HZ * TICK_DURATION_S)
CONTEXT_SAMPLES = round(SAMPLE_RATE_HZ * 0.25)
WARMUP_TICKS = 20
MEASURED_TICKS = 200
RUN_COUNT = 2
MAX_P95_MS = 50.0
MAX_TICK_MS = 250.0
DEFAULT_OUTPUT = Path("build/qualification/doa/phase-04.3-rolling.json")

_POSITIONS_M = np.asarray(
    (
        (-0.033, -0.033, 0.0),
        (-0.033, 0.033, 0.0),
        (0.033, 0.033, 0.0),
        (0.033, -0.033, 0.0),
    )
)


def run_qualification() -> dict[str, Any]:
    """Run two independent 20 Hz streams and evaluate the rolling gate."""

    samples = _rolling_fixture()
    runs = tuple(_run_stream(samples, run_index) for run_index in range(RUN_COUNT))
    semantic_hashes = tuple(run["semantic_sha256"] for run in runs)
    semantics_identical = len(set(semantic_hashes)) == 1
    performance = tuple(run["performance"] for run in runs)
    context_exact = all(run["context_exact"] for run in runs)
    no_future_lookahead = all(run["no_future_lookahead"] for run in runs)
    timing_pass = all(
        run["compute_p95_ms"] < MAX_P95_MS
        and run["compute_max_ms"] < MAX_TICK_MS
        for run in performance
    )
    passed = (
        semantics_identical
        and context_exact
        and no_future_lookahead
        and timing_pass
    )
    return {
        "semantic": {
            "schema": "ias.doa.phase_04_3_rolling_qualification.v1",
            "status": "pass" if passed else "fail",
            "update_rate_hz": UPDATE_RATE_HZ,
            "tick_duration_ms": TICK_DURATION_S * 1000.0,
            "causal_context_ms": 250,
            "future_lookahead": False,
            "warmup_ticks_per_run": WARMUP_TICKS,
            "measured_ticks_per_run": MEASURED_TICKS,
            "run_count": RUN_COUNT,
            "semantics_identical": semantics_identical,
            "tick_semantics_sha256": semantic_hashes[0],
            "context_exact": context_exact,
            "no_future_lookahead": no_future_lookahead,
            "timing_thresholds_ms": {
                "p95_exclusive": MAX_P95_MS,
                "maximum_exclusive": MAX_TICK_MS,
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "runs": list(performance),
            "timing_is_non_semantic": True,
        },
    }


def _run_stream(samples: np.ndarray, run_index: int) -> dict[str, Any]:
    array = _array_spec()
    pipeline = _build_standard_perception_pipeline(
        energy_threshold_dbfs=-40.5,
        doa_enabled=True,
    )
    tick_semantics: list[dict[str, object]] = []
    durations_ms: list[float] = []
    context_exact = True
    no_future_lookahead = True
    tick_count = WARMUP_TICKS + MEASURED_TICKS
    for tick_index in range(tick_count):
        start = tick_index * TICK_SAMPLES
        stop = start + TICK_SAMPLES
        block = MicrophoneSignalBlock(
            samples=samples[:, start:stop],
            microphone_ids=tuple(item.mic_id for item in array.microphones),
            array_id=array.array_id,
            sample_rate_hz=SAMPLE_RATE_HZ,
            time_window=AudioTimeWindow(
                start_time_s=tick_index * TICK_DURATION_S,
                end_time_s=(tick_index + 1) * TICK_DURATION_S,
                frame_index=tick_index,
            ),
            channel_validity=(True,) * len(array.microphones),
            producer_id="qualification",
            provenance="synthetic/core",
        )
        started_ns = time.perf_counter_ns()
        frame = pipeline.process(
            block,
            array,
            frame_id=f"rolling_{run_index}_{tick_index:04d}",
        )
        duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        if tick_index >= WARMUP_TICKS:
            durations_ms.append(duration_ms)

        context = frame.diagnostics["perception"].get("doa_context")
        if context is not None:
            available = int(context["available_sample_count"])
            expected = min((tick_index + 1) * TICK_SAMPLES, CONTEXT_SAMPLES)
            context_exact = context_exact and available == expected
            no_future_lookahead = no_future_lookahead and available <= stop
        tick_semantics.append(_frame_semantics(frame))

    return {
        "semantic_sha256": _canonical_sha256(tick_semantics),
        "context_exact": context_exact,
        "no_future_lookahead": no_future_lookahead,
        "performance": {
            "run_index": run_index,
            "warmup_ticks": WARMUP_TICKS,
            "measured_ticks": len(durations_ms),
            "compute_median_ms": _percentile(durations_ms, 50),
            "compute_p95_ms": _percentile(durations_ms, 95),
            "compute_max_ms": max(durations_ms),
        },
    }


def _frame_semantics(frame: AudioSensorFrame) -> dict[str, object]:
    observations = tuple(frame.observations)
    if not observations:
        return {"activity": False, "doa": None}
    observation = observations[0]
    estimate = observation.doa
    if estimate is None:
        return {"activity": True, "doa": None}
    diagnostics = observation.diagnostics["doa_estimator"]
    selection = diagnostics["selection"]
    consumer = diagnostics["consumer"]
    context = consumer["context"]
    temporal = consumer["temporal_stability"]
    return {
        "activity": True,
        "bearing_deg": estimate.estimated_bearing_deg,
        "candidates_deg": list(estimate.candidate_bearing_deg),
        "ambiguity_class": estimate.ambiguity_class,
        "role": selection["role"],
        "estimator": selection["selected_estimator_id"],
        "context_samples": context["available_sample_count"],
        "context_complete": context["complete"],
        "temporal_status": temporal["status"],
    }


def _array_spec() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="phase_04_3_array",
        prim_path="/Qualification/Phase043Array",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=tuple(
            MicrophoneSpec(
                mic_id=f"channel_{index}",
                relative_position_m=tuple(float(value) for value in position),
            )
            for index, position in enumerate(_POSITIONS_M)
        ),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _rolling_fixture() -> np.ndarray:
    sample_count = (WARMUP_TICKS + MEASURED_TICKS) * TICK_SAMPLES
    rng = np.random.default_rng(43)
    source = rng.standard_normal(sample_count + 256)
    spectrum = np.fft.rfft(source)
    frequencies = np.fft.rfftfreq(source.size, 1.0 / SAMPLE_RATE_HZ)
    spectrum[(frequencies < 800.0) | (frequencies > 4_000.0)] = 0.0
    source = np.fft.irfft(spectrum, n=source.size)
    source /= max(float(np.sqrt(np.mean(source * source))), np.finfo(float).eps)
    bearing = math.radians(45.0)
    direction = np.asarray((math.cos(bearing), math.sin(bearing), 0.0))
    time_axis = np.arange(sample_count, dtype=float) + 128.0
    source_axis = np.arange(source.size, dtype=float)
    channels = np.stack(
        [
            np.interp(
                time_axis
                + float(position @ direction) / 343.0 * SAMPLE_RATE_HZ,
                source_axis,
                source,
            )
            for position in _POSITIONS_M
        ]
    )
    channels *= 0.2 / float(np.max(np.abs(channels)))
    return np.asarray(channels, dtype=np.float32)


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(values, percentile))


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run_qualification()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"rolling_20_hz: {report['semantic']['status']}")
    return 0 if report["semantic"]["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
