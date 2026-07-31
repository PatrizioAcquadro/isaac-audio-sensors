"""Preregistration gate for a new unseen S4.8 recovery holdout."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Mapping
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    validate_source_checkpoint,
)
from isaac_audio_sensors.acquisition.s4_8_official_acquisition import (
    S48OfficialAcquisitionError,
    validate_session_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_official_acquisition import (
    next_attempt as next_official_attempt,
)
from isaac_audio_sensors.acquisition.s4_8_official_acquisition import (
    validate_attempt_ledger as validate_official_attempt_ledger,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256

AMENDMENT_PATH = Path("configs/s4_8_recovery_amendment_02.v2.json")
AMENDMENT_SCHEMA_PATH = Path("docs/schemas/s4_8_recovery_amendment_02.v2.schema.json")
HISTORICAL_AMENDMENT_PATH = Path("configs/s4_8_recovery_amendment_02.v1.json")
HISTORICAL_AMENDMENT_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_amendment_02.v1.schema.json"
)
HOLDOUT_BINDING_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_unseen_holdout_binding.v2.schema.json"
)
AMENDMENT_SPEC_PATH = Path(
    "docs/development/specs/s4_8_recovery_amendment_02_preholdout_v2.md"
)
EVALUATOR_BINDING_PATH = Path(
    "configs/s4_8_recovery_amendment_02_evaluator_binding.v2.json"
)
EVALUATOR_BINDING_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_amendment_02_evaluator_binding.v2.schema.json"
)
EVALUATOR_BINDING_SHA256 = (
    "275984676d822ac2cf002d72791eef2694042da6d3cac1419b4876f0f4a39902"
)
EVALUATOR_BINDING_SCHEMA_SHA256 = (
    "cd2c367381d19abb78e9af32ddfe2600c19fd024b5b80551386d1c9e6d393380"
)
REVIEW_FIELDS = frozenset(
    {
        "schema",
        "amendment_id",
        "source_commit",
        "decision",
        "independent",
        "reviewer_id",
        "reviewed_at_utc",
    }
)

PLANNED_TAKE_COUNT = 37
LEAKAGE_GROUP_COUNT = 15
DIRECTION_BEARINGS = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
PRODUCT_BEARINGS = (0.0, 90.0, 180.0, 270.0)
PRODUCT_CONDITIONS = (
    "front_occluded",
    "right_noise",
    "rear_noise",
    "left_occluded",
)
SQUADBOT_DIRECTION_POLICY_ID = "purdue_asn_v2_initial_engineering_2026-07-28"
SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD = 0.75
SQUADBOT_TAKE_AGGREGATION_CONTRACT = {
    "representative_bearing_field": "estimated_bearing_deg_f_project",
    "representative_bearing_derivation": (
        "linear_median_of_valid_exact_window_bearings"
    ),
    "mapping_application": "once_per_take_to_representative_bearing",
    "no_valid_bearing_result": "unavailable",
    "failed_or_missing_take_result": "adverse",
    "active_unavailable_result": "incorrect",
    "rear_unavailable_result": "correct_only_when_take_not_failed",
    "silence_unavailable_result": "correct_only_when_take_not_failed",
}
CONTINUOUS_BEARING_DIAGNOSTIC_CRITERIA = frozenset(
    {
        "bearing_median_absolute_error_stratum_a",
        "bearing_p95_absolute_error_stratum_a",
        "bearing_worst_absolute_error_stratum_a",
        "bearing_median_absolute_error_stratum_b",
        "within_cell_bearing_circular_range_stratum_a",
        "sim_adjusted_bearing_median_delta_vs_real",
        "bearing_median_absolute_error_stratum_a_stretch",
        "bearing_p95_absolute_error_stratum_a_stretch",
        "sim_adjusted_bearing_median_delta_vs_real_stretch",
    }
)
SUPERSEDED_SECTOR_CRITERIA = frozenset(
    {
        "sector_accuracy_stratum_b",
        "sector_accuracy_stratum_b_stretch",
    }
)
STRATUM_COUNTS = {
    "A_controlled_boundary_sweep": 24,
    "B_center_nominal_level": 4,
    "C_center_low_level": 4,
    "D_silence": 3,
    "E_impact_audio_video": 2,
}


def bearing_to_squadbot_direction(bearing_deg: float | None) -> str | None:
    """Map a diagnostic bearing to the frozen consumer direction value."""

    if (
        bearing_deg is None
        or isinstance(bearing_deg, bool)
        or not isinstance(bearing_deg, (int, float))
    ):
        return None
    bearing = float(bearing_deg)
    if not isfinite(bearing):
        return None
    normalized = bearing % 360.0
    if normalized < 45.0 or normalized >= 315.0:
        return "forward"
    if normalized < 165.0:
        return "right"
    if normalized < 195.0:
        return "None"
    return "left"


def reclassify_engineering_take(
    *,
    take_id: str,
    target_bearing_deg: float,
    estimated_bearing_deg: float | None,
    bearing_absolute_error_deg: float | None,
    take_failed: bool = False,
) -> dict[str, Any]:
    """Reclassify one non-holdout engineering take without changing its evidence."""

    expected = bearing_to_squadbot_direction(target_bearing_deg)
    if expected is None:
        raise ValueError("target_bearing_deg must be a finite numeric bearing")
    observed = bearing_to_squadbot_direction(estimated_bearing_deg)
    expected_unavailable = expected == "None"
    observed_unavailable = observed in {None, "None"}
    categorical_correct = not take_failed and (
        observed_unavailable if expected_unavailable else observed == expected
    )
    return {
        "take_id": take_id,
        "policy_id": SQUADBOT_DIRECTION_POLICY_ID,
        "expected_direction": expected,
        "observed_direction": observed,
        "categorical_correct": categorical_correct,
        "categorical_metric_role": "primary_gating",
        "categorical_aggregation": SQUADBOT_TAKE_AGGREGATION_CONTRACT,
        "take_failed": take_failed,
        "estimated_bearing_deg": estimated_bearing_deg,
        "bearing_absolute_error_deg": bearing_absolute_error_deg,
        "continuous_bearing_metric_role": "diagnostic_non_gating",
    }


EXPECTED_DENOMINATOR_OVERRIDES = {
    "bearing_median_absolute_error_stratum_b": 4,
    "sector_accuracy_stratum_b": 4,
    "candidate_coverage_strata_ab": 28,
    "frame_to_adapter_latency_p95": 37,
    "capture_to_frame_offline_spread": 37,
    "raw_channel_health_failure_count": 148,
    "major_polarity_anomaly_count": 148,
    "sustained_clipping_take_count": 37,
    "maximum_clip_run_samples": 37,
    "take_failure_rate": 37,
    "confidence_median_stratum_b": 4,
    "low_level_confidence_monotonicity": 4,
    "coarse_av_association_residual_stratum_e": 2,
    "sim_adjusted_bearing_median_delta_vs_real": 28,
    "sector_accuracy_stratum_b_stretch": 4,
    "candidate_coverage_strata_ab_stretch": 28,
    "sim_adjusted_bearing_median_delta_vs_real_stretch": 28,
}

EXPECTED_UNCHANGED_DENOMINATORS = {
    "bearing_median_absolute_error_stratum_a": 24,
    "bearing_p95_absolute_error_stratum_a": 24,
    "bearing_worst_absolute_error_stratum_a": 24,
    "within_cell_bearing_circular_range_stratum_a": 8,
    "within_cell_pair_tdoa_range_stratum_a": 48,
    "bearing_median_absolute_error_stratum_a_stretch": 24,
    "bearing_p95_absolute_error_stratum_a_stretch": 24,
}

EXPECTED_NULL_DENOMINATORS = {
    "silence_abstention_rate_stratum_d",
    "active_abstention_rate_strata_ab",
    "sub_floor_direction_emission_count",
    "sim_adjustment_worsened_gating_metric_count",
    "active_abstention_rate_strata_ab_stretch",
}

FROZEN_CRITERIA_REGISTER_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.7_corrective_03/criteria_register.json"
)
FROZEN_CRITERIA_REGISTER_SHA256 = (
    "64e9fc170e81174f975d5d67b7ce94b765f967b3826e5e7cd61746ab59e25375"
)
FROZEN_SCIENTIFIC_SEMANTICS_SHA256 = (
    "91c12a090102c7b1de6c250f5edd654620d845c5f1044c8ca466961f8756539d"
)

EXPECTED_ARTIFACT_KEYS = {
    "original_s4_8": frozenset(
        {
            "grant",
            "authorization",
            "ledger",
            "journal",
            "recovery_context",
            "derived_terminal_state",
            "terminal_manifest",
            "final_validation",
        }
    ),
    "recovery_amendment_01": frozenset(
        {
            "grant",
            "authorization",
            "ledger",
            "journal",
            "post_consumption_progress",
            "recovery_context",
            "derived_terminal_state",
            "independent_review",
            "terminal_manifest",
            "final_validation",
        }
    ),
}


def _safe_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise s4_8.S48Error(f"invalid amendment_02 path: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise s4_8.S48Error(f"unsafe amendment_02 path: {value!r}")
    return Path(*pure.parts)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def load_amendment(repo_root: Path) -> dict[str, Any]:
    """Load and validate the additive 37-take preregistration revision."""

    root = repo_root.resolve()
    amendment = s4_8.load_json(root / AMENDMENT_PATH)
    schema = s4_8.load_json(root / AMENDMENT_SCHEMA_PATH)
    try:
        jsonschema.validate(amendment, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 schema failure: {exc.message}"
        ) from exc
    historical = _load_historical_amendment(root, amendment)
    _validate_protocol_bindings(root, amendment, historical)
    _validate_preliminary_bindings(root, amendment)
    _validate_namespaces(amendment, historical)
    return amendment


def _load_historical_amendment(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> dict[str, Any]:
    supersedes = amendment["supersedes"]
    if _safe_relative(supersedes["path"]) != HISTORICAL_AMENDMENT_PATH:
        raise s4_8.S48Error("S4.8 recovery amendment_02 historical path mismatch")
    path = repo_root / HISTORICAL_AMENDMENT_PATH
    if not path.is_file() or s4_8.sha256_file(path) != supersedes["sha256"]:
        raise s4_8.S48Error("S4.8 recovery amendment_02 historical binding mismatch")
    historical = s4_8.load_json(path)
    schema = s4_8.load_json(repo_root / HISTORICAL_AMENDMENT_SCHEMA_PATH)
    try:
        jsonschema.validate(historical, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 historical schema failure: {exc.message}"
        ) from exc
    return historical


def _validate_bound_file(
    repo_root: Path,
    container: Mapping[str, Any],
    *,
    path_key: str,
    digest_key: str,
) -> Path:
    path = repo_root / _safe_relative(container[path_key])
    if not path.is_file() or s4_8.sha256_file(path) != container[digest_key]:
        raise s4_8.S48Error(f"S4.8 recovery amendment_02 binding mismatch: {path_key}")
    return path


def _validate_protocol_bindings(
    repo_root: Path,
    amendment: Mapping[str, Any],
    historical: Mapping[str, Any],
) -> None:
    _validate_bound_file(
        repo_root,
        amendment,
        path_key="specification_path",
        digest_key="specification_sha256",
    )
    revision = amendment["protocol_revision"]
    historical_scientific = historical["scientific_preregistration"]
    if any(
        revision[key] != historical_scientific[key]
        for key in (
            "criteria_config_path",
            "criteria_config_sha256",
            "criteria_schema_path",
            "criteria_schema_sha256",
            "criteria_spec_path",
            "criteria_spec_sha256",
        )
    ):
        raise s4_8.S48Error(
            "S4.8 37-take criteria binding does not preserve frozen history"
        )
    bindings = (
        ("design_manifest_path", "design_manifest_sha256"),
        ("design_schema_path", "design_schema_sha256"),
        ("denominators_path", "denominators_sha256"),
        ("denominators_schema_path", "denominators_schema_sha256"),
        ("criteria_config_path", "criteria_config_sha256"),
        ("criteria_schema_path", "criteria_schema_sha256"),
        ("criteria_spec_path", "criteria_spec_sha256"),
    )
    for path_key, digest_key in bindings:
        _validate_bound_file(
            repo_root,
            revision,
            path_key=path_key,
            digest_key=digest_key,
        )
    unseen = amendment["unseen_holdout"]
    _validate_bound_file(
        repo_root,
        unseen,
        path_key="binding_schema_path",
        digest_key="binding_schema_sha256",
    )
    design = s4_8.load_json(
        repo_root / _safe_relative(revision["design_manifest_path"])
    )
    design_schema = s4_8.load_json(
        repo_root / _safe_relative(revision["design_schema_path"])
    )
    try:
        jsonschema.validate(design, design_schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 37-take design schema failure: {exc.message}"
        ) from exc
    _validate_design_manifest(design)
    denominators = s4_8.load_json(
        repo_root / _safe_relative(revision["denominators_path"])
    )
    denominator_schema = s4_8.load_json(
        repo_root / _safe_relative(revision["denominators_schema_path"])
    )
    try:
        jsonschema.validate(denominators, denominator_schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 37-take denominator schema failure: {exc.message}"
        ) from exc
    _validate_denominators(repo_root, denominators, design)


def _take_signature(take: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        take["stratum_id"],
        take["bearing_deg"],
        take["radius_m"],
        take["playback_gain"],
        take["repetition"],
        take["leakage_group_id"],
        take["condition_id"],
    )


def _validate_design_manifest(design: Mapping[str, Any]) -> None:
    takes = design["take_order"]
    if (
        design["planned_take_count"] != PLANNED_TAKE_COUNT
        or len(takes) != PLANNED_TAKE_COUNT
        or design["leakage_group_count"] != LEAKAGE_GROUP_COUNT
        or design["stratum_counts"] != STRATUM_COUNTS
    ):
        raise s4_8.S48Error("S4.8 37-take design count mismatch")
    if [take["sequence_index"] for take in takes] != list(
        range(1, PLANNED_TAKE_COUNT + 1)
    ):
        raise s4_8.S48Error("S4.8 37-take design sequence mismatch")
    take_ids = [take["planned_take_id"] for take in takes]
    if len(set(take_ids)) != PLANNED_TAKE_COUNT:
        raise s4_8.S48Error("S4.8 37-take design identity mismatch")
    actual_counts = Counter(take["stratum_id"] for take in takes)
    if dict(actual_counts) != STRATUM_COUNTS:
        raise s4_8.S48Error("S4.8 37-take design stratum mismatch")
    groups = {take["leakage_group_id"] for take in takes}
    if len(groups) != LEAKAGE_GROUP_COUNT:
        raise s4_8.S48Error("S4.8 37-take leakage-group mismatch")
    if (
        design["direction_contract"]["take_aggregation"]
        != SQUADBOT_TAKE_AGGREGATION_CONTRACT
    ):
        raise s4_8.S48Error("S4.8 categorical take aggregation mismatch")

    expected: list[tuple[Any, ...]] = [
        (
            "D_silence",
            None,
            None,
            None,
            1,
            "ambient_silence",
            "silence",
        ),
    ]
    for bearing in DIRECTION_BEARINGS:
        group = f"direction_{int(bearing):03d}"
        for repetition in (1, 2, 3):
            expected.append(
                (
                    "A_controlled_boundary_sweep",
                    bearing,
                    0.8,
                    0.75,
                    repetition,
                    group,
                    "nominal_direction",
                )
            )
    expected.append(("D_silence", None, None, None, 2, "ambient_silence", "silence"))
    for bearing, condition in zip(
        PRODUCT_BEARINGS,
        PRODUCT_CONDITIONS,
        strict=True,
    ):
        expected.append(
            (
                "B_center_nominal_level",
                bearing,
                0.8,
                0.75,
                1,
                f"product_{int(bearing):03d}",
                condition,
            )
        )
    for bearing in PRODUCT_BEARINGS:
        expected.append(
            (
                "C_center_low_level",
                bearing,
                0.8,
                0.35,
                1,
                f"product_{int(bearing):03d}",
                "low_volume",
            )
        )
    expected.extend(
        (
            (
                "D_silence",
                None,
                None,
                None,
                3,
                "ambient_silence",
                "silence",
            ),
            (
                "E_impact_audio_video",
                None,
                None,
                None,
                1,
                "impact_position_01",
                "impact",
            ),
            (
                "E_impact_audio_video",
                None,
                None,
                None,
                1,
                "impact_position_02",
                "impact",
            ),
        )
    )
    if [_take_signature(take) for take in takes] != expected:
        raise s4_8.S48Error(
            "S4.8 37-take design geometry, gain, repetition, or order mismatch"
        )

    contract = design["direction_repeatability_contract"]
    if not all(
        contract[key] is True
        for key in (
            "bearing_repetitions_must_be_consecutive",
            "same_session_required",
            "each_repetition_is_an_independent_take",
            "stop_playback_between_repetitions",
            "stop_recording_between_repetitions",
            "move_mac_slightly_between_repetitions",
            "reposition_to_exact_radius_and_bearing_before_each_repetition",
            "rig_must_remain_fixed",
        )
    ):
        raise s4_8.S48Error("S4.8 37-take direction repeatability contract mismatch")


def _validate_denominators(
    repo_root: Path,
    denominators: Mapping[str, Any],
    design: Mapping[str, Any],
) -> None:
    source_relative = _safe_relative(denominators["source_criteria_register_path"])
    if (
        source_relative != FROZEN_CRITERIA_REGISTER_PATH
        or denominators["source_criteria_register_sha256"]
        != FROZEN_CRITERIA_REGISTER_SHA256
    ):
        raise s4_8.S48Error("S4.8 frozen criteria register identity mismatch")
    source_path = repo_root / source_relative
    if (
        not source_path.is_file()
        or s4_8.sha256_file(source_path)
        != denominators["source_criteria_register_sha256"]
    ):
        raise s4_8.S48Error("S4.8 frozen criteria register binding mismatch")
    source = s4_8.load_json(source_path)
    details = source.get("details", {})
    if (
        source.get("planned_take_count") != 47
        or details.get("criterion_count") != 29
        or details.get("readiness_criterion_count") != 23
        or details.get("stretch_criterion_count") != 6
        or details.get("register_schema") != "ias.s4_7.effective_criteria_register.v4"
        or details.get("resolution") != "corrective_03_exact_machine_readable_semantics"
        or details.get("scientific_semantics_sha256")
        != FROZEN_SCIENTIFIC_SEMANTICS_SHA256
    ):
        raise s4_8.S48Error("S4.8 frozen criteria semantics mismatch")
    criteria = details["criteria"]
    source_counts = {
        criterion["criterion_id"]: criterion["denominator"]["expected_count"]
        for criterion in criteria
    }
    overrides = denominators["criterion_expected_count_overrides"]
    unchanged = denominators["unchanged_non_null_expected_counts"]
    null_ids = set(denominators["null_window_or_metric_denominators_remain_null"])
    metric_roles = denominators["metric_role_amendment"]
    if overrides != EXPECTED_DENOMINATOR_OVERRIDES:
        raise s4_8.S48Error("S4.8 37-take denominator override mismatch")
    if unchanged != EXPECTED_UNCHANGED_DENOMINATORS:
        raise s4_8.S48Error("S4.8 unchanged denominator mismatch")
    if null_ids != EXPECTED_NULL_DENOMINATORS:
        raise s4_8.S48Error("S4.8 null denominator mismatch")
    if (
        set(metric_roles["continuous_bearing_diagnostic_criteria"])
        != CONTINUOUS_BEARING_DIAGNOSTIC_CRITERIA
        or set(metric_roles["superseded_sector_criteria"]) != SUPERSEDED_SECTOR_CRITERIA
        or metric_roles["primary_metric"] != "squadbot_categorical_direction_accuracy"
        or metric_roles["primary_metric_threshold"]
        != SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD
        or metric_roles["continuous_bearing_error_role"] != "diagnostic_non_gating"
        or metric_roles["categorical_direction_role"] != "primary_gating"
    ):
        raise s4_8.S48Error("S4.8 consumer metric-role amendment mismatch")
    if set(source_counts) != set(overrides) | set(unchanged) | null_ids:
        raise s4_8.S48Error("S4.8 denominator criterion coverage mismatch")
    if any(source_counts[criterion_id] is not None for criterion_id in null_ids):
        raise s4_8.S48Error("S4.8 null denominator source mismatch")
    if any(
        source_counts[criterion_id] != count
        for criterion_id, count in unchanged.items()
    ):
        raise s4_8.S48Error("S4.8 inherited denominator source mismatch")
    if (
        denominators["planned_take_denominator"] != design["planned_take_count"]
        or denominators["stratum_take_denominators"]
        != {
            **design["stratum_counts"],
            "A_plus_B": (
                design["stratum_counts"]["A_controlled_boundary_sweep"]
                + design["stratum_counts"]["B_center_nominal_level"]
            ),
        }
        or denominators["derived_denominators"]
        != {
            "raw_channel_take_records": PLANNED_TAKE_COUNT * 4,
            "direction_bearing_cells": len(DIRECTION_BEARINGS),
            "direction_bearing_cell_pair_groups": len(DIRECTION_BEARINGS) * 6,
            "product_low_gain_pairs": len(PRODUCT_BEARINGS),
        }
        or denominators["direction_metric_denominators"]
        != {
            "primary_applicable_takes": 28,
            "front_expected_takes": 7,
            "right_expected_takes": 10,
            "left_expected_takes": 7,
            "rear_unavailable_expected_takes": 4,
            "low_volume_diagnostic_takes": 4,
            "silence_unavailable_takes": 3,
            "impact_direction_not_applicable_takes": 2,
        }
    ):
        raise s4_8.S48Error("S4.8 37-take denominator formula mismatch")
    if (
        denominators["thresholds_unchanged"] is not True
        or denominators["comparators_unchanged"] is not True
        or denominators["tiers_unchanged"] is not False
        or denominators["applicability_unchanged"] is not False
    ):
        raise s4_8.S48Error("S4.8 scientific threshold contract mismatch")


def validate_protocol_revision(repo_root: Path) -> dict[str, Any]:
    """Authenticate the frozen v2 design and denominator adaptation."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    revision = amendment["protocol_revision"]
    design = s4_8.load_json(root / _safe_relative(revision["design_manifest_path"]))
    denominators = s4_8.load_json(root / _safe_relative(revision["denominators_path"]))
    return {
        "schema": "ias.s4_8.recovery_amendment_02_protocol_validation.v2",
        "status": "passed",
        "readiness": "frozen_for_precollection",
        "planned_take_count": design["planned_take_count"],
        "leakage_group_count": design["leakage_group_count"],
        "stratum_counts": design["stratum_counts"],
        "direction_bearing_count": len(DIRECTION_BEARINGS),
        "direction_repetitions_per_bearing": 3,
        "direction_repetitions_consecutive": True,
        "direction_repetitions_same_session": True,
        "independent_direction_takes": True,
        "direction_policy_id": SQUADBOT_DIRECTION_POLICY_ID,
        "primary_direction_metric": "squadbot_categorical_direction_accuracy",
        "primary_direction_threshold": SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD,
        "categorical_take_aggregation_bound": True,
        "continuous_bearing_error_gating": False,
        "rig_fixed": True,
        "thresholds_unchanged": denominators["thresholds_unchanged"],
        "criterion_count": (
            revision["readiness_criterion_count"] + revision["stretch_criterion_count"]
        ),
        "final_protocol_frozen": True,
        "official_acquisition_permitted": False,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "holdout_opening_authorized": False,
        "evaluation_authorized": False,
    }


