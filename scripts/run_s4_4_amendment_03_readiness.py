#!/usr/bin/env python3
"""Run amendment-03 live checks before any future attempt allocation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import load_json, sha256_file
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    READINESS_SCHEMA,
    REQUIRED_READINESS_CHECKS,
    S44AmendmentError,
    active_precollection_package,
    canonical_sha256,
    load_configuration,
    validate_configuration,
    validate_precollection_seal,
    validate_session_preflight,
    validate_session_readiness,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic
from scripts.run_s4_4_amendment_readiness import (
    _json_observation,
    _pi_passed,
    _run,
    _zed_passed,
)
from scripts.validate_s4_4_amendment_03 import require_capture_ready_package

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
NETWORK_CONFIRMATION = "I_CONFIRM_EXTERNAL_NETWORK_PERMISSION"


def _next_unallocated_attempt_id(
    manifest: dict[str, Any], attempt_root: Path
) -> str:
    """Resolve the next attempt without creating an attempt directory."""

    for take in manifest["takes"]:
        planned_id = take["planned_take_id"]
        planned_root = attempt_root / planned_id
        attempt_dirs = (
            sorted(path for path in planned_root.iterdir() if path.is_dir())
            if planned_root.is_dir()
            else []
        )
        expected_names = [
            f"{planned_id}__attempt_{number:02d}"
            for number in range(1, len(attempt_dirs) + 1)
        ]
        if [path.name for path in attempt_dirs] != expected_names:
            raise S44AmendmentError(
                f"{planned_id}: retained attempt sequence is malformed"
            )
        if not attempt_dirs:
            return f"{planned_id}__attempt_01"
        outcomes = [
            load_json(path / "manifest.json").get("outcome") for path in attempt_dirs
        ]
        if outcomes[-1] == "valid":
            continue
        if outcomes == ["pre_recording_failure"] or outcomes == ["invalid"]:
            return f"{planned_id}__attempt_02"
        if outcomes == ["planned"]:
            raise S44AmendmentError(
                f"{planned_id}: attempt already allocated before readiness"
            )
        if len(outcomes) == 2 and outcomes[-1] in {
            "pre_recording_failure",
            "invalid",
        }:
            raise S44AmendmentError(f"{planned_id}: replacement allowance exhausted")
        raise S44AmendmentError(f"{planned_id}: retained attempt outcome is malformed")
    raise S44AmendmentError(f"{manifest['session_id']}: session is already complete")


def _gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _operator_observations_pass(
    preflight: dict[str, Any], config: dict[str, Any]
) -> bool:
    observations = preflight.get("observations", {})
    live = observations.get("live_connectivity_and_readiness", {})
    mac = observations.get("mac", {})
    room = observations.get("room_environment", {})
    mount = observations.get("mount_and_coordinates", {})
    privacy = observations.get("privacy", {})
    storage = observations.get("storage", {})
    access = observations.get("access", {})
    return bool(
        live.get("protocol_mandated_device_state_change") is False
        and mac.get("keyboard_plane") == "level"
        and mac.get("lid_angle_deg") == 90
        and mac.get("work_focus_active_operator_confirmed") is True
        and mac.get("notifications_suppressed_operator_confirmed") is True
        and room.get("canonical_room_id") == config["identities"]["room_id"]
        and room.get("operator_will_remain_outside_retained_camera_frames") is True
        and mount.get("fixture_id") == config["identities"]["fixture_id"]
        and mount.get("project_frame") == config["identities"]["project_frame"]
        and mount.get("marked_origin_and_axes_unchanged_operator_confirmed") is True
        and mount.get("room_bounds_verified") is True
        and privacy.get(
            "no_person_private_screen_credential_or_private_label_in_recordings"
        )
        is True
        and storage.get("output_root_gitignored") is True
        and access.get("prospective_holdout_scientifically_opened") is False
    )


def _truthful_power_state(report: dict[str, Any]) -> bool:
    power = report.get("power")
    if not isinstance(power, dict):
        return False
    battery_percent = power.get("battery_percent")
    return bool(
        power.get("status") == "collected"
        and power.get("source") in {"AC Power", "Battery Power"}
        and isinstance(power.get("on_ac_power"), bool)
        and isinstance(power.get("charging"), bool)
        and isinstance(battery_percent, int)
        and not isinstance(battery_percent, bool)
        and 0 <= battery_percent <= 100
    )


def _mac_full_passed_03(report: object, preflight: dict[str, Any]) -> bool:
    if not isinstance(report, dict) or not _truthful_power_state(report):
        return False
    checks = report.get("frozen_checks")
    if not isinstance(checks, dict):
        return False
    allowed_non_gate_fields = {
        "ac_power",
        "work_focus_active",
        "notifications_suppressed",
    }
    if any(
        value is not True
        for key, value in checks.items()
        if key not in allowed_non_gate_fields
    ):
        return False
    mac = preflight.get("observations", {}).get("mac", {})
    return all(
        mac.get(field) is True
        for field in (
            "work_focus_active_operator_confirmed",
            "notifications_suppressed_operator_confirmed",
        )
    )


def _dynamic_passed_03(report: object) -> bool:
    if not isinstance(report, dict) or not _truthful_power_state(report):
        return False
    checks = report.get("checks")
    return bool(
        isinstance(checks, dict)
        and checks
        and all(value is True for key, value in checks.items() if key != "ac_power")
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_configuration(args.config.resolve(), ROOT)
    validate_configuration(config)
    if args.network_permission_confirmation != NETWORK_CONFIRMATION:
        raise S44AmendmentError("external-network permission confirmation absent")
    evidence_root = ROOT / config["retention"]["tracked_evidence_root"]
    index_path, seal_path = active_precollection_package(evidence_root)
    require_capture_ready_package(
        index_path,
        repo_root=ROOT,
        config_path=args.config.resolve(),
    )
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    seal_sha256 = sha256_file(seal_path)
    if seal_sha256 != args.expected_precollection_seal_sha256:
        raise S44AmendmentError("amendment_03 precollection seal hash mismatch")
    preflight = load_json(args.session_preflight)
    session_root = ROOT / config["retention"]["session_root"]
    other_records = [
        load_json(path)
        for path in sorted(session_root.rglob("preflight.json"))
        if path.resolve() != args.session_preflight.resolve()
    ]
    validate_session_preflight(preflight, config, other_records=other_records)
    if preflight.get("session_id") != args.session_id:
        raise S44AmendmentError("amendment_03 preflight/session mismatch")
    if preflight.get("session_date_local") != date.today().isoformat():
        raise S44AmendmentError("amendment_03 preflight is not for today")

    identities = config["identities"]
    manifest = load_json(evidence_root / f"manifests/sessions/{args.session_id}.json")
    attempt_root = ROOT / config["retention"]["attempt_root"]
    expected_next_attempt_id = _next_unallocated_attempt_id(manifest, attempt_root)
    mac_alias = identities["mac"]["ssh_alias"]
    pi_alias = "elab-raspberrypi5"
    mac_connectivity = _run(["ssh", mac_alias, "/usr/bin/true"], timeout=20)
    pi_connectivity = _run(["ssh", pi_alias, "/usr/bin/true"], timeout=20)
    mac_full = _json_observation(
        [
            "ssh",
            mac_alias,
            "/usr/bin/python3",
            "S4.2/bin/s4_2_mac_preflight.py",
            "--wav",
            identities["reference_wav"]["mac_path"],
            "--expected-sha256",
            identities["reference_wav"]["sha256"],
            "--expected-volume-percent",
            str(identities["mac"]["system_volume_percent"]),
        ]
    )
    mac_dynamic = _json_observation(
        [
            "ssh",
            mac_alias,
            "/usr/bin/python3",
            "S4.2/bin/s4_2_mac_preflight.py",
            "--dynamic-only",
            "--expected-volume-percent",
            str(identities["mac"]["system_volume_percent"]),
        ]
    )
    pi_output_root = (
        f"S4.4/amendments/{config['amendment_id']}/captures/"
        f"{expected_next_attempt_id}"
    )
    pi_preflight = _json_observation(
        [
            "ssh",
            pi_alias,
            "/usr/bin/python3",
            "S4.2/bin/s4_2_pi_capture.py",
            "preflight",
            "--output-root",
            pi_output_root,
            "--device",
            identities["respeaker"]["device"],
            "--minimum-free-bytes",
            "1073741824",
        ]
    )
    zed = _json_observation(
        [
            args.zed_python,
            "scripts/preflight_s4_2_zed.py",
            "--expected-serial",
            identities["zed"]["serial"],
            "--expected-sdk",
            identities["zed"]["sdk_version_reference"],
            "--expected-camera-firmware",
            identities["zed"]["camera_firmware_reference"],
            "--expected-sensor-firmware",
            identities["zed"]["sensor_firmware_reference"],
            "--minimum-usb-speed-mbps",
            "5000",
        ],
        timeout=90,
    )
    local_date = date.today().isoformat()
    mac_date = _run(["ssh", mac_alias, "/bin/date", "+%Y-%m-%d"], timeout=20)
    pi_date = _run(["ssh", pi_alias, "/bin/date", "+%Y-%m-%d"], timeout=20)
    dates_pass = bool(
        mac_date["return_code"] == 0
        and pi_date["return_code"] == 0
        and mac_date["stdout"].strip() == local_date
        and pi_date["stdout"].strip() == local_date
        and preflight["session_date_local"] == local_date
    )
    local_helper_sha256 = sha256_file(ROOT / "scripts/s4_2_pi_capture.py")
    pi_payload = pi_preflight.get("payload")
    pi_contract_pass = bool(
        isinstance(pi_payload, dict)
        and pi_payload.get("capture_contract", {}).get("record_subcommand") == "record"
        and pi_payload.get("capture_contract", {}).get("required_arguments")
        == ["--attempt", "--device", "--duration", "--minimum-free-bytes"]
    )
    machine_root = Path(config["retention"]["machine_local_root"])
    access_policy_path = evidence_root / "access_policy.v1.json"
    access_policy = load_json(access_policy_path)
    ledger_path = ROOT / config["retention"]["access_root"] / "access_ledger.jsonl"
    path_pass = bool(
        _gitignored(machine_root)
        and access_policy.get("future_S4.7_or_S4.8_opening_workflow_implemented")
        is False
    )
    ledger_pass = bool(
        access_policy.get("precollection_access_ledger_state")
        == "absent_until_holdout_seal"
        and not ledger_path.exists()
    )
    operator_pass = _operator_observations_pass(preflight, config)
    checks_bool = {
        "network_permission_confirmed": True,
        "mac_ssh_connectivity": mac_connectivity["return_code"] == 0,
        "mac_full_preflight_json": isinstance(mac_full.get("payload"), dict),
        "mac_dynamic_preflight_json": _dynamic_passed_03(
            mac_dynamic.get("payload")
        ),
        "mac_identity_volume_mute_power_reference_keyboard_and_lid": (
            _mac_full_passed_03(mac_full.get("payload"), preflight)
            and operator_pass
        ),
        "pi_ssh_connectivity": pi_connectivity["return_code"] == 0,
        "pi_helper_and_record_command_contract": pi_contract_pass,
        "respeaker_identity_device_format_channel_health_disk_and_output": _pi_passed(
            pi_payload, local_helper_sha256=local_helper_sha256
        ),
        "zed_identity_and_readiness": _zed_passed(zed.get("payload")),
        "clocks_and_truthful_session_timestamps": dates_pass,
        "room_environment_mount_frame_origin_and_bounds": operator_pass,
        "privacy": operator_pass,
        "gitignore_and_output_paths": path_pass,
        "access_policy_and_ledger_state": ledger_pass,
    }
    if set(checks_bool) != REQUIRED_READINESS_CHECKS:
        raise AssertionError("amendment_03 readiness/check contract drift")
    passed = all(checks_bool.values())
    payload = {
        "schema": READINESS_SCHEMA,
        "status": "passed" if passed else "failed",
        "amendment_id": config["amendment_id"],
        "session_id": args.session_id,
        "session_date_local": local_date,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "precollection_seal_sha256": seal_sha256,
        "session_preflight_path": args.session_preflight.resolve()
        .relative_to(ROOT)
        .as_posix(),
        "session_preflight_sha256": preflight["preflight_sha256"],
        "expected_next_attempt_id": expected_next_attempt_id,
        "checks": {
            key: "passed" if value else "failed"
            for key, value in sorted(checks_bool.items())
        },
        "observations": {
            "mac_connectivity": mac_connectivity,
            "mac_full_preflight": mac_full,
            "mac_dynamic_preflight": mac_dynamic,
            "pi_connectivity": pi_connectivity,
            "pi_preflight": pi_preflight,
            "pi_output_root_probed": pi_output_root,
            "zed_preflight": zed,
            "mac_date": mac_date,
            "pi_date": pi_date,
            "local_pi_helper_sha256": local_helper_sha256,
            "protocol_mandated_device_state_change": False,
        },
        "attempt_allocated": False,
        "recorder_started": False,
        "playback_started": False,
        "zed_capture_started": False,
        "media_created": False,
        "failure_retention_class": (
            None if passed else "session_readiness_failure_not_planned_cell_attempt"
        ),
    }
    record = {**payload, "readiness_sha256": canonical_sha256(payload)}
    session_root = args.session_preflight.resolve().parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = (
        session_root / "readiness" / f"readiness_{stamp}.json"
        if passed
        else session_root / "readiness_failures" / f"readiness_{stamp}.json"
    )
    write_json_atomic(destination, record)
    if passed:
        validate_session_readiness(
            record,
            config,
            precollection_seal_sha256=seal_sha256,
            session_preflight=preflight,
        )
    return {
        "status": record["status"],
        "readiness_path": destination.relative_to(ROOT).as_posix(),
        "readiness_sha256": record["readiness_sha256"],
        "expected_next_attempt_id": expected_next_attempt_id,
        "attempt_allocated": False,
        "recorder_started": False,
        "playback_started": False,
        "zed_capture_started": False,
        "media_created": False,
        "protocol_mandated_device_state_change": False,
        "failed_checks": sorted(key for key, value in checks_bool.items() if not value),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--session-id", choices=("fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--session-preflight", type=Path, required=True)
    parser.add_argument("--expected-precollection-seal-sha256", required=True)
    parser.add_argument("--network-permission-confirmation", required=True)
    parser.add_argument("--zed-python", default="/usr/bin/python3")
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment-03 readiness failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
