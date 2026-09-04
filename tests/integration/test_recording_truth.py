"""Truth stays atomic and separate across the maintained dataset lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core import AudioObservation, AudioTimeWindow
from isaac_audio_sensors.recording import (
    AnnotationRecord,
    DatasetLayoutError,
    FrameTruth,
    SessionDataset,
    SessionRecorder,
    TruthEvent,
    export_session_flac,
    replay_session,
    validate_dataset,
)
from isaac_audio_sensors.recording._records import (
    build_dataset_frame_record,
    parse_dataset_frame_record,
    serialize_dataset_frame_record,
)
from isaac_audio_sensors.recording.serialization import manifest_from_dict
from tests.helpers import signal_block_for_frame
from tests.integration.test_recording_writer import (
    _audio,
    _configuration,
    _frame,
    _kwargs,
)


def supervision(frame, index):
    # Exercise unavailable, known-empty, and populated truth in the same session.
    annotation = AnnotationRecord(
        annotation_id=f"a{index}",
        label="reviewed",
        provenance="manual_annotation:reviewer",
    )
    if index % 3 == 0:
        return None, (annotation,)
    events = (
        ()
        if index % 3 == 1
        else (
            TruthEvent(
                source_id="authored",
                class_label="Speech",
                position_world_m=(1, 0, 0),
                orientation_world_xyzw=(0.1, 0.2, 0.3, 0.4),
                bearing_deg=0,
                elevation_deg=0,
                distance_m=1,
                prim_path="/World/Source",
                audio_asset_path="generated://tone",
                schedule_overlap=True,
                emission_rms=0.2,
                received_rms={mic: 0.1 for mic in frame.channel_validity},
            ),
        )
    )
    truth = FrameTruth(
        frame_id=frame.frame_id,
        array_id=frame.array_id,
        time_window=AudioTimeWindow(
            start_time_s=frame.start_time_s,
            end_time_s=frame.end_time_s,
            frame_index=frame.frame_index,
        ),
        sample_rate_hz=frame.sample_rate_hz,
        truth_events=events,
        mixture_residual_rms={mic: 0.01 for mic in frame.channel_validity},
    )
    if events:
        annotation = replace(annotation, source_id="authored")
    return truth, (annotation,)


def append(recorder, index, *, local_index=None, with_audio=True, is_reset=False):
    frame = _frame(index, index if local_index is None else local_index)
    truth, annotations = supervision(frame, index)
    block = signal_block_for_frame(frame, _audio(index)) if with_audio else None
    result = recorder.append_frame(
        frame, block, truth=truth, annotations=annotations, is_reset=is_reset
    )
    assert result.accepted, result.reason
    return truth, annotations


@pytest.mark.parametrize("aligned", [False, True])
@pytest.mark.parametrize("with_audio", [False, True])
def test_supervision_round_trip_across_shards_episodes_and_resets(
    tmp_path, aligned, with_audio
):
    root = tmp_path / "session"
    recorder = SessionRecorder(root, _configuration(aligned=aligned), **_kwargs())
    expected = []
    for episode, count in enumerate((2, 5)):
        recorder.begin_episode("scene", f"env{episode}", "scene")
        for local_index in range(count):
            expected.append(
                append(
                    recorder,
                    len(expected),
                    local_index=local_index,
                    with_audio=with_audio,
                    is_reset=local_index == 0,
                )
            )
        recorder.end_episode()
    manifest = recorder.finalize()
    assert manifest.schema_version == "ias.audio_dataset_manifest.v2"
    dataset = SessionDataset.open(root)
    loaded = list(dataset.iter_records())
    assert [(item.truth, item.annotations) for item in loaded] == expected
    assert all(item.frame.observations == () for item in loaded)
    assert len(manifest.shards) >= 2
    assert validate_dataset(root).status == "passed"
    replay = list(replay_session(root, with_audio=with_audio))
    assert sum(event.kind == "reset" for event in replay) == 2
    assert [
        (event.frame.truth, event.frame.annotations)
        for event in replay
        if event.kind == "frame"
    ] == expected
    for path in root.glob("shards/*/frames.jsonl"):
        for line in path.read_text().splitlines():
            payload = json.loads(line)
            assert payload["record_version"] == "ias.dataset_frame_record.v2"
            assert "truth" not in payload["frame"]
            assert "annotations" not in payload["frame"]
    assert all(
        "source_truth" not in episode
        for episode in json.loads((root / "manifest.json").read_text())["episodes"]
    )


@pytest.mark.parametrize(
    "mismatch", ["frame_id", "array_id", "window", "rate", "microphones", "annotation"]
)
def test_invalid_supervision_is_rejected_before_frame_state_advances(
    tmp_path, mismatch
):
    root = tmp_path / "invalid"
    recorder = SessionRecorder(root, _configuration(aligned=False), **_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    frame = _frame(1, 1)
    truth, annotations = supervision(frame, 1)
    if mismatch in {"frame_id", "array_id"}:
        truth = replace(truth, **{mismatch: "wrong"})
    elif mismatch == "window":
        truth = replace(truth, time_window=replace(truth.time_window, frame_index=100))
    elif mismatch == "rate":
        truth = replace(truth, sample_rate_hz=24000)
    elif mismatch == "microphones":
        truth = replace(truth, mixture_residual_rms={"other": 0.1})
    else:
        annotations = annotations * 2
    result = recorder.append_frame(
        frame,
        signal_block_for_frame(frame, _audio(1)),
        truth=truth,
        annotations=annotations,
    )
    assert not result.accepted
    assert recorder.next_dataset_frame_index == 0
    append(recorder, 1)
    recorder.end_episode()
    recorder.finalize()
    assert (
        json.loads(next(root.glob("shards/*/shard.complete.json")).read_text())[
            "dropped_frames"
        ]["count"]
        == 1
    )
    assert len(list(SessionDataset.open(root).iter_records())) == 1


@pytest.mark.parametrize("aligned", [False, True])
def test_crash_resume_preserves_committed_supervision_and_replays_only_unpublished(
    tmp_path, aligned
):
    root = tmp_path / "crash"
    code = f"""
