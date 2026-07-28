#!/usr/bin/env python3
"""Run the deterministic synthetic non-holdout S4.8 rehearsal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_8_engineering_rehearsal import (
    run_synthetic_engineering_rehearsal,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gate-execution-count",
        type=int,
        default=47,
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        parser.error("--output must be outside the repository")
    report = run_synthetic_engineering_rehearsal(
        root,
        gate_execution_count=args.gate_execution_count,
    )
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
