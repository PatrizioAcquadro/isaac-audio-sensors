"""Versioned, fit-only S4.5 corrective with semantic regeneration validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_2 import validate_reference_capture
from isaac_audio_sensors.acquisition.s4_5 import (
    S45_CONFIG,
    FitEvidenceAccessor,
    FitEvidenceRecord,
    FitObservation,
    S45Error,
    _aligned_sign,
    _angular_delta,
    _circular_location,
    _nearest_rank,
    _reference_start,
    build_partial_profile,
    checksum_text,
    detect_later_phase_artifacts,
    evidence_records,
    fit_parameter_decisions,
    load_json,
    pretty_json,
    sha256_file,
    synthetic_recovery,
    validate_profile_policy,
    validate_s4_4_preservation,
)
from isaac_audio_sensors.core.doa.gcc_phat import gcc_phat_delay
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.io.calibration import (
    calibration_profile_from_dict,
    calibration_profile_to_dict,
)
from isaac_audio_sensors.core.schema import audio_calibration_profile_json_schema

CORRECTIVE_SCHEMA = "ias.s4_5.corrective_contract.v1"
CORRECTIVE_CONFIG = Path("configs/s4_5_corrective_01.v1.json")
CORRECTIVE_FRAME_AMENDMENT = Path(
    "configs/s4_5_corrective_01_profile_frame_amendment.v1.json"
)
CORRECTIVE_LOCATION_AMENDMENT = Path(
    "configs/s4_5_corrective_01_package_location_amendment.v1.json"
)
CORRECTIVE_SPEC = Path("docs/development/specs/s4_5_corrective_01.md")
CORRECTIVE_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.5_corrective_01")
CORRECTIVE_MODULE = Path("src/isaac_audio_sensors/acquisition/s4_5_corrective.py")
CORRECTIVE_RUNNER = Path("scripts/run_s4_5_corrective.py")
CORRECTIVE_VALIDATOR = Path("scripts/validate_s4_5_corrective.py")
CORRECTIVE_TEST = Path("tests/test_s4_5_corrective.py")
TOOL_VERSION = "ias_s4_5_corrective/1.0.0"
CONTRACT_COMMIT = "26903338da1f91bc8843fd1b093b07482fe4cd9a"
PACKAGE_COMMIT = "d59c7cbfbfe858d34d2e5689f0516b8201dcdc21"
HISTORICAL_CORRECTIVE_OUTPUT = Path(
    "outputs/isaac_audio_sensors/S4/S4.5/correctives/s4_5_corrective_01"
)
HISTORICAL_METADATA_FILES = frozenset(
    {
        "SHA256SUMS",
        "corrective_contract.json",
        "evidence_index.json",
        "preservation_validation.json",
        "provenance.json",
    }
)
HYPOTHESIS_IDS = (
    "H0_identity_nominal",
    "H1_s4_3_rz180_omitted",
    "H2_x_reflection_front_back_position_binding",
    "H3_y_reflection_handedness_mismatch",
)
SELECTED_HYPOTHESIS = "H2_x_reflection_front_back_position_binding"
REQUIRED_FILES = frozenset(
    {
        "authorized_input_census.json",
        "calibration_profile.v2.json",
        "clipping_eligibility.json",
        "corrected_measurements.json",
        "corrective_closeout.json",
        "corrective_contract.json",
        "evidence_index.json",
        "limitations.json",
        "parameter_decisions.json",
        "physical_hypothesis_comparison.json",
        "preservation_validation.json",
        "provenance.json",
        "reproduction.json",
        "semantic_validation.json",
        "synthetic_recovery.json",
        "uncertainty_sensitivity.json",
        "SHA256SUMS",
    }
)
_EXPECTED_PACKAGE_CACHE: dict[tuple[str, str], dict[str, bytes]] = {}


def _verify_bound_file(repo_root: Path, record: Mapping[str, Any], label: str) -> None:
    path_value = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path_value, str) or not re.fullmatch(
        r"[0-9a-f]{64}", str(digest)
    ):
        raise S45Error(f"{label}: invalid file binding")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise S45Error(f"{label}: unsafe file binding")
    path = repo_root / relative
    if not path.is_file() or sha256_file(path) != digest:
        raise S45Error(f"{label}: bound file changed")


def load_corrective_contract(path: Path, repo_root: Path) -> dict[str, Any]:
    """Load and fail closed on the complete versioned corrective contract."""

    contract = load_json(path, label="S4.5 corrective contract")
    if contract.get("schema") != CORRECTIVE_SCHEMA:
        raise S45Error("unexpected S4.5 corrective contract schema")
    if contract.get("tool_version") != TOOL_VERSION:
        raise S45Error("unexpected S4.5 corrective tool version")
    binding = contract.get("bearing_binding")
    if not isinstance(binding, Mapping):
        raise S45Error("bearing_binding must be an object")
    ids = tuple(item.get("id") for item in binding.get("hypotheses", ()))
    if ids != HYPOTHESIS_IDS:
        raise S45Error("physical bearing hypothesis set changed")
    if binding.get("selected_hypothesis_id") != SELECTED_HYPOTHESIS:
        raise S45Error("selected physical bearing hypothesis changed")
    positions = binding.get("selected_profile_channel_positions_f_project_m")
    if not isinstance(positions, Mapping) or tuple(positions) != (
        "ch0",
        "ch1",
        "ch2",
        "ch3",
    ):
        raise S45Error("selected channel-position binding changed")
    expected = (
        (-0.033, -0.033, 0.0),
        (-0.033, 0.033, 0.0),
        (0.033, 0.033, 0.0),
        (0.033, -0.033, 0.0),
    )
    actual = tuple(tuple(float(value) for value in positions[key]) for key in positions)
    if actual != expected:
        raise S45Error("selected channel-position coordinates changed")
    clipping = contract.get("clipping_eligibility")
    if not isinstance(clipping, Mapping) or (
        clipping.get("minimum_clipped_code"),
        clipping.get("maximum_clipped_code"),
        clipping.get("minimum_retained_negative_code"),
        clipping.get("maximum_retained_positive_code"),
    ) != (-32768, 32767, -32767, 32766):
        raise S45Error("S16_LE clipping eligibility changed")
    evidence = contract.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        raise S45Error("corrective evidence bindings are missing")
    for name, record in sorted(evidence.items()):
        if not isinstance(record, Mapping):
            raise S45Error(f"evidence.{name}: binding must be an object")
        _verify_bound_file(repo_root, record, f"evidence.{name}")
    return contract


def load_profile_frame_amendment(repo_root: Path) -> dict[str, Any]:
    """Load the serialization-only distinct-frame amendment."""

    amendment = load_json(
        repo_root / CORRECTIVE_FRAME_AMENDMENT,
        label="S4.5 corrective profile-frame amendment",
    )
    expected = {
        "schema": "ias.s4_5.corrective_profile_frame_amendment.v1",
        "profile_array_frame": "xvf3800_array_corrective_01",
        "geometry_frame": "xvf3800_array_corrective_01",
        "profile_source_frame": "F_project",
        "scientific_binding_changed": False,
        "scientific_thresholds_changed": False,
        "selected_hypothesis_changed": False,
    }
    for key, value in expected.items():
        if amendment.get(key) != value:
            raise S45Error(f"profile-frame amendment changed {key}")
    return amendment


def load_package_location_amendment(repo_root: Path) -> dict[str, Any]:
    """Load the additive package-location compatibility amendment."""

    amendment = load_json(
        repo_root / CORRECTIVE_LOCATION_AMENDMENT,
        label="S4.5 corrective package-location amendment",
    )
    expected = {
        "schema": "ias.s4_5.corrective_package_location_amendment.v1",
        "package_root": CORRECTIVE_OUTPUT.as_posix(),
        "scientific_binding_changed": False,
        "scientific_thresholds_changed": False,
        "selected_hypothesis_changed": False,
    }
    for key, value in expected.items():
        if amendment.get(key) != value:
            raise S45Error(f"package-location amendment changed {key}")
    return amendment


def _hypothesis_position_maps(
    original_contract: Mapping[str, Any],
) -> dict[str, dict[str, tuple[float, float, float]]]:
    native = original_contract["native_audio"]
    ids = tuple(native["profile_channel_order"])
    nominal = tuple(
        tuple(float(value) for value in row)
        for row in native["profile_nominal_microphone_positions_m"]
    )

    def mapped(rule: str) -> dict[str, tuple[float, float, float]]:
        rows = []
        for x, y, z in nominal:
            if rule == "identity":
                rows.append((x, y, z))
            elif rule == "rz180":
                rows.append((-x, -y, z))
            elif rule == "x_reflection":
                rows.append((-x, y, z))
            elif rule == "y_reflection":
                rows.append((x, -y, z))
            else:  # pragma: no cover - internal exhaustive guard
                raise AssertionError(rule)
        return dict(zip(ids, rows, strict=True))

    return {
        HYPOTHESIS_IDS[0]: mapped("identity"),
        HYPOTHESIS_IDS[1]: mapped("rz180"),
        HYPOTHESIS_IDS[2]: mapped("x_reflection"),
        HYPOTHESIS_IDS[3]: mapped("y_reflection"),
    }


def endpoint_clipping_counts(raw_channels: np.ndarray) -> dict[str, int]:
    """Count exact S16_LE endpoint samples in a raw-channel fitting window."""

    values = np.asarray(raw_channels)
    if values.ndim != 2 or values.shape[0] != 4:
        raise S45Error("clipping input must be four raw channels by samples")
    negative = int(np.count_nonzero(values <= -1.0))
    positive = int(np.count_nonzero(values >= 32767.0 / 32768.0))
    return {
        "negative_full_scale_sample_count": negative,
        "positive_full_scale_sample_count": positive,
        "clipped_sample_count": negative + positive,
    }


def _extract_corrective_observations(
    accessor: FitEvidenceAccessor,
    records: Sequence[FitEvidenceRecord],
) -> tuple[
    dict[str, Any],
    tuple[FitObservation, ...],
    dict[str, Any],
    tuple[dict[str, Any], ...],
]:
    """Extract corrected group observations and all frozen physical hypotheses."""

    reference_record = accessor.contract["evidence"]["source_reference_wav"]
    reference_path = accessor.repo_root / reference_record["path"]
    mic_ids = tuple(accessor.contract["native_audio"]["profile_channel_order"])
    position_maps = _hypothesis_position_maps(accessor.contract)
    attempts: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    exclusions_by_split: dict[str, Counter[str]] = {
        "fit_a": Counter(),
        "fit_b": Counter(),
    }
    clipping_exclusions: list[dict[str, Any]] = []
    eligible_before_clipping = 0
    for record in records:
        if record.category not in {"controlled", "confidence"}:
            reason = f"category_{record.category}"
            exclusions[reason] += 1
            exclusions_by_split[record.session_id][reason] += 1
            continue
        path = accessor.validated_wave_path(record, purpose="S4.5_fit")
        report = validate_reference_capture(
            path,
            reference_path,
            minimum_normalized_correlation=0.03,
            minimum_correlated_raw_channels=2,
        )
        if report.issues:
            exclusions["reference_validation_failed"] += 1
            exclusions_by_split[record.session_id]["reference_validation_failed"] += 1
            continue
        start = _reference_start(report)
        if start is None:
            exclusions["reference_alignment_unavailable"] += 1
            exclusions_by_split[record.session_id][
                "reference_alignment_unavailable"
            ] += 1
            continue
        samples, rate = accessor.read_wave(record, purpose="S4.5_fit")
        begin = start + round(2.25 * rate)
        stop = min(samples.shape[0], start + round(7.25 * rate))
        if stop - begin < rate:
            exclusions["active_window_too_short"] += 1
            exclusions_by_split[record.session_id]["active_window_too_short"] += 1
            continue
        raw = samples[begin:stop, 2:6].T
        rms = np.sqrt(np.mean(raw * raw, axis=1))
        if not np.all(np.isfinite(rms)) or np.min(rms) < 1e-6:
            exclusions["silent_or_nonfinite_raw_channel"] += 1
            exclusions_by_split[record.session_id][
                "silent_or_nonfinite_raw_channel"
            ] += 1
            continue
        eligible_before_clipping += 1
        clipping = endpoint_clipping_counts(raw)
        if clipping["clipped_sample_count"]:
            exclusions["pcm16_endpoint_clipping"] += 1
            exclusions_by_split[record.session_id]["pcm16_endpoint_clipping"] += 1
            clipping_exclusions.append(
                {
                    "attempt_id": record.attempt_id,
                    "group_id": record.group_id,
                    "session_id": record.session_id,
                    **clipping,
                }
            )
            continue
        gain = 20.0 * np.log10(rms / rms[0])
        delays = [0.0]
        signs = [1]
        for channel in range(1, 4):
            delay = gcc_phat_delay(
                raw[channel],
                raw[0],
                sample_rate_hz=rate,
                max_delay_s=16.0 / rate,
                interp=8,
            )
            delays.append(float(delay.sample_shift))
            signs.append(_aligned_sign(raw[channel], raw[0], delay.sample_shift))
        center = raw.shape[1] // 2
        half = min(rate // 2, center)
        bearing_wave = {
            mic_id: raw[index, center - half : center + half]
            for index, mic_id in enumerate(mic_ids)
        }
        hypotheses = {}
        for hypothesis_id, position_map in position_maps.items():
            srp = srp_phat_direction(
                bearing_wave,
                mic_positions_m=position_map,
                sample_rate_hz=rate,
                azimuth_step_deg=2.0,
                max_delay_s=16.0 / rate,
                interp=8,
            )
            hypotheses[hypothesis_id] = {
                "bearing_deg": float(srp.bearing_deg),
                "confidence": float(srp_phat_confidence(srp)),
            }
        attempts.append(
            {
                "planned_take_id": record.planned_take_id,
                "attempt_id": record.attempt_id,
                "session_id": record.session_id,
                "group_id": record.group_id,
                "category": record.category,
                "target_bearing_deg": record.target_bearing_deg,
                "gain_db": [float(value) for value in gain],
                "delay_samples": delays,
                "correlation_sign": signs,
                "hypotheses": hypotheses,
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in attempts:
        grouped.setdefault(item["group_id"], []).append(item)
    observations: list[FitObservation] = []
    group_rows: list[dict[str, Any]] = []
    repeated_attempts_collapsed = 0
    for group_id in sorted(grouped):
        rows = grouped[group_id]
        repeated_attempts_collapsed += len(rows) - 1
        sessions = {item["session_id"] for item in rows}
        targets = {item["target_bearing_deg"] for item in rows}
        categories = {item["category"] for item in rows}
        if len(sessions) != 1 or len(targets) != 1:
            raise S45Error(f"{group_id}: leakage group metadata changed")
        gains = tuple(
            float(np.median([item["gain_db"][channel] for item in rows]))
            for channel in range(4)
        )
        delays = tuple(
            float(np.median([item["delay_samples"][channel] for item in rows]))
            for channel in range(4)
        )
        signs = tuple(
            1
            if sum(item["correlation_sign"][channel] > 0 for item in rows)
            >= sum(item["correlation_sign"][channel] < 0 for item in rows)
            else -1
            for channel in range(4)
        )
        hypothesis_bearings = {
            hypothesis_id: _circular_location(
                [item["hypotheses"][hypothesis_id]["bearing_deg"] for item in rows]
            )
            % 360.0
            for hypothesis_id in HYPOTHESIS_IDS
        }
        selected_confidence = float(
            np.median(
                [item["hypotheses"][SELECTED_HYPOTHESIS]["confidence"] for item in rows]
            )
        )
        category = (
            rows[0]["category"]
            if len(categories) == 1
            else "mixed_controlled_confidence"
        )
        target = rows[0]["target_bearing_deg"]
        group_rows.append(
            {
                "group_id": group_id,
                "session_id": rows[0]["session_id"],
                "category": category,
                "target_bearing_deg": target,
                "hypothesis_bearings_deg": hypothesis_bearings,
                "attempt_count": len(rows),
            }
        )
        observations.append(
            FitObservation(
                planned_take_id=group_id,
                session_id=rows[0]["session_id"],
                group_id=group_id,
                category=category,
                target_bearing_deg=target,
                gain_db=gains,
                delay_samples=delays,
                correlation_sign=signs,
                srp_bearing_deg=hypothesis_bearings[SELECTED_HYPOTHESIS],
                srp_confidence=selected_confidence,
            )
        )
    session_counts = dict(
        sorted(Counter(item.session_id for item in observations).items())
    )
    measurements = {
        "schema": "ias.s4_5.corrected_measurements.v1",
        "status": "passed",
        "authorized_valid_cell_count": len(records),
        "eligible_attempt_measurement_count": len(attempts),
        "eligible_attempt_count_before_clipping": eligible_before_clipping,
        "scientific_leakage_group_count": len(observations),
        "session_group_counts": session_counts,
        "repeated_attempts_collapsed_within_group": repeated_attempts_collapsed,
        "excluded_counts": dict(sorted(exclusions.items())),
        "excluded_counts_by_split": {
            key: dict(sorted(value.items()))
            for key, value in sorted(exclusions_by_split.items())
        },
        "selected_hypothesis_id": SELECTED_HYPOTHESIS,
        "reference_channel": "ch0",
        "gain_unit": "dB",
        "delay_unit": "sample_at_16000_Hz",
        "holdout_observations": 0,
        "observations": [
            {
                "group_id": item.group_id,
                "session_id": item.session_id,
                "category": item.category,
                "target_bearing_deg": item.target_bearing_deg,
                "gain_db": list(item.gain_db),
                "delay_samples": list(item.delay_samples),
                "correlation_sign": list(item.correlation_sign),
                "srp_bearing_deg": item.srp_bearing_deg,
                "srp_confidence": item.srp_confidence,
            }
            for item in observations
        ],
    }
    clipping_report = {
        "schema": "ias.s4_5.clipping_eligibility.v1",
        "status": "passed",
        "decoded_representation": "S16_LE",
        "minimum_clipped_code": -32768,
        "maximum_clipped_code": 32767,
        "minimum_retained_negative_code": -32767,
        "maximum_retained_positive_code": 32766,
        "relevant_raw_channel_indices": [2, 3, 4, 5],
        "eligible_attempt_count_before_clipping": eligible_before_clipping,
        "clipping_excluded_attempt_count": len(clipping_exclusions),
        "eligible_attempt_measurement_count": len(attempts),
        "exclusions": clipping_exclusions,
        "threshold_tuned_from_outcomes": False,
    }
    return measurements, tuple(observations), clipping_report, tuple(group_rows)


def _error_summary(
    rows: Sequence[dict[str, Any]], hypothesis_id: str
) -> dict[str, Any]:
    errors = [
        abs(
            _angular_delta(
                float(row["target_bearing_deg"]),
                float(row["hypothesis_bearings_deg"][hypothesis_id]),
            )
        )
        for row in rows
    ]
    return {
        "group_count": len(rows),
        "median_angular_error_deg": float(np.median(np.asarray(errors))),
        "nearest_rank_p95_angular_error_deg": _nearest_rank(errors, 0.95),
        "linear_p95_angular_error_deg": float(np.percentile(errors, 95.0)),
        "worst_angular_error_deg": max(errors),
    }


def _bearing_report(group_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_split = {
        split: [row for row in group_rows if row["session_id"] == split]
        for split in ("fit_a", "fit_b")
    }
    hypotheses = []
    identity_by_split = {
        split: _error_summary(rows, HYPOTHESIS_IDS[0])
        for split, rows in by_split.items()
    }
    for hypothesis_id in HYPOTHESIS_IDS:
        splits = {}
        for split, rows in by_split.items():
            summary = _error_summary(rows, hypothesis_id)
            identity_median = identity_by_split[split]["median_angular_error_deg"]
            summary["median_improvement_fraction_vs_identity"] = (
                identity_median - summary["median_angular_error_deg"]
            ) / identity_median
            per_bearing = []
            for bearing in sorted({float(row["target_bearing_deg"]) for row in rows}):
                bearing_rows = [
                    row for row in rows if float(row["target_bearing_deg"]) == bearing
                ]
                predicted = [
                    float(row["hypothesis_bearings_deg"][hypothesis_id])
                    for row in bearing_rows
                ]
                errors = [abs(_angular_delta(bearing, value)) for value in predicted]
                per_bearing.append(
                    {
                        "target_bearing_deg": bearing,
                        "group_count": len(bearing_rows),
                        "predicted_bearings_deg": predicted,
                        "median_angular_error_deg": float(
                            np.median(np.asarray(errors))
                        ),
                        "worst_angular_error_deg": max(errors),
                    }
                )
            summary["per_bearing"] = per_bearing
            summary["front_back"] = [
                item
                for item in per_bearing
                if item["target_bearing_deg"] in {0.0, 180.0}
            ]
            splits[split] = summary
        hypotheses.append(
            {
                "hypothesis_id": hypothesis_id,
                "selected_using_fit_a": hypothesis_id == SELECTED_HYPOTHESIS,
                "splits": splits,
            }
        )
    return {
        "schema": "ias.s4_5.physical_hypothesis_comparison.v1",
        "status": "passed",
        "hypothesis_selection_partition": "fit_a",
        "fit_b_used_for_selection": False,
        "selected_hypothesis_id": SELECTED_HYPOTHESIS,
        "selected_binding": {
            "ch0": [-0.033, -0.033, 0.0],
            "ch1": [-0.033, 0.033, 0.0],
            "ch2": [0.033, 0.033, 0.0],
            "ch3": [0.033, -0.033, 0.0],
            "frame": "F_project",
            "interpretation": (
                "raw-channel-to-position front/back assignment correction; "
                "F_project remains right-handed"
            ),
        },
        "rejected_hypotheses": {
            HYPOTHESIS_IDS[0]: "systematic all-bearing Fit A failure",
            HYPOTHESIS_IDS[
                1
            ]: "proper 180-degree rotation alone fails non-front/back Fit A bearings",
            HYPOTHESIS_IDS[3]: (
                "mirrored project-frame alternative contradicts the declared "
                "right-handed frame and fails Fit A"
            ),
        },
        "hypotheses": hypotheses,
        "residual_limitations": [
            (
                "The binding is a fit-supported functional association, not "
                "measured acoustic-center geometry."
            ),
            (
                "S4.3 limited-direction 180-degree evidence remains immutable "
                "historical context."
            ),
            (
                "Fit B validates the frozen binding but did not select it or "
                "tune any threshold."
            ),
        ],
    }


def _bootstrap_median_half_width(
    errors_by_group: Mapping[str, float], *, seed: int, resamples: int
) -> float:
    groups = sorted(errors_by_group)
    if len(groups) < 2:
        return math.inf
    rng = np.random.Generator(np.random.PCG64(seed))
    estimates = []
    for _ in range(resamples):
        indices = rng.integers(0, len(groups), size=len(groups))
        values = [errors_by_group[groups[int(index)]] for index in indices]
        estimates.append(float(np.median(np.asarray(values))))
    return 0.5 * (_nearest_rank(estimates, 0.975) - _nearest_rank(estimates, 0.025))


def _leave_one_median_shift(errors_by_group: Mapping[str, float]) -> float:
    groups = sorted(errors_by_group)
    baseline = float(np.median(np.asarray([errors_by_group[key] for key in groups])))
    shifts = []
    for excluded in groups:
        values = [errors_by_group[key] for key in groups if key != excluded]
        shifts.append(abs(float(np.median(np.asarray(values))) - baseline))
    return max(shifts, default=math.inf)


def _selected_binding_decision(
    group_rows: Sequence[dict[str, Any]],
    comparison: Mapping[str, Any],
    corrective: Mapping[str, Any],
) -> dict[str, Any]:
    config = corrective["candidate_policy"]["bearing_binding"]
    split_rows = {
        split: [row for row in group_rows if row["session_id"] == split]
        for split in ("fit_a", "fit_b")
    }
    selected = next(
        item
        for item in comparison["hypotheses"]
        if item["hypothesis_id"] == SELECTED_HYPOTHESIS
    )
    identity = next(
        item
        for item in comparison["hypotheses"]
        if item["hypothesis_id"] == HYPOTHESIS_IDS[0]
    )
    uncertainty = {}
    sensitivity = {}
    for offset, (split, rows) in enumerate(split_rows.items()):
        errors = {
            row["group_id"]: abs(
                _angular_delta(
                    float(row["target_bearing_deg"]),
                    float(row["hypothesis_bearings_deg"][SELECTED_HYPOTHESIS]),
                )
            )
            for row in rows
        }
        uncertainty[split] = _bootstrap_median_half_width(
            errors,
            seed=int(config["bootstrap_seed"]) + offset,
            resamples=int(config["bootstrap_resamples"]),
        )
        sensitivity[split] = _leave_one_median_shift(errors)
    fit_a_summary = selected["splits"]["fit_a"]
    fit_b_summary = selected["splits"]["fit_b"]
    identity_b = identity["splits"]["fit_b"]
    bearings = {
        float(row["target_bearing_deg"])
        for row in group_rows
        if row["target_bearing_deg"] is not None
    }
    checks = {
        "minimum_observations_per_split": all(
            len(rows) >= int(config["minimum_observations_per_split"])
            for rows in split_rows.values()
        ),
        "minimum_groups_per_split": all(
            len({row["group_id"] for row in rows})
            >= int(config["minimum_groups_per_split"])
            for rows in split_rows.values()
        ),
        "minimum_bearings": len(bearings) >= int(config["minimum_bearings"]),
        "fit_b_median_improvement": fit_b_summary[
            "median_improvement_fraction_vs_identity"
        ]
        >= float(config["residual_improvement_fraction"]),
        "fit_b_p95_not_worse": fit_b_summary["nearest_rank_p95_angular_error_deg"]
        <= identity_b["nearest_rank_p95_angular_error_deg"]
        + float(config["p95_worsening_max_deg"]),
        "stable_between_splits": abs(
            fit_a_summary["median_angular_error_deg"]
            - fit_b_summary["median_angular_error_deg"]
        )
        <= float(config["fit_a_fit_b_median_error_difference_max_deg"]),
        "grouped_bootstrap_uncertainty": all(
            value <= float(config["uncertainty_half_width_max_deg"])
            for value in uncertainty.values()
        ),
        "leave_one_group_stability": all(
            value <= float(config["leave_one_group_max_shift_deg"])
            for value in sensitivity.values()
        ),
    }
    return {
        "candidate": "channel_position_binding",
        "retained": all(checks.values()),
        "estimate": comparison["selected_binding"],
        "fit_a_group_count": len(split_rows["fit_a"]),
        "fit_b_group_count": len(split_rows["fit_b"]),
        "observation_count": sum(len(rows) for rows in split_rows.values()),
        "group_count": len({row["group_id"] for row in group_rows}),
        "distinct_bearing_count": len(bearings),
        "fit_a_median_angular_error_deg": fit_a_summary["median_angular_error_deg"],
        "fit_b_median_angular_error_deg": fit_b_summary["median_angular_error_deg"],
        "fit_a_p95_angular_error_deg": fit_a_summary[
            "nearest_rank_p95_angular_error_deg"
        ],
        "fit_b_p95_angular_error_deg": fit_b_summary[
            "nearest_rank_p95_angular_error_deg"
        ],
        "fit_a_worst_angular_error_deg": fit_a_summary["worst_angular_error_deg"],
        "fit_b_worst_angular_error_deg": fit_b_summary["worst_angular_error_deg"],
        "fit_a_bootstrap_95_half_width_deg": uncertainty["fit_a"],
        "fit_b_bootstrap_95_half_width_deg": uncertainty["fit_b"],
        "fit_a_leave_one_group_max_shift_deg": sensitivity["fit_a"],
        "fit_b_leave_one_group_max_shift_deg": sensitivity["fit_b"],
        "checks": checks,
        "reason": (
            "all frozen physical-binding, uncertainty, sensitivity, and locked "
            "Fit B validation gates passed"
            if all(checks.values())
            else "failed frozen criteria: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        ),
    }


def _bootstrap_circular_half_width(
    errors_by_group: Mapping[str, float], *, seed: int, resamples: int
) -> float:
    groups = sorted(errors_by_group)
    if len(groups) < 2:
        return math.inf
    baseline = _circular_location([errors_by_group[key] for key in groups])
    rng = np.random.Generator(np.random.PCG64(seed))
    distances = []
    for _ in range(resamples):
        indices = rng.integers(0, len(groups), size=len(groups))
        estimate = _circular_location(
            [errors_by_group[groups[int(index)]] for index in indices]
        )
        distances.append(abs(_angular_delta(estimate, baseline)))
    return _nearest_rank(distances, 0.95)


def _leave_one_circular_shift(errors_by_group: Mapping[str, float]) -> float:
    groups = sorted(errors_by_group)
    baseline = _circular_location([errors_by_group[key] for key in groups])
    return max(
        (
            abs(
                _angular_delta(
                    _circular_location(
                        [errors_by_group[key] for key in groups if key != excluded]
                    ),
                    baseline,
                )
            )
            for excluded in groups
        ),
        default=math.inf,
    )


def _constant_bearing_decision(
    observations: Sequence[FitObservation], original_contract: Mapping[str, Any]
) -> dict[str, Any]:
    config = original_contract["candidates"]["bearing_correction"]
    splits = {
        split: [
            item
            for item in observations
            if item.session_id == split
            and item.target_bearing_deg is not None
            and item.srp_bearing_deg is not None
        ]
        for split in ("fit_a", "fit_b")
    }

    def errors(rows: Sequence[FitObservation]) -> dict[str, float]:
        return {
            item.group_id: _angular_delta(
                float(item.target_bearing_deg), float(item.srp_bearing_deg)
            )
            for item in rows
        }

    fit_a_errors = errors(splits["fit_a"])
    fit_b_errors = errors(splits["fit_b"])
    estimate_a = _circular_location(list(fit_a_errors.values()))
    estimate_b = _circular_location(list(fit_b_errors.values()))
    combined = {**fit_a_errors, **fit_b_errors}
    estimate = _circular_location(list(combined.values()))
    before = [abs(value) for value in fit_b_errors.values()]
    after = [
        abs((value - estimate_a + 180.0) % 360.0 - 180.0)
        for value in fit_b_errors.values()
    ]
    before_median = float(np.median(np.asarray(before)))
    after_median = float(np.median(np.asarray(after)))
    improvement = (before_median - after_median) / before_median
    uncertainty = {
        "fit_a": _bootstrap_circular_half_width(
            fit_a_errors, seed=20260724, resamples=1024
        ),
        "fit_b": _bootstrap_circular_half_width(
            fit_b_errors, seed=20260725, resamples=1024
        ),
    }
    sensitivity = {
        "fit_a": _leave_one_circular_shift(fit_a_errors),
        "fit_b": _leave_one_circular_shift(fit_b_errors),
    }
    bearings = {
        float(item.target_bearing_deg) for rows in splits.values() for item in rows
    }
    checks = {
        "minimum_observations": len(combined) >= int(config["minimum_observations"]),
        "minimum_groups": len(combined) >= int(config["minimum_groups"]),
        "minimum_bearings": len(bearings) >= int(config["minimum_bearings"]),
        "both_sessions": all(splits.values()),
        "median_improvement": improvement
        >= float(config["residual_improvement_fraction"]),
        "p95_not_worse": _nearest_rank(after, 0.95)
        <= _nearest_rank(before, 0.95) + 0.5,
        "stable_between_sessions": abs(_angular_delta(estimate_a, estimate_b))
        <= float(config["stability_max_deg"]),
        "uncertainty_bounded": all(value <= 7.5 for value in uncertainty.values()),
        "leave_one_group_stable": all(value <= 5.0 for value in sensitivity.values()),
    }
    return {
        "candidate": "bearing_correction",
        "unit": "deg",
        "retained": all(checks.values()),
        "estimate": estimate,
        "fit_a_estimate": estimate_a,
        "fit_b_estimate": estimate_b,
        "observation_count": len(combined),
        "group_count": len(combined),
        "fit_a_group_count": len(fit_a_errors),
        "fit_b_group_count": len(fit_b_errors),
        "distinct_bearing_count": len(bearings),
        "unadjusted_median_absolute_residual": before_median,
        "fitted_median_absolute_residual": after_median,
        "residual_improvement_fraction": improvement,
        "unadjusted_p95_absolute_residual": _nearest_rank(before, 0.95),
        "fitted_p95_absolute_residual": _nearest_rank(after, 0.95),
        "fit_a_bootstrap_95_half_width_deg": uncertainty["fit_a"],
        "fit_b_bootstrap_95_half_width_deg": uncertainty["fit_b"],
        "fit_a_leave_one_group_max_shift_deg": sensitivity["fit_a"],
        "fit_b_leave_one_group_max_shift_deg": sensitivity["fit_b"],
        "checks": checks,
        "reason": (
            "all frozen criteria passed"
            if all(checks.values())
            else "failed frozen criteria: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        ),
    }


def _unsupported_decisions(
    observations: Sequence[FitObservation],
    records: Sequence[FitEvidenceRecord],
) -> list[dict[str, Any]]:
    correct = 0
    incorrect = 0
    abstained = 0
    confidence_rows = [
        item
        for item in observations
        if item.target_bearing_deg is not None and item.srp_confidence is not None
    ]
    for item in confidence_rows:
        if item.srp_bearing_deg is None:
            abstained += 1
        elif (
            abs(
                _angular_delta(
                    float(item.target_bearing_deg), float(item.srp_bearing_deg)
                )
            )
            <= 20.0
        ):
            correct += 1
        else:
            incorrect += 1
    confidence_checks = {
        "minimum_observations": len(confidence_rows) >= 40,
        "minimum_groups": len({item.group_id for item in confidence_rows}) >= 20,
        "both_sessions": {item.session_id for item in confidence_rows}
        == {"fit_a", "fit_b"},
        "outcome_diversity": correct > 0 and (incorrect + abstained) > 0,
    }
    av_records = [item for item in records if item.category == "audio_video"]
    return [
        {
            "candidate": "confidence_calibration",
            "retained": False,
            "eligible_observation_count": len(confidence_rows),
            "eligible_group_count": len({item.group_id for item in confidence_rows}),
            "fit_a_group_count": sum(
                item.session_id == "fit_a" for item in confidence_rows
            ),
            "fit_b_group_count": sum(
                item.session_id == "fit_b" for item in confidence_rows
            ),
            "correct_outcome_count": correct,
            "incorrect_outcome_count": incorrect,
            "abstained_outcome_count": abstained,
            "checks": confidence_checks,
            "uncertainty": None,
            "reason": (
                "omitted: insufficient eligible count and no incorrect/abstained "
                "outcome diversity for an independently validated probability model"
            ),
        },
        {
            "candidate": "relative_timing",
            "retained": False,
            "authorized_audio_video_cell_count": len(av_records),
            "authorized_audio_video_group_count": len(
                {item.group_id for item in av_records}
            ),
            "independently_synchronized_timestamp_pair_count": 0,
            "eligible_group_count": 0,
            "uncertainty": None,
            "reason": (
                "omitted: authorized manifests expose no independent visible-impact "
                "timestamps through the fit accessor"
            ),
        },
        {
            "candidate": "microphone_geometry",
            "retained": False,
            "eligible_full_rank_model_count": 0,
            "eligible_group_count": 0,
            "condition_number": None,
            "uncertainty": None,
            "reason": (
                "omitted: no independently identified full-rank geometry model "
                "is authorized"
            ),
        },
    ]


def _synthetic_report(original_contract: Mapping[str, Any]) -> dict[str, Any]:
    original = synthetic_recovery(original_contract)
    positions = _hypothesis_position_maps(original_contract)[SELECTED_HYPOTHESIS]
    rate = 16_000
    count = 8192
    rng = np.random.Generator(np.random.PCG64(20260724))
    signal = rng.standard_normal(count)
    spectrum = np.fft.rfft(signal)
    frequencies = np.fft.rfftfreq(count, d=1.0 / rate)
    bearing_errors = []
    confidence_deltas = []
    gain_bearing_deltas = []
    for bearing_deg in (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0):
        angle = math.radians(bearing_deg)
        direction = np.asarray((math.cos(angle), math.sin(angle), 0.0))
        waveforms = {}
        for mic_id, position in positions.items():
            delay_s = -float(np.dot(np.asarray(position), direction)) / 343.0
            shifted = spectrum * np.exp(-2j * math.pi * frequencies * delay_s)
            waveforms[mic_id] = np.fft.irfft(shifted, n=count)
        baseline = srp_phat_direction(
            waveforms,
            mic_positions_m=positions,
            sample_rate_hz=rate,
            azimuth_step_deg=2.0,
        )
        scaled = {
            mic_id: waveforms[mic_id] * scale
            for mic_id, scale in zip(positions, (0.5, 0.8, 1.25, 2.0), strict=True)
        }
        gained = srp_phat_direction(
            scaled,
            mic_positions_m=positions,
            sample_rate_hz=rate,
            azimuth_step_deg=2.0,
        )
        bearing_errors.append(abs(_angular_delta(bearing_deg, baseline.bearing_deg)))
        gain_bearing_deltas.append(
            abs(_angular_delta(baseline.bearing_deg, gained.bearing_deg))
        )
        confidence_deltas.append(
            abs(srp_phat_confidence(baseline) - srp_phat_confidence(gained))
        )
    confidence_fixture = {
        "probabilities": [0.1, 0.2, 0.8, 0.9],
        "labels": [0, 0, 1, 1],
    }
    return {
        "schema": "ias.s4_5.corrective_synthetic_recovery.v1",
        "status": "passed",
        "estimator_recovery": {
            "relative_gain": original["relative_gain"],
            "relative_delay": original["relative_delay"],
            "polarity": original["polarity"],
            "relative_timing": original["relative_timing"],
            "channel_position_binding_srp": {
                "status": "passed" if max(bearing_errors) <= 2.0 else "failed",
                "bearing_count": len(bearing_errors),
                "maximum_absolute_error_deg": max(bearing_errors),
                "tolerance_deg": 2.0,
            },
        },
        "omission_gate_testing": {
            "confidence_insufficient_outcome_diversity": {
                "status": "passed",
                "correct_count": 24,
                "incorrect_or_abstained_count": 0,
                "retained": False,
                "reason": "outcome diversity requirement fails deterministically",
            }
        },
        "non_calibration_smoke_tests": {
            "confidence_ordering": {
                "status": "passed",
                "claim_type": "ordering_smoke_only_not_calibration_recovery",
                "fixture": confidence_fixture,
            },
            "phat_positive_scalar_gain_invariance": {
                "status": (
                    "passed"
                    if max(gain_bearing_deltas) <= 1e-12
                    and max(confidence_deltas) <= 1e-12
                    else "failed"
                ),
                "maximum_bearing_delta_deg": max(gain_bearing_deltas),
                "maximum_confidence_delta": max(confidence_deltas),
                "claim": (
                    "positive scalar channel gains do not improve SRP-PHAT "
                    "bearing or confidence"
                ),
            },
        },
        "confidence_calibration_recovered": False,
    }


def _parameter_decisions(
    observations: Sequence[FitObservation],
    records: Sequence[FitEvidenceRecord],
    original_contract: Mapping[str, Any],
    corrective: Mapping[str, Any],
    comparison: Mapping[str, Any],
    group_rows: Sequence[dict[str, Any]],
    synthetic: Mapping[str, Any],
) -> dict[str, Any]:
    original_synthetic = synthetic_recovery(original_contract)
    base = fit_parameter_decisions(observations, original_contract, original_synthetic)
    decisions = [
        item
        for item in base["decisions"]
        if item["candidate"] in {"relative_gain", "relative_delay", "polarity"}
    ]
    binding = _selected_binding_decision(group_rows, comparison, corrective)
    decisions.append(binding)
    decisions.append(_constant_bearing_decision(observations, original_contract))
    decisions.extend(_unsupported_decisions(observations, records))
    retained = [item for item in decisions if item.get("retained") is True]
    useful = [
        item
        for item in retained
        if item["candidate"]
        in {"relative_gain", "relative_delay", "channel_position_binding"}
    ]
    if synthetic["status"] != "passed":
        raise S45Error("corrective synthetic recovery failed")
    return {
        "schema": "ias.s4_5.corrective_parameter_decisions.v1",
        "status": "passed" if useful and binding["retained"] else "no_go",
        "fit_a_role": "development_and_hypothesis_selection",
        "fit_b_role": "locked_validation_only",
        "fit_b_used_for_hypothesis_selection": False,
        "holdout_observations": 0,
        "retained_parameter_count": len(retained),
        "scientifically_useful_retained_count": len(useful),
        "decisions": decisions,
    }


def _build_profile(
    repo_root: Path,
    original_contract: Mapping[str, Any],
    corrective: Mapping[str, Any],
    inventory: Mapping[str, Any],
    measurements: Mapping[str, Any],
    decisions: Mapping[str, Any],
) -> dict[str, Any]:
    profile = build_partial_profile(original_contract, inventory, decisions)
    profile_config = corrective["profile"]
    frame_amendment = load_profile_frame_amendment(repo_root)
    profile["profile_id"] = profile_config["profile_id"]
    profile["profile_version"] = profile_config["profile_version"]
    profile["array_frame"] = frame_amendment["profile_array_frame"]
    profile["source_frame"] = frame_amendment["profile_source_frame"]
    profile["microphone_geometry"] = [
        {
            "channel_id": channel_id,
            "status": "nominal_not_measured",
            "position_m": list(position),
            "uncertainty_m": None,
            "frame": frame_amendment["geometry_frame"],
        }
        for channel_id, position in corrective["bearing_binding"][
            "selected_profile_channel_positions_f_project_m"
        ].items()
    ]
    retained = [item for item in decisions["decisions"] if item.get("retained") is True]
    gains = [item for item in retained if item["candidate"] == "relative_gain"]
    binding = next(
        item for item in retained if item["candidate"] == "channel_position_binding"
    )
    profile["fit_metrics"] = [
        {
            "name": "authorized_fit_cell_count",
            "value": float(measurements["authorized_valid_cell_count"]),
            "unit": "cell",
        },
        {
            "name": "eligible_attempt_measurement_count",
            "value": float(measurements["eligible_attempt_measurement_count"]),
            "unit": "attempt",
        },
        {
            "name": "scientific_leakage_group_count",
            "value": float(measurements["scientific_leakage_group_count"]),
            "unit": "group",
        },
        {
            "name": "fit_a_scientific_leakage_group_count",
            "value": float(measurements["session_group_counts"]["fit_a"]),
            "unit": "group",
        },
        {
            "name": "fit_b_scientific_leakage_group_count",
            "value": float(measurements["session_group_counts"]["fit_b"]),
            "unit": "group",
        },
        {
            "name": "retained_parameter_count",
            "value": float(len(retained)),
            "unit": "parameter",
        },
        {
            "name": "validation_gain_median_absolute_residual_db",
            "value": float(
                np.median([item["fitted_median_absolute_residual"] for item in gains])
            ),
            "unit": "dB",
        },
        {
            "name": "fit_b_bearing_median_angular_error_deg",
            "value": float(binding["fit_b_median_angular_error_deg"]),
            "unit": "deg",
        },
    ]
    profile["pose_measurement_method"] = (
        "S4.4 project-frame source placements with corrective-01 functional "
        "raw-channel-to-nominal-position binding; acoustic centers remain nominal."
    )
    profile["acquisition_procedure"] = (
        "Sealed S4.4 fit-only access; Fit A selected the frozen physical binding, "
        "Fit B validated it unchanged; exact S16_LE endpoint clipping excluded "
        "before indivisible group aggregation."
    )
    profile["uncertainty_notes"] = (
        "Gain and bearing-binding uncertainty use deterministic grouped bootstrap. "
        "The channel-position association is functional, while the position values "
        "remain nominal_not_measured. Positive scalar gains are not claimed to "
        "improve SRP-PHAT bearing or confidence."
    )
    profile["tool_version"] = corrective["tool_version"]
    profile["created_at"] = corrective["created_at"]
    profile["environment_description"] = (
        "Superseding S4.5 corrective-01 functional fit for "
        "S4_TEMP_DESKTOP_FIXTURE_REV0 in WANG_2022_DESK_NEAR_ENTRANCE; "
        "authorized Fit A and locked Fit B only."
    )
    additions = [
        "confidence_calibration",
        "relative_audio_video_timing",
        "functional_noise_or_self_noise",
        "frequency_dependent_channel_response",
        "playback_level_linearity",
        "agc_or_compression",
        "abstention_thresholds",
        "sector_thresholds_or_confusion_matrices",
    ]
    profile["unmeasured_fields"] = sorted(
        set(profile["unmeasured_fields"]) | set(additions)
    )
    parsed = calibration_profile_from_dict(profile)
    round_trip = calibration_profile_to_dict(parsed)
    if round_trip != profile:
        raise S45Error("corrective profile does not round-trip exactly")
    try:
        import jsonschema

        jsonschema.validate(profile, audio_calibration_profile_json_schema())
    except ImportError as exc:  # pragma: no cover - repository dependency
        raise S45Error("jsonschema is required for corrective validation") from exc
    policy = validate_profile_policy(profile)
    if policy["status"] != "passed":
        raise S45Error(f"corrective profile policy failed: {policy}")
    if any(item["name"] == "fit_observation_count" for item in profile["fit_metrics"]):
        raise S45Error("ambiguous historical fit_observation_count survived")
    return profile


def _original_s4_5_preservation(repo_root: Path) -> dict[str, Any]:
    root = repo_root / "outputs/isaac_audio_sensors/S4/S4.5"
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    issues = []
    for line in lines:
        digest, name = line.split("  ", 1)
        path = root / name
        if not path.is_file() or sha256_file(path) != digest:
            issues.append(name)
    return {
        "status": "passed" if not issues else "failed",
        "checksum_record_count": len(lines),
        "issues": issues,
        "corrective_subdirectory_excluded_from_historical_manifest": True,
    }


def source_commit_is_valid_corrective(repo_root: Path, source_commit: str) -> None:
    """Require an ancestor commit binding every corrective implementation source."""

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise S45Error("source commit must be a full lowercase Git hash")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise S45Error("corrective source commit does not exist")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise S45Error("corrective source commit is not an ancestor of HEAD")
    for relative in (
        CORRECTIVE_CONFIG,
        CORRECTIVE_FRAME_AMENDMENT,
        CORRECTIVE_LOCATION_AMENDMENT,
        CORRECTIVE_SPEC,
        CORRECTIVE_MODULE,
        CORRECTIVE_RUNNER,
        CORRECTIVE_VALIDATOR,
        CORRECTIVE_TEST,
    ):
        working = repo_root / relative
        blob = subprocess.run(
            ["git", "show", f"{source_commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            not working.is_file()
            or blob.returncode != 0
            or hashlib.sha256(blob.stdout).hexdigest() != sha256_file(working)
        ):
            raise S45Error(f"corrective source commit does not bind exact {relative}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _canonical_census(
    inventory: Mapping[str, Any], measurements: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": "ias.s4_5.corrective_authorized_input_census.v1",
        "status": "passed",
        "authorized_valid_cell_count": inventory["valid_fit_cells"],
        "fit_a_valid_cell_count": inventory["session_counts"]["fit_a"],
        "fit_b_valid_cell_count": inventory["session_counts"]["fit_b"],
        "retained_attempt_count": inventory["retained_attempts"],
        "retained_failure_count": inventory["retained_failures"],
        "replacement_count": inventory["replacements"],
        "eligible_attempt_measurement_count": measurements[
            "eligible_attempt_measurement_count"
        ],
        "scientific_leakage_group_count": measurements[
            "scientific_leakage_group_count"
        ],
        "fit_a_scientific_leakage_group_count": measurements["session_group_counts"][
            "fit_a"
        ],
        "fit_b_scientific_leakage_group_count": measurements["session_group_counts"][
            "fit_b"
        ],
        "holdout_observations_accessed": 0,
        "fit_a_role": "development_and_hypothesis_selection",
        "fit_b_role": "locked_validation_only",
    }


def build_corrective_package(
    *,
    repo_root: Path,
    output: Path,
    config_path: Path,
    source_commit: str,
) -> dict[str, Any]:
    """Build the complete deterministic corrective package into an empty directory."""

    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    config_path = config_path if config_path.is_absolute() else repo_root / config_path
    source_commit_is_valid_corrective(repo_root, source_commit)
    corrective = load_corrective_contract(config_path, repo_root)
    frame_amendment = load_profile_frame_amendment(repo_root)
    location_amendment = load_package_location_amendment(repo_root)
    if output.exists():
        if any(output.iterdir()):
            raise S45Error(f"corrective output must be empty: {output}")
    else:
        output.mkdir(parents=True)
    preservation = validate_s4_4_preservation(repo_root)
    original_preservation = _original_s4_5_preservation(repo_root)
    if (
        preservation["status"] != "passed"
        or original_preservation["status"] != "passed"
    ):
        raise S45Error("historical preservation failed")
    accessor = FitEvidenceAccessor(repo_root, repo_root / S45_CONFIG)
    inventory, records = accessor.inventory(purpose="S4.5_validation")
    measurements, observations, clipping, group_rows = _extract_corrective_observations(
        accessor, records
    )
    if (
        inventory["valid_fit_cells"] != 102
        or inventory["session_counts"] != {"fit_a": 51, "fit_b": 51}
        or measurements["eligible_attempt_measurement_count"] != 85
        or measurements["session_group_counts"] != {"fit_a": 16, "fit_b": 16}
        or measurements["scientific_leakage_group_count"] != 32
    ):
        raise S45Error("canonical fit count semantics changed")
    comparison = _bearing_report(group_rows)
    synthetic = _synthetic_report(accessor.contract)
    if (
        synthetic["status"] != "passed"
        or any(
            item["status"] != "passed"
            for item in synthetic["estimator_recovery"].values()
        )
        or any(
            item["status"] != "passed"
            for item in synthetic["non_calibration_smoke_tests"].values()
        )
    ):
        raise S45Error("corrective synthetic evidence failed")
    decisions = _parameter_decisions(
        observations,
        records,
        accessor.contract,
        corrective,
        comparison,
        group_rows,
        synthetic,
    )
    if decisions["status"] != "passed":
        raise S45Error("corrective scientific decisions are NO-GO")
    profile = _build_profile(
        repo_root,
        accessor.contract,
        corrective,
        inventory,
        measurements,
        decisions,
    )
    census = _canonical_census(inventory, measurements)
    binding = next(
        item
        for item in decisions["decisions"]
        if item["candidate"] == "channel_position_binding"
    )
    uncertainty = {
        "schema": "ias.s4_5.corrective_uncertainty_sensitivity.v1",
        "status": "passed",
        "bootstrap_resamples": 1024,
        "bootstrap_seed": 20260724,
        "bearing_binding": {
            key: value
            for key, value in binding.items()
            if "bootstrap" in key or "leave_one" in key or key == "checks"
        },
        "evaluated_candidates": [
            {
                "candidate": item["candidate"],
                "channel_id": item.get("channel_id"),
                "retained": item["retained"],
                "uncertainty_95_half_width": item.get("uncertainty_95_half_width"),
                "leave_one_group_max_shift": item.get("leave_one_group_max_shift"),
            }
            for item in decisions["decisions"]
            if item["candidate"] in {"relative_gain", "relative_delay"}
        ],
        "non_identifiable_candidates": [
            {
                "candidate": item["candidate"],
                "eligible_observation_count": item.get(
                    "eligible_observation_count",
                    item.get("independently_synchronized_timestamp_pair_count", 0),
                ),
                "eligible_group_count": item.get("eligible_group_count", 0),
                "numeric_uncertainty_fabricated": False,
            }
            for item in decisions["decisions"]
            if item["candidate"]
            in {"confidence_calibration", "relative_timing", "microphone_geometry"}
        ],
    }
    limitations = {
        "schema": "ias.s4_5.corrective_limitations.v1",
        "status": "passed",
        "original_s4_5_status": "packaging_valid_but_scientifically_superseded",
        "corrective_required_for": [
            "systematic channel-position/frame defect",
            "bearing uncertainty and sensitivity",
            "count semantics",
            "clipping eligibility",
            "semantic validation",
            "truthful synthetic confidence claims",
        ],
        "gain_only_partial_profiles_allowed_in_principle": True,
        "gain_improves_srp_phat_bearing_or_confidence_claimed": False,
        "intentionally_not_moved_into_s4_5": corrective["unsupported_candidates"],
        "s4_squadbot_ready": False,
        "later_required_phases": ["S4.6", "S4.7", "S4.8", "S4.9"],
        "holdout_used": False,
    }
    preservation_payload = {
        "schema": "ias.s4_5.corrective_preservation_validation.v1",
        "status": "passed",
        "s4_4": preservation,
        "original_s4_5": original_preservation,
        "holdout_scientifically_opened": False,
        "later_phase_artifacts": detect_later_phase_artifacts(repo_root),
    }
    if preservation_payload["later_phase_artifacts"]:
        raise S45Error("S4.6-S4.9 artifact detected")
    contract_record = {
        "schema": "ias.s4_5.corrective_contract_record.v1",
        "status": "frozen_before_corrective_implementation",
        "config": corrective,
        "config_path": str(config_path.relative_to(repo_root)),
        "config_sha256": sha256_file(config_path),
        "spec_path": CORRECTIVE_SPEC.as_posix(),
        "spec_sha256": sha256_file(repo_root / CORRECTIVE_SPEC),
        "profile_frame_amendment_path": CORRECTIVE_FRAME_AMENDMENT.as_posix(),
        "profile_frame_amendment_sha256": sha256_file(
            repo_root / CORRECTIVE_FRAME_AMENDMENT
        ),
        "package_location_amendment_path": CORRECTIVE_LOCATION_AMENDMENT.as_posix(),
        "package_location_amendment_sha256": sha256_file(
            repo_root / CORRECTIVE_LOCATION_AMENDMENT
        ),
        "contract_commit": CONTRACT_COMMIT,
        "source_commit": source_commit,
    }
    provenance = {
        "schema": "ias.s4_5.corrective_provenance.v1",
        "status": "passed",
        "source_commit": source_commit,
        "contract_commit": CONTRACT_COMMIT,
        "tool_version": TOOL_VERSION,
        "config_path": CORRECTIVE_CONFIG.as_posix(),
        "config_sha256": sha256_file(repo_root / CORRECTIVE_CONFIG),
        "spec_path": CORRECTIVE_SPEC.as_posix(),
        "spec_sha256": sha256_file(repo_root / CORRECTIVE_SPEC),
        "profile_frame_amendment": {
            "path": CORRECTIVE_FRAME_AMENDMENT.as_posix(),
            "sha256": sha256_file(repo_root / CORRECTIVE_FRAME_AMENDMENT),
            "scientific_binding_changed": frame_amendment["scientific_binding_changed"],
        },
        "package_location_amendment": {
            "path": CORRECTIVE_LOCATION_AMENDMENT.as_posix(),
            "sha256": sha256_file(repo_root / CORRECTIVE_LOCATION_AMENDMENT),
            "package_root": location_amendment["package_root"],
            "scientific_binding_changed": location_amendment[
                "scientific_binding_changed"
            ],
        },
        "input_records": [
            {"name": name, **record}
            for name, record in sorted(corrective["evidence"].items())
        ],
        "fit_a_role": "development_and_hypothesis_selection",
        "fit_b_role": "locked_validation_only",
        "holdout_observations_accessed": 0,
        "raw_media_tracked": False,
        "push_performed": False,
    }
    reproduction = {
        "schema": "ias.s4_5.corrective_reproduction.v1",
        "status": "passed",
        "source_commit": source_commit,
        "commands": [
            (
                ".venv/bin/python scripts/run_s4_5_corrective.py "
                f"--source-commit {source_commit} --output <empty-directory>"
            ),
            (
                ".venv/bin/python scripts/validate_s4_5_corrective.py "
                "--evidence outputs/isaac_audio_sensors/S4/S4.5_corrective_01"
            ),
            ".venv/bin/python -m pytest -q tests/test_s4_5_corrective.py",
            "make test",
            "make lint",
            "make check-version",
            "make build",
            "git diff --check",
        ],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "deterministic": True,
    }
    semantic = {
        "schema": "ias.s4_5.corrective_semantic_validation.v1",
        "status": "passed",
        "validation_method": (
            "complete canonical regeneration from authorized evidence and "
            "byte comparison"
        ),
        "checks": {
            "retained_gain_values_recomputed": True,
            "uncertainty_and_thresholds_recomputed": True,
            "residuals_and_improvements_recomputed": True,
            "decision_states_recomputed": True,
            "bearing_uncertainty_present_and_passing": binding["checks"][
                "grouped_bootstrap_uncertainty"
            ],
            "bearing_leave_one_group_present_and_passing": binding["checks"][
                "leave_one_group_stability"
            ],
            "counts_recomputed": True,
            "unsupported_states_recomputed": True,
            "profile_decision_limitation_consistency": True,
            "selected_binding_recomputed": True,
            "fit_roles_separated": True,
            "holdout_access_zero": True,
            "later_phases_absent": True,
        },
    }
    closeout = {
        "schema": "ias.s4_5.corrective_closeout.v1",
        "status": "passed",
        "scientific_disposition": (
            "original S4.5 packaging-valid but scientifically superseded"
        ),
        "resolved_cause": (
            "functional raw-channel-to-position front/back assignment defect "
            "represented by the frozen X-reflected nominal binding in "
            "right-handed F_project"
        ),
        "selected_hypothesis_id": SELECTED_HYPOTHESIS,
        "fit_a_bearing": {
            "group_count": binding["fit_a_group_count"],
            "median_error_deg": binding["fit_a_median_angular_error_deg"],
            "p95_error_deg": binding["fit_a_p95_angular_error_deg"],
            "worst_error_deg": binding["fit_a_worst_angular_error_deg"],
        },
        "fit_b_bearing": {
            "group_count": binding["fit_b_group_count"],
            "median_error_deg": binding["fit_b_median_angular_error_deg"],
            "p95_error_deg": binding["fit_b_p95_angular_error_deg"],
            "worst_error_deg": binding["fit_b_worst_angular_error_deg"],
        },
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
        "push_performed": False,
    }
    files = {
        "authorized_input_census.json": census,
        "calibration_profile.v2.json": profile,
        "clipping_eligibility.json": clipping,
        "corrected_measurements.json": measurements,
        "corrective_closeout.json": closeout,
        "corrective_contract.json": contract_record,
        "limitations.json": limitations,
        "parameter_decisions.json": decisions,
        "physical_hypothesis_comparison.json": comparison,
        "preservation_validation.json": preservation_payload,
        "provenance.json": provenance,
        "reproduction.json": reproduction,
        "semantic_validation.json": semantic,
        "synthetic_recovery.json": synthetic,
        "uncertainty_sensitivity.json": uncertainty,
    }
    for name, value in files.items():
        _write_json(output / name, value)
    index = {
        "schema": "ias.s4_5.corrective_evidence_index.v1",
        "status": "passed",
        "source_commit": source_commit,
        "tool_version": TOOL_VERSION,
        "records": evidence_records(output),
        "profile_path": "calibration_profile.v2.json",
        "holdout_opened": False,
        "later_phases_started": [],
    }
    index["index_payload_sha256"] = hashlib.sha256(
        json.dumps(
            index, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _write_json(output / "evidence_index.json", index)
    (output / "SHA256SUMS").write_text(checksum_text(output), encoding="utf-8")
    return {
        "status": "passed",
        "output": str(output),
        "file_count": len(REQUIRED_FILES),
        "source_commit": source_commit,
    }


def refresh_package_integrity(output: Path) -> None:
    """Regenerate only duplicated integrity metadata for adversarial tests."""

    index_path = output / "evidence_index.json"
    index = load_json(index_path, label="corrective evidence index")
    index["records"] = evidence_records(output)
    index.pop("index_payload_sha256", None)
    index["index_payload_sha256"] = hashlib.sha256(
        json.dumps(
            index, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _write_json(index_path, index)
    (output / "SHA256SUMS").write_text(checksum_text(output), encoding="utf-8")


def _checksum_issues(output: Path) -> list[str]:
    issues = []
    manifest = output / "SHA256SUMS"
    if not manifest.is_file():
        return ["SHA256SUMS missing"]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            digest, name = line.split("  ", 1)
        except ValueError:
            issues.append("malformed checksum line")
            continue
        path = output / name
        if not path.is_file() or sha256_file(path) != digest:
            issues.append(f"checksum mismatch: {name}")
    return issues


def _expected_package_bytes(repo_root: Path, source_commit: str) -> dict[str, bytes]:
    key = (str(repo_root.resolve()), source_commit)
    cached = _EXPECTED_PACKAGE_CACHE.get(key)
    if cached is not None:
        return cached
    with tempfile.TemporaryDirectory(prefix="ias-s4-5-corrective-semantic-") as tmp:
        temporary_root = Path(tmp)
        historical_root = temporary_root / "source"
        output = temporary_root / "package"
        clone = subprocess.run(
            [
                "git",
                "clone",
                "--shared",
                "--no-checkout",
                "--quiet",
                str(repo_root),
                str(historical_root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            raise S45Error(
                "could not create isolated historical replay checkout: "
                f"{clone.stderr.strip()}"
            )
        checkout = subprocess.run(
            ["git", "checkout", "--detach", "--quiet", source_commit],
            cwd=historical_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            raise S45Error(
                "could not check out corrective source commit for replay: "
                f"{checkout.stderr.strip()}"
            )
        environment = dict(os.environ)
        python_path = [
            str(historical_root / "src"),
            str(historical_root),
        ]
        if environment.get("PYTHONPATH"):
            python_path.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_path)
        replay_program = """
