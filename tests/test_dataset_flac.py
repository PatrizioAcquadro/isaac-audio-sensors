"""S2 export-only FLAC transcode and checked replay coverage."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.dataset import (
    DatasetLayoutError,
    SessionDataset,
    export_session_flac,
    replay_session,
    validate_session_layout,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable

REFERENCE_SESSION = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "datasets"
    / "reference_session_v1"
)


@pytest.mark.parametrize(
    ("dtype", "decoded_dtype"),
    (("int16", np.dtype(np.int16)), ("int24", np.dtype(np.int32))),
)
def test_flac_export_is_validator_clean_and_replays_declared_integer_pcm(
    tmp_path,
    dtype,
    decoded_dtype,
):
    soundfile = pytest.importorskip("soundfile")
    exported = export_session_flac(
        REFERENCE_SESSION,
        tmp_path / dtype,
        dataset_id=f"reference_{dtype}",
        dtype=dtype,
        creation_timestamp_ms=1_767_225_600_000,
    )

    layout = validate_session_layout(exported, allow_incomplete=False)
    assert layout.manifest.dataset_id == f"reference_{dtype}"
    assert layout.manifest.dtype == dtype
    assert all(
        asset.kind != "audio_wav"
        for shard in layout.manifest.shards
        for asset in shard.assets
    )
    assert all(
        (exported / "shards" / shard.shard_id / "audio.flac").is_file()
        for shard in layout.manifest.shards
    )

    dataset = SessionDataset.open(exported)
    frames = list(dataset.iter_records())
    replayed = [
        event
        for event in replay_session(exported, with_audio=True)
        if event.kind == "frame"
    ]
    assert len(replayed) == len(frames) > 0
    for item, event in zip(frames, replayed, strict=True):
        assert event.audio is not None
        assert event.audio.dtype == decoded_dtype
        path = exported / "shards" / item.shard_id / "audio.flac"
        expected, _rate = soundfile.read(
            path,
            start=item.audio_start_sample,
            stop=item.audio_end_sample,
            dtype="int16" if dtype == "int16" else "int32",
            always_2d=True,
        )
        np.testing.assert_array_equal(event.audio, expected.T)
    if dtype == "int24":
        assert all(
            event.audio is not None
            and bool(np.all(np.bitwise_and(event.audio, np.int32(0xFF)) == 0))
            for event in replayed
        )


def test_flac_corruption_fails_replay_with_shard_location(tmp_path):
    pytest.importorskip("soundfile")
    exported = export_session_flac(
        REFERENCE_SESSION,
        tmp_path / "corrupt",
        dataset_id="reference_corrupt_flac",
        dtype="int16",
        creation_timestamp_ms=1_767_225_600_000,
    )
    path = exported / "shards/shard_00000/audio.flac"
    payload = bytearray(path.read_bytes())
    payload[len(payload) // 2] ^= 0x80
    path.write_bytes(payload)

    with pytest.raises(
        DatasetLayoutError,
        match=r"shard shard_00000 file audio\.flac: sha256 mismatch",
    ):
        list(replay_session(exported, with_audio=True))


def test_flac_export_missing_soundfile_is_explicit_and_publishes_nothing(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "missing_dependency"
    _hide_soundfile(monkeypatch)

    with pytest.raises(OptionalDependencyUnavailable, match="soundfile"):
        export_session_flac(
            REFERENCE_SESSION,
            destination,
            dataset_id="missing_dependency_flac",
        )
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".missing_dependency.flac-export-*"))


def test_flac_replay_missing_soundfile_is_explicit(monkeypatch, tmp_path):
    pytest.importorskip("soundfile")
    exported = export_session_flac(
        REFERENCE_SESSION,
        tmp_path / "missing_replay_dependency",
        dataset_id="missing_replay_dependency_flac",
    )
    dataset = SessionDataset.open(exported)
    item = next(dataset.iter_records())
    _hide_soundfile(monkeypatch)

    with pytest.raises(OptionalDependencyUnavailable, match="soundfile"):
        dataset.read_frame_audio(item)


@pytest.mark.parametrize("dtype", ("float32", "int32", "bad"))
def test_flac_export_rejects_undocumented_target_dtype(tmp_path, dtype):
    pytest.importorskip("soundfile")
    with pytest.raises(ValueError, match="int16.*int24"):
        export_session_flac(
            REFERENCE_SESSION,
            tmp_path / dtype,
            dataset_id=f"invalid_{dtype}",
            dtype=dtype,
        )


def _hide_soundfile(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def missing(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "soundfile":
            raise ImportError("soundfile intentionally unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "soundfile", raising=False)
    monkeypatch.setattr(builtins, "__import__", missing)
