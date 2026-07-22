"""Clean-checkout regression gate for committed S4.4 evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_committed_s4_4_evidence_passes_final_tracked_validation() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_s4_4_integrity.py",
            "--require-final",
            "--require-tracked",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["holdout_opened"] is False
    assert report["content_derived_values_returned"] is False
    assert report["machine_local_hash_only"] is None
