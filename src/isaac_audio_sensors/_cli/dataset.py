"""Dataset CLI command adapters."""

from __future__ import annotations

import argparse
from pathlib import Path

from isaac_audio_sensors._cli.output import _fail, _print_json, _write_json_output


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
        kind = {"tvt": "train_validation_test", "fit-holdout": "fit_holdout"}[args.kind]
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
