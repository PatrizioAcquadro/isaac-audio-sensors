"""Checked loading and replay behavior."""

from __future__ import annotations

import gc
import json
import shutil
import weakref
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.recording import (
    DatasetLayoutError,
    SessionDataset,
    replay_session,
)

REFERENCE = Path("tests/fixtures/recording/session")


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_replay_matches_loader_and_is_read_only(tmp_path):
    root = tmp_path / "session"
    shutil.copytree(REFERENCE, root)
    before = _snapshot(root)
    dataset = SessionDataset.open(root)
    expected = list(dataset.iter_records())

    events = list(replay_session(root, with_audio=True))
    replayed = [event for event in events if event.kind == "frame"]

    assert [event.frame for event in replayed] == expected
    for event, item in zip(replayed, expected, strict=True):
        assert np.array_equal(event.audio, dataset.read_frame_audio(item))
    assert [event.kind for event in events].count("episode_start") == 3
    assert [event.kind for event in events].count("episode_end") == 3
    assert [event.kind for event in events] == [
        kind
        for count in (2, 2, 3)
        for kind in ("episode_start", "reset", *["frame"] * count, "episode_end")
    ]
    assert _snapshot(root) == before


@pytest.mark.parametrize("corruption", ["duplicate_reset", "reset_time", "count"])
def test_replay_preserves_loader_episode_failures(tmp_path, corruption):
    root = tmp_path / corruption
    shutil.copytree(REFERENCE, root)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    episode = manifest["episodes"][-1]
    if corruption == "duplicate_reset":
        episode["reset_markers"] *= 2
    elif corruption == "reset_time":
        episode["reset_markers"][0]["timestamp_ms"] = episode["timestamps_ms"][1]
    else:
        episode["end_frame"] += 1
        episode["timestamps_ms"].append(15)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    with pytest.raises(DatasetLayoutError) as loaded:
        list(SessionDataset.open(root).iter_records())
    with pytest.raises(DatasetLayoutError) as replayed:
        list(replay_session(root))
    assert str(replayed.value) == str(loaded.value)
    assert replayed.value.code == loaded.value.code
    assert replayed.value.location == loaded.value.location


def test_incomplete_replay_requires_opt_in(tmp_path):
    root = tmp_path / "incomplete"
    shutil.copytree(REFERENCE, root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completion_state"] = "incomplete"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(DatasetLayoutError, match="finalized-incomplete"):
        list(replay_session(root))
    assert any(
        event.kind == "frame" for event in replay_session(root, allow_incomplete=True)
    )


def test_checksum_fast_path_keeps_structural_verification(tmp_path):
    root = tmp_path / "trusted"
    shutil.copytree(REFERENCE, root)
    marker_path = root / "shards/shard_00000/shard.complete.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["files"][0]["sha256"] = "0" * 64
    marker_path.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["shards"][0]["assets"][0]["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(DatasetLayoutError) as caught:
        list(replay_session(root))
    assert caught.value.code == "checksum_mismatch"
    assert any(
        event.kind == "frame" for event in replay_session(root, verify_checksums=False)
    )


def test_iteration_does_not_retain_loaded_frames():
    dataset = SessionDataset.open(REFERENCE)
    references: list[weakref.ReferenceType] = []
    for item in dataset.iter_records():
        references.append(weakref.ref(item))
    del item
    gc.collect()
    assert all(reference() is None for reference in references)
