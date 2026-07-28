from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import numpy as np

from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    DEFAULT_ALIGNMENT_CONFIG_V2,
    DEFAULT_PRESEALING_CONFIG_V2,
    PRESEALING_CONFIG_PATH_V2,
    PRESEALING_CONFIG_SCHEMA_PATH_V2,
    detect_tracked_reference_activity_v2,
    evaluate_presealing_waveform_v2,
    load_presealing_config_v2,
)

RATE = 16_000
PLAYBACK_START = RATE
PLAYBACK_STOP = 19 * RATE
EVALUATION_START = int(1.25 * RATE)
EVALUATION_STOP = int(18.75 * RATE)
BACKGROUND_INTERVALS = ((0, RATE), (PLAYBACK_STOP, 20 * RATE))
ROOT = Path(__file__).resolve().parents[1]


def _reference() -> np.ndarray:
    return np.random.default_rng(490).normal(0.0, 0.2, size=4_096)


def _capture(
    reference: np.ndarray,
    *,
    latency_samples: int = 0,
    drift_ppm: float = 0.0,
    room_ir: np.ndarray | None = None,
    phase_jump_sample: int | None = None,
    phase_jump_size: int = 0,
) -> np.ndarray:
    rng = np.random.default_rng(491)
    microphones = rng.normal(0.0, 0.0005, size=(4, 20 * RATE))
    acoustic_start = PLAYBACK_START + latency_samples
    sample_positions = np.arange(acoustic_start, PLAYBACK_STOP, dtype=np.float64)
    phase = (sample_positions - acoustic_start) * (1.0 + drift_ppm / 1_000_000.0)
    if phase_jump_sample is not None:
        phase[sample_positions >= phase_jump_sample] += phase_jump_size
    lower = np.floor(phase).astype(np.int64)
    fraction = phase - lower
    stimulus = (
        reference[lower % reference.size] * (1.0 - fraction)
        + reference[(lower + 1) % reference.size] * fraction
    )
    impulse = (
        np.asarray([1.0], dtype=np.float64)
        if room_ir is None
        else np.asarray(room_ir, dtype=np.float64)
    )
    for channel, delay in enumerate((0, 2, 4, 6)):
        filtered = np.convolve(stimulus, impulse, mode="full")[: stimulus.size]
        start = acoustic_start + delay
        stop = min(start + filtered.size, PLAYBACK_STOP)
        microphones[channel, start:stop] += 0.04 * filtered[: stop - start]
    return microphones


def _detect(
    microphones: np.ndarray,
    reference: np.ndarray,
) -> dict[str, object]:
    return detect_tracked_reference_activity_v2(
        microphones,
        reference,
        sample_rate_hz=RATE,
        process_playback_start_sample=PLAYBACK_START,
        planned_playback_stop_sample=PLAYBACK_STOP,
        evaluation_start_sample=EVALUATION_START,
        evaluation_stop_sample=EVALUATION_STOP,
        background_intervals=BACKGROUND_INTERVALS,
        config=DEFAULT_ALIGNMENT_CONFIG_V2,
    )


def test_v2_establishes_alignment_with_realistic_fixed_playback_latency() -> None:
    reference = _reference()
    latency_samples = round(0.080 * RATE)

    result = _detect(
        _capture(reference, latency_samples=latency_samples),
        reference,
    )

    assert result["alignment_status"] == "maintained"
    assert (
        abs(
            result["initial_acoustic_start_sample"] - (PLAYBACK_START + latency_samples)
        )
        <= 8
    )
    assert result["useful_sound_coverage"] >= 0.90


def test_v2_tracks_gradual_recorder_player_clock_drift() -> None:
    reference = _reference()

    result = _detect(
        _capture(reference, latency_samples=640, drift_ppm=350.0),
        reference,
    )

    assert result["alignment_status"] == "maintained"
    assert abs(result["estimated_drift_ppm"] - 350.0) <= 100.0
    assert result["useful_sound_coverage"] >= 0.90


def test_v2_tracks_small_resampling_difference() -> None:
    reference = _reference()

    result = _detect(
        _capture(reference, latency_samples=320, drift_ppm=-450.0),
        reference,
    )

    assert result["alignment_status"] == "maintained"
    assert abs(result["estimated_drift_ppm"] + 450.0) <= 120.0
    assert result["useful_sound_coverage"] >= 0.90


