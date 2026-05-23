"""Import-safe Omniverse extension controller and UI model."""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    KNOWN_BACKENDS,
    TDOA_AMBIGUITY_POLICIES,
)
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import write_frame_trace
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.pose_resolver import prim_path
from isaac_audio_sensors.isaac.replicator import (
    DEFAULT_REPLICATOR_ANNOTATOR_NAME,
    DEFAULT_REPLICATOR_WRITER_NAME,
    AudioSensorReplicatorRecorder,
)
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    create_sound_prim,
    get_or_define_prim,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
    debug_primitives_to_dicts,
)

BACKEND_CHOICES = tuple(
    backend for backend in ("geometry_only", "tdoa_synthetic", "room_acoustics")
    if backend in KNOWN_BACKENDS
)
AMBIGUITY_POLICY_CHOICES = tuple(sorted(TDOA_AMBIGUITY_POLICIES))
LAYOUT_CHOICES = ("quad_front", "quad_cross", "stereo_y", "two_mic_y", "mono")
DEFAULT_OUTPUT_ROOT = Path("outputs/isaac_audio_sensors")


class ExtensionActionError(RuntimeError):
    """User-facing extension action failure."""


@dataclass(frozen=True, slots=True)
class CurrentStageContext:
    """Current Omni stage and selected prim paths."""

    stage: Any | None
    selected_prim_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveredPrimSummary:
    """Compact discovered array/source record for UI and export."""

    id: str
    prim_path: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredMetadataSummary:
    """Record of metadata authored through the extension UI."""

    kind: str
    prim_path: str
    id: str
    attributes: Mapping[str, Any]


@dataclass(slots=True)
class ExtensionUiState:
    """Pure-Python state backing the reference extension UX."""

    selected_prim_paths: tuple[str, ...] = ()
    stage_status: str = "No stage checked."
    status_message: str = "Ready."
    error_message: str | None = None

    array_prim_path: str = "/World/Rig/AudioArray"
    array_id: str = "rig_front"
    layout_name: str = "quad_front"
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    author_child_microphones: bool = True

    source_prim_path: str = "/World/Sources/SpeakerA"
    source_id: str = "speaker_a"
    source_class_label: str = "Speech"
    audio_asset_path: str = "generated://impulse"
    source_start_time_s: float = 0.0
    source_duration_s: float = 1.0
    source_gain_db: float = 0.0

    robot_base_prim_path: str = ""
    discovery_roots_text: str = "/World"
    backend: str = "tdoa_synthetic"
    ambiguity_policy: str = "none"
    update_period_s: float = 0.05
    max_events: int = 8
    debug_overlay_enabled: bool = True
    trace_enabled: bool = True
    jsonl_trace_path: str = str(DEFAULT_OUTPUT_ROOT / "extension_trace.frames.jsonl")
    latest_frame_export_path: str = str(
        DEFAULT_OUTPUT_ROOT / "extension_latest_frame.json"
    )
    config_export_path: str = str(DEFAULT_OUTPUT_ROOT / "extension_binding.json")
    config_import_path: str = str(DEFAULT_OUTPUT_ROOT / "extension_binding.json")

    replicator_enabled: bool = False
    replicator_output_dir: str = str(DEFAULT_OUTPUT_ROOT / "replicator")
    replicator_writer_name: str = DEFAULT_REPLICATOR_WRITER_NAME
    replicator_annotator_name: str = DEFAULT_REPLICATOR_ANNOTATOR_NAME
    replicator_recording: bool = False
    replicator_status_message: str = "Replicator idle."
    replicator_write_count: int = 0
    replicator_flush_count: int = 0
    replicator_latest_write_path: str | None = None
    replicator_latest_jsonl_path: str | None = None
    replicator_latest_error: str | None = None
    replicator_output_artifacts: tuple[str, ...] = ()

    discovered_arrays: tuple[DiscoveredPrimSummary, ...] = ()
    discovered_sources: tuple[DiscoveredPrimSummary, ...] = ()
    authored_metadata: tuple[AuthoredMetadataSummary, ...] = ()

    sensor_running: bool = False
    latest_frame_id: str | None = None
    latest_detection_count: int = 0
    latest_backend: str | None = None
    latest_bearing_deg: float | None = None
    latest_sector: str | None = None
    latest_overlay_primitive_count: int = 0
    latest_overlay_labels: tuple[str, ...] = ()
    latest_overlay_status: str = "none"
    latest_overlay_error: str | None = None


