"""Official one-take acquisition contracts for S4.8 recovery amendment 02.

The technical recorder, playback, ZED, gate, clearance, and candidate-seal
implementations remain the existing S4.8 engineering components.  This module
adds the official precollection partition, immutable session anchor, one-shot
operator authorization, and append-only attempt ledger around those components.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableSequence, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256

SESSION_SCHEMA = "ias.s4_8.recovery_02_official_session_manifest.v1"
PARTITION_SCHEMA = "ias.s4_8.recovery_02_unseen_partition_manifest.v1"
PRECOLLECTION_SEAL_SCHEMA = "ias.s4_8.recovery_02_precollection_seal.v1"
AUTHORIZATION_SCHEMA = "ias.s4_8.recovery_02_take_authorization.v1"
ATTEMPT_SCHEMA = "ias.s4_8.recovery_02_attempt_record.v1"

FROZEN_RETRY_POLICY = {
    "maximum_attempts_per_planned_take": None,
    "replacement_requires_retained_retry_required": True,
    "sequence_advances_only_after_pass": True,
    "configuration_change_restarts_campaign": True,
    "automatic_retry": False,
    "automatic_continuation": False,
    "all_attempts_retained": True,
}


class S48OfficialAcquisitionError(RuntimeError):
    """Official freeze, authorization, ledger, or provenance failure."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _hashed(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = deepcopy(dict(payload))
    return {**value, field: canonical_sha256(value)}


def _take_mode(take: Mapping[str, Any]) -> str:
    if take["stratum_id"] in {
        "A_controlled_boundary_sweep",
        "B_center_nominal_level",
        "C_center_low_level",
    }:
        return "reference"
    if take["stratum_id"] == "D_silence":
        return "silence"
    if take["stratum_id"] == "E_impact_audio_video":
        return "impact_av"
    raise S48OfficialAcquisitionError("unsupported frozen take stratum")


def _cartesian_position(take: Mapping[str, Any]) -> list[float] | None:
    bearing = take["bearing_deg"]
    radius = take["radius_m"]
    if bearing is None:
        return None
    radians = math.radians(float(bearing))
    return [
        round(float(radius) * math.cos(radians), 9),
        round(float(radius) * math.sin(radians), 9),
        -0.135,
    ]


