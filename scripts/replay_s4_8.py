#!/usr/bin/env python3
"""Byte-replay the derived S4.8 package without raw or grant access."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8 import (  # noqa: E402
    OUTPUT_PATH,
    S48Error,
    replay_evidence_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--canonical", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    canonical = (
        args.canonical
        if args.canonical.is_absolute()
        else args.repo_root / args.canonical
    )
    try:
        if args.output is not None:
            result = replay_evidence_package(
                canonical,
                output=args.output,
                repo_root=args.repo_root,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="ias-s4-8-replay-") as temp:
                result = replay_evidence_package(
                    canonical,
                    output=Path(temp) / "S4.8",
                    repo_root=args.repo_root,
                )
    except (OSError, S48Error, ValueError) as exc:
        print(f"S4.8 replay failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
