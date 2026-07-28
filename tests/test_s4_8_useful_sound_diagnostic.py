from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from isaac_audio_sensors.acquisition.s4_8_useful_sound_diagnostic import (
    CONFIG_PATH,
    DEFAULT_DETECTOR_CONFIG,
    DIAGNOSTIC_PAYLOAD_SCHEMA,
    DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA,
    SCHEMA_PATH,
    aggregate_useful_sound_take,
    detect_useful_sound_windows,
    evaluate_useful_sound_scientific_payload,
    load_diagnostic_config,
    validate_diagnostic_payload,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = Path(
    "docs/development/specs/s4_8_useful_sound_diagnostic.md"
)


def _window(
    index: int,
    *,
    rms: float = 0.004,
    coherence: float = 0.02,
    confidence: float = 0.0,
    bearing: float | None = None,
) -> dict[str, float | int | None]:
    return {
        "window_index": index,
        "start_sample": index * 2000,
        "rms_median": rms,
        "srp_coherence": coherence,
        "confidence": confidence,
        "srp_bearing_deg_f_project": bearing,
    }


def _continuous_fixture(
    *,
    useful_start: int = 40,
) -> list[dict[str, float | int | None]]:
    windows = [_window(index) for index in range(80)]
    for index in range(useful_start, useful_start + 16):
        windows[index]["srp_coherence"] = 0.065
        windows[index]["confidence"] = 0.05
        windows[index]["srp_bearing_deg_f_project"] = 90.0
    return windows


def test_detector_finds_sound_without_identity_or_target() -> None:
    result = detect_useful_sound_windows(
        _continuous_fixture(),
        config=DEFAULT_DETECTOR_CONFIG,
    )

    assert result["applicable_window_indices"] == list(range(40, 56))
    assert result["applicable_window_count"] == 16
    assert result["non_applicable_window_count"] == 64
    assert result["longest_continuous_interval"] == {
        "first_window_index": 40,
        "last_window_index": 55,
        "start_sample": 80000,
        "end_sample": 114000,
        "duration_s": 2.125,
        "window_count": 16,
    }


def test_detector_excludes_loud_non_directional_and_isolated_coherent_energy() -> None:
    windows = [_window(index) for index in range(80)]
    for index in range(20, 36):
        windows[index]["rms_median"] = 0.04
    windows[50]["srp_coherence"] = 0.08

    result = detect_useful_sound_windows(
        windows,
        config=DEFAULT_DETECTOR_CONFIG,
    )

    assert result["applicable_window_count"] == 0
    assert result["exclusion_reason_counts"] == {
        "insufficient_directional_coherence": 79,
        "insufficient_directional_continuity": 1,
    }


def test_detector_is_independent_of_confidence_bearing_and_window_position() -> None:
    first = _continuous_fixture(useful_start=12)
    changed_outputs = deepcopy(first)
    for window in changed_outputs:
        window["confidence"] = 1.0 - float(window["confidence"])
        window["srp_bearing_deg_f_project"] = (
            None
            if window["srp_bearing_deg_f_project"] is not None
            else 271.0
        )

    left = detect_useful_sound_windows(first, config=DEFAULT_DETECTOR_CONFIG)
    right = detect_useful_sound_windows(
        changed_outputs,
        config=DEFAULT_DETECTOR_CONFIG,
    )

    assert left["applicable_window_indices"] == list(range(12, 28))
    assert right["applicable_window_indices"] == left["applicable_window_indices"]
    assert right["coherence_threshold"] == left["coherence_threshold"]


def test_detector_requires_basic_energy_and_consecutive_window_contract() -> None:
    windows = _continuous_fixture()
    windows[45]["rms_median"] = 0.001

    result = detect_useful_sound_windows(
        windows,
        config=DEFAULT_DETECTOR_CONFIG,
    )

    assert result["applicable_window_indices"] == list(range(46, 56))
    assert result["exclusion_reason_counts"]["below_basic_rms_floor"] == 1


def test_useful_take_aggregation_excludes_non_applicable_and_abstained_tdoa() -> None:
    pair_ids = [
        f"raw_microphone_{left}->raw_microphone_{right}"
        for left in range(4)
        for right in range(left + 1, 4)
    ]
    identity = SimpleNamespace(
        planned_take_id="synthetic_take",
        stratum_id="A_controlled_boundary_sweep",
        target_bearing_deg_f_project=0.0,
    )
    base_take = {
        "tdoa": [
            {
                "pair_id": pair_id,
                "tdoa_us": 0.0,
                "reference_tdoa_us": 0.0,
                "absolute_error_us": 0.0,
            }
            for pair_id in pair_ids
        ],
        "confidence": None,
    }
    analyzed = []
    for index in range(12):
        abstained = index == 4
        measured_us = 500.0 if abstained or index >= 10 else 10.0
        analyzed.append(
            {
                "record": {
                    "window_id": f"window_{index:03d}",
                    "window_index": index,
                    "start_sample": index * 2000,
                    "abstained": abstained,
                    "srp_bearing_deg_f_project": None if abstained else 2.0,
                    "sub_floor_direction_emitted": False,
                },
                "confidence": 0.0 if abstained else 0.05,
                "tdoa_s": dict.fromkeys(pair_ids, measured_us / 1_000_000.0),
            }
        )

    result = aggregate_useful_sound_take(
        base_take,
        identity=identity,
        analyzed_windows=analyzed,
        applicable_window_indices=list(range(10)),
    )

    assert result["window_summary"] == {
        "source_window_count": 10,
        "abstained_window_count": 1,
        "sub_floor_direction_emission_count": 0,
    }
    assert result["estimated_bearing_deg_f_project"] == 2.0
    assert result["bearing_absolute_error_deg"] == 2.0
    assert {item["tdoa_us"] for item in result["tdoa"]} == {10.0}
    assert len(result["bearing_windows"]) == 10


def test_isolated_evaluator_uses_all_frozen_criteria_and_thresholds() -> None:
    payload = build_synthetic_payload(ROOT)
    payload["schema"] = DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA
    for take in payload["takes"]:
        if take["identity"]["stratum_id"] not in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
        }:
            continue
        take["bearing_windows"] = take["bearing_windows"][:16]
        take["window_summary"] = {
            "source_window_count": 16,
            "abstained_window_count": 0,
            "sub_floor_direction_emission_count": 0,
        }

    result = evaluate_useful_sound_scientific_payload(payload, repo_root=ROOT)

    assert result["reused_holdout"] is True
    assert result["diagnostic_only"] is True
    assert result["criteria_thresholds_unchanged"] is True
    assert result["readiness_passed"] is True
    assert len(result["criteria"]) == 29
    assert sum(item["gating"] for item in result["criteria"]) == 23