def build_official_design(
    design_manifest: Mapping[str, Any],
    *,
    physical_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Adapt the exact frozen identities to the existing technical controller."""

    takes = design_manifest.get("take_order")
    if (
        design_manifest.get("planned_take_count") != 37
        or not isinstance(takes, list)
        or len(takes) != 37
    ):
        raise S48OfficialAcquisitionError("official design must contain 37 takes")
    result: list[dict[str, Any]] = []
    for sequence, source in enumerate(takes, start=1):
        if source.get("sequence_index") != sequence:
            raise S48OfficialAcquisitionError(
                "official take identities were reordered"
            )
        mode = _take_mode(source)
        condition = str(source["condition_id"])
        position = _cartesian_position(source)
        setup = {
            "condition_id": condition,
            "mac": {
                "power_state": physical_contract["mac"]["power_state"],
                "battery_operation_allowed": physical_contract["mac"][
                    "battery_operation_allowed"
                ],
                "output_device": physical_contract["mac"]["output_device"],
                "output_sample_rate_hz": physical_contract["mac"][
                    "output_sample_rate_hz"
                ],
                "output_channel_count": physical_contract["mac"][
                    "output_channel_count"
                ],
                "system_volume_percent": physical_contract["mac"][
                    "system_volume_percent"
                ],
                "muted": physical_contract["mac"]["muted"],
                "playback": "off" if mode != "reference" else "reference_signal",
                "position_m_f_project": position,
                "lid_angle_deg": (
                    None
                    if position is None
                    else physical_contract["mac"]["lid_angle_deg"]
                ),
                "heading": (
                    "not_applicable"
                    if position is None
                    else physical_contract["mac"]["heading"]
                ),
                "placement_tolerance_m": physical_contract["mac"][
                    "placement_tolerance_m"
                ],
                "bearing_reference_tolerance_deg": physical_contract["mac"][
                    "bearing_reference_tolerance_deg"
                ],
            },
            "rig": deepcopy(dict(physical_contract["rig"])),
            "other_physical_conditions": [],
        }
        if condition == "silence":
            setup["other_physical_conditions"] = [
                "remove_or_silence_all_deliberate_sources",
                "no_source_placement",
                "quiet_room",
            ]
        elif condition.endswith("_occluded"):
            setup["other_physical_conditions"] = [
                physical_contract["occlusion"]["instruction"]
            ]
        elif condition.endswith("_noise"):
            setup["other_physical_conditions"] = [
                physical_contract["noise"]["instruction"],
                physical_contract["noise"]["phrase"],
            ]
        elif condition == "impact":
            impact = physical_contract["impacts"][source["leakage_group_id"]]
            setup["other_physical_conditions"] = [
                impact["instruction"],
                physical_contract["impacts"]["privacy_instruction"],
            ]
        payload = {
            "engineering_take_id": source["planned_take_id"],
            "planned_take_id": source["planned_take_id"],
            "planned_take_definition_sha256": canonical_sha256(source),
            "sequence_index": sequence,
            "group_id": source["leakage_group_id"],
            "category": source["condition_id"],
            "stratum_id": source["stratum_id"],
            "acquisition_mode": mode,
            "duration_s": 15 if mode == "silence" else 20,
            "playback_gain": source["playback_gain"],
            "zed_required": mode == "impact_av",
            "target_position_m_f_project": position,
            "target_bearing_deg_f_project": source["bearing_deg"],
            "target_radius_m": source["radius_m"],
            "impact_target_elapsed_times_s": (
                [5.0, 10.0, 15.0] if mode == "impact_av" else None
            ),
            "complete_removal_and_fresh_reposition_required": (
                mode == "reference" and source["repetition"] > 1
            ),
            "physical_setup": setup,
        }
        result.append(
            {
                **payload,
                "engineering_take_definition_sha256": canonical_sha256(payload),
            }
        )
    return result


def build_partition_manifest(
    *,
    holdout_id: str,
    observation_root: str,
    consumed_observation_roots: Sequence[str],
    design_manifest_sha256: str,
    design: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the unopened partition anchor without touching observations."""

    payload = {
        "schema": PARTITION_SCHEMA,
        "status": "frozen_unseen_precollection",
        "holdout_id": holdout_id,
        "observation_root": observation_root,
        "consumed_observation_roots": list(consumed_observation_roots),
        "roots_disjoint": all(
            observation_root != root
            and not observation_root.startswith(f"{root}/")
            and not root.startswith(f"{observation_root}/")
            for root in consumed_observation_roots
        ),
        "design_manifest_sha256": design_manifest_sha256,
        "planned_take_ids": [take["planned_take_id"] for take in design],
        "planned_take_definition_sha256": {
            str(take["planned_take_id"]): str(
                take["planned_take_definition_sha256"]
            )
            for take in design
        },
        "planned_take_count": len(design),
        "observations_present_at_freeze": False,
        "holdout_opened": False,
    }
    if not payload["roots_disjoint"] or payload["planned_take_count"] != 37:
        raise S48OfficialAcquisitionError("unseen partition is not disjoint")
    return _hashed(payload, "partition_manifest_sha256")


def build_session_manifest(
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
    operational_locations: Mapping[str, str],
    design_manifest_sha256: str,
    partition_manifest_sha256: str,
    preflight_report_sha256: str,
) -> dict[str, Any]:
    """Build the final official session anchor used by existing gate code."""

    payload = {
        "schema": SESSION_SCHEMA,
        "status": "frozen_before_collection",
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
        "design": deepcopy([dict(take) for take in design]),
        "retry_policy": dict(FROZEN_RETRY_POLICY),
        "operational_locations": dict(operational_locations),
        "template_manifest_sha256": design_manifest_sha256,
        "partition_manifest_sha256": partition_manifest_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "authority": {
            "final_protocol_frozen": True,
            "official_acquisition_permitted": True,
            "per_take_authorization_required": True,
            "automatic_retry": False,
            "automatic_continuation": False,
            "creates_evaluation_grant": False,
            "opens_holdout_for_evaluation": False,
        },
    }
    validate_session_manifest(
        _hashed(payload, "manifest_sha256"),
        expected_manifest_sha256=canonical_sha256(payload),
    )
    return _hashed(payload, "manifest_sha256")


def validate_session_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
) -> None:
    """Validate the immutable official controller-facing session anchor."""

    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    design = manifest.get("design")
    expected_ids = (
        [take.get("planned_take_id") for take in design]
        if isinstance(design, list)
        else []
    )
    if (
        manifest.get("schema") != SESSION_SCHEMA
        or manifest.get("status") != "frozen_before_collection"
        or set(manifest) != {
            "schema",
            "status",
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
            "partition_manifest_sha256",
            "preflight_report_sha256",
            "authority",
            "manifest_sha256",
        }
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("manifest_sha256") != expected_manifest_sha256
        or manifest.get("planned_take_count") != 37
        or len(expected_ids) != 37
        or len(set(expected_ids)) != 37
        or [take.get("sequence_index") for take in design] != list(range(1, 38))
        or any(
            take.get("engineering_take_id") != take.get("planned_take_id")
            or take.get("engineering_take_definition_sha256")
            != canonical_sha256(
                {
                    key: value
                    for key, value in take.items()
                    if key != "engineering_take_definition_sha256"
                }
            )
            for take in design
        )
        or manifest.get("retry_policy") != FROZEN_RETRY_POLICY
        or not _is_sha256(manifest.get("partition_manifest_sha256"))
        or not _is_sha256(manifest.get("preflight_report_sha256"))
        or manifest.get("authority", {}).get("official_acquisition_permitted")
        is not True
    ):
        raise S48OfficialAcquisitionError(
            "official session manifest binding is invalid"
        )


