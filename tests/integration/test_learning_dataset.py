"""Learning inputs remain observed-only across recording and corpus operations."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core import (
    AudioObservation,
    DoaEstimate,
    ObservationOrigin,
    Pose3D,
)
from isaac_audio_sensors.recording import (
    DatasetLayoutError,
    DatasetSplitError,
    LearningDataset,
    SessionDataset,
    SessionRecorder,
    collate_learning_samples,
    export_session_flac,
)
from tests.helpers import signal_block_for_frame
from tests.integration.test_recording_truth import supervision
from tests.integration.test_recording_writer import (
    _configuration,
    _frame,
    _kwargs,
)


def write_session(
    root,
    *,
    dataset_id=None,
    session_id=None,
    scene="scene",
    trajectory="route",
    assets=("sound",),
    with_audio=True,
    change_frame=None,
    change_supervision=None,
    counts=(2, 3),
    aligned=False,
    sample_rate=48000,
    reverse_channels=False,
    window=6,
):
    dataset_id = dataset_id or root.name
    configuration = _configuration(aligned=aligned, dataset_id=dataset_id)
    configuration["session_id"] = session_id or dataset_id
    configuration["sample_rate_hz"] = sample_rate
    configuration["window_sample_count"] = window
    if reverse_channels:
        configuration["channel_order"].reverse()
    recorder = SessionRecorder(root, configuration, **_kwargs())
    global_index = 0
    for episode, count in enumerate(counts):
        recorder.begin_episode(
            scene,
            f"env{episode}",
            scene,
            trajectory_id=trajectory,
            source_asset_ids=assets,
        )
        for local_index in range(count):
            frame = replace(
                _frame(global_index, local_index),
                sample_rate_hz=sample_rate,
                end_time_s=local_index / 1000 + window / sample_rate,
            )
            if change_frame:
                frame = change_frame(frame, global_index)
            truth, annotations = supervision(frame, global_index)
            if change_supervision:
                truth, annotations = change_supervision(truth, annotations)
            audio = np.broadcast_to(
                np.linspace(-0.1234, 0.2345, window, dtype=np.float32)
                + global_index / 32,
                (2, window),
            ).copy()
            if reverse_channels:
                frame = replace(
                    frame,
                    channel_validity=dict(
                        reversed(list(frame.channel_validity.items()))
                    ),
                )
            block = signal_block_for_frame(frame, audio) if with_audio else None
            result = recorder.append_frame(
                frame,
                block,
                truth=truth,
                annotations=annotations,
                is_reset=local_index == 0,
            )
            assert result.accepted, result.reason
            global_index += 1
        recorder.end_episode()
    recorder.finalize()
    return root


def inputs_equal(left, right):
    assert left.keys() == right.keys()
    for key in left:
        if left[key] is None:
            assert right[key] is None
        else:
            np.testing.assert_array_equal(left[key], right[key], err_msg=key)


def observed_frame(frame, index):
    observations = tuple(
        AudioObservation(
            observation_id=f"observed-{j}",
            origin=ObservationOrigin.SIGNAL_DERIVED,
            detector_id="detector",
            detection_score=0.25 if j == 0 else None,
            doa=DoaEstimate(
                estimated_bearing_deg=None,
                candidate_bearing_deg=(30, 150),
                estimated_elevation_deg=None,
                candidate_elevation_deg=(),
                bearing_confidence=0,
            )
            if j == 0
            else DoaEstimate(
                estimated_bearing_deg=45,
                estimated_elevation_deg=10,
                bearing_confidence=0.7,
                candidate_bearing_deg=(45,),
                candidate_elevation_deg=(10,),
            ),
            diagnostics={"private": "excluded"},
        )
        for j in range(index % 3)
    )
    return replace(
        frame,
        observations=observations,
        aggregate_per_mic_rms={"front": 0.0},
        channel_validity={"front": True, "rear": False},
    )


@pytest.mark.parametrize("aligned", [False, True])
@pytest.mark.parametrize("with_audio", [False, True])
def test_learning_sample_alignment_and_opt_in_supervision(
    tmp_path, aligned, with_audio
):
    root = write_session(
        tmp_path / "session",
        aligned=aligned,
        with_audio=with_audio,
        change_frame=observed_frame,
    )
    corpus = LearningDataset.open([root])
    samples = list(corpus.iter_samples(with_supervision=True))
    source = SessionDataset.open(root)
    records = list(source.iter_records())
    assert len(samples) == len(records) == 5
    assert len({s.context["audio_reference"][0] for s in samples}) >= 2
    assert [s.context["episode_start"] for s in samples] == [
        True,
        False,
        True,
        False,
        False,
    ]
    assert [s.context["is_reset"] for s in samples] == [True, False, True, False, False]
    for index, (sample, record) in enumerate(zip(samples, records, strict=True)):
        assert sample.frame == record.frame
        assert sample.truth == record.truth
        assert sample.annotations == record.annotations
        assert sample.context["dataset_frame_index"] == index
        assert sample.context["episode_id"] == record.episode_id
        if with_audio:
            np.testing.assert_array_equal(
                sample.policy_inputs["waveform"], source.read_frame_audio(record)
            )
            assert sample.policy_inputs["waveform"].dtype == np.float32
        else:
            assert sample.policy_inputs["waveform"] is None
            assert sample.policy_inputs["audio_mask"].size == 0
    # Known-empty truth is different from absent supervision, independent of O.
    assert samples[0].truth is None
    assert samples[1].truth.truth_events == ()
    assert len(samples[2].truth.truth_events) == 1
    assert len(samples[2].frame.observations) == 2
    hidden = list(corpus.iter_samples())
    for sample, visible in zip(hidden, samples, strict=True):
        assert sample.truth is None and sample.annotations == ()
        inputs_equal(sample.policy_inputs, visible.policy_inputs)


def test_metadata_and_supervision_cannot_change_policy_inputs(tmp_path):
    first = write_session(tmp_path / "a", change_frame=observed_frame)

    def changed(frame, index):
        frame = observed_frame(frame, index)
        return replace(
            frame,
            frame_id=f"other{index}",
            frame_name="private-name",
            provenance="isaac_live",
            array_pose=Pose3D(position_m=(99, 100, 1)),
            diagnostics={"source_class": "privileged", "bearing_truth": 123},
            observations=tuple(
                replace(
                    o,
                    observation_id=f"changed{j}",
                    detector_id="other-detector",
                    diagnostics={"truth": 999},
                )
                for j, o in enumerate(frame.observations)
            ),
        )

    def changed_supervision(truth, annotations):
        if truth is not None:
            truth = replace(
                truth,
                truth_events=tuple(
                    replace(
                        event,
                        class_label="Other",
                        bearing_deg=120,
                        position_world_m=(10, 20, 30),
                    )
                    for event in truth.truth_events
                ),
            )
        return truth, tuple(replace(a, label="different") for a in annotations)

    second = write_session(
        tmp_path / "b",
        scene="private-scene",
        trajectory="private-route",
        assets=("private-asset",),
        change_frame=changed,
        change_supervision=changed_supervision,
    )
    a = list(LearningDataset.open([first]).iter_samples(with_supervision=True))
    b = list(LearningDataset.open([second]).iter_samples(with_supervision=True))
    for left, right in zip(a, b, strict=True):
        assert left.frame != right.frame
        inputs_equal(left.policy_inputs, right.policy_inputs)
    with pytest.raises(ValueError, match="read-only"):
        a[0].policy_inputs["rms"][0] = 1
    with pytest.raises(TypeError):
        a[0].policy_inputs["truth"] = 1


def test_feature_only_loading_does_not_decode_audio(tmp_path, monkeypatch):
    root = write_session(tmp_path / "a")

    def forbidden(*args):
        raise AssertionError("unexpected waveform decoding")

    monkeypatch.setattr(SessionDataset, "read_frame_audio", forbidden)
    samples = list(LearningDataset.open([root]).iter_samples(with_audio=False))
    assert len(samples) == 5
    assert all(s.policy_inputs["waveform"] is None for s in samples)


def test_collation_masks_missingness_and_variable_lengths(tmp_path):
    root = write_session(tmp_path / "audio", change_frame=observed_frame)
    longer = write_session(
        tmp_path / "long", change_frame=observed_frame, window=10, aligned=True
    )
    absent = write_session(
        tmp_path / "metadata", with_audio=False, change_frame=observed_frame
    )
    a = list(LearningDataset.open([root]).iter_samples(with_supervision=True))
    b = list(LearningDataset.open([longer]).iter_samples(with_supervision=True))
    c = list(LearningDataset.open([absent]).iter_samples(with_supervision=True))
    selected = [a[0], b[2], c[1]]
    batch = collate_learning_samples(selected)
    inputs = batch["policy_inputs"]
    assert inputs["waveform"].shape == (3, 2, 10)
    np.testing.assert_array_equal(inputs["audio_mask"].sum(axis=1), [6, 10, 0])
    np.testing.assert_array_equal(
        inputs["observation_mask"], [[False, False], [True, True], [True, False]]
    )
    np.testing.assert_array_equal(
        inputs["detection_score_mask"], [[False, False], [True, False], [True, False]]
    )
    np.testing.assert_array_equal(
        inputs["bearing_deg_mask"], [[False, False], [False, True], [False, False]]
    )
    assert inputs["candidate_bearing_deg"].shape == (3, 2, 2)
    np.testing.assert_array_equal(
        inputs["candidate_bearing_deg_mask"][1], [[True, True], [True, False]]
    )
    assert inputs["candidate_elevation_deg"].shape == (3, 2, 1)
    assert inputs["candidate_elevation_deg_mask"][1, 1, 0]
    np.testing.assert_array_equal(inputs["rms_mask"], [[True, False]] * 3)
    np.testing.assert_array_equal(inputs["channel_validity"], [[True, False]] * 3)
    assert inputs["rms"][0, 0] == 0  # valid zero is not missing
    assert batch["truth"] == tuple(s.truth for s in selected)
    assert batch["frames"] == tuple(s.frame for s in selected)
    assert batch["annotations"] == tuple(s.annotations for s in selected)
    empty = collate_learning_samples([c[0]])["policy_inputs"]
    assert empty["waveform"] is None
    assert empty["observation_mask"].shape == (1, 0)
    assert empty["candidate_bearing_deg"].shape == (1, 0, 0)
    assert empty["audio_mask"].shape == (1, 0)


@pytest.mark.parametrize(
    "change,field",
    [
        ({"sample_rate": 24000}, "sample_rate_hz"),
        ({"reverse_channels": True}, "channel_order"),
    ],
)
def test_collation_rejects_incompatible_captures(tmp_path, change, field):
    a = write_session(tmp_path / "a")
    b = write_session(tmp_path / "b", **change)
    samples = [next(LearningDataset.open([root]).iter_samples()) for root in (a, b)]
    with pytest.raises(ValueError, match=field):
        collate_learning_samples(samples)
    with pytest.raises(ValueError, match="non-empty"):
        collate_learning_samples([])


@pytest.mark.parametrize(
    "dtype,tolerance", [("int16", 1 / 32768), ("int24", 1 / 8388608)]
)
def test_flac_amplitude_and_acquisition_identity(tmp_path, dtype, tolerance):
    pytest.importorskip("soundfile")

    a = write_session(tmp_path / "a", change_frame=observed_frame)
    b = export_session_flac(a, tmp_path / "flac", dataset_id="transcoded", dtype=dtype)
    c = write_session(
        tmp_path / "c", scene="other", trajectory="other", assets=("other",)
    )
    corpus = LearningDataset.open([a, b, c])
    split = corpus.build_split(ratios={"train": 0.5, "test": 0.5}, seed=42)
    assert any(set(group) == {"a", "transcoded"} for group in split.values())
    original = list(LearningDataset.open([a]).iter_samples(with_supervision=True))
    converted = list(LearningDataset.open([b]).iter_samples(with_supervision=True))
    for left, right in zip(original, converted, strict=True):
        np.testing.assert_allclose(
            left.policy_inputs["waveform"],
            right.policy_inputs["waveform"],
            rtol=0,
            atol=tolerance,
        )
        assert left.truth == right.truth
        assert right.context["session_id"] == left.context["session_id"]
        assert right.policy_inputs["waveform"].dtype == np.float32


def test_transitive_split_is_deterministic_and_filters_whole_artifacts(tmp_path):
    a = write_session(tmp_path / "a", scene="shared", trajectory="a", assets=("a",))
    b = write_session(
        tmp_path / "b", scene="shared", trajectory="bridge", assets=("b",)
    )
    c = write_session(
        tmp_path / "c", scene="c", trajectory="bridge", assets=("bridge",)
    )
    d = write_session(tmp_path / "d", scene="d", trajectory="d", assets=("bridge",))
    e = write_session(tmp_path / "e", scene="e", trajectory="e", assets=())
    roots = [a, b, c, d, e]
    corpus = LearningDataset.open(roots)
    kwargs = {"ratios": {"train": 0.6, "test": 0.4}, "seed": 7}
    result = corpus.build_split(**kwargs)
    assert sorted(result.values()) == [("a", "b", "c", "d"), ("e",)]
    assert result == LearningDataset.open(list(reversed(roots))).build_split(**kwargs)
    assert result == corpus.build_split(
        **{**kwargs, "ratios": {"test": 0.4, "train": 0.6}},
        isolate_by=("asset", "scene", "trajectory"),
    )
    assert sum(len(list(corpus.iter_samples(split=split))) for split in result) == 25
    for partition, ids in result.items():
        samples = list(corpus.iter_samples(split=partition))
        assert {s.context["dataset_id"] for s in samples} == set(ids)
    with pytest.raises(TypeError):
        result["train"] = ()


def test_split_missing_identities_and_explicit_axis_exclusion(tmp_path):
    a = write_session(tmp_path / "a", trajectory=None, assets=None)
    b = write_session(tmp_path / "b", trajectory=None, assets=None, scene="other")
    corpus = LearningDataset.open([a, b])
    kwargs = {"ratios": {"train": 0.5, "test": 0.5}, "seed": 1}
    with pytest.raises(DatasetSplitError, match="missing asset"):
        corpus.build_split(**kwargs)
    with pytest.raises(DatasetSplitError, match="missing trajectory"):
        corpus.build_split(**kwargs, isolate_by=("trajectory",))
    assert len(corpus.build_split(**kwargs, isolate_by=("scene",))) == 2
    with pytest.raises(DatasetSplitError, match="matching split"):
        list(corpus.iter_samples(split="validation"))


@pytest.mark.parametrize("axis", ["session", "scene", "trajectory", "asset"])
def test_each_identity_axis_prevents_leakage(tmp_path, axis):
    properties = {
        "session": {"session_id": "same"},
        "scene": {"scene": "same"},
        "trajectory": {"trajectory": "same"},
        "asset": {"assets": ("same",)},
    }
    roots = [
        write_session(
            tmp_path / name,
            **{
                "scene": name,
                "trajectory": name,
                "assets": (name,),
                **properties[axis],
            },
        )
        for name in ("a", "b")
    ]
    corpus = LearningDataset.open(roots)
    kwargs = {"ratios": {"train": 0.5, "test": 0.5}, "seed": 1}
    with pytest.raises(DatasetSplitError, match="only 1 independent groups"):
        corpus.build_split(**kwargs)
    if axis != "session":
        assert len(corpus.build_split(**kwargs, isolate_by=())) == 2
    else:
        with pytest.raises(DatasetSplitError, match="session"):
            corpus.build_split(**kwargs, isolate_by=())


def test_duplicate_artifacts_are_rejected(tmp_path):
    a = write_session(tmp_path / "a")
    b = write_session(tmp_path / "b", dataset_id="a")
    for roots, message in [
        ([a, a], "duplicate session path"),
        ([a, b], "duplicate dataset_id"),
    ]:
        with pytest.raises(DatasetSplitError, match=message):
            LearningDataset.open(roots)


@pytest.mark.parametrize("corruption", ["record", "reset"])
def test_corruption_cannot_enter_samples_or_splits(tmp_path, corruption):
    a = write_session(tmp_path / "a")
    if corruption == "record":
        path = next(a.glob("shards/*/frames.jsonl"))
        path.write_bytes(path.read_bytes() + b"garbage\n")
    else:
        path = a / "manifest.json"
        payload = json.loads(path.read_text())
        # Valid timestamp in the episode, wrong timestamp for this reset's frame.
        payload["episodes"][0]["reset_markers"][0]["timestamp_ms"] = 1
        path.write_text(json.dumps(payload))
    corpus = LearningDataset.open([a])
    with pytest.raises(DatasetLayoutError):
        list(corpus.iter_samples())
    with pytest.raises(DatasetLayoutError):
        corpus.build_split(ratios={"train": 1.0}, seed=0)


def test_learning_preserves_gap_audio_ranges_and_reset_context(tmp_path):
    from tests.integration.test_recording_time_gaps import _record

    root = tmp_path / "gaps"
    _record(root)
    samples = list(LearningDataset.open([root]).iter_samples())
    source = SessionDataset.open(root)
    records = list(source.iter_records())
    assert [s.frame.timestamp_ms for s in samples] == [0, 4, 12]
    assert [s.context["is_reset"] for s in samples] == [True, False, False]
    assert [s.context["audio_reference"][1] for s in samples] == [0, 4, 12]
    for sample, record in zip(samples, records, strict=True):
        np.testing.assert_array_equal(
            sample.policy_inputs["waveform"], source.read_frame_audio(record)
        )
        assert "recording" not in sample.policy_inputs


def test_mid_episode_reset_does_not_become_an_episode_start(tmp_path):
    root = tmp_path / "reset"
    recorder = SessionRecorder(root, _configuration(aligned=False), **_kwargs())
    recorder.begin_episode("scene", "env", "scene")
    for index in range(3):
        frame = _frame(index, index)
        assert recorder.append_frame(
            frame,
            signal_block_for_frame(frame, np.ones((2, 6), np.float32)),
            is_reset=index == 1,
        ).accepted
    recorder.end_episode()
    recorder.finalize()
    samples = list(LearningDataset.open([root]).iter_samples())
    assert [s.context["episode_start"] for s in samples] == [True, False, False]
    assert [s.context["is_reset"] for s in samples] == [False, True, False]


def test_failed_split_request_does_not_reuse_a_previous_assignment(tmp_path):
    roots = [write_session(tmp_path / name) for name in ("a", "b")]
    corpus = LearningDataset.open(roots)
    corpus.build_split(ratios={"train": 1.0}, seed=1)
    with pytest.raises(DatasetSplitError, match="independent groups"):
        corpus.build_split(ratios={"train": 0.5, "test": 0.5}, seed=1)
    with pytest.raises(DatasetSplitError, match="matching split"):
        list(corpus.iter_samples(split="train"))


@pytest.mark.parametrize(
    "options",
    [
        {"seed": True},
        {"isolate_by": ("session",)},
        {"isolate_by": ("asset", "asset")},
        {"ratios": {"train": 0.9}},
        {"kind": "unknown"},
    ],
)
def test_invalid_split_options_are_explicit(tmp_path, options):
    root = write_session(tmp_path / "a")
    corpus = LearningDataset.open([root])
    with pytest.raises(DatasetSplitError):
        corpus.build_split(**{"ratios": {"train": 1.0}, "seed": 1, **options})


@pytest.mark.parametrize("field", ["sample_rate_hz", "channel_validity"])
def test_frame_and_audio_metadata_must_describe_the_same_capture(tmp_path, field):
    from tests.integration.test_recording_validation import _mutate_record

    root = write_session(tmp_path / "a")

    def mutate(record):
        # First frame has no truth: this must be checked independently of supervision.
        if field == "sample_rate_hz":
            record["frame"][field] = 24000
        else:
            record["frame"][field] = {"other": True, "rear": True}
            record["frame"]["aggregate_per_mic_rms"] = {"other": 0.1, "rear": 0.1}

    _mutate_record(root, 0, mutate)
    corpus = LearningDataset.open([root])
    with pytest.raises(DatasetLayoutError, match="frame .*disagree"):
        list(corpus.iter_samples())
    with pytest.raises(DatasetLayoutError, match="frame .*disagree"):
        corpus.build_split(ratios={"train": 1.0}, seed=0)


def test_manifest_cannot_relabel_recorded_audio_channels(tmp_path):
    root = write_session(tmp_path / "a")
    path = root / "manifest.json"
    payload = json.loads(path.read_text())
    payload["channel_order"].reverse()
    path.write_text(json.dumps(payload))
    with pytest.raises(DatasetLayoutError, match="channel_order disagrees"):
        LearningDataset.open([root])


def test_metadata_only_capture_rejects_mismatched_channels_before_advancing(tmp_path):
    recorder = SessionRecorder(
        tmp_path / "a", _configuration(aligned=False), **_kwargs()
    )
    recorder.begin_episode("scene", "env", "scene")
    frame = replace(
        _frame(0, 0), channel_validity={"other": True}, aggregate_per_mic_rms={}
    )
    rejected = recorder.append_frame(frame, None)
    assert not rejected.accepted
    assert "channel_validity" in rejected.reason
    assert recorder.next_dataset_frame_index == 0
    assert recorder.append_frame(_frame(0, 0), None).accepted
    recorder.end_episode()
    recorder.finalize()


def test_confidence_missing_and_zero_survive_recording_replay_and_learning(tmp_path):
    from isaac_audio_sensors.recording import replay_session

    def observations(frame, index):
        return replace(frame, observations=tuple(
            AudioObservation(
                observation_id=f"event-{i}",
                origin=ObservationOrigin.SIGNAL_DERIVED,
                detector_id="observed",
                doa=DoaEstimate(estimated_bearing_deg=20, bearing_confidence=c),
            ) for i, c in enumerate((None, 0.0, 0.7))
        ))

    root = write_session(tmp_path / "confidence", change_frame=observations)
    for event in replay_session(root):
        if event.kind == "frame":
            values = [o.doa.bearing_confidence for o in event.frame.frame.observations]
            assert values == [None, 0, 0.7]
    for sample in LearningDataset.open([root]).iter_samples():
        mask = sample.policy_inputs["bearing_confidence_mask"].tolist()
        assert mask == [False, True, True]
        values = sample.policy_inputs["bearing_confidence"].tolist()
        assert values == pytest.approx([0, 0, 0.7])
