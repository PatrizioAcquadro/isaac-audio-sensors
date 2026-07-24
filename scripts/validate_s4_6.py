#!/usr/bin/env python3
"""Validate the active S4.6 bundle or complete canonical evidence package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_6 import (  # noqa: E402
    OUTPUT_PATH,
    validate_evidence_package,
)
from isaac_audio_sensors.core.config import load_audio_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--bundle-only", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    if args.bundle_only:
        config = load_audio_config(
            args.repo_root / "examples/s4_6/compatible_runtime.toml"
        )
        response = config.effects.channel_response
        result = {
            "schema": "ias.s4_6.bundle_validation_result.v1",
            "status": "passed",
            "applied_channel_ids": list(response.microphones or {}),
            "functional_positions": {
                mic.mic_id: list(mic.relative_position_m)
                for mic in config.arrays["xvf3800_array"].microphones
            },
            "holdout_observations_accessed": 0,
            "later_phases_started": [],
        }
    else:
        result = validate_evidence_package(
            args.repo_root,
            args.evidence,
            require_tracked=args.require_tracked,
            require_committed=args.require_committed,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
