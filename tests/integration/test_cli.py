"""Focused CLI adapter tests."""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path

import pytest

from isaac_audio_sensors.cli import main
from isaac_audio_sensors.recording import (
    read_dataset_manifest,
    read_split_plan,
    validate_dataset,
)

CONFIG = Path("examples/configs/isaac_audio_sensors_demo.toml")
REFERENCE = Path("tests/fixtures/recording/session")


def test_core_commands_render_service_results(tmp_path, capsys):
    assert main(["validate-config", str(CONFIG)]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["scene_id"] == "demo_audio_lab_single_source"

    trace_path = tmp_path / "frame.json"
    assert (
        main(
            [
                "simulate",
                str(CONFIG),
                "--backend",
                "analytic_acoustics",
                "--array-id",
                "rig_front",
                "--out",
                str(trace_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(trace_path.read_text())
    frame = json.loads(trace_path.read_text())
    assert frame["producer_id"] == "analytic_acoustics"
    assert frame["observations"] == []
    assert frame["diagnostics"]["analytic_solver"] == {
        "solver_id": "free_field_direct",
        "provider": "core",
        "provider_version": "core",
        "environment_kind": "free_field",
    }

    schema_path = tmp_path / "frame.schema.json"
    assert main(["export-schema", "--out", str(schema_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"wrote": str(schema_path)}
    packaged = files("isaac_audio_sensors.schemas").joinpath(
        "audio_sensor_frame.v3.schema.json"
    )
    assert schema_path.read_bytes() == packaged.read_bytes()

    assert main(["capabilities", "--json"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["fidelity_levels"]


@pytest.mark.parametrize("removed", ("--max-events", "--timestamp-ms"))
def test_simulate_rejects_removed_cli_arguments(removed):
    with pytest.raises(SystemExit):
        main(["simulate", str(CONFIG), removed, "0"])


def test_zero_observation_cap_keeps_active_soundscape(capsys):
    assert main(["simulate", str(CONFIG), "--max-observations", "0"]) == 0
    frame = json.loads(capsys.readouterr().out)

    assert frame["observations"] == []
    assert any(value > 0.0 for value in frame["aggregate_per_mic_rms"].values())

def test_dataset_commands_delegate_to_recording_services(tmp_path, capsys):
    assert main(["dataset", "validate", str(REFERENCE), "--json", "-"]) == 0
    assert json.loads(capsys.readouterr().out) == validate_dataset(REFERENCE).to_dict()

    assert main(["dataset", "stats", str(REFERENCE), "--json", "-"]) == 0
    assert json.loads(capsys.readouterr().out) == (
        validate_dataset(REFERENCE).statistics.to_dict()
    )

    root = tmp_path / "session"
    shutil.copytree(REFERENCE, root)
    plan_path = tmp_path / "split.json"
    split_args = [
        "dataset",
        "split",
        str(root),
        "--kind",
        "tvt",
        "--ratios",
        "train=0.5,test=0.5",
        "--seed",
        "7",
        "--out",
        str(plan_path),
        "--apply",
    ]
    assert main(split_args) == 0
    assert capsys.readouterr().out.strip() == read_split_plan(plan_path).plan_sha256
    assert read_dataset_manifest(root / "manifest.json").splits

    assert main(["dataset", "validate", str(tmp_path / "missing")]) == 1
    assert "dataset validation failed" in capsys.readouterr().err

    assert (
        main(
            [
                "dataset",
                "split",
                str(root),
                "--kind",
                "fit-holdout",
                "--ratios",
                "fit=0.5,holdout=0.5",
                "--seed",
                "7",
                "--apply",
            ]
        )
        == 1
    )
    assert "plan-level artifact" in capsys.readouterr().err


def test_guided_command_renders_expected_failure(tmp_path, capsys):
    config = tmp_path / "missing.json"
    assert (
        main(
            [
                "guided",
                "run-headless",
                str(config),
                "--session-dir",
                str(tmp_path / "session"),
                "--export-dir",
                str(tmp_path / "export"),
                "--frames",
                "1",
                "--json",
                "-",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["error_type"] == "HeadlessWorkflowError"
    assert payload["error"].startswith("setup:")
