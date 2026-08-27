from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import tools.release.release_preflight as preflight

VERSION = "3.0.0"


def test_release_preflight_checks_inputs_in_order(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    wheelhouse = tmp_path / "wheelhouse"
    revision = "a" * 40
    calls: list[tuple[str, Path]] = []

    def check_version(root: Path):
        calls.append(("version", root))
        return VERSION, ()

    def check_source(root: Path):
        calls.append(("source", root))
        return revision

    def check_wheelhouse(path: Path):
        calls.append(("wheelhouse", path))
        return ()

    monkeypatch.setattr(preflight, "check_version_sync", check_version)
    monkeypatch.setattr(preflight, "require_clean_source", check_source)
    monkeypatch.setattr(preflight, "validate_wheelhouse", check_wheelhouse)

    assert preflight.release_preflight(
        repo_root=repo_root,
        wheelhouse=wheelhouse,
    ) == (VERSION, revision)
    assert calls == [
        ("version", repo_root.resolve()),
        ("source", repo_root.resolve()),
        ("wheelhouse", wheelhouse),
    ]


def test_release_preflight_rejects_version_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        preflight,
        "check_version_sync",
        lambda _root: (VERSION, ("README mismatch",)),
    )
    monkeypatch.setattr(
        preflight,
        "require_clean_source",
        lambda _root: pytest.fail("source check must not run"),
    )

    with pytest.raises(preflight.ReleasePreflightError, match="README mismatch"):
        preflight.release_preflight(
            repo_root=tmp_path,
            wheelhouse=tmp_path / "wheelhouse",
        )


def test_require_clean_source_rejects_dirty_worktree(tmp_path, monkeypatch):
    def fake_git(_repo_root: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return "a" * 40
        return " M tracked.py\n?? untracked.py\n"

    monkeypatch.setattr(preflight, "_git", fake_git)

    with pytest.raises(preflight.ReleasePreflightError, match="untracked.py"):
        preflight.require_clean_source(tmp_path)


def test_require_clean_source_reports_missing_git(tmp_path, monkeypatch):
    def missing_git(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(preflight.subprocess, "run", missing_git)

    with pytest.raises(preflight.ReleasePreflightError, match="git is required"):
        preflight.require_clean_source(tmp_path)


def test_release_preflight_cli_rejects_empty_wheelhouse():
    with pytest.raises(SystemExit) as exc_info:
        preflight.main(["--wheelhouse", ""])

    assert exc_info.value.code == 2


def test_git_command_failure_uses_stderr(tmp_path, monkeypatch):
    def failed_git(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "git", stderr="git failed\n")

    monkeypatch.setattr(preflight.subprocess, "run", failed_git)

    with pytest.raises(preflight.ReleasePreflightError, match="git failed"):
        preflight.require_clean_source(tmp_path)
