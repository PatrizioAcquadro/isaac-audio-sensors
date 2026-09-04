#!/usr/bin/env python3
"""Role-based Subphase 04.2 DOA qualification runner."""

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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.plugins import (
    AuditokActivityDetector,
    GccPhatLeastSquaresEstimator,
    PyroomacousticsSrpEstimator,
)
from isaac_audio_sensors.core.types import (
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
)

PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
CONTEXT_MS = 250
SAMPLE_RATE_HZ = 16_000
FREQUENCY_BANDS_HZ = ((300, 800), (800, 2000), (2000, 4000), (4000, 6000))
PRIMARY_SNRS_DB = (10, 20)
ROBUSTNESS_SNRS_DB = (-5, 0)
ACTIVITY_GRID_DBFS = tuple(np.arange(-60.0, -19.5, 0.5).tolist())
RELIABILITY_GRID = tuple(np.arange(0.0, 1.001, 0.01).round(2).tolist())
QUALIFIED_ACTIVITY_THRESHOLD_DBFS = -40.5
QUALIFIED_PYROOM_RELIABILITY = 0.06
DEFAULT_EVIDENCE_ROOT = Path(
    "evidence/functional-sim-to-real-s4/archive/dataset/S4.4/amendments/"
    "s4_4_data_expansion_amendment_04/attempts"
)
DEFAULT_CALIBRATION_PROFILE = Path(
    "evidence/functional-sim-to-real-s4/archive/outputs/"
    "isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
)
DEFAULT_OUTPUT = Path("build/qualification/doa/phase-04.2-corrected.json")

PLANAR_FOUR_M = np.asarray(
    (
        (-0.033, -0.033, 0.0),
        (-0.033, 0.033, 0.0),
        (0.033, 0.033, 0.0),
        (0.033, -0.033, 0.0),
    )
)
PLANAR_THREE_M = PLANAR_FOUR_M[:3]
RANK3_FIVE_M = np.vstack((PLANAR_FOUR_M, (0.0, 0.0, 0.04)))
TWO_MIC_M = np.asarray(((0.0, -0.05, 0.0), (0.0, 0.05, 0.0)))


@dataclass(frozen=True, slots=True)
class Scenario:
    """One synthetic, mixture-only qualification input."""

    scenario_id: str
    split: str
    condition: str
    samples: np.ndarray
    positions_m: np.ndarray
    bearing_deg: float
    elevation_deg: float | None
    frequency_band_hz: tuple[int, int]
    snr_db: int


@dataclass(frozen=True, slots=True)
class RealTake:
    """One hash-verified take and its authorized scoring interval."""

    take_id: str
    split: str
    condition: str
    bearing_deg: float | None
    samples: np.ndarray
    positions_m: np.ndarray
    sample_rate_hz: int
    score_start_s: float
    score_stop_s: float
    wav_sha256: str


def run_qualification(
    *,
    evidence_root: Path | None,
    calibration_profile: Path | None,
    quick: bool = False,
) -> dict[str, Any]:
    """Run independent qualification gates for each intended estimator role."""

    two_microphone = _evaluate_two_microphone(quick=quick)
    pyroom_issue: str | None = None
    planar_records: list[dict[str, Any]] = []
    robustness_records: list[dict[str, Any]] = []
    rank3_records: list[dict[str, Any]] = []
    deterministic = False
    try:
        planar_records, robustness_records, rank3_records, deterministic = (
            _evaluate_synthetic_pyroom(quick=quick)
        )
    except (ImportError, RuntimeError) as exc:
        pyroom_issue = str(exc)

    takes, evidence = _load_real_takes(evidence_root, calibration_profile)
    activity_selection: dict[str, Any] = _blocked_selection(
        "Real take evidence is unavailable."
    )
    reliability_selection: dict[str, Any] = _blocked_selection(
        "Activity calibration or PyRoom is unavailable."
    )
    real_records: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    real_take_performance: list[dict[str, Any]] = []
    if evidence["status"] == PASS:
        try:
            activity_selection = _select_activity_threshold(takes)
        except (ImportError, RuntimeError) as exc:
            activity_selection = _blocked_selection(str(exc))
    if (
        evidence["status"] == PASS
        and activity_selection["status"] == PASS
        and pyroom_issue is None
    ):
        real_records, streams, real_take_performance = _evaluate_real_pipeline(
            takes,
            activity_threshold_dbfs=float(activity_selection["selected"]),
        )
        reliability_selection = _select_reliability_threshold(real_records)

    selected_reliability = (
        float(reliability_selection["selected"])
        if reliability_selection["status"] == PASS
        else QUALIFIED_PYROOM_RELIABILITY
    )
    selected_planar = _apply_reliability_threshold(
        planar_records,
        selected_reliability,
    )
    selected_robustness = _apply_reliability_threshold(
        robustness_records,
        selected_reliability,
    )
    selected_rank3 = _apply_reliability_threshold(
        rank3_records,
        selected_reliability,
    )
    selected_real = _apply_reliability_threshold(real_records, selected_reliability)

    benchmark = _blocked_selection("Full benchmark is omitted in quick mode.")
    if not quick and pyroom_issue is None and activity_selection["status"] == PASS:
        benchmark = _benchmark_composed_pipeline(
            activity_threshold_dbfs=float(activity_selection["selected"]),
            reliability_threshold=selected_reliability,
        )

    roles = {
        "primary_planar_doa": _primary_planar_role(
            selected_planar,
            selected_real,
            deterministic=deterministic,
            pyroom_issue=pyroom_issue,
            evidence=evidence,
        ),
        "two_microphone_ambiguity": _two_microphone_role(two_microphone),
        "robustness": _robustness_role(
            selected_robustness,
            selected_real,
            pyroom_issue=pyroom_issue,
            evidence=evidence,
        ),
        "realtime_planar_compute": _realtime_role(benchmark),
        "optional_3d": _optional_3d_role(
            selected_rank3,
            pyroom_issue=pyroom_issue,
        ),
    }
    semantic = {
        "schema": "ias.doa.phase_04_2_qualification.v2",
        "supersedes": {
            "schema": "ias.doa.phase_04_2_qualification.v1",
            "reports": ["phase-04.2-final-a.json", "phase-04.2-final-b.json"],
            "reason": (
                "The v1 estimator competition did not reflect the estimators' "
                "distinct intended roles and is retained as historical evidence only."
            ),
        },
        "status_semantics": {
            PASS: "All required evidence is present and every observed gate passes.",
            FAIL: "Evidence is sufficient and an observed behavioral gate fails.",
            BLOCKED: "Required evidence or a dependency is missing or insufficient.",
        },
        "matrix": {
            "observation_duration_ms": CONTEXT_MS,
            "sequential_non_overlapping_real_blocks": True,
            "real_stream_starts_at_take_start": True,
            "future_lookahead": False,
            "synthetic_renderer": "independent_numpy_fractional_delay",
            "planar_microphone_counts": [3, 4],
            "frequency_bands_hz": [list(item) for item in FREQUENCY_BANDS_HZ],
        },
        "operating_point": {
            "auditok": activity_selection,
            "pyroom_reliability": reliability_selection,
            "constructor_default": QUALIFIED_PYROOM_RELIABILITY,
            "constructor_default_matches_selected": (
                reliability_selection["status"] == PASS
                and selected_reliability == QUALIFIED_PYROOM_RELIABILITY
            ),
        },
        "evidence": evidence,
        "real_streams": streams,
        "real_take_summaries": _real_take_summaries(selected_real),
        "roles": roles,
        "case_results": {
            "primary_planar_pyroom": selected_planar,
            "two_microphone_least_squares": two_microphone["synthetic_cases"],
            "two_microphone_contract": two_microphone["contract_cases"],
            "robustness_pyroom": selected_robustness,
            "real_pipeline": selected_real,
            "optional_3d_diagnostic": selected_rank3,
        },
        "limitations": [
            "Real source placement has a +/-5 degree tolerance.",
            "Real microphone acoustic centers are nominal_not_measured.",
            "The robustness conclusion is isolated from the primary planar role.",
            "Synthetic 3D diagnostics do not demonstrate realtime or real 3D support.",
            "End-to-end rolling 20 Hz integration remains a Subphase 04.3 gate.",
        ],
    }
    return {
        "semantic": semantic,
        "performance": {
            "realtime_planar_compute": benchmark,
            "real_take_pipeline": real_take_performance,
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pyroomacoustics": _module_version("pyroomacoustics"),
            "auditok": _module_version("auditok"),
        },
    }


