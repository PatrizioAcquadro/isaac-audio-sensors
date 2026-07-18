"""Pure validation checks for GUI and headless Isaac workflows.

This module intentionally imports no Omniverse, Isaac extension, USD, tensor,
or capability-discovery modules. State arguments are structural: an
``ExtensionUiState`` instance works, as does any plain object exposing the
fields used by a check.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Protocol

from .results import ValidationFinding

_BACKEND_CHOICES = (
    "geometry_only",
    "tdoa_synthetic",
    "room_acoustics",
    "room_acoustics_srp",
)
_AMBIGUITY_POLICY_CHOICES = ("front_hemisphere", "none")
_LAYOUT_CHOICES = (
    "quad_front",
    "quad_cross",
    "tetrahedral",
    "stereo_y",
    "two_mic_y",
    "mono",
)


class ValidationState(Protocol):
    """Structural subset of ``ExtensionUiState`` consumed by the checks."""

    backend: str
    ambiguity_policy: str
    update_period_s: float
    max_events: int
    array_prim_path: str
    robot_base_prim_path: str
    audio_asset_path: str
    source_directivity: str
    source_start_time_s: float
    source_duration_s: float
    source_gain_db: float
    source_position_x_m: float
    source_position_y_m: float
    source_position_z_m: float
    source_local_offset_x_m: float
    source_local_offset_y_m: float
    source_local_offset_z_m: float
    array_position_x_m: float
    array_position_y_m: float
    array_position_z_m: float
    array_roll_deg: float
    array_pitch_deg: float
    array_yaw_deg: float
    array_local_offset_x_m: float
    array_local_offset_y_m: float
    array_local_offset_z_m: float
    array_local_roll_deg: float
    array_local_pitch_deg: float
    array_local_yaw_deg: float
    layout_name: str
    sample_rate_hz: int
    device_id: str
    compute_device: str
    calibration_profile_path: str


def _error(
    check_id: str,
    message: str,
    field: str | None = None,
) -> tuple[ValidationFinding, ...]:
    return (
        ValidationFinding(
            check_id=check_id,
            severity="error",
            message=message,
            field=field,
        ),
    )


def _path_check_id(field_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", field_name.strip().lower()).strip("_")
    return f"{normalized or 'prim_path'}_absolute"


def check_abs_prim_path(
    value: str,
    field_name: str,
) -> tuple[ValidationFinding, ...]:
    """Check the controller's established absolute-USD-path predicate."""

    if not value.strip() or not value.startswith("/"):
        return _error(
            _path_check_id(field_name),
            f"{field_name} must be an absolute USD prim path.",
            field_name,
        )
    return ()


def check_runtime_state(state: ValidationState) -> tuple[ValidationFinding, ...]:
    """Check runtime configuration in the controller's fail-first order."""

    if state.backend not in _BACKEND_CHOICES:
        return _error(
            "backend_supported",
            f"Backend {state.backend!r} is not an implemented v1 backend.",
            "backend",
        )
    if state.ambiguity_policy not in _AMBIGUITY_POLICY_CHOICES:
        return _error(
            "ambiguity_policy_supported",
            f"Ambiguity policy {state.ambiguity_policy!r} is not supported.",
            "ambiguity_policy",
        )
    if state.update_period_s <= 0.0 or not math.isfinite(state.update_period_s):
        return _error(
            "update_period_positive_finite",
            "update_period_s must be positive and finite.",
            "update_period_s",
        )
    if state.max_events < 0:
        return _error(
            "max_events_non_negative",
            "max_events must be non-negative.",
            "max_events",
        )
    if state.array_prim_path.strip():
        findings = check_abs_prim_path(state.array_prim_path, "array_prim_path")
        if findings:
            return findings
    if state.robot_base_prim_path.strip():
        return check_abs_prim_path(
            state.robot_base_prim_path,
            "robot_base_prim_path",
        )
    return ()


def check_backend_available(
    backend_id: str,
    available_backend_ids: Iterable[str],
    *,
    actionable_message: str = "",
) -> tuple[ValidationFinding, ...]:
    """Check dependency-backed availability for an implemented backend."""

    if backend_id in available_backend_ids:
        return ()
    message = f"Backend {backend_id!r} is unavailable in the current capability state."
    if actionable_message:
        message = f"{message} {actionable_message}"
    return _error("backend_available", message, "backend")


