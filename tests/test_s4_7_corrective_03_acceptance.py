from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from statistics import median

import pytest

from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    CorrectiveAcceptanceError,
    _circular_absolute_difference,
    _majority_sector,
    _window_record,
    build_synthetic_payload,
    evaluate_corrective,
)
from isaac_audio_sensors.core.doa.sector_mapping import (
    bearing_deg_to_sector_name,
)

ROOT = Path(__file__).resolve().parents[1]
OFFSETS = (-45.0, -35.0, -25.0, -5.0, 5.0, 55.0, 65.0)


@pytest.fixture
def payload() -> dict[str, object]:
    return build_synthetic_payload(ROOT)


def _takes(
    payload: dict[str, object], stratum: str
) -> list[dict[str, object]]:
    return [
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == stratum
    ]


def _take(payload: dict[str, object], stratum: str) -> dict[str, object]:
    return _takes(payload, stratum)[0]


def _set_windows(
    take: dict[str, object],
    bearings: Sequence[float | None],
    *,
    reported_error: float | None,
    reported_bearing: float | None,
    reported_sector: bool | None = None,
) -> None:
    windows = [
        _window_record(index, bearing, abstained=bearing is None)
        for index, bearing in enumerate(bearings)
    ]
    take["bearing_windows"] = windows
    take["window_summary"] = {
        "source_window_count": len(windows),
        "abstained_window_count": sum(value is None for value in bearings),
        "sub_floor_direction_emission_count": 0,
    }
    take["bearing_absolute_error_deg"] = reported_error
    take["estimated_bearing_deg_f_project"] = reported_bearing
    if take["identity"]["stratum_id"] == "B_center_nominal_level":
        take["sector_correct"] = reported_sector


def _repeat_to_count(values: Sequence[float], count: int) -> list[float]:
    return [values[index % len(values)] for index in range(count)]


def _criterion(result, criterion_id: str):
    return next(
        item for item in result.outcomes if item.criterion_id == criterion_id
    )


@pytest.mark.parametrize("target", [45.0, 90.0, 135.0, 180.0])
def test_required_seven_bearing_pattern_has_the_adversarial_properties(
    target: float,
) -> None:
    bearings = _repeat_to_count(
        [target + offset for offset in OFFSETS], 159
    )
    representative = float(median(bearings))
    errors = [
        _circular_absolute_difference(target, bearing) for bearing in bearings
    ]
    assert representative == target - 5.0
    assert float(median(errors)) == 35.0
    assert bearing_deg_to_sector_name(representative) == (
        bearing_deg_to_sector_name(target)
    )
    assert _majority_sector(bearings) != bearing_deg_to_sector_name(target)


def test_conforming_exact_window_payload_passes_deterministically(
    payload: dict[str, object],
) -> None:
    first = evaluate_corrective(payload, repo_root=ROOT)
    second = evaluate_corrective(payload, repo_root=ROOT)
    assert first.readiness_passed is True
    assert first.report() == second.report()
    assert first.config_identity["corrective_id"] == "s4_7_corrective_03"
    assert first.identity_summary["bearing_window_record_count"] == 5088


