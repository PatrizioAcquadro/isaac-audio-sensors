from __future__ import annotations

import copy
from pathlib import Path

import pytest

from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
    CorrectiveAcceptanceError,
    build_identity_registry,
    build_synthetic_payload,
    evaluate_corrective,
    load_corrective_config,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def payload() -> dict[str, object]:
    return build_synthetic_payload(ROOT)


def _take(
    payload: dict[str, object], take_id: str
) -> dict[str, object]:
    return next(
        item
        for item in payload["takes"]
        if item["identity"]["planned_take_id"] == take_id
    )


def _comparison(
    payload: dict[str, object], comparison_id: str
) -> dict[str, object]:
    return next(
        item
        for item in payload["sim_vs_real"]
        if item["comparison_id"] == comparison_id
    )


def test_identity_registry_projects_all_tracked_technical_takes() -> None:
    config = load_corrective_config(ROOT)
    registry = build_identity_registry(ROOT, config)
    assert len(registry) == 47
    assert len({item.group_id for item in registry.values()}) == 15
    assert sum(
        item.stratum_id == "A_controlled_boundary_sweep"
        for item in registry.values()
    ) == 24
    assert all(
        item.paired_counterpart_take_id is not None
        for item in registry.values()
        if item.stratum_id in {"B_center_nominal_level", "C_center_low_level"}
    )


def test_complete_synthetic_payload_passes_all_readiness_criteria(
    payload: dict[str, object],
) -> None:
    result = evaluate_corrective(payload, repo_root=ROOT)
    report = result.report()
    assert result.readiness_passed is True
    assert report["status"] == "passed"
    assert len(report["criteria"]) == 29
    assert report["identity_summary"] == {
        "take_count": 47,
        "take_ids_sha256": report["identity_summary"]["take_ids_sha256"],
        "stratum_counts": {
            "A_controlled_boundary_sweep": 24,
            "B_center_nominal_level": 8,
            "C_center_low_level": 8,
            "D_silence": 3,
            "E_impact_audio_video": 4,
        },
        "group_count": 15,
        "raw_channel_record_count": 188,
        "tdoa_record_count": 144,
        "window_source_count": 7353,
        "comparison_record_count": 7,
    }
    assert report["holdout_observations_accessed_by_evaluator"] == 0


def test_only_one_of_seven_sim_real_comparisons_fails(
    payload: dict[str, object],
) -> None:
    payload["sim_vs_real"] = payload["sim_vs_real"][:1]
    with pytest.raises(CorrectiveAcceptanceError, match="registry mismatch"):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    "field,value", [("lower_is_better", False), ("band_key", "tdoa_us")]
)
def test_payload_cannot_flip_direction_or_select_another_band(
    payload: dict[str, object], field: str, value: object
) -> None:
    _comparison(payload, "bearing_doa_error_ab")[field] = value
    with pytest.raises(CorrectiveAcceptanceError, match="fields must be exactly"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_one_repetition_cannot_replace_three_in_bearing_group(
    payload: dict[str, object],
) -> None:
    a_takes = [
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == "A_controlled_boundary_sweep"
        and item["identity"]["bearing_cell_id"].endswith("22.5")
    ]
    a_takes[1]["identity"] = copy.deepcopy(a_takes[0]["identity"])
    with pytest.raises(
        CorrectiveAcceptanceError, match="duplicate take identity|mismatch"
    ):
        evaluate_corrective(payload, repo_root=ROOT)


def test_one_repetition_cannot_replace_three_in_tdoa_group(
    payload: dict[str, object],
) -> None:
    take = next(
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == "A_controlled_boundary_sweep"
    )
    take["tdoa"][1] = copy.deepcopy(take["tdoa"][0])
    with pytest.raises(CorrectiveAcceptanceError, match="duplicate TDOA pair"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_one_real_counterpart_cannot_replace_32(
    payload: dict[str, object],
) -> None:
    comparison = _comparison(payload, "bearing_doa_error_ab")
    comparison["conditions"] = [comparison["conditions"][0]]
    with pytest.raises(CorrectiveAcceptanceError, match="condition identity mismatch"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_one_window_cannot_represent_an_abstention_stratum(
    payload: dict[str, object],
) -> None:
    take = next(
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == "D_silence"
    )
    take["window_summary"] = {
        "source_window_count": 1,
        "abstained_window_count": 1,
        "sub_floor_direction_emission_count": 0,
    }
    with pytest.raises(CorrectiveAcceptanceError, match="window coverage mismatch"):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["takes"].pop(),
            "exact take set mismatch",
        ),
        (
            lambda value: value["takes"].append(copy.deepcopy(value["takes"][0])),
            "duplicate take identity",
        ),
        (
            lambda value: value["takes"][0]["identity"].__setitem__(
                "planned_take_id", "unknown_take"
            ),
            "unknown take identity",
        ),
        (
            lambda value: value["takes"][0]["identity"].__setitem__(
                "stratum_id", "A_controlled_boundary_sweep"
            ),
            "take identity mismatch",
        ),
        (
            lambda value: value["takes"][0]["identity"].__setitem__(
                "group_id", "wrong_group"
            ),
            "take identity mismatch",
        ),
        (
            lambda value: value["takes"][1]["identity"].__setitem__(
                "bearing_cell_id", "A_controlled_boundary_sweep|67.5"
            ),
            "take identity mismatch",
        ),
        (
            lambda value: value["takes"][26]["identity"].__setitem__(
                "paired_counterpart_take_id",
                value["takes"][28]["identity"]["planned_take_id"],
            ),
            "take identity mismatch",
        ),
    ],
)
def test_take_condition_group_and_pair_identity_fail_closed(
    payload: dict[str, object], mutation, message: str
) -> None:
    mutation(payload)
    with pytest.raises(CorrectiveAcceptanceError, match=message):
        evaluate_corrective(payload, repo_root=ROOT)


