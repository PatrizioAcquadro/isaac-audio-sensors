#!/usr/bin/env python3
"""Allocate one future amendment-03 attempt after every pre-attempt gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    build_attempt_contract,
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    S44AmendmentError,
    load_configuration,
    validate_configuration,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_session_preflight,
    validate_session_readiness,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic
from scripts.run_s4_4_amendment_take import (
    _capture_plan,
    _find_take,
    _require_attempt_number,
    _require_sequence,
    _validate_recorded_placement,
)
from scripts.validate_s4_4_amendment_03 import require_capture_ready_package

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"


def _capture_plan_03(
    take: dict[str, Any], config: dict[str, Any], attempt_dir: Path
) -> dict[str, Any]:
    plan = _capture_plan(take, config, attempt_dir)
    plan["commands"]["mac_dynamic_preflight"] = None
    plan["session_readiness_completed_before_attempt_allocation"] = True
    plan["protocol_mandated_device_state_change"] = False
    return plan


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    config = load_configuration((args.config or DEFAULT_CONFIG).resolve(), ROOT)
    validate_configuration(config)
    evidence_root = ROOT / config["retention"]["tracked_evidence_root"]
    require_capture_ready_package(
        evidence_root / "evidence_index.v1.json",
        repo_root=ROOT,
        config_path=(args.config or DEFAULT_CONFIG).resolve(),
    )
    inherited = load_json(evidence_root / "inheritance/inherited_fit_a.v1.json")
    validate_inherited_fit_a(inherited, config)
    seal_path = evidence_root / "precollection_seal.v1.json"
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    manifest = load_json(evidence_root / f"manifests/sessions/{args.session_id}.json")
    take = _find_take(manifest, args.planned_take_id)
    if take["session_id"] != args.session_id or not take["planned_take_id"].startswith(
        "s44a03_"
    ):
        raise S44AmendmentError("planned take is not a future amendment_03 cell")
    preflight = load_json(args.preflight)
    session_root = ROOT / config["retention"]["session_root"]
    other_records = [
        load_json(path)
        for path in sorted(session_root.glob("*/preflight.json"))
        if path.resolve() != args.preflight.resolve()
    ]
    validate_session_preflight(preflight, config, other_records=other_records)
    if preflight["session_id"] != args.session_id:
        raise S44AmendmentError("preflight/session mismatch")
    readiness = load_json(args.readiness)
    validate_session_readiness(
        readiness,
        config,
        precollection_seal_sha256=sha256_file(seal_path),
        session_preflight=preflight,
    )
    if readiness["session_id"] != args.session_id:
        raise S44AmendmentError("readiness/session mismatch")
    attempt_root = ROOT / config["retention"]["attempt_root"]
    _require_sequence(take, attempt_root)
    _require_attempt_number(take, attempt_root, args.attempt_number)
    placement = _validate_recorded_placement(args, take, config)
    contract = build_attempt_contract(
        take,
        attempt_number=args.attempt_number,
        precollection_seal_sha256=sha256_file(seal_path),
        session_readiness_sha256=readiness["readiness_sha256"],
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
            "session_preflight_path": args.preflight.resolve()
            .relative_to(ROOT)
            .as_posix(),
            "session_readiness_path": args.readiness.resolve()
            .relative_to(ROOT)
            .as_posix(),
            "placement": placement,
        },
    )
    if args.pre_recording_failure is not None:
        write_json_atomic(
            attempt_dir / "manifest.json",
            {
                **contract,
                "outcome": "pre_recording_failure",
                "technical_failure_reason": args.pre_recording_failure,
                "retained": True,
                "recorder_started": False,
            },
        )
        return {
            "status": "pre_recording_failure_retained",
            "attempt_id": contract["attempt_id"],
            "attempt_root": attempt_dir.relative_to(ROOT).as_posix(),
            "replacement_allowed": args.attempt_number == 1,
        }
    plan = _capture_plan_03(take, config, attempt_dir)
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
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--session-id", choices=("fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--planned-take-id", required=True)
    parser.add_argument("--attempt-number", type=int, choices=(1, 2), required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--recorded-position", type=float, nargs=3)
    parser.add_argument("--recorded-bearing", type=float)
    parser.add_argument("--recorded-distance", type=float)
    parser.add_argument("--placement-basis", default="operator_recorded_measurement")
    parser.add_argument("--reposition-confirmed", action="store_true")
    parser.add_argument("--pre-recording-failure")
    args = parser.parse_args()
    try:
        result = prepare(args)
    except (OSError, ValueError) as exc:
        print(f"S4.4 amendment-03 attempt preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "awaiting_physical_operator_action" else 2


if __name__ == "__main__":
    raise SystemExit(main())