def _validate_namespaces(
    amendment: Mapping[str, Any],
    historical: Mapping[str, Any],
) -> None:
    historical_paths = {
        _safe_relative(record["path"])
        for run in historical["prior_terminal_runs"]
        for record in run["artifacts"].values()
    }
    historical_namespace_roots = {
        _safe_relative(record["path"]).parent
        for run in historical["prior_terminal_runs"]
        for record in run["artifacts"].values()
    }
    unseen = amendment["unseen_holdout"]
    future = amendment["future_attempt"]
    namespace = _safe_relative(unseen["namespace_root"])
    observation_root = _safe_relative(unseen["observation_root"])
    if any(
        not _is_within(_safe_relative(unseen[key]), namespace)
        for key in (
            "precollection_seal_path",
            "partition_manifest_path",
            "session_manifest_path",
            "preflight_report_path",
            "source_archive_path",
            "attempt_ledger_path",
            "holdout_seal_path",
        )
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 holdout paths escape the new namespace"
        )
    consumed_roots = {
        _safe_relative(path) for path in unseen["consumed_observation_roots"]
    }
    if any(_paths_overlap(observation_root, root) for root in consumed_roots):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 observation root reuses consumed data"
        )
    future_paths = {
        _safe_relative(future[key])
        for key in (
            "grant_path",
            "ledger_path",
            "journal_path",
            "derived_input_path",
            "output_path",
            "closeout_path",
            "independent_review_path",
        )
    }
    if (
        len(future_paths) != 7
        or any(
            _paths_overlap(future_path, historical_path)
            for future_path in future_paths
            for historical_path in historical_paths
        )
        or any(
            _paths_overlap(future_path, historical_root)
            for future_path in future_paths
            for historical_root in historical_namespace_roots
        )
        or any(
            _paths_overlap(observation_root, historical_path)
            for historical_path in historical_paths
        )
        or any(
            _paths_overlap(observation_root, historical_root)
            for historical_root in historical_namespace_roots
        )
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 future paths overlap terminal history"
        )


