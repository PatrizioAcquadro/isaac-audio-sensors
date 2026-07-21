"""S4.2 configuration, lifecycle, timing, and evidence validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import time
import uuid
import wave
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors.core.dataset.atomic import (
    CancellationToken,
    StagedFile,
    publish_file,
    write_json_atomic,
)

CONFIG_SCHEMA = "ias.s4_2.acquisition_config.v1"
ATTEMPT_SCHEMA = "ias.s4_2.attempt_manifest.v1"
VALIDATION_SCHEMA = "ias.s4_2.validation_report.v1"
ALIGNMENT_SCHEMA = "ias.s4_2.alignment.v1"
SVO_REPLAY_SCHEMA = "ias.s4_2.svo_replay_validation.v1"
REFERENCE_CAPTURE_SCHEMA = "ias.s4_2.reference_capture_validation.v1"
LIFECYCLE_SCHEMA = "ias.s4_2.lifecycle.v1"

EXPECTED_CHANNEL_ORDER = (
    "conference",
    "asr",
    "raw_microphone_0",
    "raw_microphone_1",
    "raw_microphone_2",
    "raw_microphone_3",
)
EXPECTED_PROJECT_AXES = {
    "x": "forward",
    "y": "right_as_viewed_from_zed_operator_left_facing_camera",
    "z": "up",
}
EXPECTED_BEARING_DEFINITION = "degrees clockwise from +X toward +Y viewed from above"
EXPECTED_OPERATOR_FACING_AXES = {
    "positive_x": "behind_operator_forward_of_zed",
    "negative_x": "in_front_of_operator_behind_zed",
    "positive_y": "operator_right",
    "negative_y": "operator_left",
    "positive_z": "up_toward_ceiling",
    "negative_z": "down_toward_floor",
}
EXPECTED_OPERATOR_BEARING_DEFINITION = (
    "degrees clockwise from +X toward +Y viewed from above"
)
S42_ACCEPTANCE_AMENDMENT_ID = "S4.2-PRECAPTURE-AMENDMENT-2026-07-20-A"
S42_COORDINATE_CORRECTION_ID = "S4.2-DUAL-FRAME-RECONCILIATION-2026-07-21-A"
VALIDATION_PROFILE_SCHEMA = "ias.s4.validation_profile.v1"
KNOWN_MODALITIES = {
    "respeaker_audio",
    "zed_image",
    "zed_depth",
    "zed_imu",
    "zed_pose",
    "zed_svo2",
    "mac_reference_playback",
    "audio_video_alignment",
}
S42_VALIDATION_PROFILE = {
    "schema": VALIDATION_PROFILE_SCHEMA,
    "id": "s4_2_controlled_dry_run_v1",
    "required_modalities": sorted(KNOWN_MODALITIES),
    "duration_policy": "exact_with_tolerance",
    "stimulus_policy": "complete_reference",
    "playback_overlap_policy": "complete_with_margin",
    "svo_replay_policy": "required_before_acceptance",
    "svo_replay_stage": "offline_finalization",
    "svo_frame_count_policy": "exact_jsonl_match",
    "pose_policy": "every_frame_ok_and_fresh",
    "imu_policy": "every_frame_success_and_fresh",
    "alignment_policy": "required_with_threshold",
    "controlled_source_policy": "exact_profile",
    "channel_signal_policy": "all_channels_nonsilent",
    "clipping_policy": "reject_sustained",
}
ALLOWED_LIFECYCLE = {
    "preflight",
    "recording",
    "finalizing",
    "accepted",
    "rejected",
    "failed",
    "interrupted",
}
TERMINAL_LIFECYCLE = {"accepted", "rejected", "failed", "interrupted"}
_TRANSITIONS = {
    None: {"preflight"},
    "preflight": {"recording", "rejected", "failed", "interrupted"},
    "recording": {"finalizing", "rejected", "failed", "interrupted"},
    "finalizing": {"accepted", "rejected", "failed", "interrupted"},
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One located fail-closed finding."""

    code: str
    path: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Machine-readable semantic/integrity result."""

    checks: tuple[dict[str, Any], ...]
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VALIDATION_SCHEMA,
            "status": "passed" if self.passed else "failed",
            "checks": list(self.checks),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class S42Error(RuntimeError):
    """Located S4.2 acquisition or evidence failure."""


def operator_facing_zed_position_to_project(
    position_m: Sequence[float],
) -> tuple[float, float, float]:
    """Convert one position from F_operator_facing_zed to F_project."""

    if len(position_m) != 3 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in position_m
    ):
        raise ValueError("position must contain three finite numeric meters")
    x_operator, y_operator, z_operator = map(float, position_m)
    return (x_operator, -y_operator, z_operator)


def operator_facing_zed_bearing_to_project(bearing_deg: float) -> float:
    """Convert clockwise bearing from F_operator_facing_zed to F_project."""

    if (
        isinstance(bearing_deg, bool)
        or not isinstance(bearing_deg, (int, float))
        or not math.isfinite(float(bearing_deg))
    ):
        raise ValueError("bearing must be one finite numeric angle in degrees")
    return (-float(bearing_deg)) % 360.0


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 for one finalized file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    """Load one JSON object and reject other top-level types."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S42Error(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise S42Error(f"{path}: top-level JSON value must be an object")
    return payload