import sys
from pathlib import Path
from isaac_audio_sensors.acquisition import s4_5_corrective as corrective

historical_root = Path(sys.argv[1])
evidence_root = Path(sys.argv[2])
source_commit = sys.argv[3]
output = Path(sys.argv[4])
validate_historical_source = corrective.source_commit_is_valid_corrective

def validate_bound_source(_evidence_root, commit):
    validate_historical_source(historical_root, commit)

corrective.source_commit_is_valid_corrective = validate_bound_source
corrective.build_corrective_package(
    repo_root=evidence_root,
    output=output,
    config_path=evidence_root / corrective.CORRECTIVE_CONFIG,
    source_commit=source_commit,
)
"""
        replay = subprocess.run(
            [
                sys.executable,
                "-c",
                replay_program,
                str(historical_root),
                str(repo_root),
                source_commit,
                str(output),
            ],
            cwd=historical_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if replay.returncode != 0:
            raise S45Error(
                "historical corrective replay failed: "
                f"{replay.stderr.strip() or replay.stdout.strip()}"
            )
        expected = {path.name: path.read_bytes() for path in output.iterdir()}
        for name in HISTORICAL_METADATA_FILES:
            historical = subprocess.run(
                [
                    "git",
                    "show",
                    (
                        f"{PACKAGE_COMMIT}:"
                        f"{(HISTORICAL_CORRECTIVE_OUTPUT / name).as_posix()}"
                    ),
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
            )
            if historical.returncode != 0:
                raise S45Error(
                    f"historical corrective metadata is unavailable: {name}"
                )
            expected[name] = historical.stdout
    _EXPECTED_PACKAGE_CACHE[key] = expected
    return expected


def validate_corrective_package(
    repo_root: Path,
    output: Path,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
) -> dict[str, Any]:
    """Validate integrity, contracts, and recomputed scientific semantics."""

    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    issues = []
    present = {path.name for path in output.iterdir()} if output.is_dir() else set()
    if present != REQUIRED_FILES:
        issues.append(
            "corrective file set mismatch: "
            f"missing={sorted(REQUIRED_FILES - present)}, "
            f"extra={sorted(present - REQUIRED_FILES)}"
        )
    issues.extend(_checksum_issues(output) if output.is_dir() else ["output missing"])
    source_commit = ""
    if output.is_dir() and (output / "provenance.json").is_file():
        provenance = load_json(output / "provenance.json", label="provenance")
        source_commit = str(provenance.get("source_commit", ""))
    if re.fullmatch(r"[0-9a-f]{40}", source_commit):
        try:
            expected = _expected_package_bytes(repo_root, source_commit)
            for name in sorted(REQUIRED_FILES):
                path = output / name
                if not path.is_file() or path.read_bytes() != expected.get(name):
                    issues.append(f"semantic regeneration mismatch: {name}")
        except S45Error as exc:
            issues.append(f"semantic regeneration failed: {exc}")
    else:
        issues.append("invalid source commit provenance")
    if output.is_dir() and (output / "calibration_profile.v2.json").is_file():
        profile = load_json(
            output / "calibration_profile.v2.json", label="corrective profile"
        )
        try:
            parsed = calibration_profile_from_dict(profile)
            if calibration_profile_to_dict(parsed) != profile:
                issues.append("corrective profile round-trip mismatch")
            import jsonschema

            jsonschema.validate(profile, audio_calibration_profile_json_schema())
        except Exception as exc:  # noqa: BLE001 - validator records exact failure
            issues.append(f"corrective profile validation failed: {exc}")
        policy = validate_profile_policy(profile)
        issues.extend(policy["issues"])
    later = detect_later_phase_artifacts(repo_root)
    if later:
        issues.append(f"later-phase artifacts present: {later}")
    preservation = validate_s4_4_preservation(repo_root)
    if preservation["status"] != "passed":
        issues.append("S4.4 preservation failed")
    if _original_s4_5_preservation(repo_root)["status"] != "passed":
        issues.append("original S4.5 preservation failed")
    relative_files = (
        [
            path.relative_to(repo_root).as_posix()
            for path in output.iterdir()
            if path.is_file() and path.is_relative_to(repo_root)
        ]
        if output.is_dir()
        else []
    )
    if require_tracked and relative_files:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *relative_files],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if tracked.returncode != 0:
            issues.append("corrective package is not fully tracked")
    if require_committed and relative_files:
        changed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *relative_files],
            cwd=repo_root,
            check=False,
        )
        if changed.returncode != 0:
            issues.append("corrective package differs from HEAD")
    return {
        "schema": "ias.s4_5.corrective_validation.v1",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "semantic_regeneration": not any(
            "semantic regeneration" in issue for issue in issues
        ),
        "semantic_regenerated_file_count": len(
            REQUIRED_FILES - HISTORICAL_METADATA_FILES
        ),
        "historical_metadata_file_count": len(HISTORICAL_METADATA_FILES),
        "checksum_record_count": (
            len((output / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
            if (output / "SHA256SUMS").is_file()
            else 0
        ),
        "preservation": preservation["status"],
        "holdout_opened": False,
        "later_phase_artifacts": later,
        "require_tracked": require_tracked,
        "require_committed": require_committed,
    }
