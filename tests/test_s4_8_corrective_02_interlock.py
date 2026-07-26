from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import (
    s4_7_prerequisite_corrective_02 as prerequisite_module,
)
from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    canonical_sha256,
    consume_s4_8_grant,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_02 import (
    CANONICAL_PACKAGE,
    CANONICAL_PREREQUISITE,
    PREREQUISITE_BINDING_FIELDS,
    REPORT_DETAIL_FIELDS,
    REPORT_SCHEMAS,
    REQUIRED_PACKAGE_FILES,
    S47PrerequisiteError,
    sha256_file,
    validate_s4_7_corrective_02_prerequisite,
)

ROOT = Path(__file__).resolve().parents[1]
SEAL_RELATIVE = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/holdout_seal.v1.json"
)


@pytest.fixture(autouse=True)
def _unit_tests_do_not_run_clean_archive_replay(monkeypatch) -> None:
    monkeypatch.setattr(
        prerequisite_module,
        "_validate_deterministic_replay",
        lambda _repo_root: None,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _copy(repo: Path, relative: str) -> Path:
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / relative, destination)
    return destination


def _report_details(
    name: str,
    *,
    source_commit: str,
    config: dict[str, object],
    inherited_config: Path,
    schema_path: Path,
    corrective_spec: Path,
) -> dict[str, object]:
    inherited = json.loads(inherited_config.read_text(encoding="utf-8"))
    criteria = [
        {
            key: item[key]
            for key in (
                "criterion_id",
                "tier",
                "gating",
                "metric",
                "statistic",
                "comparator",
                "threshold",
                "denominator",
                "failure_logic",
            )
        }
        | {"effective_semantics": "resolved by corrective_02"}
        for item in inherited["criteria"]
    ]
    values: dict[str, dict[str, object]] = {
        "blindness_attestation.json": {
            "holdout_derived_outcomes_accessed": 0,
            "raw_dataset_content_accessed": False,
            "holdout_access_grant_created": False,
            "holdout_access_grant_consumed": False,
            "thresholds_selected_from_holdout": False,
        },
        "contract_validation.json": {
            "criteria_validation_status": "passed",
            "thresholds_changed": False,
            "claimed_envelope_changed": False,
            "scientific_eligibility_changed": False,
            "criteria_config_sha256": sha256_file(
                inherited_config.with_name(
                    "s4_7_holdout_acceptance.corrective_02.v3.json"
                )
            ),
            "criteria_schema_sha256": sha256_file(schema_path),
            "corrective_spec_sha256": sha256_file(corrective_spec),
        },
        "criteria_register.json": {
            "inherited_config_sha256": sha256_file(inherited_config),
            "criterion_count": 29,
            "readiness_criterion_count": 23,
            "stretch_criterion_count": 6,
            "resolution": "corrective_02_effective_semantics",
            "criteria": criteria,
        },
        "determinism_report.json": {
            "run_count": 2,
            "evaluation_reports_identical": True,
            "randomness_used": False,
            "wall_clock_input_used": False,
        },
        "fail_closed_matrix.json": {
            "case_count": 1,
            "cases": [
                {
                    "case": "synthetic",
                    "status": "passed",
                    "fail_closed": True,
                    "detail": "rejected",
                }
            ],
            "silent_pass_observed": False,
        },
        "final_validation.json": {
            "criteria_only_validation_passed": True,
            "identity_registry_complete": True,
            "comparison_registry_complete": True,
            "fail_closed_matrix_passed": True,
            "deterministic": True,
            "freeze_ordering_valid": True,
            "historical_packages_preserved": True,
            "holdout_binding_valid": True,
            "readiness_criterion_count": 23,
            "stretch_criterion_count": 6,
        },
        "freeze_ordering.json": {
            "baseline_commit": "f2230128fd02294892282b5809abe71092f19013",
            "corrective_01_closeout_commit": (
                "6b0e8387a3c04fa4b513ab1bbe8514ef1f6b11d3"
            ),
            "frozen_at_utc": config["frozen_at_utc"],
            "source_commit": source_commit,
            "baseline_before_freeze": True,
            "corrective_01_before_freeze": True,
            "source_descends_from_corrective_01": True,
        },
        "historical_preservation.json": {
            "packages": [
                {
                    "path": "outputs/isaac_audio_sensors/S4/S4.7",
                    "file_count": 16,
                    "sha256_manifest_sha256": (
                        "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53"
                    ),
                    "manifest_valid": True,
                },
                {
                    "path": (
                        "outputs/isaac_audio_sensors/S4/S4.7_corrective_01"
                    ),
                    "file_count": 18,
                    "sha256_manifest_sha256": (
                        "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676"
                    ),
                    "manifest_valid": True,
                },
            ]
        },
        "holdout_binding_report.json": {
            "seal_path": config["holdout_binding"]["seal_path"],
            "partition_manifest_path": config["holdout_binding"][
                "partition_manifest_path"
            ],
            "partition_manifest_sha256": config["holdout_binding"][
                "partition_manifest_sha256"
            ],
            "session_manifest_path": config["holdout_binding"][
                "session_manifest_path"
            ],
            "session_manifest_sha256": config["holdout_binding"][
                "session_manifest_sha256"
            ],
            "group_count": 15,
            "scientifically_opened": False,
            "technical_qa_only": True,
        },
        "identity_registry.json": {
            "take_count": 47,
            "take_ids_sha256": "c" * 64,
            "group_count": 15,
            "stratum_counts": {
                "A_controlled_boundary_sweep": 24,
                "B_center_nominal_level": 8,
                "C_center_low_level": 8,
                "D_silence": 3,
                "E_impact_audio_video": 4,
            },
            "raw_microphone_ids": [
                "raw_microphone_0",
                "raw_microphone_1",
                "raw_microphone_2",
                "raw_microphone_3",
            ],
            "microphone_pair_ids": [f"pair_{index}" for index in range(6)],
        },
        "input_contract_report.json": {
            "exact_take_set_required": True,
            "unique_identity_required": True,
            "per_take_window_coverage_required": True,
            "latency_take_count": 47,
            "raw_channel_record_count": 188,
            "tdoa_take_pair_record_count": 144,
            "bearing_sim_real_condition_count": 32,
            "bearing_referenced_take_count": 40,
            "maximum_clip_run_threshold_samples": 8,
            "sustained_clipping_minimum_samples": 4000,
            "real_values_derived": True,
        },
        "phase_boundary.json": {
            field: False for field in REPORT_DETAIL_FIELDS["phase_boundary.json"]
        },
        "reproduction.json": {
            "command": "python3 scripts/replay_s4_7_corrective_02.py",
            "comparison": "byte_for_byte_complete_package",
            "clean_source_archive": True,
            "requires_holdout_observations": False,
        },
        "sim_vs_real_registry.json": {
            "comparison_registry": config["sim_vs_real"]["comparison_registry"],
            "comparison_count": 7,
            "bearing_sim_real_condition_count": 32,
            "bearing_referenced_take_count": 40,
            "payload_may_supply_real": False,
        },
        "synthetic_evaluation_report.json": {
            "fixtures_are_synthetic": True,
            "conforming_evaluation": {
                "status": "passed",
                "holdout_observations_accessed_by_evaluator": 0,
            },
            "violating_evaluation": {
                "status": "failed",
                "holdout_observations_accessed_by_evaluator": 0,
            },
            "conforming_fixture_passes": True,
            "violating_fixture_fails": True,
        },
    }
    assert set(values[name]) == REPORT_DETAIL_FIELDS[name]
    return values[name]


