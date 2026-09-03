"""Provider-neutral internal types used only by the R9.2 harness."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    """One provider's availability and runtime identity."""

    available: bool
    provider_version: str
    runtime: Mapping[str, str]
    capabilities: Mapping[str, bool]
    details: Mapping[str, object] = field(default_factory=dict)
    external_blocker: str | None = None


@dataclass(frozen=True, slots=True)
class SignalBlock:
    """Temporary qualification signal block; not a public SDK contract."""

    samples: NDArray[np.float32]
    microphone_ids: tuple[str, ...]
    sample_rate_hz: int
    timing_ms: Mapping[str, float]

    def __post_init__(self) -> None:
        samples = np.asarray(self.samples, dtype=np.float32)
        if samples.ndim != 2:
            raise ValueError("samples must have shape [microphone, sample].")
        if samples.shape[0] != len(self.microphone_ids):
            raise ValueError("microphone_ids must match the microphone axis.")
        if not self.microphone_ids or len(set(self.microphone_ids)) != len(
            self.microphone_ids
        ):
            raise ValueError("microphone_ids must be non-empty and unique.")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive.")
        if any(float(value) < 0.0 for value in self.timing_ms.values()):
            raise ValueError("timing values must be non-negative.")
        samples.setflags(write=False)
        object.__setattr__(self, "samples", samples)


@dataclass(frozen=True, slots=True)
class DebugPathSample:
    """Provider-native path sample kept outside frames and datasets."""

    source_id: str
    microphone_id: str
    frame_index: int
    points_world: tuple[tuple[float, float, float], ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


def bounded_diagnostics(
    diagnostics: Sequence[DebugPathSample], *, limit: int = 256
) -> tuple[DebugPathSample, ...]:
    """Limit native diagnostics independently per source/mic/frame key."""

    if limit < 0:
        raise ValueError("limit must be non-negative.")
    counts: dict[tuple[str, str, int], int] = defaultdict(int)
    kept: list[DebugPathSample] = []
    for diagnostic in diagnostics:
        key = (
            diagnostic.source_id,
            diagnostic.microphone_id,
            diagnostic.frame_index,
        )
        if counts[key] >= limit:
            continue
        counts[key] += 1
        kept.append(diagnostic)
    return tuple(kept)


@dataclass(frozen=True, slots=True)
class FixtureRun:
    """One repeated fixture result and its provider-native observations."""

    fixture_id: str
    repetition: int
    block: SignalBlock | None
    measurements: Mapping[str, object]
    diagnostics: tuple[DebugPathSample, ...] = ()
    compatible: bool = True
    incompatibility: str | None = None


@dataclass(frozen=True, slots=True)
class PerformanceRun:
    """Complete-block timing distribution for a provider/environment count."""

    environment_count: int
    diagnostics_enabled: bool
    warmup_blocks: int
    measured_blocks: int
    block_ms: tuple[float, ...]
    peak_memory_mib: float
    update_ms: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.environment_count not in (1, 4):
            raise ValueError("environment_count must be one or four.")
        if self.warmup_blocks < 0 or self.measured_blocks <= 0:
            raise ValueError("performance block counts are invalid.")
        if len(self.block_ms) != self.measured_blocks:
            raise ValueError("block_ms must contain every measured block.")


class CandidateAdapter(Protocol):
    """Temporary adapter interface frozen for R9.2 only."""

    candidate_id: str
    candidate_version: str

    def probe_runtime(self) -> RuntimeProbe: ...

    def run_fixture(
        self, fixture: object, *, repetition: int, diagnostics: bool = False
    ) -> FixtureRun: ...

    def run_performance(
        self, *, environment_count: int, diagnostics: bool
    ) -> PerformanceRun: ...

    def close(self) -> None: ...
