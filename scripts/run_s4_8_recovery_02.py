#!/usr/bin/env python3
"""Validate the S4.8 recovery amendment_02 preregistration boundary."""

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
from isaac_audio_sensors.acquisition.s4_8_recovery_02 import (  # noqa: E402
    create_recovery_grant,
    recovery_preopen_validate,
    run_recovery_evaluation_once,
    validate_recovery_evidence_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preopen", action="store_true")
    action.add_argument("--create-grant", action="store_true")
    action.add_argument("--execute", action="store_true")
    action.add_argument("--validate-result", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit")
    parser.add_argument("--authorization-id")
    parser.add_argument("--event-time-utc")
    parser.add_argument("--package", type=Path)
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
                    "--create-grant requires --source-commit and --authorization-id"
                )
            result = create_recovery_grant(
                args.repo_root,
                source_commit=args.source_commit,
                authorization_id=args.authorization_id,
            )
        elif args.execute:
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
        else:
            result = validate_recovery_evidence_package(
                args.repo_root,
                package=args.package,
            )
    except (OSError, S48Error, ValueError) as exc:
        print(f"S4.8 recovery amendment_02 failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
