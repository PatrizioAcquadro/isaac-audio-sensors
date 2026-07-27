#!/usr/bin/env python3
"""Validate the S4.8 recovery amendment_02 preregistration boundary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8 import S48Error  # noqa: E402
from isaac_audio_sensors.acquisition.s4_8_recovery_02 import (  # noqa: E402
    recovery_preopen_validate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preopen", action="store_true", required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    try:
        result = recovery_preopen_validate(
            args.repo_root,
            source_commit=args.source_commit,
        )
    except (OSError, S48Error, ValueError) as exc:
        print(f"S4.8 recovery amendment_02 failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
