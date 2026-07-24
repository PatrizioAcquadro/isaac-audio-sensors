from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    load_json,
    sha256_file,
)
from scripts.validate_s4_4_amendment_03_final import (
    EVIDENCE_REL,
    MACHINE_REL,
    parse_checksum_manifest,
    validate,
    validate_access_ledger_events,
    validate_all_attempts,
    validate_attempt_directory,
    validate_closeout_payload,
    validate_evidence_index_payload,
    validate_holdout_qa_records,
    validate_holdout_seal_payload,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def retained_attempt_paths() -> dict[str, Path]:
    _, paths = validate_all_attempts(ROOT)
    return paths


@pytest.fixture
def one_attempt(tmp_path: Path) -> Path:
    source = next(
        path
        for path in (
            ROOT / "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/attempts"
        ).glob("s44a03_fit_b_001_sil/*")
        if path.is_dir()
    )
    target = tmp_path / source.name
    shutil.copytree(source, target)
    validate_attempt_directory(target)
    return target


def test_explicit_machine_local_final_closeout_validation_passes() -> None:
    result = validate(
        repo_root=ROOT,
        require_tracked=True,
        require_committed=False,
        require_machine_local=True,
        require_corrective=False,
    )
    assert result["status"] == "passed", result["issues"]
    assert result["census"] == {
        "valid_cells_total": 149,
        "retained_attempts_total": 152,
        "failures_total": 3,
        "replacements_total": 3,
        "incomplete_logical_cells": 0,
    }
    assert result["attempt_checksum_sets"] == {
        "fit_a": 52,
        "fit_b": 52,
        "prospective_holdout": 48,
    }
    assert result["holdout_technical_qa_records"] == 47
    assert result["scientific_outcomes_returned"] is False


@pytest.mark.parametrize(
    "tamper",
    ["altered_artifact", "missing_artifact", "duplicate_checksum", "mismatch"],
)
def test_attempt_and_checksum_tamper_fails(one_attempt: Path, tamper: str) -> None:
    qa_path = one_attempt / "technical_qa.json"
    sums_path = one_attempt / "SHA256SUMS"
    if tamper == "altered_artifact":
        qa_path.write_bytes(qa_path.read_bytes() + b"\n")
    elif tamper == "missing_artifact":
        qa_path.unlink()
    elif tamper == "duplicate_checksum":
        first = sums_path.read_text(encoding="utf-8").splitlines()[0]
        sums_path.write_text(
            sums_path.read_text(encoding="utf-8") + first + "\n",
            encoding="utf-8",
        )
    else:
        manifest_path = one_attempt / "manifest.json"
        manifest = load_json(manifest_path)
        manifest["artifacts"][0]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(S44AmendmentError):
        validate_attempt_directory(one_attempt)


def _qa_fixture(tmp_path: Path, attempt_paths: dict[str, Path]) -> tuple[Path, Path]:
    manifest_source = (
        ROOT / EVIDENCE_REL / "manifests/sessions/prospective_holdout.json"
    )
    manifest_target = (
        tmp_path / EVIDENCE_REL / ("manifests/sessions/prospective_holdout.json")
    )
    manifest_target.parent.mkdir(parents=True)
    shutil.copy2(manifest_source, manifest_target)
    qa_source = ROOT / MACHINE_REL / "access/technical_qa"
    qa_target = tmp_path / MACHINE_REL / "access/technical_qa"
    shutil.copytree(qa_source, qa_target)
    canonical, _ = validate_holdout_qa_records(tmp_path, attempt_paths)
    assert len(canonical) == 47
    return qa_target, next(iter(sorted(qa_target.glob("*.json"))))


@pytest.mark.parametrize("tamper", ["altered", "missing", "duplicated", "mismatched"])
def test_holdout_qa_tamper_fails(
    tmp_path: Path, retained_attempt_paths: dict[str, Path], tamper: str
) -> None:
    qa_root, qa_path = _qa_fixture(tmp_path, retained_attempt_paths)
    if tamper == "altered":
        record = load_json(qa_path)
        record["scientific_metric"] = 1
        qa_path.write_text(json.dumps(record), encoding="utf-8")
    elif tamper == "missing":
        qa_path.unlink()
    elif tamper == "duplicated":
        shutil.copy2(qa_path, qa_root / "duplicate.json")
    else:
        record = load_json(qa_path)
        record["attempt_id"] = "unknown__attempt_01"
        qa_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(S44AmendmentError):
        validate_holdout_qa_records(tmp_path, retained_attempt_paths)


def _raw_qa() -> dict[str, dict]:
    return {
        path.stem: load_json(path)
        for path in sorted((ROOT / MACHINE_REL / "access/technical_qa").glob("*.json"))
    }


@pytest.mark.parametrize("tamper", ["altered", "missing", "duplicated"])
def test_holdout_seal_tamper_fails(tamper: str) -> None:
    seal = load_json(ROOT / EVIDENCE_REL / "holdout_seal.v1.json")
    qa = _raw_qa()
    if tamper == "altered":
        seal["scientifically_opened"] = True
    elif tamper == "missing":
        qa.pop(next(iter(qa)))
    else:
        seal["artifacts"].append(copy.deepcopy(seal["artifacts"][0]))
        payload = {
            key: value for key, value in seal.items() if key != "seal_payload_sha256"
        }
        seal["seal_payload_sha256"] = canonical_sha256(payload)
    with pytest.raises(S44AmendmentError):
        validate_holdout_seal_payload(seal, qa)


def test_access_ledger_tamper_fails(tmp_path: Path) -> None:
    source = ROOT / MACHINE_REL / "access/access_ledger.jsonl"
    target = tmp_path / "access_ledger.jsonl"
    shutil.copy2(source, target)
    seal_sha = sha256_file(ROOT / EVIDENCE_REL / "holdout_seal.v1.json")
    validate_access_ledger_events(target, seal_sha256=seal_sha)
    lines = target.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[1])
    event["mode"] = "scientific"
    lines[1] = json.dumps(event, separators=(",", ":"), sort_keys=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(S44AmendmentError):
        validate_access_ledger_events(target, seal_sha256=seal_sha)


@pytest.mark.parametrize("tamper", ["duplicate", "seal_mismatch", "count_mismatch"])
def test_holdout_index_tamper_fails(tamper: str) -> None:
    index = load_json(ROOT / EVIDENCE_REL / "holdout_evidence_index.v1.json")
    if tamper == "duplicate":
        index["records"].append(copy.deepcopy(index["records"][0]))
        index["record_count"] += 1
    elif tamper == "seal_mismatch":
        index["holdout_seal_sha256"] = "0" * 64
    else:
        index["record_count"] -= 1
    with pytest.raises(S44AmendmentError):
        validate_evidence_index_payload(
            index,
            seal_sha256=sha256_file(ROOT / EVIDENCE_REL / "holdout_seal.v1.json"),
            ledger_sha256=sha256_file(
                ROOT / MACHINE_REL / "access/access_ledger.jsonl"
            ),
        )


def test_closeout_binding_tamper_fails() -> None:
    closeout = load_json(ROOT / EVIDENCE_REL / "holdout_closeout.v1.json")
    closeout["logical_census"]["retained_attempts_total"] = 151
    payload = {
        key: value
        for key, value in closeout.items()
        if key != "closeout_payload_sha256"
    }
    closeout["closeout_payload_sha256"] = canonical_sha256(payload)
    with pytest.raises(S44AmendmentError):
        validate_closeout_payload(
            closeout,
            seal_sha256=sha256_file(ROOT / EVIDENCE_REL / "holdout_seal.v1.json"),
            ledger_sha256=sha256_file(
                ROOT / MACHINE_REL / "access/access_ledger.jsonl"
            ),
            index_sha256=sha256_file(
                ROOT / EVIDENCE_REL / "holdout_evidence_index.v1.json"
            ),
        )


@pytest.mark.parametrize(
    "text",
    [
        f"{'0' * 64}  a\n{'1' * 64}  a\n",
        f"{'0' * 63}  a\n",
        f"{'0' * 64} a\n",
    ],
)
def test_checksum_parser_fails_closed(text: str) -> None:
    with pytest.raises(S44AmendmentError):
        parse_checksum_manifest(text, label="tampered")
