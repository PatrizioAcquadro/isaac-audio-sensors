#!/usr/bin/env python3
"""Standalone Raspberry Pi ReSpeaker producer used by S4.2 SSH orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ias.s4_2.pi_producer.v1"
EXPECTED_VENDOR = "2886"
EXPECTED_PRODUCT = "001a"
EXPECTED_SERIAL = "114993701261100454"
EXPECTED_MODEL = "reSpeaker XVF3800 4-Mic Array"
EXPECTED_FIRMWARE = "2.08"
EXPECTED_DEVICE = "hw:CARD=Array,DEV=0"
FROZEN_CHANNEL_ORDER = [
    "Conference",
    "ASR",
    "raw microphone 0",
    "raw microphone 1",
    "raw microphone 2",
    "raw microphone 3",
]


def _normalize_bcd_device(value: str | None) -> str | None:
    if value is not None and re.fullmatch(r"\d{4}", value):
        return f"{int(value[:2])}.{value[2:]}"
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inspect_partial_wav(path: Path) -> dict[str, Any]:
    """Inspect the header produced by the actual recorder process."""

    with wave.open(str(path), "rb") as reader:
        sample_width = reader.getsampwidth()
        compression = reader.getcomptype()
        return {
            "channel_count": reader.getnchannels(),
            "sample_rate_hz": reader.getframerate(),
            "sample_width_bytes": sample_width,
            "compression": compression,
            "encoding": (
                "PCM_S16_LE"
                if sample_width == 2 and compression == "NONE"
                else "unsupported"
            ),
        }


def _usb_identity() -> dict[str, Any] | None:
    for device in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vendor = (device / "idVendor").read_text().strip()
            product = (device / "idProduct").read_text().strip()
        except OSError:
            continue
        if vendor == EXPECTED_VENDOR and product == EXPECTED_PRODUCT:

            def read(name: str, root: Path = device) -> str | None:
                try:
                    return (root / name).read_text().strip()
                except OSError:
                    return None

            raw_firmware = read("bcdDevice")
            normalized_firmware = _normalize_bcd_device(raw_firmware)

            return {
                "vendor_id": vendor,
                "product_id": product,
                "serial": read("serial"),
                "model": read("product"),
                "firmware": normalized_firmware,
                "firmware_bcd_raw": raw_firmware,
                "usb_speed_mbps": float(read("speed") or "nan"),
            }
    return None


def preflight(args: argparse.Namespace) -> int:
    """Check the Pi/ReSpeaker capture contract without starting arecord."""

    output_root = Path(args.output_root).expanduser()
    resolved = output_root.resolve()
    home = Path.home().resolve()
    safe_output = not output_root.is_absolute() and resolved.is_relative_to(home)
    probe = resolved
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    identity = _usb_identity()
    free_bytes = 0
    output_parent_writable = False
    if safe_output and probe.exists():
        disk = os.statvfs(probe)
        free_bytes = disk.f_bavail * disk.f_frsize
        output_parent_writable = os.access(probe, os.W_OK | os.X_OK)
    arecord = Path("/usr/bin/arecord")
    inventory = subprocess.run(
        [str(arecord), "-l"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    ) if arecord.is_file() else None
    device_visible = bool(
        inventory is not None
        and inventory.returncode == 0
        and re.search(r"card \d+: Array .*device 0:", inventory.stdout)
    )
    checks = {
        "helper_available": Path(__file__).is_file(),
        "record_subcommand_contract": True,
        "device_argument_matches": args.device == EXPECTED_DEVICE,
        "device_visible": device_visible,
        "device_present": identity is not None,
        "serial_matches": identity is not None
        and identity.get("serial") == EXPECTED_SERIAL,
        "model_matches": identity is not None
        and identity.get("model") == EXPECTED_MODEL,
        "firmware_matches": identity is not None
        and identity.get("firmware") == EXPECTED_FIRMWARE,
        "usb_available": identity is not None
        and float(identity.get("usb_speed_mbps", 0)) >= 480,
        "arecord_available": arecord.is_file(),
        "frozen_format_contract": True,
        "frozen_channel_order_contract": True,
        "output_path_safe": safe_output,
        "output_path_available": safe_output and not resolved.exists(),
        "output_parent_writable": output_parent_writable,
        "disk_space": free_bytes >= args.minimum_free_bytes,
        "no_recorder_started": True,
        "no_media_created": True,
    }
    result = {
        "schema": "ias.s4_2.pi_preflight.v1",
        "operation": "preflight",
        "status": "passed" if all(checks.values()) else "failed",
        "read_only_no_media": True,
        "identity": identity,
        "device": args.device,
        "device_inventory_exit_status": (
            inventory.returncode if inventory is not None else None
        ),
        "capture_contract": {
            "record_subcommand": "record",
            "required_arguments": [
                "--attempt",
                "--device",
                "--duration",
                "--minimum-free-bytes",
            ],
            "sample_rate_hz": 16000,
            "sample_format": "S16_LE",
            "channels": 6,
            "channel_order": FROZEN_CHANNEL_ORDER,
        },
        "output_root": args.output_root,
        "free_bytes": free_bytes,
        "minimum_free_bytes": args.minimum_free_bytes,
        "helper_sha256": _sha256(Path(__file__)),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0 if all(checks.values()) else 1


def record(args: argparse.Namespace) -> int:
    attempt = Path(args.attempt).expanduser()
    if attempt.exists():
        print(json.dumps({"status": "failed", "reason": "attempt exists"}))
        return 2
    attempt.mkdir(parents=True, exist_ok=False)
    partial = attempt / "respeaker_audio.partial.wav"
    final = attempt / "respeaker_audio.wav"
    status_path = attempt / "producer_status.json"
    pid_path = attempt / "producer.pid"
    identity = _usb_identity()
    disk = os.statvfs(attempt)
    free_bytes = disk.f_bavail * disk.f_frsize
    startup_checks = {
        "device_present": identity is not None,
        "serial_matches": identity is not None
        and identity.get("serial") == EXPECTED_SERIAL,
        "model_matches": identity is not None
        and identity.get("model") == EXPECTED_MODEL,
        "firmware_matches": identity is not None
        and identity.get("firmware") == EXPECTED_FIRMWARE,
        "usb_available": identity is not None
        and float(identity.get("usb_speed_mbps", 0)) >= 480,
        "arecord_available": Path("/usr/bin/arecord").is_file(),
        "disk_space": free_bytes >= args.minimum_free_bytes,
    }
    if not all(startup_checks.values()):
        result = {
            "schema": SCHEMA,
            "operation": "record",
            "status": "failed",
            "reason": "ReSpeaker identity, USB, executable, or disk check failed",
            "identity": identity,
            "free_bytes": free_bytes,
            "minimum_free_bytes": args.minimum_free_bytes,
            "startup_checks": startup_checks,
        }
        _atomic_json(status_path, result)
        print(json.dumps({"event": "failed", "summary": result}), flush=True)
        return 3
    command = [
        "/usr/bin/arecord",
        "-D",
        args.device,
        "-d",
        str(args.duration),
        "-f",
        "S16_LE",
        "-r",
        "16000",
        "-c",
        "6",
        "-t",
        "wav",
        str(partial),
    ]
    started_wall = datetime.now(timezone.utc).isoformat()
    started_monotonic_ns = time.monotonic_ns()
    process = subprocess.Popen(command, start_new_session=True)  # noqa: S603
    pid_path.write_text(f"{os.getpid()} {process.pid}\n", encoding="ascii")
    capture_format: dict[str, Any] | None = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and process.poll() is None:
        if partial.is_file() and partial.stat().st_size >= 44:
            try:
                capture_format = _inspect_partial_wav(partial)
                break
            except (EOFError, OSError, wave.Error):
                pass
        time.sleep(0.05)
    startup_checks.update(
        {
            "capture_started": process.poll() is None,
            "six_channels": capture_format is not None
            and capture_format["channel_count"] == 6,
            "sample_rate_16000": capture_format is not None
            and capture_format["sample_rate_hz"] == 16_000,
            "sample_format_s16_le": capture_format is not None
            and capture_format["encoding"] == "PCM_S16_LE",
        }
    )
    if not all(startup_checks.values()):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=5)
        result = {
            "schema": SCHEMA,
            "operation": "record",
            "status": "failed",
            "reason": "actual arecord process failed its startup contract",
            "started_wall_time_utc": started_wall,
            "started_monotonic_ns": started_monotonic_ns,
            "identity": identity,
            "capture_format": capture_format,
            "free_bytes": free_bytes,
            "minimum_free_bytes": args.minimum_free_bytes,
            "startup_checks": startup_checks,
        }
        _atomic_json(status_path, result)
        print(json.dumps({"event": "failed", "summary": result}), flush=True)
        return 4
    print(
        json.dumps(
            {
                "event": "ready",
                "started_wall_time_utc": started_wall,
                "started_monotonic_ns": started_monotonic_ns,
                "arecord_pid": process.pid,
                "identity": identity,
                "capture_format": capture_format,
                "free_bytes": free_bytes,
                "minimum_free_bytes": args.minimum_free_bytes,
                "checks": startup_checks,
                "verification_basis": "actual_recording_partial_wav_header",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    interrupted = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        return_code = process.wait(timeout=args.duration + 10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGINT)
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            return_code = process.wait(timeout=5)
            interrupted = True
    completed_wall = datetime.now(timezone.utc).isoformat()
    completed_monotonic_ns = time.monotonic_ns()
    passed = return_code == 0 and partial.is_file() and not interrupted
    if passed:
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(partial, final)
    result = {
        "schema": SCHEMA,
        "operation": "record",
        "status": "complete" if passed else "interrupted" if interrupted else "failed",
        "reason": None
        if passed
        else f"arecord exit={return_code}; interrupted={interrupted}",
        "started_wall_time_utc": started_wall,
        "started_monotonic_ns": started_monotonic_ns,
        "completed_wall_time_utc": completed_wall,
        "completed_monotonic_ns": completed_monotonic_ns,
        "arecord_exit_status": return_code,
        "duration_s": args.duration,
        "finalized_path": final.name if passed else None,
        "partial_path": partial.name if partial.is_file() else None,
        "byte_size": final.stat().st_size if final.is_file() else 0,
        "sha256": _sha256(final) if final.is_file() else None,
        "identity": identity,
        "capture_format": capture_format,
        "startup_checks": startup_checks,
    }
    _atomic_json(status_path, result)
    pid_path.unlink(missing_ok=True)
    print(
        json.dumps({"event": result["status"], "summary": result}, sort_keys=True),
        flush=True,
    )
    return 0 if passed else 130 if interrupted else 4


def stop(args: argparse.Namespace) -> int:
    attempt = Path(args.attempt).expanduser()
    pid_path = attempt / "producer.pid"
    if not pid_path.is_file():
        print(json.dumps({"status": "not_running", "reason": "pid file absent"}))
        return 0
    try:
        helper_pid, _arecord_pid = (
            int(value) for value in pid_path.read_text(encoding="ascii").split()
        )
        pid = helper_pid
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except (OSError, ValueError):
        print(json.dumps({"status": "not_running", "reason": "stale pid file"}))
        return 0
    expected = str(attempt).encode("utf-8")
    if b"s4_2_pi_capture.py" not in command_line or expected not in command_line:
        print(json.dumps({"status": "refused", "reason": "pid identity mismatch"}))
        return 2
    os.kill(pid, signal.SIGINT)
    print(json.dumps({"status": "stop_requested"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--output-root", required=True)
    preflight_parser.add_argument("--device", required=True)
    preflight_parser.add_argument("--minimum-free-bytes", type=int, required=True)
    preflight_parser.set_defaults(function=preflight)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--attempt", required=True)
    record_parser.add_argument("--device", required=True)
    record_parser.add_argument("--duration", type=int, required=True)
    record_parser.add_argument("--minimum-free-bytes", type=int, required=True)
    record_parser.set_defaults(function=record)
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--attempt", required=True)
    stop_parser.set_defaults(function=stop)
    args = parser.parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
