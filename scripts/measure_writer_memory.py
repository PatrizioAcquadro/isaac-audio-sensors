#!/usr/bin/env python3
"""Measure frozen S2.2 writer RSS and file-descriptor bounds."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.dataset import (
    SessionRecorder,
    ShardPromotion,
    validate_session_layout,
)
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION_ROOT = REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.2/memory_sessions"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.2/memory_telemetry.json"
)

SAMPLE_RATE_HZ = 48_000
CHANNEL_ORDER = ("front", "right", "back", "left")
WINDOW_SAMPLE_COUNT = 1_024
HOP_SAMPLE_COUNT = 512
RSS_LIMIT_BYTES = 128 * 1024 * 1024
RSS_GROWTH_LIMIT_BYTES = 32 * 1024 * 1024
FD_LIMIT = 16


@dataclass(frozen=True, slots=True)
class Workload:
    name: str
    aligned: bool
    shard_max_frames: int
    duration_seconds: int
    episode_count: int
    expected_published_shards: int | None


WORKLOADS = {
    "W1a": Workload("W1a", False, 28_125, 11 * 60, 1, 2),
    "W1b": Workload("W1b", False, 28_125, 16 * 60, 1, 3),
    "W2": Workload("W2", True, 5_625, 6 * 30, 6, None),
}


def _read_rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS is absent from /proc/self/status")


def _read_fd_count() -> int:
    return sum(1 for _ in Path("/proc/self/fd").iterdir())


class _Monitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._origin = time.monotonic()
        self.samples: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None

    def sample(self, reason: str) -> dict[str, Any]:
        row = {
            "elapsed_s": time.monotonic() - self._origin,
            "rss_bytes": _read_rss_bytes(),
            "fd_count": _read_fd_count(),
            "reason": reason,
        }
        with self._lock:
            self.samples.append(row)
        return row

    def baseline(self) -> tuple[float, float]:
        rows = [self.sample("baseline") for _ in range(3)]
        return (
            sum(row["rss_bytes"] for row in rows) / 3.0,
            sum(row["fd_count"] for row in rows) / 3.0,
        )

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="writer-memory", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            self.sample("periodic")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.sample("sampling_end")


def _provenance() -> dict[str, Any]:
    return {
        "creation": CreationProvenance(
            tool_name="measure_writer_memory",
            tool_version="1.0",
            backend_id="tdoa_synthetic",
            estimator_id="deterministic_memory_harness",
        ),
        "device": DeviceProvenance(
            device_id="synthetic_memory_host",
            device_type="synthetic",
            platform="linux_procfs",
            compute_device="cpu",
        ),
        "license": "CC0-1.0",
        "source": "Frozen S2.2 deterministic synthetic writer workload",
        "coordinate_frames": ("world", "synthetic_array"),
        "time_base": "simulation_time",
        "creation_timestamp_ms": 1_767_225_600_000,
    }


def _configuration(workload: Workload) -> dict[str, Any]:
    return {
        "backend_id": "tdoa_synthetic",
        "channel_order": list(CHANNEL_ORDER),
        "dataset_id": f"s2_2_memory_{workload.name.lower()}",
        "dtype": "float32",
        "hop_sample_count": HOP_SAMPLE_COUNT,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "session_seed": 2_026_072,
        "shard_episode_aligned": workload.aligned,
        "shard_max_frames": workload.shard_max_frames,
        "split_grouping_key": "scene_id",
        "window_sample_count": WINDOW_SAMPLE_COUNT,
    }


def _frame_template() -> dict[str, Any]:
    detections = tuple(
        AudioDetection(
            detection_id=f"detection_{index}",
            source_id=f"source_{index}",
            class_label="synthetic_tone",
            detection_mode="scheduled_known_source",
            timestamp_ms=0,
            ground_truth_bearing_deg=float(index * 90),
            source_distance_m=2.0 + index,
            doa=DoaEstimate(
                estimated_bearing_deg=float(index * 90),
                bearing_confidence=1.0,
            ),
            per_mic_rms={channel: 0.1 + index * 0.01 for channel in CHANNEL_ORDER},
            diagnostics={"workload_payload": True},
        )
        for index in range(2)
    )
    return frame_to_trace_dict(
        AudioSensorFrame(
            frame_id="synthetic_0",
            frame_name="synthetic_0",
            timestamp_ms=0,
            start_time_s=0.0,
            end_time_s=WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ,
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_index=0,
            backend_id="tdoa_synthetic",
            array_id="synthetic_array",
            provenance="synthetic/core",
            detections=detections,
            aggregate_per_mic_rms={channel: 0.1 for channel in CHANNEL_ORDER},
            diagnostics={
                "generator": "s2.2_memory_harness",
                "window_sample_count": WINDOW_SAMPLE_COUNT,
                "hop_sample_count": HOP_SAMPLE_COUNT,
            },
        )
    )


def _synthetic_frame(
    template: dict[str, Any], index: int, timestamp_ms: int | None = None
) -> dict[str, Any]:
    if timestamp_ms is None:
        timestamp_ms = (index * HOP_SAMPLE_COUNT * 1_000) // SAMPLE_RATE_HZ
    payload = dict(template)
    payload.update(
        {
            "frame_id": f"synthetic_{index:09d}",
            "frame_name": f"synthetic_{index:09d}",
            "frame_index": index,
            "timestamp_ms": timestamp_ms,
            "start_time_s": index * HOP_SAMPLE_COUNT / SAMPLE_RATE_HZ,
            "end_time_s": (index * HOP_SAMPLE_COUNT + WINDOW_SAMPLE_COUNT)
            / SAMPLE_RATE_HZ,
        }
    )
    return payload


def _base_audio() -> np.ndarray:
    position = np.arange(WINDOW_SAMPLE_COUNT, dtype=np.float32)
    return np.stack(
        [
            np.sin(position * np.float32(0.007 * (channel + 1))).astype(np.float32)
            for channel in range(len(CHANNEL_ORDER))
        ]
    )


def _frame_count_for_interval(start_s: float, end_s: float, scale: float) -> int:
    start = round(start_s * SAMPLE_RATE_HZ / HOP_SAMPLE_COUNT * scale)
    end = round(end_s * SAMPLE_RATE_HZ / HOP_SAMPLE_COUNT * scale)
    return max(1, end - start)


def measure_workload(
    workload_name: str,
    *,
    session_root: str | Path,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Run one frozen workload (or a duration-scaled smoke variant)."""

    if workload_name not in WORKLOADS:
        raise ValueError(f"unknown workload {workload_name!r}")
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("scale must be a positive finite number")
    workload = WORKLOADS[workload_name]
    root = Path(session_root)
    if root.exists():
        shutil.rmtree(root)
    promotion_rows: list[dict[str, Any]] = []
    monitor = _Monitor()

    def promoted(event: ShardPromotion) -> None:
        sample = monitor.sample("shard_promotion")
        promotion_rows.append(
            {
                "shard_id": event.shard_id,
                "shard_ordinal": event.shard_ordinal,
                "start_frame": event.start_frame,
                "frame_count": event.frame_count,
                "elapsed_s": sample["elapsed_s"],
            }
        )

    recorder = SessionRecorder(
        root,
        _configuration(workload),
        promotion_callback=promoted,
        **_provenance(),
    )
    template = _frame_template()
    base_audio = _base_audio()
    baseline_rss, baseline_fd = monitor.baseline()
    monitor.start()
    global_index = 0

    if workload.name.startswith("W1"):
        recorder.begin_episode("continuous_scene", "environment_0", "continuous_scene")
        count = _frame_count_for_interval(0, workload.duration_seconds, scale)
        for _ in range(count):
            block = base_audio + np.float32((global_index % 31) * 1e-5)
            recorder.append_frame(
                _synthetic_frame(template, global_index),
                block,
                (global_index * HOP_SAMPLE_COUNT * 1_000) // SAMPLE_RATE_HZ,
                is_reset=global_index == 0,
            )
            global_index += 1
        monitor.stop()
        published_at_sampling_end = recorder.promoted_shard_count
        recorder.finalize_incomplete()
        if (
            scale == 1.0
            and published_at_sampling_end != workload.expected_published_shards
        ):
            raise AssertionError(
                f"{workload.name} published {published_at_sampling_end} shards; "
                f"expected {workload.expected_published_shards}"
            )
    else:
        episode_seconds = workload.duration_seconds / workload.episode_count
        for episode_ordinal in range(workload.episode_count):
            group = "group_a" if episode_ordinal % 4 < 2 else "group_b"
            recorder.begin_episode(
                group,
                f"environment_{episode_ordinal}",
                group,
            )
            count = _frame_count_for_interval(
                episode_ordinal * episode_seconds,
                (episode_ordinal + 1) * episode_seconds,
                scale,
            )
            for frame_in_episode in range(count):
                block = base_audio + np.float32((global_index % 31) * 1e-5)
                recorder.append_frame(
                    _synthetic_frame(
                        template,
                        global_index,
                        (frame_in_episode * HOP_SAMPLE_COUNT * 1_000) // SAMPLE_RATE_HZ,
                    ),
                    block,
                    (frame_in_episode * HOP_SAMPLE_COUNT * 1_000) // SAMPLE_RATE_HZ,
                    is_reset=frame_in_episode == 0,
                )
                global_index += 1
            recorder.end_episode()
        recorder.finalize()
        monitor.stop()
        published_at_sampling_end = recorder.promoted_shard_count

    layout = validate_session_layout(root)
    samples = list(monitor.samples)
    peak_rss_delta = max(row["rss_bytes"] for row in samples) - baseline_rss
    peak_fd_delta = max(row["fd_count"] for row in samples) - baseline_fd
    limits_passed = peak_rss_delta <= RSS_LIMIT_BYTES and peak_fd_delta <= FD_LIMIT
    return {
        "workload": workload.name,
        "scale": scale,
        "run_kind": "acceptance" if scale == 1.0 else "smoke",
        "parameters": {
            "channels": len(CHANNEL_ORDER),
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "dtype": "float32",
            "window_sample_count": WINDOW_SAMPLE_COUNT,
            "hop_sample_count": HOP_SAMPLE_COUNT,
            "shard_episode_aligned": workload.aligned,
            "shard_max_frames": workload.shard_max_frames,
            "duration_seconds_unscaled": workload.duration_seconds,
            "episode_count": workload.episode_count,
            "frames_produced": global_index,
        },
        "baseline": {
            "rss_bytes_mean": baseline_rss,
            "fd_count_mean": baseline_fd,
            "sample_count": 3,
        },
        "peak_rss_delta_bytes": peak_rss_delta,
        "peak_fd_delta": peak_fd_delta,
        "samples": samples,
        "shard_promotions": promotion_rows,
        "published_shards_at_sampling_end": published_at_sampling_end,
        "limits": {
            "peak_rss_delta_bytes": RSS_LIMIT_BYTES,
            "peak_fd_delta": FD_LIMIT,
            "w1b_minus_w1a_rss_bytes": RSS_GROWTH_LIMIT_BYTES,
        },
        "limits_passed": limits_passed,
        "validation": {
            "lifecycle_state": layout.lifecycle_state,
            "warning_count": len(layout.warnings),
            "warnings": [
                {"location": item.location, "message": item.message}
                for item in layout.warnings
            ],
            "shard_count": len(layout.shards),
            "passed": (
                layout.lifecycle_state
                == (
                    "finalized-incomplete"
                    if workload.name.startswith("W1")
                    else "complete"
                )
                and not layout.warnings
            ),
        },
        "status": "passed" if limits_passed and not layout.warnings else "failed",
    }