def _at(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return None
        value = value[component]
    return value


def _required(
    payload: Mapping[str, Any],
    paths: Iterable[str],
    issues: list[ValidationIssue],
) -> None:
    for path in paths:
        value = _at(payload, path)
        if value is None or value == "" or value == []:
            issues.append(
                ValidationIssue(
                    "missing_required_metadata",
                    path,
                    "required S4.2 metadata is missing",
                )
            )


def _expect_equal(
    payload: Mapping[str, Any],
    path: str,
    expected: Any,
    issues: list[ValidationIssue],
    code: str = "frozen_value_mismatch",
) -> None:
    actual = _at(payload, path)
    if actual != expected:
        issues.append(
            ValidationIssue(code, path, f"expected {expected!r}, got {actual!r}")
        )


def _is_positive_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def validate_validation_profile(profile: Mapping[str, Any]) -> ValidationReport:
    """Validate explicit per-trial requirements without imposing S4.2 values."""

    issues: list[ValidationIssue] = []
    if profile.get("schema") != VALIDATION_PROFILE_SCHEMA:
        issues.append(
            ValidationIssue(
                "invalid_validation_profile",
                "validation_profile.schema",
                f"expected {VALIDATION_PROFILE_SCHEMA!r}",
            )
        )
    if not isinstance(profile.get("id"), str) or not profile.get("id"):
        issues.append(
            ValidationIssue(
                "invalid_validation_profile",
                "validation_profile.id",
                "profile id must be nonempty",
            )
        )
    modalities_raw = profile.get("required_modalities")
    modalities = set(modalities_raw) if isinstance(modalities_raw, list) else set()
    if (
        not isinstance(modalities_raw, list)
        or not modalities_raw
        or len(modalities) != len(modalities_raw)
        or not modalities <= KNOWN_MODALITIES
    ):
        issues.append(
            ValidationIssue(
                "invalid_validation_profile",
                "validation_profile.required_modalities",
                "modalities must be a nonempty list of unique known identifiers",
            )
        )
    enum_fields = {
        "duration_policy": {"exact_with_tolerance", "minimum", "declared"},
        "stimulus_policy": {"complete_reference", "declared_stimulus", "none"},
        "playback_overlap_policy": {"complete_with_margin", "declared", "none"},
        "svo_replay_policy": {"required_before_acceptance", "none"},
        "svo_replay_stage": {"offline_finalization", "batch_before_acceptance"},
        "svo_frame_count_policy": {"exact_jsonl_match", "declared_coverage"},
        "pose_policy": {
            "every_frame_ok_and_fresh",
            "metric_specific",
            "not_required",
        },
        "imu_policy": {
            "every_frame_success_and_fresh",
            "metric_specific",
            "not_required",
        },
        "alignment_policy": {
            "required_with_threshold",
            "metric_specific",
            "not_required",
        },
        "controlled_source_policy": {"exact_profile", "declared_trial", "none"},
        "channel_signal_policy": {"all_channels_nonsilent", "allow_silence"},
        "clipping_policy": {"reject_sustained", "metric_specific"},
    }
    for field, allowed in enum_fields.items():
        if profile.get(field) not in allowed:
            issues.append(
                ValidationIssue(
                    "invalid_validation_profile",
                    f"validation_profile.{field}",
                    f"must be one of {sorted(allowed)}",
                )
            )
    consistency = (
        (
            "zed_pose" in modalities and profile.get("pose_policy") == "not_required",
            "zed_pose cannot be required while pose validation is disabled",
        ),
        (
            "zed_imu" in modalities and profile.get("imu_policy") == "not_required",
            "zed_imu cannot be required while IMU validation is disabled",
        ),
        (
            "zed_svo2" in modalities and profile.get("svo_replay_policy") == "none",
            "zed_svo2 cannot be required while replay validation is disabled",
        ),
        (
            "zed_svo2" in modalities and "zed_image" not in modalities,
            "zed_svo2 requires the ZED image modality",
        ),
        (
            "mac_reference_playback" in modalities
            and (
                profile.get("stimulus_policy") == "none"
                or profile.get("playback_overlap_policy") == "none"
            ),
            "required Mac playback needs declared stimulus and overlap validation",
        ),
        (
            "audio_video_alignment" in modalities
            and (
                profile.get("alignment_policy") == "not_required"
                or "respeaker_audio" not in modalities
                or "zed_image" not in modalities
            ),
            "required audio-video alignment needs audio, image, and alignment gate",
        ),
    )
    for failed, message in consistency:
        if failed:
            issues.append(
                ValidationIssue(
                    "inconsistent_validation_profile",
                    "validation_profile",
                    message,
                )
            )
    return ValidationReport(
        (
            {
                "id": "validation_profile",
                "status": "passed" if not issues else "failed",
                "profile_id": profile.get("id"),
            },
        ),
        tuple(issues),
    )


def validate_configuration(
    payload: Mapping[str, Any], *, require_ready: bool = True
) -> ValidationReport:
    """Validate the frozen S4.2 configuration before any hardware access."""

    issues: list[ValidationIssue] = []
    checks: list[dict[str, Any]] = []
    required = [
        "schema",
        "validation_profile",
        "session.attempt_root",
        "session.duration_s",
        "session.duration_tolerance_s",
        "session.chat_cue_ack_timeout_s",
        "session.post_playback_margin_s",
        "session.minimum_local_free_bytes",
        "session.minimum_pi_free_bytes",
        "respeaker.ssh_alias",
        "respeaker.device",
        "respeaker.model",
        "respeaker.usb_product",
        "respeaker.serial",
        "respeaker.firmware",
        "respeaker.channel_count",
        "respeaker.sample_rate_hz",
        "respeaker.sample_format",
        "respeaker.channel_order",
        "zed.model",
        "zed.serial",
        "zed.sdk_version",
        "zed.camera_firmware",
        "zed.sensor_firmware",
        "zed.resolution",
        "zed.fps",
        "zed.depth_mode",
        "zed.coordinate_units",
        "zed.coordinate_system",
        "mac.ssh_alias",
        "mac.inventory_path",
        "mac.inventory_sha256",
        "mac.model_identifier",
        "mac.os_version",
        "mac.os_build",
        "mac.output_device",
        "mac.system_volume_percent",
        "mac.afplay_gain",
        "mac.reference_path",
        "reference.local_path",
        "reference.metadata_path",
        "reference.sha256",
        "fixture.fixture_id",
        "fixture.room_id",
        "coordinate_frame.frame_name",
        "coordinate_frame.axes",
        "operator_facing_frame.frame_name",
        "operator_facing_frame.axes",
        "alignment.method",
        "alignment.maximum_uncertainty_ms",
        "alignment.cue_delay_s",
        "alignment.remove_cue_delay_s",
        "alignment.remove_to_playback_s",
        "alignment.remove_instruction",
        "alignment.post_event_pre_playback_s",
        "reference.duration_s",
        "reference.playback_duration_tolerance_s",
        "reference.minimum_normalized_correlation",
        "reference.minimum_correlated_raw_channels",
        "acceptance_amendment.id",
        "acceptance_amendment.record_path",
        "coordinate_correction.id",
        "coordinate_correction.record_path",
        "coordinate_correction.superseded_record_path",
        "coordinate_correction.superseded_record_sha256",
        "raw_evidence.machine_local_root",
        "raw_evidence.retention",
        "raw_evidence.checksum_command",
        "raw_evidence.semantic_validation_command",
    ]
    if require_ready:
        required.extend(
            [
                "mac.preflight_report_path",
                "session.stable_preflight_id",
                "session.stable_preflight_report_path",
                "session.stable_preflight_invalidation_path",
                "acceptance_amendment.record_sha256",
                "coordinate_correction.record_sha256",
                "source.position_m",
                "source.position_operator_facing_zed_m",
                "source.distance_from_rig_origin_m",
                "source.distance_provenance",
                "source.bearing_deg_clockwise_from_positive_x",
                "source.bearing_operator_facing_zed_deg",
                "source.speaker_height_m",
                "source.delta_x_m",
                "source.delta_y_m",
                "source.delta_z_m",
                "source.vertical_offset_uncertainty_m",
                "source.orientation_deg",
                "source.orientation_measurement_classification",
                "source.lid_angle_deg",
                "source.lid_state",
                "source.relative_side",
                "source.relative_side_operator_facing_zed",
                "source.relative_side_project_view",
                "source.screen_heading",
                "alignment.event_object",
                "alignment.event_position_m",
                "alignment.impact_tool",
                "environment.occupancy",
                "environment.noise_state",
                "environment.operator_notes",
            ]
        )
    _required(payload, required, issues)
    profile = payload.get("validation_profile")
    if isinstance(profile, Mapping):
        profile_report = validate_validation_profile(profile)
        issues.extend(profile_report.issues)
        checks.extend(profile_report.checks)
    else:
        issues.append(
            ValidationIssue(
                "invalid_validation_profile",
                "validation_profile",
                "must be an object",
            )
        )

    frozen = {
        "schema": CONFIG_SCHEMA,
        "validation_profile": S42_VALIDATION_PROFILE,
        "respeaker.ssh_alias": "elab-raspberrypi5",
        "respeaker.device": "hw:CARD=Array,DEV=0",
        "respeaker.model": "ReSpeaker XVF3800 USB 4-Mic Array",
        "respeaker.usb_product": "reSpeaker XVF3800 4-Mic Array",
        "respeaker.serial": "114993701261100454",
        "respeaker.firmware": "2.08",
        "respeaker.channel_count": 6,
        "respeaker.sample_rate_hz": 16_000,
        "respeaker.sample_format": "S16_LE",
        "respeaker.channel_order": list(EXPECTED_CHANNEL_ORDER),
        "zed.model": "ZED 2i",
        "zed.serial": "39011785",
        "zed.sdk_version": "5.4.0",
        "zed.camera_firmware": "1523",
        "zed.sensor_firmware": "777",
        "zed.resolution": "HD720",
        "zed.fps": 30,
        "zed.depth_mode": "PERFORMANCE",
        "zed.coordinate_units": "m",
        "zed.coordinate_system": "RIGHT_HANDED_Y_UP",
        "mac.ssh_alias": "patrizios-macbook",
        "mac.model_identifier": "MacBookPro18,1",
        "mac.os_version": "26.5.2",
        "mac.os_build": "25F84",
        "mac.output_device": "MacBook Pro Speakers",
        "mac.system_volume_percent": 40,
        "mac.afplay_gain": 1.0,
        "mac.inventory_sha256": (
            "2360b24977dd25e48ebe9b975a4158dd407151d7bb4de50a8f3ab7f6eb29466d"
        ),
        "fixture.fixture_id": "S4_TEMP_DESKTOP_FIXTURE_REV0",
        "fixture.room_id": "WANG_2022_DESK_NEAR_ENTRANCE",
        "coordinate_frame.frame_name": "F_project",
        "coordinate_frame.origin": "ZED stereo-lens midpoint",
        "coordinate_frame.axes": EXPECTED_PROJECT_AXES,
        "coordinate_frame.position_units": "m",
        "coordinate_frame.bearing_definition": EXPECTED_BEARING_DEFINITION,
        "operator_facing_frame.frame_name": "F_operator_facing_zed",
        "operator_facing_frame.origin": "ZED stereo-lens midpoint",
        "operator_facing_frame.axes": EXPECTED_OPERATOR_FACING_AXES,
        "operator_facing_frame.position_units": "m",
        "operator_facing_frame.bearing_definition": (
            EXPECTED_OPERATOR_BEARING_DEFINITION
        ),
        "acceptance_amendment.id": S42_ACCEPTANCE_AMENDMENT_ID,
        "acceptance_amendment.record_path": (
            "docs/development/specs/s4_2_pre_capture_acceptance_amendment.v1.json"
        ),
        "coordinate_correction.id": S42_COORDINATE_CORRECTION_ID,
        "coordinate_correction.record_path": (
            "docs/development/specs/s4_2_dual_frame_coordinate_reconciliation.v1.json"
        ),
        "coordinate_correction.superseded_record_path": (
            "docs/development/specs/s4_2_post_capture_coordinate_correction.v1.json"
        ),
        "coordinate_correction.superseded_record_sha256": (
            "80e5131a9654a9d4f5dbf978ab6ae8dcca193c4654e96765837a78c74caa58c1"
        ),
        "session.attempt_root": "dataset/S4.2/attempts",
        "raw_evidence.machine_local_root": "dataset/S4.2",
        "raw_evidence.retention": "machine_local_gitignored",
        "raw_evidence.fresh_clone_available": False,
        "raw_evidence.machine_loss_risk_acknowledged": True,
        "raw_evidence.off_machine_storage_authorized": False,
        "raw_evidence.replicated": False,
        "alignment.method": "visible_audible_impact",
        "alignment.maximum_uncertainty_ms": 50.0,
        "alignment.cue_delay_s": 3.0,
        "alignment.remove_cue_delay_s": 1.5,
        "alignment.remove_to_playback_s": 0.5,
        "alignment.post_event_pre_playback_s": 2.0,
        "reference.duration_s": 9.5,
        "reference.playback_duration_tolerance_s": 1.5,
        "reference.minimum_normalized_correlation": 0.03,
        "reference.minimum_correlated_raw_channels": 2,
        "session.duration_tolerance_s": 0.25,
        "session.duration_s": 35.0,
        "session.chat_cue_ack_timeout_s": 15.0,
        "session.post_playback_margin_s": 2.0,
    }
    for path, expected in frozen.items():
        _expect_equal(payload, path, expected, issues)

    duration = _at(payload, "session.duration_s")
    if not _is_positive_number(duration) or not 15 <= float(duration) <= 60:
        issues.append(
            ValidationIssue(
                "invalid_duration",
                "session.duration_s",
                "bounded duration must be within [15, 60] seconds",
            )
        )
    schedule_values = {
        path: _at(payload, path)
        for path in (
            "alignment.cue_delay_s",
            "alignment.remove_cue_delay_s",
            "alignment.remove_to_playback_s",
            "alignment.post_event_pre_playback_s",
            "reference.duration_s",
            "reference.playback_duration_tolerance_s",
            "session.chat_cue_ack_timeout_s",
            "session.post_playback_margin_s",
            "session.duration_tolerance_s",
        )
    }
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
        for value in schedule_values.values()
    ):
        issues.append(
            ValidationIssue(
                "invalid_capture_schedule",
                "session",
                "capture schedule values must be finite and non-negative",
            )
        )
    elif _is_positive_number(duration):
        if not math.isclose(
            float(schedule_values["alignment.remove_cue_delay_s"])
            + float(schedule_values["alignment.remove_to_playback_s"]),
            float(schedule_values["alignment.post_event_pre_playback_s"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            issues.append(
                ValidationIssue(
                    "invalid_capture_schedule",
                    "alignment",
                    "removal cue schedule must preserve the frozen "
                    "cue-to-playback interval",
                )
            )
        required_capture_s = (
            float(schedule_values["alignment.cue_delay_s"])
            + float(schedule_values["session.chat_cue_ack_timeout_s"])
            + float(schedule_values["alignment.post_event_pre_playback_s"])
            + float(schedule_values["reference.duration_s"])
            + float(schedule_values["reference.playback_duration_tolerance_s"])
            + float(schedule_values["session.post_playback_margin_s"])
        )
        if float(duration) < required_capture_s:
            issues.append(
                ValidationIssue(
                    "insufficient_capture_schedule",
                    "session.duration_s",
                    f"{duration} s cannot contain the frozen {required_capture_s} s "
                    "post-readiness schedule",
                )
            )
    for path in (
        "session.minimum_local_free_bytes",
        "session.minimum_pi_free_bytes",
    ):
        if not _is_positive_number(_at(payload, path)):
            issues.append(
                ValidationIssue(
                    "invalid_disk_threshold", path, "must be a positive number"
                )
            )
    checksum_paths = ["reference.sha256"]
    if require_ready:
        checksum_paths.extend(
            (
                "acceptance_amendment.record_sha256",
                "coordinate_correction.record_sha256",
                "coordinate_correction.superseded_record_sha256",
            )
        )
    for checksum_path in checksum_paths:
        checksum = _at(payload, checksum_path)
        try:
            if not isinstance(checksum, str) or len(checksum) != 64:
                raise ValueError
            bytes.fromhex(checksum)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "invalid_checksum",
                    checksum_path,
                    "must be a 64-character SHA-256 hex digest",
                )
            )

    for path in (
        "session.attempt_root",
        "reference.local_path",
        "reference.metadata_path",
        "mac.inventory_path",
        "acceptance_amendment.record_path",
        "coordinate_correction.record_path",
        "coordinate_correction.superseded_record_path",
        "raw_evidence.machine_local_root",
    ):
        value = _at(payload, path)
        if isinstance(value, str) and ".." in Path(value).parts:
            issues.append(
                ValidationIssue(
                    "unsafe_path", path, "parent traversal is not permitted"
                )
            )

    if require_ready:
        ready_frozen = {
            "source.position_m": [0.0, 0.9, -0.135],
            "source.position_operator_facing_zed_m": [0.0, -0.9, -0.135],
            "source.delta_x_m": 0.0,
            "source.delta_y_m": 0.9,
            "source.delta_z_m": -0.135,
            "source.bearing_deg_clockwise_from_positive_x": 90.0,
            "source.bearing_operator_facing_zed_deg": 270.0,
            "source.speaker_height_m": 0.710,
            "source.vertical_offset_uncertainty_m": 0.010,
            "source.orientation_deg": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
            "source.orientation_measurement_classification": (
                "practical_visual_placement_not_metrology"
            ),
            "source.lid_angle_deg": 90.0,
            "source.relative_side": "operator_left_facing_camera",
            "source.relative_side_operator_facing_zed": "left",
            "source.relative_side_project_view": "right",
            "alignment.event_object": (
                "blue wastebasket with standard white recycling symbol and no "
                "private label"
            ),
            "alignment.event_position_m": [1.15, 0.0, -0.4],
            "alignment.impact_tool": "long plain paper roll",
            "raw_evidence.machine_loss_risk_acknowledged": True,
            "raw_evidence.off_machine_storage_authorized": False,
            "raw_evidence.fresh_clone_available": False,
            "raw_evidence.replicated": False,
        }
        for path, expected in ready_frozen.items():
            _expect_equal(payload, path, expected, issues)

        for path in (
            "fixture.marked_footprint_confirmed",
            "fixture.no_component_moved",
            "fixture.microphone_openings_clear",
            "fixture.zed_fov_clear",
            "fixture.cables_safe",
            "environment.privacy_scene_cleared",
            "respeaker.channel_order_verified_each_take",
            "mac.balance_centered_confirmed",
            "mac.system_ui_sounds_disabled_or_prevented",
            "mac.work_focus_active_confirmed",
            "mac.notifications_suppressed_confirmed",
            "mac.mono_audio_off_confirmed",
            "mac.background_sounds_off_confirmed",
        ):
            if _at(payload, path) is not True:
                issues.append(
                    ValidationIssue(
                        "operator_confirmation_missing",
                        path,
                        "must be explicitly true for an accepted attempt",
                    )
                )
        _expect_equal(
            payload,
            "mac.focus_and_notifications_verification_basis",
            "operator_confirmed",
            issues,
        )

        position = _at(payload, "source.position_m")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or any(not isinstance(v, (int, float)) for v in position)
            or any(not math.isfinite(float(v)) for v in position)
        ):
            issues.append(
                ValidationIssue(
                    "invalid_position",
                    "source.position_m",
                    "must be three finite numbers in F_project meters",
                )
            )
        else:
            for index, path in enumerate(
                ("source.delta_x_m", "source.delta_y_m", "source.delta_z_m")
            ):
                declared = _at(payload, path)
                if not isinstance(declared, (int, float)) or not math.isclose(
                    float(declared), float(position[index]), abs_tol=1e-12
                ):
                    issues.append(
                        ValidationIssue(
                            "inconsistent_source_delta",
                            path,
                            f"must equal source.position_m[{index}]",
                        )
                    )
            declared_distance = _at(payload, "source.distance_from_rig_origin_m")
            computed_distance = math.sqrt(sum(float(v) ** 2 for v in position))
            if not _is_positive_number(declared_distance) or not math.isclose(
                computed_distance, float(declared_distance), abs_tol=0.02
            ):
                issues.append(
                    ValidationIssue(
                        "inconsistent_source_distance",
                        "source.distance_from_rig_origin_m",
                        f"position implies {computed_distance:.4f} m; "
                        "tolerance is 0.02 m",
                    )
                )
            operator_position = _at(payload, "source.position_operator_facing_zed_m")
            try:
                converted_position = operator_facing_zed_position_to_project(
                    operator_position
                )
            except (TypeError, ValueError):
                issues.append(
                    ValidationIssue(
                        "invalid_operator_position",
                        "source.position_operator_facing_zed_m",
                        "must be three finite numbers in F_operator_facing_zed meters",
                    )
                )
            else:
                if any(
                    not math.isclose(actual, float(expected), abs_tol=1e-12)
                    for actual, expected in zip(
                        converted_position, position, strict=True
                    )
                ):
                    issues.append(
                        ValidationIssue(
                            "inconsistent_dual_frame_position",
                            "source.position_operator_facing_zed_m",
                            "must convert exactly to source.position_m in F_project",
                        )
                    )
        orientation = _at(payload, "source.orientation_deg")
        if (
            not isinstance(orientation, Mapping)
            or set(orientation) != {"yaw", "pitch", "roll"}
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in orientation.values()
            )
        ):
            issues.append(
                ValidationIssue(
                    "invalid_orientation",
                    "source.orientation_deg",
                    "must contain finite yaw, pitch, and roll degrees",
                )
            )
        for path, minimum, maximum in (
            ("source.bearing_deg_clockwise_from_positive_x", 0.0, 360.0),
            ("source.bearing_operator_facing_zed_deg", 0.0, 360.0),
            ("source.lid_angle_deg", 0.0, 180.0),
        ):
            value = _at(payload, path)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_angle",
                        path,
                        f"must be finite and within [{minimum}, {maximum}] degrees",
                    )
                )
        operator_bearing = _at(payload, "source.bearing_operator_facing_zed_deg")
        project_bearing = _at(payload, "source.bearing_deg_clockwise_from_positive_x")
        try:
            converted_bearing = operator_facing_zed_bearing_to_project(operator_bearing)
        except ValueError:
            pass
        else:
            if isinstance(project_bearing, (int, float)) and not math.isclose(
                converted_bearing, float(project_bearing) % 360.0, abs_tol=1e-12
            ):
                issues.append(
                    ValidationIssue(
                        "inconsistent_dual_frame_bearing",
                        "source.bearing_operator_facing_zed_deg",
                        "must convert exactly to canonical F_project bearing",
                    )
                )
        if _at(payload, "source.relative_side") not in {
            "front",
            "behind",
            "left",
            "right",
            "operator_left_facing_camera",
            "operator_right_facing_camera",
        }:
            issues.append(
                ValidationIssue(
                    "invalid_relative_side",
                    "source.relative_side",
                    "must be front, behind, left, or right",
                )
            )
        if not _is_positive_number(_at(payload, "source.speaker_height_m")):
            issues.append(
                ValidationIssue(
                    "invalid_height",
                    "source.speaker_height_m",
                    "must be a positive finite number in meters",
                )
            )
        if not _is_positive_number(
            _at(payload, "source.vertical_offset_uncertainty_m")
        ):
            issues.append(
                ValidationIssue(
                    "invalid_uncertainty",
                    "source.vertical_offset_uncertainty_m",
                    "must be a positive finite number in meters",
                )
            )

    checks.append(
        {
            "id": "configuration_semantics",
            "status": "passed" if not issues else "failed",
            "require_ready": require_ready,
        }
    )
    return ValidationReport(tuple(checks), tuple(issues))


