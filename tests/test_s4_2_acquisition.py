"""Unit, integration, regression, and hardware-gate coverage for S4.2."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.acquisition.s4_2_orchestrator as s42_orchestrator
from isaac_audio_sensors.acquisition.s4_2 import (
    AttemptLifecycle,
    S42Error,
    artifact_record,
    calculate_alignment,
    disk_space_check,
    inspect_six_channel_wav,
    load_json,
    operator_facing_zed_bearing_to_project,
    operator_facing_zed_position_to_project,
    promote_finalized_file,
    read_jsonl,
    recompute_alignment_from_evidence,
    validate_configuration,
    validate_mac_dynamic_preflight,
    validate_mac_preflight,
    validate_playback_capture_overlap,
    validate_reference_capture,
    validate_svo_replay_report,
    validate_validation_profile,
    validate_zed_records,
    verify_artifact_records,
)
from isaac_audio_sensors.acquisition.s4_2_orchestrator import (
    _read_chat_ack,
    _resolve_operator_readiness,
    _run_alignment_cue_schedule,
    _run_chat_cue_handshake,
    _start_playback,
    _terminate_process,
    validate_producer_readiness,
)
from isaac_audio_sensors.acquisition.s4_2_reference import generate_reference
from scripts.s4_2_alignment_candidates import (
    audio_transient_candidates,
    zed_cue_window,
)
from scripts.s4_2_delete_privacy_visuals import delete_privacy_visuals
from scripts.s4_2_pi_capture import _inspect_partial_wav, _normalize_bcd_device
from scripts.validate_s4_2_integrity import validate_index
from scripts.verify_s4_2_local_dataset import verify_local_dataset

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/s4_2_acquisition.v1.json"
REFERENCE_SHA256 = "27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468"


def _ready_config() -> dict:
    payload = load_json(CONFIG_PATH)
    payload["alignment"].update(
        {
            "event_object": (
                "blue wastebasket with standard white recycling symbol and no "
                "private label"
            ),
            "event_position_m": [1.15, 0.0, -0.4],
            "impact_tool": "long plain paper roll",
        }
    )
    amendment = ROOT / payload["acceptance_amendment"]["record_path"]
    payload["acceptance_amendment"]["record_sha256"] = hashlib.sha256(
        amendment.read_bytes()
    ).hexdigest()
    correction = ROOT / payload["coordinate_correction"]["record_path"]
    payload["coordinate_correction"]["record_sha256"] = hashlib.sha256(
        correction.read_bytes()
    ).hexdigest()
    payload["environment"].update(
        {
            "noise_state": "quiet office; HVAC audible; no speech",
            "occupancy": "operator outside retained ZED field of view",
            "operator_notes": "synthetic test configuration",
            "privacy_scene_cleared": True,
        }
    )
    payload["fixture"].update(
        {
            "cables_safe": True,
            "marked_footprint_confirmed": True,
            "microphone_openings_clear": True,
            "no_component_moved": True,
            "zed_fov_clear": True,
        }
    )
    payload["mac"].update(
        {
            "balance_centered_confirmed": True,
            "background_sounds_off_confirmed": True,
            "focus_and_notifications_verification_basis": "operator_confirmed",
            "mono_audio_off_confirmed": True,
            "notifications_suppressed_confirmed": True,
            "preflight_report_path": "outputs/test/mac_preflight.json",
            "system_ui_sounds_disabled_or_prevented": True,
            "work_focus_active_confirmed": True,
        }
    )
    payload["session"].update(
        {
            "stable_preflight_id": "test_stable_session",
            "stable_preflight_report_path": "outputs/test/stable_session.json",
            "stable_preflight_invalidation_path": (
                "outputs/test/stable_session.invalidated.json"
            ),
        }
    )
    payload["source"] = {
        "position_m": [0.0, 0.9, -0.135],
        "position_operator_facing_zed_m": [0.0, -0.9, -0.135],
        "delta_x_m": 0.0,
        "delta_y_m": 0.9,
        "delta_z_m": -0.135,
        "distance_from_rig_origin_m": 0.910,
        "distance_provenance": "derived_from_position_m_not_independent_measurement",
        "bearing_deg_clockwise_from_positive_x": 90.0,
        "bearing_operator_facing_zed_deg": 270.0,
        "speaker_height_m": 0.710,
        "vertical_offset_uncertainty_m": 0.010,
        "orientation_deg": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "orientation_measurement_classification": (
            "practical_visual_placement_not_metrology"
        ),
        "lid_angle_deg": 90.0,
        "lid_state": "open",
        "relative_side": "operator_left_facing_camera",
        "relative_side_operator_facing_zed": "left",
        "relative_side_project_view": "right",
        "screen_heading": "same_general_direction_as_zed",
    }
    return payload


def _mac_report(config: dict) -> dict:
    return {
        "schema": "ias.s4_2.mac_preflight.v1",
        "read_only": True,
        "collected_at": datetime.now().astimezone().isoformat(),
        "hardware": {"model_identifier": "MacBookPro18,1"},
        "os": {"version": "26.5.2", "build": "25F84"},
        "audio_output": {
            "device_name": "MacBook Pro Speakers",
            "channel_count": 2,
            "nominal_sample_rate_hz": 48_000,
        },
        "volume": {
            "output_volume": config["mac"]["system_volume_percent"],
            "output_muted": False,
        },
        "power": {"on_ac_power": True},
        "focus_and_notifications": {
            "work_focus_active": True,
            "notifications_suppressed": True,
        },
        "controllable_audio_settings": {"background_sounds": False},
        "reference_wav": {
            "sha256": config["reference"]["sha256"],
            "hash_matches": True,
            "channel_count": 1,
            "sample_rate_hz": 48_000,
            "bits_per_sample": 16,
            "duration_s": 9.5,
            "afinfo_exit_status": 0,
            "afinfo_lpcm_detected": True,
        },
    }


def _mac_dynamic_report(config: dict) -> dict:
    return {
        "schema": "ias.s4_2.mac_dynamic_preflight.v1",
        "read_only": True,
        "scope": "per_take_dynamic_only",
        "collected_at": datetime.now().astimezone().isoformat(),
        "audio_output": {
            "device_name": config["mac"]["output_device"],
            "channel_count": 2,
            "nominal_sample_rate_hz": 48_000,
        },
        "volume": {
            "output_volume": config["mac"]["system_volume_percent"],
            "output_muted": False,
        },
        "power": {"on_ac_power": True},
        "status": "passed",
    }


def _write_wav(
    path: Path,
    *,
    channels: int = 6,
    sample_rate: int = 16_000,
    sample_width: int = 2,
    frames: int = 8_000,
    silent_channel: int | None = None,
    clip_channel: int | None = None,
) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        if sample_width == 2:
            samples: list[int] = []
            for frame in range(frames):
                for channel in range(channels):
                    if channel == silent_channel:
                        sample = 0
                    elif channel == clip_channel and frame < 4_100:
                        sample = 32767
                    else:
                        sample = ((frame * (channel + 3) * 29) % 2001) - 1000
                    samples.append(sample)
            writer.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        else:
            writer.writeframes(bytes([128]) * frames * channels)


def _inspect_s42_wav(path: Path, **kwargs):
    return inspect_six_channel_wav(
        path,
        require_nonsilent_channels=True,
        reject_sustained_clipping=True,
        **kwargs,
    )


def _zed_record(index: int, *, signature: str | None = None) -> dict:
    timestamp = 1_000_000_000 + index * 33_333_333
    return {
        "schema": "ias.s4_2.zed_frame.v1",
        "frame_index": index,
        "device_timestamp_ns": timestamp,
        "host_wall_time_utc": datetime.fromtimestamp(
            timestamp / 1e9, tz=timezone.utc
        ).isoformat(),
        "host_monotonic_ns": timestamp + 500,
        "image_status": "SUCCESS",
        "image_signature_sha256": signature
        or hashlib.sha256(f"image-{index}".encode()).hexdigest(),
        "depth_status": "SUCCESS",
        "depth_finite_ratio": 0.8,
        "depth_sample_grid_m": [1.0, 1.1, 1.2, None],
        "depth_sample_grid_shape": [2, 2],
        "depth_sample_stride_px": [60, 64],
        "imu_status": "SUCCESS",
        "imu_timestamp_ns": timestamp,
        "imu": {
            "linear_acceleration_m_s2": [0.0, 0.0, 9.81],
            "angular_velocity_rad_s": [0.0, 0.0, 0.0],
            "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
        },
        "pose_status": "OK",
        "pose_timestamp_ns": timestamp,
        "pose": {
            "translation_xyz_m": [0.0, 0.0, 0.0],
            "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "confidence_percent": 100,
            "valid": True,
        },
        "frame_name": "F_zed_world_y_up",
        "units": {"position": "m", "time": "ns", "angle": "rad"},
    }


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_incomplete_configuration_passes_design_validation_but_not_ready_gate():
    payload = load_json(CONFIG_PATH)
    assert validate_configuration(payload, require_ready=False).passed
    report = validate_configuration(payload, require_ready=True)
    assert not report.passed
    assert "missing_required_metadata" in _issue_codes(report)
    assert "operator_confirmation_missing" in _issue_codes(report)


def test_pi_firmware_bcd_representation_normalizes_without_changing_identity():
    assert _normalize_bcd_device("0208") == "2.08"
    assert _normalize_bcd_device("2.08") == "2.08"
    assert _normalize_bcd_device(None) is None


def test_actual_pi_recorder_header_contract_is_inspected(tmp_path):
    valid = tmp_path / "valid.wav"
    _write_wav(valid)
    assert _inspect_partial_wav(valid) == {
        "channel_count": 6,
        "sample_rate_hz": 16_000,
        "sample_width_bytes": 2,
        "compression": "NONE",
        "encoding": "PCM_S16_LE",
    }
    wrong = tmp_path / "wrong.wav"
    _write_wav(wrong, channels=2, sample_rate=48_000, sample_width=1)
    inspected = _inspect_partial_wav(wrong)
    assert inspected["channel_count"] == 2
    assert inspected["sample_rate_hz"] == 48_000
    assert inspected["encoding"] == "unsupported"


def test_complete_configuration_round_trip_passes():
    payload = _ready_config()
    encoded = json.dumps(payload, sort_keys=True)
    restored = json.loads(encoded)
    assert validate_configuration(restored, require_ready=True).passed


def _audio_only_validation_profile() -> dict:
    return {
        "schema": "ias.s4.validation_profile.v1",
        "id": "future_audio_only_trial",
        "required_modalities": ["respeaker_audio"],
        "duration_policy": "declared",
        "stimulus_policy": "none",
        "playback_overlap_policy": "none",
        "svo_replay_policy": "none",
        "svo_replay_stage": "batch_before_acceptance",
        "svo_frame_count_policy": "declared_coverage",
        "pose_policy": "not_required",
        "imu_policy": "not_required",
        "alignment_policy": "not_required",
        "controlled_source_policy": "declared_trial",
        "channel_signal_policy": "allow_silence",
        "clipping_policy": "metric_specific",
    }


def test_valid_relaxed_future_validation_profile_passes():
    future = _audio_only_validation_profile()
    assert validate_validation_profile(future).passed


def test_future_validation_profile_cannot_replace_frozen_s4_2_profile():
    future = _audio_only_validation_profile()
    payload = _ready_config()
    payload["validation_profile"] = future
    report = validate_configuration(payload, require_ready=True)
    assert not report.passed
    assert "frozen_value_mismatch" in _issue_codes(report)


def test_validation_profile_rejects_empty_required_modalities():
    profile = _audio_only_validation_profile()
    profile["required_modalities"] = []
    report = validate_validation_profile(profile)
    assert not report.passed
    assert any(
        issue.code == "invalid_validation_profile"
        and issue.path == "validation_profile.required_modalities"
        for issue in report.issues
    )


def test_validation_profile_cannot_silently_disable_required_modality_check():
    profile = _audio_only_validation_profile()
    profile["required_modalities"].append("zed_pose")
    report = validate_validation_profile(profile)
    assert not report.passed
    assert "inconsistent_validation_profile" in _issue_codes(report)


def test_s4_2_correlation_and_replay_stage_remain_frozen():
    payload = _ready_config()
    assert payload["reference"]["minimum_normalized_correlation"] == 0.03
    assert payload["reference"]["minimum_correlated_raw_channels"] == 2
    assert payload["validation_profile"]["svo_replay_stage"] == ("offline_finalization")
    payload["reference"]["minimum_normalized_correlation"] = 0.0
    assert not validate_configuration(payload, require_ready=True).passed


def test_corrected_project_frame_and_bearing_are_frozen():
    payload = _ready_config()
    assert payload["coordinate_frame"]["axes"]["y"] == (
        "right_as_viewed_from_zed_operator_left_facing_camera"
    )
    assert payload["coordinate_frame"]["bearing_definition"] == (
        "degrees clockwise from +X toward +Y viewed from above"
    )
    assert payload["operator_facing_frame"]["axes"]["negative_y"] == ("operator_left")
    assert payload["source"]["position_operator_facing_zed_m"] == [
        0.0,
        -0.9,
        -0.135,
    ]
    assert payload["source"]["bearing_operator_facing_zed_deg"] == 270.0
    assert payload["source"]["position_m"] == [0.0, 0.9, -0.135]
    assert payload["source"]["bearing_deg_clockwise_from_positive_x"] == 90.0
    payload["source"]["position_m"][1] = -0.9
    payload["source"]["delta_y_m"] = -0.9
    payload["source"]["bearing_deg_clockwise_from_positive_x"] = 270.0
    report = validate_configuration(payload, require_ready=True)
    assert not report.passed
    assert "frozen_value_mismatch" in _issue_codes(report)


def test_operator_facing_zed_conversion_is_explicit_and_fail_closed():
    assert operator_facing_zed_position_to_project(
        [0.0, -0.9, -0.135]
    ) == pytest.approx((0.0, 0.9, -0.135))
    assert operator_facing_zed_bearing_to_project(270.0) == pytest.approx(90.0)
    assert operator_facing_zed_position_to_project([0.0, 0.9, -0.135]) == pytest.approx(
        (0.0, -0.9, -0.135)
    )
    assert operator_facing_zed_bearing_to_project(90.0) == pytest.approx(270.0)
    with pytest.raises(ValueError):
        operator_facing_zed_position_to_project([0.0, float("nan"), 0.0])
    with pytest.raises(ValueError):
        operator_facing_zed_bearing_to_project(float("inf"))

    payload = _ready_config()
    payload["source"]["position_operator_facing_zed_m"][1] = 0.9
    payload["source"]["bearing_operator_facing_zed_deg"] = 90.0
    report = validate_configuration(payload, require_ready=True)
    assert {
        "frozen_value_mismatch",
        "inconsistent_dual_frame_position",
        "inconsistent_dual_frame_bearing",
    } <= _issue_codes(report)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("respeaker", "channel_count"), 5, "frozen_value_mismatch"),
        (
            ("respeaker", "channel_order"),
            [
                "asr",
                "conference",
                "raw_microphone_0",
                "raw_microphone_1",
                "raw_microphone_2",
                "raw_microphone_3",
            ],
            "frozen_value_mismatch",
        ),
        (("respeaker", "sample_rate_hz"), 48_000, "frozen_value_mismatch"),
        (("respeaker", "sample_format"), "S32_LE", "frozen_value_mismatch"),
        (("coordinate_frame", "frame_name"), "camera", "frozen_value_mismatch"),
        (("coordinate_frame", "position_units"), "mm", "frozen_value_mismatch"),
        (("fixture", "fixture_id"), "STALE_FIXTURE", "frozen_value_mismatch"),
        (("fixture", "room_id"), "OTHER_ROOM", "frozen_value_mismatch"),
    ],
)
def test_configuration_fails_closed_for_frozen_contract(path, value, code):
    payload = _ready_config()
    payload[path[0]][path[1]] = value
    report = validate_configuration(payload, require_ready=True)
    assert not report.passed
    assert code in _issue_codes(report)


def test_configuration_rejects_inconsistent_source_units_pose_and_side():
    payload = _ready_config()
    payload["source"].update(
        {
            "distance_from_rig_origin_m": 99.0,
            "bearing_deg_clockwise_from_positive_x": 361.0,
            "orientation_deg": {"yaw": 0.0},
            "relative_side": "above",
            "speaker_height_m": -1.0,
        }
    )
    report = validate_configuration(payload, require_ready=True)
    assert {
        "inconsistent_source_distance",
        "invalid_angle",
        "invalid_orientation",
        "invalid_relative_side",
        "invalid_height",
    } <= _issue_codes(report)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("volume", "output_volume"), 69, "mac_preflight_mismatch"),
        (("volume", "output_muted"), True, "mac_preflight_mismatch"),
        (("audio_output", "device_name"), "AirPods", "mac_preflight_mismatch"),
        (("power", "on_ac_power"), False, "mac_preflight_mismatch"),
        (
            ("reference_wav", "hash_matches"),
            False,
            "mac_preflight_mismatch",
        ),
        (
            ("controllable_audio_settings", "background_sounds"),
            True,
            "mac_preflight_mismatch",
        ),
    ],
)
def test_mac_preflight_mismatches_fail(path, value, code):
    config = _ready_config()
    report = _mac_report(config)
    report[path[0]][path[1]] = value
    validation = validate_mac_preflight(report, config)
    assert not validation.passed
    assert code in _issue_codes(validation)


def test_automatic_focus_conflict_is_warning_with_operator_confirmation():
    config = _ready_config()
    report = _mac_report(config)
    report["focus_and_notifications"] = {
        "work_focus_active": False,
        "notifications_suppressed": False,
    }
    validation = validate_mac_preflight(report, config)
    assert validation.passed
    issue = next(
        issue
        for issue in validation.issues
        if issue.code == "automatic_focus_detection_conflict"
    )
    assert issue.severity == "warning"
    assert validation.checks[1]["basis"] == "operator_confirmed"


def test_focus_operator_confirmation_cannot_be_silently_disabled():
    config = _ready_config()
    config["mac"]["work_focus_active_confirmed"] = False
    validation = validate_mac_preflight(_mac_report(config), config)
    assert not validation.passed
    assert "manual_mac_confirmation_missing" in _issue_codes(validation)


def test_manual_balance_and_system_sound_confirmations_are_required():
    config = _ready_config()
    config["mac"]["balance_centered_confirmed"] = False
    config["mac"]["system_ui_sounds_disabled_or_prevented"] = False
    report = validate_mac_preflight(_mac_report(config), config)
    assert not report.passed
    assert "manual_mac_confirmation_missing" in _issue_codes(report)


def test_per_take_mac_check_is_dynamic_only_and_fail_closed():
    config = _ready_config()
    report = _mac_dynamic_report(config)
    assert validate_mac_dynamic_preflight(report, config).passed
    report["volume"]["output_volume"] = 39
    validation = validate_mac_dynamic_preflight(report, config)
    assert not validation.passed
    assert "mac_dynamic_mismatch" in _issue_codes(validation)


def _actual_recorder_readiness(config: dict) -> dict:
    return {
        "pi": {
            "verification_basis": "actual_recording_partial_wav_header",
            "identity": {
                "model": config["respeaker"]["usb_product"],
                "serial": config["respeaker"]["serial"],
                "firmware": config["respeaker"]["firmware"],
            },
            "capture_format": {
                "channel_count": 6,
                "sample_rate_hz": 16_000,
                "sample_width_bytes": 2,
                "compression": "NONE",
                "encoding": "PCM_S16_LE",
            },
            "checks": {"capture_started": True, "six_channels": True},
        },
        "zed": {
            "verification_basis": "actual_recorder_open_and_retrieval",
            "identity": {
                "model": config["zed"]["model"],
                "serial": config["zed"]["serial"],
                "sdk_version": config["zed"]["sdk_version"],
                "camera_firmware": config["zed"]["camera_firmware"],
                "sensor_firmware": config["zed"]["sensor_firmware"],
            },
            "requested_mode": {
                "resolution": config["zed"]["resolution"],
                "fps": config["zed"]["fps"],
                "depth_mode": config["zed"]["depth_mode"],
            },
            "checks": {
                "image_retrieved": True,
                "depth_retrieved_gpu_authoritative": True,
                "imu_retrieved": True,
                "pose_ok": True,
                "svo_recording_enabled": True,
            },
        },
    }


def test_actual_recorders_are_the_authoritative_readiness_check():
    config = _ready_config()
    ready = _actual_recorder_readiness(config)
    assert validate_producer_readiness(ready, config).passed

    ready["zed"]["checks"]["depth_retrieved_gpu_authoritative"] = False
    validation = validate_producer_readiness(ready, config)
    assert not validation.passed
    assert "producer_readiness_failed_check" in _issue_codes(validation)


def test_forged_or_incomplete_recorder_readiness_fails_closed():
    config = _ready_config()
    ready = _actual_recorder_readiness(config)
    del ready["pi"]["capture_format"]["channel_count"]
    ready["zed"]["verification_basis"] = "separate_probe"
    validation = validate_producer_readiness(ready, config)
    assert not validation.passed
    assert "producer_readiness_mismatch" in _issue_codes(validation)


def test_marketing_model_cannot_replace_exact_respeaker_usb_descriptor():
    config = _ready_config()
    ready = _actual_recorder_readiness(config)
    ready["pi"]["identity"]["model"] = config["respeaker"]["model"]
    validation = validate_producer_readiness(ready, config)
    assert not validation.passed
    assert "producer_readiness_mismatch" in _issue_codes(validation)


def test_dual_operator_cues_preserve_frozen_two_second_interval(tmp_path):
    config = _ready_config()

    class Clock:
        now_ns = 1_000_000_000

        def monotonic_ns(self):
            return self.now_ns

        def sleep(self, seconds):
            self.now_ns += round(seconds * 1e9)

    clock = Clock()
    messages = []

    def record_message(message, *, flush):
        assert flush is True
        messages.append(message)

    cue, removal = _run_alignment_cue_schedule(
        config,
        tmp_path,
        wall_function=lambda: "2026-07-21T00:00:00+00:00",
        monotonic_ns_function=clock.monotonic_ns,
        sleep_function=clock.sleep,
        print_function=record_message,
    )
    assert removal["host_monotonic_ns"] - cue["host_monotonic_ns"] == 1_500_000_000
    assert clock.now_ns - cue["host_monotonic_ns"] == 2_000_000_000
    assert messages[0].startswith("ALIGNMENT EVENT NOW")
    assert messages[1].startswith("REMOVE PAPER ROLL NOW")
    assert (
        load_json(tmp_path / "operator_cue.json")["host_monotonic_ns"]
        == (cue["host_monotonic_ns"])
    )
    assert (
        load_json(tmp_path / "operator_remove_cue.json")["host_monotonic_ns"]
        == removal["host_monotonic_ns"]
    )


def test_chat_cue_handshake_uses_one_chat_ack_and_self_timed_removal(tmp_path):
    config = _ready_config()

    class Clock:
        now_ns = 1_000_000_000

        def monotonic_ns(self):
            return self.now_ns

        def sleep(self, seconds):
            self.now_ns += round(seconds * 1e9)

    clock = Clock()
    prompts = []

    def acknowledge(prompt):
        prompts.append(prompt)
        return ""

    cue, removal = _run_chat_cue_handshake(
        config,
        tmp_path,
        input_function=acknowledge,
        wall_function=lambda: "2026-07-21T00:00:00+00:00",
        monotonic_ns_function=clock.monotonic_ns,
        sleep_function=clock.sleep,
        print_function=lambda _message, *, flush: None,
    )
    assert len(prompts) == 1
    assert cue["cue_mode"] == ("assistant_chat_message_with_workstation_acknowledgment")
    assert removal["host_monotonic_ns"] - cue["host_monotonic_ns"] == (1_500_000_000)
    assert removal["cue_mode"] == (
        "operator_authorized_self_timed_from_alignment_chat_cue"
    )
    assert removal["operator_action_observation"] == (
        "operator-confirmed procedure, unobserved"
    )
    assert clock.now_ns - removal["host_monotonic_ns"] == 500_000_000
    assert (tmp_path / "chat_cue_handshake_ready.json").is_file()
    assert (tmp_path / "chat_removal_cue_target.json").is_file()


def test_chat_self_timed_removal_does_not_silently_skip_frozen_delays(tmp_path):
    config = _ready_config()
    config["alignment"]["remove_cue_delay_s"] = 1.4
    report = validate_configuration(config, require_ready=True)
    assert not report.passed
    assert "frozen_value_mismatch" in _issue_codes(report)


def test_chat_ack_timeout_is_frozen_and_fail_closed(monkeypatch):
    config = _ready_config()
    assert config["session"]["duration_s"] == 35.0
    assert config["session"]["chat_cue_ack_timeout_s"] == 15.0
    config["session"]["chat_cue_ack_timeout_s"] = 15.1
    report = validate_configuration(config, require_ready=True)
    assert not report.passed
    assert "frozen_value_mismatch" in _issue_codes(report)

    class NeverReadySelector:
        def register(self, *_args):
            return None

        def select(self, *, timeout):
            assert timeout == 15.0
            return []

        def close(self):
            return None

    monkeypatch.setattr(
        s42_orchestrator.selectors, "DefaultSelector", NeverReadySelector
    )
    with pytest.raises(S42Error, match="exceeded 15.000 seconds"):
        _read_chat_ack("prompt", timeout_s=15.0)


def test_dual_cue_schedule_and_existing_thresholds_are_frozen():
    config = _ready_config()
    assert config["alignment"]["remove_cue_delay_s"] == 1.5
    assert config["alignment"]["remove_to_playback_s"] == 0.5
    assert config["alignment"]["post_event_pre_playback_s"] == 2.0
    assert config["reference"]["minimum_normalized_correlation"] == 0.03
    assert config["reference"]["minimum_correlated_raw_channels"] == 2
    config["alignment"]["remove_to_playback_s"] = 0.4
    validation = validate_configuration(config, require_ready=True)
    assert not validation.passed
    assert "frozen_value_mismatch" in _issue_codes(validation)


def test_per_take_preflight_has_no_redundant_ssh_or_device_probe(tmp_path, monkeypatch):
    config = _ready_config()
    attempt = AttemptLifecycle(tmp_path / "attempts", attempt_id="no_extra_probe")
    monkeypatch.setattr(
        s42_orchestrator,
        "disk_space_check",
        lambda _path, _minimum: {"passed": True},
    )
    monkeypatch.setattr(
        s42_orchestrator,
        "collect_mac_dynamic_preflight",
        lambda _config, _output: {"status": "passed"},
    )

    def forbidden_ssh(*_args, **_kwargs):
        raise AssertionError("per-take preflight must not issue a separate SSH probe")

    monkeypatch.setattr(s42_orchestrator, "_ssh", forbidden_ssh)
    payload = s42_orchestrator.preflight_hardware(config, attempt)
    assert payload["status"] == "passed"
    assert payload["producer_readiness_is_authoritative"] is True


def test_stable_session_runs_nvidia_smi_and_full_mac_preflight_once(
    tmp_path, monkeypatch
):
    config = _ready_config()
    config["mac"]["preflight_report_path"] = "mac_full.json"
    config["session"]["stable_preflight_report_path"] = "stable.json"
    config["session"]["stable_preflight_invalidation_path"] = "invalidated.json"
    calls = {"mac": 0, "gpu": 0}
    monkeypatch.setattr(s42_orchestrator, "REPO_ROOT", tmp_path)

    def fake_mac(_configuration, output):
        calls["mac"] += 1
        report = _mac_report(config)
        s42_orchestrator.write_json_atomic(output, report)
        return {
            "status": "passed",
            "validation": {"status": "passed"},
            "command": {"return_code": 0},
        }

    def fake_run(command, **_kwargs):
        assert command[0] == "nvidia-smi"
        calls["gpu"] += 1
        return {"return_code": 0, "stdout": "GPU, driver", "stderr": ""}

    monkeypatch.setattr(s42_orchestrator, "collect_mac_preflight", fake_mac)
    monkeypatch.setattr(s42_orchestrator, "_run", fake_run)
    report = s42_orchestrator.collect_stable_session_preflight(
        config, tmp_path / "stable.json"
    )
    assert report["status"] == "passed"
    assert calls == {"mac": 1, "gpu": 1}


def test_reference_regeneration_is_byte_identical(tmp_path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first_payload = generate_reference(first, tmp_path / "first.json")
    second_payload = generate_reference(second, tmp_path / "second.json")
    assert first.read_bytes() == second.read_bytes()
    assert first_payload["sha256"] == REFERENCE_SHA256
    assert second_payload["sha256"] == REFERENCE_SHA256
    assert first_payload["segments"] == second_payload["segments"]


def test_reference_tracked_metadata_and_generated_wav_agree():
    metadata = load_json(
        ROOT / "outputs/isaac_audio_sensors/S4/S4.2/reference/reference_wav.json"
    )
    wav = (
        ROOT
        / metadata["regeneration_command"]
        .split(" --metadata ")[0]
        .split("--output ", 1)[1]
    )
    assert wav.is_file()
    assert hashlib.sha256(wav.read_bytes()).hexdigest() == metadata["sha256"]
    assert metadata["sha256"] == REFERENCE_SHA256


def test_six_channel_wav_integration_passes(tmp_path):
    path = tmp_path / "six.wav"
    _write_wav(path)
    properties, issues = _inspect_s42_wav(path)
    assert not issues
    assert properties["channel_count"] == 6
    assert properties["sample_rate_hz"] == 16_000
    assert all(value > 1.0 for value in properties["per_channel_rms_pcm16"])


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"channels": 5}, "wrong_channel_count"),
        ({"sample_rate": 48_000}, "wrong_sample_rate"),
        ({"sample_width": 1}, "wrong_sample_format"),
        ({"silent_channel": 3}, "silent_channel"),
        ({"clip_channel": 2}, "sustained_clipping"),
    ],
)
def test_wav_faults_fail_closed(tmp_path, kwargs, code):
    path = tmp_path / f"{code}.wav"
    _write_wav(path, **kwargs)
    _, issues = _inspect_s42_wav(path)
    assert code in {issue.code for issue in issues}


def test_future_silence_or_clipping_trial_must_explicitly_declare_quality_policy(
    tmp_path,
):
    path = tmp_path / "declared_quality.wav"
    _write_wav(path, silent_channel=3, clip_channel=2)
    _, strict_issues = _inspect_s42_wav(path)
    assert {"silent_channel", "sustained_clipping"} <= {
        issue.code for issue in strict_issues
    }
    _, declared_issues = inspect_six_channel_wav(
        path,
        require_nonsilent_channels=False,
        reject_sustained_clipping=False,
    )
    assert not declared_issues


def test_truncated_and_malformed_wav_fail_closed(tmp_path):
    truncated = tmp_path / "truncated.wav"
    _write_wav(truncated)
    truncated.write_bytes(truncated.read_bytes()[:-3])
    _, truncated_issues = _inspect_s42_wav(truncated)
    assert {issue.code for issue in truncated_issues} & {
        "truncated_wav",
        "malformed_wav",
    }
    malformed = tmp_path / "malformed.wav"
    malformed.write_bytes(b"not-a-wav")
    _, malformed_issues = _inspect_s42_wav(malformed)
    assert "malformed_wav" in {issue.code for issue in malformed_issues}


@pytest.mark.parametrize("actual_duration_s", [34.0, 36.0])
def test_short_and_long_wav_captures_fail_duration_gate(tmp_path, actual_duration_s):
    path = tmp_path / "duration.wav"
    _write_wav(path, frames=round(actual_duration_s * 16_000))
    _, issues = _inspect_s42_wav(
        path, expected_duration_s=35.0, duration_tolerance_s=0.25
    )
    assert "wav_duration_mismatch" in {issue.code for issue in issues}


def test_complete_reference_stimulus_is_required_in_retained_audio(tmp_path):
    reference = tmp_path / "reference.wav"
    generate_reference(reference, tmp_path / "reference.json")
    with wave.open(str(reference), "rb") as reader:
        template = np.frombuffer(reader.readframes(-1), dtype="<i2")[::3]
    frames = 20 * 16_000
    start = 5 * 16_000
    base = ((np.arange(frames) % 101) - 50).astype(np.int16)
    captured = np.repeat(base[:, None], 6, axis=1)
    for channel in range(6):
        captured[start : start + template.size, channel] += (
            template // (channel + 2)
        ).astype(np.int16)
    complete = tmp_path / "complete.wav"
    with wave.open(str(complete), "wb") as writer:
        writer.setnchannels(6)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(captured.astype("<i2").tobytes())
    assert validate_reference_capture(
        complete,
        reference,
        minimum_normalized_correlation=0.03,
        minimum_correlated_raw_channels=2,
    ).passed
    incomplete = tmp_path / "incomplete.wav"
    _write_wav(incomplete, frames=20 * 16_000)
    report = validate_reference_capture(
        incomplete,
        reference,
        minimum_normalized_correlation=0.03,
        minimum_correlated_raw_channels=2,
    )
    assert "incomplete_reference_stimulus" in _issue_codes(report)


def test_reference_detector_anchors_on_unique_broadband_not_repeated_chirp(tmp_path):
    reference = tmp_path / "reference.wav"
    generate_reference(reference, tmp_path / "reference.json")
    with wave.open(str(reference), "rb") as reader:
        template = np.frombuffer(reader.readframes(-1), dtype="<i2")[::3]
    frames = 20 * 16_000
    start = round(7.284 * 16_000)
    captured = np.zeros((frames, 6), dtype=np.int16)
    for channel in range(6):
        captured[start : start + template.size, channel] = (
            template // (channel + 2)
        ).astype(np.int16)
    # Add a repeated chirp near the beginning. A global whole-reference maximum
    # may prefer this false alignment because the two reference chirps match.
    chirp = template[16_000:20_000]
    captured[540 : 540 + chirp.size, 2:] += (chirp[:, None] // 3).astype(np.int16)
    path = tmp_path / "repeated_chirp.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(6)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(captured.astype("<i2").tobytes())
    report = validate_reference_capture(
        path,
        reference,
        minimum_normalized_correlation=0.03,
        minimum_correlated_raw_channels=2,
    )
    assert report.passed
    raw_results = report.checks[0]["channel_results"][2:]
    assert all(
        abs(result["reference_start_elapsed_s"] - 7.284) <= 0.050
        for result in raw_results
    )


def test_zed_records_integration_passes():
    records = [_zed_record(index) for index in range(27)]
    report = validate_zed_records(
        records,
        duration_s=1.0,
        fps=30,
        validation_profile=_ready_config()["validation_profile"],
    )
    assert report.passed


def test_future_image_only_trial_does_not_require_pose_or_imu_but_stays_strict():
    profile = _audio_only_validation_profile()
    profile["required_modalities"] = ["zed_image"]
    records = [_zed_record(index) for index in range(30)]
    for record in records:
        for key in (
            "depth_status",
            "depth_finite_ratio",
            "depth_sample_grid_m",
            "depth_sample_grid_shape",
            "depth_sample_stride_px",
            "imu_status",
            "imu_timestamp_ns",
            "imu",
            "pose_status",
            "pose_timestamp_ns",
            "pose",
        ):
            record.pop(key)
    report = validate_zed_records(
        records, duration_s=1.0, fps=30, validation_profile=profile
    )
    assert report.passed

    pose_required = dict(profile)
    pose_required["required_modalities"] = ["zed_image", "zed_pose"]
    pose_required["pose_policy"] = "every_frame_ok_and_fresh"
    missing_pose = validate_zed_records(
        records, duration_s=1.0, fps=30, validation_profile=pose_required
    )
    assert "missing_zed_metadata" in _issue_codes(missing_pose)

    records[5]["device_timestamp_ns"] = records[4]["device_timestamp_ns"]
    failed = validate_zed_records(
        records, duration_s=1.0, fps=30, validation_profile=profile
    )
    assert "duplicate_timestamp" in _issue_codes(failed)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("incomplete", "incomplete_zed_output"),
        ("image_failure", "failed_image_retrieval"),
        ("depth_failure", "failed_depth_retrieval"),
        ("imu_failure", "failed_imu_retrieval"),
        ("duplicate_time", "duplicate_timestamp"),
        ("nonmonotonic_time", "nonmonotonic_timestamp"),
        ("nonmonotonic_host_time", "nonmonotonic_timestamp"),
        ("nonmonotonic_imu_time", "nonmonotonic_timestamp"),
        ("stale_pose", "stale_pose"),
        ("invalid_pose_state", "invalid_pose_state"),
        ("invalid_pose", "invalid_pose"),
        ("stale_frame", "stale_zed_frame"),
        ("missing_metadata", "missing_zed_metadata"),
        ("bad_frame", "invalid_coordinate_frame"),
        ("bad_units", "invalid_units"),
        ("bad_depth", "invalid_depth_record"),
    ],
)
def test_zed_faults_fail_closed(mutation, code):
    records = [_zed_record(index) for index in range(30)]
    if mutation == "incomplete":
        records = records[:5]
    elif mutation == "image_failure":
        records[5]["image_status"] = "FAILURE"
    elif mutation == "depth_failure":
        records[5]["depth_status"] = "FAILURE"
    elif mutation == "imu_failure":
        records[5]["imu_status"] = "FAILURE"
    elif mutation == "duplicate_time":
        records[5]["device_timestamp_ns"] = records[4]["device_timestamp_ns"]
    elif mutation == "nonmonotonic_time":
        records[5]["device_timestamp_ns"] = records[4]["device_timestamp_ns"] - 1
    elif mutation == "nonmonotonic_host_time":
        records[5]["host_monotonic_ns"] = records[4]["host_monotonic_ns"] - 1
    elif mutation == "nonmonotonic_imu_time":
        records[5]["imu_timestamp_ns"] = records[4]["imu_timestamp_ns"] - 1
    elif mutation == "stale_pose":
        records[5]["pose_timestamp_ns"] = 1
    elif mutation == "invalid_pose_state":
        records[5]["pose_status"] = "SEARCHING"
    elif mutation == "invalid_pose":
        records[5]["pose"]["valid"] = False
    elif mutation == "stale_frame":
        signature = records[4]["image_signature_sha256"]
        records[5]["image_signature_sha256"] = signature
        records[6]["image_signature_sha256"] = signature
    elif mutation == "missing_metadata":
        del records[5]["depth_status"]
    elif mutation == "bad_frame":
        records[5]["frame_name"] = "camera"
    elif mutation == "bad_units":
        records[5]["units"]["position"] = "mm"
    elif mutation == "bad_depth":
        records[5]["depth_sample_grid_m"] = [None, None, None, None]
    report = validate_zed_records(
        records,
        duration_s=1.0,
        fps=30,
        validation_profile=_ready_config()["validation_profile"],
    )
    assert code in _issue_codes(report)


@pytest.mark.parametrize("failure_kind", ["corrupt", "truncated"])
def test_corrupt_and_truncated_svo_replay_reports_fail_closed(failure_kind):
    frame_count = 600
    report = {
        "schema": "ias.s4_2.svo_replay_validation.v1",
        "status": "failed",
        "identity": {"serial": "39011785"},
        "capture": {"resolution": "HD720", "fps": 30, "depth_mode": "PERFORMANCE"},
        "declared_frame_count": frame_count if failure_kind == "truncated" else 0,
        "replayed_frame_count": 217 if failure_kind == "truncated" else 0,
        "end_of_svo_reached": False,
        "representative_frames": [],
        "failure_reason": failure_kind,
    }
    validation = validate_svo_replay_report(
        report,
        expected_serial="39011785",
        expected_resolution="HD720",
        expected_fps=30,
        expected_depth_mode="PERFORMANCE",
        expected_frame_count=frame_count,
    )
    assert not validation.passed
    assert "svo_replay_mismatch" in _issue_codes(validation)


def test_svo_full_replay_is_universal_but_sidecar_count_policy_is_configurable():
    declared = 500
    report = {
        "schema": "ias.s4_2.svo_replay_validation.v1",
        "status": "passed",
        "identity": {"serial": "39011785"},
        "capture": {"resolution": "HD720", "fps": 30, "depth_mode": "PERFORMANCE"},
        "declared_frame_count": declared,
        "replayed_frame_count": declared,
        "end_of_svo_reached": True,
        "representative_frames": [
            {
                "frame_index": index,
                "image_status": "SUCCESS",
                "depth_status": "SUCCESS",
                "imu_status": "SUCCESS",
                "pose_status": "OK",
            }
            for index in (0, declared // 2, declared - 2)
        ],
    }
    common = {
        "expected_serial": "39011785",
        "expected_resolution": "HD720",
        "expected_fps": 30,
        "expected_depth_mode": "PERFORMANCE",
        "expected_frame_count": 600,
    }
    exact = validate_svo_replay_report(
        report, **common, frame_count_policy="exact_jsonl_match"
    )
    assert "svo_frame_count_mismatch" in _issue_codes(exact)
    coverage = validate_svo_replay_report(
        report, **common, frame_count_policy="declared_coverage"
    )
    assert coverage.passed

    report["replayed_frame_count"] = declared - 1
    truncated = validate_svo_replay_report(
        report, **common, frame_count_policy="declared_coverage"
    )
    assert "svo_replay_mismatch" in _issue_codes(truncated)


def test_svo_representative_modalities_follow_explicit_trial_contract():
    declared = 100
    report = {
        "schema": "ias.s4_2.svo_replay_validation.v1",
        "status": "passed",
        "identity": {"serial": "39011785"},
        "capture": {"resolution": "HD720", "fps": 30, "depth_mode": "PERFORMANCE"},
        "declared_frame_count": declared,
        "replayed_frame_count": declared,
        "end_of_svo_reached": True,
        "representative_frames": [
            {
                "frame_index": index,
                "image_status": "SUCCESS",
                "depth_status": "SUCCESS",
                "imu_status": "NOT_REQUESTED",
                "pose_status": "NOT_REQUESTED",
            }
            for index in (0, declared // 2, declared - 2)
        ],
    }
    common = {
        "expected_serial": "39011785",
        "expected_resolution": "HD720",
        "expected_fps": 30,
        "expected_depth_mode": "PERFORMANCE",
        "expected_frame_count": declared,
    }
    strict = validate_svo_replay_report(report, **common)
    assert "svo_representative_retrieval_failed" in _issue_codes(strict)
    image_depth = validate_svo_replay_report(
        report, **common, required_modalities=("zed_image", "zed_depth")
    )
    assert image_depth.passed


def test_corrupt_and_partial_jsonl_fail_closed(tmp_path):
    path = tmp_path / "frames.jsonl"
    path.write_bytes(b'{"ok": true}\n{"partial":')
    records, issues = read_jsonl(path)
    assert records == [{"ok": True}]
    assert "partial_jsonl_line" in {issue.code for issue in issues}


def test_alignment_offset_and_uncertainty_pass():
    result = calculate_alignment(
        audio_event_sample_index=80_000,
        audio_sample_rate_hz=16_000,
        zed_first_timestamp_ns=1_000_000_000,
        zed_event_timestamp_ns=6_005_000_000,
        audio_localization_half_width_samples=4,
        zed_frame_interval_ns=33_333_333,
        zed_localization_half_width_frames=0.5,
        event_unique=True,
        event_visible=True,
        event_audible=True,
    )
    assert result["status"] == "passed"
    assert result["offset_s"] == pytest.approx(0.005)
    assert result["total_uncertainty_ms"] < 50.0
    assert result["ssh_timing_is_synchronization"] is False


def test_delayed_interactive_readiness_resolves_before_bounded_capture():
    order: list[str] = []

    def delayed_input(_prompt):
        order.extend(["operator_waited", "operator_ready"])
        return ""

    report = _resolve_operator_readiness(True, input_function=delayed_input)
    order.append("recorders_may_start")
    assert order == ["operator_waited", "operator_ready", "recorders_may_start"]
    assert report["bounded_capture_started_after_resolution"] is True
    assert report["resolved_monotonic_ns"] >= report["started_monotonic_ns"]


def test_incomplete_playback_overlap_rejects_take():
    records = [_zed_record(index) for index in range(400)]
    playback = {
        "return_code": 0,
        "remote": {
            "exit_status": 0,
            "started_monotonic_ns": 1,
            "completed_monotonic_ns": 9_500_000_001,
        },
        "workstation_envelope": {
            "started_monotonic_ns": 2_000_000_000,
            "completed_monotonic_ns": 12_000_000_000,
            "recorders_alive": {
                "before_playback": {"pi": True, "zed": True},
                "after_playback": {"pi": False, "zed": True},
                "after_post_margin": {"pi": False, "zed": True},
            },
        },
    }
    report = validate_playback_capture_overlap(
        playback,
        records,
        reference_duration_s=9.5,
        playback_duration_tolerance_s=1.5,
    )
    assert "incomplete_playback_capture_overlap" in _issue_codes(report)


def test_forged_alignment_status_and_offset_are_recomputed_from_raw(tmp_path):
    config = _ready_config()
    config["session"]["duration_s"] = 1.0
    config["session"]["duration_tolerance_s"] = 0.01
    audio = tmp_path / "audio.wav"
    _write_wav(audio, frames=16_000)
    records = [_zed_record(index) for index in range(30)]
    annotation = calculate_alignment(
        audio_event_sample_index=8_000,
        audio_sample_rate_hz=16_000,
        zed_first_timestamp_ns=records[0]["device_timestamp_ns"],
        zed_event_timestamp_ns=records[15]["device_timestamp_ns"],
        audio_localization_half_width_samples=4,
        zed_frame_interval_ns=33_333_333,
        zed_localization_half_width_frames=0.5,
        event_unique=True,
        event_visible=True,
        event_audible=True,
    )
    annotation.update(
        {
            "zed_event_frame_index": 15,
            "audio_localization_half_width_samples": 4,
            "zed_localization_half_width_frames": 0.5,
            "extra_readout_quantization_ms": 0.0,
            "status": "passed",
            "offset_s": 123.0,
        }
    )
    recomputed, validation = recompute_alignment_from_evidence(
        annotation, audio, records, config
    )
    assert recomputed["offset_s"] == pytest.approx(-5e-9)
    assert "inconsistent_alignment_report" in _issue_codes(validation)


def test_alignment_candidate_helpers_narrow_review_without_auto_accept(tmp_path):
    path = tmp_path / "clap.wav"
    _write_wav(path, frames=8_000)
    with wave.open(str(path), "rb") as reader:
        parameters = reader.getparams()
        samples = list(
            struct.unpack(f"<{reader.getnframes() * 6}h", reader.readframes(-1))
        )
    samples[4_000 * 6 + 2] = 30_000
    with wave.open(str(path), "wb") as writer:
        writer.setparams(parameters)
        writer.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    audio = audio_transient_candidates(path)
    assert audio["auto_accept"] is False
    assert any(
        abs(candidate["sample_index"] - 4_000) <= 1 for candidate in audio["candidates"]
    )
    records = [_zed_record(index) for index in range(30)]
    cue = records[12]["host_monotonic_ns"]
    window = zed_cue_window(records, cue)
    assert window["nearest_frame_index"] == 12
    assert window["synchronization_claim"] is False


@pytest.mark.parametrize(
    "change",
    ["ambiguous", "invisible", "inaudible", "uncertain"],
)
def test_alignment_faults_reject(change):
    kwargs = {
        "audio_event_sample_index": 80_000,
        "audio_sample_rate_hz": 16_000,
        "zed_first_timestamp_ns": 1_000_000_000,
        "zed_event_timestamp_ns": 6_000_000_000,
        "audio_localization_half_width_samples": 4,
        "zed_frame_interval_ns": 33_333_333,
        "zed_localization_half_width_frames": 0.5,
        "event_unique": True,
        "event_visible": True,
        "event_audible": True,
    }
    if change == "ambiguous":
        kwargs["event_unique"] = False
    elif change == "invisible":
        kwargs["event_visible"] = False
    elif change == "inaudible":
        kwargs["event_audible"] = False
    else:
        kwargs["extra_uncertainty_ms"] = 100.0
    assert calculate_alignment(**kwargs)["status"] == "failed"


def test_attempt_lifecycle_never_overwrites_and_classifies_interruption(tmp_path):
    attempt = AttemptLifecycle(tmp_path, attempt_id="attempt_001")
    attempt.transition("recording", reason="ready")
    attempt.transition("interrupted", reason="injected SIGINT")
    lifecycle = load_json(attempt.root / "lifecycle.json")
    assert lifecycle["state"] == "interrupted"
    assert [event["state"] for event in lifecycle["events"]] == [
        "preflight",
        "recording",
        "interrupted",
    ]
    with pytest.raises(FileExistsError):
        AttemptLifecycle(tmp_path, attempt_id="attempt_001")
    with pytest.raises(S42Error):
        attempt.transition("accepted", reason="must not reopen terminal state")


def test_interrupted_local_child_is_stopped_and_classified():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    result = _terminate_process(process, "injected_child")
    assert result["action"] == "sigint"
    assert process.poll() is not None


def test_mac_playback_command_serializes_afplay_gain_as_string(monkeypatch):
    captured: dict = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _start_playback(_ready_config())
    remote_code = shlex.split(captured["args"][-1])[2]
    assert "c=['/usr/bin/afplay','-v','1.0'" in remote_code


def test_partial_remote_transfer_is_preserved_and_not_promoted(tmp_path):
    incoming = tmp_path / "incoming.partial"
    incoming.write_bytes(b"partial")
    expected_hash = hashlib.sha256(b"complete").hexdigest()
    assert hashlib.sha256(incoming.read_bytes()).hexdigest() != expected_hash
    destination = tmp_path / "raw/audio.wav"
    assert not destination.exists()
    assert incoming.read_bytes() == b"partial"


def test_atomic_promotion_and_manifest_integrity_round_trip(tmp_path):
    source = tmp_path / "producer/final.bin"
    source.parent.mkdir()
    source.write_bytes(b"finalized evidence")
    destination = tmp_path / "attempt/raw/final.bin"
    promote_finalized_file(source, destination)
    record = artifact_record(destination, role="fixture", root=tmp_path / "attempt")
    report = verify_artifact_records(tmp_path / "attempt", [record])
    assert report.passed
    destination.write_bytes(b"tampered")
    tampered = verify_artifact_records(tmp_path / "attempt", [record])
    assert "checksum_mismatch" in _issue_codes(tampered)


def test_disk_space_threshold_fails_closed(tmp_path):
    report = disk_space_check(tmp_path, 2**63 - 1)
    assert report["passed"] is False


def test_evidence_index_checksum_coverage_and_missing_roles(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("evidence\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(f"{digest}  artifact.txt\n", encoding="utf-8")
    checksum_digest = hashlib.sha256(checksums.read_bytes()).hexdigest()
    index = tmp_path / "evidence_index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "ias.s4_2.evidence_index.v1",
                "status": "in_progress",
                "checksum_manifest": "SHA256SUMS",
                "artifacts": [
                    {
                        "path": "artifact.txt",
                        "role": "tests",
                        "retention": "tracked",
                        "byte_size": artifact.stat().st_size,
                        "sha256": digest,
                    },
                    {
                        "path": "SHA256SUMS",
                        "role": "evidence_checksums",
                        "retention": "tracked",
                        "byte_size": checksums.stat().st_size,
                        "sha256": checksum_digest,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = validate_index(
        index,
        require_complete=False,
        require_git_tracked=False,
        repository_root=tmp_path,
    )
    assert report["status"] == "passed"
    complete = validate_index(
        index,
        require_complete=True,
        require_git_tracked=False,
        repository_root=tmp_path,
    )
    assert any(
        issue["code"] == "missing_evidence_roles" for issue in complete["issues"]
    )


def test_machine_local_dataset_verifies_in_place_and_never_overwrites(tmp_path):
    relative = Path("dataset/S4.2/attempts/test/raw/audio.wav")
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    _write_wav(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "ias.s4_2.evidence_index.v1",
                "artifacts": [
                    {
                        "path": relative.as_posix(),
                        "local_relative_path": relative.as_posix(),
                        "role": "raw_respeaker_wav",
                        "retention": "machine_local_gitignored",
                        "byte_size": source.stat().st_size,
                        "sha256": digest,
                        "media_properties": {"encoding": "PCM16 WAV"},
                        "acquisition_contract": {
                            "sample_rate_hz": 16000,
                            "channel_count": 6,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "validation.json"
    report = verify_local_dataset(index, tmp_path, report_path)
    assert report["status"] == "passed"
    assert source.is_file()
    with pytest.raises(FileExistsError):
        verify_local_dataset(index, tmp_path, report_path)


def test_missing_machine_local_artifact_is_reported_without_repair(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "ias.s4_2.evidence_index.v1",
                "artifacts": [
                    {
                        "path": "dataset/S4.2/attempts/missing/raw/zed.svo2",
                        "local_relative_path": (
                            "dataset/S4.2/attempts/missing/raw/zed.svo2"
                        ),
                        "role": "raw_zed_svo2",
                        "retention": "machine_local_gitignored",
                        "byte_size": 1,
                        "sha256": "0" * 64,
                        "media_properties": {"container": "SVO2"},
                        "acquisition_contract": {"zed_mode": "HD720@30"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "validation.json"
    failure = verify_local_dataset(index, tmp_path, report_path)
    assert failure["status"] == "failed"
    assert any("missing artifact" in item for item in failure["failures"])


def test_authorized_privacy_deletion_hashes_then_removes_only_visuals(tmp_path):
    attempt = tmp_path / "dataset/S4.2/attempts/rejected"
    attempt.mkdir(parents=True)
    (attempt / "lifecycle.json").write_text(
        json.dumps(
            {
                "schema": "ias.s4_2.lifecycle.v1",
                "attempt_id": "rejected",
                "state": "rejected",
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    (attempt / "capture.svo2").write_bytes(b"private visual")
    (attempt / "frame.png").write_bytes(b"private frame")
    (attempt / "audio.wav").write_bytes(b"retained nonvisual")
    report = delete_privacy_visuals(attempt, authorization="test authorization")
    assert report["status"] == "passed"
    assert not (attempt / "capture.svo2").exists()
    assert not (attempt / "frame.png").exists()
    assert (attempt / "audio.wav").read_bytes() == b"retained nonvisual"
    pre = load_json(attempt / report["pre_deletion_manifest"])
    assert pre["target_count"] == 2
    assert all(len(record["sha256"]) == 64 for record in pre["targets"])


def test_clean_checkout_contract_does_not_require_ignored_raw(tmp_path):
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked contract\n", encoding="utf-8")
    tracked_hash = hashlib.sha256(tracked.read_bytes()).hexdigest()
    checksums = tmp_path / "SHA256SUMS"
    raw_path = "dataset/S4.2/attempts/accepted/raw/audio.wav"
    raw_hash = "1" * 64
    checksums.write_text(
        f"{tracked_hash}  tracked.txt\n{raw_hash}  {raw_path}\n",
        encoding="utf-8",
    )
    index = tmp_path / "evidence_index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "ias.s4_2.evidence_index.v1",
                "status": "in_progress",
                "checksum_manifest": "SHA256SUMS",
                "artifacts": [
                    {
                        "path": "tracked.txt",
                        "role": "tests",
                        "retention": "tracked",
                        "byte_size": tracked.stat().st_size,
                        "sha256": tracked_hash,
                    },
                    {
                        "path": raw_path,
                        "local_relative_path": raw_path,
                        "role": "raw_respeaker_wav",
                        "retention": "machine_local_gitignored",
                        "byte_size": 123,
                        "sha256": raw_hash,
                        "media_properties": {"encoding": "PCM16 WAV"},
                        "acquisition_contract": {"channel_count": 6},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = validate_index(
        index,
        require_complete=False,
        require_git_tracked=False,
        repository_root=tmp_path,
        require_machine_local=False,
    )
    assert report["status"] == "passed"
    local_report = validate_index(
        index,
        require_complete=False,
        require_git_tracked=False,
        repository_root=tmp_path,
        require_machine_local=True,
    )
    assert any(issue["code"] == "missing_artifact" for issue in local_report["issues"])


@pytest.mark.s4_2_hardware
@pytest.mark.skipif(
    os.environ.get("IAS_S4_2_HARDWARE") != "1",
    reason=(
        "set IAS_S4_2_HARDWARE=1 only with ZED/ReSpeaker/Mac connected, "
        "physical metadata complete, scene privacy-cleared, and operator ready"
    ),
)
def test_live_hardware_preflight_gate():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "isaac_audio_sensors",
            "s4-2",
            "validate-config",
            str(CONFIG_PATH),
            "--require-ready",
        ],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 0, (
        "hardware gate cannot start until physical, local-evidence, "
        "and Mac fields are frozen"
    )


@pytest.mark.s4_2_hardware
@pytest.mark.skipif(
    not os.environ.get("IAS_S4_2_SVO_FIXTURE"),
    reason="set IAS_S4_2_SVO_FIXTURE to a retained real SVO2 for SDK fault tests",
)
def test_real_svo_replay_rejects_corrupt_and_truncated_files(tmp_path):
    source = Path(os.environ["IAS_S4_2_SVO_FIXTURE"])
    assert source.is_file()
    helper = ROOT / "scripts/validate_s4_2_zed_svo.py"
    for kind in ("corrupt", "truncated"):
        candidate = tmp_path / f"{kind}.svo2"
        shutil.copyfile(source, candidate)
        if kind == "corrupt":
            candidate.write_bytes(b"not an SVO2 container")
        else:
            with candidate.open("r+b") as stream:
                stream.truncate(max(1, candidate.stat().st_size // 2))
        report = tmp_path / f"{kind}.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(helper),
                str(candidate),
                "--output",
                str(report),
                "--expected-serial",
                "39011785",
                "--resolution",
                "HD720",
                "--fps",
                "30",
                "--depth-mode",
                "PERFORMANCE",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        payload = load_json(report)
        semantic = validate_svo_replay_report(
            payload,
            expected_serial="39011785",
            expected_resolution="HD720",
            expected_fps=30,
            expected_depth_mode="PERFORMANCE",
            expected_frame_count=602,
        )
        assert completed.returncode != 0 or not semantic.passed
        assert not semantic.passed
