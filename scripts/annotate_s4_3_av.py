#!/usr/bin/env python3
"""Finalize the preregistered S4.3 coarse audio-video impact association."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import (
    calculate_alignment,
    read_jsonl,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_3 import S43Error, load_json
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact(path: Path, root: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def annotate(args: argparse.Namespace) -> dict[str, Any]:
    attempt_root = args.attempt_root.resolve()
    expected_root = (ROOT / "dataset/S4.3/attempts").resolve()
    try:
        attempt_root.relative_to(expected_root)
    except ValueError as exc:
        raise S43Error("attempt must be below dataset/S4.3/attempts") from exc
    lifecycle_path = attempt_root / "lifecycle.json"
    lifecycle = load_json(lifecycle_path)
    if lifecycle.get("state") != "finalizing":
        raise S43Error(f"attempt must be finalizing, got {lifecycle.get('state')!r}")
    manifest = load_json(attempt_root / "manifest.json")
    if (
        manifest.get("trial_id") != "s4_3_rob_impact_av_01"
        or manifest.get("lifecycle_status") != "awaiting_av_annotation"
    ):
        raise S43Error("attempt is not the preregistered pending impact-AV trial")
    for destination in (
        attempt_root / "event_observation_confirmation.json",
        attempt_root / "coarse_audio_video_association.json",
        attempt_root / "final_manifest.json",
        attempt_root / "SHA256SUMS.final",
    ):
        if destination.exists():
            raise S43Error(f"immutable annotation output already exists: {destination}")
    confirmations = {
        "event_unique": args.event_unique,
        "event_visible": args.event_visible,
        "event_audible": args.event_audible,
        "privacy_clean": args.privacy_clean,
        "no_person_or_hand_in_reviewed_frames": args.no_person_or_hand,
        "no_screen_private_label_or_identifier": args.no_private_content,
        "operator_confirmed": args.operator_confirmed,
    }
    if not all(confirmations.values()):
        raise S43Error("every event and privacy confirmation is required")
    frames, issues = read_jsonl(attempt_root / "raw/zed_frames.jsonl")
    if issues:
        raise S43Error(
            f"invalid retained ZED JSONL: {[item.to_dict() for item in issues]}"
        )
    if not 0 <= args.zed_frame_index < len(frames):
        raise S43Error("ZED event frame is outside retained records")
    audio_properties = load_json(attempt_root / "analysis.json")["wav"]
    if not 0 <= args.audio_sample_index < int(audio_properties["decoded_frame_count"]):
        raise S43Error("audio event sample is outside retained WAV")
    timestamps = [int(frame["device_timestamp_ns"]) for frame in frames]
    intervals = [
        later - earlier
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        if later > earlier
    ]
    if not intervals:
        raise S43Error("cannot determine ZED frame interval")
    result = calculate_alignment(
        audio_event_sample_index=args.audio_sample_index,
        audio_sample_rate_hz=16_000,
        zed_first_timestamp_ns=timestamps[0],
        zed_event_timestamp_ns=timestamps[args.zed_frame_index],
        audio_localization_half_width_samples=args.audio_half_width_samples,
        zed_frame_interval_ns=round(median(intervals)),
        zed_localization_half_width_frames=args.zed_half_width_frames,
        extra_uncertainty_ms=args.extra_uncertainty_ms,
        event_unique=True,
        event_visible=True,
        event_audible=True,
        maximum_uncertainty_ms=50.0,
    )
    if result["status"] != "passed":
        raise S43Error(f"coarse association failed: {result}")
    confirmation = {
        "schema": "ias.s4_3.event_observation_confirmation.v1",
        **confirmations,
        "review_basis": args.review_basis,
        "reviewed_frame_indices": args.reviewed_frame_indices,
        "retention": "machine_local_gitignored",
    }
    write_json_atomic(
        attempt_root / "event_observation_confirmation.json", confirmation
    )
    result.update(
        {
            "schema": "ias.s4_3.coarse_audio_video_association.v1",
            "audio_event_sample_index": args.audio_sample_index,
            "zed_event_frame_index": args.zed_frame_index,
            "audio_localization_half_width_samples": args.audio_half_width_samples,
            "zed_localization_half_width_frames": args.zed_half_width_frames,
            "extra_uncertainty_ms": args.extra_uncertainty_ms,
            "classification": "Measured",
            "claim": (
                "coarse practical association; not synchronization or absolute latency"
            ),
        }
    )
    write_json_atomic(attempt_root / "coarse_audio_video_association.json", result)
    artifacts = [
        *manifest["artifacts"],
        _artifact(
            attempt_root / "manifest.json", attempt_root, "pre_annotation_manifest"
        ),
        _artifact(
            attempt_root / "event_observation_confirmation.json",
            attempt_root,
            "event_observation_confirmation",
        ),
        _artifact(
            attempt_root / "coarse_audio_video_association.json",
            attempt_root,
            "coarse_audio_video_association",
        ),
        _artifact(attempt_root / "zed_svo_replay.json", attempt_root, "zed_svo_replay"),
    ]
    final_manifest = {
        **manifest,
        "schema": "ias.s4_3.final_attempt_manifest.v1",
        "lifecycle_status": "accepted",
        "coarse_audio_video_association_status": "passed",
        "scientific_disposition": "pending_aggregate_and_closeout",
        "artifacts": artifacts,
    }
    write_json_atomic(attempt_root / "final_manifest.json", final_manifest)
    artifacts.append(
        _artifact(
            attempt_root / "final_manifest.json", attempt_root, "final_attempt_manifest"
        )
    )
    checksum_payload = "".join(
        f"{record['sha256']}  {record['path']}\n"
        for record in sorted(artifacts, key=lambda item: item["path"])
    )
    (attempt_root / "SHA256SUMS.final").write_text(
        checksum_payload,
        encoding="utf-8",
    )
    lifecycle["state"] = "accepted"
    lifecycle["events"].append(
        {
            "state": "accepted",
            "reason": (
                "quality, analysis, privacy review, SVO replay, and coarse "
                "AV association passed"
            ),
            "wall_time_utc": _utc(),
            "monotonic_ns": None,
        }
    )
    write_json_atomic(lifecycle_path, lifecycle)
    return {
        "status": "accepted",
        "attempt_id": manifest["attempt_id"],
        "trial_id": manifest["trial_id"],
        "association": result,
        "artifact_count": len(artifacts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt_root", type=Path)
    parser.add_argument("--audio-sample-index", type=int, required=True)
    parser.add_argument("--zed-frame-index", type=int, required=True)
    parser.add_argument("--audio-half-width-samples", type=int, required=True)
    parser.add_argument("--zed-half-width-frames", type=float, required=True)
    parser.add_argument("--extra-uncertainty-ms", type=float, default=0.0)
    parser.add_argument("--event-unique", action="store_true")
    parser.add_argument("--event-visible", action="store_true")
    parser.add_argument("--event-audible", action="store_true")
    parser.add_argument("--privacy-clean", action="store_true")
    parser.add_argument("--no-person-or-hand", action="store_true")
    parser.add_argument("--no-private-content", action="store_true")
    parser.add_argument("--operator-confirmed", action="store_true")
    parser.add_argument("--review-basis", required=True)
    parser.add_argument("--reviewed-frame-indices", type=int, nargs="+", required=True)
    args = parser.parse_args()
    try:
        result = annotate(args)
    except (OSError, S43Error, ValueError) as exc:
        print(f"S4.3 AV annotation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
