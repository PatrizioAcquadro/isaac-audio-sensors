"""Shared aggregation service for import-safe Isaac validation checks."""

from __future__ import annotations

from collections.abc import Iterable

from .checks import (
    ValidationState,
    check_abs_prim_path,
    check_array_attach_target_exists,
    check_array_geometry,
    check_array_local_offset_values,
    check_array_local_orientation_values,
    check_array_orientation_values,
    check_array_pose_editable,
    check_array_position_values,
    check_attach_target,
    check_attached_array_target,
    check_attached_source_target,
    check_config_schema_version,
    check_layout,
    check_object_profile_mapping_known,
    check_object_profile_mappings_mapping,
    check_object_profile_mappings_non_empty,
    check_object_profile_mappings_present,
    check_profile_labels,
    check_profile_match,
    check_rig_profile_config_container,
    check_rig_profile_id_known,
    check_rig_profile_id_present,
    check_rig_profile_library_present,
    check_rig_profile_library_sequence,
    check_room_anchor_exists,
    check_runtime_state,
    check_selection,
    check_sound_profile_config_container,
    check_sound_profile_id_known,
    check_sound_profile_id_present,
    check_sound_profile_library_present,
    check_sound_profile_library_sequence,
    check_source_attach_target_exists,
    check_source_geometry,
    check_source_local_offset_values,
    check_source_metadata,
    check_source_position_preset,
    check_source_position_values,
    check_stage_present,
)
from .results import ValidationReport


