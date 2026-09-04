#!/usr/bin/env python3
"""Reproducible Subphase 04.2 DOA qualification runner."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import platform
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.plugins import (
    GccPhatLeastSquaresEstimator,
    PyroomacousticsSrpEstimator,
    SrpPhatEstimator,
)

CONTEXT_MS = (50, 100, 250, 500)
FREQUENCY_BANDS_HZ = ((300, 800), (800, 2000), (2000, 4000), (4000, 6000))
SNR_DB = (-5, 0, 10, 20)
AZIMUTH_STEP_DEG = 2.0
LIVE_PERIOD_MS = 50.0
MINIMUM_CLEAN_COVERAGE = 0.95
MAX_ERROR_REGRESSION_DEG = AZIMUTH_STEP_DEG
MAX_COVERAGE_REGRESSION = 0.01
REAL_WINDOW_END_S = 4.0
DEFAULT_EVIDENCE_ROOT = Path(
    "evidence/functional-sim-to-real-s4/archive/dataset/S4.4/amendments/"
    "s4_4_data_expansion_amendment_04/attempts"
)
DEFAULT_CALIBRATION_PROFILE = Path(
    "evidence/functional-sim-to-real-s4/archive/outputs/"
    "isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
)
DEFAULT_OUTPUT = Path("build/qualification/doa/phase-04.2-report.json")

PLANAR_POSITIONS_M = np.asarray(
    (
        (-0.033, -0.033, 0.0),
        (-0.033, 0.033, 0.0),
        (0.033, 0.033, 0.0),
        (0.033, -0.033, 0.0),
    )
)
RANK3_POSITIONS_M = np.vstack((PLANAR_POSITIONS_M, (0.0, 0.0, 0.04)))


@dataclass(frozen=True, slots=True)
class Scenario:
    """One mixture-only qualification input and its evaluation labels."""

    scenario_id: str
    dataset: str
    split: str
    condition: str
    samples: np.ndarray
    positions_m: np.ndarray
    sample_rate_hz: int
    context_ms: int
    active: bool
    bearing_deg: float | None
    elevation_deg: float | None
    frequency_band_hz: tuple[int, int] | None
    snr_db: int | None


def _estimator_factories() -> dict[str, Callable[[], object]]:
    return {
        "tdoa_least_squares": lambda: GccPhatLeastSquaresEstimator(
            minimum_reliability=0.0
        ),
        "srp_phat": lambda: SrpPhatEstimator(minimum_reliability=0.0),
        "pyroomacoustics_srp": lambda: PyroomacousticsSrpEstimator(
            minimum_reliability=0.0
        ),
    }


def run_qualification(
    *,
    evidence_root: Path | None,
    calibration_profile: Path | None,
    quick: bool = False,
) -> dict[str, Any]:
    """Run the deterministic semantic matrix plus isolated performance timing."""

    scenarios = list(_synthetic_scenarios(quick=quick))
    evidence = {"included": False}
    if evidence_root is not None or calibration_profile is not None:
        if evidence_root is None or calibration_profile is None:
            raise ValueError(
                "evidence_root and calibration_profile must be provided together."
            )
        real_scenarios, evidence = _real_scenarios(
            evidence_root,
            calibration_profile,
            contexts=(50,) if quick else CONTEXT_MS,
        )
        scenarios.extend(real_scenarios)

    records, deterministic = _evaluate_scenarios(scenarios)
    thresholds = _select_thresholds(records)
    summaries = _summaries(records, thresholds)
    performance = _performance_summary(records)
    operating_points = _select_operating_points(summaries, performance)
    gates = _qualification_gates(
        summaries,
        operating_points,
        deterministic=deterministic,
        real_included=bool(evidence["included"]),
    )
    semantic = {
        "schema": "ias.doa.phase_04_2_qualification.v1",
        "matrix": {
            "contexts_ms": [50] if quick else list(CONTEXT_MS),
            "frequency_bands_hz": (
                [list(FREQUENCY_BANDS_HZ[1])]
                if quick
                else [list(item) for item in FREQUENCY_BANDS_HZ]
            ),
            "snr_db": [10] if quick else list(SNR_DB),
            "synthetic_renderer": "independent_numpy_fractional_delay",
            "future_lookahead": False,
        },
        "evidence": evidence,
        "case_results": [_semantic_record(item) for item in records],
        "thresholds": thresholds,
        "summaries": summaries,
        "operating_points": operating_points,
        "deterministic": deterministic,
        "gates": gates,
        "normmusic": {
            "evaluated": False,
            "reason": (
                "PyRoom SRP passed the essential gates."
                if gates["pyroomacoustics_srp"]["qualified"]
                else "PyRoom SRP failed; NormMUSIC requires a separate follow-up run."
            ),
        },
        "limitations": [
            "Real source placement has a +/-5 degree tolerance.",
            "Real microphone acoustic centers are nominal_not_measured.",
            "Estimator reliability scores are local and are not cross-calibrated.",
        ],
    }
    return {
        "semantic": semantic,
        "performance": performance,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pyroomacoustics": str(
                importlib.import_module("pyroomacoustics").__version__
            ),
        },
    }


def _synthetic_scenarios(*, quick: bool) -> Iterable[Scenario]:
    contexts = (50,) if quick else CONTEXT_MS
    bands = (FREQUENCY_BANDS_HZ[1],) if quick else FREQUENCY_BANDS_HZ
    snrs = (10,) if quick else SNR_DB
    bearings = (0, 90) if quick else tuple(range(0, 360, 45))
    effects = ("direct", "early_reflection", "interference", "clipping")
    fs = 16_000
    for bearing_index, bearing in enumerate(bearings):
        for band_index, band in enumerate(bands):
            for snr_index, snr in enumerate(snrs):
                condition = effects[(bearing_index + band_index + snr_index) % 4]
                split = "calibration" if bearing_index % 2 == 0 else "heldout"
                for context_ms in contexts:
                    seed = 10_000 + bearing_index * 100 + band_index * 10 + snr_index
                    samples = _synthetic_mixture(
                        PLANAR_POSITIONS_M,
                        bearing_deg=float(bearing),
                        elevation_deg=0.0,
                        frequency_band_hz=band,
                        snr_db=snr,
                        context_ms=context_ms,
                        condition=condition,
                        seed=seed,
                        sample_rate_hz=fs,
                    )
                    yield Scenario(
                        scenario_id=(
                            f"sim_planar_b{bearing:03d}_{band[0]}-{band[1]}_"
                            f"snr{snr}_{condition}_{context_ms}ms"
                        ),
                        dataset="synthetic_planar",
                        split=split,
                        condition=condition,
                        samples=samples,
                        positions_m=PLANAR_POSITIONS_M,
                        sample_rate_hz=fs,
                        context_ms=context_ms,
                        active=True,
                        bearing_deg=float(bearing),
                        elevation_deg=None,
                        frequency_band_hz=band,
                        snr_db=snr,
                    )

    rank3_bearings = (0, 180) if quick else (0, 90, 180, 270)
    elevations = (25,) if quick else (-30, 0, 30)
    for index, (bearing, elevation) in enumerate(
        (b, e) for b in rank3_bearings for e in elevations
    ):
        band = bands[index % len(bands)]
        snr = snrs[index % len(snrs)]
        context_ms = contexts[index % len(contexts)]
        samples = _synthetic_mixture(
            RANK3_POSITIONS_M,
            bearing_deg=float(bearing),
            elevation_deg=float(elevation),
            frequency_band_hz=band,
            snr_db=snr,
            context_ms=context_ms,
            condition=effects[index % len(effects)],
            seed=20_000 + index,
            sample_rate_hz=fs,
        )
        yield Scenario(
            scenario_id=f"sim_rank3_{bearing:03d}_{elevation:+03d}_{context_ms}ms",
            dataset="synthetic_rank3",
            split="heldout",
            condition=effects[index % len(effects)],
            samples=samples,
            positions_m=RANK3_POSITIONS_M,
            sample_rate_hz=fs,
            context_ms=context_ms,
            active=True,
            bearing_deg=float(bearing),
            elevation_deg=float(elevation),
            frequency_band_hz=band,
            snr_db=snr,
        )

    null_conditions = ("silence", "incoherent_noise", "common_mode_noise")
    for split_index, split in enumerate(("calibration", "heldout")):
        for condition_index, condition in enumerate(null_conditions):
            for context_ms in contexts:
                sample_count = round(fs * context_ms / 1000.0)
                rng = np.random.default_rng(
                    30_000 + split_index * 100 + condition_index
                )
                if condition == "silence":
                    samples = np.zeros((4, sample_count))
                elif condition == "incoherent_noise":
                    samples = rng.normal(0.0, 0.01, (4, sample_count))
                else:
                    common = rng.normal(0.0, 0.01, sample_count)
                    samples = np.tile(common, (4, 1))
                yield Scenario(
                    scenario_id=f"sim_null_{split}_{condition}_{context_ms}ms",
                    dataset="synthetic_null",
                    split=split,
                    condition=condition,
                    samples=samples,
                    positions_m=PLANAR_POSITIONS_M,
                    sample_rate_hz=fs,
                    context_ms=context_ms,
                    active=False,
                    bearing_deg=None,
                    elevation_deg=None,
                    frequency_band_hz=None,
                    snr_db=None,
                )

    yield Scenario(
        scenario_id="sim_invalid_two_mic_geometry",
        dataset="synthetic_invalid",
        split="heldout",
        condition="invalid_channels",
        samples=np.ones((2, 800)),
        positions_m=PLANAR_POSITIONS_M[:2],
        sample_rate_hz=fs,
        context_ms=50,
        active=False,
        bearing_deg=None,
        elevation_deg=None,
        frequency_band_hz=None,
        snr_db=None,
    )


def _synthetic_mixture(
    positions_m: np.ndarray,
    *,
    bearing_deg: float,
    elevation_deg: float,
    frequency_band_hz: tuple[int, int],
    snr_db: int,
    context_ms: int,
    condition: str,
    seed: int,
    sample_rate_hz: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sample_count = round(sample_rate_hz * context_ms / 1000.0)
    source = _band_limited_noise(
        sample_count + 256,
        sample_rate_hz,
        frequency_band_hz,
        rng,
    )
    samples = _propagate_plane_wave(
        source,
        positions_m,
        bearing_deg=bearing_deg,
        elevation_deg=elevation_deg,
        sample_count=sample_count,
        sample_rate_hz=sample_rate_hz,
    )
    if condition == "early_reflection":
        reflected = _propagate_plane_wave(
            np.pad(source[:-128], (128, 0)),
            positions_m,
            bearing_deg=(bearing_deg + 70.0) % 360.0,
            elevation_deg=-elevation_deg / 2.0,
            sample_count=sample_count,
            sample_rate_hz=sample_rate_hz,
        )
        samples += 0.25 * reflected
    elif condition == "interference":
        interferer = _band_limited_noise(
            sample_count + 256,
            sample_rate_hz,
            frequency_band_hz,
            np.random.default_rng(seed + 1),
        )
        samples += 0.3 * _propagate_plane_wave(
            interferer,
            positions_m,
            bearing_deg=(bearing_deg + 120.0) % 360.0,
            elevation_deg=0.0,
            sample_count=sample_count,
            sample_rate_hz=sample_rate_hz,
        )
    signal_rms = float(np.sqrt(np.mean(samples * samples)))
    noise = rng.standard_normal(samples.shape)
    noise *= signal_rms * 10.0 ** (-snr_db / 20.0) / float(
        np.sqrt(np.mean(noise * noise))
    )
    samples += noise
    peak = float(np.max(np.abs(samples)))
    if peak > 0.0:
        samples *= 0.8 / peak
    if condition == "clipping":
        samples = np.clip(samples * 2.5, -0.45, 0.45)
    return samples.astype(np.float32)


def _band_limited_noise(
    sample_count: int,
    sample_rate_hz: int,
    band_hz: tuple[int, int],
    rng: np.random.Generator,
) -> np.ndarray:
    values = rng.standard_normal(sample_count)
    spectrum = np.fft.rfft(values)
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / sample_rate_hz)
    spectrum[(frequencies < band_hz[0]) | (frequencies > band_hz[1])] = 0.0
    filtered = np.fft.irfft(spectrum, n=sample_count)
    rms = float(np.sqrt(np.mean(filtered * filtered)))
    return filtered / max(rms, np.finfo(float).eps)


def _propagate_plane_wave(
    source: np.ndarray,
    positions_m: np.ndarray,
    *,
    bearing_deg: float,
    elevation_deg: float,
    sample_count: int,
    sample_rate_hz: int,
) -> np.ndarray:
    bearing = math.radians(bearing_deg)
    elevation = math.radians(elevation_deg)
    direction = np.asarray(
        (
            math.cos(elevation) * math.cos(bearing),
            math.cos(elevation) * math.sin(bearing),
            math.sin(elevation),
        )
    )
    time_axis = np.arange(sample_count, dtype=float) + 128.0
    source_axis = np.arange(source.size, dtype=float)
    return np.stack(
        [
            np.interp(
                time_axis
                + float(position @ direction) / 343.0 * sample_rate_hz,
                source_axis,
                source,
                left=0.0,
                right=0.0,
            )
            for position in positions_m
        ]
    )


def _real_scenarios(
    evidence_root: Path,
    calibration_profile: Path,
    *,
    contexts: tuple[int, ...],
) -> tuple[list[Scenario], dict[str, Any]]:
    if not evidence_root.is_dir():
        raise FileNotFoundError(f"Real evidence root does not exist: {evidence_root}")
    if not calibration_profile.is_file():
        raise FileNotFoundError(
            f"Calibration profile does not exist: {calibration_profile}"
        )
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("Real qualification requires the 'room' extra.") from exc

    profile = json.loads(calibration_profile.read_text(encoding="utf-8"))
    positions = np.asarray(
        [item["position_m"] for item in profile["microphone_geometry"]],
        dtype=float,
    )
    gains = np.asarray(
        [
            10.0 ** (-float(item["gain_db"]["value"]) / 20.0)
            for item in profile["channels"]
        ]
    )
    polarities = np.asarray(
        [float(item["polarity"]["value"]) for item in profile["channels"]]
    )
    wav_paths = sorted(evidence_root.glob("**/respeaker_audio.wav"))
    selected = [path for path in wav_paths if "impact" not in str(path)]
    counts = {"nominal": 0, "stress": 0, "low_level": 0, "silence": 0}
    scenarios: list[Scenario] = []
    verified_hashes: list[str] = []
    for wav_path in selected:
        take_name = wav_path.parents[1].name
        expected_hash = json.loads(
            (wav_path.parent / "pi_producer_status.json").read_text(encoding="utf-8")
        )["sha256"]
        actual_hash = _sha256(wav_path)
        if actual_hash != expected_hash:
            raise ValueError(f"Evidence hash mismatch: {wav_path}")
        verified_hashes.append(actual_hash)
        samples, sample_rate_hz = sf.read(wav_path, dtype="float32", always_2d=True)
        if sample_rate_hz != 16_000 or samples.shape[1] != 6:
            raise ValueError(f"Unexpected ReSpeaker WAV format: {wav_path}")
        values = samples[:, 2:6].T * gains[:, None] * polarities[:, None]
        bearing, condition = _real_take_label(take_name)
        counts[condition] += 1
        split = (
            "calibration"
            if condition == "silence" and "silence_beginning" in take_name
            else "heldout"
        )
        for context_ms in contexts:
            sample_count = round(sample_rate_hz * context_ms / 1000.0)
            end = round(REAL_WINDOW_END_S * sample_rate_hz)
            window = values[:, end - sample_count : end]
            scenarios.append(
                Scenario(
                    scenario_id=f"real_{take_name}_{context_ms}ms",
                    dataset=f"real_{condition}",
                    split=split,
                    condition=condition,
                    samples=window,
                    positions_m=positions,
                    sample_rate_hz=sample_rate_hz,
                    context_ms=context_ms,
                    active=condition != "silence",
                    bearing_deg=bearing,
                    elevation_deg=None,
                    frequency_band_hz=None,
                    snr_db=None,
                )
            )
    expected_counts = {"nominal": 24, "stress": 4, "low_level": 4, "silence": 3}
    if counts != expected_counts:
        raise ValueError(f"Unexpected real-evidence inventory: {counts}")
    return scenarios, {
        "included": True,
        "take_counts": counts,
        "verified_wav_count": len(verified_hashes),
        "verified_wav_hashes_sha256": hashlib.sha256(
            "".join(verified_hashes).encode()
        ).hexdigest(),
        "calibration_profile_sha256": _sha256(calibration_profile),
        "calibration_profile_id": profile["profile_id"],
        "real_window_end_s": REAL_WINDOW_END_S,
        "raw_channels": [2, 3, 4, 5],
        "source_placement_tolerance_deg": 5.0,
        "microphone_position_status": "nominal_not_measured",
        "calibration_take": "s48r02_preholdout_001_silence_beginning",
        "heldout_silence_take_count": 2,
    }


def _real_take_label(take_name: str) -> tuple[float | None, str]:
    if "silence" in take_name:
        return None, "silence"
    match = re.search(r"direction_(\d{3})", take_name)
    if match:
        return float(match.group(1)), "nominal"
    named_bearings = {"front": 0.0, "right": 90.0, "rear": 180.0, "left": 270.0}
    for name, bearing in named_bearings.items():
        if f"_{name}_" in take_name:
            return bearing, "stress" if "low_" not in take_name else "low_level"
    raise ValueError(f"Cannot derive real-take label from {take_name!r}.")


def _evaluate_scenarios(
    scenarios: list[Scenario],
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    records: list[dict[str, Any]] = []
    deterministic: dict[str, bool] = {}
    for estimator_id, factory in _estimator_factories().items():
        estimator = factory()
        checked_contexts: set[int] = set()
        deterministic[estimator_id] = True
        warmup = scenarios[0]
        estimator.estimate(
            warmup.samples,
            warmup.positions_m,
            warmup.sample_rate_hz,
        )
        for scenario in scenarios:
            started = time.perf_counter_ns()
            estimate, diagnostics = estimator.estimate(
                scenario.samples,
                scenario.positions_m,
                scenario.sample_rate_hz,
            )
            compute_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            if scenario.context_ms not in checked_contexts:
                repeated = estimator.estimate(
                    scenario.samples,
                    scenario.positions_m,
                    scenario.sample_rate_hz,
                )
                deterministic[estimator_id] &= repeated == (estimate, diagnostics)
                checked_contexts.add(scenario.context_ms)
            bearing = estimate.estimated_bearing_deg
            elevation = estimate.estimated_elevation_deg
            records.append(
                {
                    "estimator": estimator_id,
                    "scenario_id": scenario.scenario_id,
                    "dataset": scenario.dataset,
                    "split": scenario.split,
                    "condition": scenario.condition,
                    "context_ms": scenario.context_ms,
                    "microphone_count": int(scenario.samples.shape[0]),
                    "active": scenario.active,
                    "true_bearing_deg": scenario.bearing_deg,
                    "true_elevation_deg": scenario.elevation_deg,
                    "frequency_band_hz": scenario.frequency_band_hz,
                    "snr_db": scenario.snr_db,
                    "candidate_bearing_deg": (
                        None
                        if not estimate.candidate_bearing_deg
                        else estimate.candidate_bearing_deg[0]
                    ),
                    "candidate_elevation_deg": (
                        None
                        if not estimate.candidate_elevation_deg
                        else estimate.candidate_elevation_deg[0]
                    ),
                    "raw_resolved": bearing is not None,
                    "reliability": float(diagnostics["reliability_score"]),
                    "bearing_error_deg": (
                        None
                        if bearing is None or scenario.bearing_deg is None
                        else _circular_error(bearing, scenario.bearing_deg)
                    ),
                    "elevation_error_deg": (
                        None
                        if elevation is None or scenario.elevation_deg is None
                        else abs(elevation - scenario.elevation_deg)
                    ),
                    "compute_ms": compute_ms,
                    "observation_start_s": (
                        REAL_WINDOW_END_S - scenario.context_ms / 1000.0
                        if scenario.dataset.startswith("real_")
                        else 0.0
                    ),
                    "observation_end_s": (
                        REAL_WINDOW_END_S
                        if scenario.dataset.startswith("real_")
                        else scenario.context_ms / 1000.0
                    ),
                    "availability_latency_ms": compute_ms,
                }
            )
    return records, deterministic


def _select_thresholds(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for estimator in _estimator_factories():
        selected[estimator] = {}
        for context_ms in sorted({int(item["context_ms"]) for item in records}):
            subset = [
                item
                for item in records
                if item["estimator"] == estimator
                and item["context_ms"] == context_ms
            ]
            null = [
                item
                for item in subset
                if not item["active"] and item["split"] == "calibration"
            ]
            clean = [
                item
                for item in subset
                if item["dataset"] == "synthetic_planar"
                and item["split"] == "calibration"
                and item["condition"] == "direct"
                and item["snr_db"] >= 10
            ]
            null_max = max((float(item["reliability"]) for item in null), default=0.0)
            threshold = float(np.nextafter(null_max, 1.0)) if null_max < 1.0 else 1.0
            clean_coverage = _coverage(clean, threshold)
            selected[estimator][str(context_ms)] = {
                "minimum_reliability": threshold,
                "calibration_null_max": null_max,
                "clean_active_coverage": clean_coverage,
                "calibrated": bool(clean) and clean_coverage >= MINIMUM_CLEAN_COVERAGE,
            }
    return selected


def _summaries(
    records: list[dict[str, Any]],
    thresholds: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for estimator in _estimator_factories():
        result[estimator] = {}
        for context_text, threshold_info in thresholds[estimator].items():
            context_ms = int(context_text)
            threshold = float(threshold_info["minimum_reliability"])
            subset = [
                item
                for item in records
                if item["estimator"] == estimator
                and item["context_ms"] == context_ms
                and item["split"] == "heldout"
            ]
            active = [item for item in subset if item["active"]]
            null = [item for item in subset if not item["active"]]
            errors = [
                float(item["bearing_error_deg"])
                for item in active
                if item["bearing_error_deg"] is not None
                and float(item["reliability"]) >= threshold
            ]
            rank3 = [item for item in active if item["dataset"] == "synthetic_rank3"]
            rank3_errors = [
                _great_circle_error(
                    float(item["candidate_bearing_deg"]),
                    float(item["candidate_elevation_deg"]),
                    float(item["true_bearing_deg"]),
                    float(item["true_elevation_deg"]),
                )
                for item in rank3
                if item["candidate_bearing_deg"] is not None
                and item["candidate_elevation_deg"] is not None
                and float(item["reliability"]) >= threshold
            ]
            result[estimator][context_text] = {
                "threshold": threshold,
                "calibrated": threshold_info["calibrated"],
                "active_case_count": len(active),
                "active_coverage": _coverage(active, threshold),
                "bearing_error_median_deg": _percentile(errors, 50),
                "bearing_error_p95_deg": _percentile(errors, 95),
                "bearing_error_max_deg": max(errors) if errors else None,
                "rank3_great_circle_p95_deg": _percentile(rank3_errors, 95),
                "heldout_null_count": len(null),
                "heldout_false_direction_count": sum(
                    float(item["reliability"]) >= threshold
                    and item["raw_resolved"]
                    for item in null
                ),
                "frequency_bands": _frequency_summaries(active, threshold),
                "datasets": _dataset_summaries(active, threshold),
            }
    return result


def _select_operating_points(
    summaries: dict[str, dict[str, Any]],
    performance: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    selected: dict[str, dict[str, Any] | None] = {}
    for estimator, contexts in summaries.items():
        eligible = [
            (int(context), values)
            for context, values in contexts.items()
            if values["calibrated"]
            and values["heldout_false_direction_count"] == 0
            and values["bearing_error_p95_deg"] is not None
            and performance[estimator][str(context)][
                "four_channel"
            ][
                "availability_latency_p95_ms"
            ]
            < LIVE_PERIOD_MS
        ]
        if not eligible:
            selected[estimator] = None
            continue
        best_error = min(
            float(values["bearing_error_p95_deg"]) for _, values in eligible
        )
        best_coverage = max(float(values["active_coverage"]) for _, values in eligible)
        acceptable = [
            (context, values)
            for context, values in eligible
            if float(values["bearing_error_p95_deg"])
            <= best_error + MAX_ERROR_REGRESSION_DEG
            and float(values["active_coverage"])
            >= best_coverage - MAX_COVERAGE_REGRESSION
        ]
        context, values = min(acceptable, key=lambda item: item[0])
        selected[estimator] = {
            "context_ms": context,
            "minimum_reliability": values["threshold"],
            "bearing_error_p95_deg": values["bearing_error_p95_deg"],
            "rank3_great_circle_p95_deg": values["rank3_great_circle_p95_deg"],
            "active_coverage": values["active_coverage"],
            "live_period_gate_passed": True,
        }
    return selected


def _qualification_gates(
    summaries: dict[str, dict[str, Any]],
    operating_points: dict[str, dict[str, Any] | None],
    *,
    deterministic: dict[str, bool],
    real_included: bool,
) -> dict[str, dict[str, Any]]:
    gates: dict[str, dict[str, Any]] = {}
    for estimator, point in operating_points.items():
        reasons: list[str] = []
        if point is None:
            reasons.append(
                "no context satisfies calibration, null, accuracy, and latency"
            )
        if not deterministic[estimator]:
            reasons.append("semantic replay is not deterministic")
        if not real_included:
            reasons.append("real multichannel evidence is absent")
        if estimator == "pyroomacoustics_srp" and point is not None:
            context = str(point["context_ms"])
            internal = summaries["srp_phat"][context]
            if float(point["bearing_error_p95_deg"]) > (
                float(internal["bearing_error_p95_deg"])
                + MAX_ERROR_REGRESSION_DEG
            ):
                reasons.append("bearing p95 regresses by more than one grid step")
            if float(point["active_coverage"]) < (
                float(internal["active_coverage"]) - MAX_COVERAGE_REGRESSION
            ):
                reasons.append("active coverage regresses by more than one point")
            rank3 = point["rank3_great_circle_p95_deg"]
            internal_rank3 = internal["rank3_great_circle_p95_deg"]
            if rank3 is None or internal_rank3 is None:
                reasons.append("rank-3 direction is unresolved")
            elif float(rank3) > float(internal_rank3) + MAX_ERROR_REGRESSION_DEG:
                reasons.append("rank-3 p95 regresses by more than one grid step")
        gates[estimator] = {
            "qualified": not reasons,
            "reasons": reasons,
        }
    return gates


def _frequency_summaries(
    records: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    bands = sorted(
        {
            tuple(item["frequency_band_hz"])
            for item in records
            if item["frequency_band_hz"]
        }
    )
    for band in bands:
        subset = [
            item
            for item in records
            if tuple(item["frequency_band_hz"] or ()) == band
        ]
        errors = [
            float(item["bearing_error_deg"])
            for item in subset
            if item["bearing_error_deg"] is not None
            and float(item["reliability"]) >= threshold
        ]
        output[f"{band[0]}-{band[1]}"] = {
            "coverage": _coverage(subset, threshold),
            "bearing_error_p95_deg": _percentile(errors, 95),
        }
    return output


def _dataset_summaries(
    records: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for dataset in sorted({str(item["dataset"]) for item in records}):
        subset = [item for item in records if item["dataset"] == dataset]
        errors = [
            float(item["bearing_error_deg"])
            for item in subset
            if item["bearing_error_deg"] is not None
            and float(item["reliability"]) >= threshold
        ]
        output[dataset] = {
            "case_count": len(subset),
            "coverage": _coverage(subset, threshold),
            "bearing_error_median_deg": _percentile(errors, 50),
            "bearing_error_p95_deg": _percentile(errors, 95),
        }
    return output


def _performance_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for estimator in _estimator_factories():
        output[estimator] = {}
        for context_ms in sorted({int(item["context_ms"]) for item in records}):
            groups: dict[str, Any] = {}
            for group, microphone_count in (("four_channel", 4), ("rank3", 5)):
                durations = [
                    float(item["compute_ms"])
                    for item in records
                    if item["estimator"] == estimator
                    and item["context_ms"] == context_ms
                    and item["microphone_count"] == microphone_count
                ]
                if durations:
                    groups[group] = {
                        "sample_count": len(durations),
                        "availability_latency_p50_ms": _percentile(durations, 50),
                        "availability_latency_p95_ms": _percentile(durations, 95),
                        "availability_latency_p99_ms": _percentile(durations, 99),
                        "availability_latency_max_ms": max(durations),
                    }
            if groups:
                output[estimator][str(context_ms)] = groups
    return output


def _semantic_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"compute_ms", "availability_latency_ms"}
    }


def _coverage(records: list[dict[str, Any]], threshold: float) -> float:
    if not records:
        return 0.0
    return sum(
        item["raw_resolved"] and float(item["reliability"]) >= threshold
        for item in records
    ) / len(records)


def _percentile(values: list[float], percentile: float) -> float | None:
    return None if not values else float(np.percentile(values, percentile))


def _circular_error(observed: float, expected: float) -> float:
    return abs((observed - expected + 180.0) % 360.0 - 180.0)


def _great_circle_error(
    observed_bearing: float,
    observed_elevation: float,
    expected_bearing: float,
    expected_elevation: float,
) -> float:
    def _unit(bearing_deg: float, elevation_deg: float) -> np.ndarray:
        bearing = math.radians(bearing_deg)
        elevation = math.radians(elevation_deg)
        return np.asarray(
            (
                math.cos(elevation) * math.cos(bearing),
                math.cos(elevation) * math.sin(bearing),
                math.sin(elevation),
            )
        )

    cosine = float(
        np.clip(
            _unit(observed_bearing, observed_elevation)
            @ _unit(expected_bearing, expected_elevation),
            -1.0,
            1.0,
        )
    )
    return math.degrees(math.acos(cosine))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument(
        "--calibration-profile",
        type=Path,
        default=DEFAULT_CALIBRATION_PROFILE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--quick", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    evidence_root = None if args.synthetic_only else args.evidence_root
    profile = None if args.synthetic_only else args.calibration_profile
    report = run_qualification(
        evidence_root=evidence_root,
        calibration_profile=profile,
        quick=args.quick,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    qualified = report["semantic"]["gates"]["pyroomacoustics_srp"]["qualified"]
    print(f"PyRoom SRP qualification: {'PASS' if qualified else 'NO-GO'}")
    print(f"Report: {args.output}")
    return 0 if qualified else 2


if __name__ == "__main__":
    sys.exit(main())
