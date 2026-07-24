"""Deterministic evaluation of the frozen S4.7 held-out acceptance criteria.

The criteria are frozen in ``configs/s4_7_holdout_acceptance.v1.json`` before
any held-out observation is opened. This module executes them and nothing else:
it reads the frozen configuration, applies the frozen statistics to a metrics
payload supplied by the caller, and reports one deterministic outcome per
criterion. It never reads a recording, a dataset attempt, or any other holdout
artifact, and it has no code path that can open a sealed holdout.

Evaluation fails closed. A missing observable, a non-finite value, or a
denominator that does not match its frozen expected count is a criterion
failure, never a pass and never a silent skip. An observable the frozen
configuration does not declare is a configuration error that rejects the whole
evaluation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

CRITERIA_CONFIG_PATH = Path("configs/s4_7_holdout_acceptance.v1.json")
CRITERIA_SCHEMA_PATH = Path("docs/schemas/s4_7_holdout_acceptance.v1.schema.json")
CONFIG_SCHEMA = "ias.s4_7.holdout_acceptance_config.v1"
RESULT_SCHEMA = "ias.s4_7.criteria_evaluation_result.v1"
SMALL_SAMPLE_THRESHOLD = 8

_COMPARISON_FIELDS = frozenset(
    {
        "metric",
        "condition_id",
        "band_key",
        "lower_is_better",
        "real",
        "unadjusted_simulation",
        "adjusted_simulation",
    }
)
_COUNTER_FIELDS = frozenset({"numerator", "denominator"})


class AcceptanceCriteriaError(ValueError):
    """Raised when the frozen criteria or the supplied payload are unusable."""


@dataclass(frozen=True, slots=True)
class CriterionOutcome:
    """One deterministic verdict for one frozen criterion."""

    criterion_id: str
    metric: str
    tier: str
    gating: bool
    statistic: str
    comparator: str
    threshold: float
    observed: float | None
    passed: bool
    status: str
    detail: str
    sample_count: int | None
    small_sample: bool
    denominator: dict[str, Any] | None
    sample_summary: dict[str, Any] | None

    def report(self) -> dict[str, Any]:
        """Return the sorted, JSON-serializable record for this criterion."""

        return {
            "criterion_id": self.criterion_id,
            "denominator": self.denominator,
            "detail": self.detail,
            "gating": self.gating,
            "metric": self.metric,
            "observed": self.observed,
            "passed": self.passed,
            "sample_count": self.sample_count,
            "sample_summary": self.sample_summary,
            "small_sample": self.small_sample,
            "statistic": self.statistic,
            "status": self.status,
            "threshold": self.threshold,
            "tier": self.tier,
        }


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    """The complete evaluation of every frozen criterion."""

    outcomes: tuple[CriterionOutcome, ...]
    config_identity: dict[str, Any]
    comparison_classifications: tuple[dict[str, Any], ...]

    @property
    def readiness_passed(self) -> bool:
        """Return whether every gating criterion passed."""

        return all(outcome.passed for outcome in self.outcomes if outcome.gating)

    def report(self) -> dict[str, Any]:
        """Return the deterministic evaluation report."""

        gating = [outcome for outcome in self.outcomes if outcome.gating]
        failed = [outcome.criterion_id for outcome in gating if not outcome.passed]
        return {
            "schema": RESULT_SCHEMA,
            "status": "passed" if self.readiness_passed else "failed",
            "config_identity": self.config_identity,
            "comparison_classifications": list(self.comparison_classifications),
            "criteria": [outcome.report() for outcome in self.outcomes],
            "failed_gating_criteria": failed,
            "gating_criterion_count": len(gating),
            "holdout_observations_accessed": 0,
            "readiness_passed": self.readiness_passed,
            "stretch_criterion_count": len(self.outcomes) - len(gating),
        }


def load_criteria(
    *,
    repo_root: Path,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Load and validate the frozen criteria configuration."""

    resolved = _resolve_repo_file(repo_root, config_path or CRITERIA_CONFIG_PATH)
    config = _load_json(resolved)
    schema = _load_json(_resolve_repo_file(repo_root, CRITERIA_SCHEMA_PATH))
    _validate_json_schema(config, schema, label=resolved.name)
    if config.get("schema") != CONFIG_SCHEMA:
        raise AcceptanceCriteriaError(
            f"criteria schema: expected {CONFIG_SCHEMA}, found {config.get('schema')!r}"
        )
    if config.get("status") != "frozen":
        raise AcceptanceCriteriaError("criteria status: expected frozen")
    identifiers = [item["criterion_id"] for item in config["criteria"]]
    if len(identifiers) != len(set(identifiers)):
        raise AcceptanceCriteriaError("criteria contain a duplicate criterion_id")
    return config


