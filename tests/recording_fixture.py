"""Generate the deterministic recording fixture."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_UNITS,
)
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording.layout import (
    build_dataset_frame_record,
    build_shard_completion,
    canonical_configuration_bytes,
    configuration_sha256,
    episode_id,
    episode_seed,
    plan_shards,
    serialize_dataset_frame_record,
    serialize_shard_completion,
    shard_id,
    validate_session_layout,
)
from isaac_audio_sensors.recording.manifest import (
    AssetRecord,
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ResetMarker,
    ShardRecord,
    SplitRecord,
)
from isaac_audio_sensors.recording.serialization import (
    read_dataset_manifest,
    write_dataset_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "tests" / "fixtures" / "recording" / "session"
DATASET_ID = "reference_session_v1"
SESSION_SEED = 2_026_021
SAMPLE_RATE_HZ = 48_000
CHANNEL_ORDER = ("front", "right", "back", "left")
WINDOW_SAMPLE_COUNT = 400
HOP_SAMPLE_COUNT = 240
WRITER_TOOL_VERSION = f"ias_fixture_generator/{__version__}"


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


def _frame(
    episode_ordinal: int,
    frame_ordinal: int,
    timestamp_ms: int,
) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"producer_frame_{frame_ordinal}",
        frame_name=f"reference_episode_{episode_ordinal}_frame_{frame_ordinal}",
        timestamp_ms=timestamp_ms,
        start_time_s=timestamp_ms / 1_000.0,
        end_time_s=(timestamp_ms / 1_000.0) + 0.008333333333333333,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=frame_ordinal,
        backend_id="tdoa_synthetic",
        array_id="xvf3800_reference",
        provenance="synthetic/core",
        detections=(),
        aggregate_per_mic_rms={channel: 0.125 for channel in CHANNEL_ORDER},
        waveform_paths=(),
        diagnostics={
            "fixture": "deterministic recording reference",
            "synthetic_phase": episode_ordinal * 10 + frame_ordinal,
        },
    )


def _episode(
    ordinal: int,
    *,
    scene_id: str,
    start_frame: int,
    timestamps_ms: tuple[int, ...],
) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=episode_id(ordinal),
        scene_id=scene_id,
        environment_id=f"environment_{scene_id}",
        seed=episode_seed(DATASET_ID, SESSION_SEED, ordinal),
        start_step=0,
        end_step=len(timestamps_ms) - 1,
        start_frame=start_frame,
        end_frame=start_frame + len(timestamps_ms) - 1,
        timestamps_ms=timestamps_ms,
        split_group=scene_id,
        reset_markers=(
            ResetMarker(
                step_index=0,
                frame_index=start_frame,
                timestamp_ms=timestamps_ms[0],
            ),
        ),
        labels=("synthetic_reference",),
    )


def _audio_samples(sample_count: int, shard_ordinal: int) -> np.ndarray:
    positions = np.arange(sample_count, dtype=np.int64)
    channels = []
    for channel_index in range(len(CHANNEL_ORDER)):
        integers = ((positions * (channel_index + 3) + shard_ordinal * 17) % 193) - 96
        channels.append(integers.astype(np.float32) / np.float32(512.0))
    return np.stack(channels, axis=1)


def _write_float32_wav(
    path: Path,
    samples: np.ndarray,
    *,
    sample_rate_hz: int,
) -> None:
    """Write a minimal deterministic IEEE-float32 RIFF/WAVE asset."""

    data = np.asarray(samples, dtype="<f4", order="C")
    if data.ndim != 2:
        raise ValueError("samples must have shape (frames, channels).")
    channels = data.shape[1]
    block_align = channels * 4
    payload = data.tobytes(order="C")
    fmt = struct.pack(
        "<HHIIHH",
        3,
        channels,
        sample_rate_hz,
        sample_rate_hz * block_align,
        block_align,
        32,
    )
    blob = (
        b"RIFF"
        + struct.pack("<I", 36 + len(payload))
        + b"WAVEfmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(payload))
        + payload
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def regenerate_reference_dataset(output_dir: str | Path = REFERENCE_DIR) -> Path:
    """Write and validate a promise-B reference session at ``output_dir``."""

    root = Path(output_dir)
    config_dir = root / "config"
    shards_dir = root / "shards"
    config_dir.mkdir(parents=True, exist_ok=True)
    shards_dir.mkdir(parents=True, exist_ok=True)

    configuration = _configuration()
    config_bytes = canonical_configuration_bytes(configuration)
    (config_dir / "session_config.json").write_bytes(config_bytes)

    episodes = (
        _episode(0, scene_id="scene_a", start_frame=0, timestamps_ms=(0, 5)),
        _episode(1, scene_id="scene_a", start_frame=2, timestamps_ms=(0, 5)),
        _episode(2, scene_id="scene_b", start_frame=4, timestamps_ms=(0, 5, 10)),
    )
    plan = plan_shards(
        ((0, "scene_a", 2), (1, "scene_a", 2), (2, "scene_b", 3)),
        shard_max_frames=4,
        shard_episode_aligned=True,
    )
    expected_plan = ((0, 4, (episode_id(0), episode_id(1))), (4, 3, (episode_id(2),)))
    actual_plan = tuple(
        (boundary.start_frame, boundary.frame_count, boundary.episode_ids)
        for boundary in plan
    )
    if actual_plan != expected_plan:
        raise AssertionError(f"Unexpected fixture shard plan: {actual_plan!r}")

    shard_specs = (
        {
            "episodes": (0, 1),
            "sample_count": 1_360,
            "ranges": ((0, 400), (240, 640), (640, 1_040), (880, 1_280)),
            "start_frame": 0,
        },
        {
            "episodes": (2,),
            "sample_count": 720,
            "ranges": ((0, 400), (240, 640), (640, 640)),
            "start_frame": 4,
        },
    )
    markers: list[dict[str, object]] = []
    global_frame = 0
    for shard_ordinal, spec in enumerate(shard_specs):
        shard_value = shard_id(shard_ordinal)
        shard_dir = shards_dir / shard_value
        shard_dir.mkdir(parents=True, exist_ok=True)
        records = []
        range_index = 0
        for episode_ordinal in spec["episodes"]:
            episode = episodes[episode_ordinal]
            for frame_ordinal, timestamp_ms in enumerate(episode.timestamps_ms):
                start_sample, end_sample = spec["ranges"][range_index]
                range_index += 1
                records.append(
                    build_dataset_frame_record(
                        dataset_frame_index=global_frame,
                        episode_id_value=episode.episode_id,
                        audio_start_sample=start_sample,
                        audio_end_sample=end_sample,
                        frame=_frame(
                            episode_ordinal,
                            frame_ordinal,
                            timestamp_ms,
                        ),
                        session_root=root,
                        location=f"fixture frame {global_frame}",
                    )
                )
                global_frame += 1
        (shard_dir / "frames.jsonl").write_text(
            "".join(serialize_dataset_frame_record(record) for record in records),
            encoding="utf-8",
        )
        _write_float32_wav(
            shard_dir / "audio.wav",
            _audio_samples(spec["sample_count"], shard_ordinal),
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        marker = build_shard_completion(
            shard_dir,
            shard_id_value=shard_value,
            start_frame=spec["start_frame"],
            episode_ids=tuple(
                episodes[ordinal].episode_id for ordinal in spec["episodes"]
            ),
            writer_tool_version=WRITER_TOOL_VERSION,
            reset_frame_indices=tuple(
                episodes[ordinal].start_frame for ordinal in spec["episodes"]
            ),
            max_overlap_samples=WINDOW_SAMPLE_COUNT - HOP_SAMPLE_COUNT,
        )
        (shard_dir / "shard.complete.json").write_text(
            serialize_shard_completion(marker), encoding="utf-8"
        )
        markers.append(marker)

    shards = tuple(
        ShardRecord(
            shard_id=shard_id(index),
            episode_ids=tuple(marker["episode_ids"]),
            assets=tuple(
                AssetRecord(
                    asset_id=f"{shard_id(index)}."
                    f"{'frames' if entry['path'] == 'frames.jsonl' else 'audio'}",
                    path=f"shards/{shard_id(index)}/{entry['path']}",
                    kind=(
                        "frame_trace_jsonl"
                        if entry["path"] == "frames.jsonl"
                        else "audio_wav"
                    ),
                    sha256=entry["sha256"],
                )
                for entry in marker["files"]
            ),
            completion_state="complete",
        )
        for index, marker in enumerate(markers)
    )
    manifest = AudioDatasetManifest(
        dataset_id=DATASET_ID,
        creation_timestamp_ms=1_767_225_600_000,
        creation=CreationProvenance(
            tool_name="ias_fixture_generator",
            tool_version=__version__,
            isaac_sim_version=None,
            isaac_lab_version=None,
            kit_version=None,
            backend_id="tdoa_synthetic",
            estimator_id="deterministic_reference",
        ),
        license="CC0-1.0",
        source="Deterministic synthetic recording fixture",
        runtime_profile="waveform_fidelity",
        device=DeviceProvenance(
            device_id="synthetic_reference_host",
            device_type="synthetic",
            platform="platform_independent",
            compute_device="cpu",
        ),
        coordinate_convention=COORDINATE_CONVENTION,
        coordinate_frames=("world", "xvf3800_reference"),
        time_base="simulation_time",
        sample_rate_hz=SAMPLE_RATE_HZ,
        channel_order=CHANNEL_ORDER,
        units=dict(DATASET_MANIFEST_UNITS),
        dtype="float32",
        episodes=episodes,
        shards=shards,
        calibration_profile=None,
        configuration_sha256=configuration_sha256(config_bytes),
        split_grouping_key="scene_id",
        splits=(
            SplitRecord(name="train", group_ids=("scene_a",)),
            SplitRecord(name="test", group_ids=("scene_b",)),
        ),
        completion_state="complete",
    )
    write_dataset_manifest(manifest, root / "manifest.json")
    if read_dataset_manifest(root / "manifest.json") != manifest:
        raise AssertionError("Reference manifest failed its own round-trip.")
    result = validate_session_layout(root)
    if result.lifecycle_state != "complete" or result.warnings:
        raise AssertionError("Reference session did not validate cleanly.")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REFERENCE_DIR)
    args = parser.parse_args(argv)
    output = regenerate_reference_dataset(args.output_dir)
    try:
        label = output.relative_to(REPO_ROOT)
    except ValueError:
        label = output
    print(f"wrote {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
