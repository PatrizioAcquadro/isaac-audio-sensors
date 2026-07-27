#!/usr/bin/env python3
"""Prevalidate or explicitly run the forward-only S4.8 recovery amendment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8 import S48Error  # noqa: E402
from isaac_audio_sensors.acquisition.s4_8_recovery import (  # noqa: E402
    create_recovery_grant,
    recovery_preopen_validate,
    run_recovery_evaluation_once,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preopen", action="store_true")
    action.add_argument("--create-grant", action="store_true")
    action.add_argument("--execute", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit")
    parser.add_argument("--authorization-id")
    parser.add_argument("--event-time-utc")
    args = parser.parse_args()
    try:
        if args.preopen:
            result = recovery_preopen_validate(
                args.repo_root,
                source_commit=args.source_commit,
            )
        elif args.create_grant:
            if args.source_commit is None or args.authorization_id is None:
                parser.error(
                    "--create-grant requires --source-commit and "
                    "--authorization-id"
                )
            result = create_recovery_grant(
                args.repo_root,
                source_commit=args.source_commit,
                authorization_id=args.authorization_id,
            )
        else:
            if (
                args.source_commit is None
                or args.authorization_id is None
                or args.event_time_utc is None
            ):
                parser.error(
                    "--execute requires --source-commit, --authorization-id, "
                    "and --event-time-utc"
                )
            result = run_recovery_evaluation_once(
                args.repo_root,
                source_commit=args.source_commit,
                authorization_id=args.authorization_id,
                event_time_utc=args.event_time_utc,
            )
    except (OSError, S48Error, ValueError) as exc:
        print(f"S4.8 recovery failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.execute and result.get("status") != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
