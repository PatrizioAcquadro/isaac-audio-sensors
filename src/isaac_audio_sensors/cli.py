"""Command line interface for isaac-audio-sensors."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from isaac_audio_sensors import __version__


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="isaac-audio-sensors")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-config")
    validate.add_argument("config", type=Path)
    validate.set_defaults(handler=_validate_config)

    simulate = commands.add_parser("simulate")
    simulate.add_argument("config", type=Path)
    simulate.add_argument("--backend", default=None)
    simulate.add_argument("--array-id", default=None)
    simulate.add_argument("--timestamp-ms", type=int, default=0)
    simulate.add_argument("--start-time-s", type=float, default=0.0)
    simulate.add_argument("--end-time-s", type=float, default=1.0)
    simulate.add_argument("--max-events", type=int, default=None)
    simulate.add_argument("--out", type=Path, default=None)
    simulate.set_defaults(handler=_simulate)

    schema = commands.add_parser("export-schema")
    schema.add_argument(
        "--schema",
        choices=("frame", "dataset-manifest", "calibration-profile"),
        default="frame",
    )
    schema.add_argument("--out", type=Path, default=None)
    schema.set_defaults(handler=_export_schema)

    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--json", action="store_true")
    capabilities.set_defaults(handler=_capabilities)

    dataset = commands.add_parser("dataset")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)

    dataset_validate = dataset_commands.add_parser("validate")
    dataset_validate.add_argument("session_root", type=Path)
    dataset_validate.add_argument("--allow-incomplete", action="store_true")
    dataset_validate.add_argument("--deep-audio", action="store_true")
    dataset_validate.add_argument("--json", dest="json_path", default=None)
    dataset_validate.set_defaults(handler=_dataset_validate)

    dataset_stats = dataset_commands.add_parser("stats")
    dataset_stats.add_argument("session_root", type=Path)
    dataset_stats.add_argument("--allow-incomplete", action="store_true")
    dataset_stats.add_argument("--json", dest="json_path", default=None)
    dataset_stats.set_defaults(handler=_dataset_stats)

    dataset_split = dataset_commands.add_parser("split")
    dataset_split.add_argument("session_root", type=Path)
    dataset_split.add_argument(
        "--kind", choices=("tvt", "fit-holdout"), required=True
    )
    dataset_split.add_argument("--ratios", required=True)
    dataset_split.add_argument("--seed", type=int, required=True)
    dataset_split.add_argument("--grouping-key", default=None)
    dataset_split.add_argument("--out", type=Path, default=None)
    dataset_split.add_argument("--apply", action="store_true")
    dataset_split.set_defaults(handler=_dataset_split)

    guided = commands.add_parser("guided")
    guided_commands = guided.add_subparsers(dest="guided_command", required=True)
    guided_run = guided_commands.add_parser("run-headless")
    guided_run.add_argument("config", type=Path)
    guided_run.add_argument("--session-dir", type=Path, required=True)
    guided_run.add_argument("--export-dir", type=Path, required=True)
    duration = guided_run.add_mutually_exclusive_group()
    duration.add_argument("--frames", type=int, default=None)
    duration.add_argument("--seconds", type=float, default=None)
    guided_run.add_argument("--json", dest="json_path", default=None)
    guided_run.set_defaults(handler=_guided_run_headless)
    return parser


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
            timestamp_ms=args.timestamp_ms,
            start_time_s=args.start_time_s,
            end_time_s=args.end_time_s,
            max_events=args.max_events,
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


def _dataset_validate(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.recording import DatasetLayoutError, validate_dataset

    try:
        report = validate_dataset(
            args.session_root,
            allow_incomplete=args.allow_incomplete,
            deep_audio=args.deep_audio,
        )
        payload = report.to_dict()
        if args.json_path == "-":
            _print_json(payload)
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
    except (DatasetLayoutError, OSError, ValueError) as exc:
        return _fail("dataset validation", exc)
    return 1 if report.status == "failed" else 0


def _dataset_stats(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.recording import DatasetLayoutError, validate_dataset

    try:
        report = validate_dataset(
            args.session_root,
            allow_incomplete=args.allow_incomplete,
        )
        payload = report.statistics.to_dict()
        if args.json_path in {None, "-"}:
            _print_json(payload)
        else:
            print(
                "dataset statistics: "
                f"episodes={report.statistics.episode_count} "
                f"shards={report.statistics.shard_count} "
                f"frames={report.statistics.frame_count}"
            )
            _write_json_output(Path(args.json_path), payload)
    except (DatasetLayoutError, OSError, ValueError) as exc:
        return _fail("dataset statistics", exc)
    return 1 if report.status == "failed" else 0


def _dataset_split(args: argparse.Namespace) -> int:
    from isaac_audio_sensors.recording import (
        DatasetLayoutError,
        DatasetSplitError,
        apply_split_plan,
        build_split_plan,
        read_dataset_manifest,
        write_dataset_manifest,
        write_split_plan,
    )

    try:
        kind = {"tvt": "train_validation_test", "fit-holdout": "fit_holdout"}[
            args.kind
        ]
        plan = build_split_plan(
            args.session_root,
            kind=kind,
            ratios=_parse_split_ratios(args.ratios),
            seed=args.seed,
            grouping_key=args.grouping_key,
        )
        manifest_path = args.session_root / "manifest.json"
        if args.out is not None and args.out.resolve() == manifest_path.resolve():
            raise DatasetSplitError("--out must not overwrite the dataset manifest.")
        updated = None
        if args.apply:
            updated = apply_split_plan(read_dataset_manifest(manifest_path), plan)
        if args.out is not None:
            write_split_plan(plan, args.out)
        if updated is not None:
            write_dataset_manifest(updated, manifest_path)
    except (DatasetLayoutError, DatasetSplitError, OSError, ValueError) as exc:
        return _fail("dataset split", exc)
    print(plan.plan_sha256)
    return 0


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


def _parse_split_ratios(text: str) -> dict[str, float]:
    from isaac_audio_sensors.recording import DatasetSplitError

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


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _write_json_output(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _fail(label: str, exc: BaseException) -> int:
    print(f"{label} failed: {exc}", file=sys.stderr)
    return 1
