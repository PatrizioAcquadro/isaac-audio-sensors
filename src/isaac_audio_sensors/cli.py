"""Command line interface for isaac-audio-sensors."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.capabilities import discover_capabilities
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict, write_frame_trace
from isaac_audio_sensors.core.types import AudioTimeWindow
from isaac_audio_sensors.isaac.headless_workflow import (
    HeadlessGuidedSession,
    HeadlessWorkflowError,
)
from isaac_audio_sensors.recording import (
    DatasetLayoutError,
    DatasetSplitError,
    apply_split_plan,
    build_split_plan,
    validate_dataset,
    write_json_atomic,
    write_split_plan,
)
from isaac_audio_sensors.recording.serialization import (
    manifest_to_dict,
    read_dataset_manifest,
)


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
    schema_parser.add_argument(
        "--schema",
        choices=("frame", "dataset-manifest", "calibration-profile"),
        default="frame",
    )
    schema_parser.add_argument("--out", type=Path, default=None)

    capabilities_parser = subparsers.add_parser("capabilities")
    capabilities_parser.add_argument("--json", action="store_true")

    dataset_parser = subparsers.add_parser("dataset")
    dataset_subparsers = dataset_parser.add_subparsers(
        dest="dataset_command", required=True
    )
    dataset_validate_parser = dataset_subparsers.add_parser("validate")
    dataset_validate_parser.add_argument("session_root", type=Path)
    dataset_validate_parser.add_argument("--allow-incomplete", action="store_true")
    dataset_validate_parser.add_argument("--deep-audio", action="store_true")
    dataset_validate_parser.add_argument("--json", dest="json_path", default=None)

    dataset_stats_parser = dataset_subparsers.add_parser("stats")
    dataset_stats_parser.add_argument("session_root", type=Path)
    dataset_stats_parser.add_argument("--allow-incomplete", action="store_true")
    dataset_stats_parser.add_argument("--json", dest="json_path", default=None)

    dataset_split_parser = dataset_subparsers.add_parser("split")
    dataset_split_parser.add_argument("session_root", type=Path)
    dataset_split_parser.add_argument(
        "--kind", choices=("tvt", "fit-holdout"), required=True
    )
    dataset_split_parser.add_argument("--ratios", required=True)
    dataset_split_parser.add_argument("--seed", type=int, required=True)
    dataset_split_parser.add_argument("--grouping-key", default=None)
    dataset_split_parser.add_argument("--out", type=Path, default=None)
    dataset_split_parser.add_argument("--apply", action="store_true")

    guided_parser = subparsers.add_parser("guided")
    guided_subparsers = guided_parser.add_subparsers(
        dest="guided_command", required=True
    )
    guided_run_parser = guided_subparsers.add_parser("run-headless")
    guided_run_parser.add_argument("config", type=Path)
    guided_run_parser.add_argument("--session-dir", type=Path, required=True)
    guided_run_parser.add_argument("--export-dir", type=Path, required=True)
    guided_duration = guided_run_parser.add_mutually_exclusive_group()
    guided_duration.add_argument("--frames", type=int, default=None)
    guided_duration.add_argument("--seconds", type=float, default=None)
    guided_run_parser.add_argument("--json", dest="json_path", default=None)

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
        names = {
            "frame": "audio_sensor_frame.v1.schema.json",
            "dataset-manifest": "audio_dataset_manifest.v1.schema.json",
            "calibration-profile": "audio_calibration_profile.v1.schema.json",
        }
        source = files("isaac_audio_sensors.schemas").joinpath(names[args.schema])
        output_path = args.out or Path(names[args.schema])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            source.open("rb") as source_stream,
            output_path.open("wb") as output_stream,
        ):
            shutil.copyfileobj(source_stream, output_stream)
        print(json.dumps({"wrote": str(output_path)}, sort_keys=True))
        return 0

    if args.command == "capabilities":
        report = discover_capabilities()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
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

    if args.command == "dataset":
        if args.dataset_command == "split":
            try:
                return _dataset_split(args)
            except (DatasetLayoutError, DatasetSplitError, OSError, ValueError) as exc:
                print(f"dataset split failed: {exc}", file=sys.stderr)
                return 1
        try:
            report = validate_dataset(
                args.session_root,
                allow_incomplete=args.allow_incomplete,
                deep_audio=(
                    args.deep_audio if args.dataset_command == "validate" else False
                ),
            )
        except DatasetLayoutError as exc:
            parser.error(str(exc))
        if args.dataset_command == "validate":
            payload = report.to_dict()
            if args.json_path == "-":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    f"dataset validation {report.status}: "
                    f"episodes={report.statistics.episode_count} "
                    f"shards={report.statistics.shard_count} "
                    f"frames={report.statistics.frame_count} "
                    f"errors={report.error_count} warnings={report.warning_count}"
                )
                if args.json_path is not None:
                    _write_json_output(Path(args.json_path), payload)
            return 1 if report.status == "failed" else 0
        if args.dataset_command == "stats":
            payload = report.statistics.to_dict()
            if args.json_path in {None, "-"}:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    "dataset statistics: "
                    f"episodes={report.statistics.episode_count} "
                    f"shards={report.statistics.shard_count} "
                    f"frames={report.statistics.frame_count}"
                )
                _write_json_output(Path(args.json_path), payload)
            return 1 if report.status == "failed" else 0
        parser.error(f"Unhandled dataset command {args.dataset_command!r}.")

    if args.command == "guided":
        if args.guided_command == "run-headless":
            return _guided_run_headless(args)
        parser.error(f"Unhandled guided command {args.guided_command!r}.")

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
    backend_kwargs.update(
        effects=config.effects,
        runtime_profile=config.runtime_profile,
    )
    backend = get_backend(backend_id, **backend_kwargs)
    return backend.simulate(scene, sensor, time_window)


def _write_json_output(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _guided_run_headless(args: argparse.Namespace) -> int:
    try:
        payload = HeadlessGuidedSession().run_from_config(
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
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"guided headless run failed: {exc}", file=sys.stderr)
            if args.json_path is not None:
                _write_json_output(Path(args.json_path), payload)
        return 1

    if args.json_path == "-":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "guided headless run passed: "
            f"frames={payload['recording_stats']['frames']} "
            f"export={payload['export_path']}"
        )
        if args.json_path is not None:
            _write_json_output(Path(args.json_path), payload)
    return 0


def _dataset_split(args: argparse.Namespace) -> int:
    kind = {
        "tvt": "train_validation_test",
        "fit-holdout": "fit_holdout",
    }[args.kind]
    if args.apply and kind != "train_validation_test":
        raise DatasetSplitError(
            "--apply is available only for tvt; fit_holdout remains a plan-level "
            "artifact."
        )
    ratios = _parse_split_ratios(args.ratios)
    plan = build_split_plan(
        args.session_root,
        kind=kind,
        ratios=ratios,
        seed=args.seed,
        grouping_key=args.grouping_key,
    )
    if args.out is not None:
        if args.out.resolve() == (args.session_root / "manifest.json").resolve():
            raise DatasetSplitError("--out must not overwrite the dataset manifest.")
        write_split_plan(plan, args.out)
    if args.apply:
        manifest_path = args.session_root / "manifest.json"
        manifest = read_dataset_manifest(manifest_path)
        updated = apply_split_plan(manifest, plan)
        write_json_atomic(manifest_path, manifest_to_dict(updated))
        report = validate_dataset(args.session_root)
        if report.status == "failed":
            raise DatasetSplitError(
                "updated manifest failed dataset validation: "
                + "; ".join(
                    f"{finding.code} at {finding.location}"
                    for finding in report.findings
                )
            )
    print(plan.plan_sha256)
    return 0


def _parse_split_ratios(text: str) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for item in text.split(","):
        if "=" not in item:
            raise DatasetSplitError(
                f"--ratios entry {item!r} must use partition=value syntax."
            )
        name, raw_value = (part.strip() for part in item.split("=", 1))
        if not name or not raw_value:
            raise DatasetSplitError(
                f"--ratios entry {item!r} must use partition=value syntax."
            )
        if name in ratios:
            raise DatasetSplitError(f"--ratios repeats partition {name!r}.")
        try:
            ratios[name] = float(raw_value)
        except ValueError as exc:
            raise DatasetSplitError(
                f"--ratios value for {name!r} must be numeric."
            ) from exc
    return ratios


if __name__ == "__main__":
    raise SystemExit(main())
