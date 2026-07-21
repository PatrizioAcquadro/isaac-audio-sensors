#!/usr/bin/env python3
"""Fail-closed tracked and optional machine-local S4.3 integrity validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import sha256_file
from isaac_audio_sensors.acquisition.s4_3 import (
    S43Error,
    load_json,
    load_pilot_configuration,
    validate_inventory,
    validate_preregistration,
    validate_review_remediation_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
S43_OUTPUT = ROOT / "outputs/isaac_audio_sensors/S4/S4.3"
DEFAULT_REVIEW_REMEDIATION = S43_OUTPUT / "freeze/review_remediation_manifest.json"


def _problem(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def validate(
    index_path: Path,
    *,
    config_path: Path,
    preregistration_path: Path,
    review_remediation_path: Path,
    require_machine_local: bool,
    require_final: bool,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    evidence_root = index_path.resolve().parent
    try:
        evidence_root_relative = evidence_root.relative_to(ROOT.resolve()).as_posix()
        evidence_root.relative_to(S43_OUTPUT.resolve())
    except ValueError as exc:
        raise S43Error(
            f"index must remain under the S4.3 evidence root: {S43_OUTPUT}"
        ) from exc
    if require_final and evidence_root != S43_OUTPUT.resolve():
        final_index = S43_OUTPUT / "evidence_index.json"
        raise S43Error(f"final evidence index must be {final_index}")
    index = load_json(index_path)
    if index.get("schema") != "ias.s4_3.evidence_index.v1":
        issues.append(
            _problem("wrong_index_schema", str(index_path), repr(index.get("schema")))
        )
    if index.get("status") != "passed":
        issues.append(
            _problem(
                "evidence_index_failed", str(index_path), repr(index.get("status"))
            )
        )
    configuration = load_pilot_configuration(config_path, repo_root=ROOT)
    preregistration = load_json(preregistration_path)
    freeze = validate_preregistration(
        configuration,
        preregistration,
        repo_root=ROOT,
        verify_implementation_hashes=False,
    )
    issues.extend(
        _problem(item.code, item.path, item.message) for item in freeze.issues
    )
    review_remediation = load_json(review_remediation_path)
    review_validation = validate_review_remediation_manifest(
        configuration,
        preregistration,
        review_remediation,
        repo_root=ROOT,
    )
    issues.extend(
        _problem(item.code, item.path, item.message)
        for item in review_validation.issues
    )
    inventory_path = evidence_root / "trial_inventory.json"
    if not inventory_path.is_file():
        issues.append(_problem("missing_inventory", str(inventory_path), "file absent"))
        inventory = {}
    else:
        inventory = load_json(inventory_path)
        inventory_report = validate_inventory(inventory, configuration)
        issues.extend(
            _problem(item.code, item.path, item.message)
            for item in inventory_report.issues
        )
        if require_final and inventory.get("status") != "terminal":
            issues.append(
                _problem(
                    "inventory_not_terminal",
                    str(inventory_path),
                    repr(inventory.get("status")),
                )
            )

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        issues.append(
            _problem("invalid_artifacts", str(index_path), "artifacts must be list")
        )
    seen: set[str] = set()
    indexed_hashes: dict[str, str] = {}
    checked = 0
    machine_records = 0
    for number, record in enumerate(artifacts):
        path_value = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path_value, str) or not path_value:
            issues.append(
                _problem(
                    "invalid_artifact_path", f"artifacts[{number}]", repr(path_value)
                )
            )
            continue
        if path_value in seen:
            issues.append(
                _problem("duplicate_artifact", path_value, "duplicate index path")
            )
            continue
        seen.add(path_value)
        if "outputs/isaac_audio_sensors/S4/S4.4/" in path_value:
            issues.append(
                _problem(
                    "s4_4_content_forbidden", path_value, "S4.4 was not authorized"
                )
            )
        candidate = (ROOT / path_value).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            issues.append(
                _problem("unsafe_artifact_path", path_value, "escapes repository")
            )
            continue
        retention = record.get("retention")
        is_machine = retention == "machine_local_gitignored"
        if is_machine:
            machine_records += 1
        if is_machine and not require_machine_local:
            indexed_hashes[path_value] = str(record.get("sha256"))
            continue
        if not candidate.is_file():
            issues.append(_problem("missing_artifact", path_value, "file absent"))
            continue
        if candidate.stat().st_size != record.get("byte_size"):
            issues.append(_problem("size_mismatch", path_value, "byte size differs"))
        actual = sha256_file(candidate)
        indexed_hashes[path_value] = actual
        if actual != record.get("sha256"):
            issues.append(_problem("checksum_mismatch", path_value, "SHA-256 differs"))
        checked += 1

    checksum_path = index_path.parent / "SHA256SUMS"
    if not checksum_path.is_file():
        issues.append(_problem("missing_checksums", str(checksum_path), "file absent"))
    else:
        lines = {}
        for number, line in enumerate(
            checksum_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "  " not in line:
                issues.append(
                    _problem("malformed_checksum", str(checksum_path), f"line {number}")
                )
                continue
            digest, relative = line.split("  ", 1)
            if relative in lines:
                issues.append(
                    _problem("duplicate_checksum", relative, f"line {number}")
                )
            lines[relative] = digest
        expected = {
            str(record.get("path")): str(record.get("sha256"))
            for record in artifacts
            if isinstance(record, dict)
        }
        if lines != expected:
            issues.append(
                _problem(
                    "checksum_coverage_mismatch",
                    str(checksum_path),
                    "manifest differs from index",
                )
            )

    required = {
        f"{evidence_root_relative}/reports/repeatability.json",
        f"{evidence_root_relative}/reports/controlled.json",
        f"{evidence_root_relative}/reports/robustness.json",
        f"{evidence_root_relative}/reports/repeatability_gate.json",
        f"{evidence_root_relative}/failures.json",
        f"{evidence_root_relative}/validation/deterministic_replay.json",
        f"{evidence_root_relative}/validation/machine_local_validation.json",
        f"{evidence_root_relative}/validation/raw_independent_validation.json",
        f"{evidence_root_relative}/validation/evidence_coverage.json",
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/review_remediation_manifest.json",
    }
    if require_final:
        required.update(
            {
                "outputs/isaac_audio_sensors/S4/S4.3/repository_gate.json",
                "outputs/isaac_audio_sensors/S4/S4.3/validation/repository_validation.json",
                "docs/development/closeouts/S4/s4_3_pilot_repeatability.md",
            }
        )
    for missing in sorted(required - seen):
        issues.append(_problem("required_evidence_missing", missing, "not indexed"))
    gate_paths = {
        f"{evidence_root_relative}/validation/deterministic_replay.json",
        f"{evidence_root_relative}/validation/evidence_coverage.json",
        f"{evidence_root_relative}/validation/machine_local_validation.json",
        f"{evidence_root_relative}/validation/raw_independent_validation.json",
    }
    if require_final:
        gate_paths.update(
            {
                f"{evidence_root_relative}/reports/repeatability_gate.json",
                "outputs/isaac_audio_sensors/S4/S4.3/repository_gate.json",
                "outputs/isaac_audio_sensors/S4/S4.3/validation/repository_validation.json",
            }
        )
    for relative in sorted(gate_paths):
        path = ROOT / relative
        if path.is_file() and load_json(path).get("status") != "passed":
            issues.append(
                _problem(
                    "evidence_gate_failed",
                    relative,
                    repr(load_json(path).get("status")),
                )
            )
    coverage_path = evidence_root / "validation/evidence_coverage.json"
    if coverage_path.is_file():
        coverage = load_json(coverage_path)
        records = coverage.get("metric_contracts")
        if (
            coverage.get("schema") != "ias.s4_3.evidence_coverage.v2"
            or not isinstance(records, dict)
            or set(records) != set(configuration.get("metric_contracts", {}))
            or any(
                not isinstance(record, dict)
                or record.get("status") != "passed"
                or record.get("required_outputs_verified") is not True
                or record.get("issues") != []
                for record in records.values()
            )
        ):
            issues.append(
                _problem(
                    "metric_specific_coverage_invalid",
                    str(coverage_path),
                    "all frozen metrics must have verified concrete outputs",
                )
            )
    repeatability_path = evidence_root / "reports/repeatability_gate.json"
    if repeatability_path.is_file():
        repeatability = load_json(repeatability_path)
        if (
            repeatability.get("schema") != "ias.s4_3.repeatability_gate.v2"
            or repeatability.get("checks", {}).get("raw_channel_health_failures")
            is not True
            or "raw_channel_health_failure_count"
            not in repeatability.get("observations", {})
        ):
            issues.append(
                _problem(
                    "repeatability_channel_health_gate_missing",
                    str(repeatability_path),
                    "raw-channel-health threshold must be enforced",
                )
            )
    for category in ("repeatability", "controlled", "robustness"):
        report_path = evidence_root / f"reports/{category}.json"
        if report_path.is_file() and load_json(report_path).get("schema") != (
            "ias.s4_3.category_report.v2"
        ):
            issues.append(
                _problem(
                    "category_report_schema_outdated",
                    str(report_path),
                    "metric-complete category report v2 required",
                )
            )
    if require_machine_local and machine_records == 0:
        issues.append(
            _problem(
                "machine_local_evidence_missing",
                str(index_path),
                "no raw records indexed",
            )
        )
    if index.get("s4_4_started") is not False:
        issues.append(_problem("s4_4_started", str(index_path), "must be false"))
    return {
        "schema": "ias.s4_3.integrity_validation.v1",
        "status": "passed" if not issues else "failed",
        "require_machine_local": require_machine_local,
        "require_final": require_final,
        "indexed_artifact_count": len(artifacts),
        "checked_artifact_count": checked,
        "machine_local_record_count": machine_records,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json"),
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/s4_3_pilot.v1.json")
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S4/S4.3/freeze/preregistration.json"),
    )
    parser.add_argument("--require-machine-local", action="store_true")
    parser.add_argument(
        "--review-remediation", type=Path, default=DEFAULT_REVIEW_REMEDIATION
    )
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = validate(
            args.index,
            config_path=args.config,
            preregistration_path=args.preregistration,
            review_remediation_path=args.review_remediation,
            require_machine_local=args.require_machine_local,
            require_final=args.require_final,
        )
    except (OSError, S43Error, ValueError) as exc:
        print(f"S4.3 integrity validation failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(encoded)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
