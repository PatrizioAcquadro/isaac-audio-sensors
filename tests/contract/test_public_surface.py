from __future__ import annotations

import subprocess
import sys

import pytest

from isaac_audio_sensors import AudioSensorFrame, __version__
from isaac_audio_sensors.cli import main


def test_public_package_and_cli_version_match():
    result = subprocess.run(
        [sys.executable, "-m", "isaac_audio_sensors", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert __version__ == "1.10.0"
    assert result.stdout.strip() == __version__
    assert AudioSensorFrame.__module__ == "isaac_audio_sensors.core.types"


def test_cli_exposes_current_product_operations(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for command in (
        "validate-config",
        "simulate",
        "export-trace",
        "export-schema",
        "capabilities",
        "dataset",
        "guided",
    ):
        assert command in help_text
    assert "s4" + "-2" not in help_text


def test_isaac_and_lab_import_without_loading_optional_runtimes():
    code = """
import sys
import isaac_audio_sensors.isaac
import isaac_audio_sensors.lab
assert 'omni.usd' not in sys.modules
assert 'isaaclab' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)
