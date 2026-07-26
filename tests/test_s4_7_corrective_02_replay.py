from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.7_corrective_02"
)


def test_canonical_corrective_02_replay_is_byte_identical() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_s4_7_corrective_02.py",
            "--canonical",
            CANONICAL.relative_to(ROOT).as_posix(),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["byte_identical"] is True
    assert report["file_count"] == 18


def test_non_byte_identical_package_is_rejected_by_replay(
    tmp_path: Path,
) -> None:
    tampered = tmp_path / "S4.7_corrective_02"
    shutil.copytree(CANONICAL, tampered)
    report_path = tampered / "determinism_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["details"]["run_count"] = 3
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_s4_7_corrective_02.py",
            "--canonical",
            str(tampered),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "byte-for-byte replay mismatch" in (result.stderr or result.stdout)
