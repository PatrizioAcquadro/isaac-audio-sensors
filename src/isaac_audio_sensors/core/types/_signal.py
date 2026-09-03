"""Observed microphone-signal contract shared by signal producers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isaac_audio_sensors.core.types._scene import AudioTimeWindow
from isaac_audio_sensors.core.types._validation import require_non_empty

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneSignalBlock:
    """One exact, ordered microphone-major signal window."""

    samples: NDArray[np.float32]
    microphone_ids: tuple[str, ...]
    array_id: str
    sample_rate_hz: int
    time_window: AudioTimeWindow
    channel_validity: tuple[bool, ...]
    producer_id: str
    provenance: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        import numpy as np

        require_non_empty(self.array_id, "MicrophoneSignalBlock.array_id")
        require_non_empty(self.producer_id, "MicrophoneSignalBlock.producer_id")
        require_non_empty(self.provenance, "MicrophoneSignalBlock.provenance")
        if type(self.sample_rate_hz) is not int or self.sample_rate_hz <= 0:
            raise ValueError(
                "MicrophoneSignalBlock.sample_rate_hz must be a positive integer."
            )
        if not isinstance(self.time_window, AudioTimeWindow):
            raise TypeError(
                "MicrophoneSignalBlock.time_window must be an AudioTimeWindow."
            )

        microphone_ids = tuple(self.microphone_ids)
        if not microphone_ids:
            raise ValueError(
                "MicrophoneSignalBlock.microphone_ids must not be empty."
            )
        for microphone_id in microphone_ids:
            require_non_empty(
                microphone_id,
                "MicrophoneSignalBlock.microphone_ids entry",
            )
        if len(set(microphone_ids)) != len(microphone_ids):
            raise ValueError(
                "MicrophoneSignalBlock.microphone_ids must contain unique values."
            )

        channel_validity = tuple(self.channel_validity)
        if len(channel_validity) != len(microphone_ids):
            raise ValueError(
                "MicrophoneSignalBlock.channel_validity must match microphone_ids."
            )
        if any(type(value) is not bool for value in channel_validity):
            raise ValueError(
                "MicrophoneSignalBlock.channel_validity entries must be booleans."
            )

        samples = np.array(
            self.samples,
            dtype=np.float32,
            order="C",
            copy=True,
        )
        if samples.ndim != 2:
            raise ValueError(
                "MicrophoneSignalBlock.samples must have shape [microphone, sample]."
            )
        if samples.shape[0] != len(microphone_ids):
            raise ValueError(
                "MicrophoneSignalBlock.samples microphone axis must match "
                "microphone_ids."
            )
        expected_sample_count = max(
            1,
            int(
                round(
                    (
                        self.time_window.end_time_s
                        - self.time_window.start_time_s
                    )
                    * self.sample_rate_hz
                )
            ),
        )
        if samples.shape[1] != expected_sample_count:
            raise ValueError(
                "MicrophoneSignalBlock.samples sample axis must match the exact "
                f"time window ({expected_sample_count} samples)."
            )
        if not np.all(np.isfinite(samples)):
            raise ValueError(
                "MicrophoneSignalBlock.samples must contain only finite values."
            )

        samples.setflags(write=False)
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "microphone_ids", microphone_ids)
        object.__setattr__(self, "channel_validity", channel_validity)
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


__all__ = ["MicrophoneSignalBlock"]
