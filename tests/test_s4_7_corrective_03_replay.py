from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "outputs/isaac_audio_sensors/S4/S4.7_corrective_03"


def test_clean_source_corrective_03_replay_is_byte_identical() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/replay_s4_7_corrective_03.py"),
            "--canonical",
            str(PACKAGE),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["byte_identical"] is True
    assert report["scientific_semantics_exact"] is True
    assert report["file_count"] == 18
    assert report["holdout_observations_accessed"] == 0
