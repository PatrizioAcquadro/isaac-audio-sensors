"""Command line interface for isaac-audio-sensors."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from isaac_audio_sensors import __version__
from isaac_audio_sensors._cli.commands import (
    _capabilities,
    _export_schema,
    _simulate,
    _validate_config,
)
from isaac_audio_sensors._cli.dataset import (
    _dataset_split,
    _dataset_stats,
    _dataset_validate,
)
from isaac_audio_sensors._cli.guided import _guided_run_headless


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
    simulate.add_argument("--start-time-s", type=float, default=0.0)
    simulate.add_argument("--end-time-s", type=float, default=1.0)
    simulate.add_argument("--max-detections", type=int, default=None)
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
    dataset_split.add_argument("--kind", choices=("tvt", "fit-holdout"), required=True)
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
