from __future__ import annotations

import hashlib
import json
import wave
from copy import deepcopy
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    CONFIG_PATH,
    CONFIG_SCHEMA_PATH,
    DEFAULT_PRESEALING_CONFIG,
    REPORT_SCHEMA_PATH,
    array_sha256,
    build_authenticated_process_record,
    evaluate_presealing_gate,
    load_presealing_config,
    require_presealing_pass,
    run_presealing_gate_from_files,
    validate_presealing_report,
)

RATE = 16_000
ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = Path("docs/development/specs/s4_8_presealing_gate.md")


def _reference() -> np.ndarray:
    return np.random.default_rng(483).normal(0.0, 0.2, size=4_000)


def _capture(
    reference: np.ndarray,
    *,
    amplitude: float = 0.04,
    noise: float = 0.0005,
) -> np.ndarray:
    rng = np.random.default_rng(484)
    capture = np.zeros((20 * RATE, 6), dtype=np.float64)
    microphones = rng.normal(0.0, noise, size=(4, 20 * RATE))
    start = RATE
    stop = 19 * RATE
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (np.arange(start, stop) - start - delay) % reference.size
        microphones[channel, start:stop] += amplitude * reference[indices]
    capture[:, 2:6] = microphones.T
    return capture


def _record(
    capture: np.ndarray,
    reference: np.ndarray,
    **changes: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "capture_sha256": array_sha256(capture),
        "reference_sha256": array_sha256(reference),
        "capture_started_monotonic_ns": 1_000_000_000,
        "recorder_ready_monotonic_ns": 1_050_000_000,
        "playback_started_monotonic_ns": 2_000_000_000,
        "planned_playback_stop_monotonic_ns": 20_000_000_000,
        "playback_stopped_monotonic_ns": 20_010_000_000,
        "capture_stopped_monotonic_ns": 21_000_000_000,
        "recorder_started": True,
        "recorder_exit_status": 0,
        "producer_status": "complete",
        "playback_loop_enabled": True,
        "playback_exit_status": 0,
    }
    values.update(changes)
    return build_authenticated_process_record(**values)


def _gate(
    capture: np.ndarray,
    reference: np.ndarray,
    *,
    record: dict[str, object] | None = None,
) -> dict[str, object]:
    return evaluate_presealing_gate(
        capture,
        reference,
        sample_rate_hz=RATE,
        process_record=record or _record(capture, reference),
        expected_reference_sha256=array_sha256(reference),
        config=DEFAULT_PRESEALING_CONFIG,
        dry_run=True,
    )


def _reason_codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["reasons"]}


def test_valid_non_holdout_fixture_passes_complete_dry_run_gate() -> None:
    reference = _reference()
    capture = _capture(reference)

    report = _gate(capture, reference)

    assert report["decision"] == "PASS"
    assert report["reasons"] == []
    assert report["counts"]["evaluation_block_count"] == 140
    assert report["metrics"]["useful_sound_coverage"] == 1.0
    assert report["metrics"]["longest_continuous_useful_s"] == 17.5
    assert report["metrics"]["maximum_non_applicable_gap_s"] == 0.0
    assert report["dry_run"] is True
    assert report["authority"] == {
        "creates_grant": False,
        "consumes_grant": False,
        "official_state_machine": False,
        "publishes_official_evidence": False,
        "seals_take": False,
    }


@pytest.mark.parametrize("edge", ["beginning", "end"])
def test_removed_playback_edge_requires_retry(edge: str) -> None:
    reference = _reference()
    capture = _capture(reference)
    if edge == "beginning":
        capture[int(1.25 * RATE) : 2 * RATE, 2:6] = 0.0
    else:
        capture[18 * RATE : int(18.75 * RATE), 2:6] = 0.0

    report = _gate(capture, reference)

    assert report["decision"] == "RETRY_REQUIRED"
    assert "non_applicable_gap_too_long" in _reason_codes(report)


