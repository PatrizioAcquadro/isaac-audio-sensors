from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_7_corrective_03 import (
    build_evidence_package,
    validate_criteria_only,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    REQUIRED_PACKAGE_FILES,
    S47PrerequisiteError,
    _validate_reports,
    expected_effective_criteria,
    expected_scientific_semantics_sha256,
    validate_effective_criteria,
)

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "configs/s4_7_holdout_acceptance.v1.json"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_criteria_only_validates_exact_windows_and_semantics() -> None:
    result = validate_criteria_only(ROOT)
    assert result["status"] == "passed"
    assert result["take_count"] == 47
    assert result["readiness_passed"] is True
    assert result["semantic_bypass_failed"] is True
    assert result["semantic_bypass_bearing_observed"] == 19.5
    assert result["semantic_bypass_sector_observed"] == 0.5
    assert result["deterministic"] is True
    assert result["holdout_observations_accessed"] == 0


def test_expected_register_preserves_every_frozen_scientific_field() -> None:
    expected = expected_effective_criteria(ROOT)
    frozen = _load(V1)["criteria"]
    assert len(expected) == len(frozen) == 29
    for effective, criterion in zip(expected, frozen, strict=True):
        for field in (
            "criterion_id",
            "tier",
            "gating",
            "metric",
            "statistic",
            "comparator",
            "threshold",
            "denominator",
            "strata",
            "sample_kind",
            "observable",
            "failure_logic",
        ):
            assert effective[field] == criterion[field]
        assert effective["scientific_contract"] == criterion["metric_contract"]
        assert isinstance(effective["resolution"], dict)
        assert effective["resolution"]["changes_scientific_eligibility"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda criteria: criteria[0]["scientific_contract"].__setitem__(
            "method", "error of one median bearing"
        ),
        lambda criteria: criteria[0].__setitem__(
            "observable", "caller_supplied_summary"
        ),
        lambda criteria: criteria[0].__setitem__(
            "effective_semantics", "anything non-empty"
        ),
        lambda criteria: criteria[0].__setitem__("threshold", 15.0001),
    ],
)
def test_altered_method_observable_prose_or_threshold_is_rejected(
    mutate,
) -> None:
    criteria = copy.deepcopy(expected_effective_criteria(ROOT))
    mutate(criteria)
    with pytest.raises(
        S47PrerequisiteError,
        match="scientific semantics mismatch",
    ):
        validate_effective_criteria(criteria, ROOT)


def test_evidence_builder_emits_exact_semantic_register(
    tmp_path: Path,
) -> None:
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "package"
    result = build_evidence_package(
        repo_root=ROOT,
        output=output,
        source_commit=source_commit,
        source_tree_replay=True,
    )
    assert result["status"] == "passed"
    assert {path.name for path in output.iterdir()} == REQUIRED_PACKAGE_FILES
    acceptance = _load(output / "holdout_acceptance.json")
    register = _load(output / "criteria_register.json")["details"]
    assert register["criteria"] == expected_effective_criteria(ROOT)
    assert register["scientific_semantics_sha256"] == (
        expected_scientific_semantics_sha256(ROOT)
    )
    _validate_reports(ROOT, output, acceptance)
    bypass = _load(output / "synthetic_evaluation_report.json")["details"]
    assert bypass["incorrect_corrective_02_b_median_error_deg"] == 4.5
    assert bypass["incorrect_corrective_02_b_sector_accuracy"] == 1.0
    assert bypass["frozen_b_median_error_deg"] == 19.5
    assert bypass["frozen_b_sector_accuracy"] == 0.5


def test_checksum_consistent_semantic_tamper_is_still_rejected(
    tmp_path: Path,
) -> None:
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "package"
    build_evidence_package(
        repo_root=ROOT,
        output=output,
        source_commit=source_commit,
        source_tree_replay=True,
    )
    acceptance = _load(output / "holdout_acceptance.json")
    register_path = output / "criteria_register.json"
    register = _load(register_path)
    register["details"]["criteria"][0]["scientific_contract"]["method"] = (
        "error of a median bearing"
    )
    register_path.write_text(
        json.dumps(register, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        S47PrerequisiteError,
        match="scientific semantics mismatch",
    ):
        _validate_reports(ROOT, output, acceptance)
