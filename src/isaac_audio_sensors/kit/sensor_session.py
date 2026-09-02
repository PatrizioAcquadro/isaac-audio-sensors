"""Internal sensor session service."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.acoustics.environments import free_field_environment
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import append_frame_jsonl, write_frame_trace
from isaac_audio_sensors.core.io.waveforms import (
    ContinuousWaveformWriter,
    FrameWaveformWriter,
    WaveformSink,
    waveform_safe_filename,
)
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioSceneBindingCfg,
)
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
)
from isaac_audio_sensors.isaac.frame_registry import (
    clear_latest_frames,
    publish_latest_frame,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    quat_from_any,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
)
from isaac_audio_sensors.isaac.viz.usd_debug import UsdDebugGeometryAuthor

from ._service import ControllerService, _raise_first
from .audition import AuditionPlayer
from .constants import DEFAULT_FREE_FIELD_ENVIRONMENT_ID
from .formatting import (
    _aggregate_rms_from_frame,
    _frame_is_new,
)
from .instruments import append_detection_history
from .paths import _resolve_gui_output_path
from .stage_context import (
    _stage_has_prim,
)
from .state import (
    ExtensionActionError,
)
from .validation.checks import (
    check_runtime_state,
    check_stage_present,
)
from .validation.results import ValidationReport


class SensorSession(ControllerService):
    """Own sensor session behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self.sensor = None
        self._audition_player = AuditionPlayer()
        self._usd_debug_author = None

    def latest_waveform_data(self) -> Any | None:
        """Load the latest exported waveform for UI preview."""

        paths = self.state.latest_waveform_paths
        if not paths:
            return None
        from isaac_audio_sensors.core.io.wave_read import read_wav

        return read_wav(paths[-1])

    def configure_sensor(
        self,
        *,
        stage: Any | None = None,
        array_prim_path: str | None = None,
        backend: str | None = None,
        update_period_s: float | None = None,
        max_detections: int | None = None,
        debug_draw: bool | None = None,
        occlusion: bool | None = None,
        writer_path: str | Path | None = None,
    ) -> IsaacAudioArraySensor | None:
        """Create or replace the live sensor from the current UI state."""

        try:
            if array_prim_path is not None:
                self.state.array_prim_path = str(array_prim_path)
            if backend is not None:
                self.state.backend = str(backend)
            if update_period_s is not None:
                self.state.update_period_s = float(update_period_s)
            if max_detections is not None:
                self.state.max_detections = int(max_detections)
            if debug_draw is not None:
                self.state.debug_overlay_enabled = bool(debug_draw)
            if occlusion is not None:
                self.state.occlusion_enabled = bool(occlusion)
            if writer_path is not None:
                self.state.trace_enabled = True
                self.state.jsonl_trace_path = str(writer_path)

            self._validation.invalidate()
            stage_obj = self._host._authoring._stage_or_error(stage)
            sensor = self._build_sensor(stage_obj)
            self.close_sensor()
            self.sensor = sensor
            self._host._recording._attach_guided_reset_listener(sensor)
            self.state.sensor_running = False
            self._set_status(
                f"Configured {sensor.backend} sensor for array {sensor.array_id}."
            )
            return sensor
        except Exception as exc:
            self._record_error("Sensor configure failed", exc)
            return None

    def start_sensor(
        self,
        *,
        stage: Any | None = None,
        subscribe_to_update_stream: bool = True,
    ) -> IsaacAudioArraySensor | None:
        """Configure if needed, then start the live sensor."""

        try:
            self._validate_runtime_state()
            if self.sensor is None and self.configure_sensor(stage=stage) is None:
                return None
            self._validate_backend_available()
            assert self.sensor is not None
            self._host._lifecycle._stop_controller_update_subscription()
            self.sensor.start(subscribe_to_update_stream=False)
            try:
                if subscribe_to_update_stream:
                    self._host._lifecycle._start_controller_update_subscription()
            except IsaacIntegrationUnavailable as exc:
                self._set_status(
                    "Started without Kit update subscription: " + str(exc),
                    error=False,
                )
            else:
                self._set_status("Sensor started.")
            self.state.sensor_running = True
            return self.sensor
        except Exception as exc:
            self._record_error("Sensor start failed", exc)
            return None

    def stop_sensor(self) -> None:
        """Stop the live sensor without dropping the latest frame."""

        try:
            self._host._lifecycle._stop_controller_update_subscription()
            if self.sensor is not None:
                self.sensor.stop()
            self.state.sensor_running = False
            workflow = self._host._recording._guided_workflow
            if workflow is not None and workflow.run_status.running:
                workflow.stop_run()
            self._set_status("Sensor stopped.")
        except Exception as exc:
            self._record_error("Sensor stop failed", exc)

    def play_latest_waveform(self) -> str | None:
        """Audition the most recently exported WAV through Kit or the OS."""

        try:
            paths = self.state.latest_waveform_paths
            if not paths:
                raise ExtensionActionError(
                    "No exported waveform yet. Enable WAV Export and run the "
                    "analytic_acoustics backend, then Update."
                )
            status = self._audition_player.play(paths[-1])
            self.state.audition_status = status
            self._set_status(status)
            return status
        except Exception as exc:
            self._record_error("Audition failed", exc)
            return None

    def stop_audition(self) -> str:
        """Stop whatever audition playback is active."""

        status = self._audition_player.stop()
        self.state.audition_status = status
        self._set_status(status)
        return status

    def open_waveform_folder(self) -> Path | None:
        """Open the resolved waveform output folder with the system browser."""

        try:
            import webbrowser

            folder = _resolve_gui_output_path(self.state.waveform_dir)
            folder.mkdir(parents=True, exist_ok=True)
            opened = webbrowser.open(folder.as_uri())
            self._set_status(
                f"Opened waveform folder {folder}."
                if opened
                else f"Waveform folder is {folder} (no system opener available)."
            )
            return folder
        except Exception as exc:
            self._record_error("Open waveform folder failed", exc)
            return None

    def _waveform_dir_or_none(self) -> Path | None:
        if not self.state.waveform_enabled:
            return None
        return _resolve_gui_output_path(self.state.waveform_dir)

    def _waveform_sink_or_none(self, array_id: str) -> WaveformSink | None:
        output_dir = self._waveform_dir_or_none()
        if output_dir is None:
            return None
        if self.state.waveform_mode == "session":
            name = waveform_safe_filename(array_id)
            return ContinuousWaveformWriter(output_dir / f"{name}_session.wav")
        return FrameWaveformWriter(output_dir)

    def clear_usd_debug_geometry(self) -> tuple[str, ...] | None:
        """Remove the authored debug subtree from the current stage."""

        try:
            context = self._host.current_stage_context()
            _raise_first(
                ValidationReport(check_stage_present(context.stage is not None))
            )
            if self._usd_debug_author is not None:
                self._usd_debug_author.clear(context.stage)
            self.state.latest_usd_debug_prim_paths = ()
            self._set_status(
                f"Cleared USD debug geometry under {self.state.usd_debug_root}."
            )
            return ()
        except Exception as exc:
            self._record_error("USD debug clear failed", exc)
            return None

    def _update_usd_debug_geometry(self, primitives: tuple[Any, ...]) -> None:
        if not self.state.usd_debug_enabled:
            if self.state.latest_usd_debug_prim_paths:
                self.clear_usd_debug_geometry()
            return
        try:
            context = self._host.current_stage_context()
            if context.stage is None:
                return
            author = self._usd_debug_author
            if author is None or author.root != self.state.usd_debug_root:
                if author is not None:
                    with suppress(Exception):
                        author.clear(context.stage)
                author = UsdDebugGeometryAuthor(root=self.state.usd_debug_root)
                self._usd_debug_author = author
            self.state.latest_usd_debug_prim_paths = author.author(
                context.stage,
                primitives,
            )
        except Exception as exc:
            self.state.latest_usd_debug_prim_paths = ()
            self._record_error("USD debug authoring failed", exc)

    def _environment_inputs(
        self,
    ) -> tuple[IsaacEnvironmentResolutionCfg, Any | None]:
        """Translate the explicit Kit mode to the Isaac resolution contract."""

        state = self.state
        state.latest_environment_summary = None
        tolerance = state.environment_containment_tolerance_m
        if state.environment_resolution_mode == "manual_free_field":
            return (
                IsaacEnvironmentResolutionCfg(
                    mode="manual",
                    containment_tolerance_m=tolerance,
                ),
                free_field_environment(
                    environment_id=DEFAULT_FREE_FIELD_ENVIRONMENT_ID
                ),
            )
        if state.environment_resolution_mode == "anchor":
            return (
                IsaacEnvironmentResolutionCfg(
                    mode="anchor",
                    anchor_prim_path=state.environment_anchor_prim_path.strip(),
                    containment_tolerance_m=tolerance,
                ),
                None,
            )
        return (
            IsaacEnvironmentResolutionCfg(
                mode=state.environment_resolution_mode,
                candidate_roots=self._host._authoring._discovery_roots(),
                containment_tolerance_m=tolerance,
            ),
            None,
        )

    def _record_environment_summary(self, sensor: IsaacAudioArraySensor) -> None:
        state = self.state
        environment = sensor.environment
        diagnostics = sensor._latest_stage_diagnostics or {}
        resolution = dict(diagnostics.get("environment_resolution", {}))
        state.latest_environment_summary = {
            "mode": state.environment_resolution_mode,
            "environment_id": environment.environment_id,
            "kind": environment.kind,
            "dimensions_m": environment.dimensions_m,
            "position_world": environment.world_pose.position_m,
            "orientation_world_quat": environment.world_pose.orientation_xyzw,
            "absorption": (
                environment.surfaces[0].absorption if environment.surfaces else None
            ),
            "absorption_provenance": resolution.get("absorption_provenance"),
            "anchor_prim_path": (
                state.environment_anchor_prim_path.strip()
                if state.environment_resolution_mode == "anchor"
                else None
            ),
            "selected_prim_path": resolution.get("selected_prim_path"),
            "priority": resolution.get("priority"),
            "candidate_count": resolution.get("candidate_count", 0),
            "containment_tolerance_m": (state.environment_containment_tolerance_m),
            "analytic_acoustics": {
                "max_order": state.analytic_max_order,
                "air_absorption": state.analytic_air_absorption,
                "ray_tracing": state.analytic_ray_tracing,
            },
        }

    def update_sensor(self, *, force: bool = True) -> Any | None:
        """Force one frame and update UI/export state."""

        try:
            if self.sensor is None:
                raise ExtensionActionError("Sensor is not configured.")
            previous_frame = self.sensor.latest_frame
            self._host._authoring._validate_attached_object_available(self.sensor.stage)
            self._host._authoring._validate_attached_array_available(self.sensor.stage)
            if self.state.array_prim_path.strip():
                self.sensor.array_prim_path = self.state.array_prim_path
            self.sensor.source_prim_path = (
                self.state.source_prim_path
                if self.state.source_attached_to_object
                and self.state.source_prim_path.strip()
                else None
            )
            frame = self.sensor.update(force=force)
            if isinstance(self.sensor, IsaacAudioArraySensor):
                self._record_environment_summary(self.sensor)
            is_new = _frame_is_new(previous_frame, frame)
            if self.state.trace_enabled and is_new:
                append_frame_jsonl(
                    frame,
                    _resolve_gui_output_path(self.state.jsonl_trace_path),
                )
            self._record_latest_frame(frame)
            if self.state.replicator_enabled and (force or is_new):
                self._host._replicator._write_replicator_frame(frame)
            return frame
        except Exception as exc:
            self._record_error("Sensor update failed", exc)
            return None

    def export_latest_frame(self, path: str | Path | None = None) -> Path | None:
        """Write the latest frame using deterministic v1 trace serialization."""

        try:
            if self.sensor is None or self.sensor.latest_frame is None:
                raise ExtensionActionError("No latest frame is available to export.")
            output_path = _resolve_gui_output_path(
                path or self.state.latest_frame_export_path
            )
            output = write_frame_trace(
                self.sensor.latest_frame,
                output_path,
            )
            self._set_status(f"Exported latest frame to {output}.")
            return output
        except Exception as exc:
            self._record_error("Latest-frame export failed", exc)
            return None

    def close_sensor(self) -> None:
        """Close the live sensor and writer/debug handles."""

        self._host._lifecycle._stop_controller_update_subscription()
        if self.sensor is not None:
            self.sensor.close()
        self.sensor = None
        self.state.sensor_running = False
        clear_latest_frames()

    def _build_sensor(self, stage: Any) -> IsaacAudioArraySensor:
        state = self.state
        self._validate_runtime_state()
        environment_resolution_cfg, environment = self._environment_inputs()
        explicit_array_available = bool(
            state.array_prim_path.strip()
        ) and _stage_has_prim(stage, state.array_prim_path)
        if explicit_array_available:
            explicit_source = (
                state.source_prim_path
                if state.source_attached_to_object and state.source_prim_path.strip()
                else None
            )
            sensor = IsaacAudioArraySensor.from_stage(
                stage=stage,
                array_prim_path=state.array_prim_path,
                source_prim_path=explicit_source,
                robot_base_prim_path=state.robot_base_prim_path or None,
                backend=state.backend,
                update_period_s=state.update_period_s,
                max_detections=state.max_detections,
                doa_estimator=state.doa_estimator,
                debug_draw=state.debug_overlay_enabled,
                occlusion_enabled=state.occlusion_enabled,
                environment=environment,
                environment_resolution_cfg=environment_resolution_cfg,
                analytic_max_order=state.analytic_max_order,
                analytic_air_absorption=(state.analytic_air_absorption),
                analytic_ray_tracing=state.analytic_ray_tracing,
            )
        else:
            binding_cfg = IsaacAudioSceneBindingCfg(
                discovery_roots=self._host._authoring._discovery_roots(),
                robot_base_prim_path=state.robot_base_prim_path or None,
                required_arrays=True,
                required_sources=False,
                preferred_array=self._host._authoring._preferred_discovered_array(),
                preferred_source=None,
            )
            sensor = IsaacAudioArraySensor.from_discovered_stage(
                stage=stage,
                binding_cfg=binding_cfg,
                backend=state.backend,
                update_period_s=state.update_period_s,
                max_detections=state.max_detections,
                doa_estimator=state.doa_estimator,
                debug_draw=state.debug_overlay_enabled,
                occlusion_enabled=state.occlusion_enabled,
                environment=environment,
                environment_resolution_cfg=environment_resolution_cfg,
                analytic_max_order=state.analytic_max_order,
                analytic_air_absorption=(state.analytic_air_absorption),
                analytic_ray_tracing=state.analytic_ray_tracing,
            )
        sensor.waveform_sink = self._waveform_sink_or_none(sensor.array_id)
        if sensor.array_prim_path:
            state.array_prim_path = sensor.array_prim_path
        state.array_id = sensor.array_id
        self._record_environment_summary(sensor)
        return sensor

    def _validate_runtime_state(self) -> None:
        _raise_first(ValidationReport(check_runtime_state(self.state)))

    def _validate_backend_available(self) -> None:
        _raise_first(self._validation.validate_backend_available(self.state.backend))

    def _calibration_array_facts(self) -> dict[str, Any]:
        return {
            "array_id": self.state.array_id,
            "device_id": self.state.device_id,
            "microphones": microphone_layout(self.state.layout_name),
            "sample_rate_hz": self.state.sample_rate_hz,
            "coordinate_convention": self.state.coordinate_convention,
        }

    def _record_latest_frame(self, frame: Any) -> None:
        detections = tuple(frame.detections)
        first = detections[0] if detections else None
        self.state.latest_frame_id = frame.frame_id
        self.state.latest_detection_count = len(detections)
        self.state.latest_backend = frame.backend_id
        self.state.latest_source_prim_path = self._latest_source_prim_path(first)
        self.state.latest_source_position_m = (
            None
            if first is None or first.source_pose is None
            else vec3_from_any(first.source_pose.position_m)
        )
        self.state.latest_bearing_deg = (
            None if first is None else first.doa.estimated_bearing_deg
        )
        self.state.latest_sector = None if first is None else first.doa.bearing_sector
        self.state.latest_bearing_confidence = (
            None if first is None else first.doa.bearing_confidence
        )
        self.state.latest_candidate_bearings = (
            () if first is None else tuple(first.doa.candidate_bearing_deg)
        )
        self.state.latest_occluded = (
            None if first is None else bool(getattr(first, "occluded", False))
        )
        self.state.latest_timestamp_ms = getattr(frame, "timestamp_ms", None)
        self.state.latest_waveform_paths = tuple(
            str(path) for path in (getattr(frame, "waveform_paths", ()) or ())
        )
        append_detection_history(self.state.detection_history, frame)
        array_pose = getattr(frame, "array_pose", None)
        self.state.latest_array_prim_path = (
            None
            if self.sensor is None
            else getattr(self.sensor, "array_prim_path", None)
        ) or (self.state.array_prim_path or None)
        self.state.latest_array_position_m = (
            None if array_pose is None else vec3_from_any(array_pose.position_m)
        )
        array_orientation = (
            None
            if array_pose is None
            else getattr(array_pose, "orientation_xyzw", None)
        )
        self.state.latest_array_orientation_xyzw = (
            None if array_orientation is None else quat_from_any(array_orientation)
        )
        self.state.latest_mic_world_positions = self._latest_mic_world_positions()
        self.state.latest_aggregate_rms = _aggregate_rms_from_frame(frame)
        primitives: tuple[DebugPrimitive, ...] = (
            () if self.sensor is None else tuple(self.sensor.latest_debug_primitives)
        )
        self.state.latest_overlay_primitive_count = len(primitives)
        self.state.latest_overlay_labels = tuple(
            primitive.label for primitive in primitives
        )
        self._record_overlay_status()
        self._update_usd_debug_geometry(primitives)
        publish_latest_frame(
            self.state.latest_array_prim_path or frame.array_id,
            frame,
        )
        workflow = self._host._recording._guided_workflow
        if workflow is not None:
            run_status = workflow.run_status
            if (
                run_status.configured
                and run_status.running
                and frame.frame_id != self._host._recording._guided_last_run_frame_id
            ):
                self._host._recording._guided_last_run_frame_id = str(frame.frame_id)
                workflow.observe_run_frame(getattr(frame, "timestamp_ms", None))
            self._host._recording._guided_record_frame(frame)
        self._set_status(
            f"Updated {frame.frame_id}: {len(detections)} detection(s), "
            f"{len(primitives)} overlay primitive(s)."
        )

    def _latest_mic_world_positions(self) -> dict[str, tuple[float, float, float]]:
        if self.sensor is None:
            return {}
        sensor_spec = self.sensor.latest_array_spec
        if sensor_spec is None:
            return {}
        try:
            return dict(microphone_world_positions(sensor_spec))
        except Exception:
            return {}

    def _latest_source_prim_path(self, detection: Any | None) -> str | None:
        if detection is None:
            return None
        scene = None if self.sensor is None else self.sensor.latest_scene
        if scene is not None and detection.source_id is not None:
            for source in scene.sources:
                if source.source_id == detection.source_id and source.prim_path:
                    return source.prim_path
        return self.state.source_prim_path or None

    def _record_overlay_status(self) -> None:
        if self.sensor is None or self.sensor.debug_drawer is None:
            self.state.latest_overlay_status = (
                "disabled"
                if not self.state.debug_overlay_enabled
                else "serialized_without_debug_drawer"
            )
            self.state.latest_overlay_error = None
            return
        drawer = self.sensor.debug_drawer
        self.state.latest_overlay_status = str(
            getattr(drawer, "last_status", "serialized")
        )
        latest_error = getattr(drawer, "last_error", None)
        self.state.latest_overlay_error = (
            None if latest_error is None else str(latest_error)
        )
