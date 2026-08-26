"""GCC-PHAT pairwise delay invariants."""

from __future__ import annotations

import math

import numpy as np
import pytest

from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    estimate_tdoa_matrix,
    gcc_phat_delay,
    relative_delays_from_tdoa_matrix,
)


def test_gcc_phat_delay_sign_and_relative_tdoa_matrix() -> None:
    sample_rate_hz = 8_000
    reference = np.zeros(256)
    delayed = np.zeros(256)
    reference[40] = 1.0
    delayed[45] = 1.0

    delay = gcc_phat_delay(
        delayed,
        reference,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=1,
    )
    matrix = estimate_tdoa_matrix(
        {"ref": reference, "late": delayed},
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=1,
    )

    expected_delay = 5.0 / sample_rate_hz
    assert delay.delay_s == pytest.approx(expected_delay)
    assert matrix["late->ref"] == pytest.approx(expected_delay)
    assert matrix["ref->late"] == pytest.approx(-expected_delay)
    assert relative_delays_from_tdoa_matrix(
        matrix,
        mic_ids=("ref", "late"),
        reference_mic_id="ref",
    ) == pytest.approx({"ref": 0.0, "late": expected_delay})


def test_pairwise_gcc_phat_matches_per_pair_reference() -> None:
    sample_rate_hz = 8_000
    rng = np.random.default_rng(1234)
    waveforms = {
        "front": rng.standard_normal(512),
        "left": np.roll(rng.standard_normal(512), 3),
        "rear": rng.standard_normal(480),
        "right": rng.standard_normal(640),
    }

    delays, peaks = estimate_tdoa_diagnostics(
        waveforms,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=8,
    )
    matrix = estimate_tdoa_matrix(
        waveforms,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=8,
    )

    mic_ids = tuple(waveforms)
    expected_keys = {f"{left}->{right}" for left in mic_ids for right in mic_ids}
    assert set(delays) == expected_keys
    assert set(peaks) == expected_keys
    assert matrix == delays

    for left in mic_ids:
        for right in mic_ids:
            key = f"{left}->{right}"
            if left == right:
                assert delays[key] == 0.0
                assert peaks[key] == 1.0
                continue
            reference = gcc_phat_delay(
                waveforms[left],
                waveforms[right],
                sample_rate_hz=sample_rate_hz,
                max_delay_s=0.01,
                interp=8,
            )
            assert delays[key] == pytest.approx(reference.delay_s, abs=1e-12)
            assert peaks[key] == pytest.approx(reference.peak_value, abs=1e-12)


def test_pairwise_gcc_phat_normalizes_mirrored_zero_delay() -> None:
    rng = np.random.default_rng(7)
    shared = rng.standard_normal(256)
    matrix = estimate_tdoa_matrix(
        {"a": shared, "b": shared.copy()},
        sample_rate_hz=8_000,
        max_delay_s=0.01,
        interp=1,
    )

    assert matrix["a->b"] == 0.0
    assert matrix["b->a"] == 0.0
    assert math.copysign(1.0, matrix["a->b"]) > 0.0
    assert math.copysign(1.0, matrix["b->a"]) > 0.0