def _build_repo(tmp_path: Path, *, commit_package: bool = True) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "S4.7 Test")
    _git(repo, "config", "user.email", "s47@example.invalid")

    seal = repo / SEAL_RELATIVE
    seal_payload = {
        "schema": "ias.s4_4.amendment_holdout_seal.v1",
        "status": "sealed",
        "seal_payload_sha256": "a" * 64,
        "planned_take_ids": [f"take_{index:03d}" for index in range(47)],
        "scientifically_opened": False,
    }
    _write_json(seal, seal_payload)

    config_path = _copy(
        repo, "configs/s4_7_holdout_acceptance.corrective_02.v3.json"
    )
    schema_path = _copy(
        repo,
        "docs/schemas/s4_7_holdout_acceptance.corrective_02.v3.schema.json",
    )
    corrective_spec = _copy(
        repo, "docs/development/specs/s4_holdout_acceptance_corrective_02.md"
    )
    inherited_config = _copy(repo, "configs/s4_7_holdout_acceptance.v1.json")
    inherited_spec = _copy(
        repo, "docs/development/specs/s4_holdout_acceptance.md"
    )
    _copy(repo, "configs/s4_3_pilot.v1.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["holdout_binding"]["seal_file_sha256"] = sha256_file(seal)
    config["holdout_binding"]["seal_payload_sha256"] = seal_payload[
        "seal_payload_sha256"
    ]
    _write_json(config_path, config)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "source")
    source_commit = _git(repo, "rev-parse", "HEAD")

    package = repo / CANONICAL_PACKAGE
    package.mkdir(parents=True)
    indexed_names = sorted(
        REQUIRED_PACKAGE_FILES
        - {"SHA256SUMS", "evidence_index.json", "holdout_acceptance.json"}
    )
    for name in indexed_names:
        details = _report_details(
            name,
            source_commit=source_commit,
            config=config,
            inherited_config=inherited_config,
            schema_path=schema_path,
            corrective_spec=corrective_spec,
        )
        _write_json(
            package / name,
            {
                "schema": REPORT_SCHEMAS[name],
                "status": "passed",
                "source_commit": source_commit,
                "bound_holdout_id": config["holdout_binding"][
                    "bound_holdout_id"
                ],
                "seal_file_sha256": sha256_file(seal),
                "seal_payload_sha256": seal_payload["seal_payload_sha256"],
                "planned_take_count": 47,
                "holdout_observations_accessed": 0,
                "later_phases_started": [],
                "details": details,
            },
        )
    records = [
        {
            "path": name,
            "sha256": sha256_file(package / name),
            "byte_size": (package / name).stat().st_size,
        }
        for name in indexed_names
    ]
    index = {
        "schema": "ias.s4_7.corrective_evidence_index.v3",
        "status": "passed",
        "source_commit": source_commit,
        "file_count": len(REQUIRED_PACKAGE_FILES),
        "records": records,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    _write_json(package / "evidence_index.json", index)
    acceptance = {
        "schema": "ias.s4_7.holdout_acceptance_corrective.v3",
        "status": "passed",
        "corrective_id": "s4_7_corrective_02",
        "evidence_path": CANONICAL_PACKAGE.as_posix(),
        "evidence_index_path": (
            CANONICAL_PACKAGE / "evidence_index.json"
        ).as_posix(),
        "evidence_index_sha256": sha256_file(package / "evidence_index.json"),
        "criteria_config_path": config_path.relative_to(repo).as_posix(),
        "criteria_config_sha256": sha256_file(config_path),
        "criteria_schema_path": schema_path.relative_to(repo).as_posix(),
        "criteria_schema_sha256": sha256_file(schema_path),
        "corrective_spec_path": corrective_spec.relative_to(repo).as_posix(),
        "corrective_spec_sha256": sha256_file(corrective_spec),
        "inherited_config_path": inherited_config.relative_to(repo).as_posix(),
        "inherited_config_sha256": sha256_file(inherited_config),
        "inherited_spec_path": inherited_spec.relative_to(repo).as_posix(),
        "inherited_spec_sha256": sha256_file(inherited_spec),
        "source_commit": source_commit,
        "bound_holdout_id": (
            "s4_4_data_expansion_amendment_03_prospective_holdout"
        ),
        "seal_path": SEAL_RELATIVE.as_posix(),
        "seal_file_sha256": sha256_file(seal),
        "seal_payload_sha256": seal_payload["seal_payload_sha256"],
        "planned_take_count": 47,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "readiness_passed": True,
        "holdout_observations_accessed": 0,
        "authorizes_holdout_opening": False,
        "grant_still_required_for_s4_8": True,
        "evidence_commit_policy": (
            "derived_from_git_commit_containing_exact_package_bytes"
        ),
        "deterministic_replay_required": True,
    }
    prerequisite = repo / CANONICAL_PREREQUISITE
    _write_json(prerequisite, acceptance)
    checksum_names = sorted(REQUIRED_PACKAGE_FILES - {"SHA256SUMS"})
    (package / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(package / name)}  {name}\n"
            for name in checksum_names
        ),
        encoding="utf-8",
    )
    if commit_package:
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "evidence")
    return {
        "repo": repo,
        "seal": seal,
        "package": package,
        "prerequisite": prerequisite,
        "source_commit": source_commit,
    }


