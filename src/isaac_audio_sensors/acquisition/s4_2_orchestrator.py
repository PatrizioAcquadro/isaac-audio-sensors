"""Maintained workstation-side S4.2 acquisition orchestration."""

from __future__ import annotations

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
    artifact_record,
    disk_space_check,
    inspect_six_channel_wav,
    load_json,
    promote_finalized_file,
    read_jsonl,
    sha256_file,
    validate_configuration,
    validate_mac_preflight,
    validate_zed_records,
    verify_artifact_records,
    write_checksums,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

REPO_ROOT = Path(__file__).resolve().parents[3]
PI_HELPER_LOCAL = REPO_ROOT / "scripts/s4_2_pi_capture.py"
MAC_HELPER_LOCAL = REPO_ROOT / "scripts/s4_2_mac_preflight.py"
ZED_PREFLIGHT_LOCAL = REPO_ROOT / "scripts/preflight_s4_2_zed.py"
ZED_CAPTURE_LOCAL = REPO_ROOT / "scripts/run_s4_2_zed_capture.py"
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
        f"--expected-sha256 {shlex.quote(str(reference['sha256']))}"
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
    return {
        "report": payload,
        "command": observation,
        "status": "passed" if observation["return_code"] == 0 else "failed",
    }


def _ssh_timing(alias: str, count: int = 3) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    remote = "/usr/bin/python3 -c " + shlex.quote(
        "import datetime,json,time; "
        "print(json.dumps({'remote_wall_time_utc':"
        "datetime.datetime.now(datetime.timezone.utc).isoformat(),"
        "'remote_monotonic_ns':time.monotonic_ns()}))"
    )
    for _ in range(count):
        result = _ssh(alias, remote, timeout=15)
        observations.append(result)
    return {
        "alias": alias,
        "claim": "SSH round-trip observation only; not host synchronization",
        "synchronization_claim": False,
        "observations": observations,
        "passed": all(result["return_code"] == 0 for result in observations),
    }


def _pi_preflight(configuration: Mapping[str, Any]) -> dict[str, Any]:
    pi = configuration["respeaker"]
    remote = (
        f"/usr/bin/python3 {shlex.quote(PI_HELPER_REMOTE)} preflight "
        f"--root {shlex.quote(str(pi['remote_attempt_root']))} "
        f"--device {shlex.quote(str(pi['device']))} "
        "--minimum-free-bytes "
        f"{int(configuration['session']['minimum_pi_free_bytes'])}"
    )
    observation = _ssh(str(pi["ssh_alias"]), remote, timeout=30)
    payload = _result_payload(observation)
    return {"command": observation, "report": payload}


def _zed_preflight(configuration: Mapping[str, Any]) -> dict[str, Any]:
    zed = configuration["zed"]
    command = [
        sys.executable,
        str(ZED_PREFLIGHT_LOCAL),
        "--expected-serial",
        str(zed["serial"]),
        "--expected-sdk",
        str(zed["sdk_version"]),
        "--expected-camera-firmware",
        str(zed["camera_firmware"]),
        "--expected-sensor-firmware",
        str(zed["sensor_firmware"]),
        "--minimum-usb-speed-mbps",
        str(zed["usb_minimum_speed_mbps"]),
    ]
    observation = _run(command, timeout=60, cwd=REPO_ROOT)
    payload = _result_payload(observation)
    return {"command": observation, "report": payload}


