"""Focused S4.3 preregistration, analysis, corruption, and replay tests."""

from __future__ import annotations

import copy
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.acquisition.s4_3 import (
    EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL,
    EXPECTED_OPERATIONAL_GATE_POLICY,
    S43Error,
    aggregate_category,
    analysis_microphone_positions_project_m,
    analyze_trial_wav,
    canonical_sha256,
    evaluate_repeatability,
    evaluate_zed_startup_contract,
    load_json,
    load_pilot_configuration,
    planned_inventory,
    sha256_file,
    validate_inventory,
    validate_mac_dynamic_preflight_report,
    validate_preregistration,
    verify_deterministic_replay,
    zed_device_timestamps_are_valid,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/s4_3_pilot.v1.json"
PREREG_PATH = ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze/preregistration.json"
AMENDMENT_CONFIG_PATH = ROOT / "configs/s4_3_pilot_amendment_01.v1.json"
AMENDMENT_PREREG_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_amendment_01.json"
)
OPERATIONAL_CONFIG_PATH = ROOT / "configs/s4_3_pilot_amendment_02.v1.json"
OPERATIONAL_PREREG_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_amendment_02.json"
)
OCCLUSION_CONFIRM_CONFIG_PATH = ROOT / "configs/s4_3_pilot_amendment_03.v1.json"
OCCLUSION_CONFIRM_PREREG_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_amendment_03.json"
)
INTERACTIVE_CONFIG_PATH = ROOT / "configs/s4_3_pilot_amendment_04.v1.json"
INTERACTIVE_PREREG_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_amendment_04.json"
)
REFERENCE_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.2/reference/s4_2_reference_v1.0.0.wav"
)


def _config() -> dict:
    return load_json(CONFIG_PATH)


def _preregistration() -> dict:
    return load_json(PREREG_PATH)


def _amended_config() -> dict:
    return load_pilot_configuration(AMENDMENT_CONFIG_PATH, repo_root=ROOT)


def _operational_config() -> dict:
    return load_pilot_configuration(OPERATIONAL_CONFIG_PATH, repo_root=ROOT)


def _occlusion_confirmation_config() -> dict:
    return load_pilot_configuration(OCCLUSION_CONFIRM_CONFIG_PATH, repo_root=ROOT)


def _interactive_config() -> dict:
    return load_pilot_configuration(INTERACTIVE_CONFIG_PATH, repo_root=ROOT)


def _trial(config: dict, trial_id: str) -> dict:
    return next(item for item in config["matrix"] if item["trial_id"] == trial_id)