class ExtensionController:
    """Stateful controller for the Isaac Audio Sensors reference extension."""

    def __init__(
        self,
        *,
        state: ExtensionUiState | None = None,
        stage_context_provider: Callable[[], CurrentStageContext] | None = None,
    ) -> None:
        self.state = state or ExtensionUiState()
        self.stage_context_provider = stage_context_provider
        self.sensor: IsaacAudioArraySensor | None = None
        self.replicator_recorder: AudioSensorReplicatorRecorder | None = None
        self.ext_id: str | None = None
        self.window: Any | None = None
        self.ui_available = False
        self._ui_window: OmniReferenceWindow | None = None

    def on_startup(self, ext_id: str) -> None:
        """Initialize the import-safe controller and lazily build Kit UI."""

        self.ext_id = ext_id
        self._set_status(f"Loaded {ext_id}.")
        self.build_ui_if_available()

    def on_shutdown(self) -> None:
        """Stop live work and release UI/debug resources."""

        self.stop_replicator()
        self.close_sensor()
        self._ui_window = None
        self.window = None
        self.ui_available = False
        self.ext_id = None
        self._set_status("Shutdown complete.")

    def build_ui_if_available(self) -> Any | None:
        """Build the Omniverse UI only when ``omni.ui`` imports."""

        try:
            ui = importlib.import_module("omni.ui")
        except ImportError:
            self.ui_available = False
            return None
        try:
            self._ui_window = OmniReferenceWindow(self, ui)
            self.window = self._ui_window.build()
            self.ui_available = True
            return self.window
        except Exception as exc:
            self.ui_available = False
            self._record_error("UI build failed", exc)
            return None

    def refresh_stage_selection(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        """Refresh current selected prim paths from explicit args or Omni."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            if context.stage is None:
                raise ExtensionActionError("No USD stage is open.")
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
            _validate_abs_path(state.array_prim_path, "array_prim_path")
            if state.layout_name not in LAYOUT_CHOICES:
                raise ExtensionActionError(
                    f"Unknown array layout {state.layout_name!r}."
                )
            if int(state.sample_rate_hz) <= 0:
                raise ExtensionActionError("sample_rate_hz must be positive.")

            prim = get_or_define_prim(
                stage_obj,
                prim_path=state.array_prim_path,
                prim_type="Xform",
            )
            microphones = microphone_layout(state.layout_name)
            attrs = attach_microphone_array_attrs(
                prim,
                array_id=state.array_id.strip() or _path_name(state.array_prim_path),
                sample_rate_hz=int(state.sample_rate_hz),
                coordinate_convention=state.coordinate_convention,
                layout_name=state.layout_name,
                position_world=(
                    None if _prim_has_pose(prim) else (0.0, 0.0, 0.0)
                ),
                orientation_world_quat=(
                    None if _prim_has_orientation(prim) else (0.0, 0.0, 0.0, 1.0)
                ),
                microphone_relative_offsets_m=tuple(
                    microphone.relative_position_m for microphone in microphones
                ),
                microphone_ids=tuple(microphone.mic_id for microphone in microphones),
            )
            if state.author_child_microphones:
                self._author_child_microphones(
                    stage_obj,
                    array_path=state.array_prim_path,
                    microphones=microphones,
                )

            record = AuthoredMetadataSummary(
                kind="array",
                prim_path=state.array_prim_path,
                id=str(attrs["ias:array_id"]),
                attributes=_jsonable_mapping(attrs),
            )
            self._append_authored_record(record)
            self._set_status(
                f"Authored array {record.id} at {state.array_prim_path}."
            )
            return record
        except Exception as exc:
            self._record_error("Array authoring failed", exc)
            return None

    def author_source(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Create or configure source metadata on the current target prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            _validate_abs_path(state.source_prim_path, "source_prim_path")
            if state.audio_asset_path.strip() == "":
                raise ExtensionActionError("audio_asset_path must be non-empty.")
            if state.source_duration_s <= 0.0:
                raise ExtensionActionError("source_duration_s must be positive.")
            if not math.isfinite(state.source_start_time_s):
                raise ExtensionActionError("source_start_time_s must be finite.")

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
                position_world=(
                    None if _prim_has_pose(prim) else (2.0, 0.0, 0.0)
                ),
                orientation_world_quat=(
                    None if _prim_has_orientation(prim) else (0.0, 0.0, 0.0, 1.0)
                ),
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity="omni",
            )
            authored = AuthoredMetadataSummary(
                kind="source",
                prim_path=state.source_prim_path,
                id=str(attrs["ias:source_id"]),
                attributes=_jsonable_mapping({**record.attributes, **attrs}),
            )
            self._append_authored_record(authored)
            self._set_status(
                f"Authored source {authored.id} at {state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source authoring failed", exc)
            return None

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
            self._set_status(
                "Discovery found "
                f"{len(result.arrays)} array(s), {len(result.sources)} source(s)."
            )
            return (*self.state.discovered_arrays, *self.state.discovered_sources)
        except Exception as exc:
            self._record_error("Discovery failed", exc)
            return ()

    def configure_sensor(
        self,
        *,
        stage: Any | None = None,
        array_prim_path: str | None = None,
        backend: str | None = None,
        update_period_s: float | None = None,
        max_events: int | None = None,
        debug_draw: bool | None = None,
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
            if max_events is not None:
                self.state.max_events = int(max_events)
            if debug_draw is not None:
                self.state.debug_overlay_enabled = bool(debug_draw)
            if writer_path is not None:
                self.state.trace_enabled = True
                self.state.jsonl_trace_path = str(writer_path)

            stage_obj = self._stage_or_error(stage)
            sensor = self._build_sensor(stage_obj)
            self.close_sensor()
            self.sensor = sensor
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
            if self.sensor is None and self.configure_sensor(stage=stage) is None:
                return None
            assert self.sensor is not None
            try:
                self.sensor.start(
                    subscribe_to_update_stream=subscribe_to_update_stream,
                )
            except IsaacIntegrationUnavailable as exc:
                self.sensor.start(subscribe_to_update_stream=False)
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
            if self.sensor is not None:
                self.sensor.stop()
            self.state.sensor_running = False
            self._set_status("Sensor stopped.")
        except Exception as exc:
            self._record_error("Sensor stop failed", exc)

    def update_sensor(self, *, force: bool = True) -> Any | None:
        """Force one frame and update UI/export state."""

        try:
            if self.sensor is None:
                raise ExtensionActionError("Sensor is not configured.")
            frame = self.sensor.update(force=force)
            self._record_latest_frame(frame)
            if self.state.replicator_enabled:
                self._write_replicator_frame(frame)
            return frame
        except Exception as exc:
            self._record_error("Sensor update failed", exc)
            return None

    def export_latest_frame(self, path: str | Path | None = None) -> Path | None:
        """Write the latest frame using deterministic v1 trace serialization."""

        try:
            if self.sensor is None or self.sensor.latest_frame is None:
                raise ExtensionActionError("No latest frame is available to export.")
            output = write_frame_trace(
                self.sensor.latest_frame,
                path or self.state.latest_frame_export_path,
            )
            self._set_status(f"Exported latest frame to {output}.")
            return output
        except Exception as exc:
            self._record_error("Latest-frame export failed", exc)
            return None

    def export_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Write a reusable stage-binding/config summary."""

        try:
            output = Path(path or self.state.config_export_path)
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
            input_path = Path(path or self.state.config_import_path)
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "ias.omni_extension_binding.v1":
                raise ExtensionActionError(
                    "Config import requires schema_version "
                    "'ias.omni_extension_binding.v1'."
                )
            self._apply_config_summary(payload)
            self.state.config_import_path = str(input_path)
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
            if self.sensor is None
            else tuple(self.sensor.latest_debug_primitives)
        )
        return _json_ready(
            {
                "schema_version": "ias.omni_extension_binding.v1",
                "backend": state.backend,
                "array": {
                    "prim_path": state.array_prim_path,
                    "array_id": state.array_id,
                    "layout_name": state.layout_name,
                    "sample_rate_hz": state.sample_rate_hz,
                    "coordinate_convention": state.coordinate_convention,
                },
                "source": {
                    "prim_path": state.source_prim_path,
                    "source_id": state.source_id,
                    "class_label": state.source_class_label,
                    "audio_asset_path": state.audio_asset_path,
                    "start_time_s": state.source_start_time_s,
                    "duration_s": state.source_duration_s,
                    "gain_db": state.source_gain_db,
                },
                "stage_binding": {
                    "robot_base_prim_path": state.robot_base_prim_path or None,
                    "discovery_roots": self._discovery_roots(),
                    "preferred_source": state.source_id or None,
                    "selected_prim_paths": state.selected_prim_paths,
                    "discovered_arrays": state.discovered_arrays,
                    "discovered_sources": state.discovered_sources,
                },
                "lifecycle": {
                    "update_period_s": state.update_period_s,
                    "max_events": state.max_events,
                    "ambiguity_policy": state.ambiguity_policy,
                    "debug_overlay_enabled": state.debug_overlay_enabled,
                    "writer_enabled": state.trace_enabled,
                    "writer_path": (
                        state.jsonl_trace_path if state.trace_enabled else None
                    ),
                    "runtime_options": {
                        "subscribe_to_update_stream_default": True,
                        "import_safe_outside_isaac": True,
                    },
                },
                "recording": {
                    "package_jsonl": {
                        "enabled": state.trace_enabled,
                        "path": state.jsonl_trace_path,
                    },
                    "replicator": self._replicator_status_dict(),
                },
                "authored_metadata": state.authored_metadata,
                "latest_frame": {
                    "frame_id": state.latest_frame_id,
                    "backend": state.latest_backend,
                    "detection_count": state.latest_detection_count,
                    "bearing_deg": state.latest_bearing_deg,
                    "sector": state.latest_sector,
                },
                "overlay": {
                    "primitive_count": state.latest_overlay_primitive_count,
                    "labels": state.latest_overlay_labels,
                    "status": state.latest_overlay_status,
                    "error": state.latest_overlay_error,
                    "primitives": debug_primitives_to_dicts(primitives),
                },
            }
        )

    def start_replicator(self) -> dict[str, Any] | None:
        """Start the Omniverse-native Replicator writer path."""

        try:
            self.state.replicator_enabled = True
            if self.replicator_recorder is not None:
                self.replicator_recorder.stop()
            recorder = AudioSensorReplicatorRecorder(
                output_dir=self.state.replicator_output_dir,
                writer_name=self.state.replicator_writer_name,
                annotator_name=self.state.replicator_annotator_name,
            )
            self.replicator_recorder = recorder
            status = recorder.start()
            self._apply_replicator_status(status.to_dict())
            self._set_status(
                "Replicator recording started at "
                f"{self.state.replicator_output_dir}."
            )
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

    def close_sensor(self) -> None:
        """Close the live sensor and writer/debug handles."""

        if self.sensor is not None:
            self.sensor.close()
        self.sensor = None
        self.state.sensor_running = False

    def _build_sensor(self, stage: Any) -> IsaacAudioArraySensor:
        state = self.state
        self._validate_runtime_state()
        writer_path = state.jsonl_trace_path if state.trace_enabled else None
        explicit_array_available = (
            bool(state.array_prim_path.strip())
            and _stage_has_prim(stage, state.array_prim_path)
        )
        if explicit_array_available:
            return IsaacAudioArraySensor.from_stage(
                stage=stage,
                array_prim_path=state.array_prim_path,
                robot_base_prim_path=state.robot_base_prim_path or None,
                backend=state.backend,
                update_period_s=state.update_period_s,
                max_events=state.max_events,
                ambiguity_policy=state.ambiguity_policy,
                debug_draw=state.debug_overlay_enabled,
                writer_path=writer_path,
            )

        binding_cfg = IsaacAudioSceneBindingCfg(
            discovery_roots=self._discovery_roots(),
            robot_base_prim_path=state.robot_base_prim_path or None,
            required_arrays=True,
            required_sources=False,
            preferred_array=self._preferred_discovered_array(),
            preferred_source=None,
        )
        sensor = IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            binding_cfg=binding_cfg,
            backend=state.backend,
            update_period_s=state.update_period_s,
            max_events=state.max_events,
            ambiguity_policy=state.ambiguity_policy,
            debug_draw=state.debug_overlay_enabled,
            writer_path=writer_path,
        )
        if sensor.stage_snapshot is not None:
            selected = sensor.stage_snapshot.array_by_id(sensor.array_id)
            if selected.prim_path:
                state.array_prim_path = selected.prim_path
            state.array_id = sensor.array_id
        return sensor

    def _validate_runtime_state(self) -> None:
        state = self.state
        if state.backend not in BACKEND_CHOICES:
            raise ExtensionActionError(
                f"Backend {state.backend!r} is not an implemented v1 backend."
            )
        if state.ambiguity_policy not in AMBIGUITY_POLICY_CHOICES:
            raise ExtensionActionError(
                f"Ambiguity policy {state.ambiguity_policy!r} is not supported."
            )
        if state.update_period_s <= 0.0 or not math.isfinite(state.update_period_s):
            raise ExtensionActionError("update_period_s must be positive and finite.")
        if state.max_events < 0:
            raise ExtensionActionError("max_events must be non-negative.")
        if state.array_prim_path.strip():
            _validate_abs_path(state.array_prim_path, "array_prim_path")
        if state.robot_base_prim_path.strip():
            _validate_abs_path(state.robot_base_prim_path, "robot_base_prim_path")

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

    def _stage_or_error(self, stage: Any | None) -> Any:
        context = self._context(stage=stage)
        if context.stage is None:
            raise ExtensionActionError("No USD stage is open.")
        self.state.selected_prim_paths = context.selected_prim_paths
        return context.stage

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
            if not paths:
                raise ExtensionActionError("No prim is selected.")
            return paths[0]
        except Exception as exc:
            self._record_error("Selection binding failed", exc)
            return None

    def _append_authored_record(self, record: AuthoredMetadataSummary) -> None:
        self.state.authored_metadata = (*self.state.authored_metadata, record)

    def _record_latest_frame(self, frame: Any) -> None:
        detections = tuple(frame.detections)
        first = detections[0] if detections else None
        self.state.latest_frame_id = frame.frame_id
        self.state.latest_detection_count = len(detections)
        self.state.latest_backend = frame.backend_id
        self.state.latest_bearing_deg = (
            None if first is None else first.doa.estimated_bearing_deg
        )
        self.state.latest_sector = None if first is None else first.doa.bearing_sector
        primitives: tuple[DebugPrimitive, ...] = (
            ()
            if self.sensor is None
            else tuple(self.sensor.latest_debug_primitives)
        )
        self.state.latest_overlay_primitive_count = len(primitives)
        self.state.latest_overlay_labels = tuple(
            primitive.label for primitive in primitives
        )
        self._record_overlay_status()
        self._set_status(
            f"Updated {frame.frame_id}: {len(detections)} detection(s), "
            f"{len(primitives)} overlay primitive(s)."
        )

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
        self.state.latest_overlay_error = None if latest_error is None else str(
            latest_error
        )

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
        return _json_ready(
            {
                "extension_id": self.ext_id,
                "extension_state": {
                    "backend": self.state.backend,
                    "array_prim_path": self.state.array_prim_path,
                    "source_prim_path": self.state.source_prim_path,
                    "robot_base_prim_path": self.state.robot_base_prim_path or None,
                    "discovery_roots": self._discovery_roots(),
                    "selected_prim_paths": self.state.selected_prim_paths,
                    "update_period_s": self.state.update_period_s,
                    "max_events": self.state.max_events,
                    "ambiguity_policy": self.state.ambiguity_policy,
                    "debug_overlay_enabled": self.state.debug_overlay_enabled,
                },
                "package_recording": {
                    "jsonl_enabled": self.state.trace_enabled,
                    "jsonl_trace_path": self.state.jsonl_trace_path,
                    "latest_frame_export_path": self.state.latest_frame_export_path,
                    "config_export_path": self.state.config_export_path,
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
        return {
            "enabled": state.replicator_enabled,
            "writer_name": state.replicator_writer_name,
            "annotator_name": state.replicator_annotator_name,
            "output_dir": state.replicator_output_dir,
            "started": state.replicator_recording,
            "write_count": state.replicator_write_count,
            "flush_count": state.replicator_flush_count,
            "latest_write_path": state.replicator_latest_write_path,
            "latest_jsonl_path": state.replicator_latest_jsonl_path,
            "latest_error": state.replicator_latest_error,
            "output_artifacts": list(state.replicator_output_artifacts),
            "status_message": state.replicator_status_message,
        }

    def _apply_config_summary(self, payload: Mapping[str, Any]) -> None:
        array = dict(payload.get("array", {}))
        source = dict(payload.get("source", {}))
        binding = dict(payload.get("stage_binding", {}))
        lifecycle = dict(payload.get("lifecycle", {}))
        recording = dict(payload.get("recording", {}))
        package_recording = dict(recording.get("package_jsonl", {}))
        replicator = dict(recording.get("replicator", {}))

        self.state.backend = str(payload.get("backend", self.state.backend))
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
        self.state.source_start_time_s = float(
            source.get("start_time_s", self.state.source_start_time_s)
        )
        self.state.source_duration_s = float(
            source.get("duration_s", self.state.source_duration_s)
        )
        self.state.source_gain_db = float(
            source.get("gain_db", self.state.source_gain_db)
        )
        self.state.robot_base_prim_path = str(
            binding.get("robot_base_prim_path") or ""
        )
        roots = binding.get("discovery_roots", self._discovery_roots())
        self.state.discovery_roots_text = ", ".join(str(root) for root in roots)
        self.state.selected_prim_paths = _normalize_paths(
            binding.get("selected_prim_paths", ())
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
        self.state.authored_metadata = tuple(
            _authored_metadata_from_dict(item)
            for item in payload.get("authored_metadata", ())
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.state.status_message = message
        self.state.error_message = message if error else None
        if self._ui_window is not None:
            self._ui_window.refresh_labels()

    def _record_error(self, action: str, exc: BaseException) -> None:
        self._set_status(f"{action}: {exc}", error=True)


class OmniReferenceWindow:
    """Small adapter from ``ExtensionUiState`` to ``omni.ui`` widgets."""

    def __init__(self, controller: ExtensionController, ui: Any) -> None:
        self.controller = controller
        self.ui = ui
        self.window: Any | None = None
        self._string_fields: dict[str, Any] = {}
        self._float_fields: dict[str, Any] = {}
        self._int_fields: dict[str, Any] = {}
        self._bool_fields: dict[str, Any] = {}
        self._combo_fields: dict[str, tuple[Any, tuple[str, ...]]] = {}
        self._labels: dict[str, Any] = {}

    def build(self) -> Any:
        """Build a compact task-oriented Kit window."""

        ui = self.ui
        self.window = ui.Window("Isaac Audio Sensors", width=620, height=760)
        with self.window.frame, ui.VStack(spacing=6):
            self._build_stage_section()
            self._build_array_section()
            self._build_source_section()
            self._build_control_section()
            self._build_replicator_section()
            self._build_export_section()
            self._labels["status"] = ui.Label(
                self.controller.state.status_message,
                word_wrap=True,
            )
        self.refresh_labels()
        return self.window

    def refresh_labels(self) -> None:
        """Push current state summaries to visible labels."""

        state = self.controller.state
        self._set_label("stage", state.stage_status)
        self._set_label(
            "discovery",
            f"Arrays: {_summary_ids(state.discovered_arrays)} | "
            f"Sources: {_summary_ids(state.discovered_sources)}",
        )
        self._set_label(
            "latest",
            "Frame: "
            f"{state.latest_frame_id or 'none'} | "
            f"detections={state.latest_detection_count} | "
            f"backend={state.latest_backend or state.backend} | "
            f"bearing={_optional_float_text(state.latest_bearing_deg)} | "
            f"sector={state.latest_sector or 'none'}",
        )
        self._set_label(
            "overlay",
            "Overlay: "
            f"{state.latest_overlay_primitive_count} primitive(s) | "
            f"{', '.join(state.latest_overlay_labels) or 'none'} | "
            f"{state.latest_overlay_status}",
        )
        self._set_label(
            "replicator",
            f"{state.replicator_status_message} | "
            f"latest={state.replicator_latest_write_path or 'none'}",
        )
        self._set_label("status", state.status_message)

    def sync_state_from_widgets(self) -> None:
        """Read widget models into the pure state before actions."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            setattr(state, attr_name, _model_string(widget.model))
        for attr_name, widget in self._float_fields.items():
            setattr(state, attr_name, _model_float(widget.model))
        for attr_name, widget in self._int_fields.items():
            setattr(state, attr_name, _model_int(widget.model))
        for attr_name, widget in self._bool_fields.items():
            setattr(state, attr_name, _model_bool(widget.model))
        for attr_name, (widget, choices) in self._combo_fields.items():
            index = _combo_index(widget.model)
            if 0 <= index < len(choices):
                setattr(state, attr_name, choices[index])

    def push_state_to_widgets(self) -> None:
        """Push state values into editable widgets after action-side updates."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, widget in self._float_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, widget in self._int_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, widget in self._bool_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))

    def _build_stage_section(self) -> None:
        ui = self.ui
        with self._section("Stage"):
            self._labels["stage"] = ui.Label("", word_wrap=True)
            with ui.HStack(spacing=4):
                ui.Button(
                    "Refresh",
                    clicked_fn=self._action(
                        self.controller.refresh_stage_selection
                    ),
                )
                ui.Button(
                    "Use Array",
                    clicked_fn=self._action(self.controller.use_selected_as_array),
                )
                ui.Button(
                    "Use Source",
                    clicked_fn=self._action(self.controller.use_selected_as_source),
                )
                ui.Button(
                    "Use Base",
                    clicked_fn=self._action(
                        self.controller.use_selected_as_robot_base
                    ),
                )
            self._string_row("Discovery Roots", "discovery_roots_text")
            self._string_row("Robot/Base", "robot_base_prim_path")
            ui.Button(
                "Discover",
                clicked_fn=self._action(self.controller.refresh_discovery),
            )
            self._labels["discovery"] = ui.Label("", word_wrap=True)

    def _build_array_section(self) -> None:
        ui = self.ui
        with self._section("Author Array"):
            self._string_row("Target Prim", "array_prim_path")
            self._string_row("Array ID", "array_id")
            self._combo_row("Layout", "layout_name", LAYOUT_CHOICES)
            self._int_row("Sample Rate", "sample_rate_hz")
            ui.Label(f"Convention: {self.controller.state.coordinate_convention}")
            self._bool_row("Child Mics", "author_child_microphones")
            ui.Button(
                "Create/Attach Array",
                clicked_fn=self._action(self.controller.author_array),
            )

    def _build_source_section(self) -> None:
        ui = self.ui
        with self._section("Author Source"):
            self._string_row("Target Prim", "source_prim_path")
            self._string_row("Source ID", "source_id")
            self._string_row("Class", "source_class_label")
            self._string_row("Audio URI", "audio_asset_path")
            self._float_row("Start", "source_start_time_s")
            self._float_row("Duration", "source_duration_s")
            self._float_row("Gain dB", "source_gain_db")
            ui.Button(
                "Create/Attach Source",
                clicked_fn=self._action(self.controller.author_source),
            )

    def _build_control_section(self) -> None:
        ui = self.ui
        with self._section("Sensor"):
            self._combo_row("Backend", "backend", BACKEND_CHOICES)
            self._combo_row("Ambiguity", "ambiguity_policy", AMBIGUITY_POLICY_CHOICES)
            self._float_row("Period s", "update_period_s")
            self._int_row("Max Events", "max_events")
            self._bool_row("Overlay", "debug_overlay_enabled")
            self._bool_row("JSONL", "trace_enabled")
            self._string_row("Writer Path", "jsonl_trace_path")
            with ui.HStack(spacing=4):
                ui.Button(
                    "Start",
                    clicked_fn=self._action(self.controller.start_sensor),
                )
                ui.Button("Stop", clicked_fn=self._action(self.controller.stop_sensor))
                ui.Button(
                    "Update",
                    clicked_fn=self._action(self.controller.update_sensor),
                )
            self._labels["latest"] = ui.Label("", word_wrap=True)
            self._labels["overlay"] = ui.Label("", word_wrap=True)

    def _build_replicator_section(self) -> None:
        ui = self.ui
        with self._section("Replicator"):
            self._bool_row("Enable", "replicator_enabled")
            self._string_row("Output Dir", "replicator_output_dir")
            self._string_row("Writer", "replicator_writer_name")
            self._string_row("Annotator", "replicator_annotator_name")
            with ui.HStack(spacing=4):
                ui.Button(
                    "Start",
                    clicked_fn=self._action(self.controller.start_replicator),
                )
                ui.Button(
                    "Flush",
                    clicked_fn=self._action(self.controller.flush_replicator),
                )
                ui.Button(
                    "Stop",
                    clicked_fn=self._action(self.controller.stop_replicator),
                )
            self._labels["replicator"] = ui.Label("", word_wrap=True)

    def _build_export_section(self) -> None:
        ui = self.ui
        with self._section("Export"):
            self._string_row("Latest JSON", "latest_frame_export_path")
            self._string_row("Config JSON", "config_export_path")
            self._string_row("Load Config", "config_import_path")
            with ui.HStack(spacing=4):
                ui.Button(
                    "Export Latest",
                    clicked_fn=self._action(self.controller.export_latest_frame),
                )
                ui.Button(
                    "Export Config",
                    clicked_fn=self._action(self.controller.export_config_summary),
                )
                ui.Button(
                    "Load Config",
                    clicked_fn=self._action(self.controller.import_config_summary),
                )

    def _section(self, title: str) -> Any:
        frame_type = getattr(self.ui, "CollapsableFrame", None)
        if frame_type is None:
            return self.ui.VStack(spacing=4)
        return frame_type(title, collapsed=False, height=0)

    def _string_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            widget = self.ui.StringField()
            _set_model_value(widget.model, getattr(self.controller.state, attr_name))
            self._string_fields[attr_name] = widget

    def _float_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            widget = self.ui.FloatDrag()
            _set_model_value(widget.model, getattr(self.controller.state, attr_name))
            self._float_fields[attr_name] = widget

    def _int_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            widget = self.ui.IntDrag()
            _set_model_value(widget.model, getattr(self.controller.state, attr_name))
            self._int_fields[attr_name] = widget

    def _bool_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            widget = self.ui.CheckBox()
            _set_model_value(widget.model, getattr(self.controller.state, attr_name))
            self._bool_fields[attr_name] = widget

    def _combo_row(
        self,
        label: str,
        attr_name: str,
        choices: tuple[str, ...],
    ) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            current = getattr(self.controller.state, attr_name)
            index = choices.index(current) if current in choices else 0
            widget = self.ui.ComboBox(index, *choices, width=220)
            self._combo_fields[attr_name] = (widget, choices)

            def _on_changed(model: Any, _item: Any = None) -> None:
                selected = _combo_index(model)
                if 0 <= selected < len(choices):
                    setattr(self.controller.state, attr_name, choices[selected])

            if hasattr(widget.model, "add_item_changed_fn"):
                widget.model.add_item_changed_fn(_on_changed)

    def _action(self, callback: Callable[..., Any]) -> Callable[[], None]:
        def _wrapped() -> None:
            self.sync_state_from_widgets()
            callback()
            self.push_state_to_widgets()
            self.refresh_labels()

        return _wrapped

    def _set_label(self, name: str, text: str) -> None:
        label = self._labels.get(name)
        if label is None:
            return
        if hasattr(label, "text"):
            label.text = text
            return
        if hasattr(label, "model"):
            _set_model_value(label.model, text)


def current_omni_stage_context() -> CurrentStageContext:
    """Return the live Omni stage and selected prims through lazy imports."""

    try:
        omni_usd = importlib.import_module("omni.usd")
    except ImportError as exc:
        raise ExtensionActionError(
            "omni.usd is unavailable; load this extension inside Isaac Sim "
            "or pass an explicit stage in tests."
        ) from exc
    if not hasattr(omni_usd, "get_context"):
        raise ExtensionActionError("omni.usd.get_context is unavailable.")
    context = omni_usd.get_context()
    stage = context.get_stage() if hasattr(context, "get_stage") else None
    selected_paths: tuple[str, ...] = ()
    if hasattr(context, "get_selection"):
        selection = context.get_selection()
        if hasattr(selection, "get_selected_prim_paths"):
            selected_paths = _normalize_paths(selection.get_selected_prim_paths())
    return CurrentStageContext(stage=stage, selected_prim_paths=selected_paths)


def _stage_has_prim(stage: Any, path: str) -> bool:
    if not path:
        return False
    if hasattr(stage, "GetPrimAtPath"):
        prim = stage.GetPrimAtPath(path)
        if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
            return True
    if hasattr(stage, "Traverse"):
        return any(prim_path(prim) == path for prim in stage.Traverse())
    return False


def _prim_has_pose(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(
        key in attrs
        for key in (
            "ias:position_world",
            "xformOp:translate",
            "usd_world_position",
        )
    )


def _prim_has_orientation(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(
        key in attrs
        for key in (
            "ias:orientation_world_quat",
            "xformOp:orient",
            "usd_world_orientation",
        )
    )


def _prim_attrs(prim: Any) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = attr.Get()
    return attrs


def _normalize_paths(paths: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for path in paths:
        path_string = getattr(path, "pathString", None)
        normalized.append(str(path_string if path_string is not None else path))
    return tuple(path for path in normalized if path)


def _validate_abs_path(path: str, field_name: str) -> None:
    if not path.strip() or not path.startswith("/"):
        raise ExtensionActionError(f"{field_name} must be an absolute USD prim path.")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _jsonable_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_ready(value) for key, value in sorted(mapping.items())}


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(value[key]) for key in sorted(value)}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _authored_metadata_from_dict(value: Any) -> AuthoredMetadataSummary:
    if not isinstance(value, Mapping):
        raise ExtensionActionError("authored_metadata entries must be objects.")
    return AuthoredMetadataSummary(
        kind=str(value.get("kind", "")),
        prim_path=str(value.get("prim_path", "")),
        id=str(value.get("id", "")),
        attributes=_jsonable_mapping(dict(value.get("attributes", {}))),
    )


def _summary_ids(items: tuple[DiscoveredPrimSummary, ...]) -> str:
    return ", ".join(f"{item.id}@{item.prim_path}" for item in items) or "none"


def _optional_float_text(value: float | None) -> str:
    return "none" if value is None else f"{value:.2f}"


def _set_model_value(model: Any, value: Any) -> None:
    if hasattr(model, "set_value"):
        model.set_value(value)


def _model_string(model: Any) -> str:
    if hasattr(model, "get_value_as_string"):
        return str(model.get_value_as_string())
    if hasattr(model, "as_string"):
        return str(model.as_string)
    return str(getattr(model, "value", ""))


def _model_float(model: Any) -> float:
    if hasattr(model, "get_value_as_float"):
        return float(model.get_value_as_float())
    if hasattr(model, "as_float"):
        return float(model.as_float)
    return float(getattr(model, "value", 0.0))


def _model_int(model: Any) -> int:
    if hasattr(model, "get_value_as_int"):
        return int(model.get_value_as_int())
    if hasattr(model, "as_int"):
        return int(model.as_int)
    return int(getattr(model, "value", 0))


def _model_bool(model: Any) -> bool:
    if hasattr(model, "get_value_as_bool"):
        return bool(model.get_value_as_bool())
    if hasattr(model, "as_bool"):
        return bool(model.as_bool)
    return bool(getattr(model, "value", False))


def _combo_index(model: Any) -> int:
    if hasattr(model, "get_item_value_model"):
        value_model = model.get_item_value_model()
        if hasattr(value_model, "as_int"):
            return int(value_model.as_int)
        if hasattr(value_model, "get_value_as_int"):
            return int(value_model.get_value_as_int())
    return _model_int(model)


__all__ = [
    "AMBIGUITY_POLICY_CHOICES",
    "BACKEND_CHOICES",
    "LAYOUT_CHOICES",
    "AuthoredMetadataSummary",
    "CurrentStageContext",
    "DiscoveredPrimSummary",
    "ExtensionActionError",
    "ExtensionController",
    "ExtensionUiState",
    "OmniReferenceWindow",
    "current_omni_stage_context",
]
