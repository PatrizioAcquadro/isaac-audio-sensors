from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    canonical_sha256,
    consume_s4_8_grant,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite import (
    CANONICAL_PACKAGE,
    CANONICAL_PREREQUISITE,
    PREREQUISITE_BINDING_FIELDS,
    REQUIRED_PACKAGE_FILES,
    S47PrerequisiteError,
    sha256_file,
    validate_s4_7_corrective_prerequisite,
)

ROOT = Path(__file__).resolve().parents[1]
SEAL_RELATIVE = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/holdout_seal.v1.json"
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
        repo, "configs/s4_7_holdout_acceptance.corrective_01.v2.json"
    )
    schema_path = _copy(
        repo,
        "docs/schemas/s4_7_holdout_acceptance.corrective_01.v2.schema.json",
    )
    corrective_spec = _copy(
        repo, "docs/development/specs/s4_holdout_acceptance_corrective_01.md"
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
        _write_json(
            package / name,
            {
                "schema": f"ias.s4_7.test.{name}.v2",
                "status": "passed",
                "holdout_observations_accessed": 0,
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
        "schema": "ias.s4_7.corrective_evidence_index.v2",
        "status": "passed",
        "source_commit": source_commit,
        "file_count": len(REQUIRED_PACKAGE_FILES),
        "records": records,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    _write_json(package / "evidence_index.json", index)
    acceptance = {
        "schema": "ias.s4_7.holdout_acceptance_corrective.v2",
        "status": "passed",
        "corrective_id": "s4_7_corrective_01",
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
    authenticated = validate_s4_7_corrective_prerequisite(
        state["prerequisite"], seal_path=state["seal"]
    )
    assert authenticated["status"] == "passed"
    assert authenticated["package_file_count"] == 18
    accepted = _consume(state, _grant(state, authenticated))
    assert accepted["allowed"] is True
    assert accepted["mode"] == "S4.8_evaluation"


def test_fabricated_two_field_prerequisite_is_rejected(tmp_path: Path) -> None:
    state = _build_repo(tmp_path)
    authenticated = validate_s4_7_corrective_prerequisite(
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
        validate_s4_7_corrective_prerequisite(wrong, seal_path=state["seal"])

    authenticated = validate_s4_7_corrective_prerequisite(
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
    authenticated = validate_s4_7_corrective_prerequisite(
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
    authenticated = validate_s4_7_corrective_prerequisite(
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
        validate_s4_7_corrective_prerequisite(
            incomplete["prerequisite"], seal_path=incomplete["seal"]
        )


def test_uncommitted_and_tampered_evidence_are_rejected(tmp_path: Path) -> None:
    uncommitted = _build_repo(tmp_path / "uncommitted", commit_package=False)
    with pytest.raises(S47PrerequisiteError, match="not fully tracked"):
        validate_s4_7_corrective_prerequisite(
            uncommitted["prerequisite"], seal_path=uncommitted["seal"]
        )

    tampered = _build_repo(tmp_path / "tampered")
    report = tampered["package"] / "determinism_report.json"
    report.write_text('{"status":"tampered"}\n', encoding="utf-8")
    with pytest.raises(S47PrerequisiteError, match="SHA256SUMS mismatch"):
        validate_s4_7_corrective_prerequisite(
            tampered["prerequisite"], seal_path=tampered["seal"]
        )


def test_acceptance_artifact_cannot_be_replaced_by_minimal_stub(
    tmp_path: Path,
) -> None:
    state = _build_repo(tmp_path)
    _write_json(
        state["prerequisite"],
        {
            "schema": "ias.s4_7.holdout_acceptance_corrective.v2",
            "status": "passed",
        },
    )
    with pytest.raises(S47PrerequisiteError):
        validate_s4_7_corrective_prerequisite(
            state["prerequisite"], seal_path=state["seal"]
        )
