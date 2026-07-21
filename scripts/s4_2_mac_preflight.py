#!/usr/bin/env python3
"""Read-only, redacted macOS preflight for the S4.2 controlled source."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

COLLECTOR_VERSION = "ias.s4_2.mac_preflight.v1"


def _run(*args: str) -> tuple[int, str]:
    completed = subprocess.run(  # noqa: S603 - fixed read-only commands
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode, completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redacted_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return str(Path("$HOME") / relative)


def _sw_vers(field: str) -> str | None:
    status, value = _run("/usr/bin/sw_vers", field)
    return value if status == 0 and value else None


def _selected_audio_output() -> dict[str, Any]:
    status, raw = _run("/usr/sbin/system_profiler", "SPAudioDataType", "-json")
    if status != 0:
        return {"status": "unavailable"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "unparseable"}

    selected: dict[str, Any] | None = None

    def walk(value: Any) -> None:
        nonlocal selected
        if selected is not None:
            return
        if isinstance(value, dict):
            if value.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                selected = value
                return
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    if selected is None:
        return {"status": "not_found"}
    return {
        "status": "collected",
        "device_name": selected.get("_name"),
        "channel_count": selected.get("coreaudio_device_output"),
        "nominal_sample_rate_hz": selected.get("coreaudio_device_srate"),
        "transport": selected.get("coreaudio_device_transport"),
        "built_in": selected.get("coreaudio_device_transport")
        == "coreaudio_device_type_builtin",
    }


def _volume_settings() -> dict[str, Any]:
    status, raw = _run("/usr/bin/osascript", "-e", "get volume settings")
    if status != 0:
        return {"status": "unavailable"}
    fields: dict[str, Any] = {"status": "collected"}
    for key, value in re.findall(r"([a-z ]+):([^,]+)(?:,|$)", raw):
        normalized = key.strip().replace(" ", "_")
        stripped = value.strip()
        if stripped in {"true", "false"}:
            fields[normalized] = stripped == "true"
        elif stripped.isdigit():
            fields[normalized] = int(stripped)
    return fields


def _power_state() -> dict[str, Any]:
    status, raw = _run("/usr/bin/pmset", "-g", "batt")
    if status != 0:
        return {"status": "unavailable"}
    source_match = re.search(r"Now drawing from '([^']+)'", raw)
    percent_match = re.search(r"\b(\d{1,3})%;\s*([^;\n]+)", raw)
    source = source_match.group(1) if source_match else None
    battery_percent = int(percent_match.group(1)) if percent_match else None
    condition = percent_match.group(2).strip() if percent_match else None
    return {
        "status": "collected",
        "source": source,
        "on_ac_power": source == "AC Power",
        "battery_percent": battery_percent,
        "battery_condition": condition,
        "charging": condition == "charging",
    }


def _default_bool(domain: str, key: str) -> bool | None:
    status, raw = _run("/usr/bin/defaults", "read", domain, key)
    if status != 0:
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _focus_state() -> dict[str, Any]:
    path = Path.home() / "Library/DoNotDisturb/DB/Assertions.json"
    if not path.is_file():
        return {
            "status": "unavailable",
            "work_focus_active": None,
            "notifications_suppressed": None,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unparseable",
            "work_focus_active": None,
            "notifications_suppressed": None,
        }
    modes: list[str] = []
    assertion_count = 0
    for store in payload.get("data", []):
        if not isinstance(store, dict):
            continue
        records = store.get("storeAssertionRecords", [])
        if not isinstance(records, list):
            continue
        assertion_count += len(records)
        for record in records:
            if not isinstance(record, dict):
                continue
            details = record.get("assertionDetails", {})
            if isinstance(details, dict):
                mode = details.get("assertionDetailsModeIdentifier")
                if isinstance(mode, str):
                    modes.append(mode.lower())
    return {
        "status": "collected",
        "work_focus_active": any("work" in mode for mode in modes),
        "notifications_suppressed": assertion_count > 0,
        "active_assertion_count": assertion_count,
        "privacy_note": "Focus identifiers and assertion details are not emitted.",
    }


def _reference_wav(path: Path, expected_sha256: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _redacted_path(path),
        "filename": path.name,
        "expected_sha256": expected_sha256.lower(),
        "exists": path.is_file(),
    }
    if not path.is_file():
        result.update({"sha256": None, "hash_matches": False})
        return result
    result["byte_size"] = path.stat().st_size
    result["sha256"] = _sha256(path)
    result["hash_matches"] = result["sha256"] == expected_sha256.lower()
    try:
        with wave.open(str(path), "rb") as reader:
            result.update(
                {
                    "channel_count": reader.getnchannels(),
                    "sample_rate_hz": reader.getframerate(),
                    "bits_per_sample": reader.getsampwidth() * 8,
                    "frame_count": reader.getnframes(),
                    "duration_s": reader.getnframes() / reader.getframerate(),
                    "encoding": "PCM_S16_LE"
                    if reader.getsampwidth() == 2
                    else "unsupported",
                }
            )
    except (OSError, EOFError, wave.Error) as exc:
        result["format_error"] = f"{type(exc).__name__}: {exc}"
    afinfo_status, afinfo = _run("/usr/bin/afinfo", str(path))
    result["afinfo_exit_status"] = afinfo_status
    normalized_afinfo = afinfo.lower()
    result["afinfo_lpcm_detected"] = "lpcm" in normalized_afinfo or (
        "file type id:   wave" in normalized_afinfo
        and "int16" in normalized_afinfo
        and "48000 hz" in normalized_afinfo
    )
    return result


def collect(
    wav_path: Path, expected_sha256: str, expected_volume_percent: int = 63
) -> dict[str, Any]:
    """Collect a redacted report without changing any system setting."""

    now = datetime.now().astimezone()
    audio = _selected_audio_output()
    volume = _volume_settings()
    power = _power_state()
    focus = _focus_state()
    reference = _reference_wav(wav_path, expected_sha256)
    mono = _default_bool("com.apple.universalaccess", "stereoAsMono")
    background = _default_bool("com.apple.ComfortSounds", "comfortSoundsEnabled")
    feedback = _default_bool("NSGlobalDomain", "com.apple.sound.beep.feedback")
    unresolved = [
        "left_right_balance_requires_manual_centered_verification",
        "system_ui_sounds_capture_procedure_requires_operator_confirmation",
        "equalizer_not_applicable_to_afplay_but_not_programmatically_verified",
        "sound_check_not_applicable_to_afplay_but_not_programmatically_verified",
        "spatial_head_tracking_not_applicable_to_mono_stereo_afplay_but_not_programmatically_verified",
        "headphone_accommodations_not_applicable_to_built_in_speakers_but_not_programmatically_verified",
    ]
    if mono is None:
        unresolved.append("mono_audio_state_unavailable")
    if background is None:
        unresolved.append("background_sounds_state_unavailable")
    if feedback is None:
        unresolved.append("volume_change_feedback_state_unavailable")
    if focus.get("status") != "collected":
        unresolved.append("focus_notification_state_unavailable")
    report = {
        "schema": "ias.s4_2.mac_preflight.v1",
        "collector_version": COLLECTOR_VERSION,
        "read_only": True,
        "collected_at": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
        "hardware": {
            "model_identifier": platform.machine()
            if platform.system() != "Darwin"
            else _run("/usr/sbin/sysctl", "-n", "hw.model")[1]
        },
        "os": {
            "name": "macOS",
            "version": _sw_vers("-productVersion"),
            "build": _sw_vers("-buildVersion"),
        },
        "audio_output": audio,
        "volume": volume,
        "power": power,
        "reference_wav": reference,
        "controllable_audio_settings": {
            "mono_audio": mono,
            "background_sounds": background,
            "volume_change_feedback": feedback,
            "left_right_balance": "manual_verification_required",
            "system_ui_sounds": "manual_procedure_confirmation_required",
        },
        "focus_and_notifications": focus,
        "manual_verification": {
            "left_right_balance_centered": None,
            "system_ui_sounds_disabled_or_prevented": None,
        },
        "unresolved": unresolved,
        "privacy": {
            "redacted_fields": [
                "serial_numbers",
                "hardware_uuid",
                "username",
                "hostname",
                "ip_addresses",
                "wifi",
                "apple_id",
                "focus_identifiers",
            ]
        },
    }
    report["frozen_checks"] = {
        "model_identifier_matches": report["hardware"]["model_identifier"]
        == "MacBookPro18,1",
        "os_version_matches": report["os"]["version"] == "26.5.2",
        "os_build_matches": report["os"]["build"] == "25F84",
        "output_device_matches": audio.get("device_name") == "MacBook Pro Speakers",
        "output_channels_match": audio.get("channel_count") == 2,
        "output_sample_rate_matches": audio.get("nominal_sample_rate_hz") == 48_000,
        "volume_matches": volume.get("output_volume") == expected_volume_percent,
        "unmuted": volume.get("output_muted") is False,
        "ac_power": power.get("on_ac_power") is True,
        "work_focus_active": focus.get("work_focus_active") is True,
        "notifications_suppressed": focus.get("notifications_suppressed") is True,
        "reference_hash_matches": reference.get("hash_matches") is True,
        "reference_format_matches": (
            reference.get("channel_count") == 1
            and reference.get("sample_rate_hz") == 48_000
            and reference.get("bits_per_sample") == 16
            and reference.get("duration_s") == 9.5
            and reference.get("afinfo_exit_status") == 0
            and reference.get("afinfo_lpcm_detected") is True
        ),
    }
    return report


def collect_dynamic(expected_volume_percent: int) -> dict[str, Any]:
    """Collect only settings that can change between takes in one stable session."""

    now = datetime.now().astimezone()
    audio = _selected_audio_output()
    volume = _volume_settings()
    power = _power_state()
    checks = {
        "output_device_matches": audio.get("device_name") == "MacBook Pro Speakers",
        "output_channels_match": audio.get("channel_count") == 2,
        "output_sample_rate_matches": audio.get("nominal_sample_rate_hz") == 48_000,
        "volume_matches": volume.get("output_volume") == expected_volume_percent,
        "unmuted": volume.get("output_muted") is False,
        "ac_power": power.get("on_ac_power") is True,
    }
    return {
        "schema": "ias.s4_2.mac_dynamic_preflight.v1",
        "collector_version": COLLECTOR_VERSION,
        "read_only": True,
        "scope": "per_take_dynamic_only",
        "collected_at": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
        "audio_output": audio,
        "volume": volume,
        "power": power,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
        "privacy": {
            "redacted_fields": [
                "serial_numbers",
                "hardware_uuid",
                "username",
                "hostname",
                "ip_addresses",
                "wifi",
                "apple_id",
            ]
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path, default=None)
    parser.add_argument("--expected-sha256", default=None)
    parser.add_argument(
        "--expected-volume-percent",
        type=int,
        choices=range(0, 101),
        required=True,
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dynamic-only", action="store_true")
    args = parser.parse_args()
    if args.dynamic_only:
        report = collect_dynamic(args.expected_volume_percent)
    else:
        if args.wav is None:
            parser.error("--wav is required unless --dynamic-only is used")
        if args.expected_sha256 is None or not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.expected_sha256
        ):
            parser.error("--expected-sha256 must contain exactly 64 hexadecimal digits")
        report = collect(args.wav, args.expected_sha256, args.expected_volume_percent)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(encoded)
    checks = report.get("frozen_checks", report.get("checks", {}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
