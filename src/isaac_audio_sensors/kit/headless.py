"""Headless driver for the guided Kit workflow."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from isaac_audio_sensors.kit.controller import ExtensionController
from isaac_audio_sensors.kit.workflow import (
    SAFE_PRESETS,
    GuidedStage,
    StageStatus,
)


class HeadlessWorkflowError(RuntimeError):
    """A located failure while driving one guided stage."""

    def __init__(self, stage: GuidedStage | str, message: str) -> None:
        self.stage = GuidedStage(stage)
        super().__init__(f"{self.stage.value}: {message}")


class HeadlessGuidedSession:
    """Drive an injected extension controller without constructing UI objects."""

    def __init__(self, controller: ExtensionController) -> None:
        self.controller = controller

    def run_from_config(
        self,
        config_path: str | Path,
        *,
        session_dir: str | Path,
        export_dir: str | Path,
        frames: int | None = None,
        seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run Setup through Export from one lossless config-summary JSON file."""

        config = Path(config_path).expanduser().resolve()
        session = Path(session_dir).expanduser()
        export = Path(export_dir).expanduser()
        payload = self._load_payload(config)
        controller = self.controller
        passed: list[str] = []

        try:
            self._apply_setup(payload, config)
            frame_count = self._frame_count(frames=frames, seconds=seconds)
            self._require_complete(GuidedStage.SETUP)
            passed.append(GuidedStage.SETUP.value)

            if not controller.guided_advance():
                self._fail_from_controller(GuidedStage.VALIDATE, "could not enter")
            validation = controller.guided_validate()
            if not validation.ok:
                details = "; ".join(
                    f"{item.check_id}: {item.message}" for item in validation.findings
                )
                raise HeadlessWorkflowError(GuidedStage.VALIDATE, details)
            passed.append(GuidedStage.VALIDATE.value)

            sensor = controller.guided_start_run()
            if sensor is None:
                self._fail_from_controller(GuidedStage.RUN, "sensor start failed")
            first_frame = self._step(0, GuidedStage.RUN)
            self._require_complete(GuidedStage.RUN)
            passed.append(GuidedStage.RUN.value)

            if not controller.guided_advance():
                self._fail_from_controller(GuidedStage.INSPECT, "could not enter")
            inspect = controller.guided_inspect_summary()
            if not controller.guided_mark_inspected():
                self._fail_from_controller(GuidedStage.INSPECT, "acceptance failed")
            self._require_complete(GuidedStage.INSPECT)
            passed.append(GuidedStage.INSPECT.value)

            if not controller.guided_advance():
                self._fail_from_controller(GuidedStage.RECORD, "could not enter")
            state = controller.state
            recorder = controller.guided_start_recording(
                session,
                state.guided_dataset_id,
                state.guided_shard_max_frames,
                state.guided_record_aligned,
                scene_id=state.guided_scene_id,
                environment_id=state.guided_environment_id,
                split_group=state.guided_split_group,
                session_seed=state.guided_session_seed,
            )
            if recorder is None:
                self._fail_from_controller(GuidedStage.RECORD, "start failed")
            for index in range(frame_count):
                self._step(index + 1, GuidedStage.RECORD)
            if controller.guided_stop_recording() is None:
                self._fail_from_controller(GuidedStage.RECORD, "finalize failed")
            self._require_complete(GuidedStage.RECORD)
            passed.append(GuidedStage.RECORD.value)

            exported = controller.guided_export(export)
            if exported is None:
                self._fail_from_controller(GuidedStage.EXPORT, "export failed")
            self._require_complete(GuidedStage.EXPORT)
            passed.append(GuidedStage.EXPORT.value)

            report = controller.guided_export_validation_report
            recording = controller.guided_recording_status
            export_status = controller.guided_export_status
            return {
                "status": "passed",
                "config": str(config),
                "session_dir": str(session),
                "export_path": str(exported),
                "stages_passed": passed,
                "recording_stats": asdict(recording),
                "validator_report": (None if report is None else report.to_dict()),
                "export_status": asdict(export_status),
                "inspect": inspect,
                "capture": {
                    "requested_frames": frames,
                    "requested_seconds": seconds,
                    "recorded_frame_target": frame_count,
                    "run_frame_id": getattr(first_frame, "frame_id", None),
                },
            }
        except HeadlessWorkflowError:
            self._cancel_active_recording()
            raise
        except Exception as exc:
            self._cancel_active_recording()
            stage = controller.guided_workflow.current_stage
            raise HeadlessWorkflowError(stage, str(exc)) from exc
        finally:
            controller.guided_stop_run()
            controller.close_sensor()

    @staticmethod
    def _load_payload(config: Path) -> Mapping[str, Any]:
        try:
            payload = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HeadlessWorkflowError(GuidedStage.SETUP, str(exc)) from exc
        if not isinstance(payload, Mapping):
            raise HeadlessWorkflowError(
                GuidedStage.SETUP,
                "configuration root must be a JSON object",
            )
        return payload

    def _apply_setup(self, payload: Mapping[str, Any], config: Path) -> None:
        controller = self.controller
        try:
            context = controller._context()
        except Exception as exc:
            raise HeadlessWorkflowError(
                GuidedStage.SETUP,
                f"no USD stage is available; run inside Isaac Sim ({exc})",
            ) from exc
        if context.stage is None:
            raise HeadlessWorkflowError(
                GuidedStage.SETUP,
                "no USD stage is available; run inside Isaac Sim",
            )
        guided = payload.get("guided")
        configured_preset = (
            guided.get("preset_id") if isinstance(guided, Mapping) else None
        )
        preset_id = str(configured_preset or SAFE_PRESETS[0].preset_id)
        if controller.guided_apply_preset(preset_id) is None:
            self._fail_from_controller(GuidedStage.SETUP, "preset apply failed")
        imported = controller.import_config_summary(config)
        if imported is None:
            self._fail_from_controller(GuidedStage.SETUP, "config import failed")

    def _step(self, index: int, stage: GuidedStage) -> Any:
        frame = self.controller.update_sensor(force=True)
        if frame is None:
            self._fail_from_controller(stage, f"frame {index} capture failed")
        return frame

    def _require_complete(self, stage: GuidedStage) -> None:
        if self.controller.guided_workflow.status(stage) is not StageStatus.COMPLETE:
            self._fail_from_controller(stage, "stage did not complete")

    def _fail_from_controller(self, stage: GuidedStage, fallback: str) -> None:
        findings = self.controller.guided_workflow.findings_for_stage(stage)
        detail = "; ".join(f"{item.check_id}: {item.message}" for item in findings)
        error = self.controller.state.error_message
        raise HeadlessWorkflowError(stage, detail or error or fallback)

    def _cancel_active_recording(self) -> None:
        if self.controller.guided_recording_status.active:
            self.controller.guided_cancel_recording()

    def _frame_count(
        self,
        *,
        frames: int | None,
        seconds: float | None,
    ) -> int:
        if frames is not None and seconds is not None:
            raise HeadlessWorkflowError(
                GuidedStage.RECORD,
                "frames and seconds are mutually exclusive",
            )
        if frames is not None:
            if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
                raise HeadlessWorkflowError(
                    GuidedStage.RECORD,
                    "frames must be a positive integer",
                )
            return int(frames)
        if seconds is None:
            return 1
        if not math.isfinite(seconds) or seconds <= 0.0:
            raise HeadlessWorkflowError(
                GuidedStage.RECORD,
                "seconds must be finite and positive",
            )
        period = float(self.controller.state.update_period_s)
        return max(1, int(math.ceil(seconds / period - 1e-12)))