def normalize_configuration(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Round-trip a configuration through canonical JSON-compatible values."""

    return json.loads(json.dumps(dict(payload), sort_keys=True))


def validate_mac_preflight(
    report: Mapping[str, Any],
    configuration: Mapping[str, Any],
    *,
    enforce_freshness: bool = True,
) -> ValidationReport:
    """Compare one current read-only Mac report to the frozen configuration."""

    issues: list[ValidationIssue] = []
    _expect_equal(report, "schema", "ias.s4_2.mac_preflight.v1", issues)
    _expect_equal(report, "read_only", True, issues)
    comparisons = {
        "hardware.model_identifier": _at(configuration, "mac.model_identifier"),
        "os.version": _at(configuration, "mac.os_version"),
        "os.build": _at(configuration, "mac.os_build"),
        "audio_output.device_name": _at(configuration, "mac.output_device"),
        "audio_output.channel_count": 2,
        "audio_output.nominal_sample_rate_hz": 48_000,
        "volume.output_volume": _at(configuration, "mac.system_volume_percent"),
        "volume.output_muted": False,
        "power.on_ac_power": True,
        "reference_wav.sha256": _at(configuration, "reference.sha256"),
        "reference_wav.hash_matches": True,
        "reference_wav.channel_count": 1,
        "reference_wav.sample_rate_hz": 48_000,
        "reference_wav.bits_per_sample": 16,
        "reference_wav.duration_s": 9.5,
        "reference_wav.afinfo_exit_status": 0,
        "reference_wav.afinfo_lpcm_detected": True,
        "controllable_audio_settings.background_sounds": False,
    }
    for path, expected in comparisons.items():
        _expect_equal(report, path, expected, issues, "mac_preflight_mismatch")
    if enforce_freshness:
        collected_at = report.get("collected_at")
        try:
            collected = datetime.fromisoformat(str(collected_at))
            age_s = (
                datetime.now(timezone.utc) - collected.astimezone(timezone.utc)
            ).total_seconds()
            if age_s < 0 or age_s > 600:
                issues.append(
                    ValidationIssue(
                        "stale_mac_preflight",
                        "collected_at",
                        f"report age {age_s:.3f} s is outside [0, 600] s",
                    )
                )
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    "invalid_mac_preflight_timestamp",
                    "collected_at",
                    repr(collected_at),
                )
            )
    manual = {
        "mac.balance_centered_confirmed": True,
        "mac.system_ui_sounds_disabled_or_prevented": True,
        "mac.work_focus_active_confirmed": True,
        "mac.notifications_suppressed_confirmed": True,
        "mac.mono_audio_off_confirmed": True,
        "mac.background_sounds_off_confirmed": True,
    }
    for path, expected in manual.items():
        _expect_equal(
            configuration,
            path,
            expected,
            issues,
            "manual_mac_confirmation_missing",
        )
    _expect_equal(
        configuration,
        "mac.focus_and_notifications_verification_basis",
        "operator_confirmed",
        issues,
        "manual_mac_confirmation_missing",
    )
    automatic_focus = _at(report, "focus_and_notifications.work_focus_active")
    automatic_notifications = _at(
        report, "focus_and_notifications.notifications_suppressed"
    )
    if automatic_focus is not True or automatic_notifications is not True:
        issues.append(
            ValidationIssue(
                "automatic_focus_detection_conflict",
                "focus_and_notifications",
                "automatic Focus/notification observation conflicts with or cannot "
                "verify the authoritative operator confirmation",
                severity="warning",
            )
        )
    return ValidationReport(
        (
            {
                "id": "mac_preflight",
                "status": (
                    "passed"
                    if not any(issue.severity == "error" for issue in issues)
                    else "failed"
                ),
            },
            {
                "id": "focus_and_notifications",
                "status": "passed",
                "basis": "operator_confirmed",
                "automatic_observation": {
                    "work_focus_active": automatic_focus,
                    "notifications_suppressed": automatic_notifications,
                },
            },
        ),
        tuple(issues),
    )


def validate_mac_dynamic_preflight(
    report: Mapping[str, Any], configuration: Mapping[str, Any]
) -> ValidationReport:
    """Validate the lightweight per-take Mac state without repeating inventory."""

    issues: list[ValidationIssue] = []
    _expect_equal(report, "schema", "ias.s4_2.mac_dynamic_preflight.v1", issues)
    _expect_equal(report, "read_only", True, issues)
    _expect_equal(report, "scope", "per_take_dynamic_only", issues)
    comparisons = {
        "audio_output.device_name": _at(configuration, "mac.output_device"),
        "audio_output.channel_count": 2,
        "audio_output.nominal_sample_rate_hz": 48_000,
        "volume.output_volume": _at(configuration, "mac.system_volume_percent"),
        "volume.output_muted": False,
        "power.on_ac_power": True,
        "status": "passed",
    }
    for path, expected in comparisons.items():
        _expect_equal(report, path, expected, issues, "mac_dynamic_mismatch")
    collected_at = report.get("collected_at")
    try:
        collected = datetime.fromisoformat(str(collected_at))
        age_s = (
            datetime.now(timezone.utc) - collected.astimezone(timezone.utc)
        ).total_seconds()
        if age_s < 0 or age_s > 600:
            issues.append(
                ValidationIssue(
                    "stale_mac_dynamic_preflight",
                    "collected_at",
                    f"report age {age_s:.3f} s is outside [0, 600] s",
                )
            )
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "invalid_mac_preflight_timestamp",
                "collected_at",
                repr(collected_at),
            )
        )
    return ValidationReport(
        (
            {
                "id": "mac_dynamic_preflight",
                "status": "passed" if not issues else "failed",
            },
        ),
        tuple(issues),
    )


class AttemptLifecycle:
    """Atomic, append-preserving lifecycle for one never-overwritten attempt."""

    def __init__(
        self,
        attempts_root: str | Path,
        *,
        attempt_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.attempt_id = attempt_id or self.new_attempt_id()
        if not self.valid_attempt_id(self.attempt_id):
            raise ValueError("attempt_id contains unsupported characters")
        self.root = Path(attempts_root) / self.attempt_id
        if self.root.exists():
            raise FileExistsError(f"attempt already exists: {self.root}")
        self.root.mkdir(parents=True, exist_ok=False)
        self.cancellation_token = cancellation_token or CancellationToken()
        self._events: list[dict[str, Any]] = []
        self._state: str | None = None
        self.transition("preflight", reason="attempt directory created")

    @classmethod
    def open_existing(cls, attempt_root: str | Path) -> AttemptLifecycle:
        """Resume lifecycle bookkeeping without altering retained evidence."""

        root = Path(attempt_root)
        payload = load_json(root / "lifecycle.json")
        if payload.get("schema") != LIFECYCLE_SCHEMA:
            raise S42Error(f"{root}: incompatible lifecycle schema")
        attempt_id = payload.get("attempt_id")
        state = payload.get("state")
        events = payload.get("events")
        if (
            not isinstance(attempt_id, str)
            or root.name != attempt_id
            or state not in ALLOWED_LIFECYCLE
            or not isinstance(events, list)
        ):
            raise S42Error(f"{root}: malformed lifecycle")
        instance = cls.__new__(cls)
        instance.attempt_id = attempt_id
        instance.root = root
        instance.cancellation_token = CancellationToken()
        instance._events = list(events)
        instance._state = state
        return instance

    @staticmethod
    def valid_attempt_id(value: str) -> bool:
        return bool(value) and all(
            character.isalnum() or character in "-_." for character in value
        )

    @staticmethod
    def new_attempt_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"s4_2_{stamp}_{uuid.uuid4().hex[:12]}"

    @property
    def state(self) -> str:
        if self._state is None:
            raise RuntimeError("lifecycle has no state")
        return self._state

    def transition(self, state: str, *, reason: str) -> None:
        if state not in ALLOWED_LIFECYCLE:
            raise ValueError(f"unknown lifecycle state: {state}")
        if self._state in TERMINAL_LIFECYCLE:
            raise S42Error(f"terminal attempt cannot transition from {self._state}")
        if state not in _TRANSITIONS.get(self._state, set()):
            raise S42Error(f"invalid lifecycle transition {self._state!r} -> {state!r}")
        now = datetime.now().astimezone()
        self._state = state
        self._events.append(
            {
                "state": state,
                "reason": reason,
                "wall_time_utc": now.astimezone(timezone.utc).isoformat(),
                "wall_time_local": now.isoformat(),
                "monotonic_ns": time.monotonic_ns(),
            }
        )
        write_json_atomic(
            self.root / "lifecycle.json",
            {
                "schema": LIFECYCLE_SCHEMA,
                "attempt_id": self.attempt_id,
                "state": state,
                "events": self._events,
            },
            cancellation_token=self.cancellation_token,
        )

    def write_configuration(self, payload: Mapping[str, Any]) -> None:
        write_json_atomic(
            self.root / "normalized_configuration.json",
            normalize_configuration(payload),
            cancellation_token=self.cancellation_token,
        )


def promote_finalized_file(
    source: str | Path,
    destination: str | Path,
    *,
    cancellation_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Stream a finalized producer file through an S2.2 staged publication."""

    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise S42Error(f"finalized source is missing: {source_path}")
    if destination_path.exists():
        raise FileExistsError(f"destination already exists: {destination_path}")
    staged = StagedFile(
        destination_path.parent / "_staging",
        f"{destination_path.name}.incoming",
        cancellation_token=cancellation_token,
    )
    try:
        with source_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                staged.append(block)
        record = publish_file(staged, destination_path)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise
    record["path"] = destination_path.as_posix()
    return record


def disk_space_check(path: str | Path, minimum_free_bytes: int) -> dict[str, Any]:
    """Return a fail-closed local disk-space observation."""

    destination = Path(path)
    probe = destination if destination.exists() else destination.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {
        "path": str(destination),
        "free_bytes": usage.free,
        "minimum_free_bytes": int(minimum_free_bytes),
        "passed": usage.free >= int(minimum_free_bytes),
    }


def inspect_six_channel_wav(
    path: str | Path,
    *,
    require_nonsilent_channels: bool,
    reject_sustained_clipping: bool,
    sustained_clip_run_samples_min: int = 4_000,
    expected_duration_s: float | None = None,
    duration_tolerance_s: float = 0.0,
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    """Stream-validate the frozen six-channel ReSpeaker PCM contract."""

    if (
        isinstance(sustained_clip_run_samples_min, bool)
        or not isinstance(sustained_clip_run_samples_min, int)
        or sustained_clip_run_samples_min <= 0
    ):
        raise ValueError("sustained_clip_run_samples_min must be a positive integer")

    wav_path = Path(path)
    issues: list[ValidationIssue] = []
    if not wav_path.is_file():
        return {}, (ValidationIssue("missing_audio", str(wav_path), "WAV is missing"),)
    sums = [0] * 6
    peaks = [0] * 6
    frames = 0
    current_clip_runs = [0] * 6
    maximum_clip_runs = [0] * 6
    try:
        with wave.open(str(wav_path), "rb") as reader:
            properties = {
                "channel_count": reader.getnchannels(),
                "sample_rate_hz": reader.getframerate(),
                "sample_width_bytes": reader.getsampwidth(),
                "compression": reader.getcomptype(),
                "declared_frame_count": reader.getnframes(),
            }
            if properties["channel_count"] != 6:
                issues.append(
                    ValidationIssue(
                        "wrong_channel_count",
                        str(wav_path),
                        f"expected 6, got {properties['channel_count']}",
                    )
                )
            if properties["sample_rate_hz"] != 16_000:
                issues.append(
                    ValidationIssue(
                        "wrong_sample_rate",
                        str(wav_path),
                        f"expected 16000, got {properties['sample_rate_hz']}",
                    )
                )
            if (
                properties["sample_width_bytes"] != 2
                or properties["compression"] != "NONE"
            ):
                issues.append(
                    ValidationIssue(
                        "wrong_sample_format",
                        str(wav_path),
                        "expected uncompressed signed PCM16 little-endian",
                    )
                )
            if issues:
                return properties, tuple(issues)
            while True:
                raw = reader.readframes(4096)
                if not raw:
                    break
                frame_bytes = 6 * 2
                if len(raw) % frame_bytes:
                    issues.append(
                        ValidationIssue(
                            "truncated_wav",
                            str(wav_path),
                            "decoded payload ends inside an interleaved frame",
                        )
                    )
                    break
                sample_values = struct.unpack(f"<{len(raw) // 2}h", raw)
                for offset in range(0, len(sample_values), 6):
                    frames += 1
                    for channel in range(6):
                        sample = sample_values[offset + channel]
                        absolute = abs(sample)
                        sums[channel] += sample * sample
                        peaks[channel] = max(peaks[channel], absolute)
                        if absolute >= 32_734:
                            current_clip_runs[channel] += 1
                            maximum_clip_runs[channel] = max(
                                maximum_clip_runs[channel],
                                current_clip_runs[channel],
                            )
                        else:
                            current_clip_runs[channel] = 0
            if frames != properties["declared_frame_count"]:
                issues.append(
                    ValidationIssue(
                        "truncated_wav",
                        str(wav_path),
                        "header declares "
                        f"{properties['declared_frame_count']} frames; "
                        f"decoded {frames}",
                    )
                )
    except (EOFError, OSError, wave.Error) as exc:
        return {}, (
            ValidationIssue(
                "malformed_wav", str(wav_path), f"{type(exc).__name__}: {exc}"
            ),
        )

    rms = [math.sqrt(total / frames) if frames else 0.0 for total in sums]
    for channel, value in enumerate(rms):
        if require_nonsilent_channels and value < 1.0:
            issues.append(
                ValidationIssue(
                    "silent_channel",
                    f"audio.channel[{channel}]",
                    f"RMS {value:.6f} PCM16 count is below 1.0",
                )
            )
    for channel, run in enumerate(maximum_clip_runs):
        if reject_sustained_clipping and run >= sustained_clip_run_samples_min:
            issues.append(
                ValidationIssue(
                    "sustained_clipping",
                    f"audio.channel[{channel}]",
                    f"{run} consecutive samples at or above 0.999 full scale",
                )
            )
    properties.update(
        {
            "decoded_frame_count": frames,
            "duration_s": frames / 16_000,
            "per_channel_rms_pcm16": rms,
            "per_channel_peak_pcm16": peaks,
            "per_channel_maximum_clip_run_samples": maximum_clip_runs,
            "sha256": sha256_file(wav_path),
            "byte_size": wav_path.stat().st_size,
        }
    )
    if expected_duration_s is not None and not math.isclose(
        properties["duration_s"],
        expected_duration_s,
        abs_tol=duration_tolerance_s,
    ):
        issues.append(
            ValidationIssue(
                "wav_duration_mismatch",
                str(wav_path),
                f"expected {expected_duration_s:.6f} +/- "
                f"{duration_tolerance_s:.6f} s, got "
                f"{properties['duration_s']:.6f} s",
            )
        )
    return properties, tuple(issues)


def _read_pcm16(path: Path) -> tuple[np.ndarray, int, int]:
    try:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            rate = reader.getframerate()
            if reader.getsampwidth() != 2 or reader.getcomptype() != "NONE":
                raise S42Error(f"{path}: expected uncompressed PCM16 WAV")
            raw = reader.readframes(reader.getnframes())
    except (EOFError, OSError, wave.Error) as exc:
        raise S42Error(f"{path}: invalid WAV: {exc}") from exc
    values = np.frombuffer(raw, dtype="<i2")
    if values.size % channels:
        raise S42Error(f"{path}: PCM payload ends inside a frame")
    return values.reshape(-1, channels).astype(np.float64), rate, channels


def _normalized_valid_correlation(
    captured: np.ndarray, template: np.ndarray
) -> np.ndarray:
    """Return absolute mean-removed normalized correlation at every valid lag."""

    if captured.ndim != 1 or template.ndim != 1 or captured.size < template.size:
        return np.empty(0, dtype=np.float64)
    centered = template - float(template.mean())
    template_norm = float(np.linalg.norm(centered))
    if template_norm == 0.0:
        return np.empty(0, dtype=np.float64)
    full_size = captured.size + centered.size - 1
    fft_size = 1 << (full_size - 1).bit_length()
    full = np.fft.irfft(
        np.fft.rfft(captured, fft_size) * np.fft.rfft(centered[::-1], fft_size),
        fft_size,
    )[:full_size]
    numerator = full[centered.size - 1 : captured.size]
    cumulative = np.concatenate(([0.0], np.cumsum(captured)))
    cumulative_squared = np.concatenate(([0.0], np.cumsum(captured * captured)))
    window_sum = cumulative[centered.size :] - cumulative[: -centered.size]
    window_squared = (
        cumulative_squared[centered.size :]
        - cumulative_squared[: -centered.size]
        - window_sum * window_sum / centered.size
    )
    denominator = template_norm * np.sqrt(np.maximum(window_squared, 1e-12))
    return np.abs(numerator) / denominator


def validate_reference_capture(
    captured_wav: str | Path,
    reference_wav: str | Path,
    *,
    minimum_normalized_correlation: float,
    minimum_correlated_raw_channels: int,
    start_consistency_tolerance_s: float = 0.050,
) -> ValidationReport:
    """Prove the complete deterministic stimulus exists in retained PCM evidence."""

    issues: list[ValidationIssue] = []
    checks: list[dict[str, Any]] = []
    try:
        captured, captured_rate, captured_channels = _read_pcm16(Path(captured_wav))
        reference, reference_rate, reference_channels = _read_pcm16(Path(reference_wav))
    except S42Error as exc:
        return ValidationReport(
            (),
            (
                ValidationIssue(
                    "reference_capture_unreadable", "reference_capture", str(exc)
                ),
            ),
        )
    if captured_rate != 16_000 or captured_channels != 6:
        issues.append(
            ValidationIssue(
                "reference_capture_format_mismatch",
                str(captured_wav),
                f"expected six-channel 16000 Hz, got {captured_channels} channel(s) "
                f"at {captured_rate} Hz",
            )
        )
    if reference_rate != 48_000 or reference_channels != 1:
        issues.append(
            ValidationIssue(
                "reference_format_mismatch",
                str(reference_wav),
                f"expected mono 48000 Hz, got {reference_channels} channel(s) "
                f"at {reference_rate} Hz",
            )
        )
    if issues:
        return ValidationReport(tuple(checks), tuple(issues))
    # The tracked source is deliberately band-limited below the 16 kHz path's
    # Nyquist frequency, so deterministic factor-three decimation preserves the
    # sequence used for this retained-capture identity check.
    template = reference[:, 0][::3]
    # The first and final synchronization chirps are intentionally identical.
    # A global whole-template maximum can therefore lock onto the wrong chirp
    # in otherwise valid retained audio. Anchor each channel on the unique,
    # seeded broadband segment, then search the unchanged full-reference
    # correlation only within the frozen cross-channel timing tolerance.
    identity_start = round(2.25 * captured_rate)
    identity_end = round(7.25 * captured_rate)
    identity_template = template[identity_start:identity_end]
    search_radius = round(start_consistency_tolerance_s * captured_rate)
    channel_results: list[dict[str, Any]] = []
    for channel in range(6):
        identity_correlations = _normalized_valid_correlation(
            captured[:, channel], identity_template
        )
        correlations = _normalized_valid_correlation(captured[:, channel], template)
        if identity_correlations.size and correlations.size:
            identity_peak_index = int(np.argmax(identity_correlations))
            identity_peak = float(identity_correlations[identity_peak_index])
            coarse_reference_start = identity_peak_index - identity_start
            search_start = max(0, coarse_reference_start - search_radius)
            search_stop = min(
                correlations.size, coarse_reference_start + search_radius + 1
            )
            if search_start < search_stop:
                peak_index = search_start + int(
                    np.argmax(correlations[search_start:search_stop])
                )
                peak = float(correlations[peak_index])
            else:
                peak_index = -1
                peak = 0.0
        else:
            identity_peak_index = -1
            identity_peak = 0.0
            coarse_reference_start = -1
            peak_index = -1
            peak = 0.0
        channel_results.append(
            {
                "channel_index": channel,
                "identity_peak_normalized_correlation": identity_peak,
                "identity_reference_start_sample_index": coarse_reference_start,
                "peak_normalized_correlation": peak,
                "reference_start_sample_index": peak_index,
                "reference_start_elapsed_s": (
                    peak_index / captured_rate if peak_index >= 0 else None
                ),
            }
        )
    passing_raw = [
        result
        for result in channel_results[2:]
        if (
            result["identity_peak_normalized_correlation"]
            >= minimum_normalized_correlation
            and result["peak_normalized_correlation"] >= minimum_normalized_correlation
        )
    ]
    if len(passing_raw) < minimum_correlated_raw_channels:
        issues.append(
            ValidationIssue(
                "incomplete_reference_stimulus",
                str(captured_wav),
                f"only {len(passing_raw)} raw channels contain the complete "
                f"reference at correlation >= {minimum_normalized_correlation}; "
                f"required {minimum_correlated_raw_channels}",
            )
        )
    elif max(result["reference_start_sample_index"] for result in passing_raw) - min(
        result["reference_start_sample_index"] for result in passing_raw
    ) > round(start_consistency_tolerance_s * captured_rate):
        issues.append(
            ValidationIssue(
                "inconsistent_reference_stimulus_start",
                str(captured_wav),
                "passing raw-channel reference starts differ by more than "
                f"{start_consistency_tolerance_s:.3f} s",
            )
        )
    checks.append(
        {
            "id": "complete_reference_stimulus",
            "status": "passed" if not issues else "failed",
            "reference_duration_s": template.size / captured_rate,
            "minimum_normalized_correlation": minimum_normalized_correlation,
            "minimum_correlated_raw_channels": minimum_correlated_raw_channels,
            "channel_results": channel_results,
            "evidence_interpretation": (
                "full deterministic non-silent waveform identity; final-silence "
                "coverage is established separately by recorder/playback overlap"
            ),
        }
    )
    return ValidationReport(tuple(checks), tuple(issues))


def read_jsonl(
    path: str | Path,
) -> tuple[list[dict[str, Any]], tuple[ValidationIssue, ...]]:
    """Read JSONL without accepting blank, partial, or non-object records."""

    records: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    jsonl_path = Path(path)
    if not jsonl_path.is_file():
        return [], (
            ValidationIssue("missing_jsonl", str(jsonl_path), "JSONL is missing"),
        )
    try:
        with jsonl_path.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.endswith(b"\n"):
                    issues.append(
                        ValidationIssue(
                            "partial_jsonl_line",
                            f"{jsonl_path}:{line_number}",
                            "line is not newline-terminated",
                        )
                    )
                    continue
                if not raw.strip():
                    issues.append(
                        ValidationIssue(
                            "blank_jsonl_line",
                            f"{jsonl_path}:{line_number}",
                            "blank lines are forbidden",
                        )
                    )
                    continue
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    issues.append(
                        ValidationIssue(
                            "corrupt_jsonl",
                            f"{jsonl_path}:{line_number}",
                            str(exc),
                        )
                    )
                    continue
                if not isinstance(record, dict):
                    issues.append(
                        ValidationIssue(
                            "invalid_jsonl_record",
                            f"{jsonl_path}:{line_number}",
                            "record must be an object",
                        )
                    )
                    continue
                records.append(record)
    except OSError as exc:
        issues.append(ValidationIssue("jsonl_io_error", str(jsonl_path), str(exc)))
    return records, tuple(issues)


def _validate_declared_zed_modalities(
    records: Sequence[Mapping[str, Any]],
    *,
    duration_s: float,
    fps: int,
    profile: Mapping[str, Any],
) -> ValidationReport:
    """Validate only declared ZED modalities while preserving stream integrity."""

    profile_report = validate_validation_profile(profile)
    if not profile_report.passed:
        return profile_report
    modalities = set(profile["required_modalities"])
    required_zed = modalities & {"zed_image", "zed_depth", "zed_imu", "zed_pose"}
    issues: list[ValidationIssue] = []
    expected_minimum = math.floor(duration_s * fps * 0.90) if required_zed else 0
    if len(records) < expected_minimum:
        issues.append(
            ValidationIssue(
                "incomplete_zed_output",
                "zed.frames",
                f"expected at least {expected_minimum} records, got {len(records)}",
            )
        )
    base_fields = {
        "schema",
        "frame_index",
        "device_timestamp_ns",
        "host_wall_time_utc",
        "host_monotonic_ns",
        "frame_name",
        "units",
    }
    modality_fields = {
        "zed_image": {"image_status", "image_signature_sha256"},
        "zed_depth": {
            "depth_status",
            "depth_sample_grid_m",
            "depth_sample_grid_shape",
            "depth_sample_stride_px",
        },
        "zed_imu": {"imu_status", "imu_timestamp_ns", "imu"},
        "zed_pose": {"pose_status", "pose_timestamp_ns", "pose"},
    }
    required_fields = set(base_fields)
    for modality in required_zed:
        required_fields.update(modality_fields[modality])
    timestamp_streams: dict[str, list[int]] = {
        "device": [],
        "host_monotonic": [],
        "host_wall": [],
        "imu": [],
        "pose": [],
    }
    successful_signatures: list[str] = []
    for index, record in enumerate(records):
        missing = sorted(required_fields - record.keys())
        if missing:
            issues.append(
                ValidationIssue(
                    "missing_zed_metadata",
                    f"zed.frames[{index}]",
                    f"missing required profile keys: {missing}",
                )
            )
            continue
        if record["schema"] != "ias.s4_2.zed_frame.v1":
            issues.append(
                ValidationIssue(
                    "invalid_schema",
                    f"zed.frames[{index}].schema",
                    repr(record["schema"]),
                )
            )
        if record["frame_index"] != index:
            issues.append(
                ValidationIssue(
                    "nonsequential_frame_index",
                    f"zed.frames[{index}].frame_index",
                    f"expected {index}, got {record['frame_index']!r}",
                )
            )
        if record["frame_name"] != "F_zed_world_y_up":
            issues.append(
                ValidationIssue(
                    "invalid_coordinate_frame",
                    f"zed.frames[{index}].frame_name",
                    repr(record["frame_name"]),
                )
            )
        if record["units"] != {"position": "m", "time": "ns", "angle": "rad"}:
            issues.append(
                ValidationIssue(
                    "invalid_units",
                    f"zed.frames[{index}].units",
                    repr(record["units"]),
                )
            )
        try:
            device = record["device_timestamp_ns"]
            host = record["host_monotonic_ns"]
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (device, host)
            ):
                raise ValueError
            wall = datetime.fromisoformat(str(record["host_wall_time_utc"]))
            if wall.tzinfo is None:
                raise ValueError
            timestamp_streams["device"].append(device)
            timestamp_streams["host_monotonic"].append(host)
            timestamp_streams["host_wall"].append(round(wall.timestamp() * 1e9))
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    "invalid_timestamp",
                    f"zed.frames[{index}]",
                    "base ZED timestamps must be positive and timezone-aware",
                )
            )
        for modality, status_key, failure_code in (
            ("zed_image", "image_status", "failed_image_retrieval"),
            ("zed_depth", "depth_status", "failed_depth_retrieval"),
            ("zed_imu", "imu_status", "failed_imu_retrieval"),
        ):
            if modality in required_zed and record.get(status_key) != "SUCCESS":
                issues.append(
                    ValidationIssue(
                        failure_code,
                        f"zed.frames[{index}].{status_key}",
                        repr(record.get(status_key)),
                    )
                )
        if record.get("image_status") == "SUCCESS":
            signature = record.get("image_signature_sha256")
            if not isinstance(signature, str) or len(signature) != 64:
                issues.append(
                    ValidationIssue(
                        "invalid_image_signature",
                        f"zed.frames[{index}].image_signature_sha256",
                        repr(signature),
                    )
                )
            else:
                successful_signatures.append(signature)
        if record.get("depth_status") == "SUCCESS":
            grid = record.get("depth_sample_grid_m")
            shape = record.get("depth_sample_grid_shape")
            if (
                not isinstance(grid, list)
                or not isinstance(shape, list)
                or len(shape) != 2
                or any(not isinstance(value, int) or value <= 0 for value in shape)
                or len(grid) != shape[0] * shape[1]
                or not any(
                    isinstance(value, (int, float)) and math.isfinite(float(value))
                    for value in grid
                )
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_depth_record",
                        f"zed.frames[{index}].depth_sample_grid_m",
                        "successful depth must contain a shaped finite sample grid",
                    )
                )
        if record.get("imu_status") == "SUCCESS":
            try:
                imu_timestamp = record["imu_timestamp_ns"]
                if (
                    isinstance(imu_timestamp, bool)
                    or not isinstance(imu_timestamp, int)
                    or imu_timestamp <= 0
                ):
                    raise ValueError
                timestamp_streams["imu"].append(imu_timestamp)
            except (KeyError, TypeError, ValueError):
                issues.append(
                    ValidationIssue(
                        "invalid_timestamp",
                        f"zed.frames[{index}].imu_timestamp_ns",
                        "successful IMU record requires an integer timestamp",
                    )
                )
            imu = record.get("imu")
            if not isinstance(imu, Mapping) or any(
                not isinstance(imu.get(key), list)
                or len(imu[key]) != length
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in imu[key]
                )
                for key, length in (
                    ("linear_acceleration_m_s2", 3),
                    ("angular_velocity_rad_s", 3),
                    ("orientation_xyzw", 4),
                )
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_imu_record",
                        f"zed.frames[{index}].imu",
                        "successful IMU must contain finite 3/3/4 vectors",
                    )
                )
        pose_success = record.get("pose_status") == "OK"
        if "zed_pose" in required_zed and not pose_success:
            issues.append(
                ValidationIssue(
                    "invalid_pose_state",
                    f"zed.frames[{index}].pose_status",
                    repr(record.get("pose_status")),
                )
            )
        if pose_success:
            try:
                pose_timestamp = record["pose_timestamp_ns"]
                if (
                    isinstance(pose_timestamp, bool)
                    or not isinstance(pose_timestamp, int)
                    or pose_timestamp <= 0
                ):
                    raise ValueError
                timestamp_streams["pose"].append(pose_timestamp)
            except (KeyError, TypeError, ValueError):
                issues.append(
                    ValidationIssue(
                        "invalid_timestamp",
                        f"zed.frames[{index}].pose_timestamp_ns",
                        "successful pose requires an integer timestamp",
                    )
                )
            pose = record.get("pose")
            if not isinstance(pose, Mapping) or pose.get("valid") is not True:
                issues.append(
                    ValidationIssue(
                        "invalid_pose",
                        f"zed.frames[{index}].pose",
                        "a pose reported OK must contain pose.valid=true",
                    )
                )
            else:
                translation = pose.get("translation_xyz_m")
                orientation = pose.get("orientation_xyzw")
                confidence = pose.get("confidence_percent")
                vectors_valid = all(
                    isinstance(vector, list)
                    and len(vector) == length
                    and all(
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(float(value))
                        for value in vector
                    )
                    for vector, length in ((translation, 3), (orientation, 4))
                )
                if (
                    not vectors_valid
                    or isinstance(confidence, bool)
                    or not isinstance(confidence, int)
                    or not 0 <= confidence <= 100
                ):
                    issues.append(
                        ValidationIssue(
                            "invalid_pose",
                            f"zed.frames[{index}].pose",
                            "successful pose vectors/confidence are invalid",
                        )
                    )
    for name, timestamps in timestamp_streams.items():
        for index, (earlier, later) in enumerate(
            zip(timestamps, timestamps[1:], strict=False), 1
        ):
            if later <= earlier:
                issues.append(
                    ValidationIssue(
                        "duplicate_timestamp"
                        if later == earlier
                        else "nonmonotonic_timestamp",
                        f"zed.{name}_timestamps[{index}]",
                        f"{later} follows {earlier}",
                    )
                )
    device_timestamps = timestamp_streams["device"]
    frame_intervals = [
        later - earlier
        for earlier, later in zip(
            device_timestamps, device_timestamps[1:], strict=False
        )
        if later > earlier
    ]
    allowed_age = max(frame_intervals, default=math.ceil(1e9 / fps))
    for modality, policy_field, stream, stale_code in (
        (
            "zed_imu",
            "imu_policy",
            "imu",
            "stale_imu",
        ),
        (
            "zed_pose",
            "pose_policy",
            "pose",
            "stale_pose",
        ),
    ):
        require_freshness = profile[policy_field] in {
            "every_frame_success_and_fresh",
            "every_frame_ok_and_fresh",
        }
        if modality in required_zed and require_freshness:
            timestamps = timestamp_streams[stream]
            for index, (device, modality_timestamp) in enumerate(
                zip(device_timestamps, timestamps, strict=False)
            ):
                if abs(device - modality_timestamp) > allowed_age:
                    issues.append(
                        ValidationIssue(
                            stale_code,
                            f"zed.frames[{index}].{stream}_timestamp_ns",
                            f"modality/image time differs by more than "
                            f"{allowed_age} ns",
                        )
                    )
    same_run = 1
    for index, (earlier, later) in enumerate(
        zip(successful_signatures, successful_signatures[1:], strict=False), 1
    ):
        same_run = same_run + 1 if later == earlier else 1
        if same_run > 2:
            issues.append(
                ValidationIssue(
                    "stale_zed_frame",
                    f"zed.image_signatures[{index}]",
                    f"same content signature repeated for {same_run} frames",
                )
            )
            break
    return ValidationReport(
        (
            {
                "id": "zed_records_declared_profile",
                "status": "passed" if not issues else "failed",
                "required_modalities": sorted(required_zed),
                "record_count": len(records),
                "minimum_record_count": expected_minimum,
            },
        ),
        tuple(issues),
    )