def _regenerate_indexes_and_commit(
    state: dict[str, object], message: str
) -> None:
    package = state["package"]
    indexed_names = sorted(
        REQUIRED_PACKAGE_FILES
        - {"SHA256SUMS", "evidence_index.json", "holdout_acceptance.json"}
    )
    index_path = package / "evidence_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"] = [
        {
            "path": name,
            "sha256": sha256_file(package / name),
            "byte_size": (package / name).stat().st_size,
        }
        for name in indexed_names
    ]
    _write_json(index_path, index)
    prerequisite = state["prerequisite"]
    acceptance = json.loads(prerequisite.read_text(encoding="utf-8"))
    acceptance["evidence_index_sha256"] = sha256_file(index_path)
    _write_json(prerequisite, acceptance)
    checksum_names = sorted(REQUIRED_PACKAGE_FILES - {"SHA256SUMS"})
    (package / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(package / name)}  {name}\n"
            for name in checksum_names
        ),
        encoding="utf-8",
    )
    _git(state["repo"], "add", ".")
    _git(state["repo"], "commit", "-m", message)


def _grant(
    state: dict[str, object],
    prerequisite_identity: dict[str, object],
) -> dict[str, object]:
    payload = {
        "schema": "ias.s4_4.holdout_access_grant.v1",
        "grant_id": "synthetic_corrective_grant",
        "purpose": "S4.8_evaluation",
        "seal_sha256": sha256_file(state["seal"]),
        "split_plan_sha256": "b" * 64,
        "prerequisite": {
            key: prerequisite_identity[key]
            for key in PREREQUISITE_BINDING_FIELDS
        },
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    payload["grant_sha256"] = canonical_sha256(payload)
    return payload


def _consume(
    state: dict[str, object], grant: dict[str, object], *, suffix: str = ""
) -> dict[str, object]:
    repo = state["repo"]
    grant_path = repo / f"grant{suffix}.json"
    _write_json(grant_path, grant)
    return consume_s4_8_grant(
        grant_path,
        seal_path=state["seal"],
        split_plan_sha256="b" * 64,
        prerequisite_path=state["prerequisite"],
        ledger_path=repo / f"ledger{suffix}.jsonl",
        event_time_utc="2030-01-01T00:00:00Z",
    )


def test_complete_committed_corrective_prerequisite_authenticates(
    tmp_path: Path,
) -> None:
    state = _build_repo(tmp_path)
    authenticated = validate_s4_7_corrective_02_prerequisite(
        state["prerequisite"], seal_path=state["seal"]
    )
    assert authenticated["status"] == "passed"
    assert authenticated["package_file_count"] == 18
    accepted = _consume(state, _grant(state, authenticated))
    assert accepted["allowed"] is True
    assert accepted["mode"] == "S4.8_evaluation"


def test_fabricated_two_field_prerequisite_is_rejected(tmp_path: Path) -> None:
    state = _build_repo(tmp_path)
    authenticated = validate_s4_7_corrective_02_prerequisite(
        state["prerequisite"], seal_path=state["seal"]
    )
    grant = _grant(state, authenticated)
    grant["prerequisite"] = {"schema": authenticated["schema"], "status": "passed"}
    grant["grant_sha256"] = canonical_sha256(
        {key: value for key, value in grant.items() if key != "grant_sha256"}
    )
    with pytest.raises(S44Error, match="prerequisite fields mismatch"):
        _consume(state, grant)


def test_wrong_prerequisite_paths_are_rejected(tmp_path: Path) -> None:
    state = _build_repo(tmp_path)
    wrong = state["repo"] / "copied_prerequisite.json"
    shutil.copy2(state["prerequisite"], wrong)
    with pytest.raises(S47PrerequisiteError, match="path must be canonical"):
        validate_s4_7_corrective_02_prerequisite(wrong, seal_path=state["seal"])

    authenticated = validate_s4_7_corrective_02_prerequisite(
        state["prerequisite"], seal_path=state["seal"]
    )
    grant = _grant(state, authenticated)
    grant["prerequisite"]["path"] = "caller/selected.json"
    grant["grant_sha256"] = canonical_sha256(
        {key: value for key, value in grant.items() if key != "grant_sha256"}
    )
    with pytest.raises(S44Error, match="identity binding mismatch"):
        _consume(state, grant)


def test_wrong_grant_and_prerequisite_seals_are_rejected(tmp_path: Path) -> None:
    state = _build_repo(tmp_path)
    authenticated = validate_s4_7_corrective_02_prerequisite(
        state["prerequisite"], seal_path=state["seal"]
    )
    wrong_grant = _grant(state, authenticated)
    wrong_grant["seal_sha256"] = "0" * 64
    wrong_grant["grant_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in wrong_grant.items()
            if key != "grant_sha256"
        }
    )
    with pytest.raises(S44Error, match="grant seal binding mismatch"):
        _consume(state, wrong_grant, suffix="_grant")

    wrong_prerequisite = _grant(state, authenticated)
    wrong_prerequisite["prerequisite"]["seal_file_sha256"] = "0" * 64
    wrong_prerequisite["grant_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in wrong_prerequisite.items()
            if key != "grant_sha256"
        }
    )
    with pytest.raises(S44Error, match="identity binding mismatch"):
        _consume(state, wrong_prerequisite, suffix="_prerequisite")


