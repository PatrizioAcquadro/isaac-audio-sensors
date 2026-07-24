#!/usr/bin/env python3
"""Validate the S4.5 evidence package and S4.4 preservation boundary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from isaac_audio_sensors.acquisition.s4_5 import (  # noqa: E402
    S45_OUTPUT,
    validate_evidence_package,
    validate_s4_4_preservation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=S45_OUTPUT)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    evidence = (
        args.evidence if args.evidence.is_absolute() else repo_root / args.evidence
    )
    preservation = validate_s4_4_preservation(repo_root)
    package = validate_evidence_package(
        repo_root,
        evidence,
        require_tracked=args.require_tracked,
        require_committed=args.require_committed,
    )
    result = {
        "schema": "ias.s4_5.final_validation.v1",
        "status": (
            "passed"
            if preservation["status"] == package["status"] == "passed"
            else "failed"
        ),
        "preservation": preservation,
        "package": package,
        "holdout_opened": False,
        "S4.6_started": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
