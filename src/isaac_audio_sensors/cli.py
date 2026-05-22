"""Command line interface for the 0.1.0 audio-sensor MVP."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict, write_frame_trace
from isaac_audio_sensors.core.schema import write_audio_sensor_frame_json_schema
from isaac_audio_sensors.core.types import AudioTimeWindow


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``isaac-audio-sensors`` CLI."""

    parser = argparse.ArgumentParser(prog="isaac-audio-sensors")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config")
    validate_parser.add_argument("config", type=Path)

    simulate_parser = subparsers.add_parser("simulate")
    simulate_parser.add_argument("config", type=Path)
    simulate_parser.add_argument("--backend", default=None)
    simulate_parser.add_argument("--array-id", default=None)
    simulate_parser.add_argument("--timestamp-ms", type=int, default=0)
    simulate_parser.add_argument("--start-time-s", type=float, default=0.0)
    simulate_parser.add_argument("--end-time-s", type=float, default=1.0)
    simulate_parser.add_argument("--max-events", type=int, default=None)
    simulate_parser.add_argument("--out", type=Path, default=None)

    trace_parser = subparsers.add_parser("export-trace")
    trace_parser.add_argument("config", type=Path)
    trace_parser.add_argument("--backend", default=None)
    trace_parser.add_argument("--array-id", default=None)
    trace_parser.add_argument("--timestamp-ms", type=int, default=0)
    trace_parser.add_argument("--start-time-s", type=float, default=0.0)
    trace_parser.add_argument("--end-time-s", type=float, default=1.0)
    trace_parser.add_argument("--max-events", type=int, default=None)
    trace_parser.add_argument("--out", type=Path, required=True)

    schema_parser = subparsers.add_parser("export-schema")
    schema_parser.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "validate-config":
        config = load_audio_config(args.config)
        print(
            json.dumps(
                {
                    "scene_id": config.scene_id,
                    "default_backend": config.default_backend,
                    "arrays": sorted(config.arrays),
                    "sources": [source.source_id for source in config.sources],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "simulate":
        frame = _simulate_from_args(args)
        payload = frame_to_trace_dict(frame)
        if args.out is not None:
            write_frame_trace(frame, args.out)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "export-trace":
        frame = _simulate_from_args(args)
        write_frame_trace(frame, args.out)
        print(json.dumps({"wrote": str(args.out)}, sort_keys=True))
        return 0

    if args.command == "export-schema":
        write_audio_sensor_frame_json_schema(args.out)
        print(json.dumps({"wrote": str(args.out)}, sort_keys=True))
        return 0

    parser.error(f"Unhandled command {args.command!r}.")
    return 2


def _simulate_from_args(args: argparse.Namespace):
    config = load_audio_config(args.config)
    backend_id = args.backend or config.default_backend
    array_id = args.array_id or next(iter(config.arrays))
    scene = build_scene_snapshot(config, timestamp_ms=args.timestamp_ms)
    sensor = scene.array_by_id(array_id)
    time_window = AudioTimeWindow(
        start_time_s=getattr(args, "start_time_s", 0.0),
        end_time_s=getattr(args, "end_time_s", 1.0),
        timestamp_ms=args.timestamp_ms,
        sample_rate_hz=sensor.sample_rate_hz,
        frame_index=0,
        max_events=getattr(args, "max_events", None),
    )
    backend_kwargs = {}
    if backend_id in {"tdoa_synthetic", "room_acoustics"}:
        backend_kwargs = {
            "speed_of_sound_mps": config.speed_of_sound_mps,
            "ambiguity_policy": config.tdoa_ambiguity_policy,
        }
    backend = get_backend(backend_id, **backend_kwargs)
    return backend.simulate(scene, sensor, time_window)


if __name__ == "__main__":
    raise SystemExit(main())
