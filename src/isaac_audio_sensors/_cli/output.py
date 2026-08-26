"""CLI output helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _write_json_output(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _fail(label: str, exc: BaseException) -> int:
    print(f"{label} failed: {exc}", file=sys.stderr)
    return 1