def test_semantic_bypass_regression_fails_bearing_and_sector_gates(
    payload: dict[str, object],
) -> None:
    b_takes = _takes(payload, "B_center_nominal_level")
    affected = {
        take["identity"]["planned_take_id"]
        for take in b_takes
        if take["identity"]["target_bearing_deg_f_project"] in {45.0, 135.0}
    }
    wrong_per_take_errors = []
    wrong_sector_results = []
    for take in b_takes:
        target = float(take["identity"]["target_bearing_deg_f_project"])
        take_id = take["identity"]["planned_take_id"]
        if take_id not in affected:
            wrong_per_take_errors.append(4.0)
            wrong_sector_results.append(True)
            continue
        count = len(take["bearing_windows"])
        bearings = _repeat_to_count(
            [(target + offset) % 360.0 for offset in OFFSETS], count
        )
        representative = float(median(bearings))
        frozen_error = float(
            median(
                _circular_absolute_difference(target, bearing)
                for bearing in bearings
            )
        )
        majority = _majority_sector(bearings)
        assert representative == target - 5.0
        assert frozen_error == 35.0
        assert bearing_deg_to_sector_name(representative) == (
            bearing_deg_to_sector_name(target)
        )
        assert majority != bearing_deg_to_sector_name(target)
        wrong_per_take_errors.append(
            _circular_absolute_difference(target, representative)
        )
        wrong_sector_results.append(True)
        _set_windows(
            take,
            bearings,
            reported_error=None,
            reported_bearing=None,
            reported_sector=None,
        )
    assert float(median(wrong_per_take_errors)) == 4.5
    assert sum(wrong_sector_results) / 8 == 1.0

    result = evaluate_corrective(payload, repo_root=ROOT)
    bearing = _criterion(
        result, "bearing_median_absolute_error_stratum_b"
    )
    sector = _criterion(result, "sector_accuracy_stratum_b")
    assert bearing.observed == 19.5
    assert bearing.threshold == 15.0
    assert bearing.passed is False
    assert sector.observed == 0.5
    assert sector.threshold == 0.75
    assert sector.passed is False
    assert result.readiness_passed is False

    bypass = copy.deepcopy(payload)
    for take in _takes(bypass, "B_center_nominal_level"):
        if take["identity"]["planned_take_id"] in affected:
            target = float(take["identity"]["target_bearing_deg_f_project"])
            take["bearing_absolute_error_deg"] = 5.0
            take["estimated_bearing_deg_f_project"] = target - 5.0
            take["sector_correct"] = True
    with pytest.raises(
        CorrectiveAcceptanceError,
        match="bearing_absolute_error_deg contradicts exact bearing windows",
    ):
        evaluate_corrective(bypass, repo_root=ROOT)


def test_median_window_error_is_not_error_of_median_bearing(
    payload: dict[str, object],
) -> None:
    take = _take(payload, "B_center_nominal_level")
    target = float(take["identity"]["target_bearing_deg_f_project"])
    bearings = _repeat_to_count(
        [(target + offset) % 360.0 for offset in OFFSETS],
        len(take["bearing_windows"]),
    )
    assert median(
        _circular_absolute_difference(target, value) for value in bearings
    ) == 35.0
    representative = float(median(bearings))
    assert _circular_absolute_difference(target, representative) == 5.0
    _set_windows(
        take,
        bearings,
        reported_error=None,
        reported_bearing=None,
        reported_sector=None,
    )
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert _criterion(result, "bearing_median_absolute_error_stratum_b").observed == 4.0


def test_majority_sector_is_not_sector_of_median_bearing(
    payload: dict[str, object],
) -> None:
    take = _take(payload, "B_center_nominal_level")
    target = float(take["identity"]["target_bearing_deg_f_project"])
    bearings = _repeat_to_count(
        [target + offset for offset in OFFSETS],
        len(take["bearing_windows"]),
    )
    assert bearing_deg_to_sector_name(float(median(bearings))) == (
        bearing_deg_to_sector_name(target)
    )
    assert _majority_sector(bearings) != bearing_deg_to_sector_name(target)
    _set_windows(
        take,
        bearings,
        reported_error=None,
        reported_bearing=None,
        reported_sector=None,
    )
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert _criterion(result, "sector_accuracy_stratum_b").observed == 0.875


def test_circular_wraparound_derives_small_window_errors(
    payload: dict[str, object],
) -> None:
    take = _take(payload, "A_controlled_boundary_sweep")
    target = float(take["identity"]["target_bearing_deg_f_project"])
    bearings = [
        (target - 1.0) % 360.0 if index % 2 == 0 else (target + 1.0) % 360.0
        for index in range(len(take["bearing_windows"]))
    ]
    _set_windows(
        take,
        bearings,
        reported_error=1.0,
        reported_bearing=float(median(bearings)),
    )
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert _criterion(
        result, "bearing_worst_absolute_error_stratum_a"
    ).observed == 4.0


def test_abstained_windows_are_excluded_and_counted(
    payload: dict[str, object],
) -> None:
    take = _take(payload, "A_controlled_boundary_sweep")
    target = float(take["identity"]["target_bearing_deg_f_project"])
    count = len(take["bearing_windows"])
    bearings = [None] * 80 + [(target + 6.0) % 360.0] * (count - 80)
    _set_windows(
        take,
        bearings,
        reported_error=6.0,
        reported_bearing=(target + 6.0) % 360.0,
    )
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert result.identity_summary["abstained_bearing_window_count"] == 80