def check_device_supported(
    backend_id: str,
    device: str,
    supported_devices: Iterable[str],
) -> tuple[ValidationFinding, ...]:
    """Check an explicit compute-device choice against a backend declaration."""

    requested = device.strip()
    if not requested:
        return _error(
            "compute_device_non_empty",
            "compute_device must be non-empty.",
            "compute_device",
        )
    supported = tuple(supported_devices)
    if not supported or requested in supported:
        return ()
    return _error(
        "backend_device_supported",
        f"Backend {backend_id!r} does not support device {requested!r}; "
        f"supported devices: {list(supported)}.",
        "compute_device",
    )


def check_calibration_profile(
    profile_path: str,
    *,
    read_error: str | None = None,
    compatibility_error: str | None = None,
) -> tuple[ValidationFinding, ...]:
    """Convert fresh calibration load/compatibility facts into stable findings."""

    if not profile_path.strip():
        return ()
    if read_error is not None:
        return _error(
            "calibration_profile_readable",
            f"Calibration profile {profile_path!r} cannot be loaded: {read_error}",
            "calibration_profile_path",
        )
    if compatibility_error is not None:
        return _error(
            "calibration_profile_compatible",
            f"Calibration profile {profile_path!r} is incompatible: "
            f"{compatibility_error}",
            "calibration_profile_path",
        )
    return ()


def check_source_metadata(state: ValidationState) -> tuple[ValidationFinding, ...]:
    """Check source metadata and timing in established fail-first order."""

    if state.audio_asset_path.strip() == "":
        return _error(
            "audio_asset_path_non_empty",
            "audio_asset_path must be non-empty.",
            "audio_asset_path",
        )
    if state.source_directivity.strip() == "":
        return _error(
            "source_directivity_non_empty",
            "source_directivity must be non-empty.",
            "source_directivity",
        )
    for field_name, value in (
        ("source_start_time_s", state.source_start_time_s),
        ("source_duration_s", state.source_duration_s),
        ("source_gain_db", state.source_gain_db),
    ):
        if not math.isfinite(float(value)):
            return _error(
                f"{field_name.removesuffix('_s')}_finite",
                f"{field_name} must be finite.",
                field_name,
            )
    if state.source_duration_s <= 0.0:
        return _error(
            "source_duration_positive",
            "source_duration_s must be positive.",
            "source_duration_s",
        )
    return ()


def _check_finite_values(
    values: Iterable[float],
    *,
    check_id: str,
    message: str,
    field: str,
) -> tuple[ValidationFinding, ...]:
    if not all(math.isfinite(value) for value in values):
        return _error(check_id, message, field)
    return ()


def check_source_position_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="source_position_finite",
        message="source position values must be finite.",
        field="source_position",
    )


def check_source_local_offset_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="source_local_offset_finite",
        message="source local offset values must be finite.",
        field="source_local_offset",
    )


def check_source_geometry(state: ValidationState) -> tuple[ValidationFinding, ...]:
    """Check source world and local geometry in established order."""

    position = (
        float(state.source_position_x_m),
        float(state.source_position_y_m),
        float(state.source_position_z_m),
    )
    findings = check_source_position_values(position)
    if findings:
        return findings
    offset = (
        float(state.source_local_offset_x_m),
        float(state.source_local_offset_y_m),
        float(state.source_local_offset_z_m),
    )
    return check_source_local_offset_values(offset)


def check_array_position_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="array_position_finite",
        message="array position values must be finite.",
        field="array_position",
    )


def check_array_orientation_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="array_orientation_finite",
        message="array orientation angles must be finite.",
        field="array_orientation",
    )


def check_array_local_offset_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="array_local_offset_finite",
        message="array local offset values must be finite.",
        field="array_local_offset",
    )


def check_array_local_orientation_values(
    values: Iterable[float],
) -> tuple[ValidationFinding, ...]:
    return _check_finite_values(
        values,
        check_id="array_local_orientation_finite",
        message="array local orientation angles must be finite.",
        field="array_local_orientation",
    )