def test_diagnostic_delegation_preserves_median_window_error_semantics() -> None:
    payload = build_synthetic_payload(ROOT)
    payload["schema"] = DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA
    changed = False
    for take in payload["takes"]:
        if take["identity"]["stratum_id"] not in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
        }:
            continue
        take["bearing_windows"] = take["bearing_windows"][:16]
        take["window_summary"] = {
            "source_window_count": 16,
            "abstained_window_count": 0,
            "sub_floor_direction_emission_count": 0,
        }
        if (
            not changed
            and take["identity"]["stratum_id"]
            == "A_controlled_boundary_sweep"
        ):
            target = float(take["identity"]["target_bearing_deg_f_project"])
            for index, window in enumerate(take["bearing_windows"]):
                window["srp_bearing_deg_f_project"] = (
                    target + (-10.0 if index < 8 else 10.0)
                ) % 360.0
            take["bearing_absolute_error_deg"] = 10.0
            take["estimated_bearing_deg_f_project"] = target
            take["candidate_bearings_deg_f_project"] = [target]
            take["candidate_covered"] = True
            changed = True

    result = evaluate_useful_sound_scientific_payload(payload, repo_root=ROOT)

    criterion = next(
        item
        for item in result["criteria"]
        if item["criterion_id"] == "bearing_median_absolute_error_stratum_a"
    )
    assert criterion["status"] == "evaluated"
    assert len(result["criteria"]) == 29


