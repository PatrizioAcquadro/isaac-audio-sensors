"""Regression tests for clean, commit-bound release artifact provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.release_provenance import (
    ReleaseProvenanceError,
    git_file_bytes,
    git_tree_entries,
    recorded_revision_findings,
    require_clean_source,
)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "src" / "package").mkdir(parents=True)
    (repo / "src" / "package" / "__init__.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.name", "Release Test")
    _run_git(repo, "config", "user.email", "release-test@example.invalid")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-qm", "Initial source")
    return repo, _run_git(repo, "rev-parse", "HEAD")


def test_clean_source_is_bound_to_exact_head_and_committed_tree(tmp_path):
    repo, revision = _repository(tmp_path)

    assert require_clean_source(repo) == revision
    assert require_clean_source(repo, expected_revision=revision) == revision
    assert git_file_bytes(repo, revision, "src/package/__init__.py") == b"VALUE = 1\n"
    assert list(git_tree_entries(repo, revision, "src/package")) == [
        ("__init__.py", b"VALUE = 1\n")
    ]
    assert recorded_revision_findings(repo, revision) == []


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_release_source_rejects_dirty_tracked_and_untracked_inputs(
    tmp_path, dirty_kind
):
    repo, _revision = _repository(tmp_path)
    if dirty_kind == "tracked":
        (repo / "src" / "package" / "__init__.py").write_text(
            "VALUE = 2\n", encoding="utf-8"
        )
    else:
        (repo / "docs").mkdir()
        (repo / "docs" / "untracked.md").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(ReleaseProvenanceError, match="worktree is not clean"):
        require_clean_source(repo)


def test_release_source_rejects_revision_mismatch_and_non_ancestor(tmp_path):
    repo, revision = _repository(tmp_path)

    with pytest.raises(ReleaseProvenanceError, match="does not match HEAD"):
        require_clean_source(repo, expected_revision="0" * 40)
    assert "not 40 lowercase hex" in recorded_revision_findings(
        repo, "not-a-revision"
    )[0]

    other = tmp_path / "other"
    other.mkdir()
    _run_git(other, "init", "-q")
    _run_git(other, "config", "user.name", "Release Test")
    _run_git(other, "config", "user.email", "release-test@example.invalid")
    (other / "other.txt").write_text("other\n", encoding="utf-8")
    _run_git(other, "add", ".")
    _run_git(other, "commit", "-qm", "Unrelated source")
    unrelated = _run_git(other, "rev-parse", "HEAD")
    _run_git(repo, "fetch", "-q", str(other), unrelated)

    assert revision != unrelated
    assert "not an ancestor" in recorded_revision_findings(repo, unrelated)[0]
