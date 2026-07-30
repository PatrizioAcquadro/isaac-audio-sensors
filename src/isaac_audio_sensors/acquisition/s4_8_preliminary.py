"""Four-take, diagnostic-only S4.8 preliminary workflow controls."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    run_presealing_gate_from_engineering_files,
    validate_engineering_process_journal,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_campaign import (
    S48EngineeringCampaignError,
    build_reference_take_manifest,
    validate_attempt_ledger_with_reprocessing,
    validate_preliminary_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.core import acceptance_criteria_corrective_03

CONFIG_PATH = Path("configs/s4_8_preliminary_workflow.v1.json")
CONFIG_SCHEMA_PATH = Path("docs/schemas/s4_8_preliminary_workflow.v1.schema.json")
REPROCESSING_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_preliminary_reprocessing_record.v1.schema.json"
)
REQUIRED_GATES = (
    "acquisition",
    "technical_validation",
    "detector_processing",
    "synchronization",
    "metric_calculation",
    "diagnostic_evaluator",
    "diagnostic_packaging",
)
CASE_IDS = (
    "nominal_reference",
    "low_level_reference",
    "silence",
    "audio_video_impact_with_zed",
)
AUTHORITY_NONE = {
    "creates_grant": False,
    "consumes_grant": False,
    "opens_holdout": False,
    "official_state_machine": False,
    "publishes_official_evidence": False,
    "freezes_final_protocol": False,
    "starts_official_acquisition": False,
}
DIAGNOSTIC_CLASSIFICATION = {
    "engineering_only": True,
    "uncounted": True,
    "excluded_from_official_holdout": True,
    "safe_to_inspect_and_analyze": True,
    "diagnostic_results_only": True,
    "official_evidence_eligible": False,
}
PHYSICAL_INVALIDATORS = frozenset(
    {
        "physical_acquisition_conditions",
        "playback_path",
        "reference_signal",
        "playback_gain",
        "geometry",
        "device_profile",
        "channel_map",
        "synchronization_assumptions",
        "raw_recording_validity",
    }
)


class S48PreliminaryError(RuntimeError):
    """Fail-closed preliminary workflow error."""


def _candidate_seal_manifest_authenticated(
    *,
    attempt: Path,
    candidate_seal: Mapping[str, Any],
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    campaign_anchor: str,
) -> bool:
    if candidate_seal.get("campaign_manifest_sha256") is not None:
        return candidate_seal.get("campaign_manifest_sha256") == campaign_anchor
    take_manifest = _load_json(attempt / "take_precollection_manifest.json")
    try:
        expected_take_manifest = build_reference_take_manifest(
            campaign_manifest=campaign_manifest,
            take=take,
            expected_campaign_manifest_sha256=campaign_anchor,
        )
    except S48EngineeringCampaignError as exc:
        raise S48PreliminaryError(
            f"candidate seal precollection manifest is invalid: {exc}"
        ) from exc
    return (
        candidate_seal.get("manifest_sha256")
        == take_manifest.get("manifest_sha256")
        and take_manifest == expected_take_manifest
    )


def load_workflow_config(repo_root: Path) -> dict[str, Any]:
    """Load the active workflow and authenticate its frozen v9 dependency."""

    root = repo_root.resolve()
    config = _load_json(root / CONFIG_PATH)
    schema = _load_json(root / CONFIG_SCHEMA_PATH)
    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise S48PreliminaryError(
            f"preliminary workflow schema failure: {exc.message}"
        ) from exc
    acquisition = config["acquisition_contract"]
    path = root / _safe_relative(acquisition["path"])
    if _sha256_file(path) != acquisition["sha256"]:
        raise S48PreliminaryError(
            "preliminary workflow acquisition contract hash mismatch"
        )
    if config["authority"] != AUTHORITY_NONE:
        raise S48PreliminaryError("preliminary workflow authority is invalid")
    return config


def build_reuse_decision(
    *,
    correction_id: str,
    change_class: str,
    affected_case_ids: Sequence[str],
    raw_sha256_by_case: Mapping[str, str],
    decision: str,
    technical_justification: str,
    physical_confirmation: str,
    physical_confirmation_evidence: str | None,
    replacement_complete: bool,
) -> dict[str, Any]:
    """Build one evidence-based reuse or reacquisition decision."""

    cases = list(affected_case_ids)
    if (
        not correction_id
        or change_class
        not in {"downstream_code", "detector_or_processing", *PHYSICAL_INVALIDATORS}
        or not cases
        or len(set(cases)) != len(cases)
        or any(case not in CASE_IDS for case in cases)
        or set(raw_sha256_by_case) != set(cases)
        or not all(_is_sha256(value) for value in raw_sha256_by_case.values())
        or decision not in {"reuse", "reacquire"}
        or not technical_justification.strip()
        or not isinstance(replacement_complete, bool)
        or (
            physical_confirmation_evidence is not None
            and not isinstance(physical_confirmation_evidence, str)
        )
        or physical_confirmation
        not in {
            "not_applicable",
            "not_required_by_evidence",
            "required_pending",
            "completed",
        }
    ):
        raise S48PreliminaryError("reuse decision fields are invalid")
    if change_class in PHYSICAL_INVALIDATORS and decision != "reacquire":
        raise S48PreliminaryError(
            "physical acquisition invalidators require affected-take replacement"
        )
    if change_class in PHYSICAL_INVALIDATORS:
        if replacement_complete:
            if (
                physical_confirmation != "completed"
                or not physical_confirmation_evidence
            ):
                raise S48PreliminaryError(
                    "completed replacement requires physical confirmation evidence"
                )
        else:
            physical_confirmation = "required_pending"
    if change_class == "downstream_code" and decision != "reuse":
        raise S48PreliminaryError(
            "downstream-only corrections must reuse technically valid raw takes"
        )
    if change_class == "detector_or_processing":
        if physical_confirmation in {"not_applicable"}:
            raise S48PreliminaryError(
                "detector changes require an explicit physical-confirmation decision"
            )
        if not physical_confirmation_evidence:
            raise S48PreliminaryError(
                "detector physical-confirmation decision requires evidence"
            )
    elif change_class == "downstream_code" and physical_confirmation != (
        "not_applicable"
    ):
        raise S48PreliminaryError(
            "physical-confirmation disposition contradicts change class"
        )
    if decision == "reacquire":
        if replacement_complete and (
            physical_confirmation != "completed" or not physical_confirmation_evidence
        ):
            raise S48PreliminaryError(
                "completed reacquisition requires physical confirmation evidence"
            )
        if not replacement_complete:
            physical_confirmation = "required_pending"
    payload = {
        "schema": "ias.s4_8.preliminary_reuse_decision.v1",
        "correction_id": correction_id,
        "change_class": change_class,
        "affected_case_ids": cases,
        "raw_sha256_by_case": dict(raw_sha256_by_case),
        "decision": decision,
        "technical_justification": technical_justification,
        "physical_confirmation": physical_confirmation,
        "physical_confirmation_evidence": physical_confirmation_evidence,
        "replacement_complete": replacement_complete,
        "automatic_four_take_reacquisition": False,
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    return {**payload, "decision_sha256": canonical_sha256(payload)}


def validate_reuse_decision(decision: Mapping[str, Any]) -> None:
    """Rebuild a decision to validate its rules and canonical hash."""

    rebuilt = build_reuse_decision(
        correction_id=str(decision.get("correction_id", "")),
        change_class=str(decision.get("change_class", "")),
        affected_case_ids=list(decision.get("affected_case_ids", [])),
        raw_sha256_by_case=dict(decision.get("raw_sha256_by_case", {})),
        decision=str(decision.get("decision", "")),
        technical_justification=str(decision.get("technical_justification", "")),
        physical_confirmation=str(decision.get("physical_confirmation", "")),
        physical_confirmation_evidence=decision.get("physical_confirmation_evidence"),
        replacement_complete=bool(decision.get("replacement_complete")),
    )
    if dict(decision) != rebuilt:
        raise S48PreliminaryError("reuse decision is altered or noncanonical")


def reprocess_attempt_gate(
    repo_root: Path,
    *,
    attempt_path: Path,
    reference_path: Path,
) -> dict[str, Any]:
    """Rerun the current gate offline without extending the historical journal."""

    attempt = attempt_path.resolve()
    manifest = _load_json(attempt / "take_precollection_manifest.json")
    journal = _load_json_lines(attempt / "process_journal.jsonl")
    if (
        not journal
        or journal[-1].get("event_type") != "gate_evaluated"
        or journal[-1].get("data", {}).get("decision") != "RETRY_REQUIRED"
    ):
        raise S48PreliminaryError(
            "offline reprocessing requires a retained RETRY_REQUIRED history"
        )
    capture_journal = journal[:-1]
    try:
        return run_presealing_gate_from_engineering_files(
            capture_path=attempt / "respeaker_audio.wav",
            reference_path=reference_path.resolve(),
            manifest=manifest,
            journal=capture_journal,
            expected_manifest_sha256=str(manifest.get("manifest_sha256")),
            repo_root=repo_root.resolve(),
            dry_run=False,
        )
    except Exception as exc:
        raise S48PreliminaryError(f"offline gate reprocessing failed: {exc}") from exc


def build_reprocessing_record(
    repo_root: Path,
    *,
    correction_id: str,
    case_id: str,
    preliminary_take_id: str,
    attempt_number: int,
    attempt_path: Path,
    attempt_ledger_path: Path,
    campaign_manifest_path: Path,
    corrected_report_path: Path,
    corrective_commit: str,
    technical_justification: str,
    physical_confirmation_evidence: str,
) -> dict[str, Any]:
    """Build an additive record that preserves a historical retry decision."""

    root = repo_root.resolve()
    attempt = attempt_path.resolve()
    ledger_path = attempt_ledger_path.resolve()
    campaign_path = campaign_manifest_path.resolve()
    report_path = corrected_report_path.resolve()
    if (
        case_id not in CASE_IDS
        or not correction_id
        or not preliminary_take_id.startswith("s48prelim_")
        or isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
        or len(corrective_commit) != 40
        or any(character not in "0123456789abcdef" for character in corrective_commit)
    ):
        raise S48PreliminaryError("reprocessing record identity is invalid")
    historical_paths = {
        "raw_capture": attempt / "respeaker_audio.wav",
        "retry_report": attempt / "retry_report.json",
        "gate_report": attempt / "gate_report.json",
        "controller_result": attempt / "controller_result.json",
        "process_journal": attempt / "process_journal.jsonl",
        "take_precollection_manifest": attempt / "take_precollection_manifest.json",
        "attempt_ledger": ledger_path,
        "campaign_manifest": campaign_path,
    }
    for path in (*historical_paths.values(), report_path):
        if not path.is_file():
            raise S48PreliminaryError(f"reprocessing artifact is missing: {path}")
    raw_sha256 = _sha256_file(historical_paths["raw_capture"])
    reuse = build_reuse_decision(
        correction_id=correction_id,
        change_class="detector_or_processing",
        affected_case_ids=[case_id],
        raw_sha256_by_case={case_id: raw_sha256},
        decision="reuse",
        technical_justification=technical_justification,
        physical_confirmation="not_required_by_evidence",
        physical_confirmation_evidence=physical_confirmation_evidence,
        replacement_complete=False,
    )
    corrected_report = _load_json(report_path)
    alignment = corrected_report.get("waveform", {}).get("alignment", {})
    longest = alignment.get("longest_continuous_useful_interval", {})
    payload = {
        "schema": "ias.s4_8.preliminary_reprocessing_record.v1",
        "correction_id": correction_id,
        "change_class": "detector_or_processing",
        "case_id": case_id,
        "preliminary_take_id": preliminary_take_id,
        "attempt_number": attempt_number,
        "attempt_path": str(attempt),
        "historical_result": {
            "decision": "RETRY_REQUIRED",
            **{
                name: _artifact_record(path)
                for name, path in historical_paths.items()
            },
            "journal_gate_decision": "RETRY_REQUIRED",
            "ledger_gate_decision": "RETRY_REQUIRED",
        },
        "corrected_offline_result": {
            "decision": "PASS",
            "report": _artifact_record(report_path),
            "report_canonical_sha256": canonical_sha256(corrected_report),
            "corrective_commit": corrective_commit,
            "useful_block_count": alignment.get("useful_block_count"),
            "source_block_count": alignment.get("source_block_count"),
            "useful_sound_coverage": alignment.get("useful_sound_coverage"),
            "continuous_useful_duration_s": longest.get("duration_s"),
            "maximum_non_applicable_gap_s": alignment.get(
                "maximum_non_applicable_gap_s"
            ),
        },
        "reuse_decision": reuse,
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    record = {**payload, "record_sha256": canonical_sha256(payload)}
    validate_reprocessing_record(root, record)
    return record


def resolve_reprocessing_record_paths(
    record: Mapping[str, Any],
    *,
    runtime_campaign_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve an authenticated v1 record after a whole-campaign relocation."""

    take_id = str(record.get("preliminary_take_id", ""))
    attempt_number = record.get("attempt_number")
    declared_attempt = Path(str(record.get("attempt_path", "")))
    if (
        not declared_attempt.is_absolute()
        or not take_id.startswith("s48prelim_")
        or isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
        or len(declared_attempt.parents) < 3
    ):
        raise S48PreliminaryError("reprocessing record path identity is invalid")
    declared_root = declared_attempt.parents[2]
    expected_suffix = (
        Path("attempts")
        / take_id
        / f"{take_id}__attempt_{attempt_number:02d}"
    )
    if declared_attempt != declared_root / expected_suffix:
        raise S48PreliminaryError(
            "reprocessing attempt path does not match its bound identity"
        )
    runtime_root = (
        declared_root
        if runtime_campaign_root is None
        else runtime_campaign_root.resolve()
    )
    if (
        not declared_root.name
        or runtime_root.name != declared_root.name
    ):
        raise S48PreliminaryError(
            "reprocessing campaign relocation changes campaign identity"
        )

    def relocate(value: Any) -> Path:
        source = Path(str(value))
        if not source.is_absolute():
            raise S48PreliminaryError(
                f"reprocessing artifact path is not absolute: {value}"
            )
        try:
            relative = source.relative_to(declared_root)
        except ValueError as exc:
            raise S48PreliminaryError(
                f"reprocessing artifact escapes declared campaign: {value}"
            ) from exc
        resolved = (runtime_root / relative).resolve()
        if resolved != runtime_root and runtime_root not in resolved.parents:
            raise S48PreliminaryError(
                f"reprocessing artifact escapes runtime campaign: {value}"
            )
        return resolved

    historical = record.get("historical_result", {})
    if not isinstance(historical, Mapping):
        raise S48PreliminaryError("reprocessing historical result is invalid")
    historical_paths = {
        name: relocate(historical.get(name, {}).get("path"))
        for name in (
            "raw_capture",
            "retry_report",
            "gate_report",
            "controller_result",
            "process_journal",
            "take_precollection_manifest",
            "attempt_ledger",
            "campaign_manifest",
        )
    }
    corrected = record.get("corrected_offline_result", {})
    if not isinstance(corrected, Mapping):
        raise S48PreliminaryError("reprocessing corrected result is invalid")
    return {
        "declared_campaign_root": declared_root,
        "runtime_campaign_root": runtime_root,
        "attempt_path": runtime_root / expected_suffix,
        "historical_result": historical_paths,
        "corrected_report": relocate(corrected.get("report", {}).get("path")),
    }