class ValidationController:
    """Aggregate pure checks for GUI and headless workflows.

    Stage-shaped facts are supplied per call, so this service retains no live
    USD handles. Capability-state refresh is intentionally left as the seam for
    S2.6 Run B; this Run A service has no discovery state or constructor inputs.
    """

    def validate_runtime(self, state: ValidationState) -> ValidationReport:
        return ValidationReport(check_runtime_state(state))

    def validate_source_metadata(self, state: ValidationState) -> ValidationReport:
        return ValidationReport(check_source_metadata(state))

    def validate_array_geometry(self, state: ValidationState) -> ValidationReport:
        return ValidationReport(check_array_geometry(state))

    def validate_source_geometry(self, state: ValidationState) -> ValidationReport:
        return ValidationReport(check_source_geometry(state))

    def validate_layout(self, state: ValidationState) -> ValidationReport:
        return ValidationReport(check_layout(state))

    def validate_array_pose_editable(self, attached: bool) -> ValidationReport:
        return ValidationReport(check_array_pose_editable(attached))

    def validate_source_position_preset(self, preset: str) -> ValidationReport:
        return ValidationReport(check_source_position_preset(preset))

    def validate_profile_labels(self, labels: Iterable[str]) -> ValidationReport:
        return ValidationReport(check_profile_labels(labels))

    def validate_profile_match(
        self,
        labels: Iterable[str],
        profile_id: str | None,
    ) -> ValidationReport:
        return ValidationReport(check_profile_match(labels, profile_id))

    def validate_room_anchor_exists(
        self,
        anchor_path: str,
        exists: bool,
    ) -> ValidationReport:
        return ValidationReport(check_room_anchor_exists(anchor_path, exists))

    def validate_config_schema_version(self, value: object) -> ValidationReport:
        return ValidationReport(check_config_schema_version(value))

    def validate_object_profile_mapping_known(
        self,
        label: str,
        profile_id: str,
        known: bool,
        *,
        config: bool = False,
    ) -> ValidationReport:
        return ValidationReport(
            check_object_profile_mapping_known(
                label,
                profile_id,
                known,
                config=config,
            )
        )

    def validate_sound_profile_id_present(self, requested: str) -> ValidationReport:
        return ValidationReport(check_sound_profile_id_present(requested))

    def validate_sound_profile_id_known(
        self,
        requested: str,
        known: bool,
        *,
        config: bool = False,
    ) -> ValidationReport:
        return ValidationReport(
            check_sound_profile_id_known(requested, known, config=config)
        )

    def validate_rig_profile_id_present(self, requested: str) -> ValidationReport:
        return ValidationReport(check_rig_profile_id_present(requested))

    def validate_rig_profile_id_known(
        self,
        requested: str,
        known: bool,
        *,
        config: bool = False,
    ) -> ValidationReport:
        return ValidationReport(
            check_rig_profile_id_known(requested, known, config=config)
        )

    def validate_sound_profile_config_container(
        self,
        is_mapping: bool,
    ) -> ValidationReport:
        return ValidationReport(check_sound_profile_config_container(is_mapping))

    def validate_sound_profile_library_present(
        self,
        present: bool,
    ) -> ValidationReport:
        return ValidationReport(check_sound_profile_library_present(present))

    def validate_object_profile_mappings_present(
        self,
        present: bool,
    ) -> ValidationReport:
        return ValidationReport(check_object_profile_mappings_present(present))

    def validate_object_profile_mappings_mapping(
        self,
        is_mapping: bool,
    ) -> ValidationReport:
        return ValidationReport(check_object_profile_mappings_mapping(is_mapping))

    def validate_sound_profile_library_sequence(
        self,
        is_sequence: bool,
    ) -> ValidationReport:
        return ValidationReport(check_sound_profile_library_sequence(is_sequence))

    def validate_object_profile_mappings_non_empty(
        self,
        non_empty: bool,
    ) -> ValidationReport:
        return ValidationReport(check_object_profile_mappings_non_empty(non_empty))

    def validate_rig_profile_config_container(
        self,
        is_mapping: bool,
    ) -> ValidationReport:
        return ValidationReport(check_rig_profile_config_container(is_mapping))

    def validate_rig_profile_library_present(
        self,
        present: bool,
    ) -> ValidationReport:
        return ValidationReport(check_rig_profile_library_present(present))

    def validate_rig_profile_library_sequence(
        self,
        is_sequence: bool,
    ) -> ValidationReport:
        return ValidationReport(check_rig_profile_library_sequence(is_sequence))

    def validate_abs_prim_path(
        self,
        value: str,
        field_name: str,
    ) -> ValidationReport:
        return ValidationReport(check_abs_prim_path(value, field_name))

    def validate_stage_present(self, stage_is_open: bool) -> ValidationReport:
        return ValidationReport(check_stage_present(stage_is_open))

    def validate_selection(
        self,
        selection_path: str | None,
        exists: bool,
    ) -> ValidationReport:
        return ValidationReport(check_selection(selection_path, exists))

    def validate_attach_target(
        self,
        source_path: str,
        target_path: str,
        *,
        kind: str = "source",
    ) -> ValidationReport:
        return ValidationReport(
            check_attach_target(source_path, target_path, kind=kind)
        )

    def validate_source_attach_target_exists(
        self,
        target_path: str,
        exists: bool,
    ) -> ValidationReport:
        return ValidationReport(check_source_attach_target_exists(target_path, exists))

    def validate_array_attach_target_exists(
        self,
        target_path: str,
        exists: bool,
    ) -> ValidationReport:
        return ValidationReport(check_array_attach_target_exists(target_path, exists))

    def validate_attached_source_target(
        self,
        attached: bool,
        target_path: str,
        exists: bool | None,
    ) -> ValidationReport:
        return ValidationReport(
            check_attached_source_target(attached, target_path, exists)
        )

    def validate_attached_array_target(
        self,
        attached: bool,
        target_path: str,
        exists: bool | None,
    ) -> ValidationReport:
        return ValidationReport(
            check_attached_array_target(attached, target_path, exists)
        )

    def validate_source_position_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_source_position_values(values))

    def validate_source_local_offset_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_source_local_offset_values(values))

    def validate_array_position_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_array_position_values(values))

    def validate_array_orientation_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_array_orientation_values(values))

    def validate_array_local_offset_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_array_local_offset_values(values))

    def validate_array_local_orientation_values(
        self,
        values: Iterable[float],
    ) -> ValidationReport:
        return ValidationReport(check_array_local_orientation_values(values))


__all__ = ["ValidationController"]
