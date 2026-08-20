"""Audit wheel and source distribution contents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .content_policy import ContentPolicyError, require_archive
except ImportError:
    from content_policy import ContentPolicyError, require_archive


def audit_distribution(dist_dir: Path) -> tuple[Path, ...]:
    """Require wheel and source archives to satisfy release policy."""

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if not wheels or not sdists:
        raise ContentPolicyError("dist must contain a wheel and source distribution")
    artifacts = tuple([*wheels, *sdists])
    for artifact in artifacts:
        require_archive(artifact)
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    try:
        artifacts = audit_distribution(args.dist_dir)
    except (ContentPolicyError, OSError) as exc:
        print(f"[distribution-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[distribution-audit] OK ({len(artifacts)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
