"""Top-level CLI command adapters."""

from __future__ import annotations

import argparse
import json

from isaac_audio_sensors._cli.output import _fail, _print_json


def _validate_config(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.core.config import load_audio_config

    try:
        config = load_audio_config(args.config)
    except (OSError, ValueError) as exc:
        return _fail("config validation", exc)
    _print_json(
        {
            "scene_id": config.scene_id,
            "default_backend": config.default_backend,
            "arrays": sorted(config.arrays),
            "sources": [source.source_id for source in config.sources],
        }
    )
    return 0


def _simulate(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.core.exceptions import IsaacAudioSensorsError
    from isaac_audio_sensors.core.io.traces import (
        frame_to_trace_dict,
        write_frame_trace,
    )
    from isaac_audio_sensors.core.simulation import simulate_from_config

    try:
        frame = simulate_from_config(
            args.config,
            backend_id=args.backend,
            array_id=args.array_id,
            start_time_s=args.start_time_s,
            end_time_s=args.end_time_s,
            energy_threshold_dbfs=args.energy_threshold_dbfs,
            max_observations=args.max_observations,
            doa_enabled=args.enable_doa,
        )
        if args.out is not None:
            write_frame_trace(frame, args.out)
    except (IsaacAudioSensorsError, OSError, ValueError) as exc:
        return _fail("simulation", exc)
    _print_json(frame_to_trace_dict(frame))
    return 0


def _export_schema(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.schemas.generate import write_json_schema

    try:
        output = write_json_schema(args.schema, args.out)
    except (OSError, ValueError) as exc:
        return _fail("schema export", exc)
    print(json.dumps({"wrote": str(output)}, sort_keys=True))
    return 0


def _capabilities(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.core.capabilities import discover_capabilities
    from isaac_audio_sensors.core.exceptions import IsaacAudioSensorsError

    try:
        report = discover_capabilities()
    except (IsaacAudioSensorsError, OSError, ValueError) as exc:
        return _fail("capability discovery", exc)
    if args.json:
        _print_json(report.to_dict())
    else:
        for capability in report.capabilities:
            detail = (
                f" ({capability.actionable_message})"
                if capability.actionable_message
                else ""
            )
            print(
                f"{capability.capability_id}: {capability.status} "
                f"[{capability.origin}]{detail}"
            )
    return 0
