#!/usr/bin/env python3
"""Evaluate an observation-bound S4.7 corrective_02 metrics payload.

This command reads only the supplied JSON and tracked contract/technical
manifest files. It cannot open or locate holdout observations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (  # noqa: E402
    CorrectiveAcceptanceError,
    build_synthetic_payload,
    evaluate_corrective,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--metrics", type=Path)
    source.add_argument("--synthetic-pass", action="store_true")
    source.add_argument("--synthetic-fail", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.metrics is not None:
            payload = json.loads(args.metrics.read_text(encoding="utf-8"))
        else:
            payload = build_synthetic_payload(
                ROOT, passing=not bool(args.synthetic_fail)
            )
        result = evaluate_corrective(payload, repo_root=ROOT).report()
    except (OSError, json.JSONDecodeError, CorrectiveAcceptanceError) as exc:
        print(f"S4.7 corrective_02 evaluation: failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
