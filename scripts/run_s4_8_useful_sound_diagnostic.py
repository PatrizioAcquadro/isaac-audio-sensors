#!/usr/bin/env python3
"""Run the isolated reused-holdout S4.8 useful-sound diagnostic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_8 import pretty_json
from isaac_audio_sensors.acquisition.s4_8_useful_sound_diagnostic import (
    UsefulSoundDiagnosticError,
    run_reused_holdout_diagnostic,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        parser.error("--output must be outside the repository")
    try:
        result = run_reused_holdout_diagnostic(
            root,
            progress_callback=lambda message: print(
                message,
                file=sys.stderr,
                flush=True,
            ),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(pretty_json(result), encoding="utf-8")
    except (OSError, UsefulSoundDiagnosticError) as exc:
        print(f"S4.8 useful-sound diagnostic failed: {exc}", file=sys.stderr)
        return 1
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