def evaluate_criteria(
    metrics: Mapping[str, Any],
    *,
    repo_root: Path,
    config_path: Path | None = None,
) -> AcceptanceResult:
    """Evaluate every frozen criterion against one metrics payload."""

    if not isinstance(metrics, Mapping):
        raise AcceptanceCriteriaError("metrics payload: expected a mapping")
    config = load_criteria(repo_root=repo_root, config_path=config_path)
    declared = _declared_observables(config)
    supplied = set(metrics)
    unexpected = sorted(supplied - declared)
    if unexpected:
        raise AcceptanceCriteriaError(
            "metrics payload declares observables the frozen criteria do not "
            f"define: {unexpected}"
        )

    classifications = _classify_comparisons(config, metrics)
    outcomes = tuple(
        _evaluate_one(criterion, metrics, config, classifications)
        for criterion in config["criteria"]
    )
    return AcceptanceResult(
        outcomes=outcomes,
        config_identity={
            "baseline_commit": config["baseline_commit"],
            "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
            "claimed_envelope": config["envelope"]["claimed_envelope"],
            "frozen_at_utc": config["frozen_at_utc"],
            "schema": config["schema"],
            "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
            "status": config["status"],
        },
        comparison_classifications=tuple(classifications),
    )


def _declared_observables(config: Mapping[str, Any]) -> set[str]:
    declared: set[str] = set()
    for criterion in config["criteria"]:
        observable = criterion["observable"]
        if isinstance(observable, str):
            declared.add(observable)
        else:
            declared.update(observable)
    return declared


def _evaluate_one(
    criterion: Mapping[str, Any],
    metrics: Mapping[str, Any],
    config: Mapping[str, Any],
    classifications: Sequence[Mapping[str, Any]],
) -> CriterionOutcome:
    kind = criterion["sample_kind"]
    try:
        if kind == "series":
            observed, samples = _from_series(criterion, metrics)
        elif kind == "paired_series":
            observed, samples = _from_paired_series(criterion, metrics)
        elif kind == "grouped_series":
            observed, samples = _from_grouped_series(criterion, metrics)
        elif kind == "counter":
            observed, samples = _from_counter(criterion, metrics)
        elif kind == "scalar":
            observed, samples = _from_scalar(criterion, metrics)
        elif kind == "comparison_set":
            observed, samples = _from_comparison_set(config, classifications)
        else:  # pragma: no cover - the frozen schema constrains sample_kind
            raise AcceptanceCriteriaError(f"unknown sample_kind {kind!r}")
    except _ObservationFailure as failure:
        return _failed_outcome(criterion, failure.status, str(failure))

    passed = _compare(observed, criterion["comparator"], float(criterion["threshold"]))
    count = len(samples) if samples is not None else None
    return CriterionOutcome(
        criterion_id=criterion["criterion_id"],
        metric=criterion["metric"],
        tier=criterion["tier"],
        gating=bool(criterion["gating"]),
        statistic=criterion["statistic"],
        comparator=criterion["comparator"],
        threshold=float(criterion["threshold"]),
        observed=observed,
        passed=passed,
        status="evaluated",
        detail=(
            f"{criterion['statistic']}={observed!r} "
            f"{criterion['comparator']} {criterion['threshold']!r}"
        ),
        sample_count=count,
        small_sample=count is not None and count < SMALL_SAMPLE_THRESHOLD,
        denominator=criterion["denominator"],
        sample_summary=_summarize(samples),
    )


