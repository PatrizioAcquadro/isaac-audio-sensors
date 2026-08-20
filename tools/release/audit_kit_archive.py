"""Audit a packaged Kit extension."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
    from content_policy import ContentPolicyError, archive_entries, require_archive


_REQUIRED = {
    "config/extension.toml",
    "isaac_audio_sensors_omni/__init__.py",
    "_vendor/VENDORED.json",
    "_vendor/isaac_audio_sensors/__init__.py",
}


def audit_kit_archive(path: Path) -> None:
    """Require the Kit entry points, vendored package and shared policy."""

    entries = archive_entries(path)
    missing = sorted(_REQUIRED - entries.keys())
    if missing:
        raise ContentPolicyError(f"missing Kit members: {', '.join(missing)}")
    require_archive(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        audit_kit_archive(args.archive)
    except (ContentPolicyError, OSError) as exc:
        print(f"[kit-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[kit-audit] OK {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
