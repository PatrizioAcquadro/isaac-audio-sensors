"""Internal configuration service."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.directivity import (
    DirectivityPattern,
    resolve_directivity_pattern,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import (
    euler_deg_from_quaternion,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    quat_from_any,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    debug_primitives_to_dicts,
)
from isaac_audio_sensors.kit.microphone_rig_profiles import (
    MicrophoneRigProfile,
    microphone_rig_profile_from_mapping,
    validate_microphone_rig_profile_library,
)
from isaac_audio_sensors.kit.sound_profiles import (
    SoundProfile,
    normalize_object_label,
    sound_profile_from_mapping,
    validate_sound_profile_library,
)

from ._service import ControllerService, _raise_first
from .geometry_settings import geometry_settings, parse_geometry_settings
from .paths import _resolve_gui_output_path
from .stage_context import (
    _normalize_paths,
    _path_name,
)
from .state import (
    ExtensionUiState,
    _authored_metadata_from_dict,
    _discovered_summary_from_dict,
    _json_ready,
)
from .validation.checks import (
    check_config_schema_version,
    check_environment_resolution,
    check_object_profile_mapping_known,
    check_object_profile_mappings_mapping,
    check_object_profile_mappings_non_empty,
    check_object_profile_mappings_present,
    check_rig_profile_config_container,
    check_rig_profile_id_known,
    check_rig_profile_library_present,
    check_rig_profile_library_sequence,
    check_sound_profile_config_container,
    check_sound_profile_id_known,
    check_sound_profile_library_present,
    check_sound_profile_library_sequence,
)
from .validation.results import ValidationReport

# JSON key, UI state field, input conversion.
_SCALAR_FIELDS = {
    "guided": (("mode_enabled", "guided_mode_enabled", bool),),
    "guided.recording": (
        ("dataset_id", "guided_dataset_id", str),
        ("shard_max_frames", "guided_shard_max_frames", int),
        ("shard_episode_aligned", "guided_record_aligned", bool),
        ("scene_id", "guided_scene_id", str),
        ("environment_id", "guided_environment_id", str),
        ("split_group", "guided_split_group", str),
        ("session_seed", "guided_session_seed", int),
    ),
    "guided.export": (
        ("split_enabled", "guided_split_enabled", bool),
        ("train_ratio", "guided_split_train_ratio", float),
        ("validation_ratio", "guided_split_validation_ratio", float),
        ("test_ratio", "guided_split_test_ratio", float),
    ),
    "device": (
        ("device_id", "device_id", str),
        ("compute_device", "compute_device", str),
    ),
    "array": (
        ("prim_path", "array_prim_path", str),
        ("array_id", "array_id", str),
        ("layout_name", "layout_name", str),
        ("sample_rate_hz", "sample_rate_hz", int),
        ("coordinate_convention", "coordinate_convention", str),
    ),
    "array_binding": (("attached", "array_attached_to_object", bool),),
    "source": (
        ("prim_path", "source_prim_path", str),
        ("source_id", "source_id", str),
        ("class_label", "source_class_label", str),
        ("audio_asset_path", "audio_asset_path", str),
        ("start_time_s", "source_start_time_s", float),
        ("duration_s", "source_duration_s", float),
        ("gain_db", "source_gain_db", float),
    ),
    "object_binding": (("attached", "source_attached_to_object", bool),),
    "lifecycle": (
        ("update_period_s", "update_period_s", float),
        ("max_observations", "max_observations", int),
        ("debug_overlay_enabled", "debug_overlay_enabled", bool),
        ("occlusion_enabled", "occlusion_enabled", bool),
        ("waveform_enabled", "waveform_enabled", bool),
        ("follow_viewport_selection", "follow_viewport_selection", bool),
        ("live_sync_array_pose", "live_sync_array_pose", bool),
        ("live_sync_source_pose", "live_sync_source_pose", bool),
        ("usd_debug_enabled", "usd_debug_enabled", bool),
    ),
    "environment": (
        ("mode", "environment_resolution_mode", str),
        ("containment_tolerance_m", "environment_containment_tolerance_m", float),
    ),
    "analytic_acoustics": (
        ("max_order", "analytic_max_order", int),
        ("air_absorption", "analytic_air_absorption", bool),
        ("ray_tracing", "analytic_ray_tracing", bool),
    ),
}


def _scalar_values(state: ExtensionUiState, section: str) -> dict[str, Any]:
    return {key: getattr(state, name) for key, name, _ in _SCALAR_FIELDS[section]}


class ConfigurationService(ControllerService):
    """Own configuration behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self._imported_overlay_primitives = ()

    def export_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Write a reusable stage-binding/config summary."""

        try:
            output = _resolve_gui_output_path(path or self.state.config_export_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    self.config_summary_dict(),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._set_status(f"Exported config summary to {output}.")
            return output
        except Exception as exc:
            self._record_error("Config export failed", exc)
            return None

    def import_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Load a deterministic extension config summary into UI state."""

        try:
            requested_path = path or self.state.config_import_path
            input_path = _resolve_gui_output_path(requested_path)
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            self._apply_config_summary(payload)
            self.state.config_import_path = str(requested_path)
            missing_attachment = (
                self._host._authoring._attachment_status_for_current_stage()
            )
            if missing_attachment:
                self._set_status(
                    f"Imported config summary from {input_path}; {missing_attachment}",
                    error=True,
                )
            else:
                self._set_status(f"Imported config summary from {input_path}.")
            return input_path
        except Exception as exc:
            self._record_error("Config import failed", exc)
            return None

    def config_summary_dict(self) -> dict[str, Any]:
        """Return a JSON-ready stage-binding summary for evidence/reuse."""

        state = self.state
        primitives = (
            ()
            if self._host.sensor is None
            else tuple(self._host.sensor.latest_debug_primitives)
        )
        serialized_primitives = (
            list(self._imported_overlay_primitives)
            if self._host.sensor is None
            else debug_primitives_to_dicts(primitives)
        )
        writer_path = (
            str(_resolve_gui_output_path(state.jsonl_trace_path))
            if state.trace_enabled
            else None
        )
        return _json_ready(
            {
                "schema_version": "ias.omni_extension_binding.v7",
                "backend": state.backend,
                "geometry_acoustics": geometry_settings(state),
                "activity_detection": {
                    "detector_id": "auditok",
                    "energy_threshold_dbfs": state.energy_threshold_dbfs,
                },
                "direction_estimation": {"enabled": state.doa_enabled},
                "environment": {
                    **_scalar_values(state, "environment"),
                    "anchor_prim_path": (
                        state.environment_anchor_prim_path or None
                        if state.environment_resolution_mode == "anchor"
                        else None
                    ),
                    "resolved": state.latest_environment_summary,
                },
                "analytic_acoustics": {
                    **_scalar_values(state, "analytic_acoustics"),
                },
                "device": {
                    **_scalar_values(state, "device"),
                },
                "calibration": {
                    "profile_path": state.calibration_profile_path or None,
                },
                "guided": {
                    **_scalar_values(state, "guided"),
                    "preset_id": state.guided_preset_id or None,
                    "recording": {
                        **_scalar_values(state, "guided.recording"),
                    },
                    "export": {
                        **_scalar_values(state, "guided.export"),
                    },
                },
                "array": {
                    **_scalar_values(state, "array"),
                    "position_world": (
                        self._host._authoring._array_position_from_state()
                    ),
                    "orientation_world_quat": (
                        self._host._authoring._array_orientation_from_state()
                    ),
                    "orientation_euler_deg": (
                        state.array_roll_deg,
                        state.array_pitch_deg,
                        state.array_yaw_deg,
                    ),
                },
                "source": {
                    **_scalar_values(state, "source"),
                    "position_world": (
                        self._host._authoring._source_position_from_state()
                    ),
                    "orientation_world_quat": state.source_orientation_world_quat,
                    "local_offset_m": (
                        self._host._authoring._source_local_offset_from_state()
                    ),
                    "loop_count": state.source_loop_count,
                    "directivity": state.source_directivity,
                },
                "sound_profiles": {
                    "profile_library": [
                        profile.to_dict()
                        for profile in sorted(
                            state.profile_library,
                            key=lambda item: item.profile_id,
                        )
                    ],
                    "selected_profile_id": state.selected_profile_id or None,
                    "object_profile_mappings": dict(
                        sorted(state.object_profile_mappings.items())
                    ),
                    "applied_source_profile": state.applied_source_profile or None,
                },
                "object_binding": {
                    "selected_object_prim_path": state.object_prim_path or None,
                    "selected_object_label": state.object_label,
                    **_scalar_values(state, "object_binding"),
                    "attached_object_prim_path": state.attached_object_prim_path
                    or None,
                    "source_local_offset_m": (
                        self._host._authoring._source_local_offset_from_state()
                    ),
                },
                "array_binding": {
                    **_scalar_values(state, "array_binding"),
                    "attached_object_prim_path": (
                        state.attached_array_object_prim_path or None
                    ),
                    "array_local_offset_m": (
                        self._host._authoring._array_local_offset_from_state()
                    ),
                    "array_local_orientation_quat": (
                        self._host._authoring._array_local_orientation_from_state()
                    ),
                    "array_local_euler_deg": (
                        state.array_local_roll_deg,
                        state.array_local_pitch_deg,
                        state.array_local_yaw_deg,
                    ),
                },
                "microphone_rig_profiles": {
                    "rig_library": [
                        profile.to_dict()
                        for profile in sorted(
                            state.rig_profile_library,
                            key=lambda item: item.profile_id,
                        )
                    ],
                    "selected_rig_profile_id": state.selected_rig_profile_id or None,
                    "applied_array_rig_profile": (
                        state.applied_array_rig_profile or None
                    ),
                },
                "stage_binding": {
                    "robot_base_prim_path": state.robot_base_prim_path or None,
                    "discovery_roots": self._host._authoring._discovery_roots(),
                    "preferred_source": state.source_id or None,
                    "selected_prim_paths": state.selected_prim_paths,
                    "discovered_arrays": state.discovered_arrays,
                    "discovered_sources": state.discovered_sources,
                    "discovered_objects": state.discovered_objects,
                },
                "lifecycle": {
                    **_scalar_values(state, "lifecycle"),
                    "writer_enabled": state.trace_enabled,
                    "writer_path": writer_path,
                    "waveform_dir": state.waveform_dir,
                    "waveform_mode": state.waveform_mode,
                    "usd_debug_root": state.usd_debug_root,
                    "runtime_options": {
                        "subscribe_to_update_stream_default": True,
                        "import_safe_outside_isaac": True,
                    },
                },
                "recording": {
                    "package_jsonl": {
                        "enabled": state.trace_enabled,
                        "path": writer_path,
                    },
                    "replicator": self._host._replicator._replicator_status_dict(),
                },
                "authored_metadata": state.authored_metadata,
                "latest_frame": {
                    "frame_id": state.latest_frame_id,
                    "producer_id": state.latest_producer,
                    "observation_count": state.latest_observation_count,
                    "observations": []
                    if state.latest_frame is None
                    else list(state.latest_frame.observations),
                    "array_prim_path": state.latest_array_prim_path,
                    "array_position_m": state.latest_array_position_m,
                    "array_orientation_xyzw": state.latest_array_orientation_xyzw,
                    "mic_world_positions": dict(
                        sorted(state.latest_mic_world_positions.items())
                    ),
                },
                "overlay": {
                    "primitive_count": state.latest_overlay_primitive_count,
                    "labels": state.latest_overlay_labels,
                    "status": state.latest_overlay_status,
                    "error": state.latest_overlay_error,
                    "primitives": serialized_primitives,
                },
            }
        )

    def _apply_config_summary(self, payload: Mapping[str, Any]) -> None:
        updates, primitives = self._parse_config_summary(payload)
        self._host._geometry.close()
        self._validation.invalidate()
        for name, value in updates.items():
            setattr(self.state, name, value)
        self._imported_overlay_primitives = primitives

    def _parse_config_summary(
        self, payload: Any
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        self._preflight_config_summary(payload)
        state = replace(self.state)
        for section, definitions in _SCALAR_FIELDS.items():
            values = payload
            for key in section.split("."):
                values = values.get(key, {})
            for key, name, convert in definitions:
                setattr(state, name, convert(values.get(key, getattr(state, name))))
        array = dict(payload.get("array", {}))
        source = dict(payload.get("source", {}))
        sound_profiles = payload.get("sound_profiles")
        rig_profiles = payload.get("microphone_rig_profiles")
        object_binding = dict(payload.get("object_binding", {}))
        array_binding = dict(payload.get("array_binding", {}))
        binding = dict(payload.get("stage_binding", {}))
        lifecycle = dict(payload.get("lifecycle", {}))
        activity_detection = dict(payload.get("activity_detection", {}))
        direction_estimation = dict(payload.get("direction_estimation", {}))
        environment = dict(payload.get("environment", {}))
        calibration = dict(payload.get("calibration", {}))
        recording = dict(payload.get("recording", {}))
        package_recording = dict(recording.get("package_jsonl", {}))
        replicator = dict(recording.get("replicator", {}))
        guided = dict(payload.get("guided", {}))

        preset_id = guided.get("preset_id")
        state.guided_preset_id = "" if preset_id is None else str(preset_id)

        geometry = parse_geometry_settings(payload.get("geometry_acoustics", {}))
        for name, value in geometry_settings(geometry).items():
            setattr(state, "geometry_" + name, value)
        state.backend = str(payload.get("backend", state.backend))
        state.energy_threshold_dbfs = float(activity_detection["energy_threshold_dbfs"])
        state.doa_enabled = bool(direction_estimation["enabled"])
        if "profile_path" in calibration:
            selected_calibration = calibration.get("profile_path")
            state.calibration_profile_path = (
                "" if selected_calibration is None else str(selected_calibration)
            )
        if array.get("position_world") is not None:
            (
                state.array_position_x_m,
                state.array_position_y_m,
                state.array_position_z_m,
            ) = vec3_from_any(array["position_world"])
        if array.get("orientation_world_quat") is not None:
            (
                state.array_roll_deg,
                state.array_pitch_deg,
                state.array_yaw_deg,
            ) = euler_deg_from_quaternion(
                quat_from_any(array["orientation_world_quat"])
            )
        if array.get("orientation_euler_deg") is not None:
            (
                state.array_roll_deg,
                state.array_pitch_deg,
                state.array_yaw_deg,
            ) = vec3_from_any(array["orientation_euler_deg"])
        attached_array_path = array_binding.get("attached_object_prim_path")
        if attached_array_path is not None:
            state.attached_array_object_prim_path = str(attached_array_path)
        elif not state.array_attached_to_object:
            state.attached_array_object_prim_path = ""
        array_local_offset = array_binding.get("array_local_offset_m")
        if array_local_offset is not None:
            (
                state.array_local_offset_x_m,
                state.array_local_offset_y_m,
                state.array_local_offset_z_m,
            ) = vec3_from_any(array_local_offset)
        array_local_quat = array_binding.get("array_local_orientation_quat")
        if array_local_quat is not None:
            (
                state.array_local_roll_deg,
                state.array_local_pitch_deg,
                state.array_local_yaw_deg,
            ) = euler_deg_from_quaternion(quat_from_any(array_local_quat))
        if array_binding.get("array_local_euler_deg") is not None:
            (
                state.array_local_roll_deg,
                state.array_local_pitch_deg,
                state.array_local_yaw_deg,
            ) = vec3_from_any(array_binding["array_local_euler_deg"])
        if rig_profiles is not None:
            (
                state.rig_profile_library,
                state.selected_rig_profile_id,
                state.applied_array_rig_profile,
            ) = self._parse_rig_profile_config(rig_profiles)
        if source.get("position_world") is not None:
            (
                state.source_position_x_m,
                state.source_position_y_m,
                state.source_position_z_m,
            ) = vec3_from_any(source["position_world"])
        source_orientation = source.get("orientation_world_quat")
        state.source_orientation_world_quat = (
            None if source_orientation is None else quat_from_any(source_orientation)
        )
        local_offset = object_binding.get(
            "source_local_offset_m",
            source.get("local_offset_m"),
        )
        if local_offset is not None:
            (
                state.source_local_offset_x_m,
                state.source_local_offset_y_m,
                state.source_local_offset_z_m,
            ) = vec3_from_any(local_offset)
        state.source_loop_count = source.get("loop_count", state.source_loop_count)
        state.source_directivity = resolve_directivity_pattern(
            source.get("directivity", state.source_directivity),
            "source.directivity",
        )
        if sound_profiles is not None:
            (
                state.profile_library,
                state.object_profile_mappings,
                state.selected_profile_id,
                state.applied_source_profile,
            ) = self._parse_sound_profile_config(sound_profiles)
        state.robot_base_prim_path = str(binding.get("robot_base_prim_path") or "")
        state.object_prim_path = str(
            object_binding.get("selected_object_prim_path")
            or state.object_prim_path
            or ""
        )
        state.object_label = str(
            object_binding.get("selected_object_label")
            or (
                _path_name(state.object_prim_path) if state.object_prim_path else "none"
            )
        )
        state.attached_object_prim_path = str(
            object_binding.get("attached_object_prim_path")
            or (state.object_prim_path if state.source_attached_to_object else "")
        )
        roots = binding.get("discovery_roots", self._host._authoring._discovery_roots())
        state.discovery_roots_text = ", ".join(str(root) for root in roots)
        state.selected_prim_paths = _normalize_paths(
            binding.get("selected_prim_paths", ())
        )
        state.discovered_arrays = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_arrays", ())
        )
        state.discovered_sources = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_sources", ())
        )
        state.discovered_objects = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_objects", ())
        )
        state.waveform_dir = str(
            lifecycle.get("waveform_dir", state.waveform_dir) or state.waveform_dir
        )
        waveform_mode = str(lifecycle.get("waveform_mode", state.waveform_mode))
        if waveform_mode in {"per_frame", "session"}:
            state.waveform_mode = waveform_mode
        state.usd_debug_root = str(
            lifecycle.get("usd_debug_root", state.usd_debug_root)
            or state.usd_debug_root
        )
        anchor_path = environment.get(
            "anchor_prim_path",
            state.environment_anchor_prim_path,
        )
        state.environment_anchor_prim_path = (
            "" if anchor_path is None else str(anchor_path)
        )
        environment_summary = environment.get("resolved")
        state.latest_environment_summary = (
            dict(environment_summary)
            if isinstance(environment_summary, Mapping)
            else None
        )
        state.trace_enabled = bool(
            package_recording.get(
                "enabled",
                lifecycle.get("writer_enabled", state.trace_enabled),
            )
        )
        state.jsonl_trace_path = str(
            package_recording.get(
                "path",
                lifecycle.get("writer_path", state.jsonl_trace_path),
            )
            or state.jsonl_trace_path
        )
        state.replicator_enabled = bool(
            replicator.get("enabled", state.replicator_enabled)
        )
        state.replicator_output_dir = str(
            replicator.get("output_dir", state.replicator_output_dir)
        )
        state.replicator_writer_name = str(
            replicator.get("writer_name", state.replicator_writer_name)
        )
        state.replicator_annotator_name = str(
            replicator.get("annotator_name", state.replicator_annotator_name)
        )
        state.replicator_recording = bool(
            replicator.get("started", state.replicator_recording)
        )
        state.replicator_write_count = int(
            replicator.get("write_count", state.replicator_write_count)
        )
        state.replicator_flush_count = int(
            replicator.get("flush_count", state.replicator_flush_count)
        )
        state.replicator_latest_write_path = replicator.get(
            "latest_write_path",
            state.replicator_latest_write_path,
        )
        state.replicator_latest_jsonl_path = replicator.get(
            "latest_jsonl_path",
            state.replicator_latest_jsonl_path,
        )
        state.replicator_latest_error = replicator.get(
            "latest_error",
            state.replicator_latest_error,
        )
        state.replicator_output_artifacts = tuple(
            str(item) for item in replicator.get("output_artifacts", ())
        )
        state.replicator_status_message = str(
            replicator.get(
                "status_message",
                state.replicator_status_message,
            )
        )
        state.authored_metadata = tuple(
            _authored_metadata_from_dict(item)
            for item in payload.get("authored_metadata", ())
        )
        overlay = dict(payload.get("overlay", {}))
        state.latest_overlay_primitive_count = int(overlay.get("primitive_count", 0))
        state.latest_overlay_labels = tuple(
            str(item) for item in overlay.get("labels", ())
        )
        state.latest_overlay_status = str(overlay.get("status", "none"))
        state.latest_overlay_error = overlay.get("error")
        primitives = tuple(dict(item) for item in overlay.get("primitives", ()))

        # Leave runtime fields changed by close() under their owning service.
        updates = {
            field.name: getattr(state, field.name)
            for field in fields(state)
            if getattr(state, field.name) is not getattr(self.state, field.name)
        }
        return updates, primitives

    def _preflight_config_summary(self, payload: Any) -> None:
        """Validate binding schema and acoustic constraints before parsing."""

        if not isinstance(payload, Mapping):
            raise ValueError("Config summary must be a JSON object.")
        _raise_first(
            ValidationReport(check_config_schema_version(payload.get("schema_version")))
        )
        lifecycle = payload.get("lifecycle", {})
        if not isinstance(lifecycle, Mapping):
            raise ValueError("lifecycle must be a JSON object.")
        legacy_keys = {
            "room_anchor_prim_path",
            "room_out_of_bounds",
            "room_summary",
        }.intersection(lifecycle)
        if legacy_keys:
            raise ValueError(
                "Binding v7 rejects legacy room lifecycle keys: "
                f"{sorted(legacy_keys)!r}."
            )
        if "ambiguity_policy" in lifecycle:
            raise ValueError(
                "Binding v7 removed lifecycle.ambiguity_policy; contextual DOA "
                "disambiguation belongs in downstream consumers."
            )
        if "room_acoustics" in payload:
            raise ValueError(
                "Binding v7 removed room_acoustics; use analytic_acoustics."
            )
        removed_keys = {"doa_estimator", "max_detections"}.intersection(lifecycle)
        if removed_keys:
            raise ValueError(
                "Binding v7 rejects removed perception lifecycle keys: "
                f"{sorted(removed_keys)!r}."
            )
        activity_detection = payload.get("activity_detection")
        if not isinstance(activity_detection, Mapping):
            raise ValueError("activity_detection must be a JSON object.")
        required_activity_keys = {"detector_id", "energy_threshold_dbfs"}
        missing_activity_keys = required_activity_keys - set(activity_detection)
        if missing_activity_keys:
            raise ValueError(
                "activity_detection is missing required keys "
                f"{sorted(missing_activity_keys)!r}."
            )
        unknown_activity_keys = set(activity_detection) - required_activity_keys
        if unknown_activity_keys:
            raise ValueError(
                "activity_detection contains unknown keys "
                f"{sorted(unknown_activity_keys)!r}."
            )
        if activity_detection["detector_id"] != "auditok":
            raise ValueError("activity_detection.detector_id must be 'auditok'.")
        threshold_dbfs = activity_detection["energy_threshold_dbfs"]
        if isinstance(threshold_dbfs, bool) or not isinstance(
            threshold_dbfs, int | float
        ):
            raise ValueError(
                "activity_detection.energy_threshold_dbfs must be a real number."
            )
        if not math.isfinite(float(threshold_dbfs)):
            raise ValueError("activity_detection.energy_threshold_dbfs must be finite.")
        direction_estimation = payload.get("direction_estimation")
        if not isinstance(direction_estimation, Mapping):
            raise ValueError("direction_estimation must be a JSON object.")
        required_direction_keys = {"enabled"}
        missing_direction_keys = required_direction_keys - set(direction_estimation)
        if missing_direction_keys:
            raise ValueError(
                "direction_estimation is missing required keys "
                f"{sorted(missing_direction_keys)!r}."
            )
        unknown_direction_keys = set(direction_estimation) - required_direction_keys
        if unknown_direction_keys:
            raise ValueError(
                "direction_estimation contains unknown keys "
                f"{sorted(unknown_direction_keys)!r}."
            )
        if not isinstance(direction_estimation["enabled"], bool):
            raise ValueError("direction_estimation.enabled must be a boolean.")
        environment = payload.get("environment")
        if not isinstance(environment, Mapping):
            raise ValueError("environment must be a JSON object.")
        required_environment_keys = {
            "mode",
            "anchor_prim_path",
            "containment_tolerance_m",
            "resolved",
        }
        missing_environment_keys = required_environment_keys - set(environment)
        if missing_environment_keys:
            raise ValueError(
                "environment is missing required R7.2 keys "
                f"{sorted(missing_environment_keys)!r}."
            )
        unknown_environment_keys = set(environment) - required_environment_keys
        if unknown_environment_keys:
            raise ValueError(
                "environment contains unknown keys "
                f"{sorted(unknown_environment_keys)!r}."
            )
        mode = environment.get("mode")
        if not isinstance(mode, str):
            raise ValueError("environment.mode must be a string.")
        anchor_path = environment.get("anchor_prim_path")
        if anchor_path is not None and (
            not isinstance(anchor_path, str) or not anchor_path.startswith("/")
        ):
            raise ValueError(
                "environment.anchor_prim_path must be null or an absolute USD path."
            )
        tolerance = environment.get("containment_tolerance_m")
        _raise_first(
            ValidationReport(
                check_environment_resolution(
                    mode,
                    "" if anchor_path is None else anchor_path,
                    tolerance,
                    allow_unconfigured=True,
                )
            )
        )
        resolved = environment.get("resolved")
        if resolved is not None and not isinstance(resolved, Mapping):
            raise ValueError("environment.resolved must be null or a JSON object.")
        analytic_acoustics = payload.get("analytic_acoustics")
        if not isinstance(analytic_acoustics, Mapping):
            raise ValueError("analytic_acoustics must be a JSON object.")
        unknown_solver_keys = set(analytic_acoustics) - {
            "max_order",
            "air_absorption",
            "ray_tracing",
        }
        if unknown_solver_keys:
            raise ValueError(
                "analytic_acoustics contains unknown keys "
                f"{sorted(unknown_solver_keys)!r}."
            )
        max_order = analytic_acoustics.get(
            "max_order",
            self.state.analytic_max_order,
        )
        if type(max_order) is not int or max_order < 0:
            raise ValueError(
                "analytic_acoustics.max_order must be non-negative integer."
            )
        for field_name in ("air_absorption", "ray_tracing"):
            value = analytic_acoustics.get(
                field_name,
                getattr(self.state, f"analytic_{field_name}"),
            )
            if type(value) is not bool:
                raise ValueError(f"analytic_acoustics.{field_name} must be a boolean.")
        source = payload.get("source", {})
        if not isinstance(source, Mapping):
            raise ValueError("source must be a JSON object.")
        directivity = resolve_directivity_pattern(
            source.get("directivity", self.state.source_directivity),
            "source.directivity",
        )
        orientation = source.get("orientation_world_quat")
        if orientation is not None:
            quat_from_any(orientation)
        if directivity is not DirectivityPattern.OMNI and orientation is None:
            raise ValueError(
                "source.orientation_world_quat is required for non-omni "
                f"source.directivity {directivity.value!r}."
            )
        db_to_amplitude_gain(
            source.get("gain_db", self.state.source_gain_db),
            "source.gain_db",
        )

    def _parse_sound_profile_config(
        self,
        payload: Any,
    ) -> tuple[tuple[SoundProfile, ...], dict[str, str], str, dict[str, Any]]:
        _raise_first(
            ValidationReport(
                check_sound_profile_config_container(isinstance(payload, Mapping))
            )
        )
        raw_library = payload.get("profile_library")
        _raise_first(
            ValidationReport(
                check_sound_profile_library_present(raw_library is not None)
            )
        )
        raw_mappings = payload.get("object_profile_mappings")
        _raise_first(
            ValidationReport(
                check_object_profile_mappings_present(raw_mappings is not None)
            )
        )
        _raise_first(
            ValidationReport(
                check_object_profile_mappings_mapping(isinstance(raw_mappings, Mapping))
            )
        )
        _raise_first(
            ValidationReport(
                check_sound_profile_library_sequence(
                    isinstance(raw_library, list | tuple)
                )
            )
        )
        profiles = validate_sound_profile_library(
            sound_profile_from_mapping(item) for item in raw_library
        )
        profile_ids = {profile.profile_id for profile in profiles}
        mappings = {
            normalize_object_label(str(label)): str(profile_id).strip()
            for label, profile_id in raw_mappings.items()
            if normalize_object_label(str(label))
        }
        _raise_first(
            ValidationReport(check_object_profile_mappings_non_empty(bool(mappings)))
        )
        for label, profile_id in sorted(mappings.items()):
            if profile_id not in profile_ids:
                _raise_first(
                    ValidationReport(
                        check_object_profile_mapping_known(
                            label,
                            profile_id,
                            False,
                            config=True,
                        )
                    )
                )
        selected_profile_id = payload.get("selected_profile_id")
        selected_profile_id = (
            "" if selected_profile_id is None else str(selected_profile_id).strip()
        )
        _raise_first(
            ValidationReport(
                check_sound_profile_id_known(
                    selected_profile_id,
                    selected_profile_id in profile_ids,
                    config=True,
                )
            )
        )
        applied = payload.get("applied_source_profile")
        return (
            profiles,
            dict(sorted(mappings.items())),
            selected_profile_id,
            dict(applied) if isinstance(applied, Mapping) else {},
        )

    def _parse_rig_profile_config(
        self,
        payload: Any,
    ) -> tuple[tuple[MicrophoneRigProfile, ...], str, dict[str, Any]]:
        _raise_first(
            ValidationReport(
                check_rig_profile_config_container(isinstance(payload, Mapping))
            )
        )
        raw_library = payload.get("rig_library")
        _raise_first(
            ValidationReport(check_rig_profile_library_present(raw_library is not None))
        )
        _raise_first(
            ValidationReport(
                check_rig_profile_library_sequence(
                    isinstance(raw_library, list | tuple)
                )
            )
        )
        profiles = validate_microphone_rig_profile_library(
            microphone_rig_profile_from_mapping(item) for item in raw_library
        )
        profile_ids = {profile.profile_id for profile in profiles}
        selected_rig_id = payload.get("selected_rig_profile_id")
        selected_rig_id = (
            "" if selected_rig_id is None else str(selected_rig_id).strip()
        )
        _raise_first(
            ValidationReport(
                check_rig_profile_id_known(
                    selected_rig_id,
                    selected_rig_id in profile_ids,
                    config=True,
                )
            )
        )
        applied = payload.get("applied_array_rig_profile")
        return (
            profiles,
            selected_rig_id,
            dict(applied) if isinstance(applied, Mapping) else {},
        )
