#!/usr/bin/env python3
"""Produce review candidates for S4.2 alignment without auto-accepting an event."""

from __future__ import annotations

import argparse
import heapq
import json
import struct
import wave
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import load_json, read_jsonl
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic


def audio_transient_candidates(
    path: Path, *, candidate_count: int = 8, minimum_separation_s: float = 0.20
) -> dict[str, Any]:
    """Return ranked PCM first-difference candidates using bounded memory."""

    heap: list[tuple[int, int, tuple[int, ...]]] = []
    retained_raw = 512
    with wave.open(str(path), "rb") as reader:
        if (
            reader.getnchannels() != 6
            or reader.getframerate() != 16_000
            or reader.getsampwidth() != 2
            or reader.getcomptype() != "NONE"
        ):
            raise ValueError("alignment input must be six-channel 16 kHz PCM16 WAV")
        sample_rate = reader.getframerate()
        previous = [0] * 6
        sample_index = 0
        while True:
            raw = reader.readframes(4096)
            if not raw:
                break
            values = struct.unpack(f"<{len(raw) // 2}h", raw)
            for offset in range(0, len(values), 6):
                frame = values[offset : offset + 6]
                differences = tuple(
                    abs(frame[channel] - previous[channel]) for channel in range(6)
                )
                # Raw microphone channels are authoritative for event presence;
                # processed channels remain in the per-channel diagnostics.
                score = max(differences[2:])
                item = (score, sample_index, differences)
                if len(heap) < retained_raw:
                    heapq.heappush(heap, item)
                elif score > heap[0][0]:
                    heapq.heapreplace(heap, item)
                previous[:] = frame
                sample_index += 1
    separation = round(minimum_separation_s * sample_rate)
    selected: list[tuple[int, int, tuple[int, ...]]] = []
    for candidate in sorted(heap, reverse=True):
        if all(abs(candidate[1] - existing[1]) >= separation for existing in selected):
            selected.append(candidate)
        if len(selected) >= candidate_count:
            break
    return {
        "sample_rate_hz": sample_rate,
        "method": "ranked raw-channel PCM16 first-difference; review only",
        "auto_accept": False,
        "candidates": [
            {
                "rank": rank,
                "sample_index": sample_index,
                "elapsed_s": sample_index / sample_rate,
                "raw_channel_score_pcm16": score,
                "per_channel_first_difference_pcm16": list(differences),
            }
            for rank, (score, sample_index, differences) in enumerate(selected, 1)
        ],
    }


def zed_cue_window(
    records: list[dict[str, Any]], cue_monotonic_ns: int, *, radius_frames: int = 10
) -> dict[str, Any]:
    """Locate a review window using only the workstation monotonic clock."""

    if not records:
        raise ValueError("ZED records are empty")
    nearest = min(
        range(len(records)),
        key=lambda index: abs(
            int(records[index]["host_monotonic_ns"]) - cue_monotonic_ns
        ),
    )
    return {
        "method": "nearest ZED record to workstation operator-cue monotonic time",
        "synchronization_claim": False,
        "nearest_frame_index": nearest,
        "review_start_frame_index": max(0, nearest - radius_frames),
        "review_end_frame_index": min(len(records) - 1, nearest + radius_frames),
        "cue_to_nearest_host_observation_ms": (
            int(records[nearest]["host_monotonic_ns"]) - cue_monotonic_ns
        )
        / 1e6,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt_root", type=Path)
    args = parser.parse_args()
    audio = args.attempt_root / "raw/respeaker_audio.wav"
    records, issues = read_jsonl(args.attempt_root / "raw/zed_frames.jsonl")
    if issues:
        print(json.dumps({"status": "failed", "issues": [i.to_dict() for i in issues]}))
        return 1
    cue = load_json(args.attempt_root / "operator_cue.json")
    report = {
        "schema": "ias.s4_2.alignment_candidates.v1",
        "status": "review_required",
        "audio": audio_transient_candidates(audio),
        "zed": zed_cue_window(records, int(cue["host_monotonic_ns"])),
        "instructions": (
            "Inspect candidate audio transients and the ZED SVO review window. "
            "A human must confirm one unique audible and visible impact before "
            "annotation."
        ),
    }
    write_json_atomic(args.attempt_root / "alignment_candidates.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
