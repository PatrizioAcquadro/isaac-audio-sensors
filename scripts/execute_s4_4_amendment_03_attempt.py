#!/usr/bin/env python3
"""Execute one prepared future amendment-03 attempt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    S44AmendmentError,
    active_precollection_package,
    load_configuration,
    validate_configuration,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_session_preflight,
    validate_session_readiness,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic
from scripts.execute_s4_4_amendment_attempt import (
    _av_cues,
    _finalize,
    _playback,
    _terminate,
    _utc,
    _wait_ready,
)
from scripts.validate_s4_4_amendment_03 import require_capture_ready_package

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
NETWORK_CONFIRMATION = "I_CONFIRM_EXTERNAL_NETWORK_PERMISSION"


def _load_preconditions(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    config = load_configuration((args.config or DEFAULT_CONFIG).resolve(), ROOT)
    validate_configuration(config)
    evidence_root = ROOT / config["retention"]["tracked_evidence_root"]
    index_path, seal_path = active_precollection_package(evidence_root)
    require_capture_ready_package(
        index_path,
        repo_root=ROOT,
        config_path=(args.config or DEFAULT_CONFIG).resolve(),
    )
    inherited = load_json(evidence_root / "inheritance/inherited_fit_a.v1.json")
    validate_inherited_fit_a(inherited, config)
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    if sha256_file(seal_path) != args.expected_precollection_seal_sha256:
        raise S44AmendmentError("execution precollection seal hash mismatch")
    if args.network_permission_confirmation != NETWORK_CONFIRMATION:
        raise S44AmendmentError("external-network permission confirmation absent")
    session_manifest = load_json(
        evidence_root / f"manifests/sessions/{args.session_id}.json"
    )
    matches = [
        take
        for take in session_manifest["takes"]
        if take["planned_take_id"] == args.planned_take_id
    ]
    if len(matches) != 1 or not args.planned_take_id.startswith("s44a03_"):
        raise S44AmendmentError("future planned take is not unique")
    take = matches[0]
    attempt_id = f"{args.planned_take_id}__attempt_{args.attempt_number:02d}"
    attempt_root = (
        ROOT / config["retention"]["attempt_root"] / args.planned_take_id / attempt_id
    )
    contract = load_json(attempt_root / "attempt_contract.json")
    attempt_manifest = load_json(attempt_root / "manifest.json")
    capture_plan = load_json(attempt_root / "capture_plan.json")
    if (
        contract.get("attempt_id") != attempt_id
        or attempt_manifest.get("attempt_id") != attempt_id
        or attempt_manifest.get("outcome") != "planned"
        or attempt_manifest.get("recorder_started") is not False
        or capture_plan.get("commands", {}).get("mac_dynamic_preflight") is not None
        or capture_plan.get("protocol_mandated_device_state_change") is not False
    ):
        raise S44AmendmentError("prepared amendment_03 attempt is not executable")
    if contract.get("precollection_seal_sha256") != sha256_file(seal_path):
        raise S44AmendmentError("attempt is not bound to amendment_03 seal")
    if attempt_manifest.get("capture_plan_sha256") != canonical_sha256(capture_plan):
        raise S44AmendmentError("capture plan hash mismatch")
    preflight_path = ROOT / str(contract.get("session_preflight_path"))
    preflight = load_json(preflight_path)
    session_root = ROOT / config["retention"]["session_root"]
    other_records = [
        load_json(path)
        for path in sorted(session_root.rglob("preflight.json"))
        if path.resolve() != preflight_path.resolve()
    ]
    validate_session_preflight(preflight, config, other_records=other_records)
    if preflight["session_date_local"] != date.today().isoformat():
        raise S44AmendmentError("session preflight is not for today's local date")
    if args.operator_confirmation != "I_CONFIRM_S4_4_AMENDMENT_03_CAPTURE":
        raise S44AmendmentError("exact amendment_03 operator confirmation absent")
    readiness_path = ROOT / str(contract.get("session_readiness_path"))
    readiness = load_json(readiness_path)
    validate_session_readiness(
        readiness,
        config,
        precollection_seal_sha256=sha256_file(seal_path),
        session_preflight=preflight,
    )
    if contract.get("session_readiness_sha256") != readiness.get("readiness_sha256"):
        raise S44AmendmentError("attempt/readiness hash mismatch")
    return config, take, contract, attempt_manifest, capture_plan, attempt_root


def execute(args: argparse.Namespace) -> dict[str, Any]:
    config, take, contract, manifest, plan, attempt_root = _load_preconditions(args)
    processes: dict[str, subprocess.Popen[str]] = {}
    recorder_started = False
    try:
        producer_root = attempt_root / "_producer"
        producer_root.mkdir(exist_ok=False)
        pi = subprocess.Popen(  # noqa: S603 - exact frozen argv
            plan["commands"]["respeaker"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        processes["pi"] = pi
        zed_command = plan["commands"].get("zed")
        if isinstance(zed_command, list):
            (producer_root / "zed").mkdir()
            zed = subprocess.Popen(  # noqa: S603 - exact frozen argv
                zed_command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            processes["zed"] = zed
        readiness = _wait_ready(processes, timeout=20)
        write_json_atomic(attempt_root / "producer_readiness.json", readiness)
        recorder_started = True
        manifest = {**manifest, "recorder_started": True, "started_at_utc": _utc()}
        write_json_atomic(attempt_root / "manifest.json", manifest)
        capture_started_ns = time.monotonic_ns()
        if take["category"] in {"controlled", "confidence"}:
            time.sleep(2.0)
            _playback(plan, attempt_root)
        elif take["category"] == "audio_video":
            _av_cues(attempt_root, capture_started_ns)
        for name, process in processes.items():
            process.wait(timeout=float(take["duration_s"]) + 20)
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise S44AmendmentError(f"{name} producer failed: {stderr}")
        final = _finalize(
            config=config,
            take=take,
            contract=contract,
            plan=plan,
            attempt_root=attempt_root,
        )
        manifest = {
            **manifest,
            **final,
            "retained": True,
            "scientific_outcome_used_for_replacement": False,
        }
        write_json_atomic(attempt_root / "manifest.json", manifest)
        return {
            "status": manifest["outcome"],
            "attempt_id": contract["attempt_id"],
            "attempt_root": attempt_root.relative_to(ROOT).as_posix(),
            "recorder_started": True,
            "technical_qa_sha256": final["technical_qa_sha256"],
        }
    except BaseException as exc:
        cleanup = {name: _terminate(process) for name, process in processes.items()}
        write_json_atomic(attempt_root / "cleanup.json", cleanup)
        failure_outcome = "invalid" if recorder_started else "pre_recording_failure"
        write_json_atomic(
            attempt_root / "manifest.json",
            {
                **manifest,
                "outcome": failure_outcome,
                "technical_failure_reason": f"{type(exc).__name__}: {exc}",
                "recorder_started": recorder_started,
                "retained": True,
                "scientific_outcome_used_for_replacement": False,
                "failed_at_utc": _utc(),
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--session-id", choices=("fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--planned-take-id", required=True)
    parser.add_argument("--attempt-number", type=int, choices=(1, 2), required=True)
    parser.add_argument("--expected-precollection-seal-sha256", required=True)
    parser.add_argument("--network-permission-confirmation", required=True)
    parser.add_argument("--operator-confirmation", required=True)
    args = parser.parse_args()
    try:
        result = execute(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment-03 execution failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