def test_duplicate_and_unknown_comparison_conditions_fail(
    payload: dict[str, object],
) -> None:
    duplicate = copy.deepcopy(payload)
    conditions = _comparison(duplicate, "bearing_doa_error_ab")["conditions"]
    conditions[1] = copy.deepcopy(conditions[0])
    with pytest.raises(CorrectiveAcceptanceError, match="duplicate condition"):
        evaluate_corrective(duplicate, repo_root=ROOT)

    unknown = copy.deepcopy(payload)
    conditions = _comparison(unknown, "bearing_doa_error_ab")["conditions"]
    conditions[0]["condition_id"] = "unknown_condition"
    with pytest.raises(
        CorrectiveAcceptanceError,
        match="condition identity mismatch|unknown take condition",
    ):
        evaluate_corrective(unknown, repo_root=ROOT)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("bearing_absolute_error_deg", -1.0),
            "bearing_absolute_error_deg must be >=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["latency"].__setitem__("frame_to_adapter_round_trip_ms", -1.0),
            "frame_to_adapter_round_trip_ms must be >=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_044_av"
            ).__setitem__("av_absolute_residual_ms", -1.0),
            "av_absolute_residual_ms must be >=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["channels"][0].__setitem__("maximum_clip_run_samples", -1),
            "maximum_clip_run_samples must be >=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["window_summary"].__setitem__("source_window_count", -1),
            "source_window_count must be >=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("estimated_bearing_deg_f_project", 360.0),
            "estimated_bearing_deg_f_project must be <",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_027_conf"
            ).__setitem__("confidence", 1.1),
            "confidence must be <=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["tdoa"][0].__setitem__("tdoa_us", 273.0),
            "tdoa_us must be <=",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["tdoa"][0].__setitem__("absolute_error_us", -0.1),
            "absolute_error_us must be >=",
        ),
    ],
)
def test_physical_domains_reject_impossible_values(
    payload: dict[str, object], mutate, message: str
) -> None:
    mutate(payload)
    with pytest.raises(CorrectiveAcceptanceError, match=message):
        evaluate_corrective(payload, repo_root=ROOT)


def test_integer_counts_reject_boolean_and_fraction(
    payload: dict[str, object],
) -> None:
    boolean = copy.deepcopy(payload)
    take = _take(boolean, "s44a03_prospective_holdout_001_sil")
    take["window_summary"]["source_window_count"] = True
    with pytest.raises(CorrectiveAcceptanceError, match="must be an integer"):
        evaluate_corrective(boolean, repo_root=ROOT)

    fraction = copy.deepcopy(payload)
    take = _take(fraction, "s44a03_prospective_holdout_002_ctl")
    take["channels"][0]["maximum_clip_run_samples"] = 1.5
    with pytest.raises(CorrectiveAcceptanceError, match="must be an integer"):
        evaluate_corrective(fraction, repo_root=ROOT)


def test_unfavorable_comparison_cannot_be_removed(
    payload: dict[str, object],
) -> None:
    comparison = _comparison(payload, "tdoa_a")
    for condition in comparison["conditions"]:
        condition["adjusted_simulation"] = 100.0
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert result.readiness_passed is False
    outcome = next(
        item
        for item in result.outcomes
        if item.criterion_id == "sim_adjustment_worsened_gating_metric_count"
    )
    assert outcome.observed == 1.0
    assert outcome.passed is False


def test_b_and_c_pair_sets_are_identity_complete(
    payload: dict[str, object],
) -> None:
    b_take = _take(payload, "s44a03_prospective_holdout_027_conf")
    c_take = _take(payload, b_take["identity"]["paired_counterpart_take_id"])
    assert c_take["identity"]["paired_counterpart_take_id"] == b_take["identity"][
        "planned_take_id"
    ]
    assert b_take["identity"]["bearing_cell_id"].endswith("45.0")
    assert c_take["identity"]["bearing_cell_id"].endswith("45.0")