def validate_zed_records(
    records: Sequence[Mapping[str, Any]],
    *,
    duration_s: float,
    fps: int,
    validation_profile: Mapping[str, Any],
) -> ValidationReport:
    """Validate ZED image/depth/IMU/pose sidecar records."""

    if dict(validation_profile) != dict(S42_VALIDATION_PROFILE):
        return _validate_declared_zed_modalities(
            records,
            duration_s=duration_s,
            fps=fps,
            profile=validation_profile,
        )

    issues: list[ValidationIssue] = []
    expected_minimum = math.floor(duration_s * fps * 0.90)
    if len(records) < expected_minimum:
        issues.append(
            ValidationIssue(
                "incomplete_zed_output",
                "zed.frames",
                f"expected at least {expected_minimum} records, got {len(records)}",
            )
        )
    device_timestamps: list[int] = []
    host_monotonic_timestamps: list[int] = []
    host_wall_timestamps: list[int] = []
    imu_timestamps: list[int] = []
    pose_timestamps: list[int] = []
    signatures: list[str] = []
    required = {
        "frame_index",
        "device_timestamp_ns",
        "host_wall_time_utc",
        "host_monotonic_ns",
        "image_status",
        "image_signature_sha256",
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
        "frame_name",
        "units",
    }
    for index, record in enumerate(records):
        missing = sorted(required - record.keys())
        if missing:
            issues.append(
                ValidationIssue(
                    "missing_zed_metadata",
                    f"zed.frames[{index}]",
                    f"missing keys: {missing}",
                )
            )
            continue
        if record["frame_index"] != index:
            issues.append(
                ValidationIssue(
                    "nonsequential_frame_index",
                    f"zed.frames[{index}].frame_index",
                    f"expected {index}, got {record['frame_index']!r}",
                )
            )
        for key, code in (
            ("image_status", "failed_image_retrieval"),
            ("depth_status", "failed_depth_retrieval"),
            ("imu_status", "failed_imu_retrieval"),
        ):
            if record[key] != "SUCCESS":
                issues.append(
                    ValidationIssue(
                        code, f"zed.frames[{index}].{key}", str(record[key])
                    )
                )
        if record["pose_status"] != "OK":
            issues.append(
                ValidationIssue(
                    "invalid_pose_state",
                    f"zed.frames[{index}].pose_status",
                    str(record["pose_status"]),
                )
            )
        if record["frame_name"] != "F_zed_world_y_up":
            issues.append(
                ValidationIssue(
                    "invalid_coordinate_frame",
                    f"zed.frames[{index}].frame_name",
                    repr(record["frame_name"]),
                )
            )
        depth_grid = record["depth_sample_grid_m"]
        depth_shape = record["depth_sample_grid_shape"]
        if (
            not isinstance(depth_grid, list)
            or not isinstance(depth_shape, list)
            or len(depth_shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in depth_shape)
            or len(depth_grid) != depth_shape[0] * depth_shape[1]
            or not any(
                isinstance(value, (int, float)) and math.isfinite(float(value))
                for value in depth_grid
            )
        ):
            issues.append(
                ValidationIssue(
                    "invalid_depth_record",
                    f"zed.frames[{index}].depth_sample_grid_m",
                    "must be a shaped grid containing at least one finite depth "
                    "in meters",
                )
            )
        if record["depth_sample_stride_px"] != [60, 64]:
            issues.append(
                ValidationIssue(
                    "invalid_depth_stride",
                    f"zed.frames[{index}].depth_sample_stride_px",
                    repr(record["depth_sample_stride_px"]),
                )
            )
        if record["units"] != {"position": "m", "time": "ns", "angle": "rad"}:
            issues.append(
                ValidationIssue(
                    "invalid_units",
                    f"zed.frames[{index}].units",
                    repr(record["units"]),
                )
            )
        timestamp_values: dict[str, int] = {}
        try:
            for key in (
                "device_timestamp_ns",
                "host_monotonic_ns",
                "imu_timestamp_ns",
                "pose_timestamp_ns",
            ):
                raw_value = record[key]
                if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                    raise TypeError(key)
                if raw_value <= 0:
                    raise ValueError(key)
                timestamp_values[key] = raw_value
            wall = datetime.fromisoformat(str(record["host_wall_time_utc"]))
            if wall.tzinfo is None:
                raise ValueError("host_wall_time_utc")
            wall_ns = round(wall.timestamp() * 1e9)
            device_timestamps.append(timestamp_values["device_timestamp_ns"])
            host_monotonic_timestamps.append(timestamp_values["host_monotonic_ns"])
            host_wall_timestamps.append(wall_ns)
            imu_timestamps.append(timestamp_values["imu_timestamp_ns"])
            pose_timestamps.append(timestamp_values["pose_timestamp_ns"])
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    "invalid_timestamp",
                    f"zed.frames[{index}]",
                    "host wall, host monotonic, device, IMU, and pose timestamps "
                    "must be positive, timezone-aware, and type-safe",
                )
            )
        pose = record["pose"]
        if not isinstance(pose, Mapping) or pose.get("valid") is not True:
            issues.append(
                ValidationIssue(
                    "invalid_pose",
                    f"zed.frames[{index}].pose",
                    "pose.valid must be true",
                )
            )
        else:
            translation = pose.get("translation_xyz_m")
            orientation = pose.get("orientation_xyzw")
            confidence = pose.get("confidence_percent")
            vectors_valid = all(
                isinstance(vector, list)
                and len(vector) == length
                and all(
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    for value in vector
                )
                for vector, length in ((translation, 3), (orientation, 4))
            )
            orientation_norm = (
                math.sqrt(sum(float(value) ** 2 for value in orientation))
                if vectors_valid
                else 0.0
            )
            if (
                not vectors_valid
                or not 0.5 <= orientation_norm <= 1.5
                or isinstance(confidence, bool)
                or not isinstance(confidence, int)
                or not 0 <= confidence <= 100
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_pose",
                        f"zed.frames[{index}].pose",
                        "pose vectors, quaternion norm, or confidence are invalid",
                    )
                )
        imu = record["imu"]
        if not isinstance(imu, Mapping) or any(
            not isinstance(imu.get(key), list)
            or len(imu[key]) != length
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in imu[key]
            )
            for key, length in (
                ("linear_acceleration_m_s2", 3),
                ("angular_velocity_rad_s", 3),
                ("orientation_xyzw", 4),
            )
        ):
            issues.append(
                ValidationIssue(
                    "invalid_imu_record",
                    f"zed.frames[{index}].imu",
                    "IMU vectors must be finite 3/3/4 component arrays",
                )
            )
        signature = record["image_signature_sha256"]
        if not isinstance(signature, str) or len(signature) != 64:
            issues.append(
                ValidationIssue(
                    "invalid_image_signature",
                    f"zed.frames[{index}].image_signature_sha256",
                    repr(signature),
                )
            )
        else:
            signatures.append(signature)
    for name, timestamps in (
        ("host_wall", host_wall_timestamps),
        ("host_monotonic", host_monotonic_timestamps),
        ("device", device_timestamps),
        ("imu", imu_timestamps),
        ("pose", pose_timestamps),
    ):
        for index, (earlier, later) in enumerate(
            zip(timestamps, timestamps[1:], strict=False), 1
        ):
            if later == earlier:
                issues.append(
                    ValidationIssue(
                        "duplicate_timestamp",
                        f"zed.frames[{index}].{name}_timestamp_ns",
                        str(later),
                    )
                )
            elif later < earlier:
                issues.append(
                    ValidationIssue(
                        "nonmonotonic_timestamp",
                        f"zed.frames[{index}].{name}_timestamp_ns",
                        f"{later} follows {earlier}",
                    )
                )
    if device_timestamps and pose_timestamps:
        frame_intervals = [
            later - earlier
            for earlier, later in zip(
                device_timestamps, device_timestamps[1:], strict=False
            )
            if later > earlier
        ]
        allowed_age = max(frame_intervals, default=math.ceil(1e9 / fps))
        for index, (device, pose) in enumerate(
            zip(device_timestamps, pose_timestamps, strict=False)
        ):
            if abs(device - pose) > allowed_age:
                issues.append(
                    ValidationIssue(
                        "stale_pose",
                        f"zed.frames[{index}].pose_timestamp_ns",
                        f"pose/image timestamp difference exceeds {allowed_age} ns",
                    )
                )
        for index, (device, imu) in enumerate(
            zip(device_timestamps, imu_timestamps, strict=False)
        ):
            if abs(device - imu) > allowed_age:
                issues.append(
                    ValidationIssue(
                        "stale_imu",
                        f"zed.frames[{index}].imu_timestamp_ns",
                        f"IMU/image timestamp difference exceeds {allowed_age} ns",
                    )
                )
    same_run = 1
    for index, (earlier, later) in enumerate(
        zip(signatures, signatures[1:], strict=False), 1
    ):
        same_run = same_run + 1 if later == earlier else 1
        if same_run > 2:
            issues.append(
                ValidationIssue(
                    "stale_zed_frame",
                    f"zed.frames[{index}].image_signature_sha256",
                    f"same content signature repeated for {same_run} frames",
                )
            )
            break
    return ValidationReport(
        (
            {
                "id": "zed_records",
                "status": "passed" if not issues else "failed",
                "record_count": len(records),
                "minimum_record_count": expected_minimum,
            },
        ),
        tuple(issues),
    )