def _evaluate_synthetic_pyroom(
    *,
    quick: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    bool,
]:
    primary = list(_primary_scenarios(quick=quick))
    robustness = list(_robustness_scenarios(quick=quick))
    rank3 = list(_rank3_scenarios(quick=quick))
    estimator = PyroomacousticsSrpEstimator(minimum_reliability=0.0)
    all_scenarios = primary + robustness + rank3
    if not all_scenarios:
        return [], [], [], False
    first = estimator.estimate(
        all_scenarios[0].samples,
        all_scenarios[0].positions_m,
        SAMPLE_RATE_HZ,
    )
    deterministic = first == estimator.estimate(
        all_scenarios[0].samples,
        all_scenarios[0].positions_m,
        SAMPLE_RATE_HZ,
    )
    records = [_evaluate_pyroom_scenario(estimator, item) for item in all_scenarios]
    return (
        records[: len(primary)],
        records[len(primary) : len(primary) + len(robustness)],
        records[len(primary) + len(robustness) :],
        deterministic,
    )


def _primary_scenarios(*, quick: bool) -> Iterable[Scenario]:
    arrays = (("three", PLANAR_THREE_M), ("four", PLANAR_FOUR_M))
    bearings = (0, 90) if quick else tuple(range(0, 360, 45))
    bands = (FREQUENCY_BANDS_HZ[1],) if quick else FREQUENCY_BANDS_HZ
    snrs = (10,) if quick else PRIMARY_SNRS_DB
    index = 0
    for array_name, positions in arrays:
        for bearing in bearings:
            for band in bands:
                for snr in snrs:
                    yield Scenario(
                        scenario_id=(
                            f"primary_{array_name}_b{bearing:03d}_{band[0]}-"
                            f"{band[1]}_snr{snr}"
                        ),
                        split="calibration" if index % 2 == 0 else "heldout",
                        condition="direct",
                        samples=_synthetic_mixture(
                            positions,
                            bearing_deg=float(bearing),
                            elevation_deg=0.0,
                            frequency_band_hz=band,
                            snr_db=snr,
                            condition="direct",
                            seed=10_000 + index,
                        ),
                        positions_m=positions,
                        bearing_deg=float(bearing),
                        elevation_deg=None,
                        frequency_band_hz=band,
                        snr_db=snr,
                    )
                    index += 1


def _robustness_scenarios(*, quick: bool) -> Iterable[Scenario]:
    conditions = (
        ("reflection",)
        if quick
        else (
            "low_snr",
            "reflection",
            "interference",
            "clipping",
            "noise",
        )
    )
    bearings = (0, 90) if quick else (0, 90, 180, 270)
    bands = (FREQUENCY_BANDS_HZ[1],) if quick else FREQUENCY_BANDS_HZ
    snrs = (0,) if quick else ROBUSTNESS_SNRS_DB
    index = 0
    for condition in conditions:
        for bearing in bearings:
            for band in bands:
                for snr in snrs:
                    yield Scenario(
                        scenario_id=(
                            f"robust_{condition}_b{bearing:03d}_{band[0]}-"
                            f"{band[1]}_snr{snr}"
                        ),
                        split="heldout",
                        condition=condition,
                        samples=_synthetic_mixture(
                            PLANAR_FOUR_M,
                            bearing_deg=float(bearing),
                            elevation_deg=0.0,
                            frequency_band_hz=band,
                            snr_db=snr,
                            condition={
                                "low_snr": "direct",
                                "reflection": "early_reflection",
                                "noise": "incoherent_noise",
                            }.get(condition, condition),
                            seed=20_000 + index,
                        ),
                        positions_m=PLANAR_FOUR_M,
                        bearing_deg=float(bearing),
                        elevation_deg=None,
                        frequency_band_hz=band,
                        snr_db=snr,
                    )
                    index += 1


def _rank3_scenarios(*, quick: bool) -> Iterable[Scenario]:
    bearings = (0,) if quick else (0, 90, 180, 270)
    elevations = (25,) if quick else (-30, 0, 30)
    for index, (bearing, elevation) in enumerate(
        (bearing, elevation) for bearing in bearings for elevation in elevations
    ):
        band = FREQUENCY_BANDS_HZ[index % len(FREQUENCY_BANDS_HZ)]
        yield Scenario(
            scenario_id=f"optional_3d_b{bearing:03d}_e{elevation:+03d}",
            split="heldout",
            condition="direct",
            samples=_synthetic_mixture(
                RANK3_FIVE_M,
                bearing_deg=float(bearing),
                elevation_deg=float(elevation),
                frequency_band_hz=band,
                snr_db=10,
                condition="direct",
                seed=30_000 + index,
            ),
            positions_m=RANK3_FIVE_M,
            bearing_deg=float(bearing),
            elevation_deg=float(elevation),
            frequency_band_hz=band,
            snr_db=10,
        )


