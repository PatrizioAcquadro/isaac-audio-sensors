"""Deterministic package tests for the S4.6 evidence machinery."""

from __future__ import annotations

import json
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_6 import (
    EXACT_REPLAY_COMMAND,
    REQUIRED_FILES,
    build_evidence_package,
)

ROOT = Path(__file__).resolve().parents[1]
DUMMY_COMMIT = "0" * 40


def _files(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in path.iterdir() if item.is_file()}


def test_source_tree_evidence_build_is_complete_and_passing(tmp_path: Path) -> None:
    output = tmp_path / "package"
    result = build_evidence_package(
        repo_root=ROOT,
        output=output,
        source_commit=DUMMY_COMMIT,
        source_tree_replay=True,
    )
    assert result["status"] == "passed"
    assert {path.name for path in output.iterdir()} == REQUIRED_FILES
    final = json.loads((output / "final_validation.json").read_text())
    assert final["status"] == "passed"
    assert final["authorized_component_count"] == 7
    assert final["holdout_observations_accessed"] == 0
    assert final["later_phases_started"] == []


def test_two_source_tree_builds_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for output in (first, second):
        build_evidence_package(
            repo_root=ROOT,
            output=output,
            source_commit=DUMMY_COMMIT,
            source_tree_replay=True,
        )
    assert _files(first) == _files(second)


def test_manifest_covers_every_non_manifest_file(tmp_path: Path) -> None:
    output = tmp_path / "package"
    build_evidence_package(
        repo_root=ROOT,
        output=output,
        source_commit=DUMMY_COMMIT,
        source_tree_replay=True,
    )
    names = {
        line.split("  ", 1)[1]
        for line in (output / "SHA256SUMS").read_text().splitlines()
    }
    assert names == REQUIRED_FILES - {"SHA256SUMS"}


def test_reproduction_command_and_phase_boundary_are_exact(tmp_path: Path) -> None:
    output = tmp_path / "package"
    build_evidence_package(
        repo_root=ROOT,
        output=output,
        source_commit=DUMMY_COMMIT,
        source_tree_replay=True,
    )
    reproduction = json.loads((output / "reproduction.json").read_text())
    preservation = json.loads(
        (output / "preservation_phase_boundary_report.json").read_text()
    )
    assert reproduction["command"] == EXACT_REPLAY_COMMAND
    assert reproduction["source_commit"] == DUMMY_COMMIT
    assert preservation["status"] == "passed"
    assert preservation["holdout_observations_accessed"] == 0
    assert preservation["s4_8_access_grant_created"] is False
    assert preservation["later_phases_started"] == []
