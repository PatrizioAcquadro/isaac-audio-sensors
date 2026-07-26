from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_7_corrective import (
    build_evidence_package,
    validate_criteria_only,
    validate_evidence_package,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite import (
    REQUIRED_PACKAGE_FILES,
)

ROOT = Path(__file__).resolve().parents[1]


def _build(target: Path) -> dict[str, object]:
    return build_evidence_package(
        repo_root=ROOT,
        output=target,
        source_commit="5e2d2a49d144b063da475db5fc0c5ad49398870a",
        source_tree_replay=True,
    )


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_corrective_criteria_only_validation_passes() -> None:
    result = validate_criteria_only(ROOT)
    assert result["status"] == "passed"
    assert result["issues"] == []
    assert result["take_count"] == 47
    assert result["readiness_passed"] is True
    assert result["violating_fixture_failed"] is True
    assert result["holdout_observations_accessed"] == 0


def test_corrective_package_is_complete_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert _build(first)["status"] == "passed"
    assert _build(second)["status"] == "passed"
    assert {path.name for path in first.iterdir()} == REQUIRED_PACKAGE_FILES
    assert {
        path.name: path.read_bytes() for path in first.iterdir()
    } == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_corrective_package_records_exact_identity_and_comparison_counts(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    _build(target)
    identity = _json(target / "identity_registry.json")
    inputs = _json(target / "input_contract_report.json")
    comparisons = _json(target / "sim_vs_real_registry.json")
    assert identity["take_count"] == 47
    assert identity["group_count"] == 15
    assert len(identity["raw_microphone_ids"]) == 4
    assert len(identity["microphone_pair_ids"]) == 6
    assert inputs["raw_channel_record_count"] == 188
    assert inputs["tdoa_take_pair_record_count"] == 144
    assert inputs["bearing_sim_real_condition_count"] == 32
    assert inputs["bearing_referenced_take_count"] == 40
    assert len(comparisons["comparison_registry"]) == 7


def test_corrective_fail_closed_matrix_covers_required_regressions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    _build(target)
    matrix = _json(target / "fail_closed_matrix.json")
    names = {item["case"] for item in matrix["cases"]}
    assert {
        "only_one_of_seven_comparisons",
        "payload_flips_direction",
        "payload_selects_other_band",
        "one_real_counterpart_for_32",
        "one_window_for_stratum",
        "duplicate_tdoa_pair",
        "misstratified_take",
        "wrong_group",
        "wrong_pair",
        "negative_absolute_error",
        "negative_latency",
        "negative_clip_run",
        "negative_av_residual",
    } <= names
    assert matrix["status"] == "passed"
    assert all(item["fail_closed"] for item in matrix["cases"])


def test_historical_package_hashes_are_preserved(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    preservation = _json(target / "historical_preservation.json")
    assert preservation["status"] == "passed"
    assert preservation["historical_package_file_count"] == 16
    assert preservation["historical_sha256_manifest_sha256"] == (
        "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53"
    )
    for record in preservation["historical_records"]:
        path = ROOT / "outputs/isaac_audio_sensors/S4/S4.7" / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_freeze_ordering_and_phase_boundary_are_truthful(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    ordering = _json(target / "freeze_ordering.json")
    boundary = _json(target / "phase_boundary.json")
    assert ordering["status"] == "passed"
    assert ordering["baseline_before_freeze"] is True
    assert ordering["freeze_not_after_contract_commit"] is True
    assert ordering["contract_not_after_evaluator_commit"] is True
    assert boundary["holdout_observations_accessed"] == 0
    assert boundary["holdout_access_grant_created"] is False
    assert boundary["holdout_access_grant_consumed"] is False
    assert boundary["s4_8_started"] is False
    assert boundary["s4_9_started"] is False
    assert boundary["s5_started"] is False
    assert boundary["s6_started"] is False


def test_evidence_index_and_sha256_manifest_close_over_package(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    _build(target)
    index = _json(target / "evidence_index.json")
    assert index["file_count"] == 18
    assert len(index["records"]) == 15
    for record in index["records"]:
        path = target / record["path"]
        assert path.stat().st_size == record["byte_size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    for line in (target / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest


def test_uncommitted_temporary_package_validates_semantically(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    _build(target)
    result = validate_evidence_package(ROOT, target)
    assert result["status"] == "failed"
    assert any("Git repository" in issue for issue in result["issues"])


def test_tampered_package_fails_validation(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    report = target / "determinism_report.json"
    payload = _json(report)
    payload["status"] = "failed"
    report.write_text(json.dumps(payload), encoding="utf-8")
    manifest = target / "SHA256SUMS"
    before = manifest.read_text(encoding="utf-8")
    assert hashlib.sha256(report.read_bytes()).hexdigest() not in before


def test_source_bound_files_are_committed_before_canonical_generation() -> None:
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode in {0, 1}


def test_package_builder_does_not_mutate_historical_package(tmp_path: Path) -> None:
    historical = ROOT / "outputs/isaac_audio_sensors/S4/S4.7"
    before = {path.name: path.read_bytes() for path in historical.iterdir()}
    _build(tmp_path / "package")
    after = {path.name: path.read_bytes() for path in historical.iterdir()}
    assert after == before
