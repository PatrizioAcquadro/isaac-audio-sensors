#!/usr/bin/env python3
"""Execute and technically finalize one prepared S4.4 amendment attempt."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import (
    inspect_six_channel_wav,
    promote_finalized_file,
    write_checksums,
)
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    load_amendment_configuration,
    load_json,
    sanitize_holdout_technical_qa,
    sha256_file,
    validate_precollection_seal,
    validate_session_preflight,
    validate_session_readiness,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
CONFIG_PATH = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"
EVIDENCE_ROOT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments" / AMENDMENT_ID
CURRENT_SEAL_PATH = EVIDENCE_ROOT / (
    "freeze/precollection_seal.execution_corrective_01.v1.json"
)
ZED_REPLAY = ROOT / "scripts/validate_s4_2_zed_svo.py"
NETWORK_CONFIRMATION = "I_CONFIRM_EXTERNAL_NETWORK_PERMISSION"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(command: list[str], *, timeout: float) -> dict[str, Any]:
    started = time.monotonic_ns()
    result = subprocess.run(  # noqa: S603 - exact frozen argv only
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_ms": (time.monotonic_ns() - started) / 1_000_000.0,
    }


def _wait_ready(
    processes: dict[str, subprocess.Popen[str]], *, timeout: float
) -> dict[str, Any]:
    ready: dict[str, Any] = {}
    deadline = time.monotonic() + timeout
    while len(ready) < len(processes):
        if time.monotonic() >= deadline:
            raise S44AmendmentError(
                f"producer readiness timeout: {sorted(set(processes) - set(ready))}"
            )
        progressed = False
        for name, process in processes.items():
            if name in ready or process.stdout is None:
                continue
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr else ""
                raise S44AmendmentError(
                    f"{name} exited before ready: return={process.poll()} "
                    f"stderr={stderr}"
                )
            progressed = True
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise S44AmendmentError(
                    f"{name} emitted non-JSON readiness output"
                ) from exc
            if event.get("event") == "failed":
                raise S44AmendmentError(f"{name} readiness failed: {event}")
            if event.get("event") == "ready":
                ready[name] = event
        if not progressed:
            time.sleep(0.02)
    return ready


def _terminate(process: subprocess.Popen[str]) -> dict[str, Any]:
    if process.poll() is not None:
        return {"action": "already_exited", "return_code": process.returncode}
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=5)
        return {"action": "sigint", "return_code": process.returncode}
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        return {"action": "sigkill", "return_code": process.returncode}


def _artifact(path: Path, root: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _argument(command: list[str], name: str) -> str:
    if command.count(name) != 1:
        raise S44AmendmentError(f"capture command missing unique {name}")
    index = command.index(name)
    if index + 1 >= len(command):
        raise S44AmendmentError(f"capture command {name} has no value")
    return command[index + 1]


def _load_preconditions(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    config_path = args.config or CONFIG_PATH
    config = load_amendment_configuration(config_path, ROOT)
    evidence_root = ROOT / config["retention"]["tracked_evidence_root"]
    seal_path = (
        evidence_root / "precollection_seal.v1.json"
        if int(config["version"]) == 2
        else evidence_root / "freeze/precollection_seal.execution_corrective_01.v1.json"
    )
    seal = load_json(seal_path)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)
    if sha256_file(seal_path) != args.expected_precollection_seal_sha256:
        raise S44AmendmentError("execution precollection seal hash mismatch")
    if args.network_permission_confirmation != NETWORK_CONFIRMATION:
        raise S44AmendmentError("external-network permission confirmation absent")
    manifest_path = evidence_root / f"manifests/sessions/{args.session_id}.json"
    session_manifest = load_json(manifest_path)
    matches = [
        take
        for take in session_manifest["takes"]
        if take["planned_take_id"] == args.planned_take_id
    ]
    if len(matches) != 1:
        raise S44AmendmentError("planned take is not unique in session manifest")
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
    ):
        raise S44AmendmentError("prepared attempt is not executable")
    if contract.get("precollection_seal_sha256") != sha256_file(seal_path):
        raise S44AmendmentError("attempt is not bound to execution corrective")
    if attempt_manifest.get("capture_plan_sha256") != canonical_sha256(capture_plan):
        raise S44AmendmentError("capture plan hash mismatch")
    preflight_path = ROOT / str(
        contract.get(
            "session_preflight_path",
            Path(config["retention"]["session_root"])
            / args.session_id
            / "preflight.json",
        )
    )
    preflight = load_json(preflight_path)
    other_dates = [
        str(load_json(path).get("session_date_local"))
        for path in (ROOT / config["retention"]["session_root"]).glob(
            "*/preflight.json"
        )
        if path.resolve() != preflight_path.resolve()
    ]
    validate_session_preflight(preflight, config, other_dates=other_dates)
    if preflight["session_date_local"] != date.today().isoformat():
        raise S44AmendmentError("session preflight is not for today's local date")
    if args.operator_confirmation != "I_CONFIRM_S4_4_AMENDMENT_CAPTURE":
        raise S44AmendmentError("exact operator capture confirmation absent")
    if int(config["version"]) == 2:
        readiness_path_value = contract.get("session_readiness_path")
        if not isinstance(readiness_path_value, str):
            raise S44AmendmentError("attempt lacks session readiness path")
        readiness = load_json(ROOT / readiness_path_value)
        validate_session_readiness(
            readiness,
            config,
            precollection_seal_sha256=sha256_file(seal_path),
            inherited_preflight_sha256=preflight["preflight_sha256"],
        )
        if contract.get("session_readiness_sha256") != readiness.get(
            "readiness_sha256"
        ):
            raise S44AmendmentError("attempt/readiness hash mismatch")
    return config, take, contract, attempt_manifest, capture_plan, attempt_root


def _dynamic_mac(plan: dict[str, Any], attempt_root: Path) -> None:
    observation = _run(plan["commands"]["mac_dynamic_preflight"], timeout=30)
    write_json_atomic(attempt_root / "mac_dynamic_preflight_command.json", observation)
    try:
        report = json.loads(observation["stdout"])
    except json.JSONDecodeError as exc:
        raise S44AmendmentError("Mac dynamic preflight emitted invalid JSON") from exc
    write_json_atomic(attempt_root / "mac_dynamic_preflight.json", report)
    if observation["return_code"] != 0 or report.get("status") != "passed":
        raise S44AmendmentError("Mac dynamic preflight failed")
    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or not all(checks.values()):
        raise S44AmendmentError("Mac dynamic checks are incomplete or failed")


def _playback(plan: dict[str, Any], attempt_root: Path) -> None:
    command = plan["commands"]["reference_playback"]
    if not isinstance(command, list):
        raise S44AmendmentError("reference playback command absent")
    started_wall = _utc()
    started_monotonic_ns = time.monotonic_ns()
    observation = _run(command, timeout=15)
    record = {
        **observation,
        "started_wall_time_utc": started_wall,
        "started_monotonic_ns": started_monotonic_ns,
        "completed_wall_time_utc": _utc(),
        "completed_monotonic_ns": time.monotonic_ns(),
    }
    write_json_atomic(attempt_root / "playback.json", record)
    if observation["return_code"] != 0:
        raise S44AmendmentError("reference playback failed")


def _av_cues(attempt_root: Path, capture_started_ns: int) -> None:
    events = []
    for target in (5.0, 10.0, 15.0):
        remaining = target - (time.monotonic_ns() - capture_started_ns) / 1e9
        if remaining > 0:
            time.sleep(remaining)
        event = {
            "target_elapsed_s": target,
            "cue_wall_time_utc": _utc(),
            "cue_monotonic_ns": time.monotonic_ns(),
            "operator_action": "plain_paper_roll_strike_on_blue_wastebasket",
        }
        events.append(event)
        print(json.dumps({"event": "impact_now", **event}), flush=True)
    write_json_atomic(
        attempt_root / "av_impact_cues.json",
        {
            "schema": "ias.s4_4.amendment_av_impact_cues.v1",
            "events": events,
            "operator_confirmation_required_after_capture": True,
        },
    )


def _finalize(
    *,
    config: dict[str, Any],
    take: dict[str, Any],
    contract: dict[str, Any],
    plan: dict[str, Any],
    attempt_root: Path,
) -> dict[str, Any]:
    incoming = attempt_root / "_incoming" / "pi"
    incoming.mkdir(parents=True, exist_ok=False)
    remote = _argument(plan["commands"]["respeaker"], "--attempt")
    transfer_records = []
    for filename in ("producer_status.json", "respeaker_audio.wav"):
        transfer = _run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                f"elab-raspberrypi5:{remote}/{filename}",
                str(incoming / filename),
            ],
            timeout=120,
        )
        transfer_records.append(transfer)
        if transfer["return_code"] != 0:
            raise S44AmendmentError(f"Pi transfer failed for {filename}")
    write_json_atomic(
        attempt_root / "transfer.json", {"observations": transfer_records}
    )
    producer = load_json(incoming / "producer_status.json")
    if producer.get("status") != "complete":
        raise S44AmendmentError("Pi producer status is not complete")
    if sha256_file(incoming / "respeaker_audio.wav") != producer.get("sha256"):
        raise S44AmendmentError("Pi WAV transfer hash mismatch")
    raw = attempt_root / "raw"
    raw.mkdir(exist_ok=False)
    promote_finalized_file(
        incoming / "respeaker_audio.wav", raw / "respeaker_audio.wav"
    )
    promote_finalized_file(
        incoming / "producer_status.json", raw / "pi_producer_status.json"
    )
    artifacts = [
        _artifact(raw / "respeaker_audio.wav", attempt_root, "six_channel_audio"),
        _artifact(raw / "pi_producer_status.json", attempt_root, "pi_producer_status"),
    ]
    replay_pass = not bool(take["zed_required"])
    if take["zed_required"]:
        producer_zed = attempt_root / "_producer" / "zed"
        for source_name, destination_name, role in (
            ("capture.svo2", "zed_capture.svo2", "zed_svo2"),
            ("frames.jsonl", "zed_frames.jsonl", "zed_frame_records"),
            (
                "producer_summary.json",
                "zed_producer_summary.json",
                "zed_producer_status",
            ),
        ):
            promote_finalized_file(producer_zed / source_name, raw / destination_name)
            artifacts.append(_artifact(raw / destination_name, attempt_root, role))
        replay = _run(
            [
                sys.executable,
                str(ZED_REPLAY),
                str(raw / "zed_capture.svo2"),
                "--output",
                str(attempt_root / "zed_svo_replay.json"),
                "--expected-serial",
                config["identities"]["zed"]["serial"],
                "--resolution",
                "HD720",
                "--fps",
                "30",
                "--depth-mode",
                "PERFORMANCE",
            ],
            timeout=180,
        )
        write_json_atomic(attempt_root / "zed_svo_replay_command.json", replay)
        replay_pass = replay["return_code"] == 0
        if not replay_pass:
            raise S44AmendmentError("full SVO2 replay failed")
    wav, issues = inspect_six_channel_wav(
        raw / "respeaker_audio.wav",
        require_nonsilent_channels=take["category"] != "silence",
        reject_sustained_clipping=True,
        sustained_clip_run_samples_min=4000,
        expected_duration_s=float(take["duration_s"]),
        duration_tolerance_s=0.25,
    )
    issue_records = [issue.to_dict() for issue in issues]
    qa_input = {
        "planned_take_id": take["planned_take_id"],
        "attempt_id": contract["attempt_id"],
        "identity_pass": all(producer.get("startup_checks", {}).values()),
        "assigned_metadata_declaration_carried_forward": True,
        "duration_pass": not any(
            i["code"] == "wav_duration_mismatch" for i in issue_records
        ),
        "six_channel_count_pass": wav.get("channel_count") == 6,
        "no_detected_silent_channel_issue": not any(
            i["code"] == "silent_channel" for i in issue_records
        ),
        "clipping_pass": not any(
            i["code"] == "sustained_clipping" for i in issue_records
        ),
        "producer_timestamps_present": bool(producer.get("started_wall_time_utc"))
        and bool(producer.get("completed_wall_time_utc")),
        "playback_record_present_or_not_required": (
            take["category"] not in {"controlled", "confidence"}
            or (attempt_root / "playback.json").is_file()
        ),
        "integrity_pass": sha256_file(raw / "respeaker_audio.wav")
        == producer.get("sha256"),
        "privacy_declaration_carried_forward": True,
        "full_svo2_replay_pass": replay_pass,
    }
    technical_pass = not issue_records and all(
        value
        for key, value in qa_input.items()
        if key not in {"planned_take_id", "attempt_id"}
    )
    if take["partition"] == "prospective_holdout":
        qa = sanitize_holdout_technical_qa(
            qa_input, known_holdout_take_ids={take["planned_take_id"]}
        )
    else:
        qa = {
            "schema": "ias.s4_4.amendment_fit_technical_qa.v2",
            **qa_input,
            "overall_technical_pass": technical_pass,
            "wav_technical_properties": wav,
            "technical_issues": issue_records,
            "scientific_outcomes_used": False,
        }
    write_json_atomic(attempt_root / "technical_qa.json", qa)
    artifacts.append(
        _artifact(attempt_root / "technical_qa.json", attempt_root, "technical_qa")
    )
    write_checksums(attempt_root / "SHA256SUMS", attempt_root, artifacts)
    return {
        "outcome": "valid" if technical_pass else "invalid",
        "technical_failure_reason": None if technical_pass else "technical_QA_failed",
        "artifacts": artifacts,
        "technical_qa_sha256": sha256_file(attempt_root / "technical_qa.json"),
        "completed_at_utc": _utc(),
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    config, take, contract, manifest, plan, attempt_root = _load_preconditions(args)
    processes: dict[str, subprocess.Popen[str]] = {}
    recorder_started = False
    try:
        if int(config["version"]) == 1:
            _dynamic_mac(plan, attempt_root)
        producer_root = attempt_root / "_producer"
        producer_root.mkdir(exist_ok=False)
        pi = subprocess.Popen(  # noqa: S603 - frozen exact argv
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
            zed = subprocess.Popen(  # noqa: S603 - frozen exact argv
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
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--session-id", choices=("fit_a", "fit_b", "prospective_holdout"), required=True
    )
    parser.add_argument("--planned-take-id", required=True)
    parser.add_argument("--attempt-number", type=int, choices=(1, 2), required=True)
    parser.add_argument(
        "--expected-precollection-seal-sha256",
        "--expected-corrective-seal-sha256",
        dest="expected_precollection_seal_sha256",
        required=True,
    )
    parser.add_argument("--network-permission-confirmation", required=True)
    parser.add_argument("--operator-confirmation", required=True)
    args = parser.parse_args()
    try:
        result = execute(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment execution failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
