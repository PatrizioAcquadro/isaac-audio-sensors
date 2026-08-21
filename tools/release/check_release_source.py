"""Verify that canonical artifacts will be built from one clean Git commit."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_FULL_REVISION_RE = re.compile(r"[0-9a-f]{40}")


class ReleaseSourceError(RuntimeError):
    """Raised when release inputs are not one clean Git revision."""


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ReleaseSourceError("git is required for release builds") from exc
    except subprocess.CalledProcessError as exc:
        raise ReleaseSourceError(exc.stderr.strip() or "git command failed") from exc
    return result.stdout


def require_clean_source(repo_root: Path) -> str:
    """Return HEAD when every release input is committed."""

    repo_root = repo_root.resolve()
    revision = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if _FULL_REVISION_RE.fullmatch(revision) is None:
        raise ReleaseSourceError(f"HEAD is not a full Git commit id: {revision!r}")

    status = tuple(
        line
        for line in _git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ).splitlines()
        if line
    )
    if status:
        preview = "; ".join(status[:8])
        if len(status) > 8:
            preview += f"; ... ({len(status) - 8} more)"
        raise ReleaseSourceError(
            "release source worktree is not clean; commit or isolate every "
            f"tracked/untracked input before building: {preview}"
        )
    return revision


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        revision = require_clean_source(repo_root)
    except ReleaseSourceError as exc:
        print(f"[release-source] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[release-source] OK {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
