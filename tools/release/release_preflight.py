"""Validate every source and dependency input before a release build."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    from .build_kit_extension import validate_wheelhouse
    from .check_version_sync import check_version_sync
except ImportError:
    from build_kit_extension import validate_wheelhouse
    from check_version_sync import check_version_sync

_FULL_REVISION_RE = re.compile(r"[0-9a-f]{40}")


class ReleasePreflightError(RuntimeError):
    """Raised when release inputs are not ready for a canonical build."""


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
        raise ReleasePreflightError("git is required for release builds") from exc
    except subprocess.CalledProcessError as exc:
        raise ReleasePreflightError(exc.stderr.strip() or "git command failed") from exc
    return result.stdout


def require_clean_source(repo_root: Path) -> str:
    """Return HEAD when every release input is committed."""

    repo_root = repo_root.resolve()
    revision = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if _FULL_REVISION_RE.fullmatch(revision) is None:
        raise ReleasePreflightError(
            f"HEAD is not a full Git commit id: {revision!r}"
        )

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
        raise ReleasePreflightError(
            "release source worktree is not clean; commit or isolate every "
            f"tracked/untracked input before building: {preview}"
        )
    return revision


def release_preflight(*, repo_root: Path, wheelhouse: Path) -> tuple[str, str]:
    """Validate synchronized source, one clean revision, and locked wheels."""

    repo_root = repo_root.resolve()
    version, findings = check_version_sync(repo_root)
    if findings:
        raise ReleasePreflightError(
            "version synchronization failed: " + "; ".join(findings)
        )
    revision = require_clean_source(repo_root)
    validate_wheelhouse(wheelhouse)
    return version, revision


def _nonempty_path(value: str) -> Path:
    if not value:
        raise argparse.ArgumentTypeError("wheelhouse path must not be empty")
    return Path(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=_nonempty_path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository layout to check (defaults to this script's checkout).",
    )
    args = parser.parse_args(argv)
    try:
        version, revision = release_preflight(
            repo_root=args.repo_root,
            wheelhouse=args.wheelhouse,
        )
    except (OSError, ValueError, ReleasePreflightError) as exc:
        print(f"[release-preflight] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[release-preflight] OK {version} {revision} {args.wheelhouse.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
