"""Live Isaac Sim gate for the complete guided dataset workflow."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

from isaac_audio_sensors_omni import Extension
from live_endurance_capture_gate import (
    DEMO_CONFIG,
    _author_demo_scene,
    _room_scene_adaptation,
)
from live_isaac_sim_audio_smoke import (
    _ensure_isaac_runtime,
    _record_gpu_preflight,
    _record_isaacsim_preflight,
    _record_loaded_runtime_modules,
    _record_nvidia_smi,
    _smallest_next_fix,
    _update_kit_once,
    _write_evidence,
)
from live_omniverse_extension_ux import (
    EXTENSION_ID,
    _author_minimal_stage,
    _capture_viewport_screenshot,
    _create_stage,
    _enabled_extension_id,
    _try_enable_extension_manager,
)

from isaac_audio_sensors.core.config import load_audio_config
from isaac_audio_sensors.core.dataset import SessionDataset
from isaac_audio_sensors.core.dataset.validate import validate_dataset
from isaac_audio_sensors.isaac.extension_ui import (
    CurrentStageContext,
    ExtensionController,
)
from isaac_audio_sensors.isaac.extension_ui.workflow import GuidedStage

DEFAULT_OUT = Path(
    "outputs/isaac_audio_sensors/S2/S2.7/guided_workflow_gate.json"
)
DEFAULT_EXPORT = Path(
    "outputs/isaac_audio_sensors/S2/S2.7/exported_session"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--record-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if args.record_seconds <= 0.0:
        parser.error("--record-seconds must be positive")

    session_dir = args.out.parent / "guided_recording_session"
    cancelled_dir = args.out.parent / "guided_cancelled_session"
    waveform_dir = args.out.parent / "waveforms"
    screenshot_path = args.out.parent / "guided_workflow.png"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _remove_gate_artifact(args.out)
    _remove_gate_artifact(screenshot_path)
    _remove_gate_tree(args.export_dir)
    _remove_gate_tree(session_dir)
    _remove_gate_tree(cancelled_dir)
    _remove_gate_tree(waveform_dir)

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "evidence_path": str(args.out),
        "export_dir": str(args.export_dir),
        "record_seconds_requested": args.record_seconds,
        "headless": True,
        "viewport_mode": "headless_or_existing_viewport",
        "extension_id": EXTENSION_ID,
        "stage_transitions": [],
        "invalid_states": [],
        "screenshots": "unavailable",
    }
    simulation_app = None
    extension: Extension | None = None
    exit_code = 0

    try:
        _record_isaacsim_preflight(evidence)
        _record_gpu_preflight(evidence)
        _record_nvidia_smi(evidence)
        simulation_app = _ensure_isaac_runtime(evidence)

        import omni  # type: ignore
        from pxr import Usd  # type: ignore

        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        _record_loaded_runtime_modules(evidence)
        evidence["kit_extension_manager"] = _try_enable_extension_manager(
            extension_id=EXTENSION_ID,
            extension_path=Path(__file__).resolve().parents[1]
            / "exts"
            / EXTENSION_ID,
        )

        stage, stage_mode = _create_stage(evidence)
        if stage is None:
            stage = Usd.Stage.CreateInMemory("guided_workflow_gate.usda")
            stage_mode = "pxr_usd_in_memory_fallback"
        evidence["stage_mode"] = stage_mode
        _author_minimal_stage(stage)
        _update_kit_once(evidence)

        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )

        if not RoomAcousticsBackend.is_available():
            raise RuntimeError(
                "S2.7 requires the real room_acoustics waveform backend; "
                "backend substitution is forbidden."
            )
        config = load_audio_config(DEMO_CONFIG)
        scene_adaptation = _room_scene_adaptation(config)

        startup_ext_id = _enabled_extension_id(evidence) or EXTENSION_ID
        extension = Extension()
        extension.on_startup(startup_ext_id)
        controller = extension.controller
        controller.stage_context_provider = lambda: CurrentStageContext(stage, ())
        evidence["ui_available"] = extension.ui_available
        evidence["window_type"] = type(controller.window).__name__
        evidence["ui_window_type"] = type(
            getattr(controller, "_ui_window", None)
        ).__name__
        if (
            not extension.ui_available
            or getattr(controller, "_ui_window", None) is None
        ):
            raise RuntimeError(
                "The real omni.ui guided extension window was unavailable."
            )

        _install_transition_log(controller, evidence["stage_transitions"])
        evidence["invalid_states"].append(_probe_absent_stage())

        _author_demo_scene(
            controller,
            stage,
            config,
            "room_acoustics",
            scene_adaptation,
        )
        controller.state.waveform_dir = str(waveform_dir.resolve())
        evidence["preset"] = {
            "preset_id": "xvf3800_quad_demo",
            "array_prim_path": controller.state.array_prim_path,
            "source_prim_path": controller.state.source_prim_path,
        }
        evidence["waveform_backend"] = {
            "backend_id": "room_acoustics",
            "substitution": None,
            "waveform_dir": str(waveform_dir.resolve()),
            "scene_adaptation": scene_adaptation,
        }
        if not controller.guided_advance():
            raise RuntimeError("Setup did not advance to Validate.")

        evidence["invalid_states"].append(
            _probe_invalid_backend(controller, "room_acoustics")
        )
        validation = controller.guided_validate()
        if not validation.ok:
            raise RuntimeError(f"Guided validation remained blocked: {validation}")

        sensor = _require(controller.guided_start_run(), "guided sensor start")
        first_frame = _capture_at_sim_time(controller, 0.0)
        if controller.guided_run_status.frame_count < 1:
            raise RuntimeError("Run did not observe a live sensor frame.")
        if not controller.guided_advance() or not controller.guided_mark_inspected():
            raise RuntimeError("Inspect was not explicitly completed.")
        if not controller.guided_advance():
            raise RuntimeError("Inspect did not advance to Record.")

        _require(
            controller.guided_start_recording(
                cancelled_dir,
                "guided_live_cancelled",
                50,
                False,
                scene_id="guided_scene",
                environment_id="guided_environment",
                split_group="guided_scene",
                session_seed=0,
            ),
            "cancellation recording start",
        )
        for index in range(1, 6):
            _capture_at_sim_time(controller, index * 0.05)
        incomplete = _require(
            controller.guided_cancel_recording(),
            "guided recording cancellation",
        )
        cancelled_finding = controller.guided_workflow.findings_for_stage(
            GuidedStage.RECORD
        )[0]
        retry_action = controller.guided_workflow.recovery_action(cancelled_finding)
        cancelled_blocked_status = controller.guided_workflow.status(
            GuidedStage.RECORD
        ).value
        if cancelled_blocked_status != "blocked":
            raise RuntimeError("Cancelled recording did not block Record.")
        retry_action()
        if not controller.guided_recording_status.active:
            raise RuntimeError("Cancel recovery did not start a retry recording.")
        retry_dir = Path(controller.guided_recording_status.session_dir or "")
        evidence["invalid_states"].append(
            {
                "state_id": "recording_cancelled",
                "status": "passed",
                "blocked_stage": GuidedStage.RECORD.value,
                "blocked_status": cancelled_blocked_status,
                "finding": cancelled_finding.check_id,
                "field": cancelled_finding.field,
                "completion_state": incomplete.completion_state,
                "recovery": retry_action.label,
                "retry_session_dir": str(retry_dir),
                "retry_active": True,
            }
        )

        frame_count = max(2, int(round(args.record_seconds / 0.05)))
        recording_start_s = 0.30
        last_frame = first_frame
        first_recorded_frame = None
        for index in range(frame_count + 1):
            last_frame = _capture_at_sim_time(
                controller,
                recording_start_s + index * 0.05,
            )
            if first_recorded_frame is None:
                first_recorded_frame = last_frame
        _require(controller.guided_stop_recording(), "recording finalize")
        recording = controller.guided_recording_status
        if recording.validation_status not in {"passed", "passed_with_warnings"}:
            raise RuntimeError(
                f"Finalized recording validation failed: {recording.validation_status}"
            )
        evidence["recording_stats"] = {
            "session_dir": recording.session_dir,
            "frames": recording.frames,
            "dropped_frames": recording.dropped_frames,
            "shards_promoted": recording.shards_promoted,
            "bytes_written": recording.bytes_written,
            "validation_status": recording.validation_status,
            "first_timestamp_ms": getattr(
                first_recorded_frame,
                "timestamp_ms",
                None,
            ),
            "last_timestamp_ms": getattr(last_frame, "timestamp_ms", None),
            "sim_duration_s": args.record_seconds,
        }

        exported = _require(
            controller.guided_export(args.export_dir),
            "portable guided export",
        )
        report = validate_dataset(exported)
        if report.status not in {"passed", "passed_with_warnings"}:
            raise RuntimeError(f"Canonical export validation failed: {report.status}")
        evidence["validator_summary"] = report.to_dict()
        evidence["audio_acceptance"] = _audio_acceptance(exported)
        if not evidence["audio_acceptance"]["passed"]:
            raise RuntimeError(
                f"Exported audio acceptance failed: {evidence['audio_acceptance']}"
            )
        evidence["output_inventory"] = list(controller.guided_output_inventory())
        evidence["export_status"] = _export_status_dict(
            controller.guided_export_status
        )
        evidence["sensor_type"] = type(sensor).__name__

        screenshot = _capture_viewport_screenshot(
            screenshot_path,
            framed_paths=(
                controller.state.array_prim_path,
                controller.state.source_prim_path,
            ),
        )
        evidence["screenshot_details"] = screenshot
        if screenshot.get("status") == "captured":
            evidence["screenshots"] = [str(screenshot["path"])]
        else:
            evidence["screenshots"] = "unavailable"

        if any(item.get("status") != "passed" for item in evidence["invalid_states"]):
            raise RuntimeError(
                "One or more representative invalid-state probes failed."
            )
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - live evidence preserves blockers.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "smallest_next_fix": _smallest_next_fix(exc, evidence),
            }
        )
    finally:
        if extension is not None:
            try:
                extension.on_shutdown()
                evidence["extension_shutdown"] = "ok"
            except Exception as exc:  # noqa: BLE001 - shutdown is diagnostic.
                evidence["extension_shutdown_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        if simulation_app is not None:
            try:
                simulation_app.close()
                evidence["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown is diagnostic.
                evidence["simulation_app_close_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()
    return exit_code


def _probe_absent_stage() -> dict[str, Any]:
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(None, ())
    )
    controller.guided_apply_preset("minimal_single_source")
    findings = controller.guided_workflow.findings_for_stage(GuidedStage.SETUP)
    finding = next(item for item in findings if item.check_id == "stage_present")
    recovery = controller.guided_workflow.recovery_action(finding)
    blocked_status = controller.guided_workflow.status(GuidedStage.SETUP).value
    if blocked_status != "blocked":
        raise RuntimeError("Absent-stage probe did not block Setup.")
    return {
        "state_id": "absent_stage",
        "status": "passed",
        "blocked_stage": GuidedStage.SETUP.value,
        "blocked_status": blocked_status,
        "finding": finding.check_id,
        "field": "stage",
        "recovery": recovery.label,
    }


def _probe_invalid_backend(
    controller: ExtensionController,
    expected_backend: str,
) -> dict[str, Any]:
    controller.state.backend = "planted_invalid_backend"
    report = controller.guided_validate()
    finding = next(
        item for item in report.findings if item.check_id == "backend_supported"
    )
    recovery = controller.guided_workflow.recovery_action(finding)
    blocked_status = controller.guided_workflow.status(GuidedStage.VALIDATE).value
    if blocked_status != "blocked":
        raise RuntimeError("Invalid-backend probe did not block Validate.")
    recovery()
    controller.state.backend = expected_backend
    recovered = controller.guided_validate()
    if not recovered.ok:
        raise RuntimeError("Invalid-backend recovery did not unblock Validate.")
    return {
        "state_id": "invalid_backend",
        "status": "passed",
        "blocked_stage": GuidedStage.VALIDATE.value,
        "blocked_status": blocked_status,
        "finding": finding.check_id,
        "field": finding.field,
        "recovery": recovery.label,
        "recovered": True,
        "recovered_backend": controller.state.backend,
    }


def _audio_acceptance(session_root: Path) -> dict[str, Any]:
    dataset = SessionDataset.open(session_root)
    frame_count = 0
    nonempty_ranges = 0
    nonzero_sample_values = 0
    for item in dataset.iter_records():
        frame_count += 1
        if item.audio_end_sample > item.audio_start_sample:
            nonempty_ranges += 1
        nonzero_sample_values += int(
            (dataset.read_frame_audio(item) != 0).sum()
        )
    return {
        "frame_count": frame_count,
        "nonempty_attributed_ranges": nonempty_ranges,
        "nonzero_sample_values": nonzero_sample_values,
        "all_ranges_nonempty": frame_count > 0 and nonempty_ranges == frame_count,
        "passed": (
            frame_count > 0
            and nonempty_ranges == frame_count
            and nonzero_sample_values > 0
        ),
    }


def _install_transition_log(
    controller: ExtensionController,
    transitions: list[dict[str, Any]],
) -> None:
    workflow = controller.guided_workflow
    previous_callback = workflow.on_change

    def _record() -> None:
        if previous_callback is not None:
            previous_callback()
        snapshot = {
            "stage": workflow.current_stage.value,
            "current_status": workflow.current_status.value,
            "statuses": {
                stage.value: workflow.status(stage).value for stage in GuidedStage
            },
        }
        if not transitions or transitions[-1] != snapshot:
            transitions.append(snapshot)

    workflow.on_change = _record
    _record()


def _capture_at_sim_time(controller: ExtensionController, sim_time_s: float) -> Any:
    sensor = controller.sensor
    if sensor is None:
        raise RuntimeError("Guided sensor is unavailable during live capture.")
    frame = sensor.update(sim_time_s=sim_time_s, force=True)
    controller._record_latest_frame(frame)
    return frame


def _export_status_dict(status: Any) -> dict[str, Any]:
    return {
        "destination_dir": status.destination_dir,
        "validation_status": status.validation_status,
        "split_status": status.split_status,
        "note": status.note,
        "inventory_entries": status.inventory_entries,
        "inventory_bytes": status.inventory_bytes,
    }


def _require(value: Any, label: str) -> Any:
    if value is None or value is False:
        raise RuntimeError(f"{label} returned no result.")
    return value


def _remove_gate_artifact(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def _remove_gate_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


if __name__ == "__main__":
    raise SystemExit(main())
