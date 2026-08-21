from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_EXAMPLES = (
    "examples/calibration/read_profile.py",
    "examples/core/room_acoustics_demo.py",
    "examples/core/two_mic_ambiguity.py",
    "examples/isaac_lab/isaac_lab_audio_observation.py",
    "examples/isaac_sim/live_audio_lab.py",
    "examples/recording/read_manifest.py",
)


@pytest.mark.parametrize("relative_path", PUBLIC_EXAMPLES)
def test_public_example_runs_against_installed_package(relative_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, relative_path],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