def test_stale_hash_and_incomplete_package_are_rejected(tmp_path: Path) -> None:
    stale_state = _build_repo(tmp_path / "stale")
    authenticated = validate_s4_7_corrective_02_prerequisite(
        stale_state["prerequisite"], seal_path=stale_state["seal"]
    )
    stale = _grant(stale_state, authenticated)
    stale["prerequisite"]["criteria_config_sha256"] = "0" * 64
    stale["grant_sha256"] = canonical_sha256(
        {key: value for key, value in stale.items() if key != "grant_sha256"}
    )
    with pytest.raises(S44Error, match="identity binding mismatch"):
        _consume(stale_state, stale)

    incomplete = _build_repo(tmp_path / "incomplete")
    (incomplete["package"] / "determinism_report.json").unlink()
    with pytest.raises(S47PrerequisiteError, match="file set mismatch"):
        validate_s4_7_corrective_02_prerequisite(
            incomplete["prerequisite"], seal_path=incomplete["seal"]
        )


def test_uncommitted_and_tampered_evidence_are_rejected(tmp_path: Path) -> None:
    uncommitted = _build_repo(tmp_path / "uncommitted", commit_package=False)
    with pytest.raises(S47PrerequisiteError, match="not fully tracked"):
        validate_s4_7_corrective_02_prerequisite(
            uncommitted["prerequisite"], seal_path=uncommitted["seal"]
        )

    tampered = _build_repo(tmp_path / "tampered")
    report = tampered["package"] / "determinism_report.json"
    report.write_text('{"status":"tampered"}\n', encoding="utf-8")
    with pytest.raises(S47PrerequisiteError, match="SHA256SUMS mismatch"):
        validate_s4_7_corrective_02_prerequisite(
            tampered["prerequisite"], seal_path=tampered["seal"]
        )


