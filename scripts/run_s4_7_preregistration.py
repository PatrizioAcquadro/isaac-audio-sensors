#!/usr/bin/env python3
"""Evaluate a metrics payload against the frozen S4.7 acceptance criteria.

The payload must be supplied by the caller. This entry point never opens a
sealed holdout; S4.8 supplies real results only after an authorized grant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_7 import (  # noqa: E402
    PASS_FIXTURE_PATH,
    load_json,
)
from isaac_audio_sensors.core.acceptance_criteria import (  # noqa: E402
    AcceptanceCriteriaError,
    evaluate_criteria,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--metrics", type=Path, default=PASS_FIXTURE_PATH)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    metrics_path = (
        args.metrics if args.metrics.is_absolute() else repo_root / args.metrics
    )
    try:
        result = evaluate_criteria(
            load_json(metrics_path), repo_root=repo_root
        ).report()
    except AcceptanceCriteriaError as error:
        result = {
            "schema": "ias.s4_7.criteria_evaluation_result.v1",
            "status": "failed",
            "issues": [str(error)],
        }
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
