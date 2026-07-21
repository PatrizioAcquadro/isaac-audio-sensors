"""S4.3 pilot preregistration, waveform analysis, and evidence validation."""

from __future__ import annotations

import hashlib
import json
import math
import time
import wave
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_2 import (
    ValidationIssue,
    ValidationReport,
    inspect_six_channel_wav,
    operator_facing_zed_bearing_to_project,
    operator_facing_zed_position_to_project,
    sha256_file,
    validate_reference_capture,
)
from isaac_audio_sensors.core.backends.tdoa import estimate_doa_from_delays
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    relative_delays_from_tdoa_matrix,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.microphone_array import MicrophoneArraySpec
from isaac_audio_sensors.core.types import MicrophoneSpec

CONFIG_SCHEMA = "ias.s4_3.pilot_config.v1"
CONFIG_AMENDMENT_SCHEMA = "ias.s4_3.pilot_config_amendment.v1"
CORRECTIVE_CONFIG_SCHEMA = "ias.s4_3.pilot_corrective_config.v1"
PREREGISTRATION_SCHEMA = "ias.s4_3.preregistration.v1"
ANALYSIS_SCHEMA = "ias.s4_3.trial_analysis.v1"
INVENTORY_SCHEMA = "ias.s4_3.trial_inventory.v1"
REVIEW_REMEDIATION_SCHEMA = "ias.s4_3.review_remediation_manifest.v1"
CLIPPING_CORRECTIVE_SCHEMA = "ias.s4_3.clipping_corrective.v1"
TRANSIENT_EVENT_CONTRACT_SCHEMA = "ias.s4_3.transient_event_contract.v1"
EXPECTED_CATEGORIES = {"repeatability", "controlled", "robustness"}
EXPECTED_PROJECT_FRAME = {
    "frame_name": "F_project",
    "origin": "ZED stereo-lens midpoint",
    "axes": {
        "x": "forward",
        "y": "right_as_viewed_from_zed_operator_left_facing_camera",
        "z": "up",
    },
    "bearing_definition": "degrees clockwise from +X toward +Y viewed from above",
    "position_units": "m",
}
EXPECTED_OPERATOR_FACING_FRAME = {
    "frame_name": "F_operator_facing_zed",
    "origin": "ZED stereo-lens midpoint",
    "viewpoint": "operator standing in front of and facing the ZED",
    "axes": {
        "positive_x": "behind_operator_forward_of_zed",
        "negative_x": "in_front_of_operator_behind_zed",
        "positive_y": "operator_right",
        "negative_y": "operator_left",
        "positive_z": "up_toward_ceiling",
        "negative_z": "down_toward_floor",
    },
    "bearing_definition": "degrees clockwise from +X toward +Y viewed from above",
    "position_units": "m",
    "operator_to_project": {
        "x_project": "x_operator",
        "y_project": "-y_operator",
        "z_project": "z_operator",
        "bearing_project": "(-bearing_operator) mod 360",
    },
}
EXPECTED_S42_COORDINATE_CORRECTION_ID = "S4.2-DUAL-FRAME-RECONCILIATION-2026-07-21-A"
EXPECTED_OUTCOMES = {
    "planned",
    "rejected",
    "interrupted",
    "failed",
    "unfavorable",
    "accepted",
}
EXPECTED_OPERATIONAL_GATE_POLICY = {
    "id": "S4.3-OPERATIONAL-GATES-AMENDMENT-02",
    "mac_dynamic_preflight": {
        "aggregate_status": "metadata_only",
        "command_return_code": "metadata_only_if_valid_report_present",
        "power": "metadata_only",
        "hard_fields": {
            "device_name": "MacBook Pro Speakers",
            "channel_count": 2,
            "nominal_sample_rate_hz": 48000,
            "output_volume": 40,
            "output_muted": False,
        },
    },
    "zed_impact_capture": {
        "version_policy": "metadata",
        "reference_versions": {
            "sdk_version": "5.4.0",
            "camera_firmware": "1523",
            "sensor_firmware": "777",
        },
        "metadata_only": [
            "sdk_version",
            "camera_firmware",
            "sensor_firmware",
            "version_comparisons",
        ],
        "hard_checks": [
            "serial_matches",
            "usb_video_present",
            "usb_serial_present",
            "usb_3_speed",
            "resolution_matches",
            "fps_matches",
            "depth_mode_requested",
            "grab_success",
            "image_retrieved",
            "depth_retrieved_gpu_authoritative",
            "imu_retrieved",
            "pose_ok",
            "svo_recording_enabled",
            "strictly_increasing_device_timestamps",
            "producer_outputs_complete",
            "full_svo2_replay",
        ],
    },
}
EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL = {
    "operator_ready_before_producer_start": True,
    "stimulus_cue_after_all_producers_ready": True,
    "settle_before_stimulus_cue_s": 2.0,
    "operator_input_does_not_consume_capture_duration": True,
}


class S43Error(RuntimeError):
    """Fail-closed S4.3 contract or evidence error."""


def load_json(path: str | Path) -> dict[str, Any]:
    """Read one JSON object with a located error."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S43Error(f"{source}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise S43Error(f"{source}: root must be an object")
    return payload


def canonical_sha256(value: Any) -> str:
    """Hash canonical compact JSON without mutating the input."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_mac_dynamic_preflight_report(
    payload: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate S4.3 Mac hard fields while retaining power as metadata."""

    expected_header = {
        "schema": "ias.s4_2.mac_dynamic_preflight.v1",
        "read_only": True,
        "scope": "per_take_dynamic_only",
    }
    for key, value in expected_header.items():
        if payload.get(key) != value:
            raise S43Error(f"Mac dynamic preflight mismatch: {key}")
    policy = configuration.get("operational_gate_policy")
    if policy is None:
        if payload.get("status") != "passed":
            raise S43Error("Mac dynamic preflight mismatch: status")
        if payload.get("power", {}).get("on_ac_power") is not True:
            raise S43Error("Mac is not on AC power")
        hard_fields = {
            "device_name": configuration["hardware"]["mac_output_device"],
            "output_volume": configuration["hardware"]["mac_volume_percent"],
            "output_muted": False,
        }
    else:
        if policy != EXPECTED_OPERATIONAL_GATE_POLICY:
            raise S43Error("unexpected S4.3 operational gate policy")
        hard_fields = dict(policy["mac_dynamic_preflight"]["hard_fields"])

    audio = payload.get("audio_output", {})
    volume = payload.get("volume", {})
    observed = {
        "device_name": audio.get("device_name"),
        "channel_count": audio.get("channel_count"),
        "nominal_sample_rate_hz": audio.get("nominal_sample_rate_hz"),
        "output_volume": volume.get("output_volume"),
        "output_muted": volume.get("output_muted"),
    }
    for key, expected in hard_fields.items():
        if observed.get(key) != expected:
            raise S43Error(f"Mac dynamic preflight hard field mismatch: {key}")
    if policy is not None:
        checks = payload.get("checks", {})
        required_checks = (
            "output_channels_match",
            "output_device_matches",
            "output_sample_rate_matches",
            "unmuted",
            "volume_matches",
        )
        for key in required_checks:
            if checks.get(key) is not True:
                raise S43Error(f"Mac dynamic preflight hard check failed: {key}")
    return {
        "status": "passed",
        "hard_fields": observed,
        "aggregate_status_metadata": payload.get("status"),
        "power_metadata": deepcopy(payload.get("power")),
    }


def evaluate_zed_startup_contract(
    *,
    identity: Mapping[str, Any],
    expected_serial: str,
    reference_sdk: str,
    reference_camera_firmware: str,
    reference_sensor_firmware: str,
    version_policy: str,
    usb_video_present: bool,
    usb_serial_present: bool,
    usb_speed_mbps: float,
    minimum_usb_speed_mbps: float,
    dimensions_px: Sequence[int],
    resolution: str,
    actual_fps: int,
    requested_fps: int,
    depth_mode: str,
) -> dict[str, Any]:
    """Split hard ZED capture checks from SDK/firmware provenance."""

    if version_policy not in {"exact", "metadata"}:
        raise S43Error(f"unsupported ZED version policy: {version_policy}")
    version_reference = {
        "sdk_version": reference_sdk,
        "camera_firmware": reference_camera_firmware,
        "sensor_firmware": reference_sensor_firmware,
    }
    version_comparisons = {
        key: identity.get(key) == expected
        for key, expected in version_reference.items()
    }
    hard_checks = {
        "usb_video_present": usb_video_present,
        "usb_serial_present": usb_serial_present,
        "usb_3_speed": usb_speed_mbps >= minimum_usb_speed_mbps,
        "serial_matches": identity.get("serial") == expected_serial,
        "resolution_matches": list(dimensions_px)
        == ({"HD720": [1280, 720]}.get(resolution)),
        "fps_matches": actual_fps == requested_fps,
        "depth_mode_requested": depth_mode == "PERFORMANCE",
    }
    if version_policy == "exact":
        hard_checks.update(
            {
                "sdk_matches": version_comparisons["sdk_version"],
                "camera_firmware_matches": version_comparisons["camera_firmware"],
                "sensor_firmware_matches": version_comparisons["sensor_firmware"],
            }
        )
    return {
        "status": "passed" if all(hard_checks.values()) else "failed",
        "hard_checks": hard_checks,
        "version_provenance": {
            "policy": version_policy,
            "reference": version_reference,
            "actual": {key: identity.get(key) for key in version_reference},
            "comparisons": version_comparisons,
            "gating": version_policy == "exact",
        },
    }


def zed_device_timestamps_are_valid(
    timestamps_ns: Sequence[int], *, frame_count: int
) -> bool:
    """Return whether every captured ZED frame has a strict device timestamp."""

    return (
        frame_count > 0
        and len(timestamps_ns) == frame_count
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in timestamps_ns
        )
        and all(
            later > earlier
            for earlier, later in zip(timestamps_ns, timestamps_ns[1:], strict=False)
        )
    )


def load_pilot_configuration(
    path: str | Path, *, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Load a base pilot configuration or one immutable strict amendment overlay."""

    source = Path(path)
    payload = load_json(source)
    if payload.get("schema") == CONFIG_SCHEMA:
        return payload
    if payload.get("schema") == CORRECTIVE_CONFIG_SCHEMA:
        allowed = {
            "schema",
            "phase",
            "id",
            "frozen_at_utc",
            "base_effective_configuration",
            "clipping_corrective",
            "prospective_transient_event_contract",
            "effective_noise_metric_contract",
            "matrix_additions",
            "authorization",
            "supersedes",
            "phase_boundary",
        }
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise S43Error(f"{source}: unexpected corrective fields {unexpected}")
        root = Path(repo_root) if repo_root is not None else source.resolve().parents[1]

        def bound_payload(
            field: str, expected_schema: str
        ) -> tuple[dict[str, Any], str]:
            record = payload.get(field)
            if not isinstance(record, Mapping):
                raise S43Error(f"{source}: {field} must be an object")
            relative = record.get("path")
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                raise S43Error(f"{source}: unsafe {field} path")
            target = root / relative
            if not target.is_file() or sha256_file(target) != record.get("sha256"):
                raise S43Error(f"{source}: {field} SHA-256 mismatch or file absent")
            value = load_json(target)
            if value.get("schema") != expected_schema:
                raise S43Error(f"{source}: {field} schema mismatch")
            return value, relative

        base_record = payload.get("base_effective_configuration")
        if not isinstance(base_record, Mapping):
            raise S43Error(f"{source}: base_effective_configuration must be an object")
        base_relative = base_record.get("path")
        if (
            not isinstance(base_relative, str)
            or Path(base_relative).is_absolute()
            or ".." in Path(base_relative).parts
        ):
            raise S43Error(f"{source}: unsafe base effective configuration path")
        base_path = root / base_relative
        if not base_path.is_file() or sha256_file(base_path) != base_record.get(
            "sha256"
        ):
            raise S43Error(f"{source}: base effective configuration SHA-256 mismatch")
        base = load_pilot_configuration(base_path, repo_root=root)
        if canonical_sha256(base) != base_record.get("effective_canonical_sha256"):
            raise S43Error(f"{source}: base effective canonical SHA-256 mismatch")
        clipping, clipping_relative = bound_payload(
            "clipping_corrective", CLIPPING_CORRECTIVE_SCHEMA
        )
        transient, transient_relative = bound_payload(
            "prospective_transient_event_contract", TRANSIENT_EVENT_CONTRACT_SCHEMA
        )

        def verify_nested_binding(
            record: Mapping[str, Any],
            label: str,
            *,
            path_key: str = "path",
            hash_key: str = "sha256",
        ) -> None:
            relative = record.get(path_key)
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                raise S43Error(f"{source}: unsafe nested corrective binding {label}")
            target = root / relative
            if not target.is_file() or sha256_file(target) != record.get(hash_key):
                raise S43Error(
                    f"{source}: nested corrective binding {label} SHA-256 mismatch"
                )

        for label in (
            "original_frozen_configuration",
            "original_preregistration",
            "active_pre_corrective_configuration",
            "active_pre_corrective_preregistration",
        ):
            record = clipping.get(label)
            if not isinstance(record, Mapping):
                raise S43Error(f"{source}: clipping corrective {label} absent")
            verify_nested_binding(record, label)
        inherited_record = clipping.get("inherited_definition")
        if not isinstance(inherited_record, Mapping):
            raise S43Error(f"{source}: inherited clipping definition absent")
        verify_nested_binding(
            inherited_record,
            "inherited_specification",
            path_key="specification_path",
            hash_key="specification_sha256",
        )
        verify_nested_binding(
            inherited_record,
            "inherited_implementation",
            path_key="implementation_path",
            hash_key="implementation_sha256",
        )
        transient_specification = transient.get("specification")
        if not isinstance(transient_specification, Mapping):
            raise S43Error(f"{source}: transient-event specification absent")
        verify_nested_binding(transient_specification, "transient_event_specification")
        inherited = clipping.get("inherited_definition", {})
        correction = clipping.get("corrected_effective_definition", {})
        if (
            inherited.get("sample_rate_hz") != 16_000
            or inherited.get("sustained_duration_ms") != 250
            or inherited.get("run_samples") != 4_000
            or clipping.get("original_s4_3_value_samples") != 8
            or correction.get("maximum_sustained_clip_run_samples") != 4_000
            or correction.get("failure_comparator") != "greater_than_or_equal"
            or correction.get("declared_channel_scope") != "all"
        ):
            raise S43Error(f"{source}: clipping corrective semantics mismatch")
        detector = transient.get("detector")
        if not isinstance(detector, Mapping):
            raise S43Error(f"{source}: transient detector provenance absent")
        required_detector = {
            "sample_rate_hz": 16_000,
            "energy_window_samples": 320,
            "absolute_rms_floor_full_scale": 0.002,
            "robust_sigma_multiplier": 8.0,
            "maximum_bridge_gap_samples": 1_600,
            "minimum_event_duration_samples": 160,
            "maximum_transient_duration_samples": 16_000,
            "minimum_concurrent_raw_channels": 2,
            "boundary_event_policy": "censored_not_counted",
            "stationary_excursion_policy": "reported_not_counted_as_transient",
            "detector_window_overlap_dependency": "none",
        }
        if any(detector.get(key) != value for key, value in required_detector.items()):
            raise S43Error(f"{source}: transient detector semantics mismatch")
        for field in (
            "new_trial_data_collected_before_freeze",
            "new_trial_results_viewed_before_freeze",
            "detector_tuned_after_new_results",
            "s4_4_started",
        ):
            if transient.get(field) is not False:
                raise S43Error(f"{source}: prospective boundary field {field} violated")
        additions = payload.get("matrix_additions")
        if not isinstance(additions, list) or len(additions) != 1:
            raise S43Error(
                f"{source}: exactly one prospective matrix addition required"
            )
        added_trial = additions[0]
        if (
            not isinstance(added_trial, Mapping)
            or added_trial.get("trial_id")
            != transient.get("prospective_evidence_trial_id")
            or added_trial.get("stimulus") != "silence"
            or added_trial.get("corrective_prospective_metric_trial") is not True
        ):
            raise S43Error(f"{source}: prospective silence trial binding mismatch")
        noise_contract = payload.get("effective_noise_metric_contract")
        if not isinstance(noise_contract, Mapping):
            raise S43Error(f"{source}: effective noise metric contract absent")
        if noise_contract.get(
            "legacy_distinct_event_rate"
        ) != "Unmeasured" or noise_contract.get(
            "prospective_detector_contract_sha256"
        ) != payload["prospective_transient_event_contract"].get("sha256"):
            raise S43Error(f"{source}: noise metric identity/provenance mismatch")
        effective = deepcopy(base)
        effective["frozen_at_utc"] = payload.get("frozen_at_utc")
        effective["quality"]["maximum_sustained_clip_run_samples"] = 4_000
        effective["metric_contracts"]["noise"] = deepcopy(noise_contract)
        effective["noise_event_detector"] = deepcopy(detector)
        effective["matrix"] = [*effective["matrix"], deepcopy(dict(added_trial))]
        effective["corrective_provenance"] = {
            "id": payload.get("id"),
            "clipping_corrective": {
                "path": clipping_relative,
                "sha256": payload["clipping_corrective"]["sha256"],
            },
            "prospective_transient_event_contract": {
                "path": transient_relative,
                "sha256": payload["prospective_transient_event_contract"]["sha256"],
                "prospective_evidence_trial_id": transient[
                    "prospective_evidence_trial_id"
                ],
            },
            "original_frozen_configuration": deepcopy(
                clipping.get("original_frozen_configuration")
            ),
            "original_preregistration": deepcopy(
                clipping.get("original_preregistration")
            ),
            "base_effective_configuration": deepcopy(base_record),
        }
        effective["configuration_source"] = {
            "schema": CORRECTIVE_CONFIG_SCHEMA,
            "path": source.relative_to(root).as_posix()
            if source.is_absolute()
            else source.as_posix(),
            "id": payload.get("id"),
            "base_effective_configuration": deepcopy(base_record),
            "supersedes": deepcopy(payload.get("supersedes")),
        }
        return effective
    if payload.get("schema") != CONFIG_AMENDMENT_SCHEMA:
        raise S43Error(f"{source}: unsupported pilot configuration schema")
    allowed = {
        "schema",
        "phase",
        "id",
        "frozen_at_utc",
        "base_configuration",
        "analysis_frame_correction",
        "matrix_additions",
        "operational_gate_policy",
        "interactive_stimulus_protocol",
        "supersedes",
        "authorization",
    }
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise S43Error(f"{source}: unexpected amendment fields {unexpected}")
    root = Path(repo_root) if repo_root is not None else source.resolve().parents[1]
    base_record = payload.get("base_configuration")
    if not isinstance(base_record, Mapping):
        raise S43Error(f"{source}: base_configuration must be an object")
    relative = base_record.get("path")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise S43Error(f"{source}: unsafe base configuration path")
    base_path = root / relative
    if sha256_file(base_path) != base_record.get("sha256"):
        raise S43Error(f"{source}: base configuration SHA-256 mismatch")
    base = load_json(base_path)
    if base.get("schema") != CONFIG_SCHEMA:
        raise S43Error(f"{source}: base configuration schema mismatch")
    if canonical_sha256(base) != base_record.get("canonical_sha256"):
        raise S43Error(f"{source}: base canonical SHA-256 mismatch")
    correction = payload.get("analysis_frame_correction")
    if not isinstance(correction, Mapping):
        raise S43Error(f"{source}: analysis_frame_correction must be an object")
    additions = payload.get("matrix_additions")
    if not isinstance(additions, list) or not additions:
        raise S43Error(f"{source}: matrix_additions must be a non-empty list")
    effective = deepcopy(base)
    effective["frozen_at_utc"] = payload.get("frozen_at_utc")
    effective["configuration_source"] = {
        "schema": CONFIG_AMENDMENT_SCHEMA,
        "path": source.relative_to(root).as_posix()
        if source.is_absolute()
        else source.as_posix(),
        "id": payload.get("id"),
        "base_configuration": dict(base_record),
    }
    supersedes = payload.get("supersedes")
    if supersedes is not None:
        if not isinstance(supersedes, Mapping):
            raise S43Error(f"{source}: supersedes must be an object")
        effective["configuration_source"]["supersedes"] = deepcopy(supersedes)
    effective["analysis_frame_correction"] = dict(correction)
    effective["matrix"] = [*effective["matrix"], *deepcopy(additions)]
    operational_policy = payload.get("operational_gate_policy")
    if operational_policy is not None:
        if operational_policy != EXPECTED_OPERATIONAL_GATE_POLICY:
            raise S43Error(f"{source}: unexpected operational gate policy")
        effective["operational_gate_policy"] = deepcopy(operational_policy)
    interactive_protocol = payload.get("interactive_stimulus_protocol")
    if interactive_protocol is not None:
        if interactive_protocol != EXPECTED_INTERACTIVE_STIMULUS_PROTOCOL:
            raise S43Error(f"{source}: unexpected interactive stimulus protocol")
        effective["interactive_stimulus_protocol"] = deepcopy(interactive_protocol)
    return effective


