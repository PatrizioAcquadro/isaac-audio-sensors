#!/usr/bin/env python3
"""Build the additive S4.5 active handoff package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_5_handoff import (  # noqa: E402
    OUTPUT_PATH,
    build_handoff_package,
    route_authoritative_closeout,
    write_active_pointer,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--write-active-pointer", action="store_true")
    parser.add_argument("--route-closeout", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    result = build_handoff_package(
        repo_root=repo_root,
        output=args.output,
        source_commit=args.source_commit,
    )
    package = args.output if args.output.is_absolute() else repo_root / args.output
    if args.write_active_pointer:
        result["active_pointer"] = str(write_active_pointer(repo_root, package))
    if args.route_closeout:
        route_authoritative_closeout(repo_root)
        result["closeout_routed"] = True
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
