"""Preregistration gate for a new unseen S4.8 recovery holdout."""

from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from collections.abc import Mapping
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8

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
    """Map a diagnostic bearing to the exact SquadBot ASN v2 direction value."""

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
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 historical path mismatch"
        )
    path = repo_root / HISTORICAL_AMENDMENT_PATH
    if (
        not path.is_file()
        or s4_8.sha256_file(path) != supersedes["sha256"]
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 historical binding mismatch"
        )
    historical = s4_8.load_json(path)
    schema = s4_8.load_json(repo_root / HISTORICAL_AMENDMENT_SCHEMA_PATH)
    try:
        jsonschema.validate(historical, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 historical schema failure: "
            f"{exc.message}"
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
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 binding mismatch: {path_key}"
        )
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
    expected.append(
        ("D_silence", None, None, None, 2, "ambient_silence", "silence")
    )
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
        raise s4_8.S48Error(
            "S4.8 37-take direction repeatability contract mismatch"
        )


def _validate_denominators(
    repo_root: Path,
    denominators: Mapping[str, Any],
    design: Mapping[str, Any],
) -> None:
    source_relative = _safe_relative(
        denominators["source_criteria_register_path"]
    )
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
        or details.get("register_schema")
        != "ias.s4_7.effective_criteria_register.v4"
        or details.get("resolution")
        != "corrective_03_exact_machine_readable_semantics"
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
        or set(metric_roles["superseded_sector_criteria"])
        != SUPERSEDED_SECTOR_CRITERIA
        or metric_roles["primary_metric"]
        != "squadbot_categorical_direction_accuracy"
        or metric_roles["primary_metric_threshold"]
        != SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD
        or metric_roles["continuous_bearing_error_role"]
        != "diagnostic_non_gating"
        or metric_roles["categorical_direction_role"] != "primary_gating"
    ):
        raise s4_8.S48Error("S4.8 SquadBot metric-role amendment mismatch")
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
    """Authenticate the v2 design and denominator adaptation without freezing."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    revision = amendment["protocol_revision"]
    design = s4_8.load_json(
        root / _safe_relative(revision["design_manifest_path"])
    )
    denominators = s4_8.load_json(
        root / _safe_relative(revision["denominators_path"])
    )
    return {
        "schema": "ias.s4_8.recovery_amendment_02_protocol_validation.v2",
        "status": "passed",
        "readiness": "go_for_final_freeze",
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
            revision["readiness_criterion_count"]
            + revision["stretch_criterion_count"]
        ),
        "final_protocol_frozen": False,
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
        if (
            not path.is_file()
            or s4_8.sha256_file(path) != preliminary[digest_key]
        ):
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
        and report.get("preliminary_take_count")
        == preliminary["required_take_count"]
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
            run["run_id"]: run["terminal_status"]
            for run in terminal_runs
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
        Path("scripts/run_s4_8_recovery_02.py"),
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
        if hashlib.sha256(result.stdout).digest() != hashlib.sha256(
            worktree_path.read_bytes()
        ).digest():
            return False
    return True


def recovery_preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None = None,
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
    readiness_present, readiness_passed = _preliminary_readiness_state(
        root, amendment
    )
    final_protocol_frozen = (
        amendment["preliminary_readiness"]["final_protocol_status"] == "frozen"
    )
    if any(present.values()) and not (readiness_passed and final_protocol_frozen):
        raise s4_8.S48Error(
            "S4.8 official holdout state exists before preliminary readiness "
            "and final protocol freeze"
        )
    review_present = (
        root / _safe_relative(future["independent_review_path"])
    ).is_file()
    blockers = [
        "final_official_protocol_not_frozen",
        "new_unseen_holdout_not_collected_or_bound",
        "evaluator_not_bound_to_37_take_protocol",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    if not source_binds_protocol:
        blockers.insert(0, "source_commit_does_not_bind_37_take_protocol")
    if not readiness_passed:
        blockers.insert(0, "preliminary_readiness_not_established")
    protocol_validation = validate_protocol_revision(root)
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
        "official_acquisition_permitted": False,
        "leakage_group_count": LEAKAGE_GROUP_COUNT,
        "unseen_holdout_id": unseen["holdout_id"],
        "unseen_holdout_paths_present": present,
        "independent_review_present": review_present,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "evaluation_execution_authorized": False,
        "new_grant_present": False,
        "new_ledger_present": False,
        "holdout_observation_opened": False,
        "content_derived_values_returned": False,
    }


__all__ = [
    "AMENDMENT_PATH",
    "load_amendment",
    "recovery_preopen_validate",
    "validate_protocol_revision",
    "validate_terminal_history",
]