def run_memory_measurements(
    workload: str,
    *,
    output_json: str | Path,
    session_root: str | Path = DEFAULT_SESSION_ROOT,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Run selected workloads and write the telemetry JSON artifact."""

    selected = tuple(WORKLOADS) if workload == "all" else (workload,)
    runs = {
        name: measure_workload(
            name,
            session_root=Path(session_root) / name,
            scale=scale,
        )
        for name in selected
    }
    growth: float | None = None
    growth_passed: bool | None = None
    if "W1a" in runs and "W1b" in runs:
        growth = (
            runs["W1b"]["peak_rss_delta_bytes"] - runs["W1a"]["peak_rss_delta_bytes"]
        )
        growth_passed = growth <= RSS_GROWTH_LIMIT_BYTES
    passed = all(item["status"] == "passed" for item in runs.values()) and (
        growth_passed is not False
    )
    result = {
        "schema_version": "ias.writer_memory_telemetry.v1",
        "scale": scale,
        "run_kind": "acceptance" if scale == 1.0 else "smoke",
        "sampling_rule": {
            "source": "/proc/self/status VmRSS and /proc/self/fd",
            "period_seconds": 0.5,
            "forced_after_each_shard_promotion": True,
            "baseline_sample_count": 3,
        },
        "frozen_limits": {
            "peak_rss_delta_bytes": RSS_LIMIT_BYTES,
            "peak_fd_delta": FD_LIMIT,
            "w1b_minus_w1a_rss_bytes": RSS_GROWTH_LIMIT_BYTES,
        },
        "runs": runs,
        "w1b_minus_w1a_rss_bytes": growth,
        "growth_limit_passed": growth_passed,
        "status": "passed" if passed else "failed",
        "status_is_acceptance_evidence": scale == 1.0,
    }
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", choices=(*WORKLOADS, "all"), default="all")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--session-root", type=Path, default=DEFAULT_SESSION_ROOT)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    result = run_memory_measurements(
        args.workload,
        output_json=args.output_json,
        session_root=args.session_root,
        scale=args.scale,
    )
    print(
        json.dumps(
            {
                "run_kind": result["run_kind"],
                "status": result["status"],
                "workloads": {
                    key: {
                        "peak_rss_delta_bytes": value["peak_rss_delta_bytes"],
                        "peak_fd_delta": value["peak_fd_delta"],
                        "published_shards": value["published_shards_at_sampling_end"],
                        "validation": value["validation"]["lifecycle_state"],
                    }
                    for key, value in result["runs"].items()
                },
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
