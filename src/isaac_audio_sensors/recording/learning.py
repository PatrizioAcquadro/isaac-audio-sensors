"""Observed-only NumPy learning inputs beside explicitly requested supervision."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording._learning_splits import build_corpus_split
from isaac_audio_sensors.recording.loader import (
    DatasetLayoutError,
    LoadedFrame,
    SessionDataset,
)
from isaac_audio_sensors.recording.splits import DatasetSplitError, SplitKind
from isaac_audio_sensors.recording.truth import AnnotationRecord, FrameTruth

# These names select numerical evidence, never arbitrary frame/observation maps.
_OBSERVATION_FIELDS = (
    "detection_score",
    "bearing_deg",
    "elevation_deg",
    "bearing_confidence",
)
_CANDIDATE_FIELDS = ("candidate_bearing_deg", "candidate_elevation_deg")


@dataclass(frozen=True, slots=True)
class LearningSample:
    """One aligned sample. Only ``policy_inputs`` is intended for the policy.

    ``context`` contains dataset/session/episode IDs, dataset frame index, shard
    audio bounds, sample rate, channel order, episode start, and explicit reset.
    Full frames, context, truth, and annotations are never collated into inputs.
    """

    policy_inputs: Mapping[str, np.ndarray | None]
    frame: AudioSensorFrame
    truth: FrameTruth | None
    annotations: tuple[AnnotationRecord, ...]
    context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_inputs", _freeze_inputs(self.policy_inputs))
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        object.__setattr__(self, "annotations", tuple(self.annotations))


class LearningDataset:
    """Checked, streaming access to a corpus of complete recorded artifacts.

    Iteration follows input session order and then recorded frame order.
    ``build_split`` installs an in-memory assignment; ``iter_samples(split=...)``
    selects it without applying or modifying individual manifest splits.
    """

    def __init__(self, datasets: tuple[SessionDataset, ...]) -> None:
        self._datasets = datasets
        self._splits: Mapping[str, tuple[str, ...]] | None = None

    @classmethod
    def open(
        cls, session_roots: Sequence[str | Path], *, verify_checksums: bool = True
    ) -> LearningDataset:
        """Open unique artifacts; record verification remains incremental."""

        if isinstance(session_roots, (str, Path)) or not session_roots:
            raise ValueError("session_roots must be a non-empty sequence of paths.")
        datasets = []
        paths: set[Path] = set()
        ids: set[str] = set()
        for value in session_roots:
            path = Path(value).expanduser().absolute()
            if path.resolve() in paths:
                raise DatasetSplitError(f"duplicate session path: {path}")
            dataset = SessionDataset.open(path, verify_checksums=verify_checksums)
            dataset_id = dataset.manifest.dataset_id
            if dataset_id in ids:
                raise DatasetSplitError(f"duplicate dataset_id: {dataset_id}")
            ids.add(dataset_id)
            paths.add(path.resolve())
            datasets.append(dataset)
        return cls(tuple(datasets))

    def build_split(
        self,
        *,
        ratios: Mapping[str, float],
        seed: int,
        isolate_by: Sequence[str] = ("scene", "trajectory", "asset"),
        kind: SplitKind = "train_validation_test",
    ) -> Mapping[str, tuple[str, ...]]:
        """Validate and partition whole acquisitions; return artifact IDs per split.

        Session identity is mandatory. Optional isolation axes default to scene,
        trajectory, and source asset. Missing identities on selected axes fail.
        Ratios are targets, not guarantees when indivisible groups are unequal.
        """

        self._splits = None
        assignments = build_corpus_split(
            self._datasets,
            ratios=ratios,
            seed=seed,
            isolate_by=isolate_by,
            kind=kind,
        )
        self._splits = MappingProxyType(assignments)
        return self._splits

    def iter_samples(
        self,
        *,
        with_audio: bool = True,
        with_supervision: bool = False,
        split: str | None = None,
    ) -> Iterator[LearningSample]:
        """Yield policy inputs separately from complete frames and supervision.

        Missing recorded audio stays ``None``. With audio disabled, no waveform
        is decoded. Supervision is hidden by default, including annotations.
        """

        for name, value in (
            ("with_audio", with_audio),
            ("with_supervision", with_supervision),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} must be a bool.")
        selected = None
        if split is not None:
            if self._splits is None or split not in self._splits:
                raise DatasetSplitError(
                    f"split {split!r}: build a matching split first."
                )
            selected = set(self._splits[split])
        for dataset in self._datasets:
            manifest = dataset.manifest
            if selected is not None and manifest.dataset_id not in selected:
                continue
            for episode, records in dataset.iter_episodes():
                resets = {reset.frame_index for reset in episode.reset_markers}
                for record in records:
                    audio = None
                    if (
                        with_audio
                        and record.audio_end_sample > record.audio_start_sample
                    ):
                        audio = _learning_audio(dataset, record)
                    yield LearningSample(
                        policy_inputs=_project_inputs(
                            record.frame, manifest.channel_order, audio
                        ),
                        frame=record.frame,
                        truth=record.truth if with_supervision else None,
                        annotations=record.annotations if with_supervision else (),
                        context={
                            "dataset_id": manifest.dataset_id,
                            "session_id": manifest.session_id,
                            "episode_id": record.episode_id,
                            "dataset_frame_index": record.dataset_frame_index,
                            "audio_reference": (
                                record.shard_id,
                                record.audio_start_sample,
                                record.audio_end_sample,
                            ),
                            "sample_rate_hz": manifest.sample_rate_hz,
                            "channel_order": manifest.channel_order,
                            "episode_start": record.dataset_frame_index
                            == episode.start_frame,
                            "is_reset": record.dataset_frame_index in resets,
                        },
                    )


def _learning_audio(dataset: SessionDataset, record: LoadedFrame) -> np.ndarray:
    audio = dataset.read_frame_audio(record)
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / np.float32(32768)
    elif audio.dtype == np.int32:
        # The loader returns left-aligned PCM24 in int32 containers.
        audio = audio.astype(np.float32) / np.float32(2147483648)
    if not np.isfinite(audio).all():
        raise DatasetLayoutError(
            f"dataset {dataset.manifest.dataset_id} frame "
            f"{record.dataset_frame_index}: non-finite learning audio."
        )
    return audio


def _project_inputs(
    frame: AudioSensorFrame, channel_order: tuple[str, ...], audio: np.ndarray | None
) -> dict[str, np.ndarray | None]:
    observations = frame.observations
    count = len(observations)
    rms = frame.aggregate_per_mic_rms
    result = {
        "waveform": audio,
        "audio_mask": np.ones(0 if audio is None else audio.shape[1], dtype=bool),
        "channel_validity": np.array(
            [frame.channel_validity[c] for c in channel_order]
        ),
        "rms": np.array([rms.get(c, 0.0) for c in channel_order], dtype=np.float32),
        "rms_mask": np.array([c in rms for c in channel_order], dtype=bool),
        "observation_mask": np.ones(count, dtype=bool),
    }
    for name in _OBSERVATION_FIELDS:
        values = []
        for observation in observations:
            if name == "detection_score":
                value = observation.detection_score
            elif observation.doa is None:
                value = None
            else:
                attr = (
                    "estimated_" + name
                    if name in ("bearing_deg", "elevation_deg")
                    else name
                )
                value = getattr(observation.doa, attr)
            values.append(value)
        result[name] = np.array(
            [0.0 if v is None else v for v in values], dtype=np.float32
        )
        result[name + "_mask"] = np.array([v is not None for v in values], dtype=bool)
    for name in _CANDIDATE_FIELDS:
        values = [
            getattr(o.doa, name) if o.doa is not None else () for o in observations
        ]
        width = max((len(v) for v in values), default=0)
        result[name] = np.zeros((count, width), dtype=np.float32)
        result[name + "_mask"] = np.zeros((count, width), dtype=bool)
        for row, candidates in enumerate(values):
            result[name][row, : len(candidates)] = candidates
            result[name + "_mask"][row, : len(candidates)] = True
    return result


def _freeze_inputs(
    inputs: Mapping[str, np.ndarray | None],
) -> Mapping[str, np.ndarray | None]:
    result = dict(inputs)
    for value in result.values():
        if value is not None:
            value.setflags(write=False)
    return MappingProxyType(result)


def collate_learning_samples(samples: Sequence[LearningSample]) -> dict[str, Any]:
    """Pad single-frame inputs without truncation or supervision matching.

    Boolean masks distinguish missing evidence from numerical zero. Candidate
    axes are independent; no pairing of bearing and elevation is invented.
    Sample rate and ordered microphone IDs must agree across the batch.
    """

    if not samples or any(not isinstance(s, LearningSample) for s in samples):
        raise ValueError("samples must be a non-empty sequence of LearningSample.")
    context = samples[0].context
    for sample in samples[1:]:
        for name in ("sample_rate_hz", "channel_order"):
            if sample.context[name] != context[name]:
                raise ValueError(f"batch {name} mismatch; no implicit conversion.")
    keys = set(samples[0].policy_inputs)
    if any(set(s.policy_inputs) != keys for s in samples):
        raise ValueError("batch policy input fields must agree.")
    batch = {}
    for key in samples[0].policy_inputs:
        arrays = [s.policy_inputs[key] for s in samples]
        present = [a for a in arrays if a is not None]
        if not present:
            batch[key] = None
            continue
        shape = tuple(
            max(a.shape[axis] for a in present) for axis in range(present[0].ndim)
        )
        padded = np.zeros((len(samples), *shape), dtype=present[0].dtype)
        for row, array in enumerate(arrays):
            if array is not None:
                padded[(row, *(slice(0, n) for n in array.shape))] = array
        batch[key] = padded
    return {
        "policy_inputs": _freeze_inputs(batch),
        "frames": tuple(s.frame for s in samples),
        "truth": tuple(s.truth for s in samples),
        "annotations": tuple(s.annotations for s in samples),
        "context": tuple(s.context for s in samples),
    }


__all__ = ["LearningDataset", "LearningSample", "collate_learning_samples"]