def _evaluate_pyroom_scenario(
    estimator: PyroomacousticsSrpEstimator,
    scenario: Scenario,
) -> dict[str, Any]:
    estimate, diagnostics = estimator.estimate(
        scenario.samples,
        scenario.positions_m,
        SAMPLE_RATE_HZ,
    )
    bearing = estimate.estimated_bearing_deg
    elevation = estimate.estimated_elevation_deg
    return {
        "scenario_id": scenario.scenario_id,
        "estimator": "pyroomacoustics_srp",
        "split": scenario.split,
        "condition": scenario.condition,
        "microphone_count": int(scenario.positions_m.shape[0]),
        "observation_duration_ms": CONTEXT_MS,
        "frequency_band_hz": list(scenario.frequency_band_hz),
        "snr_db": scenario.snr_db,
        "true_bearing_deg": scenario.bearing_deg,
        "true_elevation_deg": scenario.elevation_deg,
        "candidate_bearing_deg": list(estimate.candidate_bearing_deg),
        "candidate_elevation_deg": list(estimate.candidate_elevation_deg),
        "raw_resolved": bearing is not None,
        "resolved": bearing is not None,
        "estimated_bearing_deg": bearing,
        "estimated_elevation_deg": elevation,
        "reliability": float(diagnostics["reliability_score"]),
        "bearing_error_deg": (
            None if bearing is None else _circular_error(bearing, scenario.bearing_deg)
        ),
        "great_circle_error_deg": (
            None
            if bearing is None or elevation is None or scenario.elevation_deg is None
            else _great_circle_error(
                bearing,
                elevation,
                scenario.bearing_deg,
                scenario.elevation_deg,
            )
        ),
    }


def _evaluate_two_microphone(*, quick: bool) -> dict[str, Any]:
    estimator = GccPhatLeastSquaresEstimator(minimum_reliability=0.0)
    bearings = (0, 30, 90) if quick else tuple(range(0, 360, 15))
    snrs = (10,) if quick else (10, 20)
    records: list[dict[str, Any]] = []
    index = 0
    for bearing in bearings:
        for snr in snrs:
            samples = _synthetic_mixture(
                TWO_MIC_M,
                bearing_deg=float(bearing),
                elevation_deg=0.0,
                frequency_band_hz=(800, 4000),
                snr_db=snr,
                condition="direct",
                seed=40_000 + index,
            )
            estimate, _diagnostics = estimator.estimate(
                samples,
                TWO_MIC_M,
                SAMPLE_RATE_HZ,
            )
            candidate_error = (
                None
                if not estimate.candidate_bearing_deg
                else min(
                    _circular_error(candidate, float(bearing))
                    for candidate in estimate.candidate_bearing_deg
                )
            )
            records.append(
                {
                    "scenario_id": f"two_mic_b{bearing:03d}_snr{snr}",
                    "estimator": "tdoa_least_squares",
                    "true_bearing_deg": float(bearing),
                    "snr_db": snr,
                    "candidate_bearing_deg": list(estimate.candidate_bearing_deg),
                    "estimated_bearing_deg": estimate.estimated_bearing_deg,
                    "bearing_sector": estimate.bearing_sector,
                    "bearing_confidence": estimate.bearing_confidence,
                    "ambiguity_class": estimate.ambiguity_class,
                    "candidate_error_deg": candidate_error,
                    "contains_true_bearing": (
                        candidate_error is not None and candidate_error <= 15.0
                    ),
                }
            )
            index += 1
    return {
        "synthetic_cases": records,
        "contract_cases": _two_microphone_contract_cases(),
    }


