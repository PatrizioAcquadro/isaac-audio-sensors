"""Maintained workstation-side S4.2 acquisition orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import (
    ATTEMPT_SCHEMA,
    AttemptLifecycle,
    S42Error,
    ValidationIssue,
    ValidationReport,
    artifact_record,
    disk_space_check,
    inspect_six_channel_wav,
    load_json,
    promote_finalized_file,
    read_jsonl,
    recompute_alignment_from_evidence,
    sha256_file,
    validate_configuration,
    validate_mac_dynamic_preflight,
    validate_mac_preflight,
    validate_playback_capture_overlap,
    validate_reference_capture,
    validate_svo_replay_report,
    validate_zed_records,
    verify_artifact_records,
    write_checksums,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

REPO_ROOT = Path(__file__).resolve().parents[3]
PI_HELPER_LOCAL = REPO_ROOT / "scripts/s4_2_pi_capture.py"
MAC_HELPER_LOCAL = REPO_ROOT / "scripts/s4_2_mac_preflight.py"
ZED_CAPTURE_LOCAL = REPO_ROOT / "scripts/run_s4_2_zed_capture.py"
ZED_SVO_VALIDATOR_LOCAL = REPO_ROOT / "scripts/validate_s4_2_zed_svo.py"
PI_HELPER_REMOTE = "S4.2/bin/s4_2_pi_capture.py"
MAC_HELPER_REMOTE = "S4.2/bin/s4_2_mac_preflight.py"


def _wall_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    command: Sequence[str], *, timeout: float, cwd: Path | None = None
) -> dict[str, Any]:
    started_wall = _wall_utc()
    started_mono = time.monotonic_ns()
    try:
        completed = subprocess.run(  # noqa: S603 - explicit argv, no local shell
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    completed_mono = time.monotonic_ns()
    return {
        "command": list(command),
        "started_wall_time_utc": started_wall,
        "completed_wall_time_utc": _wall_utc(),
        "started_monotonic_ns": started_mono,
        "completed_monotonic_ns": completed_mono,
        "elapsed_ms": (completed_mono - started_mono) / 1e6,
        "timed_out": timed_out,
        "return_code": return_code,
        "stdout": stdout,
        "stderr": stderr,
    }


def _ssh(alias: str, remote_command: str, *, timeout: float) -> dict[str, Any]:
    return _run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            alias,
            remote_command,
        ],
        timeout=timeout,
        cwd=REPO_ROOT,
    )


def _result_payload(observation: Mapping[str, Any]) -> dict[str, Any]:
    stdout = observation.get("stdout")
    if not isinstance(stdout, str):
        raise S42Error("command stdout is not text")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise S42Error(f"command emitted invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise S42Error("command JSON must be an object")
    return payload


def deploy_helpers_and_reference(configuration: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only dedicated S4.2 helpers/reference and verify remote hashes."""

    config_report = validate_configuration(configuration, require_ready=False)
    if not config_report.passed:
        raise S42Error(f"configuration failed: {config_report.to_dict()}")
    reference = REPO_ROOT / str(configuration["reference"]["local_path"])
    expected_reference_hash = str(configuration["reference"]["sha256"])
    if not reference.is_file() or sha256_file(reference) != expected_reference_hash:
        raise S42Error("local reference WAV is missing or does not match configuration")
    pi_alias = str(configuration["respeaker"]["ssh_alias"])
    mac_alias = str(configuration["mac"]["ssh_alias"])
    observations: list[dict[str, Any]] = []
    for alias in (pi_alias, mac_alias):
        observation = _ssh(alias, "mkdir -p S4.2/bin S4.2/reference", timeout=15)
        observations.append(observation)
        if observation["return_code"] != 0:
            raise S42Error(f"{alias}: failed to create dedicated S4.2 directories")
    copies = (
        (PI_HELPER_LOCAL, f"{pi_alias}:{PI_HELPER_REMOTE}"),
        (MAC_HELPER_LOCAL, f"{mac_alias}:{MAC_HELPER_REMOTE}"),
        (
            reference,
            f"{mac_alias}:{configuration['mac']['reference_path']}",
        ),
    )
    for source, destination in copies:
        observation = _run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                str(source),
                str(destination),
            ],
            timeout=60,
            cwd=REPO_ROOT,
        )
        observations.append(observation)
        if observation["return_code"] != 0:
            raise S42Error(f"copy failed: {source.name} -> {destination}")
    pi_verify = _ssh(
        pi_alias,
        f"sha256sum {shlex.quote(PI_HELPER_REMOTE)}",
        timeout=15,
    )
    mac_verify = _ssh(
        mac_alias,
        "shasum -a 256 " + shlex.quote(str(configuration["mac"]["reference_path"])),
        timeout=15,
    )
    afinfo_verify = _ssh(
        mac_alias,
        "/usr/bin/afinfo " + shlex.quote(str(configuration["mac"]["reference_path"])),
        timeout=30,
    )
    observations.extend((pi_verify, mac_verify, afinfo_verify))
    if (
        pi_verify["return_code"] != 0
        or sha256_file(PI_HELPER_LOCAL) not in pi_verify["stdout"]
        or mac_verify["return_code"] != 0
        or expected_reference_hash not in mac_verify["stdout"]
        or afinfo_verify["return_code"] != 0
    ):
        raise S42Error("remote helper/reference verification failed")
    return {
        "schema": "ias.s4_2.deployment.v1",
        "status": "passed",
        "pi_helper_sha256": sha256_file(PI_HELPER_LOCAL),
        "mac_helper_sha256": sha256_file(MAC_HELPER_LOCAL),
        "reference_sha256": expected_reference_hash,
        "mac_reference_path": str(configuration["mac"]["reference_path"]),
        "observations": observations,
    }


def collect_mac_preflight(
    configuration: Mapping[str, Any], output: str | Path
) -> dict[str, Any]:
    """Run the deployed read-only Mac helper and retain its redacted JSON."""

    config_report = validate_configuration(configuration, require_ready=False)
    if not config_report.passed:
        raise S42Error(f"configuration failed: {config_report.to_dict()}")
    mac = configuration["mac"]
    reference = configuration["reference"]
    remote = (
        f"/usr/bin/python3 {shlex.quote(MAC_HELPER_REMOTE)} "
        f"--wav {shlex.quote(str(mac['reference_path']))} "
        f"--expected-sha256 {shlex.quote(str(reference['sha256']))} "
        f"--expected-volume-percent {int(mac['system_volume_percent'])}"
    )
    observation = _ssh(str(mac["ssh_alias"]), remote, timeout=60)
    try:
        payload = _result_payload(observation)
    except S42Error:
        write_json_atomic(
            Path(output).with_suffix(".command_failure.json"), observation
        )
        raise
    write_json_atomic(output, payload)
    validation = validate_mac_preflight(payload, configuration)
    return {
        "report": payload,
        "command": observation,
        "validation": validation.to_dict(),
        "status": "passed" if validation.passed else "failed",
    }