def _write_pcm16(path: Path, samples: np.ndarray, *, rate: int = 16_000) -> None:
    clipped = np.clip(np.rint(samples * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(samples.shape[1])
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(clipped.tobytes())


def _reference_samples() -> np.ndarray:
    with wave.open(str(REFERENCE_PATH), "rb") as reader:
        raw = reader.readframes(reader.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64)[::3] / 32768.0


def _reference_capture(path: Path, *, duration_s: int = 20) -> None:
    rng = np.random.default_rng(43)
    samples = rng.normal(0.0, 2e-5, size=(duration_s * 16_000, 6))
    reference = _reference_samples()
    base = 2 * 16_000
    shifts = [0, 0, 0, 2, 3, 1]
    gains = [0.6, 0.5, 0.42, 0.40, 0.38, 0.41]
    for channel, (shift, gain) in enumerate(zip(shifts, gains, strict=True)):
        start = base + shift
        samples[start : start + reference.size, channel] += gain * reference
    _write_pcm16(path, samples)


def test_frozen_preregistration_and_matrix_validate() -> None:
    config = _config()
    preregistration = _preregistration()
    report = validate_preregistration(config, preregistration, repo_root=ROOT)
    assert report.passed, report.to_dict()
    assert preregistration["matrix"]["canonical_json_sha256"] == canonical_sha256(
        config["matrix"]
    )
    assert preregistration["matrix"]["category_counts"] == {
        "controlled": 2,
        "repeatability": 3,
        "robustness": 6,
    }
    baseline = _trial(config, "s4_3_rpt_baseline_01")
    assert baseline["operator_source_position_m"] == [0.0, -0.9, -0.135]
    assert baseline["operator_source_bearing_deg"] == 270.0
    assert baseline["source_position_m"] == [0.0, 0.9, -0.135]
    assert baseline["source_bearing_deg"] == 90.0
    assert config["coordinate_frame"]["axes"]["y"] == (
        "right_as_viewed_from_zed_operator_left_facing_camera"
    )
    assert config["operator_facing_frame"]["axes"]["negative_y"] == ("operator_left")


def test_preregistration_rejects_dual_frame_or_instruction_contradiction() -> None:
    config = _config()
    config["matrix"][0]["operator_source_position_m"][1] = 0.9
    config["matrix"][0]["operator_source_bearing_deg"] = 90.0
    config["matrix"][0]["operator_action"] = "place_mac_left"
    report = validate_preregistration(config, _preregistration(), repo_root=ROOT)
    codes = {issue.code for issue in report.issues}
    assert {
        "dual_frame_position_mismatch",
        "dual_frame_bearing_mismatch",
        "operator_instruction_order_mismatch",
        "baseline_coordinate_mismatch",
    } <= codes


def test_preregistration_fails_closed_on_in_memory_tamper() -> None:
    config = _config()
    config["analysis"]["minimum_detection_confidence"] = 0.0
    report = validate_preregistration(
        config,
        _preregistration(),
        repo_root=ROOT,
    )
    assert not report.passed
    assert any(
        issue.code == "configuration_payload_mismatch" for issue in report.issues
    )


def test_inventory_contains_every_planned_trial_and_rejects_unknown_outcome() -> None:
    config = _config()
    inventory = planned_inventory(config)
    assert validate_inventory(inventory, config).passed
    assert len(inventory["trials"]) == 11
    tampered = copy.deepcopy(inventory)
    tampered["trials"][0]["attempts"].append(
        {"attempt_id": "bad", "outcome": "silently_dropped"}
    )
    assert not validate_inventory(tampered, config).passed


def test_reference_analysis_is_deterministic_except_runtime(tmp_path: Path) -> None:
    config = _config()
    trial = _trial(config, "s4_3_rpt_baseline_01")
    wav_path = tmp_path / "reference.wav"
    _reference_capture(wav_path)

    first = analyze_trial_wav(
        wav_path,
        trial,
        config,
        reference_path=REFERENCE_PATH,
    )
    second = analyze_trial_wav(
        wav_path,
        trial,
        config,
        reference_path=REFERENCE_PATH,
    )

    assert first["status"] == "passed", first["issues"]
    assert first["window_count"] > 0
    assert first["reference_validation"]["status"] == "passed"
    assert first["summary"]["detected_count"] > 0
    assert first["windows"][0]["tdoa_s"]
    assert first["windows"][0]["combined_spectrum_relative_db"]
    assert verify_deterministic_replay(first, second).passed
    assert first["scientific_replay_sha256"] == second["scientific_replay_sha256"]
    assert (
        first["windows"][0]["capture_to_frame_offline_ms"]
        >= config["analysis"]["window_duration_ms"]
    )


def test_intended_silence_abstains_without_becoming_quality_failure(
    tmp_path: Path,
) -> None:
    config = _config()
    trial = _trial(config, "s4_3_rob_silence_01")
    samples = np.zeros((trial["duration_s"] * 16_000, 6), dtype=np.float64)
    wav_path = tmp_path / "silence.wav"
    _write_pcm16(wav_path, samples)
    report = analyze_trial_wav(wav_path, trial, config)
    assert report["status"] == "passed"
    assert report["summary"]["abstention_rate"] == 1.0
    assert report["summary"]["detected_count"] == 0


def test_truncated_or_wrong_channel_waveform_fails_closed(tmp_path: Path) -> None:
    config = _config()
    trial = _trial(config, "s4_3_rob_silence_01")
    wrong = tmp_path / "wrong.wav"
    samples = np.zeros((trial["duration_s"] * 16_000, 2), dtype=np.float64)
    _write_pcm16(wrong, samples)
    report = analyze_trial_wav(wrong, trial, config)
    assert report["status"] == "failed"
    assert any(issue["code"] == "wrong_channel_count" for issue in report["issues"])

    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"RIFF truncated")
    report = analyze_trial_wav(corrupt, trial, config)
    assert report["status"] == "failed"
    assert any(issue["code"] == "malformed_wav" for issue in report["issues"])


def test_machine_config_is_json_round_trip_stable() -> None:
    payload = _config()
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_array_frame_amendment_overlay_is_strict_and_preserves_v1() -> None:
    base = _config()
    amended = _amended_config()
    assert len(base["matrix"]) == 11
    assert "analysis_frame_correction" not in base
    assert len(amended["matrix"]) == 12
    assert amended["analysis_frame_correction"]["yaw_deg"] == 180.0
    assert (
        analysis_microphone_positions_project_m(base).tolist()
        == base["audio"]["nominal_microphone_positions_m"]
    )
    transformed = analysis_microphone_positions_project_m(amended)
    np.testing.assert_allclose(
        transformed,
        [
            [-0.033, 0.033, 0.0],
            [-0.033, -0.033, 0.0],
            [0.033, -0.033, 0.0],
            [0.033, 0.033, 0.0],
        ],
        rtol=0.0,
        atol=1e-15,
    )
    confirmation = amended["matrix"][-1]
    assert confirmation["expansion"] == {
        "parent_trial_id": "s4_3_rpt_baseline_01",
        "trigger": "analysis_contradiction",
        "confirmation_index": 1,
        "changed_capture_variables": [],
        "changed_analysis_variable": "array_to_project_yaw_deg",
        "stopping_effect": (
            "one confirmation retry resolves or leaves the array-frame "
            "contradiction terminal"
        ),
    }


def test_array_frame_amendment_rejects_unapproved_transform() -> None:
    amended = _amended_config()
    amended["analysis_frame_correction"]["yaw_deg"] = 90.0
    with pytest.raises(S43Error, match="only the authorized 180 degree"):
        analysis_microphone_positions_project_m(amended)


def test_superseded_array_frame_amendment_is_retained() -> None:
    config = _amended_config()
    operational = _operational_config()
    superseded = operational["configuration_source"]["supersedes"]
    assert superseded["effective_canonical_sha256"] == canonical_sha256(config)
    assert superseded["configuration_sha256"] == sha256_file(AMENDMENT_CONFIG_PATH)
    assert superseded["preregistration_sha256"] == sha256_file(
        AMENDMENT_PREREG_PATH
    )
    assert len(config["matrix"]) == 12

    tampered = copy.deepcopy(config)
    tampered["matrix"].append(copy.deepcopy(tampered["matrix"][-1]))
    tampered["matrix"][-1]["trial_id"] = "s4_3_rpt_forbidden_second_confirmation"
    report = validate_preregistration(
        tampered, load_json(AMENDMENT_PREREG_PATH), repo_root=ROOT
    )
    codes = {issue.code for issue in report.issues}
    assert "expansion_per_cell_exceeded" in codes
    assert "matrix_hash_mismatch" in codes


def test_superseded_operational_amendment_is_retained_without_matrix_change() -> None:
    config = _operational_config()
    current = _occlusion_confirmation_config()
    superseded = current["configuration_source"]["supersedes"]
    assert superseded["effective_canonical_sha256"] == canonical_sha256(config)
    assert superseded["configuration_sha256"] == sha256_file(
        OPERATIONAL_CONFIG_PATH
    )
    assert superseded["preregistration_sha256"] == sha256_file(
        OPERATIONAL_PREREG_PATH
    )
    assert len(config["matrix"]) == 12


def test_superseded_occlusion_confirmation_is_retained() -> None:
    config = _occlusion_confirmation_config()
    current = _interactive_config()
    superseded = current["configuration_source"]["supersedes"]
    assert superseded["effective_canonical_sha256"] == canonical_sha256(config)
    assert superseded["configuration_sha256"] == sha256_file(
        OCCLUSION_CONFIRM_CONFIG_PATH
    )
    assert superseded["preregistration_sha256"] == sha256_file(
        OCCLUSION_CONFIRM_PREREG_PATH
    )
    assert len(config["matrix"]) == 13
    confirmation = _trial(config, "s4_3_rob_occluded_01_confirm_noise_01")
    assert confirmation["expansion"]["parent_trial_id"] == "s4_3_rob_occluded_01"
    assert confirmation["expansion"]["confirmation_index"] == 1
    assert confirmation["expansion"]["changed_capture_variables"] == []
    assert confirmation["occlusion"].startswith(
        "same operator-identified two stacked rigid cardboard boxes"
    )


def test_frozen_interactive_protocol_and_final_expansion_validate() -> None:
    config = _interactive_config()
    preregistration = load_json(INTERACTIVE_PREREG_PATH)
    report = validate_preregistration(config, preregistration, repo_root=ROOT)
    assert report.passed, report.to_dict()
    assert config["interactive_stimulus_protocol"] == (
        EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL
    )
    assert len(config["matrix"]) == 14
    confirmation = _trial(config, "s4_3_rob_voice_01_confirm_timing_01")
    assert confirmation["expansion"]["parent_trial_id"] == "s4_3_rob_voice_01"
    assert confirmation["expansion"]["trigger"] == "uncovered_required_claim"
    assert preregistration["matrix"]["added_trial_count"] == 3
    assert preregistration["matrix"]["remaining_expansion_capacity"] == 0

    source = (ROOT / "scripts/run_s4_3_trial.py").read_text(encoding="utf-8")
    assert source.index('"event": "awaiting_operator_ready"') < source.index(
        'producer_root = attempt_root / "_producer"'
    )
    assert source.index('producer_root = attempt_root / "_producer"') < source.index(
        '{"event": "stimulus_now"}'
    )


def _mac_report() -> dict:
    return {
        "schema": "ias.s4_2.mac_dynamic_preflight.v1",
        "read_only": True,
        "scope": "per_take_dynamic_only",
        "status": "failed",
        "audio_output": {
            "device_name": "MacBook Pro Speakers",
            "channel_count": 2,
            "nominal_sample_rate_hz": 48000,
        },
        "volume": {"output_volume": 40, "output_muted": False},
        "power": {
            "on_ac_power": False,
            "battery_percent": 73,
            "source": "Battery Power",
        },
        "checks": {
            "ac_power": False,
            "output_channels_match": True,
            "output_device_matches": True,
            "output_sample_rate_matches": True,
            "unmuted": True,
            "volume_matches": True,
        },
    }


def test_operational_amendment_keeps_mac_power_and_aggregate_as_metadata() -> None:
    config = _operational_config()
    assert config["operational_gate_policy"] == EXPECTED_OPERATIONAL_GATE_POLICY
    report = _mac_report()
    gate = validate_mac_dynamic_preflight_report(report, config)
    assert gate["status"] == "passed"
    assert gate["aggregate_status_metadata"] == "failed"
    assert gate["power_metadata"]["on_ac_power"] is False


@pytest.mark.parametrize(
    ("section", "field", "bad_value"),
    [
        ("audio_output", "device_name", "External Speakers"),
        ("audio_output", "channel_count", 1),
        ("audio_output", "nominal_sample_rate_hz", 44100),
        ("volume", "output_volume", 39),
        ("volume", "output_muted", True),
    ],
)
def test_operational_amendment_retains_every_mac_hard_field(
    section: str, field: str, bad_value: object
) -> None:
    report = _mac_report()
    report[section][field] = bad_value
    with pytest.raises(S43Error, match="hard field mismatch"):
        validate_mac_dynamic_preflight_report(report, _operational_config())


@pytest.mark.parametrize(
    "check",
    [
        "output_channels_match",
        "output_device_matches",
        "output_sample_rate_matches",
        "unmuted",
        "volume_matches",
    ],
)
def test_operational_amendment_retains_every_mac_helper_hard_check(
    check: str,
) -> None:
    report = _mac_report()
    report["checks"][check] = False
    with pytest.raises(S43Error, match="hard check failed"):
        validate_mac_dynamic_preflight_report(report, _operational_config())


def _zed_contract_kwargs() -> dict:
    return {
        "identity": {
            "serial": "39011785",
            "sdk_version": "changed-sdk",
            "camera_firmware": "changed-camera-fw",
            "sensor_firmware": "changed-sensor-fw",
        },
        "expected_serial": "39011785",
        "reference_sdk": "5.4.0",
        "reference_camera_firmware": "1523",
        "reference_sensor_firmware": "777",
        "version_policy": "metadata",
        "usb_video_present": True,
        "usb_serial_present": True,
        "usb_speed_mbps": 5000.0,
        "minimum_usb_speed_mbps": 5000.0,
        "dimensions_px": [1280, 720],
        "resolution": "HD720",
        "actual_fps": 30,
        "requested_fps": 30,
        "depth_mode": "PERFORMANCE",
    }


def test_zed_versions_are_metadata_only_for_s4_3_but_exact_remains_available() -> None:
    kwargs = _zed_contract_kwargs()
    metadata = evaluate_zed_startup_contract(**kwargs)
    assert metadata["status"] == "passed"
    assert not any(metadata["version_provenance"]["comparisons"].values())
    assert metadata["version_provenance"]["gating"] is False

    kwargs["version_policy"] = "exact"
    exact = evaluate_zed_startup_contract(**kwargs)
    assert exact["status"] == "failed"
    assert exact["version_provenance"]["gating"] is True


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("expected_serial", "wrong-serial"),
        ("usb_video_present", False),
        ("usb_serial_present", False),
        ("usb_speed_mbps", 480.0),
        ("dimensions_px", [640, 480]),
        ("actual_fps", 15),
        ("depth_mode", "NONE"),
    ],
)
def test_zed_metadata_version_policy_retains_capture_hard_gates(
    field: str, bad_value: object
) -> None:
    kwargs = _zed_contract_kwargs()
    kwargs[field] = bad_value
    assert evaluate_zed_startup_contract(**kwargs)["status"] == "failed"


