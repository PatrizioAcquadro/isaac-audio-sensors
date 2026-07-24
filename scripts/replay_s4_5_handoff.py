#!/usr/bin/env python3
"""Regenerate and byte-compare the canonical S4.5 handoff package."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.acquisition.s4_5_handoff import (  # noqa: E402
    S45HandoffError,
    build_handoff_package,
    load_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--canonical", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    canonical = (
        args.canonical if args.canonical.is_absolute() else repo_root / args.canonical
    )
    provenance = load_json(canonical / "provenance.v1.json", label="provenance")
    source_commit = str(provenance.get("source_commit", ""))
    with tempfile.TemporaryDirectory(prefix="ias-s4-5-handoff-replay-") as tmp:
        replay = Path(tmp) / "package"
        build_handoff_package(
            repo_root=repo_root, output=replay, source_commit=source_commit
        )
        canonical_files = {
            path.name: path.read_bytes()
            for path in canonical.iterdir()
            if path.is_file()
        }
        replay_files = {
            path.name: path.read_bytes() for path in replay.iterdir() if path.is_file()
        }
        if canonical_files != replay_files:
            differing = sorted(
                name
                for name in set(canonical_files) | set(replay_files)
                if canonical_files.get(name) != replay_files.get(name)
            )
            raise S45HandoffError(f"byte-for-byte replay mismatch: {differing}")
    print(
        json.dumps(
            {
                "schema": "ias.s4_5.active_handoff_replay_result.v1",
                "status": "passed",
                "source_commit": source_commit,
                "canonical": str(canonical),
                "byte_identical": True,
                "file_count": len(canonical_files),
                "holdout_observations_accessed": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