def validate_svo_replay_report(
    report: Mapping[str, Any],
    *,
    expected_serial: str,
    expected_resolution: str,
    expected_fps: int,
    expected_depth_mode: str,
    expected_frame_count: int,
    frame_count_policy: str = "exact_jsonl_match",
    required_modalities: Iterable[str] = (
        "zed_image",
        "zed_depth",
        "zed_imu",
        "zed_pose",
    ),
) -> ValidationReport:
    """Validate an SDK-produced, full-file SVO2 replay report."""

    issues: list[ValidationIssue] = []
    expected = {
        "schema": SVO_REPLAY_SCHEMA,
        "status": "passed",
        "identity.serial": expected_serial,
        "capture.resolution": expected_resolution,
        "capture.fps": expected_fps,
        "capture.depth_mode": expected_depth_mode,
        "end_of_svo_reached": True,
    }
    for path, value in expected.items():
        _expect_equal(report, path, value, issues, "svo_replay_mismatch")
    declared = report.get("declared_frame_count")
    replayed = report.get("replayed_frame_count")
    if (
        isinstance(declared, bool)
        or not isinstance(declared, int)
        or declared <= 0
        or replayed != declared
    ):
        issues.append(
            ValidationIssue(
                "svo_replay_mismatch",
                "replayed_frame_count",
                f"full replay must equal positive declared count; declared "
                f"{declared!r}, replayed {replayed!r}",
            )
        )
    if frame_count_policy == "exact_jsonl_match":
        if declared != expected_frame_count:
            issues.append(
                ValidationIssue(
                    "svo_frame_count_mismatch",
                    "declared_frame_count",
                    f"expected exact JSONL count {expected_frame_count}, got "
                    f"{declared!r}",
                )
            )
    elif frame_count_policy != "declared_coverage":
        issues.append(
            ValidationIssue(
                "invalid_svo_frame_count_policy",
                "frame_count_policy",
                repr(frame_count_policy),
            )
        )
    representatives = report.get("representative_frames")
    representative_count = declared if isinstance(declared, int) and declared > 0 else 0
    expected_indices = (
        sorted({0, representative_count // 2, max(0, representative_count - 2)})
        if representative_count
        else []
    )
    if (
        not isinstance(representatives, list)
        or [
            item.get("frame_index")
            for item in representatives
            if isinstance(item, Mapping)
        ]
        != expected_indices
    ):
        issues.append(
            ValidationIssue(
                "svo_representative_frame_mismatch",
                "representative_frames",
                f"expected frame indices {expected_indices}",
            )
        )
    else:
        required = set(required_modalities)
        representative_statuses = {
            "zed_image": ("image_status", "SUCCESS"),
            "zed_depth": ("depth_status", "SUCCESS"),
            "zed_imu": ("imu_status", "SUCCESS"),
            "zed_pose": ("pose_status", "OK"),
        }
        for item in representatives:
            failed = [
                field
                for modality, (
                    field,
                    expected_status,
                ) in representative_statuses.items()
                if modality in required and item.get(field) != expected_status
            ]
            if failed:
                issues.append(
                    ValidationIssue(
                        "svo_representative_retrieval_failed",
                        f"representative_frames[{item.get('frame_index')}]",
                        f"failed required status fields {failed}: {item!r}",
                    )
                )
    return ValidationReport(
        (
            {
                "id": "svo2_sdk_replay",
                "status": "passed" if not issues else "failed",
                "expected_frame_count": expected_frame_count,
            },
        ),
        tuple(issues),
    )


def validate_playback_capture_overlap(
    playback: Mapping[str, Any],
    zed_records: Sequence[Mapping[str, Any]],
    *,
    reference_duration_s: float,
    playback_duration_tolerance_s: float,
) -> ValidationReport:
    """Require complete Mac playback inside live Pi and local ZED capture windows."""

    issues: list[ValidationIssue] = []
    envelope = playback.get("workstation_envelope")
    remote = playback.get("remote")
    if not isinstance(envelope, Mapping) or not isinstance(remote, Mapping):
        return ValidationReport(
            (),
            (
                ValidationIssue(
                    "missing_playback_overlap_evidence",
                    "playback.json",
                    "workstation envelope and remote playback record are required",
                ),
            ),
        )
    try:
        start_ns = int(envelope["started_monotonic_ns"])
        completed_ns = int(envelope["completed_monotonic_ns"])
        remote_elapsed_s = (
            int(remote["completed_monotonic_ns"]) - int(remote["started_monotonic_ns"])
        ) / 1e9
    except (KeyError, TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "invalid_playback_timing",
                "playback.json",
                "playback timing fields must be integer monotonic timestamps",
            )
        )
        start_ns = completed_ns = 0
        remote_elapsed_s = 0.0
    if remote.get("exit_status") != 0 or playback.get("return_code") != 0:
        issues.append(
            ValidationIssue(
                "playback_failed", "playback.json", "afplay did not exit successfully"
            )
        )
    if not (
        reference_duration_s
        <= remote_elapsed_s
        <= reference_duration_s + playback_duration_tolerance_s
    ):
        issues.append(
            ValidationIssue(
                "playback_duration_mismatch",
                "playback.remote",
                f"expected elapsed in [{reference_duration_s:.3f}, "
                f"{reference_duration_s + playback_duration_tolerance_s:.3f}] s, "
                f"got {remote_elapsed_s:.6f} s",
            )
        )
    alive = envelope.get("recorders_alive")
    if not isinstance(alive, Mapping) or any(
        alive.get(stage, {}).get(recorder) is not True
        for stage in ("before_playback", "after_playback", "after_post_margin")
        for recorder in ("pi", "zed")
    ):
        issues.append(
            ValidationIssue(
                "incomplete_playback_capture_overlap",
                "playback.workstation_envelope.recorders_alive",
                "both recorders must remain alive before, after, and through the "
                "post-playback margin",
            )
        )
    try:
        first_zed = int(zed_records[0]["host_monotonic_ns"])
        last_zed = int(zed_records[-1]["host_monotonic_ns"])
        if first_zed > start_ns or last_zed < completed_ns:
            issues.append(
                ValidationIssue(
                    "incomplete_zed_playback_overlap",
                    "raw/zed_frames.jsonl",
                    f"ZED host interval [{first_zed}, {last_zed}] does not bracket "
                    f"playback [{start_ns}, {completed_ns}]",
                )
            )
    except (IndexError, KeyError, TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "invalid_zed_playback_overlap",
                "raw/zed_frames.jsonl",
                "cannot derive retained ZED host interval",
            )
        )
    return ValidationReport(
        (
            {
                "id": "playback_capture_overlap",
                "status": "passed" if not issues else "failed",
                "reference_duration_s": reference_duration_s,
                "remote_playback_elapsed_s": remote_elapsed_s,
                "ssh_timing_is_synchronization": False,
            },
        ),
        tuple(issues),
    )