def collect_mac_dynamic_preflight(
    configuration: Mapping[str, Any], output: str | Path
) -> dict[str, Any]:
    """Run only the dynamic Mac checks required immediately before one take."""

    mac = configuration["mac"]
    remote = (
        f"/usr/bin/python3 {shlex.quote(MAC_HELPER_REMOTE)} --dynamic-only "
        f"--expected-volume-percent {int(mac['system_volume_percent'])}"
    )
    observation = _ssh(str(mac["ssh_alias"]), remote, timeout=30)
    payload = _result_payload(observation)
    write_json_atomic(output, payload)
    validation = validate_mac_dynamic_preflight(payload, configuration)
    return {
        "command": observation,
        "report": payload,
        "validation": validation.to_dict(),
        "status": "passed" if validation.passed else "failed",
    }


def _stable_session_contract_sha256(configuration: Mapping[str, Any]) -> str:
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def collect_stable_session_preflight(
    configuration: Mapping[str, Any], output: str | Path
) -> dict[str, Any]:
    """Create one immutable Mac/GPU preflight record for a stable session."""

    config_report = validate_configuration(configuration, require_ready=True)
    if not config_report.passed:
        raise S42Error(f"configuration failed: {config_report.to_dict()}")
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    mac_output = REPO_ROOT / str(configuration["mac"]["preflight_report_path"])
    if output_path.exists() or mac_output.exists():
        raise S42Error("stable-session or full Mac preflight output already exists")
    mac = collect_mac_preflight(configuration, mac_output)
    gpu = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        timeout=15,
        cwd=REPO_ROOT,
    )
    passed = mac["status"] == "passed" and gpu["return_code"] == 0
    payload = {
        "schema": "ias.s4_2.stable_session_preflight.v1",
        "session_id": configuration["session"]["stable_preflight_id"],
        "status": "passed" if passed else "failed",
        "created_wall_time_utc": _wall_utc(),
        "created_monotonic_ns": time.monotonic_ns(),
        "configuration_sha256": _stable_session_contract_sha256(configuration),
        "full_mac_preflight": {
            "path": str(Path(configuration["mac"]["preflight_report_path"])),
            "sha256": sha256_file(mac_output),
            "validation": mac["validation"],
            "connectivity_observation": mac["command"],
        },
        "nvidia_smi": gpu,
        "connectivity_policy": (
            "Mac connectivity is observed by the full preflight; Pi connectivity "
            "is observed by the real recorder SSH command. Timing is diagnostic "
            "only and is not synchronization evidence."
        ),
        "invalidation_conditions": [
            "Mac dynamic setting mismatch",
            "device disconnection or recorder startup error",
            "operator-reported setting or hardware change",
        ],
    }
    write_json_atomic(output_path, payload)
    return payload


def validate_stable_session_preflight(
    configuration: Mapping[str, Any], report: Mapping[str, Any]
) -> ValidationReport:
    issues = []
    expected = {
        "schema": "ias.s4_2.stable_session_preflight.v1",
        "session_id": configuration["session"]["stable_preflight_id"],
        "status": "passed",
        "configuration_sha256": _stable_session_contract_sha256(configuration),
    }
    for key, value in expected.items():
        if report.get(key) != value:
            issues.append(
                {
                    "code": "stable_session_preflight_mismatch",
                    "path": key,
                    "message": f"expected {value!r}, got {report.get(key)!r}",
                }
            )
    invalidation_path = REPO_ROOT / str(
        configuration["session"]["stable_preflight_invalidation_path"]
    )
    if invalidation_path.exists():
        issues.append(
            {
                "code": "stable_session_preflight_invalidated",
                "path": str(invalidation_path),
                "message": "a replacement stable-session preflight is required",
            }
        )
    full = report.get("full_mac_preflight", {})
    mac_path = REPO_ROOT / str(configuration["mac"]["preflight_report_path"])
    if not mac_path.is_file() or full.get("sha256") != sha256_file(mac_path):
        issues.append(
            {
                "code": "stable_session_preflight_mismatch",
                "path": "full_mac_preflight",
                "message": "full Mac preflight is missing or its hash changed",
            }
        )
    else:
        mac_validation = validate_mac_preflight(
            load_json(mac_path), configuration, enforce_freshness=False
        )
        issues.extend(issue.to_dict() for issue in mac_validation.issues)
    gpu = report.get("nvidia_smi", {})
    if gpu.get("return_code") != 0:
        issues.append(
            {
                "code": "stable_session_gpu_unavailable",
                "path": "nvidia_smi.return_code",
                "message": repr(gpu.get("return_code")),
            }
        )
    typed = tuple(ValidationIssue(**issue) for issue in issues)
    passed = not any(issue.severity == "error" for issue in typed)
    return ValidationReport(
        (
            {
                "id": "stable_session_preflight",
                "status": "passed" if passed else "failed",
            },
        ),
        typed,
    )


def invalidate_stable_session_preflight(
    configuration: Mapping[str, Any], *, reason: str
) -> dict[str, Any]:
    """Write an immutable invalidation marker; never repair or overwrite it."""

    path = REPO_ROOT / str(
        configuration["session"]["stable_preflight_invalidation_path"]
    )
    if path.exists():
        return load_json(path)
    payload = {
        "schema": "ias.s4_2.stable_session_invalidation.v1",
        "session_id": configuration["session"]["stable_preflight_id"],
        "invalidated_wall_time_utc": _wall_utc(),
        "invalidated_monotonic_ns": time.monotonic_ns(),
        "reason": reason,
        "replacement_preflight_required": True,
    }
    write_json_atomic(path, payload)
    return payload


def preflight_hardware(
    configuration: Mapping[str, Any], attempt: AttemptLifecycle
) -> dict[str, Any]:
    """Run only lightweight per-take checks after stable-session validation."""

    local_disk = disk_space_check(
        attempt.root,
        int(configuration["session"]["minimum_local_free_bytes"]),
    )
    mac_dynamic = collect_mac_dynamic_preflight(
        configuration, attempt.root / "mac_dynamic_preflight.json"
    )
    payload = {
        "schema": "ias.s4_2.hardware_preflight.v1",
        "status": "passed",
        "local_disk": local_disk,
        "mac_dynamic": mac_dynamic,
        "removed_redundant_checks": [
            "three_round_trip_pi_ssh_timing",
            "three_round_trip_mac_ssh_timing",
            "separate_arecord_probe",
            "separate_zed_open_close_probe",
            "per_take_nvidia_smi",
        ],
        "producer_readiness_is_authoritative": True,
    }
    passed = local_disk["passed"] and mac_dynamic["status"] == "passed"
    payload["status"] = "passed" if passed else "failed"
    write_json_atomic(attempt.root / "hardware_preflight.json", payload)
    if not passed:
        invalidate_stable_session_preflight(
            configuration, reason="per-take dynamic Mac or local preflight failed"
        )
        raise S42Error("hardware preflight failed")
    return payload


