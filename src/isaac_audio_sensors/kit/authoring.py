"""Internal authoring service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import Any

from isaac_audio_sensors.core.math_utils import (
    euler_deg_from_quaternion,
    quaternion_from_euler_deg,
)
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    prim_path,
    quat_from_any,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.stage_audio import (
    attach_array_object_binding_attrs,
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    attach_source_object_binding_attrs,
    clear_array_object_binding_attrs,
    clear_prim_attrs,
    clear_source_object_binding_attrs,
    create_sound_prim,
    get_or_define_prim,
    move_prim_to_path,
    remove_prim,
    set_prim_xform_pose,
)
from isaac_audio_sensors.kit.microphone_rig_profiles import (
    MicrophoneRigProfile,
    validate_microphone_rig_profile_library,
)
from isaac_audio_sensors.kit.sound_profiles import (
    SoundProfile,
    match_sound_profile_id,
    normalize_object_label,
    validate_sound_profile_library,
)

from ._service import ControllerService, _raise_first
from .constants import (
    SOURCE_POSITION_PRESETS,
)
from .formatting import (
    _format_vec3,
)
from .stage_context import (
    _author_orientation_arg,
    _author_position_arg,
    _discover_scene_objects,
    _get_or_define_demo_object_prim,
    _normalize_paths,
    _object_label_candidates_for_path,
    _path_name,
    _prim_attrs,
    _prim_has_xform_pose,
    _prim_type_name,
    _refresh_applied_profile_binding_snapshot,
    _set_prim_attr,
    _stage_has_prim,
    _style_demo_object_prim,
    current_omni_stage_context,
)
from .state import (
    AuthoredMetadataSummary,
    CurrentStageContext,
    DiscoveredPrimSummary,
    _json_ready,
    _jsonable_mapping,
)
from .validation.checks import (
    check_abs_prim_path,
    check_array_attach_target_exists,
    check_array_local_offset_values,
    check_array_local_orientation_values,
    check_array_orientation_values,
    check_array_pose_editable,
    check_array_position_values,
    check_attach_target,
    check_attached_array_target,
    check_attached_source_target,
    check_object_profile_mapping_known,
    check_profile_labels,
    check_profile_match,
    check_rig_profile_id_known,
    check_rig_profile_id_present,
    check_selection,
    check_sound_profile_id_known,
    check_sound_profile_id_present,
    check_source_attach_target_exists,
    check_source_local_offset_values,
    check_source_metadata,
    check_source_position_preset,
    check_source_position_values,
    check_stage_present,
)
from .validation.results import ValidationReport


class AuthoringService(ControllerService):
    """Own authoring behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)

    def refresh_stage_selection(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        """Refresh current selected prim paths from explicit args or Omni."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            self._validate_stage_present(context.stage is not None)
            self.state.selected_prim_paths = context.selected_prim_paths
            selected = ", ".join(context.selected_prim_paths) or "none"
            self.state.stage_status = f"Stage ready. Selected: {selected}"
            self._set_status("Stage selection refreshed.")
            return context.selected_prim_paths
        except Exception as exc:
            self._record_error("Stage selection failed", exc)
            return ()

    def use_selected_as_array(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the array target."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.array_prim_path = path
        self._set_status(f"Array target set to {path}.")
        return path

    def use_selected_as_source(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the source target."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.source_prim_path = path
        self._set_status(f"Source target set to {path}.")
        return path

    def use_selected_as_object(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the scene object target."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            self._validate_stage_present(context.stage is not None)
            self.state.selected_prim_paths = context.selected_prim_paths
            path = (
                context.selected_prim_paths[0] if context.selected_prim_paths else None
            )
            self._validate_selection(path, exists=True)
            assert path is not None
            self._validate_abs_path(path, "object_prim_path")
            self._validate_selection(path, exists=_stage_has_prim(context.stage, path))
            self._validate_attach_target(self.state.source_prim_path, path)
            self.state.object_prim_path = path
            self.state.object_label = _path_name(path)
            self._set_status(f"Object target set to {_path_name(path)} at {path}.")
            return path
        except Exception as exc:
            self._record_error("Object selection failed", exc)
            return None

    def create_demo_object(
        self,
        *,
        stage: Any | None = None,
        prim_path: str = "/World/Oven",
        position_world: tuple[float, float, float] = (2.0, 0.0, 0.0),
    ) -> str | None:
        """Create a minimal procedural object prim for attach workflow demos."""

        try:
            stage_obj = self._stage_or_error(stage)
            self._validate_abs_path(prim_path, "object_prim_path")
            parent = prim_path.rstrip("/").rsplit("/", 1)[0]
            if parent and parent != prim_path:
                get_or_define_prim(stage_obj, prim_path=parent, prim_type="Xform")
            prim = _get_or_define_demo_object_prim(stage_obj, prim_path)
            if not _prim_has_xform_pose(prim):
                set_prim_xform_pose(prim, position=position_world)
            _style_demo_object_prim(stage_obj, prim=prim, position_world=position_world)
            self.state.object_prim_path = prim_path
            self.state.object_label = _path_name(prim_path)
            self._set_status(
                f"Created demo object {_path_name(prim_path)} at {prim_path}."
            )
            return prim_path
        except Exception as exc:
            self._record_error("Demo object creation failed", exc)
            return None

    def read_selected_source_transform(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[float, float, float] | None:
        """Read the selected source prim's current world position into UI state."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            self._validate_stage_present(context.stage is not None)
            self.state.selected_prim_paths = context.selected_prim_paths
            selected_path = (
                context.selected_prim_paths[0]
                if context.selected_prim_paths
                else self.state.source_prim_path
            )
            self._validate_abs_path(selected_path, "source_prim_path")
            pose = IsaacStagePoseResolver(context.stage).resolve_world_pose(
                selected_path,
                field_name="selected source",
            )
            self.state.source_prim_path = selected_path
            self._set_source_position_state(pose.position_world)
            self._set_status(
                "Read source transform "
                f"{_format_vec3(pose.position_world)} from {selected_path}."
            )
            return pose.position_world
        except Exception as exc:
            self._record_error("Source transform read failed", exc)
            return None

    def read_selected_array_transform(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[float, float, float] | None:
        """Read the selected array prim's current world pose into UI state."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            self._validate_stage_present(context.stage is not None)
            self.state.selected_prim_paths = context.selected_prim_paths
            selected_path = (
                context.selected_prim_paths[0]
                if context.selected_prim_paths
                else self.state.array_prim_path
            )
            self._validate_abs_path(selected_path, "array_prim_path")
            pose = IsaacStagePoseResolver(context.stage).resolve_world_pose(
                selected_path,
                field_name="selected array",
            )
            self.state.array_prim_path = selected_path
            self._set_array_pose_state(
                pose.position_world,
                pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0),
            )
            self._set_status(
                "Read array transform "
                f"{_format_vec3(pose.position_world)} / "
                f"yaw={self.state.array_yaw_deg:.1f} deg from {selected_path}."
            )
            return pose.position_world
        except Exception as exc:
            self._record_error("Array transform read failed", exc)
            return None

    def use_selected_as_robot_base(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the robot/base frame."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.robot_base_prim_path = path
        self._set_status(f"Robot/base target set to {path}.")
        return path

    def author_array(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Create or configure array metadata on the current target prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            self._validate_abs_path(state.array_prim_path, "array_prim_path")
            prim = get_or_define_prim(
                stage_obj,
                prim_path=state.array_prim_path,
                prim_type="Xform",
            )
            record = self._author_array_on_stage(
                stage_obj,
                position_world=_author_position_arg(
                    prim,
                    default=(0.0, 0.0, 0.0),
                ),
                orientation_world_quat=_author_orientation_arg(
                    prim,
                    default=(0.0, 0.0, 0.0, 1.0),
                ),
            )
            self._append_authored_record(record)
            self._set_status(f"Authored array {record.id} at {state.array_prim_path}.")
            return record
        except Exception as exc:
            self._record_error("Array authoring failed", exc)
            return None

    def apply_array_pose(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the current array pose fields to the target prim and metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            _raise_first(
                ValidationReport(
                    check_array_pose_editable(self.state.array_attached_to_object)
                )
            )
            position = self._array_position_from_state()
            orientation = self._array_orientation_from_state()
            record = self._author_array_on_stage(
                stage_obj,
                position_world=position,
                orientation_world_quat=orientation,
                kind="array_pose",
            )
            self._append_authored_record(record)
            self._set_status(
                "Applied array pose "
                f"{_format_vec3(position)} / yaw={self.state.array_yaw_deg:g} deg "
                f"to {self.state.array_prim_path}."
            )
            return record
        except Exception as exc:
            self._record_error("Array pose apply failed", exc)
            return None

    def _author_array_on_stage(
        self,
        stage_obj: Any,
        *,
        position_world: tuple[float, float, float] | None,
        orientation_world_quat: tuple[float, float, float, float] | None,
        microphones: tuple[Any, ...] | None = None,
        kind: str = "array",
        extra_attrs: Mapping[str, Any] | None = None,
    ) -> AuthoredMetadataSummary:
        """Create/update the array prim with metadata and an explicit pose."""

        state = self.state
        self._validate_abs_path(state.array_prim_path, "array_prim_path")
        self._validate_layout_state()

        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.array_prim_path,
            prim_type="Xform",
        )
        mics = (
            tuple(microphones)
            if microphones is not None
            else microphone_layout(state.layout_name)
        )
        attrs: dict[str, Any] = dict(
            attach_microphone_array_attrs(
                prim,
                array_id=state.array_id.strip() or _path_name(state.array_prim_path),
                sample_rate_hz=int(state.sample_rate_hz),
                coordinate_convention=state.coordinate_convention,
                layout_name=state.layout_name,
                position_world=position_world,
                orientation_world_quat=orientation_world_quat,
                microphone_relative_offsets_m=tuple(
                    microphone.relative_position_m for microphone in mics
                ),
                microphone_ids=tuple(microphone.mic_id for microphone in mics),
            )
        )
        for name, value in dict(extra_attrs or {}).items():
            _set_prim_attr(prim, name, value)
            attrs[name] = value
        if state.author_child_microphones:
            self._remove_stale_child_microphones(
                stage_obj,
                array_path=state.array_prim_path,
                keep_mic_ids=tuple(microphone.mic_id for microphone in mics),
            )
            self._author_child_microphones(
                stage_obj,
                array_path=state.array_prim_path,
                microphones=mics,
            )
        return AuthoredMetadataSummary(
            kind=kind,
            prim_path=state.array_prim_path,
            id=str(attrs["ias:array_id"]),
            attributes=_jsonable_mapping(attrs),
        )

    def apply_source_position(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the current source XYZ fields to the target prim and metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            authored = self._author_source_on_stage(
                stage_obj,
                position_world=self._source_position_from_state(),
            )
            self._set_status(
                "Applied source position "
                f"{_format_vec3(self._source_position_from_state())} "
                f"to {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source position apply failed", exc)
            return None

    def apply_source_position_preset(
        self,
        preset: str,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply a deterministic source placement preset."""

        try:
            key = preset.strip().lower()
            _raise_first(ValidationReport(check_source_position_preset(preset)))
            self._set_source_position_state(SOURCE_POSITION_PRESETS[key])
            authored = self.apply_source_position(stage=stage)
            if authored is not None:
                self._set_status(
                    f"Applied {key} source preset "
                    f"{_format_vec3(SOURCE_POSITION_PRESETS[key])} "
                    f"to {self.state.source_prim_path}."
                )
            return authored
        except Exception as exc:
            self._record_error("Source preset failed", exc)
            return None

    def select_sound_profile(
        self, profile_id: str | None = None
    ) -> SoundProfile | None:
        """Select a profile manually by id without authoring source metadata."""

        try:
            profile = self._sound_profile_by_id(
                profile_id or self.state.selected_profile_id
            )
            self.state.selected_profile_id = profile.profile_id
            self._set_status(
                f"Selected sound profile {profile.display_label} "
                f"({profile.profile_id})."
            )
            return profile
        except Exception as exc:
            self._record_error("Sound profile selection failed", exc)
            return None

    def auto_select_profile_from_object(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> SoundProfile | None:
        """Select the best profile from selected or attached object labels."""

        try:
            labels = self._object_label_candidates(
                stage=stage,
                selected_paths=selected_paths,
            )
            _raise_first(ValidationReport(check_profile_labels(labels)))
            selected_object_path = self._selected_object_candidate_path(
                stage=stage,
                selected_paths=selected_paths,
            )
            if selected_object_path is not None:
                self.state.object_prim_path = selected_object_path
                self.state.object_label = labels[0]
            library = self._validated_sound_profiles()
            profile_id = match_sound_profile_id(
                labels=labels,
                profiles=library,
                object_profile_mappings=self.state.object_profile_mappings,
            )
            _raise_first(ValidationReport(check_profile_match(labels, profile_id)))
            assert profile_id is not None
            profile = self._sound_profile_by_id(profile_id)
            self.state.selected_profile_id = profile.profile_id
            self._set_status(
                f"Auto-selected {profile.display_label} from object labels: "
                f"{', '.join(labels)}."
            )
            return profile
        except Exception as exc:
            self._record_error("Sound profile auto-match failed", exc)
            return None

    def apply_selected_profile(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the selected profile to the current source prim metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            profile = self._sound_profile_by_id(self.state.selected_profile_id)
            authored = self._author_profile_on_current_source(stage_obj, profile)
            self._set_status(
                f"Applied sound profile {profile.display_label} "
                f"to {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Sound profile apply failed", exc)
            return None

    def select_rig_profile(
        self, profile_id: str | None = None
    ) -> MicrophoneRigProfile | None:
        """Select a microphone rig profile by id without authoring metadata."""

        try:
            profile = self._rig_profile_by_id(
                profile_id or self.state.selected_rig_profile_id
            )
            self.state.selected_rig_profile_id = profile.profile_id
            self._set_status(
                f"Selected rig profile {profile.display_label} ({profile.profile_id})."
            )
            return profile
        except Exception as exc:
            self._record_error("Rig profile selection failed", exc)
            return None

    def apply_selected_rig_profile(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the selected rig profile to the current array prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            profile = self._rig_profile_by_id(self.state.selected_rig_profile_id)
            authored = self._author_rig_on_current_array(stage_obj, profile)
            hint = ""
            mount_path = profile.recommended_mount_prim_path
            if (
                mount_path
                and not self.state.array_attached_to_object
                and _stage_has_prim(stage_obj, mount_path)
            ):
                hint = f" Recommended mount available: {mount_path}."
            self._set_status(
                f"Applied rig profile {profile.display_label} "
                f"to {self.state.array_prim_path}.{hint}"
            )
            return authored
        except Exception as exc:
            self._record_error("Rig profile apply failed", exc)
            return None

    def author_source(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Create or configure source metadata on the current target prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            authored = self._author_source_on_stage(
                stage_obj,
                position_world=self._source_position_from_state(),
            )
            self._set_status(
                f"Authored source {authored.id} at {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source authoring failed", exc)
            return None

    def attach_source_to_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Attach the current source under the selected object with local offset."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            object_path = state.object_prim_path or state.attached_object_prim_path
            self._validate_abs_path(object_path, "object_prim_path")
            self._validate_abs_path(state.source_prim_path, "source_prim_path")
            self._validate_source_metadata_state()
            _raise_first(
                ValidationReport(
                    check_source_attach_target_exists(
                        object_path,
                        _stage_has_prim(stage_obj, object_path),
                    )
                )
            )
            source_name = _path_name(state.source_prim_path)
            attached_path = f"{object_path.rstrip('/')}/{source_name}"
            offset = self._source_local_offset_from_state()
            move_prim_to_path(
                stage_obj,
                source_path=state.source_prim_path,
                dest_path=attached_path,
                prim_type="Sound",
            )
            state.source_prim_path = attached_path
            record = create_sound_prim(
                stage_obj,
                prim_path=attached_path,
                audio_asset_path=state.audio_asset_path,
                spatial=True,
                loop=False,
                start_time_s=state.source_start_time_s,
                gain_db=state.source_gain_db,
            )
            prim = get_or_define_prim(
                stage_obj,
                prim_path=attached_path,
                prim_type=record.prim_type,
            )
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id.strip() or _path_name(attached_path),
                class_label=state.source_class_label.strip() or "Sound",
                position_world=None,
                orientation_world_quat=None,
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            binding_attrs = attach_source_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=offset,
            )
            profile_attrs = _refresh_applied_profile_binding_snapshot(
                prim,
                state,
                object_path=object_path,
                local_offset_m=offset,
            )
            state.source_attached_to_object = True
            state.attached_object_prim_path = object_path
            state.object_prim_path = object_path
            state.object_label = _path_name(object_path)
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    attached_path,
                    field_name="attached source",
                )
                self._set_source_position_state(pose.position_world)
            authored = AuthoredMetadataSummary(
                kind="source_object_attachment",
                prim_path=attached_path,
                id=str(attrs["ias:source_id"]),
                attributes=_jsonable_mapping(
                    {**record.attributes, **attrs, **binding_attrs, **profile_attrs}
                ),
            )
            self._append_authored_record(authored)
            self._validation.invalidate("source attached to stage object")
            self._set_status(
                "Attached source "
                f"{authored.id} to {_path_name(object_path)} at {object_path} "
                f"with local offset {_format_vec3(offset)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source attach failed", exc)
            return None

    def detach_source_from_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Detach the current source to a standalone source path."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            self._validate_abs_path(state.source_prim_path, "source_prim_path")
            self._validate_source_metadata_state()
            source_path = state.source_prim_path
            pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                source_path,
                field_name="attached source",
            )
            standalone_path = f"/World/Sources/{_path_name(source_path)}"
            get_or_define_prim(stage_obj, prim_path="/World/Sources", prim_type="Xform")
            prim = move_prim_to_path(
                stage_obj,
                source_path=source_path,
                dest_path=standalone_path,
                prim_type="Sound",
            )
            state.source_prim_path = standalone_path
            record = create_sound_prim(
                stage_obj,
                prim_path=standalone_path,
                audio_asset_path=state.audio_asset_path,
                spatial=True,
                loop=False,
                start_time_s=state.source_start_time_s,
                gain_db=state.source_gain_db,
            )
            prim = get_or_define_prim(
                stage_obj,
                prim_path=standalone_path,
                prim_type=record.prim_type,
            )
            clear_source_object_binding_attrs(prim)
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id.strip() or _path_name(standalone_path),
                class_label=state.source_class_label.strip() or "Sound",
                position_world=pose.position_world,
                orientation_world_quat=pose.orientation_world_quat
                or (0.0, 0.0, 0.0, 1.0),
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            state.source_attached_to_object = False
            state.attached_object_prim_path = ""
            self._set_source_position_state(pose.position_world)
            authored = AuthoredMetadataSummary(
                kind="source_object_detach",
                prim_path=standalone_path,
                id=str(attrs["ias:source_id"]),
                attributes=_jsonable_mapping({**record.attributes, **attrs}),
            )
            self._append_authored_record(authored)
            self._validation.invalidate("source detached from stage object")
            self._set_status(
                "Detached source "
                f"{authored.id} to {standalone_path} at "
                f"{_format_vec3(pose.position_world)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source detach failed", exc)
            return None

    def attach_array_to_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Mount the current array under the selected object/robot prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            object_path = (
                state.object_prim_path
                or state.attached_array_object_prim_path
                or state.robot_base_prim_path
            )
            self._validate_abs_path(object_path, "object_prim_path")
            self._validate_abs_path(state.array_prim_path, "array_prim_path")
            self._validate_attach_target(
                state.array_prim_path,
                object_path,
                kind="array",
            )
            _raise_first(
                ValidationReport(
                    check_array_attach_target_exists(
                        object_path,
                        _stage_has_prim(stage_obj, object_path),
                    )
                )
            )
            array_name = _path_name(state.array_prim_path)
            attached_path = f"{object_path.rstrip('/')}/{array_name}"
            offset = self._array_local_offset_from_state()
            local_orientation = self._array_local_orientation_from_state()
            move_prim_to_path(
                stage_obj,
                source_path=state.array_prim_path,
                dest_path=attached_path,
                prim_type="Xform",
                include_children=True,
            )
            state.array_prim_path = attached_path
            prim = get_or_define_prim(
                stage_obj,
                prim_path=attached_path,
                prim_type="Xform",
            )
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            binding_attrs = attach_array_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=offset,
                local_orientation_quat=local_orientation,
            )
            state.array_attached_to_object = True
            state.attached_array_object_prim_path = object_path
            state.object_prim_path = object_path
            state.object_label = _path_name(object_path)
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    attached_path,
                    field_name="attached array",
                )
                self._set_array_pose_state(
                    pose.position_world,
                    pose.orientation_world_quat,
                )
            authored = AuthoredMetadataSummary(
                kind="array_object_attachment",
                prim_path=attached_path,
                id=state.array_id.strip() or array_name,
                attributes=_jsonable_mapping(binding_attrs),
            )
            self._append_authored_record(authored)
            self._validation.invalidate("array attached to stage object")
            self._set_status(
                "Attached array "
                f"{authored.id} to {_path_name(object_path)} at {object_path} "
                f"with local offset {_format_vec3(offset)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Array attach failed", exc)
            return None

    def detach_array_from_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Detach the current array to a standalone path, keeping its world pose."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            self._validate_abs_path(state.array_prim_path, "array_prim_path")
            array_path = state.array_prim_path
            pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                array_path,
                field_name="attached array",
            )
            standalone_path = f"/World/AudioArrays/{_path_name(array_path)}"
            get_or_define_prim(
                stage_obj,
                prim_path="/World/AudioArrays",
                prim_type="Xform",
            )
            prim = move_prim_to_path(
                stage_obj,
                source_path=array_path,
                dest_path=standalone_path,
                prim_type="Xform",
                include_children=True,
            )
            state.array_prim_path = standalone_path
            clear_array_object_binding_attrs(prim)
            orientation = pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
            attrs = attach_microphone_array_attrs(
                prim,
                array_id=state.array_id.strip() or _path_name(standalone_path),
                sample_rate_hz=int(state.sample_rate_hz),
                coordinate_convention=state.coordinate_convention,
                layout_name=state.layout_name,
                position_world=pose.position_world,
                orientation_world_quat=orientation,
            )
            state.array_attached_to_object = False
            state.attached_array_object_prim_path = ""
            self._set_array_pose_state(pose.position_world, orientation)
            authored = AuthoredMetadataSummary(
                kind="array_object_detach",
                prim_path=standalone_path,
                id=str(attrs["ias:array_id"]),
                attributes=_jsonable_mapping(attrs),
            )
            self._append_authored_record(authored)
            self._validation.invalidate("array detached from stage object")
            self._set_status(
                "Detached array "
                f"{authored.id} to {standalone_path} at "
                f"{_format_vec3(pose.position_world)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Array detach failed", exc)
            return None

    def _author_source_on_stage(
        self,
        stage_obj: Any,
        *,
        position_world: tuple[float, float, float],
    ) -> AuthoredMetadataSummary:
        """Create/update the source prim with metadata and explicit position."""

        state = self.state
        self._validate_abs_path(state.source_prim_path, "source_prim_path")
        self._validate_source_metadata_state()

        record = create_sound_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            audio_asset_path=state.audio_asset_path,
            spatial=True,
            loop=False,
            start_time_s=state.source_start_time_s,
            gain_db=state.source_gain_db,
        )
        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            prim_type=record.prim_type,
        )
        attrs = attach_sound_source_attrs(
            prim,
            source_id=state.source_id.strip() or _path_name(state.source_prim_path),
            class_label=state.source_class_label.strip() or "Sound",
            position_world=position_world,
            orientation_world_quat=_author_orientation_arg(
                prim,
                default=(0.0, 0.0, 0.0, 1.0),
            ),
            audio_asset_path=state.audio_asset_path,
            start_time_s=state.source_start_time_s,
            duration_s=state.source_duration_s,
            gain_db=state.source_gain_db,
            directivity=state.source_directivity,
        )
        authored = AuthoredMetadataSummary(
            kind="source",
            prim_path=state.source_prim_path,
            id=str(attrs["ias:source_id"]),
            attributes=_jsonable_mapping({**record.attributes, **attrs}),
        )
        self._append_authored_record(authored)
        return authored

    def _author_profile_on_current_source(
        self,
        stage_obj: Any,
        profile: SoundProfile,
    ) -> AuthoredMetadataSummary:
        state = self.state
        self._validate_abs_path(state.source_prim_path, "source_prim_path")
        attached = state.source_attached_to_object
        object_path = state.attached_object_prim_path or state.object_prim_path
        object_label = self._profile_object_label(stage_obj)
        if attached:
            self._validate_abs_path(object_path, "object_prim_path")
            self._validate_attached_object_available(stage_obj)
            position_world = None
        else:
            position_world = self._current_source_world_position(stage_obj)
            self._set_source_position_state(position_world)

        state.source_id = profile.source_id_for(
            object_label=object_label,
            current_source_id=state.source_id.strip()
            or _path_name(state.source_prim_path),
            source_prim_path=state.source_prim_path,
        )
        state.source_class_label = profile.class_label
        state.audio_asset_path = profile.audio_asset_path
        state.source_start_time_s = float(profile.start_time_s)
        state.source_duration_s = float(profile.duration_s)
        state.source_gain_db = float(profile.gain_db)
        state.source_directivity = profile.directivity
        self._validate_source_metadata_state()

        record = create_sound_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            audio_asset_path=state.audio_asset_path,
            spatial=True,
            loop=False,
            start_time_s=state.source_start_time_s,
            gain_db=state.source_gain_db,
        )
        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            prim_type=record.prim_type,
        )
        _set_prim_attr(prim, "ias:sound_profile_id", profile.profile_id)
        _set_prim_attr(prim, "ias:sound_profile_label", profile.display_label)

        binding_attrs: Mapping[str, object] = {}
        if attached:
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id,
                class_label=state.source_class_label,
                position_world=None,
                orientation_world_quat=None,
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            binding_attrs = attach_source_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=self._source_local_offset_from_state(),
            )
        else:
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id,
                class_label=state.source_class_label,
                position_world=position_world,
                orientation_world_quat=_author_orientation_arg(
                    prim,
                    default=(0.0, 0.0, 0.0, 1.0),
                ),
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )

        snapshot = self._applied_profile_snapshot(
            profile,
            source_position_world=position_world,
        )
        state.applied_source_profile = snapshot
        authored = AuthoredMetadataSummary(
            kind="source_profile",
            prim_path=state.source_prim_path,
            id=state.source_id,
            attributes=_jsonable_mapping(
                {
                    **record.attributes,
                    **attrs,
                    **binding_attrs,
                    "ias:sound_profile_id": profile.profile_id,
                    "ias:sound_profile_label": profile.display_label,
                    "applied_source_profile": snapshot,
                }
            ),
        )
        self._append_authored_record(authored)
        return authored

    def _current_source_world_position(
        self,
        stage_obj: Any,
    ) -> tuple[float, float, float]:
        if self.state.source_prim_path.strip() and _stage_has_prim(
            stage_obj,
            self.state.source_prim_path,
        ):
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    self.state.source_prim_path,
                    field_name="source",
                )
                return pose.position_world
        return self._source_position_from_state()

    def _applied_profile_snapshot(
        self,
        profile: SoundProfile,
        *,
        source_position_world: tuple[float, float, float] | None,
    ) -> dict[str, Any]:
        state = self.state
        return _json_ready(
            {
                "profile_id": profile.profile_id,
                "display_label": profile.display_label,
                "source_prim_path": state.source_prim_path,
                "source_id": state.source_id,
                "class_label": state.source_class_label,
                "audio_asset_path": state.audio_asset_path,
                "start_time_s": state.source_start_time_s,
                "duration_s": state.source_duration_s,
                "gain_db": state.source_gain_db,
                "directivity": state.source_directivity,
                "source_attached_to_object": state.source_attached_to_object,
                "object_prim_path": state.object_prim_path or None,
                "object_label": state.object_label,
                "attached_object_prim_path": state.attached_object_prim_path or None,
                "source_local_offset_m": self._source_local_offset_from_state(),
                "source_position_world": source_position_world,
            }
        )

    def _author_rig_on_current_array(
        self,
        stage_obj: Any,
        profile: MicrophoneRigProfile,
    ) -> AuthoredMetadataSummary:
        state = self.state
        self._validate_abs_path(state.array_prim_path, "array_prim_path")
        attached = state.array_attached_to_object
        object_path = state.attached_array_object_prim_path or state.object_prim_path
        if attached:
            self._validate_abs_path(object_path, "object_prim_path")
            self._validate_attached_array_available(stage_obj)

        state.layout_name = profile.layout_name
        state.sample_rate_hz = int(profile.sample_rate_hz)
        (
            state.array_local_offset_x_m,
            state.array_local_offset_y_m,
            state.array_local_offset_z_m,
        ) = profile.mount_local_offset_m
        (
            state.array_local_roll_deg,
            state.array_local_pitch_deg,
            state.array_local_yaw_deg,
        ) = euler_deg_from_quaternion(profile.mount_local_orientation_quat)

        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.array_prim_path,
            prim_type="Xform",
        )
        if attached:
            position_world = None
            orientation_world = None
        else:
            position_world = _author_position_arg(
                prim,
                default=self._array_position_from_state(),
            )
            orientation_world = _author_orientation_arg(
                prim,
                default=self._array_orientation_from_state(),
            )
        record = self._author_array_on_stage(
            stage_obj,
            position_world=position_world,
            orientation_world_quat=orientation_world,
            microphones=profile.microphones(),
            kind="array_rig_profile",
            extra_attrs={
                "ias:rig_profile_id": profile.profile_id,
                "ias:rig_profile_label": profile.display_label,
            },
        )
        binding_attrs: Mapping[str, object] = {}
        if attached:
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            binding_attrs = attach_array_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=profile.mount_local_offset_m,
                local_orientation_quat=profile.mount_local_orientation_quat,
            )
        snapshot = self._applied_rig_profile_snapshot(profile)
        state.applied_array_rig_profile = snapshot
        authored = AuthoredMetadataSummary(
            kind="array_rig_profile",
            prim_path=state.array_prim_path,
            id=record.id,
            attributes=_jsonable_mapping(
                {
                    **dict(record.attributes),
                    **binding_attrs,
                    "applied_array_rig_profile": snapshot,
                }
            ),
        )
        self._append_authored_record(authored)
        return authored

    def _applied_rig_profile_snapshot(
        self,
        profile: MicrophoneRigProfile,
    ) -> dict[str, Any]:
        state = self.state
        return _json_ready(
            {
                "profile_id": profile.profile_id,
                "display_label": profile.display_label,
                "array_prim_path": state.array_prim_path,
                "array_id": state.array_id,
                "layout_name": state.layout_name,
                "sample_rate_hz": state.sample_rate_hz,
                "microphone_ids": profile.microphone_ids,
                "microphone_relative_offsets_m": (
                    profile.microphone_relative_offsets_m
                ),
                "microphone_gains_db": profile.microphone_gains_db,
                "mount_local_offset_m": profile.mount_local_offset_m,
                "mount_local_orientation_quat": profile.mount_local_orientation_quat,
                "recommended_mount_prim_path": profile.recommended_mount_prim_path,
                "array_attached_to_object": state.array_attached_to_object,
                "attached_object_prim_path": state.attached_array_object_prim_path
                or None,
            }
        )

    def _validate_source_metadata_state(self) -> None:
        _raise_first(ValidationReport(check_source_metadata(self.state)))

    def _source_position_from_state(self) -> tuple[float, float, float]:
        position = (
            float(self.state.source_position_x_m),
            float(self.state.source_position_y_m),
            float(self.state.source_position_z_m),
        )
        _raise_first(ValidationReport(check_source_position_values(position)))
        return position

    def _source_local_offset_from_state(self) -> tuple[float, float, float]:
        offset = (
            float(self.state.source_local_offset_x_m),
            float(self.state.source_local_offset_y_m),
            float(self.state.source_local_offset_z_m),
        )
        _raise_first(ValidationReport(check_source_local_offset_values(offset)))
        return offset

    def _set_source_position_state(self, position: Iterable[float]) -> None:
        x, y, z = vec3_from_any(position)
        self.state.source_position_x_m = x
        self.state.source_position_y_m = y
        self.state.source_position_z_m = z

    def _array_position_from_state(self) -> tuple[float, float, float]:
        position = (
            float(self.state.array_position_x_m),
            float(self.state.array_position_y_m),
            float(self.state.array_position_z_m),
        )
        _raise_first(ValidationReport(check_array_position_values(position)))
        return position

    def _array_orientation_from_state(self) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_roll_deg),
            float(self.state.array_pitch_deg),
            float(self.state.array_yaw_deg),
        )
        _raise_first(ValidationReport(check_array_orientation_values(angles)))
        return quaternion_from_euler_deg(
            roll_deg=angles[0],
            pitch_deg=angles[1],
            yaw_deg=angles[2],
        )

    def _array_local_offset_from_state(self) -> tuple[float, float, float]:
        offset = (
            float(self.state.array_local_offset_x_m),
            float(self.state.array_local_offset_y_m),
            float(self.state.array_local_offset_z_m),
        )
        _raise_first(ValidationReport(check_array_local_offset_values(offset)))
        return offset

    def _array_local_orientation_from_state(
        self,
    ) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_local_roll_deg),
            float(self.state.array_local_pitch_deg),
            float(self.state.array_local_yaw_deg),
        )
        _raise_first(ValidationReport(check_array_local_orientation_values(angles)))
        return quaternion_from_euler_deg(
            roll_deg=angles[0],
            pitch_deg=angles[1],
            yaw_deg=angles[2],
        )

    def _set_array_pose_state(
        self,
        position: Iterable[float],
        orientation_quat: Iterable[float] | None = None,
    ) -> None:
        x, y, z = vec3_from_any(position)
        self.state.array_position_x_m = x
        self.state.array_position_y_m = y
        self.state.array_position_z_m = z
        if orientation_quat is not None:
            (
                self.state.array_roll_deg,
                self.state.array_pitch_deg,
                self.state.array_yaw_deg,
            ) = euler_deg_from_quaternion(quat_from_any(orientation_quat))

    def refresh_discovery(
        self,
        *,
        stage: Any | None = None,
    ) -> tuple[DiscoveredPrimSummary, ...]:
        """Discover array/source metadata on the current stage."""

        try:
            stage_obj = self._stage_or_error(stage)
            result = discover_stage_audio(
                stage_obj,
                cfg=self._discovery_cfg(required_arrays=False, required_sources=False),
            )
            self.state.discovered_arrays = tuple(
                DiscoveredPrimSummary(
                    id=array.spec.array_id,
                    prim_path=array.spec.prim_path or "",
                    reasons=tuple(array.reasons),
                )
                for array in result.arrays
            )
            self.state.discovered_sources = tuple(
                DiscoveredPrimSummary(
                    id=source.spec.source_id,
                    prim_path=source.spec.prim_path or "",
                    reasons=tuple(source.reasons),
                )
                for source in result.sources
            )
            self.state.discovered_objects = _discover_scene_objects(
                stage_obj,
                roots=self._discovery_roots(),
                excluded_paths=(
                    self.state.array_prim_path,
                    self.state.source_prim_path,
                    self.state.robot_base_prim_path,
                ),
            )
            self._set_status(
                "Discovery found "
                f"{len(result.arrays)} array(s), {len(result.sources)} source(s), "
                f"{len(self.state.discovered_objects)} object(s)."
            )
            return (
                *self.state.discovered_arrays,
                *self.state.discovered_sources,
                *self.state.discovered_objects,
            )
        except Exception as exc:
            self._record_error("Discovery failed", exc)
            return ()

    def _author_child_microphones(
        self,
        stage: Any,
        *,
        array_path: str,
        microphones: Iterable[Any],
    ) -> None:
        for microphone in microphones:
            child_path = f"{array_path.rstrip('/')}/{microphone.mic_id}"
            child = get_or_define_prim(
                stage,
                prim_path=child_path,
                prim_type="Microphone",
            )
            attach_microphone_attrs(
                child,
                mic_id=microphone.mic_id,
                relative_position_m=microphone.relative_position_m,
                relative_orientation_quat=microphone.relative_orientation_quat,
                gain_db=microphone.gain_db,
                self_noise_db=microphone.self_noise_db,
            )

    def _remove_stale_child_microphones(
        self,
        stage: Any,
        *,
        array_path: str,
        keep_mic_ids: tuple[str, ...],
    ) -> None:
        if not hasattr(stage, "Traverse"):
            return
        prefix = array_path.rstrip("/") + "/"
        keep = set(keep_mic_ids)
        for prim in tuple(stage.Traverse()):
            path = prim_path(prim)
            if not path.startswith(prefix) or "/" in path[len(prefix) :]:
                continue
            attrs = _prim_attrs(prim)
            is_microphone = (
                _prim_type_name(prim) == "Microphone" or "ias:microphone_id" in attrs
            )
            if not is_microphone:
                continue
            mic_id = str(attrs.get("ias:microphone_id", _path_name(path)))
            if mic_id not in keep:
                remove_prim(stage, path)

    def _discovery_cfg(
        self,
        *,
        required_arrays: bool,
        required_sources: bool,
    ) -> IsaacAudioDiscoveryCfg:
        return IsaacAudioDiscoveryCfg(
            discovery_roots=self._discovery_roots(),
            robot_base_prim_path=self.state.robot_base_prim_path or None,
            required_arrays=required_arrays,
            required_sources=required_sources,
            default_microphone_layout=self.state.layout_name,
            default_sample_rate_hz=self.state.sample_rate_hz,
            coordinate_convention=self.state.coordinate_convention,
            default_source_duration_s=self.state.source_duration_s,
        )

    def _discovery_roots(self) -> tuple[str, ...]:
        roots = tuple(
            root.strip()
            for root in self.state.discovery_roots_text.replace(";", ",").split(",")
            if root.strip()
        )
        return roots or ("/World",)

    def _preferred_discovered_array(self) -> str | None:
        if not self.state.array_id:
            return None
        for item in self.state.discovered_arrays:
            if item.id == self.state.array_id:
                return self.state.array_id
        return None

    def _validated_sound_profiles(self) -> tuple[SoundProfile, ...]:
        profiles = validate_sound_profile_library(self.state.profile_library)
        self.state.profile_library = profiles
        profile_ids = {profile.profile_id for profile in profiles}
        bad_mappings = {
            label: profile_id
            for label, profile_id in self.state.object_profile_mappings.items()
            if profile_id not in profile_ids
        }
        if bad_mappings:
            label, profile_id = next(iter(sorted(bad_mappings.items())))
            _raise_first(
                ValidationReport(
                    check_object_profile_mapping_known(
                        label,
                        profile_id,
                        False,
                    )
                )
            )
        return profiles

    def _sound_profile_by_id(self, profile_id: str) -> SoundProfile:
        requested = profile_id.strip()
        _raise_first(ValidationReport(check_sound_profile_id_present(requested)))
        for profile in self._validated_sound_profiles():
            if profile.profile_id == requested:
                return profile
        _raise_first(
            ValidationReport(
                check_sound_profile_id_known(
                    requested,
                    False,
                )
            )
        )
        raise AssertionError("unreachable sound profile validation")

    def _validated_rig_profiles(self) -> tuple[MicrophoneRigProfile, ...]:
        profiles = validate_microphone_rig_profile_library(
            self.state.rig_profile_library
        )
        self.state.rig_profile_library = profiles
        return profiles

    def _rig_profile_by_id(self, profile_id: str) -> MicrophoneRigProfile:
        requested = profile_id.strip()
        _raise_first(ValidationReport(check_rig_profile_id_present(requested)))
        for profile in self._validated_rig_profiles():
            if profile.profile_id == requested:
                return profile
        _raise_first(
            ValidationReport(
                check_rig_profile_id_known(
                    requested,
                    False,
                )
            )
        )
        raise AssertionError("unreachable rig profile validation")

    def _profile_object_label(self, stage_obj: Any | None) -> str:
        labels = self._object_label_candidates(stage=stage_obj, selected_paths=None)
        return labels[0] if labels else _path_name(self.state.source_prim_path)

    def _object_label_candidates(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> tuple[str, ...]:
        candidates: list[str] = []
        context_stage = stage
        if selected_paths is not None:
            context = self._context(stage=stage, selected_paths=selected_paths)
            context_stage = context.stage or stage
            for path in context.selected_prim_paths:
                candidates.extend(
                    _object_label_candidates_for_path(context_stage, path)
                )
        for label in (self.state.object_label,):
            if label and label != "none":
                candidates.append(label)
        for path in (
            self.state.object_prim_path,
            self.state.attached_object_prim_path,
        ):
            if path:
                candidates.extend(
                    _object_label_candidates_for_path(context_stage, path)
                )
        if self.state.source_attached_to_object and self.state.source_prim_path:
            parent_path = self.state.source_prim_path.rstrip("/").rsplit("/", 1)[0]
            candidates.extend(
                _object_label_candidates_for_path(context_stage, parent_path)
            )
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = str(candidate).strip()
            if not text or text.lower() == "none":
                continue
            key = normalize_object_label(text)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return tuple(normalized)

    def _selected_object_candidate_path(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> str | None:
        if selected_paths is None:
            return None
        context = self._context(stage=stage, selected_paths=selected_paths)
        for path in context.selected_prim_paths:
            if path in {self.state.array_prim_path, self.state.source_prim_path}:
                continue
            if context.stage is None or _stage_has_prim(context.stage, path):
                return path
        return None

    def _stage_or_error(self, stage: Any | None) -> Any:
        context = self._context(stage=stage)
        self._validate_stage_present(context.stage is not None)
        self.state.selected_prim_paths = context.selected_prim_paths
        return context.stage

    def _validate_abs_path(self, path: str, field_name: str) -> None:
        _raise_first(ValidationReport(check_abs_prim_path(path, field_name)))

    def _validate_stage_present(self, stage_is_open: bool) -> None:
        _raise_first(ValidationReport(check_stage_present(stage_is_open)))

    def _validate_selection(self, path: str | None, *, exists: bool) -> None:
        _raise_first(ValidationReport(check_selection(path, exists)))

    def _validate_attach_target(
        self,
        source_path: str,
        target_path: str,
        *,
        kind: str = "source",
    ) -> None:
        _raise_first(
            ValidationReport(
                check_attach_target(
                    source_path,
                    target_path,
                    kind=kind,
                )
            )
        )

    def _validate_attached_object_available(self, stage: Any | None) -> None:
        object_path = (
            self.state.attached_object_prim_path or self.state.object_prim_path
        )
        exists = (
            None
            if not self.state.source_attached_to_object
            or stage is None
            or not object_path
            else _stage_has_prim(stage, object_path)
        )
        _raise_first(
            ValidationReport(
                check_attached_source_target(
                    self.state.source_attached_to_object,
                    object_path,
                    exists,
                )
            )
        )

    def _validate_attached_array_available(self, stage: Any | None) -> None:
        object_path = (
            self.state.attached_array_object_prim_path or self.state.object_prim_path
        )
        exists = (
            None
            if not self.state.array_attached_to_object
            or stage is None
            or not object_path
            else _stage_has_prim(stage, object_path)
        )
        _raise_first(
            ValidationReport(
                check_attached_array_target(
                    self.state.array_attached_to_object,
                    object_path,
                    exists,
                )
            )
        )

    def _attachment_status_for_current_stage(self) -> str | None:
        if not self.state.source_attached_to_object:
            return None
        object_path = (
            self.state.attached_object_prim_path or self.state.object_prim_path
        )
        if not object_path:
            return "attached object path is missing"
        try:
            stage = self._context().stage
        except Exception:
            return None
        if stage is None:
            return None
        if not _stage_has_prim(stage, object_path):
            return f"attached object is missing from the current stage: {object_path}"
        return None

    def _context(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> CurrentStageContext:
        if stage is not None:
            return CurrentStageContext(
                stage=stage,
                selected_prim_paths=_normalize_paths(selected_paths or ()),
            )
        if selected_paths is not None:
            return CurrentStageContext(
                stage=None,
                selected_prim_paths=_normalize_paths(selected_paths),
            )
        if self.stage_context_provider is not None:
            return self.stage_context_provider()
        return current_omni_stage_context()

    def _first_selected_path(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> str | None:
        try:
            paths = self.refresh_stage_selection(
                stage=stage,
                selected_paths=selected_paths,
            )
            self._validate_selection(paths[0] if paths else None, exists=True)
            return paths[0]
        except Exception as exc:
            self._record_error("Selection binding failed", exc)
            return None

    def _append_authored_record(self, record: AuthoredMetadataSummary) -> None:
        self.state.authored_metadata = (*self.state.authored_metadata, record)