def test_v2_accepts_room_filtering_and_reverberation() -> None:
    reference = _reference()
    room_ir = np.asarray([1.0, 0.55, 0.30, 0.16, 0.08])

    result = _detect(
        _capture(
            reference,
            latency_samples=960,
            drift_ppm=120.0,
            room_ir=room_ir,
        ),
        reference,
    )

    assert result["alignment_status"] == "maintained"
    assert result["median_reference_correlation"] >= 0.20
    assert result["useful_sound_coverage"] >= 0.90


def test_v2_rejects_abrupt_phase_discontinuity() -> None:
    reference = _reference()

    result = _detect(
        _capture(
            reference,
            latency_samples=640,
            phase_jump_sample=10 * RATE,
            phase_jump_size=256,
        ),
        reference,
    )

    assert result["alignment_status"] == "failed"
    assert "phase_discontinuity" in result["alignment_failure_reasons"]


def _reason_codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["reasons"]}


def test_v2_gate_rejects_missing_first_250_ms_despite_successful_process() -> None:
    reference = _reference()
    microphones = _capture(reference)
    microphones[:, PLAYBACK_START:EVALUATION_START] = 0.0

    report = evaluate_presealing_waveform_v2(
        microphones,
        reference,
        sample_rate_hz=RATE,
        process_playback_start_sample=PLAYBACK_START,
        planned_playback_stop_sample=PLAYBACK_STOP,
        evaluation_start_sample=EVALUATION_START,
        evaluation_stop_sample=EVALUATION_STOP,
        background_intervals=BACKGROUND_INTERVALS,
        config=DEFAULT_ALIGNMENT_CONFIG_V2,
    )

    assert report["decision"] == "RETRY_REQUIRED"
    assert "acoustic_playback_started_late" in _reason_codes(report)


def test_v2_gate_rejects_missing_final_250_ms_despite_successful_process() -> None:
    reference = _reference()
    microphones = _capture(reference)
    microphones[:, EVALUATION_STOP:PLAYBACK_STOP] = 0.0

    report = evaluate_presealing_waveform_v2(
        microphones,
        reference,
        sample_rate_hz=RATE,
        process_playback_start_sample=PLAYBACK_START,
        planned_playback_stop_sample=PLAYBACK_STOP,
        evaluation_start_sample=EVALUATION_START,
        evaluation_stop_sample=EVALUATION_STOP,
        background_intervals=BACKGROUND_INTERVALS,
        config=DEFAULT_ALIGNMENT_CONFIG_V2,
    )

    assert report["decision"] == "RETRY_REQUIRED"
    assert "acoustic_playback_stopped_early" in _reason_codes(report)


def test_v2_gate_rejects_whole_loop_acoustic_start_delay() -> None:
    reference = _reference()

    report = evaluate_presealing_waveform_v2(
        _capture(reference, latency_samples=reference.size),
        reference,
        sample_rate_hz=RATE,
        process_playback_start_sample=PLAYBACK_START,
        planned_playback_stop_sample=PLAYBACK_STOP,
        evaluation_start_sample=EVALUATION_START,
        evaluation_stop_sample=EVALUATION_STOP,
        background_intervals=BACKGROUND_INTERVALS,
        config=DEFAULT_ALIGNMENT_CONFIG_V2,
    )

    assert report["decision"] == "RETRY_REQUIRED"
    assert "acoustic_playback_started_late" in _reason_codes(report)


def test_v2_alignment_limits_are_tracked_schema_valid_and_outcome_independent() -> None:
    raw = json.loads((ROOT / PRESEALING_CONFIG_PATH_V2).read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / PRESEALING_CONFIG_SCHEMA_PATH_V2).read_text(encoding="utf-8")
    )

    jsonschema.validate(raw, schema)
    assert load_presealing_config_v2(ROOT) == DEFAULT_PRESEALING_CONFIG_V2
    assert raw["detector"] == DEFAULT_ALIGNMENT_CONFIG_V2
    serialized = json.dumps(raw, sort_keys=True)
    for forbidden in (
        "take_id",
        "cell",
        "bearing",
        "confidence",
        "accuracy",
        "tdoa",
        "criterion",
    ):
        assert forbidden not in serialized
