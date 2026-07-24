#!/usr/bin/env python3
"""Validate the canonical S4.7 preregistration evidence package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_7 import (  # noqa: E402
    OUTPUT_PATH,
    validate_evidence_package,
)
from isaac_audio_sensors.core.acceptance_criteria import (  # noqa: E402
    AcceptanceCriteriaError,
    load_criteria,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--criteria-only", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    if args.criteria_only:
        try:
            config = load_criteria(repo_root=args.repo_root)
        except AcceptanceCriteriaError as error:
            result = {
                "schema": "ias.s4_7.criteria_validation_result.v1",
                "status": "failed",
                "issues": [str(error)],
            }
        else:
            readiness = [
                item for item in config["criteria"] if item["tier"] == "readiness"
            ]
            result = {
                "schema": "ias.s4_7.criteria_validation_result.v1",
                "status": "passed",
                "issues": [],
                "criterion_count": len(config["criteria"]),
                "readiness_criterion_count": len(readiness),
                "frozen_at_utc": config["frozen_at_utc"],
                "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
                "holdout_observations_accessed": 0,
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