def _wait_ready(
    processes: Mapping[str, subprocess.Popen[str]], timeout_s: float
) -> dict[str, dict[str, Any]]:
    selector = selectors.DefaultSelector()
    for name, process in processes.items():
        if process.stdout is None:
            raise S42Error(f"{name}: stdout pipe unavailable")
        selector.register(process.stdout, selectors.EVENT_READ, name)
    ready: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout_s
    while len(ready) < len(processes):
        if time.monotonic() >= deadline:
            raise S42Error(f"producer readiness timeout; ready={sorted(ready)}")
        for key, _ in selector.select(timeout=0.25):
            line = key.fileobj.readline()
            if not line:
                name = str(key.data)
                process = processes[name]
                raise S42Error(f"{name}: exited before readiness with {process.poll()}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise S42Error(f"{key.data}: invalid producer event: {line!r}") from exc
            if event.get("event") == "ready":
                event["observed_workstation_wall_time_utc"] = _wall_utc()
                event["observed_workstation_monotonic_ns"] = time.monotonic_ns()
                ready[str(key.data)] = event
    selector.close()
    return ready


def validate_producer_readiness(
    ready: Mapping[str, Mapping[str, Any]], configuration: Mapping[str, Any]
) -> ValidationReport:
    """Fail closed unless readiness came from both actual recorder instances."""

    issues: list[ValidationIssue] = []
    if set(ready) != {"pi", "zed"}:
        issues.append(
            ValidationIssue(
                "producer_readiness_missing",
                "producer_readiness",
                f"expected pi and zed readiness, got {sorted(ready)}",
            )
        )
    pi = ready.get("pi", {})
    zed_ready = ready.get("zed", {})
    expected_pi = {
        "verification_basis": "actual_recording_partial_wav_header",
        "identity.model": configuration["respeaker"]["usb_product"],
        "identity.serial": configuration["respeaker"]["serial"],
        "identity.firmware": configuration["respeaker"]["firmware"],
        "capture_format.channel_count": configuration["respeaker"]["channel_count"],
        "capture_format.sample_rate_hz": configuration["respeaker"]["sample_rate_hz"],
        "capture_format.sample_width_bytes": 2,
        "capture_format.compression": "NONE",
        "capture_format.encoding": "PCM_S16_LE",
    }
    expected_zed = {
        "verification_basis": "actual_recorder_open_and_retrieval",
        "identity.model": configuration["zed"]["model"],
        "identity.serial": configuration["zed"]["serial"],
        "identity.sdk_version": configuration["zed"]["sdk_version"],
        "identity.camera_firmware": configuration["zed"]["camera_firmware"],
        "identity.sensor_firmware": configuration["zed"]["sensor_firmware"],
        "requested_mode.resolution": configuration["zed"]["resolution"],
        "requested_mode.fps": configuration["zed"]["fps"],
        "requested_mode.depth_mode": configuration["zed"]["depth_mode"],
    }

    def value_at(payload: Mapping[str, Any], path: str) -> Any:
        value: Any = payload
        for part in path.split("."):
            if not isinstance(value, Mapping):
                return None
            value = value.get(part)
        return value

    for producer, payload, expected in (
        ("pi", pi, expected_pi),
        ("zed", zed_ready, expected_zed),
    ):
        for path, expected_value in expected.items():
            actual = value_at(payload, path)
            if actual != expected_value:
                issues.append(
                    ValidationIssue(
                        "producer_readiness_mismatch",
                        f"{producer}.{path}",
                        f"expected {expected_value!r}, got {actual!r}",
                    )
                )
        checks = payload.get("checks")
        if not isinstance(checks, Mapping) or not checks:
            issues.append(
                ValidationIssue(
                    "producer_readiness_missing_checks",
                    f"{producer}.checks",
                    "actual recorder must report non-empty startup checks",
                )
            )
        elif any(value is not True for value in checks.values()):
            failed = sorted(name for name, value in checks.items() if value is not True)
            issues.append(
                ValidationIssue(
                    "producer_readiness_failed_check",
                    f"{producer}.checks",
                    f"failed or non-boolean checks: {failed}",
                )
            )
    return ValidationReport(
        (
            {
                "id": "actual_recorder_readiness",
                "status": "passed" if not issues else "failed",
            },
        ),
        tuple(issues),
    )


def _wait_until_monotonic_ns(
    target_ns: int,
    *,
    monotonic_ns_function: Any = time.monotonic_ns,
    sleep_function: Any = time.sleep,
) -> None:
    while True:
        remaining_ns = target_ns - int(monotonic_ns_function())
        if remaining_ns <= 0:
            return
        sleep_function(remaining_ns / 1e9)


def _run_alignment_cue_schedule(
    configuration: Mapping[str, Any],
    attempt_root: Path,
    *,
    wall_function: Any = _wall_utc,
    monotonic_ns_function: Any = time.monotonic_ns,
    sleep_function: Any = time.sleep,
    print_function: Any = print,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Emit the strike/removal cues on monotonic deadlines and retain observations."""

    alignment = configuration["alignment"]
    cue_ns = int(monotonic_ns_function())
    cue = {
        "schema": "ias.s4_2.operator_cue.v1",
        "event": "ALIGNMENT_EVENT_NOW",
        "instruction": alignment["event_instruction"],
        "host_wall_time_utc": wall_function(),
        "host_monotonic_ns": cue_ns,
        "cue_mode": "fixed_post_readiness_monotonic_schedule",
        "cue_delay_s": float(alignment["cue_delay_s"]),
    }
    write_json_atomic(attempt_root / "operator_cue.json", cue)
    print_function("ALIGNMENT EVENT NOW\n" + str(cue["instruction"]), flush=True)

    remove_target_ns = cue_ns + round(float(alignment["remove_cue_delay_s"]) * 1e9)
    _wait_until_monotonic_ns(
        remove_target_ns,
        monotonic_ns_function=monotonic_ns_function,
        sleep_function=sleep_function,
    )
    remove_observed_ns = int(monotonic_ns_function())
    removal = {
        "schema": "ias.s4_2.operator_cue.v1",
        "event": "REMOVE_PAPER_ROLL_NOW",
        "instruction": alignment["remove_instruction"],
        "host_wall_time_utc": wall_function(),
        "host_monotonic_ns": remove_observed_ns,
        "scheduled_host_monotonic_ns": remove_target_ns,
        "scheduled_elapsed_from_alignment_s": float(alignment["remove_cue_delay_s"]),
        "observed_elapsed_from_alignment_s": (remove_observed_ns - cue_ns) / 1e9,
        "schedule_error_ms": (remove_observed_ns - remove_target_ns) / 1e6,
        "scheduled_playback_start_monotonic_ns": cue_ns
        + round(float(alignment["post_event_pre_playback_s"]) * 1e9),
    }
    write_json_atomic(attempt_root / "operator_remove_cue.json", removal)
    print_function("REMOVE PAPER ROLL NOW\n" + str(removal["instruction"]), flush=True)

    playback_target_ns = cue_ns + round(
        float(alignment["post_event_pre_playback_s"]) * 1e9
    )
    _wait_until_monotonic_ns(
        playback_target_ns,
        monotonic_ns_function=monotonic_ns_function,
        sleep_function=sleep_function,
    )
    return cue, removal


def _run_chat_cue_handshake(
    configuration: Mapping[str, Any],
    attempt_root: Path,
    *,
    input_function: Any = input,
    wall_function: Any = _wall_utc,
    monotonic_ns_function: Any = time.monotonic_ns,
    sleep_function: Any = time.sleep,
    print_function: Any = print,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Timestamp one chat cue and the authorized self-timed removal schedule."""

    alignment = configuration["alignment"]
    ready = {
        "schema": "ias.s4_2.chat_cue_handshake.v1",
        "status": "awaiting_alignment_chat_cue",
        "host_wall_time_utc": wall_function(),
        "host_monotonic_ns": int(monotonic_ns_function()),
        "instruction": (
            "operator acts only on the assistant's exact chat message; terminal "
            "or tool notifications are not action cues"
        ),
    }
    write_json_atomic(attempt_root / "chat_cue_handshake_ready.json", ready)
    print_function("CHAT CUE HANDSHAKE READY; WAIT FOR CHAT", flush=True)
    _read_chat_ack(
        "After sending ALIGNMENT EVENT NOW in chat, press ENTER to timestamp "
        "the chat-cue acknowledgment: ",
        timeout_s=float(configuration["session"]["chat_cue_ack_timeout_s"]),
        input_function=input_function,
    )
    cue_ns = int(monotonic_ns_function())
    cue = {
        "schema": "ias.s4_2.operator_cue.v1",
        "event": "ALIGNMENT_EVENT_NOW",
        "instruction": alignment["event_instruction"],
        "host_wall_time_utc": wall_function(),
        "host_monotonic_ns": cue_ns,
        "cue_mode": "assistant_chat_message_with_workstation_acknowledgment",
        "timestamp_basis": "PTY acknowledgment immediately after chat cue",
        "cue_delay_s": float(alignment["cue_delay_s"]),
        "chat_ack_timeout_s": float(configuration["session"]["chat_cue_ack_timeout_s"]),
    }
    write_json_atomic(attempt_root / "operator_cue.json", cue)
    removal_target_ns = cue_ns + round(float(alignment["remove_cue_delay_s"]) * 1e9)
    write_json_atomic(
        attempt_root / "chat_removal_cue_target.json",
        {
            "schema": "ias.s4_2.chat_cue_target.v1",
            "event": "REMOVE_PAPER_ROLL_NOW",
            "target_host_monotonic_ns": removal_target_ns,
            "delay_from_alignment_ack_s": float(alignment["remove_cue_delay_s"]),
            "operator_procedure": "self_timed_without_second_chat_cue",
        },
    )
    _wait_until_monotonic_ns(
        removal_target_ns,
        monotonic_ns_function=monotonic_ns_function,
        sleep_function=sleep_function,
    )
    removal_ns = int(monotonic_ns_function())
    playback_target_ns = cue_ns + round(
        float(alignment["post_event_pre_playback_s"]) * 1e9
    )
    removal = {
        "schema": "ias.s4_2.operator_cue.v1",
        "event": "SELF_TIMED_PAPER_ROLL_REMOVAL_TARGET",
        "instruction": alignment["remove_instruction"],
        "host_wall_time_utc": wall_function(),
        "host_monotonic_ns": removal_ns,
        "scheduled_host_monotonic_ns": removal_target_ns,
        "scheduled_elapsed_from_alignment_s": float(alignment["remove_cue_delay_s"]),
        "observed_elapsed_from_alignment_s": (removal_ns - cue_ns) / 1e9,
        "schedule_error_ms": (removal_ns - removal_target_ns) / 1e6,
        "cue_mode": "operator_authorized_self_timed_from_alignment_chat_cue",
        "timestamp_basis": (
            "workstation scheduled target; operator removal is not automatically "
            "observed"
        ),
        "operator_action_observation": "operator-confirmed procedure, unobserved",
        "scheduled_playback_start_monotonic_ns": playback_target_ns,
    }
    write_json_atomic(attempt_root / "operator_remove_cue.json", removal)
    print_function(
        "SELF-TIMED REMOVAL TARGET REACHED; no chat action is required", flush=True
    )
    _wait_until_monotonic_ns(
        playback_target_ns,
        monotonic_ns_function=monotonic_ns_function,
        sleep_function=sleep_function,
    )
    return cue, removal


def _read_chat_ack(
    prompt: str,
    *,
    timeout_s: float,
    input_function: Any = input,
) -> None:
    """Read one PTY acknowledgment and fail closed after the declared timeout."""

    if timeout_s <= 0.0:
        raise S42Error("chat-cue acknowledgment timeout must be positive")
    if input_function is not input:
        input_function(prompt)
        return
    print(prompt, end="", flush=True)
    selector = selectors.DefaultSelector()
    try:
        selector.register(sys.stdin, selectors.EVENT_READ)
        if not selector.select(timeout=timeout_s):
            raise S42Error(f"chat-cue acknowledgment exceeded {timeout_s:.3f} seconds")
        if sys.stdin.readline() == "":
            raise S42Error("chat-cue acknowledgment input closed")
    finally:
        selector.close()


def _resolve_operator_readiness(
    interactive: bool, *, input_function: Any = input
) -> dict[str, Any]:
    """Resolve human readiness before starting either bounded recorder."""

    started_wall = _wall_utc()
    started_ns = time.monotonic_ns()
    if interactive:
        try:
            input_function(
                "Confirm the scene is clear and the impact tool is ready, then "
                "press ENTER to start the bounded recorders: "
            )
        except EOFError as exc:
            raise S42Error("interactive operator readiness input closed") from exc
    return {
        "schema": "ias.s4_2.operator_readiness.v1",
        "status": "resolved",
        "mode": "interactive_stdin" if interactive else "preconfirmed_noninteractive",
        "started_wall_time_utc": started_wall,
        "resolved_wall_time_utc": _wall_utc(),
        "started_monotonic_ns": started_ns,
        "resolved_monotonic_ns": time.monotonic_ns(),
        "bounded_capture_started_after_resolution": True,
    }


def _run_svo_replay(
    configuration: Mapping[str, Any],
    svo_path: Path,
    output_path: Path,
    *,
    expected_frame_count: int,
) -> tuple[dict[str, Any], Any]:
    zed = configuration["zed"]
    observation = _run(
        [
            sys.executable,
            str(ZED_SVO_VALIDATOR_LOCAL),
            str(svo_path),
            "--output",
            str(output_path),
            "--expected-serial",
            str(zed["serial"]),
            "--resolution",
            str(zed["resolution"]),
            "--fps",
            str(zed["fps"]),
            "--depth-mode",
            str(zed["depth_mode"]),
        ],
        timeout=180,
        cwd=REPO_ROOT,
    )
    report = load_json(output_path)
    validation = validate_svo_replay_report(
        report,
        expected_serial=str(zed["serial"]),
        expected_resolution=str(zed["resolution"]),
        expected_fps=int(zed["fps"]),
        expected_depth_mode=str(zed["depth_mode"]),
        expected_frame_count=expected_frame_count,
        frame_count_policy=str(
            configuration["validation_profile"]["svo_frame_count_policy"]
        ),
        required_modalities=configuration["validation_profile"]["required_modalities"],
    )
    if observation["return_code"] != 0 and validation.passed:
        raise S42Error("SVO replay process failed despite a passing report")
    return {"command": observation, "report": report}, validation


def _start_playback(configuration: Mapping[str, Any]) -> subprocess.Popen[str]:
    mac = configuration["mac"]
    reference_path = str(mac["reference_path"])
    gain = float(mac["afplay_gain"])
    remote_python = (
        "import datetime,json,subprocess,time; "
        "s=time.monotonic_ns(); "
        "w=datetime.datetime.now(datetime.timezone.utc).isoformat(); "
        f"c=['/usr/bin/afplay','-v',{str(gain)!r},{reference_path!r}]; "
        "p=subprocess.run(c,check=False); "
        "print(json.dumps({'command':c,'started_wall_time_utc':w,"
        "'started_monotonic_ns':s,'completed_wall_time_utc':"
        "datetime.datetime.now(datetime.timezone.utc).isoformat(),"
        "'completed_monotonic_ns':time.monotonic_ns(),"
        "'exit_status':p.returncode}))"
    )
    remote = "/usr/bin/python3 -c " + shlex.quote(remote_python)
    return subprocess.Popen(  # noqa: S603 - explicit SSH argv
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            str(mac["ssh_alias"]),
            remote,
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _terminate_process(process: subprocess.Popen[str], name: str) -> dict[str, Any]:
    if process.poll() is not None:
        return {
            "name": name,
            "action": "already_exited",
            "return_code": process.returncode,
        }
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=5)
        return {"name": name, "action": "sigint", "return_code": process.returncode}
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        return {"name": name, "action": "sigkill", "return_code": process.returncode}


def _retrieve_pi(
    configuration: Mapping[str, Any], attempt: AttemptLifecycle
) -> dict[str, Any]:
    pi = configuration["respeaker"]
    remote_attempt = f"{pi['remote_attempt_root']}/{attempt.attempt_id}"
    incoming = attempt.root / "_incoming/pi"
    incoming.mkdir(parents=True, exist_ok=False)
    observations: list[dict[str, Any]] = []
    for filename in ("producer_status.json", "respeaker_audio.wav"):
        destination = incoming / filename
        source = f"{pi['ssh_alias']}:{remote_attempt}/{filename}"
        result = _run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                source,
                str(destination),
            ],
            timeout=120,
            cwd=REPO_ROOT,
        )
        observations.append(result)
        if result["return_code"] != 0:
            raise S42Error(f"partial Pi transfer: {filename}")
    status = load_json(incoming / "producer_status.json")
    if status.get("status") != "complete":
        raise S42Error(f"Pi producer did not finalize: {status.get('reason')}")
    if sha256_file(incoming / "respeaker_audio.wav") != status.get("sha256"):
        raise S42Error("Pi WAV transfer checksum mismatch")
    return {"status": status, "observations": observations, "incoming": incoming}


