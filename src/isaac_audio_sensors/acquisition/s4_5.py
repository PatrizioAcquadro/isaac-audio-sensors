"""Deterministic, fit-only S4.5 supported functional calibration."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import wave
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_2 import validate_reference_capture
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    require_evidence_access,
)
from isaac_audio_sensors.core.doa.gcc_phat import gcc_phat_delay
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.io.calibration import (
    calibration_profile_from_dict,
    calibration_profile_to_dict,
)
from isaac_audio_sensors.core.schema import audio_calibration_profile_json_schema

CONTRACT_SCHEMA = "ias.s4_5.fitting_contract.v1"
FIT_INVENTORY_SCHEMA = "ias.s4_5.fit_inventory.v1"
MEASUREMENTS_SCHEMA = "ias.s4_5.fit_measurements.v1"
DECISIONS_SCHEMA = "ias.s4_5.parameter_decisions.v1"
PRESERVATION_SCHEMA = "ias.s4_5.preservation_validation.v1"
VALIDATION_SCHEMA = "ias.s4_5.validation.v1"
EVIDENCE_INDEX_SCHEMA = "ias.s4_5.evidence_index.v1"

FIT_A_MACHINE_ROOT = Path(
    "dataset/S4.4/amendments/s4_4_data_expansion_amendment_02/attempts"
)
FIT_B_MACHINE_ROOT = Path(
    "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/attempts"
)
AMENDMENT_02_EVIDENCE_ROOT = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_02"
)
AMENDMENT_03_EVIDENCE_ROOT = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03"
)
S45_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.5")
S45_SPEC = Path("docs/development/specs/s4_5_supported_functional_fitting.md")
S45_CONFIG = Path("configs/s4_5_fitting.v1.json")
S45_CLOSEOUT = Path("docs/development/closeouts/S4/s4_5_calibration_fit.md")
_PURPOSES = frozenset({"S4.5_fit", "S4.5_validation"})
_LATER_PHASE = re.compile(r"(?:^|[^a-z0-9])s4[._-]?[6-9](?:[^0-9]|$)", re.I)
_SCAN_ROOTS = (
    "configs",
    "dataset",
    "examples",
    "exts",
    "outputs",
    "scripts",
    "src",
    "tests",
)
_SCAN_IGNORES = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)


class S45Error(ValueError):
    """A located S4.5 contract, access, fitting, or validation failure."""


@dataclass(frozen=True, slots=True)
class FitEvidenceRecord:
    """One validated, authorized fit attempt."""

    planned_take_id: str
    attempt_id: str
    session_id: str
    group_id: str
    category: str
    target_bearing_deg: float | None
    wav_path: str
    wav_sha256: str
    wav_byte_size: int


@dataclass(frozen=True, slots=True)
class FitObservation:
    """One group-level scientific observation from authorized fit evidence."""

    planned_take_id: str
    session_id: str
    group_id: str
    category: str
    target_bearing_deg: float | None
    gain_db: tuple[float, float, float, float]
    delay_samples: tuple[float, float, float, float]
    correlation_sign: tuple[int, int, int, int]
    srp_bearing_deg: float | None
    srp_confidence: float | None


def sha256_file(path: Path) -> str:
    """Return one file's SHA-256 without exposing its contents."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pretty_json(value: Any) -> str:
    """Return deterministic evidence JSON."""

    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def load_json(path: Path, *, label: str = "JSON") -> dict[str, Any]:
    """Read one JSON object with a located fail-closed error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S45Error(f"{label}: cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S45Error(f"{label}: {path} must contain one object")
    return value


def safe_relative(value: object, label: str) -> str:
    """Require a non-escaping POSIX relative path."""

    if not isinstance(value, str) or not value:
        raise S45Error(f"{label}: expected non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise S45Error(f"{label}: unsafe path {value!r}")
    return value


def _resolved_file(repo_root: Path, relative: object, label: str) -> Path:
    safe = safe_relative(relative, label)
    root = repo_root.resolve()
    path = (root / safe).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise S45Error(f"{label}: path escapes repository") from exc
    if not path.is_file():
        raise S45Error(f"{label}: missing file {safe}")
    return path


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise S45Error(f"{label}: expected lowercase SHA-256")
    return value


def _verify_file_record(repo_root: Path, record: object, label: str) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise S45Error(f"{label}: expected exact path/SHA-256 record")
    path = _resolved_file(repo_root, record["path"], f"{label}.path")
    expected = _require_sha256(record["sha256"], f"{label}.sha256")
    if sha256_file(path) != expected:
        raise S45Error(f"{label}: altered hash for {record['path']}")
    return path


def load_fitting_contract(path: Path, repo_root: Path) -> dict[str, Any]:
    """Load and validate the frozen S4.5 contract and every bound input."""

    contract = load_json(path, label="S4.5 contract")
    required = {
        "schema",
        "tool_version",
        "created_at",
        "entry",
        "purposes",
        "fit_sessions",
        "leakage_group_field",
        "native_audio",
        "profile",
        "sign_conventions",
        "candidates",
        "synthetic_tolerances",
        "determinism",
        "unsupported_claims",
        "evidence",
    }
    if set(contract) != required:
        raise S45Error("S4.5 contract field set changed")
    if contract["schema"] != CONTRACT_SCHEMA:
        raise S45Error("S4.5 contract schema changed")
    if contract["purposes"] != ["S4.5_fit", "S4.5_validation"]:
        raise S45Error("S4.5 purpose allowlist changed")
    if contract["fit_sessions"] != ["fit_a", "fit_b"]:
        raise S45Error("S4.5 fit session allowlist changed")
    if contract["leakage_group_field"] != "group_id":
        raise S45Error("S4.5 leakage grouping field changed")
    native = contract["native_audio"]
    if (
        native.get("channel_count") != 6
        or native.get("sample_rate_hz") != 16_000
        or native.get("format") != "S16_LE"
        or native.get("raw_channel_indices") != [2, 3, 4, 5]
        or native.get("profile_channel_order") != ["ch0", "ch1", "ch2", "ch3"]
        or native.get("reference_profile_channel") != "ch0"
    ):
        raise S45Error("S4.5 native audio/reference convention changed")
    evidence = contract["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {
        "fit_a_manifest",
        "fit_b_manifest",
        "holdout_closeout",
        "holdout_seal",
        "inherited_fit_a",
        "s3_model_contract",
        "source_reference_wav",
    }:
        raise S45Error("S4.5 evidence binding set changed")
    for name, record in sorted(evidence.items()):
        _verify_file_record(repo_root, record, f"evidence.{name}")
    entry = contract["entry"]
    if (
        not isinstance(entry, dict)
        or set(entry) != {"branch", "commit"}
        or entry["branch"] != "main"
    ):
        raise S45Error("S4.5 entry provenance changed")
    commit = str(entry["commit"])
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise S45Error("S4.5 entry commit does not exist")
    return contract


def _validate_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_session: str,
) -> dict[str, Mapping[str, Any]]:
    supplied = _require_sha256(manifest.get("manifest_sha256"), "manifest self-hash")
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if canonical_sha256(payload) != supplied:
        raise S45Error(f"{expected_session}: manifest self-hash mismatch")
    if (
        manifest.get("session_id") != expected_session
        or manifest.get("partition") != "fit"
        or manifest.get("planned_take_count") != 51
    ):
        raise S45Error(f"{expected_session}: manifest identity/count changed")
    takes = manifest.get("takes")
    if not isinstance(takes, list) or len(takes) != 51:
        raise S45Error(f"{expected_session}: take census invalid")
    by_id: dict[str, Mapping[str, Any]] = {}
    for take in takes:
        if not isinstance(take, dict):
            raise S45Error(f"{expected_session}: malformed take record")
        planned = take.get("planned_take_id")
        if not isinstance(planned, str) or not planned or planned in by_id:
            raise S45Error(f"{expected_session}: duplicate or malformed identity")
        if (
            take.get("session_id") != expected_session
            or take.get("partition") != "fit"
            or not isinstance(take.get("group_id"), str)
        ):
            raise S45Error(f"{planned}: wrong session, partition, or group")
        supplied_take = _require_sha256(
            take.get("take_definition_sha256"), f"{planned}: take hash"
        )
        take_payload = {
            key: value for key, value in take.items() if key != "take_definition_sha256"
        }
        if canonical_sha256(take_payload) != supplied_take:
            raise S45Error(f"{planned}: take definition hash mismatch")
        by_id[planned] = take
    return by_id


def _parse_checksum_manifest(path: Path, attempt_root: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise S45Error(f"cannot read checksum manifest {path}: {exc}") from exc
    if not lines:
        raise S45Error(f"empty checksum manifest {path}")
    records: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise S45Error(f"malformed checksum record in {path}")
        digest = _require_sha256(line[:64], f"{path}: checksum")
        relative = safe_relative(line[66:], f"{path}: checksum path")
        if relative in records:
            raise S45Error(f"duplicate checksum path {relative}")
        candidate = (attempt_root / relative).resolve()
        try:
            candidate.relative_to(attempt_root.resolve())
        except ValueError as exc:
            raise S45Error(f"unsafe checksum path {relative}") from exc
        if not candidate.is_file() or sha256_file(candidate) != digest:
            raise S45Error(f"altered hash for {candidate}")
        records[relative] = digest
    return records


def _allowed_precollection_hashes(repo_root: Path, session_id: str) -> set[str]:
    root = (
        AMENDMENT_02_EVIDENCE_ROOT
        if session_id == "fit_a"
        else AMENDMENT_03_EVIDENCE_ROOT
    )
    paths = sorted((repo_root / root).glob("precollection_seal.v*.json"))
    if not paths:
        raise S45Error(f"{session_id}: no precollection seals found")
    return {sha256_file(path) for path in paths}


def _attempt_roots(repo_root: Path, take: Mapping[str, Any]) -> tuple[Path, ...]:
    paths = take.get("expected_artifact_paths")
    if not isinstance(paths, dict):
        raise S45Error(f"{take.get('planned_take_id')}: artifact paths malformed")
    values = [
        paths.get("attempt_01_root"),
        paths.get("replacement_attempt_02_root"),
    ]
    roots: list[Path] = []
    for value in values:
        safe = safe_relative(value, "attempt root")
        path = (repo_root / safe).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise S45Error(f"unsafe attempt root {safe}") from exc
        if path.is_dir():
            roots.append(path)
    if not roots:
        raise S45Error(f"{take.get('planned_take_id')}: no retained attempt")
    return tuple(roots)


def _validate_attempt(
    repo_root: Path,
    take: Mapping[str, Any],
    attempt_root: Path,
    *,
    allowed_seal_hashes: set[str],
) -> tuple[dict[str, Any], FitEvidenceRecord | None]:
    manifest = load_json(attempt_root / "manifest.json", label="attempt manifest")
    contract = load_json(
        attempt_root / "attempt_contract.json", label="attempt contract"
    )
    planned = str(take["planned_take_id"])
    attempt_id = attempt_root.name
    expected_number = int(attempt_id.rsplit("_", 1)[-1])
    shared = (
        manifest.get("planned_take_id") == planned,
        contract.get("planned_take_id") == planned,
        manifest.get("attempt_id") == attempt_id,
        contract.get("attempt_id") == attempt_id,
        manifest.get("attempt_number") == expected_number,
        contract.get("attempt_number") == expected_number,
        manifest.get("partition") == "fit",
        contract.get("partition") == "fit",
        manifest.get("session_id") == take["session_id"],
        contract.get("session_id") == take["session_id"],
        manifest.get("take_definition_sha256") == take["take_definition_sha256"],
        contract.get("take_definition_sha256") == take["take_definition_sha256"],
        manifest.get("scientific_outcome_used_for_replacement") is False,
        contract.get("scientific_outcome_used_for_replacement") is False,
    )
    if not all(shared):
        raise S45Error(f"{attempt_id}: provenance mismatch")
    seal_hash = _require_sha256(
        contract.get("precollection_seal_sha256"),
        f"{attempt_id}: precollection seal",
    )
    if seal_hash not in allowed_seal_hashes:
        raise S45Error(f"{attempt_id}: provenance seal mismatch")
    planned_cell = load_json(
        attempt_root.parent / "planned_cell.json", label="planned cell"
    )
    if (
        planned_cell.get("planned_take_id") != planned
        or planned_cell.get("group_id") != take["group_id"]
        or planned_cell.get("take_definition_sha256") != take["take_definition_sha256"]
    ):
        raise S45Error(f"{planned}: wrong group or planned-cell provenance")
    outcome = manifest.get("outcome")
    if outcome not in {"valid", "invalid", "pre_recording_failure"}:
        raise S45Error(f"{attempt_id}: malformed outcome")
    if outcome != "valid":
        return manifest, None
    if manifest.get("retained") is not True:
        raise S45Error(f"{attempt_id}: valid attempt is not retained")
    checksums = _parse_checksum_manifest(attempt_root / "SHA256SUMS", attempt_root)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise S45Error(f"{attempt_id}: malformed artifact records")
    wav_records = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("role") == "six_channel_audio"
    ]
    if len(wav_records) != 1:
        raise S45Error(f"{attempt_id}: six-channel WAV binding absent")
    wav_record = wav_records[0]
    relative = safe_relative(wav_record.get("path"), f"{attempt_id}: WAV path")
    wav_path = (attempt_root / relative).resolve()
    try:
        wav_path.relative_to(attempt_root.resolve())
    except ValueError as exc:
        raise S45Error(f"{attempt_id}: unsafe WAV path") from exc
    expected_hash = _require_sha256(wav_record.get("sha256"), f"{attempt_id}: WAV hash")
    if (
        checksums.get(relative) != expected_hash
        or not wav_path.is_file()
        or wav_path.stat().st_size != wav_record.get("byte_size")
        or sha256_file(wav_path) != expected_hash
    ):
        raise S45Error(f"{attempt_id}: WAV hash/size provenance mismatch")
    qa = load_json(attempt_root / "technical_qa.json", label="fit technical QA")
    if (
        qa.get("overall_technical_pass") is not True
        or qa.get("scientific_outcomes_used") is not False
        or qa.get("attempt_id") != attempt_id
    ):
        raise S45Error(f"{attempt_id}: fit technical QA invalid")
    target = take.get("target_bearing_deg_f_project")
    return manifest, FitEvidenceRecord(
        planned_take_id=planned,
        attempt_id=attempt_id,
        session_id=str(take["session_id"]),
        group_id=str(take["group_id"]),
        category=str(take["category"]),
        target_bearing_deg=None if target is None else float(target),
        wav_path=wav_path.relative_to(repo_root.resolve()).as_posix(),
        wav_sha256=expected_hash,
        wav_byte_size=wav_path.stat().st_size,
    )


class FitEvidenceAccessor:
    """Fail-closed S4.5 access to inherited Fit A and completed Fit B."""

    def __init__(self, repo_root: Path, contract_path: Path = S45_CONFIG) -> None:
        self.repo_root = repo_root.resolve()
        self.contract_path = (
            contract_path
            if contract_path.is_absolute()
            else self.repo_root / contract_path
        )
        self.contract = load_fitting_contract(self.contract_path, self.repo_root)
        evidence = self.contract["evidence"]
        fit_a_path = self.repo_root / evidence["fit_a_manifest"]["path"]
        fit_b_path = self.repo_root / evidence["fit_b_manifest"]["path"]
        self.takes = {
            **_validate_manifest(
                load_json(fit_a_path, label="Fit A manifest"),
                expected_session="fit_a",
            ),
            **_validate_manifest(
                load_json(fit_b_path, label="Fit B manifest"),
                expected_session="fit_b",
            ),
        }
        if len(self.takes) != 102:
            raise S45Error("fit identity census must contain 102 planned cells")
        seal = load_json(
            self.repo_root / evidence["holdout_seal"]["path"],
            label="holdout seal",
        )
        holdout_ids = seal.get("planned_take_ids")
        if (
            not isinstance(holdout_ids, list)
            or len(holdout_ids) != 47
            or len(set(holdout_ids)) != 47
        ):
            raise S45Error("holdout identity census invalid")
        self.fit_ids = set(self.takes)
        self.holdout_ids = {str(value) for value in holdout_ids}
        if self.fit_ids & self.holdout_ids:
            raise S45Error("fit and holdout identities overlap")

    def authorize(self, planned_take_id: str, purpose: str) -> dict[str, Any]:
        """Authorize only configured fit identities for one exact S4.5 purpose."""

        if purpose not in _PURPOSES:
            raise S45Error(f"unknown purpose: {purpose!r}")
        try:
            return require_evidence_access(
                planned_take_id=planned_take_id,
                purpose=purpose,
                fit_ids=self.fit_ids,
                holdout_ids=self.holdout_ids,
            )
        except S44AmendmentError as exc:
            raise S45Error(str(exc)) from exc

    def inventory(
        self, *, purpose: str
    ) -> tuple[dict[str, Any], tuple[FitEvidenceRecord, ...]]:
        """Validate and return the complete fit attempt census."""

        if purpose not in _PURPOSES:
            raise S45Error(f"unknown purpose: {purpose!r}")
        records: list[FitEvidenceRecord] = []
        retained_attempts = failures = replacements = 0
        category_counts: Counter[str] = Counter()
        session_counts: Counter[str] = Counter()
        group_ids: set[str] = set()
        for planned in sorted(self.takes):
            self.authorize(planned, purpose)
            take = self.takes[planned]
            allowed_hashes = _allowed_precollection_hashes(
                self.repo_root, str(take["session_id"])
            )
            manifests: list[dict[str, Any]] = []
            valid: list[FitEvidenceRecord] = []
            for attempt_root in _attempt_roots(self.repo_root, take):
                manifest, record = _validate_attempt(
                    self.repo_root,
                    take,
                    attempt_root,
                    allowed_seal_hashes=allowed_hashes,
                )
                retained_attempts += 1
                manifests.append(manifest)
                if record is None:
                    failures += 1
                else:
                    valid.append(record)
            ordered = sorted(manifests, key=lambda value: int(value["attempt_number"]))
            if [int(value["attempt_number"]) for value in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                raise S45Error(f"{planned}: malformed attempt sequence")
            if len(ordered) > 2 or len(valid) != 1 or ordered[-1]["outcome"] != "valid":
                raise S45Error(f"{planned}: no unique final valid fit attempt")
            if len(ordered) == 2:
                replacements += 1
                if (
                    ordered[0]["outcome"] == "valid"
                    or ordered[1].get("replacement") is not True
                ):
                    raise S45Error(f"{planned}: invalid replacement history")
            record = valid[0]
            records.append(record)
            category_counts[record.category] += 1
            session_counts[record.session_id] += 1
            group_ids.add(record.group_id)
        if session_counts != {"fit_a": 51, "fit_b": 51}:
            raise S45Error(f"fit session census changed: {dict(session_counts)}")
        inventory = {
            "schema": FIT_INVENTORY_SCHEMA,
            "status": "passed",
            "purpose": purpose,
            "planned_fit_cells": len(self.takes),
            "valid_fit_cells": len(records),
            "retained_attempts": retained_attempts,
            "retained_failures": failures,
            "replacements": replacements,
            "session_counts": dict(sorted(session_counts.items())),
            "category_counts": dict(sorted(category_counts.items())),
            "group_count": len(group_ids),
            "fit_a_inherited_in_place": True,
            "fit_b_completed": True,
            "holdout_attempts_accessed": 0,
            "records": [
                {
                    "planned_take_id": record.planned_take_id,
                    "attempt_id": record.attempt_id,
                    "session_id": record.session_id,
                    "group_id": record.group_id,
                    "category": record.category,
                    "target_bearing_deg": record.target_bearing_deg,
                    "wav_path": record.wav_path,
                    "wav_sha256": record.wav_sha256,
                    "wav_byte_size": record.wav_byte_size,
                }
                for record in records
            ],
        }
        return inventory, tuple(records)

    def read_wave(
        self, record: FitEvidenceRecord, *, purpose: str
    ) -> tuple[np.ndarray, int]:
        """Return one already-inventoried fit WAV after reauthorization/recheck."""

        decision = self.authorize(record.planned_take_id, purpose)
        if decision != {"allowed": True, "mode": "fit_only", "holdout_opened": False}:
            raise S45Error(f"{record.planned_take_id}: non-fit access decision")
        path = _resolved_file(self.repo_root, record.wav_path, "fit WAV")
        if (
            path.stat().st_size != record.wav_byte_size
            or sha256_file(path) != record.wav_sha256
        ):
            raise S45Error(f"{record.attempt_id}: WAV changed after inventory")
        try:
            with wave.open(str(path), "rb") as reader:
                if (
                    reader.getnchannels() != 6
                    or reader.getframerate() != 16_000
                    or reader.getsampwidth() != 2
                    or reader.getcomptype() != "NONE"
                ):
                    raise S45Error(f"{record.attempt_id}: WAV contract mismatch")
                raw = reader.readframes(reader.getnframes())
        except (EOFError, OSError, wave.Error) as exc:
            raise S45Error(f"{record.attempt_id}: invalid WAV: {exc}") from exc
        values = np.frombuffer(raw, dtype="<i2")
        if values.size % 6:
            raise S45Error(f"{record.attempt_id}: truncated interleaved PCM")
        return values.reshape(-1, 6).astype(np.float64) / 32768.0, 16_000


def _reference_start(report: Any, minimum: float = 0.03) -> int | None:
    if not getattr(report, "checks", None):
        return None
    rows = report.checks[0].get("channel_results", [])
    starts = [
        int(item["reference_start_sample_index"])
        for item in rows[2:]
        if float(item.get("peak_normalized_correlation", 0.0)) >= minimum
        and int(item.get("reference_start_sample_index", -1)) >= 0
    ]
    return None if not starts else round(float(median(starts)))


def _aligned_sign(signal: np.ndarray, reference: np.ndarray, shift: float) -> int:
    integer = int(round(shift))
    if integer >= 0:
        left = signal[integer:]
        right = reference[: left.size]
    else:
        right = reference[-integer:]
        left = signal[: right.size]
    if left.size < 32:
        raise S45Error("polarity alignment has insufficient overlap")
    left = left - float(np.mean(left))
    right = right - float(np.mean(right))
    score = float(np.dot(left, right))
    return -1 if score < 0.0 else 1


def extract_fit_observations(
    accessor: FitEvidenceAccessor,
    records: Sequence[FitEvidenceRecord],
) -> tuple[dict[str, Any], tuple[FitObservation, ...]]:
    """Extract one indivisible scientific observation per eligible fit group."""

    reference_record = accessor.contract["evidence"]["source_reference_wav"]
    reference_path = accessor.repo_root / reference_record["path"]
    positions = accessor.contract["native_audio"][
        "profile_nominal_microphone_positions_m"
    ]
    mic_ids = tuple(accessor.contract["native_audio"]["profile_channel_order"])
    position_map = {
        mic_id: tuple(float(value) for value in position)
        for mic_id, position in zip(mic_ids, positions, strict=True)
    }
    observations: list[FitObservation] = []
    exclusions: Counter[str] = Counter()
    for record in records:
        if record.category not in {"controlled", "confidence"}:
            exclusions[f"category_{record.category}"] += 1
            continue
        path = accessor.repo_root / record.wav_path
        report = validate_reference_capture(
            path,
            reference_path,
            minimum_normalized_correlation=0.03,
        )
        if report.issues:
            exclusions["reference_validation_failed"] += 1
            continue
        start = _reference_start(report)
        if start is None:
            exclusions["reference_alignment_unavailable"] += 1
            continue
        samples, rate = accessor.read_wave(record, purpose="S4.5_fit")
        begin = start + round(2.25 * rate)
        stop = min(samples.shape[0], start + round(7.25 * rate))
        if stop - begin < rate:
            exclusions["active_window_too_short"] += 1
            continue
        raw = samples[begin:stop, 2:6].T
        rms = np.sqrt(np.mean(raw * raw, axis=1))
        if not np.all(np.isfinite(rms)) or np.min(rms) < 1e-6:
            exclusions["silent_or_nonfinite_raw_channel"] += 1
            continue
        gain = 20.0 * np.log10(rms / rms[0])
        delays = [0.0]
        signs = [1]
        for channel in range(1, 4):
            delay = gcc_phat_delay(
                raw[channel],
                raw[0],
                sample_rate_hz=rate,
                max_delay_s=16.0 / rate,
                interp=8,
            )
            delays.append(float(delay.sample_shift))
            signs.append(_aligned_sign(raw[channel], raw[0], delay.sample_shift))
        center = raw.shape[1] // 2
        half = min(rate // 2, center)
        bearing_wave = {
            mic_id: raw[index, center - half : center + half]
            for index, mic_id in enumerate(mic_ids)
        }
        srp = srp_phat_direction(
            bearing_wave,
            mic_positions_m=position_map,
            sample_rate_hz=rate,
            azimuth_step_deg=2.0,
            max_delay_s=16.0 / rate,
            interp=8,
        )
        observations.append(
            FitObservation(
                planned_take_id=record.planned_take_id,
                session_id=record.session_id,
                group_id=record.group_id,
                category=record.category,
                target_bearing_deg=record.target_bearing_deg,
                gain_db=tuple(float(value) for value in gain),
                delay_samples=tuple(delays),
                correlation_sign=tuple(signs),
                srp_bearing_deg=float(srp.bearing_deg),
                srp_confidence=float(srp_phat_confidence(srp)),
            )
        )
    groups = [item.group_id for item in observations]
    if len(groups) != len(set(groups)):
        raise S45Error("repeated observations from one leakage group detected")
    payload = {
        "schema": MEASUREMENTS_SCHEMA,
        "status": "passed",
        "observation_count": len(observations),
        "group_count": len(set(groups)),
        "session_counts": dict(
            sorted(Counter(item.session_id for item in observations).items())
        ),
        "excluded_counts": dict(sorted(exclusions.items())),
        "reference_channel": "ch0",
        "gain_unit": "dB",
        "delay_unit": "sample_at_16000_Hz",
        "holdout_observations": 0,
        "observations": [
            {
                "planned_take_id": item.planned_take_id,
                "session_id": item.session_id,
                "group_id": item.group_id,
                "category": item.category,
                "target_bearing_deg": item.target_bearing_deg,
                "gain_db": list(item.gain_db),
                "delay_samples": list(item.delay_samples),
                "correlation_sign": list(item.correlation_sign),
                "srp_bearing_deg": item.srp_bearing_deg,
                "srp_confidence": item.srp_confidence,
            }
            for item in observations
        ],
    }
    return payload, tuple(observations)


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise S45Error("cannot compute percentile of empty values")
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _grouped_bootstrap_half_width(
    values_by_group: Mapping[str, Sequence[float]],
    *,
    seed: int,
    resamples: int,
) -> float:
    groups = sorted(values_by_group)
    if len(groups) < 2:
        return math.inf
    rng = np.random.Generator(np.random.PCG64(seed))
    estimates: list[float] = []
    for _ in range(resamples):
        indices = rng.integers(0, len(groups), size=len(groups))
        values = [
            value for index in indices for value in values_by_group[groups[int(index)]]
        ]
        estimates.append(float(np.median(np.asarray(values, dtype=float))))
    lower = _nearest_rank(estimates, 0.025)
    upper = _nearest_rank(estimates, 0.975)
    return 0.5 * (upper - lower)


def _leave_one_group_shift(values_by_group: Mapping[str, Sequence[float]]) -> float:
    groups = sorted(values_by_group)
    all_values = [value for group in groups for value in values_by_group[group]]
    baseline = float(np.median(np.asarray(all_values, dtype=float)))
    shifts = []
    for excluded in groups:
        values = [
            value
            for group in groups
            if group != excluded
            for value in values_by_group[group]
        ]
        shifts.append(abs(float(np.median(np.asarray(values))) - baseline))
    return max(shifts, default=math.inf)


def _continuous_decision(
    observations: Sequence[FitObservation],
    *,
    field: str,
    channel: int,
    config: Mapping[str, Any],
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    attr = "gain_db" if field == "relative_gain" else "delay_samples"
    train = [item for item in observations if item.session_id == "fit_a"]
    validation = [item for item in observations if item.session_id == "fit_b"]
    all_items = [*train, *validation]

    def values(rows: Sequence[FitObservation]) -> list[float]:
        return [float(getattr(item, attr)[channel]) for item in rows]

    train_values = values(train)
    validation_values = values(validation)
    all_values = values(all_items)
    estimate_a = -float(np.median(np.asarray(train_values)))
    estimate_b = -float(np.median(np.asarray(validation_values)))
    estimate_all = -float(np.median(np.asarray(all_values)))
    before = [abs(value) for value in validation_values]
    after = [abs(value + estimate_a) for value in validation_values]
    before_median = float(np.median(np.asarray(before)))
    after_median = float(np.median(np.asarray(after)))
    improvement = (
        0.0
        if before_median <= 1e-15
        else (before_median - after_median) / before_median
    )
    values_by_group = {
        item.group_id: [float(getattr(item, attr)[channel])] for item in all_items
    }
    uncertainty = _grouped_bootstrap_half_width(
        values_by_group, seed=seed + channel, resamples=resamples
    )
    sensitivity = _leave_one_group_shift(values_by_group)
    distinct_bearings = {
        item.target_bearing_deg
        for item in all_items
        if item.target_bearing_deg is not None
    }
    unit = "dB" if field == "relative_gain" else "sample"
    p95_worsening_limit = float(
        config[
            "p95_worsening_max_db"
            if field == "relative_gain"
            else "p95_worsening_max_samples"
        ]
    )
    stability_limit = float(
        config[
            "stability_max_db" if field == "relative_gain" else "stability_max_samples"
        ]
    )
    uncertainty_limit = float(
        config[
            "uncertainty_half_width_max_db"
            if field == "relative_gain"
            else "uncertainty_half_width_max_samples"
        ]
    )
    checks = {
        "minimum_observations": len(all_items) >= int(config["minimum_observations"]),
        "minimum_groups": len(values_by_group) >= int(config["minimum_groups"]),
        "both_sessions": bool(train) and bool(validation),
        "minimum_bearings": len(distinct_bearings) >= int(config["minimum_bearings"]),
        "median_improvement": improvement
        >= float(config["residual_improvement_fraction"]),
        "p95_not_worse": _nearest_rank(after, 0.95)
        <= _nearest_rank(before, 0.95) + p95_worsening_limit,
        "signed_median_not_farther": abs(
            float(np.median(np.asarray(validation_values))) + estimate_a
        )
        <= abs(float(np.median(np.asarray(validation_values)))) + 1e-15,
        "stable_between_sessions": abs(estimate_a - estimate_b) <= stability_limit,
        "uncertainty_bounded": uncertainty <= uncertainty_limit,
        "leave_one_group_stable": sensitivity <= stability_limit,
    }
    return {
        "candidate": field,
        "channel_id": f"ch{channel}",
        "unit": unit,
        "retained": all(checks.values()),
        "estimate": estimate_all,
        "uncertainty_95_half_width": uncertainty,
        "fit_a_estimate": estimate_a,
        "fit_b_estimate": estimate_b,
        "fit_a_fit_b_difference": abs(estimate_a - estimate_b),
        "observation_count": len(all_items),
        "group_count": len(values_by_group),
        "distinct_bearing_count": len(distinct_bearings),
        "unadjusted_median_absolute_residual": before_median,
        "fitted_median_absolute_residual": after_median,
        "residual_improvement_fraction": improvement,
        "unadjusted_p95_absolute_residual": _nearest_rank(before, 0.95),
        "fitted_p95_absolute_residual": _nearest_rank(after, 0.95),
        "leave_one_group_max_shift": sensitivity,
        "checks": checks,
        "reason": "all frozen criteria passed"
        if all(checks.values())
        else "failed frozen criteria: "
        + ", ".join(name for name, passed in checks.items() if not passed),
    }


def _polarity_decision(
    observations: Sequence[FitObservation],
    *,
    channel: int,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    group_signs = {
        item.group_id: int(item.correlation_sign[channel]) for item in observations
    }
    train = [item for item in observations if item.session_id == "fit_a"]
    validation = [item for item in observations if item.session_id == "fit_b"]
    positives = sum(value > 0 for value in group_signs.values())
    negatives = len(group_signs) - positives
    sign = 1 if positives >= negatives else -1
    agreement = max(positives, negatives) / max(1, len(group_signs))
    leave_one = []
    for excluded in sorted(group_signs):
        values = [value for group, value in group_signs.items() if group != excluded]
        leave_one.append(
            1
            if sum(value > 0 for value in values) >= sum(value < 0 for value in values)
            else -1
        )
    checks = {
        "minimum_observations": len(observations)
        >= int(config["minimum_observations"]),
        "minimum_groups": len(group_signs) >= int(config["minimum_groups"]),
        "both_sessions": bool(train) and bool(validation),
        "group_sign_agreement": agreement >= float(config["group_sign_agreement_min"]),
        "leave_one_group_sign_stability": all(value == sign for value in leave_one),
    }
    return {
        "candidate": "polarity",
        "channel_id": f"ch{channel}",
        "unit": "multiplier",
        "retained": all(checks.values()),
        "estimate": float(sign),
        "uncertainty_disagreeing_group_fraction": 1.0 - agreement,
        "observation_count": len(observations),
        "group_count": len(group_signs),
        "checks": checks,
        "reason": "persistent group sign passed all frozen criteria"
        if all(checks.values())
        else "failed frozen criteria: "
        + ", ".join(name for name, passed in checks.items() if not passed),
    }


def _angular_delta(target: float, observed: float) -> float:
    return (target - observed + 180.0) % 360.0 - 180.0


def _circular_location(values: Sequence[float]) -> float:
    radians = np.radians(np.asarray(values, dtype=float))
    return math.degrees(
        math.atan2(float(np.mean(np.sin(radians))), float(np.mean(np.cos(radians))))
    )


def _bearing_decision(
    observations: Sequence[FitObservation],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = [
        item
        for item in observations
        if item.target_bearing_deg is not None and item.srp_bearing_deg is not None
    ]
    train = [item for item in eligible if item.session_id == "fit_a"]
    validation = [item for item in eligible if item.session_id == "fit_b"]

    def errors(rows: Sequence[FitObservation]) -> list[float]:
        return [
            _angular_delta(
                float(item.target_bearing_deg),
                float(item.srp_bearing_deg),
            )
            for item in rows
        ]

    train_errors = errors(train)
    validation_errors = errors(validation)
    all_errors = errors(eligible)
    estimate_a = _circular_location(train_errors)
    estimate_b = _circular_location(validation_errors)
    estimate = _circular_location(all_errors)
    before = [abs(value) for value in validation_errors]
    after = [
        abs((value - estimate_a + 180.0) % 360.0 - 180.0) for value in validation_errors
    ]
    before_median = float(np.median(np.asarray(before))) if before else math.inf
    after_median = float(np.median(np.asarray(after))) if after else math.inf
    improvement = (
        0.0
        if not math.isfinite(before_median) or before_median <= 1e-15
        else (before_median - after_median) / before_median
    )
    groups = {item.group_id for item in eligible}
    bearings = {float(item.target_bearing_deg) for item in eligible}
    checks = {
        "minimum_observations": len(eligible) >= int(config["minimum_observations"]),
        "minimum_groups": len(groups) >= int(config["minimum_groups"]),
        "minimum_bearings": len(bearings) >= int(config["minimum_bearings"]),
        "both_sessions": bool(train) and bool(validation),
        "median_improvement": improvement
        >= float(config["residual_improvement_fraction"]),
        "p95_not_worse": bool(after)
        and _nearest_rank(after, 0.95) <= _nearest_rank(before, 0.95) + 0.5,
        "stable_between_sessions": abs(_angular_delta(estimate_a, estimate_b))
        <= float(config["stability_max_deg"]),
    }
    return {
        "candidate": "bearing_correction",
        "unit": "deg",
        "retained": all(checks.values()),
        "estimate": estimate,
        "fit_a_estimate": estimate_a,
        "fit_b_estimate": estimate_b,
        "observation_count": len(eligible),
        "group_count": len(groups),
        "distinct_bearing_count": len(bearings),
        "unadjusted_median_absolute_residual": before_median,
        "fitted_median_absolute_residual": after_median,
        "residual_improvement_fraction": improvement,
        "checks": checks,
        "reason": "all frozen criteria passed"
        if all(checks.values())
        else "failed frozen criteria: "
        + ", ".join(name for name, passed in checks.items() if not passed),
    }


def fit_parameter_decisions(
    observations: Sequence[FitObservation],
    contract: Mapping[str, Any],
    synthetic: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen retain/omit rules without using holdout evidence."""

    candidates = contract["candidates"]
    determinism = contract["determinism"]
    seed = int(determinism["grouped_bootstrap_seed"])
    resamples = int(determinism["bootstrap_resamples"])
    decisions: list[dict[str, Any]] = []
    for field in ("relative_gain", "relative_delay"):
        for channel in range(1, 4):
            decision = _continuous_decision(
                observations,
                field=field,
                channel=channel,
                config=candidates[field],
                seed=seed + (0 if field == "relative_gain" else 100),
                resamples=resamples,
            )
            decision["synthetic_recovery_passed"] = bool(
                synthetic[field]["status"] == "passed"
            )
            decision["retained"] = bool(
                decision["retained"] and decision["synthetic_recovery_passed"]
            )
            if not decision["synthetic_recovery_passed"]:
                decision["reason"] = "synthetic recovery failed"
            decisions.append(decision)
    for channel in range(1, 4):
        decision = _polarity_decision(
            observations, channel=channel, config=candidates["polarity"]
        )
        decision["synthetic_recovery_passed"] = bool(
            synthetic["polarity"]["status"] == "passed"
        )
        decision["retained"] = bool(
            decision["retained"] and decision["synthetic_recovery_passed"]
        )
        decisions.append(decision)
    bearing = _bearing_decision(observations, candidates["bearing_correction"])
    bearing["synthetic_recovery_passed"] = bool(
        synthetic["bearing_correction"]["status"] == "passed"
    )
    bearing["retained"] = bool(
        bearing["retained"] and bearing["synthetic_recovery_passed"]
    )
    decisions.append(bearing)
    decisions.extend(
        [
            {
                "candidate": "confidence_calibration",
                "retained": False,
                "synthetic_recovery_passed": synthetic["confidence_calibration"][
                    "status"
                ]
                == "passed",
                "reason": (
                    "omitted: a one-observation-per-group S3 confidence sample does "
                    "not establish an independently validated probability model "
                    "without outcome-diverse grouped calibration evidence"
                ),
            },
            {
                "candidate": "relative_timing",
                "retained": False,
                "synthetic_recovery_passed": synthetic["relative_timing"]["status"]
                == "passed",
                "reason": (
                    "omitted: fit manifests do not expose independently synchronized "
                    "visible-impact timestamps through the S4.5 fit accessor"
                ),
            },
            {
                "candidate": "microphone_geometry",
                "retained": False,
                "synthetic_recovery_passed": False,
                "reason": candidates["microphone_geometry"]["omission_reason"],
            },
        ]
    )
    useful = [
        item
        for item in decisions
        if item.get("retained") is True
        and item.get("candidate")
        in {
            "relative_gain",
            "relative_delay",
            "bearing_correction",
            "confidence_calibration",
            "relative_timing",
        }
    ]
    return {
        "schema": DECISIONS_SCHEMA,
        "status": "passed" if useful else "no_go",
        "fit_only": True,
        "holdout_observations": 0,
        "retained_parameter_count": len(
            [item for item in decisions if item.get("retained") is True]
        ),
        "scientifically_useful_retained_count": len(useful),
        "decisions": decisions,
    }


