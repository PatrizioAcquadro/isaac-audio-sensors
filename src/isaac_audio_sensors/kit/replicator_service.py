"""Internal replicator service service."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from isaac_audio_sensors.isaac.replicator import AudioSensorReplicatorRecorder

from ._service import ControllerService
from .paths import _resolve_gui_output_path
from .state import (
    ExtensionActionError,
    _json_ready,
)


class ReplicatorService(ControllerService):
    """Own replicator service behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self.replicator_recorder = None

    def start_replicator(self) -> dict[str, Any] | None:
        """Start the Omniverse-native Replicator writer path."""

        try:
            self.state.replicator_enabled = True
            if self.replicator_recorder is not None:
                self.replicator_recorder.stop()
            output_dir = _resolve_gui_output_path(self.state.replicator_output_dir)
            recorder = AudioSensorReplicatorRecorder(
                output_dir=output_dir,
                writer_name=self.state.replicator_writer_name,
                annotator_name=self.state.replicator_annotator_name,
            )
            self.replicator_recorder = recorder
            status = recorder.start()
            self._apply_replicator_status(status.to_dict())
            self._set_status(f"Replicator recording started at {output_dir}.")
            return self._replicator_status_dict()
        except Exception as exc:
            self.replicator_recorder = None
            self._record_error("Replicator start failed", exc)
            return None

    def flush_replicator(self) -> dict[str, Any] | None:
        """Flush Replicator writer output."""

        try:
            if self.replicator_recorder is None:
                raise ExtensionActionError("Replicator recording is not started.")
            status = self.replicator_recorder.flush()
            self._apply_replicator_status(status.to_dict())
            self._set_status("Replicator recording flushed.")
            return self._replicator_status_dict()
        except Exception as exc:
            self._record_error("Replicator flush failed", exc)
            return None

    def stop_replicator(self) -> dict[str, Any] | None:
        """Stop Replicator recording without disabling configured settings."""

        try:
            if self.replicator_recorder is None:
                self.state.replicator_recording = False
                self.state.replicator_status_message = "Replicator idle."
                return self._replicator_status_dict()
            status = self.replicator_recorder.stop()
            self._apply_replicator_status(status.to_dict())
            self._set_status("Replicator recording stopped.")
            return self._replicator_status_dict()
        except Exception as exc:
            self._record_error("Replicator stop failed", exc)
            return None

    def _write_replicator_frame(self, frame: Any) -> None:
        if self.replicator_recorder is None:
            raise ExtensionActionError(
                "Replicator recording is enabled but not started."
            )
        result = self.replicator_recorder.write_frame(
            frame,
            metadata=self._replicator_frame_metadata(frame),
        )
        self._apply_replicator_status(
            self.replicator_recorder.status.to_dict(),
        )
        self._set_status(
            f"Updated {frame.frame_id}; Replicator wrote {result.json_path}."
        )

    def _replicator_frame_metadata(self, frame: Any) -> dict[str, Any]:
        writer_path = (
            str(_resolve_gui_output_path(self.state.jsonl_trace_path))
            if self.state.trace_enabled
            else None
        )
        return _json_ready(
            {
                "extension_id": self.ext_id,
                "extension_state": {
                    "backend": self.state.backend,
                    "array_prim_path": self.state.array_prim_path,
                    "source_prim_path": self.state.source_prim_path,
                    "source_position_m": self._source_position_from_state(),
                    "selected_profile_id": self.state.selected_profile_id or None,
                    "applied_source_profile": self.state.applied_source_profile or None,
                    "source_attached_to_object": self.state.source_attached_to_object,
                    "attached_object_prim_path": self.state.attached_object_prim_path
                    or None,
                    "source_local_offset_m": self._source_local_offset_from_state(),
                    "latest_source_position_m": self.state.latest_source_position_m,
                    "array_position_m": self._array_position_from_state(),
                    "array_attached_to_object": self.state.array_attached_to_object,
                    "attached_array_object_prim_path": (
                        self.state.attached_array_object_prim_path or None
                    ),
                    "array_local_offset_m": self._array_local_offset_from_state(),
                    "selected_rig_profile_id": (
                        self.state.selected_rig_profile_id or None
                    ),
                    "robot_base_prim_path": self.state.robot_base_prim_path or None,
                    "discovery_roots": self._discovery_roots(),
                    "selected_prim_paths": self.state.selected_prim_paths,
                    "update_period_s": self.state.update_period_s,
                    "max_events": self.state.max_events,
                    "ambiguity_policy": self.state.ambiguity_policy,
                    "debug_overlay_enabled": self.state.debug_overlay_enabled,
                    "occlusion_enabled": self.state.occlusion_enabled,
                },
                "package_recording": {
                    "jsonl_enabled": self.state.trace_enabled,
                    "jsonl_trace_path": writer_path,
                    "latest_frame_export_path": str(
                        _resolve_gui_output_path(self.state.latest_frame_export_path)
                    ),
                    "config_export_path": str(
                        _resolve_gui_output_path(self.state.config_export_path)
                    ),
                },
                "overlay": {
                    "primitive_count": self.state.latest_overlay_primitive_count,
                    "labels": self.state.latest_overlay_labels,
                    "status": self.state.latest_overlay_status,
                    "error": self.state.latest_overlay_error,
                },
                "frame": {
                    "frame_id": frame.frame_id,
                    "backend_id": frame.backend_id,
                    "array_id": frame.array_id,
                    "timestamp_ms": frame.timestamp_ms,
                },
            }
        )

    def _apply_replicator_status(self, status: Mapping[str, Any]) -> None:
        self.state.replicator_recording = bool(status.get("started"))
        self.state.replicator_write_count = int(status.get("write_count", 0))
        self.state.replicator_flush_count = int(status.get("flush_count", 0))
        self.state.replicator_latest_write_path = status.get("latest_write_path")
        self.state.replicator_latest_jsonl_path = status.get("latest_jsonl_path")
        self.state.replicator_latest_error = status.get("latest_error")
        self.state.replicator_output_artifacts = tuple(
            str(item) for item in status.get("output_artifacts", ())
        )
        self.state.replicator_status_message = (
            f"Replicator started={status.get('started')} "
            f"writer_registered={status.get('writer_registered')} "
            f"writes={status.get('write_count', 0)} "
            f"flushes={status.get('flush_count', 0)}"
        )

    def _replicator_status_dict(self) -> dict[str, Any]:
        state = self.state
        if self.replicator_recorder is not None:
            status = self.replicator_recorder.status.to_dict()
            status["enabled"] = state.replicator_enabled
            return status
        output_dir = state.replicator_output_dir
        if output_dir.strip():
            with suppress(Exception):
                output_dir = str(_resolve_gui_output_path(output_dir))
        return {
            "enabled": state.replicator_enabled,
            "writer_name": state.replicator_writer_name,
            "annotator_name": state.replicator_annotator_name,
            "output_dir": output_dir,
            "started": state.replicator_recording,
            "write_count": state.replicator_write_count,
            "flush_count": state.replicator_flush_count,
            "latest_write_path": state.replicator_latest_write_path,
            "latest_jsonl_path": state.replicator_latest_jsonl_path,
            "latest_error": state.replicator_latest_error,
            "output_artifacts": list(state.replicator_output_artifacts),
            "status_message": state.replicator_status_message,
        }