def _write_manifest(
    attempt: AttemptLifecycle,
    configuration: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    *,
    status: str,
    limitations: Sequence[str],
) -> dict[str, Any]:
    payload = {
        "schema": ATTEMPT_SCHEMA,
        "attempt_id": attempt.attempt_id,
        "lifecycle_status": status,
        "configuration_schema": configuration["schema"],
        "normalized_configuration": dict(configuration),
        "acceptance_amendment": dict(configuration["acceptance_amendment"]),
        "coordinate_correction": dict(configuration["coordinate_correction"]),
        "coordinate_frame": dict(configuration["coordinate_frame"]),
        "operator_facing_frame": dict(configuration["operator_facing_frame"]),
        "source_geometry": dict(configuration["source"]),
        "raw_evidence_policy": dict(configuration["raw_evidence"]),
        "created_at_utc": _wall_utc(),
        "artifacts": list(artifacts),
        "limitations": [
            *list(limitations),
            "raw evidence exists only under dataset/S4.2 on this workstation",
            "raw evidence is not replicated or available from a fresh clone",
            "workstation loss can make the raw evidence unavailable",
        ],
        "unsupported_claims": [
            "sample-accurate synchronization",
            "absolute capture latency",
            "acoustic time-of-flight",
            "calibrated optical-acoustic extrinsics",
            "universal source-room-device transfer",
            "off-machine or replicated S4.2 raw retention",
            "S4.2 raw availability after workstation loss",
            "S4.2 raw availability from a fresh clone",
            "independent review of absent machine-local raw evidence",
        ],
        "ssh_timing_is_synchronization": False,
    }
    write_json_atomic(attempt.root / "manifest.json", payload)
    return payload