def calculate_alignment(
    *,
    audio_event_sample_index: int,
    audio_sample_rate_hz: int,
    zed_first_timestamp_ns: int,
    zed_event_timestamp_ns: int,
    audio_localization_half_width_samples: int,
    zed_frame_interval_ns: int,
    zed_localization_half_width_frames: float,
    extra_uncertainty_ms: float = 0.0,
    event_unique: bool,
    event_visible: bool,
    event_audible: bool,
    maximum_uncertainty_ms: float = 50.0,
) -> dict[str, Any]:
    """Compute cross-system elapsed-time offset and frozen RSS uncertainty."""

    if audio_event_sample_index < 0 or audio_localization_half_width_samples < 0:
        raise ValueError("audio sample indices and half-width must be non-negative")
    if audio_sample_rate_hz <= 0 or zed_frame_interval_ns <= 0:
        raise ValueError("sample rate and ZED frame interval must be positive")
    if zed_event_timestamp_ns < zed_first_timestamp_ns:
        raise ValueError("ZED event timestamp precedes first ZED timestamp")
    if zed_localization_half_width_frames < 0 or extra_uncertainty_ms < 0:
        raise ValueError("uncertainty components must be non-negative")
    audio_elapsed_s = audio_event_sample_index / audio_sample_rate_hz
    zed_elapsed_s = (zed_event_timestamp_ns - zed_first_timestamp_ns) / 1e9
    audio_sample_ms = 1000.0 / audio_sample_rate_hz
    audio_localization_ms = (
        audio_localization_half_width_samples * 1000.0 / audio_sample_rate_hz
    )
    zed_half_frame_ms = zed_frame_interval_ns / 2e6
    zed_localization_ms = (
        zed_localization_half_width_frames * zed_frame_interval_ns / 1e6
    )
    components = {
        "audio_sample_quantization_ms": audio_sample_ms,
        "audio_localization_ms": audio_localization_ms,
        "zed_half_frame_ms": zed_half_frame_ms,
        "zed_visual_localization_ms": zed_localization_ms,
        "extra_readout_quantization_ms": extra_uncertainty_ms,
    }
    total_uncertainty_ms = math.sqrt(
        sum(component * component for component in components.values())
    )
    reasons: list[str] = []
    if not event_unique:
        reasons.append("alignment event is not unique")
    if not event_visible:
        reasons.append("alignment event is not visible in ZED evidence")
    if not event_audible:
        reasons.append("alignment event is not audible in six-channel WAV")
    if total_uncertainty_ms > maximum_uncertainty_ms:
        reasons.append(
            f"uncertainty {total_uncertainty_ms:.6f} ms exceeds "
            f"{maximum_uncertainty_ms:.6f} ms"
        )
    return {
        "schema": ALIGNMENT_SCHEMA,
        "status": "passed" if not reasons else "failed",
        "method": "visible_audible_impact",
        "audio_event_sample_index": audio_event_sample_index,
        "audio_sample_rate_hz": audio_sample_rate_hz,
        "audio_event_elapsed_s": audio_elapsed_s,
        "zed_first_timestamp_ns": zed_first_timestamp_ns,
        "zed_event_timestamp_ns": zed_event_timestamp_ns,
        "zed_event_elapsed_s": zed_elapsed_s,
        "offset_s": zed_elapsed_s - audio_elapsed_s,
        "offset_definition": "zed_event_elapsed_s - audio_event_elapsed_s",
        "uncertainty_components": components,
        "total_uncertainty_ms": total_uncertainty_ms,
        "maximum_uncertainty_ms": maximum_uncertainty_ms,
        "event_unique": event_unique,
        "event_visible": event_visible,
        "event_audible": event_audible,
        "failure_reasons": reasons,
        "supported_claims": [
            "coarse audio-video association",
            "metrics with decision margin greater than total_uncertainty_ms",
        ],
        "unsupported_claims": [
            "sample-accurate synchronization",
            "acoustic time-of-flight",
            "absolute capture latency",
            "host clock synchronization",
            "calibrated optical-acoustic extrinsics",
        ],
        "ssh_timing_is_synchronization": False,
    }


