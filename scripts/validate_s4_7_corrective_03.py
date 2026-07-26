#!/usr/bin/env python3
"""Validate S4.7 corrective_03 criteria or its complete evidence package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_7_corrective_03 import (  # noqa: E402
    OUTPUT_PATH,
    validate_criteria_only,
    validate_evidence_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--criteria-only", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args()
    result = (
        validate_criteria_only(args.repo_root)
        if args.criteria_only
        else validate_evidence_package(
            args.repo_root,
            args.evidence,
            require_tracked=args.require_tracked,
            require_committed=args.require_committed,
            verify_replay=not args.skip_replay,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
