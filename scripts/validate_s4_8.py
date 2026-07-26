#!/usr/bin/env python3
"""Validate the S4.8 package without reopening the holdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8 import (  # noqa: E402
    OUTPUT_PATH,
    S48Error,
    validate_evidence_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--package", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    package = (
        args.package
        if args.package.is_absolute()
        else args.repo_root / args.package
    )
    try:
        result = validate_evidence_package(package, repo_root=args.repo_root)
    except (OSError, S48Error, ValueError) as exc:
        print(f"S4.8 validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
