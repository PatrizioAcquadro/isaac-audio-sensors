#!/usr/bin/env python3
"""Arm and run one authenticated S4.8 Mac playback process."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit(event: str, **values: Any) -> None:
    print(
        json.dumps(
            {
                "schema": "ias.s4_8.mac_playback_event.v1",
                "event": event,
                **values,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _validate_asset(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or _sha256(path) != expected_sha256:
        raise RuntimeError("playback asset hash mismatch")
    with wave.open(str(path), "rb") as stream:
        values = {
            "sample_rate_hz": stream.getframerate(),
            "channel_count": stream.getnchannels(),
            "sample_width_bytes": stream.getsampwidth(),
            "frame_count": stream.getnframes(),
            "compression": stream.getcomptype(),
        }
    if (
        values["sample_rate_hz"] != 48_000
        or values["channel_count"] != 1
        or values["sample_width_bytes"] != 2
        or values["frame_count"] != 864_000
        or values["compression"] != "NONE"
    ):
        raise RuntimeError("playback asset format mismatch")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--gain", type=float, required=True)
    args = parser.parse_args()
    process: subprocess.Popen[str] | None = None
    try:
        if (
            len(args.expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in args.expected_sha256
            )
            or not math.isfinite(args.gain)
            or args.gain <= 0.0
        ):
            raise RuntimeError("playback arguments are invalid")
        asset = args.asset.expanduser().resolve()
        asset_format = _validate_asset(asset, args.expected_sha256)
        _emit(
            "armed",
            asset_sha256=args.expected_sha256,
            asset_format=asset_format,
            helper_monotonic_ns=time.monotonic_ns(),
        )
        if sys.stdin.readline() != "START\n":
            raise RuntimeError("authenticated START command was not received")
        process = subprocess.Popen(
            ["/usr/bin/afplay", "-v", str(args.gain), str(asset)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        _emit(
            "playback_started",
            afplay_pid=process.pid,
            helper_monotonic_ns=time.monotonic_ns(),
        )
        stderr = process.communicate()[1]
        _emit(
            "playback_completed",
            afplay_pid=process.pid,
            afplay_exit_status=process.returncode,
            helper_monotonic_ns=time.monotonic_ns(),
            stderr=stderr,
        )
        return 0 if process.returncode == 0 else 1
    except (OSError, RuntimeError, wave.Error) as exc:
        _emit(
            "failed",
            error_type=type(exc).__name__,
            error=str(exc),
            helper_monotonic_ns=time.monotonic_ns(),
        )
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