def validate_reprocessing_record(
    repo_root: Path,
    record: Mapping[str, Any],
    *,
    expected_attempt_path: Path | None = None,
    expected_case_id: str | None = None,
    runtime_campaign_root: Path | None = None,
) -> dict[str, Any]:
    """Authenticate an additive PASS while retaining the original retry."""

    root = repo_root.resolve()
    schema = _load_json(root / REPROCESSING_SCHEMA_PATH)
    try:
        jsonschema.validate(dict(record), schema)
    except jsonschema.ValidationError as exc:
        raise S48PreliminaryError(
            f"preliminary reprocessing schema failure: {exc.message}"
        ) from exc
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    if record.get("record_sha256") != canonical_sha256(payload):
        raise S48PreliminaryError("preliminary reprocessing record hash mismatch")
    if record.get("classification") != DIAGNOSTIC_CLASSIFICATION or record.get(
        "authority"
    ) != AUTHORITY_NONE:
        raise S48PreliminaryError("preliminary reprocessing boundary is invalid")
    resolved_paths = resolve_reprocessing_record_paths(
        record,
        runtime_campaign_root=runtime_campaign_root,
    )
    attempt = resolved_paths["attempt_path"]
    if expected_attempt_path is not None and attempt != expected_attempt_path.resolve():
        raise S48PreliminaryError("reprocessing record targets a different attempt")
    if expected_case_id is not None and record.get("case_id") != expected_case_id:
        raise S48PreliminaryError("reprocessing record targets a different case")
    historical = record["historical_result"]
    for name in (
        "raw_capture",
        "retry_report",
        "gate_report",
        "controller_result",
        "process_journal",
        "take_precollection_manifest",
        "campaign_manifest",
    ):
        _validate_artifact_record(
            historical[name],
            resolved_path=resolved_paths["historical_result"][name],
        )
    _validate_artifact_record(
        record["corrected_offline_result"]["report"],
        resolved_path=resolved_paths["corrected_report"],
    )
    expected_attempt_artifacts = {
        "raw_capture": attempt / "respeaker_audio.wav",
        "retry_report": attempt / "retry_report.json",
        "gate_report": attempt / "gate_report.json",
        "controller_result": attempt / "controller_result.json",
        "process_journal": attempt / "process_journal.jsonl",
        "take_precollection_manifest": attempt / "take_precollection_manifest.json",
    }
    if any(
        resolved_paths["historical_result"][name] != path
        for name, path in expected_attempt_artifacts.items()
    ):
        raise S48PreliminaryError(
            "reprocessing record does not bind the retained attempt files"
        )
    historical_paths = resolved_paths["historical_result"]
    retry_report = _load_json(historical_paths["retry_report"])
    gate_report = _load_json(historical_paths["gate_report"])
    controller = _load_json(historical_paths["controller_result"])
    manifest = _load_json(historical_paths["take_precollection_manifest"])
    journal = _load_json_lines(historical_paths["process_journal"])
    campaign = _load_json(historical_paths["campaign_manifest"])
    ledger_path = historical_paths["attempt_ledger"]
    ledger = _load_json_lines(ledger_path)
    if (
        retry_report.get("decision") != "RETRY_REQUIRED"
        or gate_report != retry_report
        or controller.get("decision") != "RETRY_REQUIRED"
        or controller.get("report") != retry_report
        or controller.get("preliminary_case_id") != record.get("case_id")
        or controller.get("classification") != DIAGNOSTIC_CLASSIFICATION
        or controller.get("counts_as_official_take") is not False
        or controller.get("official_evidence_eligible") is not False
    ):
        raise S48PreliminaryError(
            "reprocessing record contradicts the historical retry result"
        )
    ledger_matches = [
        item
        for item in ledger
        if item.get("engineering_take_id") == record.get("preliminary_take_id")
        and item.get("attempt_number") == record.get("attempt_number")
    ]
    ledger_artifact = historical["attempt_ledger"]
    if (
        not ledger_path.is_absolute()
        or not _is_sha256(ledger_artifact.get("sha256"))
        or len(ledger_matches) != 1
        or _sha256_jsonl_prefix(
            ledger_path,
            line_count=int(ledger_matches[0]["sequence"]) + 1,
        )
        != ledger_artifact["sha256"]
    ):
        raise S48PreliminaryError(
            "reprocessing record does not bind the retained ledger prefix"
        )
    try:
        validate_engineering_process_journal(
            manifest,
            journal,
            expected_manifest_sha256=str(manifest.get("manifest_sha256")),
            required_terminal_event="gate_evaluated",
        )
        validate_attempt_ledger_with_reprocessing(
            ledger,
            campaign_manifest=campaign,
            expected_campaign_manifest_sha256=str(campaign.get("manifest_sha256")),
            reprocessed_attempts=[
                (
                    str(record["preliminary_take_id"]),
                    int(record["attempt_number"]),
                )
            ],
        )
    except Exception as exc:
        raise S48PreliminaryError(
            f"reprocessing historical provenance validation failed: {exc}"
        ) from exc
    gate_event = journal[-1]
    if (
        gate_event.get("data", {}).get("decision") != "RETRY_REQUIRED"
        or gate_event.get("data", {}).get("report_sha256")
        != canonical_sha256(retry_report)
        or len(ledger_matches) != 1
        or ledger_matches[0].get("decision") != "RETRY_REQUIRED"
        or ledger_matches[0].get("report_sha256") != canonical_sha256(retry_report)
        or ledger_matches[0].get("candidate_seal_sha256") is not None
    ):
        raise S48PreliminaryError(
            "reprocessing record contradicts journal or ledger history"
        )
    corrected = record["corrected_offline_result"]
    corrected_report = _load_json(resolved_paths["corrected_report"])
    alignment = corrected_report.get("waveform", {}).get("alignment", {})
    longest = alignment.get("longest_continuous_useful_interval", {})
    capture_sha256 = historical["raw_capture"]["sha256"]
    if (
        corrected_report.get("decision") != "PASS"
        or corrected_report.get("reasons") != []
        or corrected_report.get("input_provenance", {}).get("capture_sha256")
        != capture_sha256
        or corrected_report.get("input_provenance", {}).get("manifest_sha256")
        != manifest.get("manifest_sha256")
        or corrected_report.get("input_provenance", {}).get(
            "process_journal_head_sha256"
        )
        != journal[-2].get("event_sha256")
        or corrected.get("report_canonical_sha256")
        != canonical_sha256(corrected_report)
        or corrected.get("useful_block_count") != alignment.get("useful_block_count")
        or corrected.get("source_block_count") != alignment.get("source_block_count")
        or corrected.get("useful_sound_coverage")
        != alignment.get("useful_sound_coverage")
        or corrected.get("continuous_useful_duration_s") != longest.get("duration_s")
        or corrected.get("maximum_non_applicable_gap_s")
        != alignment.get("maximum_non_applicable_gap_s")
    ):
        raise S48PreliminaryError("corrected offline PASS binding is invalid")
    reuse = record["reuse_decision"]
    validate_reuse_decision(reuse)
    if (
        reuse.get("correction_id") != record.get("correction_id")
        or reuse.get("affected_case_ids") != [record.get("case_id")]
        or reuse.get("raw_sha256_by_case")
        != {str(record.get("case_id")): capture_sha256}
        or reuse.get("decision") != "reuse"
        or reuse.get("physical_confirmation") != "not_required_by_evidence"
    ):
        raise S48PreliminaryError("reprocessing reuse disposition is invalid")
    return corrected_report


