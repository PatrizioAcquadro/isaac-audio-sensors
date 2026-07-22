#!/usr/bin/env python3
"""Prepare one committed, preregistered S4.4 amendment attempt.

The command stops at the operator/capture boundary after emitting an exact plan.
The existing S4.2/S4.3 producers remain the capture implementation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    build_attempt_contract,
    canonical_sha256,
    load_json,
    sha256_file,
    validate_precollection_seal,
    validate_session_preflight,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
EVIDENCE_ROOT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments" / AMENDMENT_ID
CONFIG_PATH = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"


def _find_take(manifest: dict[str, Any], planned_id: str) -> dict[str, Any]:
    matches = [
        take for take in manifest["takes"] if take["planned_take_id"] == planned_id
    ]
    if len(matches) != 1:
        raise S44AmendmentError(f"planned take is not unique: {planned_id}")
    return matches[0]


def _latest_outcome(root: Path, planned_id: str) -> str | None:
    cell = root / planned_id
    manifests = sorted(cell.glob("*/manifest.json")) if cell.is_dir() else []
    if not manifests:
        return None
    return str(load_json(manifests[-1]).get("outcome"))


def _require_sequence(take: dict[str, Any], attempt_root: Path) -> None:
    predecessor = take["predecessor_planned_take_id"]
    if (
        predecessor is not None
        and _latest_outcome(attempt_root, predecessor) != "valid"
    ):
        raise S44AmendmentError(
            f"capture denied: predecessor {predecessor} is not technically valid"
        )
    existing = _latest_outcome(attempt_root, take["planned_take_id"])
    if existing == "valid":
        raise S44AmendmentError("capture denied: planned cell is already valid")


def _validate_recorded_placement(
    args: argparse.Namespace, take: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    category = take["category"]
    position = args.recorded_position
    if category == "silence":
        if (
            position is not None
            or args.recorded_bearing is not None
            or args.recorded_distance is not None
        ):
            raise S44AmendmentError(
                "silence does not accept fabricated source placement"
            )
        return {
            "recorded_position_m_f_project": None,
            "recorded_bearing_deg_f_project": None,
            "recorded_distance_m": None,
            "recording_basis": "not_applicable_silence",
        }
    if position is None:
        raise S44AmendmentError("exact recorded source position is required")
    for value, axis in zip(position, ("x", "y", "z"), strict=True):
        low, high = config["room_bounds_m"][axis]
        if not math.isfinite(value) or not low <= value <= high:
            raise S44AmendmentError(f"recorded position {axis} is outside room bounds")
    if category in {"controlled", "confidence"} and (
        args.recorded_bearing is None
        or args.recorded_distance is None
        or not args.reposition_confirmed
    ):
        raise S44AmendmentError(
            "controlled/confidence capture requires exact bearing, distance, "
            "and fresh reposition confirmation"
        )
    return {
        "recorded_position_m_f_project": position,
        "recorded_bearing_deg_f_project": args.recorded_bearing,
        "recorded_distance_m": args.recorded_distance,
        "recording_basis": args.placement_basis,
        "complete_removal_and_fresh_reposition_confirmed": args.reposition_confirmed,
    }


def _capture_plan(
    take: dict[str, Any], config: dict[str, Any], attempt_dir: Path
) -> dict[str, Any]:
    duration = int(take["duration_s"])
    pi_remote = f"S4.4/amendments/{AMENDMENT_ID}/{take['planned_take_id']}"
    commands: dict[str, Any] = {
        "respeaker": [
            "ssh",
            "elab-raspberrypi5",
            "/usr/bin/python3",
            "S4.2/bin/s4_2_pi_capture.py",
            "--attempt",
            pi_remote,
            "--duration",
            str(duration),
            "--device",
            config["identities"]["respeaker"]["device"],
        ],
        "mac_dynamic_preflight": [
            "ssh",
            config["identities"]["mac"]["ssh_alias"],
            "/usr/bin/python3",
            "S4.2/bin/s4_2_mac_preflight.py",
            "--dynamic-only",
            "--expected-volume-percent",
            "40",
        ],
        "reference_playback": (
            [
                "ssh",
                config["identities"]["mac"]["ssh_alias"],
                "/usr/bin/afplay",
                "-v",
                str(take["playback_gain"]),
                config["identities"]["reference_wav"]["mac_path"],
            ]
            if take["category"] in {"controlled", "confidence"}
            else None
        ),
        "zed": None,
    }
    if take["zed_required"]:
        zed = config["identities"]["zed"]
        commands["zed"] = [
            str(ROOT / ".venv/bin/python"),
            "scripts/run_s4_2_zed_capture.py",
            "--duration",
            str(duration),
            "--output-dir",
            str(attempt_dir / "_producer/zed"),
            "--expected-serial",
            zed["serial"],
            "--expected-sdk",
            zed["sdk_version_reference"],
            "--expected-camera-firmware",
            zed["camera_firmware_reference"],
            "--expected-sensor-firmware",
            zed["sensor_firmware_reference"],
            "--version-policy",
            "metadata",
            "--resolution",
            "HD720",
            "--fps",
            "30",
            "--depth-mode",
            "PERFORMANCE",
            "--minimum-usb-speed-mbps",
            "480",
        ]
    return {
        "schema": "ias.s4_4.amendment_capture_plan.v1",
        "status": "awaiting_physical_operator_action",
        "reuse": [
            "scripts/s4_2_pi_capture.py",
            "scripts/s4_2_mac_preflight.py",
            "scripts/run_s4_2_zed_capture.py",
            "scripts/validate_s4_2_zed_svo.py",
            "S4.2/S4.3 lead-in_tail_playback_sync_safety_and_finalization",
        ],
        "commands": commands,
        "operator_actions": {
            "preflight_complete": True,
            "target_position_m_f_project": take["target_position_m_f_project"],
            "target_bearing_deg_f_project": take["target_bearing_deg_f_project"],
            "target_radius_m": take["target_radius_m"],
            "mac_volume_percent": take.get("mac_system_volume_percent"),
            "fresh_reposition_required": take[
                "complete_removal_and_fresh_reposition_required"
            ],
            "impact_target_elapsed_times_s": take.get("impact_target_elapsed_times_s"),
        },
        "automatic_execution_performed": False,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    seal_path = EVIDENCE_ROOT / "precollection_seal.v1.json"
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    manifest = load_json(EVIDENCE_ROOT / f"manifests/sessions/{args.session_id}.json")
    take = _find_take(manifest, args.planned_take_id)
    if take["session_id"] != args.session_id:
        raise S44AmendmentError("planned take/session mismatch")
    preflight = load_json(args.preflight)
    other_dates: list[str] = []
    session_root = ROOT / config["retention"]["session_root"]
    for path in session_root.glob("*/preflight.json"):
        if path.resolve() != args.preflight.resolve():
            value = load_json(path).get("session_date_local")
            if isinstance(value, str):
                other_dates.append(value)
    validate_session_preflight(preflight, config, other_dates=other_dates)
    if preflight["session_id"] != args.session_id:
        raise S44AmendmentError("preflight/session mismatch")
    attempt_root = ROOT / config["retention"]["attempt_root"]
    _require_sequence(take, attempt_root)
    placement = _validate_recorded_placement(args, take, config)
    contract = build_attempt_contract(
        take,
        attempt_number=args.attempt_number,
        precollection_seal_sha256=sha256_file(seal_path),
    )
    attempt_dir = attempt_root / take["planned_take_id"] / contract["attempt_id"]
    if attempt_dir.exists():
        raise S44AmendmentError(f"attempt path already exists: {attempt_dir}")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    write_json_atomic(attempt_dir.parent / "planned_cell.json", take)
    write_json_atomic(
        attempt_dir / "attempt_contract.json",
        {
            **contract,
            "session_preflight_sha256": preflight["preflight_sha256"],
            "placement": placement,
        },
    )
    if args.pre_recording_failure is not None:
        manifest_payload = {
            **contract,
            "outcome": "pre_recording_failure",
            "technical_failure_reason": args.pre_recording_failure,
            "retained": True,
            "recorder_started": False,
        }
        write_json_atomic(attempt_dir / "manifest.json", manifest_payload)
        return {
            "status": "pre_recording_failure_retained",
            "attempt_id": contract["attempt_id"],
            "attempt_root": attempt_dir.relative_to(ROOT).as_posix(),
            "replacement_allowed": args.attempt_number == 1,
        }
    plan = _capture_plan(take, config, attempt_dir)
    write_json_atomic(attempt_dir / "capture_plan.json", plan)
    write_json_atomic(
        attempt_dir / "manifest.json",
        {
            **contract,
            "outcome": "planned",
            "technical_failure_reason": None,
            "retained": True,
            "recorder_started": False,
            "capture_plan_sha256": canonical_sha256(plan),
        },
    )
    return {
        "status": "awaiting_physical_operator_action",
        "attempt_id": contract["attempt_id"],
        "attempt_root": attempt_dir.relative_to(ROOT).as_posix(),
        "capture_plan": plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session-id", choices=("fit_a", "fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--planned-take-id", required=True)
    parser.add_argument("--attempt-number", type=int, choices=(1, 2), required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--recorded-position", type=float, nargs=3)
    parser.add_argument("--recorded-bearing", type=float)
    parser.add_argument("--recorded-distance", type=float)
    parser.add_argument("--placement-basis", default="operator_recorded_measurement")
    parser.add_argument("--reposition-confirmed", action="store_true")
    parser.add_argument("--pre-recording-failure")
    args = parser.parse_args()
    try:
        result = prepare(args)
    except (OSError, S44AmendmentError, ValueError) as exc:
        print(f"S4.4 amendment attempt preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "awaiting_physical_operator_action" else 2


if __name__ == "__main__":
    raise SystemExit(main())
