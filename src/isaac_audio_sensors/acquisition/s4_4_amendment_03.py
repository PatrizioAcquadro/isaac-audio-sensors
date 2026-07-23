"""Additive S4.4 amendment-03 contracts.

Amendment 03 inherits completed amendment-02 Fit A by hash and creates new
identities only for future Fit B and prospective holdout acquisition.  It does
not fit parameters or expose holdout scientific outcomes.
"""

from __future__ import annotations

import copy
import hashlib
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    load_amendment_configuration,
    load_json,
    sha256_file,
    validate_attempt_census,
    validate_source_checkpoint,
)
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    build_manifests as build_amendment_02_manifests,
)
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    validate_configuration as validate_amendment_02_configuration,
)
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    validate_session_readiness as validate_amendment_02_readiness,
)

CONFIG_SCHEMA = "ias.s4_4.data_expansion_amendment_config.v3"
MANIFEST_SCHEMA = "ias.s4_4.data_expansion_manifest.v3"
INHERITED_FIT_A_SCHEMA = "ias.s4_4.amendment_03_inherited_fit_a.v1"
PREFLIGHT_SCHEMA = "ias.s4_4.amendment_session_preflight.v2"
READINESS_SCHEMA = "ias.s4_4.amendment_session_readiness.v2"
PRECOLLECTION_SEAL_SCHEMA = "ias.s4_4.amendment_precollection_seal.v3"
AGGREGATE_SCHEMA = "ias.s4_4.aggregate_index.v3"
AMENDMENT_ID = "s4_4_data_expansion_amendment_03"
AMENDMENT_02_ID = "s4_4_data_expansion_amendment_02"
FUTURE_SESSION_COUNTS = {"fit_b": 51, "prospective_holdout": 47}
LOGICAL_COUNTS = {
    "inherited_fit_a": 51,
    "new_fit_b": 51,
    "new_prospective_holdout": 47,
    "total": 149,
}
REQUIRED_READINESS_CHECKS = {
    "network_permission_confirmed",
    "mac_ssh_connectivity",
    "mac_full_preflight_json",
    "mac_dynamic_preflight_json",
    "mac_identity_volume_mute_power_reference_keyboard_and_lid",
    "pi_ssh_connectivity",
    "pi_helper_and_record_command_contract",
    "respeaker_identity_device_format_channel_health_disk_and_output",
    "zed_identity_and_readiness",
    "clocks_and_truthful_session_timestamps",
    "room_environment_mount_frame_origin_and_bounds",
    "privacy",
    "gitignore_and_output_paths",
    "access_policy_and_ledger_state",
}


def active_precollection_package(evidence_root: Path) -> tuple[Path, Path]:
    """Return the active same-amendment index and seal, failing closed on partial v2."""

    index_v2 = evidence_root / "evidence_index.v2.json"
    seal_v2 = evidence_root / "precollection_seal.v2.json"
    checksum_v2 = evidence_root / "SHA256SUMS.v2"
    if any(path.exists() for path in (index_v2, seal_v2, checksum_v2)):
        if not all(path.is_file() for path in (index_v2, seal_v2, checksum_v2)):
            raise S44AmendmentError(
                "amendment_03 multiday continuation package is incomplete"
            )
        return index_v2, seal_v2
    return evidence_root / "evidence_index.v1.json", evidence_root / (
        "precollection_seal.v1.json"
    )


_TRACKED_PATHS = {
    "amendment_01": (
        "configs/s4_4_data_expansion_amendment_01.v1.json",
        "docs/development/specs/s4_4_data_expansion_amendment_01.md",
        "docs/development/closeouts/S4/s4_4_data_expansion_amendment_01.md",
        "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
        "s4_4_data_expansion_amendment_01",
    ),
    "amendment_02": (
        "configs/s4_4_data_expansion_amendment_02.v1.json",
        "docs/development/specs/s4_4_data_expansion_amendment_02.md",
        "docs/development/closeouts/S4/s4_4_data_expansion_amendment_02.md",
        "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
        "s4_4_data_expansion_amendment_02",
    ),
}
_MACHINE_ROOTS = {
    "amendment_01": Path("dataset/S4.4/amendments/s4_4_data_expansion_amendment_01"),
    "amendment_02": Path("dataset/S4.4/amendments/s4_4_data_expansion_amendment_02"),
}


def _self_hashed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {**payload, field: canonical_sha256(payload)}