def build_precollection_seal(
    *,
    source_commit: str,
    source_checkpoint: Mapping[str, Any],
    amendment_sha256: str,
    design_manifest_sha256: str,
    partition_manifest_sha256: str,
    session_manifest_sha256: str,
    preflight_report_sha256: str,
) -> dict[str, Any]:
    payload = {
        "schema": PRECOLLECTION_SEAL_SCHEMA,
        "status": "frozen_before_collection",
        "source_commit": source_commit,
        "source_checkpoint": deepcopy(dict(source_checkpoint)),
        "amendment_sha256": amendment_sha256,
        "design_manifest_sha256": design_manifest_sha256,
        "partition_manifest_sha256": partition_manifest_sha256,
        "session_manifest_sha256": session_manifest_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "planned_take_count": 37,
        "attempt_ledger_empty": True,
        "observation_root_empty": True,
        "postcollection_holdout_seal_present": False,
        "unseen_holdout_binding_present": False,
        "official_acquisition_permitted": True,
        "evaluation_authorized": False,
    }
    return _hashed(payload, "seal_sha256")


def ledger_head(
    ledger: Sequence[Mapping[str, Any]],
    *,
    session_manifest_sha256: str,
) -> str:
    return (
        session_manifest_sha256
        if not ledger
        else str(ledger[-1].get("record_sha256"))
    )


def validate_attempt_ledger(
    ledger: Sequence[Mapping[str, Any]],
    *,
    session_manifest: Mapping[str, Any],
    expected_session_manifest_sha256: str,
) -> None:
    """Validate every retained PASS/RETRY_REQUIRED record in append order."""

    validate_session_manifest(
        session_manifest,
        expected_manifest_sha256=expected_session_manifest_sha256,
    )
    design = session_manifest["design"]
    expected_index = 0
    expected_attempt = 1
    previous = expected_session_manifest_sha256
    for sequence, record in enumerate(ledger):
        if expected_index >= len(design):
            raise S48OfficialAcquisitionError("official ledger exceeds design")
        take = design[expected_index]
        payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if (
            record.get("schema") != ATTEMPT_SCHEMA
            or record.get("sequence") != sequence
            or record.get("session_manifest_sha256")
            != expected_session_manifest_sha256
            or record.get("previous_record_sha256") != previous
            or record.get("planned_take_id") != take["planned_take_id"]
            or record.get("planned_take_definition_sha256")
            != take["planned_take_definition_sha256"]
            or record.get("attempt_number") != expected_attempt
            or record.get("decision") not in {"PASS", "RETRY_REQUIRED"}
            or not _is_sha256(record.get("official_attempt_record_sha256"))
            or not _is_sha256(record.get("authorization_sha256"))
            or record.get("record_sha256") != canonical_sha256(payload)
        ):
            raise S48OfficialAcquisitionError(
                "official attempt ledger is invalid"
            )
        if record["decision"] == "PASS":
            expected_index += 1
            expected_attempt = 1
        else:
            expected_attempt += 1
        previous = str(record["record_sha256"])


def next_attempt(
    ledger: Sequence[Mapping[str, Any]],
    *,
    session_manifest: Mapping[str, Any],
    expected_session_manifest_sha256: str,
) -> tuple[dict[str, Any], int]:
    validate_attempt_ledger(
        ledger,
        session_manifest=session_manifest,
        expected_session_manifest_sha256=expected_session_manifest_sha256,
    )
    passed = sum(record["decision"] == "PASS" for record in ledger)
    if passed >= len(session_manifest["design"]):
        raise S48OfficialAcquisitionError("official collection is complete")
    attempt = (
        int(ledger[-1]["attempt_number"]) + 1
        if ledger and ledger[-1]["decision"] == "RETRY_REQUIRED"
        else 1
    )
    return dict(session_manifest["design"][passed]), attempt


def build_take_authorization(
    *,
    session_manifest: Mapping[str, Any],
    precollection_seal_sha256: str,
    ledger: Sequence[Mapping[str, Any]],
    planned_take_id: str,
    attempt_number: int,
    source_revision: str,
    authorization_id: str,
    user_confirmation: str,
) -> dict[str, Any]:
    """Create one authorization bound to the exact current ledger head."""

    anchor = str(session_manifest.get("manifest_sha256"))
    take, expected_attempt = next_attempt(
        ledger,
        session_manifest=session_manifest,
        expected_session_manifest_sha256=anchor,
    )
    if (
        take["planned_take_id"] != planned_take_id
        or expected_attempt != attempt_number
        or not authorization_id
        or user_confirmation != "go"
        or not _is_sha256(precollection_seal_sha256)
        or source_revision != session_manifest["code_head"]
    ):
        raise S48OfficialAcquisitionError(
            "authorization does not target the exact next official attempt"
        )
    payload = {
        "schema": AUTHORIZATION_SCHEMA,
        "authorization_id": authorization_id,
        "session_manifest_sha256": anchor,
        "precollection_seal_sha256": precollection_seal_sha256,
        "ledger_head_sha256": ledger_head(
            ledger, session_manifest_sha256=anchor
        ),
        "planned_take_id": planned_take_id,
        "planned_take_definition_sha256": take[
            "planned_take_definition_sha256"
        ],
        "attempt_number": attempt_number,
        "source_revision": source_revision,
        "user_confirmation": {
            "value": user_confirmation,
            "explicit": True,
            "creates_authority_for_exactly_one_attempt": True,
        },
        "one_take_only": True,
        "automatic_retry": False,
        "automatic_continuation": False,
        "scientific_outcomes_inspected": False,
    }
    return _hashed(payload, "authorization_sha256")


def validate_take_authorization(
    authorization: Mapping[str, Any],
    *,
    session_manifest: Mapping[str, Any],
    precollection_seal_sha256: str,
    ledger: Sequence[Mapping[str, Any]],
    take: Mapping[str, Any],
    attempt_number: int,
) -> None:
    payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_sha256"
    }
    anchor = str(session_manifest.get("manifest_sha256"))
    expected_take, expected_attempt = next_attempt(
        ledger,
        session_manifest=session_manifest,
        expected_session_manifest_sha256=anchor,
    )
    if (
        authorization.get("schema") != AUTHORIZATION_SCHEMA
        or authorization.get("authorization_sha256")
        != canonical_sha256(payload)
        or authorization.get("session_manifest_sha256") != anchor
        or authorization.get("precollection_seal_sha256")
        != precollection_seal_sha256
        or authorization.get("ledger_head_sha256")
        != ledger_head(ledger, session_manifest_sha256=anchor)
        or authorization.get("planned_take_id") != take.get("planned_take_id")
        or authorization.get("planned_take_definition_sha256")
        != take.get("planned_take_definition_sha256")
        or authorization.get("attempt_number") != attempt_number
        or dict(expected_take) != dict(take)
        or expected_attempt != attempt_number
        or authorization.get("source_revision") != session_manifest["code_head"]
        or authorization.get("user_confirmation", {}).get("value") != "go"
        or authorization.get("one_take_only") is not True
        or authorization.get("automatic_retry") is not False
        or authorization.get("automatic_continuation") is not False
    ):
        raise S48OfficialAcquisitionError(
            "authorization is stale, reused, or targets another attempt"
        )


def build_official_attempt_record(
    *,
    session_manifest_sha256: str,
    partition_manifest_sha256: str,
    precollection_seal_sha256: str,
    source_commit: str,
    take: Mapping[str, Any],
    attempt_number: int,
    authorization: Mapping[str, Any],
    decision: str,
    technical_report_sha256: str,
    technical_candidate_seal_sha256: str | None,
    recorder_started: bool | None,
    playback_started: bool | None,
    zed_recording_started: bool | None,
    controller_failure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Wrap the existing technical disposition in retained official provenance."""

    if (
        decision not in {"PASS", "RETRY_REQUIRED"}
        or not _is_sha256(technical_report_sha256)
        or (decision == "PASS") != _is_sha256(technical_candidate_seal_sha256)
        or any(
            value is not True and value is not False and value is not None
            for value in (
                recorder_started,
                playback_started,
                zed_recording_started,
            )
        )
    ):
        raise S48OfficialAcquisitionError("official attempt result is invalid")
    payload = {
        "schema": "ias.s4_8.recovery_02_official_attempt.v1",
        "session_manifest_sha256": session_manifest_sha256,
        "partition_manifest_sha256": partition_manifest_sha256,
        "precollection_seal_sha256": precollection_seal_sha256,
        "source_commit": source_commit,
        "planned_take_id": take["planned_take_id"],
        "planned_take_definition_sha256": take[
            "planned_take_definition_sha256"
        ],
        "attempt_number": attempt_number,
        "authorization_id": authorization["authorization_id"],
        "authorization_sha256": authorization["authorization_sha256"],
        "decision": decision,
        "technical_report_sha256": technical_report_sha256,
        "technical_candidate_seal_sha256": technical_candidate_seal_sha256,
        "start_state": {
            "recorder_started": recorder_started,
            "playback_started": playback_started,
            "zed_recording_started": zed_recording_started,
        },
        "controller_failure": (
            None if controller_failure is None else dict(controller_failure)
        ),
        "retained": True,
        "counts_as_official_attempt": True,
        "automatic_retry": False,
        "automatic_continuation": False,
    }
    return _hashed(payload, "official_attempt_record_sha256")


def append_attempt_record(
    ledger: MutableSequence[dict[str, Any]],
    *,
    session_manifest: Mapping[str, Any],
    official_attempt: Mapping[str, Any],
) -> dict[str, Any]:
    anchor = str(session_manifest["manifest_sha256"])
    take, attempt = next_attempt(
        ledger,
        session_manifest=session_manifest,
        expected_session_manifest_sha256=anchor,
    )
    if (
        official_attempt.get("planned_take_id") != take["planned_take_id"]
        or official_attempt.get("attempt_number") != attempt
    ):
        raise S48OfficialAcquisitionError("attempt result is not the next action")
    payload = {
        "schema": ATTEMPT_SCHEMA,
        "sequence": len(ledger),
        "session_manifest_sha256": anchor,
        "previous_record_sha256": ledger_head(
            ledger, session_manifest_sha256=anchor
        ),
        "planned_take_id": take["planned_take_id"],
        "planned_take_definition_sha256": take[
            "planned_take_definition_sha256"
        ],
        "attempt_number": attempt,
        "decision": official_attempt["decision"],
        "official_attempt_record_sha256": official_attempt[
            "official_attempt_record_sha256"
        ],
        "authorization_sha256": official_attempt["authorization_sha256"],
    }
    record = _hashed(payload, "record_sha256")
    ledger.append(record)
    validate_attempt_ledger(
        ledger,
        session_manifest=session_manifest,
        expected_session_manifest_sha256=anchor,
    )
    return record


def validate_empty_observation_root(repo_root: Path, observation_root: str) -> None:
    root = (repo_root.resolve() / observation_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise S48OfficialAcquisitionError(
            "official observation root is not empty before collection"
        )


__all__ = [
    "ATTEMPT_SCHEMA",
    "AUTHORIZATION_SCHEMA",
    "FROZEN_RETRY_POLICY",
    "PARTITION_SCHEMA",
    "PRECOLLECTION_SEAL_SCHEMA",
    "SESSION_SCHEMA",
    "S48OfficialAcquisitionError",
    "append_attempt_record",
    "build_official_attempt_record",
    "build_official_design",
    "build_partition_manifest",
    "build_precollection_seal",
    "build_session_manifest",
    "build_take_authorization",
    "ledger_head",
    "next_attempt",
    "validate_attempt_ledger",
    "validate_empty_observation_root",
    "validate_session_manifest",
    "validate_take_authorization",
]
