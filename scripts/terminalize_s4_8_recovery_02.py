#!/usr/bin/env python3
"""Validate or run S4.8 amendment-02 terminalization-only publication."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition.s4_8_recovery_02_terminalizer import (  # noqa: E402
    S48TerminalizationError,
    create_terminalization_authorization,
    preterminal_validate,
    terminalize,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preterminal", action="store_true")
    action.add_argument("--create-authorization", action="store_true")
    action.add_argument("--terminalize", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--authorization-id")
    parser.add_argument("--authorized-at-utc")
    args = parser.parse_args()
    try:
        if args.preterminal:
            if args.authorization_id is not None or args.authorized_at_utc is not None:
                parser.error("--preterminal does not accept authorization arguments")
            result = preterminal_validate(
                args.repo_root,
                implementation_commit=args.implementation_commit,
            )
        elif args.create_authorization:
            if args.authorization_id is None or args.authorized_at_utc is None:
                parser.error(
                    "--create-authorization requires --authorization-id and "
                    "--authorized-at-utc"
                )
            result = create_terminalization_authorization(
                args.repo_root,
                implementation_commit=args.implementation_commit,
                authorization_id=args.authorization_id,
                authorized_at_utc=args.authorized_at_utc,
            )
        else:
            if args.authorization_id is None:
                parser.error("--terminalize requires --authorization-id")
            if args.authorized_at_utc is not None:
                parser.error("--terminalize does not accept --authorized-at-utc")
            result = terminalize(
                args.repo_root,
                implementation_commit=args.implementation_commit,
                authorization_id=args.authorization_id,
            )
    except (
        OSError,
        S48TerminalizationError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"S4.8 amendment-02 terminalization failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