@pytest.mark.parametrize("gap_s", [0.125, 0.25, 0.5, 0.75, 1.0])
def test_internal_playback_gaps_are_detected_and_rejected(gap_s: float) -> None:
    reference = _reference()
    capture = _capture(reference)
    start = 9 * RATE
    capture[start : start + round(gap_s * RATE), 2:6] = 0.0

    report = _gate(capture, reference)

    assert report["decision"] == "RETRY_REQUIRED"
    assert "continuous_useful_interval_too_short" in _reason_codes(report)
    if gap_s > 0.5:
        assert "non_applicable_gap_too_long" in _reason_codes(report)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("silence", "reference_stimulus_missing"),
        ("diffuse_noise", "reference_stimulus_missing"),
        ("volume_drop", "continuous_useful_interval_too_short"),
        ("weak_channel", "channel_gain_imbalance"),
        ("unequal_gains", "channel_gain_imbalance"),
        ("polarity_inversion", "channel_polarity_inversion"),
        ("clipping", "clipping_limit_exceeded"),
        ("premature_termination", "playback_stopped_early"),
    ],
)
def test_waveform_fault_matrix_requires_retry(
    mutation: str,
    expected_reason: str,
) -> None:
    reference = _reference()
    capture = _capture(reference)
    record_changes: dict[str, object] = {}
    if mutation == "silence":
        capture[:, 2:6] = 0.0
    elif mutation == "diffuse_noise":
        capture[:, 2:6] = np.random.default_rng(485).normal(
            0.0,
            0.04,
            size=(20 * RATE, 4),
        )
    elif mutation == "volume_drop":
        capture[9 * RATE : 19 * RATE, 2:6] *= 0.01
    elif mutation == "weak_channel":
        capture[:, 2] *= 0.01
    elif mutation == "unequal_gains":
        capture[:, 2:6] *= np.asarray([0.25, 0.5, 1.0, 1.5])
    elif mutation == "polarity_inversion":
        capture[:, 3] *= -1.0
    elif mutation == "clipping":
        capture[10 * RATE : 10 * RATE + 16, 2] = -1.0
    elif mutation == "premature_termination":
        capture[17 * RATE : 19 * RATE, 2:6] = 0.0
        record_changes["playback_stopped_monotonic_ns"] = 18_000_000_000
    record = _record(capture, reference, **record_changes)

    report = _gate(capture, reference, record=record)

    assert report["decision"] == "RETRY_REQUIRED"
    assert expected_reason in _reason_codes(report)


@pytest.mark.parametrize(
    ("record_changes", "expected_reason"),
    [
        (
            {"playback_started_monotonic_ns": 2_250_000_000},
            "playback_start_outside_tolerance",
        ),
        ({"playback_exit_status": 1}, "playback_process_failed"),
        ({"recorder_started": False}, "recorder_not_started"),
        ({"producer_status": "failed"}, "producer_incomplete"),
        ({"playback_loop_enabled": False}, "continuous_loop_not_confirmed"),
    ],
)
def test_process_fault_matrix_requires_retry(
    record_changes: dict[str, object],
    expected_reason: str,
) -> None:
    reference = _reference()
    capture = _capture(reference)
    record = _record(capture, reference, **record_changes)

    report = _gate(capture, reference, record=record)

    assert report["decision"] == "RETRY_REQUIRED"
    assert expected_reason in _reason_codes(report)


def test_wrong_reference_hash_and_process_record_tampering_fail_closed() -> None:
    reference = _reference()
    capture = _capture(reference)
    record = _record(capture, reference)
    wrong_hash = "f" * 64

    wrong_reference = evaluate_presealing_gate(
        capture,
        reference,
        sample_rate_hz=RATE,
        process_record=record,
        expected_reference_sha256=wrong_hash,
        config=DEFAULT_PRESEALING_CONFIG,
        dry_run=True,
    )
    tampered_record = deepcopy(record)
    tampered_record["playback_started_monotonic_ns"] = 2_250_000_000
    tampered = _gate(capture, reference, record=tampered_record)

    assert wrong_reference["decision"] == "RETRY_REQUIRED"
    assert "reference_hash_mismatch" in _reason_codes(wrong_reference)
    assert tampered["decision"] == "RETRY_REQUIRED"
    assert "process_record_authentication_failed" in _reason_codes(tampered)


def test_gate_rejects_capture_hash_rate_channel_and_duration_defects() -> None:
    reference = _reference()
    capture = _capture(reference)
    record = _record(capture, reference)

    wrong_capture_hash = deepcopy(record)
    wrong_capture_hash["capture_sha256"] = "e" * 64
    wrong_capture_hash = build_authenticated_process_record(
        **{
            key: value
            for key, value in wrong_capture_hash.items()
            if key not in {"schema", "record_sha256"}
        }
    )
    bad_hash_report = _gate(capture, reference, record=wrong_capture_hash)
    bad_rate_report = evaluate_presealing_gate(
        capture,
        reference,
        sample_rate_hz=8_000,
        process_record=record,
        expected_reference_sha256=array_sha256(reference),
        config=DEFAULT_PRESEALING_CONFIG,
        dry_run=True,
    )
    bad_channels_report = _gate(capture[:, :5], reference)
    bad_duration_report = _gate(capture[:-RATE], reference)

    assert "capture_hash_mismatch" in _reason_codes(bad_hash_report)
    assert "sample_rate_mismatch" in _reason_codes(bad_rate_report)
    assert "channel_count_mismatch" in _reason_codes(bad_channels_report)
    assert "duration_mismatch" in _reason_codes(bad_duration_report)