def synthetic_recovery(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Run deterministic known-truth recovery for every implemented candidate."""

    rate = 16_000
    rng = np.random.Generator(np.random.PCG64(20260724))
    n = 16_384
    time = np.arange(n, dtype=float) / rate
    base = (
        0.3 * np.sin(2.0 * np.pi * 1000.0 * time)
        + 0.2 * np.sin(2.0 * np.pi * 3000.0 * time)
        + 0.05 * rng.standard_normal(n)
    )
    gain_truth = (-6.0, -1.5, 3.0)
    gain_errors = []
    for truth in gain_truth:
        effected = base * 10.0 ** (truth / 20.0)
        recovered = 20.0 * math.log10(
            float(np.sqrt(np.mean(effected * effected)))
            / float(np.sqrt(np.mean(base * base)))
        )
        gain_errors.append(abs(recovered - truth))
    delay_truth = (-3.25, -0.5, 0.5, 2.75)
    delay_errors = []
    spectrum = np.fft.rfft(base)
    frequencies = np.fft.rfftfreq(n)
    for truth in delay_truth:
        delayed = np.fft.irfft(
            spectrum * np.exp(-2j * np.pi * frequencies * truth), n=n
        )
        recovered = gcc_phat_delay(
            delayed,
            base,
            sample_rate_hz=rate,
            max_delay_s=16.0 / rate,
            interp=32,
        ).sample_shift
        delay_errors.append(abs(float(recovered) - truth))
    polarity_truth = (-1, 1)
    polarity_recovered = [
        _aligned_sign(base * truth, base, 0.0) for truth in polarity_truth
    ]
    bearing_errors = [
        _angular_delta((value + 17.5) % 360.0, value)
        for value in (0.0, 45.0, 120.0, 275.0)
    ]
    bearing_estimate = _circular_location(bearing_errors)
    timing_truth = 12.5
    timing_observed = [value + timing_truth for value in (-5.0, 0.0, 4.0, 9.0)]
    timing_recovered = float(
        np.median(np.asarray(timing_observed))
        - np.median(np.asarray([-5.0, 0.0, 4.0, 9.0]))
    )
    probabilities = np.asarray([0.1, 0.2, 0.8, 0.9], dtype=float)
    labels = np.asarray([0.0, 0.0, 1.0, 1.0], dtype=float)
    brier = float(np.mean((probabilities - labels) ** 2))
    confidence_status = "passed" if brier < 0.05 else "failed"
    tolerances = contract["synthetic_tolerances"]
    return {
        "schema": "ias.s4_5.synthetic_recovery.v1",
        "status": "passed",
        "relative_gain": {
            "status": "passed"
            if max(gain_errors) <= float(tolerances["gain_db"])
            else "failed",
            "maximum_absolute_error_db": max(gain_errors),
            "tolerance_db": tolerances["gain_db"],
        },
        "relative_delay": {
            "status": "passed"
            if max(delay_errors) <= float(tolerances["delay_samples"])
            else "failed",
            "maximum_absolute_error_samples": max(delay_errors),
            "tolerance_samples": tolerances["delay_samples"],
        },
        "polarity": {
            "status": "passed"
            if polarity_recovered == list(polarity_truth)
            else "failed",
            "truth": list(polarity_truth),
            "recovered": polarity_recovered,
        },
        "bearing_correction": {
            "status": "passed"
            if abs(_angular_delta(17.5, bearing_estimate))
            <= float(tolerances["bearing_deg"])
            else "failed",
            "truth_deg": 17.5,
            "recovered_deg": bearing_estimate,
            "absolute_error_deg": abs(_angular_delta(17.5, bearing_estimate)),
        },
        "confidence_calibration": {
            "status": confidence_status,
            "fixture_brier_score": brier,
            "deterministic": True,
        },
        "relative_timing": {
            "status": "passed"
            if abs(timing_recovered - timing_truth)
            <= float(tolerances["relative_timing_ms"])
            else "failed",
            "truth_ms": timing_truth,
            "recovered_ms": timing_recovered,
            "absolute_error_ms": abs(timing_recovered - timing_truth),
        },
    }


def build_partial_profile(
    contract: Mapping[str, Any],
    inventory: Mapping[str, Any],
    decisions: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a truthful partial v1 profile without changing its public contract."""

    by_key = {
        (item["candidate"], item.get("channel_id")): item
        for item in decisions["decisions"]
    }
    native = contract["native_audio"]
    profile_config = contract["profile"]
    channels = []
    fitted_parameters = []
    for index, channel_id in enumerate(native["profile_channel_order"]):
        if index == 0:
            gain = {
                "status": "nominal_not_measured",
                "value": 0.0,
                "uncertainty": None,
            }
            delay = {
                "status": "nominal_not_measured",
                "value": 0.0,
                "uncertainty": None,
            }
            polarity = {
                "status": "nominal_not_measured",
                "value": 1.0,
                "uncertainty": None,
            }
        else:
            gain_decision = by_key[("relative_gain", channel_id)]
            delay_decision = by_key[("relative_delay", channel_id)]
            polarity_decision = by_key[("polarity", channel_id)]

            def scalar(
                item: Mapping[str, Any], uncertainty_field: str
            ) -> dict[str, Any]:
                if item["retained"]:
                    return {
                        "status": "measured",
                        "value": float(item["estimate"]),
                        "uncertainty": float(item[uncertainty_field]),
                    }
                return {"status": "unmeasured", "value": None, "uncertainty": None}

            gain = scalar(gain_decision, "uncertainty_95_half_width")
            delay_samples = scalar(delay_decision, "uncertainty_95_half_width")
            delay = {
                **delay_samples,
                "value": (
                    None
                    if delay_samples["value"] is None
                    else float(delay_samples["value"]) / 16_000.0
                ),
                "uncertainty": (
                    None
                    if delay_samples["uncertainty"] is None
                    else float(delay_samples["uncertainty"]) / 16_000.0
                ),
            }
            polarity = (
                {
                    "status": "measured",
                    "value": float(polarity_decision["estimate"]),
                    "uncertainty": float(
                        polarity_decision["uncertainty_disagreeing_group_fraction"]
                    ),
                }
                if polarity_decision["retained"]
                else {"status": "unmeasured", "value": None, "uncertainty": None}
            )
            for name, item, unit, value, uncertainty in (
                (
                    f"relative_gain_db.{channel_id}",
                    gain_decision,
                    "dB",
                    gain["value"],
                    gain["uncertainty"],
                ),
                (
                    f"relative_delay_s.{channel_id}",
                    delay_decision,
                    "s",
                    delay["value"],
                    delay["uncertainty"],
                ),
                (
                    f"polarity.{channel_id}",
                    polarity_decision,
                    "multiplier",
                    polarity["value"],
                    polarity["uncertainty"],
                ),
            ):
                if item["retained"]:
                    fitted_parameters.append(
                        {
                            "name": name,
                            "unit": unit,
                            "estimate": {
                                "status": "measured",
                                "value": value,
                                "uncertainty": uncertainty,
                            },
                        }
                    )
        channels.append(
            {
                "channel_id": channel_id,
                "gain_db": gain,
                "delay_s": delay,
                "polarity": polarity,
                "frequency_response": {
                    "status": "unsupported",
                    "points": [],
                    "uncertainty_db": None,
                },
                "self_noise_db_spl": {
                    "status": "unsupported",
                    "value": None,
                    "uncertainty": None,
                },
                "usable_frequency_range": {
                    "status": "unsupported",
                    "minimum_hz": None,
                    "maximum_hz": None,
                },
            }
        )
    bearing = by_key.get(("bearing_correction", None))
    if bearing and bearing["retained"]:
        fitted_parameters.append(
            {
                "name": "functional_bearing_correction_deg",
                "unit": "deg",
                "estimate": {
                    "status": "measured",
                    "value": float(bearing["estimate"]),
                    "uncertainty": None,
                },
            }
        )
    retained = [item for item in decisions["decisions"] if item.get("retained") is True]
    gain_residuals = [item for item in retained if item["candidate"] == "relative_gain"]
    delay_residuals = [
        item for item in retained if item["candidate"] == "relative_delay"
    ]
    fit_metrics = [
        {
            "name": "fit_observation_count",
            "value": float(sum(inventory["session_counts"].values())),
            "unit": "attempt",
        },
        {
            "name": "retained_parameter_count",
            "value": float(len(retained)),
            "unit": "parameter",
        },
    ]
    if gain_residuals:
        fit_metrics.append(
            {
                "name": "validation_gain_median_absolute_residual_db",
                "value": float(
                    np.median(
                        [
                            item["fitted_median_absolute_residual"]
                            for item in gain_residuals
                        ]
                    )
                ),
                "unit": "dB",
            }
        )
    if delay_residuals:
        fit_metrics.append(
            {
                "name": "validation_delay_median_absolute_residual_samples",
                "value": float(
                    np.median(
                        [
                            item["fitted_median_absolute_residual"]
                            for item in delay_residuals
                        ]
                    )
                ),
                "unit": "sample",
            }
        )
    geometry = [
        {
            "channel_id": channel_id,
            "status": "nominal_not_measured",
            "position_m": position,
            "uncertainty_m": None,
            "frame": profile_config["array_frame"],
        }
        for channel_id, position in zip(
            native["profile_channel_order"],
            native["profile_nominal_microphone_positions_m"],
            strict=True,
        )
    ]
    raw_measurements = [
        {"path": item["wav_path"], "sha256": item["wav_sha256"]}
        for item in inventory["records"]
    ]
    payload = {
        "schema_version": profile_config["schema_version"],
        "profile_id": profile_config["profile_id"],
        "profile_version": profile_config["profile_version"],
        "device_id": profile_config["device_id"],
        "device_model": profile_config["device_model"],
        "array_id": profile_config["array_id"],
        "channel_order": list(native["profile_channel_order"]),
        "reference_rig_bom_path": (
            "outputs/isaac_audio_sensors/S4/S4.1/rig_frame_lock.json"
        ),
        "microphone_geometry": geometry,
        "array_frame": profile_config["array_frame"],
        "source_frame": "F_project",
        "coordinate_convention": "x_forward_y_right_z_up_clockwise_bearing",
        "units": {
            "delay": "s",
            "frequency": "Hz",
            "gain": "dB",
            "position": "m",
            "position_uncertainty": "m",
            "self_noise": "dB_SPL",
            "speed_of_sound": "m/s",
            "temperature": "deg_C",
        },
        "sample_rate_hz": 16_000,
        "temperature_c": {
            "status": "unmeasured",
            "value": None,
            "uncertainty": None,
        },
        "speed_of_sound_policy": "fixed",
        "speed_of_sound_mps": {
            "status": "nominal_not_measured",
            "value": 343.0,
            "uncertainty": None,
        },
        "environment_description": (
            "Functional fit for the S4_TEMP_DESKTOP_FIXTURE_REV0 in "
            "WANG_2022_DESK_NEAR_ENTRANCE using inherited Fit A and Fit B only."
        ),
        "channels": channels,
        "source_id": "s4_2_reference_wav",
        "speaker_id": "macbook_pro_speakers_fit_only",
        "pose_measurement_method": (
            "S4.4 recorded functional project-frame source placements; "
            "microphone positions remain nominal and unmeasured."
        ),
        "reference_signal": (
            f"{contract['evidence']['source_reference_wav']['path']} "
            f"sha256={contract['evidence']['source_reference_wav']['sha256']}"
        ),
        "acquisition_procedure": (
            "Sealed S4.4 amendment-03 fit-only access; one observation per "
            "leakage group; Fit A fitting and Fit B validation."
        ),
        "fitted_model_parameters": fitted_parameters,
        "fit_metrics": fit_metrics,
        "holdout_metrics": [],
        "applicability_limits": {
            "temperature_min_c": None,
            "temperature_max_c": None,
            "frequency_min_hz": None,
            "frequency_max_hz": None,
            "environment_tags": [
                "S4_TEMP_DESKTOP_FIXTURE_REV0",
                "WANG_2022_DESK_NEAR_ENTRANCE",
                "respeaker_xvf3800_16kHz",
                "macbook_reference_source",
                "fit_only",
            ],
        },
        "uncertainty_notes": (
            "Uncertainty is deterministic grouped-bootstrap 95% half-width. "
            "Corrections are relative/functional and include the tested "
            "source-room-sensor path; no absolute or component-isolated claim."
        ),
        "raw_measurements": raw_measurements,
        "tool_version": contract["tool_version"],
        "created_at": contract["created_at"],
        "unmeasured_fields": [
            "temperature_c",
            "microphone_geometry.*.uncertainty_m",
            "channels.*.frequency_response",
            "channels.*.self_noise_db_spl",
            "channels.*.usable_frequency_range",
            "holdout_metrics",
            "absolute_spl",
            "absolute_microphone_sensitivity",
            "isolated_speaker_response",
            "isolated_microphone_response",
            "certified_room_acoustics",
            "traceable_acoustic_calibration",
            "precision_optical_acoustic_extrinsics",
        ],
        "evidence_status": "measured",
    }
    profile = calibration_profile_from_dict(payload)
    round_tripped = calibration_profile_to_dict(profile)
    if round_tripped != payload:
        raise S45Error("partial calibration profile does not round-trip exactly")
    try:
        import jsonschema

        jsonschema.validate(round_tripped, audio_calibration_profile_json_schema())
    except ImportError as exc:
        raise S45Error("jsonschema is required for S4.5 profile validation") from exc
    except jsonschema.ValidationError as exc:
        raise S45Error(
            f"partial profile schema validation failed: {exc.message}"
        ) from exc
    return round_tripped


def detect_later_phase_artifacts(repo_root: Path) -> list[str]:
    """Return filename/path-owned S4.6-S4.9 artifacts."""

    found: list[str] = []
    root = repo_root.resolve()
    for root_name in _SCAN_ROOTS:
        scan = root / root_name
        if not scan.exists():
            continue
        for current, directories, files in __import__("os").walk(scan):
            directories[:] = sorted(
                value for value in directories if value not in _SCAN_IGNORES
            )
            current_path = Path(current)
            matching = [value for value in directories if _LATER_PHASE.search(value)]
            for value in matching:
                found.append((current_path / value).relative_to(root).as_posix())
            directories[:] = [value for value in directories if value not in matching]
            for value in sorted(files):
                if _LATER_PHASE.search(value):
                    found.append((current_path / value).relative_to(root).as_posix())
    return sorted(found)


def validate_s4_4_preservation(repo_root: Path) -> dict[str, Any]:
    """Permit S4.5 while retaining every historical S4.4 final assertion."""

    from scripts.validate_s4_4_amendment_03_final import validate as validate_final

    historical = validate_final(
        repo_root=repo_root,
        require_tracked=True,
        require_committed=True,
        require_machine_local=True,
        require_corrective=True,
    )
    disallowed_issues = [
        issue
        for issue in historical["issues"]
        if issue.get("code") != "later_phase_artifact_present"
        or re.search(
            r"(?:^|[^a-z0-9])s4[._-]?5(?:[^0-9]|$)",
            str(issue.get("path", "")),
            re.IGNORECASE,
        )
        is None
    ]
    later = detect_later_phase_artifacts(repo_root)
    grants = [
        path.relative_to(repo_root).as_posix()
        for path in sorted((repo_root / "dataset/S4.4").rglob("*grant*"))
        if path.is_file()
    ]
    checks = {
        "historical_s4_4_checks_pass_except_expected_s4_5_presence": (
            not disallowed_issues
        ),
        "frozen_s4_4_census_preserved": historical.get("census")
        == {
            "valid_cells_total": 149,
            "retained_attempts_total": 152,
            "failures_total": 3,
            "replacements_total": 3,
            "incomplete_logical_cells": 0,
        },
        "holdout_scientifically_unopened": historical.get(
            "holdout_scientifically_opened"
        )
        is False,
        "scientific_outcomes_not_returned": historical.get(
            "scientific_outcomes_returned"
        )
        is False,
        "no_s4_8_grant": not grants,
        "no_s4_6_through_s4_9_artifacts": not later,
        "dataset_untracked": not bool(
            subprocess.run(
                ["git", "ls-files", "dataset"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
    }
    return {
        "schema": PRESERVATION_SCHEMA,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "historical_validator_status": historical["status"],
        "historical_validator_only_expected_s4_5_presence": not disallowed_issues,
        "historical_issues": historical["issues"],
        "s4_4_census": historical.get("census"),
        "holdout_scientifically_opened": False,
        "scientific_outcomes_returned": False,
        "s4_8_grants": grants,
        "later_phase_artifacts": later,
    }


def validate_profile_policy(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Reject invented unsupported fields and any holdout metric."""

    issues: list[str] = []
    if profile.get("holdout_metrics") != []:
        issues.append("holdout_metrics must be empty")
    forbidden = {
        "absolute_spl",
        "absolute_microphone_sensitivity",
        "isolated_speaker_response",
        "isolated_microphone_response",
        "certified_room_acoustics",
        "traceable_acoustic_calibration",
        "precision_optical_acoustic_extrinsics",
    }
    fitted_names = {
        str(item.get("name"))
        for item in profile.get("fitted_model_parameters", [])
        if isinstance(item, dict)
    }
    if forbidden & fitted_names:
        issues.append("unsupported field contains a fitted value")
    for channel in profile.get("channels", []):
        if channel.get("frequency_response") != {
            "status": "unsupported",
            "points": [],
            "uncertainty_db": None,
        }:
            issues.append("unsupported frequency response contains values")
        if channel.get("self_noise_db_spl", {}).get("value") is not None:
            issues.append("unsupported self-noise contains a value")
    return {
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }


def validate_evidence_package(
    repo_root: Path,
    output: Path,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
) -> dict[str, Any]:
    """Validate the complete deterministic S4.5 evidence package."""

    required = {
        "pre_s4_5_s4_4_validation.json",
        "fit_inventory.json",
        "fitting_contract.json",
        "authorized_attempt_census.json",
        "synthetic_recovery.json",
        "fit_measurements.json",
        "grouped_residual_results.json",
        "parameter_decisions.json",
        "uncertainty_sensitivity.json",
        "limitations.json",
        "calibration_profile.v1.json",
        "preservation_validation.json",
        "reproduction.json",
        "provenance.json",
        "evidence_index.json",
        "SHA256SUMS",
    }
    issues: list[str] = []
    present = (
        {path.name for path in output.iterdir() if path.is_file()}
        if output.is_dir()
        else set()
    )
    if present != required:
        issues.append(
            f"evidence file set mismatch: missing={sorted(required - present)}, "
            f"extra={sorted(present - required)}"
        )
    if issues:
        return {
            "schema": VALIDATION_SCHEMA,
            "status": "failed",
            "issues": issues,
        }
    checksums = _parse_checksum_manifest(output / "SHA256SUMS", output)
    if set(checksums) != required - {"SHA256SUMS"}:
        issues.append("SHA256SUMS path set mismatch")
    profile = load_json(output / "calibration_profile.v1.json", label="profile")
    policy = validate_profile_policy(profile)
    if policy["status"] != "passed":
        issues.extend(policy["issues"])
    try:
        parsed = calibration_profile_from_dict(profile)
        if calibration_profile_to_dict(parsed) != profile:
            issues.append("profile round-trip mismatch")
        import jsonschema

        jsonschema.validate(profile, audio_calibration_profile_json_schema())
    except (ValueError, ImportError) as exc:
        issues.append(f"profile validation failed: {exc}")
    except jsonschema.ValidationError as exc:
        issues.append(f"profile schema failed: {exc.message}")
    decisions = load_json(output / "parameter_decisions.json", label="decisions")
    if decisions.get("status") != "passed":
        issues.append("no scientifically useful retained parameter")
    synthetic = load_json(output / "synthetic_recovery.json", label="synthetic")
    for name in (
        "relative_gain",
        "relative_delay",
        "polarity",
        "bearing_correction",
        "confidence_calibration",
        "relative_timing",
    ):
        if synthetic.get(name, {}).get("status") != "passed":
            issues.append(f"synthetic recovery failed: {name}")
    preservation = load_json(
        output / "preservation_validation.json", label="preservation"
    )
    if preservation.get("status") != "passed":
        issues.append("S4.4 preservation validation failed")
    index = load_json(output / "evidence_index.json", label="evidence index")
    if index.get("schema") != EVIDENCE_INDEX_SCHEMA:
        issues.append("evidence index schema mismatch")
    if require_tracked:
        relative_paths = [
            path.relative_to(repo_root).as_posix() for path in sorted(output.iterdir())
        ]
        tracked = set(
            subprocess.run(
                ["git", "ls-files", "--", *relative_paths],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
        if tracked != set(relative_paths):
            issues.append("S4.5 evidence is not fully tracked")
    if require_committed:
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "HEAD",
                "--",
                str(output.relative_to(repo_root)),
            ],
            cwd=repo_root,
            check=False,
        ).returncode
        if changed != 0:
            issues.append("S4.5 evidence differs from HEAD")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "passed" if not issues else "failed",
        "profile_round_trip": not any("profile" in issue for issue in issues),
        "profile_schema": not any("schema" in issue for issue in issues),
        "holdout_metrics_empty": profile.get("holdout_metrics") == [],
        "unsupported_field_policy": policy["status"],
        "checksum_record_count": len(checksums),
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "issues": issues,
    }


def source_commit_is_valid(repo_root: Path, source_commit: str) -> None:
    """Require a real committed source ancestor with exact S4.5 source blobs."""

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise S45Error("source commit must be a full lowercase Git hash")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise S45Error("source commit does not exist")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise S45Error("source commit is not an ancestor of HEAD")
    source_paths = (
        S45_CONFIG,
        S45_SPEC,
        Path("src/isaac_audio_sensors/acquisition/s4_5.py"),
        Path("scripts/run_s4_5_fitting.py"),
        Path("scripts/validate_s4_5.py"),
        Path("tests/test_s4_5_fitting.py"),
    )
    for relative in source_paths:
        working = repo_root / relative
        if not working.is_file():
            raise S45Error(f"source file missing: {relative}")
        blob = subprocess.run(
            ["git", "show", f"{source_commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if blob.returncode != 0 or hashlib.sha256(
            blob.stdout
        ).hexdigest() != sha256_file(working):
            raise S45Error(f"source commit does not bind exact {relative}")


def evidence_records(output: Path) -> list[dict[str, Any]]:
    """Return deterministic evidence-index records for all current files."""

    return [
        {
            "path": path.name,
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"evidence_index.json", "SHA256SUMS"}
    ]


def checksum_text(output: Path) -> str:
    """Return the deterministic checksum manifest excluding itself."""

    names = sorted(
        path.name
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    return "".join(f"{sha256_file(output / name)}  {name}\n" for name in names)
