#!/usr/bin/env python3
"""Generate the deterministic S4.2 controlled-reference WAV and metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_2_reference import (
    REFERENCE_FILENAME,
    generate_reference,
    metadata_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S4/S4.2/reference")
        / REFERENCE_FILENAME,
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path(
            "outputs/isaac_audio_sensors/S4/S4.2/reference/reference_wav.json"
        ),
    )
    args = parser.parse_args()
    print(metadata_json(generate_reference(args.output, args.metadata)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