def analysis_microphone_positions_project_m(
    configuration: Mapping[str, Any],
) -> np.ndarray:
    """Resolve nominal array coordinates into the declared project frame."""

    positions = np.asarray(
        configuration["audio"]["nominal_microphone_positions_m"], dtype=float
    )
    if positions.shape != (4, 3) or not np.all(np.isfinite(positions)):
        raise S43Error("nominal microphone positions must be finite 4x3 meters")
    correction = configuration.get("analysis_frame_correction")
    if correction is None:
        return positions
    if not isinstance(correction, Mapping):
        raise S43Error("analysis_frame_correction must be an object")
    if (
        correction.get("transform") != "rotation_about_positive_z"
        or correction.get("source_frame") != "F_array_nominal"
        or correction.get("target_frame") != "F_project"
        or correction.get("yaw_deg") != 180.0
    ):
        raise S43Error("only the authorized 180 degree array-frame correction is valid")
    angle = math.radians(float(correction["yaw_deg"]))
    rotation = np.asarray(
        [
            [math.cos(angle), -math.sin(angle), 0.0],
            [math.sin(angle), math.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    transformed = positions @ rotation.T
    transformed[np.abs(transformed) < 1e-15] = 0.0
    return transformed


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, path, message)


def validate_preregistration(
    configuration: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    *,
    repo_root: str | Path,
    verify_implementation_hashes: bool = True,
) -> ValidationReport:
    """Validate the complete frozen contract before hardware or result access."""

    root = Path(repo_root)
    issues: list[ValidationIssue] = []
    if configuration.get("schema") != CONFIG_SCHEMA:
        issues.append(
            _issue("wrong_config_schema", "schema", repr(configuration.get("schema")))
        )
    if preregistration.get("schema") != PREREGISTRATION_SCHEMA:
        issues.append(
            _issue(
                "wrong_preregistration_schema",
                "preregistration.schema",
                repr(preregistration.get("schema")),
            )
        )
    if preregistration.get("status") not in {
        "frozen_before_trial_collection",
        "frozen_before_additional_trial_collection",
    }:
        issues.append(
            _issue(
                "not_frozen",
                "preregistration.status",
                "must be frozen before initial or additional collection",
            )
        )
    amendment_basis = preregistration.get("amendment_basis", "result_trigger")
    if preregistration.get("status") == "frozen_before_trial_collection":
        boundary_fields = (
            "trial_results_viewed_before_freeze",
            "s4_3_recorder_started_before_freeze",
            "s4_4_started",
        )
    elif amendment_basis == "result_trigger":
        boundary_fields = (
            "trial_results_viewed_before_initial_freeze",
            "s4_3_recorder_started_before_initial_freeze",
            "additional_recorder_started_after_trigger_before_amendment_freeze",
            "s4_4_started",
        )
    elif amendment_basis == "operator_authorized_operational":
        boundary_fields = (
            "trial_results_viewed_before_initial_freeze",
            "s4_3_recorder_started_before_initial_freeze",
            "additional_recorder_started_after_authorization_before_amendment_freeze",
            "scientific_contract_changed",
            "s4_4_started",
        )
    elif amendment_basis == "corrective_metric_provenance":
        boundary_fields = (
            "new_trial_data_collected_before_corrective_freeze",
            "new_trial_results_viewed_before_corrective_freeze",
            "detector_tuned_after_new_results",
            "original_frozen_files_modified",
            "s4_4_started",
        )
    else:
        issues.append(
            _issue(
                "invalid_amendment_basis",
                "amendment_basis",
                repr(amendment_basis),
            )
        )
        boundary_fields = ("s4_4_started",)
    for field in boundary_fields:
        if preregistration.get(field) is not False:
            issues.append(_issue("phase_boundary_violation", field, "must be false"))
    if (
        preregistration.get("status") == "frozen_before_additional_trial_collection"
        and amendment_basis == "result_trigger"
        and preregistration.get("trigger_results_declared") is not True
    ):
        issues.append(
            _issue(
                "amendment_trigger_results_undeclared",
                "trigger_results_declared",
                "must be true for a result-triggered amendment",
            )
        )
    if (
        preregistration.get("status") == "frozen_before_additional_trial_collection"
        and amendment_basis == "corrective_metric_provenance"
        and preregistration.get("corrective_authorization_declared") is not True
    ):
        issues.append(
            _issue(
                "corrective_authorization_undeclared",
                "corrective_authorization_declared",
                "must be true for corrective metric provenance",
            )
        )
    if (
        preregistration.get("status") == "frozen_before_additional_trial_collection"
        and amendment_basis == "operator_authorized_operational"
        and preregistration.get("operator_authorization_declared") is not True
    ):
        issues.append(
            _issue(
                "operator_authorization_undeclared",
                "operator_authorization_declared",
                "must be true for an operator-authorized operational amendment",
            )
        )

    if configuration.get("coordinate_frame") != EXPECTED_PROJECT_FRAME:
        issues.append(
            _issue(
                "coordinate_frame_mismatch",
                "coordinate_frame",
                "must match the S4.1/package +Y-right clockwise convention",
            )
        )
    if configuration.get("operator_facing_frame") != EXPECTED_OPERATOR_FACING_FRAME:
        issues.append(
            _issue(
                "operator_facing_frame_mismatch",
                "operator_facing_frame",
                "must match the frozen operator-viewpoint frame and conversion",
            )
        )
    correction = configuration.get("s4_2_coordinate_correction")
    if not isinstance(correction, Mapping):
        issues.append(
            _issue(
                "missing_coordinate_correction",
                "s4_2_coordinate_correction",
                "must bind the operator-confirmed S4.2 Y-sign correction",
            )
        )
    else:
        if correction.get("id") != EXPECTED_S42_COORDINATE_CORRECTION_ID:
            issues.append(
                _issue(
                    "coordinate_correction_id_mismatch",
                    "s4_2_coordinate_correction.id",
                    repr(correction.get("id")),
                )
            )
        correction_relative = correction.get("path")
        correction_sha256 = correction.get("sha256")
        if (
            not isinstance(correction_relative, str)
            or ".." in Path(correction_relative).parts
        ):
            issues.append(
                _issue(
                    "unsafe_coordinate_correction_path",
                    "s4_2_coordinate_correction.path",
                    repr(correction_relative),
                )
            )
        else:
            correction_path = root / correction_relative
            if not correction_path.is_file():
                issues.append(
                    _issue(
                        "missing_coordinate_correction",
                        correction_relative,
                        "file is absent",
                    )
                )
            elif sha256_file(correction_path) != correction_sha256:
                issues.append(
                    _issue(
                        "coordinate_correction_hash_mismatch",
                        correction_relative,
                        "SHA-256 does not match the frozen configuration",
                    )
                )
        superseded_relative = correction.get("superseded_path")
        superseded_sha256 = correction.get("superseded_sha256")
        if (
            not isinstance(superseded_relative, str)
            or ".." in Path(superseded_relative).parts
        ):
            issues.append(
                _issue(
                    "unsafe_superseded_correction_path",
                    "s4_2_coordinate_correction.superseded_path",
                    repr(superseded_relative),
                )
            )
        else:
            superseded_path = root / superseded_relative
            if not superseded_path.is_file():
                issues.append(
                    _issue(
                        "missing_superseded_correction",
                        superseded_relative,
                        "retained contradictory correction is absent",
                    )
                )
            elif sha256_file(superseded_path) != superseded_sha256:
                issues.append(
                    _issue(
                        "superseded_correction_hash_mismatch",
                        superseded_relative,
                        "SHA-256 does not match the retained correction",
                    )
                )

    analysis_correction = configuration.get("analysis_frame_correction")
    if analysis_correction is not None:
        try:
            analysis_microphone_positions_project_m(configuration)
        except (KeyError, S43Error, TypeError, ValueError) as exc:
            issues.append(
                _issue(
                    "invalid_analysis_frame_correction",
                    "analysis_frame_correction",
                    str(exc),
                )
            )
        else:
            if analysis_correction.get("id") != "S4.3-ARRAY-FRAME-AMENDMENT-01":
                issues.append(
                    _issue(
                        "analysis_frame_correction_id_mismatch",
                        "analysis_frame_correction.id",
                        repr(analysis_correction.get("id")),
                    )
                )
            evidence = analysis_correction.get("diagnostic_evidence")
            if not isinstance(evidence, Mapping):
                issues.append(
                    _issue(
                        "missing_analysis_frame_evidence",
                        "analysis_frame_correction.diagnostic_evidence",
                        "must be an object",
                    )
                )
            else:
                evidence_relative = evidence.get("path")
                if (
                    not isinstance(evidence_relative, str)
                    or Path(evidence_relative).is_absolute()
                    or ".." in Path(evidence_relative).parts
                ):
                    issues.append(
                        _issue(
                            "unsafe_analysis_frame_evidence_path",
                            "analysis_frame_correction.diagnostic_evidence.path",
                            repr(evidence_relative),
                        )
                    )
                else:
                    evidence_path = root / evidence_relative
                    if not evidence_path.is_file():
                        issues.append(
                            _issue(
                                "missing_analysis_frame_evidence",
                                evidence_relative,
                                "file is absent",
                            )
                        )
                    elif sha256_file(evidence_path) != evidence.get("sha256"):
                        issues.append(
                            _issue(
                                "analysis_frame_evidence_hash_mismatch",
                                evidence_relative,
                                "SHA-256 differs",
                            )
                        )

    config_record = preregistration.get("configuration", {})
    spec_record = preregistration.get("specification", {})
    for label, record in (
        ("configuration", config_record),
        ("specification", spec_record),
    ):
        if not isinstance(record, Mapping):
            issues.append(_issue("invalid_freeze_record", label, "must be an object"))
            continue
        relative = record.get("path")
        expected = record.get("sha256")
        if not isinstance(relative, str) or ".." in Path(relative).parts:
            issues.append(_issue("unsafe_freeze_path", f"{label}.path", repr(relative)))
            continue
        path = root / relative
        if not path.is_file():
            issues.append(_issue("missing_frozen_file", relative, "file is absent"))
        elif sha256_file(path) != expected:
            issues.append(
                _issue(
                    "frozen_hash_mismatch",
                    relative,
                    "SHA-256 does not match preregistration",
                )
            )
        elif label == "configuration" and load_pilot_configuration(
            path, repo_root=root
        ) != dict(configuration):
            issues.append(
                _issue(
                    "configuration_payload_mismatch",
                    relative,
                    "validated configuration differs from the frozen file",
                )
            )

    implementation_records = preregistration.get("implementation")
    if preregistration.get(
        "status"
    ) == "frozen_before_additional_trial_collection" and (
        not isinstance(implementation_records, list) or not implementation_records
    ):
        issues.append(
            _issue(
                "missing_frozen_implementation",
                "implementation",
                "amendment must hash its analysis and evidence implementation",
            )
        )
    if verify_implementation_hashes and isinstance(implementation_records, list):
        for index, record in enumerate(implementation_records):
            if not isinstance(record, Mapping):
                issues.append(
                    _issue(
                        "invalid_implementation_record",
                        f"implementation[{index}]",
                        "must be an object",
                    )
                )
                continue
            relative = record.get("path")
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                issues.append(
                    _issue(
                        "unsafe_implementation_path",
                        f"implementation[{index}].path",
                        repr(relative),
                    )
                )
                continue
            implementation_path = root / relative
            if not implementation_path.is_file():
                issues.append(
                    _issue(
                        "missing_frozen_implementation",
                        relative,
                        "file is absent",
                    )
                )
            elif sha256_file(implementation_path) != record.get("sha256"):
                issues.append(
                    _issue(
                        "implementation_hash_mismatch",
                        relative,
                        "SHA-256 differs",
                    )
                )

    matrix = configuration.get("matrix")
    if not isinstance(matrix, list):
        issues.append(_issue("invalid_matrix", "matrix", "must be a list"))
        matrix = []
    matrix_record = preregistration.get("matrix", {})
    if not isinstance(matrix_record, Mapping) or canonical_sha256(
        matrix
    ) != matrix_record.get("canonical_json_sha256"):
        issues.append(
            _issue("matrix_hash_mismatch", "matrix", "canonical matrix hash differs")
        )
    if matrix_record.get("planned_trial_count") != len(matrix):
        issues.append(
            _issue("matrix_count_mismatch", "matrix", "planned count differs")
        )

    ids: set[str] = set()
    categories: Counter[str] = Counter()
    base_categories: Counter[str] = Counter()
    expansion_by_parent: Counter[str] = Counter()
    for index, trial in enumerate(matrix):
        path = f"matrix[{index}]"
        if not isinstance(trial, Mapping):
            issues.append(_issue("invalid_trial", path, "must be an object"))
            continue
        trial_id = trial.get("trial_id")
        if not isinstance(trial_id, str) or not trial_id.startswith("s4_3_"):
            issues.append(
                _issue("invalid_trial_id", f"{path}.trial_id", repr(trial_id))
            )
        elif trial_id in ids:
            issues.append(_issue("duplicate_trial_id", f"{path}.trial_id", trial_id))
        else:
            ids.add(trial_id)
        category = trial.get("category")
        if category not in EXPECTED_CATEGORIES:
            issues.append(
                _issue("invalid_category", f"{path}.category", repr(category))
            )
        else:
            categories[str(category)] += 1
        expansion_record = trial.get("expansion")
        if expansion_record is None:
            if category in EXPECTED_CATEGORIES:
                base_categories[str(category)] += 1
        elif not isinstance(expansion_record, Mapping):
            issues.append(
                _issue(
                    "invalid_expansion_record", f"{path}.expansion", "must be object"
                )
            )
        else:
            parent = expansion_record.get("parent_trial_id")
            trigger = expansion_record.get("trigger")
            if parent not in ids or parent == trial_id:
                issues.append(
                    _issue(
                        "invalid_expansion_parent",
                        f"{path}.expansion.parent_trial_id",
                        repr(parent),
                    )
                )
            else:
                expansion_by_parent[str(parent)] += 1
            if trigger not in configuration.get("expansion", {}).get("triggers", []):
                issues.append(
                    _issue(
                        "invalid_expansion_trigger",
                        f"{path}.expansion.trigger",
                        repr(trigger),
                    )
                )
        duration = trial.get("duration_s")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 10 <= duration <= 60
        ):
            issues.append(
                _issue("invalid_duration", f"{path}.duration_s", repr(duration))
            )
        reference_trial = "mac_reference" in str(trial.get("stimulus"))
        frozen_volume = configuration.get("hardware", {}).get("mac_volume_percent")
        if reference_trial and trial.get("mac_volume_percent") != frozen_volume:
            issues.append(
                _issue(
                    "reference_volume_mismatch",
                    path,
                    "reference volume is not frozen",
                )
            )
        if trial.get("source_frame") != "F_project":
            issues.append(
                _issue(
                    "analysis_frame_mismatch",
                    f"{path}.source_frame",
                    "machine-readable analysis must use F_project",
                )
            )
        if trial.get("operator_source_frame") != "F_operator_facing_zed":
            issues.append(
                _issue(
                    "operator_frame_mismatch",
                    f"{path}.operator_source_frame",
                    "physical placement must use F_operator_facing_zed first",
                )
            )
        operator_action = trial.get("operator_action")
        if not isinstance(operator_action, str) or not operator_action.startswith(
            "from_your_view_"
        ):
            issues.append(
                _issue(
                    "operator_instruction_order_mismatch",
                    f"{path}.operator_action",
                    "must lead with the operator viewpoint",
                )
            )
        project_position = trial.get("source_position_m")
        operator_position = trial.get("operator_source_position_m")
        if (project_position is None) != (operator_position is None):
            issues.append(
                _issue(
                    "dual_frame_position_missing",
                    path,
                    "operator and project positions must both be present or null",
                )
            )
        elif project_position is not None:
            try:
                converted_position = operator_facing_zed_position_to_project(
                    operator_position
                )
            except (TypeError, ValueError):
                issues.append(
                    _issue(
                        "invalid_operator_position",
                        f"{path}.operator_source_position_m",
                        "must contain three finite meters",
                    )
                )
            else:
                if not isinstance(project_position, list) or len(project_position) != 3:
                    issues.append(
                        _issue(
                            "invalid_project_position",
                            f"{path}.source_position_m",
                            "must contain three finite meters",
                        )
                    )
                elif any(
                    not math.isclose(actual, float(expected), abs_tol=1e-12)
                    for actual, expected in zip(
                        converted_position, project_position, strict=True
                    )
                ):
                    issues.append(
                        _issue(
                            "dual_frame_position_mismatch",
                            path,
                            "operator position does not convert to F_project",
                        )
                    )
        project_bearing = trial.get("source_bearing_deg")
        operator_bearing = trial.get("operator_source_bearing_deg")
        if (project_bearing is None) != (operator_bearing is None):
            issues.append(
                _issue(
                    "dual_frame_bearing_missing",
                    path,
                    "operator and project bearings must both be present or null",
                )
            )
        elif project_bearing is not None:
            try:
                converted_bearing = operator_facing_zed_bearing_to_project(
                    operator_bearing
                )
            except ValueError:
                issues.append(
                    _issue(
                        "invalid_operator_bearing",
                        f"{path}.operator_source_bearing_deg",
                        "must be one finite angle",
                    )
                )
            else:
                if not isinstance(project_bearing, (int, float)) or not math.isclose(
                    converted_bearing, float(project_bearing) % 360.0, abs_tol=1e-12
                ):
                    issues.append(
                        _issue(
                            "dual_frame_bearing_mismatch",
                            path,
                            "operator bearing does not convert to F_project",
                        )
                    )
        if category == "repeatability" and (
            trial.get("operator_source_position_m") != [0.0, -0.9, -0.135]
            or trial.get("operator_source_bearing_deg") != 270.0
            or trial.get("source_position_m") != [0.0, 0.9, -0.135]
            or trial.get("source_bearing_deg") != 90.0
        ):
            issues.append(
                _issue(
                    "baseline_coordinate_mismatch",
                    path,
                    "baseline must be operator-left Y=-0.90 m/270 deg and "
                    "canonical project-right Y=+0.90 m/90 deg",
                )
            )

    if dict(sorted(categories.items())) != dict(
        sorted(preregistration.get("matrix", {}).get("category_counts", {}).items())
    ):
        issues.append(
            _issue("category_count_mismatch", "matrix", repr(dict(categories)))
        )
    if base_categories.get("repeatability") != configuration.get(
        "repeatability_acceptance", {}
    ).get("required_baseline_trials"):
        issues.append(
            _issue(
                "repeatability_count_mismatch",
                "matrix",
                "baseline repetition count differs",
            )
        )
    expansion_count = sum(expansion_by_parent.values())
    expansion_contract = configuration.get("expansion", {})
    corrective_allowance = (
        1
        if configuration.get("configuration_source", {}).get("schema")
        == CORRECTIVE_CONFIG_SCHEMA
        else 0
    )
    if expansion_count > (
        expansion_contract.get("maximum_added_trials_total", -1) + corrective_allowance
    ):
        issues.append(
            _issue("expansion_total_exceeded", "matrix", str(expansion_count))
        )
    if any(
        count
        > expansion_contract.get("maximum_confirmation_trials_per_triggered_cell", -1)
        for count in expansion_by_parent.values()
    ):
        issues.append(
            _issue(
                "expansion_per_cell_exceeded",
                "matrix",
                repr(dict(expansion_by_parent)),
            )
        )
    if configuration.get("phase_boundary", {}).get("s4_4_started") is not False:
        issues.append(
            _issue("s4_4_started", "phase_boundary.s4_4_started", "must remain false")
        )
    if len(configuration.get("metric_contracts", {})) < 20:
        issues.append(
            _issue(
                "metric_coverage_missing",
                "metric_contracts",
                "required S4.3 metric contracts are incomplete",
            )
        )

    return ValidationReport(
        (
            {
                "id": "s4_3_preregistration",
                "status": "passed" if not issues else "failed",
                "planned_trial_count": len(matrix),
                "category_counts": dict(sorted(categories.items())),
            },
        ),
        tuple(issues),
    )


def validate_corrective_provenance(
    configuration: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> ValidationReport:
    """Validate the clipping correction and prospective noise contract chain."""

    root = Path(repo_root)
    issues: list[ValidationIssue] = []
    source = configuration.get("configuration_source")
    if (
        not isinstance(source, Mapping)
        or source.get("schema") != CORRECTIVE_CONFIG_SCHEMA
    ):
        issues.append(
            _issue(
                "corrective_configuration_absent",
                "configuration_source",
                "corrected effective configuration is required",
            )
        )
        return ValidationReport((), tuple(issues))
    provenance = configuration.get("corrective_provenance")
    if not isinstance(provenance, Mapping):
        issues.append(
            _issue(
                "corrective_provenance_absent",
                "corrective_provenance",
                "must be an object",
            )
        )
        return ValidationReport((), tuple(issues))
    for label in (
        "original_frozen_configuration",
        "original_preregistration",
        "clipping_corrective",
        "prospective_transient_event_contract",
    ):
        record = provenance.get(label)
        if not isinstance(record, Mapping):
            issues.append(_issue("corrective_binding_absent", label, "must be object"))
            continue
        relative = record.get("path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            issues.append(_issue("unsafe_corrective_binding", label, repr(relative)))
            continue
        path = root / relative
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            issues.append(
                _issue(
                    "corrective_binding_hash_mismatch",
                    relative,
                    "file absent or SHA-256 differs",
                )
            )
    original = provenance.get("original_frozen_configuration")
    if isinstance(original, Mapping):
        path = root / str(original.get("path"))
        if (
            path.is_file()
            and load_json(path)
            .get("quality", {})
            .get("maximum_sustained_clip_run_samples")
            != 8
        ):
            issues.append(
                _issue(
                    "original_clipping_value_changed",
                    str(original.get("path")),
                    "original frozen value must remain 8",
                )
            )
    if (
        configuration.get("quality", {}).get("maximum_sustained_clip_run_samples")
        != 4_000
    ):
        issues.append(
            _issue(
                "effective_clipping_threshold_mismatch",
                "quality.maximum_sustained_clip_run_samples",
                "must be 4000",
            )
        )
    detector = configuration.get("noise_event_detector")
    if not isinstance(detector, Mapping):
        issues.append(
            _issue(
                "transient_detector_provenance_absent",
                "noise_event_detector",
                "must be prospectively frozen",
            )
        )
    prereg_config = preregistration.get("configuration")
    source_path = source.get("path")
    if (
        not isinstance(prereg_config, Mapping)
        or prereg_config.get("path") != source_path
        or canonical_sha256(configuration)
        != prereg_config.get("effective_canonical_sha256")
    ):
        issues.append(
            _issue(
                "corrective_preregistration_configuration_mismatch",
                "preregistration.configuration",
                "must bind the corrected effective configuration",
            )
        )
    corrective_records = preregistration.get("corrective_records")
    required_corrective_paths = {
        "docs/development/specs/s4_3_pilot_corrective_01.md",
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/clipping_corrective_01.json",
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/transient_event_contract_01.json",
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "trial_inventory_corrective_01_precollection.json",
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/corrective_01_supersession.json",
        "outputs/isaac_audio_sensors/S4/S4.3/diagnostics/"
        "corrective_01_precollection_gate.json",
    }
    observed_corrective_paths: set[str] = set()
    if not isinstance(corrective_records, list):
        issues.append(
            _issue(
                "corrective_record_inventory_absent",
                "preregistration.corrective_records",
                "must be a list",
            )
        )
    else:
        for index, record in enumerate(corrective_records):
            if not isinstance(record, Mapping):
                issues.append(
                    _issue(
                        "invalid_corrective_record",
                        f"preregistration.corrective_records[{index}]",
                        "must be an object",
                    )
                )
                continue
            relative = record.get("path")
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or relative in observed_corrective_paths
            ):
                issues.append(
                    _issue(
                        "unsafe_corrective_record",
                        f"preregistration.corrective_records[{index}]",
                        repr(relative),
                    )
                )
                continue
            observed_corrective_paths.add(relative)
            path = root / relative
            if not path.is_file() or sha256_file(path) != record.get("sha256"):
                issues.append(
                    _issue(
                        "corrective_record_hash_mismatch",
                        relative,
                        "file absent or SHA-256 differs",
                    )
                )
    if not required_corrective_paths <= observed_corrective_paths:
        issues.append(
            _issue(
                "corrective_record_coverage_missing",
                "preregistration.corrective_records",
                repr(sorted(required_corrective_paths - observed_corrective_paths)),
            )
        )
    return ValidationReport(
        (
            {
                "id": "s4_3_corrective_provenance",
                "status": "passed" if not issues else "failed",
                "effective_sustained_clip_run_samples": configuration.get(
                    "quality", {}
                ).get("maximum_sustained_clip_run_samples"),
                "prospective_evidence_trial_id": provenance.get(
                    "prospective_transient_event_contract", {}
                ).get("prospective_evidence_trial_id"),
            },
        ),
        tuple(issues),
    )


def validate_review_remediation_manifest(
    configuration: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    repo_root: str | Path,
    verify_implementation_hashes: bool = True,
) -> ValidationReport:
    """Bind post-trial validator changes without rewriting the frozen contract."""

    root = Path(repo_root)
    issues: list[ValidationIssue] = []
    if manifest.get("schema") != REVIEW_REMEDIATION_SCHEMA:
        issues.append(
            _issue(
                "wrong_review_remediation_schema",
                "schema",
                repr(manifest.get("schema")),
            )
        )
    for field in (
        "scientific_thresholds_changed",
        "matrix_changed",
        "raw_evidence_modified",
        "trials_recollected",
        "s4_4_started",
    ):
        if manifest.get(field) is not False:
            issues.append(_issue("review_scope_violation", field, "must be false"))
    for label, expected_payload in (
        ("configuration", configuration),
        ("preregistration", preregistration),
    ):
        record = manifest.get(label)
        if not isinstance(record, Mapping):
            issues.append(_issue("missing_review_binding", label, "must be object"))
            continue
        relative = record.get("path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            issues.append(_issue("unsafe_review_binding", label, repr(relative)))
            continue
        path = root / relative
        if not path.is_file():
            issues.append(_issue("missing_review_binding", relative, "file absent"))
            continue
        if sha256_file(path) != record.get("sha256"):
            issues.append(
                _issue("review_binding_hash_mismatch", relative, "SHA-256 differs")
            )
        if label == "configuration":
            if canonical_sha256(expected_payload) != record.get(
                "effective_canonical_sha256"
            ):
                issues.append(
                    _issue(
                        "review_effective_configuration_mismatch",
                        relative,
                        "effective canonical SHA-256 differs",
                    )
                )
        elif load_json(path) != dict(expected_payload):
            issues.append(
                _issue(
                    "review_preregistration_payload_mismatch",
                    relative,
                    "payload differs from active frozen preregistration",
                )
            )
    matrix = configuration.get("matrix", [])
    if canonical_sha256(matrix) != manifest.get("matrix_canonical_sha256"):
        issues.append(
            _issue("review_matrix_hash_mismatch", "matrix", "SHA-256 differs")
        )
    threshold_payload = {
        key: configuration.get(key)
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
    if canonical_sha256(threshold_payload) != manifest.get(
        "scientific_contract_canonical_sha256"
    ):
        issues.append(
            _issue(
                "review_scientific_contract_hash_mismatch",
                "scientific_contract_canonical_sha256",
                "SHA-256 differs",
            )
        )
    implementation = manifest.get("implementation")
    required_paths = {
        "src/isaac_audio_sensors/acquisition/s4_3.py",
        "scripts/build_s4_3_evidence.py",
        "scripts/validate_s4_3_integrity.py",
        "tests/test_s4_3_pilot.py",
    }
    observed_paths: set[str] = set()
    if not isinstance(implementation, list) or not implementation:
        issues.append(
            _issue("missing_review_implementation", "implementation", "must be list")
        )
    else:
        for index, record in enumerate(implementation):
            if not isinstance(record, Mapping):
                issues.append(
                    _issue(
                        "invalid_review_implementation",
                        f"implementation[{index}]",
                        "must be object",
                    )
                )
                continue
            relative = record.get("path")
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or relative in observed_paths
            ):
                issues.append(
                    _issue(
                        "unsafe_review_implementation",
                        f"implementation[{index}]",
                        repr(relative),
                    )
                )
                continue
            observed_paths.add(relative)
            path = root / relative
            if not path.is_file():
                issues.append(
                    _issue("missing_review_implementation", relative, "file absent")
                )
            elif verify_implementation_hashes and sha256_file(path) != record.get(
                "sha256"
            ):
                issues.append(
                    _issue(
                        "review_implementation_hash_mismatch",
                        relative,
                        "SHA-256 differs",
                    )
                )
    if not required_paths <= observed_paths:
        issues.append(
            _issue(
                "review_implementation_coverage_missing",
                "implementation",
                repr(sorted(required_paths - observed_paths)),
            )
        )
    return ValidationReport(
        (
            {
                "id": "s4_3_review_remediation",
                "status": "passed" if not issues else "failed",
                "matrix_canonical_sha256": canonical_sha256(matrix),
                "scientific_contract_canonical_sha256": canonical_sha256(
                    threshold_payload
                ),
                "implementation_record_count": len(implementation)
                if isinstance(implementation, list)
                else 0,
            },
        ),
        tuple(issues),
    )


def planned_inventory(configuration: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete pre-result inventory without fabricating attempts."""

    trials = []
    for definition in configuration["matrix"]:
        trials.append(
            {
                "trial_id": definition["trial_id"],
                "category": definition["category"],
                "planned_definition_sha256": canonical_sha256(definition),
                "planned_outcome": "planned",
                "attempts": [],
            }
        )
    return {
        "schema": INVENTORY_SCHEMA,
        "status": "pre_collection",
        "configuration_sha256": canonical_sha256(configuration),
        "planned_trial_count": len(trials),
        "trials": trials,
        "outcome_counts": {outcome: 0 for outcome in sorted(EXPECTED_OUTCOMES)},
        "s4_4_started": False,
    }


def _read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as reader:
            if (
                reader.getnchannels() != 6
                or reader.getframerate() != 16_000
                or reader.getsampwidth() != 2
                or reader.getcomptype() != "NONE"
            ):
                raise S43Error(f"{path}: expected six-channel 16 kHz PCM16")
            raw = reader.readframes(reader.getnframes())
    except (EOFError, OSError, wave.Error) as exc:
        raise S43Error(f"{path}: invalid WAV: {exc}") from exc
    values = np.frombuffer(raw, dtype="<i2")
    if values.size % 6:
        raise S43Error(f"{path}: payload ends inside an interleaved frame")
    return values.reshape(-1, 6).astype(np.float64) / 32768.0, 16_000


def _reference_start_sample(report: ValidationReport, minimum: float) -> int | None:
    if not report.checks:
        return None
    results = report.checks[0].get("channel_results", [])
    starts = [
        int(item["reference_start_sample_index"])
        for item in results[2:]
        if item.get("peak_normalized_correlation", 0.0) >= minimum
        and int(item.get("reference_start_sample_index", -1)) >= 0
    ]
    return None if not starts else round(float(median(starts)))


def _window_bounds(
    samples: np.ndarray,
    trial: Mapping[str, Any],
    configuration: Mapping[str, Any],
    reference_start: int | None,
) -> list[tuple[int, int]]:
    rate = int(configuration["audio"]["sample_rate_hz"])
    size = round(configuration["analysis"]["window_duration_ms"] * rate / 1000)
    hop = round(
        size * (1.0 - configuration["analysis"]["window_overlap_percent"] / 100.0)
    )
    stimulus = str(trial["stimulus"])
    if "mac_reference" in stimulus and reference_start is not None:
        start = reference_start + round(2.25 * rate)
        stop = reference_start + round(7.25 * rate)
    elif stimulus == "silence":
        start, stop = rate, max(rate, samples.shape[0] - rate)
    elif stimulus == "visible_audible_ordinary_object_impact":
        raw = samples[:, 2:6]
        energy = np.max(np.abs(raw), axis=1)
        peak = int(np.argmax(energy))
        start, stop = max(0, peak - rate), min(samples.shape[0], peak + rate)
    else:
        start, stop = rate, max(rate, samples.shape[0] - rate)
    stop = min(stop, samples.shape[0])
    if stop - start < size:
        return []
    return [(offset, offset + size) for offset in range(start, stop - size + 1, hop)]


def _array_sensor(configuration: Mapping[str, Any]) -> MicrophoneArraySpec:
    ids = configuration["audio"]["analysis_channel_ids"]
    positions = analysis_microphone_positions_project_m(configuration)
    microphones = tuple(
        MicrophoneSpec(mic_id=str(mic_id), relative_position_m=tuple(position))
        for mic_id, position in zip(ids, positions.tolist(), strict=True)
    )
    return MicrophoneArraySpec(
        array_id="s4_3_respeaker_nominal",
        prim_path="/S4_3/ReSpeaker",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=int(configuration["audio"]["sample_rate_hz"]),
    )


def _angular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _relative_band_db(
    values: np.ndarray, rate: int, bands: Sequence[Sequence[int]]
) -> dict[str, float]:
    windowed = values * np.hanning(values.size)
    power = np.abs(np.fft.rfft(windowed)) ** 2
    frequencies = np.fft.rfftfreq(values.size, 1.0 / rate)
    energies: list[float] = []
    for low, high in bands:
        mask = (frequencies >= low) & (frequencies < high)
        energies.append(float(np.sum(power[mask])))
    total = max(sum(energies), 1e-30)
    return {
        f"{int(low)}-{int(high)}": 10.0 * math.log10(max(energy / total, 1e-30))
        for (low, high), energy in zip(bands, energies, strict=True)
    }


def _aligned_correlation(
    left: np.ndarray, right: np.ndarray, delay_s: float, rate: int
) -> float:
    shift = int(round(delay_s * rate))
    if shift > 0:
        left, right = left[shift:], right[:-shift]
    elif shift < 0:
        left, right = left[:shift], right[-shift:]
    if left.size < 2 or float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _expected_tdoa(
    positions: np.ndarray, ids: Sequence[str], bearing_deg: float, speed: float
) -> dict[str, float]:
    angle = math.radians(bearing_deg)
    direction = np.asarray([math.cos(angle), math.sin(angle), 0.0])
    return {
        f"{left}->{right}": float(
            -(positions[left_index] - positions[right_index]) @ direction / speed
        )
        for left_index, left in enumerate(ids)
        for right_index, right in enumerate(ids)
    }


def _relative_decay(
    samples: np.ndarray,
    trial: Mapping[str, Any],
    configuration: Mapping[str, Any],
    reference_start: int | None,
) -> dict[str, Any]:
    """Measure coarse combined decay on the frozen analysis window/hop grid."""

    rate = int(configuration["audio"]["sample_rate_hz"])
    size = round(configuration["analysis"]["window_duration_ms"] * rate / 1000)
    hop = round(
        size * (1.0 - configuration["analysis"]["window_overlap_percent"] / 100.0)
    )
    combined = np.mean(samples[:, 2:6], axis=1)
    stimulus = str(trial["stimulus"])
    if "mac_reference" in stimulus and reference_start is not None:
        search_start = reference_start + round(0.95 * rate)
        search_stop = min(combined.size, reference_start + round(1.30 * rate))
        event_kind = "first_reference_chirp"
    elif stimulus == "visible_audible_ordinary_object_impact":
        search_start, search_stop = 0, combined.size
        event_kind = "ordinary_object_impact"
    else:
        return {
            "status": "not_applicable",
            "reason": "no preregistered chirp or impact event",
        }
    if search_stop <= search_start:
        return {"status": "unmeasured", "reason": "event search interval absent"}
    peak_sample = search_start + int(
        np.argmax(np.abs(combined[search_start:search_stop]))
    )
    energies = []
    offsets = []
    for start in range(
        peak_sample, min(combined.size - size + 1, peak_sample + rate), hop
    ):
        window = combined[start : start + size]
        energies.append(float(np.mean(window * window)))
        offsets.append(start - peak_sample)
    if not energies or max(energies) <= 0.0:
        return {"status": "unmeasured", "reason": "event has no finite energy"}
    peak_energy = max(energies)
    relative_db = [
        10.0 * math.log10(max(value / peak_energy, 1e-30)) for value in energies
    ]

    def crossing(threshold_db: float) -> float | None:
        for offset, value in zip(offsets, relative_db, strict=True):
            if value <= threshold_db:
                return 1000.0 * offset / rate
        return None

    minus_10 = crossing(-10.0)
    minus_20 = crossing(-20.0)
    return {
        "status": "measured" if minus_10 is not None else "censored",
        "event_kind": event_kind,
        "event_peak_sample": peak_sample,
        "window_duration_ms": configuration["analysis"]["window_duration_ms"],
        "hop_ms": 1000.0 * hop / rate,
        "decay_to_minus_10_db_ms": minus_10,
        "decay_to_minus_20_db_ms": minus_20,
        "censored_at_ms": 1000.0 * offsets[-1] / rate,
        "relative_energy_db": relative_db,
        "classification": "Measured",
        "limitation": "combined source-room-fixture-sensor decay; not RT60",
    }


def analyze_trial_wav(
    wav_path: str | Path,
    trial: Mapping[str, Any],
    configuration: Mapping[str, Any],
    *,
    reference_path: str | Path | None = None,
) -> dict[str, Any]:
    """Analyze one immutable real or fixture WAV under the frozen S4.3 policy."""

    path = Path(wav_path)
    intended_silence = trial["stimulus"] == "silence"
    properties, audio_issues = inspect_six_channel_wav(
        path,
        require_nonsilent_channels=not intended_silence,
        reject_sustained_clipping=True,
        sustained_clip_run_samples_min=int(
            configuration["quality"]["maximum_sustained_clip_run_samples"]
        ),
        expected_duration_s=float(trial["duration_s"]),
        duration_tolerance_s=float(configuration["quality"]["duration_tolerance_s"]),
    )
    issues = list(audio_issues)
    reference_report: ValidationReport | None = None
    reference_start: int | None = None
    if "mac_reference" in str(trial["stimulus"]):
        if reference_path is None:
            issues.append(
                _issue("missing_reference", str(path), "reference path is required")
            )
        else:
            reference_report = validate_reference_capture(
                path,
                reference_path,
                minimum_normalized_correlation=float(
                    configuration["reference"]["minimum_normalized_correlation"]
                ),
                minimum_correlated_raw_channels=int(
                    configuration["reference"]["minimum_correlated_raw_channels"]
                ),
            )
            issues.extend(reference_report.issues)
            reference_start = _reference_start_sample(
                reference_report,
                float(configuration["reference"]["minimum_normalized_correlation"]),
            )
    if issues:
        return {
            "schema": ANALYSIS_SCHEMA,
            "status": "failed",
            "trial_id": trial["trial_id"],
            "trial_definition_sha256": canonical_sha256(trial),
            "wav": properties,
            "reference_validation": None
            if reference_report is None
            else reference_report.to_dict(),
            "issues": [item.to_dict() for item in issues],
            "windows": [],
        }

    samples, rate = _read_pcm16(path)
    bounds = _window_bounds(samples, trial, configuration, reference_start)
    if not bounds:
        raise S43Error(f"{path}: no eligible analysis windows")
    raw_ids = tuple(
        str(value) for value in configuration["audio"]["analysis_channel_ids"]
    )
    positions = analysis_microphone_positions_project_m(configuration)
    position_map = {
        mic_id: tuple(positions[index]) for index, mic_id in enumerate(raw_ids)
    }
    sensor = _array_sensor(configuration)
    speed = float(configuration["analysis"]["nominal_speed_of_sound_mps"])
    aperture = max(
        float(np.linalg.norm(positions[left] - positions[right]))
        for left in range(4)
        for right in range(left + 1, 4)
    )
    max_delay = aperture / speed + 1.0 / rate
    bearing_reference = trial.get("source_bearing_deg")
    expected = (
        None
        if bearing_reference is None
        else _expected_tdoa(positions, raw_ids, float(bearing_reference), speed)
    )
    windows: list[dict[str, Any]] = []
    for index, (start, stop) in enumerate(bounds):
        started = time.perf_counter_ns()
        raw = samples[start:stop, 2:6].T
        per_rms = np.sqrt(np.mean(raw * raw, axis=1))
        median_rms = float(np.median(per_rms))
        signal_by_level = median_rms > float(
            configuration["analysis"]["signal_rms_full_scale_threshold"]
        )
        frame: dict[str, Any] = {
            "frame_index": index,
            "start_sample": start,
            "stop_sample": stop,
            "start_elapsed_s": start / rate,
            "stop_elapsed_s": stop / rate,
            "per_channel_rms_full_scale": {
                mic_id: float(per_rms[channel])
                for channel, mic_id in enumerate(raw_ids)
            },
            "median_raw_rms_full_scale": median_rms,
        }
        relative_rms = 20.0 * np.log10(
            np.maximum(per_rms / max(median_rms, 1e-30), 1e-30)
        )
        frame["per_channel_relative_rms_db"] = {
            mic_id: float(relative_rms[channel])
            for channel, mic_id in enumerate(raw_ids)
        }
        combined = np.mean(raw, axis=0)
        frame["combined_spectrum_relative_db"] = _relative_band_db(
            combined, rate, configuration["analysis"]["spectral_bands_hz"]
        )
        if signal_by_level:
            waveforms = {mic_id: raw[channel] for channel, mic_id in enumerate(raw_ids)}
            srp = srp_phat_direction(
                waveforms,
                mic_positions_m=position_map,
                sample_rate_hz=rate,
                speed_of_sound_mps=speed,
                azimuth_step_deg=float(configuration["analysis"]["azimuth_step_deg"]),
                max_delay_s=max_delay,
                interp=int(configuration["analysis"]["gcc_interp"]),
            )
            confidence = srp_phat_confidence(srp)
            tdoa, peaks = estimate_tdoa_diagnostics(
                waveforms,
                sample_rate_hz=rate,
                max_delay_s=max_delay,
                interp=int(configuration["analysis"]["gcc_interp"]),
            )
            delays = relative_delays_from_tdoa_matrix(tdoa, mic_ids=raw_ids)
            least_squares = estimate_doa_from_delays(
                sensor=sensor,
                per_mic_delay_s=delays,
                speed_of_sound_mps=speed,
                ambiguity_policy="none",
            )
            detected = confidence >= float(
                configuration["analysis"]["minimum_detection_confidence"]
            )
            bearing = float(srp.bearing_deg)
            candidates = [bearing]
            pair_polarity: dict[str, float] = {}
            for left_index, left in enumerate(raw_ids):
                for right_index, right in enumerate(raw_ids):
                    if right_index <= left_index:
                        continue
                    pair_polarity[f"{left}->{right}"] = _aligned_correlation(
                        raw[left_index],
                        raw[right_index],
                        float(tdoa[f"{left}->{right}"]),
                        rate,
                    )
            frame.update(
                {
                    "signal_present": detected,
                    "abstained": not detected,
                    "srp_bearing_deg": bearing,
                    "candidate_bearing_deg": candidates,
                    "bearing_sector": bearing_deg_to_sector_name(bearing),
                    "bearing_confidence": float(confidence),
                    "ambiguity_class": (
                        "low_confidence"
                        if confidence
                        < float(
                            configuration["analysis"][
                                "low_confidence_ambiguity_threshold"
                            ]
                        )
                        else "single_dominant_candidate"
                    ),
                    "least_squares_bearing_deg": least_squares.estimated_bearing_deg,
                    "least_squares_candidates_deg": list(
                        least_squares.candidate_bearing_deg
                    ),
                    "tdoa_s": {key: float(value) for key, value in tdoa.items()},
                    "gcc_phat_peak": {
                        key: float(value) for key, value in peaks.items()
                    },
                    "relative_channel_delay_s": {
                        key: float(value) for key, value in delays.items()
                    },
                    "aligned_pair_correlation": pair_polarity,
                    "major_polarity_anomaly": any(
                        value < -0.25 for value in pair_polarity.values()
                    ),
                }
            )
            if bearing_reference is not None:
                frame["absolute_bearing_error_deg"] = _angular_error(
                    bearing, float(bearing_reference)
                )
                frame["candidate_covered"] = any(
                    _angular_error(candidate, float(bearing_reference))
                    <= float(
                        configuration["analysis"]["candidate_coverage_tolerance_deg"]
                    )
                    for candidate in candidates
                )
                expected_sector = bearing_deg_to_sector_name(float(bearing_reference))
                frame["expected_sector"] = expected_sector
                frame["sector_correct"] = frame["bearing_sector"] == expected_sector
                frame["expected_tdoa_s"] = expected
                frame["tdoa_error_s"] = {
                    key: float(tdoa[key] - expected[key]) for key in expected
                }
        else:
            frame.update(
                {
                    "signal_present": False,
                    "abstained": True,
                    "srp_bearing_deg": None,
                    "candidate_bearing_deg": [],
                    "bearing_sector": None,
                    "bearing_confidence": 0.0,
                    "ambiguity_class": "abstained_low_level",
                    "least_squares_bearing_deg": None,
                    "least_squares_candidates_deg": [],
                    "tdoa_s": {},
                    "gcc_phat_peak": {},
                    "relative_channel_delay_s": {},
                    "aligned_pair_correlation": {},
                    "major_polarity_anomaly": False,
                }
            )
            if bearing_reference is not None:
                frame.update(
                    {
                        "absolute_bearing_error_deg": None,
                        "candidate_covered": False,
                        "expected_sector": bearing_deg_to_sector_name(
                            float(bearing_reference)
                        ),
                        "sector_correct": False,
                        "expected_tdoa_s": expected,
                        "tdoa_error_s": {},
                    }
                )
        analysis_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        adapter_payload = json.dumps(frame, sort_keys=True, separators=(",", ":"))
        adapter_started = time.perf_counter_ns()
        restored = json.loads(adapter_payload)
        adapter_ms = (time.perf_counter_ns() - adapter_started) / 1_000_000.0
        if restored["frame_index"] != index:
            raise S43Error("analysis frame adapter round-trip changed frame index")
        frame["analysis_runtime_ms"] = analysis_ms
        frame["capture_to_frame_offline_ms"] = (
            float(configuration["analysis"]["window_duration_ms"]) + analysis_ms
        )
        frame["frame_to_adapter_round_trip_ms"] = adapter_ms
        windows.append(frame)

    scientific = [
        {key: value for key, value in frame.items() if not key.endswith("_ms")}
        for frame in windows
    ]
    relative_decay = _relative_decay(
        samples,
        trial,
        configuration,
        reference_start,
    )
    report = {
        "schema": ANALYSIS_SCHEMA,
        "status": "passed",
        "trial_id": trial["trial_id"],
        "category": trial["category"],
        "stimulus": trial["stimulus"],
        "trial_definition_sha256": canonical_sha256(trial),
        "configuration_sha256": canonical_sha256(configuration),
        "wav": properties,
        "reference_validation": None
        if reference_report is None
        else reference_report.to_dict(),
        "reference_start_sample": reference_start,
        "window_count": len(windows),
        "windows": windows,
        "scientific_replay_sha256": canonical_sha256(
            {"windows": scientific, "relative_decay": relative_decay}
        ),
        "relative_decay": relative_decay,
        "issues": [],
        "classifications": {
            "device_and_format": "Verified",
            "waveform_metrics": "Measured",
            "microphone_geometry": "Nominal",
            "array_to_project_alignment": (
                "Measured functional correction"
                if configuration.get("analysis_frame_correction") is not None
                else "Approximate"
            ),
            "source_pose": "Approximate"
            if bearing_reference is not None
            else "Unmeasured",
            "absolute_spl": "Unsupported",
            "live_end_to_end_latency": "Unsupported",
        },
        "analysis_frame_correction": configuration.get("analysis_frame_correction"),
    }
    report["summary"] = summarize_windows(
        windows,
        bearing_reference_deg=(
            None if bearing_reference is None else float(bearing_reference)
        ),
    )
    return report


def _nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _stats(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0, "median": None, "mad": None, "p95": None, "worst": None}
    center = float(median(clean))
    return {
        "count": len(clean),
        "median": center,
        "mad": float(median(abs(value - center) for value in clean)),
        "p95": _nearest_rank(clean, 0.95),
        "worst": max(clean),
    }


def summarize_windows(
    windows: Sequence[Mapping[str, Any]], *, bearing_reference_deg: float | None = None
) -> dict[str, Any]:
    """Aggregate one trial without hiding abstentions or missing values."""

    detected = [frame for frame in windows if not bool(frame.get("abstained"))]
    bearing_errors = [
        float(frame["absolute_bearing_error_deg"])
        for frame in detected
        if frame.get("absolute_bearing_error_deg") is not None
    ]
    referenced = [frame for frame in windows if "candidate_covered" in frame]
    candidate_counts = [
        float(len(frame.get("candidate_bearing_deg", [])))
        for frame in detected
        if "candidate_covered" in frame
    ]
    nearest_candidate_errors = []
    if bearing_reference_deg is not None:
        nearest_candidate_errors = [
            min(
                _angular_error(float(candidate), float(bearing_reference_deg))
                for candidate in frame.get("candidate_bearing_deg", [])
            )
            for frame in detected
            if frame.get("candidate_bearing_deg")
        ]
    return {
        "window_count": len(windows),
        "detected_count": len(detected),
        "abstained_count": sum(bool(frame.get("abstained")) for frame in windows),
        "abstention_rate": (
            sum(bool(frame.get("abstained")) for frame in windows) / len(windows)
            if windows
            else None
        ),
        "bearing_deg": _stats(
            [
                float(frame["srp_bearing_deg"])
                for frame in detected
                if frame.get("srp_bearing_deg") is not None
            ]
        ),
        "absolute_bearing_error_deg": _stats(bearing_errors),
        "candidate_count": _stats(candidate_counts),
        "nearest_candidate_error_deg": _stats(nearest_candidate_errors),
        "confidence": _stats([float(frame["bearing_confidence"]) for frame in windows]),
        "sector_accuracy": (
            sum(
                not bool(frame.get("abstained")) and bool(frame.get("sector_correct"))
                for frame in referenced
            )
            / len(referenced)
            if referenced
            else None
        ),
        "candidate_coverage": (
            sum(
                not bool(frame.get("abstained"))
                and bool(frame.get("candidate_covered"))
                for frame in referenced
            )
            / len(referenced)
            if referenced
            else None
        ),
        "candidate_coverage_counts": {
            "denominator": len(referenced),
            "covered": sum(
                not bool(frame.get("abstained"))
                and bool(frame.get("candidate_covered"))
                for frame in referenced
            ),
            "uncovered": sum(
                bool(frame.get("abstained")) or not bool(frame.get("candidate_covered"))
                for frame in referenced
            ),
            "abstained_uncovered": sum(
                bool(frame.get("abstained")) for frame in referenced
            ),
        },
        "major_polarity_anomaly_count": sum(
            bool(frame.get("major_polarity_anomaly")) for frame in windows
        ),
        "capture_to_frame_offline_ms": _stats(
            [float(frame["capture_to_frame_offline_ms"]) for frame in windows]
        ),
        "frame_to_adapter_round_trip_ms": _stats(
            [float(frame["frame_to_adapter_round_trip_ms"]) for frame in windows]
        ),
        "median_raw_rms_full_scale": _stats(
            [float(frame["median_raw_rms_full_scale"]) for frame in windows]
        ),
    }


def verify_deterministic_replay(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> ValidationReport:
    """Compare deterministic science while allowing honest runtime variation."""

    issues: list[ValidationIssue] = []
    for label, report in (("first", first), ("second", second)):
        if report.get("schema") != ANALYSIS_SCHEMA or report.get("status") != "passed":
            issues.append(_issue("invalid_replay_report", label, "analysis must pass"))
    if first.get("trial_id") != second.get("trial_id"):
        issues.append(_issue("replay_trial_mismatch", "trial_id", "trial ids differ"))
    if first.get("scientific_replay_sha256") != second.get("scientific_replay_sha256"):
        issues.append(
            _issue(
                "nondeterministic_science", "scientific_replay_sha256", "digests differ"
            )
        )
    return ValidationReport(
        (
            {
                "id": "s4_3_deterministic_replay",
                "status": "passed" if not issues else "failed",
                "scientific_replay_sha256": first.get("scientific_replay_sha256"),
                "runtime_fields_excluded": [
                    "analysis_runtime_ms",
                    "capture_to_frame_offline_ms",
                    "frame_to_adapter_round_trip_ms",
                ],
            },
        ),
        tuple(issues),
    )


def validate_inventory(
    inventory: Mapping[str, Any], configuration: Mapping[str, Any]
) -> ValidationReport:
    """Fail closed on missing planned trials, attempts, or unknown outcomes."""

    issues: list[ValidationIssue] = []
    if inventory.get("schema") != INVENTORY_SCHEMA:
        issues.append(
            _issue("wrong_inventory_schema", "schema", repr(inventory.get("schema")))
        )
    planned = {trial["trial_id"]: trial for trial in configuration["matrix"]}
    entries = inventory.get("trials")
    if not isinstance(entries, list):
        entries = []
        issues.append(_issue("invalid_inventory", "trials", "must be a list"))
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            issues.append(
                _issue("invalid_inventory_entry", f"trials[{index}]", "must be object")
            )
            continue
        trial_id = entry.get("trial_id")
        if trial_id not in planned:
            issues.append(
                _issue("unplanned_trial", f"trials[{index}].trial_id", repr(trial_id))
            )
            continue
        if trial_id in seen:
            issues.append(
                _issue("duplicate_inventory_trial", f"trials[{index}]", str(trial_id))
            )
        seen.add(str(trial_id))
        if entry.get("planned_definition_sha256") != canonical_sha256(
            planned[str(trial_id)]
        ):
            issues.append(
                _issue("trial_definition_mismatch", f"trials[{index}]", str(trial_id))
            )
        attempts = entry.get("attempts", [])
        if not isinstance(attempts, list):
            issues.append(
                _issue("invalid_attempts", f"trials[{index}].attempts", "must be list")
            )
            continue
        attempt_ids: set[str] = set()
        for attempt in attempts:
            if not isinstance(attempt, Mapping) or attempt.get(
                "outcome"
            ) not in EXPECTED_OUTCOMES - {"planned"}:
                issues.append(
                    _issue(
                        "invalid_attempt_outcome",
                        f"trials[{index}].attempts",
                        repr(attempt),
                    )
                )
                continue
            if attempt.get("attempt_id") in attempt_ids:
                issues.append(
                    _issue(
                        "duplicate_attempt",
                        f"trials[{index}].attempts",
                        str(attempt.get("attempt_id")),
                    )
                )
            attempt_ids.add(str(attempt.get("attempt_id")))
    missing = sorted(set(planned) - seen)
    if missing:
        issues.append(_issue("planned_trials_missing", "trials", repr(missing)))
    if inventory.get("s4_4_started") is not False:
        issues.append(_issue("s4_4_started", "s4_4_started", "must remain false"))
    return ValidationReport(
        (
            {
                "id": "s4_3_inventory",
                "status": "passed" if not issues else "failed",
                "planned_count": len(planned),
                "inventory_count": len(seen),
            },
        ),
        tuple(issues),
    )


def inventory_from_attempts(
    configuration: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Inventory every planned trial and every retained machine-local attempt."""

    root = Path(repo_root)
    inventory = planned_inventory(configuration)
    inventory["status"] = "collected"
    outcome_counts: Counter[str] = Counter()
    attempt_count = 0
    for entry in inventory["trials"]:
        trial_root = (
            root / configuration["retention"]["attempt_root"] / entry["trial_id"]
        )
        if not trial_root.is_dir():
            continue
        for attempt_root in sorted(
            path for path in trial_root.iterdir() if path.is_dir()
        ):
            lifecycle_path = attempt_root / "lifecycle.json"
            if not lifecycle_path.is_file():
                state = "failed"
                reason = "lifecycle_missing"
            else:
                lifecycle = load_json(lifecycle_path)
                state = str(lifecycle.get("state"))
                events = lifecycle.get("events", [])
                reason = events[-1].get("reason") if events else None
            outcome = state if state in EXPECTED_OUTCOMES else "in_progress"
            manifest_path = attempt_root / "manifest.json"
            analysis_path = attempt_root / "analysis.json"
            attempt = {
                "attempt_id": attempt_root.name,
                "outcome": outcome,
                "lifecycle_state": state,
                "reason": reason,
                "attempt_root": attempt_root.relative_to(root).as_posix(),
                "manifest_sha256": (
                    sha256_file(manifest_path) if manifest_path.is_file() else None
                ),
                "analysis_sha256": (
                    sha256_file(analysis_path) if analysis_path.is_file() else None
                ),
                "quality_status": (
                    load_json(manifest_path).get("quality_status")
                    if manifest_path.is_file()
                    else "missing"
                ),
                "scientific_disposition": (
                    load_json(manifest_path).get("scientific_disposition")
                    if manifest_path.is_file()
                    else "missing"
                ),
            }
            entry["attempts"].append(attempt)
            attempt_count += 1
            outcome_counts[outcome] += 1
        terminal = [
            attempt
            for attempt in entry["attempts"]
            if attempt["outcome"] in EXPECTED_OUTCOMES - {"planned"}
        ]
        if terminal:
            entry["planned_outcome"] = terminal[-1]["outcome"]
    inventory["attempt_count"] = attempt_count
    inventory["outcome_counts"] = {
        outcome: outcome_counts.get(outcome, 0)
        for outcome in [*sorted(EXPECTED_OUTCOMES), "in_progress"]
    }
    inventory["terminal_trial_count"] = sum(
        any(
            attempt["outcome"] in EXPECTED_OUTCOMES - {"planned"}
            for attempt in entry["attempts"]
        )
        for entry in inventory["trials"]
    )
    inventory["status"] = (
        "terminal"
        if inventory["terminal_trial_count"] == inventory["planned_trial_count"]
        and outcome_counts.get("in_progress", 0) == 0
        else "in_progress"
    )
    return inventory


def _group_values(windows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return [float(window[field]) for window in windows if window.get(field) is not None]


def _raw_channel_ids(configuration: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in configuration["audio"]["analysis_channel_ids"])


def _spectral_band_ids(configuration: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        f"{int(low)}-{int(high)}"
        for low, high in configuration["analysis"]["spectral_bands_hz"]
    )


def _ordered_pair_ids(channel_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{left}->{right}" for left in channel_ids for right in channel_ids)


def _nonself_pair_ids(channel_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        f"{left}->{right}"
        for left in channel_ids
        for right in channel_ids
        if left != right
    )


def _unique_pair_ids(channel_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        f"{left}->{right}"
        for left_index, left in enumerate(channel_ids)
        for right_index, right in enumerate(channel_ids)
        if right_index > left_index
    )


def build_channel_evidence(
    analysis: Mapping[str, Any] | None,
    trial: Mapping[str, Any],
    configuration: Mapping[str, Any],
    *,
    attempt_id: str,
    outcome: str,
) -> dict[str, Any]:
    """Describe every declared channel, including explicit missing-channel evidence."""

    expected_order = tuple(
        str(value) for value in configuration["audio"]["channel_order"]
    )
    raw_ids = set(_raw_channel_ids(configuration))
    sustained_clip_run_samples_min = int(
        configuration["quality"]["maximum_sustained_clip_run_samples"]
    )
    if analysis is None:
        return {
            "trial_id": trial["trial_id"],
            "attempt_id": attempt_id,
            "outcome": outcome,
            "status": "not_applicable_before_capture",
            "reason": "attempt ended before a waveform analysis record existed",
            "expected_channel_count": len(expected_order),
            "declared_channel_order": list(expected_order),
            "channels": [],
            "raw_channel_health_failure_count": 0,
        }
    wav = analysis.get("wav")
    if not isinstance(wav, Mapping):
        wav = {}
    observed_count = wav.get("channel_count")
    arrays = {
        "rms_pcm16": wav.get("per_channel_rms_pcm16"),
        "peak_pcm16": wav.get("per_channel_peak_pcm16"),
        "maximum_clip_run_samples": wav.get("per_channel_maximum_clip_run_samples"),
    }
    channels = []
    for index, channel_id in enumerate(expected_order):
        values: dict[str, Any] = {}
        for field, sequence in arrays.items():
            values[field] = (
                sequence[index]
                if isinstance(sequence, list) and index < len(sequence)
                else None
            )
        numeric = all(
            isinstance(values[field], (int, float))
            and math.isfinite(float(values[field]))
            for field in values
        )
        present = isinstance(observed_count, int) and observed_count > index and numeric
        raw = channel_id in raw_ids
        nonsilent_required = raw and trial.get("stimulus") != "silence"
        silent_failure = bool(
            nonsilent_required
            and isinstance(values["rms_pcm16"], (int, float))
            and float(values["rms_pcm16"]) <= 0.0
        )
        sustained_clipping = bool(
            isinstance(values["maximum_clip_run_samples"], (int, float))
            and float(values["maximum_clip_run_samples"])
            >= sustained_clip_run_samples_min
        )
        healthy = present and not silent_failure and not sustained_clipping
        channels.append(
            {
                "channel_index": index,
                "channel_id": channel_id,
                "analysis_raw_channel": raw,
                "present": present,
                "finite_summary": numeric,
                "nonsilent_required": nonsilent_required,
                "silent_failure": silent_failure,
                "sustained_clipping": sustained_clipping,
                "healthy": healthy,
                **values,
            }
        )
    declared_failures = sum(not bool(channel["healthy"]) for channel in channels)
    raw_failures = sum(
        not bool(channel["healthy"])
        for channel in channels
        if channel["analysis_raw_channel"]
    )
    complete = (
        observed_count == len(expected_order)
        and len(channels) == len(expected_order)
        and all(channel["finite_summary"] for channel in channels)
    )
    return {
        "trial_id": trial["trial_id"],
        "attempt_id": attempt_id,
        "outcome": outcome,
        "status": "passed" if complete and declared_failures == 0 else "failed",
        "expected_channel_count": len(expected_order),
        "observed_channel_count": observed_count,
        "declared_channel_order": list(expected_order),
        "order_verification": {
            "status": "passed" if complete else "failed",
            "method": "frozen device identity and firmware channel map plus WAV index",
            "limitation": "physical acoustic centers were not independently traced",
        },
        "sustained_clip_run_samples_min": sustained_clip_run_samples_min,
        "sustained_clip_failure_comparator": "greater_than_or_equal",
        "declared_channel_health_failure_count": declared_failures,
        "channels": channels,
        "raw_channel_health_failure_count": raw_failures,
    }


def _boolean_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return half-open true runs from one boolean vector."""

    if mask.ndim != 1:
        raise S43Error("event mask must be one-dimensional")
    padded = np.concatenate((np.asarray([False]), mask, np.asarray([False])))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [
        (int(start), int(stop))
        for start, stop in zip(changes[::2], changes[1::2], strict=True)
    ]


def _bridge_event_gaps(mask: np.ndarray, maximum_gap_samples: int) -> np.ndarray:
    """Bridge only bounded inactive gaps, leaving interval boundaries censored."""

    bridged = mask.copy()
    false_runs = _boolean_runs(~mask)
    for start, stop in false_runs:
        if start > 0 and stop < mask.size and stop - start <= maximum_gap_samples:
            bridged[start:stop] = True
    return bridged


def _prospective_transient_events(
    raw_samples: np.ndarray,
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Count de-duplicated transient candidates independently of report windows."""

    detector = configuration.get("noise_event_detector")
    if not isinstance(detector, Mapping):
        raise S43Error("prospective transient-event detector provenance is absent")
    rate = int(configuration["audio"]["sample_rate_hz"])
    if detector.get("sample_rate_hz") != rate:
        raise S43Error("prospective transient detector sample rate is inconsistent")
    window = int(detector["energy_window_samples"])
    if raw_samples.ndim != 2 or raw_samples.shape[1] != len(
        configuration["audio"]["analysis_channel_ids"]
    ):
        raise S43Error("prospective transient detector requires every raw channel")
    kernel = np.ones(window, dtype=np.float64) / window
    envelopes = np.column_stack(
        [
            np.sqrt(np.convolve(raw_samples[:, channel] ** 2, kernel, mode="same"))
            for channel in range(raw_samples.shape[1])
        ]
    )
    medians = np.median(envelopes, axis=0)
    mads = np.median(np.abs(envelopes - medians), axis=0)
    thresholds = np.maximum(
        float(detector["absolute_rms_floor_full_scale"]),
        medians + float(detector["robust_sigma_multiplier"]) * 1.4826 * mads,
    )
    concurrent = np.sum(envelopes >= thresholds, axis=1) >= int(
        detector["minimum_concurrent_raw_channels"]
    )
    bridged = _bridge_event_gaps(
        concurrent, int(detector["maximum_bridge_gap_samples"])
    )
    events: list[dict[str, Any]] = []
    stationary: list[dict[str, Any]] = []
    censored: list[dict[str, Any]] = []
    short: list[dict[str, Any]] = []
    aggregate_envelope = np.median(envelopes, axis=1)
    for start, stop in _boolean_runs(bridged):
        duration = stop - start
        peak = start + int(np.argmax(aggregate_envelope[start:stop]))
        record = {
            "start_sample": start,
            "stop_sample_exclusive": stop,
            "duration_samples": duration,
            "duration_ms": 1000.0 * duration / rate,
            "peak_sample": peak,
            "peak_median_raw_rms_full_scale": float(aggregate_envelope[peak]),
        }
        if start == 0 or stop == bridged.size:
            censored.append(record)
        elif duration < int(detector["minimum_event_duration_samples"]):
            short.append(record)
        elif duration > int(detector["maximum_transient_duration_samples"]):
            stationary.append(record)
        else:
            events.append(record)
    duration_s = raw_samples.shape[0] / rate
    return {
        "status": "measured",
        "metric_id": "prospective_deduplicated_transient_event_rate",
        "contract_sha256": configuration["corrective_provenance"][
            "prospective_transient_event_contract"
        ]["sha256"],
        "detector_window_overlap_dependency": "none",
        "duration_s": duration_s,
        "event_count": len(events),
        "event_rate_per_s": len(events) / duration_s,
        "events": events,
        "stationary_excursion_count": len(stationary),
        "stationary_excursions": stationary,
        "boundary_censored_excursion_count": len(censored),
        "boundary_censored_excursions": censored,
        "short_excursion_count": len(short),
        "short_excursions": short,
        "per_channel_baseline_rms_full_scale": medians.tolist(),
        "per_channel_mad_rms_full_scale": mads.tolist(),
        "per_channel_threshold_rms_full_scale": thresholds.tolist(),
        "classification": "Measured",
    }


def analyze_noise_characterization(
    wav_path: str | Path,
    analysis: Mapping[str, Any],
    trial: Mapping[str, Any],
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate legacy RMS exceedances from prospective de-duplicated events."""

    stimulus = str(trial.get("stimulus"))
    if stimulus != "silence" and "mac_reference" not in stimulus:
        return {
            "trial_id": trial["trial_id"],
            "status": "not_applicable",
            "reason": "no intended-silence or reference pre-stimulus interval",
        }
    samples, rate = _read_pcm16(Path(wav_path))
    if stimulus == "silence":
        interval_start = 0
        interval_stop = samples.shape[0]
        interval_kind = "intended_silence"
    else:
        reference_start = analysis.get("reference_start_sample")
        if not isinstance(reference_start, int) or reference_start <= 0:
            return {
                "trial_id": trial["trial_id"],
                "status": "unmeasured",
                "reason": "reference pre-stimulus boundary absent",
            }
        interval_start = 0
        interval_stop = min(reference_start, samples.shape[0])
        interval_kind = "reference_pre_stimulus"
    size = round(configuration["analysis"]["window_duration_ms"] * rate / 1000)
    hop = round(
        size * (1.0 - configuration["analysis"]["window_overlap_percent"] / 100.0)
    )
    raw_indices = tuple(
        int(value) for value in configuration["audio"]["analysis_channel_indices"]
    )
    raw_ids = _raw_channel_ids(configuration)
    threshold = float(configuration["analysis"]["signal_rms_full_scale_threshold"])
    median_rms_values: list[float] = []
    per_channel: dict[str, list[float]] = {channel_id: [] for channel_id in raw_ids}
    spectrum: dict[str, list[float]] = {
        band_id: [] for band_id in _spectral_band_ids(configuration)
    }
    for start in range(interval_start, interval_stop - size + 1, hop):
        window = samples[start : start + size, raw_indices].T
        rms = np.sqrt(np.mean(window * window, axis=1))
        median_rms_values.append(float(np.median(rms)))
        for channel_id, value in zip(raw_ids, rms, strict=True):
            per_channel[channel_id].append(float(value))
        bands = _relative_band_db(
            np.mean(window, axis=0),
            rate,
            configuration["analysis"]["spectral_bands_hz"],
        )
        for band_id, value in bands.items():
            spectrum[band_id].append(float(value))
    duration_s = (interval_stop - interval_start) / rate
    exceedance_count = sum(value > threshold for value in median_rms_values)
    if not median_rms_values or duration_s <= 0.0:
        return {
            "trial_id": trial["trial_id"],
            "status": "unmeasured",
            "reason": "noise interval contains no complete frozen window",
        }
    return {
        "trial_id": trial["trial_id"],
        "schema": "ias.s4_3.noise_characterization.v2",
        "status": "measured",
        "interval_kind": interval_kind,
        "interval_start_sample": interval_start,
        "interval_stop_sample": interval_stop,
        "duration_s": duration_s,
        "window_duration_ms": configuration["analysis"]["window_duration_ms"],
        "window_overlap_percent": configuration["analysis"]["window_overlap_percent"],
        "window_count": len(median_rms_values),
        "legacy_overlapping_window_rms_exceedance": {
            "status": "measured",
            "metric_id": "legacy_overlapping_window_rms_exceedance_rate",
            "threshold_median_raw_rms_full_scale": threshold,
            "exceedance_window_count": exceedance_count,
            "overlapping_window_count": len(median_rms_values),
            "exceedance_rate_per_s": exceedance_count / duration_s,
            "classification": "Measured",
            "limitation": (
                "overlapping analysis-window exceedances are correlated and are "
                "not distinct physical transient events"
            ),
        },
        "legacy_distinct_event_rate": {
            "status": "unmeasured",
            "metric_id": "legacy_distinct_transient_event_rate",
            "classification": "Unmeasured",
            "reason": (
                "the retained S4.3 waveform was inspected before the prospective "
                "de-duplicated detector contract was frozen"
            ),
        },
        "prospective_distinct_transient_events": (
            _prospective_transient_events(
                samples[interval_start:interval_stop, raw_indices], configuration
            )
            if trial["trial_id"]
            == configuration.get("corrective_provenance", {})
            .get("prospective_transient_event_contract", {})
            .get("prospective_evidence_trial_id")
            else {
                "status": "unmeasured",
                "metric_id": "prospective_deduplicated_transient_event_rate",
                "classification": "Unmeasured",
                "reason": "trial predates the prospectively frozen detector contract",
            }
        ),
        "median_raw_rms_full_scale": _stats(median_rms_values),
        "per_channel_rms_full_scale": {
            channel_id: _stats(values)
            for channel_id, values in sorted(per_channel.items())
        },
        "combined_spectrum_relative_db": {
            band_id: _stats(values) for band_id, values in sorted(spectrum.items())
        },
        "classification": "Measured",
        "limitation": (
            "functional room-fixture-sensor noise, not microphone self-noise SPL; "
            "legacy overlapping-window exceedances and prospective de-duplicated "
            "events are distinct metrics"
        ),
    }


def aggregate_category(
    category: str,
    analyses: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Any],
    *,
    configuration: Mapping[str, Any] | None = None,
    channel_evidence: Sequence[Mapping[str, Any]] = (),
    noise_transient_results: Sequence[Mapping[str, Any]] = (),
    coarse_audio_video_association: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a separated category report with complete small-sample summaries."""

    selected = [report for report in analyses if report.get("category") == category]
    definitions = (
        {str(trial["trial_id"]): trial for trial in configuration.get("matrix", [])}
        if configuration is not None
        else {}
    )
    window_records = [
        (report, window) for report in selected for window in report.get("windows", [])
    ]
    windows = [window for _report, window in window_records]
    nonabstained_records = [
        (report, window)
        for report, window in window_records
        if not bool(window.get("abstained"))
    ]
    nonabstained = [window for _report, window in nonabstained_records]
    referenced_records = [
        (report, window)
        for report, window in window_records
        if "candidate_covered" in window
    ]
    channel_rms: dict[str, list[float]] = {}
    channel_relative: dict[str, list[float]] = {}
    spectral: dict[str, list[float]] = {}
    tdoa_us: dict[str, list[float]] = {}
    tdoa_error_us: dict[str, list[float]] = {}
    delays_us: dict[str, list[float]] = {}
    polarity: dict[str, list[float]] = {}
    for report, window in window_records:
        for key, value in window.get("per_channel_rms_full_scale", {}).items():
            channel_rms.setdefault(key, []).append(float(value))
        for key, value in window.get("combined_spectrum_relative_db", {}).items():
            spectral.setdefault(key, []).append(float(value))
        if bool(window.get("abstained")):
            continue
        if report.get("stimulus") != "silence":
            for key, value in window.get("per_channel_relative_rms_db", {}).items():
                channel_relative.setdefault(key, []).append(float(value))
        for key, value in window.get("tdoa_s", {}).items():
            if key.split("->")[0] != key.split("->")[1]:
                tdoa_us.setdefault(key, []).append(float(value) * 1e6)
        for key, value in window.get("tdoa_error_s", {}).items():
            if key.split("->")[0] != key.split("->")[1]:
                tdoa_error_us.setdefault(key, []).append(float(value) * 1e6)
        for key, value in window.get("relative_channel_delay_s", {}).items():
            delays_us.setdefault(key, []).append(float(value) * 1e6)
        for key, value in window.get("aligned_pair_correlation", {}).items():
            polarity.setdefault(key, []).append(float(value))

    inventory_trials = [
        entry for entry in inventory["trials"] if entry["category"] == category
    ]
    attempts = [attempt for entry in inventory_trials for attempt in entry["attempts"]]
    trial_ids = {str(entry["trial_id"]) for entry in inventory_trials}
    corrected_summaries = {}
    for report in selected:
        definition = definitions.get(str(report["trial_id"]), {})
        reference = definition.get("source_bearing_deg")
        corrected_summaries[str(report["trial_id"])] = summarize_windows(
            report.get("windows", []),
            bearing_reference_deg=(None if reference is None else float(reference)),
        )
    candidate_counts = [
        float(len(window.get("candidate_bearing_deg", [])))
        for _report, window in referenced_records
        if not bool(window.get("abstained"))
    ]
    nearest_candidate_errors = []
    for report, window in referenced_records:
        if bool(window.get("abstained")):
            continue
        definition = definitions.get(str(report["trial_id"]), {})
        reference = definition.get("source_bearing_deg")
        candidates = window.get("candidate_bearing_deg", [])
        if reference is not None and candidates:
            nearest_candidate_errors.append(
                min(
                    _angular_error(float(candidate), float(reference))
                    for candidate in candidates
                )
            )
        elif window.get("absolute_bearing_error_deg") is not None and candidates:
            nearest_candidate_errors.append(float(window["absolute_bearing_error_deg"]))
    least_squares_bearings = _group_values(nonabstained, "least_squares_bearing_deg")
    least_squares_missing_count = sum(
        window.get("least_squares_bearing_deg") is None
        for _report, window in referenced_records
        if not bool(window.get("abstained"))
    )
    report_payload = {
        "schema": "ias.s4_3.category_report.v2",
        "category": category,
        "planned_trial_count": len(inventory_trials),
        "attempt_count": len(attempts),
        "accepted_analysis_count": len(selected),
        "outcome_counts": dict(Counter(attempt["outcome"] for attempt in attempts)),
        "trial_summaries": [
            {
                "trial_id": report["trial_id"],
                "summary": corrected_summaries[str(report["trial_id"])],
                "relative_decay": report.get("relative_decay"),
                "scientific_replay_sha256": report["scientific_replay_sha256"],
            }
            for report in selected
        ],
        "pooled": {
            "window_count": len(windows),
            "nonabstained_window_count": len(nonabstained),
            "bearing_deg": _stats(_group_values(nonabstained, "srp_bearing_deg")),
            "absolute_bearing_error_deg": _stats(
                _group_values(nonabstained, "absolute_bearing_error_deg")
            ),
            "least_squares_bearing_deg": _stats(least_squares_bearings),
            "least_squares_missing_count": least_squares_missing_count,
            "candidate_count": _stats(candidate_counts),
            "nearest_candidate_error_deg": _stats(nearest_candidate_errors),
            "confidence": _stats(_group_values(windows, "bearing_confidence")),
            "abstention_rate": (
                sum(bool(window.get("abstained")) for window in windows) / len(windows)
                if windows
                else None
            ),
            "ambiguity_counts": dict(
                Counter(str(window.get("ambiguity_class")) for window in windows)
            ),
            "sector_accuracy": (
                sum(
                    not bool(window.get("abstained"))
                    and bool(window.get("sector_correct"))
                    for _, window in referenced_records
                )
                / len(referenced_records)
                if referenced_records
                else None
            ),
            "sector_accuracy_counts": {
                "denominator": len(referenced_records),
                "correct": sum(
                    not bool(window.get("abstained"))
                    and bool(window.get("sector_correct"))
                    for _, window in referenced_records
                ),
                "incorrect": sum(
                    bool(window.get("abstained"))
                    or not bool(window.get("sector_correct"))
                    for _, window in referenced_records
                ),
                "abstained_incorrect": sum(
                    bool(window.get("abstained")) for _, window in referenced_records
                ),
            },
            "candidate_coverage": (
                sum(
                    not bool(window.get("abstained"))
                    and bool(window.get("candidate_covered"))
                    for _, window in referenced_records
                )
                / len(referenced_records)
                if referenced_records
                else None
            ),
            "candidate_coverage_counts": {
                "denominator": len(referenced_records),
                "covered": sum(
                    not bool(window.get("abstained"))
                    and bool(window.get("candidate_covered"))
                    for _, window in referenced_records
                ),
                "uncovered": sum(
                    bool(window.get("abstained"))
                    or not bool(window.get("candidate_covered"))
                    for _, window in referenced_records
                ),
                "abstained_uncovered": sum(
                    bool(window.get("abstained")) for _, window in referenced_records
                ),
            },
            "major_polarity_anomaly_count": sum(
                bool(window.get("major_polarity_anomaly")) for window in windows
            ),
            "capture_to_frame_offline_ms": _stats(
                _group_values(windows, "capture_to_frame_offline_ms")
            ),
            "frame_to_adapter_round_trip_ms": _stats(
                _group_values(windows, "frame_to_adapter_round_trip_ms")
            ),
            "per_channel_rms_full_scale": {
                key: _stats(values) for key, values in sorted(channel_rms.items())
            },
            "per_channel_relative_rms_db": {
                key: _stats(values) for key, values in sorted(channel_relative.items())
            },
            "combined_spectrum_relative_db": {
                key: _stats(values) for key, values in sorted(spectral.items())
            },
            "tdoa_us": {key: _stats(values) for key, values in sorted(tdoa_us.items())},
            "tdoa_error_us": {
                key: _stats(values) for key, values in sorted(tdoa_error_us.items())
            },
            "relative_channel_delay_us": {
                key: _stats(values) for key, values in sorted(delays_us.items())
            },
            "aligned_pair_correlation": {
                key: _stats(values) for key, values in sorted(polarity.items())
            },
        },
        "small_sample_p95": True,
        "limitations": [
            "functional engineering characterization only",
            "central, spread, tail, and worst values describe the retained pilot",
            "nearest-rank p95 is labeled small-sample and is not a population estimate",
        ],
    }
    report_payload["channel_presence_order_health"] = [
        dict(record)
        for record in channel_evidence
        if str(record.get("trial_id")) in trial_ids
    ]
    report_payload["noise_transient_results"] = [
        dict(record)
        for record in noise_transient_results
        if str(record.get("trial_id")) in trial_ids
        and record.get("status") != "not_applicable"
    ]
    if category == "robustness":
        report_payload["coarse_audio_video_association"] = (
            None
            if coarse_audio_video_association is None
            else dict(coarse_audio_video_association)
        )
    return report_payload


def _circular_range(values: Sequence[float]) -> float | None:
    if not values:
        return None
    normalized = sorted(float(value) % 360.0 for value in values)
    if len(normalized) == 1:
        return 0.0
    gaps = [
        later - earlier
        for earlier, later in zip(normalized, normalized[1:], strict=False)
    ]
    gaps.append(normalized[0] + 360.0 - normalized[-1])
    return 360.0 - max(gaps)


def evaluate_repeatability(
    analyses: Sequence[Mapping[str, Any]], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply only the preregistered baseline and silence criteria."""

    baseline = [
        report for report in analyses if report.get("category") == "repeatability"
    ]
    silence = [
        report for report in analyses if report.get("trial_id") == "s4_3_rob_silence_01"
    ]
    thresholds = configuration["repeatability_acceptance"]
    definitions = {str(trial["trial_id"]): trial for trial in configuration["matrix"]}
    expected_baseline_ids = {
        trial_id
        for trial_id, trial in definitions.items()
        if trial.get("category") == "repeatability"
    }
    baseline_ids = {str(report.get("trial_id")) for report in baseline}
    summaries = {
        str(report["trial_id"]): summarize_windows(
            report.get("windows", []),
            bearing_reference_deg=float(
                definitions[str(report["trial_id"])]["source_bearing_deg"]
            ),
        )
        for report in baseline
        if str(report.get("trial_id")) in definitions
    }
    trial_bearings = [
        float(summaries[str(report["trial_id"])]["bearing_deg"]["median"])
        for report in baseline
        if summaries.get(str(report.get("trial_id")), {})
        .get("bearing_deg", {})
        .get("median")
        is not None
    ]
    trial_errors = [
        float(
            summaries[str(report["trial_id"])]["absolute_bearing_error_deg"]["median"]
        )
        for report in baseline
        if summaries.get(str(report.get("trial_id")), {})
        .get("absolute_bearing_error_deg", {})
        .get("median")
        is not None
    ]
    sector = [
        float(summaries[str(report["trial_id"])]["sector_accuracy"])
        for report in baseline
        if summaries.get(str(report.get("trial_id")), {}).get("sector_accuracy")
        is not None
    ]
    candidates = [
        float(summaries[str(report["trial_id"])]["candidate_coverage"])
        for report in baseline
        if summaries.get(str(report.get("trial_id")), {}).get("candidate_coverage")
        is not None
    ]

    def trial_medians(field: str) -> dict[str, list[float]]:
        grouped: dict[str, list[float]] = {}
        for report in baseline:
            per_report: dict[str, list[float]] = {}
            for window in report["windows"]:
                if field in {"tdoa_s", "relative_channel_delay_s"} and bool(
                    window.get("abstained")
                ):
                    continue
                for key, value in window.get(field, {}).items():
                    if field.endswith("_s"):
                        value = float(value) * 1e6
                    per_report.setdefault(key, []).append(float(value))
            for key, values in per_report.items():
                grouped.setdefault(key, []).append(float(median(values)))
        return grouped

    tdoa = trial_medians("tdoa_s")
    relative_rms = trial_medians("per_channel_relative_rms_db")
    spectrum = trial_medians("combined_spectrum_relative_db")
    raw_ids = _raw_channel_ids(configuration)
    expected_tdoa = set(_ordered_pair_ids(raw_ids))
    expected_bands = set(_spectral_band_ids(configuration))
    raw_health_records = [
        build_channel_evidence(
            report,
            definitions[str(report["trial_id"])],
            configuration,
            attempt_id=str(report["trial_id"]),
            outcome="accepted",
        )
        for report in baseline
        if str(report.get("trial_id")) in definitions
    ]
    raw_health_failure_count = sum(
        int(record["raw_channel_health_failure_count"]) for record in raw_health_records
    )
    checks = {
        "complete_repeatability_trials": baseline_ids == expected_baseline_ids,
        "required_baseline_trials": len(baseline)
        >= thresholds["required_baseline_trials"],
        "median_absolute_bearing_error": bool(trial_errors)
        and float(median(trial_errors))
        <= thresholds["median_absolute_bearing_error_deg_max"],
        "worst_trial_median_absolute_bearing_error": bool(trial_errors)
        and max(trial_errors)
        <= thresholds["worst_trial_median_absolute_bearing_error_deg_max"],
        "bearing_circular_range": _circular_range(trial_bearings) is not None
        and float(_circular_range(trial_bearings))
        <= thresholds["trial_median_bearing_circular_range_deg_max"],
        "sector_accuracy": len(sector) == len(baseline)
        and float(np.mean(sector)) >= thresholds["sector_accuracy_min"],
        "candidate_coverage": len(candidates) == len(baseline)
        and float(np.mean(candidates)) >= thresholds["candidate_coverage_min"],
        "pair_tdoa_range": set(tdoa) == expected_tdoa
        and all(
            len(values) == len(baseline)
            and max(values) - min(values)
            <= thresholds["pair_tdoa_trial_median_range_us_max"]
            for values in tdoa.values()
        ),
        "relative_rms_range": set(relative_rms) == set(raw_ids)
        and all(
            len(values) == len(baseline)
            and max(values) - min(values)
            <= thresholds["relative_rms_trial_median_range_db_max"]
            for values in relative_rms.values()
        ),
        "spectral_band_range": set(spectrum) == expected_bands
        and all(
            len(values) == len(baseline)
            and max(values) - min(values)
            <= thresholds["spectral_band_trial_median_range_db_max"]
            for values in spectrum.values()
        ),
        "raw_channel_health_failures": raw_health_failure_count
        <= thresholds["raw_channel_health_failure_count_max"],
        "major_polarity_anomalies": sum(
            report["summary"]["major_polarity_anomaly_count"] for report in baseline
        )
        <= thresholds["major_polarity_anomaly_count_max"],
        "silence_abstention": len(silence) == 1
        and silence[0]["summary"]["abstention_rate"]
        >= thresholds["silence_abstention_rate_min"],
    }
    return {
        "schema": "ias.s4_3.repeatability_gate.v2",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "observations": {
            "trial_median_bearing_deg": trial_bearings,
            "trial_median_absolute_bearing_error_deg": trial_errors,
            "bearing_circular_range_deg": _circular_range(trial_bearings),
            "sector_accuracy_by_trial": sector,
            "candidate_coverage_by_trial": candidates,
            "pair_tdoa_trial_medians_us": tdoa,
            "relative_rms_trial_medians_db": relative_rms,
            "spectral_band_trial_medians_db": spectrum,
            "raw_channel_health_failure_count": raw_health_failure_count,
            "raw_channel_health_by_trial": raw_health_records,
            "silence_abstention_rate": (
                silence[0]["summary"]["abstention_rate"] if len(silence) == 1 else None
            ),
        },
        "thresholds": dict(thresholds),
    }


def validate_metric_evidence(
    configuration: Mapping[str, Any],
    analyses: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Any],
    category_reports: Mapping[str, Mapping[str, Any]],
    channel_evidence: Sequence[Mapping[str, Any]],
    noise_transient_results: Sequence[Mapping[str, Any]],
    failure_report: Mapping[str, Any],
    coarse_audio_video_association: Mapping[str, Any] | None,
    svo_replay: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate each frozen metric against concrete, complete evidence."""

    metric_names = {
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
    }
    issues: dict[str, list[str]] = {name: [] for name in sorted(metric_names)}

    def require(metric: str, condition: bool, message: str) -> None:
        if not condition:
            issues[metric].append(message)

    contracts = configuration.get("metric_contracts", {})
    contract_fields = {
        "method",
        "reference",
        "units",
        "uncertainty",
        "aggregation",
        "exclusions",
        "missing",
        "applicability",
        "limitations",
    }
    for metric in metric_names:
        contract = contracts.get(metric)
        require(metric, isinstance(contract, Mapping), "metric contract absent")
        if isinstance(contract, Mapping):
            missing_fields = sorted(contract_fields - set(contract))
            require(
                metric,
                not missing_fields,
                f"metric contract fields absent: {missing_fields}",
            )
    unexpected_contracts = sorted(set(contracts) - metric_names)
    if unexpected_contracts:
        for metric in metric_names:
            require(
                metric,
                False,
                f"unvalidated metric contracts present: {unexpected_contracts}",
            )

    definitions = {
        str(trial["trial_id"]): trial for trial in configuration.get("matrix", [])
    }
    accepted_trial_ids = {
        str(entry["trial_id"])
        for entry in inventory.get("trials", [])
        if any(
            attempt.get("outcome") == "accepted"
            for attempt in entry.get("attempts", [])
        )
    }
    analyses_by_id = {
        str(report.get("trial_id")): report
        for report in analyses
        if isinstance(report, Mapping)
    }
    require(
        "acquisition_analysis_failures",
        set(analyses_by_id) == accepted_trial_ids,
        "accepted trial analyses are missing or duplicated",
    )
    raw_ids = _raw_channel_ids(configuration)
    raw_set = set(raw_ids)
    ordered_pairs = set(_ordered_pair_ids(raw_ids))
    nonself_pairs = set(_nonself_pair_ids(raw_ids))
    unique_pairs = set(_unique_pair_ids(raw_ids))
    band_set = set(_spectral_band_ids(configuration))
    category_expected: dict[str, dict[str, int]] = {
        category: {
            "windows": 0,
            "nonabstained": 0,
            "referenced": 0,
            "referenced_nonabstained": 0,
            "active_nonabstained": 0,
        }
        for category in EXPECTED_CATEGORIES
    }

    for trial_id in sorted(accepted_trial_ids):
        report = analyses_by_id.get(trial_id)
        trial = definitions.get(trial_id)
        if report is None or trial is None:
            continue
        category = str(trial["category"])
        windows = report.get("windows")
        if not isinstance(windows, list) or not windows:
            for metric in metric_names - {"acquisition_analysis_failures"}:
                require(metric, False, f"{trial_id}: analyzed windows absent")
            continue
        require(
            "acquisition_analysis_failures",
            report.get("status") == "passed"
            and report.get("window_count") == len(windows),
            f"{trial_id}: analysis status/count invalid",
        )
        referenced = trial.get("source_bearing_deg") is not None
        active = trial.get("stimulus") != "silence"
        for index, window in enumerate(windows):
            label = f"{trial_id}.windows[{index}]"
            abstained = window.get("abstained")
            require(
                "abstention", isinstance(abstained, bool), f"{label}: abstention absent"
            )
            if not isinstance(abstained, bool):
                abstained = True
            category_expected[category]["windows"] += 1
            if not abstained:
                category_expected[category]["nonabstained"] += 1
            if referenced:
                category_expected[category]["referenced"] += 1
                if not abstained:
                    category_expected[category]["referenced_nonabstained"] += 1
            if active and not abstained:
                category_expected[category]["active_nonabstained"] += 1
            confidence = window.get("bearing_confidence")
            require(
                "confidence",
                isinstance(confidence, (int, float))
                and math.isfinite(float(confidence)),
                f"{label}: confidence absent or nonfinite",
            )
            require(
                "ambiguity",
                isinstance(window.get("ambiguity_class"), str)
                and bool(window.get("ambiguity_class")),
                f"{label}: ambiguity class absent",
            )
            for metric, field in (
                ("capture_to_frame_latency", "capture_to_frame_offline_ms"),
                ("frame_to_adapter_latency", "frame_to_adapter_round_trip_ms"),
            ):
                value = window.get(field)
                require(
                    metric,
                    isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    and float(value) >= 0.0,
                    f"{label}: {field} absent or invalid",
                )
            for metric, field, expected in (
                ("relative_rms_level", "per_channel_rms_full_scale", raw_set),
                ("combined_spectrum", "combined_spectrum_relative_db", band_set),
            ):
                values = window.get(field)
                require(
                    metric,
                    isinstance(values, Mapping)
                    and set(values) == expected
                    and all(
                        isinstance(value, (int, float)) and math.isfinite(float(value))
                        for value in values.values()
                    ),
                    f"{label}: incomplete {field}",
                )
            if referenced:
                require(
                    "candidate_bearing",
                    isinstance(window.get("candidate_covered"), bool),
                    f"{label}: candidate coverage flag absent",
                )
                require(
                    "sector_accuracy",
                    isinstance(window.get("sector_correct"), bool),
                    f"{label}: sector correctness flag absent",
                )
                if not abstained:
                    candidates = window.get("candidate_bearing_deg")
                    require(
                        "candidate_bearing",
                        isinstance(candidates, list)
                        and bool(candidates)
                        and all(
                            isinstance(value, (int, float))
                            and math.isfinite(float(value))
                            for value in candidates
                        ),
                        f"{label}: candidate bearings absent",
                    )
                    for field in ("srp_bearing_deg", "absolute_bearing_error_deg"):
                        value = window.get(field)
                        require(
                            "bearing_doa_error",
                            isinstance(value, (int, float))
                            and math.isfinite(float(value)),
                            f"{label}: {field} absent or nonfinite",
                        )
                    least_squares = window.get("least_squares_bearing_deg")
                    require(
                        "bearing_doa_error",
                        "least_squares_bearing_deg" in window
                        and (
                            least_squares is None
                            or (
                                isinstance(least_squares, (int, float))
                                and math.isfinite(float(least_squares))
                            )
                        )
                        and isinstance(
                            window.get("least_squares_candidates_deg"), list
                        ),
                        f"{label}: least-squares result/missing state absent",
                    )
            if active and not abstained:
                for metric, field, expected in (
                    ("tdoa", "tdoa_s", ordered_pairs),
                    ("relative_channel_delay", "relative_channel_delay_s", raw_set),
                    (
                        "major_polarity_anomaly",
                        "aligned_pair_correlation",
                        unique_pairs,
                    ),
                    ("channel_imbalance", "per_channel_relative_rms_db", raw_set),
                ):
                    values = window.get(field)
                    require(
                        metric,
                        isinstance(values, Mapping)
                        and set(values) == expected
                        and all(
                            isinstance(value, (int, float))
                            and math.isfinite(float(value))
                            for value in values.values()
                        ),
                        f"{label}: incomplete {field}",
                    )
                require(
                    "major_polarity_anomaly",
                    isinstance(window.get("major_polarity_anomaly"), bool),
                    f"{label}: polarity anomaly flag absent",
                )
                if referenced:
                    tdoa_error = window.get("tdoa_error_s")
                    require(
                        "tdoa",
                        isinstance(tdoa_error, Mapping)
                        and set(tdoa_error) == ordered_pairs
                        and all(
                            isinstance(value, (int, float))
                            and math.isfinite(float(value))
                            for value in tdoa_error.values()
                        ),
                        f"{label}: incomplete tdoa_error_s",
                    )

        decay = report.get("relative_decay")
        if (
            "mac_reference" in str(trial.get("stimulus"))
            or trial.get("stimulus") == "visible_audible_ordinary_object_impact"
        ):
            require(
                "echo_relative_decay",
                isinstance(decay, Mapping)
                and decay.get("status") in {"measured", "censored", "unmeasured"},
                f"{trial_id}: relative decay result absent",
            )

    for category in sorted(EXPECTED_CATEGORIES):
        report = category_reports.get(category)
        for metric in metric_names - {
            "acquisition_analysis_failures",
            "coarse_audio_video_association",
        }:
            require(
                metric,
                isinstance(report, Mapping)
                and report.get("schema") == "ias.s4_3.category_report.v2",
                f"{category}: category report absent or wrong schema",
            )
        if not isinstance(report, Mapping):
            continue
        pooled = report.get("pooled")
        if not isinstance(pooled, Mapping):
            for metric in metric_names:
                require(metric, False, f"{category}: pooled report absent")
            continue
        expected = category_expected[category]
        aggregate_requirements = {
            "bearing_doa_error": (
                "absolute_bearing_error_deg",
                expected["referenced_nonabstained"],
            ),
            "candidate_bearing": (
                "candidate_count",
                expected["referenced_nonabstained"],
            ),
            "capture_to_frame_latency": (
                "capture_to_frame_offline_ms",
                expected["windows"],
            ),
            "confidence": ("confidence", expected["windows"]),
            "frame_to_adapter_latency": (
                "frame_to_adapter_round_trip_ms",
                expected["windows"],
            ),
        }
        for metric, (field, count) in aggregate_requirements.items():
            stats = pooled.get(field)
            require(
                metric,
                isinstance(stats, Mapping) and stats.get("count") == count,
                f"{category}: {field} count is incomplete",
            )
        least_squares = pooled.get("least_squares_bearing_deg")
        least_squares_missing = pooled.get("least_squares_missing_count")
        require(
            "bearing_doa_error",
            isinstance(least_squares, Mapping)
            and isinstance(least_squares_missing, int)
            and least_squares.get("count") + least_squares_missing
            == expected["referenced_nonabstained"],
            f"{category}: least-squares result/missing count is incomplete",
        )
        nearest = pooled.get("nearest_candidate_error_deg")
        require(
            "candidate_bearing",
            isinstance(nearest, Mapping)
            and nearest.get("count") == expected["referenced_nonabstained"],
            f"{category}: nearest-candidate error count is incomplete",
        )
        coverage_counts = pooled.get("candidate_coverage_counts")
        require(
            "candidate_bearing",
            isinstance(coverage_counts, Mapping)
            and coverage_counts.get("denominator") == expected["referenced"]
            and coverage_counts.get("abstained_uncovered")
            == expected["referenced"] - expected["referenced_nonabstained"],
            f"{category}: candidate coverage denominator is incomplete",
        )
        sector_counts = pooled.get("sector_accuracy_counts")
        require(
            "sector_accuracy",
            isinstance(sector_counts, Mapping)
            and sector_counts.get("denominator") == expected["referenced"]
            and sector_counts.get("abstained_incorrect")
            == expected["referenced"] - expected["referenced_nonabstained"],
            f"{category}: sector denominator is incomplete",
        )
        ambiguity_counts = pooled.get("ambiguity_counts")
        require(
            "ambiguity",
            isinstance(ambiguity_counts, Mapping)
            and sum(int(value) for value in ambiguity_counts.values())
            == expected["windows"],
            f"{category}: ambiguity counts are incomplete",
        )
        abstention_rate = pooled.get("abstention_rate")
        require(
            "abstention",
            isinstance(abstention_rate, (int, float))
            and math.isclose(
                float(abstention_rate),
                (expected["windows"] - expected["nonabstained"]) / expected["windows"],
                abs_tol=1e-15,
            ),
            f"{category}: abstention rate/count is incomplete",
        )
        for metric, field, keys, count in (
            ("tdoa", "tdoa_us", nonself_pairs, expected["active_nonabstained"]),
            (
                "relative_channel_delay",
                "relative_channel_delay_us",
                raw_set,
                expected["active_nonabstained"],
            ),
            (
                "major_polarity_anomaly",
                "aligned_pair_correlation",
                unique_pairs,
                expected["active_nonabstained"],
            ),
            (
                "relative_rms_level",
                "per_channel_rms_full_scale",
                raw_set,
                expected["windows"],
            ),
            (
                "combined_spectrum",
                "combined_spectrum_relative_db",
                band_set,
                expected["windows"],
            ),
            (
                "channel_imbalance",
                "per_channel_relative_rms_db",
                raw_set,
                expected["active_nonabstained"],
            ),
        ):
            grouped = pooled.get(field)
            require(
                metric,
                isinstance(grouped, Mapping)
                and set(grouped) == keys
                and all(
                    isinstance(stats, Mapping) and stats.get("count") == count
                    for stats in grouped.values()
                ),
                f"{category}: {field} per-key evidence incomplete",
            )
        expected_error_count = expected["referenced_nonabstained"]
        grouped_error = pooled.get("tdoa_error_us")
        require(
            "tdoa",
            isinstance(grouped_error, Mapping)
            and set(grouped_error) == nonself_pairs
            and all(
                isinstance(stats, Mapping)
                and stats.get("count") == expected_error_count
                for stats in grouped_error.values()
            ),
            f"{category}: tdoa_error_us per-pair evidence incomplete",
        )

    attempt_count = sum(
        len(entry.get("attempts", [])) for entry in inventory.get("trials", [])
    )
    require(
        "channel_presence_order_health",
        len(channel_evidence) == attempt_count,
        "attempt-level channel evidence count is incomplete",
    )
    channel_by_attempt = {
        str(record.get("attempt_id")): record for record in channel_evidence
    }
    for entry in inventory.get("trials", []):
        for attempt in entry.get("attempts", []):
            attempt_id = str(attempt.get("attempt_id"))
            record = channel_by_attempt.get(attempt_id)
            require(
                "channel_presence_order_health",
                isinstance(record, Mapping),
                f"{attempt_id}: channel evidence absent",
            )
            if not isinstance(record, Mapping):
                continue
            status = record.get("status")
            require(
                "channel_presence_order_health",
                status in {"passed", "failed", "not_applicable_before_capture"},
                f"{attempt_id}: channel evidence status invalid",
            )
            if status != "not_applicable_before_capture":
                channels = record.get("channels")
                require(
                    "channel_presence_order_health",
                    isinstance(channels, list)
                    and len(channels) == len(configuration["audio"]["channel_order"])
                    and all(
                        set(
                            (
                                "channel_index",
                                "channel_id",
                                "present",
                                "healthy",
                                "rms_pcm16",
                                "peak_pcm16",
                                "maximum_clip_run_samples",
                                "sustained_clipping",
                            )
                        )
                        <= set(channel)
                        for channel in channels
                    ),
                    (
                        f"{attempt_id}: per-channel presence/health/clip summaries "
                        "incomplete"
                    ),
                )
                if attempt.get("outcome") == "accepted":
                    require(
                        "channel_presence_order_health",
                        status == "passed",
                        f"{attempt_id}: accepted attempt channel health failed",
                    )

    expected_noise_ids = {
        trial_id
        for trial_id in accepted_trial_ids
        if definitions[trial_id].get("stimulus") == "silence"
        or "mac_reference" in str(definitions[trial_id].get("stimulus"))
    }
    measured_noise = {
        str(record.get("trial_id")): record
        for record in noise_transient_results
        if record.get("status") == "measured"
    }
    require(
        "noise",
        set(measured_noise) == expected_noise_ids,
        "noise-transient results are absent for applicable trials",
    )
    corrective_noise = (
        configuration.get("configuration_source", {}).get("schema")
        == CORRECTIVE_CONFIG_SCHEMA
    )
    prospective_trial_id = (
        configuration.get("corrective_provenance", {})
        .get("prospective_transient_event_contract", {})
        .get("prospective_evidence_trial_id")
    )
    if corrective_noise:
        require(
            "noise",
            isinstance(prospective_trial_id, str)
            and prospective_trial_id in measured_noise,
            "required prospective silence evidence is absent",
        )
    for trial_id, record in measured_noise.items():
        if not corrective_noise:
            require(
                "noise",
                isinstance(record.get("transient_count"), int)
                and isinstance(record.get("transient_rate_per_s"), (int, float))
                and record.get("window_count", 0) > 0
                and set(record.get("per_channel_rms_full_scale", {})) == raw_set
                and set(record.get("combined_spectrum_relative_db", {})) == band_set,
                f"{trial_id}: historical noise output incomplete",
            )
            continue
        legacy = record.get("legacy_overlapping_window_rms_exceedance")
        legacy_distinct = record.get("legacy_distinct_event_rate")
        prospective = record.get("prospective_distinct_transient_events")
        require(
            "noise",
            record.get("schema") == "ias.s4_3.noise_characterization.v2"
            and isinstance(legacy, Mapping)
            and legacy.get("metric_id")
            == "legacy_overlapping_window_rms_exceedance_rate"
            and isinstance(legacy.get("exceedance_window_count"), int)
            and isinstance(legacy.get("exceedance_rate_per_s"), (int, float))
            and isinstance(legacy_distinct, Mapping)
            and legacy_distinct.get("status") == "unmeasured"
            and legacy_distinct.get("classification") == "Unmeasured"
            and record.get("window_count", 0) > 0
            and set(record.get("per_channel_rms_full_scale", {})) == raw_set
            and set(record.get("combined_spectrum_relative_db", {})) == band_set,
            (
                f"{trial_id}: legacy noise/channel/spectrum output incomplete "
                "or mislabeled"
            ),
        )
        require(
            "noise",
            isinstance(prospective_trial_id, str),
            "prospective transient detector provenance or evidence trial is absent",
        )
        if trial_id == prospective_trial_id:
            require(
                "noise",
                isinstance(prospective, Mapping)
                and prospective.get("status") == "measured"
                and prospective.get("metric_id")
                == "prospective_deduplicated_transient_event_rate"
                and isinstance(prospective.get("event_count"), int)
                and isinstance(prospective.get("event_rate_per_s"), (int, float))
                and prospective.get("detector_window_overlap_dependency") == "none"
                and prospective.get("contract_sha256")
                == configuration["corrective_provenance"][
                    "prospective_transient_event_contract"
                ]["sha256"],
                f"{trial_id}: prospective transient-event evidence incomplete",
            )
        else:
            require(
                "noise",
                isinstance(prospective, Mapping)
                and prospective.get("status") == "unmeasured",
                (
                    f"{trial_id}: inspected legacy data must not confirm "
                    "prospective events"
                ),
            )

    silence = analyses_by_id.get("s4_3_rob_silence_01")
    require(
        "silence",
        isinstance(silence, Mapping)
        and bool(silence.get("windows"))
        and all(bool(window.get("abstained")) for window in silence.get("windows", [])),
        "silence trial abstention evidence absent",
    )
    robustness = category_reports.get("robustness", {})
    conditions = robustness.get("condition_deltas", {}).get("conditions", [])
    condition_ids = {
        str(condition.get("trial_id"))
        for condition in conditions
        if isinstance(condition, Mapping)
    }
    require(
        "occlusion",
        "s4_3_rob_occluded_01" in condition_ids,
        "occlusion paired delta absent",
    )
    require(
        "overlap",
        "s4_3_rob_overlap_01" in condition_ids,
        "overlap paired delta absent",
    )

    nonaccepted = [
        attempt
        for entry in inventory.get("trials", [])
        for attempt in entry.get("attempts", [])
        if attempt.get("outcome") != "accepted"
    ]
    require(
        "acquisition_analysis_failures",
        failure_report.get("failure_count") == len(nonaccepted)
        and len(failure_report.get("failures", [])) == len(nonaccepted)
        and failure_report.get("all_failures_retained") is True,
        "failure inventory is incomplete",
    )

    av = coarse_audio_video_association
    require(
        "coarse_audio_video_association",
        isinstance(av, Mapping)
        and av.get("schema") == "ias.s4_3.coarse_audio_video_association.v1"
        and av.get("status") == "passed"
        and av.get("event_audible") is True
        and av.get("event_visible") is True
        and av.get("event_unique") is True
        and all(
            isinstance(av.get(field), (int, float)) and math.isfinite(float(av[field]))
            for field in (
                "audio_event_sample_index",
                "audio_sample_rate_hz",
                "zed_event_frame_index",
                "zed_event_timestamp_ns",
                "offset_s",
                "total_uncertainty_ms",
                "maximum_uncertainty_ms",
            )
        )
        and float(av.get("total_uncertainty_ms", math.inf))
        <= float(av.get("maximum_uncertainty_ms", -math.inf)),
        "coarse audio-video association output absent or invalid",
    )
    require(
        "coarse_audio_video_association",
        isinstance(svo_replay, Mapping)
        and svo_replay.get("status") == "passed"
        and svo_replay.get("end_of_svo_reached") is True
        and svo_replay.get("declared_frame_count")
        == svo_replay.get("replayed_frame_count"),
        "complete SVO2 replay evidence absent",
    )

    records = {
        metric: {
            "contract_present": isinstance(contracts.get(metric), Mapping),
            "status": "passed" if not issues[metric] else "failed",
            "required_outputs_verified": not issues[metric],
            "issues": issues[metric],
            "reports": [
                "reports/repeatability.json",
                "reports/controlled.json",
                "reports/robustness.json",
            ],
        }
        for metric in sorted(metric_names)
    }
    return {
        "schema": "ias.s4_3.evidence_coverage.v2",
        "status": (
            "passed"
            if records and all(item["status"] == "passed" for item in records.values())
            else "failed"
        ),
        "metric_contract_count": len(contracts),
        "metric_contracts": records,
        "planned_trial_count": inventory.get("planned_trial_count"),
        "terminal_trial_count": inventory.get("terminal_trial_count"),
        "accepted_analysis_count": len(analyses),
        "attempt_channel_evidence_count": len(channel_evidence),
        "noise_transient_result_count": len(noise_transient_results),
        "s4_4_content_present": False,
    }
