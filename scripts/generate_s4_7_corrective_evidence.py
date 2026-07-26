#!/usr/bin/env python3
"""Generate the deterministic S4.7 corrective evidence package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_7_corrective import (  # noqa: E402
    OUTPUT_PATH,
    S47CorrectiveEvidenceError,
    build_evidence_package,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective import (  # noqa: E402
    CorrectiveAcceptanceError,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree-replay", action="store_true")
    args = parser.parse_args()
    try:
        result = build_evidence_package(
            repo_root=args.repo_root,
            output=args.output,
            source_commit=args.source_commit,
            source_tree_replay=args.source_tree_replay,
        )
    except (S47CorrectiveEvidenceError, CorrectiveAcceptanceError, OSError) as exc:
        print(f"S4.7 corrective evidence: failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
