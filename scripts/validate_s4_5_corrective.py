#!/usr/bin/env python3
"""Semantically validate the additive S4.5 corrective-01 package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_5_corrective import (  # noqa: E402
    CORRECTIVE_OUTPUT,
    validate_corrective_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=CORRECTIVE_OUTPUT)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    result = validate_corrective_package(
        args.repo_root,
        args.evidence,
        require_tracked=args.require_tracked,
        require_committed=args.require_committed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