def load_reprocessing_record(
    repo_root: Path,
    record_path: Path,
    *,
    expected_attempt_path: Path,
    expected_case_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and authenticate one versioned additive reprocessing record."""

    record = _load_json(record_path.resolve())
    report = validate_reprocessing_record(
        repo_root,
        record,
        expected_attempt_path=expected_attempt_path,
        expected_case_id=expected_case_id,
        runtime_campaign_root=expected_attempt_path.resolve().parents[2],
    )
    return record, report


def process_case(
    repo_root: Path,
    *,
    manifest: Mapping[str, Any],
    case_root: Path,
    case_id: str,
    reprocessing_record_path: Path | None = None,
) -> dict[str, Any]:
    """Authenticate and run the current detector/metric path on one raw case."""

    root = repo_root.resolve()
    anchor = str(manifest.get("manifest_sha256"))
    validate_preliminary_manifest(manifest, expected_manifest_sha256=anchor)
    matches = [
        item
        for item in manifest["design"]
        if item.get("preliminary_case_id") == case_id
    ]
    if len(matches) != 1:
        raise S48PreliminaryError(
            "case is absent or duplicated in preliminary manifest"
        )
    take = matches[0]
    attempt = case_root.resolve()
    capture = attempt / "respeaker_audio.wav"
    controller_result = _load_json(attempt / "controller_result.json")
    capture_sha256 = _sha256_file(capture)
    reprocessing_record = None
    if reprocessing_record_path is None:
        gate_report = _load_json(attempt / "gate_report.json")
        candidate_seal = _load_json(attempt / "candidate_seal.json")
        seal_payload = {
            key: value for key, value in candidate_seal.items() if key != "seal_sha256"
        }
        seal_manifest_authenticated = _candidate_seal_manifest_authenticated(
            attempt=attempt,
            candidate_seal=candidate_seal,
            campaign_manifest=manifest,
            take=take,
            campaign_anchor=anchor,
        )
        if (
            controller_result.get("decision") != "PASS"
            or controller_result.get("preliminary_case_id") != case_id
            or controller_result.get("classification") != DIAGNOSTIC_CLASSIFICATION
            or controller_result.get("counts_as_official_take") is not False
            or controller_result.get("official_evidence_eligible") is not False
            or gate_report.get("decision") != "PASS"
            or candidate_seal.get("engineering_only") is not True
            or candidate_seal.get("authority", {}).get("official_state_machine")
            is not False
            or candidate_seal.get("authority", {}).get(
                "publishes_official_evidence"
            )
            is not False
            or candidate_seal.get("capture_sha256") != capture_sha256
            or not seal_manifest_authenticated
            or candidate_seal.get("report_sha256") != canonical_sha256(gate_report)
            or candidate_seal.get("seal_sha256") != canonical_sha256(seal_payload)
            or (
                candidate_seal.get("engineering_take_definition_sha256") is not None
                and candidate_seal.get("engineering_take_definition_sha256")
                != take["engineering_take_definition_sha256"]
            )
        ):
            raise S48PreliminaryError(
                "acquisition artifacts did not pass authentication"
            )
        acquisition_source = "original_pass"
        historical_acquisition_decision = "PASS"
    else:
        reprocessing_record, gate_report = load_reprocessing_record(
            root,
            reprocessing_record_path,
            expected_attempt_path=attempt,
            expected_case_id=case_id,
        )
        if (
            reprocessing_record.get("preliminary_take_id")
            != take["engineering_take_id"]
            or gate_report.get("decision") != "PASS"
            or controller_result.get("decision") != "RETRY_REQUIRED"
            or controller_result.get("preliminary_case_id") != case_id
        ):
            raise S48PreliminaryError(
                "additive reprocessing record does not select this case"
            )
        acquisition_source = "additive_reprocessing_record"
        historical_acquisition_decision = "RETRY_REQUIRED"
    registry = acceptance_criteria_corrective_03.build_identity_registry(root)
    source_take_id = take["template_planned_take_id"]
    identity = registry.get(source_take_id)
    if identity is None:
        raise S48PreliminaryError("preliminary case has no evaluator identity")
    runs_root = root / "runs"
    runs_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="s4_8_preliminary_processing_", dir=runs_root
    ) as temporary:
        staging_root = Path(temporary)
        staging_attempt = (
            staging_root / "attempts" / source_take_id / f"{source_take_id}__diagnostic"
        )
        raw_root = staging_attempt / "raw"
        raw_root.mkdir(parents=True)
        shutil.copyfile(capture, raw_root / "respeaker_audio.wav")
        _write_json(
            staging_attempt / "technical_qa.json",
            {
                "schema": "ias.s4_8.preliminary_technical_qa_adapter.v1",
                "overall_technical_pass": True,
                "source_gate_report_sha256": canonical_sha256(gate_report),
                "diagnostic_only": True,
            },
        )
        if case_id == "audio_video_impact_with_zed":
            _stage_av_inputs(
                attempt,
                staging_attempt=staging_attempt,
                source_take_id=source_take_id,
                expected_hashes=gate_report["input_provenance"]["zed_artifact_hashes"],
            )
        artifacts = []
        for path in sorted(staging_attempt.rglob("*")):
            if path.is_file():
                artifacts.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "byte_size": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
        seal = {"artifacts": artifacts}
        profile = s4_8._profile_runtime(root)
        derived, inventory = s4_8._analyze_real_take(
            root,
            staging_attempt,
            identity,
            profile=profile,
            seal=seal,
        )
    return {
        "schema": "ias.s4_8.preliminary_case_processing.v1",
        "case_id": case_id,
        "preliminary_take_id": take["engineering_take_id"],
        "source_evaluator_take_id": source_take_id,
        "raw_capture_sha256": capture_sha256,
        "acquisition_gate": "PASS",
        "acquisition_source": acquisition_source,
        "historical_acquisition_decision": historical_acquisition_decision,
        "corrected_offline_decision": gate_report["decision"],
        "reprocessing_record_sha256": (
            None
            if reprocessing_record is None
            else reprocessing_record["record_sha256"]
        ),
        "fresh_physical_confirmation_required": (
            False
            if reprocessing_record is not None
            else None
        ),
        "technical_validation_gate": "PASS",
        "detector_processing_gate": "PASS",
        "synchronization_gate": (
            "PASS" if case_id == "audio_video_impact_with_zed" else "NOT_APPLICABLE"
        ),
        "derived_take": derived,
        "inventory": inventory,
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def build_diagnostic_payload(
    repo_root: Path,
    case_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replace four synthetic representatives with processed preliminary takes."""

    if {item.get("case_id") for item in case_results} != set(CASE_IDS):
        raise S48PreliminaryError("exactly four distinct case results are required")
    payload = acceptance_criteria_corrective_03.build_synthetic_payload(
        repo_root.resolve()
    )
    replacements = {
        item["source_evaluator_take_id"]: deepcopy(item["derived_take"])
        for item in case_results
    }
    runtime_alignment = _runtime_domain_alignment(list(replacements.values()))
    replaced = []
    for index, take in enumerate(payload["takes"]):
        take_id = take["identity"]["planned_take_id"]
        if take_id in replacements:
            payload["takes"][index] = replacements[take_id]
            replaced.append(take_id)
        else:
            take["latency"].update(runtime_alignment)
    if set(replaced) != set(replacements):
        raise S48PreliminaryError("diagnostic evaluator replacement is incomplete")
    return payload


def _runtime_domain_alignment(
    derived_takes: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Impute runtime-only synthetic fields from the real diagnostic host."""

    fields = (
        "capture_to_frame_offline_ms",
        "frame_to_adapter_round_trip_ms",
    )
    values: dict[str, list[float]] = {field: [] for field in fields}
    for take in derived_takes:
        latency = take.get("latency")
        if not isinstance(latency, Mapping):
            raise S48PreliminaryError("derived take lacks runtime latency")
        for field in fields:
            value = latency.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise S48PreliminaryError(f"invalid derived runtime latency: {field}")
            values[field].append(float(value))
    if any(len(records) != len(CASE_IDS) for records in values.values()):
        raise S48PreliminaryError("runtime alignment requires all four real takes")
    return {field: float(median(records)) for field, records in values.items()}


def run_diagnostic_evaluator(
    repo_root: Path,
    *,
    manifest: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run the exact evaluator with explicit synthetic completion."""

    anchor = str(manifest.get("manifest_sha256"))
    validate_preliminary_manifest(manifest, expected_manifest_sha256=anchor)
    runtime_alignment = _runtime_domain_alignment(
        [item["derived_take"] for item in case_results]
    )
    payload = build_diagnostic_payload(repo_root, case_results)
    try:
        evaluation = acceptance_criteria_corrective_03.evaluate_corrective(
            payload, repo_root=repo_root.resolve()
        ).report()
        gate = "PASS" if evaluation["readiness_passed"] is True else "FAIL"
        failure_class = None if gate == "PASS" else "evaluator"
    except Exception as exc:
        evaluation = {
            "schema": "ias.s4_8.preliminary_evaluator_failure.v1",
            "status": "failed",
            "readiness_passed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        gate = "FAIL"
        failure_class = "evaluator"
    return {
        "schema": "ias.s4_8.preliminary_diagnostic_evaluation.v1",
        "status": "passed" if gate == "PASS" else "failed",
        "gate": gate,
        "failure_class": failure_class,
        "preliminary_manifest_sha256": anchor,
        "raw_preliminary_take_count": 4,
        "synthetic_completion_take_count": 43,
        "synthetic_completion": {
            "method": "synthetic_scientific_completion_with_real_runtime_domain",
            "runtime_domain_alignment": runtime_alignment,
            "real_runtime_take_count": 4,
            "synthetic_runtime_imputation_take_count": 43,
        },
        "official_take_count": 0,
        "payload_sha256": canonical_sha256(payload),
        "evaluation": evaluation,
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "official_s4_8_pass_claimed": False,
        "authority": dict(AUTHORITY_NONE),
    }


def build_diagnostic_package(
    *,
    manifest: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an in-memory, self-authenticating diagnostic package index."""

    anchor = str(manifest.get("manifest_sha256"))
    validate_preliminary_manifest(manifest, expected_manifest_sha256=anchor)
    if evaluation.get("preliminary_manifest_sha256") != anchor:
        raise S48PreliminaryError("evaluation is bound to a different manifest")
    case_hashes = {
        str(item["case_id"]): canonical_sha256(item) for item in case_results
    }
    gates = {
        "acquisition": all(
            item.get("acquisition_gate") == "PASS" for item in case_results
        ),
        "technical_validation": all(
            item.get("technical_validation_gate") == "PASS" for item in case_results
        ),
        "detector_processing": all(
            item.get("detector_processing_gate") == "PASS" for item in case_results
        ),
        "synchronization": all(
            item.get("synchronization_gate") in {"PASS", "NOT_APPLICABLE"}
            for item in case_results
        ),
        "metric_calculation": len(case_results) == 4,
        "diagnostic_evaluator": evaluation.get("gate") == "PASS",
        "diagnostic_packaging": True,
    }
    payload = {
        "schema": "ias.s4_8.preliminary_diagnostic_package.v1",
        "status": "passed" if all(gates.values()) else "failed",
        "preliminary_manifest_sha256": anchor,
        "case_result_sha256": case_hashes,
        "evaluation_sha256": canonical_sha256(evaluation),
        "gates": {
            name: {
                "status": "PASS" if passed else "FAIL",
                "failure_class": None if passed else _failure_class(name),
            }
            for name, passed in gates.items()
        },
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "official_s4_8_evidence": False,
        "official_s4_8_pass_claimed": False,
        "authority": dict(AUTHORITY_NONE),
    }
    return {**payload, "package_sha256": canonical_sha256(payload)}


def build_readiness_report(
    *,
    manifest: Mapping[str, Any],
    package: Mapping[str, Any],
    reuse_decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Permit a later freeze only after all preliminary controls pass."""

    anchor = str(manifest.get("manifest_sha256"))
    validate_preliminary_manifest(manifest, expected_manifest_sha256=anchor)
    latest_decisions: dict[str, Mapping[str, Any]] = {}
    for decision in reuse_decisions:
        validate_reuse_decision(decision)
        latest_decisions[str(decision["correction_id"])] = decision
    package_payload = {
        key: value for key, value in package.items() if key != "package_sha256"
    }
    package_authentic = package.get("package_sha256") == canonical_sha256(
        package_payload
    )
    unresolved = [
        decision["correction_id"]
        for decision in latest_decisions.values()
        if decision["physical_confirmation"] == "required_pending"
        or (
            decision["decision"] == "reacquire"
            and decision["replacement_complete"] is not True
        )
    ]
    gates = package.get("gates")
    all_gates_pass = (
        isinstance(gates, Mapping)
        and set(gates) == set(REQUIRED_GATES)
        and all(
            isinstance(record, Mapping) and record.get("status") == "PASS"
            for record in gates.values()
        )
    )
    passed = (
        package.get("status") == "passed"
        and package.get("preliminary_manifest_sha256") == anchor
        and package.get("classification") == DIAGNOSTIC_CLASSIFICATION
        and package.get("official_s4_8_evidence") is False
        and package.get("official_s4_8_pass_claimed") is False
        and package_authentic
        and all_gates_pass
        and not unresolved
    )
    payload = {
        "schema": "ias.s4_8.preliminary_readiness.v1",
        "status": "passed" if passed else "failed",
        "preliminary_manifest_sha256": anchor,
        "package_sha256": package.get("package_sha256"),
        "preliminary_take_count": 4,
        "official_holdout_take_count": 47,
        "unresolved_corrections": unresolved,
        "all_required_gates_passed": all_gates_pass,
        "diagnostic_package_authenticated": package_authentic,
        "final_protocol_freeze_permitted": passed,
        "final_protocol_frozen": False,
        "official_acquisition_permitted": False,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "holdout_opening_authorized": False,
        "official_evaluation_authorized": False,
        "classification": dict(DIAGNOSTIC_CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    return {**payload, "readiness_sha256": canonical_sha256(payload)}


def _stage_av_inputs(
    attempt: Path,
    *,
    staging_attempt: Path,
    source_take_id: str,
    expected_hashes: Mapping[str, Any],
) -> None:
    frames = attempt / "zed/frames.jsonl"
    svo2 = attempt / "zed/capture.svo2"
    if expected_hashes.get("frames_sha256") != _sha256_file(
        frames
    ) or expected_hashes.get("svo2_sha256") != _sha256_file(svo2):
        raise S48PreliminaryError("impact/ZED raw hashes contradict the gate report")
    sources = {
        frames: staging_attempt / "raw/zed_frames.jsonl",
        attempt / "pi_producer_status.json": (
            staging_attempt / "raw/pi_producer_status.json"
        ),
    }
    for source, destination in sources.items():
        if not source.is_file():
            raise S48PreliminaryError(f"impact/ZED processing input missing: {source}")
        shutil.copyfile(source, destination)
    _write_json(
        staging_attempt / "operator_event_confirmation.json",
        {
            "schema": "ias.s4_4.amendment_av_operator_event_confirmation.v1",
            "planned_take_id": source_take_id,
            "attempt_id": staging_attempt.name,
            "protocol_compliance_pass": True,
            "required_impact_count": 3,
            "retained_media_deleted_or_overwritten": False,
            "scientific_outcome_used_for_replacement": False,
            "technical_qa_passed": True,
            "technical_quality_failure_reason": None,
            "diagnostic_adapter": True,
        },
    )


def _failure_class(gate: str) -> str:
    return {
        "acquisition": "acquisition",
        "technical_validation": "acquisition",
        "detector_processing": "detector",
        "synchronization": "synchronization",
        "metric_calculation": "metric",
        "diagnostic_evaluator": "evaluator",
        "diagnostic_packaging": "packaging",
    }[gate]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S48PreliminaryError(f"JSON read failure for {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S48PreliminaryError(f"JSON object required: {path}")
    return value


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in lines]
    except (OSError, json.JSONDecodeError) as exc:
        raise S48PreliminaryError(f"JSONL read failure for {path}: {exc}") from exc
    if not values or not all(isinstance(value, dict) for value in values):
        raise S48PreliminaryError(f"non-empty JSON object lines required: {path}")
    return values


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact_record(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def _sha256_jsonl_prefix(path: Path, *, line_count: int) -> str:
    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError as exc:
        raise S48PreliminaryError(f"JSONL prefix read failure: {path}: {exc}") from exc
    if line_count < 1 or len(lines) < line_count:
        raise S48PreliminaryError(f"JSONL prefix is incomplete: {path}")
    return hashlib.sha256(b"".join(lines[:line_count])).hexdigest()


def _validate_artifact_record(
    artifact: Mapping[str, Any],
    *,
    resolved_path: Path | None = None,
) -> None:
    path = Path(str(artifact.get("path", "")))
    authenticated_path = path.resolve() if resolved_path is None else resolved_path
    if (
        not path.is_absolute()
        or not _is_sha256(artifact.get("sha256"))
        or _sha256_file(authenticated_path) != artifact.get("sha256")
    ):
        raise S48PreliminaryError(
            f"reprocessing artifact hash mismatch: {artifact.get('path')}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise S48PreliminaryError(f"file hash failure: {path}: {exc}") from exc
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_relative(value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise S48PreliminaryError(f"unsafe repository path: {value!r}")
    return path


__all__ = [
    "AUTHORITY_NONE",
    "CASE_IDS",
    "CONFIG_PATH",
    "DIAGNOSTIC_CLASSIFICATION",
    "REPROCESSING_SCHEMA_PATH",
    "REQUIRED_GATES",
    "S48PreliminaryError",
    "build_diagnostic_package",
    "build_diagnostic_payload",
    "build_readiness_report",
    "build_reprocessing_record",
    "build_reuse_decision",
    "load_reprocessing_record",
    "load_workflow_config",
    "process_case",
    "reprocess_attempt_gate",
    "resolve_reprocessing_record_paths",
    "run_diagnostic_evaluator",
    "validate_reprocessing_record",
    "validate_reuse_decision",
]
