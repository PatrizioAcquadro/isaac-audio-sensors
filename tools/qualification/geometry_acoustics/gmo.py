"""Host-testable classification of RTX Acoustic GenericModelOutput."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike


@dataclass(frozen=True, slots=True)
class SignalWay:
    transmitter_id: int
    receiver_id: int
    channel_id: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class GmoClassification:
    semantic: str
    signal_ways: tuple[SignalWay, ...]
    is_passive_microphone_pcm: bool
    duplicate_keys: tuple[tuple[int, int, int], ...]


def expand_signal_way_ids(
    transmitter_ids: ArrayLike,
    receiver_ids: ArrayLike,
    channel_ids: ArrayLike,
    *,
    signal_way_count: int,
    samples_per_way: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expand the GMO metadata prefix to one ID triplet per waveform sample."""

    arrays = tuple(
        np.asarray(values).reshape(-1)
        for values in (transmitter_ids, receiver_ids, channel_ids)
    )
    if signal_way_count <= 0 or samples_per_way <= 0:
        raise ValueError("GMO signal-way dimensions must be positive.")
    if any(values.size < signal_way_count for values in arrays):
        raise ValueError("GMO identifier buffers do not contain the metadata prefix.")
    return tuple(
        np.repeat(values[:signal_way_count], samples_per_way) for values in arrays
    )


def classify_acoustic_gmo(
    transmitter_ids: ArrayLike,
    receiver_ids: ArrayLike,
    channel_ids: ArrayLike,
) -> GmoClassification:
    """Classify GMO as active transmitter/receiver signal ways, never raw PCM."""

    tx = np.asarray(transmitter_ids).reshape(-1)
    rx = np.asarray(receiver_ids).reshape(-1)
    channels = np.asarray(channel_ids).reshape(-1)
    if not (tx.size == rx.size == channels.size):
        raise ValueError("GMO identifier arrays must have equal lengths.")
    counts: dict[tuple[int, int, int], int] = defaultdict(int)
    transitions: list[tuple[int, int, int]] = []
    previous: tuple[int, int, int] | None = None
    seen_runs: set[tuple[int, int, int]] = set()
    duplicates: set[tuple[int, int, int]] = set()
    for raw_key in zip(tx, rx, channels, strict=True):
        key = tuple(int(value) for value in raw_key)
        counts[key] += 1
        if key != previous:
            if key in seen_runs:
                duplicates.add(key)
            seen_runs.add(key)
            transitions.append(key)
            previous = key
    ways = tuple(
        SignalWay(key[0], key[1], key[2], counts[key]) for key in sorted(counts)
    )
    return GmoClassification(
        semantic="active_transmitter_receiver_signal_ways",
        signal_ways=ways,
        is_passive_microphone_pcm=False,
        duplicate_keys=tuple(sorted(duplicates)),
    )
