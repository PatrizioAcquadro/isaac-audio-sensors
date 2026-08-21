"""Generate the deterministic recording fixture through the public API."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    SessionRecorder,
    validate_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "tests/fixtures/recording/session"
DATASET_ID = "reference_session_v1"
SESSION_SEED = 2_026_021
SAMPLE_RATE_HZ = 48_000
CHANNEL_ORDER = ("front", "right", "back", "left")
WINDOW_SAMPLE_COUNT = 400
HOP_SAMPLE_COUNT = 240


def _configuration() -> dict[str, object]:
    return {
        "backend_id": "tdoa_synthetic",
        "channel_order": list(CHANNEL_ORDER),
        "dataset_id": DATASET_ID,
        "dtype": "float32",
        "episode_seed_policy": "derived",
        "hop_sample_count": HOP_SAMPLE_COUNT,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "session_seed": SESSION_SEED,
        "shard_episode_aligned": True,
        "shard_max_frames": 4,
        "split_grouping_key": "scene_id",
        "window_sample_count": WINDOW_SAMPLE_COUNT,
    }


def _frame(episode: int, index: int, timestamp_ms: int) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"producer_frame_{index}",
        frame_name=f"reference_episode_{episode}_frame_{index}",
        timestamp_ms=timestamp_ms,
        start_time_s=timestamp_ms / 1_000.0,
        end_time_s=timestamp_ms / 1_000.0 + WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=index,
        backend_id="tdoa_synthetic",
        array_id="xvf3800_reference",
        provenance="synthetic/core",
        aggregate_per_mic_rms={channel: 0.125 for channel in CHANNEL_ORDER},
        diagnostics={
            "fixture": "deterministic recording reference",
            "synthetic_phase": episode * 10 + index,
        },
    )


def _audio(episode: int, index: int) -> np.ndarray:
    positions = np.arange(WINDOW_SAMPLE_COUNT, dtype=np.float32)
    return np.stack(
        [
            ((positions * (channel + 3) + episode * 17 + index * 11) % 193 - 96)
            / np.float32(512.0)
            for channel in range(len(CHANNEL_ORDER))
        ]
    ).astype(np.float32)


def regenerate_reference_dataset(output_dir: str | Path = REFERENCE_DIR) -> Path:
    """Create and validate the canonical reference session."""

    root = Path(output_dir)
    if root.exists():
        shutil.rmtree(root)
    recorder = SessionRecorder(
        root,
        _configuration(),
        creation=CreationProvenance(
            tool_name="ias_fixture_generator",
            tool_version=__version__,
            backend_id="tdoa_synthetic",
            estimator_id="deterministic_reference",
        ),
        device=DeviceProvenance(
            device_id="synthetic_reference_host",
            device_type="synthetic",
            platform="platform_independent",
            compute_device="cpu",
        ),
        license="CC0-1.0",
        source="Deterministic synthetic recording fixture",
        coordinate_frames=("world", "xvf3800_reference"),
        time_base="simulation_time",
        creation_timestamp_ms=1_767_225_600_000,
    )
    specs = (("scene_a", 2), ("scene_a", 2), ("scene_b", 3))
    for episode, (scene_id, frame_count) in enumerate(specs):
        recorder.begin_episode(scene_id, f"environment_{scene_id}", scene_id)
        for index in range(frame_count):
            result = recorder.append_frame(
                _frame(episode, index, index * 5),
                _audio(episode, index),
                is_reset=index == 0,
            )
            if not result.accepted:
                raise AssertionError(result.reason)
        recorder.end_episode()
    recorder.finalize()
    report = validate_dataset(root)
    if report.status != "passed":
        raise AssertionError(report.findings)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REFERENCE_DIR)
    output = regenerate_reference_dataset(parser.parse_args(argv).output_dir)
    try:
        label = output.relative_to(REPO_ROOT)
    except ValueError:
        label = output
    print(f"wrote {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