def test_retry_decision_has_no_scientific_performance_inputs() -> None:
    reference = _reference()
    capture = _capture(reference)

    report = _gate(capture, reference)

    forbidden = {
        "bearing_error",
        "sector_accuracy",
        "final_confidence",
        "tdoa_accuracy",
        "acceptance_results",
        "criterion_outcomes",
    }
    assert forbidden.isdisjoint(report["input_provenance"])
    assert report["decision_basis"] == [
        "integrity",
        "playback_presence",
        "continuity",
        "coverage",
        "clipping",
        "channel_health",
    ]


def test_tracked_configuration_and_report_are_schema_valid() -> None:
    raw = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    config_schema = json.loads((ROOT / CONFIG_SCHEMA_PATH).read_text(encoding="utf-8"))
    report_schema = json.loads((ROOT / REPORT_SCHEMA_PATH).read_text(encoding="utf-8"))
    reference = _reference()
    report = _gate(_capture(reference), reference)

    jsonschema.validate(raw, config_schema)
    jsonschema.validate(report, report_schema)
    validate_presealing_report(report, repo_root=ROOT)
    assert load_presealing_config(ROOT) == DEFAULT_PRESEALING_CONFIG
    serialized = json.dumps(raw, sort_keys=True)
    for forbidden in (
        "take_id",
        "cell",
        "target_bearing",
        "confidence",
        "bearing_error",
        "sector_accuracy",
        "tdoa_accuracy",
        "criterion_outcome",
    ):
        assert forbidden not in serialized


def _write_pcm16(path: Path, samples: np.ndarray, channel_count: int) -> None:
    clipped = np.clip(samples, -1.0, 32767.0 / 32768.0)
    encoded = np.rint(clipped * 32768.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channel_count)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(encoded.tobytes())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_file_dry_run_authenticates_exact_wav_and_process_record(
    tmp_path: Path,
) -> None:
    reference = _reference()
    capture = _capture(reference)
    capture_path = tmp_path / "engineering_capture.wav"
    reference_path = tmp_path / "engineering_reference.wav"
    record_path = tmp_path / "process_record.json"
    _write_pcm16(capture_path, capture, 6)
    _write_pcm16(reference_path, reference[:, None], 1)
    record = _record(capture, reference)
    record = build_authenticated_process_record(
        **{
            **{
                key: value
                for key, value in record.items()
                if key
                not in {
                    "schema",
                    "record_sha256",
                    "capture_sha256",
                    "reference_sha256",
                }
            },
            "capture_sha256": _file_sha256(capture_path),
            "reference_sha256": _file_sha256(reference_path),
        }
    )
    record_path.write_text(json.dumps(record), encoding="utf-8")

    report = run_presealing_gate_from_files(
        capture_wav_path=capture_path,
        reference_wav_path=reference_path,
        process_record_path=record_path,
        expected_reference_sha256=_file_sha256(reference_path),
        repo_root=ROOT,
        dry_run=True,
    )

    assert report["decision"] == "PASS"
    assert report["dry_run"] is True
    assert report["input_provenance"]["capture_sha256"] == _file_sha256(capture_path)
    assert report["input_provenance"]["reference_sha256"] == _file_sha256(
        reference_path
    )


def test_presealing_spec_preserves_boundaries_and_exact_detector_rule() -> None:
    text = (ROOT / SPEC_PATH).read_text(encoding="utf-8")

    for required in (
        "separately versioned",
        "legacy detector remains reproducible",
        "authenticated pre-roll and post-roll",
        "exact looped reference",
        "90%",
        "16.0 s",
        "0.5 s",
        "PASS",
        "RETRY_REQUIRED",
        "dry-run",
        "no grant",
        "no official state-machine",
        "bearing error",
        "final confidence",
        "non-holdout",
        "physical rehearsal",
    ):
        assert required in text


def test_sealing_interlock_rejects_retry_and_binds_passing_report() -> None:
    reference = _reference()
    valid_capture = _capture(reference)
    valid_report = _gate(valid_capture, reference)
    invalid_capture = valid_capture.copy()
    invalid_capture[9 * RATE : 10 * RATE, 2:6] = 0.0
    invalid_report = _gate(invalid_capture, reference)

    clearance = require_presealing_pass(valid_report, repo_root=ROOT)

    assert clearance["status"] == "presealing_pass_required_before_seal"
    assert clearance["report_sha256"]
    assert clearance["capture_sha256"] == array_sha256(valid_capture)
    with pytest.raises(
        Exception,
        match="RETRY_REQUIRED cannot be sealed",
    ):
        require_presealing_pass(invalid_report, repo_root=ROOT)
