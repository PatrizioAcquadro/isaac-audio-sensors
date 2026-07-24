#!/usr/bin/env python3
"""Build the additive S4.5 corrective-01 evidence package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_5_corrective import (  # noqa: E402
    CORRECTIVE_CONFIG,
    CORRECTIVE_OUTPUT,
    build_corrective_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=CORRECTIVE_OUTPUT)
    parser.add_argument("--config", type=Path, default=CORRECTIVE_CONFIG)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = build_corrective_package(
        repo_root=args.repo_root,
        output=args.output,
        config_path=args.config,
        source_commit=args.source_commit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