def run_capture(
    configuration: Mapping[str, Any],
    *,
    attempt_id: str | None = None,
    interactive_cue: bool = False,
    chat_cue_handshake: bool = False,
) -> dict[str, Any]:
    """Run a bounded capture and stop at the manual alignment-annotation gate."""

    config_report = validate_configuration(configuration, require_ready=True)
    if not config_report.passed:
        raise S42Error(
            f"configuration failed before hardware: {config_report.to_dict()}"
        )
    reference_path = REPO_ROOT / str(configuration["reference"]["local_path"])
    metadata_path = REPO_ROOT / str(configuration["reference"]["metadata_path"])
    inventory_path = REPO_ROOT / str(configuration["mac"]["inventory_path"])
    amendment_path = REPO_ROOT / str(
        configuration["acceptance_amendment"]["record_path"]
    )
    coordinate_correction_path = REPO_ROOT / str(
        configuration["coordinate_correction"]["record_path"]
    )
    superseded_coordinate_correction_path = REPO_ROOT / str(
        configuration["coordinate_correction"]["superseded_record_path"]
    )
    if (
        not reference_path.is_file()
        or not metadata_path.is_file()
        or not inventory_path.is_file()
        or not amendment_path.is_file()
        or not coordinate_correction_path.is_file()
        or not superseded_coordinate_correction_path.is_file()
    ):
        raise S42Error(
            "reference WAV, metadata, Mac inventory, acceptance amendment, or "
            "coordinate correction or retained superseded correction is missing"
        )
    if sha256_file(reference_path) != configuration["reference"]["sha256"]:
        raise S42Error("reference WAV checksum mismatch")
    if sha256_file(inventory_path) != configuration["mac"]["inventory_sha256"]:
        raise S42Error("Mac inventory checksum mismatch")
    if (
        sha256_file(amendment_path)
        != configuration["acceptance_amendment"]["record_sha256"]
    ):
        raise S42Error("pre-capture acceptance amendment checksum mismatch")
    if (
        sha256_file(coordinate_correction_path)
        != configuration["coordinate_correction"]["record_sha256"]
    ):
        raise S42Error("dual-frame coordinate reconciliation checksum mismatch")
    if (
        sha256_file(superseded_coordinate_correction_path)
        != configuration["coordinate_correction"]["superseded_record_sha256"]
    ):
        raise S42Error("superseded coordinate correction checksum mismatch")
    session_report_path = REPO_ROOT / str(
        configuration["session"]["stable_preflight_report_path"]
    )
    session_report = load_json(session_report_path)
    session_validation = validate_stable_session_preflight(
        configuration, session_report
    )
    if not session_validation.passed:
        raise S42Error(
            f"stable-session preflight mismatch: {session_validation.to_dict()}"
        )
    mac_report_path = REPO_ROOT / str(configuration["mac"]["preflight_report_path"])
    mac_report = load_json(mac_report_path)

    attempts_root = REPO_ROOT / str(configuration["session"]["attempt_root"])
    attempt = AttemptLifecycle(attempts_root, attempt_id=attempt_id)
    attempt.write_configuration(configuration)
    write_json_atomic(attempt.root / "stable_session_preflight.json", session_report)
    write_json_atomic(attempt.root / "mac_preflight.json", mac_report)
    write_json_atomic(attempt.root / "reference_wav.json", load_json(metadata_path))
    write_json_atomic(
        attempt.root / "mac_source_inventory.json", load_json(inventory_path)
    )
    write_json_atomic(
        attempt.root / "pre_capture_acceptance_amendment.json",
        load_json(amendment_path),
    )
    write_json_atomic(
        attempt.root / "dual_frame_coordinate_reconciliation.json",
        load_json(coordinate_correction_path),
    )
    write_json_atomic(
        attempt.root / "superseded_post_capture_coordinate_correction.json",
        load_json(superseded_coordinate_correction_path),
    )
    processes: dict[str, subprocess.Popen[str]] = {}
    cleanup: list[dict[str, Any]] = []
    try:
        preflight_hardware(configuration, attempt)
        print(
            "WARNING: after readiness is confirmed, both bounded recorders will "
            "start. Do not strike the alignment object until instructed.",
            flush=True,
        )
        operator_readiness = _resolve_operator_readiness(interactive_cue)
        write_json_atomic(attempt.root / "operator_readiness.json", operator_readiness)
        producer_root = attempt.root / "_producer"
        zed_output = producer_root / "zed"
        zed_output.mkdir(parents=True, exist_ok=False)
        zed = configuration["zed"]
        duration = int(configuration["session"]["duration_s"])
        zed_process = subprocess.Popen(  # noqa: S603 - explicit argv
            [
                sys.executable,
                str(ZED_CAPTURE_LOCAL),
                "--duration",
                str(duration),
                "--output-dir",
                str(zed_output),
                "--expected-serial",
                str(zed["serial"]),
                "--expected-sdk",
                str(zed["sdk_version"]),
                "--expected-camera-firmware",
                str(zed["camera_firmware"]),
                "--expected-sensor-firmware",
                str(zed["sensor_firmware"]),
                "--resolution",
                str(zed["resolution"]),
                "--fps",
                str(zed["fps"]),
                "--depth-mode",
                str(zed["depth_mode"]),
                "--minimum-usb-speed-mbps",
                str(zed["usb_minimum_speed_mbps"]),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        processes["zed"] = zed_process
        pi = configuration["respeaker"]
        remote_attempt = f"{pi['remote_attempt_root']}/{attempt.attempt_id}"
        remote_command = (
            f"/usr/bin/python3 {shlex.quote(PI_HELPER_REMOTE)} record "
            f"--attempt {shlex.quote(remote_attempt)} "
            f"--device {shlex.quote(str(pi['device']))} --duration {duration} "
            "--minimum-free-bytes "
            f"{int(configuration['session']['minimum_pi_free_bytes'])}"
        )
        pi_process = subprocess.Popen(  # noqa: S603 - explicit SSH argv
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                str(pi["ssh_alias"]),
                remote_command,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        processes["pi"] = pi_process
        ready = _wait_ready(processes, timeout_s=20)
        write_json_atomic(attempt.root / "producer_readiness.json", ready)
        readiness_validation = validate_producer_readiness(ready, configuration)
        write_json_atomic(
            attempt.root / "producer_readiness_validation.json",
            readiness_validation.to_dict(),
        )
        if not readiness_validation.passed:
            raise S42Error(
                "actual recorder readiness contract failed: "
                f"{readiness_validation.to_dict()}"
            )
        attempt.transition(
            "recording", reason="actual Pi and ZED recorders verified and ready"
        )
        print(
            "WARNING: S4.2 recording is active. The alignment cue will follow "
            "after the frozen lead time. Do not strike yet.",
            flush=True,
        )
        time.sleep(float(configuration["alignment"]["cue_delay_s"]))
        if chat_cue_handshake:
            _run_chat_cue_handshake(configuration, attempt.root)
        else:
            _run_alignment_cue_schedule(configuration, attempt.root)
        alive_before = {name: processes[name].poll() is None for name in ("pi", "zed")}
        playback_started_wall = _wall_utc()
        playback_started_ns = time.monotonic_ns()
        playback = _start_playback(configuration)
        processes["mac_playback"] = playback
        playback_stdout, playback_stderr = playback.communicate(timeout=20)
        playback_record = {
            "return_code": playback.returncode,
            "stdout": playback_stdout,
            "stderr": playback_stderr,
        }
        try:
            playback_record["remote"] = json.loads(playback_stdout)
        except json.JSONDecodeError:
            playback_record["remote"] = None
        if playback.returncode != 0:
            write_json_atomic(attempt.root / "playback.json", playback_record)
            raise S42Error("Mac reference playback failed")
        alive_after = {name: processes[name].poll() is None for name in ("pi", "zed")}
        time.sleep(float(configuration["session"]["post_playback_margin_s"]))
        alive_after_margin = {
            name: processes[name].poll() is None for name in ("pi", "zed")
        }
        playback_record["workstation_envelope"] = {
            "started_wall_time_utc": playback_started_wall,
            "completed_wall_time_utc": _wall_utc(),
            "started_monotonic_ns": playback_started_ns,
            "completed_monotonic_ns": time.monotonic_ns(),
            "post_playback_margin_s": float(
                configuration["session"]["post_playback_margin_s"]
            ),
            "recorders_alive": {
                "before_playback": alive_before,
                "after_playback": alive_after,
                "after_post_margin": alive_after_margin,
            },
            "claim": (
                "workstation process-liveness envelope; SSH timing is not "
                "cross-host synchronization"
            ),
        }
        write_json_atomic(attempt.root / "playback.json", playback_record)
        all_alive = (
            *alive_before.values(),
            *alive_after.values(),
            *alive_after_margin.values(),
        )
        if not all(all_alive):
            raise S42Error("recorders did not contain complete playback and margin")
        for name in ("pi", "zed"):
            process = processes[name]
            try:
                process.wait(timeout=duration + 20)
            except subprocess.TimeoutExpired as exc:
                raise S42Error(f"{name} producer timeout") from exc
            if process.returncode != 0:
                stdout = process.stdout.read() if process.stdout else ""
                stderr = process.stderr.read() if process.stderr else ""
                write_json_atomic(
                    attempt.root / f"{name}_producer_failure.json",
                    {
                        "return_code": process.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                )
                raise S42Error(f"{name} producer exited with {process.returncode}")
        attempt.transition("finalizing", reason="all local producers finalized")
        pi_retrieval = _retrieve_pi(configuration, attempt)
        raw = attempt.root / "raw"
        records: list[dict[str, Any]] = []
        promotions = (
            (
                pi_retrieval["incoming"] / "respeaker_audio.wav",
                raw / "respeaker_audio.wav",
                "six_channel_audio",
            ),
            (
                pi_retrieval["incoming"] / "producer_status.json",
                raw / "pi_producer_status.json",
                "pi_producer_status",
            ),
            (zed_output / "capture.svo2", raw / "zed_capture.svo2", "zed_svo2"),
            (
                zed_output / "frames.jsonl",
                raw / "zed_frames.jsonl",
                "zed_frame_records",
            ),
            (
                zed_output / "producer_summary.json",
                raw / "zed_producer_summary.json",
                "zed_producer_status",
            ),
        )
        for source, destination, role in promotions:
            promote_finalized_file(source, destination)
            records.append(artifact_record(destination, role=role, root=attempt.root))
        audio_properties, audio_issues = inspect_six_channel_wav(
            raw / "respeaker_audio.wav",
            expected_duration_s=float(configuration["session"]["duration_s"]),
            duration_tolerance_s=float(
                configuration["session"]["duration_tolerance_s"]
            ),
            require_nonsilent_channels=configuration["validation_profile"][
                "channel_signal_policy"
            ]
            == "all_channels_nonsilent",
            reject_sustained_clipping=configuration["validation_profile"][
                "clipping_policy"
            ]
            == "reject_sustained",
        )
        zed_records, jsonl_issues = read_jsonl(raw / "zed_frames.jsonl")
        zed_validation = validate_zed_records(
            zed_records,
            duration_s=float(configuration["session"]["duration_s"]),
            fps=int(configuration["zed"]["fps"]),
            validation_profile=configuration["validation_profile"],
        )
        reference_validation = validate_reference_capture(
            raw / "respeaker_audio.wav",
            reference_path,
            minimum_normalized_correlation=float(
                configuration["reference"]["minimum_normalized_correlation"]
            ),
            minimum_correlated_raw_channels=int(
                configuration["reference"]["minimum_correlated_raw_channels"]
            ),
        )
        overlap_validation = validate_playback_capture_overlap(
            playback_record,
            zed_records,
            reference_duration_s=float(configuration["reference"]["duration_s"]),
            playback_duration_tolerance_s=float(
                configuration["reference"]["playback_duration_tolerance_s"]
            ),
        )
        combined_issues = (
            *audio_issues,
            *jsonl_issues,
            *zed_validation.issues,
            *reference_validation.issues,
            *overlap_validation.issues,
        )
        capture_validation = {
            "schema": "ias.s4_2.capture_validation.v1",
            "status": "passed" if not combined_issues else "failed",
            "audio_properties": audio_properties,
            "issues": [issue.to_dict() for issue in combined_issues],
            "zed": zed_validation.to_dict(),
            "svo_replay": {
                "status": "deferred_to_offline_finalization",
                "policy": configuration["validation_profile"]["svo_replay_policy"],
                "stage": configuration["validation_profile"]["svo_replay_stage"],
            },
            "reference_capture": reference_validation.to_dict(),
            "playback_capture_overlap": overlap_validation.to_dict(),
        }
        write_json_atomic(attempt.root / "capture_validation.json", capture_validation)
        if capture_validation["status"] != "passed":
            raise S42Error("captured evidence failed semantic validation")
        for record in records:
            if record["role"] == "six_channel_audio":
                record["media_properties"] = audio_properties
            elif record["role"] == "zed_svo2":
                record["media_properties"] = {
                    "container": "SVO2",
                    "compression": "H265",
                    "resolution": configuration["zed"]["resolution"],
                    "fps": configuration["zed"]["fps"],
                    "depth_mode": configuration["zed"]["depth_mode"],
                    "depth_reconstruction": (
                        "replay frozen stereo SVO2 with ZED SDK and recorded mode"
                    ),
                }
            elif record["role"] == "zed_frame_records":
                record["media_properties"] = {
                    "encoding": "UTF-8 JSONL",
                    "schema": "ias.s4_2.zed_frame.v1",
                    "record_count": len(zed_records),
                    "contains": [
                        "image signatures",
                        "sampled depth grids in meters",
                        "IMU",
                        "device/host timestamps",
                        "tracking pose/state",
                    ],
                }
        records.extend(
            artifact_record(path, role=role, root=attempt.root)
            for path, role in (
                (attempt.root / "normalized_configuration.json", "configuration"),
                (attempt.root / "mac_preflight.json", "mac_preflight"),
                (
                    attempt.root / "stable_session_preflight.json",
                    "stable_session_preflight",
                ),
                (
                    attempt.root / "mac_dynamic_preflight.json",
                    "mac_dynamic_preflight",
                ),
                (attempt.root / "reference_wav.json", "reference_metadata"),
                (attempt.root / "mac_source_inventory.json", "mac_source_inventory"),
                (
                    attempt.root / "pre_capture_acceptance_amendment.json",
                    "pre_capture_acceptance_amendment",
                ),
                (
                    attempt.root / "dual_frame_coordinate_reconciliation.json",
                    "dual_frame_coordinate_reconciliation",
                ),
                (
                    attempt.root / "superseded_post_capture_coordinate_correction.json",
                    "superseded_post_capture_coordinate_correction",
                ),
                (attempt.root / "hardware_preflight.json", "hardware_preflight"),
                (attempt.root / "producer_readiness.json", "producer_readiness"),
                (
                    attempt.root / "producer_readiness_validation.json",
                    "producer_readiness_validation",
                ),
                (attempt.root / "operator_readiness.json", "operator_readiness"),
                (attempt.root / "operator_cue.json", "operator_cue"),
                (
                    attempt.root / "operator_remove_cue.json",
                    "operator_remove_cue",
                ),
                *(
                    (
                        (
                            attempt.root / "chat_cue_handshake_ready.json",
                            "chat_cue_handshake_ready",
                        ),
                        (
                            attempt.root / "chat_removal_cue_target.json",
                            "chat_removal_cue_target",
                        ),
                    )
                    if chat_cue_handshake
                    else ()
                ),
                (attempt.root / "playback.json", "playback_record"),
                (attempt.root / "capture_validation.json", "capture_validation"),
            )
        )
        _write_manifest(
            attempt,
            configuration,
            records,
            status="finalizing",
            limitations=["awaiting manual visible/audible alignment annotation"],
        )
        records.append(
            artifact_record(
                attempt.root / "manifest.json",
                role="attempt_manifest",
                root=attempt.root,
            )
        )
        write_checksums(attempt.root / "SHA256SUMS", attempt.root, records)
        return {
            "status": "awaiting_alignment_annotation",
            "attempt_id": attempt.attempt_id,
            "attempt_root": str(attempt.root),
            "audio_properties": audio_properties,
            "zed_record_count": len(zed_records),
        }
    except KeyboardInterrupt:
        for name, process in processes.items():
            cleanup.append(_terminate_process(process, name))
        if attempt.state not in {"accepted", "rejected", "failed", "interrupted"}:
            attempt.transition("interrupted", reason="operator interruption")
        write_json_atomic(attempt.root / "cleanup.json", {"actions": cleanup})
        raise
    except BaseException as exc:
        for name, process in processes.items():
            cleanup.append(_terminate_process(process, name))
        if "pi" in processes:
            pi = configuration["respeaker"]
            remote_attempt = f"{pi['remote_attempt_root']}/{attempt.attempt_id}"
            stop_command = (
                f"/usr/bin/python3 {shlex.quote(PI_HELPER_REMOTE)} stop "
                f"--attempt {shlex.quote(remote_attempt)}"
            )
            cleanup.append(
                {
                    "name": "pi_remote_stop",
                    "observation": _ssh(str(pi["ssh_alias"]), stop_command, timeout=15),
                }
            )
        if attempt.state not in {"accepted", "rejected", "failed", "interrupted"}:
            if attempt.state == "preflight":
                invalidate_stable_session_preflight(
                    configuration,
                    reason=f"recorder startup or per-take preflight error: {exc}",
                )
            attempt.transition("failed", reason=f"{type(exc).__name__}: {exc}")
        write_json_atomic(attempt.root / "cleanup.json", {"actions": cleanup})
        raise


def finalize_attempt(attempt_root: str | Path) -> dict[str, Any]:
    """Revalidate retained media and accept without trusting stored pass labels."""

    attempt = AttemptLifecycle.open_existing(attempt_root)
    if attempt.state != "finalizing":
        raise S42Error(f"attempt state must be finalizing, got {attempt.state}")
    configuration = load_json(attempt.root / "normalized_configuration.json")
    config_report = validate_configuration(configuration, require_ready=True)
    alignment = load_json(attempt.root / "alignment.json")
    event_confirmation = load_json(attempt.root / "event_observation_confirmation.json")
    manifest = load_json(attempt.root / "manifest.json")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise S42Error("manifest.artifacts must be a list")
    integrity = verify_artifact_records(attempt.root, records)
    issues: list[dict[str, Any]] = []
    if not config_report.passed:
        issues.extend(issue.to_dict() for issue in config_report.issues)
    raw = attempt.root / "raw"
    audio_properties, audio_issues = inspect_six_channel_wav(
        raw / "respeaker_audio.wav",
        expected_duration_s=float(configuration["session"]["duration_s"]),
        duration_tolerance_s=float(configuration["session"]["duration_tolerance_s"]),
        require_nonsilent_channels=configuration["validation_profile"][
            "channel_signal_policy"
        ]
        == "all_channels_nonsilent",
        reject_sustained_clipping=configuration["validation_profile"]["clipping_policy"]
        == "reject_sustained",
    )
    zed_records, jsonl_issues = read_jsonl(raw / "zed_frames.jsonl")
    zed_validation = validate_zed_records(
        zed_records,
        duration_s=float(configuration["session"]["duration_s"]),
        fps=int(configuration["zed"]["fps"]),
        validation_profile=configuration["validation_profile"],
    )
    reference_validation = validate_reference_capture(
        raw / "respeaker_audio.wav",
        REPO_ROOT / str(configuration["reference"]["local_path"]),
        minimum_normalized_correlation=float(
            configuration["reference"]["minimum_normalized_correlation"]
        ),
        minimum_correlated_raw_channels=int(
            configuration["reference"]["minimum_correlated_raw_channels"]
        ),
    )
    overlap_validation = validate_playback_capture_overlap(
        load_json(attempt.root / "playback.json"),
        zed_records,
        reference_duration_s=float(configuration["reference"]["duration_s"]),
        playback_duration_tolerance_s=float(
            configuration["reference"]["playback_duration_tolerance_s"]
        ),
    )
    svo_replay, svo_validation = _run_svo_replay(
        configuration,
        raw / "zed_capture.svo2",
        attempt.root / "svo_replay_finalization_validation.json",
        expected_frame_count=len(zed_records),
    )
    recomputed_alignment, alignment_validation = recompute_alignment_from_evidence(
        alignment,
        raw / "respeaker_audio.wav",
        zed_records,
        configuration,
    )
    write_json_atomic(attempt.root / "alignment_recomputed.json", recomputed_alignment)
    for report in (
        ValidationReport((), audio_issues),
        ValidationReport((), jsonl_issues),
        zed_validation,
        reference_validation,
        overlap_validation,
        svo_validation,
        alignment_validation,
    ):
        issues.extend(issue.to_dict() for issue in report.issues)
    if event_confirmation.get("schema") != (
        "ias.s4_2.event_observation_confirmation.v1"
    ) or any(
        event_confirmation.get(field) is not True
        for field in (
            "operator_confirmed",
            "event_unique",
            "event_audible",
            "no_person_or_hand_in_reviewed_frames",
            "no_unexpected_mac_or_ui_sound",
        )
    ):
        issues.append(
            {
                "code": "event_observation_confirmation_failed",
                "path": "event_observation_confirmation.json",
                "message": (
                    "required operator/privacy/audio confirmations are incomplete"
                ),
                "severity": "error",
            }
        )
    if not integrity.passed:
        issues.extend(issue.to_dict() for issue in integrity.issues)
    finalization_validation = {
        "schema": "ias.s4_2.finalization_validation.v1",
        "status": "passed" if not issues else "failed",
        "audio_properties": audio_properties,
        "zed_records": zed_validation.to_dict(),
        "svo_replay": {
            "process": svo_replay["command"],
            "report": svo_replay["report"],
            "validation": svo_validation.to_dict(),
        },
        "reference_capture": reference_validation.to_dict(),
        "playback_capture_overlap": overlap_validation.to_dict(),
        "alignment_recomputation": alignment_validation.to_dict(),
        "issues": issues,
    }
    write_json_atomic(
        attempt.root / "finalization_validation.json", finalization_validation
    )
    gate = {
        "schema": "ias.s4_2.attempt_gate.v1",
        "status": "passed" if not issues else "failed",
        "attempt_id": attempt.attempt_id,
        "configuration": config_report.to_dict(),
        "alignment_annotation": alignment,
        "alignment_recomputed": recomputed_alignment,
        "finalization_validation": finalization_validation,
        "event_observation_confirmation": event_confirmation,
        "artifact_integrity": integrity.to_dict(),
        "issues": issues,
    }
    write_json_atomic(attempt.root / "gate.json", gate)
    if issues:
        attempt.transition("rejected", reason="final S4.2 attempt gate failed")
        return gate
    new_records = list(records)
    for path, role in (
        (attempt.root / "alignment.json", "alignment_report"),
        (attempt.root / "alignment_recomputed.json", "alignment_recomputed"),
        (
            attempt.root / "svo_replay_finalization_validation.json",
            "svo_replay_finalization_validation",
        ),
        (
            attempt.root / "finalization_validation.json",
            "finalization_validation",
        ),
        (attempt.root / "gate.json", "attempt_gate"),
        (
            attempt.root / "event_observation_confirmation.json",
            "event_observation_confirmation",
        ),
    ):
        new_records.append(artifact_record(path, role=role, root=attempt.root))
    _write_manifest(
        attempt,
        configuration,
        new_records,
        status="accepted",
        limitations=list(alignment.get("unsupported_claims", [])),
    )
    checksum_records = list(new_records)
    checksum_records.append(
        artifact_record(
            attempt.root / "manifest.json",
            role="attempt_manifest",
            root=attempt.root,
        )
    )
    write_checksums(
        attempt.root / "SHA256SUMS",
        attempt.root,
        checksum_records,
    )
    attempt.transition("accepted", reason="all frozen S4.2 attempt gates passed")
    return gate


__all__ = [
    "collect_mac_dynamic_preflight",
    "collect_mac_preflight",
    "collect_stable_session_preflight",
    "deploy_helpers_and_reference",
    "finalize_attempt",
    "invalidate_stable_session_preflight",
    "preflight_hardware",
    "run_capture",
    "validate_producer_readiness",
    "validate_stable_session_preflight",
]
