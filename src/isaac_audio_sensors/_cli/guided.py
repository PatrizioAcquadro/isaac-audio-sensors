"""Guided-workflow CLI command adapter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from isaac_audio_sensors._cli.output import _print_json, _write_json_output


def _guided_run_headless(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.kit.controller import ExtensionController
    from isaac_audio_sensors.kit.headless import (
        HeadlessGuidedSession,
        HeadlessWorkflowError,
    )

    try:
        payload = HeadlessGuidedSession(ExtensionController()).run_from_config(
            args.config,
            session_dir=args.session_dir,
            export_dir=args.export_dir,
            frames=args.frames,
            seconds=args.seconds,
        )
    except (HeadlessWorkflowError, OSError, ValueError) as exc:
        payload = {
            "status": "failed",
            "config": str(args.config),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if args.json_path == "-":
            _print_json(payload)
        else:
            print(f"guided headless run failed: {exc}", file=sys.stderr)
            if args.json_path is not None:
                _write_json_output(Path(args.json_path), payload)
        return 1
    if args.json_path == "-":
        _print_json(payload)
    else:
        print(
            "guided headless run passed: "
            f"frames={payload['recording_stats']['frames']} "
            f"export={payload['export_path']}"
        )
        if args.json_path is not None:
            _write_json_output(Path(args.json_path), payload)
    return 0
