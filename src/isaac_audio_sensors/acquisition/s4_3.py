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
PREREGISTRATION_SCHEMA = "ias.s4_3.preregistration.v1"
ANALYSIS_SCHEMA = "ias.s4_3.trial_analysis.v1"
INVENTORY_SCHEMA = "ias.s4_3.trial_inventory.v1"
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
                "camera_firmware_matches": version_comparisons[
                    "camera_firmware"
                ],
                "sensor_firmware_matches": version_comparisons[
                    "sensor_firmware"
                ],
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
            for earlier, later in zip(
                timestamps_ns, timestamps_ns[1:], strict=False
            )
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
    if isinstance(implementation_records, list):
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
    if expansion_count > expansion_contract.get("maximum_added_trials_total", -1):
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
    report["summary"] = summarize_windows(windows)
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


def summarize_windows(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate one trial without hiding abstentions or missing values."""

    detected = [frame for frame in windows if frame.get("signal_present")]
    bearing_errors = [
        float(frame["absolute_bearing_error_deg"])
        for frame in windows
        if frame.get("absolute_bearing_error_deg") is not None
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
        "confidence": _stats([float(frame["bearing_confidence"]) for frame in windows]),
        "sector_accuracy": (
            sum(bool(frame.get("sector_correct")) for frame in windows) / len(windows)
            if windows and any("sector_correct" in frame for frame in windows)
            else None
        ),
        "candidate_coverage": (
            sum(bool(frame.get("candidate_covered")) for frame in windows)
            / len(windows)
            if windows and any("candidate_covered" in frame for frame in windows)
            else None
        ),
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


def aggregate_category(
    category: str,
    analyses: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a separated category report with complete small-sample summaries."""

    selected = [report for report in analyses if report.get("category") == category]
    windows = [window for report in selected for window in report.get("windows", [])]
    channel_rms: dict[str, list[float]] = {}
    channel_relative: dict[str, list[float]] = {}
    spectral: dict[str, list[float]] = {}
    tdoa_us: dict[str, list[float]] = {}
    delays_us: dict[str, list[float]] = {}
    polarity: dict[str, list[float]] = {}
    for window in windows:
        for key, value in window.get("per_channel_rms_full_scale", {}).items():
            channel_rms.setdefault(key, []).append(float(value))
        for key, value in window.get("per_channel_relative_rms_db", {}).items():
            channel_relative.setdefault(key, []).append(float(value))
        for key, value in window.get("combined_spectrum_relative_db", {}).items():
            spectral.setdefault(key, []).append(float(value))
        for key, value in window.get("tdoa_s", {}).items():
            if key.split("->")[0] != key.split("->")[1]:
                tdoa_us.setdefault(key, []).append(float(value) * 1e6)
        for key, value in window.get("relative_channel_delay_s", {}).items():
            delays_us.setdefault(key, []).append(float(value) * 1e6)
        for key, value in window.get("aligned_pair_correlation", {}).items():
            polarity.setdefault(key, []).append(float(value))

    inventory_trials = [
        entry for entry in inventory["trials"] if entry["category"] == category
    ]
    attempts = [attempt for entry in inventory_trials for attempt in entry["attempts"]]
    return {
        "schema": "ias.s4_3.category_report.v1",
        "category": category,
        "planned_trial_count": len(inventory_trials),
        "attempt_count": len(attempts),
        "accepted_analysis_count": len(selected),
        "outcome_counts": dict(Counter(attempt["outcome"] for attempt in attempts)),
        "trial_summaries": [
            {
                "trial_id": report["trial_id"],
                "summary": report["summary"],
                "relative_decay": report.get("relative_decay"),
                "scientific_replay_sha256": report["scientific_replay_sha256"],
            }
            for report in selected
        ],
        "pooled": {
            "window_count": len(windows),
            "bearing_deg": _stats(_group_values(windows, "srp_bearing_deg")),
            "absolute_bearing_error_deg": _stats(
                _group_values(windows, "absolute_bearing_error_deg")
            ),
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
                sum(bool(window.get("sector_correct")) for window in windows)
                / len(windows)
                if windows and any("sector_correct" in window for window in windows)
                else None
            ),
            "candidate_coverage": (
                sum(bool(window.get("candidate_covered")) for window in windows)
                / len(windows)
                if windows and any("candidate_covered" in window for window in windows)
                else None
            ),
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
    trial_bearings = [
        float(report["summary"]["bearing_deg"]["median"])
        for report in baseline
        if report["summary"]["bearing_deg"]["median"] is not None
    ]
    trial_errors = [
        float(report["summary"]["absolute_bearing_error_deg"]["median"])
        for report in baseline
        if report["summary"]["absolute_bearing_error_deg"]["median"] is not None
    ]
    sector = [
        float(report["summary"]["sector_accuracy"])
        for report in baseline
        if report["summary"]["sector_accuracy"] is not None
    ]
    candidates = [
        float(report["summary"]["candidate_coverage"])
        for report in baseline
        if report["summary"]["candidate_coverage"] is not None
    ]

    def trial_medians(field: str) -> dict[str, list[float]]:
        grouped: dict[str, list[float]] = {}
        for report in baseline:
            per_report: dict[str, list[float]] = {}
            for window in report["windows"]:
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
    checks = {
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
        "pair_tdoa_range": bool(tdoa)
        and all(
            max(values) - min(values)
            <= thresholds["pair_tdoa_trial_median_range_us_max"]
            for values in tdoa.values()
        ),
        "relative_rms_range": bool(relative_rms)
        and all(
            max(values) - min(values)
            <= thresholds["relative_rms_trial_median_range_db_max"]
            for values in relative_rms.values()
        ),
        "spectral_band_range": bool(spectrum)
        and all(
            max(values) - min(values)
            <= thresholds["spectral_band_trial_median_range_db_max"]
            for values in spectrum.values()
        ),
        "major_polarity_anomalies": sum(
            report["summary"]["major_polarity_anomaly_count"] for report in baseline
        )
        <= thresholds["major_polarity_anomaly_count_max"],
        "silence_abstention": len(silence) == 1
        and silence[0]["summary"]["abstention_rate"]
        >= thresholds["silence_abstention_rate_min"],
    }
    return {
        "schema": "ias.s4_3.repeatability_gate.v1",
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
            "silence_abstention_rate": (
                silence[0]["summary"]["abstention_rate"] if len(silence) == 1 else None
            ),
        },
        "thresholds": dict(thresholds),
    }
