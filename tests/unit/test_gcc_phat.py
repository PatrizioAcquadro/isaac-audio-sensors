from __future__ import annotations

import math

import numpy as np
import pytest

from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    relative_delays_from_tdoa_matrix,
)


@pytest.mark.parametrize("interp", [1, 8])
def test_pairwise_delays_match_known_arrivals_with_unequal_channel_lengths(interp):
    arrivals = {"front": 40, "left": 43, "rear": 47, "right": 45}
    waveforms = {}
    for index, (mic_id, arrival) in enumerate(arrivals.items()):
        waveform = np.zeros(256 + index * 32)
        waveform[arrival] = 1.0
        waveforms[mic_id] = waveform

    delays, peaks = estimate_tdoa_diagnostics(
        waveforms, sample_rate_hz=8_000, max_delay_s=0.01, interp=interp
    )

    for left, left_arrival in arrivals.items():
        for right, right_arrival in arrivals.items():
            key = f"{left}->{right}"
            assert delays[key] == pytest.approx((left_arrival - right_arrival) / 8_000)
            assert peaks[key] == peaks[f"{right}->{left}"]
    assert relative_delays_from_tdoa_matrix(
        delays, mic_ids=tuple(arrivals), reference_mic_id="front"
    ) == pytest.approx(
        {mic: (arrival - 40) / 8_000 for mic, arrival in arrivals.items()}
    )


def test_pairwise_gcc_phat_normalizes_mirrored_zero_delay():
    shared = np.random.default_rng(7).standard_normal(256)
    delays, _peaks = estimate_tdoa_diagnostics(
        {"a": shared, "b": shared.copy()},
        sample_rate_hz=8_000,
        max_delay_s=0.01,
        interp=1,
    )

    for key in ("a->b", "b->a"):
        assert delays[key] == 0.0
        assert math.copysign(1.0, delays[key]) > 0.0
