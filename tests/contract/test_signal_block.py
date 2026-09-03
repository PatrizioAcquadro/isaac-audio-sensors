from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from isaac_audio_sensors.core import (
    AudioTimeWindow,
    MicrophoneSignalBlock,
)

WINDOW = AudioTimeWindow(start_time_s=1.0, end_time_s=1.01, frame_index=7)


def _block(**overrides: object) -> MicrophoneSignalBlock:
    values: dict[str, object] = {
        "samples": np.zeros((2, 480), dtype=np.float64),
        "microphone_ids": ("left", "right"),
        "array_id": "rig",
        "sample_rate_hz": 48_000,
        "time_window": WINDOW,
        "channel_validity": (True, True),
        "producer_id": "capture",
        "provenance": "physical/capture",
    }
    values.update(overrides)
    return MicrophoneSignalBlock(**values)


def test_signal_block_has_the_minimal_public_boundary() -> None:
    source = np.asfortranarray(np.arange(960, dtype=np.float64).reshape(2, 480))
    block = _block(samples=source, channel_validity=(True, False))

    assert tuple(field.name for field in fields(MicrophoneSignalBlock)) == (
        "samples",
        "microphone_ids",
        "array_id",
        "sample_rate_hz",
        "time_window",
        "channel_validity",
        "producer_id",
        "provenance",
        "diagnostics",
    )
    assert block.samples.dtype == np.float32
    assert block.samples.flags.c_contiguous
    assert not block.samples.flags.writeable
    assert not np.shares_memory(block.samples, source)
    assert source.flags.writeable
    assert block.channel_validity == (True, False)
    assert block.time_window is WINDOW


def test_signal_block_accepts_a_fully_invalid_finite_window() -> None:
    block = _block(channel_validity=(False, False))

    assert block.channel_validity == (False, False)
    assert np.all(block.samples == 0.0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"samples": np.zeros(480)}, "shape"),
        ({"samples": np.zeros((1, 480))}, "microphone axis"),
        ({"samples": np.zeros((2, 479))}, "exact time window"),
        ({"samples": np.full((2, 480), np.nan)}, "finite"),
        ({"microphone_ids": ()}, "must not be empty"),
        ({"microphone_ids": ("left", "left")}, "unique"),
        ({"microphone_ids": ("left", "")}, "non-empty"),
        ({"channel_validity": (True,)}, "must match"),
        ({"channel_validity": (True, 1)}, "must be booleans"),
        ({"sample_rate_hz": True}, "positive integer"),
        ({"sample_rate_hz": 0}, "positive integer"),
        ({"array_id": ""}, "non-empty"),
        ({"producer_id": ""}, "non-empty"),
        ({"provenance": ""}, "non-empty"),
    ),
)
def test_signal_block_rejects_invalid_values(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _block(**overrides)


def test_signal_block_requires_a_typed_time_window() -> None:
    with pytest.raises(TypeError, match="AudioTimeWindow"):
        _block(time_window={"start_time_s": 1.0, "end_time_s": 1.01})