def _validate_self_hash(value: Mapping[str, Any], field: str, label: str) -> None:
    supplied = value.get(field)
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise S44AmendmentError(f"{label}: missing self-hash")
    payload = {key: item for key, item in value.items() if key != field}
    if canonical_sha256(payload) != supplied:
        raise S44AmendmentError(f"{label}: self-hash mismatch")


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise S44AmendmentError(f"{label}: expected relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise S44AmendmentError(f"{label}: unsafe path")
    return value


def _file_record(path: Path, repo_root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(repo_root).as_posix(),
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _record_tree_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    encoded = "".join(
        f"{record['sha256']}  {record['path']}\n"
        for record in sorted(records, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tracked_records(repo_root: Path, predecessor: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["git", "ls-files", "--", *_TRACKED_PATHS[predecessor]],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S44AmendmentError(f"cannot enumerate {predecessor} tracked bytes")
    paths = sorted({line for line in result.stdout.splitlines() if line})
    if not paths:
        raise S44AmendmentError(f"{predecessor} tracked record set is empty")
    return [_file_record(repo_root / relative, repo_root) for relative in paths]


def _machine_records(repo_root: Path, predecessor: str) -> list[dict[str, Any]]:
    root = repo_root / _MACHINE_ROOTS[predecessor]
    if not root.is_dir():
        raise S44AmendmentError(f"{predecessor} machine-local root is absent")
    return [
        _file_record(path, repo_root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def load_configuration(path: Path, repo_root: Path) -> dict[str, Any]:
    """Resolve the narrow v3 overlay on the immutable amendment-02 contract."""

    overlay = load_json(path)
    required = {
        "schema",
        "amendment_id",
        "version",
        "status",
        "inherits_config",
        "immutable_predecessors",
        "continuation",
        "inherited_fit_a",
        "prospective_rule_changes",
        "sessions",
        "preflight_required_checks",
        "retention",
    }
    if set(overlay) != required:
        raise S44AmendmentError("amendment_03 config overlay field set invalid")
    inherited = overlay["inherits_config"]
    if not isinstance(inherited, dict) or set(inherited) != {"path", "sha256"}:
        raise S44AmendmentError("amendment_03 inherited config binding invalid")
    relative = _safe_relative(inherited["path"], "inherits_config.path")
    base_path = repo_root / relative
    if not base_path.is_file() or sha256_file(base_path) != inherited["sha256"]:
        raise S44AmendmentError("immutable amendment_02 config changed or is absent")
    base = load_amendment_configuration(base_path, repo_root)
    validate_amendment_02_configuration(base, repo_root)
    resolved = copy.deepcopy(base)
    for key in (
        "schema",
        "amendment_id",
        "version",
        "status",
        "immutable_predecessors",
        "continuation",
        "inherited_fit_a",
        "prospective_rule_changes",
        "sessions",
        "preflight_required_checks",
        "retention",
    ):
        resolved[key] = copy.deepcopy(overlay[key])
    resolved["inherits_config"] = copy.deepcopy(inherited)
    return resolved


def validate_configuration(config: Mapping[str, Any]) -> None:
    if (
        config.get("schema") != CONFIG_SCHEMA
        or config.get("amendment_id") != AMENDMENT_ID
        or config.get("version") != 3
        or config.get("status") != "prospective_precollection"
    ):
        raise S44AmendmentError("amendment_03 identity/version invalid")
    scope = config.get("scope", {})
    if (
        scope.get("phase") != "S4.4"
        or scope.get("planned_fit_takes") != 102
        or scope.get("planned_prospective_holdout_takes") != 47
        or scope.get("planned_total_takes") != 149
        or scope.get("later_phases_started") is not False
    ):
        raise S44AmendmentError("amendment_03 S4.4 scope changed")
    continuation = config.get("continuation", {})
    if continuation != {
        "predecessor_amendment_id": AMENDMENT_02_ID,
        "mode": "prospective_continuation_without_predecessor_mutation",
        "inherit_completed_fit_a": True,
        "inherit_future_fit_b_or_holdout_identities": False,
        "assignments_merged": False,
        "access_histories_merged": False,
        "blindness_claims_merged": False,
    }:
        raise S44AmendmentError("amendment_03 continuation contract invalid")
    calendar = config.get("prospective_rule_changes", {}).get(
        "calendar_day_separation", {}
    )
    if (
        calendar.get("distinct_calendar_dates_required") is not False
        or calendar.get("same_local_calendar_date_permitted") is not True
        or calendar.get("truthful_dates_and_timestamps_required") is not True
        or calendar.get("distinct_session_ids_required") is not True
        or calendar.get("separate_fit_b_and_holdout_preflight_and_readiness_required")
        is not True
    ):
        raise S44AmendmentError("amendment_03 same-day session policy invalid")
    device = config.get("prospective_rule_changes", {}).get("device_state", {})
    for key in (
        "restart_required",
        "reboot_required",
        "power_cycle_required",
        "usb_disconnect_reconnect_required",
        "ssh_reconnect_required",
    ):
        if device.get(key) is not False:
            raise S44AmendmentError(f"amendment_03 unexpectedly requires {key}")
    if (
        device.get("live_connectivity_and_readiness_required") is not True
        or device.get("protocol_only_state_change_forbidden") is not True
    ):
        raise S44AmendmentError("amendment_03 live-readiness policy weakened")
    checks = config.get("preflight_required_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != 12
        or len(set(checks)) != 12
        or "device_restart_or_reconnection" in checks
        or "live_connectivity_and_readiness" not in checks
    ):
        raise S44AmendmentError("amendment_03 preflight check contract invalid")
    sessions = config.get("sessions")
    if not isinstance(sessions, list) or [
        item.get("session_id") for item in sessions
    ] != [
        "fit_a",
        "fit_b",
        "prospective_holdout",
    ]:
        raise S44AmendmentError("amendment_03 session identities invalid")
    if [item.get("logical_cell_count") for item in sessions] != [51, 51, 47]:
        raise S44AmendmentError("amendment_03 logical session counts invalid")
    if [item.get("new_planned_take_count") for item in sessions] != [0, 51, 47]:
        raise S44AmendmentError("amendment_03 future-only counts invalid")
    if any(item.get("same_calendar_date_permitted") is not True for item in sessions):
        raise S44AmendmentError("amendment_03 same-day permission missing")
    retention = config.get("retention", {})
    if (
        not str(retention.get("machine_local_root", "")).endswith(AMENDMENT_ID)
        or not str(retention.get("tracked_evidence_root", "")).endswith(AMENDMENT_ID)
        or retention.get("raw_gitignored") is not True
        or retention.get("private_machine_local_records_gitignored") is not True
        or retention.get("clean_checkout_requires_raw_media") is not False
    ):
        raise S44AmendmentError("amendment_03 retention isolation invalid")


def validate_predecessor_bytes(
    config: Mapping[str, Any], repo_root: Path, *, require_machine_local: bool
) -> dict[str, Any]:
    """Prove immutable amendment-01/02 tracked and optional local byte sets."""

    result: dict[str, Any] = {}
    for predecessor in ("amendment_01", "amendment_02"):
        expected = config["immutable_predecessors"][predecessor]
        tracked = _tracked_records(repo_root, predecessor)
        tracked_tree = _record_tree_sha256(tracked)
        if tracked_tree != expected["tracked_tree_sha256"]:
            raise S44AmendmentError(f"immutable {predecessor} tracked bytes changed")
        entry: dict[str, Any] = {
            "tracked_record_count": len(tracked),
            "tracked_tree_sha256": tracked_tree,
        }
        if require_machine_local:
            machine = _machine_records(repo_root, predecessor)
            machine_tree = _record_tree_sha256(machine)
            if machine_tree != expected["machine_local_tree_sha256"]:
                raise S44AmendmentError(
                    f"immutable {predecessor} machine-local bytes changed"
                )
            entry.update(
                {
                    "machine_local_record_count": len(machine),
                    "machine_local_tree_sha256": machine_tree,
                }
            )
        result[predecessor] = entry
    key_paths = {
        "amendment_01": {
            "precollection_seal_file_sha256": (
                "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
                "s4_4_data_expansion_amendment_01/precollection_seal.v1.json"
            ),
            "no_go_closeout_file_sha256": (
                "outputs/isaac_audio_sensors/S4/S4.4/closures/"
                "s4_4_data_expansion_amendment_01_no_go.v1.json"
            ),
            "no_go_seal_file_sha256": (
                "outputs/isaac_audio_sensors/S4/S4.4/closures/"
                "s4_4_data_expansion_amendment_01_no_go_seal.v1.json"
            ),
        },
        "amendment_02": {
            "precollection_seal_file_sha256": (
                "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
                "s4_4_data_expansion_amendment_02/precollection_seal.v1.json"
            ),
            "fit_a_session_manifest_file_sha256": (
                "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
                "s4_4_data_expansion_amendment_02/manifests/sessions/fit_a.json"
            ),
        },
    }
    for predecessor, bindings in key_paths.items():
        for key, relative in bindings.items():
            if (
                sha256_file(repo_root / relative)
                != config["immutable_predecessors"][predecessor][key]
            ):
                raise S44AmendmentError(f"immutable predecessor binding changed: {key}")
    return result


_IDENTITY_FIELDS = {
    "planned_take_id",
    "predecessor_planned_take_id",
    "successor_planned_take_id",
    "expected_artifact_paths",
    "take_definition_sha256",
    "group_id",
}


def _remap_future_session(
    base_manifest: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    session_id = str(base_manifest["session_id"])
    takes = copy.deepcopy(base_manifest["takes"])
    for sequence, take in enumerate(takes, 1):
        condition_tag = {
            "controlled": "ctl",
            "confidence": "conf",
            "silence": "sil",
            "audio_video": "av",
        }[take["category"]]
        take["planned_take_id"] = f"s44a03_{session_id}_{sequence:03d}_{condition_tag}"
        take["group_id"] = "s44a03_grp_" + canonical_sha256(take["group_identity"])[:20]
    for index, take in enumerate(takes):
        planned_id = take["planned_take_id"]
        take["predecessor_planned_take_id"] = (
            None if index == 0 else takes[index - 1]["planned_take_id"]
        )
        take["successor_planned_take_id"] = (
            None if index == len(takes) - 1 else takes[index + 1]["planned_take_id"]
        )
        root = config["retention"]["attempt_root"]
        attempt_01 = f"{root}/{planned_id}/{planned_id}__attempt_01"
        attempt_02 = f"{root}/{planned_id}/{planned_id}__attempt_02"
        take["expected_artifact_paths"] = {
            "planned_cell_record": f"{root}/{planned_id}/planned_cell.json",
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
    payload = {
        "schema": MANIFEST_SCHEMA,
        "status": "frozen_before_collection",
        "amendment_id": AMENDMENT_ID,
        "partition": base_manifest["partition"],
        "session_id": session_id,
        "session_date_local": None,
        "calendar_policy": "same_local_calendar_date_permitted",
        "separate_session_required": True,
        "planned_take_count": len(takes),
        "takes": takes,
    }
    return _self_hashed(payload, "manifest_sha256")


def build_future_manifests(
    config: Mapping[str, Any], repo_root: Path
) -> dict[str, Any]:
    base_path = repo_root / config["inherits_config"]["path"]
    base = load_amendment_configuration(base_path, repo_root)
    base_manifests = build_amendment_02_manifests(base)
    result = {
        session_id: _remap_future_session(base_manifests[session_id], config)
        for session_id in FUTURE_SESSION_COUNTS
    }
    validate_future_manifests(result, config, base_manifests=base_manifests)
    return result


def validate_future_manifests(
    manifests: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    base_manifests: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    if set(manifests) != set(FUTURE_SESSION_COUNTS):
        raise S44AmendmentError("amendment_03 future manifest set invalid")
    groups: dict[str, set[str]] = defaultdict(set)
    all_ids: set[str] = set()
    for session_id, expected_count in FUTURE_SESSION_COUNTS.items():
        manifest = manifests[session_id]
        _validate_self_hash(manifest, "manifest_sha256", session_id)
        if (
            manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("amendment_id") != AMENDMENT_ID
            or manifest.get("session_id") != session_id
            or manifest.get("planned_take_count") != expected_count
            or manifest.get("session_date_local") is not None
            or manifest.get("calendar_policy") != "same_local_calendar_date_permitted"
            or manifest.get("separate_session_required") is not True
        ):
            raise S44AmendmentError(f"{session_id}: future manifest contract invalid")
        takes = manifest.get("takes")
        if not isinstance(takes, list) or len(takes) != expected_count:
            raise S44AmendmentError(f"{session_id}: future take count invalid")
        for index, take in enumerate(takes, 1):
            planned_id = take.get("planned_take_id")
            if (
                take.get("sequence_index") != index
                or not isinstance(planned_id, str)
                or not planned_id.startswith(f"s44a03_{session_id}_")
                or planned_id in all_ids
            ):
                raise S44AmendmentError(f"{session_id}: future identity invalid")
            all_ids.add(planned_id)
            expected_hash = canonical_sha256(
                {
                    key: value
                    for key, value in take.items()
                    if key != "take_definition_sha256"
                }
            )
            if take.get("take_definition_sha256") != expected_hash:
                raise S44AmendmentError(f"{planned_id}: take hash invalid")
            paths = take.get("expected_artifact_paths", {})
            if not isinstance(paths, dict) or any(
                AMENDMENT_02_ID in str(value) for value in paths.values()
            ):
                raise S44AmendmentError(f"{planned_id}: expected path is not new v3")
            groups[str(take["group_id"])].add(str(take["partition"]))
        if base_manifests is not None:
            original = base_manifests[session_id]["takes"]
            new_science = [
                {
                    key: value
                    for key, value in take.items()
                    if key not in _IDENTITY_FIELDS
                }
                for take in takes
            ]
            old_science = [
                {
                    key: value
                    for key, value in take.items()
                    if key not in _IDENTITY_FIELDS
                }
                for take in original
            ]
            if new_science != old_science:
                raise S44AmendmentError(f"{session_id}: scientific matrix changed")
    if any(len(partitions) != 1 for partitions in groups.values()):
        raise S44AmendmentError("amendment_03 fit/holdout group leakage")


def combined_future_manifest(
    manifests: Mapping[str, Mapping[str, Any]], partition: str
) -> dict[str, Any]:
    selected = [
        value for value in manifests.values() if value["partition"] == partition
    ]
    takes = [take for manifest in selected for take in manifest["takes"]]
    payload = {
        "schema": "ias.s4_4.amendment_03_future_partition_manifest.v1",
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


def _read_checksums(path: Path, root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            raise S44AmendmentError(f"{path}:{number}: malformed checksum")
        digest, relative = line.split("  ", 1)
        candidate = root / _safe_relative(relative, "attempt checksum path")
        if (
            relative in seen
            or not candidate.is_file()
            or sha256_file(candidate) != digest
        ):
            raise S44AmendmentError(f"{path}:{number}: checksum mismatch")
        seen.add(relative)
        records.append({"path": relative, "sha256": digest})
    return records


def build_inherited_fit_a(config: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    inherited = config["inherited_fit_a"]
    manifest_path = repo_root / inherited["session_manifest_path"]
    preflight_path = repo_root / inherited["preflight_path"]
    readiness_path = repo_root / inherited["readiness_path"]
    manifest = load_json(manifest_path)
    preflight = load_json(preflight_path)
    readiness = load_json(readiness_path)
    predecessor = config["immutable_predecessors"]["amendment_02"]
    if (
        sha256_file(manifest_path) != predecessor["fit_a_session_manifest_file_sha256"]
        or manifest.get("manifest_sha256")
        != predecessor["fit_a_session_manifest_payload_sha256"]
        or sha256_file(preflight_path) != predecessor["fit_a_preflight_file_sha256"]
        or preflight.get("preflight_sha256")
        != predecessor["fit_a_preflight_payload_sha256"]
        or sha256_file(readiness_path) != predecessor["fit_a_readiness_file_sha256"]
        or readiness.get("readiness_sha256")
        != predecessor["fit_a_readiness_payload_sha256"]
    ):
        raise S44AmendmentError("amendment_02 inherited Fit A binding changed")
    base_config = load_amendment_configuration(
        repo_root / config["inherits_config"]["path"], repo_root
    )
    validate_amendment_02_readiness(
        readiness,
        base_config,
        precollection_seal_sha256=predecessor["precollection_seal_file_sha256"],
        inherited_preflight_sha256=preflight["preflight_sha256"],
        require_today=False,
    )
    attempt_root = repo_root / inherited["attempt_root"]
    attempts_for_census: list[dict[str, Any]] = []
    logical_cells: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for take in manifest["takes"]:
        planned_id = str(take["planned_take_id"])
        cell_root = attempt_root / planned_id
        planned_path = cell_root / "planned_cell.json"
        if load_json(planned_path) != take:
            raise S44AmendmentError(f"{planned_id}: inherited planned cell changed")
        attempt_records: list[dict[str, Any]] = []
        for attempt_dir in sorted(
            path for path in cell_root.iterdir() if path.is_dir()
        ):
            attempt_manifest_path = attempt_dir / "manifest.json"
            checksum_path = attempt_dir / "SHA256SUMS"
            if not attempt_manifest_path.is_file() or not checksum_path.is_file():
                raise S44AmendmentError(f"{attempt_dir}: retained attempt incomplete")
            attempt = load_json(attempt_manifest_path)
            checksum_records = _read_checksums(checksum_path, attempt_dir)
            attempts_for_census.append(attempt)
            attempt_records.append(
                {
                    "attempt_id": attempt["attempt_id"],
                    "attempt_number": attempt["attempt_number"],
                    "outcome": attempt["outcome"],
                    "replacement": attempt["replacement"],
                    "retained": attempt.get("retained") is True,
                    "manifest_path": attempt_manifest_path.relative_to(
                        repo_root
                    ).as_posix(),
                    "manifest_sha256": sha256_file(attempt_manifest_path),
                    "checksums_path": checksum_path.relative_to(repo_root).as_posix(),
                    "checksums_sha256": sha256_file(checksum_path),
                    "checksummed_artifact_count": len(checksum_records),
                    "additional_attempts_allowed": 0,
                }
            )
        category_counts[str(take["category"])] += 1
        logical_cells.append(
            {
                "sequence_index": take["sequence_index"],
                "planned_take_id": planned_id,
                "category": take["category"],
                "partition": "fit",
                "take_definition_sha256": take["take_definition_sha256"],
                "planned_cell_path": planned_path.relative_to(repo_root).as_posix(),
                "planned_cell_sha256": sha256_file(planned_path),
                "attempts": attempt_records,
                "additional_attempts_allowed": 0,
            }
        )
    base_manifests = build_amendment_02_manifests(base_config)
    census = validate_attempt_census(base_manifests, attempts_for_census)
    if census.get("census_sha256") != predecessor["fit_a_in_progress_census_sha256"]:
        raise S44AmendmentError("amendment_02 inherited census changed")
    expected_categories = inherited["category_counts"]
    if (
        len(logical_cells) != 51
        or len(attempts_for_census) != 52
        or sum(attempt["outcome"] == "valid" for attempt in attempts_for_census) != 51
        or sum(
            attempt["outcome"] in {"invalid", "pre_recording_failure"}
            for attempt in attempts_for_census
        )
        != 1
        or sum(bool(attempt["replacement"]) for attempt in attempts_for_census) != 1
        or dict(category_counts) != expected_categories
    ):
        raise S44AmendmentError("amendment_02 inherited Fit A census invalid")
    by_id = {attempt["attempt_id"]: attempt for attempt in attempts_for_census}
    if (
        by_id[inherited["failed_attempt_id"]]["outcome"] != "invalid"
        or by_id[inherited["replacement_attempt_id"]]["outcome"] != "valid"
        or by_id[inherited["replacement_attempt_id"]]["replacement"] is not True
    ):
        raise S44AmendmentError("inherited Fit A failure/replacement identity changed")
    inventory = _machine_records(repo_root, "amendment_02")
    inventory_tree = _record_tree_sha256(inventory)
    if inventory_tree != predecessor["machine_local_tree_sha256"]:
        raise S44AmendmentError("amendment_02 Fit A file inventory changed")
    payload = {
        "schema": INHERITED_FIT_A_SCHEMA,
        "status": "complete_immutable_inheritance",
        "source_amendment_id": AMENDMENT_02_ID,
        "session_id": "fit_a",
        "session_manifest": {
            "path": inherited["session_manifest_path"],
            "file_sha256": sha256_file(manifest_path),
            "payload_sha256": manifest["manifest_sha256"],
        },
        "preflight": {
            "path": inherited["preflight_path"],
            "file_sha256": sha256_file(preflight_path),
            "payload_sha256": preflight["preflight_sha256"],
            "session_date_local": preflight["session_date_local"],
        },
        "readiness": {
            "path": inherited["readiness_path"],
            "file_sha256": sha256_file(readiness_path),
            "payload_sha256": readiness["readiness_sha256"],
        },
        "census": census,
        "logical_cells": logical_cells,
        "file_inventory": inventory,
        "file_inventory_sha256": canonical_sha256(inventory),
        "file_inventory_sha256sum_tree": inventory_tree,
        "failed_attempt_id": inherited["failed_attempt_id"],
        "replacement_attempt_id": inherited["replacement_attempt_id"],
        "failed_and_replacement_attempts_retained": True,
        "replacement_allowance_reset": False,
        "additional_attempts_allowed_for_inherited_cells": 0,
        "scientific_outcomes_inspected": False,
    }
    return _self_hashed(payload, "inherited_fit_a_sha256")


def validate_inherited_fit_a(
    record: Mapping[str, Any], config: Mapping[str, Any]
) -> None:
    _validate_self_hash(record, "inherited_fit_a_sha256", "inherited Fit A")
    if (
        record.get("schema") != INHERITED_FIT_A_SCHEMA
        or record.get("source_amendment_id") != AMENDMENT_02_ID
        or record.get("session_id") != "fit_a"
        or len(record.get("logical_cells", [])) != 51
        or record.get("replacement_allowance_reset") is not False
        or record.get("additional_attempts_allowed_for_inherited_cells") != 0
        or record.get("scientific_outcomes_inspected") is not False
    ):
        raise S44AmendmentError("inherited Fit A contract invalid")
    census = record.get("census", {})
    if (
        census.get("attempts") != 52
        or census.get("valid_takes") != 51
        or census.get("failures") != 1
        or census.get("replacements") != 1
        or census.get("census_sha256")
        != config["immutable_predecessors"]["amendment_02"][
            "fit_a_in_progress_census_sha256"
        ]
    ):
        raise S44AmendmentError("inherited Fit A census invalid")
    inventory = record.get("file_inventory")
    if not isinstance(inventory, list) or canonical_sha256(inventory) != record.get(
        "file_inventory_sha256"
    ):
        raise S44AmendmentError("inherited Fit A inventory hash invalid")


def build_continuation_reference(
    config: Mapping[str, Any], inherited_fit_a: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema": "ias.s4_4.amendment_continuation_reference.v1",
        "status": "prospective_continuation",
        "predecessor_amendment_id": AMENDMENT_02_ID,
        "continuation_amendment_id": AMENDMENT_ID,
        "predecessor_modified_or_reclassified": False,
        "predecessor_precollection_seal_file_sha256": config["immutable_predecessors"][
            "amendment_02"
        ]["precollection_seal_file_sha256"],
        "inherited_fit_a_sha256": inherited_fit_a["inherited_fit_a_sha256"],
        "inherited_logical_cells": 51,
        "new_fit_b_cells": 51,
        "new_prospective_holdout_cells": 47,
        "future_amendment_02_identities_reused": False,
        "assignments_merged": False,
        "access_histories_merged": False,
        "blindness_claims_merged": False,
    }
    return _self_hashed(payload, "continuation_reference_sha256")


def build_aggregate_index(
    config: Mapping[str, Any],
    inherited_fit_a: Mapping[str, Any],
    fit_b: Mapping[str, Any],
    holdout: Mapping[str, Any],
) -> dict[str, Any]:
    inherited_groups = {
        str(cell["planned_take_id"]): str(cell["partition"])
        for cell in inherited_fit_a["logical_cells"]
    }
    future_groups = {
        str(take["group_id"]): str(take["partition"])
        for manifest in (fit_b, holdout)
        for take in manifest["takes"]
    }
    if any(partition != "fit" for partition in inherited_groups.values()):
        raise S44AmendmentError("inherited Fit A partition changed")
    if set(future_groups) & set(inherited_groups):
        raise S44AmendmentError("inherited/future identity collision")
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "status": "frozen_before_collection",
        "logical_counts": LOGICAL_COUNTS,
        "records": [
            {
                "record_id": "original_s4_4_freeze",
                "role": "historically_analyzed_legacy_evidence",
                "access_history": "dataset/S4.4/access/access_ledger.jsonl",
                "historically_unopened_claim": False,
            },
            {
                "record_id": "s4_4_data_expansion_amendment_01",
                "role": "immutable_historical_no_go_evidence",
                "status": "no_go",
                "access_history_merged": False,
                "blindness_claim_inherited": False,
            },
            {
                "record_id": AMENDMENT_02_ID,
                "role": "immutable_predecessor_with_inherited_complete_fit_a",
                "inherited_fit_a_sha256": inherited_fit_a["inherited_fit_a_sha256"],
                "logical_cell_count": 51,
                "future_fit_b_or_holdout_reused": False,
                "access_history": (
                    "dataset/S4.4/amendments/s4_4_data_expansion_amendment_02/"
                    "access/access_ledger.jsonl"
                ),
                "access_history_merged": False,
                "blindness_claim_inherited": False,
            },
            {
                "record_id": AMENDMENT_ID,
                "role": "prospective_future_fit_b_and_unopened_holdout",
                "fit_b_manifest_sha256": fit_b["manifest_sha256"],
                "prospective_holdout_manifest_sha256": holdout["manifest_sha256"],
                "scientifically_opened": False,
                "access_history": config["retention"]["access_root"]
                + "/access_ledger.jsonl",
            },
        ],
        "assignments_merged": False,
        "access_histories_merged": False,
        "blindness_claims_merged": False,
        "fit_holdout_group_leakage": False,
    }
    return _self_hashed(payload, "aggregate_index_sha256")


def build_precollection_seal(
    *, bindings: Mapping[str, str], checkpoint: Mapping[str, Any] | None
) -> dict[str, Any]:
    if not bindings or any(
        not isinstance(value, str) or len(value) != 64 for value in bindings.values()
    ):
        raise S44AmendmentError("amendment_03 seal bindings invalid")
    payload = {
        "schema": PRECOLLECTION_SEAL_SCHEMA,
        "status": "committed"
        if checkpoint is not None
        else "awaiting_commit_authorization",
        "amendment_id": AMENDMENT_ID,
        "bindings": dict(sorted(bindings.items())),
        "source_checkpoint": checkpoint,
        "collection_allowed": checkpoint is not None,
        "capture_prohibited_until_committed_and_sealed": True,
        "holdout_scientifically_opened": False,
        "s4_5_or_later_started": False,
    }
    return _self_hashed(payload, "seal_payload_sha256")


def validate_precollection_seal(
    seal: Mapping[str, Any], *, repo_root: Path, require_committed: bool
) -> None:
    _validate_self_hash(seal, "seal_payload_sha256", "amendment_03 seal")
    checkpoint = seal.get("source_checkpoint")
    if (
        seal.get("schema") != PRECOLLECTION_SEAL_SCHEMA
        or seal.get("amendment_id") != AMENDMENT_ID
        or seal.get("capture_prohibited_until_committed_and_sealed") is not True
        or seal.get("holdout_scientifically_opened") is not False
        or seal.get("s4_5_or_later_started") is not False
    ):
        raise S44AmendmentError("amendment_03 precollection seal invalid")
    if require_committed:
        if (
            seal.get("status") != "committed"
            or seal.get("collection_allowed") is not True
            or not isinstance(checkpoint, Mapping)
        ):
            raise S44AmendmentError(
                "capture denied: amendment_03 is not committed and sealed"
            )
        validate_source_checkpoint(checkpoint, repo_root)
    elif seal.get("collection_allowed") is not (checkpoint is not None):
        raise S44AmendmentError("amendment_03 seal collection flag inconsistent")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise S44AmendmentError(f"{label}: timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise S44AmendmentError(f"{label}: invalid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise S44AmendmentError(f"{label}: timezone-aware timestamp required")
    return parsed


def validate_session_preflight(
    record: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    other_records: Sequence[Mapping[str, Any]],
) -> None:
    if (
        record.get("schema") != PREFLIGHT_SCHEMA
        or record.get("status") != "passed"
        or record.get("amendment_id") != AMENDMENT_ID
        or record.get("session_id") not in FUTURE_SESSION_COUNTS
    ):
        raise S44AmendmentError("amendment_03 session preflight identity invalid")
    try:
        session_date = date.fromisoformat(str(record.get("session_date_local")))
    except ValueError as exc:
        raise S44AmendmentError("session date must be exact ISO calendar date") from exc
    recorded_at = _parse_timestamp(record.get("recorded_at_local"), "recorded_at_local")
    _parse_timestamp(record.get("collected_at_utc"), "collected_at_utc")
    if recorded_at.date() != session_date:
        raise S44AmendmentError("session date and truthful local timestamp disagree")
    for other in other_records:
        if other.get("session_id") == record.get("session_id") and other.get(
            "session_date_local"
        ) == record.get("session_date_local"):
            raise S44AmendmentError(
                "only one preflight is permitted per session and local-date segment"
            )
    checks = record.get("checks")
    required = set(config["preflight_required_checks"])
    if not isinstance(checks, Mapping) or set(checks) != required:
        raise S44AmendmentError("amendment_03 preflight exact check set mismatch")
    if "device_restart_or_reconnection" in checks or any(
        value != "passed" for value in checks.values()
    ):
        raise S44AmendmentError("amendment_03 preflight contains invalid gate")
    if record.get("identity_contract_sha256") != canonical_sha256(config["identities"]):
        raise S44AmendmentError("amendment_03 preflight identity hash mismatch")
    observations = record.get("observations")
    required_observations = {
        "live_connectivity_and_readiness",
        "mac",
        "respeaker",
        "zed",
        "clocks",
        "room_environment",
        "mount_and_coordinates",
        "privacy",
        "storage",
        "access",
    }
    if not isinstance(observations, Mapping) or not required_observations <= set(
        observations
    ):
        raise S44AmendmentError("amendment_03 preflight observations incomplete")
    live = observations["live_connectivity_and_readiness"]
    if (
        not isinstance(live, Mapping)
        or live.get("protocol_mandated_device_state_change") is not False
    ):
        raise S44AmendmentError("amendment_03 live readiness observation invalid")
    _validate_self_hash(record, "preflight_sha256", "amendment_03 preflight")


def validate_session_readiness(
    record: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    precollection_seal_sha256: str,
    session_preflight: Mapping[str, Any],
    require_today: bool = True,
) -> None:
    if (
        record.get("schema") != READINESS_SCHEMA
        or record.get("status") != "passed"
        or record.get("amendment_id") != AMENDMENT_ID
        or record.get("session_id") != session_preflight.get("session_id")
        or record.get("session_date_local")
        != session_preflight.get("session_date_local")
    ):
        raise S44AmendmentError("amendment_03 readiness identity/status invalid")
    parsed_date = date.fromisoformat(str(record["session_date_local"]))
    if require_today and parsed_date != date.today():
        raise S44AmendmentError("amendment_03 readiness is not for today's date")
    _parse_timestamp(record.get("collected_at_utc"), "readiness collected_at_utc")
    if record.get("precollection_seal_sha256") != precollection_seal_sha256:
        raise S44AmendmentError("amendment_03 readiness seal binding mismatch")
    if record.get("session_preflight_sha256") != session_preflight.get(
        "preflight_sha256"
    ):
        raise S44AmendmentError("amendment_03 readiness preflight binding mismatch")
    checks = record.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != REQUIRED_READINESS_CHECKS:
        raise S44AmendmentError("amendment_03 readiness exact check set mismatch")
    if any(value != "passed" for value in checks.values()):
        raise S44AmendmentError("amendment_03 readiness contains failed checks")
    for field in (
        "attempt_allocated",
        "recorder_started",
        "playback_started",
        "zed_capture_started",
        "media_created",
    ):
        if record.get(field) is not False:
            raise S44AmendmentError("readiness crossed attempt or media boundary")
    _validate_self_hash(record, "readiness_sha256", "amendment_03 readiness")


def validate_future_attempt_census(
    inherited_fit_a: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_inherited_fit_a(
        inherited_fit_a,
        {
            "immutable_predecessors": {
                "amendment_02": {
                    "fit_a_in_progress_census_sha256": inherited_fit_a["census"][
                        "census_sha256"
                    ]
                }
            }
        },
    )
    takes = {
        take["planned_take_id"]: take
        for manifest in manifests.values()
        for take in manifest["takes"]
    }
    by_take: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for attempt in attempts:
        planned_id = attempt.get("planned_take_id")
        attempt_id = attempt.get("attempt_id")
        if (
            planned_id not in takes
            or not isinstance(attempt_id, str)
            or attempt_id in seen
        ):
            raise S44AmendmentError("future attempt references unknown/duplicate cell")
        seen.add(attempt_id)
        number = attempt.get("attempt_number")
        if number not in {1, 2} or attempt_id != f"{planned_id}__attempt_{number:02d}":
            raise S44AmendmentError("future attempt identity invalid")
        if (
            attempt.get("partition") != takes[planned_id]["partition"]
            or attempt.get("session_id") != takes[planned_id]["session_id"]
            or attempt.get("take_definition_sha256")
            != takes[planned_id]["take_definition_sha256"]
        ):
            raise S44AmendmentError("future replacement changed frozen condition")
        if attempt.get("scientific_outcome_used_for_replacement") is not False:
            raise S44AmendmentError("scientific outcome cannot drive replacement")
        by_take[str(planned_id)].append(attempt)
    future_valid = future_failures = future_replacements = 0
    second_failure = False
    for planned_id, records in by_take.items():
        ordered = sorted(records, key=lambda item: int(item["attempt_number"]))
        if [item["attempt_number"] for item in ordered] != list(
            range(1, len(ordered) + 1)
        ) or len(ordered) > 2:
            raise S44AmendmentError(f"{planned_id}: future attempt sequence invalid")
        outcomes = [item.get("outcome") for item in ordered]
        if any(
            value not in {"planned", "pre_recording_failure", "invalid", "valid"}
            for value in outcomes
        ):
            raise S44AmendmentError("future attempt outcome invalid")
        if len(ordered) == 2:
            future_replacements += 1
            if outcomes[0] not in {"pre_recording_failure", "invalid"}:
                raise S44AmendmentError("future replacement lacks retained failure")
        future_failures += sum(
            outcome in {"pre_recording_failure", "invalid"} for outcome in outcomes
        )
        if "valid" in outcomes:
            if outcomes[-1] != "valid":
                raise S44AmendmentError("future attempt follows valid take")
            future_valid += 1
        if len(outcomes) == 2 and outcomes[-1] in {"pre_recording_failure", "invalid"}:
            second_failure = True
    valid = 51 + future_valid
    payload = {
        "schema": "ias.s4_4.amendment_03_attempt_census.v1",
        "status": "no_go"
        if second_failure
        else "passed"
        if valid == 149
        else "incomplete",
        "logical_planned_cells": 149,
        "inherited_fit_a": {
            "logical_cells": 51,
            "attempts": 52,
            "valid_cells": 51,
            "failures": 1,
            "replacements": 1,
        },
        "future_attempts": len(attempts),
        "attempts_total": 52 + len(attempts),
        "valid_cells_total": valid,
        "failures_total": 1 + future_failures,
        "replacements_total": 1 + future_replacements,
        "incomplete_logical_cells": 149 - valid,
        "inherited_replacement_allowance_reset": False,
        "all_attempts_retained": True,
        "second_failure_present": second_failure,
    }
    return _self_hashed(payload, "census_sha256")
