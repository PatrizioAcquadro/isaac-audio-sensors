#!/usr/bin/env python3
"""Seal the completed S4.8 amendment-02 collection without opening it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8_postcollection_finalizer import (  # noqa: E402
    S48PostcollectionFinalizerError,
    finalize_postcollection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finalize", action="store_true", required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = finalize_postcollection(args.repo_root)
    except (OSError, ValueError, S48PostcollectionFinalizerError) as exc:
        print(f"S4.8 amendment-02 finalization failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
