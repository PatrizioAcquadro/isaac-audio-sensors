"""Fast coverage for the S2.9 reliability and endurance gate harnesses."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reliability() -> ModuleType:
    return _load_script("live_reliability_gate")


def _assert_record(record: dict, scenario: str) -> None:
    assert set(record) == {"scenario", "status", "detail"}
    assert record["scenario"] == scenario
    assert record["status"] == "passed", record["detail"]
    assert isinstance(record["detail"], dict)


def test_cancellation_restart_helper_is_resumable(reliability, tmp_path):
    record = reliability.scenario_cancellation_restart(
        tmp_path / "cancel",
        frame_count=7,
        shard_max_frames=2,
        seed=17,
    )

    _assert_record(record, "cancellation_restart")
    detail = record["detail"]
    assert detail["classification_before_restart"] == "in-progress-or-aborted"
    assert detail["semantic_equal_to_control"] is True
    assert detail["accounting"]["unreported_frames"] == 0


def test_simulator_replacement_helper_requires_new_session(reliability, tmp_path):
    record = reliability.scenario_simulator_replacement(
        tmp_path / "replacement",
        frame_count=5,
        shard_max_frames=2,
    )

    _assert_record(record, "simulator_replacement")
    detail = record["detail"]
    assert detail["replacement_operation"] == "new_session"
    assert detail["mid_session_rejection"]["accepted"] is False
    assert "disagrees with configuration" in detail["mid_session_rejection"][
        "located_error"
    ]


def test_dependency_removal_helper_keeps_published_prefix(reliability, tmp_path):
    record = reliability.scenario_dependency_removal(
        tmp_path / "dependency",
        frame_count=4,
        shard_max_frames=2,
    )

    _assert_record(record, "dependency_removal")
    detail = record["detail"]
    assert detail["completion_state"] == "incomplete"
    assert detail["published_prefix_shards"] == 1
    assert detail["failed_shard_marker_absent"] is True


def test_disk_failure_helper_covers_all_atomic_phases(reliability, tmp_path):
    record = reliability.scenario_disk_failure(
        tmp_path / "disk",
        frame_count=7,
        shard_max_frames=2,
    )

    _assert_record(record, "disk_failure")
    phases = record["detail"]["phases"]
    assert [item["phase"] for item in phases] == ["payload", "promotion", "marker"]
    assert all(item["published_prefix_shards"] == 1 for item in phases)
    assert all(item["failed_shard_marker_absent"] for item in phases)


def test_sigkill_resume_helper_matches_control_prefix(reliability, tmp_path):
    record = reliability.scenario_resume(
        tmp_path / "resume",
        frame_count=7,
        shard_max_frames=2,
    )

    _assert_record(record, "resume")
    detail = record["detail"]
    assert detail["classification_before_resume"] == "in-progress-or-aborted"
    assert detail["shared_prefix_semantic_equal"] is True
    assert detail["full_semantic_equal"] is True


def test_endurance_script_ast_and_argparse_smoke():
    path = REPO_ROOT / "scripts/live_endurance_capture_gate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert {"build_parser", "compute_shard_max_frames", "main"} <= functions

    endurance = _load_script("live_endurance_capture_gate")
    args = endurance.build_parser().parse_args(["--minutes", "1.5"])
    assert args.minutes == 1.5
    assert endurance.compute_shard_max_frames(0.05) == 6_000