def test_maximum_clip_run_is_a_maximum_not_a_total(
    payload: dict[str, object],
) -> None:
    for take in payload["takes"]:
        for channel in take["channels"]:
            channel["maximum_clip_run_samples"] = 1
    result = evaluate_corrective(payload, repo_root=ROOT)
    outcome = next(
        item
        for item in result.outcomes
        if item.criterion_id == "maximum_clip_run_samples"
    )
    assert outcome.observed == 1.0
    assert outcome.sample_count == 188


def test_latency_is_exactly_one_summary_per_47_takes(
    payload: dict[str, object],
) -> None:
    result = evaluate_corrective(payload, repo_root=ROOT)
    latency = [
        item
        for item in result.outcomes
        if item.metric in {"frame_to_adapter_latency", "capture_to_frame_latency"}
    ]
    assert len(latency) == 2
    assert all(item.sample_count == 47 for item in latency)


def test_real_series_cannot_override_keyed_four_degree_bearing_errors(
    payload: dict[str, object],
) -> None:
    take_errors = [
        item["bearing_absolute_error_deg"]
        for item in payload["takes"]
        if item["identity"]["stratum_id"]
        in {"A_controlled_boundary_sweep", "B_center_nominal_level"}
    ]
    assert take_errors == [4.0] * 32
    comparison = _comparison(payload, "bearing_doa_error_ab")
    for condition in comparison["conditions"]:
        condition["real"] = 100.0
    with pytest.raises(CorrectiveAcceptanceError, match="fields must be exactly"):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    "comparison_id",
    [
        "bearing_doa_error_ab",
        "sector_accuracy_b",
        "candidate_bearing_ab",
        "tdoa_a",
        "abstention_abd",
        "confidence_bc",
        "coarse_audio_video_association_e",
    ],
)
def test_every_caller_supplied_real_value_is_rejected(
    payload: dict[str, object], comparison_id: str
) -> None:
    condition = _comparison(payload, comparison_id)["conditions"][0]
    condition["real"] = 0.0
    with pytest.raises(CorrectiveAcceptanceError, match="fields must be exactly"):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("estimated_bearing_deg_f_project", 40.0),
            "bearing_absolute_error_deg contradicts",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("bearing_absolute_error_deg", 5.0),
            "bearing_absolute_error_deg contradicts",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_027_conf"
            )["identity"].__setitem__("target_bearing_deg_f_project", 90.0),
            "take identity mismatch",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_027_conf"
            ).__setitem__("sector_correct", False),
            "sector_correct contradicts",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("candidate_covered", False),
            "candidate_covered contradicts",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            ).__setitem__("failed", True),
            "failed contradicts failure_reasons",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_002_ctl"
            )["tdoa"][0].__setitem__("absolute_error_us", 6.0),
            "absolute_error_us contradicts",
        ),
        (
            lambda value: _take(
                value, "s44a03_prospective_holdout_044_av"
            ).__setitem__("av_absolute_residual_ms", 21.0),
            "av_absolute_residual_ms contradicts",
        ),
    ],
)
def test_reported_and_source_observations_cannot_contradict(
    payload: dict[str, object], mutation, message: str
) -> None:
    mutation(payload)
    with pytest.raises(CorrectiveAcceptanceError, match=message):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    "comparison_id", ["sector_accuracy_b", "candidate_bearing_ab"]
)
def test_binary_sim_real_condition_values_reject_fraction(
    payload: dict[str, object], comparison_id: str
) -> None:
    condition = _comparison(payload, comparison_id)["conditions"][0]
    condition["adjusted_simulation"] = 0.5
    with pytest.raises(CorrectiveAcceptanceError, match="exactly 0 or 1"):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    ("maximum_run", "reported_sustained"),
    [(9, True), (3999, True), (4000, False)],
)
def test_sustained_clipping_classification_fails_closed(
    payload: dict[str, object],
    maximum_run: int,
    reported_sustained: bool,
) -> None:
    channel = payload["takes"][0]["channels"][0]
    channel["maximum_clip_run_samples"] = maximum_run
    channel["sustained_clipping"] = reported_sustained
    with pytest.raises(
        CorrectiveAcceptanceError,
        match="sustained_clipping contradicts",
    ):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    ("maximum_run", "sustained", "expected_sustained_takes"),
    [(9, False, 0.0), (3999, False, 0.0), (4000, True, 1.0)],
)
def test_sustained_clipping_boundary_is_exact(
    payload: dict[str, object],
    maximum_run: int,
    sustained: bool,
    expected_sustained_takes: float,
) -> None:
    channel = payload["takes"][0]["channels"][0]
    channel["maximum_clip_run_samples"] = maximum_run
    channel["sustained_clipping"] = sustained
    result = evaluate_corrective(payload, repo_root=ROOT)
    clipping = next(
        item
        for item in result.outcomes
        if item.criterion_id == "sustained_clipping_take_count"
    )
    maximum = next(
        item
        for item in result.outcomes
        if item.criterion_id == "maximum_clip_run_samples"
    )
    assert clipping.observed == expected_sustained_takes
    assert clipping.sample_count == 47
    assert maximum.observed == float(maximum_run)
    assert maximum.sample_count == 188
