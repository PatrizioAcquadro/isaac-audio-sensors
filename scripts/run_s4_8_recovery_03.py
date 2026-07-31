#!/usr/bin/env python3
"""Validate or explicitly run the non-official S4.8 amendment-03 replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8_recovery_03 import (  # noqa: E402
    S48Recovery03Error,
    run_engineering_replay,
    validate_release_candidate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the frozen S4.8 amendment-03 release candidate or run "
            "its isolated, non-official engineering replay."
        )
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-rc", action="store_true")
    action.add_argument("--engineering-replay", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.validate_rc:
            result = validate_release_candidate(args.repo_root)
        else:
            result = run_engineering_replay(args.repo_root)
    except (OSError, S48Recovery03Error, ValueError) as exc:
        print(f"S4.8 recovery amendment-03 failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
