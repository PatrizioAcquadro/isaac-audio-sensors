"""Stateful controller for the Isaac Audio Sensors reference extension."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import write_frame_trace
from isaac_audio_sensors.core.math_utils import (
    euler_deg_from_quaternion,
    quaternion_from_euler_deg,
)
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.frame_registry import (
    clear_latest_frames,
    publish_latest_frame,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    prim_path,
    quat_from_any,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.replicator import AudioSensorReplicatorRecorder
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
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
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
    debug_primitives_to_dicts,
)
from isaac_audio_sensors.isaac.viz.usd_debug import UsdDebugGeometryAuthor
from isaac_audio_sensors.kit.microphone_rig_profiles import (
    MicrophoneRigProfile,
    microphone_rig_profile_from_mapping,
    validate_microphone_rig_profile_library,
)
from isaac_audio_sensors.kit.sound_profiles import (
    SoundProfile,
    match_sound_profile_id,
    normalize_object_label,
    sound_profile_from_mapping,
    validate_sound_profile_library,
)
from isaac_audio_sensors.kit.validation import (
    ValidationController,
    ValidationFinding,
    ValidationReport,
)
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    SessionRecorder,
)
from isaac_audio_sensors.recording.serialization import (
    read_dataset_manifest,
    write_dataset_manifest,
)
from isaac_audio_sensors.recording.splits import (
    DatasetSplitError,
    apply_split_plan,
    build_split_plan,
)
from isaac_audio_sensors.recording.validate import validate_dataset

from .audition import AuditionPlayer
from .constants import (
    DEFAULT_ROOM_ABSORPTION,
    DEFAULT_ROOM_DIMENSIONS_M,
    DEFAULT_ROOM_ID,
    DEFAULT_ROOM_MAX_ORDER,
    OMNI_ACTION_TOGGLE_WINDOW,
    OMNI_DEFAULT_HOTKEY,
    OMNI_DEFAULT_HOTKEY_DISPLAY,
    OMNI_MENU_GROUP,
    OMNI_WINDOW_TITLE,
    SOURCE_POSITION_PRESETS,
)
from .formatting import (
    _aggregate_rms_from_frame,
    _format_vec3,
    _frame_is_new,
    _vec_close,
)
from .instruments import append_detection_history
from .paths import _resolve_gui_output_path
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
    _stage_prim_at_path,
    _style_demo_object_prim,
    current_omni_stage_context,
)
from .state import (
    AuthoredMetadataSummary,
    CurrentStageContext,
    DiscoveredPrimSummary,
    ExtensionActionError,
    ExtensionUiState,
    _authored_metadata_from_dict,
    _discovered_summary_from_dict,
    _json_ready,
    _jsonable_mapping,
)
from .ui_models import (
    _focus_window,
    _normalize_hotkey_setting,
    _set_window_visible,
    _window_visible,
)
from .window import OmniReferenceWindow
from .workflow import (
    SAFE_PRESETS,
    ExportStatus,
    GuidedStage,
    GuidedWorkflow,
    RecordingStatus,
    RunStatus,
    SafePreset,
)


def _raise_first(report: ValidationReport) -> None:
    for finding in report.findings:
        if finding.severity == "error":
            raise ExtensionActionError(finding.message)


class ExtensionController:
    """Stateful controller for the Isaac Audio Sensors reference extension."""

    def __init__(
        self,
        *,
        state: ExtensionUiState | None = None,
        stage_context_provider: Callable[[], CurrentStageContext] | None = None,
    ) -> None:
        self.state = state or ExtensionUiState()
        self._validation = ValidationController()
        self.stage_context_provider = stage_context_provider
        self.sensor: IsaacAudioArraySensor | None = None
        self.replicator_recorder: AudioSensorReplicatorRecorder | None = None
        self.ext_id: str | None = None
        self.window: Any | None = None
        self.ui_available = False
        self._ui_window: OmniReferenceWindow | None = None
        self.action_status = "Kit action not registered."
        self.menu_status = "Kit menu not registered."
        self.hotkey_status = "Kit hotkey not registered."
        self._registered_action: Any | None = None
        self._registered_hotkey: Any | None = None
        self._registered_hotkey_key: str | None = None
        self._controller_update_subscription: Any | None = None
        self._menu_items: list[Any] = []
        self._audition_player = AuditionPlayer()
        self._stage_event_subscription: Any | None = None
        self._simulation_reset_callback_id: int | None = None
        self._last_followed_selection: tuple[str, ...] | None = None
        self._usd_debug_author: UsdDebugGeometryAuthor | None = None
        self._guided_recorder: SessionRecorder | None = None
        self._guided_recording_request: dict[str, Any] | None = None
        self._guided_last_run_frame_id: str | None = None
        self._guided_last_recorded_frame_id: str | None = None
        self._guided_last_recorded_timestamp_ms: int | None = None
        self._guided_last_recorded_producer_index: int | None = None
        self._guided_reset_pending = False
        self._guided_dataset_validation_report: Any | None = None
        self._guided_export_validation_report: Any | None = None
        self._guided_output_entries: tuple[dict[str, Any], ...] = ()

    @property
    def guided_workflow(self) -> GuidedWorkflow:
        """Return the lazily constructed import-safe guided workflow."""

        workflow = getattr(self, "_guided_workflow", None)
        if workflow is None:
            workflow = GuidedWorkflow(
                self._validation,
                self.state,
                recovery_handlers={
                    "stage": lambda _finding: self.refresh_stage_selection(),
                    "preset": lambda _finding: (
                        self.guided_apply_preset(
                            self.state.guided_preset_id or SAFE_PRESETS[0].preset_id
                        ),
                        self._validation.refresh_capabilities("guided preset recovery"),
                    ),
                    "capabilities": lambda _finding: (
                        self._validation.refresh_capabilities("guided recovery action")
                    ),
                    "recording": lambda _finding: self._guided_restart_recording(),
                    "finish_recording": lambda _finding: self.guided_stop_recording(),
                    "run": lambda _finding: self.guided_start_run(),
                    "inspect": lambda _finding: self.guided_mark_inspected(),
                    "focus": lambda finding: self._set_status(
                        f"Review {finding.field or 'the guided workflow'}."
                    ),
                },
            )
            self._guided_workflow = workflow
        return workflow

    def guided_apply_preset(self, preset_id: str) -> SafePreset | None:
        """Apply one safe preset through the existing config-summary path."""

        try:
            stage_present = self._context().stage is not None
            preset = self.guided_workflow.apply_preset(
                preset_id,
                lambda item: self._apply_config_summary(item.config_summary()),
                stage_present=stage_present,
            )
            self._set_status(f"Applied guided preset {preset.label}.")
            return preset
        except Exception as exc:
            self._record_error("Guided preset apply failed", exc)
            return None

    def guided_validate(self) -> ValidationReport:
        """Run the shared validation matrix and record the Validate gate."""

        state = self.state
        context = self._context()
        stage = context.stage
        capabilities_were_stale = getattr(
            self._validation, "_capability_state", None
        ) is not None and getattr(self._validation, "_capabilities_stale", False)
        reports = [
            self._validation.validate_stage_present(stage is not None),
            self._validation.validate_runtime(state),
            self._validation.validate_backend_available(state.backend),
            self._validation.validate_backend_device(
                state.backend,
                state.compute_device,
            ),
            self._validation.validate_abs_prim_path(
                state.source_prim_path,
                "source_prim_path",
            ),
            self._validation.validate_source_metadata(state),
            self._validation.validate_source_geometry(state),
            self._validation.validate_array_geometry(state),
            self._validation.validate_layout(state),
            self._validation.validate_calibration_profile(
                state.calibration_profile_path,
                self._calibration_array_facts(),
            ),
        ]
        if state.room_anchor_prim_path:
            reports.append(
                self._validation.validate_room_anchor_exists(
                    state.room_anchor_prim_path,
                    stage is not None
                    and _stage_has_prim(stage, state.room_anchor_prim_path),
                )
            )
        reports.extend(
            (
                self._validation.validate_attached_source_target(
                    state.source_attached_to_object,
                    state.attached_object_prim_path or state.object_prim_path,
                    None
                    if not state.source_attached_to_object or stage is None
                    else _stage_has_prim(
                        stage,
                        state.attached_object_prim_path or state.object_prim_path,
                    ),
                ),
                self._validation.validate_attached_array_target(
                    state.array_attached_to_object,
                    state.attached_array_object_prim_path,
                    None
                    if not state.array_attached_to_object or stage is None
                    else _stage_has_prim(
                        stage,
                        state.attached_array_object_prim_path,
                    ),
                ),
            )
        )
        findings = tuple(
            dict.fromkeys(finding for report in reports for finding in report.findings)
        )
        capabilities_fresh = (
            getattr(self._validation, "_capability_state", None) is not None
            and not getattr(self._validation, "_capabilities_stale", True)
            and not capabilities_were_stale
        )
        report = self.guided_workflow.record_validation(
            ValidationReport(findings),
            capabilities_fresh=capabilities_fresh,
        )
        if report.ok:
            self._set_status("Guided validation passed.")
        else:
            self._set_status(
                f"Guided validation found {len(report.findings)} issue(s).",
                error=True,
            )
        return report

    def guided_advance(self) -> bool:
        """Advance to the next guided stage when its gate is open."""

        return self.guided_workflow.advance()

    def guided_back(self) -> bool:
        """Return to the preceding guided stage."""

        return self.guided_workflow.back()

    @property
    def guided_run_status(self) -> RunStatus:
        """Return the current immutable Run lifecycle snapshot."""

        return self.guided_workflow.run_status

    @property
    def guided_recording_status(self) -> RecordingStatus:
        """Return the current immutable recording progress snapshot."""

        return self.guided_workflow.recording_status

    @property
    def guided_dataset_validation_report(self) -> Any | None:
        return self._guided_dataset_validation_report

    @property
    def guided_export_validation_report(self) -> Any | None:
        return self._guided_export_validation_report

    @property
    def guided_export_status(self) -> ExportStatus:
        return self.guided_workflow.export_status

    def guided_start_run(self) -> Any | None:
        """Configure and start the sensor through the existing lifecycle."""

        if not self.guided_workflow.goto(GuidedStage.RUN):
            return None
        self._guided_last_run_frame_id = None
        self.guided_workflow.start_run(configured=False, running=False)
        sensor = self.configure_sensor()
        if sensor is None:
            self.guided_workflow.fail_run(
                "Sensor configuration failed.",
                check_id="guided_run_configuration_failed",
            )
            return None
        self.guided_workflow.update_run_lifecycle(
            configured=True,
            running=False,
        )
        started = self.start_sensor()
        if started is None:
            self.guided_workflow.fail_run(
                "The configured sensor is not running; start Run again.",
                check_id="guided_run_sensor_not_running",
            )
            return None
        self.guided_workflow.update_run_lifecycle(
            configured=True,
            running=True,
        )
        return started

    def guided_stop_run(self) -> None:
        """Stop the sensor through the existing lifecycle action."""

        self.stop_sensor()

    def guided_inspect_summary(self) -> dict[str, Any]:
        """Return compact live evidence for the human Inspect decision."""

        capability = getattr(self._validation, "_capability_state", None)
        return {
            "latest_frame_id": self.state.latest_frame_id,
            "latest_timestamp_ms": self.state.latest_timestamp_ms,
            "detection_count": self.state.latest_detection_count,
            "backend": self.state.latest_backend or self.state.backend,
            "capability_generation": (
                None if capability is None else capability.captured_at_generation
            ),
        }

    def guided_mark_inspected(self) -> bool:
        """Accept the current read-only instrument evidence."""

        if not self.guided_workflow.goto(GuidedStage.INSPECT):
            return False
        return self.guided_workflow.mark_inspected()

    def guided_start_recording(
        self,
        session_dir: str | Path,
        dataset_id: str,
        shard_max_frames: int,
        aligned: bool,
        *,
        scene_id: str | None = None,
        environment_id: str | None = None,
        split_group: str | None = None,
        session_seed: int | None = None,
        preserve_time_gaps: bool = False,
    ) -> SessionRecorder | None:
        """Start one guided dataset session and its single v1 episode."""

        try:
            if type(preserve_time_gaps) is not bool:
                raise ExtensionActionError("preserve_time_gaps must be a bool.")
            if not self.guided_workflow.goto(GuidedStage.RECORD):
                return None
            if self._guided_recorder is not None:
                raise ExtensionActionError("A guided recording is already active.")
            if not self.state.sensor_running or self.sensor is None:
                raise ExtensionActionError(
                    "The sensor must remain running to start recording."
                )
            root = Path(session_dir)
            chosen_scene = scene_id or self.state.guided_scene_id
            chosen_environment = environment_id or self.state.guided_environment_id
            chosen_group = split_group or self.state.guided_split_group
            chosen_seed = (
                self.state.guided_session_seed
                if session_seed is None
                else int(session_seed)
            )
            self.state.guided_session_dir = str(root)
            self.state.guided_dataset_id = str(dataset_id)
            self.state.guided_shard_max_frames = int(shard_max_frames)
            self.state.guided_record_aligned = bool(aligned)
            self.state.guided_scene_id = str(chosen_scene)
            self.state.guided_environment_id = str(chosen_environment)
            self.state.guided_split_group = str(chosen_group)
            self.state.guided_session_seed = int(chosen_seed)
            request = {
                "session_dir": str(root),
                "dataset_id": str(dataset_id),
                "shard_max_frames": int(shard_max_frames),
                "aligned": bool(aligned),
                "scene_id": str(chosen_scene),
                "environment_id": str(chosen_environment),
                "split_group": str(chosen_group),
                "session_seed": int(chosen_seed),
                "preserve_time_gaps": preserve_time_gaps,
            }
            configuration = self._guided_recorder_configuration(request)
            self._guided_last_recorded_frame_id = None
            self._guided_last_recorded_timestamp_ms = None
            self._guided_last_recorded_producer_index = None
            self._guided_reset_pending = False
            self._guided_dataset_validation_report = None
            recorder = SessionRecorder(
                root,
                configuration,
                creation=CreationProvenance(
                    tool_name="isaac_audio_sensors_guided",
                    tool_version=__version__,
                    backend_id=self.state.backend,
                    estimator_id=self.state.backend,
                ),
                device=DeviceProvenance(
                    device_id=self.state.device_id,
                    device_type="simulator",
                    platform=sys.platform,
                    compute_device=self.state.compute_device,
                ),
                license="CC0-1.0",
                source="Isaac Audio Sensors guided extension",
                coordinate_frames=("world", "array"),
                time_base="simulation_time",
            )
            episode = recorder.begin_episode(
                str(chosen_scene),
                str(chosen_environment),
                str(chosen_group),
                seed=int(chosen_seed),
            )
            self._guided_recorder = recorder
            self._guided_recording_request = request
            self.guided_workflow.start_recording(
                RecordingStatus(
                    active=True,
                    session_dir=str(root),
                    dataset_id=str(dataset_id),
                    bytes_written=self._guided_session_bytes(root),
                    current_episode=episode,
                )
            )
            self._set_status(f"Recording guided dataset {dataset_id}.")
            return recorder
        except Exception as exc:
            self.guided_workflow.fail_recording(str(exc))
            self._record_error("Guided recording start failed", exc)
            return None

    def guided_cancel_recording(self) -> Any | None:
        """Cooperatively cancel and finalize an incomplete guided session."""

        recorder = self._guided_recorder
        if recorder is None:
            return None
        try:
            manifest = recorder.cancel()
            previous = self.guided_workflow.recording_status
            status = replace(
                previous,
                active=False,
                cancelled=True,
                shards_promoted=recorder.promoted_shard_count,
                bytes_written=self._guided_session_bytes(recorder.session_root),
                current_episode=None,
            )
            self._guided_recorder = None
            self.guided_workflow.cancel_recording(status)
            self._set_status("Guided recording cancelled and finalized incomplete.")
            return manifest
        except Exception as exc:
            self.guided_workflow.fail_recording(str(exc))
            self._record_error("Guided recording cancellation failed", exc)
            return None

    def guided_stop_recording(self) -> Any | None:
        """Finalize, validate, and gate the guided recording."""

        recorder = self._guided_recorder
        if recorder is None:
            return None
        try:
            recorder.end_episode()
            manifest = recorder.finalize()
            report = validate_dataset(recorder.session_root)
            self._guided_dataset_validation_report = report
            previous = self.guided_workflow.recording_status
            status = replace(
                previous,
                active=False,
                shards_promoted=recorder.promoted_shard_count,
                bytes_written=self._guided_session_bytes(recorder.session_root),
                current_episode=None,
                validation_status=report.status,
            )
            findings = ()
            if report.status not in {"passed", "passed_with_warnings"}:
                findings = tuple(
                    self._dataset_finding(item) for item in report.findings
                ) or (
                    self._guided_validation_finding(
                        "dataset_validation_failed",
                        "Dataset validation failed without a located finding.",
                    ),
                )
            self._guided_recorder = None
            self.guided_workflow.finish_recording(status, findings)
            self._set_status(
                f"Guided dataset validation {report.status}.",
                error=bool(findings),
            )
            return manifest
        except Exception as exc:
            self.guided_workflow.fail_recording(str(exc))
            self._record_error("Guided recording stop failed", exc)
            return None

    def guided_export(self, destination_dir: str | Path) -> Path | None:
        """Copy, optionally split, and validate one portable guided session."""

        workflow = self.guided_workflow
        if not workflow.goto(GuidedStage.EXPORT):
            return None
        destination = Path(destination_dir).expanduser()
        self.state.guided_export_dir = str(destination)
        workflow.start_export(str(destination))
        self._guided_export_validation_report = None
        self._guided_output_entries = ()
        source_text = self.guided_recording_status.session_dir
        if not source_text:
            workflow.fail_export(
                "No finalized guided session is available to export.",
                check_id="guided_export_session_missing",
                field="guided_session_dir",
            )
            return None
        source = Path(source_text).expanduser()
        source_resolved = source.resolve(strict=False)
        destination_resolved = destination.resolve(strict=False)
        if self._path_is_within(destination_resolved, source_resolved):
            workflow.fail_export(
                "Export destination must be outside the recorded session root.",
                check_id="guided_export_destination_inside_session",
            )
            return None
        if destination.exists():
            workflow.fail_export(
                "Export destination already exists; choose a new directory.",
                check_id="guided_export_destination_exists",
            )
            return None
        if not self._guided_destination_is_writable(destination):
            workflow.fail_export(
                "Export destination parent is not writable.",
                check_id="guided_export_destination_unwritable",
            )
            return None

        staging_container: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging_container = Path(
                tempfile.mkdtemp(
                    prefix=f".{destination.name}.guided-export-",
                    dir=destination.parent,
                )
            )
            staged = staging_container / destination.name
            shutil.copytree(source, staged, symlinks=False, copy_function=shutil.copy2)
            report = validate_dataset(staged)
            if report.status == "failed":
                finding = next(iter(report.findings), None)
                detail = (
                    "Portable copy validation failed."
                    if finding is None
                    else f"{finding.location}: {finding.detail}"
                )
                workflow.fail_export(
                    detail,
                    check_id=(
                        "guided_export_validation_failed"
                        if finding is None
                        else f"dataset_{finding.code}"
                    ),
                )
                self._guided_export_validation_report = report
                return None

            split_status, note = self._guided_apply_export_split(staged)
            report = validate_dataset(staged)
            self._guided_export_validation_report = report
            if report.status == "failed":
                finding = next(iter(report.findings), None)
                workflow.fail_export(
                    "Exported copy failed validation after split application."
                    if finding is None
                    else f"{finding.location}: {finding.detail}",
                    check_id=(
                        "guided_export_validation_failed"
                        if finding is None
                        else f"dataset_{finding.code}"
                    ),
                )
                return None
            entries = self._guided_inventory_from_root(staged)
            os.replace(staged, destination)
            self._guided_output_entries = entries
            workflow.finish_export(
                ExportStatus(
                    destination_dir=str(destination),
                    validation_status=report.status,
                    split_status=split_status,
                    note=note,
                    inventory_entries=len(entries),
                    inventory_bytes=sum(int(item["bytes"]) for item in entries),
                )
            )
            self._set_status(
                f"Guided export validated at {destination}."
                + (" " + note if note else "")
            )
            return destination
        except DatasetSplitError as exc:
            message = str(exc)
            impossible = "impossible ratios" in message
            workflow.fail_export(
                message,
                check_id=(
                    "guided_export_split_impossible"
                    if impossible
                    else "guided_export_split_failed"
                ),
                field="guided_split_ratios",
                note=(
                    "Adjust split ratios so the number of positive partitions "
                    "does not exceed the session group count."
                    if impossible
                    else message
                ),
            )
            self._record_error("Guided export split failed", exc)
            return None
        except Exception as exc:
            workflow.fail_export(
                str(exc),
                check_id="guided_export_failed",
            )
            self._record_error("Guided export failed", exc)
            return None
        finally:
            if staging_container is not None and staging_container.exists():
                shutil.rmtree(staging_container)

    def guided_output_inventory(self) -> tuple[dict[str, Any], ...]:
        """Return marker/manifest inventory entries without hashing files."""

        return tuple(dict(entry) for entry in self._guided_output_entries)

    def _guided_apply_export_split(self, root: Path) -> tuple[str, str | None]:
        if not self.state.guided_split_enabled:
            return "not_requested", "Split plan disabled."
        manifest = read_dataset_manifest(root / "manifest.json")
        grouping_key = manifest.split_grouping_key
        groups = {
            str(getattr(episode, grouping_key, episode.split_group))
            for episode in manifest.episodes
        }
        if len(groups) < 2:
            return (
                "skipped_single_group",
                "Split skipped: the session contains one group.",
            )
        ratios = {
            name: float(value)
            for name, value in (
                ("train", self.state.guided_split_train_ratio),
                ("validation", self.state.guided_split_validation_ratio),
                ("test", self.state.guided_split_test_ratio),
            )
            if float(value) > 0.0
        }
        plan = build_split_plan(
            manifest,
            kind="train_validation_test",
            ratios=ratios,
            seed=int(self.state.guided_session_seed),
        )
        write_dataset_manifest(
            apply_split_plan(manifest, plan),
            root / "manifest.json",
        )
        return "applied", f"TVT split applied with seed {plan.seed}."

    @staticmethod
    def _guided_inventory_from_root(root: Path) -> tuple[dict[str, Any], ...]:
        manifest = read_dataset_manifest(root / "manifest.json")
        entries: list[dict[str, Any]] = []
        for shard in manifest.shards:
            marker_path = root / "shards" / shard.shard_id / "shard.complete.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker_files = {str(item["path"]): item for item in marker.get("files", ())}
            for asset in shard.assets:
                marker_entry = marker_files[Path(asset.path).name]
                entries.append(
                    {
                        "path": asset.path,
                        "kind": asset.kind,
                        "bytes": int(marker_entry["bytes"]),
                        "sha256": str(asset.sha256),
                    }
                )
        return tuple(sorted(entries, key=lambda item: str(item["path"])))

    @staticmethod
    def _path_is_within(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _guided_destination_is_writable(destination: Path) -> bool:
        parent = destination.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        try:
            mode = parent.stat().st_mode
        except OSError:
            return False
        write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        return (
            parent.is_dir()
            and bool(mode & write_bits)
            and bool(mode & execute_bits)
            and os.access(parent, os.W_OK | os.X_OK)
        )

    def _guided_recorder_configuration(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        channel_order = [
            microphone.mic_id
            for microphone in microphone_layout(self.state.layout_name)
        ]
        window_samples = max(
            1,
            int(round(self.state.sample_rate_hz * self.state.update_period_s)),
        )
        latest = None if self.sensor is None else self.sensor.latest_frame
        diagnostics = getattr(latest, "diagnostics", {}) if latest else {}
        diagnostic_window = diagnostics.get("window_sample_count")
        if (
            isinstance(diagnostic_window, int)
            and not isinstance(diagnostic_window, bool)
            and diagnostic_window > 0
        ):
            window_samples = diagnostic_window
        configuration = {
            "backend_id": self.state.backend,
            "channel_order": channel_order,
            "dataset_id": request["dataset_id"],
            "dtype": "float32",
            "hop_sample_count": window_samples,
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": int(self.state.sample_rate_hz),
            "session_seed": int(request["session_seed"]),
            "shard_episode_aligned": bool(request["aligned"]),
            "shard_max_frames": int(request["shard_max_frames"]),
            "split_grouping_key": "scene_id",
            "window_sample_count": window_samples,
        }
        if request.get("preserve_time_gaps", False):
            configuration["preserve_time_gaps"] = True
        return configuration

    def _guided_record_frame(self, frame: Any) -> None:
        recorder = self._guided_recorder
        if recorder is None or not self.guided_workflow.recording_status.active:
            return
        frame_id = str(frame.frame_id)
        timestamp_ms = int(frame.timestamp_ms)
        producer_index = getattr(frame, "frame_index", None)
        producer_index = (
            producer_index
            if isinstance(producer_index, int) and not isinstance(producer_index, bool)
            else None
        )
        automatic_reset = (
            self._guided_last_recorded_timestamp_ms is not None
            and timestamp_ms < self._guided_last_recorded_timestamp_ms
        ) or (
            producer_index is not None
            and self._guided_last_recorded_producer_index is not None
            and producer_index < self._guided_last_recorded_producer_index
        )
        reset_boundary = self._guided_reset_pending or automatic_reset
        if frame_id == self._guided_last_recorded_frame_id and not reset_boundary:
            return
        try:
            first_recorded_frame = self._guided_last_recorded_timestamp_ms is None
            audio_block = self._guided_audio_block_for_frame(frame, recorder)
            if reset_boundary and not first_recorded_frame:
                recorder.end_episode()
                request = self._guided_recording_request or {}
                reset_ordinal = self.guided_workflow.recording_status.reset_count + 1
                environment = str(
                    request.get(
                        "environment_id",
                        self.state.guided_environment_id,
                    )
                )
                episode = recorder.begin_episode(
                    str(request.get("scene_id", self.state.guided_scene_id)),
                    f"{environment}_reset_{reset_ordinal:05d}",
                    str(request.get("split_group", self.state.guided_split_group)),
                )
                self.guided_workflow.update_recording(
                    replace(
                        self.guided_workflow.recording_status,
                        current_episode=episode,
                        reset_count=reset_ordinal,
                    )
                )
            recording_frame = replace(frame, waveform_paths=())
            result = recorder.append_frame(
                recording_frame,
                audio_block,
                is_reset=first_recorded_frame or reset_boundary,
            )
            if result.accepted:
                self._guided_last_recorded_frame_id = frame_id
                self._guided_last_recorded_timestamp_ms = timestamp_ms
                self._guided_last_recorded_producer_index = producer_index
                self._guided_reset_pending = False
            previous = self.guided_workflow.recording_status
            status = replace(
                previous,
                frames=previous.frames + int(result.accepted),
                dropped_frames=(previous.dropped_frames + int(not result.accepted)),
                shards_promoted=recorder.promoted_shard_count,
                bytes_written=self._guided_session_bytes(recorder.session_root),
            )
            self.guided_workflow.update_recording(status)
        except Exception as exc:
            self.guided_workflow.fail_recording(str(exc))
            self._record_error("Guided frame recording failed", exc)

    def guided_notify_simulator_reset(self) -> None:
        """Mark the next recorded frame as the start of a reset episode."""

        if self._guided_recorder is not None:
            self._guided_reset_pending = True

    def _attach_guided_reset_listener(self, sensor: Any) -> None:
        add_listener = getattr(sensor, "_add_reset_listener", None)
        if callable(add_listener):
            add_listener(self.guided_notify_simulator_reset)

    def _handle_simulation_reset(self, _event: Any) -> None:
        """Reset the sensor and recorder boundary from Isaac's reset lifecycle."""

        self.guided_notify_simulator_reset()
        if self.sensor is not None:
            self.sensor.reset()

    @staticmethod
    def _guided_audio_block_for_frame(
        frame: Any,
        recorder: SessionRecorder,
    ) -> Any | None:
        paths = tuple(str(path) for path in (frame.waveform_paths or ()))
        if not paths:
            return None
        from isaac_audio_sensors.core.io.wave_read import read_wav

        data = read_wav(paths[-1])
        if data.sample_rate_hz != recorder.sample_rate_hz:
            raise ValueError(
                "waveform sample rate disagrees with guided recording config"
            )
        if data.channel_count != recorder.channels:
            raise ValueError(
                "waveform channel count disagrees with guided recording config"
            )
        samples = data.samples
        if samples.shape[1] > recorder.window_sample_count:
            samples = samples[:, -recorder.window_sample_count :]
        return samples

    @staticmethod
    def _guided_session_bytes(root: Path) -> int:
        if not root.exists():
            return 0
        total = 0
        for path in root.rglob("*"):
            with suppress(OSError):
                if path.is_file():
                    total += path.stat().st_size
        return total

    @staticmethod
    def _guided_validation_finding(
        check_id: str,
        message: str,
    ) -> ValidationFinding:
        return ValidationFinding(
            check_id,
            "error",
            message,
            "guided_session_dir",
        )

    @staticmethod
    def _dataset_finding(finding: Any) -> ValidationFinding:
        return ValidationFinding(
            f"dataset_{finding.code}",
            finding.severity,
            f"{finding.location}: {finding.detail}",
            "guided_session_dir",
        )

    def _guided_restart_recording(self) -> SessionRecorder | None:
        request = self._guided_recording_request
        if request is None:
            return None
        base = Path(request["session_dir"])
        candidate = base
        suffix = 1
        while candidate.exists():
            candidate = base.with_name(f"{base.name}_retry_{suffix}")
            suffix += 1
        retry = {**request, "session_dir": str(candidate)}
        return self.guided_start_recording(
            retry["session_dir"],
            retry["dataset_id"],
            retry["shard_max_frames"],
            retry["aligned"],
            scene_id=retry["scene_id"],
            environment_id=retry["environment_id"],
            split_group=retry["split_group"],
            session_seed=retry["session_seed"],
            preserve_time_gaps=bool(retry.get("preserve_time_gaps", False)),
        )

    def on_startup(self, ext_id: str) -> None:
        """Initialize the import-safe controller and lazily build Kit UI."""

        self._validation.invalidate("extension startup")
        self.ext_id = ext_id
        self._set_status(f"Loaded {ext_id}.")
        self.build_ui_if_available()
        self.register_kit_integrations()

    def on_shutdown(self) -> None:
        """Stop live work and release UI/debug resources."""

        self.unregister_kit_integrations()
        self.stop_replicator()
        self.close_sensor()
        self._ui_window = None
        self.window = None
        self.ui_available = False
        self.ext_id = None
        self._set_status("Shutdown complete.")

    def build_ui_if_available(self) -> Any | None:
        """Build the Omniverse UI only when ``omni.ui`` imports."""

        if self.window is not None:
            self.ui_available = True
            return self.window
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

    def show_window(self) -> Any | None:
        """Show or rebuild the Kit window from menu/action/hotkey entrypoints."""

        window = self.build_ui_if_available()
        if window is None:
            self._set_status("Window unavailable: omni.ui could not be loaded.")
            return None
        if not _set_window_visible(window, True):
            self._set_status("Window shown; this Kit build did not expose visibility.")
            return window
        _focus_window(window)
        self._refresh_menu()
        self._set_status("Window shown.")
        return window

    def hide_window(self) -> None:
        """Hide the Kit window without destroying controller state."""

        if self.window is None:
            return
        _set_window_visible(self.window, False)
        self._refresh_menu()
        self._set_status("Window hidden.")

    def toggle_window(self) -> Any | None:
        """Toggle the Kit window, rebuilding it if the user closed it with X."""

        if self.is_window_visible():
            self.hide_window()
            return self.window
        return self.show_window()

    def is_window_visible(self) -> bool:
        """Return whether the Kit window is currently visible."""

        return _window_visible(self.window)

    def register_kit_integrations(self) -> None:
        """Register action, menu, and optional hotkey integrations when Kit exists."""

        self._register_action()
        self._register_menu()
        self._register_hotkey()
        self._register_stage_event_subscription()
        self._register_simulation_reset_callback()

    def unregister_kit_integrations(self) -> None:
        """Best-effort cleanup of Kit action/menu/hotkey registrations."""

        self._unregister_simulation_reset_callback()
        self._unregister_stage_event_subscription()
        self._unregister_hotkey()
        self._unregister_menu()
        self._unregister_action()

    def _register_action(self) -> None:
        if not self.ext_id:
            self.action_status = "Kit action unavailable: extension id is unset."
            return
        try:
            actions_core = importlib.import_module("omni.kit.actions.core")
        except ImportError as exc:
            self.action_status = (
                f"Kit action unavailable: omni.kit.actions.core ({exc})."
            )
            return
        get_registry = getattr(actions_core, "get_action_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "register_action"):
            self.action_status = "Kit action unavailable: action registry missing."
            return

        if hasattr(registry, "deregister_action"):
            with suppress(Exception):
                registry.deregister_action(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
        try:
            self._registered_action = registry.register_action(
                self.ext_id,
                OMNI_ACTION_TOGGLE_WINDOW,
                self.toggle_window,
                display_name="Toggle Isaac Audio Sensors Window",
                description="Show or hide the Isaac Audio Sensors Kit window.",
                tag="Isaac Audio Sensors",
            )
        except Exception as exc:
            self.action_status = f"Kit action registration failed: {exc}"
            return
        self.action_status = (
            f"Kit action registered: {self.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}."
        )

    def _unregister_action(self) -> None:
        if not self.ext_id:
            return
        try:
            actions_core = importlib.import_module("omni.kit.actions.core")
        except ImportError:
            self._registered_action = None
            return
        get_registry = getattr(actions_core, "get_action_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "deregister_action"):
            self._registered_action = None
            return
        try:
            if self._registered_action is not None:
                registry.deregister_action(self._registered_action)
            else:
                registry.deregister_action(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
            self.action_status = "Kit action deregistered."
        except Exception as exc:
            self.action_status = f"Kit action cleanup failed: {exc}"
        self._registered_action = None

    def _register_menu(self) -> None:
        if not self.ext_id:
            self.menu_status = "Kit menu unavailable: extension id is unset."
            return
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError as exc:
            self.menu_status = f"Kit menu unavailable: omni.kit.menu.utils ({exc})."
            return
        menu_item_type = getattr(menu_utils, "MenuItemDescription", None)
        add_menu_items = getattr(menu_utils, "add_menu_items", None)
        if menu_item_type is None or not callable(add_menu_items):
            self.menu_status = "Kit menu unavailable: menu utils API missing."
            return
        try:
            self._menu_items = [
                menu_item_type(
                    name=OMNI_WINDOW_TITLE,
                    ticked=True,
                    ticked_fn=lambda _value=False: self.is_window_visible(),
                    onclick_action=(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW),
                )
            ]
            add_menu_items(self._menu_items, name=OMNI_MENU_GROUP)
        except Exception as exc:
            self.menu_status = f"Kit menu registration failed: {exc}"
            self._menu_items = []
            return
        self.menu_status = (
            f"Kit menu registered: {OMNI_MENU_GROUP} -> {OMNI_WINDOW_TITLE}."
        )

    def _unregister_menu(self) -> None:
        if not self._menu_items:
            return
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError:
            self._menu_items = []
            return
        remove_menu_items = getattr(menu_utils, "remove_menu_items", None)
        if callable(remove_menu_items):
            try:
                remove_menu_items(self._menu_items, name=OMNI_MENU_GROUP)
                self.menu_status = "Kit menu deregistered."
            except Exception as exc:
                self.menu_status = f"Kit menu cleanup failed: {exc}"
        self._menu_items = []

    def _register_hotkey(self) -> None:
        if not self.ext_id:
            self.hotkey_status = "Kit hotkey unavailable: extension id is unset."
            return
        hotkey = self._configured_hotkey()
        if not hotkey:
            self.hotkey_status = "Kit hotkey disabled by configuration."
            return
        try:
            hotkeys_core = importlib.import_module("omni.kit.hotkeys.core")
        except ImportError as exc:
            self.hotkey_status = (
                "Kit hotkey unavailable: omni.kit.hotkeys.core "
                f"({exc}); menu/action remain registered."
            )
            return
        get_registry = getattr(hotkeys_core, "get_hotkey_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "register_hotkey"):
            self.hotkey_status = (
                "Kit hotkey unavailable: hotkey registry missing; "
                "menu/action remain registered."
            )
            return
        if hasattr(registry, "deregister_hotkeys"):
            with suppress(Exception):
                registry.deregister_hotkeys(self.ext_id, hotkey)
        try:
            self._registered_hotkey = registry.register_hotkey(
                self.ext_id,
                hotkey,
                self.ext_id,
                OMNI_ACTION_TOGGLE_WINDOW,
                filter=None,
            )
        except Exception as exc:
            self.hotkey_status = (
                f"Kit hotkey registration failed for {hotkey}: {exc}; "
                "menu/action remain registered."
            )
            return
        if self._registered_hotkey is None:
            last_error = getattr(registry, "last_error", "unknown error")
            self.hotkey_status = (
                f"Kit hotkey unavailable for {hotkey}: {last_error}; "
                "menu/action remain registered."
            )
            return
        self._registered_hotkey_key = hotkey
        self.hotkey_status = (
            f"Kit hotkey registered: {OMNI_DEFAULT_HOTKEY_DISPLAY} "
            f"({hotkey}) -> {self.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}."
        )

    def _unregister_hotkey(self) -> None:
        if not self.ext_id or self._registered_hotkey_key is None:
            self._registered_hotkey = None
            return
        try:
            hotkeys_core = importlib.import_module("omni.kit.hotkeys.core")
        except ImportError:
            self._registered_hotkey = None
            self._registered_hotkey_key = None
            return
        get_registry = getattr(hotkeys_core, "get_hotkey_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None:
            self._registered_hotkey = None
            self._registered_hotkey_key = None
            return
        try:
            if self._registered_hotkey is not None and hasattr(
                registry, "deregister_hotkey"
            ):
                registry.deregister_hotkey(self._registered_hotkey)
            elif hasattr(registry, "deregister_hotkeys"):
                registry.deregister_hotkeys(self.ext_id, self._registered_hotkey_key)
            self.hotkey_status = "Kit hotkey deregistered."
        except Exception as exc:
            self.hotkey_status = f"Kit hotkey cleanup failed: {exc}"
        self._registered_hotkey = None
        self._registered_hotkey_key = None

    def _configured_hotkey(self) -> str:
        try:
            carb_settings = importlib.import_module("carb.settings")
        except ImportError:
            return OMNI_DEFAULT_HOTKEY
        get_settings = getattr(carb_settings, "get_settings", None)
        settings = get_settings() if callable(get_settings) else None
        if settings is None or not hasattr(settings, "get"):
            return OMNI_DEFAULT_HOTKEY
        ext_ids = tuple(
            dict.fromkeys(
                (
                    self.ext_id or "isaac_audio_sensors.omni",
                    "isaac_audio_sensors.omni",
                )
            )
        )
        for ext_id in ext_ids:
            for path in (
                f"/persistent/exts/{ext_id}/shortcut",
                f"/exts/{ext_id}/shortcut",
            ):
                value = settings.get(path)
                if value is not None:
                    return _normalize_hotkey_setting(str(value))
        return OMNI_DEFAULT_HOTKEY

    def _on_window_visibility_changed(self, _visible: bool) -> None:
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError:
            return
        refresh_menu_items = getattr(menu_utils, "refresh_menu_items", None)
        if callable(refresh_menu_items):
            with suppress(Exception):
                refresh_menu_items(OMNI_MENU_GROUP)

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
                self._validation.validate_array_pose_editable(
                    self.state.array_attached_to_object
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
            _raise_first(self._validation.validate_source_position_preset(preset))
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
            _raise_first(self._validation.validate_profile_labels(labels))
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
            _raise_first(self._validation.validate_profile_match(labels, profile_id))
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
                self._validation.validate_source_attach_target_exists(
                    object_path,
                    _stage_has_prim(stage_obj, object_path),
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
                self._validation.validate_array_attach_target_exists(
                    object_path,
                    _stage_has_prim(stage_obj, object_path),
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
        _raise_first(self._validation.validate_source_metadata(self.state))

    def _source_position_from_state(self) -> tuple[float, float, float]:
        position = (
            float(self.state.source_position_x_m),
            float(self.state.source_position_y_m),
            float(self.state.source_position_z_m),
        )
        _raise_first(self._validation.validate_source_position_values(position))
        return position

    def _source_local_offset_from_state(self) -> tuple[float, float, float]:
        offset = (
            float(self.state.source_local_offset_x_m),
            float(self.state.source_local_offset_y_m),
            float(self.state.source_local_offset_z_m),
        )
        _raise_first(self._validation.validate_source_local_offset_values(offset))
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
        _raise_first(self._validation.validate_array_position_values(position))
        return position

    def _array_orientation_from_state(self) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_roll_deg),
            float(self.state.array_pitch_deg),
            float(self.state.array_yaw_deg),
        )
        _raise_first(self._validation.validate_array_orientation_values(angles))
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
        _raise_first(self._validation.validate_array_local_offset_values(offset))
        return offset

    def _array_local_orientation_from_state(
        self,
    ) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_local_roll_deg),
            float(self.state.array_local_pitch_deg),
            float(self.state.array_local_yaw_deg),
        )
        _raise_first(self._validation.validate_array_local_orientation_values(angles))
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

    def configure_sensor(
        self,
        *,
        stage: Any | None = None,
        array_prim_path: str | None = None,
        backend: str | None = None,
        update_period_s: float | None = None,
        max_events: int | None = None,
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
            if max_events is not None:
                self.state.max_events = int(max_events)
            if debug_draw is not None:
                self.state.debug_overlay_enabled = bool(debug_draw)
            if occlusion is not None:
                self.state.occlusion_enabled = bool(occlusion)
            if writer_path is not None:
                self.state.trace_enabled = True
                self.state.jsonl_trace_path = str(writer_path)

            self._validation.invalidate("sensor configuration apply")
            stage_obj = self._stage_or_error(stage)
            sensor = self._build_sensor(stage_obj)
            self.close_sensor()
            self.sensor = sensor
            self._attach_guided_reset_listener(sensor)
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
            self._validate_backend_available()
            assert self.sensor is not None
            self._stop_controller_update_subscription()
            self.sensor.start(subscribe_to_update_stream=False)
            try:
                if subscribe_to_update_stream:
                    self._start_controller_update_subscription()
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
            self._stop_controller_update_subscription()
            if self.sensor is not None:
                self.sensor.stop()
            self.state.sensor_running = False
            workflow = getattr(self, "_guided_workflow", None)
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
                    "room_acoustics backend, then Update."
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

    def clear_usd_debug_geometry(self) -> tuple[str, ...] | None:
        """Remove the authored debug subtree from the current stage."""

        try:
            context = self._context()
            self._validate_stage_present(context.stage is not None)
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
            context = self._context()
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

    def _room_spec_or_none(self, stage: Any) -> Any | None:
        """Scene-anchored or explicitly placed shoebox for room_acoustics."""

        state = self.state
        state.latest_room_summary = None
        if state.backend != "room_acoustics":
            return None
        from isaac_audio_sensors.core.room_anchor import room_spec_from_bounds
        from isaac_audio_sensors.core.types import RoomAcousticsSpec
        from isaac_audio_sensors.isaac.usd_bounds import (
            DEFAULT_SEMANTIC_ABSORPTION,
            resolve_room_absorption,
            world_aligned_bbox,
        )

        anchor_path = state.room_anchor_prim_path.strip()
        if anchor_path:
            prim = _stage_prim_at_path(stage, anchor_path)
            _raise_first(
                self._validation.validate_room_anchor_exists(
                    anchor_path,
                    prim is not None,
                )
            )
            assert prim is not None
            minimum, maximum = world_aligned_bbox(prim, prim_path=anchor_path)
            absorption, absorption_provenance = resolve_room_absorption(
                prim,
                semantic_absorption=dict(DEFAULT_SEMANTIC_ABSORPTION),
                default=DEFAULT_ROOM_ABSORPTION,
            )
            room = room_spec_from_bounds(
                min_world=minimum,
                max_world=maximum,
                room_id=DEFAULT_ROOM_ID,
                absorption=absorption,
                max_order=DEFAULT_ROOM_MAX_ORDER,
                out_of_bounds=state.room_out_of_bounds,
                anchor_prim_path=anchor_path,
            )
        else:
            # No anchor designated: place the default shoebox explicitly,
            # centered on the array (rooms no longer refit per frame).
            array_position = self._array_position_from_state()
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage).resolve_world_pose(
                    state.array_prim_path,
                    field_name="room placement array",
                )
                array_position = tuple(float(value) for value in pose.position_world)
            dimensions = DEFAULT_ROOM_DIMENSIONS_M
            room = RoomAcousticsSpec(
                room_id=DEFAULT_ROOM_ID,
                dimensions_m=dimensions,
                absorption=DEFAULT_ROOM_ABSORPTION,
                max_order=DEFAULT_ROOM_MAX_ORDER,
                origin_m=tuple(
                    array_position[axis] - dimensions[axis] / 2.0 for axis in range(3)
                ),
                out_of_bounds=state.room_out_of_bounds,
            )
            absorption_provenance = "config"
        state.latest_room_summary = {
            "room_id": room.room_id,
            "dimensions_m": room.dimensions_m,
            "origin_m": room.origin_m,
            "absorption": room.absorption,
            "absorption_provenance": absorption_provenance,
            "max_order": room.max_order,
            "out_of_bounds": room.out_of_bounds,
            "anchor_prim_path": room.anchor_prim_path,
        }
        return room

    def update_sensor(self, *, force: bool = True) -> Any | None:
        """Force one frame and update UI/export state."""

        try:
            if self.sensor is None:
                raise ExtensionActionError("Sensor is not configured.")
            previous_frame = self.sensor.latest_frame
            self._validate_attached_object_available(self.sensor.stage)
            self._validate_attached_array_available(self.sensor.stage)
            if self.state.array_prim_path.strip():
                self.sensor.array_prim_path = self.state.array_prim_path
            self.sensor.source_prim_path = (
                self.state.source_prim_path
                if self.state.source_attached_to_object
                and self.state.source_prim_path.strip()
                else None
            )
            frame = self.sensor.update(force=force)
            self._record_latest_frame(frame)
            if self.state.replicator_enabled and (
                force or _frame_is_new(previous_frame, frame)
            ):
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
                self._validation.validate_config_schema_version(
                    payload.get("schema_version")
                )
            )
            self._apply_config_summary(payload)
            self.state.config_import_path = str(requested_path)
            missing_attachment = self._attachment_status_for_current_stage()
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
            () if self.sensor is None else tuple(self.sensor.latest_debug_primitives)
        )
        serialized_primitives = (
            list(getattr(self, "_imported_overlay_primitives", ()))
            if self.sensor is None
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
                    "position_world": self._array_position_from_state(),
                    "orientation_world_quat": self._array_orientation_from_state(),
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
                    "position_world": self._source_position_from_state(),
                    "local_offset_m": self._source_local_offset_from_state(),
                    "start_time_s": state.source_start_time_s,
                    "duration_s": state.source_duration_s,
                    "gain_db": state.source_gain_db,
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
                    "source_local_offset_m": self._source_local_offset_from_state(),
                },
                "array_binding": {
                    "attached": state.array_attached_to_object,
                    "attached_object_prim_path": (
                        state.attached_array_object_prim_path or None
                    ),
                    "array_local_offset_m": self._array_local_offset_from_state(),
                    "array_local_orientation_quat": (
                        self._array_local_orientation_from_state()
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
                    "discovery_roots": self._discovery_roots(),
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
                    "replicator": self._replicator_status_dict(),
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

    def close_sensor(self) -> None:
        """Close the live sensor and writer/debug handles."""

        self._stop_controller_update_subscription()
        if self.sensor is not None:
            self.sensor.close()
        self.sensor = None
        self.state.sensor_running = False
        clear_latest_frames()

    def _start_controller_update_subscription(self) -> None:
        try:
            import omni.kit.app  # type: ignore
        except ImportError as exc:
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires omni.kit.app inside "
                "an Isaac Sim Python environment."
            ) from exc
        app = omni.kit.app.get_app()
        get_stream = getattr(app, "get_update_event_stream", None)
        if not callable(get_stream):
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires get_update_event_stream."
            )
        stream = get_stream()
        subscribe = getattr(stream, "create_subscription_to_pop", None)
        if not callable(subscribe):
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires create_subscription_to_pop."
            )

        def _on_update(_event: Any) -> None:
            self._viewport_follow_tick()
            if self.sensor is None or not self.state.sensor_running:
                return
            frame = self.update_sensor(force=False)
            if frame is not None and self._ui_window is not None:
                self._ui_window.refresh_labels()

        self._controller_update_subscription = subscribe(
            _on_update,
            name="isaac_audio_sensors.kit.update",
        )

    def _stop_controller_update_subscription(self) -> None:
        self._controller_update_subscription = None

    def _register_stage_event_subscription(self) -> None:
        """Follow viewport selection through omni.usd stage events when present."""

        try:
            import omni.usd  # type: ignore
        except ImportError:
            self._stage_event_subscription = None
            return
        try:
            context = omni.usd.get_context()
            stream = context.get_stage_event_stream()
            selection_changed = int(omni.usd.StageEventType.SELECTION_CHANGED)
            stage_change_types = {
                int(event_type): name.lower()
                for name in ("OPENING", "OPENED", "CLOSING", "CLOSED")
                if (event_type := getattr(omni.usd.StageEventType, name, None))
                is not None
            }

            def _on_stage_event(event: Any) -> None:
                event_type = int(getattr(event, "type", -1))
                stage_change = stage_change_types.get(event_type)
                if stage_change is not None:
                    self._validation.invalidate(f"USD stage {stage_change}")
                    return
                if event_type != selection_changed:
                    return
                self._handle_viewport_selection_changed()

            self._stage_event_subscription = stream.create_subscription_to_pop(
                _on_stage_event,
                name="isaac_audio_sensors.kit.stage_events",
            )
        except Exception:
            self._stage_event_subscription = None

    def _unregister_stage_event_subscription(self) -> None:
        self._stage_event_subscription = None

    def _register_simulation_reset_callback(self) -> None:
        """Subscribe to the Isaac World post-reset lifecycle when available."""

        self._unregister_simulation_reset_callback()
        try:
            simulation = importlib.import_module("isaacsim.core.simulation_manager")
            manager = simulation.SimulationManager
            event = simulation.IsaacEvents.POST_RESET
            self._simulation_reset_callback_id = manager.register_callback(
                self._handle_simulation_reset,
                event=event,
            )
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
            self._simulation_reset_callback_id = None

    def _unregister_simulation_reset_callback(self) -> None:
        callback_id = self._simulation_reset_callback_id
        self._simulation_reset_callback_id = None
        if callback_id is None:
            return
        try:
            simulation = importlib.import_module("isaacsim.core.simulation_manager")
            simulation.SimulationManager.deregister_callback(callback_id)
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
            pass

    def _viewport_follow_tick(self) -> None:
        """Per-tick fallback when stage events are unavailable, plus pose sync."""

        if (
            self._stage_event_subscription is None
            and self.state.follow_viewport_selection
        ):
            self._handle_viewport_selection_changed()
        self._live_sync_pose_tick()

    def _handle_viewport_selection_changed(self) -> None:
        try:
            context = self._context()
        except Exception:
            return
        selection = tuple(context.selected_prim_paths)
        if selection == self._last_followed_selection:
            return
        self._last_followed_selection = selection
        self.state.selected_prim_paths = selection
        if not self.state.follow_viewport_selection or not selection:
            return
        self._adopt_viewport_selection(selection[0], stage=context.stage)
        if self._ui_window is not None:
            self._ui_window.push_state_to_widgets()
            self._ui_window.refresh_labels()

    def _adopt_viewport_selection(self, path: str, *, stage: Any | None) -> None:
        """Route a selected prim to the matching target field via discovery."""

        if any(item.prim_path == path for item in self.state.discovered_arrays):
            self.state.array_prim_path = path
            self._set_status(f"Viewport selection adopted as array: {path}")
            return
        if any(item.prim_path == path for item in self.state.discovered_sources):
            self.state.source_prim_path = path
            self._set_status(f"Viewport selection adopted as source: {path}")
            return
        self.use_selected_as_object(stage=stage, selected_paths=(path,))

    def _live_sync_pose_tick(self) -> None:
        """Mirror manipulator-driven prim poses into the numeric fields."""

        state = self.state
        if not (state.live_sync_array_pose or state.live_sync_source_pose):
            return
        try:
            context = self._context()
        except Exception:
            return
        if context.stage is None:
            return
        changed = False
        if state.live_sync_source_pose and state.source_prim_path.strip():
            changed = self._sync_source_pose_from_prim(context.stage) or changed
        if state.live_sync_array_pose and state.array_prim_path.strip():
            changed = self._sync_array_pose_from_prim(context.stage) or changed
        if changed and self._ui_window is not None:
            self._ui_window.push_state_to_widgets()
            self._ui_window.refresh_labels()

    def _sync_source_pose_from_prim(self, stage: Any) -> bool:
        try:
            pose = IsaacStagePoseResolver(stage).resolve_world_pose(
                self.state.source_prim_path,
                field_name="live source",
            )
        except Exception:
            return False
        position = tuple(float(value) for value in pose.position_world)
        if _vec_close(self._source_position_from_state(), position):
            return False
        self._set_source_position_state(position)
        return True

    def _sync_array_pose_from_prim(self, stage: Any) -> bool:
        try:
            pose = IsaacStagePoseResolver(stage).resolve_world_pose(
                self.state.array_prim_path,
                field_name="live array",
            )
        except Exception:
            return False
        position = tuple(float(value) for value in pose.position_world)
        orientation = tuple(
            float(value)
            for value in (pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0))
        )
        if _vec_close(self._array_position_from_state(), position) and _vec_close(
            self._array_orientation_from_state(), orientation
        ):
            return False
        self._set_array_pose_state(position, orientation)
        return True

    def _build_sensor(self, stage: Any) -> IsaacAudioArraySensor:
        state = self.state
        self._validate_runtime_state()
        writer_path = (
            _resolve_gui_output_path(state.jsonl_trace_path)
            if state.trace_enabled
            else None
        )
        explicit_array_available = bool(
            state.array_prim_path.strip()
        ) and _stage_has_prim(stage, state.array_prim_path)
        if explicit_array_available:
            explicit_source = (
                state.source_prim_path
                if state.source_attached_to_object and state.source_prim_path.strip()
                else None
            )
            return IsaacAudioArraySensor.from_stage(
                stage=stage,
                array_prim_path=state.array_prim_path,
                source_prim_path=explicit_source,
                robot_base_prim_path=state.robot_base_prim_path or None,
                backend=state.backend,
                update_period_s=state.update_period_s,
                max_events=state.max_events,
                ambiguity_policy=state.ambiguity_policy,
                debug_draw=state.debug_overlay_enabled,
                occlusion_enabled=state.occlusion_enabled,
                writer_path=writer_path,
                waveform_dir=self._waveform_dir_or_none(),
                waveform_mode=state.waveform_mode,
                room=self._room_spec_or_none(stage),
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
            occlusion_enabled=state.occlusion_enabled,
            writer_path=writer_path,
            waveform_dir=self._waveform_dir_or_none(),
            waveform_mode=state.waveform_mode,
            room=self._room_spec_or_none(stage),
        )
        if sensor.stage_snapshot is not None:
            selected = sensor.stage_snapshot.array_by_id(sensor.array_id)
            if selected.prim_path:
                state.array_prim_path = selected.prim_path
            state.array_id = sensor.array_id
        return sensor

    def _validate_runtime_state(self) -> None:
        _raise_first(self._validation.validate_runtime(self.state))

    def _validate_backend_available(self) -> None:
        _raise_first(self._validation.validate_backend_available(self.state.backend))

    def _validate_backend_device(self) -> None:
        _raise_first(
            self._validation.validate_backend_device(
                self.state.backend,
                self.state.compute_device,
            )
        )

    def _validate_calibration_profile(self) -> None:
        _raise_first(
            self._validation.validate_calibration_profile(
                self.state.calibration_profile_path,
                self._calibration_array_facts(),
            )
        )

    def _calibration_array_facts(self) -> dict[str, Any]:
        return {
            "array_id": self.state.array_id,
            "device_id": self.state.device_id,
            "microphones": microphone_layout(self.state.layout_name),
            "sample_rate_hz": self.state.sample_rate_hz,
            "coordinate_convention": self.state.coordinate_convention,
        }

    def _validate_layout_state(self) -> None:
        _raise_first(self._validation.validate_layout(self.state))

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
                self._validation.validate_object_profile_mapping_known(
                    label,
                    profile_id,
                    False,
                )
            )
        return profiles

    def _sound_profile_by_id(self, profile_id: str) -> SoundProfile:
        requested = profile_id.strip()
        _raise_first(self._validation.validate_sound_profile_id_present(requested))
        for profile in self._validated_sound_profiles():
            if profile.profile_id == requested:
                return profile
        _raise_first(
            self._validation.validate_sound_profile_id_known(
                requested,
                False,
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
        _raise_first(self._validation.validate_rig_profile_id_present(requested))
        for profile in self._validated_rig_profiles():
            if profile.profile_id == requested:
                return profile
        _raise_first(
            self._validation.validate_rig_profile_id_known(
                requested,
                False,
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
        _raise_first(self._validation.validate_abs_prim_path(path, field_name))

    def _validate_stage_present(self, stage_is_open: bool) -> None:
        _raise_first(self._validation.validate_stage_present(stage_is_open))

    def _validate_selection(self, path: str | None, *, exists: bool) -> None:
        _raise_first(self._validation.validate_selection(path, exists))

    def _validate_attach_target(
        self,
        source_path: str,
        target_path: str,
        *,
        kind: str = "source",
    ) -> None:
        _raise_first(
            self._validation.validate_attach_target(
                source_path,
                target_path,
                kind=kind,
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
            self._validation.validate_attached_source_target(
                self.state.source_attached_to_object,
                object_path,
                exists,
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
            self._validation.validate_attached_array_target(
                self.state.array_attached_to_object,
                object_path,
                exists,
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
        workflow = getattr(self, "_guided_workflow", None)
        if workflow is not None:
            run_status = workflow.run_status
            if (
                run_status.configured
                and run_status.running
                and frame.frame_id != self._guided_last_run_frame_id
            ):
                self._guided_last_run_frame_id = str(frame.frame_id)
                workflow.observe_run_frame(getattr(frame, "timestamp_ms", None))
            self._guided_record_frame(frame)
        self._set_status(
            f"Updated {frame.frame_id}: {len(detections)} detection(s), "
            f"{len(primitives)} overlay primitive(s)."
        )

    def _latest_mic_world_positions(self) -> dict[str, tuple[float, float, float]]:
        if self.sensor is None:
            return {}
        sensor_spec = getattr(self.sensor, "_latest_sensor", None)
        if sensor_spec is None:
            return {}
        try:
            return dict(microphone_world_positions(sensor_spec))
        except Exception:
            return {}

    def _latest_source_prim_path(self, detection: Any | None) -> str | None:
        if detection is None:
            return None
        scene = (
            None if self.sensor is None else getattr(self.sensor, "_latest_scene", None)
        )
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

    def _apply_config_summary(self, payload: Mapping[str, Any]) -> None:
        self._validation.invalidate("configuration summary apply")
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
            self._set_array_pose_state(array["position_world"], None)
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
            self._set_source_position_state(source["position_world"])
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
        self.state.source_directivity = str(
            source.get("directivity", self.state.source_directivity)
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
        roots = binding.get("discovery_roots", self._discovery_roots())
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

    def _apply_profile_config(self, payload: Any) -> None:
        _raise_first(
            self._validation.validate_sound_profile_config_container(
                isinstance(payload, Mapping)
            )
        )
        raw_library = payload.get("profile_library")
        _raise_first(
            self._validation.validate_sound_profile_library_present(
                raw_library is not None
            )
        )
        raw_mappings = payload.get("object_profile_mappings")
        _raise_first(
            self._validation.validate_object_profile_mappings_present(
                raw_mappings is not None
            )
        )
        _raise_first(
            self._validation.validate_object_profile_mappings_mapping(
                isinstance(raw_mappings, Mapping)
            )
        )
        _raise_first(
            self._validation.validate_sound_profile_library_sequence(
                isinstance(raw_library, list | tuple)
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
            self._validation.validate_object_profile_mappings_non_empty(bool(mappings))
        )
        for label, profile_id in sorted(mappings.items()):
            if profile_id not in profile_ids:
                _raise_first(
                    self._validation.validate_object_profile_mapping_known(
                        label,
                        profile_id,
                        False,
                        config=True,
                    )
                )
        selected_profile_id = payload.get("selected_profile_id")
        selected_profile_id = (
            "" if selected_profile_id is None else str(selected_profile_id).strip()
        )
        _raise_first(
            self._validation.validate_sound_profile_id_known(
                selected_profile_id,
                selected_profile_id in profile_ids,
                config=True,
            )
        )
        self.state.profile_library = profiles
        self.state.object_profile_mappings = dict(sorted(mappings.items()))
        self.state.selected_profile_id = selected_profile_id
        applied = payload.get("applied_source_profile")
        self.state.applied_source_profile = (
            dict(applied) if isinstance(applied, Mapping) else {}
        )

    def _apply_rig_profile_config(self, payload: Any) -> None:
        _raise_first(
            self._validation.validate_rig_profile_config_container(
                isinstance(payload, Mapping)
            )
        )
        raw_library = payload.get("rig_library")
        _raise_first(
            self._validation.validate_rig_profile_library_present(
                raw_library is not None
            )
        )
        _raise_first(
            self._validation.validate_rig_profile_library_sequence(
                isinstance(raw_library, list | tuple)
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
            self._validation.validate_rig_profile_id_known(
                selected_rig_id,
                selected_rig_id in profile_ids,
                config=True,
            )
        )
        self.state.rig_profile_library = profiles
        self.state.selected_rig_profile_id = selected_rig_id
        applied = payload.get("applied_array_rig_profile")
        self.state.applied_array_rig_profile = (
            dict(applied) if isinstance(applied, Mapping) else {}
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.state.status_message = message
        self.state.error_message = message if error else None
        if self._ui_window is not None:
            self._ui_window.refresh_labels()

    def _record_error(self, action: str, exc: BaseException) -> None:
        self._set_status(f"{action}: {exc}", error=True)
