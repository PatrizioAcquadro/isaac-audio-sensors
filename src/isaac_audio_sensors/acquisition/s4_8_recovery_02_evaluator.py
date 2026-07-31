"""Outcome-blind evaluator adapter for the frozen S4.8 37-take protocol.

The historical corrective evaluators remain byte-identical. This module reuses
their validators, exact-window derivation, threshold evaluation, and result
types while supplying only the amended identities, denominators, and metric
roles. It has no dataset, grant, ledger, or holdout-opening code path.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as c2
from isaac_audio_sensors.core import acceptance_criteria_corrective_03 as c3

PAYLOAD_SCHEMA = "ias.s4_8.recovery_02.corrective_metrics.v1"
RESULT_SCHEMA = "ias.s4_8.recovery_02.criteria_evaluation_result.v2"
TOOL_VERSION = "ias_s4_8_recovery_02_evaluator/1.0.1"

DESIGN_PATH = Path("configs/s4_8_recovery_amendment_02_preholdout_manifest.v2.json")
DENOMINATORS_PATH = Path("configs/s4_8_recovery_amendment_02_denominators.v2.json")
SESSION_MANIFEST_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_04/manifests/sessions/"
    "prospective_holdout_recovery_02.v2.json"
)
PARTITION_MANIFEST_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_04/manifests/"
    "prospective_holdout_recovery_02_manifest.v2.json"
)
CRITERIA_REGISTER_PATH = recovery.FROZEN_CRITERIA_REGISTER_PATH

_PAYLOAD_FIELDS = frozenset({"schema", "contract", "takes", "sim_vs_real"})
_CONTRACT_FIELDS = frozenset(
    {
        "protocol_sha256",
        "holdout_id",
        "planned_take_ids_sha256",
        "planned_take_count",
    }
)
_TAKE_FIELDS = frozenset((*c2._TAKE_FIELDS, "bearing_windows"))
_COMPARISON_EXPECTED_COUNTS = {
    "bearing_doa_error_ab": 28,
    "sector_accuracy_b": 4,
    "candidate_bearing_ab": 28,
    "tdoa_a": 144,
    "abstention_abd": 31,
    "confidence_bc": 8,
    "coarse_audio_video_association_e": 2,
}
_GATING_COMPARISON_IDS = frozenset(
    {
        "candidate_bearing_ab",
        "tdoa_a",
        "abstention_abd",
        "confidence_bc",
        "coarse_audio_video_association_e",
    }
)


@dataclass(frozen=True, slots=True)
class Recovery02EvaluationResult:
    """Complete amended criteria result without holdout access."""

    outcomes: tuple[c2.CriterionOutcome, ...]
    comparisons: tuple[dict[str, Any], ...]
    categorical_take_results: tuple[dict[str, Any], ...]
    identity_summary: dict[str, Any]
    config_identity: dict[str, Any]
    evaluation_error: str | None = None

    @property
    def readiness_passed(self) -> bool:
        return self.evaluation_error is None and all(
            item.passed for item in self.outcomes if item.gating
        )

    def report(self) -> dict[str, Any]:
        failed_gating_criteria = (
            ["evaluation_input_contract_rejected"]
            if self.evaluation_error is not None
            else [
                item.criterion_id
                for item in self.outcomes
                if item.gating and not item.passed
            ]
        )
        return {
            "schema": RESULT_SCHEMA,
            "status": "passed" if self.readiness_passed else "failed",
            "readiness_passed": self.readiness_passed,
            "failed_gating_criteria": failed_gating_criteria,
            "criteria": [item.report() for item in self.outcomes],
            "comparison_classifications": list(self.comparisons),
            "categorical_take_results": list(self.categorical_take_results),
            "identity_summary": self.identity_summary,
            "config_identity": self.config_identity,
            "evaluation_error": self.evaluation_error,
            "holdout_observations_accessed_by_evaluator": 0,
        }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _protocol_material(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    recovery.validate_protocol_revision(root)
    design = _load_json(root / DESIGN_PATH)
    denominators = _load_json(root / DENOMINATORS_PATH)
    session = _load_json(root / SESSION_MANIFEST_PATH)
    partition = _load_json(root / PARTITION_MANIFEST_PATH)
    register = _load_json(root / CRITERIA_REGISTER_PATH)
    return {
        "amendment": amendment,
        "design": design,
        "denominators": denominators,
        "session": session,
        "partition": partition,
        "criteria_register": register,
    }


def build_identity_registry(
    repo_root: Path,
) -> dict[str, c2.TakeIdentity]:
    """Build the exact 37 identities from authenticated frozen manifests."""

    material = _protocol_material(repo_root)
    design_takes = material["design"]["take_order"]
    session_takes = material["session"]["design"]
    partition_ids = material["partition"]["planned_take_ids"]
    if (
        len(design_takes) != recovery.PLANNED_TAKE_COUNT
        or len(session_takes) != recovery.PLANNED_TAKE_COUNT
        or partition_ids != [take["planned_take_id"] for take in design_takes]
        or partition_ids != [take["planned_take_id"] for take in session_takes]
    ):
        raise c2.CorrectiveAcceptanceError(
            "S4.8 37-take evaluator identity order mismatch"
        )
    session_by_id = {take["planned_take_id"]: take for take in session_takes}
    if len(session_by_id) != recovery.PLANNED_TAKE_COUNT:
        raise c2.CorrectiveAcceptanceError(
            "S4.8 37-take evaluator identity set mismatch"
        )

    pair_lookup: dict[tuple[str, float], str] = {}
    for take in design_takes:
        if take["stratum_id"] in {
            "B_center_nominal_level",
            "C_center_low_level",
        }:
            key = (take["stratum_id"], float(take["bearing_deg"]))
            if key in pair_lookup:
                raise c2.CorrectiveAcceptanceError(
                    "S4.8 37-take B/C pair identity is duplicated"
                )
            pair_lookup[key] = take["planned_take_id"]

    registry: dict[str, c2.TakeIdentity] = {}
    for take in design_takes:
        take_id = take["planned_take_id"]
        session_take = session_by_id[take_id]
        expected_session = {
            "sequence_index": take["sequence_index"],
            "stratum_id": take["stratum_id"],
            "group_id": take["leakage_group_id"],
            "target_bearing_deg_f_project": take["bearing_deg"],
            "playback_gain": take["playback_gain"],
        }
        if any(
            session_take.get(key) != value for key, value in expected_session.items()
        ):
            raise c2.CorrectiveAcceptanceError(
                f"S4.8 37-take session identity mismatch: {take_id}"
            )
        stratum = take["stratum_id"]
        bearing = take["bearing_deg"]
        counterpart = None
        if stratum in {"B_center_nominal_level", "C_center_low_level"}:
            other = (
                "C_center_low_level"
                if stratum == "B_center_nominal_level"
                else "B_center_nominal_level"
            )
            counterpart = pair_lookup.get((other, float(bearing)))
            if counterpart is None:
                raise c2.CorrectiveAcceptanceError(
                    f"S4.8 37-take B/C counterpart missing: {take_id}"
                )
        registry[take_id] = c2.TakeIdentity(
            planned_take_id=take_id,
            stratum_id=stratum,
            group_id=take["leakage_group_id"],
            bearing_cell_id=(
                None if bearing is None else f"{stratum}|{float(bearing):.1f}"
            ),
            repetition=take["repetition"],
            condition_id=take["condition_id"],
            paired_counterpart_take_id=counterpart,
            target_bearing_deg_f_project=(None if bearing is None else float(bearing)),
            duration_s=session_take["duration_s"],
        )
    counts = Counter(identity.stratum_id for identity in registry.values())
    if (
        dict(counts) != recovery.STRATUM_COUNTS
        or len({identity.group_id for identity in registry.values()})
        != recovery.LEAKAGE_GROUP_COUNT
    ):
        raise c2.CorrectiveAcceptanceError(
            "S4.8 37-take evaluator registry count mismatch"
        )
    return registry


def protocol_identity(repo_root: Path) -> dict[str, Any]:
    """Return the binding-independent frozen protocol identity."""

    root = repo_root.resolve()
    material = _protocol_material(root)
    registry = build_identity_registry(root)
    payload = {
        "amendment_id": material["amendment"]["amendment_id"],
        "revision_id": material["amendment"]["revision_id"],
        "holdout_id": material["amendment"]["unseen_holdout"]["holdout_id"],
        "planned_take_count": recovery.PLANNED_TAKE_COUNT,
        "planned_take_ids_sha256": _canonical_sha256(sorted(registry)),
        "design_sha256": c2.sha256_file(root / DESIGN_PATH),
        "denominators_sha256": c2.sha256_file(root / DENOMINATORS_PATH),
        "criteria_register_sha256": c2.sha256_file(root / CRITERIA_REGISTER_PATH),
        "session_manifest_sha256": c2.sha256_file(root / SESSION_MANIFEST_PATH),
        "partition_manifest_sha256": c2.sha256_file(root / PARTITION_MANIFEST_PATH),
        "primary_metric": "squadbot_categorical_direction_accuracy",
        "primary_threshold": recovery.SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD,
        "take_aggregation": recovery.SQUADBOT_TAKE_AGGREGATION_CONTRACT,
    }
    return {**payload, "protocol_sha256": _canonical_sha256(payload)}


def _expected_contract(repo_root: Path) -> dict[str, Any]:
    identity = protocol_identity(repo_root)
    return {
        "protocol_sha256": identity["protocol_sha256"],
        "holdout_id": identity["holdout_id"],
        "planned_take_ids_sha256": identity["planned_take_ids_sha256"],
        "planned_take_count": recovery.PLANNED_TAKE_COUNT,
    }


def classify_categorical_take(
    *,
    identity: c2.TakeIdentity,
    representative_bearing_deg: float | None,
    failed: bool,
) -> dict[str, Any]:
    """Apply the frozen SquadBot mapping exactly once to one take."""

    expected = recovery.bearing_to_squadbot_direction(
        identity.target_bearing_deg_f_project
    )
    observed = recovery.bearing_to_squadbot_direction(representative_bearing_deg)
    applicable = identity.stratum_id in {
        "A_controlled_boundary_sweep",
        "B_center_nominal_level",
    }
    if identity.stratum_id == "D_silence":
        correct: bool | None = not failed and observed in {None, "None"}
    elif applicable:
        expected_unavailable = expected == "None"
        observed_unavailable = observed in {None, "None"}
        correct = not failed and (
            observed_unavailable if expected_unavailable else observed == expected
        )
    else:
        correct = None
    return {
        "planned_take_id": identity.planned_take_id,
        "stratum_id": identity.stratum_id,
        "expected_direction": expected,
        "observed_direction": observed,
        "representative_bearing_deg_f_project": representative_bearing_deg,
        "failed": failed,
        "primary_metric_applicable": applicable,
        "categorical_correct": correct,
    }


def _adapted_configs(
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = repo_root.resolve()
    corrective_03 = c3.load_corrective_config(root)
    corrective_02 = c2.load_corrective_config(root)
    adapted = copy.deepcopy(corrective_02)
    for entry in adapted["sim_vs_real"]["comparison_registry"]:
        entry["expected_count"] = _COMPARISON_EXPECTED_COUNTS[entry["comparison_id"]]
    return corrective_03, adapted


def _effective_criteria(repo_root: Path) -> list[dict[str, Any]]:
    source = _load_json(repo_root.resolve() / c2.V1_CONFIG_PATH)["criteria"]
    diagnostic = (
        recovery.CONTINUOUS_BEARING_DIAGNOSTIC_CRITERIA
        | recovery.SUPERSEDED_SECTOR_CRITERIA
    )
    criteria = []
    for item in source:
        amended = dict(item)
        if amended["criterion_id"] in diagnostic:
            amended["gating"] = False
        criteria.append(amended)
    criteria.append(
        {
            "criterion_id": "squadbot_categorical_direction_accuracy",
            "tier": "readiness",
            "gating": True,
            "metric": "squadbot_categorical_direction",
            "statistic": "rate",
            "comparator": "greater_than_or_equal",
            "threshold": recovery.SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD,
        }
    )
    return criteria


def evaluate_payload(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> Recovery02EvaluationResult:
    """Return a truthful result without opening any observations."""

    root = repo_root.resolve()
    try:
        return _evaluate_payload_strict(payload, repo_root=root)
    except c2.CorrectiveAcceptanceError as exc:
        protocol = protocol_identity(root)
        return Recovery02EvaluationResult(
            outcomes=(),
            comparisons=(),
            categorical_take_results=(),
            identity_summary={
                "planned_take_count": recovery.PLANNED_TAKE_COUNT,
                "planned_take_denominator": recovery.PLANNED_TAKE_COUNT,
                "categorical_applicable_take_count": (
                    recovery.EXPECTED_DENOMINATOR_OVERRIDES[
                        "candidate_coverage_strata_ab"
                    ]
                ),
                "primary_metric_denominator": (
                    recovery.EXPECTED_DENOMINATOR_OVERRIDES[
                        "candidate_coverage_strata_ab"
                    ]
                ),
                "denominators_shrunk": False,
                "input_contract_adverse": True,
            },
            config_identity={
                "schema": RESULT_SCHEMA,
                "tool_version": TOOL_VERSION,
                "protocol_sha256": protocol["protocol_sha256"],
                "holdout_id": protocol["holdout_id"],
                "planned_take_count": recovery.PLANNED_TAKE_COUNT,
                "primary_direction_metric": ("squadbot_categorical_direction_accuracy"),
                "primary_direction_threshold": (
                    recovery.SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD
                ),
            },
            evaluation_error=str(exc),
        )


def _evaluate_payload_strict(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> Recovery02EvaluationResult:
    """Evaluate a contract-valid payload or raise an internal rejection."""

    root = repo_root.resolve()
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
        raise c2.CorrectiveAcceptanceError(
            f"payload fields must be exactly {sorted(_PAYLOAD_FIELDS)}"
        )
    if payload["schema"] != PAYLOAD_SCHEMA:
        raise c2.CorrectiveAcceptanceError(
            "S4.8 recovery_02 metrics payload schema mismatch"
        )
    contract = payload["contract"]
    if (
        not isinstance(contract, Mapping)
        or set(contract) != _CONTRACT_FIELDS
        or dict(contract) != _expected_contract(root)
    ):
        raise c2.CorrectiveAcceptanceError(
            "S4.8 recovery_02 payload contract identity mismatch"
        )
    registry = build_identity_registry(root)
    corrective_03, corrective_02 = _adapted_configs(root)
    takes = payload["takes"]
    if not isinstance(takes, Sequence) or isinstance(takes, (str, bytes)):
        raise c2.CorrectiveAcceptanceError("takes must be a sequence")

    normalized_takes: list[dict[str, Any]] = []
    derived_by_take: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    total_windows = 0
    valid_windows = 0
    abstained_windows = 0
    for index, raw in enumerate(takes):
        label = f"takes[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _TAKE_FIELDS:
            raise c2.CorrectiveAcceptanceError(
                f"{label} fields must be exactly {sorted(_TAKE_FIELDS)}"
            )
        identity_payload = raw.get("identity")
        take_id = (
            identity_payload.get("planned_take_id")
            if isinstance(identity_payload, Mapping)
            else None
        )
        if not isinstance(take_id, str) or not take_id:
            raise c2.CorrectiveAcceptanceError(
                f"{label}.planned_take_id must be a non-empty string"
            )
        if take_id in seen:
            raise c2.CorrectiveAcceptanceError(f"duplicate take identity: {take_id}")
        seen.add(take_id)
        identity = registry.get(take_id)
        if identity is None:
            raise c2.CorrectiveAcceptanceError(f"unknown take identity: {take_id}")
        normalized = dict(raw)
        windows = normalized.pop("bearing_windows")
        if (
            identity.stratum_id
            in corrective_03["window_observation_contract"]["applicable_strata"]
        ):
            derivation = c3._derive_window_values(
                windows,
                normalized,
                identity,
                corrective_03,
            )
            derived_by_take[take_id] = derivation
            normalized["bearing_absolute_error_deg"] = derivation["per_take_error_deg"]
            target = float(identity.target_bearing_deg_f_project)
            surrogate = (target + derivation["per_take_error_deg"]) % 360.0
            normalized["estimated_bearing_deg_f_project"] = surrogate
            if identity.stratum_id == "B_center_nominal_level":
                normalized["sector_correct"] = c3.bearing_deg_to_sector_name(
                    surrogate
                ) == c3.bearing_deg_to_sector_name(target)
            total_windows += derivation["source_window_count"]
            valid_windows += derivation["valid_window_count"]
            abstained_windows += derivation["abstained_window_count"]
        elif windows != []:
            raise c2.CorrectiveAcceptanceError(
                f"{take_id}.bearing_windows is not applicable and must be empty"
            )
        normalized_takes.append(normalized)
    normalized = c2._validate_take_records(
        normalized_takes,
        registry,
        corrective_02,
    )
    comparisons = c2._validate_comparisons(
        payload["sim_vs_real"],
        normalized,
        registry,
        corrective_02,
    )
    values = _derive_criterion_values(
        normalized,
        registry,
        comparisons,
        corrective_02,
    )

    sector_values = [
        bool(derived_by_take[take_id]["sector_correct"])
        for take_id, identity in registry.items()
        if identity.stratum_id == "B_center_nominal_level"
    ]
    sector_accuracy = sum(sector_values) / len(sector_values)
    representatives_by_cell: dict[str, list[float]] = defaultdict(list)
    for take_id, identity in registry.items():
        if identity.stratum_id == "A_controlled_boundary_sweep":
            representatives_by_cell[str(identity.bearing_cell_id)].append(
                derived_by_take[take_id]["representative_bearing_deg"]
            )
    repeatability = max(
        c2._circular_range(group) for group in representatives_by_cell.values()
    )

    categorical = tuple(
        classify_categorical_take(
            identity=registry[take_id],
            representative_bearing_deg=(
                derived_by_take[take_id]["representative_bearing_deg"]
                if take_id in derived_by_take
                else None
            ),
            failed=bool(normalized[take_id]["failed"]),
        )
        for take_id in sorted(registry)
    )
    applicable = [item for item in categorical if item["primary_metric_applicable"]]
    categorical_accuracy = (
        sum(item["categorical_correct"] is True for item in applicable)
        / recovery.EXPECTED_DENOMINATOR_OVERRIDES["candidate_coverage_strata_ab"]
    )
    values["squadbot_categorical_direction_accuracy"] = (
        categorical_accuracy,
        28,
    )
    outcomes = []
    for criterion in _effective_criteria(root):
        outcome = c2._evaluate_threshold(
            criterion,
            values[criterion["criterion_id"]],
        )
        if outcome.criterion_id in recovery.SUPERSEDED_SECTOR_CRITERIA:
            outcome = _replace_outcome(
                outcome,
                observed=sector_accuracy,
                sample_count=4,
            )
        elif outcome.criterion_id == "within_cell_bearing_circular_range_stratum_a":
            outcome = _replace_outcome(
                outcome,
                observed=repeatability,
                sample_count=8,
            )
        outcomes.append(outcome)

    stratum_counts = Counter(item.stratum_id for item in registry.values())
    protocol = protocol_identity(root)
    return Recovery02EvaluationResult(
        outcomes=tuple(outcomes),
        comparisons=tuple(comparisons),
        categorical_take_results=categorical,
        identity_summary={
            "take_count": len(normalized),
            "take_ids_sha256": _canonical_sha256(sorted(normalized)),
            "stratum_counts": dict(sorted(stratum_counts.items())),
            "group_count": len({item.group_id for item in registry.values()}),
            "raw_channel_record_count": sum(
                len(item["channels"]) for item in normalized.values()
            ),
            "tdoa_record_count": sum(len(item["tdoa"]) for item in normalized.values()),
            "bearing_window_record_count": total_windows,
            "valid_bearing_window_count": valid_windows,
            "abstained_bearing_window_count": abstained_windows,
            "categorical_applicable_take_count": len(applicable),
            "categorical_correct_take_count": sum(
                item["categorical_correct"] is True for item in applicable
            ),
            "categorical_expected_direction_counts": {
                "forward": 7,
                "right": 10,
                "left": 7,
                "None": 4,
            },
            "inherited_criterion_count": 29,
            "effective_gating_criterion_count": sum(
                outcome.gating for outcome in outcomes
            ),
        },
        config_identity={
            "schema": RESULT_SCHEMA,
            "tool_version": TOOL_VERSION,
            "protocol_sha256": protocol["protocol_sha256"],
            "holdout_id": protocol["holdout_id"],
            "planned_take_count": recovery.PLANNED_TAKE_COUNT,
            "primary_direction_metric": ("squadbot_categorical_direction_accuracy"),
            "primary_direction_threshold": (
                recovery.SQUADBOT_CATEGORICAL_ACCURACY_THRESHOLD
            ),
        },
    )


def _replace_outcome(
    outcome: c2.CriterionOutcome,
    *,
    observed: float,
    sample_count: int,
) -> c2.CriterionOutcome:
    if outcome.comparator == "less_than_or_equal":
        passed = observed <= outcome.threshold
    elif outcome.comparator == "greater_than_or_equal":
        passed = observed >= outcome.threshold
    elif outcome.comparator == "equal":
        passed = observed == outcome.threshold
    else:  # pragma: no cover - frozen comparator set
        raise c2.CorrectiveAcceptanceError(
            f"unsupported comparator: {outcome.comparator}"
        )
    return c2.CriterionOutcome(
        criterion_id=outcome.criterion_id,
        tier=outcome.tier,
        gating=outcome.gating,
        metric=outcome.metric,
        statistic=outcome.statistic,
        comparator=outcome.comparator,
        threshold=outcome.threshold,
        observed=observed,
        sample_count=sample_count,
        passed=passed,
    )


def _derive_criterion_values(
    takes: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, c2.TakeIdentity],
    comparisons: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, tuple[float, int]]:
    """Adapt only the frozen denominators and amended comparison roles."""

    by_stratum: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for take_id in sorted(takes):
        by_stratum[registry[take_id].stratum_id].append(takes[take_id])
    a = by_stratum["A_controlled_boundary_sweep"]
    b = by_stratum["B_center_nominal_level"]
    c = by_stratum["C_center_low_level"]
    d = by_stratum["D_silence"]
    e = by_stratum["E_impact_audio_video"]
    all_takes = [takes[key] for key in sorted(takes)]
    ab = a + b
    a_errors = [float(item["bearing_absolute_error_deg"]) for item in a]
    b_errors = [float(item["bearing_absolute_error_deg"]) for item in b]

    a_cells: dict[str, list[float]] = defaultdict(list)
    tdoa_groups: dict[str, list[float]] = defaultdict(list)
    for take_id in sorted(takes):
        identity = registry[take_id]
        if identity.stratum_id != "A_controlled_boundary_sweep":
            continue
        take = takes[take_id]
        a_cells[str(identity.bearing_cell_id)].append(
            float(take["estimated_bearing_deg_f_project"])
        )
        for item in take["tdoa"]:
            tdoa_groups[f"{identity.bearing_cell_id}|{item['pair_id']}"].append(
                float(item["tdoa_us"])
            )
    if len(a_cells) != 8 or any(len(group) != 3 for group in a_cells.values()):
        raise c2.CorrectiveAcceptanceError(
            "A bearing cells require exactly 3 repetitions"
        )
    if len(tdoa_groups) != 48 or any(len(group) != 3 for group in tdoa_groups.values()):
        raise c2.CorrectiveAcceptanceError(
            "A TDOA groups require exactly 3 repetitions"
        )

    b_by_pair = {
        c2._pair_key(registry[item["identity"]["planned_take_id"]]): float(
            item["confidence"]
        )
        for item in b
    }
    c_by_pair = {
        c2._pair_key(registry[item["identity"]["planned_take_id"]]): float(
            item["confidence"]
        )
        for item in c
    }
    if set(b_by_pair) != set(c_by_pair) or len(b_by_pair) != 4:
        raise c2.CorrectiveAcceptanceError(
            "B/C paired series must contain exactly four shared conditions"
        )

    channels = [channel for take in all_takes for channel in take["channels"]]
    window_count_d = sum(item["window_summary"]["source_window_count"] for item in d)
    window_count_ab = sum(item["window_summary"]["source_window_count"] for item in ab)
    abstained_d = sum(item["window_summary"]["abstained_window_count"] for item in d)
    abstained_ab = sum(item["window_summary"]["abstained_window_count"] for item in ab)
    comparison_map = {item["comparison_id"]: item for item in comparisons}
    bearing_comparison = comparison_map["bearing_doa_error_ab"]
    worsened = sum(
        item["classification"] == "worsens"
        for item in comparisons
        if item["comparison_id"] in _GATING_COMPARISON_IDS
    )
    frame_latency = [
        float(item["latency"]["frame_to_adapter_round_trip_ms"]) for item in all_takes
    ]
    capture_latency = [
        float(item["latency"]["capture_to_frame_offline_ms"]) for item in all_takes
    ]
    max_clip = max(int(item["maximum_clip_run_samples"]) for item in channels)
    clip_take_count = sum(
        any(channel["sustained_clipping"] for channel in take["channels"])
        for take in all_takes
    )
    values = {
        "bearing_median_absolute_error_stratum_a": (float(median(a_errors)), 24),
        "bearing_p95_absolute_error_stratum_a": (c2._nearest_rank(a_errors), 24),
        "bearing_worst_absolute_error_stratum_a": (max(a_errors), 24),
        "bearing_median_absolute_error_stratum_b": (float(median(b_errors)), 4),
        "sector_accuracy_stratum_b": (
            sum(bool(item["sector_correct"]) for item in b) / 4,
            4,
        ),
        "candidate_coverage_strata_ab": (
            sum(bool(item["candidate_covered"]) for item in ab) / 28,
            28,
        ),
        "within_cell_bearing_circular_range_stratum_a": (
            max(c2._circular_range(group) for group in a_cells.values()),
            8,
        ),
        "within_cell_pair_tdoa_range_stratum_a": (
            max(max(group) - min(group) for group in tdoa_groups.values()),
            48,
        ),
        "frame_to_adapter_latency_p95": (
            c2._nearest_rank(frame_latency),
            37,
        ),
        "capture_to_frame_offline_spread": (
            max(capture_latency) - min(capture_latency),
            37,
        ),
        "raw_channel_health_failure_count": (
            float(sum(item["health_failure"] for item in channels)),
            148,
        ),
        "major_polarity_anomaly_count": (
            float(sum(item["major_polarity_anomaly"] for item in channels)),
            148,
        ),
        "sustained_clipping_take_count": (float(clip_take_count), 37),
        "maximum_clip_run_samples": (float(max_clip), 37),
        "take_failure_rate": (
            sum(bool(item["failed"]) for item in all_takes) / 37,
            37,
        ),
        "silence_abstention_rate_stratum_d": (
            abstained_d / window_count_d,
            window_count_d,
        ),
        "active_abstention_rate_strata_ab": (
            abstained_ab / window_count_ab,
            window_count_ab,
        ),
        "confidence_median_stratum_b": (float(median(b_by_pair.values())), 4),
        "sub_floor_direction_emission_count": (
            float(
                sum(
                    item["window_summary"]["sub_floor_direction_emission_count"]
                    for item in all_takes
                )
            ),
            sum(item["window_summary"]["source_window_count"] for item in all_takes),
        ),
        "low_level_confidence_monotonicity": (
            float(median(c_by_pair.values())) - float(median(b_by_pair.values())),
            4,
        ),
        "coarse_av_association_residual_stratum_e": (
            max(float(item["av_absolute_residual_ms"]) for item in e),
            2,
        ),
        "sim_adjusted_bearing_median_delta_vs_real": (
            abs(
                float(bearing_comparison["adjusted_simulation"])
                - float(bearing_comparison["real"])
            ),
            28,
        ),
        "sim_adjustment_worsened_gating_metric_count": (float(worsened), 5),
    }
    values.update(
        {
            "bearing_median_absolute_error_stratum_a_stretch": values[
                "bearing_median_absolute_error_stratum_a"
            ],
            "bearing_p95_absolute_error_stratum_a_stretch": values[
                "bearing_p95_absolute_error_stratum_a"
            ],
            "sector_accuracy_stratum_b_stretch": values["sector_accuracy_stratum_b"],
            "candidate_coverage_strata_ab_stretch": values[
                "candidate_coverage_strata_ab"
            ],
            "active_abstention_rate_strata_ab_stretch": values[
                "active_abstention_rate_strata_ab"
            ],
            "sim_adjusted_bearing_median_delta_vs_real_stretch": values[
                "sim_adjusted_bearing_median_delta_vs_real"
            ],
        }
    )
    return values


def build_synthetic_payload(repo_root: Path) -> dict[str, Any]:
    """Build deterministic engineering-only input for adapter tests."""

    root = repo_root.resolve()
    registry = build_identity_registry(root)
    corrective_03, config = _adapted_configs(root)
    microphones = config["identity_contract"]["raw_microphone_ids"]
    pair_ids = config["identity_contract"]["microphone_pair_ids"]
    takes: list[dict[str, Any]] = []
    for take_id in sorted(registry):
        identity = registry[take_id]
        expected_windows = config["window_contract"]["expected_count_by_duration_s"][
            str(identity.duration_s)
        ]
        is_a = identity.stratum_id == "A_controlled_boundary_sweep"
        is_b = identity.stratum_id == "B_center_nominal_level"
        is_c = identity.stratum_id == "C_center_low_level"
        is_d = identity.stratum_id == "D_silence"
        is_e = identity.stratum_id == "E_impact_audio_video"
        target = identity.target_bearing_deg_f_project
        bearing = None if target is None else (float(target) + 4.0) % 360.0
        windows = (
            [c3._window_record(index, bearing) for index in range(expected_windows)]
            if is_a or is_b
            else []
        )
        takes.append(
            {
                "identity": identity.payload_identity(),
                "failed": False,
                "failure_reasons": [],
                "latency": {
                    "frame_to_adapter_round_trip_ms": 1.0,
                    "capture_to_frame_offline_ms": 10.0,
                },
                "window_summary": {
                    "source_window_count": expected_windows,
                    "abstained_window_count": expected_windows if is_d else 0,
                    "sub_floor_direction_emission_count": 0,
                },
                "channels": [
                    {
                        "microphone_id": microphone,
                        "health_failure": False,
                        "major_polarity_anomaly": False,
                        "maximum_clip_run_samples": 0,
                        "sustained_clipping": False,
                    }
                    for microphone in microphones
                ],
                "bearing_absolute_error_deg": 4.0 if (is_a or is_b) else None,
                "estimated_bearing_deg_f_project": (
                    bearing if (is_a or is_b) else None
                ),
                "sector_correct": True if is_b else None,
                "candidate_covered": True if (is_a or is_b) else None,
                "candidate_bearings_deg_f_project": (
                    [float(target)] if (is_a or is_b) else []
                ),
                "confidence": 0.04 if is_b else (0.02 if is_c else None),
                "tdoa": (
                    [
                        {
                            "pair_id": pair_id,
                            "tdoa_us": 10.0,
                            "reference_tdoa_us": 5.0,
                            "absolute_error_us": 5.0,
                        }
                        for pair_id in pair_ids
                    ]
                    if is_a
                    else []
                ),
                "audio_event_time_ms": 100.0 if is_e else None,
                "video_event_time_ms": 120.0 if is_e else None,
                "av_absolute_residual_ms": 20.0 if is_e else None,
                "bearing_windows": windows,
            }
        )
    normalized_for_comparisons = [
        {key: value for key, value in item.items() if key != "bearing_windows"}
        for item in takes
    ]
    normalized_map = {
        item["identity"]["planned_take_id"]: item for item in normalized_for_comparisons
    }
    comparisons = []
    for entry in config["sim_vs_real"]["comparison_registry"]:
        conditions = sorted(c2._expected_comparison_conditions(entry, registry, config))
        comparisons.append(
            {
                "comparison_id": entry["comparison_id"],
                "conditions": [
                    {
                        "condition_id": condition_id,
                        "unadjusted_simulation": c2._derive_real_condition_value(
                            entry,
                            condition_id,
                            normalized_map,
                            registry,
                            config,
                        ),
                        "adjusted_simulation": c2._derive_real_condition_value(
                            entry,
                            condition_id,
                            normalized_map,
                            registry,
                            config,
                        ),
                    }
                    for condition_id in conditions
                ],
            }
        )
    return {
        "schema": PAYLOAD_SCHEMA,
        "contract": _expected_contract(root),
        "takes": takes,
        "sim_vs_real": comparisons,
    }


__all__ = [
    "PAYLOAD_SCHEMA",
    "RESULT_SCHEMA",
    "TOOL_VERSION",
    "Recovery02EvaluationResult",
    "build_identity_registry",
    "build_synthetic_payload",
    "classify_categorical_take",
    "evaluate_payload",
    "protocol_identity",
]