def test_zed_device_timestamps_remain_fail_closed() -> None:
    assert zed_device_timestamps_are_valid([10, 20, 30], frame_count=3)
    assert not zed_device_timestamps_are_valid([10, 10, 30], frame_count=3)
    assert not zed_device_timestamps_are_valid([10, 30], frame_count=3)
    assert not zed_device_timestamps_are_valid([], frame_count=0)


def _passing_summary() -> dict:
    return {
        "bearing_deg": {"median": 90.0},
        "absolute_bearing_error_deg": {"median": 0.0},
        "sector_accuracy": 1.0,
        "candidate_coverage": 1.0,
        "major_polarity_anomaly_count": 0,
        "abstention_rate": 0.0,
        "confidence": {"median": 0.2},
        "median_raw_rms_full_scale": {"median": 0.1},
    }


def _passing_window() -> dict:
    return {
        "srp_bearing_deg": 90.0,
        "absolute_bearing_error_deg": 0.0,
        "bearing_confidence": 0.2,
        "abstained": False,
        "ambiguity_class": "single_dominant_candidate",
        "sector_correct": True,
        "candidate_covered": True,
        "major_polarity_anomaly": False,
        "capture_to_frame_offline_ms": 251.0,
        "frame_to_adapter_round_trip_ms": 0.01,
        "tdoa_s": {"raw_microphone_0->raw_microphone_1": 0.0001},
        "relative_channel_delay_s": {"raw_microphone_0": 0.0},
        "per_channel_rms_full_scale": {"raw_microphone_0": 0.1},
        "per_channel_relative_rms_db": {"raw_microphone_0": 0.0},
        "combined_spectrum_relative_db": {"250-500": -3.0},
        "aligned_pair_correlation": {"raw_microphone_0->raw_microphone_1": 0.8},
    }


