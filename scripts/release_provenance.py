"""Fail-closed Git provenance helpers for canonical release artifacts."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

_FULL_REVISION_RE = re.compile(r"[0-9a-f]{40}")


class ReleaseProvenanceError(RuntimeError):
    """Raised when a release source cannot be tied to a clean Git revision."""


def _git(
    repo_root: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=check,
            capture_output=True,
            text=text,
        )
    except FileNotFoundError as exc:
        raise ReleaseProvenanceError("git is required for release builds") from exc
    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.strip()
            if isinstance(exc.stderr, str) and exc.stderr.strip()
            else "git command failed"
        )
        raise ReleaseProvenanceError(detail) from exc


def head_revision(repo_root: Path) -> str:
    """Return the full commit id for ``HEAD`` or fail if it is unavailable."""

    result = _git(repo_root.resolve(), "rev-parse", "--verify", "HEAD^{commit}")
    assert isinstance(result.stdout, str)
    revision = result.stdout.strip().lower()
    if _FULL_REVISION_RE.fullmatch(revision) is None:
        raise ReleaseProvenanceError(
            f"HEAD did not resolve to a full Git commit id: {revision!r}"
        )
    return revision


def worktree_status(repo_root: Path) -> tuple[str, ...]:
    """Return every tracked or untracked worktree change relevant to a build."""

    result = _git(
        repo_root.resolve(),
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    assert isinstance(result.stdout, str)
    return tuple(line for line in result.stdout.splitlines() if line)


def require_clean_source(
    repo_root: Path, *, expected_revision: str | None = None
) -> str:
    """Return ``HEAD`` only when the entire release worktree is clean."""

    repo_root = repo_root.resolve()
    revision = head_revision(repo_root)
    if expected_revision is not None and expected_revision != revision:
        raise ReleaseProvenanceError(
            "requested source revision does not match HEAD: "
            f"{expected_revision!r} != {revision!r}"
        )
    status = worktree_status(repo_root)
    if status:
        preview = "; ".join(status[:8])
        if len(status) > 8:
            preview += f"; ... ({len(status) - 8} more)"
        raise ReleaseProvenanceError(
            "release source worktree is not clean; commit or isolate every "
            f"tracked/untracked input before building: {preview}"
        )
    return revision


def recorded_revision_findings(repo_root: Path, revision: object) -> list[str]:
    """Validate that a recorded full revision exists and is in local history."""

    if not isinstance(revision, str) or _FULL_REVISION_RE.fullmatch(revision) is None:
        return [f"recorded source revision is not 40 lowercase hex: {revision!r}"]
    try:
        _git(repo_root.resolve(), "cat-file", "-e", f"{revision}^{{commit}}")
        result = _git(
            repo_root.resolve(),
            "merge-base",
            "--is-ancestor",
            revision,
            "HEAD",
            check=False,
        )
    except ReleaseProvenanceError as exc:
        return [f"recorded source revision cannot be verified: {exc}"]
    if result.returncode != 0:
        return [f"recorded source revision is not an ancestor of HEAD: {revision}"]
    return []


def git_file_bytes(repo_root: Path, revision: str, relative_path: str) -> bytes:
    """Read one file exactly as stored in a committed Git tree."""

    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(
        part in {"", ".", ".."} for part in pure_path.parts
    ):
        raise ReleaseProvenanceError(
            f"unsafe Git tree path requested: {relative_path!r}"
        )
    result = _git(
        repo_root.resolve(),
        "show",
        f"{revision}:{pure_path.as_posix()}",
        text=False,
    )
    assert isinstance(result.stdout, bytes)
    return result.stdout


def git_tree_entries(
    repo_root: Path, revision: str, relative_root: str
) -> Iterator[tuple[str, bytes]]:
    """Yield committed files below a repository-relative directory."""

    root = PurePosixPath(relative_root)
    if root.is_absolute() or any(part in {"", ".", ".."} for part in root.parts):
        raise ReleaseProvenanceError(
            f"unsafe Git tree root requested: {relative_root!r}"
        )
    result = _git(
        repo_root.resolve(),
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        revision,
        "--",
        root.as_posix(),
        text=False,
    )
    assert isinstance(result.stdout, bytes)
    prefix = f"{root.as_posix()}/"
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseProvenanceError(
                "release source contains a non-UTF-8 Git path"
            ) from exc
        if not path.startswith(prefix):
            raise ReleaseProvenanceError(
                f"Git returned a path outside {relative_root!r}: {path!r}"
            )
        yield path.removeprefix(prefix), git_file_bytes(repo_root, revision, path)


__all__ = [
    "ReleaseProvenanceError",
    "git_file_bytes",
    "git_tree_entries",
    "head_revision",
    "recorded_revision_findings",
    "require_clean_source",
    "worktree_status",
]
