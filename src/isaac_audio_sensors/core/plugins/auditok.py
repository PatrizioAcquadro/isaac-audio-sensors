"""Fixed-threshold Auditok activity detector adapter."""

from __future__ import annotations

import math
from types import ModuleType

import numpy as np

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.types import ActivityDecision

_FLOAT32_SAMPLE_WIDTH = 4
_AUDITOK_FLOAT32_SCALE = 32768.0
_AUDITOK_REFERENCE_DB = 20.0 * math.log10(_AUDITOK_FLOAT32_SCALE)


class AuditokActivityDetector:
    """Detect generic activity with Auditok's fixed energy threshold."""

    detector_id = "auditok"

    def __init__(
        self,
        *,
        energy_threshold_dbfs: float,
        analysis_window_s: float = 0.05,
        min_activity_s: float = 0.10,
        max_silence_s: float = 0.10,
    ) -> None:
        self.energy_threshold_dbfs = _finite_float(
            energy_threshold_dbfs,
            "energy_threshold_dbfs",
        )
        self.analysis_window_s = _positive_float(
            analysis_window_s,
            "analysis_window_s",
        )
        self.min_activity_s = _positive_float(
            min_activity_s,
            "min_activity_s",
        )
        self.max_silence_s = _non_negative_float(
            max_silence_s,
            "max_silence_s",
        )
        self._history: np.ndarray | None = None
        self._history_start_sample = 0
        self._stream_samples = 0
        self._sample_rate_hz: int | None = None
        self._channel_count: int | None = None

    def detect(
        self,
        samples: np.ndarray,
        sample_rate_hz: int,
    ) -> ActivityDecision:
        """Return whether an Auditok token overlaps the current sample block."""

        values, rate = _validated_samples(samples, sample_rate_hz)
        channel_count, current_sample_count = values.shape
        analysis_window_samples = int(self.analysis_window_s * rate)
        if analysis_window_samples < 1:
            raise ValueError(
                "analysis_window_s must cover at least one sample at "
                "sample_rate_hz."
            )
        self._validate_layout(rate, channel_count)

        auditok = _require_auditok()
        current_start = self._stream_samples
        if self._history is None:
            buffer_start = current_start
            buffered = values
        else:
            buffer_start = self._history_start_sample
            buffered = np.concatenate((self._history, values), axis=1)

        payload = _float32_interleaved_bytes(buffered)
        auditok_threshold_db = self.energy_threshold_dbfs + _AUDITOK_REFERENCE_DB
        regions = tuple(
            auditok.split(
                payload,
                sampling_rate=rate,
                sample_width=_FLOAT32_SAMPLE_WIDTH,
                channels=channel_count,
                use_channel="any",
                energy_threshold=auditok_threshold_db,
                analysis_window=self.analysis_window_s,
                min_dur=self.min_activity_s,
                max_dur=None,
                max_silence=self.max_silence_s,
                strict_min_dur=True,
            )
        )

        current_start_in_buffer = current_start - buffer_start
        current_end_in_buffer = current_start_in_buffer + current_sample_count
        active = any(
            _region_overlaps(
                region,
                sample_rate_hz=rate,
                channel_count=channel_count,
                start_sample=current_start_in_buffer,
                end_sample=current_end_in_buffer,
            )
            for region in regions
        )
        energy_dbfs = _current_energy_dbfs(
            auditok,
            values,
            channel_count=channel_count,
        )

        stream_end = current_start + current_sample_count
        history_start = _history_start(
            stream_end,
            analysis_window_samples=analysis_window_samples,
            min_activity_s=self.min_activity_s,
            max_silence_s=self.max_silence_s,
            sample_rate_hz=rate,
        )
        history_offset = history_start - buffer_start
        self._history = np.array(
            buffered[:, history_offset:],
            dtype=np.dtype("=f4"),
            copy=True,
            order="C",
        )
        self._history_start_sample = history_start
        self._stream_samples = stream_end
        self._sample_rate_hz = rate
        self._channel_count = channel_count

        return ActivityDecision(
            active=active,
            activity_probability=None,
            diagnostics={
                "profile": "fixed_threshold",
                "auditok_version": str(auditok.__version__),
                "energy_dbfs": energy_dbfs,
                "threshold_dbfs": self.energy_threshold_dbfs,
                "margin_db": energy_dbfs - self.energy_threshold_dbfs,
                "analysis_window_s": self.analysis_window_s,
                "min_activity_s": self.min_activity_s,
                "max_silence_s": self.max_silence_s,
                "channel_policy": "any",
            },
        )

    def reset(self) -> None:
        """Clear stream history while preserving the fixed configuration."""

        self._history = None
        self._history_start_sample = 0
        self._stream_samples = 0
        self._sample_rate_hz = None
        self._channel_count = None

    def _validate_layout(self, sample_rate_hz: int, channel_count: int) -> None:
        if self._sample_rate_hz is None:
            return
        if (
            sample_rate_hz != self._sample_rate_hz
            or channel_count != self._channel_count
        ):
            raise ValueError(
                "sample_rate_hz and channel count must remain unchanged until reset()."
            )