def test_acceptance_artifact_cannot_be_replaced_by_minimal_stub(
    tmp_path: Path,
) -> None:
    state = _build_repo(tmp_path)
    _write_json(
        state["prerequisite"],
        {
            "schema": "ias.s4_7.holdout_acceptance_corrective.v3",
            "status": "passed",
        },
    )
    with pytest.raises(S47PrerequisiteError):
        validate_s4_7_corrective_02_prerequisite(
            state["prerequisite"], seal_path=state["seal"]
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda report: report.__setitem__("schema", "ias.wrong.schema.v1"),
            "semantic schema mismatch",
        ),
        (
            lambda report: report.__setitem__("status", "failed"),
            "semantic status mismatch",
        ),
        (
            lambda report: report.__setitem__(
                "holdout_observations_accessed", 1
            ),
            "semantic holdout_observations_accessed mismatch",
        ),
    ],
)
def test_committed_checksum_consistent_inner_report_tampering_is_rejected(
    tmp_path: Path, mutation, message: str
) -> None:
    state = _build_repo(tmp_path)
    report_path = state["package"] / "determinism_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mutation(report)
    _write_json(report_path, report)
    _regenerate_indexes_and_commit(state, "regenerate all checksums")
    with pytest.raises(S47PrerequisiteError, match=message):
        validate_s4_7_corrective_02_prerequisite(
            state["prerequisite"], seal_path=state["seal"]
        )


@pytest.mark.parametrize(
    ("name", "mutation", "message"),
    [
        (
            "identity_registry.json",
            lambda report: report.__setitem__("planned_take_count", 46),
            "planned_take_count mismatch",
        ),
        (
            "holdout_binding_report.json",
            lambda report: report.__setitem__("seal_payload_sha256", "0" * 64),
            "seal_payload_sha256 mismatch",
        ),
        (
            "phase_boundary.json",
            lambda report: report["details"].__setitem__("s4_8_started", True),
            "semantic s4_8_started mismatch",
        ),
        (
            "determinism_report.json",
            lambda report: report.__setitem__("source_commit", "0" * 40),
            "source_commit mismatch",
        ),
    ],
)
def test_cross_report_identity_and_phase_contradictions_are_rejected(
    tmp_path: Path,
    name: str,
    mutation,
    message: str,
) -> None:
    state = _build_repo(tmp_path)
    report_path = state["package"] / name
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mutation(report)
    _write_json(report_path, report)
    _regenerate_indexes_and_commit(state, "commit contradictory report")
    with pytest.raises(S47PrerequisiteError, match=message):
        validate_s4_7_corrective_02_prerequisite(
            state["prerequisite"], seal_path=state["seal"]
        )
