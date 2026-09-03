from __future__ import annotations

import math

import auditok
import numpy as np
import pytest

from isaac_audio_sensors.core.plugins import AuditokActivityDetector
from isaac_audio_sensors.core.plugins.auditok import (
    _AUDITOK_REFERENCE_DB,
    _float32_interleaved_bytes,
)

SAMPLE_RATE_HZ = 1_000
WINDOW_S = 0.01
WINDOW_SAMPLES = 10


def _samples(amplitude: float, *, channels: int = 1) -> np.ndarray:
    return np.full(
        (channels, WINDOW_SAMPLES),
        amplitude,
        dtype=np.float32,
    )


def _detector(
    *,
    min_activity_s: float = WINDOW_S,
    max_silence_s: float = 0.0,
) -> AuditokActivityDetector:
    return AuditokActivityDetector(
        energy_threshold_dbfs=-20.0,
        analysis_window_s=WINDOW_S,
        min_activity_s=min_activity_s,
        max_silence_s=max_silence_s,
    )


def _candidate_calibration_threshold_dbfs(samples: np.ndarray) -> float:
    payload = _float32_interleaved_bytes(samples)
    energies = auditok.signal.compute_frame_energies(
        payload,
        4,
        samples.shape[0],
        WINDOW_SAMPLES,
        use_channel="any",
    )
    estimate = auditok.signal.estimate_energy_threshold(
        energies,
        method="percentile",
        percentile=10.0,
        margin=6.0,
    )
    floor = -50.0 + _AUDITOK_REFERENCE_DB
    return max(estimate, floor) - _AUDITOK_REFERENCE_DB


def test_float32_bytes_round_trip_preserves_scale_order_and_strides() -> None:
    source = np.array(
        [
            [0.0, 99.0, 0.25, 99.0, -0.5, 99.0],
            [1.0, 99.0, -1.0, 99.0, 0.125, 99.0],
        ],
        dtype=np.float64,
    )[:, ::2]
    assert not source.flags.c_contiguous

    payload = _float32_interleaved_bytes(source)
    restored = auditok.signal.to_array(payload, 4, 2)

    assert len(payload) == source.size * 4
    np.testing.assert_array_equal(
        restored,
        source.astype(np.float32).astype(np.float64) * 32768.0,
    )


def test_threshold_and_diagnostics_use_ias_dbfs_scale() -> None:
    detector = _detector()

    decision = detector.detect(_samples(0.1), SAMPLE_RATE_HZ)

    assert decision.active is True
    assert decision.activity_probability is None
    assert decision.diagnostics["profile"] == "fixed_threshold"
    assert decision.diagnostics["auditok_version"] == "0.5.2"
    assert decision.diagnostics["threshold_dbfs"] == -20.0
    assert decision.diagnostics["energy_dbfs"] == pytest.approx(-20.0, abs=1e-5)
    assert decision.diagnostics["margin_db"] == pytest.approx(0.0, abs=1e-5)


def test_current_block_is_causal_and_uses_bounded_past_context() -> None:
    detector = _detector(min_activity_s=0.02, max_silence_s=0.01)

    assert detector.detect(_samples(0.2), SAMPLE_RATE_HZ).active is False
    assert detector.detect(_samples(0.2), SAMPLE_RATE_HZ).active is True
    assert detector.detect(_samples(0.0), SAMPLE_RATE_HZ).active is True
    assert detector.detect(_samples(0.0), SAMPLE_RATE_HZ).active is False


def test_any_channel_policy_does_not_cancel_antiphase_activity() -> None:
    detector = _detector()
    samples = np.stack(
        (
            np.full(WINDOW_SAMPLES, 0.2, dtype=np.float32),
            np.full(WINDOW_SAMPLES, -0.2, dtype=np.float32),
        )
    )

    decision = detector.detect(samples, SAMPLE_RATE_HZ)

    assert decision.active is True
    assert decision.diagnostics["channel_policy"] == "any"