def _two_microphone_contract_cases() -> list[dict[str, Any]]:
    from isaac_audio_sensors.core.backends._analytic.doa import (
        estimate_doa_from_delays,
    )

    sensor = _array_spec(TWO_MIC_M, SAMPLE_RATE_HZ, array_id="two_mic_contract")
    spacing = float(np.linalg.norm(TWO_MIC_M[1] - TWO_MIC_M[0]))
    checks: list[dict[str, Any]] = []
    expected = {
        "zero": (0.0, 180.0),
        "intermediate_positive": (30.0, 150.0),
        "intermediate_negative": (210.0, 330.0),
        "endpoint_positive": (90.0,),
        "endpoint_negative": (270.0,),
    }
    projections = {
        "zero": 0.0,
        "intermediate_positive": 0.5,
        "intermediate_negative": -0.5,
        "endpoint_positive": 1.0,
        "endpoint_negative": -1.0,
    }
    first_id, second_id = (item.mic_id for item in sensor.microphones)
    for case_id, projection in projections.items():
        delay = -projection * spacing / 343.0
        estimate = estimate_doa_from_delays(
            sensor=sensor,
            per_mic_delay_s={first_id: 0.0, second_id: delay},
        )
        candidates_match = _candidate_sets_match(
            estimate.candidate_bearing_deg,
            expected[case_id],
        )
        ambiguous = len(expected[case_id]) == 2
        semantic_match = (
            estimate.estimated_bearing_deg is None
            and estimate.bearing_sector is None
            and estimate.bearing_confidence == 0.0
            and estimate.ambiguity_class == "ambiguous_front_back"
            if ambiguous
            else estimate.estimated_bearing_deg is not None
            and estimate.bearing_sector is not None
            and estimate.bearing_confidence == 0.9
            and estimate.ambiguity_class is None
        )
        checks.append(
            {
                "case_id": case_id,
                "status": PASS if candidates_match and semantic_match else FAIL,
                "candidate_bearing_deg": list(estimate.candidate_bearing_deg),
                "estimated_bearing_deg": estimate.estimated_bearing_deg,
                "bearing_sector": estimate.bearing_sector,
                "bearing_confidence": estimate.bearing_confidence,
                "ambiguity_class": estimate.ambiguity_class,
            }
        )

    rng = np.random.default_rng(41)
    signal = rng.standard_normal(CONTEXT_MS * SAMPLE_RATE_HZ // 1000)
    adapter = GccPhatLeastSquaresEstimator()
    zero_estimate, _ = adapter.estimate(
        np.stack((signal, signal)),
        TWO_MIC_M,
        SAMPLE_RATE_HZ,
    )
    checks.append(
        {
            "case_id": "adapter_zero_tdoa",
            "status": (
                PASS
                if _candidate_sets_match(
                    zero_estimate.candidate_bearing_deg,
                    expected["zero"],
                )
                and zero_estimate.estimated_bearing_deg is None
                and zero_estimate.bearing_sector is None
                and zero_estimate.bearing_confidence == 0.0
                else FAIL
            ),
            "candidate_bearing_deg": list(zero_estimate.candidate_bearing_deg),
            "estimated_bearing_deg": zero_estimate.estimated_bearing_deg,
            "bearing_sector": zero_estimate.bearing_sector,
            "bearing_confidence": zero_estimate.bearing_confidence,
            "ambiguity_class": zero_estimate.ambiguity_class,
        }
    )
    silence, _ = adapter.estimate(
        np.zeros((2, signal.size)),
        TWO_MIC_M,
        SAMPLE_RATE_HZ,
    )
    checks.append(
        {
            "case_id": "adapter_silence",
            "status": (
                PASS
                if silence.ambiguity_class == "low_information"
                and not silence.candidate_bearing_deg
                else FAIL
            ),
            "candidate_bearing_deg": list(silence.candidate_bearing_deg),
            "estimated_bearing_deg": silence.estimated_bearing_deg,
            "bearing_sector": silence.bearing_sector,
            "bearing_confidence": silence.bearing_confidence,
            "ambiguity_class": silence.ambiguity_class,
        }
    )
    return checks


def _load_real_takes(
    evidence_root: Path | None,
    calibration_profile: Path | None,
) -> tuple[list[RealTake], dict[str, Any]]:
    if evidence_root is None and calibration_profile is None:
        return [], {
            "status": BLOCKED,
            "reason": "Real evidence and its calibration profile were not provided.",
            "included": False,
        }
    if evidence_root is None or calibration_profile is None:
        return [], {
            "status": BLOCKED,
            "reason": "The evidence root and calibration profile are both required.",
            "included": False,
        }
    if not evidence_root.is_dir() or not calibration_profile.is_file():
        return [], {
            "status": BLOCKED,
            "reason": "The evidence root or calibration profile does not exist.",
            "included": False,
        }
    try:
        import soundfile as sf
    except ImportError:
        return [], {
            "status": BLOCKED,
            "reason": "Reading real evidence requires the room optional dependencies.",
            "included": False,
        }

    try:
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
        wav_paths = [path for path in wav_paths if "impact" not in str(path)]
        takes: list[RealTake] = []
        counts = {"nominal": 0, "stress": 0, "low_level": 0, "silence": 0}
        wav_hashes: list[str] = []
        configuration_hashes: list[str] = []
        sealed_report_hashes: list[str] = []
        for wav_path in wav_paths:
            take_id = wav_path.parents[1].name
            bearing, condition = _real_take_label(take_id)
            status_path = wav_path.parent / "pi_producer_status.json"
            report_path = wav_path.parent / "technical_gate_report.json"
            official_path = wav_path.parent / "official_attempt_record.json"
            seal_path = wav_path.parent / "technical_candidate_seal.json"
            manifest_path = wav_path.parent / "technical_precollection_manifest.json"
            producer_status = json.loads(status_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            official = json.loads(official_path.read_text(encoding="utf-8"))
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else None
            )
            wav_hash = _sha256(wav_path)
            if wav_hash != producer_status["sha256"]:
                raise ValueError(f"WAV hash mismatch for {take_id}.")
            sealed_report_hash = official["technical_report_sha256"]
            if sealed_report_hash != seal["report_sha256"]:
                raise ValueError(f"Sealed-report references disagree for {take_id}.")
            if (
                report["decision"] != "PASS"
                or official["decision"] != "PASS"
                or official["retained"] is not True
            ):
                raise ValueError(f"Take is not retained PASS evidence: {take_id}.")
            if condition != "silence":
                configuration_hash = _canonical_json_sha256(report["configuration"])
                linked_configuration_hashes = {
                    report["input_provenance"]["configuration_sha256"],
                    manifest["gate_configuration_sha256"],
                }
                if report.get("configuration_sha256") is not None:
                    linked_configuration_hashes.add(report["configuration_sha256"])
                if linked_configuration_hashes != {configuration_hash}:
                    raise ValueError(
                        f"Authorized configuration hash mismatch for {take_id}."
                    )
                configuration_hashes.append(configuration_hash)
            samples, sample_rate_hz = sf.read(
                wav_path,
                dtype="float32",
                always_2d=True,
            )
            if sample_rate_hz != SAMPLE_RATE_HZ or samples.shape[1] != 6:
                raise ValueError(f"Unexpected ReSpeaker format for {take_id}.")
            calibrated = samples[:, 2:6].T * gains[:, None] * polarities[:, None]
            counts[condition] += 1
            split = _real_take_split(take_id, condition)
            if condition == "silence":
                score_start_s = 0.0
                score_stop_s = samples.shape[0] / sample_rate_hz
            else:
                configuration = report["configuration"]
                score_start_s = float(configuration["reference_active_start_s"])
                score_stop_s = float(configuration["reference_active_stop_s"])
            takes.append(
                RealTake(
                    take_id=take_id,
                    split=split,
                    condition=condition,
                    bearing_deg=bearing,
                    samples=np.asarray(calibrated, dtype=np.float32),
                    positions_m=positions,
                    sample_rate_hz=sample_rate_hz,
                    score_start_s=score_start_s,
                    score_stop_s=score_stop_s,
                    wav_sha256=wav_hash,
                )
            )
            wav_hashes.append(wav_hash)
            sealed_report_hashes.append(sealed_report_hash)
        expected = {"nominal": 24, "stress": 4, "low_level": 4, "silence": 3}
        split_counts = {
            "calibration": sum(item.split == "calibration" for item in takes),
            "heldout": sum(item.split == "heldout" for item in takes),
        }
        if counts != expected or split_counts != {"calibration": 11, "heldout": 24}:
            raise ValueError(
                f"Insufficient representative take inventory: {counts}, {split_counts}."
            )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [], {
            "status": BLOCKED,
            "reason": str(exc),
            "included": False,
        }
    return takes, {
        "status": PASS,
        "included": True,
        "take_counts": counts,
        "split_counts": split_counts,
        "verified_wav_count": len(wav_hashes),
        "verified_authorized_configuration_count": len(configuration_hashes),
        "verified_wav_hashes_sha256": _hash_strings(wav_hashes),
        "verified_configuration_hashes_sha256": _hash_strings(configuration_hashes),
        "sealed_report_references_sha256": _hash_strings(sealed_report_hashes),
        "configuration_verification": (
            "canonical report configuration hash matches the report provenance "
            "and precollection manifest; sealed report references match the "
            "official record"
        ),
        "calibration_profile_sha256": _sha256(calibration_profile),
        "calibration_profile_id": profile["profile_id"],
        "raw_channels": [2, 3, 4, 5],
        "source_placement_tolerance_deg": 5.0,
        "microphone_position_status": "nominal_not_measured",
    }


def _select_activity_threshold(takes: list[RealTake]) -> dict[str, Any]:
    calibration = [
        take
        for take in takes
        if take.split == "calibration" and take.condition != "stress"
    ]
    rows: list[dict[str, Any]] = []
    selected: float | None = None
    selected_take_summaries: list[dict[str, Any]] = []
    for threshold in ACTIVITY_GRID_DBFS:
        metrics = _activity_metrics(calibration, threshold_dbfs=threshold)
        take_summaries = metrics.pop("take_summaries")
        eligible = (
            metrics["minimum_active_take_coverage"] >= 0.90
            and metrics["maximum_silence_take_false_activity"] <= 0.10
        )
        rows.append({"threshold_dbfs": threshold, "eligible": eligible, **metrics})
        if eligible:
            selected = threshold
            selected_take_summaries = take_summaries
    if selected is None:
        return {
            "status": FAIL,
            "reason": "No fixed-grid threshold satisfies the calibration gates.",
            "grid_step_db": 0.5,
            "calibration_results": rows,
        }
    return {
        "status": PASS,
        "selected": selected,
        "selection_rule": "highest_eligible_fixed_grid_value",
        "grid_step_db": 0.5,
        "active_take_minimum_coverage": 0.90,
        "silence_take_maximum_false_activity": 0.10,
        "selected_take_summaries": selected_take_summaries,
        "calibration_results": rows,
    }


def _activity_metrics(
    takes: list[RealTake],
    *,
    threshold_dbfs: float,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for take in takes:
        pipeline = AudioPerceptionPipeline(
            activity_detector=AuditokActivityDetector(
                energy_threshold_dbfs=threshold_dbfs
            )
        )
        array = _array_spec(take.positions_m, take.sample_rate_hz)
        scored = 0
        active = 0
        for frame_index, start in enumerate(
            range(0, take.samples.shape[1], _block_sample_count(take.sample_rate_hz))
        ):
            stop = start + _block_sample_count(take.sample_rate_hz)
            if stop > take.samples.shape[1]:
                break
            frame = pipeline.process(
                _signal_block(take, start, stop, frame_index),
                array,
                frame_id=f"activity_{take.take_id}_{frame_index:04d}",
            )
            if not _score_block(take, start, stop):
                continue
            scored += 1
            active += frame.diagnostics["perception"]["activity_detected"] is True
        summaries.append(
            {
                "take_id": take.take_id,
                "condition": take.condition,
                "scored_blocks": scored,
                "activity_blocks": active,
                "activity_rate": active / scored if scored else 0.0,
            }
        )
    active_rates = [
        item["activity_rate"] for item in summaries if item["condition"] != "silence"
    ]
    silence_rates = [
        item["activity_rate"] for item in summaries if item["condition"] == "silence"
    ]
    return {
        "minimum_active_take_coverage": min(active_rates, default=0.0),
        "maximum_silence_take_false_activity": max(silence_rates, default=1.0),
        "take_summaries": summaries,
    }


def _evaluate_real_pipeline(
    takes: list[RealTake],
    *,
    activity_threshold_dbfs: float,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    records: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    for take in takes:
        pipeline = AudioPerceptionPipeline(
            activity_detector=AuditokActivityDetector(
                energy_threshold_dbfs=activity_threshold_dbfs
            ),
            doa_estimator=PyroomacousticsSrpEstimator(minimum_reliability=0.0),
        )
        array = _array_spec(take.positions_m, take.sample_rate_hz)
        processed = 0
        scored = 0
        compute_ms: list[float] = []
        samples_per_block = _block_sample_count(take.sample_rate_hz)
        for frame_index, start in enumerate(
            range(0, take.samples.shape[1], samples_per_block)
        ):
            stop = start + samples_per_block
            if stop > take.samples.shape[1]:
                break
            started = time.perf_counter_ns()
            frame = pipeline.process(
                _signal_block(take, start, stop, frame_index),
                array,
                frame_id=f"qualification_{take.take_id}_{frame_index:04d}",
            )
            compute_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
            processed += 1
            if not _score_block(take, start, stop):
                continue
            scored += 1
            perception = frame.diagnostics["perception"]
            activity = perception["activity_detected"] is True
            doa = None
            diagnostics: Mapping[str, Any] = {}
            if activity:
                observation = frame.observations[0]
                doa = observation.doa
                diagnostics = observation.diagnostics.get("doa_estimator", {})
            bearing = None if doa is None else doa.estimated_bearing_deg
            candidates = () if doa is None else doa.candidate_bearing_deg
            reliability = float(diagnostics.get("reliability_score", 0.0))
            records.append(
                {
                    "take_id": take.take_id,
                    "split": take.split,
                    "condition": take.condition,
                    "block_index": frame_index,
                    "observation_start_s": start / take.sample_rate_hz,
                    "observation_end_s": stop / take.sample_rate_hz,
                    "scoring_interval_s": [take.score_start_s, take.score_stop_s],
                    "activity_detected": activity,
                    "doa_attempted": activity,
                    "raw_resolved": bearing is not None,
                    "resolved": bearing is not None,
                    "estimated_bearing_deg": bearing,
                    "candidate_bearing_deg": list(candidates),
                    "reliability": reliability,
                    "true_bearing_deg": take.bearing_deg,
                    "bearing_error_deg": (
                        None
                        if bearing is None or take.bearing_deg is None
                        else _circular_error(bearing, take.bearing_deg)
                    ),
                }
            )
        streams.append(
            {
                "take_id": take.take_id,
                "split": take.split,
                "condition": take.condition,
                "take_duration_s": take.samples.shape[1] / take.sample_rate_hz,
                "processed_from_s": 0.0,
                "processed_block_count": processed,
                "scored_block_count": scored,
                "block_duration_ms": CONTEXT_MS,
                "non_overlapping": True,
                "causal": True,
                "wav_sha256": take.wav_sha256,
            }
        )
        performance.append(
            {
                "take_id": take.take_id,
                "processed_call_count": len(compute_ms),
                "compute_median_ms": _percentile(compute_ms, 50),
                "compute_p95_ms": _percentile(compute_ms, 95),
                "compute_max_ms": max(compute_ms),
                "observation_duration_ms": CONTEXT_MS,
            }
        )
    return records, streams, performance


def _select_reliability_threshold(records: list[dict[str, Any]]) -> dict[str, Any]:
    calibration = [item for item in records if item["split"] == "calibration"]
    active = [
        item
        for item in calibration
        if item["condition"] in {"nominal", "low_level"} and item["activity_detected"]
    ]
    silence = [
        item
        for item in calibration
        if item["condition"] == "silence" and item["activity_detected"]
    ]
    if not active or not silence:
        return _blocked_selection(
            "Calibration lacks detector-positive active or silence blocks."
        )
    rows: list[dict[str, Any]] = []
    for threshold in RELIABILITY_GRID:
        active_resolution = sum(
            item["raw_resolved"] and item["reliability"] >= threshold for item in active
        ) / len(active)
        silence_selected = sum(
            item["raw_resolved"] and item["reliability"] >= threshold
            for item in silence
        )
        eligible = active_resolution >= 0.95 and silence_selected == 0
        rows.append(
            {
                "threshold": threshold,
                "eligible": eligible,
                "active_resolution": active_resolution,
                "silence_selected_bearings": silence_selected,
            }
        )
        if eligible:
            return {
                "status": PASS,
                "selected": threshold,
                "selection_rule": "lowest_eligible_fixed_grid_value",
                "grid_step": 0.01,
                "active_resolution_minimum": 0.95,
                "silence_selected_bearings_maximum": 0,
                "calibration_active_block_count": len(active),
                "calibration_silence_block_count": len(silence),
                "calibration_results": rows,
            }
    return {
        "status": FAIL,
        "reason": "No fixed-grid threshold satisfies the calibration gates.",
        "grid_step": 0.01,
        "calibration_results": rows,
    }


def _apply_reliability_threshold(
    records: list[dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for source in records:
        item = dict(source)
        item["minimum_reliability"] = threshold
        item["resolved"] = bool(
            item.get("raw_resolved")
            and float(item.get("reliability", 0.0)) >= threshold
        )
        if not item["resolved"]:
            item["estimated_bearing_deg"] = None
            if "estimated_elevation_deg" in item:
                item["estimated_elevation_deg"] = None
            item["bearing_error_deg"] = None
            if "great_circle_error_deg" in item:
                item["great_circle_error_deg"] = None
        selected.append(item)
    return selected


def _primary_planar_role(
    synthetic: list[dict[str, Any]],
    real: list[dict[str, Any]],
    *,
    deterministic: bool,
    pyroom_issue: str | None,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if pyroom_issue is not None:
        requirements = [_blocked_requirement("pyroom_available", pyroom_issue)]
        return _role(
            "pyroomacoustics_srp",
            "Primary general planar DOA for >=3 non-collinear microphones.",
            requirements,
        )
    heldout = [item for item in synthetic if item["split"] == "heldout"]
    synthetic_summary = _direction_summary(heldout)
    requirements = [
        _requirement(
            "synthetic_resolved_coverage",
            synthetic_summary["resolved_coverage"],
            ">=",
            0.95,
        ),
        _requirement(
            "synthetic_bearing_error_p95_deg",
            synthetic_summary["bearing_error_p95_deg"],
            "<=",
            15.0,
        ),
        _requirement("deterministic_replay", deterministic, "==", True),
    ]
    for band in FREQUENCY_BANDS_HZ:
        band_summary = _direction_summary(
            [item for item in synthetic if item["frequency_band_hz"] == list(band)]
        )
        requirements.append(
            _requirement(
                f"frequency_band_{band[0]}_{band[1]}_p95_deg",
                band_summary["bearing_error_p95_deg"],
                "<=",
                20.0,
            )
        )
    if evidence["status"] != PASS:
        requirements.append(
            _blocked_requirement("representative_real_takes", str(evidence["reason"]))
        )
    else:
        nominal = [
            item
            for item in _real_take_summaries(real)
            if item["split"] == "heldout" and item["condition"] == "nominal"
        ]
        silence = [
            item
            for item in real
            if item["split"] == "heldout" and item["condition"] == "silence"
        ]
        requirements.extend(
            (
                _requirement(
                    "minimum_real_nominal_take_coverage",
                    min((item["resolved_coverage"] for item in nominal), default=None),
                    ">=",
                    0.95,
                ),
                _requirement(
                    "worst_real_nominal_take_p95_deg",
                    max(
                        (
                            item["bearing_error_p95_deg"]
                            for item in nominal
                            if item["bearing_error_p95_deg"] is not None
                        ),
                        default=None,
                    ),
                    "<=",
                    15.0,
                ),
                _requirement(
                    "heldout_silence_selected_bearings",
                    sum(item["resolved"] for item in silence),
                    "==",
                    0,
                ),
            )
        )
    return _role(
        "pyroomacoustics_srp",
        "Primary general planar DOA for >=3 non-collinear microphones.",
        requirements,
    )


def _two_microphone_role(results: Mapping[str, Any]) -> dict[str, Any]:
    records = results["synthetic_cases"]
    contract = results["contract_cases"]
    errors = [item["candidate_error_deg"] for item in records]
    containment = sum(item["contains_true_bearing"] for item in records) / len(records)
    hidden_unique = sum(
        item["estimated_bearing_deg"] is not None
        and len(item["candidate_bearing_deg"]) > 1
        for item in records
    )
    requirements = [
        _requirement(
            "exact_zero_intermediate_endpoint_semantics",
            _aggregate_status(item["status"] for item in contract),
            "==",
            PASS,
        ),
        _requirement("hidden_unique_bearings", hidden_unique, "==", 0),
        _requirement("synthetic_candidate_containment", containment, ">=", 0.95),
        _requirement(
            "candidate_error_p95_deg",
            _percentile(errors, 95),
            "<=",
            15.0,
        ),
    ]
    role = _role(
        "tdoa_least_squares",
        "Two-microphone physical ambiguity representation.",
        requirements,
    )
    role["nsmrl_hardware_performance"] = {
        "status": BLOCKED,
        "reason": "No NSMRL-specific two-microphone hardware evidence is present.",
    }
    return role


def _robustness_role(
    synthetic: list[dict[str, Any]],
    real: list[dict[str, Any]],
    *,
    pyroom_issue: str | None,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if pyroom_issue is not None:
        return _role(
            "pyroomacoustics_srp",
            "Independent robustness behavior for the primary planar estimator.",
            [_blocked_requirement("pyroom_available", pyroom_issue)],
        )
    requirements: list[dict[str, Any]] = []
    condition_summaries: dict[str, Any] = {}
    for condition in (
        "low_snr",
        "reflection",
        "interference",
        "clipping",
        "noise",
    ):
        summary = _direction_summary(
            [item for item in synthetic if item["condition"] == condition]
        )
        condition_summaries[condition] = summary
        requirements.extend(
            (
                _requirement(
                    f"synthetic_{condition}_coverage",
                    summary["resolved_coverage"],
                    ">=",
                    0.90,
                ),
                _requirement(
                    f"synthetic_{condition}_p95_deg",
                    summary["bearing_error_p95_deg"],
                    "<=",
                    30.0,
                ),
            )
        )
    if evidence["status"] != PASS:
        requirements.append(
            _blocked_requirement(
                "representative_real_robustness", str(evidence["reason"])
            )
        )
    else:
        summaries = [
            item
            for item in _real_take_summaries(real)
            if item["condition"] in {"stress", "low_level"}
        ]
        condition_summaries.update(_real_robustness_condition_summaries(summaries))
        for item in summaries:
            requirements.extend(
                (
                    _requirement(
                        f"{item['take_id']}_coverage",
                        item["resolved_coverage"],
                        ">=",
                        0.90,
                    ),
                    _requirement(
                        f"{item['take_id']}_p95_deg",
                        item["bearing_error_p95_deg"],
                        "<=",
                        30.0,
                    ),
                )
            )
    role = _role(
        "pyroomacoustics_srp",
        "Independent robustness behavior for the primary planar estimator.",
        requirements,
    )
    role["condition_summaries"] = condition_summaries
    return role


def _realtime_role(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    if benchmark["status"] == BLOCKED:
        requirements = [
            _blocked_requirement("composed_pipeline_benchmark", benchmark["reason"])
        ]
    else:
        requirements = [
            _requirement("measured_call_count", benchmark["measured_calls"], "==", 200),
            {
                "id": "compute_p95_ms",
                "status": PASS if benchmark["compute_p95_ms"] < 50.0 else FAIL,
                "evidence": "performance.realtime_planar_compute.compute_p95_ms",
                "operator": "<",
                "threshold": 50.0,
            },
            {
                "id": "compute_max_ms",
                "status": (
                    PASS
                    if benchmark["compute_max_ms"]
                    < float(benchmark["observation_duration_ms"])
                    else FAIL
                ),
                "evidence": "performance.realtime_planar_compute.compute_max_ms",
                "operator": "<",
                "threshold": float(benchmark["observation_duration_ms"]),
            },
        ]
    role = _role(
        "auditok_to_pyroomacoustics_srp",
        "Composed planar compute time, separate from observation duration.",
        requirements,
    )
    role["rolling_20_hz_integration"] = {
        "status": BLOCKED,
        "reason": "End-to-end rolling integration is deferred to Subphase 04.3.",
    }
    return role


def _optional_3d_role(
    records: list[dict[str, Any]],
    *,
    pyroom_issue: str | None,
) -> dict[str, Any]:
    diagnostic = _direction_summary(records, error_key="great_circle_error_deg")
    diagnostic_status = (
        BLOCKED
        if pyroom_issue is not None or not records
        else PASS
        if diagnostic["resolved_coverage"] >= 0.95
        and diagnostic["bearing_error_p95_deg"] <= 15.0
        else FAIL
    )
    return {
        "status": BLOCKED,
        "estimator": "pyroomacoustics_srp",
        "intended_role": "Optional rank-3 array 3D direction estimation.",
        "reason": "Representative real 3D and realtime 3D evidence is absent.",
        "synthetic_diagnostic": {
            "status": diagnostic_status,
            **diagnostic,
        },
        "realtime_3d_supported": False,
    }


def _benchmark_composed_pipeline(
    *,
    activity_threshold_dbfs: float,
    reliability_threshold: float,
) -> dict[str, Any]:
    samples = _synthetic_mixture(
        PLANAR_FOUR_M,
        bearing_deg=45.0,
        elevation_deg=0.0,
        frequency_band_hz=(800, 4000),
        snr_db=20,
        condition="direct",
        seed=50_000,
    )
    array = _array_spec(PLANAR_FOUR_M, SAMPLE_RATE_HZ, array_id="benchmark_array")
    pipeline = AudioPerceptionPipeline(
        activity_detector=AuditokActivityDetector(
            energy_threshold_dbfs=activity_threshold_dbfs
        ),
        doa_estimator=PyroomacousticsSrpEstimator(
            minimum_reliability=reliability_threshold
        ),
    )
    durations: list[float] = []
    for index in range(220):
        block = MicrophoneSignalBlock(
            samples=samples,
            microphone_ids=tuple(item.mic_id for item in array.microphones),
            array_id=array.array_id,
            sample_rate_hz=SAMPLE_RATE_HZ,
            time_window=AudioTimeWindow(
                start_time_s=index * CONTEXT_MS / 1000.0,
                end_time_s=(index + 1) * CONTEXT_MS / 1000.0,
                frame_index=index,
            ),
            channel_validity=(True,) * 4,
            producer_id="qualification",
            provenance="synthetic/core",
        )
        started = time.perf_counter_ns()
        pipeline.process(block, array, frame_id=f"benchmark_{index:04d}")
        duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if index >= 20:
            durations.append(duration_ms)
    return {
        "status": PASS,
        "pipeline": "AuditokActivityDetector -> AudioPerceptionPipeline -> PyRoom SRP",
        "observation_duration_ms": CONTEXT_MS,
        "warmup_calls": 20,
        "measured_calls": len(durations),
        "compute_median_ms": _percentile(durations, 50),
        "compute_p95_ms": _percentile(durations, 95),
        "compute_max_ms": max(durations),
        "timing_is_non_semantic": True,
    }


def _real_take_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    take_ids = sorted({str(item["take_id"]) for item in records})
    summaries: list[dict[str, Any]] = []
    for take_id in take_ids:
        subset = [item for item in records if item["take_id"] == take_id]
        resolved = [item for item in subset if item["resolved"]]
        errors = [
            item["bearing_error_deg"]
            for item in resolved
            if item["bearing_error_deg"] is not None
        ]
        summaries.append(
            {
                "take_id": take_id,
                "split": subset[0]["split"],
                "condition": subset[0]["condition"],
                "scored_blocks": len(subset),
                "activity_coverage": sum(item["activity_detected"] for item in subset)
                / len(subset),
                "resolved_coverage": len(resolved) / len(subset),
                "abstention_rate": 1.0 - len(resolved) / len(subset),
                "bearing_error_median_deg": _percentile(errors, 50),
                "bearing_error_p95_deg": _percentile(errors, 95),
                "bearing_error_max_deg": max(errors) if errors else None,
            }
        )
    return summaries


def _real_robustness_condition_summaries(
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    groups = {
        "occlusion": [item for item in summaries if "occluded" in item["take_id"]],
        "real_noise": [item for item in summaries if "noise" in item["take_id"]],
        "low_level": [item for item in summaries if item["condition"] == "low_level"],
    }
    return {
        name: {
            "take_count": len(items),
            "minimum_take_coverage": min(
                (item["resolved_coverage"] for item in items),
                default=None,
            ),
            "worst_take_p95_deg": max(
                (
                    item["bearing_error_p95_deg"]
                    for item in items
                    if item["bearing_error_p95_deg"] is not None
                ),
                default=None,
            ),
            "take_summaries": items,
        }
        for name, items in groups.items()
    }


def _direction_summary(
    records: list[dict[str, Any]],
    *,
    error_key: str = "bearing_error_deg",
) -> dict[str, Any]:
    if not records:
        return {
            "case_count": 0,
            "resolved_coverage": None,
            "bearing_error_median_deg": None,
            "bearing_error_p95_deg": None,
            "bearing_error_max_deg": None,
        }
    errors = [
        item[error_key]
        for item in records
        if item["resolved"] and item.get(error_key) is not None
    ]
    return {
        "case_count": len(records),
        "resolved_coverage": sum(item["resolved"] for item in records) / len(records),
        "bearing_error_median_deg": _percentile(errors, 50),
        "bearing_error_p95_deg": _percentile(errors, 95),
        "bearing_error_max_deg": max(errors) if errors else None,
    }


def _role(
    estimator: str,
    intended_role: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": _aggregate_status(item["status"] for item in requirements),
        "estimator": estimator,
        "intended_role": intended_role,
        "requirements": requirements,
    }


def _requirement(
    requirement_id: str,
    observed: Any,
    operator: str,
    threshold: Any,
) -> dict[str, Any]:
    if observed is None:
        return _blocked_requirement(requirement_id, "No observations are available.")
    comparisons = {
        ">=": lambda: observed >= threshold,
        "<=": lambda: observed <= threshold,
        "<": lambda: observed < threshold,
        "==": lambda: observed == threshold,
    }
    passed = comparisons[operator]()
    return {
        "id": requirement_id,
        "status": PASS if passed else FAIL,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
    }


def _blocked_requirement(requirement_id: str, reason: str) -> dict[str, Any]:
    return {"id": requirement_id, "status": BLOCKED, "reason": reason}


def _blocked_selection(reason: str) -> dict[str, Any]:
    return {"status": BLOCKED, "reason": reason}


def _aggregate_status(statuses: Iterable[str]) -> str:
    values = tuple(statuses)
    if any(value == FAIL for value in values):
        return FAIL
    if any(value == BLOCKED for value in values) or not values:
        return BLOCKED
    if any(value != PASS for value in values):
        raise ValueError(f"Unknown qualification status in {values!r}.")
    return PASS


def _real_take_split(take_id: str, condition: str) -> str:
    if condition == "nominal" and take_id.endswith("_r1"):
        return "calibration"
    if condition == "low_level" and any(
        label in take_id for label in ("_front_", "_right_")
    ):
        return "calibration"
    if condition == "silence" and "silence_beginning" in take_id:
        return "calibration"
    return "heldout"


def _real_take_label(take_name: str) -> tuple[float | None, str]:
    if "silence" in take_name:
        return None, "silence"
    match = re.search(r"direction_(\d{3})", take_name)
    if match:
        return float(match.group(1)), "nominal"
    named_bearings = {"front": 0.0, "right": 90.0, "rear": 180.0, "left": 270.0}
    for name, bearing in named_bearings.items():
        if f"_{name}_" in take_name:
            condition = "low_level" if "_low_" in take_name else "stress"
            return bearing, condition
    raise ValueError(f"Cannot derive real-take label from {take_name!r}.")


def _score_block(take: RealTake, start: int, stop: int) -> bool:
    start_s = start / take.sample_rate_hz
    stop_s = stop / take.sample_rate_hz
    return start_s >= take.score_start_s and stop_s <= take.score_stop_s


def _block_sample_count(sample_rate_hz: int) -> int:
    return round(sample_rate_hz * CONTEXT_MS / 1000.0)


def _array_spec(
    positions_m: np.ndarray,
    sample_rate_hz: int,
    *,
    array_id: str = "qualification_array",
) -> MicrophoneArraySpec:
    microphones = tuple(
        MicrophoneSpec(
            mic_id=f"channel_{index}",
            relative_position_m=tuple(float(value) for value in position),
        )
        for index, position in enumerate(np.asarray(positions_m))
    )
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path="/QualificationArray",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=sample_rate_hz,
    )


def _signal_block(
    take: RealTake,
    start: int,
    stop: int,
    frame_index: int,
) -> MicrophoneSignalBlock:
    return MicrophoneSignalBlock(
        samples=take.samples[:, start:stop],
        microphone_ids=tuple(
            f"channel_{index}" for index in range(take.samples.shape[0])
        ),
        array_id="qualification_array",
        sample_rate_hz=take.sample_rate_hz,
        time_window=AudioTimeWindow(
            start_time_s=start / take.sample_rate_hz,
            end_time_s=stop / take.sample_rate_hz,
            frame_index=frame_index,
        ),
        channel_validity=(True,) * take.samples.shape[0],
        producer_id="qualification",
        provenance="replay/trace",
    )


def _synthetic_mixture(
    positions_m: np.ndarray,
    *,
    bearing_deg: float,
    elevation_deg: float,
    frequency_band_hz: tuple[int, int],
    snr_db: int,
    condition: str,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sample_count = _block_sample_count(SAMPLE_RATE_HZ)
    source = _band_limited_noise(
        sample_count + 256,
        SAMPLE_RATE_HZ,
        frequency_band_hz,
        rng,
    )
    samples = _propagate_plane_wave(
        source,
        positions_m,
        bearing_deg=bearing_deg,
        elevation_deg=elevation_deg,
        sample_count=sample_count,
    )
    if condition == "early_reflection":
        samples += 0.25 * _propagate_plane_wave(
            np.pad(source[:-128], (128, 0)),
            positions_m,
            bearing_deg=(bearing_deg + 70.0) % 360.0,
            elevation_deg=-elevation_deg / 2.0,
            sample_count=sample_count,
        )
    elif condition == "interference":
        interferer = _band_limited_noise(
            sample_count + 256,
            SAMPLE_RATE_HZ,
            frequency_band_hz,
            np.random.default_rng(seed + 1),
        )
        samples += 0.3 * _propagate_plane_wave(
            interferer,
            positions_m,
            bearing_deg=(bearing_deg + 120.0) % 360.0,
            elevation_deg=0.0,
            sample_count=sample_count,
        )
    signal_rms = float(np.sqrt(np.mean(samples * samples)))
    noise = rng.standard_normal(samples.shape)
    noise *= (
        signal_rms * 10.0 ** (-snr_db / 20.0) / float(np.sqrt(np.mean(noise * noise)))
    )
    samples += noise
    if condition == "incoherent_noise":
        samples += rng.normal(0.0, signal_rms, samples.shape)
    peak = float(np.max(np.abs(samples)))
    if peak > 0.0:
        samples *= 0.8 / peak
    if condition == "clipping":
        samples = np.clip(samples * 2.5, -0.45, 0.45)
    return np.asarray(samples, dtype=np.float32)


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
                time_axis + float(position @ direction) / 343.0 * SAMPLE_RATE_HZ,
                source_axis,
                source,
                left=0.0,
                right=0.0,
            )
            for position in positions_m
        ]
    )


def _candidate_sets_match(
    actual: Iterable[float],
    expected: Iterable[float],
    *,
    tolerance_deg: float = 1e-6,
) -> bool:
    actual_values = tuple(actual)
    expected_values = tuple(expected)
    return len(actual_values) == len(expected_values) and all(
        any(_circular_error(value, target) <= tolerance_deg for value in actual_values)
        for target in expected_values
    )


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    finite = [
        float(value) for value in values if value is not None and math.isfinite(value)
    ]
    if not finite:
        return None
    return float(np.percentile(finite, percentile))


def _circular_error(actual_deg: float, expected_deg: float) -> float:
    return abs((actual_deg - expected_deg + 180.0) % 360.0 - 180.0)


def _great_circle_error(
    actual_bearing_deg: float,
    actual_elevation_deg: float,
    expected_bearing_deg: float,
    expected_elevation_deg: float,
) -> float:
    actual_bearing = math.radians(actual_bearing_deg)
    actual_elevation = math.radians(actual_elevation_deg)
    expected_bearing = math.radians(expected_bearing_deg)
    expected_elevation = math.radians(expected_elevation_deg)
    dot = math.cos(actual_elevation) * math.cos(expected_elevation) * math.cos(
        actual_bearing - expected_bearing
    ) + math.sin(actual_elevation) * math.sin(expected_elevation)
    return math.degrees(math.acos(float(np.clip(dot, -1.0, 1.0))))


def _module_version(name: str) -> str | None:
    try:
        return str(importlib.import_module(name).__version__)
    except (ImportError, AttributeError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_strings(values: Iterable[str]) -> str:
    return hashlib.sha256("".join(values).encode()).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument(
        "--calibration-profile",
        type=Path,
        default=DEFAULT_CALIBRATION_PROFILE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--synthetic-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    evidence_root = None if args.synthetic_only else args.evidence_root
    calibration_profile = None if args.synthetic_only else args.calibration_profile
    report = run_qualification(
        evidence_root=evidence_root,
        calibration_profile=calibration_profile,
        quick=args.quick,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for role_name, role in report["semantic"]["roles"].items():
        print(f"{role_name}: {role['status']}")
    required = (
        report["semantic"]["roles"]["primary_planar_doa"]["status"],
        report["semantic"]["roles"]["two_microphone_ambiguity"]["status"],
        report["semantic"]["roles"]["realtime_planar_compute"]["status"],
    )
    if FAIL in required:
        return 2
    if BLOCKED in required:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
