#!/usr/bin/env python3
"""Run amendment session readiness before any planned-cell attempt is allocated."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    REQUIRED_READINESS_CHECKS,
    S44AmendmentError,
    canonical_sha256,
    load_amendment_configuration,
    load_json,
    sha256_file,
    validate_configuration,
    validate_precollection_seal,
    validate_session_preflight,
    validate_session_readiness,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
NETWORK_CONFIRMATION = "I_CONFIRM_EXTERNAL_NETWORK_PERMISSION"


def _run(argv: list[str], *, timeout: float = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(  # noqa: S603 - frozen helper/read-only probes
            argv,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "return_code": None,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "timed_out": True,
            "execution_error": None,
        }
    except OSError as exc:
        return {
            "argv": argv,
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "execution_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "argv": argv,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": False,
        "execution_error": None,
    }


def _json_observation(argv: list[str], *, timeout: float = 60) -> dict[str, Any]:
    observation = _run(argv, timeout=timeout)
    try:
        payload = json.loads(observation["stdout"])
    except json.JSONDecodeError:
        payload = None
    return {**observation, "payload": payload}


def _mac_full_passed(report: object, inherited: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False
    checks = report.get("frozen_checks")
    if not isinstance(checks, dict):
        return False
    allowed_operator_authority = {"work_focus_active", "notifications_suppressed"}
    if any(
        value is not True
        for key, value in checks.items()
        if key not in allowed_operator_authority
    ):
        return False
    mac = inherited.get("observations", {}).get("mac", {})
    return all(
        mac.get(field) is True
        for field in (
            "work_focus_active_operator_confirmed",
            "notifications_suppressed_operator_confirmed",
        )
    )


def _dynamic_passed(report: object) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("status") == "passed"
        and isinstance(report.get("checks"), dict)
        and report["checks"]
        and all(report["checks"].values())
    )


def _pi_passed(report: object, *, local_helper_sha256: str) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("schema") == "ias.s4_2.pi_preflight.v1"
        and report.get("status") == "passed"
        and report.get("read_only_no_media") is True
        and report.get("helper_sha256") == local_helper_sha256
        and isinstance(report.get("checks"), dict)
        and report["checks"]
        and all(report["checks"].values())
    )


def _zed_passed(report: object) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("status") == "passed"
        and isinstance(report.get("checks"), dict)
        and report["checks"]
        and all(report["checks"].values())
    )


def _gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = args.config.resolve()
    config = load_amendment_configuration(config_path, ROOT)
    validate_configuration(config, ROOT)
    if int(config["version"]) != 2:
        raise S44AmendmentError("pre-attempt readiness is required for amendment_02")
    if args.network_permission_confirmation != NETWORK_CONFIRMATION:
        raise S44AmendmentError("external-network permission confirmation absent")
    evidence_root = ROOT / config["retention"]["tracked_evidence_root"]
    seal_path = evidence_root / "precollection_seal.v1.json"
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    seal_sha256 = sha256_file(seal_path)
    if seal_sha256 != args.expected_precollection_seal_sha256:
        raise S44AmendmentError("amendment_02 seal hash mismatch")
    inherited = load_json(args.inherited_preflight)
    validate_session_preflight(inherited, config, other_dates=[])
    if inherited.get("session_id") != args.session_id:
        raise S44AmendmentError("inherited preflight session mismatch")
    if inherited.get("session_date_local") != date.today().isoformat():
        raise S44AmendmentError("inherited preflight is not for today")

    identities = config["identities"]
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
    pi_output_root = f"S4.4/amendments/{config['amendment_id']}/captures"
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
    dates_pass = (
        mac_date["return_code"] == 0
        and pi_date["return_code"] == 0
        and mac_date["stdout"].strip() == local_date
        and pi_date["stdout"].strip() == local_date
    )
    inherited_observations = inherited.get("observations", {})
    privacy = inherited_observations.get("privacy", {})
    room = inherited_observations.get("room_environment", {})
    privacy_pass = bool(
        privacy.get("no_person_private_screen_credential_or_private_label_in_recordings")
        and room.get("operator_will_remain_outside_retained_camera_frames")
    )
    machine_root = Path(config["retention"]["machine_local_root"])
    access_policy = evidence_root / "access_policy.v1.json"
    output_access_pass = _gitignored(machine_root) and access_policy.is_file()
    local_helper_sha256 = sha256_file(ROOT / "scripts/s4_2_pi_capture.py")
    checks_bool = {
        "network_permission_confirmed": True,
        "mac_ssh_connectivity": mac_connectivity["return_code"] == 0,
        "mac_full_preflight_json": isinstance(mac_full["payload"], dict),
        "mac_dynamic_preflight_json": _dynamic_passed(mac_dynamic["payload"]),
        "mac_identity_volume_mute_power_and_reference": _mac_full_passed(
            mac_full["payload"], inherited
        ),
        "pi_ssh_connectivity": pi_connectivity["return_code"] == 0,
        "pi_nonrecording_preflight_json": isinstance(pi_preflight["payload"], dict),
        "pi_identity_device_format_disk_and_output": _pi_passed(
            pi_preflight["payload"], local_helper_sha256=local_helper_sha256
        ),
        "zed_nonrecording_preflight": _zed_passed(zed["payload"]),
        "clocks": dates_pass,
        "privacy_and_environment": privacy_pass,
        "output_and_access_paths": output_access_pass,
    }
    if set(checks_bool) != REQUIRED_READINESS_CHECKS:
        raise AssertionError("readiness implementation/check contract drift")
    passed = all(checks_bool.values())
    payload = {
        "schema": "ias.s4_4.amendment_session_readiness.v1",
        "status": "passed" if passed else "failed",
        "amendment_id": config["amendment_id"],
        "session_id": args.session_id,
        "session_date_local": local_date,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "precollection_seal_sha256": seal_sha256,
        "inherited_preflight_path": args.inherited_preflight.resolve()
        .relative_to(ROOT)
        .as_posix(),
        "inherited_preflight_sha256": inherited["preflight_sha256"],
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
            "zed_preflight": zed,
            "mac_date": mac_date,
            "pi_date": pi_date,
            "local_pi_helper_sha256": local_helper_sha256,
        },
        "attempt_allocated": False,
        "recorder_started": False,
        "media_created": False,
        "failure_retention_class": (
            None if passed else "session_preflight_failure_not_planned_cell_attempt"
        ),
    }
    record = {**payload, "readiness_sha256": canonical_sha256(payload)}
    session_root = ROOT / config["retention"]["session_root"] / args.session_id
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
            inherited_preflight_sha256=inherited["preflight_sha256"],
        )
    return {
        "status": record["status"],
        "readiness_path": destination.relative_to(ROOT).as_posix(),
        "readiness_sha256": record["readiness_sha256"],
        "attempt_allocated": False,
        "recorder_started": False,
        "media_created": False,
        "failed_checks": sorted(key for key, value in checks_bool.items() if not value),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--session-id", choices=("fit_a", "fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--inherited-preflight", type=Path, required=True)
    parser.add_argument("--expected-precollection-seal-sha256", required=True)
    parser.add_argument("--network-permission-confirmation", required=True)
    parser.add_argument("--zed-python", default="/usr/bin/python3")
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment readiness failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
