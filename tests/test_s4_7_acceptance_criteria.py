"""Fail-closed and determinism tests for the frozen S4.7 criteria evaluator."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.core.acceptance_criteria import (
    CRITERIA_CONFIG_PATH,
    CRITERIA_SCHEMA_PATH,
    AcceptanceCriteriaError,
    evaluate_criteria,
    load_criteria,
)

ROOT = Path(__file__).resolve().parents[1]
PASS_FIXTURE = ROOT / "examples/s4_7/synthetic_pass_metrics.v1.json"
FAIL_FIXTURE = ROOT / "examples/s4_7/synthetic_fail_metrics.v1.json"
HOLDOUT_ATTEMPTS = ROOT / "dataset/S4.4/amendments"


def _payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _passing() -> dict[str, Any]:
    return _payload(PASS_FIXTURE)


def _evaluate(payload: dict[str, Any]):
    return evaluate_criteria(payload, repo_root=ROOT)


def _outcome(result, criterion_id: str):
    return next(item for item in result.outcomes if item.criterion_id == criterion_id)


def _criteria_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (CRITERIA_CONFIG_PATH, CRITERIA_SCHEMA_PATH):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    return root


def test_conforming_synthetic_payload_passes_every_readiness_criterion() -> None:
    result = _evaluate(_passing())
    report = result.report()

    assert result.readiness_passed is True
    assert report["status"] == "passed"
    assert report["failed_gating_criteria"] == []
    assert report["gating_criterion_count"] == 23
    assert report["stretch_criterion_count"] == 6
    assert report["holdout_observations_accessed"] == 0


def test_stretch_tier_can_fail_without_moving_the_gate() -> None:
    result = _evaluate(_passing())
    stretch = [item for item in result.outcomes if item.tier == "stretch"]

    assert any(not item.passed for item in stretch)
    assert all(item.gating is False for item in stretch)
    assert result.readiness_passed is True


def test_violating_synthetic_payload_fails_the_gate() -> None:
    result = _evaluate(_payload(FAIL_FIXTURE))
    failed = set(result.report()["failed_gating_criteria"])

    assert result.readiness_passed is False
    assert {
        "bearing_median_absolute_error_stratum_a",
        "sector_accuracy_stratum_b",
        "raw_channel_health_failure_count",
        "silence_abstention_rate_stratum_d",
        "sub_floor_direction_emission_count",
        "low_level_confidence_monotonicity",
        "coarse_av_association_residual_stratum_e",
        "sim_adjustment_worsened_gating_metric_count",
    } <= failed


def test_evaluation_is_deterministic() -> None:
    first = _evaluate(_passing()).report()
    second = _evaluate(_passing()).report()

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_frozen_statistics_match_the_declared_conventions() -> None:
    result = _evaluate(_passing())

    assert _outcome(result, "bearing_median_absolute_error_stratum_a").observed == 7.5
    assert _outcome(result, "bearing_p95_absolute_error_stratum_a").observed == 18.0
    assert _outcome(result, "bearing_worst_absolute_error_stratum_a").observed == 22.0
    assert _outcome(result, "sector_accuracy_stratum_b").observed == 0.875
    assert _outcome(
        result, "within_cell_bearing_circular_range_stratum_a"
    ).observed == pytest.approx(8.0)


def test_circular_range_handles_the_wrapping_bearing_cell() -> None:
    payload = _passing()
    cells = payload["stratum_a_cell_take_median_bearing_deg"]
    assert any(min(values) < 10.0 < max(values) for values in cells.values())

    observed = _outcome(
        _evaluate(payload), "within_cell_bearing_circular_range_stratum_a"
    ).observed
    assert observed is not None
    assert observed < 20.0


def test_small_samples_are_labeled_without_changing_the_comparison() -> None:
    result = _evaluate(_passing())
    stratum_b = _outcome(result, "bearing_median_absolute_error_stratum_b")
    stratum_a = _outcome(result, "bearing_median_absolute_error_stratum_a")

    assert stratum_b.sample_count == 8
    assert stratum_b.small_sample is False
    assert stratum_a.sample_count == 24
    assert (
        _outcome(result, "coarse_av_association_residual_stratum_e").small_sample
        is True
    )


@pytest.mark.parametrize(
    ("case", "mutate", "criterion_id", "status"),
    (
        (
            "missing_series",
            lambda item: item.pop("stratum_b_take_median_bearing_absolute_error_deg"),
            "bearing_median_absolute_error_stratum_b",
            "missing_observable",
        ),
        (
            "non_finite_series_member",
            lambda item: item[
                "stratum_b_take_median_bearing_absolute_error_deg"
            ].__setitem__(0, float("nan")),
            "bearing_median_absolute_error_stratum_b",
            "non_finite_value",
        ),
        (
            "series_denominator_mismatch",
            lambda item: item["stratum_a_take_median_bearing_absolute_error_deg"].pop(),
            "bearing_median_absolute_error_stratum_a",
            "denominator_mismatch",
        ),
        (
            "counter_denominator_mismatch",
            lambda item: item.__setitem__(
                "stratum_b_sector_correct_take_count",
                {"numerator": 7, "denominator": 9},
            ),
            "sector_accuracy_stratum_b",
            "denominator_mismatch",
        ),
        (
            "counter_field_set_mismatch",
            lambda item: item.__setitem__(
                "stratum_b_sector_correct_take_count", {"numerator": 7}
            ),
            "sector_accuracy_stratum_b",
            "malformed_observable",
        ),
        (
            "empty_series",
            lambda item: item.__setitem__(
                "stratum_e_av_association_absolute_residual_ms", []
            ),
            "coarse_av_association_residual_stratum_e",
            "empty_observable",
        ),
        (
            "non_numeric_series_member",
            lambda item: item[
                "stratum_e_av_association_absolute_residual_ms"
            ].__setitem__(0, "18.4"),
            "coarse_av_association_residual_stratum_e",
            "malformed_observable",
        ),
        (
            "grouped_series_group_count_mismatch",
            lambda item: item["stratum_a_cell_take_median_bearing_deg"].pop(
                "cell_22.5"
            ),
            "within_cell_bearing_circular_range_stratum_a",
            "denominator_mismatch",
        ),
        (
            "grouped_series_not_a_mapping",
            lambda item: item.__setitem__(
                "stratum_a_cell_take_median_bearing_deg", [1.0, 2.0]
            ),
            "within_cell_bearing_circular_range_stratum_a",
            "malformed_observable",
        ),
        (
            "scalar_is_boolean",
            lambda item: item.__setitem__(
                "all_takes_raw_channel_health_failure_count", True
            ),
            "raw_channel_health_failure_count",
            "malformed_observable",
        ),
        (
            "missing_comparison_set",
            lambda item: item.pop("sim_vs_real_comparisons"),
            "sim_adjustment_worsened_gating_metric_count",
            "missing_observable",
        ),
    ),
)
def test_unusable_observations_fail_closed_instead_of_passing(
    case: str,
    mutate,
    criterion_id: str,
    status: str,
) -> None:
    del case
    payload = _passing()
    mutate(payload)
    result = _evaluate(payload)
    outcome = _outcome(result, criterion_id)

    assert outcome.passed is False
    assert outcome.status == status
    assert outcome.observed is None
    assert result.readiness_passed is False


@pytest.mark.parametrize(
    ("case", "mutate", "message"),
    (
        (
            "undeclared_observable",
            lambda item: item.__setitem__("invented_observable", [1.0]),
            "observables the frozen criteria do not define",
        ),
        (
            "comparison_field_set_mismatch",
            lambda item: item["sim_vs_real_comparisons"][0].pop("band_key"),
            "expected exactly the fields",
        ),
        (
            "comparison_unknown_band_key",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "band_key", "invented_band"
            ),
            "unknown band_key",
        ),
        (
            "comparison_non_boolean_direction",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "lower_is_better", "yes"
            ),
            "lower_is_better must be boolean",
        ),
        (
            "comparison_non_finite_value",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "adjusted_simulation", float("inf")
            ),
            "must be finite",
        ),
        (
            "comparison_set_not_a_sequence",
            lambda item: item.__setitem__("sim_vs_real_comparisons", {"a": 1}),
            "expected a sequence of comparison records",
        ),
    ),
)
def test_malformed_payload_structure_rejects_the_whole_evaluation(
    case: str,
    mutate,
    message: str,
) -> None:
    del case
    payload = _passing()
    mutate(payload)

    with pytest.raises(AcceptanceCriteriaError, match=message):
        _evaluate(payload)


def test_comparison_classification_uses_the_frozen_preserve_bands() -> None:
    payload = _passing()
    records = payload["sim_vs_real_comparisons"]
    bearing = next(item for item in records if item["metric"] == "bearing_doa_error")
    bearing["adjusted_simulation"] = bearing["unadjusted_simulation"] + 1.0

    result = _evaluate(payload)
    classified = next(
        item
        for item in result.comparison_classifications
        if item["metric"] == "bearing_doa_error"
    )
    assert classified["classification"] == "preserves"
    assert classified["band"] == 2.0
    assert _outcome(result, "sim_adjustment_worsened_gating_metric_count").passed


def test_an_adjustment_that_degrades_a_gating_metric_fails_the_gate() -> None:
    payload = _passing()
    bearing = next(
        item
        for item in payload["sim_vs_real_comparisons"]
        if item["metric"] == "bearing_doa_error"
    )
    bearing["adjusted_simulation"] = bearing["unadjusted_simulation"] + 6.0

    result = _evaluate(payload)
    classified = next(
        item
        for item in result.comparison_classifications
        if item["metric"] == "bearing_doa_error"
    )
    assert classified["classification"] == "worsens"
    assert (
        _outcome(result, "sim_adjustment_worsened_gating_metric_count").passed is False
    )
    assert result.readiness_passed is False


def test_higher_is_better_metrics_classify_by_their_declared_direction() -> None:
    payload = _passing()
    sector = next(
        item
        for item in payload["sim_vs_real_comparisons"]
        if item["metric"] == "sector_accuracy"
    )
    assert sector["lower_is_better"] is False
    sector["adjusted_simulation"] = sector["unadjusted_simulation"] - 0.2

    result = _evaluate(payload)
    classified = next(
        item
        for item in result.comparison_classifications
        if item["metric"] == "sector_accuracy"
    )
    assert classified["classification"] == "worsens"


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        ("status_not_frozen", lambda item: item.__setitem__("status", "draft")),
        (
            "schema_mismatch",
            lambda item: item.__setitem__("schema", "ias.s4_7.invented.v1"),
        ),
        (
            "duplicate_criterion_id",
            lambda item: item["criteria"].append(copy.deepcopy(item["criteria"][0])),
        ),
        (
            "unknown_statistic",
            lambda item: item["criteria"][0].__setitem__("statistic", "mean"),
        ),
        (
            "incomplete_metric_contract",
            lambda item: item["criteria"][0]["metric_contract"].pop("exclusions"),
        ),
        (
            "holdout_declared_open",
            lambda item: item["holdout_binding"].__setitem__(
                "scientifically_opened", True
            ),
        ),
        (
            "declares_holdout_access",
            lambda item: item["phase_boundary"].__setitem__(
                "holdout_observations_accessed", 4
            ),
        ),
        (
            "declares_opening_workflow",
            lambda item: item["authority"].__setitem__(
                "implements_holdout_opening_workflow", True
            ),
        ),
    ),
)
def test_a_tampered_criteria_configuration_is_rejected(
    tmp_path: Path,
    case: str,
    mutate,
) -> None:
    del case
    root = _criteria_root(tmp_path)
    config = json.loads((root / CRITERIA_CONFIG_PATH).read_text(encoding="utf-8"))
    mutate(config)
    (root / CRITERIA_CONFIG_PATH).write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(AcceptanceCriteriaError):
        load_criteria(repo_root=root)


@pytest.mark.parametrize(
    "config_path",
    (
        ROOT / CRITERIA_CONFIG_PATH,
        Path("../configs/s4_7_holdout_acceptance.v1.json"),
        Path("configs/s4_7_absent.v1.json"),
    ),
)
def test_unsafe_configuration_paths_are_rejected(config_path: Path) -> None:
    with pytest.raises(AcceptanceCriteriaError):
        load_criteria(repo_root=ROOT, config_path=Path(config_path))


def test_evaluator_never_opens_a_sealed_holdout_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    original_open = Path.open
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def record(path: Path) -> None:
        resolved = path.resolve()
        if HOLDOUT_ATTEMPTS.exists() and resolved.is_relative_to(HOLDOUT_ATTEMPTS):
            opened.append(resolved.as_posix())

    def guarded_open(self: Path, *args: Any, **kwargs: Any):
        record(self)
        return original_open(self, *args, **kwargs)

    def guarded_read_bytes(self: Path) -> bytes:
        record(self)
        return original_read_bytes(self)

    def guarded_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        record(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    _evaluate(_passing())
    assert opened == []


def test_frozen_configuration_declares_no_holdout_access() -> None:
    config = load_criteria(repo_root=ROOT)

    assert config["phase_boundary"]["holdout_observations_accessed"] == 0
    assert config["authority"]["opens_holdout_observations"] is False
    assert config["holdout_binding"]["scientifically_opened"] is False