import os, sys
from isaac_audio_sensors.recording import SessionRecorder
from tests.integration.test_recording_writer import _configuration, _kwargs
from tests.integration.test_recording_truth import append
recorder = SessionRecorder(sys.argv[1], _configuration(aligned={aligned}), **_kwargs())
recorder.begin_episode("scene", "env", "scene")
for index in range(4):
    append(recorder, index)
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(root)], check=True)
    recorder = SessionRecorder.resume(
        root, _configuration(aligned=aligned), **_kwargs()
    )
    assert recorder.next_dataset_frame_index == 3
    for index in range(3, 6):
        append(recorder, index)
    recorder.end_episode()
    recorder.finalize()
    records = list(SessionDataset.open(root).iter_records())
    assert [(item.truth, item.annotations) for item in records] == [
        supervision(_frame(index, index), index) for index in range(6)
    ]
    assert validate_dataset(root).status == "passed"


def test_finalization_recovery_and_flac_preserve_supervision(tmp_path, monkeypatch):
    root = tmp_path / "session"
    recorder = SessionRecorder(root, _configuration(aligned=False), **_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    expected = [append(recorder, index) for index in range(3)]
    recorder.end_episode()
    import isaac_audio_sensors.recording.recorder as module

    real_write = module.write_json_atomic

    def interrupted(path, payload):
        if Path(path).name == "manifest.json":
            raise OSError("interrupted")
        return real_write(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(module, "write_json_atomic", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            recorder.finalize()
    assert not (root / "manifest.json").exists()
    SessionRecorder.recover_finalization(root)
    assert [
        (item.truth, item.annotations)
        for item in SessionDataset.open(root).iter_records()
    ] == expected
    pytest.importorskip("soundfile")
    exported = export_session_flac(
        root, tmp_path / "flac", dataset_id="flac_truth", creation_timestamp_ms=1
    )
    assert [
        (item.truth, item.annotations)
        for item in SessionDataset.open(exported).iter_records()
    ] == expected
    for path in root.glob("shards/*/frames.jsonl"):
        assert path.read_bytes() == (exported / path.relative_to(root)).read_bytes()


def test_frame_record_rejects_misaligned_malformed_and_legacy_supervision():
    frame = replace(
        _frame(2, 2),
        observations=(
            AudioObservation(
                observation_id="obs", origin="external_system", detector_id="external"
            ),
        ),
    )
    truth, annotations = supervision(frame, 2)
    annotations = (replace(annotations[0], observation_id="obs"),)
    record = build_dataset_frame_record(
        dataset_frame_index=0,
        episode_id_value="episode_00000",
        audio_start_sample=0,
        audio_end_sample=6,
        frame=frame,
        truth=truth,
        annotations=annotations,
    )
    encoded = serialize_dataset_frame_record(record)
    assert parse_dataset_frame_record(encoded) == record
    for change in ("misaligned", "unknown", "nan", "bool", "legacy", "annotation"):
        payload = json.loads(encoded)
        if change == "misaligned":
            payload["truth"]["frame_id"] = "wrong"
        elif change == "unknown":
            payload["truth"]["truth_events"][0]["audible"] = True
        elif change in {"nan", "bool"}:
            payload["truth"]["truth_events"][0]["emission_rms"] = (
                float("nan") if change == "nan" else True
            )
        elif change == "annotation":
            payload["annotations"][0]["observation_id"] = "absent"
        else:
            payload["record_version"] = "ias.dataset_frame_record.v1"
        with pytest.raises(DatasetLayoutError):
            parse_dataset_frame_record(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            )
    manifest = json.loads(
        Path("examples/manifests/minimal_manifest.v2.json").read_text()
    )
    manifest["schema_version"] = "ias.audio_dataset_manifest.v1"
    with pytest.raises(ValueError):
        manifest_from_dict(manifest)
    manifest["schema_version"] = "ias.audio_dataset_manifest.v2"
    manifest["episodes"][0]["source_truth"] = []
    with pytest.raises(ValueError):
        manifest_from_dict(manifest)


def test_analytic_truth_production_to_dataset(tmp_path):
    from tests.contract.test_dataset_truth import scene_with, simulate
    from tests.helpers import source

    frame, block, truth = simulate(scene_with(source("speaker", (1, 0, 0))))
    configuration = {
        **_configuration(aligned=True),
        "backend_id": "analytic_acoustics",
        "channel_order": list(block.microphone_ids),
        "window_sample_count": block.samples.shape[1],
        "hop_sample_count": block.samples.shape[1],
    }
    kwargs = _kwargs()
    kwargs["creation"] = replace(kwargs["creation"], backend_id="analytic_acoustics")
    root = tmp_path / "analytic"
    recorder = SessionRecorder(root, configuration, **kwargs)
    recorder.begin_episode("scene", "env", "scene")
    assert recorder.append_frame(frame, block, truth=truth).accepted
    recorder.end_episode()
    recorder.finalize()
    dataset = SessionDataset.open(root)
    (item,) = dataset.iter_records()
    assert item.truth == truth
    from isaac_audio_sensors.core.io.traces import frame_to_trace_dict

    assert frame_to_trace_dict(item.frame) == frame_to_trace_dict(frame)
    np.testing.assert_array_equal(dataset.read_frame_audio(item), block.samples)


def test_gap_padding_does_not_shift_truth_time_window(tmp_path):
    from tests.integration.test_recording_time_gaps import (
        _configuration as gap_configuration,
    )
    from tests.integration.test_recording_time_gaps import (
        _frame as gap_frame,
    )
    from tests.integration.test_recording_time_gaps import (
        _kwargs as gap_kwargs,
    )

    root = tmp_path / "gaps"
    recorder = SessionRecorder(root, gap_configuration(), **gap_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    expected = []
    for index, timestamp in enumerate((0, 4, 12)):
        frame = gap_frame(index, timestamp)
        truth, annotations = supervision(frame, index + 1)
        assert recorder.append_frame(
            frame,
            signal_block_for_frame(frame, np.ones((1, 6), np.float32)),
            truth=truth,
            annotations=annotations,
        ).accepted
        expected.append((truth, annotations))
    recorder.end_episode()
    recorder.finalize()
    records = list(SessionDataset.open(root).iter_records())
    assert [(item.truth, item.annotations) for item in records] == expected
    assert recorder.time_gap_summary["inserted_silence_samples"] == 4
    assert records[-1].frame.start_time_s == 0.012
    assert validate_dataset(root).status == "passed"