def recompute_alignment_from_evidence(
    annotation: Mapping[str, Any],
    captured_wav: str | Path,
    zed_records: Sequence[Mapping[str, Any]],
    configuration: Mapping[str, Any],
) -> tuple[dict[str, Any], ValidationReport]:
    """Recalculate alignment from retained media and reject forged summaries."""

    from statistics import median

    issues: list[ValidationIssue] = []
    try:
        audio_properties, audio_issues = inspect_six_channel_wav(
            captured_wav,
            expected_duration_s=float(configuration["session"]["duration_s"]),
            duration_tolerance_s=float(
                configuration["session"]["duration_tolerance_s"]
            ),
            require_nonsilent_channels=configuration["validation_profile"][
                "channel_signal_policy"
            ]
            == "all_channels_nonsilent",
            reject_sustained_clipping=configuration["validation_profile"][
                "clipping_policy"
            ]
            == "reject_sustained",
        )
        issues.extend(audio_issues)
        sample_index = int(annotation["audio_event_sample_index"])
        frame_index = int(annotation["zed_event_frame_index"])
        audio_half_width = int(annotation["audio_localization_half_width_samples"])
        zed_half_width = float(annotation["zed_localization_half_width_frames"])
        extra_uncertainty = float(annotation.get("extra_readout_quantization_ms", 0.0))
        if not 0 <= sample_index < int(audio_properties["decoded_frame_count"]):
            raise ValueError("audio event sample index is outside retained WAV")
        if not 0 <= frame_index < len(zed_records):
            raise ValueError("ZED event frame index is outside retained JSONL")
        timestamps = [int(record["device_timestamp_ns"]) for record in zed_records]
        intervals = [
            later - earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
            if later > earlier
        ]
        if not intervals:
            raise ValueError("cannot derive a ZED frame interval")
        recomputed = calculate_alignment(
            audio_event_sample_index=sample_index,
            audio_sample_rate_hz=int(configuration["respeaker"]["sample_rate_hz"]),
            zed_first_timestamp_ns=timestamps[0],
            zed_event_timestamp_ns=timestamps[frame_index],
            audio_localization_half_width_samples=audio_half_width,
            zed_frame_interval_ns=round(median(intervals)),
            zed_localization_half_width_frames=zed_half_width,
            extra_uncertainty_ms=extra_uncertainty,
            event_unique=annotation.get("event_unique") is True,
            event_visible=annotation.get("event_visible") is True,
            event_audible=annotation.get("event_audible") is True,
            maximum_uncertainty_ms=float(
                configuration["alignment"]["maximum_uncertainty_ms"]
            ),
        )
        recomputed.update(
            {
                "zed_event_frame_index": frame_index,
                "audio_localization_half_width_samples": audio_half_width,
                "zed_localization_half_width_frames": zed_half_width,
                "extra_readout_quantization_ms": extra_uncertainty,
                "source": "recomputed_from_retained_wav_and_jsonl",
            }
        )
    except (KeyError, TypeError, ValueError, S42Error) as exc:
        issues.append(
            ValidationIssue(
                "alignment_recomputation_failed",
                "alignment.json",
                str(exc),
            )
        )
        recomputed = {
            "schema": ALIGNMENT_SCHEMA,
            "status": "failed",
            "source": "recomputed_from_retained_wav_and_jsonl",
            "failure_reasons": [str(exc)],
        }
    comparable_fields = (
        "audio_event_sample_index",
        "audio_sample_rate_hz",
        "zed_first_timestamp_ns",
        "zed_event_timestamp_ns",
        "zed_event_frame_index",
        "offset_s",
        "total_uncertainty_ms",
        "status",
    )
    for field in comparable_fields:
        stored = annotation.get(field)
        actual = recomputed.get(field)
        if isinstance(actual, float) and isinstance(stored, (int, float)):
            matches = math.isclose(float(stored), actual, abs_tol=1e-12)
        else:
            matches = stored == actual
        if not matches:
            issues.append(
                ValidationIssue(
                    "inconsistent_alignment_report",
                    f"alignment.json.{field}",
                    f"stored {stored!r}, recomputed {actual!r}",
                )
            )
    if recomputed.get("status") != "passed":
        issues.append(
            ValidationIssue(
                "alignment_failed",
                "alignment.json",
                repr(recomputed.get("failure_reasons")),
            )
        )
    return recomputed, ValidationReport(
        (
            {
                "id": "alignment_recomputed_from_retained_evidence",
                "status": "passed" if not issues else "failed",
            },
        ),
        tuple(issues),
    )


