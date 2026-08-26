"""Internal recording workflow service."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
)
from isaac_audio_sensors.kit.validation import (
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

from ._service import ControllerService
from .stage_context import (
    _stage_has_prim,
)
from .state import (
    ExtensionActionError,
)
from .validation.checks import (
    check_abs_prim_path,
    check_array_geometry,
    check_attached_array_target,
    check_attached_source_target,
    check_layout,
    check_room_anchor_exists,
    check_runtime_state,
    check_source_geometry,
    check_source_metadata,
    check_stage_present,
)
from .workflow import (
    SAFE_PRESETS,
    ExportStatus,
    GuidedStage,
    GuidedWorkflow,
    RecordingStatus,
    RunStatus,
    SafePreset,
)


class RecordingWorkflow(ControllerService):
    """Own recording workflow behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self._guided_recorder = None
        self._guided_recording_request = None
        self._guided_last_run_frame_id = None
        self._guided_last_recorded_frame_id = None
        self._guided_last_recorded_timestamp_ms = None
        self._guided_last_recorded_producer_index = None
        self._guided_reset_pending = False
        self._guided_dataset_validation_report = None
        self._guided_export_validation_report = None
        self._guided_output_entries = ()
        self._guided_workflow: GuidedWorkflow | None = None

    @property
    def guided_workflow(self) -> GuidedWorkflow:
        """Return the lazily constructed import-safe guided workflow."""

        workflow = self._guided_workflow
        if workflow is None:
            workflow = GuidedWorkflow(
                self.state,
                recovery_handlers={
                    "stage": lambda _finding: self._host.refresh_stage_selection(),
                    "preset": lambda _finding: self.guided_apply_preset(
                        self.state.guided_preset_id or SAFE_PRESETS[0].preset_id
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
            stage_present = self._host.current_stage_context().stage is not None
            preset = self.guided_workflow.apply_preset(
                preset_id,
                lambda item: self._host._configuration._apply_config_summary(
                    item.config_summary()
                ),
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
        context = self._host.current_stage_context()
        stage = context.stage
        reports = [
            ValidationReport(check_stage_present(stage is not None)),
            ValidationReport(check_runtime_state(state)),
            self._validation.validate_backend_available(state.backend),
            self._validation.validate_backend_device(
                state.backend,
                state.compute_device,
            ),
            ValidationReport(
                check_abs_prim_path(
                    state.source_prim_path,
                    "source_prim_path",
                )
            ),
            ValidationReport(check_source_metadata(state)),
            ValidationReport(check_source_geometry(state)),
            ValidationReport(check_array_geometry(state)),
            ValidationReport(check_layout(state)),
            self._validation.validate_calibration_profile(
                state.calibration_profile_path,
                self._host._sensor_session._calibration_array_facts(),
            ),
        ]
        if state.room_anchor_prim_path:
            reports.append(
                ValidationReport(
                    check_room_anchor_exists(
                        state.room_anchor_prim_path,
                        stage is not None
                        and _stage_has_prim(stage, state.room_anchor_prim_path),
                    )
                )
            )
        reports.extend(
            (
                ValidationReport(
                    check_attached_source_target(
                        state.source_attached_to_object,
                        state.attached_object_prim_path or state.object_prim_path,
                        None
                        if not state.source_attached_to_object or stage is None
                        else _stage_has_prim(
                            stage,
                            state.attached_object_prim_path or state.object_prim_path,
                        ),
                    )
                ),
                ValidationReport(
                    check_attached_array_target(
                        state.array_attached_to_object,
                        state.attached_array_object_prim_path,
                        None
                        if not state.array_attached_to_object or stage is None
                        else _stage_has_prim(
                            stage,
                            state.attached_array_object_prim_path,
                        ),
                    )
                ),
            )
        )
        findings = tuple(
            dict.fromkeys(finding for report in reports for finding in report.findings)
        )
        report = self.guided_workflow.record_validation(ValidationReport(findings))
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
        sensor = self._host.configure_sensor()
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
        started = self._host.start_sensor()
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

        self._host.stop_sensor()

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
            if not self.state.sensor_running or self._host.sensor is None:
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
        latest = None if self._host.sensor is None else self._host.sensor.latest_frame
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
        sensor.add_reset_listener(self.guided_notify_simulator_reset)

    def _handle_simulation_reset(self, _event: Any) -> None:
        """Reset the sensor and recorder boundary from Isaac's reset lifecycle."""

        self.guided_notify_simulator_reset()
        if self._host.sensor is not None:
            self._host.sensor.reset()

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