def check_array_geometry(state: ValidationState) -> tuple[ValidationFinding, ...]:
    """Check array world and local geometry in established order."""

    position = (
        float(state.array_position_x_m),
        float(state.array_position_y_m),
        float(state.array_position_z_m),
    )
    findings = check_array_position_values(position)
    if findings:
        return findings
    orientation = (
        float(state.array_roll_deg),
        float(state.array_pitch_deg),
        float(state.array_yaw_deg),
    )
    findings = check_array_orientation_values(orientation)
    if findings:
        return findings
    local_offset = (
        float(state.array_local_offset_x_m),
        float(state.array_local_offset_y_m),
        float(state.array_local_offset_z_m),
    )
    findings = check_array_local_offset_values(local_offset)
    if findings:
        return findings
    local_orientation = (
        float(state.array_local_roll_deg),
        float(state.array_local_pitch_deg),
        float(state.array_local_yaw_deg),
    )
    return check_array_local_orientation_values(local_orientation)


def check_layout(state: ValidationState) -> tuple[ValidationFinding, ...]:
    """Check array layout and sample rate in established order."""

    if state.layout_name not in _LAYOUT_CHOICES:
        return _error(
            "array_layout_known",
            f"Unknown array layout {state.layout_name!r}.",
            "layout_name",
        )
    if int(state.sample_rate_hz) <= 0:
        return _error(
            "sample_rate_positive",
            "sample_rate_hz must be positive.",
            "sample_rate_hz",
        )
    return ()


def check_stage_present(stage_is_open: bool) -> tuple[ValidationFinding, ...]:
    """Check whether a USD stage-shaped input is available."""

    if not stage_is_open:
        return _error("stage_present", "No USD stage is open.")
    return ()


def check_selection(
    selection_path: str | None,
    exists: bool,
) -> tuple[ValidationFinding, ...]:
    """Check selection presence and, when present, stage existence."""

    if not selection_path:
        return _error("selection_present", "No prim is selected.")
    if not exists:
        return _error(
            "selected_object_exists",
            f"Selected object does not exist: {selection_path}.",
            "object_prim_path",
        )
    return ()


def check_attach_target(
    source_path: str,
    target_path: str,
    *,
    kind: str = "source",
) -> tuple[ValidationFinding, ...]:
    """Check that a source or array is not attached to itself."""

    if source_path != target_path:
        return ()
    if kind == "array":
        return _error(
            "array_attach_target_distinct",
            "Cannot attach an array to itself.",
            "object_prim_path",
        )
    return _error(
        "source_attach_target_distinct",
        "Cannot attach a source to itself.",
        "object_prim_path",
    )


def check_array_pose_editable(attached: bool) -> tuple[ValidationFinding, ...]:
    if attached:
        return _error(
            "array_pose_editable",
            "Array is attached to an object; edit the local offset "
            "or detach the array first.",
            "array_position",
        )
    return ()


def check_source_position_preset(preset: str) -> tuple[ValidationFinding, ...]:
    if preset.strip().lower() not in {"front", "right", "left", "behind"}:
        return _error(
            "source_position_preset_known",
            f"Unknown source position preset {preset!r}.",
            "source_position_preset",
        )
    return ()


def check_profile_labels(labels: Iterable[str]) -> tuple[ValidationFinding, ...]:
    if not tuple(labels):
        return _error(
            "profile_object_label_available",
            "No selected or attached object label is available.",
            "object_label",
        )
    return ()


def check_profile_match(
    labels: Iterable[str],
    profile_id: str | None,
) -> tuple[ValidationFinding, ...]:
    label_tuple = tuple(labels)
    if profile_id is None:
        return _error(
            "sound_profile_match_available",
            "No sound profile matches object labels: "
            + ", ".join(label_tuple)
            + ".",
            "selected_profile_id",
        )
    return ()


def check_room_anchor_exists(
    anchor_path: str,
    exists: bool,
) -> tuple[ValidationFinding, ...]:
    if not exists:
        return _error(
            "room_anchor_exists",
            f"Room anchor prim not found at {anchor_path!r}.",
            "room_anchor_prim_path",
        )
    return ()


