#!/usr/bin/env python3
"""Run one preregistered S4.3 hardware trial without changing device settings."""

from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import (
    promote_finalized_file,
    sha256_file,
    write_checksums,
)
from isaac_audio_sensors.acquisition.s4_3 import (
    EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL,
    S43Error,
    analyze_trial_wav,
    canonical_sha256,
    load_json,
    load_pilot_configuration,
    validate_mac_dynamic_preflight_report,
    validate_preregistration,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
PI_HELPER = "S4.2/bin/s4_2_pi_capture.py"
MAC_HELPER = "S4.2/bin/s4_2_mac_preflight.py"
ZED_HELPER = ROOT / "scripts/run_s4_2_zed_capture.py"
ZED_REPLAY = ROOT / "scripts/validate_s4_2_zed_svo.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_lifecycle(
    root: Path,
    events: list[dict[str, Any]],
    state: str,
    reason: str,
) -> None:
    events.append(
        {
            "state": state,
            "reason": reason,
            "wall_time_utc": _utc(),
            "monotonic_ns": time.monotonic_ns(),
        }
    )
    write_json_atomic(
        root / "lifecycle.json",
        {
            "schema": "ias.s4_3.lifecycle.v1",
            "state": state,
            "events": events,
        },
    )


def _run(command: list[str], *, timeout: float) -> dict[str, Any]:
    started = time.monotonic_ns()
    result = subprocess.run(  # noqa: S603 - explicit argv only
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


def _ssh(alias: str, remote: str, *, timeout: float) -> dict[str, Any]:
    return _run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            alias,
            remote,
        ],
        timeout=timeout,
    )


def _json_stdout(observation: dict[str, Any]) -> dict[str, Any]:
    if observation["return_code"] != 0:
        raise S43Error(
            f"command failed ({observation['return_code']}): "
            f"{observation['stderr'].strip()}"
        )
    try:
        payload = json.loads(observation["stdout"])
    except json.JSONDecodeError as exc:
        raise S43Error("command did not return one JSON object") from exc
    if not isinstance(payload, dict):
        raise S43Error("command JSON must be an object")
    return payload


def _wait_ready(
    processes: dict[str, subprocess.Popen[str]], *, timeout: float
) -> dict[str, Any]:
    ready: dict[str, Any] = {}
    deadline = time.monotonic() + timeout
    streams = {
        process.stdout: name
        for name, process in processes.items()
        if process.stdout is not None
    }
    while len(ready) < len(processes):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise S43Error(
                f"producer readiness timeout: {sorted(set(processes) - set(ready))}"
            )
        readable, _, _ = select.select(list(streams), [], [], remaining)
        if not readable:
            continue
        for stream in readable:
            line = stream.readline()
            name = streams[stream]
            if not line:
                process = processes[name]
                stderr = process.stderr.read() if process.stderr else ""
                raise S43Error(
                    f"{name} exited before ready: return={process.poll()} "
                    f"stderr={stderr}"
                )
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise S43Error(f"{name} emitted non-JSON readiness output") from exc
            if event.get("event") == "failed":
                raise S43Error(f"{name} readiness failed: {event}")
            if event.get("event") == "ready":
                ready[name] = event
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


def _mac_dynamic(configuration: dict[str, Any]) -> dict[str, Any]:
    hardware = configuration["hardware"]
    remote = (
        f"/usr/bin/python3 {shlex.quote(MAC_HELPER)} --dynamic-only "
        f"--expected-volume-percent {int(hardware['mac_volume_percent'])}"
    )
    observation = _ssh(hardware["mac_ssh_alias"], remote, timeout=30)
    try:
        payload = json.loads(observation["stdout"])
    except json.JSONDecodeError as exc:
        raise S43Error("Mac dynamic preflight did not return JSON") from exc
    if not isinstance(payload, dict):
        raise S43Error("Mac dynamic preflight JSON must be an object")
    if (
        configuration.get("operational_gate_policy") is None
        and observation["return_code"] != 0
    ):
        raise S43Error(
            f"Mac dynamic preflight command failed ({observation['return_code']})"
        )
    gate = validate_mac_dynamic_preflight_report(payload, configuration)
    return {
        "report": payload,
        "command": observation,
        "gate": gate,
        "status": "passed",
        "command_return_code_metadata": observation["return_code"],
    }


