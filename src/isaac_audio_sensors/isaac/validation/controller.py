"""Shared aggregation service for import-safe Isaac validation checks.

Capability discovery is intentionally cached because it imports and probes
optional dependencies. Callers must invalidate the cache when a stage is
opened, closed, or attached; when an acoustic pack is activated or deactivated;
and when backend or pack-relevant configuration changes. Invalidation is cheap:
it marks an existing snapshot stale, and the next capability-state access or
backend-availability check performs exactly one lazy refresh.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from isaac_audio_sensors.core.capabilities import (
    CapabilityReport,
    discover_capabilities,
)
from isaac_audio_sensors.core.fidelity import ACOUSTIC_FIDELITY_LADDER

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
    check_backend_available,
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


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """One immutable capability-discovery snapshot."""

    capabilities: CapabilityReport
    available_backend_ids: tuple[str, ...]
    active_pack: str | None
    captured_at_generation: int


def _available_backend_ids(report: CapabilityReport) -> tuple[str, ...]:
    available: list[str] = []
    for metadata in ACOUSTIC_FIDELITY_LADDER:
        try:
            level = report.get(metadata.level.value)
        except KeyError:
            continue
        if level.available:
            available.extend(metadata.backend_ids)
    available.extend(
        capability.capability_id
        for capability in report.capabilities
        if capability.kind == "backend" and capability.available
    )
    return tuple(dict.fromkeys(available))


class ValidationController:
    """Aggregate pure checks for GUI and headless workflows.

    Stage-shaped facts are supplied per call, so this service retains no live
    USD handles. Capability snapshots are refreshed lazily after explicit
    invalidation; a snapshot that has never been populated is an error when
    accessed directly rather than an implicit empty result.
    """

    def __init__(self) -> None:
        self._capability_state: CapabilityState | None = None
        self._capability_generation = 0
        self._capabilities_stale = False
        self._capability_invalidation_reason: str | None = None

    @property
    def capability_state(self) -> CapabilityState:
        """Return the current snapshot, lazily refreshing an invalidated one.

        Direct access before the first discovery raises clearly. Backend
        validation performs that initial discovery because it cannot answer
        availability safely without one.
        """

        if self._capability_state is None:
            raise RuntimeError(
                "Capability state has never been refreshed; call "
                "refresh_capabilities(reason) first."
            )
        if self._capabilities_stale:
            reason = self._capability_invalidation_reason or "unspecified change"
            return self.refresh_capabilities(
                f"lazy refresh after invalidation: {reason}"
            )
        return self._capability_state

    def refresh_capabilities(self, reason: str) -> CapabilityState:
        """Re-run dependency discovery and store a new generation snapshot."""

        del reason  # The reason is required at call sites to document the trigger.
        report = discover_capabilities()
        generation = self._capability_generation + 1
        snapshot = CapabilityState(
            capabilities=report,
            available_backend_ids=_available_backend_ids(report),
            active_pack=report.active_pack,
            captured_at_generation=generation,
        )
        self._capability_generation = generation
        self._capability_state = snapshot
        self._capabilities_stale = False
        self._capability_invalidation_reason = None
        return snapshot

    def invalidate(self, reason: str) -> None:
        """Mark capability state stale without performing dependency discovery."""

        self._capabilities_stale = True
        self._capability_invalidation_reason = reason

    def validate_backend_available(self, backend_id: str) -> ValidationReport:
        """Validate a backend against the current, never-stale snapshot."""

        if self._capability_state is None:
            state = self.refresh_capabilities(
                f"initial backend availability validation: {backend_id}"
            )
        else:
            state = self.capability_state
        try:
            capability = state.capabilities.get(backend_id)
        except KeyError:
            actionable_message = ""
        else:
            actionable_message = capability.actionable_message
        return ValidationReport(
            check_backend_available(
                backend_id,
                state.available_backend_ids,
                actionable_message=actionable_message,
            )
        )

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


__all__ = ["CapabilityState", "ValidationController"]