def _validate_preliminary_bindings(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    preliminary = amendment["preliminary_readiness"]
    for path_key, digest_key in (
        ("workflow_config_path", "workflow_config_sha256"),
        ("workflow_schema_path", "workflow_schema_sha256"),
        ("workflow_spec_path", "workflow_spec_sha256"),
    ):
        path = repo_root / _safe_relative(preliminary[path_key])
        if not path.is_file() or s4_8.sha256_file(path) != preliminary[digest_key]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 binding mismatch: {path_key}"
            )


def _preliminary_readiness_state(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> tuple[bool, bool]:
    preliminary = amendment["preliminary_readiness"]
    path = repo_root / _safe_relative(preliminary["readiness_path"])
    if not path.exists():
        return False, False
    if s4_8.sha256_file(path) != preliminary["readiness_file_sha256"]:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 preliminary readiness binding mismatch"
        )
    report = s4_8.load_json(path)
    campaign_path = repo_root / _safe_relative(
        preliminary["source_campaign_manifest_path"]
    )
    if (
        not campaign_path.is_file()
        or s4_8.sha256_file(campaign_path)
        != preliminary["source_campaign_manifest_file_sha256"]
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 preliminary campaign binding mismatch"
        )
    campaign = s4_8.load_json(campaign_path)
    campaign_signatures = [
        (
            take["preliminary_case_id"],
            take["stratum_id"],
            take["target_bearing_deg_f_project"],
            take["target_radius_m"],
            take["playback_gain"],
            take["zed_required"],
        )
        for take in campaign.get("design", [])
    ]
    expected_campaign_signatures = [
        (
            "nominal_reference",
            "B_center_nominal_level",
            45.0,
            0.8,
            0.75,
            False,
        ),
        (
            "low_level_reference",
            "C_center_low_level",
            45.0,
            0.8,
            0.35,
            False,
        ),
        ("silence", "D_silence", None, None, None, False),
        (
            "audio_video_impact_with_zed",
            "E_impact_audio_video",
            None,
            None,
            None,
            True,
        ),
    ]
    passed = (
        report.get("schema") == "ias.s4_8.preliminary_readiness.v1"
        and report.get("status") == preliminary["required_status"]
        and report.get("preliminary_take_count") == preliminary["required_take_count"]
        and report.get("all_required_gates_passed") is True
        and report.get("final_protocol_freeze_permitted") is True
        and report.get("final_protocol_frozen") is False
        and report.get("official_holdout_take_count")
        == preliminary["readiness_source_protocol_take_count"]
        and report.get("preliminary_manifest_sha256")
        == preliminary["source_campaign_manifest_payload_sha256"]
        and campaign.get("manifest_sha256")
        == preliminary["source_campaign_manifest_payload_sha256"]
        and campaign_signatures == expected_campaign_signatures
        and preliminary["physical_cases_unchanged_by_revision"] is True
        and preliminary["reuse_for_37_take_revision_permitted"] is True
        and report.get("official_acquisition_permitted") is False
        and report.get("grant_creation_authorized") is False
        and report.get("grant_consumption_authorized") is False
        and report.get("holdout_opening_authorized") is False
        and report.get("official_evaluation_authorized") is False
    )
    if not passed:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 preliminary readiness is invalid"
        )
    return True, True