@pytest.mark.parametrize("field", ["window_index", "window_id"])
def test_missing_or_duplicate_window_identities_fail_closed(
    payload: dict[str, object], field: str
) -> None:
    windows = _take(payload, "A_controlled_boundary_sweep")["bearing_windows"]
    if field == "window_index":
        windows[1]["window_index"] = windows[0]["window_index"]
    else:
        windows[1]["window_id"] = windows[0]["window_id"]
    with pytest.raises(CorrectiveAcceptanceError, match="window"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_missing_window_fails_closed(payload: dict[str, object]) -> None:
    _take(payload, "A_controlled_boundary_sweep")["bearing_windows"].pop()
    with pytest.raises(CorrectiveAcceptanceError, match="window count mismatch"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_no_valid_bearing_window_fails_take(
    payload: dict[str, object],
) -> None:
    take = _take(payload, "B_center_nominal_level")
    _set_windows(
        take,
        [None] * len(take["bearing_windows"]),
        reported_error=None,
        reported_bearing=None,
        reported_sector=False,
    )
    with pytest.raises(CorrectiveAcceptanceError, match="no valid bearing window"):
        evaluate_corrective(payload, repo_root=ROOT)


def test_tied_sector_vote_is_incorrect(payload: dict[str, object]) -> None:
    take = _take(payload, "B_center_nominal_level")
    target = float(take["identity"]["target_bearing_deg_f_project"])
    bearings = [target] * 79 + [target + 45.0] * 79 + [target + 90.0]
    assert _majority_sector(bearings) is None
    errors = [
        _circular_absolute_difference(target, value) for value in bearings
    ]
    _set_windows(
        take,
        bearings,
        reported_error=float(median(errors)),
        reported_bearing=float(median(bearings)),
        reported_sector=False,
    )
    result = evaluate_corrective(payload, repo_root=ROOT)
    assert _criterion(result, "sector_accuracy_stratum_b").observed == 0.875


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("srp_bearing_deg_f_project", float("nan"), "must be finite"),
        ("srp_bearing_deg_f_project", 360.0, r"must be in \[0, 360\)"),
        ("start_sample", 1, "start_sample mismatch"),
    ],
)
def test_non_finite_out_of_domain_or_inconsistent_windows_fail_closed(
    payload: dict[str, object], field: str, value: object, message: str
) -> None:
    window = _take(payload, "A_controlled_boundary_sweep")["bearing_windows"][0]
    window[field] = value
    with pytest.raises(CorrectiveAcceptanceError, match=message):
        evaluate_corrective(payload, repo_root=ROOT)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "bearing_absolute_error_deg",
            5.0,
            "bearing_absolute_error_deg contradicts",
        ),
        (
            "estimated_bearing_deg_f_project",
            5.0,
            "estimated_bearing_deg_f_project contradicts",
        ),
        ("sector_correct", False, "sector_correct contradicts"),
    ],
)
def test_contradictory_reported_summaries_fail_closed(
    payload: dict[str, object], field: str, value: object, message: str
) -> None:
    take = _take(
        payload,
        (
            "B_center_nominal_level"
            if field == "sector_correct"
            else "A_controlled_boundary_sweep"
        ),
    )
    take[field] = value
    with pytest.raises(CorrectiveAcceptanceError, match=message):
        evaluate_corrective(payload, repo_root=ROOT)


def test_sim_real_uses_window_derived_error_not_reported_summary(
    payload: dict[str, object],
) -> None:
    for take in [
        *_takes(payload, "A_controlled_boundary_sweep"),
        *_takes(payload, "B_center_nominal_level"),
    ]:
        target = float(take["identity"]["target_bearing_deg_f_project"])
        bearings = [(target + 35.0) % 360.0] * len(take["bearing_windows"])
        _set_windows(
            take,
            bearings,
            reported_error=None,
            reported_bearing=None,
            reported_sector=(
                False
                if take["identity"]["stratum_id"] == "B_center_nominal_level"
                else None
            ),
        )
    result = evaluate_corrective(payload, repo_root=ROOT)
    comparison = next(
        item
        for item in result.comparisons
        if item["comparison_id"] == "bearing_doa_error_ab"
    )
    assert comparison["real"] == 35.0
    condition = next(
        item
        for item in payload["sim_vs_real"]
        if item["comparison_id"] == "bearing_doa_error_ab"
    )["conditions"][0]
    condition["real"] = 4.0
    with pytest.raises(CorrectiveAcceptanceError, match="fields must be exactly"):
        evaluate_corrective(payload, repo_root=ROOT)
