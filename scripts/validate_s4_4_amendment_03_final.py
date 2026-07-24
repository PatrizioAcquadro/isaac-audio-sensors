#!/usr/bin/env python3
"""Fail-closed, outcome-blind S4.4 Amendment 03 final-closeout validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    canonicalize_holdout_technical_qa,
    hash_only_holdout_integrity,
    load_json,
    sha256_file,
    validate_ledger,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    detect_later_phase_artifacts,
    validate_predecessor_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REL = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03"
)
MACHINE_REL = Path("dataset/S4.4/amendments/s4_4_data_expansion_amendment_03")
FIT_A_ATTEMPTS_REL = Path(
    "dataset/S4.4/amendments/s4_4_data_expansion_amendment_02/attempts"
)
FUTURE_ATTEMPTS_REL = MACHINE_REL / "attempts"
SOURCE_CHECKPOINT_COMMIT = "d86710df72c0ad782420b05135b3371cd9e0048f"
PRECOLLECTION_COMMIT = "9e1d0eb46c60f7bb8714cb182c6fd99f76232d4d"
HOLDOUT_CLOSEOUT_COMMIT = "c432d9848d1c1498914ed1a2aad6c78baefc6519"
RECORDED_FINAL_GATE_COMMIT = "322afa08c4276e42a3f69182695f7227a67b9c9d"
CORRECTIVE_01_PACKAGE_COMMIT = "78f09d7e4bb95f3f821a70d14f333760b917742a"
EXPECTED_CENSUS = {
    "valid_cells_total": 149,
    "retained_attempts_total": 152,
    "failures_total": 3,
    "replacements_total": 3,
    "incomplete_logical_cells": 0,
}
EXPECTED_ATTEMPTS = {"fit_a": 52, "fit_b": 52, "prospective_holdout": 48}
SHA_LINE = re.compile(r"^([0-9a-f]{64})  ([^\n]+)$")


def _issue(code: str, path: object, message: str) -> dict[str, str]:
    return {"code": code, "path": str(path), "message": message}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise S44AmendmentError(message)


def _safe_relative(value: object, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label}: path required")
    relative = PurePosixPath(str(value))
    _require(
        not relative.is_absolute() and ".." not in relative.parts,
        f"{label}: unsafe path",
    )
    return str(value)


def parse_checksum_manifest(
    text: str, *, label: str, allow_parent: bool = False
) -> dict[str, str]:
    """Parse one exact SHA256SUMS file and reject malformed/duplicate paths."""

    records: dict[str, str] = {}
    lines = text.splitlines()
    _require(bool(lines), f"{label}: checksum manifest is empty")
    for number, line in enumerate(lines, 1):
        match = SHA_LINE.fullmatch(line)
        _require(match is not None, f"{label}:{number}: malformed checksum")
        digest, relative = match.groups()
        if allow_parent:
            _require(
                not PurePosixPath(relative).is_absolute(),
                f"{label}:{number}: unsafe path",
            )
        else:
            _safe_relative(relative, f"{label}:{number}")
        _require(relative not in records, f"{label}:{number}: duplicate checksum path")
        records[relative] = digest
    return records


def _load_self_hashed(path: Path, field: str, schema: str) -> dict[str, Any]:
    record = load_json(path)
    _require(record.get("schema") == schema, f"{path}: schema mismatch")
    payload = {key: value for key, value in record.items() if key != field}
    _require(
        record.get(field) == canonical_sha256(payload), f"{path}: self-hash mismatch"
    )
    return record


def validate_attempt_directory(attempt_dir: Path) -> dict[str, Any]:
    """Validate one retained attempt without deriving any scientific outcome."""

    manifest_path = attempt_dir / "manifest.json"
    checksum_path = attempt_dir / "SHA256SUMS"
    _require(manifest_path.is_file(), f"{attempt_dir}: manifest missing")
    _require(checksum_path.is_file(), f"{attempt_dir}: SHA256SUMS missing")
    manifest = load_json(manifest_path)
    _require(
        manifest.get("attempt_id") == attempt_dir.name,
        f"{attempt_dir}: attempt identity mismatch",
    )
    _require(manifest.get("retained") is True, f"{attempt_dir}: attempt not retained")
    artifacts = manifest.get("artifacts")
    _require(
        isinstance(artifacts, list) and bool(artifacts),
        f"{attempt_dir}: artifacts absent",
    )
    expected: dict[str, str] = {}
    for number, artifact in enumerate(artifacts):
        _require(
            isinstance(artifact, Mapping), f"{attempt_dir}: artifact {number} invalid"
        )
        relative = _safe_relative(artifact.get("path"), f"{attempt_dir}: artifact path")
        _require(
            relative not in expected, f"{attempt_dir}: duplicate manifest artifact"
        )
        digest = str(artifact.get("sha256"))
        _require(
            SHA_LINE.fullmatch(f"{digest}  {relative}") is not None,
            f"{attempt_dir}: artifact digest invalid",
        )
        target = attempt_dir / relative
        _require(target.is_file(), f"{attempt_dir}: artifact missing: {relative}")
        _require(
            target.stat().st_size == artifact.get("byte_size"),
            f"{attempt_dir}: artifact size mismatch: {relative}",
        )
        _require(
            sha256_file(target) == digest,
            f"{attempt_dir}: artifact hash mismatch: {relative}",
        )
        expected[relative] = digest
    checksums = parse_checksum_manifest(
        checksum_path.read_text(encoding="utf-8"), label=str(checksum_path)
    )
    _require(checksums == expected, f"{attempt_dir}: checksum coverage mismatch")
    return manifest


def validate_all_attempts(repo_root: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    manifests: list[tuple[dict[str, Any], Path]] = []
    for root in (repo_root / FIT_A_ATTEMPTS_REL, repo_root / FUTURE_ATTEMPTS_REL):
        _require(root.is_dir(), f"{root}: attempt root absent")
        attempt_dirs = sorted(path for path in root.glob("*/*") if path.is_dir())
        for directory in attempt_dirs:
            manifests.append((validate_attempt_directory(directory), directory))
    counts = Counter(str(record.get("session_id")) for record, _ in manifests)
    _require(
        dict(counts) == EXPECTED_ATTEMPTS,
        f"attempt session census mismatch: {dict(counts)}",
    )
    seen_ids: set[str] = set()
    by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attempt_paths: dict[str, Path] = {}
    for record, directory in manifests:
        attempt_id = str(record.get("attempt_id"))
        planned_id = str(record.get("planned_take_id"))
        _require(attempt_id not in seen_ids, f"duplicate attempt id: {attempt_id}")
        seen_ids.add(attempt_id)
        _require(
            record.get("outcome") in {"valid", "invalid", "pre_recording_failure"},
            f"{attempt_id}: final outcome invalid",
        )
        _require(
            record.get("scientific_outcome_used_for_replacement") is False,
            f"{attempt_id}: scientific outcome drove replacement",
        )
        by_cell[planned_id].append(record)
        attempt_paths[attempt_id] = directory
    failures = replacements = valid_cells = 0
    for planned_id, records in by_cell.items():
        ordered = sorted(records, key=lambda item: int(item["attempt_number"]))
        _require(
            [item["attempt_number"] for item in ordered]
            == list(range(1, len(ordered) + 1))
            and len(ordered) <= 2,
            f"{planned_id}: attempt sequence invalid",
        )
        outcomes = [str(item["outcome"]) for item in ordered]
        failures += sum(item != "valid" for item in outcomes)
        if len(ordered) == 2:
            replacements += 1
            _require(outcomes[0] != "valid", f"{planned_id}: replacement after valid")
            _require(
                ordered[1].get("replacement") is True,
                f"{planned_id}: replacement flag absent",
            )
        if "valid" in outcomes:
            _require(outcomes[-1] == "valid", f"{planned_id}: attempt after valid")
            valid_cells += 1
    census = {
        "valid_cells_total": valid_cells,
        "retained_attempts_total": len(manifests),
        "failures_total": failures,
        "replacements_total": replacements,
        "incomplete_logical_cells": 149 - valid_cells,
    }
    _require(census == EXPECTED_CENSUS, f"final census mismatch: {census}")
    return census, attempt_paths


def validate_holdout_qa_records(
    repo_root: Path, attempt_paths: Mapping[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = load_json(
        repo_root / EVIDENCE_REL / "manifests/sessions/prospective_holdout.json"
    )
    planned_ids = [str(item["planned_take_id"]) for item in manifest["takes"]]
    _require(
        len(planned_ids) == 47 and len(set(planned_ids)) == 47,
        "holdout plan census invalid",
    )
    qa_root = repo_root / MACHINE_REL / "access/technical_qa"
    paths = sorted(qa_root.glob("*.json"))
    _require(len(paths) == 47, f"holdout QA count mismatch: {len(paths)}")
    raw_by_take: dict[str, dict[str, Any]] = {}
    canonical: list[dict[str, Any]] = []
    for path in paths:
        raw = load_json(path)
        projected = canonicalize_holdout_technical_qa(raw)
        planned_id = str(projected["planned_take_id"])
        _require(planned_id in set(planned_ids), f"{path}: unknown planned take")
        _require(path.stem == planned_id, f"{path}: QA filename mismatch")
        _require(planned_id not in raw_by_take, f"{path}: duplicate holdout QA")
        _require(
            projected["overall_technical_pass"] is True, f"{path}: technical QA failed"
        )
        _require(
            projected["scientific_outputs_exposed"] is False,
            f"{path}: scientific output exposed",
        )
        attempt_id = str(projected["attempt_id"])
        _require(attempt_id in attempt_paths, f"{path}: unknown attempt binding")
        retained = attempt_paths[attempt_id] / "technical_qa.json"
        _require(
            retained.is_file() and sha256_file(retained) == sha256_file(path),
            f"{path}: retained QA binding mismatch",
        )
        raw_by_take[planned_id] = raw
        canonical.append(projected)
    _require(set(raw_by_take) == set(planned_ids), "holdout QA plan coverage mismatch")
    return canonical, raw_by_take


def validate_holdout_seal_payload(
    seal: Mapping[str, Any], raw_qa: Mapping[str, Mapping[str, Any]]
) -> None:
    payload = {
        key: value for key, value in seal.items() if key != "seal_payload_sha256"
    }
    _require(
        seal.get("seal_payload_sha256") == canonical_sha256(payload),
        "holdout seal self-hash mismatch",
    )
    _require(
        seal.get("status") == "sealed"
        and seal.get("scientifically_opened") is False
        and seal.get("technical_qa_only") is True
        and seal.get("scientific_outputs_included") is False,
        "holdout seal state invalid",
    )
    planned = seal.get("planned_take_ids")
    _require(
        isinstance(planned, list) and len(planned) == 47 and len(set(planned)) == 47,
        "holdout seal plan invalid",
    )
    _require(set(raw_qa) == set(planned), "holdout seal QA collection mismatch")
    expected_qa = {
        planned_id: canonical_sha256(raw_qa[planned_id])
        for planned_id in sorted(raw_qa)
    }
    _require(
        seal.get("technical_qa_record_sha256") == expected_qa,
        "holdout seal QA binding mismatch",
    )
    artifact_keys: set[tuple[str, str]] = set()
    for record in seal.get("artifacts", []):
        relative = _safe_relative(record.get("path"), "holdout seal artifact")
        key = (relative, str(record.get("role")))
        _require(key not in artifact_keys, f"duplicate holdout seal artifact: {key}")
        artifact_keys.add(key)


def validate_holdout_seals(
    repo_root: Path, raw_qa: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], str]:
    machine_path = repo_root / MACHINE_REL / "access/holdout_seal.json"
    tracked_path = repo_root / EVIDENCE_REL / "holdout_seal.v1.json"
    _require(machine_path.is_file() and tracked_path.is_file(), "holdout seal missing")
    digest = sha256_file(machine_path)
    _require(
        digest == sha256_file(tracked_path), "machine/tracked holdout seal mismatch"
    )
    seal = load_json(machine_path)
    validate_holdout_seal_payload(seal, raw_qa)
    integrity = hash_only_holdout_integrity(seal, repo_root)
    _require(integrity["status"] == "passed", "holdout seal artifact integrity failed")
    _require(
        integrity["checked_artifact_count"] == 160,
        "holdout seal artifact count mismatch",
    )
    return seal, digest


def validate_access_ledger_events(path: Path, *, seal_sha256: str) -> dict[str, Any]:
    _require(path.is_file(), "access ledger missing")
    result = validate_ledger(path, expected_seal_sha256=seal_sha256)
    _require(result["status"] == "passed", "access ledger hash chain invalid")
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    expected = [
        ("seal_initialized", "S4.4_amendment_sealing", "sealed"),
        ("integrity_validation", "S4.4_amendment_integrity_validation", "hash_only"),
        ("closeout_sealed", "S4.4_amendment_sealing", "sealed"),
    ]
    _require(
        [(item.get("event"), item.get("purpose"), item.get("mode")) for item in records]
        == expected,
        "access ledger contains an unapproved event",
    )
    for item in records:
        _require(
            item.get("allowed") is True
            and item.get("holdout_opened") is False
            and item.get("scientific_outputs_returned") is False,
            "access ledger event crossed scientific boundary",
        )
    return result


def validate_evidence_index_payload(
    index: Mapping[str, Any], *, seal_sha256: str, ledger_sha256: str
) -> list[Mapping[str, Any]]:
    _require(
        index.get("schema") == "ias.s4_4.amendment_03_holdout_evidence_index.v1"
        and index.get("evidence_index_payload_sha256")
        == "69a7b46e58cfc62a5c08955307b419c786e56f4ff16b2a5a470a98f2bbc93fb7",
        "holdout evidence index identity mismatch",
    )
    records = index.get("records")
    _require(
        isinstance(records, list) and index.get("record_count") == len(records) == 360,
        "holdout evidence index count mismatch",
    )
    _require(
        index.get("holdout_seal_sha256") == seal_sha256,
        "holdout evidence index seal mismatch",
    )
    _require(
        index.get("access_ledger_sha256") == ledger_sha256,
        "holdout evidence index ledger mismatch",
    )
    _require(
        index.get("scientifically_opened") is False
        and index.get("scientific_outputs_included") is False,
        "holdout evidence index scientific state invalid",
    )
    seen: set[str] = set()
    for record in records:
        relative = _safe_relative(record.get("path"), "holdout evidence index record")
        _require(relative not in seen, f"duplicate holdout evidence path: {relative}")
        seen.add(relative)
    return records


def validate_evidence_index_records(
    repo_root: Path, path: Path, *, seal_sha256: str, ledger_sha256: str
) -> dict[str, Any]:
    index = load_json(path)
    records = validate_evidence_index_payload(
        index, seal_sha256=seal_sha256, ledger_sha256=ledger_sha256
    )
    for record in records:
        relative = str(record["path"])
        target = repo_root / relative
        _require(target.is_file(), f"holdout evidence missing: {relative}")
        _require(
            target.stat().st_size == record.get("byte_size"),
            f"holdout evidence size mismatch: {relative}",
        )
        _require(
            sha256_file(target) == record.get("sha256"),
            f"holdout evidence hash mismatch: {relative}",
        )
    return index


def validate_closeout_records(
    repo_root: Path,
    *,
    seal_sha256: str,
    ledger_sha256: str,
    index_sha256: str,
) -> dict[str, Any]:
    evidence = repo_root / EVIDENCE_REL
    machine = repo_root / MACHINE_REL / "closeout"
    bindings = {
        "closeout.json": evidence / "holdout_closeout.v1.json",
        "evidence_index.json": evidence / "holdout_evidence_index.v1.json",
        "hash_only_integrity.json": evidence / "holdout_hash_only_integrity.v1.json",
        "immutable_predecessor_proof.json": evidence
        / "immutable_predecessor_proof.v1.json",
    }
    for local_name, tracked in bindings.items():
        local = machine / local_name
        _require(
            local.is_file() and tracked.is_file(),
            f"closeout record missing: {local_name}",
        )
        _require(
            sha256_file(local) == sha256_file(tracked),
            f"machine/tracked closeout mismatch: {local_name}",
        )
    closeout = load_json(evidence / "holdout_closeout.v1.json")
    validate_closeout_payload(
        closeout,
        seal_sha256=seal_sha256,
        ledger_sha256=ledger_sha256,
        index_sha256=index_sha256,
    )
    integrity = load_json(evidence / "holdout_hash_only_integrity.v1.json")
    _require(
        integrity
        == {
            "checked_artifact_count": 160,
            "content_derived_values_returned": False,
            "holdout_opened": False,
            "issues": [],
            "media_returned": False,
            "schema": "ias.s4_4.amendment_hash_only_integrity.v1",
            "scientific_outcomes_returned": False,
            "status": "passed",
        },
        "recorded hash-only integrity report invalid",
    )
    machine_sums = parse_checksum_manifest(
        (machine / "SHA256SUMS").read_text(encoding="utf-8"),
        label=str(machine / "SHA256SUMS"),
        allow_parent=True,
    )
    _require(
        set(machine_sums)
        == {
            "../access/holdout_seal.json",
            "../access/access_ledger.jsonl",
            *bindings,
        },
        "machine closeout checksum coverage mismatch",
    )
    for relative, digest in machine_sums.items():
        target = (machine / relative).resolve()
        _require(
            target.is_relative_to((repo_root / MACHINE_REL).resolve()),
            f"machine closeout checksum escapes evidence root: {relative}",
        )
        _require(
            sha256_file(target) == digest,
            f"machine closeout checksum mismatch: {relative}",
        )
    return closeout


def validate_closeout_payload(
    closeout: Mapping[str, Any],
    *,
    seal_sha256: str,
    ledger_sha256: str,
    index_sha256: str,
) -> None:
    payload = {
        key: value
        for key, value in closeout.items()
        if key != "closeout_payload_sha256"
    }
    _require(closeout.get("status") == "passed", "holdout closeout status invalid")
    _require(
        closeout.get("schema") == "ias.s4_4.amendment_03_holdout_closeout.v1"
        and closeout.get("closeout_payload_sha256") == canonical_sha256(payload),
        "holdout closeout identity/self-hash invalid",
    )
    logical_census = closeout.get("logical_census")
    _require(
        isinstance(logical_census, Mapping)
        and all(
            logical_census.get(key) == value for key, value in EXPECTED_CENSUS.items()
        ),
        "holdout closeout census invalid",
    )
    holdout = closeout.get("holdout", {})
    _require(
        holdout.get("sealed") is True
        and holdout.get("scientifically_opened") is False
        and holdout.get("scientific_outputs_exposed") is False
        and holdout.get("holdout_seal_sha256") == seal_sha256
        and holdout.get("access_ledger_sha256") == ledger_sha256,
        "holdout closeout binding/state invalid",
    )
    _require(
        closeout.get("records", {}).get("evidence_index_sha256") == index_sha256,
        "holdout closeout index mismatch",
    )


def _git_blob(repo_root: Path, commit: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", "--no-ext-diff", f"{commit}:{relative}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    _require(result.returncode == 0, f"Git blob absent: {commit}:{relative}")
    return result.stdout


def _git_commit_exists(repo_root: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    _require(result.returncode == 0, f"Git commit absent: {commit}")


def _git_ancestor(repo_root: Path, older: str, newer: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    _require(result.returncode == 0, f"Git ancestry invalid: {older} !<= {newer}")


def validate_historical_provenance(repo_root: Path) -> dict[str, Any]:
    commits = [
        SOURCE_CHECKPOINT_COMMIT,
        PRECOLLECTION_COMMIT,
        HOLDOUT_CLOSEOUT_COMMIT,
        RECORDED_FINAL_GATE_COMMIT,
    ]
    for commit in commits:
        _git_commit_exists(repo_root, commit)
    for older, newer in zip(commits, commits[1:], strict=False):
        _git_ancestor(repo_root, older, newer)
    evidence = repo_root / EVIDENCE_REL
    checkpoint = load_json(evidence / "freeze/source_checkpoint.v5.json")
    payload = {
        key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"
    }
    _require(
        checkpoint.get("checkpoint_sha256") == canonical_sha256(payload),
        "v5 source checkpoint self-hash mismatch",
    )
    _require(
        checkpoint.get("commit") == SOURCE_CHECKPOINT_COMMIT,
        "v5 source checkpoint commit mismatch",
    )
    for record in checkpoint.get("source_records", []):
        relative = _safe_relative(record.get("path"), "v5 source checkpoint")
        blob = _git_blob(repo_root, SOURCE_CHECKPOINT_COMMIT, relative)
        _require(
            hashlib.sha256(blob).hexdigest() == record.get("sha256"),
            f"v5 historical source mismatch: {relative}",
        )
    version_manifests = {
        "SHA256SUMS": "f7af03045e2743ac3572def2c055bd50f127eb17",
        "SHA256SUMS.v2": "d966fa0b8e75bfe8dab17b1840cc65fc4979951f",
        "SHA256SUMS.v3": "74b0c90f246c9b17e16f2da7706c7c773a44e543",
        "SHA256SUMS.v4": "4783a33ca00b72b10ea41647ec796939a8544d70",
        "SHA256SUMS.v5": PRECOLLECTION_COMMIT,
    }
    checked = 0
    for name, package_commit in version_manifests.items():
        _git_commit_exists(repo_root, package_commit)
        relative_manifest = (EVIDENCE_REL / name).as_posix()
        historical_text = _git_blob(
            repo_root, package_commit, relative_manifest
        ).decode("utf-8")
        _require(
            (evidence / name).read_text(encoding="utf-8") == historical_text,
            f"frozen checksum manifest changed: {name}",
        )
        for relative, digest in parse_checksum_manifest(
            historical_text, label=relative_manifest
        ).items():
            blob = _git_blob(repo_root, package_commit, relative)
            _require(
                hashlib.sha256(blob).hexdigest() == digest,
                f"historical v1-v5 checksum mismatch: {relative}",
            )
            if relative.startswith(EVIDENCE_REL.as_posix() + "/"):
                _require(
                    sha256_file(repo_root / relative) == digest,
                    f"frozen package byte changed: {relative}",
                )
            checked += 1
    closeout_manifest = EVIDENCE_REL / "SHA256SUMS.closeout"
    historical_closeout = _git_blob(
        repo_root, RECORDED_FINAL_GATE_COMMIT, closeout_manifest.as_posix()
    ).decode("utf-8")
    _require(
        closeout_manifest.read_text(encoding="utf-8") == historical_closeout,
        "historical closeout checksum manifest changed",
    )
    for relative, digest in parse_checksum_manifest(
        historical_closeout, label=closeout_manifest.as_posix()
    ).items():
        blob = _git_blob(
            repo_root,
            RECORDED_FINAL_GATE_COMMIT,
            (EVIDENCE_REL / relative).as_posix(),
        )
        _require(
            hashlib.sha256(blob).hexdigest() == digest,
            f"historical closeout checksum mismatch: {relative}",
        )
        _require(
            sha256_file(evidence / relative) == digest,
            f"immutable closeout byte changed: {relative}",
        )
    return {"status": "passed", "historical_checksum_records": checked + 6}


def _tracked(repo_root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _committed_exact(repo_root: Path, relative: str) -> bool:
    if not _tracked(repo_root, relative):
        return False
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _validate_corrective_package(
    repo_root: Path,
    *,
    correction_id: str,
    require_tracked: bool,
    require_committed: bool,
    verify_current_sources: bool,
) -> dict[str, Any]:
    root = repo_root / EVIDENCE_REL / correction_id
    checkpoint_path = root / "source_checkpoint.v1.json"
    index_path = root / "corrective_index.v1.json"
    checksum_path = root / "SHA256SUMS"
    gate_path = (
        repo_root
        / EVIDENCE_REL
        / f"validation/final_closeout_{correction_id}.v1.json"
    )
    for path in (checkpoint_path, index_path, checksum_path, gate_path):
        _require(path.is_file(), f"corrective record missing: {path}")
    checkpoint = _load_self_hashed(
        checkpoint_path,
        "checkpoint_sha256",
        "ias.s4_4.amendment_03_corrective_source_checkpoint.v1",
    )
    index = _load_self_hashed(
        index_path,
        "corrective_index_sha256",
        "ias.s4_4.amendment_03_corrective_index.v1",
    )
    gate = _load_self_hashed(
        gate_path,
        "gate_sha256",
        "ias.s4_4.amendment_03_final_closeout_corrective.v1",
    )
    source_commit = str(checkpoint.get("source_commit"))
    _git_commit_exists(repo_root, source_commit)
    _git_ancestor(repo_root, RECORDED_FINAL_GATE_COMMIT, source_commit)
    _git_ancestor(repo_root, source_commit, "HEAD")
    source_records = checkpoint.get("source_records", [])
    _require(isinstance(source_records, list), "corrective source records invalid")
    source_paths: set[str] = set()
    for record in source_records:
        relative = _safe_relative(record.get("path"), "corrective source checkpoint")
        _require(relative not in source_paths, "duplicate corrective source path")
        source_paths.add(relative)
        blob = _git_blob(repo_root, source_commit, relative)
        _require(
            hashlib.sha256(blob).hexdigest() == record.get("sha256"),
            f"corrective source Git blob mismatch: {relative}",
        )
        if verify_current_sources:
            _require(
                sha256_file(repo_root / relative) == record.get("sha256"),
                f"corrective source checkout mismatch: {relative}",
            )
    records = index.get("records")
    _require(
        isinstance(records, list) and index.get("record_count") == len(records),
        "corrective index count mismatch",
    )
    expected: dict[str, str] = {}
    for record in records:
        relative = _safe_relative(record.get("path"), "corrective record")
        _require(relative not in expected, f"duplicate corrective path: {relative}")
        if relative in source_paths or record.get("role") == "corrected_source":
            source_blob = _git_blob(repo_root, source_commit, relative)
            _require(
                len(source_blob) == record.get("byte_size")
                and hashlib.sha256(source_blob).hexdigest() == record.get("sha256"),
                f"corrective historical source mismatch: {relative}",
            )
            if verify_current_sources:
                _require(
                    sha256_file(repo_root / relative) == record.get("sha256"),
                    f"corrected file checkout mismatch: {relative}",
                )
        elif (
            correction_id == "corrective_01"
            and record.get("role") == "authoritative_final_closeout"
        ):
            source_blob = _git_blob(
                repo_root, CORRECTIVE_01_PACKAGE_COMMIT, relative
            )
            _require(
                len(source_blob) == record.get("byte_size")
                and hashlib.sha256(source_blob).hexdigest() == record.get("sha256"),
                f"corrective historical closeout mismatch: {relative}",
            )
        else:
            target = repo_root / relative
            _require(target.is_file(), f"corrective file missing: {relative}")
            _require(
                target.stat().st_size == record.get("byte_size")
                and sha256_file(target) == record.get("sha256"),
                f"corrective file mismatch: {relative}",
            )
        expected[relative] = str(record["sha256"])
    checksums = parse_checksum_manifest(
        checksum_path.read_text(encoding="utf-8"), label=str(checksum_path)
    )
    _require(checksums == expected, "corrective checksum/index coverage mismatch")
    _require(
        index.get("source_checkpoint_sha256") == sha256_file(checkpoint_path),
        "corrective checkpoint binding mismatch",
    )
    _require(
        index.get("final_gate_sha256") == sha256_file(gate_path),
        "corrective final-gate binding mismatch",
    )
    _require(
        index.get("correction_id") == correction_id
        and index.get("census") == EXPECTED_CENSUS
        and index.get("reduced_mac_readiness_authoritative") is True
        and index.get("legacy_readiness_extra_fields_optional") is True
        and index.get("historical_v1_v5_rewritten") is False
        and index.get("historical_closeout_checksums_rewritten") is False
        and index.get("prospective_holdout_scientifically_opened") is False
        and index.get("S4.5_or_later_started") is False,
        "corrective index contract mismatch",
    )
    _require(
        gate.get("source_commit") == source_commit,
        "corrective final gate source mismatch",
    )
    _require(
        gate.get("census") == EXPECTED_CENSUS and gate.get("status") == "passed",
        "corrective final gate census/status invalid",
    )
    holdout_opened = (
        gate.get("holdout", {}).get("scientifically_opened")
        if correction_id == "corrective_01"
        else gate.get("holdout_scientifically_opened")
    )
    outcomes_exposed = (
        gate.get("holdout", {}).get("scientific_outputs_exposed")
        if correction_id == "corrective_01"
        else gate.get("scientific_outcomes_returned")
    )
    _require(
        holdout_opened is False and outcomes_exposed is False,
        "corrective final gate opened holdout",
    )
    if correction_id == "corrective_02":
        previous_paths = {
            "corrective_01/SHA256SUMS": (
                repo_root / EVIDENCE_REL / "corrective_01/SHA256SUMS"
            ),
            "corrective_01/corrective_index.v1.json": (
                repo_root
                / EVIDENCE_REL
                / "corrective_01/corrective_index.v1.json"
            ),
            "corrective_01/source_checkpoint.v1.json": (
                repo_root
                / EVIDENCE_REL
                / "corrective_01/source_checkpoint.v1.json"
            ),
            "validation/final_closeout_corrective_01.v1.json": (
                repo_root
                / EVIDENCE_REL
                / "validation/final_closeout_corrective_01.v1.json"
            ),
        }
        expected_previous = {
            relative: sha256_file(path)
            for relative, path in sorted(previous_paths.items())
        }
        _require(
            checkpoint.get("supersedes_correction_id") == "corrective_01"
            and index.get("supersedes_correction_id") == "corrective_01"
            and checkpoint.get("previous_corrective_sha256") == expected_previous
            and index.get("previous_corrective_sha256") == expected_previous,
            "corrective-02 predecessor binding mismatch",
        )
    if require_tracked or require_committed:
        for path in (checkpoint_path, index_path, checksum_path, gate_path):
            relative = path.relative_to(repo_root).as_posix()
            _require(
                _tracked(repo_root, relative),
                f"corrective record not tracked: {relative}",
            )
            if require_committed:
                _require(
                    _committed_exact(repo_root, relative),
                    f"corrective record not committed exact: {relative}",
                )
    return {
        "status": "passed",
        "correction_id": correction_id,
        "record_count": len(records),
        "source_commit": source_commit,
    }


def validate_corrective_records(
    repo_root: Path, *, require_tracked: bool, require_committed: bool
) -> dict[str, Any]:
    historical = _validate_corrective_package(
        repo_root,
        correction_id="corrective_01",
        require_tracked=require_tracked,
        require_committed=require_committed,
        verify_current_sources=False,
    )
    current = _validate_corrective_package(
        repo_root,
        correction_id="corrective_02",
        require_tracked=require_tracked,
        require_committed=require_committed,
        verify_current_sources=True,
    )
    return {
        "status": "passed",
        "correction_id": "corrective_02",
        "record_count": historical["record_count"] + current["record_count"],
        "source_commit": current["source_commit"],
        "immutable_predecessor": historical,
    }


def validate(
    *,
    repo_root: Path,
    require_tracked: bool,
    require_committed: bool,
    require_machine_local: bool,
    require_corrective: bool,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if require_committed:
        require_tracked = True
    authoritative_final = all(
        (
            require_tracked,
            require_committed,
            require_machine_local,
            require_corrective,
        )
    )
    issues: list[dict[str, str]] = []
    results: dict[str, Any] = {}

    def run(label: str, function: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            value = function(*args, **kwargs)
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            issues.append(_issue(label, label, str(exc)))
            return None
        return value

    results["historical_provenance"] = run(
        "historical_provenance_invalid", validate_historical_provenance, repo_root
    )
    census_and_paths = None
    if require_machine_local:
        census_and_paths = run(
            "attempt_evidence_invalid", validate_all_attempts, repo_root
        )
    canonical_qa = raw_qa = None
    if census_and_paths is not None:
        qa_value = run(
            "holdout_qa_invalid",
            validate_holdout_qa_records,
            repo_root,
            census_and_paths[1],
        )
        if qa_value is not None:
            canonical_qa, raw_qa = qa_value
    seal_value = None
    if raw_qa is not None:
        seal_value = run(
            "holdout_seal_invalid", validate_holdout_seals, repo_root, raw_qa
        )
    ledger = None
    if seal_value is not None:
        ledger_path = repo_root / MACHINE_REL / "access/access_ledger.jsonl"
        ledger = run(
            "access_ledger_invalid",
            validate_access_ledger_events,
            ledger_path,
            seal_sha256=seal_value[1],
        )
    index = None
    if seal_value is not None and ledger is not None:
        index_path = repo_root / EVIDENCE_REL / "holdout_evidence_index.v1.json"
        ledger_path = repo_root / MACHINE_REL / "access/access_ledger.jsonl"
        index = run(
            "holdout_index_invalid",
            validate_evidence_index_records,
            repo_root,
            index_path,
            seal_sha256=seal_value[1],
            ledger_sha256=sha256_file(ledger_path),
        )
    if index is not None and seal_value is not None:
        results["closeout_records"] = run(
            "closeout_record_invalid",
            validate_closeout_records,
            repo_root,
            seal_sha256=seal_value[1],
            ledger_sha256=sha256_file(
                repo_root / MACHINE_REL / "access/access_ledger.jsonl"
            ),
            index_sha256=sha256_file(
                repo_root / EVIDENCE_REL / "holdout_evidence_index.v1.json"
            ),
        )
    if require_corrective:
        results["corrective_records"] = run(
            "corrective_record_invalid",
            validate_corrective_records,
            repo_root,
            require_tracked=require_tracked,
            require_committed=require_committed,
        )
    try:
        config = load_json(
            repo_root / "configs/s4_4_data_expansion_amendment_03.v1.json"
        )
        results["immutable_predecessors"] = validate_predecessor_bytes(
            config, repo_root, require_machine_local=require_machine_local
        )
    except (OSError, ValueError) as exc:
        issues.append(
            _issue("immutable_predecessor_invalid", "amendments_01_02", str(exc))
        )
    tracked_dataset = subprocess.run(
        ["git", "ls-files", "dataset"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked_dataset:
        issues.append(_issue("dataset_tracked", "dataset", tracked_dataset))
    later_phase_artifacts = detect_later_phase_artifacts(repo_root)
    for relative in later_phase_artifacts:
        issues.append(
            _issue(
                "later_phase_artifact_present",
                relative,
                "phase-owned S4.5-S4.8 artifact present",
            )
        )
    holdout_validated = (
        index is not None
        and seal_value is not None
        and ledger is not None
        and results.get("closeout_records") is not None
    )
    status = (
        "failed"
        if issues
        else "passed"
        if authoritative_final
        else "incomplete"
    )
    return {
        "schema": "ias.s4_4.amendment_03_final_closeout_validation.v1",
        "source_commit": _git_head(repo_root),
        "status": status,
        "validation_scope": (
            "authoritative_final" if authoritative_final else "diagnostic_incomplete"
        ),
        "authoritative_final": authoritative_final and not issues,
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "require_machine_local": require_machine_local,
        "require_corrective": require_corrective,
        "census": census_and_paths[0] if census_and_paths else None,
        "attempt_checksum_sets": EXPECTED_ATTEMPTS if census_and_paths else None,
        "holdout_technical_qa_records": len(canonical_qa) if canonical_qa else None,
        "holdout_scientifically_opened": False if holdout_validated else None,
        "scientific_outcomes_returned": False,
        "S4.5_or_later_started": bool(later_phase_artifacts),
        "later_phase_artifacts": later_phase_artifacts,
        "results": results,
        "issues": issues,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--require-tracked", action="store_true", default=True)
    parser.add_argument("--require-committed", action="store_true", default=True)
    parser.add_argument("--require-machine-local", action="store_true", default=True)
    parser.add_argument("--require-corrective", action="store_true", default=True)
    args = parser.parse_args(argv)
    result = validate(
        repo_root=args.repo_root,
        require_tracked=args.require_tracked,
        require_committed=args.require_committed,
        require_machine_local=args.require_machine_local,
        require_corrective=args.require_corrective,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