def preflight_hardware(
    configuration: Mapping[str, Any], attempt: AttemptLifecycle
) -> dict[str, Any]:
    """Run all hardware checks only after configuration/metadata validation."""

    local_disk = disk_space_check(
        attempt.root,
        int(configuration["session"]["minimum_local_free_bytes"]),
    )
    pi_timing = _ssh_timing(str(configuration["respeaker"]["ssh_alias"]))
    mac_timing = _ssh_timing(str(configuration["mac"]["ssh_alias"]))
    pi = _pi_preflight(configuration)
    zed = _zed_preflight(configuration)
    payload = {
        "schema": "ias.s4_2.hardware_preflight.v1",
        "status": "passed",
        "local_disk": local_disk,
        "pi_ssh_timing": pi_timing,
        "mac_ssh_timing": mac_timing,
        "pi": pi,
        "zed": zed,
    }
    passed = (
        local_disk["passed"]
        and pi_timing["passed"]
        and mac_timing["passed"]
        and pi["command"]["return_code"] == 0
        and pi["report"].get("status") == "passed"
        and zed["command"]["return_code"] == 0
        and zed["report"].get("status") == "passed"
    )
    payload["status"] = "passed" if passed else "failed"
    write_json_atomic(attempt.root / "hardware_preflight.json", payload)
    if not passed:
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
                ready[str(key.data)] = event
    selector.close()
    return ready


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
        "coordinate_frame": dict(configuration["coordinate_frame"]),
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
    if (
        not reference_path.is_file()
        or not metadata_path.is_file()
        or not inventory_path.is_file()
        or not amendment_path.is_file()
    ):
        raise S42Error(
            "reference WAV, metadata, Mac inventory, or acceptance amendment is missing"
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
    mac_report_path = REPO_ROOT / str(configuration["mac"]["preflight_report_path"])
    mac_report = load_json(mac_report_path)
    mac_validation = validate_mac_preflight(mac_report, configuration)
    if not mac_validation.passed:
        raise S42Error(f"Mac preflight mismatch: {mac_validation.to_dict()}")

    attempts_root = REPO_ROOT / str(configuration["session"]["attempt_root"])
    attempt = AttemptLifecycle(attempts_root, attempt_id=attempt_id)
    attempt.write_configuration(configuration)
    write_json_atomic(attempt.root / "mac_preflight.json", mac_report)
    write_json_atomic(attempt.root / "reference_wav.json", load_json(metadata_path))
    write_json_atomic(
        attempt.root / "mac_source_inventory.json", load_json(inventory_path)
    )
    write_json_atomic(
        attempt.root / "pre_capture_acceptance_amendment.json",
        load_json(amendment_path),
    )
    processes: dict[str, subprocess.Popen[str]] = {}
    cleanup: list[dict[str, Any]] = []
    try:
        preflight_hardware(configuration, attempt)
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
            f"--device {shlex.quote(str(pi['device']))} --duration {duration}"
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
        attempt.transition("recording", reason="Pi and ZED producers reported ready")
        print(
            "WARNING: S4.2 recording is active. Prepare the visible/audible "
            "alignment event, but do not perform it yet.",
            flush=True,
        )
        if interactive_cue:
            try:
                input("Press ENTER to issue ALIGNMENT EVENT NOW: ")
            except EOFError as exc:
                raise S42Error("interactive alignment cue input closed") from exc
        else:
            time.sleep(3)
        cue = {
            "schema": "ias.s4_2.operator_cue.v1",
            "event": "ALIGNMENT_EVENT_NOW",
            "instruction": configuration["alignment"]["event_instruction"],
            "host_wall_time_utc": _wall_utc(),
            "host_monotonic_ns": time.monotonic_ns(),
            "cue_mode": "interactive_stdin" if interactive_cue else "timed_3_s",
        }
        write_json_atomic(attempt.root / "operator_cue.json", cue)
        print("ALIGNMENT EVENT NOW", flush=True)
        time.sleep(4 if interactive_cue else 2)
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
        write_json_atomic(attempt.root / "playback.json", playback_record)
        if playback.returncode != 0:
            raise S42Error("Mac reference playback failed")
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
            raw / "respeaker_audio.wav"
        )
        zed_records, jsonl_issues = read_jsonl(raw / "zed_frames.jsonl")
        zed_validation = validate_zed_records(
            zed_records,
            duration_s=float(configuration["session"]["duration_s"]),
            fps=int(configuration["zed"]["fps"]),
        )
        capture_validation = {
            "schema": "ias.s4_2.capture_validation.v1",
            "status": "passed"
            if not audio_issues and not jsonl_issues and zed_validation.passed
            else "failed",
            "audio_properties": audio_properties,
            "issues": [
                issue.to_dict()
                for issue in (*audio_issues, *jsonl_issues, *zed_validation.issues)
            ],
            "zed": zed_validation.to_dict(),
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
                (attempt.root / "reference_wav.json", "reference_metadata"),
                (attempt.root / "mac_source_inventory.json", "mac_source_inventory"),
                (
                    attempt.root / "pre_capture_acceptance_amendment.json",
                    "pre_capture_acceptance_amendment",
                ),
                (attempt.root / "hardware_preflight.json", "hardware_preflight"),
                (attempt.root / "producer_readiness.json", "producer_readiness"),
                (attempt.root / "operator_cue.json", "operator_cue"),
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
            attempt.transition("failed", reason=f"{type(exc).__name__}: {exc}")
        write_json_atomic(attempt.root / "cleanup.json", {"actions": cleanup})
        raise


def finalize_attempt(attempt_root: str | Path) -> dict[str, Any]:
    """Accept only a complete finalizing attempt with a passing alignment record."""

    attempt = AttemptLifecycle.open_existing(attempt_root)
    if attempt.state != "finalizing":
        raise S42Error(f"attempt state must be finalizing, got {attempt.state}")
    configuration = load_json(attempt.root / "normalized_configuration.json")
    config_report = validate_configuration(configuration, require_ready=True)
    alignment = load_json(attempt.root / "alignment.json")
    event_confirmation = load_json(
        attempt.root / "event_observation_confirmation.json"
    )
    manifest = load_json(attempt.root / "manifest.json")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise S42Error("manifest.artifacts must be a list")
    integrity = verify_artifact_records(attempt.root, records)
    issues: list[dict[str, Any]] = []
    if not config_report.passed:
        issues.extend(issue.to_dict() for issue in config_report.issues)
    if alignment.get("status") != "passed":
        issues.append(
            {
                "code": "alignment_failed",
                "path": "alignment.json",
                "message": repr(alignment.get("failure_reasons")),
                "severity": "error",
            }
        )
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
    gate = {
        "schema": "ias.s4_2.attempt_gate.v1",
        "status": "passed" if not issues else "failed",
        "attempt_id": attempt.attempt_id,
        "configuration": config_report.to_dict(),
        "alignment": alignment,
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
    "collect_mac_preflight",
    "deploy_helpers_and_reference",
    "finalize_attempt",
    "preflight_hardware",
    "run_capture",
]