def _start_playback(configuration: dict[str, Any]) -> subprocess.Popen[str]:
    hardware = configuration["hardware"]
    reference = configuration["reference"]
    command = [
        "/usr/bin/afplay",
        "-v",
        str(hardware["mac_afplay_gain"]),
        str(reference["mac_path"]),
    ]
    remote_python = (
        "import datetime,json,subprocess,time;"
        "s=time.monotonic_ns();"
        "w=datetime.datetime.now(datetime.timezone.utc).isoformat();"
        f"c={command!r};"
        "p=subprocess.run(c,check=False);"
        "print(json.dumps({'command':c,'started_wall_time_utc':w,"
        "'started_monotonic_ns':s,'completed_wall_time_utc':"
        "datetime.datetime.now(datetime.timezone.utc).isoformat(),"
        "'completed_monotonic_ns':time.monotonic_ns(),"
        "'exit_status':p.returncode}))"
    )
    remote = "/usr/bin/python3 -c " + shlex.quote(remote_python)
    return subprocess.Popen(  # noqa: S603 - explicit argv
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            hardware["mac_ssh_alias"],
            remote,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _trial(configuration: dict[str, Any], trial_id: str) -> dict[str, Any]:
    matches = [item for item in configuration["matrix"] if item["trial_id"] == trial_id]
    if len(matches) != 1:
        raise S43Error(f"trial id is not uniquely preregistered: {trial_id}")
    return dict(matches[0])


def _artifact(path: Path, root: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    configuration = load_pilot_configuration(args.config, repo_root=ROOT)
    preregistration = load_json(args.preregistration)
    freeze = validate_preregistration(configuration, preregistration, repo_root=ROOT)
    if not freeze.passed:
        raise S43Error(f"preregistration failed: {freeze.to_dict()}")
    trial = _trial(configuration, args.trial_id)
    expected_confirmation = f"I_CONFIRMED_{trial['operator_action']}"
    if args.operator_confirmation != expected_confirmation:
        raise S43Error(
            "operator confirmation does not match the preregistered action; "
            f"expected {expected_confirmation!r}"
        )
    if args.interactive_trigger and trial["stimulus"] not in {
        "standardized_voice",
        "mac_reference_plus_standardized_voice",
        "visible_audible_ordinary_object_impact",
    }:
        raise S43Error("interactive trigger is not declared for this stimulus")
    if not args.interactive_trigger and trial["stimulus"] in {
        "standardized_voice",
        "mac_reference_plus_standardized_voice",
        "visible_audible_ordinary_object_impact",
    }:
        raise S43Error("this stimulus requires --interactive-trigger")
    if args.interactive_trigger and configuration.get(
        "interactive_stimulus_protocol"
    ) != EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL:
        raise S43Error("interactive stimulus protocol is not frozen")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    attempt_id = (
        args.attempt_id or f"{trial['trial_id']}_{stamp}_{uuid.uuid4().hex[:8]}"
    )
    if not all(character.isalnum() or character in "-_." for character in attempt_id):
        raise S43Error("attempt id contains unsafe characters")
    attempt_root = (
        ROOT
        / configuration["retention"]["attempt_root"]
        / trial["trial_id"]
        / attempt_id
    )
    attempt_root.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    processes: dict[str, subprocess.Popen[str]] = {}
    artifacts: list[dict[str, Any]] = []
    remote_attempt = f"S4.3/captures/{attempt_id}"
    write_json_atomic(attempt_root / "trial_definition.json", trial)
    write_json_atomic(
        attempt_root / "contract.json",
        {
            "schema": "ias.s4_3.attempt_contract.v1",
            "attempt_id": attempt_id,
            "trial_id": trial["trial_id"],
            "trial_definition_sha256": canonical_sha256(trial),
            "configuration_sha256": canonical_sha256(configuration),
            "preregistration_sha256": sha256_file(args.preregistration),
            "operator_confirmation": args.operator_confirmation,
            "remote_attempt": remote_attempt,
            "created_at_utc": _utc(),
        },
    )
    _write_lifecycle(attempt_root, events, "preflight", "frozen contract verified")
    try:
        reference_required = "mac_reference" in trial["stimulus"]
        reference = ROOT / configuration["reference"]["local_path"]
        if reference_required:
            if (
                not reference.is_file()
                or sha256_file(reference) != configuration["reference"]["sha256"]
            ):
                raise S43Error("local deterministic reference is missing or changed")
            pi_helper_check = (
                f"test -f {shlex.quote(PI_HELPER)} && "
                f"sha256sum {shlex.quote(PI_HELPER)}"
            )
            mac_reference = str(configuration["reference"]["mac_path"])
            mac_contract_check = (
                f"test -f {shlex.quote(MAC_HELPER)} && "
                f"test -f {shlex.quote(mac_reference)} && "
                f"shasum -a 256 {shlex.quote(mac_reference)}"
            )
            remote_checks = {
                "pi_helper": _ssh(
                    configuration["hardware"]["respeaker_ssh_alias"],
                    pi_helper_check,
                    timeout=15,
                ),
                "mac_helper_and_reference": _ssh(
                    configuration["hardware"]["mac_ssh_alias"],
                    mac_contract_check,
                    timeout=15,
                ),
            }
            if remote_checks["pi_helper"]["return_code"] != 0:
                raise S43Error("existing Pi capture helper is unavailable")
            if (
                remote_checks["mac_helper_and_reference"]["return_code"] != 0
                or configuration["reference"]["sha256"]
                not in remote_checks["mac_helper_and_reference"]["stdout"]
            ):
                raise S43Error(
                    "existing Mac helper/reference is unavailable or changed"
                )
            write_json_atomic(
                attempt_root / "remote_contract_checks.json", remote_checks
            )
            write_json_atomic(
                attempt_root / "mac_dynamic_preflight.json", _mac_dynamic(configuration)
            )
        else:
            pi_helper_check = (
                f"test -f {shlex.quote(PI_HELPER)} && "
                f"sha256sum {shlex.quote(PI_HELPER)}"
            )
            pi_check = _ssh(
                configuration["hardware"]["respeaker_ssh_alias"],
                pi_helper_check,
                timeout=15,
            )
            if pi_check["return_code"] != 0:
                raise S43Error("existing Pi capture helper is unavailable")
            write_json_atomic(
                attempt_root / "remote_contract_checks.json", {"pi_helper": pi_check}
            )

        if args.interactive_trigger:
            print(
                json.dumps(
                    {
                        "event": "awaiting_operator_ready",
                        "trial_id": trial["trial_id"],
                        "stimulus": trial["stimulus"],
                        "recorder_started": False,
                    }
                ),
                flush=True,
            )
            if sys.stdin.readline() == "":
                raise S43Error("interactive operator-ready input closed")
            write_json_atomic(
                attempt_root / "operator_ready.json",
                {
                    "schema": "ias.s4_3.operator_ready.v1",
                    "confirmed_at_utc": _utc(),
                    "confirmed_monotonic_ns": time.monotonic_ns(),
                    "stimulus": trial["stimulus"],
                    "recorder_started": False,
                },
            )

        producer_root = attempt_root / "_producer"
        producer_root.mkdir()
        pi_command = (
            f"/usr/bin/python3 {shlex.quote(PI_HELPER)} record "
            f"--attempt {shlex.quote(remote_attempt)} "
            f"--device {shlex.quote(configuration['hardware']['respeaker_device'])} "
            f"--duration {int(trial['duration_s'])} --minimum-free-bytes 1073741824"
        )
        pi_process = subprocess.Popen(  # noqa: S603 - explicit argv
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                configuration["hardware"]["respeaker_ssh_alias"],
                pi_command,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        processes["pi"] = pi_process
        if trial["zed_required"]:
            zed_output = producer_root / "zed"
            zed_output.mkdir()
            zed_policy = configuration.get("operational_gate_policy", {}).get(
                "zed_impact_capture", {}
            )
            reference_versions = zed_policy.get(
                "reference_versions",
                {
                    "sdk_version": configuration["hardware"]["zed_sdk"],
                    "camera_firmware": "1523",
                    "sensor_firmware": "777",
                },
            )
            zed_process = subprocess.Popen(  # noqa: S603 - explicit argv
                [
                    sys.executable,
                    str(ZED_HELPER),
                    "--duration",
                    str(trial["duration_s"]),
                    "--output-dir",
                    str(zed_output),
                    "--expected-serial",
                    configuration["hardware"]["zed_serial"],
                    "--expected-sdk",
                    reference_versions["sdk_version"],
                    "--expected-camera-firmware",
                    reference_versions["camera_firmware"],
                    "--expected-sensor-firmware",
                    reference_versions["sensor_firmware"],
                    "--version-policy",
                    zed_policy.get("version_policy", "exact"),
                    "--resolution",
                    "HD720",
                    "--fps",
                    "30",
                    "--depth-mode",
                    "PERFORMANCE",
                    "--minimum-usb-speed-mbps",
                    "5000",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            processes["zed"] = zed_process
        ready = _wait_ready(processes, timeout=20)
        write_json_atomic(attempt_root / "producer_readiness.json", ready)
        _write_lifecycle(attempt_root, events, "recording", "required producers ready")
        settle_s = float(
            configuration.get("interactive_stimulus_protocol", {}).get(
                "settle_before_stimulus_cue_s", 2.0
            )
        )
        time.sleep(settle_s)
        if args.interactive_trigger:
            write_json_atomic(
                attempt_root / "stimulus_trigger.json",
                {
                    "schema": "ias.s4_3.stimulus_trigger.v1",
                    "triggered_at_utc": _utc(),
                    "triggered_monotonic_ns": time.monotonic_ns(),
                    "stimulus": trial["stimulus"],
                },
            )
            print(json.dumps({"event": "stimulus_now"}), flush=True)
        playback_record: dict[str, Any] | None = None
        if reference_required:
            playback = _start_playback(configuration)
            processes["mac_playback"] = playback
            stdout, stderr = playback.communicate(timeout=15)
            playback_record = {
                "return_code": playback.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
            if playback.returncode != 0:
                raise S43Error("Mac reference playback failed")
            playback_record["remote"] = json.loads(stdout)
            write_json_atomic(attempt_root / "playback.json", playback_record)

        for name in ("pi", "zed"):
            if name not in processes:
                continue
            process = processes[name]
            process.wait(timeout=float(trial["duration_s"]) + 20)
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise S43Error(f"{name} producer failed: {stderr}")
        _write_lifecycle(attempt_root, events, "finalizing", "producers finalized")

        incoming = attempt_root / "_incoming" / "pi"
        incoming.mkdir(parents=True)
        transfer_records = []
        for filename in ("producer_status.json", "respeaker_audio.wav"):
            observation = _run(
                [
                    "scp",
                    "-q",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=8",
                    f"{configuration['hardware']['respeaker_ssh_alias']}:{remote_attempt}/{filename}",
                    str(incoming / filename),
                ],
                timeout=120,
            )
            transfer_records.append(observation)
            if observation["return_code"] != 0:
                raise S43Error(f"Pi transfer failed for {filename}")
        write_json_atomic(
            attempt_root / "transfer.json", {"observations": transfer_records}
        )
        producer_status = load_json(incoming / "producer_status.json")
        if producer_status.get("status") != "complete":
            raise S43Error("Pi producer status is not complete")
        if sha256_file(incoming / "respeaker_audio.wav") != producer_status.get(
            "sha256"
        ):
            raise S43Error("transferred WAV does not match Pi producer SHA-256")
        raw = attempt_root / "raw"
        raw.mkdir()
        promote_finalized_file(
            incoming / "respeaker_audio.wav", raw / "respeaker_audio.wav"
        )
        promote_finalized_file(
            incoming / "producer_status.json", raw / "pi_producer_status.json"
        )
        artifacts.extend(
            [
                _artifact(
                    raw / "respeaker_audio.wav", attempt_root, "six_channel_audio"
                ),
                _artifact(
                    raw / "pi_producer_status.json", attempt_root, "pi_producer_status"
                ),
            ]
        )
        if trial["zed_required"]:
            zed_output = producer_root / "zed"
            for source_name, destination_name, role in (
                ("capture.svo2", "zed_capture.svo2", "zed_svo2"),
                ("frames.jsonl", "zed_frames.jsonl", "zed_frame_records"),
                (
                    "producer_summary.json",
                    "zed_producer_summary.json",
                    "zed_producer_status",
                ),
            ):
                promote_finalized_file(zed_output / source_name, raw / destination_name)
                artifacts.append(_artifact(raw / destination_name, attempt_root, role))
            replay = _run(
                [
                    sys.executable,
                    str(ZED_REPLAY),
                    str(raw / "zed_capture.svo2"),
                    "--output",
                    str(attempt_root / "zed_svo_replay.json"),
                    "--expected-serial",
                    configuration["hardware"]["zed_serial"],
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
            if replay["return_code"] != 0:
                raise S43Error("ZED full SVO2 replay failed")

        analysis = analyze_trial_wav(
            raw / "respeaker_audio.wav",
            trial,
            configuration,
            reference_path=reference if reference_required else None,
        )
        write_json_atomic(attempt_root / "analysis.json", analysis)
        if analysis["status"] != "passed":
            raise S43Error(f"trial analysis failed: {analysis['issues']}")
        artifacts.append(
            _artifact(attempt_root / "analysis.json", attempt_root, "trial_analysis")
        )
        terminal = "awaiting_av_annotation" if trial["zed_required"] else "accepted"
        manifest = {
            "schema": "ias.s4_3.attempt_manifest.v1",
            "attempt_id": attempt_id,
            "trial_id": trial["trial_id"],
            "category": trial["category"],
            "stimulus": trial["stimulus"],
            "lifecycle_status": terminal,
            "quality_status": "passed",
            "scientific_disposition": "pending_aggregate_and_closeout",
            "created_at_utc": _utc(),
            "trial_definition_sha256": canonical_sha256(trial),
            "configuration_sha256": canonical_sha256(configuration),
            "artifacts": artifacts,
            "raw_retention": configuration["retention"],
            "limitations": configuration["phase_boundary"]["unsupported_claims"],
            "s4_4_started": False,
        }
        write_json_atomic(attempt_root / "manifest.json", manifest)
        artifacts.append(
            _artifact(attempt_root / "manifest.json", attempt_root, "attempt_manifest")
        )
        write_checksums(attempt_root / "SHA256SUMS", attempt_root, artifacts)
        if terminal == "accepted":
            _write_lifecycle(
                attempt_root, events, "accepted", "quality and analysis passed"
            )
        return {
            "status": terminal,
            "attempt_id": attempt_id,
            "attempt_root": attempt_root.relative_to(ROOT).as_posix(),
            "trial_id": trial["trial_id"],
            "analysis_summary": analysis["summary"],
        }
    except BaseException as exc:
        cleanup = {name: _terminate(process) for name, process in processes.items()}
        if processes.get("pi") is not None:
            stop_remote = (
                f"/usr/bin/python3 {shlex.quote(PI_HELPER)} stop "
                f"--attempt {shlex.quote(remote_attempt)}"
            )
            cleanup["pi_remote_stop"] = _ssh(
                configuration["hardware"]["respeaker_ssh_alias"],
                stop_remote,
                timeout=15,
            )
        write_json_atomic(attempt_root / "cleanup.json", cleanup)
        current = load_json(attempt_root / "lifecycle.json").get("state")
        if current not in {"accepted", "rejected", "failed", "interrupted"}:
            state = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            _write_lifecycle(
                attempt_root, events, state, f"{type(exc).__name__}: {exc}"
            )
        write_json_atomic(
            attempt_root / "failure.json",
            {
                "schema": "ias.s4_3.failure.v1",
                "attempt_id": attempt_id,
                "trial_id": trial["trial_id"],
                "error_type": type(exc).__name__,
                "error": str(exc),
                "occurred_at_utc": _utc(),
                "retained": True,
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path("configs/s4_3_pilot.v1.json")
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S4/S4.3/freeze/preregistration.json"),
    )
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--attempt-id", default=None)
    parser.add_argument("--operator-confirmation", required=True)
    parser.add_argument("--interactive-trigger", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, S43Error, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.3 trial failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"accepted", "awaiting_av_annotation"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