def artifact_record(
    path: str | Path,
    *,
    role: str,
    root: str | Path,
    media_properties: Mapping[str, Any] | None = None,
    acquisition_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe one finalized artifact relative to an attempt root."""

    artifact = Path(path)
    relative = artifact.relative_to(Path(root))
    record = {
        "path": relative.as_posix(),
        "local_relative_path": relative.as_posix(),
        "role": role,
        "retention": "machine_local_gitignored",
        "byte_size": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
        "acquisition_contract": dict(
            acquisition_contract
            or {
                "configuration": "normalized_configuration.json",
                "lifecycle": "lifecycle.json",
                "publication": "S2.2 atomic writer/session lifecycle",
            }
        ),
        "media_properties": dict(
            media_properties
            or {"format": "role-specific record; see role and acquisition contract"}
        ),
    }
    return record


def verify_artifact_records(
    root: str | Path, records: Sequence[Mapping[str, Any]]
) -> ValidationReport:
    """Reject missing, unsafe, duplicate, or checksum-mismatched artifacts."""

    evidence_root = Path(root).resolve()
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value:
            issues.append(
                ValidationIssue(
                    "invalid_artifact_path",
                    f"artifacts[{index}].path",
                    repr(path_value),
                )
            )
            continue
        if path_value in seen:
            issues.append(
                ValidationIssue(
                    "duplicate_artifact", f"artifacts[{index}].path", path_value
                )
            )
            continue
        seen.add(path_value)
        candidate = (evidence_root / path_value).resolve()
        try:
            candidate.relative_to(evidence_root)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "unsafe_artifact_path", f"artifacts[{index}].path", path_value
                )
            )
            continue
        if not candidate.is_file():
            issues.append(
                ValidationIssue("missing_artifact", path_value, "file is missing")
            )
            continue
        expected_bytes = record.get("byte_size")
        if expected_bytes != candidate.stat().st_size:
            issues.append(
                ValidationIssue(
                    "artifact_size_mismatch",
                    path_value,
                    f"expected {expected_bytes!r}, got {candidate.stat().st_size}",
                )
            )
        expected_hash = record.get("sha256")
        actual_hash = sha256_file(candidate)
        if expected_hash != actual_hash:
            issues.append(
                ValidationIssue(
                    "checksum_mismatch",
                    path_value,
                    f"expected {expected_hash!r}, got {actual_hash}",
                )
            )
    return ValidationReport(
        (
            {
                "id": "artifact_integrity",
                "status": "passed" if not issues else "failed",
                "artifact_count": len(records),
            },
        ),
        tuple(issues),
    )


def write_checksums(
    output: str | Path, root: str | Path, records: Sequence[Mapping[str, Any]]
) -> None:
    """Write sorted GNU-compatible SHA-256 lines through an S2.2 staged file."""

    destination = Path(output)
    staged = StagedFile(destination.parent / "_staging", destination.name + ".incoming")
    try:
        for record in sorted(records, key=lambda item: str(item["path"])):
            line = f"{record['sha256']}  {record['path']}\n".encode()
            staged.append(line)
        publish_file(staged, destination)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise


def fsync_file(stream: BinaryIO) -> None:
    """Explicitly flush and fsync a producer-owned stream before inspection."""

    stream.flush()
    os.fsync(stream.fileno())


__all__ = [
    "ALIGNMENT_SCHEMA",
    "ATTEMPT_SCHEMA",
    "AttemptLifecycle",
    "CONFIG_SCHEMA",
    "EXPECTED_CHANNEL_ORDER",
    "LIFECYCLE_SCHEMA",
    "S42Error",
    "ValidationIssue",
    "ValidationReport",
    "artifact_record",
    "calculate_alignment",
    "disk_space_check",
    "inspect_six_channel_wav",
    "load_json",
    "normalize_configuration",
    "promote_finalized_file",
    "read_jsonl",
    "sha256_file",
    "validate_configuration",
    "validate_mac_dynamic_preflight",
    "validate_mac_preflight",
    "validate_zed_records",
    "verify_artifact_records",
    "write_checksums",
]
