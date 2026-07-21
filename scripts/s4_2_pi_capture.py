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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ias.s4_2.pi_producer.v1"
EXPECTED_VENDOR = "2886"
EXPECTED_PRODUCT = "001a"
EXPECTED_SERIAL = "114993701261100454"
EXPECTED_MODEL = "reSpeaker XVF3800 4-Mic Array"
EXPECTED_FIRMWARE = "2.08"


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


def _arecord_probe(device: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "/usr/bin/arecord",
            "-D",
            device,
            "--dump-hw-params",
            "-d",
            "1",
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "6",
            "/dev/null",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    combined = completed.stdout + "\n" + completed.stderr
    return {
        "exit_status": completed.returncode,
        "six_channels": bool(re.search(r"^CHANNELS:\s+6$", combined, re.MULTILINE)),
        "sample_rate_16000": bool(
            re.search(r"^RATE:\s+16000$", combined, re.MULTILINE)
        ),
        "sample_format_s16_le": bool(
            re.search(r"^FORMAT:\s+S16_LE$", combined, re.MULTILINE)
        ),
    }


def preflight(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    identity = _usb_identity()
    disk = os.statvfs(root)
    free_bytes = disk.f_bavail * disk.f_frsize
    alsa = _arecord_probe(args.device)
    checks = {
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
        "capture_opened": alsa["exit_status"] == 0,
        "six_channels": alsa["six_channels"],
        "sample_rate_16000": alsa["sample_rate_16000"],
        "sample_format_s16_le": alsa["sample_format_s16_le"],
        "disk_space": free_bytes >= args.minimum_free_bytes,
    }
    payload = {
        "schema": SCHEMA,
        "operation": "preflight",
        "status": "passed" if all(checks.values()) else "failed",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "alsa": alsa,
        "free_bytes": free_bytes,
        "minimum_free_bytes": args.minimum_free_bytes,
        "checks": checks,
    }
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
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
    time.sleep(0.5)
    if process.poll() is not None:
        result = {
            "schema": SCHEMA,
            "operation": "record",
            "status": "failed",
            "reason": f"arecord exited before readiness with {process.returncode}",
            "started_wall_time_utc": started_wall,
            "started_monotonic_ns": started_monotonic_ns,
        }
        _atomic_json(status_path, result)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 3
    print(
        json.dumps(
            {
                "event": "ready",
                "started_wall_time_utc": started_wall,
                "started_monotonic_ns": started_monotonic_ns,
                "arecord_pid": process.pid,
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
    preflight_parser.add_argument("--root", required=True)
    preflight_parser.add_argument("--device", required=True)
    preflight_parser.add_argument("--minimum-free-bytes", type=int, required=True)
    preflight_parser.set_defaults(function=preflight)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--attempt", required=True)
    record_parser.add_argument("--device", required=True)
    record_parser.add_argument("--duration", type=int, required=True)
    record_parser.set_defaults(function=record)
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--attempt", required=True)
    stop_parser.set_defaults(function=stop)
    args = parser.parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
