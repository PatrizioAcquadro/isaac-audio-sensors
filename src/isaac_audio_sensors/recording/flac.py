"""Explicit export-only FLAC transcode for finalized dataset sessions."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.recording._atomic import write_json_atomic
from isaac_audio_sensors.recording._records import (
    canonical_configuration_bytes,
    configuration_sha256,
)
from isaac_audio_sensors.recording._shards import build_flac_shard_completion
from isaac_audio_sensors.recording.loader import SessionDataset
from isaac_audio_sensors.recording.manifest import AssetRecord, ShardRecord
from isaac_audio_sensors.recording.serialization import manifest_to_dict

_FLAC_DTYPES = {"int16": "PCM_16", "int24": "PCM_24"}
_TRANSCODE_FRAMES = 65_536


def _import_soundfile() -> Any:
    try:
        import soundfile  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "FLAC dataset export and replay require soundfile from the 'room' extra."
        ) from exc
    return soundfile


def export_session_flac(
    source_root: str | Path,
    destination_root: str | Path,
    *,
    dataset_id: str,
    dtype: str = "int16",
    creation_timestamp_ms: int | None = None,
) -> Path:
    """Atomically transcode a complete float32-WAV session to integer FLAC."""

    soundfile = _import_soundfile()
    source = Path(source_root).expanduser().resolve()
    destination = Path(destination_root).expanduser().resolve()
    if source == destination:
        raise ValueError("FLAC export destination must differ from the source")
    if destination.exists():
        raise FileExistsError(f"FLAC export destination already exists: {destination}")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("dataset_id must be a non-empty string")
    if dtype not in _FLAC_DTYPES:
        raise ValueError("FLAC export dtype must be 'int16' or 'int24'")

    dataset = SessionDataset.open(source)
    for _ in dataset.iter_records():
        pass
    manifest = dataset.manifest
    if manifest.completion_state != "complete":
        raise ValueError("FLAC export requires a complete source session")
    if manifest.dtype != "float32":
        raise ValueError("FLAC export source must declare float32 WAV audio")
    if len(manifest.channel_order) > 8:
        raise ValueError("FLAC export supports at most 8 channels")

    destination.parent.mkdir(parents=True, exist_ok=True)
    container = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.flac-export-",
            dir=destination.parent,
        )
    )
    staged_root = container / destination.name
    try:
        staged_root.mkdir()
        configuration = json.loads(
            (source / "config/session_config.json").read_text(encoding="utf-8")
        )
        configuration["dataset_id"] = dataset_id
        configuration["dtype"] = dtype
        config_bytes = canonical_configuration_bytes(configuration)
        config_path = staged_root / "config/session_config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_bytes(config_bytes)

        if (source / "calibration").is_dir():
            shutil.copytree(source / "calibration", staged_root / "calibration")

        target_shards: list[ShardRecord] = []
        for source_shard in manifest.shards:
            source_dir = source / "shards" / source_shard.shard_id
            source_marker = dataset._verified_markers[source_shard.shard_id]
            if source_marker["audio"] != {
                **source_marker["audio"],
                "path": "audio.wav",
                "container": "wav",
                "subtype": "FLOAT",
                "dtype": "float32",
            }:
                raise ValueError(
                    f"shard {source_shard.shard_id} is not canonical float32 WAV"
                )
            target_dir = staged_root / "shards" / source_shard.shard_id
            target_dir.mkdir(parents=True)
            shutil.copy2(source_dir / "frames.jsonl", target_dir / "frames.jsonl")
            _transcode_wav_to_flac(
                soundfile,
                source_dir / "audio.wav",
                target_dir / "audio.flac",
                subtype=_FLAC_DTYPES[dtype],
            )
            reset_indices = tuple(
                marker.frame_index
                for episode in manifest.episodes
                if episode.episode_id in source_marker["episode_ids"]
                for marker in episode.reset_markers
            )
            dropped = source_marker["dropped_frames"]
            target_marker = build_flac_shard_completion(
                target_dir,
                shard_id_value=source_shard.shard_id,
                start_frame=int(source_marker["start_frame"]),
                episode_ids=tuple(source_marker["episode_ids"]),
                writer_tool_version=f"{__version__} flac-export",
                dropped_frame_count=int(dropped["count"]),
                dropped_producer_frame_ids=tuple(dropped["producer_frame_ids"]),
                reset_frame_indices=reset_indices,
            )
            write_json_atomic(target_dir / "shard.complete.json", target_marker)
            files = {item["path"]: item for item in target_marker["files"]}
            target_shards.append(
                ShardRecord(
                    shard_id=source_shard.shard_id,
                    episode_ids=source_shard.episode_ids,
                    assets=(
                        AssetRecord(
                            asset_id=f"{source_shard.shard_id}.frames",
                            path=(f"shards/{source_shard.shard_id}/frames.jsonl"),
                            kind="frame_trace_jsonl",
                            sha256=str(files["frames.jsonl"]["sha256"]),
                        ),
                        AssetRecord(
                            asset_id=f"{source_shard.shard_id}.audio",
                            path=f"shards/{source_shard.shard_id}/audio.flac",
                            kind="audio_flac",
                            sha256=str(files["audio.flac"]["sha256"]),
                        ),
                    ),
                    completion_state="complete",
                )
            )

        exported = replace(
            manifest,
            dataset_id=dataset_id,
            creation_timestamp_ms=(
                int(time.time() * 1000)
                if creation_timestamp_ms is None
                else int(creation_timestamp_ms)
            ),
            creation=replace(
                manifest.creation,
                tool_name="isaac_audio_sensors_flac_export",
                tool_version=__version__,
            ),
            source=f"FLAC export of {manifest.dataset_id}",
            dtype=dtype,
            shards=tuple(target_shards),
            configuration_sha256=configuration_sha256(config_bytes),
        )
        write_json_atomic(staged_root / "manifest.json", manifest_to_dict(exported))
        exported_dataset = SessionDataset.open(staged_root)
        for _ in exported_dataset.iter_records():
            pass
        os.replace(staged_root, destination)
        return destination
    finally:
        shutil.rmtree(container, ignore_errors=True)


def _transcode_wav_to_flac(
    soundfile: Any,
    source: Path,
    destination: Path,
    *,
    subtype: str,
) -> None:
    try:
        with soundfile.SoundFile(source, mode="r") as reader:
            if reader.format != "WAV" or reader.subtype != "FLOAT":
                raise ValueError(f"source {source} must be FLOAT WAV")
            with soundfile.SoundFile(
                destination,
                mode="w",
                samplerate=reader.samplerate,
                channels=reader.channels,
                format="FLAC",
                subtype=subtype,
            ) as writer:
                while True:
                    block = reader.read(
                        _TRANSCODE_FRAMES,
                        dtype="float32",
                        always_2d=True,
                    )
                    if block.shape[0] == 0:
                        break
                    writer.write(block)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"FLAC transcode failed for {source}: {exc}") from exc


__all__ = ["export_session_flac"]
