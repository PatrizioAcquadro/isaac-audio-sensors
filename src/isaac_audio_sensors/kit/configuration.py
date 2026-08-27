"""Internal configuration service."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.directivity import resolve_directivity_pattern
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
from .paths import _resolve_gui_output_path
from .stage_context import (
    _normalize_paths,
    _path_name,
)
from .state import (
    _authored_metadata_from_dict,
    _discovered_summary_from_dict,
    _json_ready,
)
from .validation.checks import (
    check_config_schema_version,
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
            _raise_first(
                ValidationReport(
                    check_config_schema_version(payload.get("schema_version"))
                )
            )
            self._preflight_config_summary(payload)
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
                "schema_version": "ias.omni_extension_binding.v1",
                "backend": state.backend,
                "device": {
                    "device_id": state.device_id,
                    "compute_device": state.compute_device,
                },
                "calibration": {
                    "profile_path": state.calibration_profile_path or None,
                },
                "guided": {
                    "mode_enabled": state.guided_mode_enabled,
                    "preset_id": state.guided_preset_id or None,
                    "recording": {
                        "dataset_id": state.guided_dataset_id,
                        "shard_max_frames": state.guided_shard_max_frames,
                        "shard_episode_aligned": state.guided_record_aligned,
                        "scene_id": state.guided_scene_id,
                        "environment_id": state.guided_environment_id,
                        "split_group": state.guided_split_group,
                        "session_seed": state.guided_session_seed,
                    },
                    "export": {
                        "split_enabled": state.guided_split_enabled,
                        "train_ratio": state.guided_split_train_ratio,
                        "validation_ratio": state.guided_split_validation_ratio,
                        "test_ratio": state.guided_split_test_ratio,
                    },
                },
                "array": {
                    "prim_path": state.array_prim_path,
                    "array_id": state.array_id,
                    "layout_name": state.layout_name,
                    "sample_rate_hz": state.sample_rate_hz,
                    "coordinate_convention": state.coordinate_convention,
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
                    "prim_path": state.source_prim_path,
                    "source_id": state.source_id,
                    "class_label": state.source_class_label,
                    "audio_asset_path": state.audio_asset_path,
                    "position_world": (
                        self._host._authoring._source_position_from_state()
                    ),
                    "local_offset_m": (
                        self._host._authoring._source_local_offset_from_state()
                    ),
                    "start_time_s": state.source_start_time_s,
                    "duration_s": state.source_duration_s,
                    "gain_db": state.source_gain_db,
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
                    "attached": state.source_attached_to_object,
                    "attached_object_prim_path": state.attached_object_prim_path
                    or None,
                    "source_local_offset_m": (
                        self._host._authoring._source_local_offset_from_state()
                    ),
                },
                "array_binding": {
                    "attached": state.array_attached_to_object,
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
                    "update_period_s": state.update_period_s,
                    "max_events": state.max_events,
                    "ambiguity_policy": state.ambiguity_policy,
                    "debug_overlay_enabled": state.debug_overlay_enabled,
                    "occlusion_enabled": state.occlusion_enabled,
                    "writer_enabled": state.trace_enabled,
                    "writer_path": writer_path,
                    "waveform_enabled": state.waveform_enabled,
                    "waveform_dir": state.waveform_dir,
                    "waveform_mode": state.waveform_mode,
                    "follow_viewport_selection": state.follow_viewport_selection,
                    "live_sync_array_pose": state.live_sync_array_pose,
                    "live_sync_source_pose": state.live_sync_source_pose,
                    "usd_debug_enabled": state.usd_debug_enabled,
                    "usd_debug_root": state.usd_debug_root,
                    "room_anchor_prim_path": state.room_anchor_prim_path,
                    "room_out_of_bounds": state.room_out_of_bounds,
                    "room_summary": state.latest_room_summary,
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
                    "backend": state.latest_backend,
                    "detection_count": state.latest_detection_count,
                    "source_prim_path": state.latest_source_prim_path,
                    "source_position_m": state.latest_source_position_m,
                    "bearing_deg": state.latest_bearing_deg,
                    "sector": state.latest_sector,
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
        self._validation.invalidate()
        array = dict(payload.get("array", {}))
        source = dict(payload.get("source", {}))
        sound_profiles = payload.get("sound_profiles")
        rig_profiles = payload.get("microphone_rig_profiles")
        object_binding = dict(payload.get("object_binding", {}))
        array_binding = dict(payload.get("array_binding", {}))
        binding = dict(payload.get("stage_binding", {}))
        lifecycle = dict(payload.get("lifecycle", {}))
        device = dict(payload.get("device", {}))
        calibration = dict(payload.get("calibration", {}))
        recording = dict(payload.get("recording", {}))
        package_recording = dict(recording.get("package_jsonl", {}))
        replicator = dict(recording.get("replicator", {}))
        guided = dict(payload.get("guided", {}))
        guided_recording = dict(guided.get("recording", {}))
        guided_export = dict(guided.get("export", {}))

        self.state.guided_mode_enabled = bool(
            guided.get("mode_enabled", self.state.guided_mode_enabled)
        )
        preset_id = guided.get("preset_id")
        self.state.guided_preset_id = "" if preset_id is None else str(preset_id)
        self.state.guided_dataset_id = str(
            guided_recording.get("dataset_id", self.state.guided_dataset_id)
        )
        self.state.guided_shard_max_frames = int(
            guided_recording.get(
                "shard_max_frames",
                self.state.guided_shard_max_frames,
            )
        )
        self.state.guided_record_aligned = bool(
            guided_recording.get(
                "shard_episode_aligned",
                self.state.guided_record_aligned,
            )
        )
        self.state.guided_scene_id = str(
            guided_recording.get("scene_id", self.state.guided_scene_id)
        )
        self.state.guided_environment_id = str(
            guided_recording.get(
                "environment_id",
                self.state.guided_environment_id,
            )
        )
        self.state.guided_split_group = str(
            guided_recording.get("split_group", self.state.guided_split_group)
        )
        self.state.guided_session_seed = int(
            guided_recording.get(
                "session_seed",
                self.state.guided_session_seed,
            )
        )
        self.state.guided_split_enabled = bool(
            guided_export.get(
                "split_enabled",
                self.state.guided_split_enabled,
            )
        )
        self.state.guided_split_train_ratio = float(
            guided_export.get(
                "train_ratio",
                self.state.guided_split_train_ratio,
            )
        )
        self.state.guided_split_validation_ratio = float(
            guided_export.get(
                "validation_ratio",
                self.state.guided_split_validation_ratio,
            )
        )
        self.state.guided_split_test_ratio = float(
            guided_export.get(
                "test_ratio",
                self.state.guided_split_test_ratio,
            )
        )

        self.state.backend = str(payload.get("backend", self.state.backend))
        self.state.device_id = str(device.get("device_id", self.state.device_id))
        self.state.compute_device = str(
            device.get("compute_device", self.state.compute_device)
        )
        if "profile_path" in calibration:
            selected_calibration = calibration.get("profile_path")
            self.state.calibration_profile_path = (
                "" if selected_calibration is None else str(selected_calibration)
            )
        self.state.array_prim_path = str(
            array.get("prim_path", self.state.array_prim_path)
        )
        self.state.array_id = str(array.get("array_id", self.state.array_id))
        self.state.layout_name = str(array.get("layout_name", self.state.layout_name))
        self.state.sample_rate_hz = int(
            array.get("sample_rate_hz", self.state.sample_rate_hz)
        )
        self.state.coordinate_convention = str(
            array.get("coordinate_convention", self.state.coordinate_convention)
        )
        if array.get("position_world") is not None:
            self._host._authoring._set_array_pose_state(
                array["position_world"], None
            )
        if array.get("orientation_world_quat") is not None:
            (
                self.state.array_roll_deg,
                self.state.array_pitch_deg,
                self.state.array_yaw_deg,
            ) = euler_deg_from_quaternion(
                quat_from_any(array["orientation_world_quat"])
            )
        if array.get("orientation_euler_deg") is not None:
            (
                self.state.array_roll_deg,
                self.state.array_pitch_deg,
                self.state.array_yaw_deg,
            ) = vec3_from_any(array["orientation_euler_deg"])
        self.state.array_attached_to_object = bool(
            array_binding.get("attached", self.state.array_attached_to_object)
        )
        attached_array_path = array_binding.get("attached_object_prim_path")
        if attached_array_path is not None:
            self.state.attached_array_object_prim_path = str(attached_array_path)
        elif not self.state.array_attached_to_object:
            self.state.attached_array_object_prim_path = ""
        array_local_offset = array_binding.get("array_local_offset_m")
        if array_local_offset is not None:
            (
                self.state.array_local_offset_x_m,
                self.state.array_local_offset_y_m,
                self.state.array_local_offset_z_m,
            ) = vec3_from_any(array_local_offset)
        array_local_quat = array_binding.get("array_local_orientation_quat")
        if array_local_quat is not None:
            (
                self.state.array_local_roll_deg,
                self.state.array_local_pitch_deg,
                self.state.array_local_yaw_deg,
            ) = euler_deg_from_quaternion(quat_from_any(array_local_quat))
        if array_binding.get("array_local_euler_deg") is not None:
            (
                self.state.array_local_roll_deg,
                self.state.array_local_pitch_deg,
                self.state.array_local_yaw_deg,
            ) = vec3_from_any(array_binding["array_local_euler_deg"])
        if rig_profiles is not None:
            self._apply_rig_profile_config(rig_profiles)
        self.state.source_prim_path = str(
            source.get("prim_path", self.state.source_prim_path)
        )
        self.state.source_id = str(source.get("source_id", self.state.source_id))
        self.state.source_class_label = str(
            source.get("class_label", self.state.source_class_label)
        )
        self.state.audio_asset_path = str(
            source.get("audio_asset_path", self.state.audio_asset_path)
        )
        if source.get("position_world") is not None:
            self._host._authoring._set_source_position_state(
                source["position_world"]
            )
        local_offset = object_binding.get(
            "source_local_offset_m",
            source.get("local_offset_m"),
        )
        if local_offset is not None:
            (
                self.state.source_local_offset_x_m,
                self.state.source_local_offset_y_m,
                self.state.source_local_offset_z_m,
            ) = vec3_from_any(local_offset)
        self.state.source_start_time_s = float(
            source.get("start_time_s", self.state.source_start_time_s)
        )
        self.state.source_duration_s = float(
            source.get("duration_s", self.state.source_duration_s)
        )
        self.state.source_gain_db = float(
            source.get("gain_db", self.state.source_gain_db)
        )
        self.state.source_loop_count = source.get(
            "loop_count", self.state.source_loop_count
        )
        self.state.source_directivity = resolve_directivity_pattern(
            source.get("directivity", self.state.source_directivity),
            "source.directivity",
        )
        if sound_profiles is not None:
            self._apply_profile_config(sound_profiles)
        self.state.robot_base_prim_path = str(binding.get("robot_base_prim_path") or "")
        self.state.object_prim_path = str(
            object_binding.get("selected_object_prim_path")
            or self.state.object_prim_path
            or ""
        )
        self.state.object_label = str(
            object_binding.get("selected_object_label")
            or (
                _path_name(self.state.object_prim_path)
                if self.state.object_prim_path
                else "none"
            )
        )
        self.state.source_attached_to_object = bool(
            object_binding.get("attached", self.state.source_attached_to_object)
        )
        self.state.attached_object_prim_path = str(
            object_binding.get("attached_object_prim_path")
            or (
                self.state.object_prim_path
                if self.state.source_attached_to_object
                else ""
            )
        )
        roots = binding.get(
            "discovery_roots", self._host._authoring._discovery_roots()
        )
        self.state.discovery_roots_text = ", ".join(str(root) for root in roots)
        self.state.selected_prim_paths = _normalize_paths(
            binding.get("selected_prim_paths", ())
        )
        self.state.discovered_arrays = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_arrays", ())
        )
        self.state.discovered_sources = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_sources", ())
        )
        self.state.discovered_objects = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_objects", ())
        )
        self.state.update_period_s = float(
            lifecycle.get("update_period_s", self.state.update_period_s)
        )
        self.state.max_events = int(lifecycle.get("max_events", self.state.max_events))
        self.state.ambiguity_policy = str(
            lifecycle.get("ambiguity_policy", self.state.ambiguity_policy)
        )
        self.state.debug_overlay_enabled = bool(
            lifecycle.get(
                "debug_overlay_enabled",
                self.state.debug_overlay_enabled,
            )
        )
        self.state.occlusion_enabled = bool(
            lifecycle.get(
                "occlusion_enabled",
                self.state.occlusion_enabled,
            )
        )
        self.state.waveform_enabled = bool(
            lifecycle.get("waveform_enabled", self.state.waveform_enabled)
        )
        self.state.waveform_dir = str(
            lifecycle.get("waveform_dir", self.state.waveform_dir)
            or self.state.waveform_dir
        )
        waveform_mode = str(lifecycle.get("waveform_mode", self.state.waveform_mode))
        if waveform_mode in {"per_frame", "session"}:
            self.state.waveform_mode = waveform_mode
        self.state.follow_viewport_selection = bool(
            lifecycle.get(
                "follow_viewport_selection",
                self.state.follow_viewport_selection,
            )
        )
        self.state.live_sync_array_pose = bool(
            lifecycle.get("live_sync_array_pose", self.state.live_sync_array_pose)
        )
        self.state.live_sync_source_pose = bool(
            lifecycle.get("live_sync_source_pose", self.state.live_sync_source_pose)
        )
        self.state.usd_debug_enabled = bool(
            lifecycle.get("usd_debug_enabled", self.state.usd_debug_enabled)
        )
        self.state.usd_debug_root = str(
            lifecycle.get("usd_debug_root", self.state.usd_debug_root)
            or self.state.usd_debug_root
        )
        self.state.room_anchor_prim_path = str(
            lifecycle.get(
                "room_anchor_prim_path",
                self.state.room_anchor_prim_path,
            )
        )
        self.state.room_out_of_bounds = str(
            lifecycle.get("room_out_of_bounds", self.state.room_out_of_bounds)
            or self.state.room_out_of_bounds
        )
        room_summary = lifecycle.get("room_summary")
        self.state.latest_room_summary = (
            dict(room_summary) if isinstance(room_summary, Mapping) else None
        )
        self.state.trace_enabled = bool(
            package_recording.get(
                "enabled",
                lifecycle.get("writer_enabled", self.state.trace_enabled),
            )
        )
        self.state.jsonl_trace_path = str(
            package_recording.get(
                "path",
                lifecycle.get("writer_path", self.state.jsonl_trace_path),
            )
            or self.state.jsonl_trace_path
        )
        self.state.replicator_enabled = bool(
            replicator.get("enabled", self.state.replicator_enabled)
        )
        self.state.replicator_output_dir = str(
            replicator.get("output_dir", self.state.replicator_output_dir)
        )
        self.state.replicator_writer_name = str(
            replicator.get("writer_name", self.state.replicator_writer_name)
        )
        self.state.replicator_annotator_name = str(
            replicator.get("annotator_name", self.state.replicator_annotator_name)
        )
        self.state.replicator_recording = bool(
            replicator.get("started", self.state.replicator_recording)
        )
        self.state.replicator_write_count = int(
            replicator.get("write_count", self.state.replicator_write_count)
        )
        self.state.replicator_flush_count = int(
            replicator.get("flush_count", self.state.replicator_flush_count)
        )
        self.state.replicator_latest_write_path = replicator.get(
            "latest_write_path",
            self.state.replicator_latest_write_path,
        )
        self.state.replicator_latest_jsonl_path = replicator.get(
            "latest_jsonl_path",
            self.state.replicator_latest_jsonl_path,
        )
        self.state.replicator_latest_error = replicator.get(
            "latest_error",
            self.state.replicator_latest_error,
        )
        self.state.replicator_output_artifacts = tuple(
            str(item) for item in replicator.get("output_artifacts", ())
        )
        self.state.replicator_status_message = str(
            replicator.get(
                "status_message",
                self.state.replicator_status_message,
            )
        )
        self.state.authored_metadata = tuple(
            _authored_metadata_from_dict(item)
            for item in payload.get("authored_metadata", ())
        )
        latest_frame = dict(payload.get("latest_frame", {}))
        self.state.latest_frame_id = latest_frame.get("frame_id")
        self.state.latest_backend = latest_frame.get("backend")
        self.state.latest_detection_count = int(latest_frame.get("detection_count", 0))
        self.state.latest_source_prim_path = latest_frame.get("source_prim_path")
        source_position = latest_frame.get("source_position_m")
        self.state.latest_source_position_m = (
            None if source_position is None else vec3_from_any(source_position)
        )
        self.state.latest_bearing_deg = latest_frame.get("bearing_deg")
        self.state.latest_sector = latest_frame.get("sector")
        self.state.latest_array_prim_path = latest_frame.get("array_prim_path")
        array_position = latest_frame.get("array_position_m")
        self.state.latest_array_position_m = (
            None if array_position is None else vec3_from_any(array_position)
        )
        array_orientation = latest_frame.get("array_orientation_xyzw")
        self.state.latest_array_orientation_xyzw = (
            None if array_orientation is None else quat_from_any(array_orientation)
        )
        self.state.latest_mic_world_positions = {
            str(key): vec3_from_any(value)
            for key, value in dict(latest_frame.get("mic_world_positions", {})).items()
        }
        overlay = dict(payload.get("overlay", {}))
        self.state.latest_overlay_primitive_count = int(
            overlay.get("primitive_count", 0)
        )
        self.state.latest_overlay_labels = tuple(
            str(item) for item in overlay.get("labels", ())
        )
        self.state.latest_overlay_status = str(overlay.get("status", "none"))
        self.state.latest_overlay_error = overlay.get("error")
        self._imported_overlay_primitives = tuple(
            dict(item) for item in overlay.get("primitives", ())
        )

    def _preflight_config_summary(self, payload: Any) -> None:
        """Validate entity gains/directivity and profile libraries before mutation."""

        if not isinstance(payload, Mapping):
            raise ValueError("Config summary must be a JSON object.")
        source = payload.get("source", {})
        if not isinstance(source, Mapping):
            raise ValueError("source must be a JSON object.")
        resolve_directivity_pattern(
            source.get("directivity", self.state.source_directivity),
            "source.directivity",
        )
        db_to_amplitude_gain(
            source.get("gain_db", self.state.source_gain_db),
            "source.gain_db",
        )
        sound_profiles = payload.get("sound_profiles")
        if sound_profiles is not None:
            self._parse_sound_profile_config(sound_profiles)
        rig_profiles = payload.get("microphone_rig_profiles")
        if rig_profiles is not None:
            self._parse_rig_profile_config(rig_profiles)

    def _apply_profile_config(self, payload: Any) -> None:
        profiles, mappings, selected_profile_id, applied = (
            self._parse_sound_profile_config(payload)
        )
        self.state.profile_library = profiles
        self.state.object_profile_mappings = mappings
        self.state.selected_profile_id = selected_profile_id
        self.state.applied_source_profile = applied

    def _apply_rig_profile_config(self, payload: Any) -> None:
        profiles, selected_rig_id, applied = self._parse_rig_profile_config(payload)
        self.state.rig_profile_library = profiles
        self.state.selected_rig_profile_id = selected_rig_id
        self.state.applied_array_rig_profile = applied

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
                check_object_profile_mappings_mapping(
                    isinstance(raw_mappings, Mapping)
                )
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
            ValidationReport(
                check_rig_profile_library_present(raw_library is not None)
            )
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
