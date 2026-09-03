"""Build the non-ranking R9.2 coverage summary from both valid reports."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .reporting import build_coverage_summary, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("IAS_R9_OUTPUT_ROOT", "build/validation/r9/rev2")),
    )
    args = parser.parse_args(argv)
    reports = [
        json.loads((args.output_root / candidate / "r9.1-rev2-report.json").read_text())
        for candidate in ("steam_audio", "nvidia_rtx_acoustic")
    ]
    summary = build_coverage_summary(reports)
    write_json(args.output_root / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
