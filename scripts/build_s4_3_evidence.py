#!/usr/bin/env python3
"""Build deterministic S4.3 reports and complete tracked/raw evidence indexes."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import sha256_file
from isaac_audio_sensors.acquisition.s4_3 import (
    S43Error,
    aggregate_category,
    analyze_noise_characterization,
    analyze_trial_wav,
    build_channel_evidence,
    canonical_sha256,
    evaluate_repeatability,
    inventory_from_attempts,
    load_json,
    load_pilot_configuration,
    validate_corrective_provenance,
    validate_inventory,
    validate_metric_evidence,
    validate_preregistration,
    validate_review_remediation_manifest,
    verify_deterministic_replay,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/isaac_audio_sensors/S4/S4.3"
DEFAULT_REVIEW_REMEDIATION = DEFAULT_OUTPUT / "freeze/review_remediation_manifest.json"
DEFAULT_REVIEW_CONFIG = ROOT / "configs/s4_3_pilot_amendment_04.v1.json"
DEFAULT_REVIEW_PREREGISTRATION = (
    DEFAULT_OUTPUT / "freeze/preregistration_amendment_04.json"
)


def _trial(configuration: dict[str, Any], trial_id: str) -> dict[str, Any]:
    return next(
        item for item in configuration["matrix"] if item["trial_id"] == trial_id
    )


def _attempt_paths(
    inventory: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (entry, attempt)
        for entry in inventory["trials"]
        for attempt in entry["attempts"]
    ]


def _parse_checksums(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        if "  " not in line:
            raise S43Error(f"{path}:{number}: malformed checksum line")
        digest, relative = line.split("  ", 1)
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise S43Error(f"{path}:{number}: invalid SHA-256")
        if not relative or relative in records or ".." in Path(relative).parts:
            raise S43Error(f"{path}:{number}: unsafe or duplicate path")
        records[relative] = digest
    return records


def _verify_attempt(attempt_root: Path, *, outcome: str) -> dict[str, Any]:
    issues = []
    final_checksum = attempt_root / "SHA256SUMS.final"
    primary_checksum = (
        final_checksum if final_checksum.is_file() else attempt_root / "SHA256SUMS"
    )
    if not primary_checksum.is_file():
        if outcome == "accepted":
            return {
                "status": "failed",
                "issues": ["accepted attempt SHA256SUMS missing"],
                "checked": 0,
            }
        required_failure = ["contract.json", "lifecycle.json", "failure.json"]
        missing = [
            name for name in required_failure if not (attempt_root / name).is_file()
        ]
        return {
            "status": "passed" if not missing else "failed",
            "issues": [f"missing retained failure record: {name}" for name in missing],
            "checked": len(required_failure) - len(missing),
            "failure_evidence_without_media": True,
        }
    checksum_paths = [
        primary_checksum,
        *sorted(attempt_root.glob("SHA256SUMS.amendment_*")),
    ]
    checked = 0
    for checksum_path in checksum_paths:
        try:
            records = _parse_checksums(checksum_path)
        except (OSError, S43Error) as exc:
            issues.append(str(exc))
            continue
        checked += len(records)
        for relative, expected in records.items():
            candidate = (attempt_root / relative).resolve()
            try:
                candidate.relative_to(attempt_root.resolve())
            except ValueError:
                issues.append(f"unsafe path: {relative}")
                continue
            if not candidate.is_file():
                issues.append(f"missing: {relative}")
            elif sha256_file(candidate) != expected:
                issues.append(f"checksum mismatch: {relative}")
    return {
        "status": "passed" if not issues else "failed",
        "checked": checked,
        "checksum_manifests": [
            path.relative_to(attempt_root).as_posix() for path in checksum_paths
        ],
        "issues": issues,
    }


def _artifact(path: Path, *, role: str, retention: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "role": role,
        "retention": retention,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _condition_deltas(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = [report for report in analyses if report["category"] == "repeatability"]
    baseline_rms = [
        report["summary"]["median_raw_rms_full_scale"]["median"] for report in baseline
    ]
    baseline_confidence = [
        report["summary"]["confidence"]["median"] for report in baseline
    ]
    baseline_error = [
        report["summary"]["absolute_bearing_error_deg"]["median"]
        for report in baseline
        if report["summary"]["absolute_bearing_error_deg"]["median"] is not None
    ]
    if not baseline or any(
        value is None for value in baseline_rms + baseline_confidence
    ):
        return {"status": "unmeasured", "reason": "complete baseline unavailable"}
    rms_reference = sum(float(value) for value in baseline_rms) / len(baseline_rms)
    confidence_reference = sum(float(value) for value in baseline_confidence) / len(
        baseline_confidence
    )
    error_reference = (
        sum(float(value) for value in baseline_error) / len(baseline_error)
        if baseline_error
        else None
    )
    conditions = []
    for report in analyses:
        if report["category"] != "robustness":
            continue
        rms = report["summary"]["median_raw_rms_full_scale"]["median"]
        confidence = report["summary"]["confidence"]["median"]
        error = report["summary"]["absolute_bearing_error_deg"]["median"]
        conditions.append(
            {
                "trial_id": report["trial_id"],
                "relative_rms_delta_db": (
                    None
                    if rms in {None, 0.0} or rms_reference == 0.0
                    else 20.0 * math.log10(float(rms) / rms_reference)
                ),
                "confidence_delta": (
                    None
                    if confidence is None
                    else float(confidence) - confidence_reference
                ),
                "absolute_bearing_error_delta_deg": (
                    None
                    if error is None or error_reference is None
                    else float(error) - error_reference
                ),
                "abstention_rate": report["summary"]["abstention_rate"],
                "interpretation": "robustness observation; not controlled transfer",
            }
        )
    return {
        "status": "measured",
        "baseline": {
            "mean_trial_median_rms_full_scale": rms_reference,
            "mean_trial_median_confidence": confidence_reference,
            "mean_trial_median_absolute_bearing_error_deg": error_reference,
        },
        "conditions": conditions,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    configuration = load_pilot_configuration(args.config, repo_root=ROOT)
    preregistration = load_json(args.preregistration)
    freeze = validate_preregistration(
        configuration,
        preregistration,
        repo_root=ROOT,
        verify_implementation_hashes=False,
    )
    if not freeze.passed:
        raise S43Error(f"preregistration failed: {freeze.to_dict()}")
    corrective_validation = validate_corrective_provenance(
        configuration,
        preregistration,
        repo_root=ROOT,
    )
    if not corrective_validation.passed:
        raise S43Error(
            f"corrective provenance failed: {corrective_validation.to_dict()}"
        )
    review_remediation = load_json(args.review_remediation)
    review_configuration = load_pilot_configuration(args.review_config, repo_root=ROOT)
    review_preregistration = load_json(args.review_preregistration)
    review_validation = validate_review_remediation_manifest(
        review_configuration,
        review_preregistration,
        review_remediation,
        repo_root=ROOT,
        verify_implementation_hashes=False,
    )
    if not review_validation.passed:
        raise S43Error(
            f"review remediation manifest failed: {review_validation.to_dict()}"
        )
    output = args.output.resolve()
    try:
        output.relative_to(DEFAULT_OUTPUT.resolve())
    except ValueError as exc:
        raise S43Error(
            f"output must remain under the S4.3 evidence root: {DEFAULT_OUTPUT}"
        ) from exc
    output.mkdir(parents=True, exist_ok=True)
    reports_root = output / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    validation_root = output / "validation"
    validation_root.mkdir(parents=True, exist_ok=True)

    inventory = inventory_from_attempts(configuration, repo_root=ROOT)
    inventory_report = validate_inventory(inventory, configuration)
    if not args.allow_in_progress and inventory["status"] != "terminal":
        terminal_count = inventory["terminal_trial_count"]
        planned_count = inventory["planned_trial_count"]
        raise S43Error(
            f"only {terminal_count}/{planned_count} planned trials have "
            "terminal outcomes"
        )
    if not inventory_report.passed and not args.allow_in_progress:
        raise S43Error(f"inventory validation failed: {inventory_report.to_dict()}")
    write_json_atomic(output / "trial_inventory.json", inventory)

    analyses: list[dict[str, Any]] = []
    replay_checks = []
    machine_checks = []
    failures = []
    channel_evidence = []
    noise_characterization_results = []
    coarse_audio_video_association: dict[str, Any] | None = None
    impact_svo_replay: dict[str, Any] | None = None
    reference_path = ROOT / configuration["reference"]["local_path"]
    for entry, attempt in _attempt_paths(inventory):
        attempt_root = ROOT / attempt["attempt_root"]
        trial = _trial(configuration, entry["trial_id"])
        integrity = _verify_attempt(attempt_root, outcome=attempt["outcome"])
        machine_checks.append(
            {
                "trial_id": entry["trial_id"],
                "attempt_id": attempt["attempt_id"],
                "integrity": integrity,
            }
        )
        if attempt["outcome"] != "accepted":
            failed_analysis_path = attempt_root / "analysis.json"
            failed_analysis = (
                load_json(failed_analysis_path)
                if failed_analysis_path.is_file()
                else None
            )
            channel_evidence.append(
                build_channel_evidence(
                    failed_analysis,
                    trial,
                    configuration,
                    attempt_id=attempt["attempt_id"],
                    outcome=attempt["outcome"],
                )
            )
            failures.append(
                {
                    "trial_id": entry["trial_id"],
                    "attempt_id": attempt["attempt_id"],
                    "outcome": attempt["outcome"],
                    "reason": attempt["reason"],
                    "retained": True,
                }
            )
            continue
        stored_path = attempt_root / "analysis.json"
        wav_path = attempt_root / "raw/respeaker_audio.wav"
        stored = load_json(stored_path)
        active_configuration_sha256 = canonical_sha256(configuration)
        superseded_configuration_sha256 = (
            configuration.get("configuration_source", {})
            .get("supersedes", {})
            .get("effective_canonical_sha256")
        )
        accepted_configuration_hashes = {active_configuration_sha256}
        if isinstance(superseded_configuration_sha256, str):
            accepted_configuration_hashes.add(superseded_configuration_sha256)
        equivalent_configuration_hashes = (
            configuration.get("configuration_source", {})
            .get("supersedes", {})
            .get("scientifically_equivalent_effective_canonical_sha256", [])
        )
        if not isinstance(equivalent_configuration_hashes, list) or any(
            not isinstance(value, str) for value in equivalent_configuration_hashes
        ):
            raise S43Error("invalid scientifically equivalent configuration hashes")
        accepted_configuration_hashes.update(equivalent_configuration_hashes)
        stored_configuration_sha256 = stored.get("configuration_sha256")
        if stored_configuration_sha256 not in accepted_configuration_hashes:
            amendment_filename = configuration.get("analysis_frame_correction", {}).get(
                "reanalyzed_filename"
            )
            if not isinstance(amendment_filename, str):
                raise S43Error(
                    f"{attempt_root}: accepted analysis predates active configuration "
                    "and no immutable reanalysis is declared"
                )
            stored_path = attempt_root / amendment_filename
            stored = load_json(stored_path)
            if stored.get("configuration_sha256") not in (
                accepted_configuration_hashes
            ):
                raise S43Error(
                    f"{stored_path}: reanalysis configuration SHA-256 differs"
                )
        replayed = analyze_trial_wav(
            wav_path,
            trial,
            configuration,
            reference_path=(
                reference_path if "mac_reference" in trial["stimulus"] else None
            ),
        )
        replay = verify_deterministic_replay(stored, replayed)
        replay_checks.append(
            {
                "trial_id": entry["trial_id"],
                "attempt_id": attempt["attempt_id"],
                "validation": replay.to_dict(),
            }
        )
        for stored_window, replayed_window in zip(
            stored.get("windows", []), replayed.get("windows", []), strict=True
        ):
            for runtime_field in (
                "analysis_runtime_ms",
                "capture_to_frame_offline_ms",
                "frame_to_adapter_round_trip_ms",
            ):
                replayed_window[runtime_field] = stored_window[runtime_field]
        analyses.append(replayed)
        channel_evidence.append(
            build_channel_evidence(
                replayed,
                trial,
                configuration,
                attempt_id=attempt["attempt_id"],
                outcome=attempt["outcome"],
            )
        )
        noise_characterization_results.append(
            analyze_noise_characterization(wav_path, replayed, trial, configuration)
        )
        if entry["trial_id"] == "s4_3_rob_impact_av_01":
            association_path = attempt_root / "coarse_audio_video_association.json"
            replay_path = attempt_root / "zed_svo_replay.json"
            coarse_audio_video_association = load_json(association_path)
            impact_svo_replay = load_json(replay_path)

    category_reports = {}
    for category in ("repeatability", "controlled", "robustness"):
        report = aggregate_category(
            category,
            analyses,
            inventory,
            configuration=configuration,
            channel_evidence=channel_evidence,
            noise_transient_results=noise_characterization_results,
            coarse_audio_video_association=coarse_audio_video_association,
        )
        if category == "robustness":
            report["condition_deltas"] = _condition_deltas(analyses)
        category_reports[category] = report
        write_json_atomic(reports_root / f"{category}.json", report)
    repeatability = evaluate_repeatability(analyses, configuration)
    write_json_atomic(reports_root / "repeatability_gate.json", repeatability)
    failure_report = {
        "schema": "ias.s4_3.failure_inventory.v1",
        "failure_count": len(failures),
        "failures": failures,
        "all_failures_retained": True,
    }
    write_json_atomic(output / "failures.json", failure_report)
    deterministic = {
        "schema": "ias.s4_3.deterministic_replay.v1",
        "status": (
            "passed"
            if replay_checks
            and all(item["validation"]["status"] == "passed" for item in replay_checks)
            else "failed"
        ),
        "accepted_attempt_count": len(replay_checks),
        "checks": replay_checks,
    }
    write_json_atomic(validation_root / "deterministic_replay.json", deterministic)
    machine = {
        "schema": "ias.s4_3.machine_local_validation.v1",
        "status": (
            "passed"
            if machine_checks
            and all(item["integrity"]["status"] == "passed" for item in machine_checks)
            else "failed"
        ),
        "machine_local_root": configuration["retention"]["machine_local_root"],
        "replicated": False,
        "fresh_clone_raw_available": False,
        "attempt_count": len(machine_checks),
        "checks": machine_checks,
    }
    write_json_atomic(validation_root / "machine_local_validation.json", machine)
    raw_independent = {
        "schema": "ias.s4_3.raw_independent_validation.v1",
        "status": (
            "passed"
            if freeze.passed
            and review_validation.passed
            and corrective_validation.passed
            and (inventory_report.passed or args.allow_in_progress)
            else "failed"
        ),
        "preregistration": freeze.to_dict(),
        "review_remediation": review_validation.to_dict(),
        "corrective_provenance": corrective_validation.to_dict(),
        "inventory_contract": inventory_report.to_dict(),
        "raw_required": False,
        "scope": (
            "frozen specification, configuration, matrix, schemas, and "
            "inventory semantics"
        ),
    }
    write_json_atomic(
        validation_root / "raw_independent_validation.json", raw_independent
    )

    coverage = validate_metric_evidence(
        configuration,
        analyses,
        inventory,
        category_reports,
        channel_evidence,
        noise_characterization_results,
        failure_report,
        coarse_audio_video_association,
        impact_svo_replay,
    )
    write_json_atomic(validation_root / "evidence_coverage.json", coverage)

    freeze_root = ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze"
    diagnostic_root = ROOT / "outputs/isaac_audio_sensors/S4/S4.3/diagnostics"
    tracked_paths = [
        ROOT / "docs/development/specs/s4_3_pilot_repeatability.md",
        ROOT / "configs/s4_3_pilot.v1.json",
        freeze_root / "preregistration.json",
        freeze_root / "trial_inventory_precollection.json",
        freeze_root / "preregistration_superseded_y_sign.json",
        freeze_root / "trial_inventory_precollection_superseded_y_sign.json",
        freeze_root / "preregistration_superseded_single_frame_y_sign.json",
        freeze_root
        / "trial_inventory_precollection_superseded_single_frame_y_sign.json",
        ROOT / str(preregistration["specification"]["path"]),
        ROOT / args.config,
        ROOT / args.preregistration,
        freeze_root / "trial_inventory_amendment_01_precollection.json",
        freeze_root / "amendment_01_supersession.json",
        ROOT / "docs/development/specs/s4_3_pilot_repeatability_amendment_02.md",
        ROOT / "configs/s4_3_pilot_amendment_02.v1.json",
        freeze_root / "preregistration_amendment_02.json",
        freeze_root / "trial_inventory_amendment_02_precollection.json",
        freeze_root / "amendment_02_supersession.json",
        ROOT / "docs/development/specs/s4_3_pilot_repeatability_amendment_03.md",
        ROOT / "configs/s4_3_pilot_amendment_03.v1.json",
        freeze_root / "preregistration_amendment_03.json",
        freeze_root / "trial_inventory_amendment_03_precollection.json",
        diagnostic_root / "bearing_frame_contradiction_20260721T185522Z.json",
        freeze_root / "amendment_03_supersession.json",
        ROOT / "docs/development/specs/s4_3_pilot_repeatability_amendment_04.md",
        ROOT / "configs/s4_3_pilot_amendment_04.v1.json",
        freeze_root / "preregistration_amendment_04.json",
        freeze_root / "trial_inventory_amendment_04_precollection.json",
        ROOT / args.review_remediation,
        ROOT / "docs/development/specs/s4_3_pilot_corrective_01.md",
        ROOT / args.config,
        ROOT / args.preregistration,
        freeze_root / "clipping_corrective_01.json",
        freeze_root / "transient_event_contract_01.json",
        freeze_root / "trial_inventory_corrective_01_precollection.json",
        freeze_root / "corrective_01_supersession.json",
        diagnostic_root / "voice_interactive_timing_failure_20260721T201200Z.json",
        diagnostic_root / "corrective_01_precollection_gate.json",
        diagnostic_root / "corrective_01_precollection/trial_inventory.json",
        diagnostic_root
        / "corrective_01_precollection/validation/deterministic_replay.json",
        diagnostic_root
        / "corrective_01_precollection/validation/raw_independent_validation.json",
        diagnostic_root
        / "corrective_01_precollection/validation/evidence_coverage.json",
        ROOT / "docs/development/specs/s4_3_pilot_corrective_02.md",
        freeze_root / "boundary_defect_reproduction_02.json",
        freeze_root / "transient_event_contract_02.json",
        freeze_root / "trial_inventory_corrective_02_precollection.json",
        freeze_root / "corrective_02_supersession.json",
        diagnostic_root / "corrective_02_precollection_gate.json",
        diagnostic_root / "corrective_02_precollection/trial_inventory.json",
        diagnostic_root
        / "corrective_02_precollection/validation/deterministic_replay.json",
        diagnostic_root
        / "corrective_02_precollection/validation/raw_independent_validation.json",
        diagnostic_root
        / "corrective_02_precollection/validation/evidence_coverage.json",
        ROOT / "src/isaac_audio_sensors/acquisition/s4_3.py",
        ROOT / "scripts/run_s4_3_trial.py",
        ROOT / "scripts/reanalyze_s4_3_array_frame.py",
        ROOT / "scripts/annotate_s4_3_av.py",
        ROOT / "scripts/build_s4_3_evidence.py",
        ROOT / "scripts/validate_s4_3_integrity.py",
        ROOT / "tests/test_s4_3_pilot.py",
        output / "trial_inventory.json",
        output / "failures.json",
        reports_root / "repeatability.json",
        reports_root / "controlled.json",
        reports_root / "robustness.json",
        reports_root / "repeatability_gate.json",
        validation_root / "deterministic_replay.json",
        validation_root / "machine_local_validation.json",
        validation_root / "raw_independent_validation.json",
        validation_root / "evidence_coverage.json",
    ]
    if output == DEFAULT_OUTPUT.resolve():
        tracked_paths.extend(
            path
            for path in (
                ROOT / "docs/development/closeouts/S4/s4_3_pilot_repeatability.md",
                output / "repository_gate.json",
                validation_root / "repository_validation.json",
                validation_root / "final_integrity_validation.json",
            )
            if path.is_file()
        )
    tracked_paths = list(dict.fromkeys(tracked_paths))
    raw_root = ROOT / configuration["retention"]["machine_local_root"]
    raw_paths = (
        sorted(path for path in raw_root.rglob("*") if path.is_file())
        if raw_root.is_dir()
        else []
    )
    evidence_index = {
        "schema": "ias.s4_3.evidence_index.v1",
        "status": (
            "passed"
            if all(
                record["status"] == "passed"
                for record in (deterministic, machine, raw_independent, coverage)
            )
            and repeatability["status"] == "passed"
            else "failed"
        ),
        "tracked_artifact_count": len(tracked_paths),
        "machine_local_artifact_count": len(raw_paths),
        "artifacts": [
            *[
                _artifact(path, role="tracked_s4_3_evidence", retention="git_tracked")
                for path in tracked_paths
            ],
            *[
                _artifact(
                    path,
                    role="machine_local_s4_3_evidence",
                    retention="machine_local_gitignored",
                )
                for path in raw_paths
            ],
        ],
        "outcome_counts": dict(
            Counter(attempt["outcome"] for _entry, attempt in _attempt_paths(inventory))
        ),
        "s4_4_started": False,
    }
    write_json_atomic(output / "evidence_index.json", evidence_index)
    checksums = "".join(
        f"{record['sha256']}  {record['path']}\n"
        for record in sorted(evidence_index["artifacts"], key=lambda item: item["path"])
    )
    (output / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    return {
        "status": evidence_index["status"],
        "planned_trial_count": inventory["planned_trial_count"],
        "terminal_trial_count": inventory["terminal_trial_count"],
        "accepted_analysis_count": len(analyses),
        "repeatability_status": repeatability["status"],
        "failure_count": len(failures),
        "tracked_artifact_count": len(tracked_paths),
        "machine_local_artifact_count": len(raw_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/s4_3_pilot_corrective_02.v1.json"),
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=Path(
            "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
            "preregistration_corrective_02.json"
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--review-remediation", type=Path, default=DEFAULT_REVIEW_REMEDIATION
    )
    parser.add_argument("--review-config", type=Path, default=DEFAULT_REVIEW_CONFIG)
    parser.add_argument(
        "--review-preregistration",
        type=Path,
        default=DEFAULT_REVIEW_PREREGISTRATION,
    )
    parser.add_argument("--allow-in-progress", action="store_true")
    args = parser.parse_args()
    try:
        result = build(args)
    except (OSError, S43Error, ValueError) as exc:
        print(f"S4.3 evidence build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