def _require_auditok() -> ModuleType:
    try:
        import auditok
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "AuditokActivityDetector requires auditok>=0.5.2,<0.6."
        ) from exc
    return auditok


def _validated_samples(
    samples: np.ndarray,
    sample_rate_hz: int,
) -> tuple[np.ndarray, int]:
    if isinstance(sample_rate_hz, bool) or not isinstance(
        sample_rate_hz,
        (int, np.integer),
    ):
        raise ValueError("sample_rate_hz must be a positive integer.")
    rate = int(sample_rate_hz)
    if rate <= 0:
        raise ValueError("sample_rate_hz must be a positive integer.")

    raw = np.asarray(samples)
    if raw.ndim != 2 or raw.shape[0] < 1 or raw.shape[1] < 1:
        raise ValueError("samples must have shape [at least 1 channel, samples].")
    if not np.issubdtype(raw.dtype, np.number):
        raise ValueError("samples must contain numeric values.")
    if not np.all(np.isfinite(raw)):
        raise ValueError("samples must contain only finite values.")
    with np.errstate(over="ignore", invalid="ignore"):
        values = np.asarray(raw, dtype=np.dtype("=f4"))
    if not np.all(np.isfinite(values)):
        raise ValueError("samples must be representable as finite float32 values.")
    return np.ascontiguousarray(values), rate


def _float32_interleaved_bytes(samples: np.ndarray) -> bytes:
    """Encode ``[channel, sample]`` values as native float32 sample frames."""

    return np.ascontiguousarray(
        samples.T,
        dtype=np.dtype("=f4"),
    ).tobytes(order="C")


def _current_energy_dbfs(
    auditok: ModuleType,
    samples: np.ndarray,
    *,
    channel_count: int,
) -> float:
    array = auditok.signal.to_array(
        _float32_interleaved_bytes(samples),
        _FLOAT32_SAMPLE_WIDTH,
        channel_count,
    )
    per_channel = np.asarray(auditok.signal.calculate_energy(array), dtype=float)
    return float(np.max(per_channel)) - _AUDITOK_REFERENCE_DB


def _region_overlaps(
    region: object,
    *,
    sample_rate_hz: int,
    channel_count: int,
    start_sample: int,
    end_sample: int,
) -> bool:
    region_start = int(round(float(region.start) * sample_rate_hz))
    region_samples = len(region.data) // (_FLOAT32_SAMPLE_WIDTH * channel_count)
    region_end = region_start + region_samples
    return region_start < end_sample and region_end > start_sample


def _history_start(
    stream_end: int,
    *,
    analysis_window_samples: int,
    min_activity_s: float,
    max_silence_s: float,
    sample_rate_hz: int,
) -> int:
    context_samples = math.ceil(
        (min_activity_s + max_silence_s) * sample_rate_hz
    ) + analysis_window_samples
    desired_start = max(0, stream_end - context_samples)
    return (desired_start // analysis_window_samples) * analysis_window_samples


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite.") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite.")
    return numeric


def _positive_float(value: object, name: str) -> float:
    numeric = _finite_float(value, name)
    if numeric <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return numeric


def _non_negative_float(value: object, name: str) -> float:
    numeric = _finite_float(value, name)
    if numeric < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return numeric


__all__ = ["AuditokActivityDetector"]