def check_config_schema_version(value: object) -> tuple[ValidationFinding, ...]:
    if value != "ias.omni_extension_binding.v1":
        return _error(
            "config_schema_version_supported",
            "Config import requires schema_version "
            "'ias.omni_extension_binding.v1'.",
            "schema_version",
        )
    return ()


def check_object_profile_mapping_known(
    label: str,
    profile_id: str,
    known: bool,
    *,
    config: bool = False,
) -> tuple[ValidationFinding, ...]:
    if known:
        return ()
    if config:
        return _error(
            "config_object_profile_mapping_known",
            "sound_profiles.object_profile_mappings "
            f"{label!r} references unknown profile {profile_id!r}.",
            "object_profile_mappings",
        )
    return _error(
        "object_profile_mapping_known",
        "Object profile mapping "
        f"{label!r} references unknown profile {profile_id!r}.",
        "object_profile_mappings",
    )


def check_sound_profile_id_present(requested: str) -> tuple[ValidationFinding, ...]:
    if not requested:
        return _error(
            "selected_profile_id_non_empty",
            "selected_profile_id must be non-empty.",
            "selected_profile_id",
        )
    return ()


def check_sound_profile_id_known(
    requested: str,
    known: bool,
    *,
    config: bool = False,
) -> tuple[ValidationFinding, ...]:
    if known or (config and not requested):
        return ()
    if config:
        return _error(
            "config_selected_sound_profile_known",
            f"Unknown selected sound profile id {requested!r}.",
            "selected_profile_id",
        )
    return _error(
        "sound_profile_id_known",
        f"Unknown sound profile id {requested!r}.",
        "selected_profile_id",
    )


def check_rig_profile_id_present(requested: str) -> tuple[ValidationFinding, ...]:
    if not requested:
        return _error(
            "selected_rig_profile_id_non_empty",
            "selected_rig_profile_id must be non-empty.",
            "selected_rig_profile_id",
        )
    return ()


def check_rig_profile_id_known(
    requested: str,
    known: bool,
    *,
    config: bool = False,
) -> tuple[ValidationFinding, ...]:
    if known or (config and not requested):
        return ()
    if config:
        return _error(
            "config_selected_rig_profile_known",
            f"Unknown selected rig profile id {requested!r}.",
            "selected_rig_profile_id",
        )
    return _error(
        "rig_profile_id_known",
        f"Unknown rig profile id {requested!r}.",
        "selected_rig_profile_id",
    )


def check_sound_profile_config_container(
    is_mapping: bool,
) -> tuple[ValidationFinding, ...]:
    if not is_mapping:
        return _error(
            "sound_profiles_config_object",
            "sound_profiles config must be an object.",
            "sound_profiles",
        )
    return ()


def check_sound_profile_library_present(
    present: bool,
) -> tuple[ValidationFinding, ...]:
    if not present:
        return _error(
            "sound_profile_library_present",
            "sound_profiles.profile_library is required when profiles are present.",
            "profile_library",
        )
    return ()


def check_object_profile_mappings_present(
    present: bool,
) -> tuple[ValidationFinding, ...]:
    if not present:
        return _error(
            "object_profile_mappings_present",
            "sound_profiles.object_profile_mappings is required when "
            "profiles are present.",
            "object_profile_mappings",
        )
    return ()


def check_object_profile_mappings_mapping(
    is_mapping: bool,
) -> tuple[ValidationFinding, ...]:
    if not is_mapping:
        return _error(
            "object_profile_mappings_object",
            "sound_profiles.object_profile_mappings must be an object.",
            "object_profile_mappings",
        )
    return ()


def check_sound_profile_library_sequence(
    is_sequence: bool,
) -> tuple[ValidationFinding, ...]:
    if not is_sequence:
        return _error(
            "sound_profile_library_sequence",
            "sound_profiles.profile_library must be a list of profile objects.",
            "profile_library",
        )
    return ()


def check_object_profile_mappings_non_empty(
    non_empty: bool,
) -> tuple[ValidationFinding, ...]:
    if not non_empty:
        return _error(
            "object_profile_mappings_non_empty",
            "sound_profiles.object_profile_mappings must not be empty.",
            "object_profile_mappings",
        )
    return ()


