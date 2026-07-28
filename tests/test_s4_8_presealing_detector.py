from __future__ import annotations

from copy import deepcopy

import numpy as np

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    DEFAULT_GENERALIZED_DETECTOR_CONFIG,
    detect_authenticated_reference_activity,
)

RATE = 16_000
CAPTURE_SAMPLES = 20 * RATE
PLAYBACK_START = RATE
EVALUATION_START = int(1.25 * RATE)
EVALUATION_STOP = int(18.75 * RATE)
BACKGROUND_INTERVALS = ((0, RATE), (19 * RATE, 20 * RATE))


def _reference() -> np.ndarray:
    rng = np.random.default_rng(481)
    return rng.normal(0.0, 0.2, size=4_000)


def _fixture(
    *,
    occupancy: float = 1.0,
    amplitude: float = 0.04,
    diffuse_noise: float = 0.0005,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(482)
    reference = _reference()
    microphones = rng.normal(
        0.0,
        diffuse_noise,
        size=(4, CAPTURE_SAMPLES),
    )
    evaluation_samples = EVALUATION_STOP - EVALUATION_START
    active_samples = round(evaluation_samples * occupancy)
    active_stop = EVALUATION_START + active_samples
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (
            np.arange(EVALUATION_START, active_stop) - PLAYBACK_START - delay
        ) % reference.size
        microphones[channel, EVALUATION_START:active_stop] += (
            amplitude * reference[indices]
        )
    return microphones, reference


def _detect(
    microphones: np.ndarray,
    reference: np.ndarray,
) -> dict[str, object]:
    return detect_authenticated_reference_activity(
        microphones,
        reference,
        sample_rate_hz=RATE,
        playback_start_sample=PLAYBACK_START,
        evaluation_start_sample=EVALUATION_START,
        evaluation_stop_sample=EVALUATION_STOP,
        background_intervals=BACKGROUND_INTERVALS,
        config=DEFAULT_GENERALIZED_DETECTOR_CONFIG,
    )


def test_generalized_detector_measures_zero_through_full_occupancy() -> None:
    measured = {}
    for occupancy in (0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 1.0):
        microphones, reference = _fixture(occupancy=occupancy)
        result = _detect(microphones, reference)
        measured[occupancy] = float(result["useful_sound_coverage"])

    for occupancy, coverage in measured.items():
        assert abs(coverage - occupancy) <= 0.025
    assert measured[0.90] >= 0.90
    assert measured[0.95] >= 0.95
    assert measured[1.0] == 1.0


def test_generalized_detector_rejects_silence_and_energetic_diffuse_noise() -> None:
    silent, reference = _fixture(occupancy=0.0, diffuse_noise=0.0)
    noisy, _ = _fixture(occupancy=0.0, diffuse_noise=0.04)

    silence_result = _detect(silent, reference)
    noise_result = _detect(noisy, reference)

    assert silence_result["useful_block_count"] == 0
    assert noise_result["useful_block_count"] == 0
    assert noise_result["exclusion_reason_counts"]["reference_correlation"] > 0


def test_generalized_detector_reports_exact_gap_grid_and_transitions() -> None:
    for gap_s in (0.125, 0.25, 0.5, 0.75, 1.0):
        microphones, reference = _fixture()
        start = 9 * RATE
        stop = start + round(gap_s * RATE)
        microphones[:, start:stop] = 0.0

        result = _detect(microphones, reference)

        assert any(
            abs(float(interval["duration_s"]) - gap_s) <= 0.125
            for interval in result["non_applicable_intervals"]
        )
        assert result["first_useful_interval"]["start_s"] == 1.25
        assert result["last_useful_interval"]["end_s"] == 18.75


def test_generalized_detector_handles_volume_snr_and_diffuse_noise() -> None:
    cases = (
        (0.08, 0.0005),
        (0.02, 0.002),
        (0.012, 0.003),
    )
    for amplitude, diffuse_noise in cases:
        microphones, reference = _fixture(
            amplitude=amplitude,
            diffuse_noise=diffuse_noise,
        )
        result = _detect(microphones, reference)
        assert result["useful_sound_coverage"] >= 0.90


def test_generalized_detector_excludes_short_coherent_events() -> None:
    microphones, reference = _fixture(occupancy=0.0)
    event_start = 10 * RATE
    event_stop = event_start + int(0.75 * RATE)
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (
            np.arange(event_start, event_stop) - PLAYBACK_START - delay
        ) % reference.size
        microphones[channel, event_start:event_stop] += 0.04 * reference[indices]

    result = _detect(microphones, reference)

    assert result["candidate_block_count"] > 0
    assert result["useful_block_count"] == 0
    assert result["exclusion_reason_counts"]["insufficient_continuity"] > 0


def test_generalized_detector_accepts_stable_moderate_coherence() -> None:
    microphones, reference = _fixture(amplitude=0.012, diffuse_noise=0.004)

    result = _detect(microphones, reference)

    assert result["useful_sound_coverage"] >= 0.90
    assert result["median_reference_correlation"] >= 0.20


def test_generalized_detector_ignores_forbidden_outcome_like_fields() -> None:
    microphones, reference = _fixture()
    first = _detect(microphones, reference)
    changed = deepcopy(first)
    changed["confidence"] = 0.0
    changed["bearing_error"] = 180.0
    changed["criterion_outcomes"] = ["failed"]

    second = _detect(microphones, reference)

    assert second == first
    assert not {
        "confidence",
        "bearing",
        "target",
        "criterion",
        "accuracy",
        "tdoa",
    } & set(DEFAULT_GENERALIZED_DETECTOR_CONFIG)
