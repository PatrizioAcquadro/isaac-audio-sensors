"""Exact-window evaluation for the additive S4.7 corrective_03 contract.

The module restores the frozen window-level bearing and sector calculations,
then delegates every unchanged corrective_02 identity, physical-domain,
comparison, clipping, latency, and threshold rule to the existing evaluator.
It contains no dataset or grant-opening path.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import jsonschema

from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    CONFIG_PATH as CORRECTIVE_02_CONFIG_PATH,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    PAYLOAD_SCHEMA as CORRECTIVE_02_PAYLOAD_SCHEMA,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    CorrectiveAcceptanceError,
    CriterionOutcome,
    TakeIdentity,
    sha256_file,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    build_identity_registry as build_corrective_02_identity_registry,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    build_synthetic_payload as build_corrective_02_synthetic_payload,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    evaluate_corrective as evaluate_corrective_02,
)
from isaac_audio_sensors.core.doa.sector_mapping import (
    bearing_deg_to_sector_name,
)

CONFIG_PATH = Path("configs/s4_7_holdout_acceptance.corrective_03.v4.json")
SCHEMA_PATH = Path(
    "docs/schemas/s4_7_holdout_acceptance.corrective_03.v4.schema.json"
)
V1_CONFIG_PATH = Path("configs/s4_7_holdout_acceptance.v1.json")
PAYLOAD_SCHEMA = "ias.s4_7.corrective_metrics.v4"
RESULT_SCHEMA = "ias.s4_7.criteria_evaluation_result.v4"

_PAYLOAD_FIELDS = frozenset({"schema", "contract", "takes", "sim_vs_real"})
_CONTRACT_FIELDS = frozenset(
    {
        "config_sha256",
        "bound_holdout_id",
        "seal_payload_sha256",
        "planned_take_count",
    }
)
_WINDOW_FIELDS = frozenset(
    {
        "window_id",
        "window_index",
        "start_sample",
        "abstained",
        "srp_bearing_deg_f_project",
        "sub_floor_direction_emitted",
    }
)
_CORRECTIVE_02_TAKE_FIELDS = frozenset(
    {
        "identity",
        "failed",
        "failure_reasons",
        "latency",
        "window_summary",
        "channels",
        "bearing_absolute_error_deg",
        "estimated_bearing_deg_f_project",
        "sector_correct",
        "candidate_covered",
        "candidate_bearings_deg_f_project",
        "confidence",
        "tdoa",
        "audio_event_time_ms",
        "video_event_time_ms",
        "av_absolute_residual_ms",
    }
)
_TAKE_FIELDS = _CORRECTIVE_02_TAKE_FIELDS | {"bearing_windows"}


@dataclass(frozen=True, slots=True)
class CorrectiveAcceptanceResult:
    """Complete corrective_03 identity and criteria result."""

    outcomes: tuple[CriterionOutcome, ...]
    comparisons: tuple[dict[str, Any], ...]
    identity_summary: dict[str, Any]
    config_identity: dict[str, Any]

    @property
    def readiness_passed(self) -> bool:
        return all(item.passed for item in self.outcomes if item.gating)

    def report(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "status": "passed" if self.readiness_passed else "failed",
            "readiness_passed": self.readiness_passed,
            "failed_gating_criteria": [
                item.criterion_id
                for item in self.outcomes
                if item.gating and not item.passed
            ],
            "criteria": [item.report() for item in self.outcomes],
            "comparison_classifications": list(self.comparisons),
            "identity_summary": self.identity_summary,
            "config_identity": self.config_identity,
            "holdout_observations_accessed_by_evaluator": 0,
        }


def load_corrective_config(repo_root: Path) -> dict[str, Any]:
    """Load and authenticate the additive corrective_03 contract."""

    root = repo_root.resolve()
    config = _load_json(_repo_file(root, CONFIG_PATH))
    schema = _load_json(_repo_file(root, SCHEMA_PATH))
    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise CorrectiveAcceptanceError(
            f"corrective_03 config schema validation failed: {exc.message}"
        ) from exc
    bindings = (
        (
            config["supersedes"]["config_path"],
            config["supersedes"]["config_sha256"],
        ),
        (
            config["supersedes"]["schema_path"],
            config["supersedes"]["schema_sha256"],
        ),
        (
            config["supersedes"]["spec_path"],
            config["supersedes"]["spec_sha256"],
        ),
        (
            f"{config['supersedes']['package_path']}/SHA256SUMS",
            config["supersedes"]["package_sha256_manifest"],
        ),
        (
            config["inherited_contract"]["criteria_config_path"],
            config["inherited_contract"]["criteria_config_sha256"],
        ),
        (
            config["inherited_contract"]["criteria_spec_path"],
            config["inherited_contract"]["criteria_spec_sha256"],
        ),
        (
            config["window_observation_contract"]["source_config_path"],
            config["window_observation_contract"]["source_config_sha256"],
        ),
    )
    for relative, expected in bindings:
        if sha256_file(_repo_file(root, Path(relative))) != expected:
            raise CorrectiveAcceptanceError(f"hash binding mismatch: {relative}")
    return config


def build_identity_registry(
    repo_root: Path, config: Mapping[str, Any] | None = None
) -> dict[str, TakeIdentity]:
    """Reuse the authenticated corrective_02 47-take technical projection."""

    load_corrective_config(repo_root) if config is None else None
    return build_corrective_02_identity_registry(repo_root)


def build_synthetic_payload(
    repo_root: Path, *, passing: bool = True
) -> dict[str, Any]:
    """Build a deterministic exact-window, identity-complete synthetic fixture."""

    root = repo_root.resolve()
    config = load_corrective_config(root)
    registry = build_identity_registry(root, config)
    payload = build_corrective_02_synthetic_payload(root, passing=passing)
    payload["schema"] = PAYLOAD_SCHEMA
    payload["contract"]["config_sha256"] = sha256_file(root / CONFIG_PATH)
    applicable = set(config["window_observation_contract"]["applicable_strata"])
    for take in payload["takes"]:
        take_id = take["identity"]["planned_take_id"]
        identity = registry[take_id]
        if identity.stratum_id not in applicable:
            take["bearing_windows"] = []
            continue
        target = float(identity.target_bearing_deg_f_project)
        count = config["window_observation_contract"][
            "expected_count_by_duration_s"
        ][str(identity.duration_s)]
        take["bearing_windows"] = [
            _window_record(index, (target + 4.0) % 360.0)
            for index in range(count)
        ]
    return payload


def build_semantic_bypass_regression_payload(
    repo_root: Path,
) -> dict[str, Any]:
    """Build the exact four-affected/four-conforming B-take regression."""

    payload = build_synthetic_payload(repo_root)
    offsets = (-45.0, -35.0, -25.0, -5.0, 5.0, 55.0, 65.0)
    for take in payload["takes"]:
        identity = take["identity"]
        if (
            identity["stratum_id"] != "B_center_nominal_level"
            or identity["target_bearing_deg_f_project"] not in {45.0, 135.0}
        ):
            continue
        target = float(identity["target_bearing_deg_f_project"])
        count = len(take["bearing_windows"])
        bearings = [
            (target + offsets[index % len(offsets)]) % 360.0
            for index in range(count)
        ]
        take["bearing_windows"] = [
            _window_record(index, bearing)
            for index, bearing in enumerate(bearings)
        ]
        take["window_summary"] = {
            "source_window_count": count,
            "abstained_window_count": 0,
            "sub_floor_direction_emission_count": 0,
        }
        take["bearing_absolute_error_deg"] = None
        take["estimated_bearing_deg_f_project"] = None
        take["sector_correct"] = None
    return payload


def evaluate_corrective(
    payload: Mapping[str, Any], *, repo_root: Path
) -> CorrectiveAcceptanceResult:
    """Derive frozen scientific summaries from exact windows and evaluate."""

    root = repo_root.resolve()
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
        raise CorrectiveAcceptanceError(
            f"payload fields must be exactly {sorted(_PAYLOAD_FIELDS)}"
        )
    if payload["schema"] != PAYLOAD_SCHEMA:
        raise CorrectiveAcceptanceError("corrective_03 metrics payload schema mismatch")
    config = load_corrective_config(root)
    registry = build_identity_registry(root, config)
    _validate_contract_identity(payload["contract"], config, root)
    takes = payload["takes"]
    if not isinstance(takes, Sequence) or isinstance(takes, (str, bytes)):
        raise CorrectiveAcceptanceError("takes must be a sequence")

    delegated = copy.deepcopy(dict(payload))
    delegated["schema"] = CORRECTIVE_02_PAYLOAD_SCHEMA
    delegated["contract"]["config_sha256"] = sha256_file(
        root / CORRECTIVE_02_CONFIG_PATH
    )
    total_windows = 0
    valid_windows = 0
    abstained_windows = 0
    derived_by_take: dict[str, dict[str, Any]] = {}
    normalized_takes: list[dict[str, Any]] = []
    seen_take_ids: set[str] = set()
    for index, raw in enumerate(takes):
        label = f"takes[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _TAKE_FIELDS:
            raise CorrectiveAcceptanceError(
                f"{label} fields must be exactly {sorted(_TAKE_FIELDS)}"
            )
        identity_payload = raw.get("identity")
        if not isinstance(identity_payload, Mapping):
            raise CorrectiveAcceptanceError(f"{label}.identity must be an object")
        take_id = identity_payload.get("planned_take_id")
        if not isinstance(take_id, str) or not take_id:
            raise CorrectiveAcceptanceError(
                f"{label}.planned_take_id must be a non-empty string"
            )
        if take_id in seen_take_ids:
            raise CorrectiveAcceptanceError(f"duplicate take identity: {take_id}")
        seen_take_ids.add(take_id)
        identity = registry.get(take_id)
        if identity is None:
            raise CorrectiveAcceptanceError(f"unknown take identity: {take_id}")
        normalized = dict(raw)
        windows = normalized.pop("bearing_windows")
        if identity.stratum_id in config["window_observation_contract"][
            "applicable_strata"
        ]:
            derivation = _derive_window_values(
                windows, normalized, identity, config
            )
            derived_by_take[take_id] = derivation
            normalized["bearing_absolute_error_deg"] = derivation[
                "per_take_error_deg"
            ]
            target = float(identity.target_bearing_deg_f_project)
            surrogate = (target + derivation["per_take_error_deg"]) % 360.0
            normalized["estimated_bearing_deg_f_project"] = surrogate
            if identity.stratum_id == "B_center_nominal_level":
                normalized["sector_correct"] = (
                    bearing_deg_to_sector_name(surrogate)
                    == bearing_deg_to_sector_name(target)
                )
            total_windows += derivation["source_window_count"]
            valid_windows += derivation["valid_window_count"]
            abstained_windows += derivation["abstained_window_count"]
        elif windows != []:
            raise CorrectiveAcceptanceError(
                f"{take_id}.bearing_windows is not applicable and must be empty"
            )
        normalized_takes.append(normalized)
    delegated["takes"] = normalized_takes
    delegated_result = evaluate_corrective_02(delegated, repo_root=root)
    comparisons = [dict(item) for item in delegated_result.comparisons]
    sector_comparison = next(
        item
        for item in comparisons
        if item["comparison_id"] == "sector_accuracy_b"
    )
    sector_values = [
        bool(derived_by_take[take_id]["sector_correct"])
        for take_id, identity in registry.items()
        if identity.stratum_id == "B_center_nominal_level"
    ]
    sector_accuracy = sum(sector_values) / len(sector_values)
    sector_comparison["real"] = sector_accuracy

    representatives_by_cell: dict[str, list[float]] = {}
    for take_id, identity in registry.items():
        if identity.stratum_id != "A_controlled_boundary_sweep":
            continue
        representatives_by_cell.setdefault(
            str(identity.bearing_cell_id), []
        ).append(derived_by_take[take_id]["representative_bearing_deg"])
    repeatability = max(
        _circular_range(values) for values in representatives_by_cell.values()
    )
    outcomes = tuple(
        _replace_derived_outcome(item, sector_accuracy, repeatability)
        for item in delegated_result.outcomes
    )
    config_identity = {
        "schema": config["schema"],
        "corrective_id": config["corrective_id"],
        "config_sha256": sha256_file(root / CONFIG_PATH),
        "bound_holdout_id": delegated_result.config_identity["bound_holdout_id"],
        "seal_payload_sha256": delegated_result.config_identity[
            "seal_payload_sha256"
        ],
        "planned_take_count": 47,
        "frozen_at_utc": config["frozen_at_utc"],
    }
    identity_summary = dict(delegated_result.identity_summary)
    identity_summary.update(
        {
            "bearing_window_record_count": total_windows,
            "valid_bearing_window_count": valid_windows,
            "abstained_bearing_window_count": abstained_windows,
            "bearing_window_derivation": "corrective_03_exact_windows",
        }
    )
    return CorrectiveAcceptanceResult(
        outcomes=outcomes,
        comparisons=tuple(comparisons),
        identity_summary=identity_summary,
        config_identity=config_identity,
    )


def _derive_window_values(
    windows: Any,
    take: Mapping[str, Any],
    identity: TakeIdentity,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    take_id = identity.planned_take_id
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes)):
        raise CorrectiveAcceptanceError(
            f"{take_id}.bearing_windows must be a sequence"
        )
    contract = config["window_observation_contract"]
    expected_count = contract["expected_count_by_duration_s"][
        str(identity.duration_s)
    ]
    if len(windows) != expected_count:
        raise CorrectiveAcceptanceError(
            f"{take_id} exact bearing window count mismatch: "
            f"expected {expected_count}, found {len(windows)}"
        )
    seen_indices: set[int] = set()
    seen_ids: set[str] = set()
    valid: list[float] = []
    abstained_count = 0
    sub_floor_count = 0
    for position, item in enumerate(windows):
        label = f"{take_id}.bearing_windows[{position}]"
        if not isinstance(item, Mapping) or set(item) != _WINDOW_FIELDS:
            raise CorrectiveAcceptanceError(
                f"{label} fields must be exactly {sorted(_WINDOW_FIELDS)}"
            )
        index = _integer(item["window_index"], f"{label}.window_index", 0)
        if index in seen_indices:
            raise CorrectiveAcceptanceError(
                f"{take_id} duplicate bearing window index: {index}"
            )
        seen_indices.add(index)
        expected_id = f"window_{index:03d}"
        window_id = item["window_id"]
        if not isinstance(window_id, str) or window_id != expected_id:
            raise CorrectiveAcceptanceError(
                f"{label}.window_id mismatch: expected {expected_id}"
            )
        if window_id in seen_ids:
            raise CorrectiveAcceptanceError(
                f"{take_id} duplicate bearing window identity: {window_id}"
            )
        seen_ids.add(window_id)
        start = _integer(item["start_sample"], f"{label}.start_sample", 0)
        expected_start = index * contract["hop_samples"]
        if start != expected_start:
            raise CorrectiveAcceptanceError(
                f"{label}.start_sample mismatch: expected {expected_start}"
            )
        abstained = item["abstained"]
        if not isinstance(abstained, bool):
            raise CorrectiveAcceptanceError(f"{label}.abstained must be boolean")
        emitted = item["sub_floor_direction_emitted"]
        if not isinstance(emitted, bool):
            raise CorrectiveAcceptanceError(
                f"{label}.sub_floor_direction_emitted must be boolean"
            )
        sub_floor_count += int(emitted)
        bearing = item["srp_bearing_deg_f_project"]
        if abstained:
            if bearing is not None:
                raise CorrectiveAcceptanceError(
                    f"{label} abstained state requires a null bearing"
                )
            abstained_count += 1
        else:
            valid.append(_bearing(bearing, f"{label}.srp_bearing_deg_f_project"))
    expected_indices = set(range(expected_count))
    if seen_indices != expected_indices:
        raise CorrectiveAcceptanceError(
            f"{take_id} exact bearing window identity set mismatch"
        )
    if not valid:
        raise CorrectiveAcceptanceError(
            f"{take_id} has no valid bearing window"
        )
    summary = take.get("window_summary")
    if not isinstance(summary, Mapping):
        raise CorrectiveAcceptanceError(f"{take_id}.window_summary must be an object")
    expected_summary = {
        "source_window_count": expected_count,
        "abstained_window_count": abstained_count,
        "sub_floor_direction_emission_count": sub_floor_count,
    }
    if dict(summary) != expected_summary:
        raise CorrectiveAcceptanceError(
            f"{take_id}.window_summary contradicts exact bearing windows"
        )
    target = identity.target_bearing_deg_f_project
    if target is None:  # pragma: no cover - applicability is registry-bound
        raise CorrectiveAcceptanceError(f"{take_id} lacks a target bearing")
    errors = [_circular_absolute_difference(target, value) for value in valid]
    derived_error = float(median(errors))
    representative = float(median(valid))
    _reported_exact(
        take.get("bearing_absolute_error_deg"),
        derived_error,
        f"{take_id}.bearing_absolute_error_deg",
    )
    reported_representative = take.get("estimated_bearing_deg_f_project")
    if reported_representative is not None and _bearing(
        reported_representative,
        f"{take_id}.estimated_bearing_deg_f_project",
    ) != representative:
        raise CorrectiveAcceptanceError(
            f"{take_id}.estimated_bearing_deg_f_project contradicts "
            "exact bearing windows"
        )
    majority_sector = _majority_sector(valid)
    sector_correct = (
        majority_sector is not None
        and majority_sector == bearing_deg_to_sector_name(target)
    )
    if identity.stratum_id == "B_center_nominal_level":
        reported_sector = take.get("sector_correct")
        if reported_sector is not None and reported_sector is not sector_correct:
            raise CorrectiveAcceptanceError(
                f"{take_id}.sector_correct contradicts window-sector majority"
            )
    return {
        "source_window_count": expected_count,
        "valid_window_count": len(valid),
        "abstained_window_count": abstained_count,
        "per_take_error_deg": derived_error,
        "representative_bearing_deg": representative,
        "majority_sector": majority_sector,
        "sector_correct": sector_correct,
    }


def _majority_sector(valid_bearings: Sequence[float]) -> str | None:
    counts = Counter(bearing_deg_to_sector_name(value) for value in valid_bearings)
    if not counts:
        return None
    highest = max(counts.values())
    winners = [sector for sector, count in counts.items() if count == highest]
    return winners[0] if len(winners) == 1 else None


def _circular_range(values: Sequence[float]) -> float:
    ordered = sorted(float(value) % 360.0 for value in values)
    gaps = [
        later - earlier
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    ]
    gaps.append(ordered[0] + 360.0 - ordered[-1])
    return 360.0 - max(gaps)


def _replace_derived_outcome(
    outcome: CriterionOutcome,
    sector_accuracy: float,
    repeatability: float,
) -> CriterionOutcome:
    if outcome.criterion_id in {
        "sector_accuracy_stratum_b",
        "sector_accuracy_stratum_b_stretch",
    }:
        observed = sector_accuracy
        sample_count = 8
    elif outcome.criterion_id == "within_cell_bearing_circular_range_stratum_a":
        observed = repeatability
        sample_count = 8
    else:
        return outcome
    if outcome.comparator == "less_than_or_equal":
        passed = observed <= outcome.threshold
    elif outcome.comparator == "greater_than_or_equal":
        passed = observed >= outcome.threshold
    else:  # pragma: no cover
        raise CorrectiveAcceptanceError(
            f"unsupported derived comparator: {outcome.comparator}"
        )
    return CriterionOutcome(
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


def _window_record(
    index: int,
    bearing: float | None,
    *,
    abstained: bool = False,
    sub_floor_direction_emitted: bool = False,
) -> dict[str, Any]:
    return {
        "window_id": f"window_{index:03d}",
        "window_index": index,
        "start_sample": index * 2000,
        "abstained": abstained,
        "srp_bearing_deg_f_project": None if abstained else bearing,
        "sub_floor_direction_emitted": sub_floor_direction_emitted,
    }


def _reported_exact(value: Any, expected: float, label: str) -> None:
    if value is None:
        return
    reported = _bearing_error(value, label)
    if reported != expected:
        raise CorrectiveAcceptanceError(
            f"{label} contradicts exact bearing windows"
        )


def _bearing(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CorrectiveAcceptanceError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CorrectiveAcceptanceError(f"{label} must be finite")
    if not 0.0 <= result < 360.0:
        raise CorrectiveAcceptanceError(f"{label} must be in [0, 360)")
    return result


def _bearing_error(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CorrectiveAcceptanceError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 180.0:
        raise CorrectiveAcceptanceError(f"{label} must be in [0, 180]")
    return result


def _integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorrectiveAcceptanceError(f"{label} must be an integer")
    if value < minimum:
        raise CorrectiveAcceptanceError(f"{label} must be >= {minimum}")
    return value


def _circular_absolute_difference(first: float, second: float) -> float:
    difference = abs((float(first) - float(second)) % 360.0)
    return min(difference, 360.0 - difference)


def _validate_contract_identity(
    value: Any, config: Mapping[str, Any], repo_root: Path
) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONTRACT_FIELDS:
        raise CorrectiveAcceptanceError(
            f"payload contract fields must be exactly {sorted(_CONTRACT_FIELDS)}"
        )
    corrective_02 = _load_json(repo_root / CORRECTIVE_02_CONFIG_PATH)
    expected = {
        "config_sha256": sha256_file(repo_root / CONFIG_PATH),
        "bound_holdout_id": corrective_02["holdout_binding"]["bound_holdout_id"],
        "seal_payload_sha256": corrective_02["holdout_binding"][
            "seal_payload_sha256"
        ],
        "planned_take_count": 47,
    }
    if dict(value) != expected:
        raise CorrectiveAcceptanceError("payload contract identity mismatch")


def _repo_file(root: Path, relative: Path) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CorrectiveAcceptanceError(
            f"contract path escapes repository: {relative}"
        ) from exc
    if not path.is_file():
        raise CorrectiveAcceptanceError(f"contract file is missing: {relative}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CorrectiveAcceptanceError(f"expected JSON object: {path}")
    return value


__all__ = [
    "CONFIG_PATH",
    "PAYLOAD_SCHEMA",
    "RESULT_SCHEMA",
    "SCHEMA_PATH",
    "CorrectiveAcceptanceError",
    "CorrectiveAcceptanceResult",
    "TakeIdentity",
    "build_identity_registry",
    "build_semantic_bypass_regression_payload",
    "build_synthetic_payload",
    "evaluate_corrective",
    "load_corrective_config",
    "sha256_file",
]
