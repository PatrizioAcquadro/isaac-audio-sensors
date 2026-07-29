#!/usr/bin/env python3
"""Process S4.8 preliminary takes and evaluate freeze readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_8_preliminary import (
    AUTHORITY_NONE,
    CASE_IDS,
    S48PreliminaryError,
    build_diagnostic_package,
    build_readiness_report,
    build_reprocessing_record,
    build_reuse_decision,
    load_workflow_config,
    process_case,
    reprocess_attempt_gate,
    run_diagnostic_evaluator,
    validate_reprocessing_record,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S48PreliminaryError(f"JSON read failure for {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S48PreliminaryError(f"JSON object required: {path}")
    return value


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise S48PreliminaryError(f"refusing to overwrite {path}") from exc


def _parse_case_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        case_id, separator, raw_path = value.partition("=")
        if not separator or case_id not in CASE_IDS or case_id in roots:
            raise S48PreliminaryError(
                "--case-root must provide each case once as CASE_ID=PATH"
            )
        roots[case_id] = Path(raw_path).resolve()
    if set(roots) != set(CASE_IDS):
        raise S48PreliminaryError("all four preliminary case roots are required")
    return roots


def _parse_reprocessing_records(values: list[str]) -> dict[str, Path]:
    records: dict[str, Path] = {}
    for value in values:
        case_id, separator, raw_path = value.partition("=")
        if not separator or case_id not in CASE_IDS or case_id in records:
            raise S48PreliminaryError(
                "--reprocessing-record must use CASE_ID=PATH without duplicates"
            )
        records[case_id] = Path(raw_path).resolve()
    return records


def _require_diagnostic_output(path: Path) -> Path:
    resolved = path.resolve()
    forbidden = (
        ROOT / "dataset",
        ROOT / "outputs/isaac_audio_sensors/S4",
    )
    if any(resolved == root or root in resolved.parents for root in forbidden):
        raise S48PreliminaryError(
            "preliminary output cannot enter an official S4.8 namespace"
        )
    return resolved


def process(args: argparse.Namespace) -> dict[str, Any]:
    load_workflow_config(ROOT)
    manifest = _load_json(args.manifest.resolve())
    case_roots = _parse_case_roots(args.case_root)
    reprocessing_records = _parse_reprocessing_records(args.reprocessing_record)
    output = _require_diagnostic_output(args.output)
    if output.exists():
        raise S48PreliminaryError(f"refusing to reuse output directory: {output}")
    output.mkdir(parents=True)
    case_results = [
        process_case(
            ROOT,
            manifest=manifest,
            case_root=case_roots[case_id],
            case_id=case_id,
            reprocessing_record_path=reprocessing_records.get(case_id),
        )
        for case_id in CASE_IDS
    ]
    evaluation = run_diagnostic_evaluator(
        ROOT,
        manifest=manifest,
        case_results=case_results,
    )
    package = build_diagnostic_package(
        manifest=manifest,
        case_results=case_results,
        evaluation=evaluation,
    )
    _write_new_json(output / "case_results.json", {"cases": case_results})
    _write_new_json(output / "diagnostic_evaluation.json", evaluation)
    _write_new_json(output / "diagnostic_package.json", package)
    records = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            records.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            )
    (output / "SHA256SUMS").write_text("".join(records), encoding="utf-8")
    return {
        "status": package["status"],
        "output": str(output),
        "preliminary_take_count": 4,
        "official_take_count": 0,
        "package_sha256": package["package_sha256"],
        "classification": package["classification"],
        "authority": dict(AUTHORITY_NONE),
    }


def record_reprocessing(args: argparse.Namespace) -> dict[str, Any]:
    load_workflow_config(ROOT)
    report_path = _require_diagnostic_output(args.corrected_report)
    record_path = _require_diagnostic_output(args.record)
    if report_path.exists() or record_path.exists():
        raise S48PreliminaryError(
            "refusing to overwrite an additive reprocessing artifact"
        )
    report = reprocess_attempt_gate(
        ROOT,
        attempt_path=args.attempt,
        reference_path=args.reference,
    )
    if report.get("decision") != "PASS":
        raise S48PreliminaryError("corrected offline gate did not PASS")
    _write_new_json(report_path, report)
    record = build_reprocessing_record(
        ROOT,
        correction_id=args.correction_id,
        case_id=args.case_id,
        preliminary_take_id=args.preliminary_take_id,
        attempt_number=args.attempt_number,
        attempt_path=args.attempt,
        attempt_ledger_path=args.attempt_ledger,
        campaign_manifest_path=args.campaign_manifest,
        corrected_report_path=report_path,
        corrective_commit=args.corrective_commit,
        technical_justification=args.justification,
        physical_confirmation_evidence=args.physical_confirmation_evidence,
    )
    _write_new_json(record_path, record)
    corrected = record["corrected_offline_result"]
    return {
        "status": "passed",
        "historical_decision": record["historical_result"]["decision"],
        "corrected_offline_decision": corrected["decision"],
        "corrected_report_path": str(report_path),
        "corrected_report_sha256": corrected["report"]["sha256"],
        "corrected_report_canonical_sha256": corrected[
            "report_canonical_sha256"
        ],
        "reprocessing_record_path": str(record_path),
        "reprocessing_record_sha256": record["record_sha256"],
        "reuse_decision": record["reuse_decision"]["decision"],
        "fresh_physical_confirmation_required": False,
        "classification": record["classification"],
        "authority": record["authority"],
    }


def decide_reuse(args: argparse.Namespace) -> dict[str, Any]:
    raw_hashes = {}
    for value in args.raw_sha256:
        case_id, separator, digest = value.partition("=")
        if not separator or case_id in raw_hashes:
            raise S48PreliminaryError(
                "--raw-sha256 must use CASE_ID=SHA256 without duplicates"
            )
        raw_hashes[case_id] = digest
    decision = build_reuse_decision(
        correction_id=args.correction_id,
        change_class=args.change_class,
        affected_case_ids=args.affected_case,
        raw_sha256_by_case=raw_hashes,
        decision=args.decision,
        technical_justification=args.justification,
        physical_confirmation=args.physical_confirmation,
        physical_confirmation_evidence=args.physical_confirmation_evidence,
        replacement_complete=args.replacement_complete,
    )
    path = _require_diagnostic_output(args.decision_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(decision, sort_keys=True, separators=(",", ":")) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    return decision


def readiness(args: argparse.Namespace) -> dict[str, Any]:
    load_workflow_config(ROOT)
    manifest = _load_json(args.manifest.resolve())
    package = _load_json(args.package.resolve())
    decisions = []
    if args.decision_log.is_file():
        for line in args.decision_log.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise S48PreliminaryError("decision log line must be a JSON object")
            decisions.append(value)
    for path in args.reprocessing_record:
        record = _load_json(path.resolve())
        validate_reprocessing_record(ROOT, record)
        decisions.append(record["reuse_decision"])
    report = build_readiness_report(
        manifest=manifest,
        package=package,
        reuse_decisions=decisions,
    )
    _write_new_json(_require_diagnostic_output(args.output), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)

    reprocessing_parser = subparsers.add_parser("record-reprocessing")
    reprocessing_parser.add_argument("--attempt", type=Path, required=True)
    reprocessing_parser.add_argument("--reference", type=Path, required=True)
    reprocessing_parser.add_argument("--attempt-ledger", type=Path, required=True)
    reprocessing_parser.add_argument("--campaign-manifest", type=Path, required=True)
    reprocessing_parser.add_argument("--corrected-report", type=Path, required=True)
    reprocessing_parser.add_argument("--record", type=Path, required=True)
    reprocessing_parser.add_argument("--correction-id", required=True)
    reprocessing_parser.add_argument("--case-id", choices=CASE_IDS, required=True)
    reprocessing_parser.add_argument("--preliminary-take-id", required=True)
    reprocessing_parser.add_argument("--attempt-number", type=int, required=True)
    reprocessing_parser.add_argument("--corrective-commit", required=True)
    reprocessing_parser.add_argument("--justification", required=True)
    reprocessing_parser.add_argument(
        "--physical-confirmation-evidence", required=True
    )
    reprocessing_parser.set_defaults(function=record_reprocessing)

    process_parser = subparsers.add_parser("process")
    process_parser.add_argument("--manifest", type=Path, required=True)
    process_parser.add_argument(
        "--case-root",
        action="append",
        required=True,
        help="repeat exactly four times as CASE_ID=PATH",
    )
    process_parser.add_argument(
        "--reprocessing-record",
        action="append",
        default=[],
        help="optional additive correction as CASE_ID=PATH",
    )
    process_parser.add_argument("--output", type=Path, required=True)
    process_parser.set_defaults(function=process)

    decision_parser = subparsers.add_parser("decide-reuse")
    decision_parser.add_argument("--decision-log", type=Path, required=True)
    decision_parser.add_argument("--correction-id", required=True)
    decision_parser.add_argument(
        "--change-class",
        choices=(
            "downstream_code",
            "detector_or_processing",
            "physical_acquisition_conditions",
            "playback_path",
            "reference_signal",
            "playback_gain",
            "geometry",
            "device_profile",
            "channel_map",
            "synchronization_assumptions",
            "raw_recording_validity",
        ),
        required=True,
    )
    decision_parser.add_argument(
        "--affected-case", action="append", required=True, choices=CASE_IDS
    )
    decision_parser.add_argument("--raw-sha256", action="append", required=True)
    decision_parser.add_argument(
        "--decision", choices=("reuse", "reacquire"), required=True
    )
    decision_parser.add_argument("--justification", required=True)
    decision_parser.add_argument(
        "--physical-confirmation",
        choices=(
            "not_applicable",
            "not_required_by_evidence",
            "required_pending",
            "completed",
        ),
        required=True,
    )
    decision_parser.add_argument("--physical-confirmation-evidence")
    decision_parser.add_argument("--replacement-complete", action="store_true")
    decision_parser.set_defaults(function=decide_reuse)

    readiness_parser = subparsers.add_parser("readiness")
    readiness_parser.add_argument("--manifest", type=Path, required=True)
    readiness_parser.add_argument("--package", type=Path, required=True)
    readiness_parser.add_argument("--decision-log", type=Path, required=True)
    readiness_parser.add_argument(
        "--reprocessing-record",
        action="append",
        default=[],
        type=Path,
        help="additive correction record whose embedded reuse decision is required",
    )
    readiness_parser.add_argument("--output", type=Path, required=True)
    readiness_parser.set_defaults(function=readiness)

    args = parser.parse_args()
    try:
        result = args.function(args)
    except (OSError, ValueError, S48PreliminaryError) as exc:
        print(f"S4.8 preliminary workflow failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    succeeded = result.get("status") == "passed" or args.operation == "decide-reuse"
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
