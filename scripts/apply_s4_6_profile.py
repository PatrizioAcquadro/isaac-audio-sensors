#!/usr/bin/env python3
"""Resolve and apply the frozen S4.6 profile to a runtime configuration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC), str(ROOT)]

from isaac_audio_sensors.core.config import validate_audio_config  # noqa: E402
from isaac_audio_sensors.core.profile_application import (  # noqa: E402
    APPLICATION_CONFIG_PATH,
    ProfileApplicationError,
    apply_profile_application,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-config",
        type=Path,
        default=Path("examples/s4_6/compatible_runtime.toml"),
    )
    parser.add_argument("--mode", choices=("apply", "off"), default="apply")
    parser.add_argument(
        "--application-config",
        type=Path,
        default=APPLICATION_CONFIG_PATH,
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    runtime_path = (
        args.runtime_config
        if args.runtime_config.is_absolute()
        else args.repo_root / args.runtime_config
    )
    try:
        with runtime_path.open("rb") as stream:
            raw = tomllib.load(stream)
        raw.get("audio", {}).pop("profile_application", None)
        result = apply_profile_application(
            validate_audio_config(raw),
            repo_root=args.repo_root,
            mode=args.mode,
            application_config_path=args.application_config,
        )
    except (OSError, ValueError, ProfileApplicationError) as exc:
        print(
            json.dumps(
                {
                    "schema": "ias.s4_6.profile_application_cli.v1",
                    "status": "failed",
                    "issues": [str(exc)],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    payload = result.report()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(text, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
