"""Stratum-aware, engineering-only S4.8 physical rehearsal contracts.

This module does not create or consume a grant, open a holdout, run an
official state machine, or publish official evidence.  It binds the existing
47-cell scientific design to mode-appropriate acquisition gates:

* A/B/C use the unchanged v2 reference-playback controller and gate.
* D uses capture/device/channel integrity without reference playback.
* E uses capture/device/channel integrity plus frozen transient and ZED checks.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from collections.abc import Mapping, MutableSequence, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_3 import (
    S43Error,
    _prospective_transient_events,
    load_pilot_configuration,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    build_engineering_precollection_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    S48PresealingGateError,
    evaluate_capture_integrity_v2,
    load_presealing_config_v2,
    read_pcm16_wav_strict,
)

CAMPAIGN_MANIFEST_SCHEMA = "ias.s4_8.engineering_campaign_manifest.v1"
PRELIMINARY_MANIFEST_SCHEMA = "ias.s4_8.preliminary_manifest.v1"
ATTEMPT_LEDGER_SCHEMA = "ias.s4_8.engineering_attempt_ledger_record.v1"
NONREFERENCE_REPORT_SCHEMA = "ias.s4_8.nonreference_presealing_report.v1"
NONREFERENCE_JOURNAL_SCHEMA = (
    "ias.s4_8.nonreference_engineering_process_journal_event.v1"
)
NONREFERENCE_CLEARANCE_SCHEMA = (
    "ias.s4_8.nonreference_engineering_candidate_clearance.v1"
)
NONREFERENCE_SEAL_SCHEMA = "ias.s4_8.nonreference_engineering_candidate_seal.v1"
AUTHORITY_NONE = {
    "creates_grant": False,
    "consumes_grant": False,
    "official_state_machine": False,
    "publishes_official_evidence": False,
}
_MANIFEST_FIELDS = {
    "schema",
    "code_head",
    "source_archive_sha256",
    "source_package_hashes",
    "environment",
    "reference_wav_sha256",
    "gate_configuration_sha256",
    "detector_configuration_sha256",
    "controller",
    "protocol",
    "devices",
    "channel_map",
    "planned_take_count",
    "design",
    "retry_policy",
    "operational_locations",
    "template_manifest_sha256",
    "authority",
}
_PRELIMINARY_MANIFEST_FIELDS = _MANIFEST_FIELDS | {
    "classification",
    "workflow",
}
_RETRY_POLICY = {
    "maximum_attempts_per_planned_take": 2,
    "replacement_requires_retained_retry_required": True,
    "sequence_advances_only_after_pass": True,
    "configuration_change_restarts_campaign": True,
}
_EXPECTED_CHANNEL_MAP = [
    "Conference",
    "ASR",
    "raw microphone 0",
    "raw microphone 1",
    "raw microphone 2",
    "raw microphone 3",
]


class S48EngineeringCampaignError(RuntimeError):
    """Stratum-aware engineering campaign contract failure."""


def derive_stratum_aware_design(
    template_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Derive engineering identities while preserving the 47-cell order."""

    takes = template_manifest.get("takes")
    if (
        template_manifest.get("planned_take_count") != 47
        or not isinstance(takes, list)
        or len(takes) != 47
    ):
        raise S48EngineeringCampaignError(
            "campaign template must contain the frozen 47-take design"
        )
    design: list[dict[str, Any]] = []
    for expected_sequence, source in enumerate(takes, start=1):
        if (
            not isinstance(source, Mapping)
            or source.get("sequence_index") != expected_sequence
        ):
            raise S48EngineeringCampaignError(
                "campaign template sequence is incomplete or reordered"
            )
        category = source.get("category")
        gain = source.get("playback_gain")
        if category == "controlled" and gain == 0.75:
            stratum_id = "A_controlled_boundary_sweep"
            acquisition_mode = "reference"
        elif category == "confidence" and gain == 0.75:
            stratum_id = "B_center_nominal_level"
            acquisition_mode = "reference"
        elif category == "confidence" and gain == 0.35:
            stratum_id = "C_center_low_level"
            acquisition_mode = "reference"
        elif category == "silence" and gain is None:
            stratum_id = "D_silence"
            acquisition_mode = "silence"
        elif (
            category == "audio_video"
            and gain is None
            and source.get("zed_required") is True
        ):
            stratum_id = "E_impact_audio_video"
            acquisition_mode = "impact_av"
        else:
            raise S48EngineeringCampaignError(
                f"unsupported frozen take definition at sequence {expected_sequence}"
            )
        suffix = {
            "reference": "ref",
            "silence": "sil",
            "impact_av": "av",
        }[acquisition_mode]
        payload = {
            "engineering_take_id": (
                f"s48eng_rehearsal_{expected_sequence:03d}_{suffix}"
            ),
            "template_planned_take_id": source.get("planned_take_id"),
            "template_take_definition_sha256": source.get(
                "take_definition_sha256"
            ),
            "sequence_index": expected_sequence,
            "group_id": source.get("group_id"),
            "category": category,
            "stratum_id": stratum_id,
            "acquisition_mode": acquisition_mode,
            "duration_s": source.get("duration_s"),
            "playback_gain": gain,
            "zed_required": source.get("zed_required"),
            "target_position_m_f_project": source.get(
                "target_position_m_f_project"
            ),
            "target_bearing_deg_f_project": source.get(
                "target_bearing_deg_f_project"
            ),
            "target_radius_m": source.get("target_radius_m"),
            "impact_target_elapsed_times_s": source.get(
                "impact_target_elapsed_times_s"
            ),
            "complete_removal_and_fresh_reposition_required": source.get(
                "complete_removal_and_fresh_reposition_required"
            ),
        }
        if (
            not _is_sha256(payload["template_take_definition_sha256"])
            or not isinstance(payload["template_planned_take_id"], str)
            or not isinstance(payload["group_id"], str)
            or payload["duration_s"] not in {15, 20}
            or (acquisition_mode == "silence" and payload["duration_s"] != 15)
            or (acquisition_mode != "silence" and payload["duration_s"] != 20)
            or (acquisition_mode == "impact_av")
            != bool(payload["zed_required"])
            or (
                acquisition_mode == "impact_av"
                and payload["impact_target_elapsed_times_s"]
                != [5.0, 10.0, 15.0]
            )
        ):
            raise S48EngineeringCampaignError(
                f"invalid frozen take definition at sequence {expected_sequence}"
            )
        design.append(
            {
                **payload,
                "engineering_take_definition_sha256": canonical_sha256(payload),
            }
        )
    counts = {
        stratum: sum(item["stratum_id"] == stratum for item in design)
        for stratum in (
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
            "C_center_low_level",
            "D_silence",
            "E_impact_audio_video",
        )
    }
    if counts != {
        "A_controlled_boundary_sweep": 24,
        "B_center_nominal_level": 8,
        "C_center_low_level": 8,
        "D_silence": 3,
        "E_impact_audio_video": 4,
    }:
        raise S48EngineeringCampaignError("frozen stratum counts are invalid")
    return design


