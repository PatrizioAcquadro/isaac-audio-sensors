"""Scientific, clipping, semantic, and adversarial S4.5 corrective tests."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from isaac_audio_sensors.acquisition.s4_5 import (
    FitEvidenceAccessor,
    load_json,
    pretty_json,
)
from isaac_audio_sensors.acquisition.s4_5_corrective import (
    CORRECTIVE_CONFIG,
    CORRECTIVE_FRAME_AMENDMENT,
    CORRECTIVE_LOCATION_AMENDMENT,
    CORRECTIVE_OUTPUT,
    HYPOTHESIS_IDS,
    PACKAGE_COMMIT,
    SELECTED_HYPOTHESIS,
    _bearing_report,
    _extract_corrective_observations,
    _parameter_decisions,
    _synthetic_report,
    endpoint_clipping_counts,
    load_corrective_contract,
    load_package_location_amendment,
    load_profile_frame_amendment,
    refresh_package_integrity,
    validate_corrective_package,
)

ROOT = Path(__file__).resolve().parents[1]
MACHINE_FIT_A = (
    ROOT / "dataset/S4.4/amendments/s4_4_data_expansion_amendment_02/attempts"
)
CANONICAL = ROOT / CORRECTIVE_OUTPUT


def _accessor() -> FitEvidenceAccessor:
    if not MACHINE_FIT_A.is_dir():
        pytest.skip("machine-local sealed Fit A evidence is unavailable")
    return FitEvidenceAccessor(ROOT)


def _canonical_package() -> Path:
    if not (CANONICAL / "evidence_index.json").is_file():
        pytest.skip("canonical corrective evidence has not been generated")
    return CANONICAL


@pytest.fixture(scope="module")
def corrective_analysis() -> dict[str, Any]:
    """Compute the immutable 102-WAV corrective analysis once per test module."""

    accessor = _accessor()
    inventory, records = accessor.inventory(purpose="S4.5_validation")
    measurements, observations, clipping, group_rows = (
        _extract_corrective_observations(accessor, records)
    )
    comparison = _bearing_report(group_rows)
    corrective = load_corrective_contract(ROOT / CORRECTIVE_CONFIG, ROOT)
    decisions = _parameter_decisions(
        observations,
        records,
        accessor.contract,
        corrective,
        comparison,
        group_rows,
        _synthetic_report(accessor.contract),
    )
    return {
        "inventory": inventory,
        "measurements": measurements,
        "observations": observations,
        "clipping": clipping,
        "group_rows": group_rows,
        "comparison": comparison,
        "decisions": decisions,
    }


def test_corrective_contract_freezes_physical_hypotheses_and_fit_roles() -> None:
    contract = load_corrective_contract(ROOT / CORRECTIVE_CONFIG, ROOT)
    assert tuple(item["id"] for item in contract["bearing_binding"]["hypotheses"]) == (
        HYPOTHESIS_IDS
    )
    assert contract["bearing_binding"]["selected_hypothesis_id"] == SELECTED_HYPOTHESIS
    assert contract["bearing_binding"]["fit_a_selection_only"] is True
    assert contract["phase_boundary"]["fit_a_role"].startswith("development")
    assert contract["phase_boundary"]["fit_b_role"] == "locked validation only"
    assert contract["phase_boundary"]["holdout_access_forbidden"] is True
    amendment = load_profile_frame_amendment(ROOT)
    assert amendment["profile_array_frame"] == "xvf3800_array_corrective_01"
    assert amendment["profile_source_frame"] == "F_project"
    assert amendment["scientific_binding_changed"] is False
    assert (ROOT / CORRECTIVE_FRAME_AMENDMENT).is_file()
    location = load_package_location_amendment(ROOT)
    assert location["package_root"] == CORRECTIVE_OUTPUT.as_posix()
    assert location["scientific_binding_changed"] is False
    assert (ROOT / CORRECTIVE_LOCATION_AMENDMENT).is_file()


def test_pcm16_endpoint_clipping_excludes_only_exact_endpoints() -> None:
    clipped = np.zeros((4, 8), dtype=np.float64)
    clipped[0, 0] = -1.0
    clipped[3, 7] = 32767.0 / 32768.0
    assert endpoint_clipping_counts(clipped) == {
        "negative_full_scale_sample_count": 1,
        "positive_full_scale_sample_count": 1,
        "clipped_sample_count": 2,
    }
    retained = np.zeros((4, 8), dtype=np.float64)
    retained[0, 0] = -32767.0 / 32768.0
    retained[3, 7] = 32766.0 / 32768.0
    assert endpoint_clipping_counts(retained)["clipped_sample_count"] == 0


def test_corrected_extraction_counts_clipping_and_groups(
    corrective_analysis: dict[str, Any],
) -> None:
    inventory = corrective_analysis["inventory"]
    measurements = corrective_analysis["measurements"]
    observations = corrective_analysis["observations"]
    clipping = corrective_analysis["clipping"]
    group_rows = corrective_analysis["group_rows"]
    assert inventory["session_counts"] == {"fit_a": 51, "fit_b": 51}
    assert measurements["authorized_valid_cell_count"] == 102
    assert measurements["eligible_attempt_measurement_count"] == 85
    assert measurements["scientific_leakage_group_count"] == 32
    assert measurements["session_group_counts"] == {"fit_a": 16, "fit_b": 16}
    assert clipping["clipping_excluded_attempt_count"] == 0
    assert len(observations) == len(group_rows) == 32
    assert measurements["holdout_observations"] == 0


def test_fit_a_selects_binding_and_fit_b_only_validates_it(
    corrective_analysis: dict[str, Any],
) -> None:
    report = corrective_analysis["comparison"]
    assert report["hypothesis_selection_partition"] == "fit_a"
    assert report["fit_b_used_for_selection"] is False
    assert report["selected_hypothesis_id"] == SELECTED_HYPOTHESIS
    summaries = {
        item["hypothesis_id"]: item["splits"]["fit_a"] for item in report["hypotheses"]
    }
    assert summaries[HYPOTHESIS_IDS[0]]["median_angular_error_deg"] == 81.5
    assert summaries[HYPOTHESIS_IDS[1]]["median_angular_error_deg"] == 98.5
    assert summaries[HYPOTHESIS_IDS[2]]["median_angular_error_deg"] == pytest.approx(
        5.5
    )
    assert summaries[HYPOTHESIS_IDS[3]]["median_angular_error_deg"] == 174.5
    assert summaries[HYPOTHESIS_IDS[2]]["nearest_rank_p95_angular_error_deg"] == 15.0


def test_bearing_retention_requires_uncertainty_and_leave_one_group_stability(
    corrective_analysis: dict[str, Any],
) -> None:
    decisions = corrective_analysis["decisions"]
    binding = next(
        item
        for item in decisions["decisions"]
        if item["candidate"] == "channel_position_binding"
    )
    assert binding["retained"] is True
    assert binding["checks"]["grouped_bootstrap_uncertainty"] is True
    assert binding["checks"]["leave_one_group_stability"] is True
    assert binding["fit_a_bootstrap_95_half_width_deg"] <= 7.5
    assert binding["fit_b_bootstrap_95_half_width_deg"] <= 7.5
    assert binding["fit_a_leave_one_group_max_shift_deg"] <= 5.0
    assert binding["fit_b_leave_one_group_max_shift_deg"] <= 5.0


def test_synthetic_report_is_truthful_about_confidence_and_phat_gain() -> None:
    report = _synthetic_report(_accessor().contract)
    assert report["status"] == "passed"
    assert report["confidence_calibration_recovered"] is False
    confidence = report["non_calibration_smoke_tests"]["confidence_ordering"]
    assert confidence["claim_type"] == "ordering_smoke_only_not_calibration_recovery"
    omission = report["omission_gate_testing"][
        "confidence_insufficient_outcome_diversity"
    ]
    assert omission["retained"] is False
    assert omission["incorrect_or_abstained_count"] == 0
    phat = report["non_calibration_smoke_tests"]["phat_positive_scalar_gain_invariance"]
    assert phat["status"] == "passed"
    assert "do not improve" in phat["claim"]


def test_profile_uses_semantically_correct_counts_and_binding() -> None:
    profile = load_json(_canonical_package() / "calibration_profile.v2.json")
    metrics = {item["name"]: item for item in profile["fit_metrics"]}
    assert "fit_observation_count" not in metrics
    assert metrics["authorized_fit_cell_count"] == {
        "name": "authorized_fit_cell_count",
        "unit": "cell",
        "value": 102.0,
    }
    assert metrics["eligible_attempt_measurement_count"]["value"] == 85.0
    assert metrics["scientific_leakage_group_count"]["value"] == 32.0
    assert metrics["fit_a_scientific_leakage_group_count"]["value"] == 16.0
    assert metrics["fit_b_scientific_leakage_group_count"]["value"] == 16.0
    assert profile["array_frame"] == "xvf3800_array_corrective_01"
    assert profile["source_frame"] == "F_project"
    assert [item["position_m"] for item in profile["microphone_geometry"]] == [
        [-0.033, -0.033, 0.0],
        [-0.033, 0.033, 0.0],
        [0.033, 0.033, 0.0],
        [0.033, -0.033, 0.0],
    ]


def test_semantic_validator_accepts_canonical_package(
    pre_s4_6_root: Path,
) -> None:
    result = validate_corrective_package(pre_s4_6_root, _canonical_package())
    assert result["status"] == "passed", result
    assert result["semantic_regeneration"] is True
    assert result["semantic_regenerated_file_count"] == 12
    assert result["historical_metadata_file_count"] == 5
    assert result["holdout_opened"] is False
    assert result["later_phase_artifacts"] == []


def _decision(
    payload: dict[str, Any], candidate: str, channel_id: str | None = None
) -> dict[str, Any]:
    return next(
        item
        for item in payload["decisions"]
        if item["candidate"] == candidate and item.get("channel_id") == channel_id
    )


def _mutate_gain(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    _decision(payload, "relative_gain", "ch1")["estimate"] = 99.0
    path.write_text(pretty_json(payload), encoding="utf-8")


def _mutate_improvement(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    row = _decision(payload, "relative_gain", "ch1")
    row["fitted_median_absolute_residual"] = 0.0001
    row["residual_improvement_fraction"] = 0.9999
    path.write_text(pretty_json(payload), encoding="utf-8")


def _mutate_count(package: Path) -> None:
    path = package / "authorized_input_census.json"
    payload = load_json(path)
    payload["eligible_attempt_measurement_count"] = 86
    path.write_text(pretty_json(payload), encoding="utf-8")


def _mutate_decision(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    _decision(payload, "relative_delay", "ch1")["retained"] = True
    path.write_text(pretty_json(payload), encoding="utf-8")


def _remove_bearing_uncertainty(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    row = _decision(payload, "channel_position_binding")
    del row["fit_a_bootstrap_95_half_width_deg"]
    path.write_text(pretty_json(payload), encoding="utf-8")


def _fail_bearing_leave_one_group(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    row = _decision(payload, "channel_position_binding")
    row["fit_a_leave_one_group_max_shift_deg"] = 99.0
    row["checks"]["leave_one_group_stability"] = False
    path.write_text(pretty_json(payload), encoding="utf-8")


def _mutate_binding(package: Path) -> None:
    path = package / "physical_hypothesis_comparison.json"
    payload = load_json(path)
    payload["selected_binding"]["ch0"] = [0.033, -0.033, 0.0]
    path.write_text(pretty_json(payload), encoding="utf-8")


def _support_unsupported_candidate(package: Path) -> None:
    path = package / "parameter_decisions.json"
    payload = load_json(path)
    row = _decision(payload, "confidence_calibration")
    row["retained"] = True
    row["reason"] = "supported"
    path.write_text(pretty_json(payload), encoding="utf-8")


def _mutate_source_commit(package: Path) -> None:
    path = package / "provenance.json"
    payload = load_json(path)
    payload["source_commit"] = PACKAGE_COMMIT
    path.write_text(pretty_json(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "mutator",
    (
        _mutate_gain,
        _mutate_improvement,
        _mutate_count,
        _mutate_decision,
        _remove_bearing_uncertainty,
        _fail_bearing_leave_one_group,
        _mutate_binding,
        _support_unsupported_candidate,
        _mutate_source_commit,
    ),
    ids=(
        "gain_plus_99_db",
        "false_residual_improvement",
        "observation_count",
        "retained_omitted_state",
        "missing_bearing_uncertainty",
        "failing_bearing_leave_one_group",
        "selected_mapping",
        "unsupported_promoted",
        "source_commit_binding",
    ),
)
def test_semantic_validator_rejects_rechecksummed_scientific_tampering(
    tmp_path: Path,
    mutator: Callable[[Path], None],
    pre_s4_6_root: Path,
) -> None:
    package = tmp_path / "package"
    shutil.copytree(_canonical_package(), package)
    mutator(package)
    refresh_package_integrity(package)
    result = validate_corrective_package(pre_s4_6_root, package)
    assert result["status"] == "failed"
    assert not any("checksum mismatch" in issue for issue in result["issues"])
    assert any("semantic regeneration" in issue for issue in result["issues"])
