"""Audit an optional acoustics pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
    from content_policy import ContentPolicyError, archive_entries, require_archive


_REQUIRED = {"pack_manifest.json", "requirements.lock", "install_pack.py"}


def audit_acoustic_pack(path: Path) -> None:
    """Require declared wheels and recursively apply release policy."""

    entries = archive_entries(path)
    missing = sorted(_REQUIRED - entries.keys())
    if missing:
        raise ContentPolicyError(f"missing pack members: {', '.join(missing)}")
    try:
        manifest = json.loads(entries["pack_manifest.json"])
        declared = manifest.get("pack_distributions", manifest.get("artifacts"))
        wheel_names = {
            f"wheels/{item.get('wheel', item.get('filename'))}" for item in declared
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ContentPolicyError("invalid pack manifest") from exc
    missing_wheels = sorted(wheel_names - entries.keys())
    if missing_wheels:
        raise ContentPolicyError(f"missing pack wheels: {', '.join(missing_wheels)}")
    require_archive(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        audit_acoustic_pack(args.archive)
    except (ContentPolicyError, OSError) as exc:
        print(f"[pack-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[pack-audit] OK {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