def test_diagnostic_contract_is_general_schema_valid_and_non_authoritative() -> None:
    raw = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    schema = json.loads((ROOT / SCHEMA_PATH).read_text(encoding="utf-8"))

    jsonschema.validate(raw, schema)
    loaded = load_diagnostic_config(ROOT)

    assert loaded == raw
    assert loaded["detector"] == DEFAULT_DETECTOR_CONFIG
    assert loaded["reused_holdout"] is True
    assert loaded["diagnostic_only"] is True
    assert loaded["authority"] == {
        "creates_grant": False,
        "consumes_grant": False,
        "official_state_machine": False,
        "publishes_official_evidence": False,
    }
    serialized = json.dumps(loaded["detector"], sort_keys=True)
    assert "take_id" not in serialized
    assert "target_bearing" not in serialized
    assert "timestamp" not in serialized
    assert "confidence" not in serialized
    assert "acceptance" not in serialized


def test_diagnostic_payload_schema_requires_truthful_lane_metadata() -> None:
    payload = {
        "schema": DIAGNOSTIC_PAYLOAD_SCHEMA,
        "reused_holdout": True,
        "diagnostic_only": True,
        "useful_sound_applicability_method": "method",
        "complete_capture_window_count": 7353,
        "source_window_count": 10,
        "applicable_useful_window_count": 4,
        "non_applicable_window_count": 6,
        "detector_configuration": DEFAULT_DETECTOR_CONFIG,
        "detector_provenance": {
            "config_path": CONFIG_PATH.as_posix(),
            "config_sha256": "0" * 64,
            "implementation_path": (
                "src/isaac_audio_sensors/acquisition/"
                "s4_8_useful_sound_diagnostic.py"
            ),
            "implementation_sha256": "1" * 64,
            "holdout_seal_path": "sealed.json",
            "holdout_seal_sha256": "2" * 64,
            "source_full_capture_payload_sha256": "3" * 64,
            "authenticated_waveform_and_producer_status": True,
            "unsealed_playback_timing_used": False,
            "reference_audio_used": False,
            "outcome_fields_used_for_applicability": [],
        },
        "per_take_applicability": [
            {
                "take_id": "diagnostic_fixture",
                "stratum": "A_controlled_boundary_sweep",
                "source_window_count": 10,
                "useful_sound_window_count": 4,
                "non_applicable_window_count": 6,
                "useful_window_coverage": 0.4,
                "abstained_useful_window_count": 0,
                "useful_window_abstention_rate": 0.0,
                "confidence_quantiles": {
                    "p25": 0.04,
                    "median": 0.05,
                    "p75": 0.05,
                    "p90": 0.06,
                    "maximum": 0.06,
                },
                "longest_continuous_useful_sound_interval": {
                    "first_window_index": 2,
                    "last_window_index": 5,
                    "start_sample": 4000,
                    "end_sample": 14000,
                    "duration_s": 0.625,
                    "window_count": 4,
                },
                "coherence_background_lower_window_count": 5,
                "coherence_background_median": 0.01,
                "coherence_background_mad": 0.001,
                "coherence_background_normalized_mad": 0.0014826,
                "coherence_threshold": 0.017413,
                "exclusion_reason_counts": {
                    "insufficient_directional_coherence": 6
                },
                "windows": [],
            }
        ],
        "scientific_payload": {
            "schema": DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA,
            "contract": {},
            "takes": [],
            "sim_vs_real": [],
        },
    }

    validate_diagnostic_payload(payload, repo_root=ROOT)

    payload["reused_holdout"] = False
    try:
        validate_diagnostic_payload(payload, repo_root=ROOT)
    except Exception as exc:
        assert "reused_holdout" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("false reused_holdout metadata was accepted")


def test_future_capture_protocol_requires_continuous_verified_stimulus() -> None:
    text = (ROOT / SPEC_PATH).read_text(encoding="utf-8")

    for required in (
        "reused holdout",
        "diagnostic only",
        "1.0 s pre-roll",
        "1.0 s post-roll",
        "loops continuously",
        "minimum useful-sound coverage",
        "90%",
        "automated playback-presence verification",
        "retry before sealing",
        "no new holdout",
    ):
        assert required in text
