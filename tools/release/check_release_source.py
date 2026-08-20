"""Verify that canonical artifacts will be built from one clean Git commit."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from .release_provenance import ReleaseProvenanceError, require_clean_source
except ImportError:
    from release_provenance import ReleaseProvenanceError, require_clean_source


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        revision = require_clean_source(repo_root)
    except ReleaseProvenanceError as exc:
        print(f"[release-source] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[release-source] OK {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