def check_rig_profile_config_container(
    is_mapping: bool,
) -> tuple[ValidationFinding, ...]:
    if not is_mapping:
        return _error(
            "rig_profiles_config_object",
            "microphone_rig_profiles config must be an object.",
            "microphone_rig_profiles",
        )
    return ()


def check_rig_profile_library_present(
    present: bool,
) -> tuple[ValidationFinding, ...]:
    if not present:
        return _error(
            "rig_profile_library_present",
            "microphone_rig_profiles.rig_library is required when rig "
            "profiles are present.",
            "rig_library",
        )
    return ()


def check_rig_profile_library_sequence(
    is_sequence: bool,
) -> tuple[ValidationFinding, ...]:
    if not is_sequence:
        return _error(
            "rig_profile_library_sequence",
            "microphone_rig_profiles.rig_library must be a list of profile objects.",
            "rig_library",
        )
    return ()


def check_source_attach_target_exists(
    target_path: str,
    exists: bool,
) -> tuple[ValidationFinding, ...]:
    if not exists:
        return _error(
            "source_attach_target_exists",
            f"Selected object no longer exists: {target_path}.",
            "object_prim_path",
        )
    return ()


def check_array_attach_target_exists(
    target_path: str,
    exists: bool,
) -> tuple[ValidationFinding, ...]:
    if not exists:
        return _error(
            "array_attach_target_exists",
            f"Selected mount prim no longer exists: {target_path}.",
            "object_prim_path",
        )
    return ()


def check_attached_source_target(
    attached: bool,
    target_path: str,
    exists: bool | None,
) -> tuple[ValidationFinding, ...]:
    if not attached:
        return ()
    if not target_path:
        return _error(
            "attached_source_target_configured",
            "Source is marked attached but no object path is configured.",
            "attached_object_prim_path",
        )
    if exists is False:
        return _error(
            "attached_source_target_exists",
            f"Attached object no longer exists: {target_path}. "
            "Select another object or detach the source.",
            "attached_object_prim_path",
        )
    return ()


def check_attached_array_target(
    attached: bool,
    target_path: str,
    exists: bool | None,
) -> tuple[ValidationFinding, ...]:
    if not attached:
        return ()
    if not target_path:
        return _error(
            "attached_array_target_configured",
            "Array is marked attached but no mount path is configured.",
            "attached_array_object_prim_path",
        )
    if exists is False:
        return _error(
            "attached_array_target_exists",
            f"Attached array mount no longer exists: {target_path}. "
            "Select another mount or detach the array.",
            "attached_array_object_prim_path",
        )
    return ()


__all__ = [
    "ValidationState",
    "check_abs_prim_path",
    "check_backend_available",
    "check_array_pose_editable",
    "check_array_attach_target_exists",
    "check_array_geometry",
    "check_array_local_offset_values",
    "check_array_local_orientation_values",
    "check_array_orientation_values",
    "check_array_position_values",
    "check_attach_target",
    "check_attached_array_target",
    "check_attached_source_target",
    "check_config_schema_version",
    "check_calibration_profile",
    "check_device_supported",
    "check_layout",
    "check_object_profile_mapping_known",
    "check_object_profile_mappings_mapping",
    "check_object_profile_mappings_non_empty",
    "check_object_profile_mappings_present",
    "check_profile_labels",
    "check_profile_match",
    "check_rig_profile_config_container",
    "check_rig_profile_id_known",
    "check_rig_profile_id_present",
    "check_rig_profile_library_present",
    "check_rig_profile_library_sequence",
    "check_room_anchor_exists",
    "check_runtime_state",
    "check_selection",
    "check_source_attach_target_exists",
    "check_source_geometry",
    "check_source_local_offset_values",
    "check_source_metadata",
    "check_source_position_preset",
    "check_source_position_values",
    "check_sound_profile_config_container",
    "check_sound_profile_id_known",
    "check_sound_profile_id_present",
    "check_sound_profile_library_present",
    "check_sound_profile_library_sequence",
    "check_stage_present",
]
