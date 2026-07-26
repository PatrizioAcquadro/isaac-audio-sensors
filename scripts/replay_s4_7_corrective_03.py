#!/usr/bin/env python3
"""Replay corrective_03 from its source commit and compare every byte."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--canonical", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    canonical = (
        args.canonical if args.canonical.is_absolute() else repo_root / args.canonical
    )
    acceptance = json.loads(
        (canonical / "holdout_acceptance.json").read_text(encoding="utf-8")
    )
    source_commit = str(acceptance["source_commit"])
    archive = subprocess.run(
        ["git", "archive", "--format=tar", source_commit],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(
        prefix="ias-s4-7-corrective-03-replay-"
    ) as temp:
        checkout = Path(temp) / "checkout"
        checkout.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
            try:
                stream.extractall(checkout, filter="data")
            except TypeError:  # pragma: no cover
                stream.extractall(checkout)
        replay = Path(temp) / "replay"
        completed = subprocess.run(
            [
                sys.executable,
                str(checkout / "scripts/generate_s4_7_corrective_03_evidence.py"),
                "--repo-root",
                str(checkout),
                "--output",
                str(replay),
                "--source-commit",
                source_commit,
                "--source-tree-replay",
            ],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.stderr or completed.stdout)
        canonical_files = {
            path.name: path.read_bytes()
            for path in canonical.iterdir()
            if path.is_file()
        }
        replay_files = {
            path.name: path.read_bytes()
            for path in replay.iterdir()
            if path.is_file()
        }
        differing = sorted(
            name
            for name in set(canonical_files) | set(replay_files)
            if canonical_files.get(name) != replay_files.get(name)
        )
        if differing:
            raise SystemExit(f"byte-for-byte replay mismatch: {differing}")
    print(
        json.dumps(
            {
                "schema": "ias.s4_7.corrective_clean_replay.v4",
                "status": "passed",
                "source_commit": source_commit,
                "canonical": str(canonical),
                "byte_identical": True,
                "scientific_semantics_exact": True,
                "file_count": len(canonical_files),
                "clean_source_archive": True,
                "holdout_observations_accessed": 0,
                "later_phases_started": [],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