def derive_preliminary_design(
    template_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Select the four representative, uncounted preliminary cases."""

    catalog = derive_stratum_aware_design(template_manifest)
    cases = (
        (
            "nominal_reference",
            "B_center_nominal_level",
            "s48prelim_001_nominal_reference",
        ),
        (
            "low_level_reference",
            "C_center_low_level",
            "s48prelim_002_low_level_reference",
        ),
        ("silence", "D_silence", "s48prelim_003_silence"),
        (
            "audio_video_impact_with_zed",
            "E_impact_audio_video",
            "s48prelim_004_audio_video_impact_with_zed",
        ),
    )
    design: list[dict[str, Any]] = []
    for sequence_index, (case_id, stratum_id, take_id) in enumerate(
        cases, start=1
    ):
        source = next(
            item for item in catalog if item["stratum_id"] == stratum_id
        )
        payload = {
            **{
                key: value
                for key, value in source.items()
                if key != "engineering_take_definition_sha256"
            },
            "engineering_take_id": take_id,
            "sequence_index": sequence_index,
            "preliminary_case_id": case_id,
            "source_engineering_take_id": source["engineering_take_id"],
            "source_engineering_take_definition_sha256": source[
                "engineering_take_definition_sha256"
            ],
        }
        design.append(
            {
                **payload,
                "engineering_take_definition_sha256": canonical_sha256(payload),
            }
        )
    return design


def build_stratum_aware_campaign_manifest(
    *,
    code_head: str,
    source_archive_sha256: str,
    source_package_hashes: Mapping[str, str],
    environment: Mapping[str, Any],
    reference_wav_sha256: str,
    gate_configuration_sha256: str,
    detector_configuration_sha256: str,
    controller: Mapping[str, Any],
    protocol: Mapping[str, Any],
    devices: Mapping[str, Any],
    channel_map: Sequence[str],
    design: Sequence[Mapping[str, Any]],
    retry_policy: Mapping[str, Any],
    operational_locations: Mapping[str, str],
    template_manifest_sha256: str,
) -> dict[str, Any]:
    """Build the single external precollection anchor for the rehearsal."""

    payload = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "code_head": code_head,
        "source_archive_sha256": source_archive_sha256,
        "source_package_hashes": dict(source_package_hashes),
        "environment": deepcopy(dict(environment)),
        "reference_wav_sha256": reference_wav_sha256,
        "gate_configuration_sha256": gate_configuration_sha256,
        "detector_configuration_sha256": detector_configuration_sha256,
        "controller": dict(controller),
        "protocol": dict(protocol),
        "devices": deepcopy(dict(devices)),
        "channel_map": list(channel_map),
        "planned_take_count": len(design),
        "design": deepcopy([dict(item) for item in design]),
        "retry_policy": dict(retry_policy),
        "operational_locations": dict(operational_locations),
        "template_manifest_sha256": template_manifest_sha256,
        "authority": dict(AUTHORITY_NONE),
    }
    _validate_campaign_payload(payload)
    return {**payload, "manifest_sha256": canonical_sha256(payload)}


def build_preliminary_manifest(
    *,
    code_head: str,
    source_archive_sha256: str,
    source_package_hashes: Mapping[str, str],
    environment: Mapping[str, Any],
    reference_wav_sha256: str,
    gate_configuration_sha256: str,
    detector_configuration_sha256: str,
    controller: Mapping[str, Any],
    protocol: Mapping[str, Any],
    devices: Mapping[str, Any],
    channel_map: Sequence[str],
    design: Sequence[Mapping[str, Any]],
    retry_policy: Mapping[str, Any],
    operational_locations: Mapping[str, str],
    template_manifest_sha256: str,
) -> dict[str, Any]:
    """Build the four-case preliminary anchor with no official authority."""

    payload = {
        "schema": PRELIMINARY_MANIFEST_SCHEMA,
        "code_head": code_head,
        "source_archive_sha256": source_archive_sha256,
        "source_package_hashes": dict(source_package_hashes),
        "environment": deepcopy(dict(environment)),
        "reference_wav_sha256": reference_wav_sha256,
        "gate_configuration_sha256": gate_configuration_sha256,
        "detector_configuration_sha256": detector_configuration_sha256,
        "controller": dict(controller),
        "protocol": dict(protocol),
        "devices": deepcopy(dict(devices)),
        "channel_map": list(channel_map),
        "planned_take_count": len(design),
        "design": deepcopy([dict(item) for item in design]),
        "retry_policy": dict(retry_policy),
        "operational_locations": dict(operational_locations),
        "template_manifest_sha256": template_manifest_sha256,
        "classification": {
            "engineering_only": True,
            "uncounted": True,
            "excluded_from_official_holdout": True,
            "safe_to_inspect_and_analyze": True,
            "diagnostic_results_only": True,
            "official_evidence_eligible": False,
        },
        "workflow": {
            "case_count": 4,
            "case_order": [
                "nominal_reference",
                "low_level_reference",
                "silence",
                "audio_video_impact_with_zed",
            ],
            "complete_stack_required": True,
            "official_protocol_freeze_permitted": False,
            "official_acquisition_permitted": False,
        },
        "authority": dict(AUTHORITY_NONE),
    }
    _validate_preliminary_payload(payload)
    return {**payload, "manifest_sha256": canonical_sha256(payload)}


def build_reference_take_manifest(
    *,
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
) -> dict[str, Any]:
    """Derive the unchanged v2 A/B/C manifest from the campaign anchor."""

    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    matches = [
        item
        for item in campaign_manifest["design"]
        if item["engineering_take_id"] == take.get("engineering_take_id")
    ]
    if (
        len(matches) != 1
        or dict(matches[0]) != dict(take)
        or take.get("acquisition_mode") != "reference"
    ):
        raise S48EngineeringCampaignError(
            "reference manifest requires the exact A/B/C campaign cell"
        )
    environment_sha256 = canonical_sha256(campaign_manifest["environment"])
    return build_engineering_precollection_manifest(
        code_head=str(campaign_manifest["code_head"]),
        environment_identity=(
            f"campaign:{expected_campaign_manifest_sha256}:"
            f"environment:{environment_sha256}:"
            f"take:{take['engineering_take_definition_sha256']}"
        ),
        reference_wav_sha256=str(
            campaign_manifest["reference_wav_sha256"]
        ),
        gate_configuration_sha256=str(
            campaign_manifest["gate_configuration_sha256"]
        ),
        detector_configuration_sha256=str(
            campaign_manifest["detector_configuration_sha256"]
        ),
        device_profile_id=str(
            campaign_manifest["devices"]["respeaker"]["profile_id"]
        ),
        channel_map=campaign_manifest["channel_map"],
        protocol_id=(
            f"{campaign_manifest['protocol']['identity']}:"
            f"{expected_campaign_manifest_sha256}:"
            f"{take['engineering_take_definition_sha256']}"
        ),
        capture_controller_identity=str(
            campaign_manifest["controller"]["identity"]
        ),
        capture_controller_version=str(
            campaign_manifest["controller"]["version"]
        ),
    )


def validate_campaign_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
) -> None:
    """Validate the exact campaign anchor and all embedded take hashes."""

    if not _is_sha256(expected_manifest_sha256):
        raise S48EngineeringCampaignError("campaign manifest anchor is invalid")
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    _validate_campaign_payload(payload)
    if (
        set(manifest) != _MANIFEST_FIELDS | {"manifest_sha256"}
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise S48EngineeringCampaignError(
            "campaign manifest does not match the external anchor"
        )


def validate_preliminary_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
) -> None:
    """Validate the exact four-case preliminary anchor."""

    if not _is_sha256(expected_manifest_sha256):
        raise S48EngineeringCampaignError("preliminary manifest anchor is invalid")
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    _validate_preliminary_payload(payload)
    if (
        set(manifest) != _PRELIMINARY_MANIFEST_FIELDS | {"manifest_sha256"}
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise S48EngineeringCampaignError(
            "preliminary manifest does not match the external anchor"
        )


def validate_engineering_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
) -> None:
    """Validate a historical 47-take or active four-take engineering anchor."""

    if manifest.get("schema") == PRELIMINARY_MANIFEST_SCHEMA:
        validate_preliminary_manifest(
            manifest,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        return
    validate_campaign_manifest(
        manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def append_attempt_ledger_record(
    ledger: MutableSequence[dict[str, Any]],
    *,
    campaign_manifest_sha256: str,
    planned_take: Mapping[str, Any],
    attempt_number: int,
    decision: str,
    report_sha256: str,
    candidate_seal_sha256: str | None,
) -> dict[str, Any]:
    """Append one PASS or RETRY_REQUIRED record without hiding attempts."""

    if (
        not _is_sha256(campaign_manifest_sha256)
        or not isinstance(attempt_number, int)
        or isinstance(attempt_number, bool)
        or attempt_number < 1
        or decision not in {"PASS", "RETRY_REQUIRED"}
        or not _is_sha256(report_sha256)
        or (decision == "PASS" and not _is_sha256(candidate_seal_sha256))
        or (decision == "RETRY_REQUIRED" and candidate_seal_sha256 is not None)
        or not _is_sha256(planned_take.get("engineering_take_definition_sha256"))
    ):
        raise S48EngineeringCampaignError("attempt ledger record is invalid")
    previous = (
        campaign_manifest_sha256
        if not ledger
        else str(ledger[-1].get("record_sha256"))
    )
    payload = {
        "schema": ATTEMPT_LEDGER_SCHEMA,
        "sequence": len(ledger),
        "campaign_manifest_sha256": campaign_manifest_sha256,
        "previous_record_sha256": previous,
        "engineering_take_id": planned_take.get("engineering_take_id"),
        "engineering_take_definition_sha256": planned_take.get(
            "engineering_take_definition_sha256"
        ),
        "planned_sequence_index": planned_take.get("sequence_index"),
        "attempt_number": attempt_number,
        "decision": decision,
        "report_sha256": report_sha256,
        "candidate_seal_sha256": candidate_seal_sha256,
    }
    record = {**payload, "record_sha256": canonical_sha256(payload)}
    ledger.append(record)
    return record


def validate_attempt_ledger(
    ledger: Sequence[Mapping[str, Any]],
    *,
    campaign_manifest: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
) -> None:
    """Validate chain, retry retention, and sequence advancement."""

    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    design = campaign_manifest["design"]
    by_id = {item["engineering_take_id"]: item for item in design}
    previous = expected_campaign_manifest_sha256
    expected_design_index = 0
    prior_for_take: Mapping[str, Any] | None = None
    for sequence, record in enumerate(ledger):
        payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        take = by_id.get(record.get("engineering_take_id"))
        fields = {
            "schema",
            "sequence",
            "campaign_manifest_sha256",
            "previous_record_sha256",
            "engineering_take_id",
            "engineering_take_definition_sha256",
            "planned_sequence_index",
            "attempt_number",
            "decision",
            "report_sha256",
            "candidate_seal_sha256",
            "record_sha256",
        }
        attempt_number = record.get("attempt_number")
        if (
            set(record) != fields
            or record.get("schema") != ATTEMPT_LEDGER_SCHEMA
            or not isinstance(attempt_number, int)
            or isinstance(attempt_number, bool)
            or attempt_number < 1
            or record.get("sequence") != sequence
            or record.get("campaign_manifest_sha256")
            != expected_campaign_manifest_sha256
            or record.get("previous_record_sha256") != previous
            or record.get("record_sha256") != canonical_sha256(payload)
            or take is None
            or record.get("engineering_take_definition_sha256")
            != take["engineering_take_definition_sha256"]
            or record.get("planned_sequence_index") != take["sequence_index"]
            or expected_design_index >= len(design)
            or take["engineering_take_id"]
            != design[expected_design_index]["engineering_take_id"]
            or record.get("decision") not in {"PASS", "RETRY_REQUIRED"}
            or not _is_sha256(record.get("report_sha256"))
            or (
                record.get("decision") == "PASS"
                and not _is_sha256(record.get("candidate_seal_sha256"))
            )
            or (
                record.get("decision") == "RETRY_REQUIRED"
                and record.get("candidate_seal_sha256") is not None
            )
        ):
            raise S48EngineeringCampaignError(
                "attempt ledger chain, binding, or disposition is invalid"
            )
        assert isinstance(attempt_number, int)
        if attempt_number == 1:
            if prior_for_take is not None:
                raise S48EngineeringCampaignError(
                    "attempt 1 cannot replace an existing take attempt"
                )
        elif (
            prior_for_take is None
            or prior_for_take.get("attempt_number") != attempt_number - 1
            or prior_for_take.get("decision") != "RETRY_REQUIRED"
            or prior_for_take.get("engineering_take_id")
            != record.get("engineering_take_id")
        ):
            raise S48EngineeringCampaignError(
                "retry requires the retained immediately prior attempt"
            )
        if record["decision"] == "PASS":
            expected_design_index += 1
            prior_for_take = None
        else:
            prior_for_take = record
        previous = str(record["record_sha256"])


def validate_attempt_request(
    ledger: Sequence[Mapping[str, Any]],
    *,
    campaign_manifest: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    take: Mapping[str, Any],
    attempt_number: int,
) -> None:
    """Authorize the exact next attempt before any producer is started."""

    validate_attempt_ledger(
        ledger,
        campaign_manifest=campaign_manifest,
        expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
    )
    expected_take, expected_attempt = _next_attempt(ledger, campaign_manifest)
    if (
        dict(take) != dict(expected_take)
        or attempt_number != expected_attempt
    ):
        raise S48EngineeringCampaignError(
            "requested take/attempt is not the next frozen ledger action"
        )


def _next_attempt(
    ledger: Sequence[Mapping[str, Any]],
    campaign_manifest: Mapping[str, Any],
) -> tuple[Mapping[str, Any], int]:
    design = campaign_manifest["design"]
    passed_count = sum(record.get("decision") == "PASS" for record in ledger)
    if passed_count >= len(design):
        raise S48EngineeringCampaignError("engineering campaign is already complete")
    expected_take = design[passed_count]
    if ledger and ledger[-1].get("decision") == "RETRY_REQUIRED":
        prior_attempt = ledger[-1].get("attempt_number")
        if (
            not isinstance(prior_attempt, int)
            or isinstance(prior_attempt, bool)
            or prior_attempt < 1
        ):
            raise S48EngineeringCampaignError(
                "retained retry attempt number is invalid"
            )
        expected_attempt = prior_attempt + 1
    else:
        expected_attempt = 1
    return expected_take, expected_attempt


def evaluate_nonreference_presealing_gate(
    *,
    capture_path: Path,
    take: Mapping[str, Any],
    campaign_manifest: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    process_journal_head_sha256: str,
    repo_root: Path,
    zed_artifacts: Mapping[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Evaluate D/E technical integrity without scientific outcome fields."""

    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    matching = [
        item
        for item in campaign_manifest["design"]
        if item["engineering_take_id"] == take.get("engineering_take_id")
    ]
    if len(matching) != 1 or dict(matching[0]) != dict(take):
        raise S48EngineeringCampaignError(
            "take is not the exact campaign-manifest definition"
        )
    mode = take.get("acquisition_mode")
    if mode not in {"silence", "impact_av"}:
        raise S48EngineeringCampaignError(
            "non-reference gate is restricted to D/E takes"
        )
    if not _is_sha256(process_journal_head_sha256):
        raise S48EngineeringCampaignError("process-journal head hash is invalid")
    root = repo_root.resolve()
    config = load_presealing_config_v2(root)
    if (
        campaign_manifest["gate_configuration_sha256"]
        != canonical_sha256(config)
        or campaign_manifest["detector_configuration_sha256"]
        != canonical_sha256(config["detector"])
    ):
        raise S48EngineeringCampaignError(
            "campaign manifest v2 configuration hashes are stale"
        )
    try:
        capture, sample_rate_hz = read_pcm16_wav_strict(capture_path)
        integrity = evaluate_capture_integrity_v2(
            capture,
            sample_rate_hz=sample_rate_hz,
            device_profile_id=campaign_manifest["devices"]["respeaker"][
                "profile_id"
            ],
            channel_map=campaign_manifest["channel_map"],
            config=config,
        )
    except (S48EngineeringAcquisitionError, S48PresealingGateError) as exc:
        raise S48EngineeringCampaignError(str(exc)) from exc
    reasons = [dict(item) for item in integrity["reasons"]]
    expected_frames = round(float(take["duration_s"]) * sample_rate_hz)
    if capture.shape[0] != expected_frames:
        reasons.append(
            _reason(
                "capture_duration_mismatch",
                "integrity",
                "capture frame count does not match the frozen take duration",
                expected_frames=expected_frames,
                actual_frames=int(capture.shape[0]),
            )
        )
    impact_integrity: dict[str, Any] | None = None
    zed_integrity: dict[str, Any] | None = None
    zed_hashes: dict[str, str] | None = None
    if mode == "silence" and zed_artifacts is not None:
        reasons.append(
            _reason(
                "unexpected_zed_artifacts",
                "provenance",
                "silence take must not be rebound to ZED artifacts",
            )
        )
    if mode == "impact_av":
        impact_integrity = _evaluate_impact_integrity(
            capture,
            sample_rate_hz=sample_rate_hz,
            repo_root=root,
        )
        reasons.extend(impact_integrity["reasons"])
        zed_integrity = _evaluate_zed_integrity(
            zed_artifacts,
            expected_serial=str(campaign_manifest["devices"]["zed"]["serial"]),
        )
        reasons.extend(zed_integrity["reasons"])
        if isinstance(zed_artifacts, Mapping):
            zed_hashes = {
                key: str(zed_artifacts.get(key))
                for key in ("svo2_sha256", "frames_sha256")
                if _is_sha256(zed_artifacts.get(key))
            }
    capture_sha256 = _sha256_file(capture_path)
    return {
        "schema": NONREFERENCE_REPORT_SCHEMA,
        "decision": "PASS" if not reasons else "RETRY_REQUIRED",
        "mode": mode,
        "dry_run": bool(dry_run),
        "reasons": reasons,
        "capture_integrity": integrity,
        "impact_integrity": impact_integrity,
        "zed_integrity": zed_integrity,
        "input_provenance": {
            "capture_sha256": capture_sha256,
            "reference_sha256": None,
            "campaign_manifest_sha256": expected_campaign_manifest_sha256,
            "engineering_take_definition_sha256": take[
                "engineering_take_definition_sha256"
            ],
            "process_journal_head_sha256": process_journal_head_sha256,
            "configuration_sha256": campaign_manifest[
                "gate_configuration_sha256"
            ],
            "detector_configuration_sha256": campaign_manifest[
                "detector_configuration_sha256"
            ],
            "zed_artifact_hashes": zed_hashes,
            "outcome_fields_read": [],
        },
        "authority": dict(AUTHORITY_NONE),
    }


def append_nonreference_journal_event(
    journal: MutableSequence[dict[str, Any]],
    *,
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    event_type: str,
    observed_monotonic_ns: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one mode-specific event to the exact campaign/take chain."""

    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    order = _nonreference_event_order(take)
    if (
        len(journal) >= len(order)
        or event_type != order[len(journal)]
        or isinstance(observed_monotonic_ns, bool)
        or not isinstance(observed_monotonic_ns, int)
        or observed_monotonic_ns < 0
    ):
        raise S48EngineeringCampaignError(
            "non-reference event is missing, duplicated, or out of order"
        )
    payload = {
        "schema": NONREFERENCE_JOURNAL_SCHEMA,
        "sequence": len(journal),
        "campaign_manifest_sha256": expected_campaign_manifest_sha256,
        "engineering_take_definition_sha256": take[
            "engineering_take_definition_sha256"
        ],
        "previous_event_sha256": (
            expected_campaign_manifest_sha256
            if not journal
            else journal[-1]["event_sha256"]
        ),
        "event_type": event_type,
        "observed_monotonic_ns": observed_monotonic_ns,
        "data": dict(data),
    }
    event = {**payload, "event_sha256": canonical_sha256(payload)}
    journal.append(event)
    return event


def validate_nonreference_process_journal(
    *,
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    expected_campaign_manifest_sha256: str,
    required_terminal_event: str,
) -> None:
    """Validate the complete D/E mode sequence and every hash-chain link."""

    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    matches = [
        item
        for item in campaign_manifest["design"]
        if item["engineering_take_id"] == take.get("engineering_take_id")
    ]
    if len(matches) != 1 or dict(matches[0]) != dict(take):
        raise S48EngineeringCampaignError(
            "journal take is not the exact campaign definition"
        )
    order = _nonreference_event_order(take)
    if required_terminal_event not in order:
        raise S48EngineeringCampaignError(
            "unsupported non-reference terminal journal event"
        )
    expected_order = order[: order.index(required_terminal_event) + 1]
    if len(journal) != len(expected_order):
        raise S48EngineeringCampaignError(
            "non-reference process journal is incomplete"
        )
    previous = expected_campaign_manifest_sha256
    previous_time = -1
    fields = {
        "schema",
        "sequence",
        "campaign_manifest_sha256",
        "engineering_take_definition_sha256",
        "previous_event_sha256",
        "event_type",
        "observed_monotonic_ns",
        "data",
        "event_sha256",
    }
    for sequence, (event, expected_type) in enumerate(
        zip(journal, expected_order, strict=True)
    ):
        payload = {
            key: value for key, value in event.items() if key != "event_sha256"
        }
        observed_time = event.get("observed_monotonic_ns")
        if (
            set(event) != fields
            or event.get("schema") != NONREFERENCE_JOURNAL_SCHEMA
            or event.get("sequence") != sequence
            or event.get("campaign_manifest_sha256")
            != expected_campaign_manifest_sha256
            or event.get("engineering_take_definition_sha256")
            != take["engineering_take_definition_sha256"]
            or event.get("previous_event_sha256") != previous
            or event.get("event_type") != expected_type
            or isinstance(observed_time, bool)
            or not isinstance(observed_time, int)
            or observed_time < previous_time
            or not isinstance(event.get("data"), Mapping)
            or event.get("event_sha256") != canonical_sha256(payload)
        ):
            raise S48EngineeringCampaignError(
                "non-reference journal hash chain or event sequence is invalid"
            )
        previous = str(event["event_sha256"])
        previous_time = observed_time
    controller = journal[0]["data"]
    if (
        controller.get("identity")
        != campaign_manifest["controller"]["identity"]
        or controller.get("version")
        != campaign_manifest["controller"]["version"]
        or controller.get("mode") != take["acquisition_mode"]
    ):
        raise S48EngineeringCampaignError(
            "non-reference controller identity or mode mismatch"
        )
    if required_terminal_event in {
        "capture_authenticated",
        "gate_evaluated",
        "candidate_clearance_created",
    }:
        capture_event = next(
            event
            for event in journal
            if event.get("event_type") == "capture_authenticated"
        )
        capture = capture_event["data"]
        expected_zed = (
            capture.get("zed_artifact_hashes")
            if take["acquisition_mode"] == "impact_av"
            else None
        )
        if (
            not _is_sha256(capture.get("capture_sha256"))
            or capture.get("device_profile_id")
            != campaign_manifest["devices"]["respeaker"]["profile_id"]
            or capture.get("channel_map") != campaign_manifest["channel_map"]
            or capture.get("gate_configuration_sha256")
            != campaign_manifest["gate_configuration_sha256"]
            or capture.get("detector_configuration_sha256")
            != campaign_manifest["detector_configuration_sha256"]
            or (
                take["acquisition_mode"] == "silence"
                and capture.get("zed_artifact_hashes") is not None
            )
            or (
                take["acquisition_mode"] == "impact_av"
                and (
                    not isinstance(expected_zed, Mapping)
                    or set(expected_zed) != {"svo2_sha256", "frames_sha256"}
                    or not all(_is_sha256(value) for value in expected_zed.values())
                )
            )
        ):
            raise S48EngineeringCampaignError(
                "non-reference capture authentication contradicts campaign"
            )


def create_nonreference_candidate_clearance(
    report: Mapping[str, Any],
    *,
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    journal: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Clear one exact D/E PASS report for an engineering-only seal."""

    validate_nonreference_process_journal(
        campaign_manifest=campaign_manifest,
        take=take,
        journal=journal,
        expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
        required_terminal_event="gate_evaluated",
    )
    capture_event = next(
        event
        for event in journal
        if event.get("event_type") == "capture_authenticated"
    )
    gate_event = journal[-1]
    _validate_nonreference_report(
        report,
        campaign_manifest=campaign_manifest,
        take=take,
        expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
        process_journal_head_sha256=str(capture_event["event_sha256"]),
    )
    if (
        report["decision"] != "PASS"
        or report["reasons"] != []
        or gate_event["data"].get("decision") != report["decision"]
        or gate_event["data"].get("report_sha256") != canonical_sha256(report)
    ):
        raise S48EngineeringCampaignError(
            "a RETRY_REQUIRED report cannot create candidate clearance"
        )
    provenance = report["input_provenance"]
    payload = {
        "schema": NONREFERENCE_CLEARANCE_SCHEMA,
        "status": "cleared_for_engineering_candidate_seal",
        "campaign_manifest_sha256": expected_campaign_manifest_sha256,
        "engineering_take_definition_sha256": take[
            "engineering_take_definition_sha256"
        ],
        "process_journal_head_sha256": gate_event["event_sha256"],
        "report_sha256": canonical_sha256(report),
        "capture_sha256": provenance["capture_sha256"],
        "zed_artifact_hashes": provenance["zed_artifact_hashes"],
        "configuration_sha256": provenance["configuration_sha256"],
        "detector_configuration_sha256": provenance[
            "detector_configuration_sha256"
        ],
        "scientific_outcome_fields_used": [],
        "authority": dict(AUTHORITY_NONE),
    }
    return {**payload, "clearance_sha256": canonical_sha256(payload)}


def seal_nonreference_candidate(
    *,
    capture_path: Path,
    report: Mapping[str, Any],
    clearance: Mapping[str, Any],
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    candidate_seal_path: Path,
    clearance_registry_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Seal one exact D/E candidate; the clearance is single use."""

    anchor = str(campaign_manifest.get("manifest_sha256"))
    validate_nonreference_process_journal(
        campaign_manifest=campaign_manifest,
        take=take,
        journal=journal,
        expected_campaign_manifest_sha256=anchor,
        required_terminal_event="candidate_clearance_created",
    )
    capture_event = next(
        event
        for event in journal
        if event.get("event_type") == "capture_authenticated"
    )
    gate_event = journal[-2]
    clearance_event = journal[-1]
    _validate_nonreference_report(
        report,
        campaign_manifest=campaign_manifest,
        take=take,
        expected_campaign_manifest_sha256=anchor,
        process_journal_head_sha256=str(capture_event["event_sha256"]),
    )
    clearance_payload = {
        key: value for key, value in clearance.items() if key != "clearance_sha256"
    }
    clearance_sha256 = canonical_sha256(clearance_payload)
    if (
        clearance.get("schema") != NONREFERENCE_CLEARANCE_SCHEMA
        or clearance.get("status") != "cleared_for_engineering_candidate_seal"
        or clearance.get("clearance_sha256") != clearance_sha256
        or clearance.get("campaign_manifest_sha256")
        != campaign_manifest["manifest_sha256"]
        or clearance.get("engineering_take_definition_sha256")
        != take["engineering_take_definition_sha256"]
        or clearance.get("process_journal_head_sha256")
        != gate_event["event_sha256"]
        or clearance_event["data"].get("clearance_sha256")
        != clearance_sha256
        or clearance.get("report_sha256") != canonical_sha256(report)
        or clearance.get("capture_sha256")
        != report["input_provenance"]["capture_sha256"]
        or clearance.get("zed_artifact_hashes")
        != report["input_provenance"]["zed_artifact_hashes"]
        or clearance.get("scientific_outcome_fields_used") != []
        or clearance.get("authority") != AUTHORITY_NONE
        or report.get("decision") != "PASS"
        or report.get("reasons") != []
    ):
        raise S48EngineeringCampaignError(
            "candidate clearance is stale, altered, or mismatched"
        )
    capture_sha256 = _sha256_file(capture_path)
    if capture_sha256 != clearance["capture_sha256"]:
        raise S48EngineeringCampaignError(
            "candidate clearance cannot seal a different capture"
        )
    if clearance_registry_path.exists():
        raise S48EngineeringCampaignError("candidate clearance was already reused")
    payload = {
        "schema": NONREFERENCE_SEAL_SCHEMA,
        "status": "engineering_candidate_sealed",
        "engineering_only": True,
        "dry_run": bool(dry_run),
        "mode": take["acquisition_mode"],
        "capture_sha256": capture_sha256,
        "zed_artifact_hashes": clearance["zed_artifact_hashes"],
        "campaign_manifest_sha256": campaign_manifest["manifest_sha256"],
        "engineering_take_definition_sha256": take[
            "engineering_take_definition_sha256"
        ],
        "process_journal_sha256": clearance_event["event_sha256"],
        "report_sha256": canonical_sha256(report),
        "clearance_sha256": clearance_sha256,
        "authority": dict(AUTHORITY_NONE),
    }
    seal = {**payload, "seal_sha256": canonical_sha256(payload)}
    if not dry_run:
        _write_new_json(
            clearance_registry_path,
            {
                "schema": (
                    "ias.s4_8.nonreference_engineering_clearance_consumption.v1"
                ),
                "clearance_sha256": clearance_sha256,
                "candidate_seal_sha256": seal["seal_sha256"],
            },
        )
        _write_new_json(candidate_seal_path, seal)
    return seal


def run_supported_nonreference_acquisition(
    *,
    backend: Any,
    repo_root: Path,
    take: Mapping[str, Any],
    campaign_manifest: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    capture_path: Path,
    zed_artifact_root: Path | None,
    journal_path: Path,
    retry_report_path: Path,
    candidate_seal_path: Path,
    clearance_registry_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the sole supported D/E recorder-to-candidate-seal path."""

    root = repo_root.resolve()
    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=expected_campaign_manifest_sha256,
    )
    matches = [
        item
        for item in campaign_manifest["design"]
        if item["engineering_take_id"] == take.get("engineering_take_id")
    ]
    if len(matches) != 1 or dict(matches[0]) != dict(take):
        raise S48EngineeringCampaignError(
            "take is not the exact campaign-manifest definition"
        )
    mode = take.get("acquisition_mode")
    if mode not in {"silence", "impact_av"}:
        raise S48EngineeringCampaignError(
            "non-reference controller is restricted to D/E takes"
        )
    if (mode == "impact_av") != (zed_artifact_root is not None):
        raise S48EngineeringCampaignError(
            "ZED artifact root must be supplied exactly for impact/AV takes"
        )
    for path in (
        capture_path,
        journal_path,
        retry_report_path,
        candidate_seal_path,
        clearance_registry_path,
        *(() if zed_artifact_root is None else (zed_artifact_root,)),
    ):
        if path.resolve().is_relative_to(root):
            raise S48EngineeringCampaignError(
                "engineering operational files must remain outside the repository"
            )
    if journal_path.exists():
        raise S48EngineeringCampaignError(
            "refusing to reuse an existing engineering process journal"
        )
    journal: list[dict[str, Any]] = []

    def observe(event_type: str, data: Mapping[str, Any]) -> dict[str, Any]:
        event = append_nonreference_journal_event(
            journal,
            campaign_manifest=campaign_manifest,
            take=take,
            expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
            event_type=event_type,
            observed_monotonic_ns=int(backend.monotonic_ns()),
            data=data,
        )
        _append_json_line(journal_path, event)
        return event

    observe(
        "capture_controller_started",
        {
            "identity": campaign_manifest["controller"]["identity"],
            "version": campaign_manifest["controller"]["version"],
            "pid": os.getpid(),
            "mode": mode,
        },
    )
    duration_s = float(take["duration_s"])
    recorder = backend.start_recorder(capture_path, duration_s=duration_s)
    recorder_started = observe("recorder_started", recorder)
    ready = backend.wait_recorder_ready(recorder)
    observe("recorder_ready", {"pid": recorder.get("pid"), "ready": bool(ready)})
    if ready is not True:
        raise S48EngineeringCampaignError("recorder did not become ready")
    capture_start_ns = int(recorder_started["observed_monotonic_ns"])
    zed: object | None = None
    if mode == "silence":
        observe("silence_interval_started", backend.begin_silence_interval())
        backend.wait_until(
            capture_start_ns + round(duration_s * 1_000_000_000)
        )
        observe("silence_interval_completed", backend.complete_silence_interval())
    else:
        assert zed_artifact_root is not None
        zed = backend.start_zed(zed_artifact_root, duration_s=duration_s)
        observe("zed_started", zed)
        zed_ready = backend.wait_zed_ready(zed)
        observe("zed_ready", {"pid": zed.get("pid"), "ready": bool(zed_ready)})
        if zed_ready is not True:
            raise S48EngineeringCampaignError("ZED recorder did not become ready")
        for cue_index, elapsed_s in enumerate(
            take["impact_target_elapsed_times_s"],
            start=1,
        ):
            backend.wait_until(
                capture_start_ns + round(float(elapsed_s) * 1_000_000_000)
            )
            observe(
                f"impact_cue_{cue_index}",
                backend.record_impact_cue(cue_index),
            )
        backend.wait_until(
            capture_start_ns + round(duration_s * 1_000_000_000)
        )
    zed_artifacts: Mapping[str, Any] | None = None
    if zed is not None:
        zed_status = backend.stop_zed(zed)
        artifacts = zed_status.pop("artifacts", None)
        observe("zed_terminated", zed_status)
        if isinstance(artifacts, Mapping):
            zed_artifacts = artifacts
    recorder_status = backend.stop_recorder(recorder)
    observe("recorder_terminated", recorder_status)
    if not capture_path.is_file():
        raise S48EngineeringCampaignError("recorder produced no capture WAV")
    capture_event = observe(
        "capture_authenticated",
        {
            "capture_sha256": _sha256_file(capture_path),
            "device_profile_id": campaign_manifest["devices"]["respeaker"][
                "profile_id"
            ],
            "channel_map": campaign_manifest["channel_map"],
            "gate_configuration_sha256": campaign_manifest[
                "gate_configuration_sha256"
            ],
            "detector_configuration_sha256": campaign_manifest[
                "detector_configuration_sha256"
            ],
            "zed_artifact_hashes": (
                None
                if zed_artifacts is None
                else {
                    key: zed_artifacts.get(key)
                    for key in ("svo2_sha256", "frames_sha256")
                }
            ),
        },
    )
    report = evaluate_nonreference_presealing_gate(
        capture_path=capture_path,
        take=take,
        campaign_manifest=campaign_manifest,
        expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
        process_journal_head_sha256=capture_event["event_sha256"],
        repo_root=root,
        zed_artifacts=zed_artifacts,
        dry_run=dry_run,
    )
    gate_event = observe(
        "gate_evaluated",
        {
            "report_sha256": canonical_sha256(report),
            "decision": report["decision"],
        },
    )
    if report["decision"] != "PASS":
        _write_new_json(retry_report_path, report)
        return {
            "decision": "RETRY_REQUIRED",
            "report": report,
            "clearance": None,
            "candidate_seal": None,
            "journal_head_sha256": gate_event["event_sha256"],
        }
    clearance = create_nonreference_candidate_clearance(
        report,
        campaign_manifest=campaign_manifest,
        take=take,
        expected_campaign_manifest_sha256=expected_campaign_manifest_sha256,
        journal=journal,
    )
    clearance_event = observe(
        "candidate_clearance_created",
        {"clearance_sha256": clearance["clearance_sha256"]},
    )
    candidate_seal = seal_nonreference_candidate(
        capture_path=capture_path,
        report=report,
        clearance=clearance,
        campaign_manifest=campaign_manifest,
        take=take,
        journal=journal,
        candidate_seal_path=candidate_seal_path,
        clearance_registry_path=clearance_registry_path,
        dry_run=dry_run,
    )
    return {
        "decision": "PASS",
        "report": report,
        "clearance": clearance,
        "candidate_seal": candidate_seal,
        "journal_head_sha256": clearance_event["event_sha256"],
    }


def _validate_nonreference_report(
    report: Mapping[str, Any],
    *,
    campaign_manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    expected_campaign_manifest_sha256: str,
    process_journal_head_sha256: str,
) -> None:
    provenance = report.get("input_provenance")
    if (
        report.get("schema") != NONREFERENCE_REPORT_SCHEMA
        or report.get("decision") not in {"PASS", "RETRY_REQUIRED"}
        or report.get("mode") != take.get("acquisition_mode")
        or not isinstance(report.get("reasons"), list)
        or not isinstance(provenance, Mapping)
        or provenance.get("capture_sha256") is None
        or not _is_sha256(provenance.get("capture_sha256"))
        or provenance.get("reference_sha256") is not None
        or provenance.get("campaign_manifest_sha256")
        != expected_campaign_manifest_sha256
        or provenance.get("engineering_take_definition_sha256")
        != take.get("engineering_take_definition_sha256")
        or provenance.get("process_journal_head_sha256")
        != process_journal_head_sha256
        or provenance.get("configuration_sha256")
        != campaign_manifest.get("gate_configuration_sha256")
        or provenance.get("detector_configuration_sha256")
        != campaign_manifest.get("detector_configuration_sha256")
        or provenance.get("outcome_fields_read") != []
        or report.get("authority") != AUTHORITY_NONE
    ):
        raise S48EngineeringCampaignError(
            "non-reference gate report is invalid or mismatched"
        )


def _evaluate_impact_integrity(
    capture: np.ndarray,
    *,
    sample_rate_hz: int,
    repo_root: Path,
) -> dict[str, Any]:
    heldout_config_path = repo_root / "configs/s4_8_heldout_evaluation.v1.json"
    try:
        import json

        heldout = json.loads(heldout_config_path.read_text(encoding="utf-8"))
        analysis = heldout["analysis"]
        transient_path = repo_root / analysis["transient_contract_path"]
        if _sha256_file(transient_path) != analysis["transient_contract_sha256"]:
            raise S48EngineeringCampaignError(
                "frozen transient contract hash mismatch"
            )
        detector_config = load_pilot_configuration(
            repo_root / analysis["s4_3_effective_config_path"],
            repo_root=repo_root,
        )
        transient = _prospective_transient_events(
            capture[:, 2:6],
            detector_config,
            contract_sha256=analysis["transient_contract_sha256"],
        )
    except (OSError, KeyError, ValueError, S43Error) as exc:
        raise S48EngineeringCampaignError(
            f"frozen impact detector could not be evaluated: {exc}"
        ) from exc
    candidates = [
        int(record["peak_sample"]) for record in transient.get("events", [])
    ]
    selected: tuple[int, int, int] | None = None
    if len(candidates) >= 3:
        expected_interval_s = float(analysis["av_expected_interval_s"])
        selected = min(
            itertools.combinations(sorted(candidates), 3),
            key=lambda values: (
                abs((values[1] - values[0]) / sample_rate_hz - expected_interval_s)
                + abs(
                    (values[2] - values[1]) / sample_rate_hz
                    - expected_interval_s
                ),
                values,
            ),
        )
    reasons = []
    if selected is None:
        reasons.append(
            _reason(
                "fewer_than_three_frozen_audio_transients",
                "impact_integrity",
                "frozen detector found fewer than three impact candidates",
                candidate_count=len(candidates),
            )
        )
    return {
        "detector_contract_sha256": analysis["transient_contract_sha256"],
        "candidate_event_count": len(candidates),
        "selected_event_count": 0 if selected is None else 3,
        "selected_peak_samples": [] if selected is None else list(selected),
        "transient_report": transient,
        "reasons": reasons,
    }


def _evaluate_zed_integrity(
    zed_artifacts: Mapping[str, Any] | None,
    *,
    expected_serial: str,
) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    if not isinstance(zed_artifacts, Mapping):
        return {
            "passed": False,
            "reasons": [
                _reason(
                    "zed_artifacts_missing",
                    "zed_integrity",
                    "impact/AV take requires authenticated ZED artifacts",
                )
            ],
        }
    producer = zed_artifacts.get("producer_summary")
    replay = zed_artifacts.get("replay_report")
    if not isinstance(producer, Mapping):
        reasons.append(
            _reason(
                "zed_producer_summary_missing",
                "zed_integrity",
                "ZED producer summary is missing",
            )
        )
    else:
        if producer.get("schema") == "ias.s4_2.zed_producer_summary.v1":
            startup = producer.get("startup_checks")
            requested = producer.get("requested_mode")
            producer_serial = (
                producer.get("identity", {}).get("serial")
                if isinstance(producer.get("identity"), Mapping)
                else None
            )
            producer_passed = (
                producer.get("status") == "complete"
                and producer_serial == expected_serial
                and isinstance(requested, Mapping)
                and requested.get("resolution") == "HD720"
                and requested.get("fps") == 30
                and requested.get("depth_mode") == "PERFORMANCE"
                and isinstance(startup, Mapping)
                and all(bool(value) for value in startup.values())
                and producer.get("grab_failures") == 0
                and producer.get("retrieval_failures") == []
                and producer.get("timestamp_failures") == []
                and isinstance(producer.get("frame_count"), int)
                and producer["frame_count"] > 0
                and isinstance(producer.get("svo_byte_size"), int)
                and producer["svo_byte_size"] > 0
            )
        else:
            producer_passed = (
                producer.get("status") == "complete"
                and producer.get("serial") == expected_serial
                and producer.get("resolution") == "HD720"
                and producer.get("fps") == 30
                and producer.get("depth_mode") == "PERFORMANCE"
                and producer.get("strictly_increasing_device_timestamps") is True
            )
        if not producer_passed:
            reasons.append(
                _reason(
                    "zed_producer_integrity_failed",
                    "zed_integrity",
                    "ZED producer identity, mode, timestamps, or outputs failed",
                )
            )
    if not isinstance(replay, Mapping):
        reasons.append(
            _reason(
                "zed_replay_report_missing",
                "zed_integrity",
                "full ZED SVO2 replay report is missing",
            )
        )
    else:
        if replay.get("schema") == "ias.s4_2.zed_svo_validation.v1":
            identity = replay.get("identity")
            replay_passed = (
                replay.get("status") == "passed"
                and isinstance(identity, Mapping)
                and identity.get("serial") == expected_serial
                and replay.get("end_of_svo_reached") is True
                and replay.get("declared_frame_count")
                == replay.get("replayed_frame_count")
                and isinstance(replay.get("declared_frame_count"), int)
                and replay["declared_frame_count"] > 0
            )
        else:
            replay_passed = (
                replay.get("status") == "passed"
                and replay.get("full_replay") is True
            )
        if not replay_passed:
            reasons.append(
                _reason(
                    "zed_full_replay_failed",
                    "zed_integrity",
                    "ZED SVO2 did not pass a complete replay",
                )
            )
    for key in ("svo2_sha256", "frames_sha256"):
        if not _is_sha256(zed_artifacts.get(key)):
            reasons.append(
                _reason(
                    f"{key}_missing",
                    "provenance",
                    f"authenticated {key} is required",
                )
            )
    return {"passed": not reasons, "reasons": reasons}


def _nonreference_event_order(take: Mapping[str, Any]) -> tuple[str, ...]:
    mode = take.get("acquisition_mode")
    if mode == "silence":
        return (
            "capture_controller_started",
            "recorder_started",
            "recorder_ready",
            "silence_interval_started",
            "silence_interval_completed",
            "recorder_terminated",
            "capture_authenticated",
            "gate_evaluated",
            "candidate_clearance_created",
        )
    if mode == "impact_av":
        return (
            "capture_controller_started",
            "recorder_started",
            "recorder_ready",
            "zed_started",
            "zed_ready",
            "impact_cue_1",
            "impact_cue_2",
            "impact_cue_3",
            "zed_terminated",
            "recorder_terminated",
            "capture_authenticated",
            "gate_evaluated",
            "candidate_clearance_created",
        )
    raise S48EngineeringCampaignError(
        "non-reference journal is restricted to D/E takes"
    )


def _validate_campaign_payload(payload: Mapping[str, Any]) -> None:
    design = payload.get("design")
    hashes = payload.get("source_package_hashes")
    retry = payload.get("retry_policy")
    controller = payload.get("controller")
    protocol = payload.get("protocol")
    locations = payload.get("operational_locations")
    if (
        set(payload) != _MANIFEST_FIELDS
        or payload.get("schema") != CAMPAIGN_MANIFEST_SCHEMA
        or not _is_git_head(payload.get("code_head"))
        or not all(
            _is_sha256(payload.get(key))
            for key in (
                "source_archive_sha256",
                "reference_wav_sha256",
                "gate_configuration_sha256",
                "detector_configuration_sha256",
                "template_manifest_sha256",
            )
        )
        or not isinstance(hashes, Mapping)
        or not hashes
        or not all(
            isinstance(path, str) and path and _is_sha256(digest)
            for path, digest in hashes.items()
        )
        or not isinstance(payload.get("environment"), Mapping)
        or not payload["environment"]
        or not isinstance(controller, Mapping)
        or set(controller) != {"identity", "version", "sha256"}
        or not all(
            isinstance(controller.get(key), str) and controller[key]
            for key in ("identity", "version")
        )
        or not _is_sha256(controller.get("sha256"))
        or not isinstance(protocol, Mapping)
        or set(protocol) != {"identity", "sha256"}
        or not isinstance(protocol.get("identity"), str)
        or not protocol["identity"]
        or not _is_sha256(protocol.get("sha256"))
        or not isinstance(payload.get("devices"), Mapping)
        or set(payload["devices"]) != {"respeaker", "playback", "zed"}
        or payload.get("channel_map") != _EXPECTED_CHANNEL_MAP
        or payload.get("planned_take_count") != 47
        or not isinstance(design, list)
        or len(design) != 47
        or retry != _RETRY_POLICY
        or not isinstance(locations, Mapping)
        or set(locations) != {"campaign_root", "pi_capture_root"}
        or not all(isinstance(value, str) and value for value in locations.values())
        or payload.get("authority") != AUTHORITY_NONE
    ):
        raise S48EngineeringCampaignError(
            "stratum-aware campaign manifest payload is invalid"
        )
    for index, take in enumerate(design, start=1):
        if (
            not isinstance(take, Mapping)
            or take.get("sequence_index") != index
            or not isinstance(take.get("engineering_take_id"), str)
            or not _is_sha256(take.get("engineering_take_definition_sha256"))
        ):
            raise S48EngineeringCampaignError(
                "campaign design entry is invalid or reordered"
            )
        take_payload = {
            key: value
            for key, value in take.items()
            if key != "engineering_take_definition_sha256"
        }
        if (
            take["engineering_take_definition_sha256"]
            != canonical_sha256(take_payload)
        ):
            raise S48EngineeringCampaignError(
                "campaign design entry hash is stale"
            )
    counts = {
        value: sum(take.get("stratum_id") == value for take in design)
        for value in (
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
            "C_center_low_level",
            "D_silence",
            "E_impact_audio_video",
        )
    }
    if counts != {
        "A_controlled_boundary_sweep": 24,
        "B_center_nominal_level": 8,
        "C_center_low_level": 8,
        "D_silence": 3,
        "E_impact_audio_video": 4,
    }:
        raise S48EngineeringCampaignError("campaign stratum counts are invalid")


def _validate_preliminary_payload(payload: Mapping[str, Any]) -> None:
    design = payload.get("design")
    common = {
        key: value
        for key, value in payload.items()
        if key not in {"classification", "workflow"}
    }
    classification = payload.get("classification")
    workflow = payload.get("workflow")
    if (
        set(payload) != _PRELIMINARY_MANIFEST_FIELDS
        or common.get("schema") != PRELIMINARY_MANIFEST_SCHEMA
        or not _is_git_head(common.get("code_head"))
        or not all(
            _is_sha256(common.get(key))
            for key in (
                "source_archive_sha256",
                "reference_wav_sha256",
                "gate_configuration_sha256",
                "detector_configuration_sha256",
                "template_manifest_sha256",
            )
        )
        or not isinstance(common.get("source_package_hashes"), Mapping)
        or not common["source_package_hashes"]
        or not all(
            isinstance(path, str) and path and _is_sha256(digest)
            for path, digest in common["source_package_hashes"].items()
        )
        or not isinstance(common.get("environment"), Mapping)
        or not common["environment"]
        or not isinstance(common.get("controller"), Mapping)
        or set(common["controller"]) != {"identity", "version", "sha256"}
        or not _is_sha256(common["controller"].get("sha256"))
        or not isinstance(common.get("protocol"), Mapping)
        or set(common["protocol"]) != {"identity", "sha256"}
        or not _is_sha256(common["protocol"].get("sha256"))
        or not isinstance(common.get("devices"), Mapping)
        or set(common["devices"]) != {"respeaker", "playback", "zed"}
        or common.get("channel_map") != _EXPECTED_CHANNEL_MAP
        or common.get("planned_take_count") != 4
        or not isinstance(design, list)
        or len(design) != 4
        or common.get("retry_policy") != _RETRY_POLICY
        or not isinstance(common.get("operational_locations"), Mapping)
        or set(common["operational_locations"])
        != {"campaign_root", "pi_capture_root"}
        or common.get("authority") != AUTHORITY_NONE
        or classification
        != {
            "engineering_only": True,
            "uncounted": True,
            "excluded_from_official_holdout": True,
            "safe_to_inspect_and_analyze": True,
            "diagnostic_results_only": True,
            "official_evidence_eligible": False,
        }
        or workflow
        != {
            "case_count": 4,
            "case_order": [
                "nominal_reference",
                "low_level_reference",
                "silence",
                "audio_video_impact_with_zed",
            ],
            "complete_stack_required": True,
            "official_protocol_freeze_permitted": False,
            "official_acquisition_permitted": False,
        }
    ):
        raise S48EngineeringCampaignError(
            "four-case preliminary manifest payload is invalid"
        )
    expected = [
        ("nominal_reference", "B_center_nominal_level", "reference"),
        ("low_level_reference", "C_center_low_level", "reference"),
        ("silence", "D_silence", "silence"),
        (
            "audio_video_impact_with_zed",
            "E_impact_audio_video",
            "impact_av",
        ),
    ]
    for index, (take, expected_case) in enumerate(
        zip(design, expected, strict=True), start=1
    ):
        case_id, stratum_id, acquisition_mode = expected_case
        take_payload = {
            key: value
            for key, value in take.items()
            if key != "engineering_take_definition_sha256"
        }
        if (
            not isinstance(take, Mapping)
            or take.get("sequence_index") != index
            or take.get("preliminary_case_id") != case_id
            or take.get("stratum_id") != stratum_id
            or take.get("acquisition_mode") != acquisition_mode
            or not str(take.get("engineering_take_id", "")).startswith(
                "s48prelim_"
            )
            or not _is_sha256(
                take.get("source_engineering_take_definition_sha256")
            )
            or take.get("engineering_take_definition_sha256")
            != canonical_sha256(take_payload)
        ):
            raise S48EngineeringCampaignError(
                "preliminary design is invalid, incomplete, or reordered"
            )


def _reason(
    code: str,
    category: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "message": message,
        "details": details,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise S48EngineeringCampaignError(f"file hash failure: {exc}") from exc
    return digest.hexdigest()


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise S48EngineeringCampaignError(
            f"refusing to overwrite engineering operational file: {path}"
        ) from exc


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise S48EngineeringCampaignError(
            f"engineering journal append failure: {exc}"
        ) from exc


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_git_head(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )
