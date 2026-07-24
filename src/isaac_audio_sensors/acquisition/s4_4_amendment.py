"""Prospective S4.4 data-expansion amendment contracts and access controls.

This module does not fit parameters or open the prospective holdout.  It builds
the preregistered acquisition order, validates machine-local acquisition
records, and enforces repository-tool access boundaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

CONFIG_SCHEMA = "ias.s4_4.data_expansion_amendment_config.v1"
MANIFEST_SCHEMA = "ias.s4_4.data_expansion_manifest.v1"
MANIFEST_SCHEMA_V2 = "ias.s4_4.data_expansion_manifest.v2"
PREFLIGHT_SCHEMA = "ias.s4_4.amendment_session_preflight.v1"
READINESS_SCHEMA = "ias.s4_4.amendment_session_readiness.v1"
ATTEMPT_SCHEMA = "ias.s4_4.amendment_attempt.v1"
CENSUS_SCHEMA = "ias.s4_4.amendment_attempt_census.v1"
QA_SCHEMA = "ias.s4_4.amendment_technical_qa.v1"
QA_SCHEMA_V2 = "ias.s4_4.amendment_technical_qa.v2"
PRECOLLECTION_SEAL_SCHEMA = "ias.s4_4.amendment_precollection_seal.v1"
PRECOLLECTION_SEAL_SCHEMA_V2 = "ias.s4_4.amendment_precollection_seal.v2"
HOLDOUT_SEAL_SCHEMA = "ias.s4_4.amendment_holdout_seal.v1"
AGGREGATE_SCHEMA = "ias.s4_4.aggregate_index.v1"
AGGREGATE_SCHEMA_V2 = "ias.s4_4.aggregate_index.v2"
LEDGER_EVENT_SCHEMA = "ias.s4_4.amendment_access_ledger_event.v1"
ZERO_SHA256 = "0" * 64
REQUIRED_READINESS_CHECKS = {
    "network_permission_confirmed",
    "mac_ssh_connectivity",
    "mac_full_preflight_json",
    "mac_dynamic_preflight_json",
    "mac_identity_volume_mute_power_and_reference",
    "pi_ssh_connectivity",
    "pi_nonrecording_preflight_json",
    "pi_identity_device_format_disk_and_output",
    "zed_nonrecording_preflight",
    "clocks",
    "privacy_and_environment",
    "output_and_access_paths",
}

EXPECTED_SESSION_COUNTS = {"fit_a": 51, "fit_b": 51, "prospective_holdout": 47}
EXPECTED_PARTITION_COUNTS = {"fit": 102, "prospective_holdout": 47}
EXPECTED_CATEGORY_COUNTS = {
    ("fit_a", "controlled"): 32,
    ("fit_a", "confidence"): 12,
    ("fit_a", "silence"): 3,
    ("fit_a", "audio_video"): 4,
    ("fit_b", "controlled"): 32,
    ("fit_b", "confidence"): 12,
    ("fit_b", "silence"): 3,
    ("fit_b", "audio_video"): 4,
    ("prospective_holdout", "controlled"): 24,
    ("prospective_holdout", "confidence"): 16,
    ("prospective_holdout", "silence"): 3,
    ("prospective_holdout", "audio_video"): 4,
}
LEGACY_TECHNICAL_QA_INPUT_FIELDS = {
    "planned_take_id",
    "attempt_id",
    "identity_pass",
    "assigned_metadata_pass",
    "duration_pass",
    "channel_order_pass",
    "channel_health_pass",
    "clipping_pass",
    "timestamps_pass",
    "reference_presence_pass",
    "integrity_pass",
    "privacy_pass",
    "full_svo2_replay_pass",
}
TECHNICAL_QA_FIELD_PROJECTION = {
    "assigned_metadata_pass": "assigned_metadata_declaration_carried_forward",
    "channel_order_pass": "six_channel_count_pass",
    "channel_health_pass": "no_detected_silent_channel_issue",
    "timestamps_pass": "producer_timestamps_present",
    "reference_presence_pass": "playback_record_present_or_not_required",
    "privacy_pass": "privacy_declaration_carried_forward",
}
TECHNICAL_QA_INPUT_FIELDS = {
    TECHNICAL_QA_FIELD_PROJECTION.get(field, field)
    for field in LEGACY_TECHNICAL_QA_INPUT_FIELDS
}
LEGACY_TECHNICAL_QA_OUTPUT_FIELDS = LEGACY_TECHNICAL_QA_INPUT_FIELDS | {
    "schema",
    "partition",
    "overall_technical_pass",
    "scientific_outputs_exposed",
    "suppressed_field_count",
}
TECHNICAL_QA_OUTPUT_FIELDS = TECHNICAL_QA_INPUT_FIELDS | {
    "schema",
    "source_schema",
    "partition",
    "overall_technical_pass",
    "scientific_outputs_exposed",
    "suppressed_field_count",
}
KNOWN_ACCESS_PURPOSES = {
    "S4.4_amendment_integrity_validation",
    "S4.4_amendment_technical_QA",
    "S4.5_fit",
    "S4.5_validation",
}


class S44AmendmentError(ValueError):
    """A located, fail-closed amendment contract error."""


def canonical_json(value: Any) -> str:
    """Serialize as canonical compact JSON."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    """Hash canonical JSON."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash one file in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S44AmendmentError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S44AmendmentError(f"{path}: expected one JSON object")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise S44AmendmentError(f"{label}: expected non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise S44AmendmentError(f"{label}: unsafe path {value!r}")
    return value


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise S44AmendmentError(f"{label}: expected lowercase SHA-256")
    return value


def load_amendment_configuration(path: Path, repo_root: Path) -> dict[str, Any]:
    """Load a full v1 config or the narrow version-2 overlay on its frozen base."""

    payload = load_json(path)
    inherited = payload.get("inherits_config")
    if inherited is None:
        return payload
    if not isinstance(inherited, Mapping) or set(inherited) != {"path", "sha256"}:
        raise S44AmendmentError("inherited config binding invalid")
    relative = _safe_relative(inherited["path"], "inherits_config.path")
    base_path = repo_root / relative
    expected = _require_sha256(inherited["sha256"], "inherits_config.sha256")
    if not base_path.is_file() or sha256_file(base_path) != expected:
        raise S44AmendmentError("inherited config changed or is absent")
    base = load_json(base_path)
    allowed = {
        "schema",
        "amendment_id",
        "version",
        "status",
        "inherits_config",
        "historical_no_go_amendment_01",
        "retention",
    }
    if set(payload) != allowed:
        raise S44AmendmentError("amendment_02 config overlay field set invalid")
    merged = json.loads(json.dumps(base))
    for key in ("schema", "amendment_id", "version", "status"):
        merged[key] = payload[key]
    merged["historical_no_go_amendment_01"] = payload["historical_no_go_amendment_01"]
    merged["retention"] = payload["retention"]
    return merged


def _require_commit(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise S44AmendmentError(f"{label}: expected lowercase 40-character commit")
    return value


def _self_hashed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {**payload, field: canonical_sha256(payload)}


def _validate_self_hash(value: Mapping[str, Any], field: str, label: str) -> None:
    supplied = _require_sha256(value.get(field), f"{label}.{field}")
    payload = {key: item for key, item in value.items() if key != field}
    if canonical_sha256(payload) != supplied:
        raise S44AmendmentError(f"{label}: self-hash mismatch")


def validate_historical_freeze(config: Mapping[str, Any], repo_root: Path) -> None:
    """Prove every original S4.4 tracked artifact remains byte-identical."""

    freeze = config.get("historical_freeze")
    if not isinstance(freeze, Mapping):
        raise S44AmendmentError("historical_freeze: expected object")
    if freeze.get("split_plan_payload_sha256") != (
        "1569c00cbaec57e5625e0876fd243e17a2a67b287b3edf9865e41bb7ce8c0ce3"
    ):
        raise S44AmendmentError("historical SplitPlan payload hash changed")
    records = freeze.get("records")
    if not isinstance(records, list) or len(records) != 17:
        raise S44AmendmentError("historical freeze: expected exactly 17 records")
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {"path", "sha256"}:
            raise S44AmendmentError(f"historical freeze records[{index}]: invalid")
        relative = _safe_relative(record["path"], f"historical records[{index}].path")
        if relative in seen or "/amendments/" in relative:
            raise S44AmendmentError(
                f"historical freeze record path invalid: {relative}"
            )
        seen.add(relative)
        expected = _require_sha256(record["sha256"], f"historical {relative}")
        path = repo_root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise S44AmendmentError(
                f"immutable historical S4.4 artifact changed or missing: {relative}"
            )
    split_plan = load_json(
        repo_root / "outputs/isaac_audio_sensors/S4/S4.4/split_plan.json"
    )
    if split_plan.get("plan_sha256") != freeze["split_plan_payload_sha256"]:
        raise S44AmendmentError("historical SplitPlan assignment changed")


def validate_configuration(config: Mapping[str, Any], repo_root: Path) -> None:
    """Validate fixed amendment scope, identities, retention, and original binding."""

    if config.get("schema") != CONFIG_SCHEMA:
        raise S44AmendmentError(f"config schema: expected {CONFIG_SCHEMA}")
    amendment_id = config.get("amendment_id")
    version = config.get("version")
    approved = {
        "s4_4_data_expansion_amendment_01": 1,
        "s4_4_data_expansion_amendment_02": 2,
    }
    if amendment_id not in approved or version != approved[amendment_id]:
        raise S44AmendmentError("amendment id/version is not approved")
    scope = config.get("scope", {})
    if (
        scope.get("phase") != "S4.4"
        or scope.get("planned_fit_takes") != 102
        or scope.get("planned_prospective_holdout_takes") != 47
        or scope.get("planned_total_takes") != 149
        or scope.get("later_phases_started") is not False
    ):
        raise S44AmendmentError("scope counts or S4.4 boundary changed")
    bounds = config.get("room_bounds_m")
    if bounds != {"x": [-1.2, 2.4], "y": [-5.0, 8.0], "z": [-0.47, 1.42]}:
        raise S44AmendmentError("room bounds changed")
    identities = config.get("identities", {})
    if identities.get("reference_wav", {}).get("sha256") != (
        "27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468"
    ):
        raise S44AmendmentError("S4.3 reference WAV identity changed")
    mac = identities.get("mac", {})
    if (
        mac.get("model") != "MacBookPro18,1"
        or mac.get("system_volume_percent") != 40
        or mac.get("lid_angle_deg") != 90
        or mac.get("keyboard_plane") != "level"
        or mac.get("complete_removal_and_fresh_reposition_before_every_repetition")
        is not True
    ):
        raise S44AmendmentError("Mac acquisition contract changed")
    retention = config.get("retention", {})
    if (
        retention.get("raw_gitignored") is not True
        or retention.get("private_machine_local_records_gitignored") is not True
        or retention.get("clean_checkout_requires_raw_media") is not False
    ):
        raise S44AmendmentError("retention boundary changed")
    expected_suffix = str(amendment_id)
    if any(
        not str(retention.get(field, "")).endswith(expected_suffix)
        for field in ("machine_local_root", "tracked_evidence_root")
    ) or any(
        f"/{expected_suffix}/" not in str(retention.get(field, "")) + "/"
        for field in ("attempt_root", "session_root", "access_root")
    ):
        raise S44AmendmentError("amendment retention identities are not isolated")
    if version == 2:
        historical = config.get("historical_no_go_amendment_01")
        if not isinstance(historical, Mapping) or historical != {
            "amendment_id": "s4_4_data_expansion_amendment_01",
            "status": "no_go",
            "closure_record_path": (
                "outputs/isaac_audio_sensors/S4/S4.4/closures/"
                "s4_4_data_expansion_amendment_01_no_go.v1.json"
            ),
            "closure_seal_path": (
                "outputs/isaac_audio_sensors/S4/S4.4/closures/"
                "s4_4_data_expansion_amendment_01_no_go_seal.v1.json"
            ),
            "assignments_reused": False,
            "access_histories_merged": False,
            "blindness_claims_merged": False,
        }:
            raise S44AmendmentError("amendment_02 historical NO-GO reference invalid")
    validate_historical_freeze(config, repo_root)


def _radial_position(radius: float, bearing_deg: float, z: float) -> list[float]:
    angle = math.radians(bearing_deg)
    return [round(radius * math.cos(angle), 6), round(radius * math.sin(angle), 6), z]


def _bearing_order(bearings: Sequence[float], direction: str) -> list[float]:
    values = [float(value) for value in bearings]
    if direction == "clockwise":
        return values
    if direction == "counterclockwise":
        return [values[0], *reversed(values[1:])]
    raise S44AmendmentError(f"unknown sweep direction {direction!r}")


def _source_fields(config: Mapping[str, Any], category: str) -> dict[str, Any]:
    identities = config["identities"]
    if category in {"controlled", "confidence"}:
        return {
            "source_device": identities["mac"]["model"] + " built-in speakers",
            "source_type": "reference_wav",
            "source_identity": identities["reference_wav"]["sha256"],
            "mac_system_volume_percent": 40,
            "mac_lid_angle_deg": 90,
            "mac_keyboard_plane": "level",
            "source_orientation": identities["mac"]["orientation"],
        }
    if category == "audio_video":
        impact = identities["impact"]
        return {
            "source_device": impact["object"],
            "source_type": "visible_audible_ordinary_object_impact",
            "source_identity": f"{impact['object']}__{impact['surface']}",
            "impact_action": impact["action"],
            "impact_target_elapsed_times_s": impact["three_target_elapsed_times_s"],
            "impact_privacy_clean_identity_required": True,
        }
    return {
        "source_device": "not_applicable",
        "source_type": "silence",
        "source_identity": "ambient_room_silence",
    }


def _planned_take(
    config: Mapping[str, Any],
    *,
    session_id: str,
    partition: str,
    category: str,
    repetition: int,
    bearing_deg: float | None = None,
    radius_m: float | None = None,
    position_m: Sequence[float] | None = None,
    playback_gain: float | None = None,
    sweep_index: int | None = None,
    sweep_direction: str | None = None,
    silence_slot: str | None = None,
) -> dict[str, Any]:
    z = float(config["identities"]["mac"]["source_height_m"])
    target_position = (
        list(position_m)
        if position_m is not None
        else (
            _radial_position(float(radius_m), float(bearing_deg), z)
            if radius_m is not None and bearing_deg is not None
            else None
        )
    )
    condition = {
        "session_id": session_id,
        "room_id": config["identities"]["room_id"],
        "source_device": _source_fields(config, category)["source_device"],
        "source_identity": _source_fields(config, category)["source_identity"],
        "source_type": _source_fields(config, category)["source_type"],
        "target_position_m_f_project": target_position,
        "target_bearing_deg_f_project": bearing_deg,
        "target_radius_m": radius_m,
        "mounting_condition": config["identities"]["fixture_id"],
        "acoustic_condition": (
            "ambient_silence"
            if category == "silence"
            else "privacy_clean_impact"
            if category == "audio_video"
            else "unobstructed_reference"
        ),
    }
    group_prefix = "s44a_grp_" if int(config["version"]) == 1 else "s44a02_grp_"
    group_id = group_prefix + canonical_sha256(condition)[:20]
    return {
        "partition": partition,
        "session_id": session_id,
        "session_date_local": None,
        "category": category,
        "repetition": repetition,
        "sweep_index": sweep_index,
        "sweep_direction": sweep_direction,
        "silence_slot": silence_slot,
        "duration_s": config["durations_s"][category],
        "source_frame": "F_project",
        "target_position_m_f_project": target_position,
        "target_bearing_deg_f_project": bearing_deg,
        "target_radius_m": radius_m,
        "playback_gain": playback_gain,
        "complete_removal_and_fresh_reposition_required": category
        in {"controlled", "confidence"},
        "recorded_position_bearing_distance_required": category
        in {"controlled", "confidence"},
        "modality_bundle": (
            ["six_channel_audio", "zed_svo2", "zed_frame_jsonl"]
            if category == "audio_video"
            else ["six_channel_audio"]
        ),
        "zed_required": category == "audio_video",
        "group_id": group_id,
        "group_identity": condition,
        **_source_fields(config, category),
    }


def _fit_session(config: Mapping[str, Any], session_id: str) -> list[dict[str, Any]]:
    partition = "fit"
    matrix = config["matrix"]["fit"]
    order = config["ordering"][session_id]
    takes = [
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=1,
            silence_slot="beginning",
        )
    ]
    controlled: list[dict[str, Any]] = []
    for sweep_index, (radius, direction) in enumerate(
        zip(
            order["controlled_radius_order_m"],
            order["controlled_directions"],
            strict=True,
        ),
        1,
    ):
        for repetition in (1, 2):
            for bearing in _bearing_order(matrix["controlled_bearings_deg"], direction):
                controlled.append(
                    _planned_take(
                        config,
                        session_id=session_id,
                        partition=partition,
                        category="controlled",
                        repetition=repetition,
                        bearing_deg=bearing,
                        radius_m=float(radius),
                        playback_gain=1.0,
                        sweep_index=sweep_index,
                        sweep_direction=direction,
                    )
                )
    takes.extend(controlled[:24])
    takes.append(
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=2,
            silence_slot="middle",
        )
    )
    takes.extend(controlled[24:])
    gains = list(matrix["confidence_playback_gains"])
    if order["confidence_gain_order"] == "low_to_high":
        gains.reverse()
    for gain in gains:
        for bearing in matrix["confidence_bearings_deg"]:
            takes.append(
                _planned_take(
                    config,
                    session_id=session_id,
                    partition=partition,
                    category="confidence",
                    repetition=1,
                    bearing_deg=float(bearing),
                    radius_m=float(matrix["confidence_radius_m"]),
                    playback_gain=float(gain),
                )
            )
    takes.append(
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=3,
            silence_slot="end",
        )
    )
    for position in matrix["audio_video_positions_m"]:
        for repetition in (1, 2):
            takes.append(
                _planned_take(
                    config,
                    session_id=session_id,
                    partition=partition,
                    category="audio_video",
                    repetition=repetition,
                    position_m=position,
                )
            )
    return takes


def _holdout_session(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    session_id = "prospective_holdout"
    partition = "prospective_holdout"
    matrix = config["matrix"][partition]
    takes = [
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=1,
            silence_slot="beginning",
        )
    ]
    for repetition, direction in enumerate(
        config["ordering"][session_id]["controlled_sweep_directions"], 1
    ):
        for bearing in _bearing_order(matrix["controlled_bearings_deg"], direction):
            takes.append(
                _planned_take(
                    config,
                    session_id=session_id,
                    partition=partition,
                    category="controlled",
                    repetition=repetition,
                    bearing_deg=bearing,
                    radius_m=float(matrix["controlled_radius_m"]),
                    playback_gain=float(matrix["controlled_playback_gain"]),
                    sweep_index=repetition,
                    sweep_direction=direction,
                )
            )
    takes.append(
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=2,
            silence_slot="middle",
        )
    )
    gains = list(matrix["confidence_playback_gains"])
    for repetition in (1, 2):
        for bearing_index, bearing in enumerate(matrix["confidence_bearings_deg"]):
            ordered = (
                gains if (bearing_index + repetition) % 2 else list(reversed(gains))
            )
            for gain in ordered:
                takes.append(
                    _planned_take(
                        config,
                        session_id=session_id,
                        partition=partition,
                        category="confidence",
                        repetition=repetition,
                        bearing_deg=float(bearing),
                        radius_m=float(matrix["confidence_radius_m"]),
                        playback_gain=float(gain),
                    )
                )
    takes.append(
        _planned_take(
            config,
            session_id=session_id,
            partition=partition,
            category="silence",
            repetition=3,
            silence_slot="end",
        )
    )
    for position in matrix["audio_video_positions_m"]:
        for repetition in (1, 2):
            takes.append(
                _planned_take(
                    config,
                    session_id=session_id,
                    partition=partition,
                    category="audio_video",
                    repetition=repetition,
                    position_m=position,
                )
            )
    return takes


def build_manifests(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build exact ordered fit and prospective-holdout manifests."""

    session_takes = {
        "fit_a": _fit_session(config, "fit_a"),
        "fit_b": _fit_session(config, "fit_b"),
        "prospective_holdout": _holdout_session(config),
    }
    manifests: dict[str, dict[str, Any]] = {}
    for session_id, takes in session_takes.items():
        for sequence, take in enumerate(takes, 1):
            condition_tag = {
                "controlled": "ctl",
                "confidence": "conf",
                "silence": "sil",
                "audio_video": "av",
            }[take["category"]]
            planned_id = (
                f"s44a{int(config['version']):02d}_"
                f"{session_id}_{sequence:03d}_{condition_tag}"
            )
            take["planned_take_id"] = planned_id
            take["sequence_index"] = sequence
        for sequence, take in enumerate(takes, 1):
            take["predecessor_planned_take_id"] = (
                None if sequence == 1 else takes[sequence - 2]["planned_take_id"]
            )
            take["successor_planned_take_id"] = (
                None if sequence == len(takes) else takes[sequence]["planned_take_id"]
            )
            attempt_root = config["retention"]["attempt_root"]
            planned_id = take["planned_take_id"]
            attempt_01 = f"{attempt_root}/{planned_id}/{planned_id}__attempt_01"
            attempt_02 = f"{attempt_root}/{planned_id}/{planned_id}__attempt_02"
            take["expected_artifact_paths"] = {
                "planned_cell_record": f"{attempt_root}/{planned_id}/planned_cell.json",
                "attempt_01_root": attempt_01,
                "replacement_attempt_02_root": attempt_02,
                "attempt_01_manifest": f"{attempt_01}/manifest.json",
                "replacement_attempt_02_manifest": f"{attempt_02}/manifest.json",
            }
            take["take_definition_sha256"] = canonical_sha256(
                {
                    key: value
                    for key, value in take.items()
                    if key != "take_definition_sha256"
                }
            )
        partition = takes[0]["partition"]
        payload = {
            "schema": (
                MANIFEST_SCHEMA_V2 if int(config["version"]) == 2 else MANIFEST_SCHEMA
            ),
            "status": "frozen_before_collection",
            "amendment_id": config["amendment_id"],
            "partition": partition,
            "session_id": session_id,
            "session_date_local": None,
            "calendar_day_role": next(
                item["calendar_day_role"]
                for item in config["sessions"]
                if item["session_id"] == session_id
            ),
            "planned_take_count": len(takes),
            "takes": takes,
        }
        manifests[session_id] = _self_hashed(payload, "manifest_sha256")
    validate_manifests(manifests, config)
    return manifests


def _validate_position(position: object, bounds: Mapping[str, Sequence[float]]) -> None:
    if position is None:
        return
    if not isinstance(position, list) or len(position) != 3:
        raise S44AmendmentError("target position must be a three-element list")
    for value, axis in zip(position, ("x", "y", "z"), strict=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise S44AmendmentError(f"position {axis}: expected finite number")
        if not math.isfinite(float(value)) or not (
            bounds[axis][0] <= float(value) <= bounds[axis][1]
        ):
            raise S44AmendmentError(f"position {axis}: outside frozen room bounds")


def validate_manifests(
    manifests: Mapping[str, Mapping[str, Any]], config: Mapping[str, Any]
) -> None:
    """Validate exact counts, ordering, coordinates, hashes, and leakage."""

    if set(manifests) != set(EXPECTED_SESSION_COUNTS):
        raise S44AmendmentError("manifest session set mismatch")
    partitions: Counter[str] = Counter()
    categories: Counter[tuple[str, str]] = Counter()
    all_ids: set[str] = set()
    groups: dict[str, set[str]] = defaultdict(set)
    bounds = config["room_bounds_m"]
    for session_id, manifest in manifests.items():
        expected_manifest_schema = (
            MANIFEST_SCHEMA_V2 if int(config["version"]) == 2 else MANIFEST_SCHEMA
        )
        if manifest.get("schema") != expected_manifest_schema:
            raise S44AmendmentError(f"{session_id}: wrong manifest schema")
        _validate_self_hash(manifest, "manifest_sha256", session_id)
        takes = manifest.get("takes")
        if (
            not isinstance(takes, list)
            or len(takes) != EXPECTED_SESSION_COUNTS[session_id]
        ):
            raise S44AmendmentError(f"{session_id}: planned take count mismatch")
        if manifest.get("planned_take_count") != len(takes):
            raise S44AmendmentError(f"{session_id}: declared count mismatch")
        if takes[-4:][0]["category"] != "audio_video" or any(
            take["category"] != "audio_video" for take in takes[-4:]
        ):
            raise S44AmendmentError(f"{session_id}: audio-video takes are not last")
        silence_positions = [
            take["sequence_index"] for take in takes if take["category"] == "silence"
        ]
        expected_silence = (
            [1, 26, 47] if session_id != "prospective_holdout" else [1, 26, 43]
        )
        if silence_positions != expected_silence:
            raise S44AmendmentError(f"{session_id}: silence placement mismatch")
        for index, take in enumerate(takes, 1):
            if take.get("sequence_index") != index:
                raise S44AmendmentError(f"{session_id}: noncontiguous sequence")
            planned_id = take.get("planned_take_id")
            if not isinstance(planned_id, str) or planned_id in all_ids:
                raise S44AmendmentError(f"{session_id}: duplicate or invalid take id")
            all_ids.add(planned_id)
            expected_previous = (
                None if index == 1 else takes[index - 2]["planned_take_id"]
            )
            expected_next = (
                None if index == len(takes) else takes[index]["planned_take_id"]
            )
            if take.get("predecessor_planned_take_id") != expected_previous:
                raise S44AmendmentError(f"{planned_id}: predecessor mismatch")
            if take.get("successor_planned_take_id") != expected_next:
                raise S44AmendmentError(f"{planned_id}: successor mismatch")
            expected_hash = canonical_sha256(
                {
                    key: value
                    for key, value in take.items()
                    if key != "take_definition_sha256"
                }
            )
            if take.get("take_definition_sha256") != expected_hash:
                raise S44AmendmentError(f"{planned_id}: definition hash mismatch")
            _validate_position(take.get("target_position_m_f_project"), bounds)
            category = str(take["category"])
            if take.get("duration_s") != config["durations_s"][category]:
                raise S44AmendmentError(f"{planned_id}: duration mismatch")
            if category in {"controlled", "confidence"} and (
                take.get("complete_removal_and_fresh_reposition_required") is not True
                or take.get("recorded_position_bearing_distance_required") is not True
                or take.get("mac_system_volume_percent") != 40
                or take.get("mac_lid_angle_deg") != 90
            ):
                raise S44AmendmentError(f"{planned_id}: positioning contract weakened")
            partitions[str(take["partition"])] += 1
            categories[(session_id, category)] += 1
            groups[str(take["group_id"])].add(str(take["partition"]))
    if dict(partitions) != EXPECTED_PARTITION_COUNTS:
        raise S44AmendmentError(f"partition counts mismatch: {dict(partitions)}")
    if dict(categories) != EXPECTED_CATEGORY_COUNTS:
        raise S44AmendmentError("session/category counts mismatch")
    crossing = sorted(
        group_id for group_id, values in groups.items() if len(values) != 1
    )
    if crossing:
        raise S44AmendmentError(f"fit/holdout leakage groups: {crossing}")


def combined_partition_manifest(
    manifests: Mapping[str, Mapping[str, Any]], partition: str
) -> dict[str, Any]:
    """Combine session manifests within one partition without changing assignments."""

    selected = [
        value for value in manifests.values() if value["partition"] == partition
    ]
    takes = [take for manifest in selected for take in manifest["takes"]]
    payload = {
        "schema": "ias.s4_4.amendment_partition_manifest.v1",
        "status": "frozen_before_collection",
        "partition": partition,
        "session_manifest_sha256": {
            manifest["session_id"]: manifest["manifest_sha256"] for manifest in selected
        },
        "planned_take_count": len(takes),
        "planned_take_ids": [take["planned_take_id"] for take in takes],
        "group_ids": sorted({take["group_id"] for take in takes}),
    }
    return _self_hashed(payload, "partition_manifest_sha256")


def build_aggregate_index(
    config: Mapping[str, Any],
    *,
    fit_manifest_sha256: str,
    holdout_manifest_sha256: str,
) -> dict[str, Any]:
    """Reference legacy and amendment records without merging blindness claims."""

    records = [
        {
            "record_id": "original_s4_4_freeze",
            "role": "historically_analyzed_legacy_evidence",
            "split_plan_path": ("outputs/isaac_audio_sensors/S4/S4.4/split_plan.json"),
            "split_plan_payload_sha256": config["historical_freeze"][
                "split_plan_payload_sha256"
            ],
            "holdout_manifest_path": (
                "outputs/isaac_audio_sensors/S4/S4.4/holdout_manifest.json"
            ),
            "holdout_seal_path": (
                "outputs/isaac_audio_sensors/S4/S4.4/holdout_seal.json"
            ),
            "historically_unopened_claim": False,
            "access_history": "dataset/S4.4/access/access_ledger.jsonl",
        }
    ]
    if int(config["version"]) == 2:
        historical = config["historical_no_go_amendment_01"]
        records.append(
            {
                "record_id": historical["amendment_id"],
                "role": "immutable_historical_no_go_evidence",
                "status": "no_go",
                "closure_record_path": historical["closure_record_path"],
                "closure_seal_path": historical["closure_seal_path"],
                "assignments_reused": False,
                "access_history": (
                    "dataset/S4.4/amendments/"
                    "s4_4_data_expansion_amendment_01/access/access_ledger.jsonl"
                ),
                "access_history_existed_at_closure": False,
                "blindness_claim_inherited": False,
            }
        )
    records.append(
        {
            "record_id": config["amendment_id"],
            "role": "primary_unopened_prospective_holdout_for_future_evaluation",
            "fit_manifest_sha256": fit_manifest_sha256,
            "prospective_holdout_manifest_sha256": holdout_manifest_sha256,
            "scientifically_opened": False,
            "access_history": config["retention"]["access_root"]
            + "/access_ledger.jsonl",
        }
    )
    payload = {
        "schema": (
            AGGREGATE_SCHEMA_V2 if int(config["version"]) == 2 else AGGREGATE_SCHEMA
        ),
        "status": "frozen_before_collection",
        "records": records,
        "assignments_merged": False,
        "access_histories_merged": False,
        "blindness_claims_merged": False,
        "original_assignment_changed": False,
    }
    return _self_hashed(payload, "aggregate_index_sha256")


def build_precollection_seal(
    config: Mapping[str, Any],
    *,
    bindings: Mapping[str, str],
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind manifests, schemas, identities, policy, and the original freeze."""

    for label, digest in bindings.items():
        _require_sha256(digest, f"precollection binding {label}")
    status = "committed" if checkpoint is not None else "awaiting_commit_authorization"
    payload = {
        "schema": (
            PRECOLLECTION_SEAL_SCHEMA_V2
            if int(config["version"]) == 2
            else PRECOLLECTION_SEAL_SCHEMA
        ),
        "status": status,
        "amendment_id": config["amendment_id"],
        "bindings": dict(sorted(bindings.items())),
        "historical_split_plan_payload_sha256": config["historical_freeze"][
            "split_plan_payload_sha256"
        ],
        "historical_record_set_sha256": canonical_sha256(
            config["historical_freeze"]["records"]
        ),
        "identity_contract_sha256": canonical_sha256(config["identities"]),
        "grouping_policy_sha256": canonical_sha256(config["grouping"]),
        "replacement_policy_sha256": canonical_sha256(config["replacement_policy"]),
        "retention_policy_sha256": canonical_sha256(config["retention"]),
        "source_checkpoint": checkpoint,
        "collection_allowed": checkpoint is not None,
        "s4_5_or_later_started": False,
    }
    return _self_hashed(payload, "seal_payload_sha256")


def validate_source_checkpoint(
    checkpoint: Mapping[str, Any],
    repo_root: Path,
    *,
    require_current_checkout: bool = True,
) -> None:
    """Require exact Git bytes and optionally require the current checkout bytes."""

    if set(checkpoint) != {"commit", "source_records", "checkpoint_sha256"}:
        raise S44AmendmentError("source checkpoint field set mismatch")
    _validate_self_hash(checkpoint, "checkpoint_sha256", "source checkpoint")
    commit = _require_commit(checkpoint.get("commit"), "source checkpoint commit")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise S44AmendmentError("source checkpoint commit does not exist")
    records = checkpoint.get("source_records")
    if not isinstance(records, list) or not records:
        raise S44AmendmentError("source checkpoint records absent")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {"path", "sha256"}:
            raise S44AmendmentError(f"source checkpoint records[{index}] invalid")
        relative = _safe_relative(record["path"], f"checkpoint records[{index}].path")
        expected = _require_sha256(record["sha256"], f"checkpoint {relative}")
        result = subprocess.run(
            ["git", "show", "--no-ext-diff", f"{commit}:{relative}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            result.returncode != 0
            or hashlib.sha256(result.stdout).hexdigest() != expected
        ):
            raise S44AmendmentError(f"source checkpoint Git blob mismatch: {relative}")
        if require_current_checkout:
            path = repo_root / relative
            if not path.is_file() or sha256_file(path) != expected:
                raise S44AmendmentError(
                    f"source checkpoint checkout mismatch: {relative}"
                )


def validate_precollection_seal(
    seal: Mapping[str, Any],
    *,
    repo_root: Path,
    require_committed: bool,
    require_current_source: bool = True,
) -> None:
    """Validate the preregistration seal; capture requires committed state."""

    if seal.get("schema") not in {
        PRECOLLECTION_SEAL_SCHEMA,
        PRECOLLECTION_SEAL_SCHEMA_V2,
    }:
        raise S44AmendmentError("precollection seal schema mismatch")
    expected_id = (
        "s4_4_data_expansion_amendment_02"
        if seal.get("schema") == PRECOLLECTION_SEAL_SCHEMA_V2
        else "s4_4_data_expansion_amendment_01"
    )
    if seal.get("amendment_id") != expected_id:
        raise S44AmendmentError("precollection seal amendment/schema mismatch")
    _validate_self_hash(seal, "seal_payload_sha256", "precollection seal")
    checkpoint = seal.get("source_checkpoint")
    if require_committed:
        if (
            seal.get("status") != "committed"
            or seal.get("collection_allowed") is not True
            or not isinstance(checkpoint, Mapping)
        ):
            raise S44AmendmentError(
                "capture denied: precollection freeze is not committed"
            )
        validate_source_checkpoint(
            checkpoint,
            repo_root,
            require_current_checkout=require_current_source,
        )
    elif seal.get("collection_allowed") is not (checkpoint is not None):
        raise S44AmendmentError("precollection seal collection flag inconsistent")


def build_source_checkpoint(
    repo_root: Path, commit: str, paths: Sequence[str]
) -> dict[str, Any]:
    """Create the post-authorization exact source checkpoint contract."""

    commit = _require_commit(commit, "source checkpoint commit")
    records: list[dict[str, str]] = []
    for relative in sorted(paths):
        safe = _safe_relative(relative, "source checkpoint path")
        result = subprocess.run(
            ["git", "show", "--no-ext-diff", f"{commit}:{safe}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise S44AmendmentError(f"checkpoint source absent from commit: {safe}")
        records.append(
            {"path": safe, "sha256": hashlib.sha256(result.stdout).hexdigest()}
        )
    return _self_hashed(
        {"commit": commit, "source_records": records}, "checkpoint_sha256"
    )


def validate_session_preflight(
    record: Mapping[str, Any], config: Mapping[str, Any], *, other_dates: Sequence[str]
) -> None:
    """Validate all inherited gates and enforce three distinct calendar days."""

    if record.get("schema") != PREFLIGHT_SCHEMA or record.get("status") != "passed":
        raise S44AmendmentError("session preflight schema/status invalid")
    session_id = record.get("session_id")
    if session_id not in EXPECTED_SESSION_COUNTS:
        raise S44AmendmentError("session preflight session id invalid")
    value = record.get("session_date_local")
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise S44AmendmentError("session date must be exact ISO calendar date") from exc
    if parsed.isoformat() in set(other_dates):
        raise S44AmendmentError("session date must differ from both other sessions")
    checks = record.get("checks")
    required = config["preflight_required_checks"]
    if not isinstance(checks, Mapping) or set(checks) != set(required):
        raise S44AmendmentError("session preflight exact check set mismatch")
    if any(value != "passed" for value in checks.values()):
        raise S44AmendmentError("session preflight contains a non-passing gate")
    expected_identity_hash = canonical_sha256(config["identities"])
    if record.get("identity_contract_sha256") != expected_identity_hash:
        raise S44AmendmentError("session preflight identity contract mismatch")
    _validate_self_hash(record, "preflight_sha256", "session preflight")


def validate_session_readiness(
    record: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    precollection_seal_sha256: str,
    inherited_preflight_sha256: str,
    require_today: bool = True,
) -> None:
    """Validate the no-media gate that must pass before attempt allocation."""

    if record.get("schema") != READINESS_SCHEMA or record.get("status") != "passed":
        raise S44AmendmentError("session readiness schema/status invalid")
    if record.get("amendment_id") != config.get("amendment_id"):
        raise S44AmendmentError("session readiness amendment mismatch")
    if record.get("session_id") not in EXPECTED_SESSION_COUNTS:
        raise S44AmendmentError("session readiness session id invalid")
    session_date = str(record.get("session_date_local"))
    try:
        parsed = date.fromisoformat(session_date)
    except ValueError as exc:
        raise S44AmendmentError("session readiness date invalid") from exc
    if require_today and parsed != date.today():
        raise S44AmendmentError("session readiness is not for today's local date")
    if record.get("precollection_seal_sha256") != _require_sha256(
        precollection_seal_sha256, "session readiness seal"
    ):
        raise S44AmendmentError("session readiness seal binding mismatch")
    if record.get("inherited_preflight_sha256") != _require_sha256(
        inherited_preflight_sha256, "session readiness inherited preflight"
    ):
        raise S44AmendmentError("session readiness preflight binding mismatch")
    checks = record.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != REQUIRED_READINESS_CHECKS:
        raise S44AmendmentError("session readiness exact check set mismatch")
    if any(value != "passed" for value in checks.values()):
        raise S44AmendmentError("session readiness contains a non-passing gate")
    if (
        record.get("attempt_allocated") is not False
        or record.get("recorder_started") is not False
        or record.get("media_created") is not False
    ):
        raise S44AmendmentError("session readiness crossed the attempt/media boundary")
    _validate_self_hash(record, "readiness_sha256", "session readiness")


def build_attempt_contract(
    take: Mapping[str, Any],
    *,
    attempt_number: int,
    precollection_seal_sha256: str,
    session_readiness_sha256: str | None = None,
) -> dict[str, Any]:
    """Create one deterministic attempt identity; only attempt 2 is a replacement."""

    if attempt_number not in {1, 2}:
        raise S44AmendmentError("at most one replacement attempt is allowed")
    planned_id = str(take["planned_take_id"])
    payload = {
        "schema": ATTEMPT_SCHEMA,
        "planned_take_id": planned_id,
        "attempt_id": f"{planned_id}__attempt_{attempt_number:02d}",
        "attempt_number": attempt_number,
        "replacement": attempt_number == 2,
        "partition": take["partition"],
        "session_id": take["session_id"],
        "take_definition_sha256": take["take_definition_sha256"],
        "precollection_seal_sha256": _require_sha256(
            precollection_seal_sha256, "attempt precollection seal"
        ),
        "outcome": "planned",
        "technical_failure_reason": None,
        "scientific_outcome_used_for_replacement": False,
    }
    if session_readiness_sha256 is not None:
        payload["session_readiness_sha256"] = _require_sha256(
            session_readiness_sha256, "attempt session readiness"
        )
    return _self_hashed(payload, "attempt_contract_sha256")


def validate_attempt_census(
    manifests: Mapping[str, Mapping[str, Any]], attempts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Retain all attempts, enforce one replacement, and classify NO-GO."""

    takes = {
        take["planned_take_id"]: take
        for manifest in manifests.values()
        for take in manifest["takes"]
    }
    by_take: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen_attempts: set[str] = set()
    valid_outcomes = {"planned", "pre_recording_failure", "invalid", "valid"}
    for attempt in attempts:
        planned_id = attempt.get("planned_take_id")
        attempt_id = attempt.get("attempt_id")
        if planned_id not in takes or not isinstance(attempt_id, str):
            raise S44AmendmentError("attempt references unknown planned take")
        if attempt_id in seen_attempts:
            raise S44AmendmentError("duplicate attempt id")
        seen_attempts.add(attempt_id)
        number = attempt.get("attempt_number")
        if number not in {1, 2} or attempt_id != f"{planned_id}__attempt_{number:02d}":
            raise S44AmendmentError("attempt number/id mismatch")
        if attempt.get("partition") != takes[planned_id]["partition"]:
            raise S44AmendmentError("replacement partition changed")
        if attempt.get("session_id") != takes[planned_id]["session_id"]:
            raise S44AmendmentError("replacement session changed")
        if (
            attempt.get("take_definition_sha256")
            != takes[planned_id]["take_definition_sha256"]
        ):
            raise S44AmendmentError("replacement condition changed")
        if attempt.get("outcome") not in valid_outcomes:
            raise S44AmendmentError("attempt outcome invalid")
        if attempt.get("scientific_outcome_used_for_replacement") is not False:
            raise S44AmendmentError("scientific outcome cannot drive replacement")
        by_take[str(planned_id)].append(attempt)
    second_failure = False
    valid_cells = 0
    failures = 0
    replacements = 0
    for planned_id, records in by_take.items():
        ordered = sorted(records, key=lambda item: int(item["attempt_number"]))
        if len(ordered) > 2 or [item["attempt_number"] for item in ordered] != list(
            range(1, len(ordered) + 1)
        ):
            raise S44AmendmentError(f"{planned_id}: invalid attempt sequence")
        outcomes = [str(item["outcome"]) for item in ordered]
        if len(ordered) == 2:
            replacements += 1
            if outcomes[0] not in {"pre_recording_failure", "invalid"}:
                raise S44AmendmentError("replacement requires first technical failure")
        failures += sum(
            outcome in {"pre_recording_failure", "invalid"} for outcome in outcomes
        )
        if "valid" in outcomes:
            if outcomes[-1] != "valid":
                raise S44AmendmentError("attempts after a valid take are forbidden")
            valid_cells += 1
        if len(outcomes) == 2 and outcomes[-1] in {"pre_recording_failure", "invalid"}:
            second_failure = True
    payload = {
        "schema": CENSUS_SCHEMA,
        "status": "no_go"
        if second_failure
        else "incomplete"
        if valid_cells < 149
        else "passed",
        "planned_takes": 149,
        "attempts": len(attempts),
        "valid_takes": valid_cells,
        "failures": failures,
        "replacements": replacements,
        "incomplete_planned_cells": 149 - valid_cells,
        "all_attempts_retained": True,
        "second_failure_present": second_failure,
    }
    return _self_hashed(payload, "census_sha256")


def sanitize_holdout_technical_qa(
    report: Mapping[str, Any], *, known_holdout_take_ids: set[str]
) -> dict[str, Any]:
    """Project technical predicates to the honest v2 names and suppress science."""

    planned_id = report.get("planned_take_id")
    if planned_id not in known_holdout_take_ids:
        raise S44AmendmentError("holdout QA references unknown holdout take")
    if set(report) >= LEGACY_TECHNICAL_QA_INPUT_FIELDS:
        permitted = {
            TECHNICAL_QA_FIELD_PROJECTION.get(key, key): report[key]
            for key in LEGACY_TECHNICAL_QA_INPUT_FIELDS
        }
        consumed = LEGACY_TECHNICAL_QA_INPUT_FIELDS
        source_schema = str(report.get("schema", "producer_legacy_field_set"))
    elif set(report) >= TECHNICAL_QA_INPUT_FIELDS:
        permitted = {key: report[key] for key in TECHNICAL_QA_INPUT_FIELDS}
        consumed = TECHNICAL_QA_INPUT_FIELDS
        source_schema = str(report.get("schema", "producer_canonical_field_set"))
    else:
        missing_legacy = LEGACY_TECHNICAL_QA_INPUT_FIELDS - set(report)
        missing_canonical = TECHNICAL_QA_INPUT_FIELDS - set(report)
        raise S44AmendmentError(
            "holdout QA missing fields: "
            f"legacy={sorted(missing_legacy)}, canonical={sorted(missing_canonical)}"
        )
    for key in TECHNICAL_QA_INPUT_FIELDS - {"planned_take_id", "attempt_id"}:
        if not isinstance(permitted[key], bool):
            raise S44AmendmentError(f"holdout QA {key}: expected boolean")
    output = {
        "schema": QA_SCHEMA_V2,
        "source_schema": source_schema,
        "partition": "prospective_holdout",
        **permitted,
        "overall_technical_pass": all(
            bool(permitted[key])
            for key in TECHNICAL_QA_INPUT_FIELDS - {"planned_take_id", "attempt_id"}
        ),
        "scientific_outputs_exposed": False,
        "suppressed_field_count": len(set(report) - consumed - {"schema"}),
    }
    return output


def canonicalize_holdout_technical_qa(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the v2 canonical projection of legacy or current technical QA."""

    schema = record.get("schema")
    if schema == QA_SCHEMA:
        if set(record) != LEGACY_TECHNICAL_QA_OUTPUT_FIELDS:
            raise S44AmendmentError(
                "persisted legacy holdout QA field set is not allowlisted"
            )
        projected = sanitize_holdout_technical_qa(
            record, known_holdout_take_ids={str(record.get("planned_take_id"))}
        )
        projected["source_schema"] = QA_SCHEMA
        projected["suppressed_field_count"] = int(record["suppressed_field_count"])
        if projected["overall_technical_pass"] is not record.get(
            "overall_technical_pass"
        ):
            raise S44AmendmentError("legacy holdout QA overall predicate mismatch")
    elif schema == QA_SCHEMA_V2:
        if set(record) != TECHNICAL_QA_OUTPUT_FIELDS:
            raise S44AmendmentError(
                "persisted canonical holdout QA field set is not allowlisted"
            )
        projected = dict(record)
        expected_overall = all(
            bool(projected[key])
            for key in TECHNICAL_QA_INPUT_FIELDS - {"planned_take_id", "attempt_id"}
        )
        if projected.get("overall_technical_pass") is not expected_overall:
            raise S44AmendmentError("canonical holdout QA overall predicate mismatch")
    else:
        raise S44AmendmentError("holdout QA schema/partition invalid")
    if projected.get("partition") != "prospective_holdout":
        raise S44AmendmentError("holdout QA schema/partition invalid")
    if projected.get("scientific_outputs_exposed") is not False:
        raise S44AmendmentError("holdout scientific output exposure is forbidden")
    return projected


def validate_holdout_technical_qa(record: Mapping[str, Any]) -> None:
    """Reject scientific fields and validate the legacy-to-v2 projection."""

    canonicalize_holdout_technical_qa(record)


def build_holdout_seal(
    holdout_manifest: Mapping[str, Any],
    qa_records: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Seal only after technical QA; scientific results are never accepted."""

    holdout_ids = set(holdout_manifest["planned_take_ids"])
    qa_by_take: dict[str, Mapping[str, Any]] = {}
    for record in qa_records:
        validate_holdout_technical_qa(record)
        planned_id = str(record["planned_take_id"])
        if planned_id in qa_by_take or planned_id not in holdout_ids:
            raise S44AmendmentError("duplicate or unknown holdout QA record")
        qa_by_take[planned_id] = record
    if set(qa_by_take) != holdout_ids or any(
        record["overall_technical_pass"] is not True for record in qa_by_take.values()
    ):
        raise S44AmendmentError("cannot seal incomplete or failed holdout technical QA")
    sealed_artifacts: list[dict[str, Any]] = []
    artifact_take_ids: set[str] = set()
    for record in artifacts:
        if set(record) != {"planned_take_id", "path", "byte_size", "sha256", "role"}:
            raise S44AmendmentError("holdout seal artifact fields invalid")
        if record["planned_take_id"] not in holdout_ids:
            raise S44AmendmentError("holdout seal contains non-holdout artifact")
        _safe_relative(record["path"], "holdout seal artifact path")
        _require_sha256(record["sha256"], "holdout seal artifact hash")
        artifact_take_ids.add(str(record["planned_take_id"]))
        sealed_artifacts.append(dict(record))
    if artifact_take_ids != holdout_ids:
        raise S44AmendmentError(
            "holdout seal requires at least one integrity record per planned cell"
        )
    payload = {
        "schema": HOLDOUT_SEAL_SCHEMA,
        "status": "sealed",
        "partition_manifest_sha256": holdout_manifest["partition_manifest_sha256"],
        "planned_take_ids": sorted(holdout_ids),
        "technical_qa_record_sha256": {
            planned_id: canonical_sha256(qa_by_take[planned_id])
            for planned_id in sorted(qa_by_take)
        },
        "artifacts": sorted(
            sealed_artifacts, key=lambda item: (item["path"], item["role"])
        ),
        "scientifically_opened": False,
        "technical_qa_only": True,
        "scientific_outputs_included": False,
        "repository_tool_enforcement_only": True,
        "filesystem_owner_reads_prevented_or_detected": False,
    }
    return _self_hashed(payload, "seal_payload_sha256")


def hash_only_holdout_integrity(
    seal: Mapping[str, Any], repo_root: Path
) -> dict[str, Any]:
    """Read bytes only for size/SHA-256 and return no content-derived values."""

    _validate_self_hash(seal, "seal_payload_sha256", "holdout seal")
    issues: list[dict[str, str]] = []
    checked = 0
    for record in seal.get("artifacts", []):
        relative = _safe_relative(record.get("path"), "holdout artifact path")
        path = (repo_root / relative).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError:
            issues.append({"code": "unsafe_path", "path": relative})
            continue
        if not path.is_file():
            issues.append({"code": "missing_file", "path": relative})
            continue
        if path.stat().st_size != record.get("byte_size"):
            issues.append({"code": "size_mismatch", "path": relative})
        if sha256_file(path) != record.get("sha256"):
            issues.append({"code": "hash_mismatch", "path": relative})
        checked += 1
    return {
        "schema": "ias.s4_4.amendment_hash_only_integrity.v1",
        "status": "passed" if not issues else "failed",
        "checked_artifact_count": checked,
        "issues": issues,
        "holdout_opened": False,
        "content_derived_values_returned": False,
        "media_returned": False,
        "scientific_outcomes_returned": False,
    }


def require_evidence_access(
    *, planned_take_id: str, purpose: str, fit_ids: set[str], holdout_ids: set[str]
) -> dict[str, Any]:
    """Fail closed for unknown purposes/paths and expose fit only to S4.5."""

    if purpose not in KNOWN_ACCESS_PURPOSES:
        raise S44AmendmentError(f"unknown access purpose: {purpose!r}")
    if planned_take_id not in fit_ids | holdout_ids:
        raise S44AmendmentError(f"unknown planned take: {planned_take_id!r}")
    if planned_take_id in fit_ids:
        return {"allowed": True, "mode": "fit_only", "holdout_opened": False}
    if purpose == "S4.4_amendment_integrity_validation":
        return {"allowed": True, "mode": "hash_only", "holdout_opened": False}
    if purpose == "S4.4_amendment_technical_QA":
        return {"allowed": True, "mode": "technical_QA_only", "holdout_opened": False}
    raise S44AmendmentError("prospective holdout access denied for fitting or tuning")


def validate_ledger(path: Path, *, expected_seal_sha256: str) -> dict[str, Any]:
    """Validate the amendment's separate append-only hash chain."""

    _require_sha256(expected_seal_sha256, "ledger seal")
    if not path.exists():
        return {
            "status": "passed",
            "event_count": 0,
            "head_sha256": ZERO_SHA256,
            "issues": [],
        }
    previous = ZERO_SHA256
    issues: list[dict[str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            issues.append({"code": "malformed_event", "path": str(index)})
            continue
        if not isinstance(record, dict):
            issues.append({"code": "invalid_event", "path": str(index)})
            continue
        supplied = record.get("event_sha256")
        payload = {key: value for key, value in record.items() if key != "event_sha256"}
        checks = (
            record.get("schema") == LEDGER_EVENT_SCHEMA,
            record.get("sequence") == index,
            record.get("previous_event_sha256") == previous,
            record.get("seal_sha256") == expected_seal_sha256,
            supplied == canonical_sha256(payload),
        )
        if not all(checks):
            issues.append({"code": "ledger_event_invalid", "path": str(index)})
        previous = str(supplied)
    return {
        "status": "passed" if not issues else "failed",
        "event_count": len(lines),
        "head_sha256": previous,
        "issues": issues,
    }


def append_ledger_event(path: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    """Append an allowed or denied repository-tool access attempt."""

    seal_sha = _require_sha256(event.get("seal_sha256"), "ledger event seal")
    validation = validate_ledger(path, expected_seal_sha256=seal_sha)
    if validation["status"] != "passed":
        raise S44AmendmentError("access ledger is invalid; refusing append")
    payload = {
        "schema": LEDGER_EVENT_SCHEMA,
        "sequence": validation["event_count"],
        "previous_event_sha256": validation["head_sha256"],
        **event,
        "holdout_opened": False,
        "scientific_outputs_returned": False,
    }
    record = _self_hashed(payload, "event_sha256")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(record) + "\n")
    return record


def initialize_access_ledger(
    path: Path, *, seal_sha256: str, event_time_utc: str
) -> dict[str, Any]:
    """Create the one permitted first event for a newly sealed holdout."""

    if path.exists():
        raise S44AmendmentError("access ledger already exists; refusing reinitialize")
    return append_ledger_event(
        path,
        {
            "event": "seal_initialized",
            "event_time_utc": event_time_utc,
            "seal_sha256": _require_sha256(seal_sha256, "ledger seal"),
            "purpose": "S4.4_amendment_sealing",
            "allowed": True,
            "mode": "sealed",
        },
    )


def authorize_and_record_access(
    *,
    planned_take_id: str,
    purpose: str,
    fit_ids: set[str],
    holdout_ids: set[str],
    ledger_path: Path,
    seal_sha256: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Authorize and audit one access attempt, including fail-closed denials."""

    if not ledger_path.is_file():
        raise S44AmendmentError("access denied: sealed access ledger is missing")
    try:
        decision = require_evidence_access(
            planned_take_id=planned_take_id,
            purpose=purpose,
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )
    except S44AmendmentError:
        append_ledger_event(
            ledger_path,
            {
                "event": "access_attempt",
                "event_time_utc": event_time_utc,
                "seal_sha256": seal_sha256,
                "purpose": purpose,
                "planned_take_id": planned_take_id,
                "allowed": False,
                "mode": "denied",
            },
        )
        raise
    append_ledger_event(
        ledger_path,
        {
            "event": "access_attempt",
            "event_time_utc": event_time_utc,
            "seal_sha256": seal_sha256,
            "purpose": purpose,
            "planned_take_id": planned_take_id,
            "allowed": True,
            "mode": decision["mode"],
        },
    )
    return decision


def technical_qa_and_record(
    report: Mapping[str, Any],
    *,
    known_holdout_take_ids: set[str],
    ledger_path: Path,
    seal_sha256: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Sanitize technical QA and append its pass/fail access event."""

    if not ledger_path.is_file():
        raise S44AmendmentError("technical QA denied: sealed access ledger is missing")
    output = sanitize_holdout_technical_qa(
        report, known_holdout_take_ids=known_holdout_take_ids
    )
    append_ledger_event(
        ledger_path,
        {
            "event": "technical_qa",
            "event_time_utc": event_time_utc,
            "seal_sha256": seal_sha256,
            "purpose": "S4.4_amendment_technical_QA",
            "planned_take_id": output["planned_take_id"],
            "allowed": True,
            "mode": "technical_QA_only",
            "technical_status": (
                "passed" if output["overall_technical_pass"] else "failed"
            ),
        },
    )
    return output


def hash_only_integrity_and_record(
    seal: Mapping[str, Any],
    *,
    repo_root: Path,
    ledger_path: Path,
    seal_sha256: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Run hash-only integrity and append an audit event without science."""

    if not ledger_path.is_file():
        raise S44AmendmentError(
            "integrity validation denied: sealed access ledger is missing"
        )
    result = hash_only_holdout_integrity(seal, repo_root)
    append_ledger_event(
        ledger_path,
        {
            "event": "integrity_validation",
            "event_time_utc": event_time_utc,
            "seal_sha256": seal_sha256,
            "purpose": "S4.4_amendment_integrity_validation",
            "allowed": True,
            "mode": "hash_only",
            "technical_status": result["status"],
            "checked_artifact_count": result["checked_artifact_count"],
        },
    )
    return result
