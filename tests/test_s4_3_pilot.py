"""Focused S4.3 preregistration, analysis, corruption, and replay tests."""

from __future__ import annotations

import copy
import json
import wave
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.acquisition.s4_3_postcapture as s43_postcapture
from isaac_audio_sensors.acquisition.s4_3 import (
    EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL,
    EXPECTED_OPERATIONAL_GATE_POLICY,
    S43Error,
    _prospective_transient_events,
    aggregate_category,
    analysis_microphone_positions_project_m,
    analyze_noise_characterization,
    analyze_trial_wav,
    build_channel_evidence,
    canonical_sha256,
    evaluate_repeatability,
    evaluate_zed_startup_contract,
    load_json,
    load_pilot_configuration,
    planned_inventory,
    sha256_file,
    summarize_windows,
    validate_corrective_provenance,
    validate_inventory,
    validate_mac_dynamic_preflight_report,
    validate_metric_evidence,
    validate_preregistration,
    validate_review_remediation_manifest,
    verify_deterministic_replay,
    zed_device_timestamps_are_valid,
)
from isaac_audio_sensors.acquisition.s4_3_postcapture import (
    validate_corrective_02_postcapture_manifest,
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
CORRECTIVE_01_CONFIG_PATH = ROOT / "configs/s4_3_pilot_corrective_01.v1.json"
CORRECTIVE_CONFIG_PATH = ROOT / "configs/s4_3_pilot_corrective_02.v1.json"
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


def _corrective_config() -> dict:
    return load_pilot_configuration(CORRECTIVE_CONFIG_PATH, repo_root=ROOT)


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
    report = validate_preregistration(
        config,
        preregistration,
        repo_root=ROOT,
        verify_implementation_hashes=False,
    )
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
    assert superseded["preregistration_sha256"] == sha256_file(AMENDMENT_PREREG_PATH)
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
    assert superseded["configuration_sha256"] == sha256_file(OPERATIONAL_CONFIG_PATH)
    assert superseded["preregistration_sha256"] == sha256_file(OPERATIONAL_PREREG_PATH)
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
    report = validate_preregistration(
        config,
        preregistration,
        repo_root=ROOT,
        verify_implementation_hashes=False,
    )
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
    raw_ids = [f"raw_microphone_{index}" for index in range(4)]
    ordered_pairs = {
        f"{left}->{right}": 0.0001 if left != right else 0.0
        for left in raw_ids
        for right in raw_ids
    }
    unique_pairs = {
        f"{left}->{right}": 0.8
        for left_index, left in enumerate(raw_ids)
        for right_index, right in enumerate(raw_ids)
        if right_index > left_index
    }
    return {
        "srp_bearing_deg": 90.0,
        "least_squares_bearing_deg": 90.0,
        "least_squares_candidates_deg": [90.0],
        "candidate_bearing_deg": [90.0],
        "absolute_bearing_error_deg": 0.0,
        "bearing_confidence": 0.2,
        "abstained": False,
        "ambiguity_class": "single_dominant_candidate",
        "sector_correct": True,
        "candidate_covered": True,
        "major_polarity_anomaly": False,
        "capture_to_frame_offline_ms": 251.0,
        "frame_to_adapter_round_trip_ms": 0.01,
        "tdoa_s": ordered_pairs,
        "tdoa_error_s": dict(ordered_pairs),
        "relative_channel_delay_s": {channel_id: 0.0 for channel_id in raw_ids},
        "per_channel_rms_full_scale": {channel_id: 0.1 for channel_id in raw_ids},
        "per_channel_relative_rms_db": {channel_id: 0.0 for channel_id in raw_ids},
        "combined_spectrum_relative_db": {
            "250-500": -3.0,
            "500-1000": -3.0,
            "1000-2000": -3.0,
            "2000-4000": -3.0,
            "4000-6500": -3.0,
        },
        "aligned_pair_correlation": unique_pairs,
        "median_raw_rms_full_scale": 0.1,
    }


def _passing_wav() -> dict:
    return {
        "channel_count": 6,
        "per_channel_rms_pcm16": [100.0] * 6,
        "per_channel_peak_pcm16": [1000] * 6,
        "per_channel_maximum_clip_run_samples": [0] * 6,
    }


def test_repeatability_gate_and_category_aggregation_are_fail_closed() -> None:
    config = _config()
    analyses = [
        {
            "trial_id": f"s4_3_rpt_baseline_0{index}",
            "category": "repeatability",
            "summary": _passing_summary(),
            "windows": [_passing_window()],
            "stimulus": "mac_reference",
            "wav": _passing_wav(),
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
    report = aggregate_category(
        "repeatability", analyses, inventory, configuration=config
    )
    assert report["planned_trial_count"] == 3
    assert report["accepted_analysis_count"] == 3
    assert report["pooled"]["absolute_bearing_error_deg"]["worst"] == 0.0

    analyses[0]["summary"]["bearing_deg"]["median"] = 130.0
    analyses[0]["summary"]["absolute_bearing_error_deg"]["median"] = 40.0
    analyses[0]["windows"][0]["srp_bearing_deg"] = 130.0
    analyses[0]["windows"][0]["absolute_bearing_error_deg"] = 40.0
    assert evaluate_repeatability(analyses, config)["status"] == "failed"


def _synthetic_metric_fixture() -> dict:
    config = _interactive_config()
    inventory = planned_inventory(config)
    analyses = []
    channel_evidence = []
    noise_results = []
    for entry in inventory["trials"]:
        trial = _trial(config, entry["trial_id"])
        attempt_id = f"{trial['trial_id']}_synthetic_evidence"
        entry["attempts"] = [
            {
                "attempt_id": attempt_id,
                "outcome": "accepted",
                "reason": "synthetic regression fixture",
            }
        ]
        window = _passing_window()
        reference = trial.get("source_bearing_deg")
        if reference is None:
            window.update(
                {
                    "abstained": True,
                    "signal_present": False,
                    "srp_bearing_deg": None,
                    "least_squares_bearing_deg": None,
                    "candidate_bearing_deg": [],
                    "bearing_confidence": 0.0,
                    "ambiguity_class": "abstained_low_level",
                }
            )
            for field in (
                "absolute_bearing_error_deg",
                "candidate_covered",
                "sector_correct",
                "tdoa_s",
                "tdoa_error_s",
                "relative_channel_delay_s",
                "aligned_pair_correlation",
            ):
                window.pop(field, None)
        else:
            window["srp_bearing_deg"] = float(reference)
            window["least_squares_bearing_deg"] = float(reference)
            window["candidate_bearing_deg"] = [float(reference)]
        stimulus = str(trial["stimulus"])
        analysis = {
            "schema": "ias.s4_3.trial_analysis.v1",
            "status": "passed",
            "trial_id": trial["trial_id"],
            "category": trial["category"],
            "stimulus": stimulus,
            "window_count": 1,
            "windows": [window],
            "wav": _passing_wav(),
            "relative_decay": (
                {"status": "measured", "decay_to_minus_10_db_ms": 125.0}
                if "mac_reference" in stimulus
                or stimulus == "visible_audible_ordinary_object_impact"
                else {"status": "not_applicable"}
            ),
            "scientific_replay_sha256": canonical_sha256(
                {"trial_id": trial["trial_id"]}
            ),
        }
        analysis["summary"] = summarize_windows(
            analysis["windows"],
            bearing_reference_deg=(None if reference is None else float(reference)),
        )
        analyses.append(analysis)
        channel_evidence.append(
            build_channel_evidence(
                analysis,
                trial,
                config,
                attempt_id=attempt_id,
                outcome="accepted",
            )
        )
        if stimulus == "silence" or "mac_reference" in stimulus:
            raw_ids = config["audio"]["analysis_channel_ids"]
            bands = [
                f"{low}-{high}" for low, high in config["analysis"]["spectral_bands_hz"]
            ]
            noise_results.append(
                {
                    "trial_id": trial["trial_id"],
                    "status": "measured",
                    "window_count": 1,
                    "transient_count": 0,
                    "transient_rate_per_s": 0.0,
                    "per_channel_rms_full_scale": {
                        channel_id: {"count": 1} for channel_id in raw_ids
                    },
                    "combined_spectrum_relative_db": {
                        band: {"count": 1} for band in bands
                    },
                }
            )
    inventory.update(
        {
            "status": "terminal",
            "attempt_count": len(inventory["trials"]),
            "terminal_trial_count": len(inventory["trials"]),
            "outcome_counts": {"accepted": len(inventory["trials"])},
        }
    )
    reports = {
        category: aggregate_category(
            category,
            analyses,
            inventory,
            configuration=config,
            channel_evidence=channel_evidence,
            noise_transient_results=noise_results,
        )
        for category in ("repeatability", "controlled", "robustness")
    }
    reports["robustness"]["condition_deltas"] = {
        "status": "measured",
        "conditions": [
            {
                "trial_id": trial_id,
                "relative_rms_delta_db": 0.0,
                "confidence_delta": 0.0,
                "absolute_bearing_error_delta_deg": 0.0,
                "abstention_rate": 0.0,
            }
            for trial_id in (
                "s4_3_rob_occluded_01",
                "s4_3_rob_overlap_01",
            )
        ],
    }
    return {
        "config": config,
        "inventory": inventory,
        "analyses": analyses,
        "reports": reports,
        "channel_evidence": channel_evidence,
        "noise_results": noise_results,
        "failure_report": {
            "schema": "ias.s4_3.failure_inventory.v1",
            "failure_count": 0,
            "failures": [],
            "all_failures_retained": True,
        },
        "av": {
            "schema": "ias.s4_3.coarse_audio_video_association.v1",
            "status": "passed",
            "event_audible": True,
            "event_visible": True,
            "event_unique": True,
            "audio_event_sample_index": 100,
            "audio_sample_rate_hz": 16000,
            "zed_event_frame_index": 10,
            "zed_event_timestamp_ns": 1000,
            "offset_s": 0.01,
            "total_uncertainty_ms": 20.0,
            "maximum_uncertainty_ms": 50.0,
        },
        "svo": {
            "status": "passed",
            "end_of_svo_reached": True,
            "declared_frame_count": 20,
            "replayed_frame_count": 20,
        },
    }


def _validate_fixture(fixture: dict) -> dict:
    return validate_metric_evidence(
        fixture["config"],
        fixture["analyses"],
        fixture["inventory"],
        fixture["reports"],
        fixture["channel_evidence"],
        fixture["noise_results"],
        fixture["failure_report"],
        fixture["av"],
        fixture["svo"],
    )


def test_metric_specific_coverage_positive_fixture_passes_all_22_contracts() -> None:
    coverage = _validate_fixture(_synthetic_metric_fixture())
    assert coverage["status"] == "passed", coverage
    assert len(coverage["metric_contracts"]) == 22
    assert all(
        record["required_outputs_verified"]
        for record in coverage["metric_contracts"].values()
    )


@pytest.mark.parametrize(
    "metric",
    [
        "abstention",
        "acquisition_analysis_failures",
        "ambiguity",
        "bearing_doa_error",
        "candidate_bearing",
        "capture_to_frame_latency",
        "channel_imbalance",
        "channel_presence_order_health",
        "coarse_audio_video_association",
        "combined_spectrum",
        "confidence",
        "echo_relative_decay",
        "frame_to_adapter_latency",
        "major_polarity_anomaly",
        "noise",
        "occlusion",
        "overlap",
        "relative_channel_delay",
        "relative_rms_level",
        "sector_accuracy",
        "silence",
        "tdoa",
    ],
)
def test_metric_specific_coverage_fails_when_required_output_is_absent(
    metric: str,
) -> None:
    fixture = _synthetic_metric_fixture()
    baseline = next(
        report
        for report in fixture["analyses"]
        if report["trial_id"] == "s4_3_rpt_baseline_01"
    )
    window = baseline["windows"][0]
    if metric == "abstention":
        window.pop("abstained")
    elif metric == "acquisition_analysis_failures":
        fixture["inventory"]["trials"][0]["attempts"].append(
            {"attempt_id": "retained_failure", "outcome": "failed"}
        )
    elif metric == "ambiguity":
        window.pop("ambiguity_class")
    elif metric == "bearing_doa_error":
        window.pop("absolute_bearing_error_deg")
    elif metric == "candidate_bearing":
        window["candidate_bearing_deg"] = []
    elif metric == "capture_to_frame_latency":
        window.pop("capture_to_frame_offline_ms")
    elif metric == "channel_imbalance":
        window["per_channel_relative_rms_db"].pop("raw_microphone_3")
    elif metric == "channel_presence_order_health":
        fixture["channel_evidence"][0]["channels"][0].pop("maximum_clip_run_samples")
    elif metric == "coarse_audio_video_association":
        fixture["av"]["status"] = "failed"
    elif metric == "combined_spectrum":
        window["combined_spectrum_relative_db"].pop("4000-6500")
    elif metric == "confidence":
        window.pop("bearing_confidence")
    elif metric == "echo_relative_decay":
        baseline["relative_decay"] = None
    elif metric == "frame_to_adapter_latency":
        window.pop("frame_to_adapter_round_trip_ms")
    elif metric == "major_polarity_anomaly":
        window["aligned_pair_correlation"].pop("raw_microphone_2->raw_microphone_3")
    elif metric == "noise":
        fixture["noise_results"] = []
    elif metric in {"occlusion", "overlap"}:
        omitted = (
            "s4_3_rob_occluded_01" if metric == "occlusion" else "s4_3_rob_overlap_01"
        )
        conditions = fixture["reports"]["robustness"]["condition_deltas"]["conditions"]
        fixture["reports"]["robustness"]["condition_deltas"]["conditions"] = [
            condition for condition in conditions if condition["trial_id"] != omitted
        ]
    elif metric == "relative_channel_delay":
        window["relative_channel_delay_s"].pop("raw_microphone_3")
    elif metric == "relative_rms_level":
        window["per_channel_rms_full_scale"].pop("raw_microphone_3")
    elif metric == "sector_accuracy":
        window.pop("sector_correct")
    elif metric == "silence":
        silence = next(
            report
            for report in fixture["analyses"]
            if report["trial_id"] == "s4_3_rob_silence_01"
        )
        silence["windows"][0]["abstained"] = False
    elif metric == "tdoa":
        window["tdoa_s"].pop("raw_microphone_3->raw_microphone_2")
    coverage = _validate_fixture(fixture)
    assert coverage["status"] == "failed"
    assert coverage["metric_contracts"][metric]["status"] == "failed", coverage


def test_abstained_numeric_values_are_excluded_but_remain_uncovered() -> None:
    config = _config()
    detected = _passing_window()
    abstained = copy.deepcopy(detected)
    abstained.update(
        {
            "abstained": True,
            "signal_present": False,
            "absolute_bearing_error_deg": 170.0,
            "candidate_covered": False,
            "sector_correct": False,
        }
    )
    abstained["tdoa_s"] = {key: 0.99 for key in abstained["tdoa_s"]}
    abstained["tdoa_error_s"] = {key: 0.99 for key in abstained["tdoa_error_s"]}
    abstained["relative_channel_delay_s"] = {
        key: 0.99 for key in abstained["relative_channel_delay_s"]
    }
    summary = summarize_windows([detected, abstained], bearing_reference_deg=90.0)
    assert summary["absolute_bearing_error_deg"]["count"] == 1
    assert summary["absolute_bearing_error_deg"]["worst"] == 0.0
    assert summary["candidate_coverage_counts"] == {
        "denominator": 2,
        "covered": 1,
        "uncovered": 1,
        "abstained_uncovered": 1,
    }
    analysis = {
        "trial_id": "s4_3_rpt_baseline_01",
        "category": "repeatability",
        "stimulus": "mac_reference",
        "windows": [detected, abstained],
        "summary": summary,
        "relative_decay": {"status": "measured"},
        "scientific_replay_sha256": "a" * 64,
    }
    report = aggregate_category(
        "repeatability",
        [analysis],
        planned_inventory(config),
        configuration=config,
    )
    assert report["pooled"]["absolute_bearing_error_deg"]["count"] == 1
    assert all(stats["count"] == 1 for stats in report["pooled"]["tdoa_us"].values())
    assert all(
        stats["count"] == 1
        for stats in report["pooled"]["relative_channel_delay_us"].values()
    )


def test_repeatability_gate_rejects_partial_pairs_and_raw_health_failure() -> None:
    config = _config()
    analyses = []
    for index in (1, 2, 3):
        analyses.append(
            {
                "trial_id": f"s4_3_rpt_baseline_0{index}",
                "category": "repeatability",
                "stimulus": "mac_reference",
                "summary": _passing_summary(),
                "windows": [_passing_window()],
                "wav": _passing_wav(),
            }
        )
    analyses.append(
        {
            "trial_id": "s4_3_rob_silence_01",
            "category": "robustness",
            "summary": {"abstention_rate": 1.0},
            "windows": [],
        }
    )
    assert evaluate_repeatability(analyses, config)["status"] == "passed"
    partial = copy.deepcopy(analyses)
    partial[0]["windows"][0]["tdoa_s"].pop("raw_microphone_3->raw_microphone_2")
    gate = evaluate_repeatability(partial, config)
    assert gate["checks"]["pair_tdoa_range"] is False
    unhealthy = copy.deepcopy(analyses)
    unhealthy[0]["wav"]["per_channel_maximum_clip_run_samples"][2] = 4000
    gate = evaluate_repeatability(unhealthy, config)
    assert gate["checks"]["raw_channel_health_failures"] is False
    assert gate["observations"]["raw_channel_health_failure_count"] == 1


@pytest.mark.parametrize(
    ("run_samples", "expected_status"), [(3_999, "passed"), (4_000, "failed")]
)
def test_corrected_sustained_clip_boundary_controls_analysis(
    tmp_path: Path, run_samples: int, expected_status: str
) -> None:
    config = _corrective_config()
    trial = copy.deepcopy(_trial(config, "s4_3_rob_silence_02_prospective_events_01"))
    trial["duration_s"] = 3
    samples = np.zeros((48_000, 6), dtype=np.float64)
    samples[:run_samples, 0] = 1.0
    wav_path = tmp_path / f"clip-{run_samples}.wav"
    _write_pcm16(wav_path, samples)
    result = analyze_trial_wav(wav_path, trial, config)
    assert result["status"] == expected_status
    assert result["wav"]["per_channel_maximum_clip_run_samples"][0] == run_samples
    assert ("sustained_clipping" in {issue["code"] for issue in result["issues"]}) is (
        expected_status == "failed"
    )


def test_corrected_clipping_checks_every_declared_channel_and_reports_short_runs() -> (
    None
):
    config = _corrective_config()
    trial = _trial(config, "s4_3_rob_overlap_01")
    for channel_index, channel_id in enumerate(config["audio"]["channel_order"]):
        analysis = {"wav": _passing_wav()}
        analysis["wav"]["per_channel_maximum_clip_run_samples"][channel_index] = 4_000
        evidence = build_channel_evidence(
            analysis,
            trial,
            config,
            attempt_id=f"channel-{channel_index}",
            outcome="accepted",
        )
        assert evidence["status"] == "failed"
        assert evidence["channels"][channel_index]["channel_id"] == channel_id
        assert evidence["channels"][channel_index]["sustained_clipping"] is True
    analysis = {"wav": _passing_wav()}
    analysis["wav"]["per_channel_maximum_clip_run_samples"][0] = 15
    evidence = build_channel_evidence(
        analysis, trial, config, attempt_id="overlap-short-run", outcome="accepted"
    )
    assert evidence["status"] == "passed"
    assert evidence["channels"][0]["maximum_clip_run_samples"] == 15
    assert evidence["channels"][0]["sustained_clipping"] is False


def test_effective_configuration_is_the_only_s4_3_clipping_threshold_source() -> None:
    config = _corrective_config()
    trial = _trial(config, "s4_3_rob_overlap_01")
    analysis = {"wav": _passing_wav()}
    analysis["wav"]["per_channel_maximum_clip_run_samples"][0] = 4_000
    assert (
        build_channel_evidence(
            analysis, trial, config, attempt_id="at-threshold", outcome="accepted"
        )["status"]
        == "failed"
    )
    alternate = copy.deepcopy(config)
    alternate["quality"]["maximum_sustained_clip_run_samples"] = 5_000
    assert (
        build_channel_evidence(
            analysis, trial, alternate, attempt_id="below-effective", outcome="accepted"
        )["status"]
        == "passed"
    )


def test_missing_or_inconsistent_corrective_provenance_fails_closed(
    tmp_path: Path,
) -> None:
    payload = load_json(CORRECTIVE_CONFIG_PATH)
    payload["prospective_transient_event_contract"]["path"] = (
        "missing/transient-event-contract-02.json"
    )
    broken_path = tmp_path / "broken-corrective.json"
    broken_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(S43Error, match="corrective-02 binding.*SHA-256 mismatch"):
        load_pilot_configuration(broken_path, repo_root=ROOT)

    config = _corrective_config()
    inconsistent = copy.deepcopy(config)
    inconsistent["quality"]["maximum_sustained_clip_run_samples"] = 3_999
    preregistration = {
        "configuration": {
            "path": "configs/s4_3_pilot_corrective_02.v1.json",
            "effective_canonical_sha256": canonical_sha256(inconsistent),
        }
    }
    report = validate_corrective_provenance(
        inconsistent, preregistration, repo_root=ROOT
    )
    assert not report.passed
    assert any(
        issue.code == "effective_clipping_threshold_mismatch" for issue in report.issues
    )


def test_missing_or_inconsistent_corrective_02_provenance_fails_closed() -> None:
    config = _corrective_config()
    preregistration = {
        "configuration": {
            "path": "configs/s4_3_pilot_corrective_02.v1.json",
            "effective_canonical_sha256": canonical_sha256(config),
        },
        "corrective_records": [],
    }

    missing = copy.deepcopy(config)
    missing["corrective_provenance"].pop("corrective_02_specification")
    preregistration["configuration"]["effective_canonical_sha256"] = canonical_sha256(
        missing
    )
    report = validate_corrective_provenance(
        missing, preregistration, repo_root=ROOT
    )
    assert not report.passed
    assert any(
        issue.code == "corrective_binding_absent"
        and issue.path == "corrective_02_specification"
        for issue in report.issues
    )

    inconsistent = copy.deepcopy(config)
    inconsistent["noise_event_detector"]["lower_index_support_samples"] = 159
    preregistration["configuration"]["effective_canonical_sha256"] = canonical_sha256(
        inconsistent
    )
    report = validate_corrective_provenance(
        inconsistent, preregistration, repo_root=ROOT
    )
    assert not report.passed
    assert any(
        issue.code == "corrective_02_boundary_support_mismatch"
        for issue in report.issues
    )


def test_corrective_02_replacement_failure_handling_is_bounded_and_tracked() -> None:
    relative = (
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_failure_handling_01.json"
    )
    record = load_json(ROOT / relative)
    assert record["status"] == "frozen_before_replacement_attempt"
    assert record["authorization"]["replacement_attempt_count_authorized"] == 1
    assert record["replacement_rule"]["maximum_replacement_attempts"] == 1
    assert record["replacement_rule"]["any_further_failure_stops_collection"] is True
    assert record["scientific_changes"] == {
        "detector_changed": False,
        "matrix_changed": False,
        "threshold_changed": False,
        "trial_definition_changed": False,
        "supported_claim_changed": False,
        "unrelated_failure_handling_changed": False,
    }
    for script in (
        "scripts/build_s4_3_evidence.py",
        "scripts/validate_s4_3_integrity.py",
    ):
        assert "corrective_02_failure_handling_01.json" in (
            ROOT / script
        ).read_text(encoding="utf-8")


def test_corrective_02_postcapture_manifest_passes_and_fails_closed() -> None:
    path = (
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    manifest = load_json(path)
    validate_corrective_02_postcapture_manifest(manifest, repo_root=ROOT)

    inconsistent = copy.deepcopy(manifest)
    inconsistent["scientific_changes"]["detector_changed_after_capture"] = True
    with pytest.raises(S43Error, match="scientific-change"):
        validate_corrective_02_postcapture_manifest(inconsistent, repo_root=ROOT)

    missing = copy.deepcopy(manifest)
    missing["retained_attempts"] = missing["retained_attempts"][:1]
    with pytest.raises(S43Error, match="exactly two"):
        validate_corrective_02_postcapture_manifest(missing, repo_root=ROOT)


def test_corrective_02_postcapture_rejects_nonexistent_commit() -> None:
    path = (
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    manifest = load_json(path)
    next(
        item
        for item in manifest["post_capture_implementation"]
        if item["path"] == "tests/test_s4_3_pilot.py"
    )["sha256"] = sha256_file(Path(__file__))
    manifest["provenance_commits"][
        "pre_capture_freeze_and_implementation"
    ] = "f" * 40
    with pytest.raises(S43Error, match="commit"):
        validate_corrective_02_postcapture_manifest(manifest, repo_root=ROOT)


def test_corrective_02_postcapture_rejects_reversed_commits() -> None:
    path = (
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    manifest = load_json(path)
    next(
        item
        for item in manifest["post_capture_implementation"]
        if item["path"] == "tests/test_s4_3_pilot.py"
    )["sha256"] = sha256_file(Path(__file__))
    commits = manifest["provenance_commits"]
    commits["pre_capture_freeze_and_implementation"], commits[
        "replacement_authorization"
    ] = (
        commits["replacement_authorization"],
        commits["pre_capture_freeze_and_implementation"],
    )
    with pytest.raises(S43Error, match="ancestry"):
        validate_corrective_02_postcapture_manifest(manifest, repo_root=ROOT)


def test_corrective_02_postcapture_rejects_real_commit_missing_freeze_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    manifest = load_json(path)
    monkeypatch.setitem(
        manifest["provenance_commits"],
        "pre_capture_freeze_and_implementation",
        "1d0b93d95860bc88450d925f98d58d229e59c552",
    )
    with pytest.raises(S43Error, match="artifact"):
        validate_corrective_02_postcapture_manifest(manifest, repo_root=ROOT)


def test_corrective_02_postcapture_rejects_non_repository(
    tmp_path: Path,
) -> None:
    manifest = load_json(
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    with pytest.raises(S43Error, match="Git"):
        validate_corrective_02_postcapture_manifest(
            manifest, repo_root=tmp_path
        )


def test_corrective_02_postcapture_fails_closed_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_json(
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "corrective_02_postcapture_evidence_manifest.json"
    )
    monkeypatch.setattr(s43_postcapture.shutil, "which", lambda _name: None)
    with pytest.raises(S43Error, match="Git is unavailable"):
        validate_corrective_02_postcapture_manifest(manifest, repo_root=ROOT)


def _noise_result(
    tmp_path: Path, raw: np.ndarray, *, overlap_percent: int = 50
) -> dict:
    config = _corrective_config()
    config["analysis"]["window_overlap_percent"] = overlap_percent
    samples = np.zeros((raw.shape[0], 6), dtype=np.float64)
    samples[:, 2:6] = raw
    wav_path = tmp_path / f"noise-{overlap_percent}-{len(list(tmp_path.iterdir()))}.wav"
    _write_pcm16(wav_path, samples)
    return analyze_noise_characterization(
        wav_path,
        {"reference_start_sample": None},
        _trial(config, "s4_3_rob_silence_03_boundary_support_01"),
        config,
    )


def test_stationary_above_threshold_is_not_repeatedly_counted_as_events(
    tmp_path: Path,
) -> None:
    raw = np.zeros((4 * 16_000, 4), dtype=np.float64)
    raw[16_000 : 16_000 + 24_000, :] = 0.05
    prospective = _noise_result(tmp_path, raw)["prospective_distinct_transient_events"]
    assert prospective["event_count"] == 0
    assert prospective["stationary_excursion_count"] == 1


@pytest.mark.parametrize("amplitude", [0.0021, 0.0025])
@pytest.mark.parametrize("boundary", ["start", "stop"])
def test_prospective_event_with_required_rms_support_at_boundary_is_censored(
    tmp_path: Path,
    amplitude: float,
    boundary: str,
) -> None:
    raw = np.zeros((3 * 16_000, 4), dtype=np.float64)
    if boundary == "start":
        raw[:2_400, :] = amplitude
    else:
        raw[-2_400:, :] = amplitude

    prospective = _noise_result(tmp_path, raw)[
        "prospective_distinct_transient_events"
    ]
    assert prospective["event_count"] == 0
    assert prospective["boundary_censored_excursion_count"] == 1
    assert len(prospective["boundary_censored_excursions"]) == 1
    support = prospective["boundary_support"]
    assert support["even_window_raw_support_for_center_j"] == "[j-160,j+160)"
    assert support["complete_center_start_inclusive"] == 160
    assert support["complete_center_stop_exclusive"] == raw.shape[0] - 159
    assert support["arbitrary_fixed_time_guard_used"] is False


@pytest.mark.parametrize("amplitude", [0.0021, 0.0025])
def test_equivalent_fully_interior_low_amplitude_event_counts_once(
    tmp_path: Path, amplitude: float
) -> None:
    raw = np.zeros((3 * 16_000, 4), dtype=np.float64)
    raw[12_000:14_400, :] = amplitude
    prospective = _noise_result(tmp_path, raw)[
        "prospective_distinct_transient_events"
    ]
    assert prospective["event_count"] == 1
    assert prospective["boundary_censored_excursion_count"] == 0
    assert len(prospective["events"]) == 1


def test_corrective_02_preserves_short_and_channel_concurrence_semantics() -> None:
    config = _corrective_config()
    raw = np.zeros((48_000, 4), dtype=np.float64)
    raw[20_000:20_320, :] = 0.00201
    short = _prospective_transient_events(raw, config)
    assert short["event_count"] == 0
    assert short["short_excursion_count"] == 1

    one_channel = np.zeros((48_000, 4), dtype=np.float64)
    one_channel[12_000:14_400, 0] = 0.05
    assert _prospective_transient_events(one_channel, config)["event_count"] == 0
    two_channels = one_channel.copy()
    two_channels[12_000:14_400, 1] = 0.05
    assert _prospective_transient_events(two_channels, config)["event_count"] == 1


def test_corrective_02_preserves_duration_boundary_and_gap_bridging() -> None:
    config = _corrective_config()
    at_maximum = np.zeros((48_000, 4), dtype=np.float64)
    at_maximum[20_000 : 20_000 + 16_089, :] = 0.0025
    result = _prospective_transient_events(at_maximum, config)
    assert result["event_count"] == 1
    assert result["events"][0]["duration_samples"] == 16_000

    above_maximum = np.zeros((48_000, 4), dtype=np.float64)
    above_maximum[20_000 : 20_000 + 16_090, :] = 0.0025
    result = _prospective_transient_events(above_maximum, config)
    assert result["event_count"] == 0
    assert result["stationary_excursion_count"] == 1
    assert result["stationary_excursions"][0]["duration_samples"] == 16_001

    bridged = np.zeros((48_000, 4), dtype=np.float64)
    bridged[10_000:10_400, :] = 0.05
    bridged[12_319:12_719, :] = 0.05
    assert _prospective_transient_events(bridged, config)["event_count"] == 1
    separated = np.zeros((48_000, 4), dtype=np.float64)
    separated[10_000:10_400, :] = 0.05
    separated[12_320:12_720, :] = 0.05
    assert _prospective_transient_events(separated, config)["event_count"] == 2


def test_separated_events_are_distinct_and_one_spanning_windows_counts_once(
    tmp_path: Path,
) -> None:
    raw = np.zeros((4 * 16_000, 4), dtype=np.float64)
    raw[8_000:10_400, :] = 0.05
    raw[24_000:27_200, :] = 0.05
    result = _noise_result(tmp_path, raw)
    prospective = result["prospective_distinct_transient_events"]
    assert prospective["event_count"] == 2
    assert len(prospective["events"]) == 2
    assert result["legacy_overlapping_window_rms_exceedance"]["metric_id"] == (
        "legacy_overlapping_window_rms_exceedance_rate"
    )
    assert result["legacy_distinct_event_rate"] == {
        "status": "unmeasured",
        "metric_id": "legacy_distinct_transient_event_rate",
        "classification": "Unmeasured",
        "reason": (
            "the retained S4.3 waveform was inspected before the prospective "
            "de-duplicated detector contract was frozen"
        ),
    }


def test_prospective_event_count_is_independent_of_reporting_window_overlap(
    tmp_path: Path,
) -> None:
    raw = np.zeros((3 * 16_000, 4), dtype=np.float64)
    raw[12_000:16_800, :] = 0.05
    counts = [
        _noise_result(tmp_path, raw, overlap_percent=overlap)[
            "prospective_distinct_transient_events"
        ]["event_count"]
        for overlap in (0, 50, 90)
    ]
    assert counts == [1, 1, 1]


def test_corrected_noise_coverage_fails_without_provenance_or_new_evidence() -> None:
    fixture = _synthetic_metric_fixture()
    fixture["config"] = _corrective_config()
    coverage = _validate_fixture(fixture)
    assert coverage["metric_contracts"]["noise"]["status"] == "failed"
    assert any(
        "required prospective silence evidence is absent" in issue
        for issue in coverage["metric_contracts"]["noise"]["issues"]
    )

    missing_provenance = copy.deepcopy(fixture)
    missing_provenance["config"].pop("corrective_provenance")
    coverage = _validate_fixture(missing_provenance)
    assert coverage["metric_contracts"]["noise"]["status"] == "failed"
    assert any(
        "provenance" in issue
        for issue in coverage["metric_contracts"]["noise"]["issues"]
    )


def _review_manifest_payload() -> dict:
    config = _interactive_config()
    threshold_payload = {
        key: config.get(key)
        for key in (
            "analysis",
            "audio",
            "expansion",
            "metric_contracts",
            "quality",
            "reference",
            "repeatability_acceptance",
        )
    }
    implementation_paths = [
        "src/isaac_audio_sensors/acquisition/s4_3.py",
        "scripts/build_s4_3_evidence.py",
        "scripts/validate_s4_3_integrity.py",
        "tests/test_s4_3_pilot.py",
    ]
    return {
        "schema": "ias.s4_3.review_remediation_manifest.v1",
        "status": "frozen_post_trial_review_remediation",
        "configuration": {
            "path": "configs/s4_3_pilot_amendment_04.v1.json",
            "sha256": sha256_file(INTERACTIVE_CONFIG_PATH),
            "effective_canonical_sha256": canonical_sha256(config),
        },
        "preregistration": {
            "path": (
                "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
                "preregistration_amendment_04.json"
            ),
            "sha256": sha256_file(INTERACTIVE_PREREG_PATH),
        },
        "matrix_canonical_sha256": canonical_sha256(config["matrix"]),
        "scientific_contract_canonical_sha256": canonical_sha256(threshold_payload),
        "implementation": [
            {"path": path, "sha256": sha256_file(ROOT / path)}
            for path in implementation_paths
        ],
        "scientific_thresholds_changed": False,
        "matrix_changed": False,
        "raw_evidence_modified": False,
        "trials_recollected": False,
        "s4_4_started": False,
    }


def test_review_remediation_manifest_binds_code_without_rewriting_freeze() -> None:
    config = _interactive_config()
    preregistration = load_json(INTERACTIVE_PREREG_PATH)
    manifest = _review_manifest_payload()
    report = validate_review_remediation_manifest(
        config, preregistration, manifest, repo_root=ROOT
    )
    assert report.passed, report.to_dict()
    tampered = copy.deepcopy(manifest)
    tampered["implementation"][0]["sha256"] = "0" * 64
    report = validate_review_remediation_manifest(
        config, preregistration, tampered, repo_root=ROOT
    )
    assert not report.passed
    assert any(
        issue.code == "review_implementation_hash_mismatch" for issue in report.issues
    )
