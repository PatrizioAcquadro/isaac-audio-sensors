#!/usr/bin/env python3
"""Run the mandatory v2 engineering recorder-to-candidate-seal path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    SubprocessEngineeringBackend,
    run_supported_engineering_acquisition,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--capture-wav", type=Path, required=True)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--retry-report", type=Path, required=True)
    parser.add_argument("--candidate-seal", type=Path, required=True)
    parser.add_argument("--clearance-registry", type=Path, required=True)
    parser.add_argument("--recorder-command-json", required=True)
    parser.add_argument("--playback-command-json", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
        recorder_command = _command(args.recorder_command_json, "recorder")
        playback_command = _command(args.playback_command_json, "playback")
        result = run_supported_engineering_acquisition(
            backend=SubprocessEngineeringBackend(
                recorder_command=recorder_command,
                playback_command=playback_command,
            ),
            repo_root=args.repo_root.resolve(),
            capture_path=args.capture_wav.resolve(),
            reference_path=args.reference_wav.resolve(),
            manifest=manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            journal_path=args.journal.resolve(),
            retry_report_path=args.retry_report.resolve(),
            candidate_seal_path=args.candidate_seal.resolve(),
            clearance_registry_path=args.clearance_registry.resolve(),
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, S48EngineeringAcquisitionError) as exc:
        print(f"S4.8 engineering acquisition failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 1


def _command(raw: str, label: str) -> list[str]:
    value = json.loads(raw)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{label} command must be a non-empty JSON string array")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