class _ObservationFailure(Exception):
    """Internal signal that one criterion cannot be observed."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _failed_outcome(
    criterion: Mapping[str, Any],
    status: str,
    detail: str,
) -> CriterionOutcome:
    return CriterionOutcome(
        criterion_id=criterion["criterion_id"],
        metric=criterion["metric"],
        tier=criterion["tier"],
        gating=bool(criterion["gating"]),
        statistic=criterion["statistic"],
        comparator=criterion["comparator"],
        threshold=float(criterion["threshold"]),
        observed=None,
        passed=False,
        status=status,
        detail=detail,
        sample_count=None,
        small_sample=False,
        denominator=criterion["denominator"],
        sample_summary=None,
    )


def _require(metrics: Mapping[str, Any], name: str) -> Any:
    if name not in metrics:
        raise _ObservationFailure(
            "missing_observable", f"observable {name!r} is absent from the payload"
        )
    return metrics[name]


def _finite_series(value: Any, name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _ObservationFailure(
            "malformed_observable", f"observable {name!r}: expected a sequence"
        )
    if not value:
        raise _ObservationFailure(
            "empty_observable", f"observable {name!r}: sample is empty"
        )
    samples: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise _ObservationFailure(
                "malformed_observable",
                f"observable {name!r}: expected numbers, found {item!r}",
            )
        number = float(item)
        if not math.isfinite(number):
            raise _ObservationFailure(
                "non_finite_value",
                f"observable {name!r}: non-finite value {item!r}",
            )
        samples.append(number)
    return samples


def _check_expected_count(criterion: Mapping[str, Any], observed: int) -> None:
    denominator = criterion["denominator"]
    if not denominator:
        return
    expected = denominator.get("expected_count")
    if expected is None:
        return
    if observed != int(expected):
        raise _ObservationFailure(
            "denominator_mismatch",
            f"denominator: expected {expected} {denominator['basis']}, "
            f"found {observed}",
        )


def _from_series(
    criterion: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[float, list[float]]:
    name = criterion["observable"]
    samples = _finite_series(_require(metrics, name), name)
    _check_expected_count(criterion, len(samples))
    return _reduce(criterion["statistic"], samples), samples


def _from_paired_series(
    criterion: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[float, list[float]]:
    first_name, second_name = criterion["observable"]
    first = _finite_series(_require(metrics, first_name), first_name)
    second = _finite_series(_require(metrics, second_name), second_name)
    _check_expected_count(criterion, len(first))
    difference = float(median(first)) - float(median(second))
    statistic = criterion["statistic"]
    if statistic == "median_difference":
        observed = difference
    elif statistic == "absolute_median_difference":
        observed = abs(difference)
    else:  # pragma: no cover - the frozen schema constrains the pairing
        raise AcceptanceCriteriaError(
            f"statistic {statistic!r} is not valid for a paired series"
        )
    return observed, first + second


def _from_grouped_series(
    criterion: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[float, list[float]]:
    name = criterion["observable"]
    groups = _require(metrics, name)
    if not isinstance(groups, Mapping) or not groups:
        raise _ObservationFailure(
            "malformed_observable",
            f"observable {name!r}: expected a non-empty mapping of groups",
        )
    _check_expected_count(criterion, len(groups))
    statistic = criterion["statistic"]
    flattened: list[float] = []
    ranges: list[float] = []
    for group_id in sorted(groups):
        samples = _finite_series(groups[group_id], f"{name}[{group_id}]")
        flattened.extend(samples)
        if statistic == "max_group_range":
            ranges.append(max(samples) - min(samples))
        elif statistic == "max_group_circular_range":
            ranges.append(_circular_range(samples))
        else:  # pragma: no cover - the frozen schema constrains grouping
            raise AcceptanceCriteriaError(
                f"statistic {statistic!r} is not valid for a grouped series"
            )
    return max(ranges), flattened


def _from_counter(
    criterion: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[float, None]:
    name = criterion["observable"]
    counter = _require(metrics, name)
    if not isinstance(counter, Mapping) or set(counter) != _COUNTER_FIELDS:
        raise _ObservationFailure(
            "malformed_observable",
            f"observable {name!r}: expected fields {sorted(_COUNTER_FIELDS)}",
        )
    numerator = counter["numerator"]
    denominator = counter["denominator"]
    for label, value in (("numerator", numerator), ("denominator", denominator)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _ObservationFailure(
                "malformed_observable",
                f"observable {name!r}: {label} must be an integer, found {value!r}",
            )
    if denominator <= 0:
        raise _ObservationFailure(
            "denominator_mismatch",
            f"observable {name!r}: denominator must be positive",
        )
    if numerator < 0 or numerator > denominator:
        raise _ObservationFailure(
            "malformed_observable",
            f"observable {name!r}: numerator {numerator} outside 0..{denominator}",
        )
    _check_expected_count(criterion, denominator)
    return numerator / denominator, None


def _from_scalar(
    criterion: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[float, None]:
    name = criterion["observable"]
    if criterion["statistic"] != "identity":  # pragma: no cover - schema pairs these
        raise AcceptanceCriteriaError(
            f"statistic {criterion['statistic']!r} is not valid for a scalar"
        )
    value = _require(metrics, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ObservationFailure(
            "malformed_observable", f"observable {name!r}: expected a number"
        )
    number = float(value)
    if not math.isfinite(number):
        raise _ObservationFailure(
            "non_finite_value", f"observable {name!r}: non-finite value {value!r}"
        )
    return number, None


def _from_comparison_set(
    config: Mapping[str, Any],
    classifications: Sequence[Mapping[str, Any]],
) -> tuple[float, None]:
    if not classifications:
        raise _ObservationFailure(
            "missing_observable",
            "observable 'sim_vs_real_comparisons' is absent from the payload",
        )
    gating = set(config["sim_vs_real"]["gating_metric_ids"])
    worsened = [
        record
        for record in classifications
        if record["metric"] in gating and record["classification"] == "worsens"
    ]
    return float(len(worsened)), None


def _classify_comparisons(
    config: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records = metrics.get("sim_vs_real_comparisons")
    if records is None:
        return []
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise AcceptanceCriteriaError(
            "sim_vs_real_comparisons: expected a sequence of comparison records"
        )
    bands = config["sim_vs_real"]["preserve_bands"]
    classified: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != _COMPARISON_FIELDS:
            raise AcceptanceCriteriaError(
                f"sim_vs_real_comparisons[{index}]: expected exactly the fields "
                f"{sorted(_COMPARISON_FIELDS)}"
            )
        band_key = record["band_key"]
        if band_key not in bands:
            raise AcceptanceCriteriaError(
                f"sim_vs_real_comparisons[{index}]: unknown band_key {band_key!r}"
            )
        lower_is_better = record["lower_is_better"]
        if not isinstance(lower_is_better, bool):
            raise AcceptanceCriteriaError(
                f"sim_vs_real_comparisons[{index}]: lower_is_better must be boolean"
            )
        values: dict[str, float] = {}
        for field in ("real", "unadjusted_simulation", "adjusted_simulation"):
            value = record[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AcceptanceCriteriaError(
                    f"sim_vs_real_comparisons[{index}]: {field} must be a number"
                )
            number = float(value)
            if not math.isfinite(number):
                raise AcceptanceCriteriaError(
                    f"sim_vs_real_comparisons[{index}]: {field} must be finite"
                )
            values[field] = number
        raw_change = values["adjusted_simulation"] - values["unadjusted_simulation"]
        signed_change = raw_change if lower_is_better else -raw_change
        band = float(bands[band_key])
        if abs(raw_change) <= band:
            classification = "preserves"
        elif signed_change < 0.0:
            classification = "improves"
        else:
            classification = "worsens"
        classified.append(
            {
                "adjusted_simulation": values["adjusted_simulation"],
                "band": band,
                "band_key": band_key,
                "classification": classification,
                "condition_id": record["condition_id"],
                "lower_is_better": lower_is_better,
                "metric": record["metric"],
                "raw_change": raw_change,
                "real": values["real"],
                "signed_change": signed_change,
                "unadjusted_simulation": values["unadjusted_simulation"],
            }
        )
    classified.sort(key=lambda item: (item["metric"], item["condition_id"]))
    return classified


def _reduce(statistic: str, samples: Sequence[float]) -> float:
    if statistic == "median":
        return float(median(samples))
    if statistic == "p95_nearest_rank":
        return _nearest_rank(samples, 0.95)
    if statistic == "worst":
        return float(max(samples))
    if statistic == "range":
        return float(max(samples) - min(samples))
    raise AcceptanceCriteriaError(  # pragma: no cover - schema constrains this
        f"statistic {statistic!r} is not valid for a series"
    )


def _nearest_rank(samples: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in samples)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _circular_range(samples: Sequence[float]) -> float:
    normalized = sorted(float(value) % 360.0 for value in samples)
    if len(normalized) == 1:
        return 0.0
    gaps = [
        later - earlier
        for earlier, later in zip(normalized, normalized[1:], strict=False)
    ]
    gaps.append(normalized[0] + 360.0 - normalized[-1])
    return 360.0 - max(gaps)


def _summarize(samples: Sequence[float] | None) -> dict[str, Any] | None:
    if samples is None:
        return None
    return {
        "count": len(samples),
        "median": float(median(samples)),
        "p95_nearest_rank": _nearest_rank(samples, 0.95),
        "worst": float(max(samples)),
    }


def _compare(observed: float, comparator: str, threshold: float) -> bool:
    if comparator == "less_than_or_equal":
        return observed <= threshold
    if comparator == "greater_than_or_equal":
        return observed >= threshold
    if comparator == "equal":
        return observed == threshold
    raise AcceptanceCriteriaError(  # pragma: no cover - schema constrains this
        f"unknown comparator {comparator!r}"
    )


def _resolve_repo_file(repo_root: Path, relative: Path) -> Path:
    if relative.is_absolute():
        raise AcceptanceCriteriaError(f"path must be repository relative: {relative}")
    root = repo_root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise AcceptanceCriteriaError(f"path escapes the repository: {relative}")
    if not candidate.is_file():
        raise AcceptanceCriteriaError(f"missing repository file: {relative}")
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AcceptanceCriteriaError(f"{path.name}: invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise AcceptanceCriteriaError(f"{path.name}: expected a JSON object")
    return payload


def _validate_json_schema(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    label: str,
) -> None:
    import jsonschema

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as error:
        raise AcceptanceCriteriaError(
            f"{label}: schema validation failed: {error.message}"
        ) from error