def test_reset_matches_fresh_instance_and_allows_new_layout() -> None:
    detector = _detector(min_activity_s=0.02)
    detector.detect(_samples(0.2), SAMPLE_RATE_HZ)
    detector.reset()

    after_reset = detector.detect(_samples(0.0, channels=2), 2_000)
    fresh = _detector(min_activity_s=0.02).detect(
        _samples(0.0, channels=2),
        2_000,
    )

    assert after_reset == fresh


def test_layout_changes_fail_until_reset() -> None:
    detector = _detector()
    detector.detect(_samples(0.0), SAMPLE_RATE_HZ)

    with pytest.raises(ValueError, match="unchanged until reset"):
        detector.detect(_samples(0.0), SAMPLE_RATE_HZ * 2)
    with pytest.raises(ValueError, match="unchanged until reset"):
        detector.detect(_samples(0.0, channels=2), SAMPLE_RATE_HZ)


def test_repeated_streams_are_deterministic() -> None:
    stream = (
        _samples(0.0),
        _samples(0.2),
        _samples(0.2),
        _samples(0.0),
        _samples(0.0),
    )
    first = _detector(min_activity_s=0.02, max_silence_s=0.01)
    second = _detector(min_activity_s=0.02, max_silence_s=0.01)

    first_results = tuple(first.detect(block, SAMPLE_RATE_HZ) for block in stream)
    second_results = tuple(second.detect(block, SAMPLE_RATE_HZ) for block in stream)

    assert first_results == second_results


def test_retained_history_does_not_alias_the_caller_buffer() -> None:
    detector = _detector(min_activity_s=0.02)
    first = _samples(0.2)
    assert detector.detect(first, SAMPLE_RATE_HZ).active is False
    first.fill(0.0)

    assert detector.detect(_samples(0.2), SAMPLE_RATE_HZ).active is True


@pytest.mark.parametrize(
    ("samples", "sample_rate_hz", "message"),
    (
        (np.empty((1, 0)), SAMPLE_RATE_HZ, "shape"),
        (np.zeros((1, 2, 3)), SAMPLE_RATE_HZ, "shape"),
        (np.array([[math.nan]]), SAMPLE_RATE_HZ, "finite"),
        (np.array([[1e300]]), SAMPLE_RATE_HZ, "finite float32"),
        (np.zeros((1, 1)), 0, "positive integer"),
        (np.zeros((1, 1)), 1.5, "positive integer"),
    ),
)
def test_invalid_signal_inputs_fail_closed(
    samples: np.ndarray,
    sample_rate_hz: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _detector().detect(samples, sample_rate_hz)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"energy_threshold_dbfs": math.nan}, "energy_threshold_dbfs"),
        (
            {"energy_threshold_dbfs": -20.0, "analysis_window_s": 0.0},
            "analysis_window_s",
        ),
        (
            {"energy_threshold_dbfs": -20.0, "min_activity_s": -1.0},
            "min_activity_s",
        ),
        (
            {"energy_threshold_dbfs": -20.0, "max_silence_s": -1.0},
            "max_silence_s",
        ),
    ),
)
def test_invalid_detector_configuration_fails_closed(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        AuditokActivityDetector(**kwargs)


def test_initial_calibration_candidate_remains_an_explicit_pre_stream_step() -> None:
    quiet = np.tile(
        np.array([0.0005, 0.001, 0.002, 0.001], dtype=np.float32),
        750,
    )[None, :]
    contaminated = quiet.copy()
    contaminated[:, : 29 * quiet.shape[1] // 30] = 0.2

    quiet_threshold = _candidate_calibration_threshold_dbfs(quiet)
    contaminated_threshold = _candidate_calibration_threshold_dbfs(contaminated)

    assert quiet_threshold >= -50.0
    assert contaminated_threshold > quiet_threshold
    assert _detector().detect(_samples(0.011), SAMPLE_RATE_HZ).active is False


def test_short_impulse_is_an_operating_limit_not_a_qualification_failure() -> None:
    detector = _detector(min_activity_s=0.02, max_silence_s=0.0)

    impulse = detector.detect(_samples(0.2), SAMPLE_RATE_HZ)
    following_silence = detector.detect(_samples(0.0), SAMPLE_RATE_HZ)

    assert impulse.active is False
    assert following_silence.active is False
