#!/usr/bin/env python3
"""Run the non-authoritative S4.8 pre-sealing gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    S48PresealingGateError,
    run_presealing_gate_from_files,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--capture-wav", type=Path, required=True)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--process-record", type=Path, required=True)
    parser.add_argument("--expected-reference-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="run without sealing, grants, state-machine execution, or evidence",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    if args.output is not None and args.output.resolve().is_relative_to(root):
        parser.error("--output must be outside the repository")
    try:
        report = run_presealing_gate_from_files(
            capture_wav_path=args.capture_wav.resolve(),
            reference_wav_path=args.reference_wav.resolve(),
            process_record_path=args.process_record.resolve(),
            expected_reference_sha256=args.expected_reference_sha256,
            repo_root=root,
            dry_run=True,
        )
    except (OSError, S48PresealingGateError) as exc:
        print(f"S4.8 pre-sealing gate failed: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(serialized, end="")
    else:
        args.output.resolve().write_text(serialized, encoding="utf-8")
        print(args.output.resolve())
    return 0 if report["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