def test_repeatability_gate_and_category_aggregation_are_fail_closed() -> None:
    config = _config()
    analyses = [
        {
            "trial_id": f"s4_3_rpt_baseline_0{index}",
            "category": "repeatability",
            "summary": _passing_summary(),
            "windows": [_passing_window()],
            "relative_decay": {"status": "measured"},
            "scientific_replay_sha256": str(index) * 64,
        }
        for index in (1, 2, 3)
    ]
    silence_summary = _passing_summary()
    silence_summary["abstention_rate"] = 1.0
    analyses.append(
        {
            "trial_id": "s4_3_rob_silence_01",
            "category": "robustness",
            "summary": silence_summary,
            "windows": [],
            "relative_decay": {"status": "not_applicable"},
            "scientific_replay_sha256": "a" * 64,
        }
    )
    gate = evaluate_repeatability(analyses, config)
    assert gate["status"] == "passed", gate

    inventory = planned_inventory(config)
    report = aggregate_category("repeatability", analyses, inventory)
    assert report["planned_trial_count"] == 3
    assert report["accepted_analysis_count"] == 3
    assert report["pooled"]["absolute_bearing_error_deg"]["worst"] == 0.0

    analyses[0]["summary"]["bearing_deg"]["median"] = 130.0
    analyses[0]["summary"]["absolute_bearing_error_deg"]["median"] = 40.0
    assert evaluate_repeatability(analyses, config)["status"] == "failed"