def _validate_terminal_package(
    repo_root: Path,
    *,
    run: Mapping[str, Any],
) -> None:
    artifacts = run["artifacts"]
    package = (
        repo_root / _safe_relative(artifacts["terminal_manifest"]["path"])
    ).parent
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != s4_8.PACKAGE_FILES:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 package drift: {run['run_id']}"
        )
    s4_8._validate_manifest(package)
    final = s4_8.load_json(
        repo_root / _safe_relative(artifacts["final_validation"]["path"])
    )
    if (
        final.get("status") != "failed"
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
        or final.get("scientific_evaluation_state") != run["evaluation_state"]
        or final.get("scientific_evaluation_status") != run["scientific_status"]
    ):
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 terminal status drift: {run['run_id']}"
        )
    provenance = s4_8.load_json(package / "provenance.json")
    if provenance.get("source_commit") != run["source_commit"]:
        raise s4_8.S48Error(f"S4.8 recovery amendment_02 source drift: {run['run_id']}")
    if run["failure_gate"] is not None:
        criteria = s4_8.load_json(package / "criteria_results.json")
        if criteria.get("failed_gating_criteria") != [run["failure_gate"]]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 failure drift: {run['run_id']}"
            )


def validate_terminal_history(
    repo_root: Path,
    amendment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Authenticate both terminal runs without loading scientific payloads."""

    root = repo_root.resolve()
    loaded = dict(amendment or load_amendment(root))
    historical = _load_historical_amendment(root, loaded)
    terminal_runs = historical["prior_terminal_runs"]
    artifact_count = 0
    manifest_hashes: dict[str, str] = {}
    for run in terminal_runs:
        run_id = run["run_id"]
        artifacts = run["artifacts"]
        if frozenset(artifacts) != EXPECTED_ARTIFACT_KEYS[run_id]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 artifact set drift: {run_id}"
            )
        grant = s4_8.load_json(root / _safe_relative(artifacts["grant"]["path"]))
        if grant.get("grant_id") != run["grant_id"]:
            raise s4_8.S48Error(f"S4.8 recovery amendment_02 grant drift: {run_id}")
        for name, record in artifacts.items():
            path = root / _safe_relative(record["path"])
            if not path.is_file() or s4_8.sha256_file(path) != record["sha256"]:
                raise s4_8.S48Error(
                    "S4.8 recovery amendment_02 terminal artifact mismatch: "
                    f"{run_id}.{name}"
                )
            artifact_count += 1
        manifest_hashes[run_id] = artifacts["terminal_manifest"]["sha256"]
        _validate_terminal_package(root, run=run)
    return {
        "schema": "ias.s4_8.recovery_amendment_02_terminal_history.v1",
        "status": "passed",
        "terminal_run_count": 2,
        "terminal_statuses": {
            run["run_id"]: run["terminal_status"] for run in terminal_runs
        },
        "artifact_count": artifact_count,
        "package_manifest_sha256": manifest_hashes,
        "raw_holdout_read": False,
        "scientific_payload_loaded": False,
    }


def _future_state_paths(amendment: Mapping[str, Any]) -> dict[str, Path]:
    future = amendment["future_attempt"]
    grant = _safe_relative(future["grant_path"])
    return {
        "grant": grant,
        "authorization": grant.with_name(s4_8.AUTHORIZATION_RECORD_NAME),
        "ledger": _safe_relative(future["ledger_path"]),
        "journal": _safe_relative(future["journal_path"]),
        "derived_input": _safe_relative(future["derived_input_path"]),
        "output": _safe_relative(future["output_path"]),
    }


def _require_no_unauthorized_state(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    for name, relative in _future_state_paths(amendment).items():
        if (repo_root / relative).exists():
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 unauthorized future state exists: {name}"
            )


def _authenticate_independent_review(
    repo_root: Path,
    *,
    amendment: Mapping[str, Any],
    source_commit: str,
    allow_source_mismatch: bool = False,
) -> dict[str, Any] | None:
    path = repo_root / _safe_relative(
        amendment["future_attempt"]["independent_review_path"]
    )
    if not path.exists():
        return None
    if not path.is_file():
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 independent review is not a file"
        )
    try:
        review = s4_8.load_json(path)
    except (OSError, ValueError, s4_8.S48Error) as exc:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 independent review is malformed"
        ) from exc
    if (
        set(review) != REVIEW_FIELDS
        or review.get("schema") != "ias.s4_8.independent_recovery_review.v1"
        or review.get("amendment_id") != amendment["amendment_id"]
        or review.get("decision") != "approved"
        or review.get("independent") is not True
        or not isinstance(review.get("reviewer_id"), str)
        or not review["reviewer_id"].strip()
        or not isinstance(review.get("reviewed_at_utc"), str)
        or not review["reviewed_at_utc"].strip()
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 requires an independent review "
            "bound to this source"
        )
    if review.get("source_commit") != source_commit:
        if allow_source_mismatch:
            return None
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 requires an independent review "
            "bound to this source"
        )
    return review


def _require_fix_ancestor(
    repo_root: Path,
    *,
    amendment: Mapping[str, Any],
    source_commit: str,
) -> None:
    historical = _load_historical_amendment(repo_root, amendment)
    fixed = historical["scientific_preregistration"]["producer_fix_commit"]
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", fixed, source_commit],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 source does not contain producer fix"
        )


def _source_binds_protocol_revision(
    repo_root: Path,
    *,
    amendment: Mapping[str, Any],
    source_commit: str,
) -> bool:
    revision = amendment["protocol_revision"]
    relative_paths = {
        AMENDMENT_PATH,
        AMENDMENT_SCHEMA_PATH,
        AMENDMENT_SPEC_PATH,
        Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02.py"),
        Path("src/isaac_audio_sensors/acquisition/s4_8_official_acquisition.py"),
        Path("src/isaac_audio_sensors/acquisition/s4_8_engineering_acquisition.py"),
        Path("src/isaac_audio_sensors/acquisition/s4_8_engineering_campaign.py"),
        Path("src/isaac_audio_sensors/acquisition/s4_8_physical_backend.py"),
        Path("scripts/run_s4_8_recovery_02.py"),
        Path("scripts/run_s4_8_physical_rehearsal.py"),
        _safe_relative(revision["design_manifest_path"]),
        _safe_relative(revision["design_schema_path"]),
        _safe_relative(revision["denominators_path"]),
        _safe_relative(revision["denominators_schema_path"]),
        _safe_relative(amendment["unseen_holdout"]["binding_schema_path"]),
    }
    for relative in relative_paths:
        worktree_path = repo_root / relative
        if not worktree_path.is_file():
            return False
        result = subprocess.run(
            ["git", "show", f"{source_commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            return False
        if (
            hashlib.sha256(result.stdout).digest()
            != hashlib.sha256(worktree_path.read_bytes()).digest()
        ):
            return False
    return True


def _source_contains_files(
    repo_root: Path,
    *,
    source_commit: str,
    paths: Mapping[Path, str],
) -> bool:
    for relative, expected_sha256 in paths.items():
        worktree_path = repo_root / relative
        if (
            not worktree_path.is_file()
            or s4_8.sha256_file(worktree_path) != expected_sha256
        ):
            return False
        result = subprocess.run(
            ["git", "show", f"{source_commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            result.returncode != 0
            or hashlib.sha256(result.stdout).hexdigest() != expected_sha256
        ):
            return False
    return True


def authenticate_evaluator_binding(
    repo_root: Path,
    *,
    source_commit: str,
) -> dict[str, Any] | None:
    """Authenticate the outcome-blind evaluator freeze without opening data."""

    root = repo_root.resolve()
    binding_path = root / EVALUATOR_BINDING_PATH
    if not binding_path.exists():
        return None
    schema_path = root / EVALUATOR_BINDING_SCHEMA_PATH
    if (
        not binding_path.is_file()
        or not schema_path.is_file()
        or s4_8.sha256_file(binding_path) != EVALUATOR_BINDING_SHA256
        or s4_8.sha256_file(schema_path) != EVALUATOR_BINDING_SCHEMA_SHA256
    ):
        raise s4_8.S48Error("S4.8 37-take evaluator binding hash mismatch")
    binding = s4_8.load_json(binding_path)
    schema = s4_8.load_json(schema_path)
    try:
        jsonschema.validate(binding, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 37-take evaluator binding schema failure: {exc.message}"
        ) from exc

    committed = _source_contains_files(
        root,
        source_commit=source_commit,
        paths={
            EVALUATOR_BINDING_PATH: EVALUATOR_BINDING_SHA256,
            EVALUATOR_BINDING_SCHEMA_PATH: EVALUATOR_BINDING_SCHEMA_SHA256,
        },
    )
    if not committed:
        return None

    evaluator = binding["evaluator"]
    evaluator_source_commit = evaluator["source_commit"]
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            evaluator_source_commit,
            source_commit,
        ],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise s4_8.S48Error("S4.8 37-take evaluator source is not an ancestor")
    source_records = evaluator["source_files"]
    source_paths: dict[Path, str] = {}
    for record in source_records:
        relative = _safe_relative(record["path"])
        if relative in source_paths:
            raise s4_8.S48Error("S4.8 37-take evaluator source path is duplicated")
        source_paths[relative] = record["sha256"]
    if not _source_contains_files(
        root,
        source_commit=evaluator_source_commit,
        paths=source_paths,
    ):
        raise s4_8.S48Error("S4.8 37-take evaluator source authentication failed")

    for record in binding["bindings"].values():
        relative = _safe_relative(record["path"])
        path = root / relative
        if not path.is_file() or s4_8.sha256_file(path) != record["sha256"]:
            raise s4_8.S48Error(
                f"S4.8 37-take evaluator protocol binding mismatch: {relative}"
            )

    from isaac_audio_sensors.acquisition.s4_8_recovery_02_evaluator import (
        RESULT_SCHEMA,
        TOOL_VERSION,
        protocol_identity,
    )

    identity = protocol_identity(root)
    protocol = binding["protocol"]
    if (
        evaluator["tool_version"] != TOOL_VERSION
        or evaluator["result_schema"] != RESULT_SCHEMA
        or protocol["protocol_sha256"] != identity["protocol_sha256"]
        or protocol["planned_take_count"] != identity["planned_take_count"]
        or protocol["planned_take_ids_sha256"] != identity["planned_take_ids_sha256"]
        or protocol["stratum_counts"] != STRATUM_COUNTS
        or protocol["take_aggregation"] != SQUADBOT_TAKE_AGGREGATION_CONTRACT
        or set(protocol["continuous_bearing_diagnostic_criteria"])
        != CONTINUOUS_BEARING_DIAGNOSTIC_CRITERIA
        or set(protocol["superseded_sector_criteria"]) != SUPERSEDED_SECTOR_CRITERIA
    ):
        raise s4_8.S48Error("S4.8 37-take evaluator protocol identity mismatch")

    precollection_record = binding["bindings"]["precollection_seal"]
    precollection = s4_8.load_json(root / _safe_relative(precollection_record["path"]))
    holdout_record = binding["bindings"]["holdout_seal"]
    holdout = s4_8.load_json(root / _safe_relative(holdout_record["path"]))
    holdout_binding_record = binding["bindings"]["holdout_binding"]
    holdout_binding = s4_8.load_json(
        root / _safe_relative(holdout_binding_record["path"])
    )
    if (
        precollection.get("seal_sha256") != precollection_record["payload_sha256"]
        or precollection.get("evaluation_authorized") is not False
        or holdout.get("seal_payload_sha256") != holdout_record["payload_sha256"]
        or holdout.get("status") != "sealed_unopened"
        or holdout.get("technically_sealed") is not True
        or holdout.get("scientifically_opened") is not False
        or holdout.get("scientific_artifact_contents_parsed") is not False
        or holdout.get("scientific_outcomes_derived") is not False
        or holdout.get("scientific_outputs_returned") is not False
        or holdout_binding.get("status") != "sealed_unopened"
        or holdout_binding.get("scientifically_opened") is not False
        or holdout_binding.get("planned_take_count") != PLANNED_TAKE_COUNT
        or holdout_binding.get("holdout_id") != binding["holdout_id"]
    ):
        raise s4_8.S48Error("S4.8 37-take evaluator sealed-holdout identity mismatch")
    return {
        "status": "authenticated",
        "binding_id": binding["binding_id"],
        "binding_sha256": EVALUATOR_BINDING_SHA256,
        "schema_sha256": EVALUATOR_BINDING_SCHEMA_SHA256,
        "evaluator_source_commit": evaluator_source_commit,
        "tool_version": evaluator["tool_version"],
        "entrypoint": evaluator["entrypoint"],
        "result_schema": evaluator["result_schema"],
        "protocol_sha256": protocol["protocol_sha256"],
        "planned_take_count": protocol["planned_take_count"],
        "primary_metric": protocol["primary_metric"],
        "primary_threshold": protocol["primary_threshold"],
        "primary_denominator": protocol["primary_denominator"],
        "effective_gating_criterion_count": protocol[
            "effective_gating_criterion_count"
        ],
        "scientifically_opened": False,
        "scientific_outcomes_derived": False,
        "grant_created": False,
        "grant_consumed": False,
        "evaluation_run": False,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise s4_8.S48Error("official attempt ledger record is not an object")
        records.append(value)
    return records


def _validate_official_precollection_freeze(
    repo_root: Path,
    amendment: Mapping[str, Any],
    *,
    require_current_source: bool = True,
) -> dict[str, Any]:
    unseen = amendment["unseen_holdout"]
    design_path = repo_root / _safe_relative(
        amendment["protocol_revision"]["design_manifest_path"]
    )
    session_path = repo_root / _safe_relative(unseen["session_manifest_path"])
    partition_path = repo_root / _safe_relative(unseen["partition_manifest_path"])
    seal_path = repo_root / _safe_relative(unseen["precollection_seal_path"])
    preflight_path = repo_root / _safe_relative(unseen["preflight_report_path"])
    ledger_path = repo_root / _safe_relative(unseen["attempt_ledger_path"])
    required = (session_path, partition_path, seal_path, preflight_path)
    if any(not path.is_file() for path in required):
        return {
            "valid": False,
            "reason": "committed_precollection_freeze_not_present",
        }
    session = s4_8.load_json(session_path)
    validate_session_manifest(
        session,
        expected_manifest_sha256=str(session.get("manifest_sha256")),
    )
    partition = s4_8.load_json(partition_path)
    partition_payload = {
        key: value
        for key, value in partition.items()
        if key != "partition_manifest_sha256"
    }
    design = s4_8.load_json(design_path)
    expected_ids = [take["planned_take_id"] for take in design["take_order"]]
    if (
        partition.get("partition_manifest_sha256")
        != canonical_sha256(partition_payload)
        or partition.get("status") != "frozen_unseen_precollection"
        or partition.get("observation_root") != unseen["observation_root"]
        or partition.get("planned_take_ids") != expected_ids
        or partition.get("planned_take_count") != PLANNED_TAKE_COUNT
        or partition.get("roots_disjoint") is not True
        or partition.get("observations_present_at_freeze") is not False
        or partition.get("holdout_opened") is not False
    ):
        raise s4_8.S48Error("S4.8 official partition manifest is invalid")
    seal = s4_8.load_json(seal_path)
    seal_payload = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        seal.get("seal_sha256") != canonical_sha256(seal_payload)
        or seal.get("status") != "frozen_before_collection"
        or seal.get("amendment_sha256") != s4_8.sha256_file(repo_root / AMENDMENT_PATH)
        or seal.get("design_manifest_sha256") != s4_8.sha256_file(design_path)
        or seal.get("partition_manifest_sha256")
        != partition["partition_manifest_sha256"]
        or seal.get("session_manifest_sha256") != session["manifest_sha256"]
        or seal.get("preflight_report_sha256") != s4_8.sha256_file(preflight_path)
        or seal.get("official_acquisition_permitted") is not True
        or seal.get("postcollection_holdout_seal_present") is not False
        or seal.get("unseen_holdout_binding_present") is not False
        or seal.get("evaluation_authorized") is not False
    ):
        raise s4_8.S48Error("S4.8 official precollection seal is invalid")
    validate_source_checkpoint(
        seal["source_checkpoint"],
        repo_root,
        require_current_checkout=require_current_source,
    )
    preflight = s4_8.load_json(preflight_path)
    if (
        preflight.get("status") != "passed"
        or preflight.get("read_only_hardware_checks") is not True
        or any(
            preflight.get(field) is not False
            for field in (
                "recorder_started",
                "playback_started",
                "zed_recording_started",
            )
        )
    ):
        raise s4_8.S48Error("S4.8 official physical preflight is invalid")
    ledger = _load_jsonl(ledger_path)
    validate_official_attempt_ledger(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )
    try:
        next_take, next_attempt = next_official_attempt(
            ledger,
            session_manifest=session,
            expected_session_manifest_sha256=session["manifest_sha256"],
        )
    except S48OfficialAcquisitionError as exc:
        if str(exc) != "official collection is complete":
            raise
        next_take = None
        next_attempt = None
    authorization_root = (
        repo_root
        / _safe_relative(unseen["namespace_root"])
        / "acquisition"
        / "authorizations"
    )
    authorizations = (
        list(authorization_root.glob("*.json")) if authorization_root.is_dir() else []
    )
    return {
        "valid": True,
        "session_manifest_sha256": session["manifest_sha256"],
        "partition_manifest_sha256": partition["partition_manifest_sha256"],
        "precollection_seal_sha256": seal["seal_sha256"],
        "source_commit": seal["source_commit"],
        "attempt_count": len(ledger),
        "next_take_id": (None if next_take is None else next_take["planned_take_id"]),
        "next_attempt_number": next_attempt,
        "authorization_count": len(authorizations),
        "recorder_started_during_preflight": False,
        "playback_started_during_preflight": False,
        "zed_recording_started_during_preflight": False,
    }


def recovery_preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None = None,
    require_access_paths_absent: bool = True,
) -> dict[str, Any]:
    """Validate the preregistration while keeping execution at NO-GO."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    history = validate_terminal_history(root, amendment)
    resolved_commit = source_commit or s4_8._git(root, "rev-parse", "HEAD")
    _require_fix_ancestor(
        root,
        amendment=amendment,
        source_commit=resolved_commit,
    )
    source_binds_protocol = _source_binds_protocol_revision(
        root,
        amendment=amendment,
        source_commit=resolved_commit,
    )
    if require_access_paths_absent:
        _require_no_unauthorized_state(root, amendment)
    unseen = amendment["unseen_holdout"]
    future = amendment["future_attempt"]
    holdout_paths = {
        key: _safe_relative(unseen[key])
        for key in (
            "binding_path",
            "precollection_seal_path",
            "partition_manifest_path",
            "session_manifest_path",
            "holdout_seal_path",
            "observation_root",
        )
    }
    present = {key: (root / path).exists() for key, path in holdout_paths.items()}
    readiness_present, readiness_passed = _preliminary_readiness_state(root, amendment)
    final_protocol_frozen = (
        amendment["preliminary_readiness"]["final_protocol_status"] == "frozen"
    )
    if any(present.values()) and not (readiness_passed and final_protocol_frozen):
        raise s4_8.S48Error(
            "S4.8 official holdout state exists before preliminary readiness "
            "and final protocol freeze"
        )
    review_path = root / _safe_relative(future["independent_review_path"])
    review_present = review_path.exists()
    independent_review = _authenticate_independent_review(
        root,
        amendment=amendment,
        source_commit=resolved_commit,
        allow_source_mismatch=True,
    )
    seal_present = present["holdout_seal_path"]
    binding_present = present["binding_path"]
    if seal_present != binding_present:
        raise s4_8.S48Error(
            "S4.8 postcollection holdout seal and binding are incomplete"
        )
    finalization: dict[str, Any] | None = None
    if seal_present:
        from isaac_audio_sensors.acquisition.s4_8_postcollection_finalizer import (
            S48PostcollectionFinalizerError,
            authenticate_existing_finalization,
        )

        try:
            finalization = authenticate_existing_finalization(root)
        except S48PostcollectionFinalizerError as exc:
            raise s4_8.S48Error(
                f"S4.8 postcollection finalization authentication failed: {exc}"
            ) from exc
    evaluator_binding = authenticate_evaluator_binding(
        root,
        source_commit=resolved_commit,
    )
    blockers = ["explicit_authorization_not_granted"]
    if independent_review is None:
        blockers.insert(0, "independent_review_not_present")
    if evaluator_binding is None:
        blockers.insert(0, "evaluator_not_bound_to_37_take_protocol")
    if finalization is None:
        blockers.insert(0, "new_unseen_holdout_not_collected_or_bound")
    if not source_binds_protocol:
        blockers.insert(0, "source_commit_does_not_bind_37_take_protocol")
    if not readiness_passed:
        blockers.insert(0, "preliminary_readiness_not_established")
    protocol_validation = validate_protocol_revision(root)
    official_freeze = _validate_official_precollection_freeze(
        root,
        amendment,
        require_current_source=False,
    )
    official_acquisition_permitted = (
        source_binds_protocol
        and readiness_passed
        and final_protocol_frozen
        and official_freeze["valid"]
    )
    return {
        "schema": "ias.s4_8.recovery_amendment_02_preopen.v2",
        "status": "passed",
        "protocol_revision_readiness": protocol_validation["readiness"],
        "official_readiness": "no_go",
        "amendment_id": amendment["amendment_id"],
        "revision_id": amendment["revision_id"],
        "source_commit": resolved_commit,
        "candidate_grant_id": (
            future["grant_id_template"].format(source_commit=resolved_commit)
            if source_binds_protocol
            else None
        ),
        "blockers": blockers,
        "terminal_history": history,
        "criteria_set_unchanged": False,
        "criteria_roles_amended_for_squadbot": True,
        "primary_direction_metric": "squadbot_categorical_direction_accuracy",
        "categorical_take_aggregation_bound": True,
        "continuous_bearing_error_gating": False,
        "thresholds_unchanged": True,
        "denominators_updated_for_design": True,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "planned_take_count": PLANNED_TAKE_COUNT,
        "preliminary_take_count": 4,
        "preliminary_readiness_present": readiness_present,
        "preliminary_readiness_passed": readiness_passed,
        "final_protocol_frozen": final_protocol_frozen,
        "source_commit_binds_protocol_revision": source_binds_protocol,
        "official_acquisition_permitted": official_acquisition_permitted,
        "official_acquisition_blockers": (
            []
            if official_acquisition_permitted
            else [
                reason
                for condition, reason in (
                    (
                        not source_binds_protocol,
                        "source_commit_does_not_bind_37_take_protocol",
                    ),
                    (
                        not readiness_passed,
                        "preliminary_readiness_not_established",
                    ),
                    (
                        not final_protocol_frozen,
                        "final_official_protocol_not_frozen",
                    ),
                    (
                        not official_freeze["valid"],
                        str(
                            official_freeze.get(
                                "reason",
                                "committed_precollection_freeze_not_present",
                            )
                        ),
                    ),
                )
                if condition
            ]
        ),
        "official_precollection_freeze": official_freeze,
        "leakage_group_count": LEAKAGE_GROUP_COUNT,
        "unseen_holdout_id": unseen["holdout_id"],
        "unseen_holdout_paths_present": present,
        "holdout_collection_complete": finalization is not None,
        "holdout_seal_authenticated": finalization is not None,
        "holdout_binding_authenticated": finalization is not None,
        "postcollection_finalization": finalization,
        "evaluator_binding_authenticated": evaluator_binding is not None,
        "evaluator_binding": evaluator_binding,
        "independent_review_present": review_present,
        "independent_review_authenticated": independent_review is not None,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "evaluation_execution_authorized": False,
        "new_grant_present": (root / _safe_relative(future["grant_path"])).is_file(),
        "new_ledger_present": (root / _safe_relative(future["ledger_path"])).is_file(),
        "holdout_observation_opened": False,
        "content_derived_values_returned": False,
    }


def create_recovery_grant(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    """Create the exact externally authorized amendment-02 grant."""

    from isaac_audio_sensors.acquisition.s4_8_recovery_02_execution import (
        create_recovery_grant as create,
    )

    return create(
        repo_root,
        source_commit=source_commit,
        authorization_id=authorization_id,
    )


def run_recovery_evaluation_once(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Consume, open, and evaluate the amendment-02 holdout exactly once."""

    from isaac_audio_sensors.acquisition.s4_8_recovery_02_execution import (
        run_recovery_evaluation_once as run,
    )

    return run(
        repo_root,
        source_commit=source_commit,
        authorization_id=authorization_id,
        event_time_utc=event_time_utc,
    )


def validate_recovery_evidence_package(
    repo_root: Path,
    *,
    package: Path | None = None,
) -> dict[str, Any]:
    """Validate terminal bytes without rerunning the scientific evaluator."""

    from isaac_audio_sensors.acquisition.s4_8_recovery_02_execution import (
        validate_recovery_evidence_package as validate,
    )

    return validate(repo_root, package=package)


__all__ = [
    "AMENDMENT_PATH",
    "authenticate_evaluator_binding",
    "create_recovery_grant",
    "load_amendment",
    "recovery_preopen_validate",
    "run_recovery_evaluation_once",
    "validate_recovery_evidence_package",
    "validate_protocol_revision",
    "validate_terminal_history",
]
