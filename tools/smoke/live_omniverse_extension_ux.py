"""Live Isaac Sim/Kit smoke for the Omniverse extension reference UX."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import platform
import struct
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from isaac_audio_sensors_omni import Extension
from live_isaac_sim_audio_smoke import (
    _ensure_isaac_runtime,
    _record_gpu_preflight,
    _record_isaacsim_preflight,
    _record_loaded_runtime_modules,
    _record_nvidia_smi,
    _remove_existing_artifacts,
    _smallest_next_fix,
    _update_kit_once,
    _write_evidence,
)

from isaac_audio_sensors.core.io.traces import frame_from_trace_dict
from isaac_audio_sensors.isaac.pose_resolver import IsaacStagePoseResolver
from isaac_audio_sensors.kit import (
    OMNI_ACTION_TOGGLE_WINDOW,
    OMNI_DEFAULT_HOTKEY,
    OMNI_MENU_GROUP,
    OMNI_WINDOW_TITLE,
    CurrentStageContext,
    ExtensionController,
)
from isaac_audio_sensors.kit.instruments import (
    compass_view_model,
    meter_view_models,
    render_instruments_panel_rgba,
    timeline_rows,
    write_rgba_png,
)

EXTENSION_ID = "isaac_audio_sensors.omni"
EXPECTED_UI_SECTIONS = (
    "Stage",
    "Author Array",
    "Author Source",
    "Sensor",
    "Instruments",
    "Audio Output",
    "Replicator",
    "Export",
)
EXPECTED_INSTRUMENT_KEYS = (
    "compass",
    "compass_provider",
    "meters",
    "timeline",
)
EXPECTED_UI_BUTTONS = (
    "Refresh",
    "Use Array",
    "Use Source",
    "Use Object",
    "Use Base",
    "Create Demo Object",
    "Discover",
    "Create/Attach Array",
    "Select Rig Profile",
    "Apply Rig Profile",
    "Read Array Transform",
    "Apply Array Pose",
    "Attach Array To Object",
    "Detach Array",
    "Read Selected Transform",
    "Apply Position",
    "Select Profile",
    "Auto From Object",
    "Apply Profile",
    "Front",
    "Right",
    "Left",
    "Behind",
    "Create/Attach Source",
    "Attach Source To Object",
    "Detach Source",
    "Start",
    "Stop",
    "Update",
    "Play",
    "Stop Audio",
    "Open WAV Folder",
    "Clear Debug Geometry",
    "Flush",
    "Export Latest",
    "Export Config",
    "Load Config",
)
EXPECTED_STRING_FIELDS = (
    "array_id",
    "array_prim_path",
    "audio_asset_path",
    "config_export_path",
    "config_import_path",
    "discovery_roots_text",
    "jsonl_trace_path",
    "latest_frame_export_path",
    "object_prim_path",
    "replicator_annotator_name",
    "replicator_output_dir",
    "replicator_writer_name",
    "robot_base_prim_path",
    "source_class_label",
    "source_directivity",
    "source_id",
    "source_prim_path",
    "selected_profile_id",
    "selected_rig_profile_id",
    "usd_debug_root",
    "waveform_dir",
)
EXPECTED_FLOAT_FIELDS = (
    "array_local_offset_x_m",
    "array_local_offset_y_m",
    "array_local_offset_z_m",
    "array_local_yaw_deg",
    "array_local_pitch_deg",
    "array_local_roll_deg",
    "array_position_x_m",
    "array_position_y_m",
    "array_position_z_m",
    "array_yaw_deg",
    "array_pitch_deg",
    "array_roll_deg",
    "source_local_offset_x_m",
    "source_local_offset_y_m",
    "source_local_offset_z_m",
    "source_duration_s",
    "source_gain_db",
    "source_position_x_m",
    "source_position_y_m",
    "source_position_z_m",
    "source_start_time_s",
    "update_period_s",
)
EXPECTED_INT_FIELDS = ("max_events", "sample_rate_hz")
EXPECTED_BOOL_FIELDS = (
    "author_child_microphones",
    "debug_overlay_enabled",
    "follow_viewport_selection",
    "live_sync_array_pose",
    "live_sync_source_pose",
    "replicator_enabled",
    "trace_enabled",
    "usd_debug_enabled",
    "waveform_enabled",
)
EXPECTED_COMBO_FIELDS = (
    "ambiguity_policy",
    "backend",
    "layout_name",
    "waveform_mode",
)
ARRAY_RIG_PROFILE_ID = "quad_cross_120mm"
ARRAY_MOUNT_PRIM_PATH = "/World/Rig/RobotMount"
ARRAY_MOUNT_POSITION_BEFORE = (0.0, -1.0, 0.0)
ARRAY_MOUNT_POSITION_AFTER = (1.5, -2.0, 0.5)
ARRAY_MOUNT_LOCAL_OFFSET = (0.0, 0.0, 0.1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/omniverse_extension_live_ux.json"),
    )
    parser.add_argument(
        "--require-screenshot",
        action="store_true",
        help="Fail the live gate if any required viewport screenshot is unavailable.",
    )
    args = parser.parse_args()

    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    pre_frame_config_path = args.out.with_suffix(".pre_frame.config.json")
    latest_frame_path = args.out.with_suffix(".latest_frame.json")
    replicator_dir = args.out.with_suffix(".replicator")
    screenshot_path = args.out.with_suffix(".viewport.png")
    generic_artifacts = {
        "frame_trace_path": frame_trace_path,
        "config_path": config_path,
        "latest_frame_path": latest_frame_path,
        "replicator_dir": replicator_dir,
        "screenshot_path": screenshot_path,
    }
    _remove_existing_artifacts(
        args.out,
        frame_trace_path,
        config_path,
        pre_frame_config_path,
        latest_frame_path,
        screenshot_path,
    )
    _prepare_output_dir(replicator_dir)

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "evidence_path": str(args.out),
        "frame_trace_path": str(frame_trace_path),
        "config_path": str(config_path),
        "pre_frame_config_path": str(pre_frame_config_path),
        "latest_frame_path": str(latest_frame_path),
        "replicator_output_dir": str(replicator_dir),
        "screenshot_path": str(screenshot_path),
        "extension_id": EXTENSION_ID,
        "extension_path": str(
            Path(__file__).resolve().parents[2] / "exts" / EXTENSION_ID
        ),
        "headless": True,
        "viewport_mode": "headless_or_existing_viewport",
        "require_screenshot": args.require_screenshot,
        "workflow_steps": [],
        "object_attach_live_qa": {},
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

        evidence["pxr_imported"] = True
        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        _record_loaded_runtime_modules(evidence)
        _record_gpu_preflight(evidence)
        evidence["kit_extension_manager"] = _try_enable_extension_manager(
            extension_id=EXTENSION_ID,
            extension_path=Path(evidence["extension_path"]),
        )

        stage, stage_mode = _create_stage(evidence)
        evidence["stage_mode"] = stage_mode
        if stage is None:
            stage = Usd.Stage.CreateInMemory("omniverse_extension_live_ux.usda")
            evidence["stage_mode"] = "pxr_usd_in_memory_fallback"
        _author_minimal_stage(stage)
        _update_kit_once(evidence)

        startup_ext_id = _enabled_extension_id(evidence) or EXTENSION_ID
        evidence["manual_extension_startup_id"] = startup_ext_id
        extension = Extension()
        extension.on_startup(startup_ext_id)
        controller = extension.controller
        controller.ext_id = startup_ext_id
        controller.state.backend = "tdoa_synthetic"
        controller.state.jsonl_trace_path = str(frame_trace_path)
        controller.state.latest_frame_export_path = str(latest_frame_path)
        controller.state.config_export_path = str(config_path)
        controller.state.config_import_path = str(config_path)
        controller.state.replicator_enabled = True
        controller.state.replicator_output_dir = str(replicator_dir)
        controller.state.usd_debug_enabled = True
        if getattr(controller, "_ui_window", None) is not None:
            controller._ui_window.push_state_to_widgets()

        evidence["ui_available"] = extension.ui_available
        evidence["ui_control_inventory"] = _inventory_ui_controls(controller)
        evidence["omnigraph"] = _collect_omnigraph_evidence(controller)
        evidence["window_integration"] = _probe_window_integrations(controller)
        evidence["extension_manager_metadata"] = _probe_extension_manager_metadata(
            Path(evidence["extension_path"]),
            extension_id=EXTENSION_ID,
        )
        evidence["ui_editable_model_probe"] = _probe_ui_editable_models(controller)
        evidence["ui_invalid_numeric_probe"] = _probe_ui_invalid_numeric(controller)
        evidence["export_latest_without_frame"] = _probe_export_latest_without_frame(
            controller
        )
        evidence["error_checks"] = _run_error_checks(stage)

        controller.state.config_export_path = str(pre_frame_config_path)
        if getattr(controller, "_ui_window", None) is not None:
            controller._ui_window.push_state_to_widgets()
        _step(
            evidence,
            "export_config_summary_before_frame",
            controller.export_config_summary,
        )
        controller.state.config_export_path = str(config_path)
        if getattr(controller, "_ui_window", None) is not None:
            controller._ui_window.push_state_to_widgets()

        generic_result = _step(
            evidence,
            "generic_scene_object_attach_workflow",
            lambda: _run_object_attach_scenario(
                evidence=evidence,
                controller=controller,
                stage=stage,
                fixture_kind="generic_scene",
                artifacts=generic_artifacts,
                object_path="/World/Oven",
                source_prim_path="/World/Sources/SpeakerA",
                source_id="speaker_a",
                parent_position_before=(2.0, 0.0, 0.0),
                parent_position_after=(0.0, 2.0, 0.0),
                local_offset_before=(0.0, 0.0, 0.0),
                local_offset_after=(0.5, 0.0, 0.25),
                discovery_roots_text="/World/Oven",
                stage_setup=_author_minimal_stage,
                require_screenshot=args.require_screenshot,
            ),
        )
        evidence["object_attach_live_qa"]["generic_scene"] = generic_result
        _promote_legacy_generic_evidence(evidence, generic_result)

        evidence["instruments"] = _step(
            evidence,
            "instruments_live_qa",
            lambda: _collect_instruments_evidence(
                controller,
                screenshot_path=args.out.with_suffix(".instruments.png"),
            ),
        )
        evidence["usd_debug"] = _step(
            evidence,
            "usd_debug_live_qa",
            lambda: _collect_usd_debug_evidence(controller, stage=stage),
        )
        evidence["audio_output"] = _step(
            evidence,
            "audio_output_live_qa",
            lambda: _collect_audio_output_evidence(controller, stage=stage),
        )

        _validate_live_extension_outputs(evidence=evidence)
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - smoke evidence records exact error.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "blocked",
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
            except Exception as exc:  # noqa: BLE001 - diagnostic only.
                evidence["extension_shutdown_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        if simulation_app is not None:
            try:
                simulation_app.close()
                evidence["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown diagnostic only.
                evidence["simulation_app_close_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()

    return exit_code


def _step(evidence: dict[str, Any], name: str, callback: Any) -> Any:
    try:
        result = callback()
    except Exception as exc:
        record = {
            "name": name,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        evidence["workflow_steps"].append(record)
        raise
    record = {
        "name": name,
        "status": "passed" if result is not None else "returned_none",
        "result_summary": _result_summary(result),
    }
    evidence["workflow_steps"].append(record)
    if result is None:
        raise RuntimeError(f"Workflow step {name!r} returned None.")
    return result


def _stringify_artifacts(artifacts: dict[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in sorted(artifacts.items())}


def _run_object_attach_scenario(
    *,
    evidence: dict[str, Any],
    controller: ExtensionController,
    stage: Any,
    fixture_kind: str,
    artifacts: dict[str, Path],
    object_path: str,
    source_prim_path: str,
    source_id: str,
    parent_position_before: tuple[float, float, float],
    parent_position_after: tuple[float, float, float],
    local_offset_before: tuple[float, float, float],
    local_offset_after: tuple[float, float, float],
    discovery_roots_text: str,
    stage_setup: Any | None,
    usd_path: Path | None = None,
    stage_open: dict[str, Any] | None = None,
    require_screenshot: bool = False,
) -> dict[str, Any]:
    label = fixture_kind
    if stage_setup is not None:
        stage_setup(stage)
    _ensure_audio_seed_prims(stage, source_prim_path=source_prim_path)
    object_prim = _require_stage_prim(stage, object_path)
    _set_translate(object_prim, parent_position_before)
    _update_kit_once(evidence)

    controller.close_sensor()
    controller.state.backend = "tdoa_synthetic"
    controller.state.trace_enabled = True
    controller.state.jsonl_trace_path = str(artifacts["frame_trace_path"])
    controller.state.latest_frame_export_path = str(artifacts["latest_frame_path"])
    controller.state.config_export_path = str(artifacts["config_path"])
    controller.state.config_import_path = str(artifacts["config_path"])
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(artifacts["replicator_dir"])
    controller.state.array_prim_path = "/World/Rig/AudioArray"
    controller.state.source_prim_path = source_prim_path
    controller.state.source_id = source_id
    controller.state.source_class_label = "Speech"
    controller.state.audio_asset_path = "generated://impulse"
    controller.state.source_position_x_m = 2.0
    controller.state.source_position_y_m = 0.0
    controller.state.source_position_z_m = 0.0
    controller.state.object_prim_path = object_path
    controller.state.object_label = _path_name(object_path)
    controller.state.source_attached_to_object = False
    controller.state.attached_object_prim_path = ""
    controller.state.source_local_offset_x_m = local_offset_before[0]
    controller.state.source_local_offset_y_m = local_offset_before[1]
    controller.state.source_local_offset_z_m = local_offset_before[2]
    controller.state.robot_base_prim_path = ""
    controller.state.discovery_roots_text = discovery_roots_text
    controller.state.array_attached_to_object = False
    controller.state.attached_array_object_prim_path = ""
    controller.state.array_position_x_m = 0.0
    controller.state.array_position_y_m = 0.0
    controller.state.array_position_z_m = 0.0
    controller.state.array_yaw_deg = 0.0
    controller.state.array_pitch_deg = 0.0
    controller.state.array_roll_deg = 0.0
    controller.state.array_local_offset_x_m = 0.0
    controller.state.array_local_offset_y_m = 0.0
    controller.state.array_local_offset_z_m = 0.0
    controller.state.array_local_yaw_deg = 0.0
    controller.state.array_local_pitch_deg = 0.0
    controller.state.array_local_roll_deg = 0.0
    controller.state.selected_rig_profile_id = ARRAY_RIG_PROFILE_ID
    controller.state.applied_array_rig_profile = {}
    if getattr(controller, "_ui_window", None) is not None:
        controller._ui_window.push_state_to_widgets()

    result: dict[str, Any] = {
        "status": "started",
        "fixture_kind": fixture_kind,
        "usd_path": str(usd_path) if usd_path is not None else None,
        "artifacts": _stringify_artifacts(artifacts),
        "stage_open": stage_open,
        "stage_summary": _stage_summary(stage),
        "selected_object_path": object_path,
        "selected_object_label": _path_name(object_path),
        "selected_object_type": _prim_type_name(object_prim),
        "selection_method": "controller.use_selected_as_object",
        "source_seed_path": source_prim_path,
        "local_offset_before": list(local_offset_before),
        "local_offset_after": list(local_offset_after),
    }

    _set_context_selection(("/World/Rig/AudioArray",), evidence)
    _step(
        evidence,
        f"{label}_refresh_stage_selection_array",
        lambda: controller.refresh_stage_selection(
            stage=stage,
            selected_paths=("/World/Rig/AudioArray",),
        ),
    )
    _step(
        evidence,
        f"{label}_use_selected_as_array",
        lambda: controller.use_selected_as_array(
            stage=stage,
            selected_paths=("/World/Rig/AudioArray",),
        ),
    )
    _step(
        evidence,
        f"{label}_author_array",
        lambda: controller.author_array(stage=stage),
    )
    _set_context_selection((source_prim_path,), evidence)
    _step(
        evidence,
        f"{label}_use_selected_as_source",
        lambda: controller.use_selected_as_source(
            stage=stage,
            selected_paths=(source_prim_path,),
        ),
    )
    _step(
        evidence,
        f"{label}_read_selected_source_transform",
        lambda: controller.read_selected_source_transform(
            stage=stage,
            selected_paths=(source_prim_path,),
        ),
    )
    result["source_position_after_read"] = _source_position_state(controller)
    _step(
        evidence,
        f"{label}_apply_source_front_preset",
        lambda: controller.apply_source_position_preset("front", stage=stage),
    )
    result["source_position_after_front_preset"] = _source_position_state(controller)
    _step(
        evidence,
        f"{label}_author_source",
        lambda: controller.author_source(stage=stage),
    )
    _set_context_selection((object_path,), evidence)
    _step(
        evidence,
        f"{label}_use_selected_as_object",
        lambda: controller.use_selected_as_object(
            stage=stage,
            selected_paths=(object_path,),
        ),
    )
    discovery = _step(
        evidence,
        f"{label}_refresh_discovery",
        lambda: controller.refresh_discovery(stage=stage),
    )
    result["discovery"] = {
        "count": len(discovery),
        "selected_object_found": any(
            getattr(item, "prim_path", "") == object_path for item in discovery
        ),
        "sample": [
            {
                "id": getattr(item, "id", ""),
                "prim_path": getattr(item, "prim_path", ""),
                "reasons": list(getattr(item, "reasons", ())),
            }
            for item in tuple(discovery)[:8]
        ],
    }
    _step(
        evidence,
        f"{label}_attach_source_to_object",
        lambda: controller.attach_source_to_object(stage=stage),
    )
    selected_profile = _step(
        evidence,
        f"{label}_auto_select_sound_profile",
        lambda: controller.auto_select_profile_from_object(
            stage=stage,
            selected_paths=(object_path,),
        ),
    )
    result["sound_profile_selection"] = _sound_profile_state(
        controller,
        selected_profile,
    )
    _step(
        evidence,
        f"{label}_apply_sound_profile",
        lambda: controller.apply_selected_profile(stage=stage),
    )
    result["sound_profile_application"] = _source_profile_state(controller, stage)
    result["source_object_attachment"] = _source_object_state(controller)
    attached_source_path = controller.state.source_prim_path
    result["source_path"] = attached_source_path
    result["parent_transform_before"] = _pose_summary(stage, object_path)
    result["source_transform_before"] = _pose_summary(stage, attached_source_path)

    _step(
        evidence,
        f"{label}_start_sensor",
        lambda: controller.start_sensor(
            stage=stage,
            subscribe_to_update_stream=False,
        ),
    )
    _step(evidence, f"{label}_start_replicator", controller.start_replicator)
    before_frame = _step(
        evidence,
        f"{label}_update_sensor_before_parent_move",
        controller.update_sensor,
    )
    result["frame_before_parent_move"] = _frame_source_summary(before_frame)

    _set_translate(object_prim, parent_position_after)
    result["parent_transform_move_command"] = {
        "prim_path": object_path,
        "position_world": list(parent_position_after),
        "attached_source_prim_path": attached_source_path,
        "method": "live USD Xform edit equivalent to normal Isaac transform",
    }
    _update_kit_once(evidence)
    after_move_frame = _step(
        evidence,
        f"{label}_update_sensor_after_parent_move",
        controller.update_sensor,
    )
    result["parent_transform_after"] = _pose_summary(stage, object_path)
    result["source_transform_after_parent_move"] = _pose_summary(
        stage,
        attached_source_path,
    )
    result["frame_after_parent_move"] = _frame_source_summary(after_move_frame)
    result["object_move_changed_frame"] = _source_frame_changed(
        before_frame,
        after_move_frame,
    )

    result["source_transform_before_local_offset_change"] = _pose_summary(
        stage,
        attached_source_path,
    )
    controller.state.source_local_offset_x_m = local_offset_after[0]
    controller.state.source_local_offset_y_m = local_offset_after[1]
    controller.state.source_local_offset_z_m = local_offset_after[2]
    if getattr(controller, "_ui_window", None) is not None:
        controller._ui_window.push_state_to_widgets()
    _step(
        evidence,
        f"{label}_apply_changed_local_offset",
        lambda: controller.attach_source_to_object(stage=stage),
    )
    _update_kit_once(evidence)
    after_offset_frame = _step(
        evidence,
        f"{label}_update_sensor_after_local_offset_change",
        controller.update_sensor,
    )
    result["source_transform_after_local_offset_change"] = _pose_summary(
        stage,
        attached_source_path,
    )
    result["frame_after_local_offset_change"] = _frame_source_summary(
        after_offset_frame
    )
    result["local_offset_changed_frame"] = _source_frame_changed(
        after_move_frame,
        after_offset_frame,
    )

    mount_prim = _require_stage_prim(stage, ARRAY_MOUNT_PRIM_PATH)
    _set_translate(mount_prim, ARRAY_MOUNT_POSITION_BEFORE)
    _set_context_selection((controller.state.array_prim_path,), evidence)
    _step(
        evidence,
        f"{label}_read_selected_array_transform",
        lambda: controller.read_selected_array_transform(
            stage=stage,
            selected_paths=(controller.state.array_prim_path,),
        ),
    )
    result["array_pose_after_read"] = _array_pose_state(controller)
    _step(
        evidence,
        f"{label}_select_rig_profile",
        lambda: controller.select_rig_profile(ARRAY_RIG_PROFILE_ID),
    )
    _step(
        evidence,
        f"{label}_apply_rig_profile",
        lambda: controller.apply_selected_rig_profile(stage=stage),
    )
    result["rig_profile_application"] = _rig_profile_state(controller, stage)
    before_rotation_frame = _step(
        evidence,
        f"{label}_update_sensor_before_array_rotation",
        controller.update_sensor,
    )
    result["frame_before_array_rotation"] = _frame_array_summary(
        controller,
        before_rotation_frame,
    )
    controller.state.array_yaw_deg = 90.0
    if getattr(controller, "_ui_window", None) is not None:
        controller._ui_window.push_state_to_widgets()
    _step(
        evidence,
        f"{label}_apply_array_pose_yaw",
        lambda: controller.apply_array_pose(stage=stage),
    )
    _update_kit_once(evidence)
    after_rotation_frame = _step(
        evidence,
        f"{label}_update_sensor_after_array_rotation",
        controller.update_sensor,
    )
    result["frame_after_array_rotation"] = _frame_array_summary(
        controller,
        after_rotation_frame,
    )
    result["array_rotation_changed_frame"] = _array_rotation_changed(
        result["frame_before_array_rotation"],
        result["frame_after_array_rotation"],
    )

    result["array_transform_before_mount"] = _pose_summary(
        stage,
        controller.state.array_prim_path,
    )
    saved_object_path = controller.state.object_prim_path
    saved_object_label = controller.state.object_label
    controller.state.object_prim_path = ARRAY_MOUNT_PRIM_PATH
    controller.state.array_local_offset_x_m = ARRAY_MOUNT_LOCAL_OFFSET[0]
    controller.state.array_local_offset_y_m = ARRAY_MOUNT_LOCAL_OFFSET[1]
    controller.state.array_local_offset_z_m = ARRAY_MOUNT_LOCAL_OFFSET[2]
    controller.state.array_local_yaw_deg = 0.0
    controller.state.array_local_pitch_deg = 0.0
    controller.state.array_local_roll_deg = 0.0
    if getattr(controller, "_ui_window", None) is not None:
        controller._ui_window.push_state_to_widgets()
    _step(
        evidence,
        f"{label}_attach_array_to_object",
        lambda: controller.attach_array_to_object(stage=stage),
    )
    controller.state.object_prim_path = saved_object_path
    controller.state.object_label = saved_object_label
    if getattr(controller, "_ui_window", None) is not None:
        controller._ui_window.push_state_to_widgets()
    result["array_object_attachment"] = _array_object_state(controller)
    attached_array_path = controller.state.array_prim_path
    result["array_path"] = attached_array_path
    result["mount_transform_before"] = _pose_summary(stage, ARRAY_MOUNT_PRIM_PATH)
    before_mount_frame = _step(
        evidence,
        f"{label}_update_sensor_before_mount_move",
        controller.update_sensor,
    )
    result["frame_before_array_mount_move"] = _frame_array_summary(
        controller,
        before_mount_frame,
    )
    _set_translate(mount_prim, ARRAY_MOUNT_POSITION_AFTER)
    result["mount_transform_move_command"] = {
        "prim_path": ARRAY_MOUNT_PRIM_PATH,
        "position_world": list(ARRAY_MOUNT_POSITION_AFTER),
        "attached_array_prim_path": attached_array_path,
        "method": "live USD Xform edit equivalent to normal Isaac transform",
    }
    _update_kit_once(evidence)
    after_mount_frame = _step(
        evidence,
        f"{label}_update_sensor_after_mount_move",
        controller.update_sensor,
    )
    result["mount_transform_after"] = _pose_summary(stage, ARRAY_MOUNT_PRIM_PATH)
    result["array_transform_after_mount_move"] = _pose_summary(
        stage,
        attached_array_path,
    )
    result["frame_after_array_mount_move"] = _frame_array_summary(
        controller,
        after_mount_frame,
    )
    result["array_move_changed_frame"] = _array_move_changed(
        result["frame_before_array_mount_move"],
        result["frame_after_array_mount_move"],
    )

    _step(evidence, f"{label}_export_latest_frame", controller.export_latest_frame)
    _step(evidence, f"{label}_flush_replicator", controller.flush_replicator)
    _step(evidence, f"{label}_export_config_summary", controller.export_config_summary)
    result["config_export_path"] = str(artifacts["config_path"])
    result["config_export"] = _config_binding_summary(artifacts["config_path"])

    result["config_import_result"] = _probe_import_update_after_config(
        stage=stage,
        config_path=artifacts["config_path"],
    )
    result["screenshot"] = _capture_viewport_screenshot(
        artifacts["screenshot_path"],
        framed_paths=(
            object_path,
            attached_source_path,
            ARRAY_MOUNT_PRIM_PATH,
            attached_array_path,
        ),
    )
    if require_screenshot and result["screenshot"].get("status") != "captured":
        result["status"] = "failed"
        evidence.setdefault("object_attach_live_qa", {})[fixture_kind] = result
        _enforce_required_screenshot(result["screenshot"], fixture_kind)

    result["missing_object_probe"] = _probe_missing_object_status(
        controller=controller,
        stage=stage,
        object_path=object_path,
    )
    _step(
        evidence,
        f"{label}_stop_sensor",
        lambda: (controller.stop_sensor() or "stopped"),
    )
    _step(evidence, f"{label}_stop_replicator", controller.stop_replicator)
    result["replicator_status"] = controller._replicator_status_dict()
    result["replicator_artifacts"] = _replicator_artifacts(artifacts["replicator_dir"])
    result["status"] = "passed"
    return result


def _ensure_audio_seed_prims(stage: Any, *, source_prim_path: str) -> None:
    for path, prim_type in (
        ("/World", "Xform"),
        ("/World/Rig", "Xform"),
        ("/World/Rig/AudioArray", "Xform"),
        (ARRAY_MOUNT_PRIM_PATH, "Xform"),
        ("/World/Sources", "Xform"),
        (source_prim_path, "Sound"),
    ):
        if not _stage_has_prim(stage, path):
            stage.DefinePrim(path, prim_type)
    source = _require_stage_prim(stage, source_prim_path)
    _set_translate(source, (2.0, 0.0, 0.0))
    mount = _require_stage_prim(stage, ARRAY_MOUNT_PRIM_PATH)
    _set_translate(mount, ARRAY_MOUNT_POSITION_BEFORE)


def _require_stage_prim(stage: Any, path: str) -> Any:
    prim = _stage_get_prim_at_path(stage, path)
    if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
        raise RuntimeError(f"Required prim is missing from live stage: {path}")
    return prim


def _stage_summary(stage: Any) -> dict[str, Any]:
    default_prim = None
    with_default = getattr(stage, "GetDefaultPrim", None)
    if callable(with_default):
        prim = with_default()
        if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
            default_prim = _prim_path(prim)
    root_layer = getattr(stage, "GetRootLayer", lambda: None)()
    return {
        "default_prim": default_prim,
        "prim_count": _stage_prim_count(stage),
        "root_layer_identifier": str(getattr(root_layer, "identifier", "")),
        "root_layer_real_path": str(getattr(root_layer, "realPath", "")),
    }


def _stage_prim_count(stage: Any) -> int:
    if not hasattr(stage, "Traverse"):
        return 0
    return sum(1 for _ in stage.Traverse())


def _pose_summary(stage: Any, prim_path_value: str) -> dict[str, Any]:
    pose = IsaacStagePoseResolver(stage).resolve_world_pose(
        prim_path_value,
        field_name=prim_path_value,
    )
    return {
        "prim_path": prim_path_value,
        "position_world": list(pose.position_world),
        "orientation_world_quat": (
            None
            if pose.orientation_world_quat is None
            else list(pose.orientation_world_quat)
        ),
        "provenance": pose.provenance,
    }


def _config_binding_summary(config_path: Path) -> dict[str, Any]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        "path": str(config_path),
        "schema_version": payload.get("schema_version"),
        "source": payload.get("source", {}),
        "sound_profiles": payload.get("sound_profiles", {}),
        "object_binding": payload.get("object_binding", {}),
        "recording": payload.get("recording", {}),
    }


def _probe_import_update_after_config(
    *,
    stage: Any,
    config_path: Path,
) -> dict[str, Any]:
    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    imported.build_ui_if_available()
    import_result = imported.import_config_summary(config_path)
    roundtrip = _probe_config_roundtrip(imported, config_path)
    imported.state.replicator_enabled = False
    imported.state.trace_enabled = False
    imported.close_sensor()
    sensor = imported.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = imported.update_sensor() if sensor is not None else None
    imported.stop_sensor()
    return {
        "status": (
            "passed"
            if import_result is not None
            and frame is not None
            and imported.state.source_attached_to_object
            else "failed"
        ),
        "import_result": str(import_result) if import_result is not None else None,
        "roundtrip_probe": roundtrip,
        "object_prim_path": imported.state.object_prim_path,
        "attached_object_prim_path": imported.state.attached_object_prim_path,
        "source_prim_path": imported.state.source_prim_path,
        "selected_profile_id": imported.state.selected_profile_id,
        "applied_source_profile": imported.state.applied_source_profile,
        "source_local_offset_m": [
            imported.state.source_local_offset_x_m,
            imported.state.source_local_offset_y_m,
            imported.state.source_local_offset_z_m,
        ],
        "frame_after_import_update": (
            None if frame is None else _frame_source_summary(frame)
        ),
        "status_message": imported.state.status_message,
        "error_message": imported.state.error_message,
    }


def _probe_missing_object_status(
    *,
    controller: ExtensionController,
    stage: Any,
    object_path: str,
) -> dict[str, Any]:
    remove_result = _remove_stage_prim(stage, object_path)
    invalidated_path = None
    invalidation_reason = None
    if not remove_result.get("removed") or remove_result.get("exists_after") is True:
        invalidated_path = f"{object_path}/__missing_for_live_qa__"
        controller.state.attached_object_prim_path = invalidated_path
        invalidation_reason = (
            "remove_failed"
            if not remove_result.get("removed")
            else "removed_prim_still_resolves_in_composed_stage"
        )
    frame = controller.update_sensor()
    message = controller.state.error_message
    expected_path = invalidated_path or object_path
    return {
        "status": (
            "passed"
            if frame is None and message and expected_path in message
            else "failed"
        ),
        "remove_result": remove_result,
        "invalidated_path": invalidated_path,
        "invalidation_reason": invalidation_reason,
        "update_result": _result_summary(frame),
        "status_message": controller.state.status_message,
        "error_message": message,
    }


def _remove_stage_prim(stage: Any, path: str) -> dict[str, Any]:
    if not hasattr(stage, "RemovePrim"):
        return {"removed": False, "reason": "stage has no RemovePrim"}
    try:
        from pxr import Sdf  # type: ignore

        result = stage.RemovePrim(Sdf.Path(path))
    except Exception as exc:
        try:
            result = stage.RemovePrim(path)
        except Exception as fallback_exc:
            return {
                "removed": False,
                "error_type": type(fallback_exc).__name__,
                "error": str(fallback_exc),
                "first_error": f"{type(exc).__name__}: {exc}",
            }
    return {
        "removed": bool(result),
        "path": path,
        "exists_after": _stage_has_prim(stage, path),
    }


def _replicator_artifacts(replicator_dir: Path) -> list[str]:
    if not replicator_dir.is_dir():
        return []
    return [str(path) for path in sorted(replicator_dir.iterdir()) if path.is_file()]


def _promote_legacy_generic_evidence(
    evidence: dict[str, Any],
    generic_result: dict[str, Any],
) -> None:
    evidence["source_position_after_read"] = generic_result.get(
        "source_position_after_read"
    )
    evidence["source_position_after_front_preset"] = generic_result.get(
        "source_position_after_front_preset"
    )
    evidence["source_object_attachment"] = generic_result.get(
        "source_object_attachment"
    )
    evidence["object_source_frame_before_move"] = generic_result.get(
        "frame_before_parent_move"
    )
    evidence["object_source_frame_after_move"] = generic_result.get(
        "frame_after_parent_move"
    )
    evidence["object_transform_move_command"] = generic_result.get(
        "parent_transform_move_command"
    )
    evidence["object_move_changed_frame"] = generic_result.get(
        "object_move_changed_frame"
    )
    evidence["source_move_changed_frame"] = generic_result.get(
        "object_move_changed_frame"
    )
    evidence["config_roundtrip_probe"] = generic_result.get(
        "config_import_result", {}
    ).get("roundtrip_probe")
    evidence["screenshot"] = generic_result.get("screenshot")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))


def _inventory_ui_controls(controller: ExtensionController) -> dict[str, Any]:
    window = getattr(controller, "_ui_window", None)
    if window is None:
        return {"status": "failed", "reason": "ui_window_unavailable"}
    sections = tuple(getattr(window, "_sections", ()))
    buttons = tuple(getattr(window, "_buttons", ()))
    instruments = getattr(window, "_instruments", {}) or {}
    inventory = {
        "sections": list(sections),
        "buttons": list(buttons),
        "string_fields": sorted(window._string_fields),
        "float_fields": sorted(window._float_fields),
        "int_fields": sorted(window._int_fields),
        "bool_fields": sorted(window._bool_fields),
        "combo_fields": sorted(window._combo_fields),
        "labels": sorted(window._labels),
        "instruments": sorted(instruments),
        "instrument_meter_rows": len(instruments.get("meters") or ()),
        "instrument_timeline_rows": len(instruments.get("timeline") or ()),
    }
    missing = {
        "sections": _missing(EXPECTED_UI_SECTIONS, sections),
        "buttons": _missing(EXPECTED_UI_BUTTONS, buttons),
        "string_fields": _missing(EXPECTED_STRING_FIELDS, window._string_fields),
        "float_fields": _missing(EXPECTED_FLOAT_FIELDS, window._float_fields),
        "int_fields": _missing(EXPECTED_INT_FIELDS, window._int_fields),
        "bool_fields": _missing(EXPECTED_BOOL_FIELDS, window._bool_fields),
        "combo_fields": _missing(EXPECTED_COMBO_FIELDS, window._combo_fields),
        "instruments": _missing(EXPECTED_INSTRUMENT_KEYS, instruments),
    }
    missing = {key: value for key, value in missing.items() if value}
    return {
        "status": "passed" if not missing else "failed",
        "missing": missing,
        **inventory,
    }


def _missing(expected: tuple[str, ...], actual: Any) -> list[str]:
    actual_set = set(actual)
    return [item for item in expected if item not in actual_set]


def _probe_window_integrations(controller: ExtensionController) -> dict[str, Any]:
    record: dict[str, Any] = {
        "window_title": OMNI_WINDOW_TITLE,
        "menu_path": f"{OMNI_MENU_GROUP} -> {OMNI_WINDOW_TITLE}",
        "action_id": f"{controller.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}",
        "default_hotkey": OMNI_DEFAULT_HOTKEY,
        "action_status": controller.action_status,
        "menu_status": controller.menu_status,
        "hotkey_status": controller.hotkey_status,
        "initial_visible": controller.is_window_visible(),
    }
    controller.hide_window()
    record["visible_after_close_probe"] = controller.is_window_visible()
    action_probe = _execute_toggle_window_action(controller)
    record["action_probe"] = action_probe
    record["visible_after_action_probe"] = controller.is_window_visible()
    controller.show_window()
    record["visible_after_restore"] = controller.is_window_visible()

    passed = (
        "registered" in controller.action_status.lower()
        and "registered" in controller.menu_status.lower()
        and record["visible_after_close_probe"] is False
        and action_probe.get("status") == "passed"
        and record["visible_after_action_probe"] is True
        and record["visible_after_restore"] is True
        and (
            "registered" in controller.hotkey_status.lower()
            or "unavailable" in controller.hotkey_status.lower()
            or "disabled" in controller.hotkey_status.lower()
        )
    )
    record["status"] = "passed" if passed else "failed"
    return record


def _execute_toggle_window_action(
    controller: ExtensionController,
) -> dict[str, Any]:
    try:
        import omni.kit.actions.core as actions_core  # type: ignore
    except ImportError as exc:
        return {"status": "failed", "reason": f"actions core unavailable: {exc}"}
    registry = actions_core.get_action_registry()
    if registry is None:
        return {"status": "failed", "reason": "action registry unavailable"}
    try:
        result = registry.execute_action(controller.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
    except Exception as exc:  # noqa: BLE001 - evidence records exact runtime issue.
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return {
        "status": "passed" if result is not None else "returned_none",
        "result_summary": _result_summary(result),
    }


def _probe_extension_manager_metadata(
    ext_path: Path,
    *,
    extension_id: str,
) -> dict[str, Any]:
    manifest_path = ext_path / "config" / "extension.toml"
    try:
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Isaac 3.10 fallback.
            import tomli as tomllib  # type: ignore

        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        package = manifest.get("package", {})
    except Exception as exc:  # noqa: BLE001 - evidence records exact runtime issue.
        return {
            "status": "failed",
            "manifest_path": str(manifest_path),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    if package.get("exchange", False):
        author_group = "COMMUNITY_VERIFIED"
    elif not package.get("trusted", True):
        author_group = "COMMUNITY_UNVERIFIED"
    else:
        author_group = "NVIDIA"
    ext_source = "NVIDIA" if author_group == "NVIDIA" else "THIRD PARTY"

    resources = {}
    for key in ("readme", "changelog", "icon", "preview_image"):
        relative_path = package.get(key, "")
        path = ext_path / relative_path
        resources[key] = {
            "relative_path": relative_path,
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }

    required_keywords = {"audio", "microphone", "sensor", "robotics", "tdoa"}
    keywords = set(package.get("keywords", ()))
    missing_keywords = sorted(required_keywords - keywords)
    missing_resources = [
        key
        for key, value in resources.items()
        if not value["exists"] or int(value["size_bytes"]) <= 0
    ]
    kit_common_info = _probe_kit_extension_common_info(
        extension_id=extension_id,
        ext_path=ext_path,
        manifest_package=package,
    )
    kit_source_status = kit_common_info.get("status")
    kit_source = kit_common_info.get("ext_source")
    passed = (
        ext_source == "THIRD PARTY"
        and package.get("category", "").lower() == "simulation"
        and bool(package.get("repository"))
        and not missing_keywords
        and not missing_resources
        and (
            kit_source_status == "unavailable"
            or (kit_source_status == "passed" and kit_source == "THIRD PARTY")
        )
    )
    return {
        "status": "passed" if passed else "failed",
        "manifest_path": str(manifest_path),
        "ext_source": ext_source,
        "author_group": author_group,
        "category": package.get("category", ""),
        "repository": package.get("repository", ""),
        "keywords": sorted(keywords),
        "missing_keywords": missing_keywords,
        "resources": resources,
        "missing_resources": missing_resources,
        "kit_window_extensions_common": kit_common_info,
    }


def _probe_kit_extension_common_info(
    *,
    extension_id: str,
    ext_path: Path,
    manifest_package: dict[str, Any],
) -> dict[str, Any]:
    try:
        from omni.kit.window.extensions.common import (  # type: ignore
            ExtensionCommonInfo,
        )
    except Exception as exc:  # noqa: BLE001 - unavailable outside Kit.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}

    package = dict(manifest_package)
    package.setdefault("name", extension_id)
    package.setdefault("id", f"{extension_id}-{package.get('version', '0.0.0')}")
    package.setdefault("packageId", package["id"])
    ext_info = {
        "package": package,
        "path": str(ext_path),
        "configPath": str(ext_path / "config" / "extension.toml"),
        "isInCache": False,
        "isUser": False,
        "isKitFile": False,
        "state": {
            "enabled": True,
            "reloadable": True,
            "failed": False,
        },
    }
    try:
        common_info = ExtensionCommonInfo(package["id"], ext_info, is_local=True)
    except Exception as exc:  # noqa: BLE001 - evidence should capture API drift.
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}

    ext_source = getattr(common_info, "ext_source", None)
    author_group = getattr(common_info, "author_group", None)
    return {
        "status": "passed",
        "ext_source": _enum_ui_name(ext_source),
        "author_group": _enum_ui_name(author_group),
        "is_untrusted": getattr(common_info, "is_untrusted", None),
        "category": getattr(common_info, "category", ""),
        "repository": getattr(common_info, "repository", ""),
        "icon_path": getattr(common_info, "icon_path", ""),
        "preview_image_path": getattr(common_info, "preview_image_path", ""),
    }


def _enum_ui_name(value: Any) -> str:
    get_ui_name = getattr(value, "get_ui_name", None)
    if callable(get_ui_name):
        return str(get_ui_name())
    name = getattr(value, "name", None)
    if name is not None:
        return str(name)
    return str(value)


def _probe_ui_editable_models(controller: ExtensionController) -> dict[str, Any]:
    window = getattr(controller, "_ui_window", None)
    if window is None:
        return {"status": "skipped", "reason": "ui_window_unavailable"}
    duration = window._float_fields.get("source_duration_s")
    position_x = window._float_fields.get("source_position_x_m")
    position_y = window._float_fields.get("source_position_y_m")
    position_z = window._float_fields.get("source_position_z_m")
    local_offset_x = window._float_fields.get("source_local_offset_x_m")
    local_offset_y = window._float_fields.get("source_local_offset_y_m")
    local_offset_z = window._float_fields.get("source_local_offset_z_m")
    sample_rate = window._int_fields.get("sample_rate_hz")
    source_id = window._string_fields.get("source_id")
    object_path = window._string_fields.get("object_prim_path")
    if (
        duration is None
        or position_x is None
        or position_y is None
        or position_z is None
        or local_offset_x is None
        or local_offset_y is None
        or local_offset_z is None
        or sample_rate is None
        or source_id is None
        or object_path is None
    ):
        return {"status": "failed", "reason": "expected editable fields missing"}
    duration.model.set_value("10.0")
    position_x.model.set_value("2.0")
    position_y.model.set_value("0.0")
    position_z.model.set_value("0.0")
    local_offset_x.model.set_value("0.0")
    local_offset_y.model.set_value("0.0")
    local_offset_z.model.set_value("0.0")
    sample_rate.model.set_value("44100")
    source_id.model.set_value("speaker_a")
    object_path.model.set_value("/World/Oven")
    window.sync_state_from_widgets()
    return {
        "status": "passed",
        "source_duration_s": controller.state.source_duration_s,
        "source_position_world": [
            controller.state.source_position_x_m,
            controller.state.source_position_y_m,
            controller.state.source_position_z_m,
        ],
        "source_local_offset_m": [
            controller.state.source_local_offset_x_m,
            controller.state.source_local_offset_y_m,
            controller.state.source_local_offset_z_m,
        ],
        "object_prim_path": controller.state.object_prim_path,
        "sample_rate_hz": controller.state.sample_rate_hz,
        "source_id": controller.state.source_id,
        "duration_widget_kind": getattr(duration, "kind", type(duration).__name__),
        "sample_rate_widget_kind": getattr(
            sample_rate, "kind", type(sample_rate).__name__
        ),
        "source_id_widget_kind": getattr(source_id, "kind", type(source_id).__name__),
    }


def _probe_ui_invalid_numeric(controller: ExtensionController) -> dict[str, Any]:
    window = getattr(controller, "_ui_window", None)
    if window is None:
        return {"status": "failed", "reason": "ui_window_unavailable"}
    duration = window._float_fields.get("source_duration_s")
    if duration is None:
        return {"status": "failed", "reason": "source_duration_s field missing"}
    previous = _model_string(duration.model)
    called = {"value": False}

    def _callback() -> str:
        called["value"] = True
        return "called"

    duration.model.set_value("not-a-number")
    window._action(_callback)()
    error = controller.state.error_message
    restore_error = None
    try:
        duration.model.set_value(previous or "10.0")
        window.sync_state_from_widgets()
        window.refresh_labels()
    except Exception as exc:  # noqa: BLE001 - evidence should keep moving.
        restore_error = f"{type(exc).__name__}: {exc}"
    passed = (
        called["value"] is False
        and error is not None
        and "UI input failed" in error
        and restore_error is None
    )
    return {
        "status": "passed" if passed else "failed",
        "callback_called": called["value"],
        "error_message": error,
        "restore_error": restore_error,
    }


def _probe_export_latest_without_frame(
    controller: ExtensionController,
) -> dict[str, Any]:
    result = controller.export_latest_frame()
    error = controller.state.error_message
    passed = result is None and error is not None and "No latest frame" in error
    return {
        "status": "passed" if passed else "failed",
        "result": _result_summary(result),
        "error_message": error,
    }


def _source_position_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "source_prim_path": state.source_prim_path,
        "position_world": [
            state.source_position_x_m,
            state.source_position_y_m,
            state.source_position_z_m,
        ],
    }


def _source_object_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "source_prim_path": state.source_prim_path,
        "object_prim_path": state.object_prim_path,
        "object_label": state.object_label,
        "source_attached_to_object": state.source_attached_to_object,
        "attached_object_prim_path": state.attached_object_prim_path,
        "source_local_offset_m": [
            state.source_local_offset_x_m,
            state.source_local_offset_y_m,
            state.source_local_offset_z_m,
        ],
    }


def _sound_profile_state(
    controller: ExtensionController,
    profile: Any | None,
) -> dict[str, Any]:
    state = controller.state
    return {
        "selected_profile_id": state.selected_profile_id,
        "selected_profile_label": (
            None if profile is None else getattr(profile, "display_label", None)
        ),
        "profile_library_ids": [
            getattr(item, "profile_id", "") for item in state.profile_library
        ],
        "object_profile_mappings": dict(sorted(state.object_profile_mappings.items())),
        "status_message": state.status_message,
        "error_message": state.error_message,
    }


def _source_profile_state(
    controller: ExtensionController,
    stage: Any,
) -> dict[str, Any]:
    state = controller.state
    prim = _stage_get_prim_at_path(stage, state.source_prim_path)
    attrs = {} if prim is None else _prim_attrs(prim)
    return {
        "selected_profile_id": state.selected_profile_id,
        "applied_source_profile": state.applied_source_profile,
        "source_prim_path": state.source_prim_path,
        "source_id": state.source_id,
        "class_label": state.source_class_label,
        "audio_asset_path": state.audio_asset_path,
        "start_time_s": state.source_start_time_s,
        "duration_s": state.source_duration_s,
        "gain_db": state.source_gain_db,
        "directivity": state.source_directivity,
        "source_attached_to_object": state.source_attached_to_object,
        "authored_attrs": {
            key: _jsonable_value(attrs.get(key))
            for key in (
                "filePath",
                "ias:source_id",
                "ias:class_label",
                "ias:audio_asset_path",
                "ias:start_time_s",
                "ias:duration_s",
                "ias:gain_db",
                "ias:directivity",
                "ias:sound_profile_id",
                "ias:attached_object_prim_path",
                "ias:source_local_offset_m",
            )
            if key in attrs
        },
        "status_message": state.status_message,
        "error_message": state.error_message,
    }


def _frame_source_summary(frame: Any) -> dict[str, Any]:
    detections = tuple(getattr(frame, "detections", ()))
    detection = detections[0] if detections else None
    source_pose = None if detection is None else detection.source_pose
    return {
        "frame_id": getattr(frame, "frame_id", None),
        "frame_index": getattr(frame, "frame_index", None),
        "detection_count": len(detections),
        "source_id": None if detection is None else detection.source_id,
        "class_label": None if detection is None else detection.class_label,
        "audio_asset_path": None if detection is None else detection.audio_asset_path,
        "source_position_m": (
            None if source_pose is None else list(source_pose.position_m)
        ),
        "bearing_deg": (
            None if detection is None else detection.doa.estimated_bearing_deg
        ),
        "sector": None if detection is None else detection.doa.bearing_sector,
    }


def _source_frame_changed(before: Any, after: Any) -> dict[str, Any]:
    before_summary = _frame_source_summary(before)
    after_summary = _frame_source_summary(after)
    return {
        "status": (
            "passed"
            if before_summary["source_position_m"] != after_summary["source_position_m"]
            and before_summary["bearing_deg"] != after_summary["bearing_deg"]
            else "failed"
        ),
        "before": before_summary,
        "after": after_summary,
    }


def _array_pose_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "array_prim_path": state.array_prim_path,
        "position_m": [
            state.array_position_x_m,
            state.array_position_y_m,
            state.array_position_z_m,
        ],
        "euler_deg": [
            state.array_roll_deg,
            state.array_pitch_deg,
            state.array_yaw_deg,
        ],
        "error_message": state.error_message,
    }


def _array_object_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "array_attached_to_object": state.array_attached_to_object,
        "attached_object_prim_path": state.attached_array_object_prim_path or None,
        "array_prim_path": state.array_prim_path,
        "array_local_offset_m": [
            state.array_local_offset_x_m,
            state.array_local_offset_y_m,
            state.array_local_offset_z_m,
        ],
        "error_message": state.error_message,
    }


def _rig_profile_state(
    controller: ExtensionController,
    stage: Any,
) -> dict[str, Any]:
    state = controller.state
    prim = _stage_get_prim_at_path(stage, state.array_prim_path)
    attrs = {} if prim is None else _prim_attrs(prim)
    return {
        "selected_rig_profile_id": state.selected_rig_profile_id or None,
        "applied_array_rig_profile": dict(state.applied_array_rig_profile),
        "authored_attrs": {
            name: _jsonable_value(value)
            for name, value in sorted(attrs.items())
            if name.startswith("ias:")
        },
        "error_message": state.error_message,
    }


def _frame_array_summary(
    controller: ExtensionController,
    frame: Any,
) -> dict[str, Any]:
    summary = _frame_source_summary(frame)
    array_pose = getattr(frame, "array_pose", None)
    summary["array_position_m"] = (
        None
        if array_pose is None
        else [float(value) for value in array_pose.position_m]
    )
    orientation = (
        None if array_pose is None else getattr(array_pose, "orientation_xyzw", None)
    )
    summary["array_orientation_xyzw"] = (
        None if orientation is None else [float(value) for value in orientation]
    )
    summary["mic_world_positions"] = {
        mic_id: [float(value) for value in position]
        for mic_id, position in sorted(
            controller.state.latest_mic_world_positions.items()
        )
    }
    summary["aggregate_per_mic_rms"] = {
        mic_id: float(value)
        for mic_id, value in sorted(
            dict(getattr(frame, "aggregate_per_mic_rms", {}) or {}).items()
        )
    }
    return summary


def _array_rotation_changed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "orientation_changed": (
            before.get("array_orientation_xyzw") != after.get("array_orientation_xyzw")
        ),
        "mic_world_positions_changed": (
            before.get("mic_world_positions") != after.get("mic_world_positions")
        ),
        "bearing_changed": before.get("bearing_deg") != after.get("bearing_deg"),
        "sector_changed": before.get("sector") != after.get("sector"),
        "rms_changed": (
            before.get("aggregate_per_mic_rms") != after.get("aggregate_per_mic_rms")
        ),
        "source_position_unchanged": (
            before.get("source_position_m") == after.get("source_position_m")
        ),
    }
    passed = (
        checks["orientation_changed"]
        and checks["mic_world_positions_changed"]
        and checks["bearing_changed"]
        and checks["source_position_unchanged"]
    )
    return {
        "status": "passed" if passed else "failed",
        "checks": checks,
        "before": before,
        "after": after,
    }


def _array_move_changed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "array_position_changed": (
            before.get("array_position_m") != after.get("array_position_m")
        ),
        "mic_world_positions_changed": (
            before.get("mic_world_positions") != after.get("mic_world_positions")
        ),
        "bearing_changed": before.get("bearing_deg") != after.get("bearing_deg"),
        "sector_changed": before.get("sector") != after.get("sector"),
        "rms_changed": (
            before.get("aggregate_per_mic_rms") != after.get("aggregate_per_mic_rms")
        ),
    }
    passed = (
        checks["array_position_changed"]
        and checks["mic_world_positions_changed"]
        and (
            checks["bearing_changed"]
            or checks["sector_changed"]
            or checks["rms_changed"]
        )
    )
    return {
        "status": "passed" if passed else "failed",
        "checks": checks,
        "before": before,
        "after": after,
    }


def _probe_config_roundtrip(
    controller: ExtensionController,
    config_path: Path,
) -> dict[str, Any]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    window = getattr(controller, "_ui_window", None)
    if window is not None:
        window.push_state_to_widgets()
        window.sync_state_from_widgets()
    expected = _expected_config_state(payload)
    observed = _observed_config_state(controller)
    mismatches = _state_mismatches(expected, observed)
    combo_models = _combo_model_values(window) if window is not None else {}
    combo_mismatches = {
        name: value
        for name, value in combo_models.items()
        if value.get("state_value") != value.get("model_value")
    }
    return {
        "status": (
            "passed"
            if window is not None and not mismatches and not combo_mismatches
            else "failed"
        ),
        "config_path": str(config_path),
        "ui_window_available": window is not None,
        "expected": expected,
        "observed": observed,
        "mismatches": mismatches,
        "combo_models": combo_models,
        "combo_mismatches": combo_mismatches,
    }


def _expected_config_state(payload: dict[str, Any]) -> dict[str, Any]:
    array = payload.get("array", {})
    source = payload.get("source", {})
    sound_profiles = payload.get("sound_profiles", {})
    rig_profiles = payload.get("microphone_rig_profiles", {})
    object_binding = payload.get("object_binding", {})
    array_binding = payload.get("array_binding", {})
    lifecycle = payload.get("lifecycle", {})
    recording = payload.get("recording", {})
    package_jsonl = recording.get("package_jsonl", {})
    replicator = recording.get("replicator", {})
    return {
        "backend": payload.get("backend"),
        "array_prim_path": array.get("prim_path"),
        "array_position_world": array.get("position_world"),
        "array_orientation_world_quat": array.get("orientation_world_quat"),
        "array_attached_to_object": array_binding.get("attached"),
        "attached_array_object_prim_path": array_binding.get(
            "attached_object_prim_path"
        ),
        "array_local_offset_m": array_binding.get("array_local_offset_m"),
        "selected_rig_profile_id": rig_profiles.get("selected_rig_profile_id"),
        "applied_array_rig_profile": rig_profiles.get("applied_array_rig_profile"),
        "source_prim_path": source.get("prim_path"),
        "source_id": source.get("source_id"),
        "source_directivity": source.get("directivity"),
        "source_position_world": source.get("position_world"),
        "source_local_offset_m": object_binding.get("source_local_offset_m"),
        "object_prim_path": object_binding.get("selected_object_prim_path"),
        "source_attached_to_object": object_binding.get("attached"),
        "attached_object_prim_path": object_binding.get("attached_object_prim_path"),
        "source_duration_s": source.get("duration_s"),
        "sample_rate_hz": array.get("sample_rate_hz"),
        "jsonl_trace_path": package_jsonl.get("path"),
        "trace_enabled": package_jsonl.get("enabled"),
        "debug_overlay_enabled": lifecycle.get("debug_overlay_enabled"),
        "replicator_enabled": replicator.get("enabled"),
        "replicator_output_dir": replicator.get("output_dir"),
        "replicator_writer_name": replicator.get("writer_name"),
        "replicator_annotator_name": replicator.get("annotator_name"),
        "selected_profile_id": sound_profiles.get("selected_profile_id"),
        "object_profile_mappings": sound_profiles.get("object_profile_mappings"),
        "applied_source_profile": sound_profiles.get("applied_source_profile"),
    }


def _observed_config_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "backend": state.backend,
        "array_prim_path": state.array_prim_path,
        "array_position_world": [
            state.array_position_x_m,
            state.array_position_y_m,
            state.array_position_z_m,
        ],
        "array_orientation_world_quat": list(
            controller._array_orientation_from_state()
        ),
        "array_attached_to_object": state.array_attached_to_object,
        "attached_array_object_prim_path": (
            state.attached_array_object_prim_path or None
        ),
        "array_local_offset_m": [
            state.array_local_offset_x_m,
            state.array_local_offset_y_m,
            state.array_local_offset_z_m,
        ],
        "selected_rig_profile_id": state.selected_rig_profile_id or None,
        "applied_array_rig_profile": state.applied_array_rig_profile or None,
        "source_prim_path": state.source_prim_path,
        "source_id": state.source_id,
        "source_directivity": state.source_directivity,
        "source_position_world": [
            state.source_position_x_m,
            state.source_position_y_m,
            state.source_position_z_m,
        ],
        "source_local_offset_m": [
            state.source_local_offset_x_m,
            state.source_local_offset_y_m,
            state.source_local_offset_z_m,
        ],
        "object_prim_path": state.object_prim_path or None,
        "source_attached_to_object": state.source_attached_to_object,
        "attached_object_prim_path": state.attached_object_prim_path or None,
        "source_duration_s": state.source_duration_s,
        "sample_rate_hz": state.sample_rate_hz,
        "jsonl_trace_path": state.jsonl_trace_path,
        "trace_enabled": state.trace_enabled,
        "debug_overlay_enabled": state.debug_overlay_enabled,
        "replicator_enabled": state.replicator_enabled,
        "replicator_output_dir": state.replicator_output_dir,
        "replicator_writer_name": state.replicator_writer_name,
        "replicator_annotator_name": state.replicator_annotator_name,
        "selected_profile_id": state.selected_profile_id or None,
        "object_profile_mappings": dict(sorted(state.object_profile_mappings.items())),
        "applied_source_profile": state.applied_source_profile or None,
    }


def _state_mismatches(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    mismatches = {}
    for key, expected_value in expected.items():
        observed_value = observed.get(key)
        matched = _state_values_match(expected_value, observed_value)
        if not matched:
            mismatches[key] = {
                "expected": expected_value,
                "observed": observed_value,
            }
    return mismatches


def _state_values_match(expected_value: Any, observed_value: Any) -> bool:
    if isinstance(expected_value, (int, float)) and isinstance(
        observed_value,
        (int, float),
    ):
        return abs(float(observed_value) - float(expected_value)) <= 1e-9
    if isinstance(expected_value, list) and isinstance(observed_value, list):
        if len(expected_value) != len(observed_value):
            return False
        return all(
            _state_values_match(expected_item, observed_item)
            for expected_item, observed_item in zip(
                expected_value,
                observed_value,
                strict=True,
            )
        )
    if isinstance(expected_value, dict) and isinstance(observed_value, dict):
        if set(expected_value) != set(observed_value):
            return False
        return all(
            _state_values_match(expected_value[key], observed_value[key])
            for key in expected_value
        )
    return observed_value == expected_value


def _combo_model_values(window: Any) -> dict[str, dict[str, Any]]:
    values = {}
    for attr_name, (widget, choices) in window._combo_fields.items():
        index = _combo_index(widget.model)
        model_value = choices[index] if 0 <= index < len(choices) else None
        values[attr_name] = {
            "index": index,
            "model_value": model_value,
            "state_value": getattr(window.controller.state, attr_name),
        }
    return values


def _model_string(model: Any) -> str:
    if hasattr(model, "get_value_as_string"):
        return str(model.get_value_as_string())
    if hasattr(model, "as_string"):
        return str(model.as_string)
    return str(getattr(model, "value", ""))


def _combo_index(model: Any) -> int:
    if hasattr(model, "get_item_value_model"):
        item_model = model.get_item_value_model()
        try:
            as_int = item_model.as_int
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            return int(as_int)
        get_value = getattr(item_model, "get_value_as_int", None)
        if callable(get_value):
            return int(get_value())
    get_value = getattr(model, "get_value_as_int", None)
    if callable(get_value):
        return int(get_value())
    try:
        as_int = model.as_int
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        return int(as_int)
    return int(getattr(model, "value", 0) or 0)


def _result_summary(result: Any) -> Any:
    if isinstance(result, Path):
        return str(result)
    if isinstance(result, str | int | float | bool):
        return result
    if isinstance(result, tuple | list):
        return {"count": len(result), "items": [str(item) for item in result[:8]]}
    if isinstance(result, dict):
        return {
            str(key): _result_summary(value)
            for key, value in sorted(result.items())
            if key in {"enabled", "started", "writer_registered", "write_count"}
        }
    return type(result).__name__


def _create_stage(evidence: dict[str, Any]) -> tuple[Any | None, str]:
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        if hasattr(context, "new_stage"):
            context.new_stage()
            _update_kit_once(evidence)
        stage = context.get_stage() if hasattr(context, "get_stage") else None
        if stage is not None:
            return stage, "omni_usd_context_stage"
    except Exception as exc:  # noqa: BLE001 - fallback recorded.
        evidence["omni_usd_context_stage_error"] = f"{type(exc).__name__}: {exc}"
    return None, "unavailable"


def _author_minimal_stage(stage: Any) -> None:
    for path, prim_type in (
        ("/World", "Xform"),
        ("/World/Rig", "Xform"),
        ("/World/Rig/AudioArray", "Xform"),
        ("/World/Sources", "Xform"),
        ("/World/Sources/SpeakerA", "Xform"),
        ("/World/Oven", "Cube"),
        ("/World/KeyLight", "DistantLight"),
    ):
        if not _stage_has_prim(stage, path):
            stage.DefinePrim(path, prim_type)
    source = _stage_get_prim_at_path(stage, "/World/Sources/SpeakerA")
    _set_translate(source, (2.0, 1.0, 0.0))
    oven = _stage_get_prim_at_path(stage, "/World/Oven")
    _set_translate(oven, (2.0, 0.0, 0.0))
    _style_generic_visual_fixture(stage)


def _style_generic_visual_fixture(stage: Any) -> None:
    try:
        from pxr import Gf, UsdGeom, UsdLux  # type: ignore

        oven = _stage_get_prim_at_path(stage, "/World/Oven")
        cube = UsdGeom.Cube(oven)
        cube.CreateSizeAttr(0.9)
        gprim = UsdGeom.Gprim(oven)
        gprim.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.48, 0.08)])
        gprim.CreateDisplayOpacityAttr([1.0])
        gprim.CreateDoubleSidedAttr(True)

        light_prim = _stage_get_prim_at_path(stage, "/World/KeyLight")
        light = UsdLux.DistantLight(light_prim)
        light.CreateIntensityAttr(750.0)
        light.CreateAngleAttr(0.35)
        _set_translate(light_prim, (0.0, -3.0, 5.0))
        dome_prim = _stage_get_prim_at_path(stage, "/World/DemoObjectDomeLight")
        if dome_prim is None or (
            hasattr(dome_prim, "IsValid") and not dome_prim.IsValid()
        ):
            dome_prim = stage.DefinePrim("/World/DemoObjectDomeLight", "DomeLight")
        dome = UsdLux.DomeLight(dome_prim)
        dome.CreateIntensityAttr(450.0)
        dome.CreateColorAttr(Gf.Vec3f(1.0, 0.92, 0.82))
        fill_prim = _stage_get_prim_at_path(stage, "/World/DemoObjectFillLight")
        if fill_prim is None or (
            hasattr(fill_prim, "IsValid") and not fill_prim.IsValid()
        ):
            fill_prim = stage.DefinePrim("/World/DemoObjectFillLight", "SphereLight")
        fill = UsdLux.SphereLight(fill_prim)
        fill.CreateIntensityAttr(1800.0)
        fill.CreateRadiusAttr(3.0)
        _set_translate(fill_prim, (-3.0, -4.0, 3.0))
    except Exception:
        return


def _set_translate(prim: Any, position: tuple[float, float, float]) -> None:
    if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
        raise RuntimeError(f"Cannot set transform on missing prim: {prim}")
    try:
        from pxr import Gf, UsdGeom  # type: ignore

        value = Gf.Vec3d(*position)
        xform = UsdGeom.Xformable(prim)
        for op in xform.GetOrderedXformOps():
            if hasattr(op, "GetOpName") and op.GetOpName() == "xformOp:translate":
                op.Set(value)
                return
        op = xform.AddTranslateOp()
        op.Set(value)
    except Exception:
        if hasattr(prim, "attributes"):
            prim.attributes["xformOp:translate"] = position


def _stage_has_prim(stage: Any, path: str) -> bool:
    prim = _stage_get_prim_at_path(stage, path)
    if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
        return True
    if hasattr(stage, "Traverse"):
        return any(_prim_path(prim) == path for prim in stage.Traverse())
    return False


def _stage_get_prim_at_path(stage: Any, path: str) -> Any | None:
    if not hasattr(stage, "GetPrimAtPath"):
        return None
    for candidate_path in (_usd_path(path), path):
        try:
            return stage.GetPrimAtPath(candidate_path)
        except TypeError:
            continue
    return None


def _prim_attrs(prim: Any) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                with suppress(Exception):
                    attrs[str(attr.GetName())] = attr.Get()
    return attrs


def _jsonable_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple | list):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable_value(item) for key, item in sorted(value.items())}
    for attr_name in ("path", "pathString", "resolvedPath"):
        attr_value = getattr(value, attr_name, None)
        if attr_value:
            return str(attr_value)
    return str(value)


def _usd_path(path: str) -> Any:
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return path
    try:
        return Sdf.Path(path)
    except Exception:
        return path


def _set_context_selection(paths: tuple[str, ...], evidence: dict[str, Any]) -> None:
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        selection = (
            context.get_selection() if hasattr(context, "get_selection") else None
        )
        if selection is None or not hasattr(selection, "set_selected_prim_paths"):
            evidence.setdefault("selection_api", []).append(
                {"paths": list(paths), "status": "selection_setter_unavailable"}
            )
            return
        try:
            selection.set_selected_prim_paths(list(paths), True)
        except TypeError:
            selection.set_selected_prim_paths(list(paths))
        evidence.setdefault("selection_api", []).append(
            {"paths": list(paths), "status": "set"}
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        evidence.setdefault("selection_api", []).append(
            {"paths": list(paths), "status": f"{type(exc).__name__}: {exc}"}
        )


def _run_error_checks(stage: Any) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(None, ())
    )
    controller.export_latest_frame()
    checks["export_latest_without_frame"] = controller.state.error_message
    controller.refresh_stage_selection(selected_paths=())
    checks["no_stage"] = controller.state.error_message
    controller.use_selected_as_array(stage=stage, selected_paths=())
    checks["no_selection"] = controller.state.error_message
    controller.state.array_prim_path = "relative/path"
    controller.author_array(stage=stage)
    checks["invalid_prim_path"] = controller.state.error_message
    controller.state.array_prim_path = "/World/Rig/AudioArray"
    controller.state.backend = "invalid_backend"
    controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    checks["invalid_backend"] = controller.state.error_message
    controller.state.replicator_output_dir = ""
    controller.start_replicator()
    checks["invalid_replicator_output"] = controller.state.error_message
    controller.state.config_export_path = "."
    controller.export_config_summary()
    checks["bad_config_export_path"] = controller.state.error_message
    return checks


def _collect_instruments_evidence(
    controller: ExtensionController,
    *,
    screenshot_path: Path,
) -> dict[str, Any]:
    """Record compass/meter/timeline values and widget visibility evidence."""

    state = controller.state
    window = getattr(controller, "_ui_window", None)
    view_model = compass_view_model(
        bearing_deg=state.latest_bearing_deg,
        candidate_bearings=state.latest_candidate_bearings,
        sector=state.latest_sector,
        confidence=state.latest_bearing_confidence,
        occluded=state.latest_occluded,
    )
    meters = meter_view_models(state.latest_aggregate_rms)
    rows = timeline_rows(state.detection_history)
    record: dict[str, Any] = {
        "frame_id": state.latest_frame_id,
        "detection_count": state.latest_detection_count,
        "history_count": len(state.detection_history),
        "compass": {
            "bearing_deg": state.latest_bearing_deg,
            "sector": state.latest_sector,
            "confidence": state.latest_bearing_confidence,
            "occluded": state.latest_occluded,
            "needle_count": len(view_model.needles),
            "needle_unit_xy": (
                list(view_model.needles[0].unit_xy) if view_model.needles else None
            ),
            "summary": view_model.summary,
        },
        "meters": [
            {"mic_id": meter.mic_id, "db": meter.db, "fraction": meter.fraction}
            for meter in meters
        ],
        "timeline_row_count": len(rows),
    }
    widget_record: dict[str, Any] = {"available": False}
    if window is not None:
        instruments = getattr(window, "_instruments", {}) or {}
        meter_rows = instruments.get("meters") or []
        timeline_labels = instruments.get("timeline") or []
        compass_label = window._labels.get("compass")
        widget_record = {
            "available": True,
            "compass_image": instruments.get("compass") is not None,
            "compass_label_text": getattr(compass_label, "text", None),
            "visible_meter_rows": sum(
                1
                for row in meter_rows
                if getattr(row.get("row"), "visible", False)
            ),
            "visible_timeline_rows": sum(
                1 for label in timeline_labels if getattr(label, "visible", False)
            ),
        }
    record["widgets"] = widget_record
    record["panel"] = _write_instruments_panel(
        screenshot_path,
        view_model=view_model,
        meters=meters,
    )
    record["app_screenshot"] = _capture_app_screenshot(
        screenshot_path.with_suffix(".app.png")
    )
    passed = (
        bool(view_model.needles)
        and bool(record["meters"])
        and record["timeline_row_count"] > 0
        and widget_record.get("available") is True
        and widget_record.get("compass_image") is True
        and int(widget_record.get("visible_meter_rows", 0)) > 0
        and int(widget_record.get("visible_timeline_rows", 0)) > 0
        and record["panel"].get("status") == "captured"
    )
    record["status"] = "passed" if passed else "failed"
    return record


def _write_instruments_panel(
    path: Path,
    *,
    view_model: Any,
    meters: Any,
) -> dict[str, Any]:
    """Write the compass + meter raster (the compass widget's exact pixels)."""

    try:
        panel = render_instruments_panel_rgba(view_model, meters)
        write_rgba_png(path, panel)
    except Exception as exc:  # noqa: BLE001 - report the exact render error.
        return {
            "status": "failed",
            "path": str(path),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    png = _png_info(path)
    if png is None:
        return {"status": "failed", "path": str(path), "error": "invalid png"}
    return {
        "status": "captured",
        "path": str(path),
        "method": "render_instruments_panel_rgba",
        "file_size_bytes": path.stat().st_size,
        "width": png["width"],
        "height": png["height"],
    }


def _collect_omnigraph_evidence(controller: ExtensionController) -> dict[str, Any]:
    """Record the OmniGraph node registration outcome honestly."""

    message = str(controller.state.omnigraph_status)
    record: dict[str, Any] = {"status_message": message}
    try:
        from isaac_audio_sensors_omni.graph_node import NODE_TYPE_NAME

        record["node_type_name"] = NODE_TYPE_NAME
    except Exception:  # noqa: BLE001 - name lookup is diagnostic only.
        record["node_type_name"] = None
    try:
        import omni.graph.core as og  # type: ignore

        get_node_type = getattr(og, "get_node_type", None)
        if callable(get_node_type) and record["node_type_name"]:
            node_type = get_node_type(record["node_type_name"])
            record["registry_lookup"] = bool(node_type)
    except Exception as exc:  # noqa: BLE001 - lookup is diagnostic only.
        record["registry_lookup_error"] = str(exc)
    duplicate_registered = (
        "Attempted to register Python node type" in message
        and "twice" in message
        and bool(record.get("registry_lookup"))
    )
    if (
        "registered:" in message
        or message.startswith("OmniGraph node registered")
        or message.startswith("OmniGraph node already registered")
        or duplicate_registered
    ):
        record["status"] = "passed"
    elif "unavailable" in message:
        record["status"] = "skipped"
    else:
        record["status"] = "failed"
    return record


def _collect_usd_debug_evidence(
    controller: ExtensionController,
    *,
    stage: Any,
) -> dict[str, Any]:
    """Prove the debug subtree is authored as real prims on the live stage."""

    paths = list(controller.state.latest_usd_debug_prim_paths)
    exists = {path: bool(_stage_has_prim(stage, path)) for path in paths}
    record: dict[str, Any] = {
        "root": controller.state.usd_debug_root,
        "enabled": controller.state.usd_debug_enabled,
        "prim_paths": paths,
        "prims_exist": exists,
        "root_exists": bool(_stage_has_prim(stage, controller.state.usd_debug_root)),
    }
    passed = bool(paths) and all(exists.values()) and record["root_exists"]
    record["status"] = "passed" if passed else "failed"
    return record


def _collect_audio_output_evidence(
    controller: ExtensionController,
    *,
    stage: Any,
) -> dict[str, Any]:
    """Exercise WAV export + panel preview on the room backend when available."""

    record: dict[str, Any] = {"requested_backend": "room_acoustics"}
    try:
        import pyroomacoustics  # type: ignore # noqa: F401
        import soundfile  # type: ignore # noqa: F401
    except ImportError as exc:
        record["status"] = "skipped"
        record["reason"] = f"room extra unavailable: {exc}"
        return record
    previous_backend = controller.state.backend
    try:
        controller.stop_sensor()
        if controller.state.source_attached_to_object:
            # The attach scenario's object may be gone; unbind for this leg.
            with suppress(Exception):
                controller.detach_source_from_object(stage=stage)
            controller.state.source_attached_to_object = False
            controller.state.attached_object_prim_path = ""
        controller.state.backend = "room_acoustics"
        controller.state.replicator_enabled = False
        controller.state.waveform_enabled = True
        controller.state.waveform_dir = "live_waveforms_gui"
        controller.state.waveform_mode = "per_frame"
        if controller.configure_sensor(stage=stage) is None:
            raise RuntimeError(
                controller.state.error_message or "room sensor configure failed"
            )
        if controller.start_sensor(stage=stage) is None:
            raise RuntimeError(
                controller.state.error_message or "room sensor start failed"
            )
        if controller.update_sensor(force=True) is None:
            raise RuntimeError(
                controller.state.error_message or "room sensor update failed"
            )
        paths = controller.state.latest_waveform_paths
        record["waveform_paths"] = list(paths)
        if not paths:
            raise RuntimeError("room_acoustics update produced no waveform_paths")
        from isaac_audio_sensors.core.io.wave_read import read_wav

        data = read_wav(paths[-1])
        record["waveform"] = {
            "channels": data.channel_count,
            "sample_rate_hz": data.sample_rate_hz,
            "frames": data.frame_count,
            "duration_s": data.duration_s,
        }
        window = getattr(controller, "_ui_window", None)
        if window is not None:
            record["panel_label"] = getattr(
                window._labels.get("waveform"), "text", None
            )
            panel = getattr(window, "_audio_panel", {}) or {}
            record["panel_rendered_path"] = panel.get("rendered_path")
        record["audition_status"] = (
            controller.play_latest_waveform() or controller.state.error_message
        )
        record["audition_stop_status"] = controller.stop_audition()
        record["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - evidence records the exact error.
        record["status"] = "failed"
        record["error_type"] = type(exc).__name__
        record["error"] = str(exc)
    finally:
        with suppress(Exception):
            controller.stop_sensor()
        with suppress(Exception):
            controller.close_sensor()
        controller.state.backend = previous_backend
        controller.state.waveform_enabled = False
    return record


def _capture_app_screenshot(path: Path) -> dict[str, Any]:
    """Capture the whole app swapchain (viewport plus Kit UI windows)."""

    attempts: list[dict[str, Any]] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        path.unlink()
    attempts.append(_attempt_renderer_swapchain_capture(path))
    record = _captured_screenshot_record(
        path=path,
        method="renderer_capture.capture_next_frame_swapchain",
        attempts=attempts,
        framed_paths=(),
    )
    if record is not None:
        return record
    return _screenshot_unavailable(
        path,
        reason=_last_attempt_reason(attempts),
        attempts=attempts,
        framed_paths=(),
    )


def _capture_viewport_screenshot(
    path: Path,
    *,
    framed_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    framed = tuple(path for path in framed_paths if path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        path.unlink()

    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        if viewport is None:
            return _screenshot_unavailable(
                path,
                reason="no active viewport",
                attempts=attempts,
                framed_paths=framed,
            )
        viewport_info = _viewport_info(viewport)
        _frame_viewport_paths(
            viewport_utility=viewport_utility,
            viewport=viewport,
            framed_paths=framed,
            attempts=attempts,
        )
        utility_capture = getattr(viewport_utility, "capture_viewport_to_file", None)
        if callable(utility_capture):
            attempts.append(
                _attempt_viewport_utility_capture(
                    utility_capture=utility_capture,
                    viewport=viewport,
                    path=path,
                )
            )
            record = _captured_screenshot_record(
                path=path,
                method="viewport_utility.capture_viewport_to_file",
                attempts=attempts,
                framed_paths=framed,
                viewport_info=viewport_info,
            )
            if record is not None:
                return record
        else:
            attempts.append(
                {
                    "method": "viewport_utility.capture_viewport_to_file",
                    "status": "unavailable",
                    "reason": "capture_viewport_to_file is not callable",
                }
            )

        legacy_capture = getattr(viewport, "capture_to_file", None)
        if callable(legacy_capture):
            attempts.append(
                _attempt_legacy_viewport_capture(
                    legacy_capture=legacy_capture,
                    path=path,
                )
            )
            record = _captured_screenshot_record(
                path=path,
                method="viewport.capture_to_file",
                attempts=attempts,
                framed_paths=framed,
                viewport_info=viewport_info,
            )
            if record is not None:
                return record
        else:
            attempts.append(
                {
                    "method": "viewport.capture_to_file",
                    "status": "unavailable",
                    "reason": "active viewport has no capture_to_file method",
                }
            )

        attempts.append(_attempt_renderer_swapchain_capture(path))
        record = _captured_screenshot_record(
            path=path,
            method="renderer_capture.capture_next_frame_swapchain",
            attempts=attempts,
            framed_paths=framed,
            viewport_info=viewport_info,
        )
        if record is not None:
            return record
        return _screenshot_unavailable(
            path,
            reason=_last_attempt_reason(attempts),
            attempts=attempts,
            framed_paths=framed,
            viewport_info=viewport_info,
        )
    except Exception as exc:  # noqa: BLE001 - screenshot is optional evidence.
        attempts.append(
            {
                "method": "capture_viewport_screenshot",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return _screenshot_unavailable(
            path,
            reason=f"{type(exc).__name__}: {exc}",
            attempts=attempts,
            framed_paths=framed,
        )


def _frame_viewport_paths(
    *,
    viewport_utility: Any,
    viewport: Any,
    framed_paths: tuple[str, ...],
    attempts: list[dict[str, Any]],
) -> None:
    if not framed_paths:
        return
    frame = getattr(viewport_utility, "frame_viewport_prims", None)
    if not callable(frame):
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "unavailable",
                "reason": "frame_viewport_prims is not callable",
                "framed_paths": list(framed_paths),
            }
        )
        return
    try:
        framed = frame(viewport, prims=list(framed_paths))
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "passed" if framed else "returned_false",
                "framed_paths": list(framed_paths),
            }
        )
    except Exception as exc:  # noqa: BLE001 - framing failure is diagnostic only.
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "failed",
                "framed_paths": list(framed_paths),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )


def _attempt_viewport_utility_capture(
    *,
    utility_capture: Any,
    viewport: Any,
    path: Path,
) -> dict[str, Any]:
    try:
        result = utility_capture(viewport, file_path=str(path))
        wait_result = _wait_for_capture_result(result)
        return {
            "method": "viewport_utility.capture_viewport_to_file",
            "status": "called",
            "result": str(result),
            "wait_result": _result_summary(wait_result),
            "file_wait": _wait_for_screenshot_file(path),
        }
    except Exception as exc:  # noqa: BLE001 - fall back to the next API.
        return {
            "method": "viewport_utility.capture_viewport_to_file",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _attempt_legacy_viewport_capture(
    *,
    legacy_capture: Any,
    path: Path,
) -> dict[str, Any]:
    try:
        result = legacy_capture(str(path))
        wait_result = _wait_for_capture_result(result)
        return {
            "method": "viewport.capture_to_file",
            "status": "called",
            "result": str(result),
            "wait_result": _result_summary(wait_result),
            "file_wait": _wait_for_screenshot_file(path),
        }
    except Exception as exc:  # noqa: BLE001 - fall back to renderer capture.
        return {
            "method": "viewport.capture_to_file",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _attempt_renderer_swapchain_capture(path: Path) -> dict[str, Any]:
    try:
        import omni.renderer_capture  # type: ignore

        renderer = omni.renderer_capture.acquire_renderer_capture_interface()
        capture = getattr(renderer, "capture_next_frame_swapchain", None)
        if not callable(capture):
            return {
                "method": "renderer_capture.capture_next_frame_swapchain",
                "status": "unavailable",
                "reason": "capture_next_frame_swapchain is not callable",
            }
        result = capture(str(path))
        wait_async = getattr(renderer, "wait_async_capture", None)
        wait_result = _wait_for_capture_result(
            wait_async() if callable(wait_async) else None
        )
        return {
            "method": "renderer_capture.capture_next_frame_swapchain",
            "status": "called",
            "result": str(result),
            "wait_result": _result_summary(wait_result),
            "file_wait": _wait_for_screenshot_file(path),
        }
    except Exception as exc:  # noqa: BLE001 - report the exact renderer error.
        return {
            "method": "renderer_capture.capture_next_frame_swapchain",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _wait_for_capture_result(result: Any) -> Any:
    if result is None:
        return None
    for method_name in ("wait", "wait_for_result"):
        method = getattr(result, method_name, None)
        if callable(method):
            value = method()
            if inspect.isawaitable(value):
                return _run_capture_awaitable(value)
            return value
    if inspect.isawaitable(result):
        return _run_capture_awaitable(result)
    return None


def _run_capture_awaitable(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        return "event_loop_running_wait_skipped"
    return loop.run_until_complete(awaitable)


def _wait_for_screenshot_file(path: Path, *, max_updates: int = 120) -> dict[str, Any]:
    if _png_info(path) is not None:
        return {"status": "ready", "updates": 0}
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        update = getattr(app, "update", None) if app is not None else None
        if not callable(update):
            return {
                "status": "unavailable",
                "reason": "omni.kit.app.get_app().update is not callable",
                "updates": 0,
            }
        for index in range(max_updates):
            update()
            if _png_info(path) is not None:
                return {"status": "ready", "updates": index + 1}
        return {"status": "not_ready", "updates": max_updates}
    except Exception as exc:  # noqa: BLE001 - screenshot waiting is diagnostic.
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _captured_screenshot_record(
    *,
    path: Path,
    method: str,
    attempts: list[dict[str, Any]],
    framed_paths: tuple[str, ...],
    viewport_info: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    png = _png_info(path)
    if png is None:
        return None
    return {
        "status": "captured",
        "path": str(path),
        "method": method,
        "file_size_bytes": path.stat().st_size,
        "width": png["width"],
        "height": png["height"],
        "viewport_api_type": (viewport_info or {}).get("viewport_api_type"),
        "camera_path": (viewport_info or {}).get("camera_path"),
        "framed_paths": list(framed_paths),
        "attempts": attempts,
    }


def _screenshot_unavailable(
    path: Path,
    *,
    reason: str,
    attempts: list[dict[str, Any]],
    framed_paths: tuple[str, ...],
    viewport_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    png = _png_info(path)
    return {
        "status": "unavailable",
        "path": str(path),
        "reason": reason,
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
        "width": None if png is None else png["width"],
        "height": None if png is None else png["height"],
        "viewport_api_type": (viewport_info or {}).get("viewport_api_type"),
        "camera_path": (viewport_info or {}).get("camera_path"),
        "framed_paths": list(framed_paths),
        "attempts": attempts,
    }


def _viewport_info(viewport: Any) -> dict[str, Any]:
    camera = getattr(viewport, "camera_path", None)
    return {
        "viewport_api_type": type(viewport).__name__,
        "camera_path": str(getattr(camera, "pathString", camera or "")) or None,
    }


def _png_info(path: Path) -> dict[str, int] | None:
    if not path.is_file() or path.stat().st_size < 24:
        return None
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _last_attempt_reason(attempts: list[dict[str, Any]]) -> str:
    for attempt in reversed(attempts):
        if attempt.get("error"):
            return f"{attempt.get('method')}: {attempt.get('error')}"
        if attempt.get("reason"):
            return f"{attempt.get('method')}: {attempt.get('reason')}"
        if attempt.get("status") == "called":
            return f"{attempt.get('method')} did not create a readable PNG"
    return "no screenshot capture attempts were available"


def _enforce_required_screenshot(record: dict[str, Any], fixture_kind: str) -> None:
    if record.get("status") == "captured":
        return
    raise RuntimeError(
        "Viewport screenshot capture is required for "
        f"{fixture_kind} but failed: {json.dumps(record, sort_keys=True)}"
    )


def _validate_live_extension_outputs(
    *,
    evidence: dict[str, Any],
) -> None:
    for probe_name in (
        "ui_control_inventory",
        "ui_editable_model_probe",
        "ui_invalid_numeric_probe",
        "export_latest_without_frame",
        "config_roundtrip_probe",
        "instruments",
        "usd_debug",
    ):
        probe = evidence.get(probe_name, {})
        if probe.get("status") != "passed":
            raise RuntimeError(f"{probe_name} failed: {probe}")
    audio_output = evidence.get("audio_output", {})
    if audio_output.get("status") not in {"passed", "skipped"}:
        raise RuntimeError(f"audio_output evidence failed: {audio_output}")
    omnigraph = evidence.get("omnigraph", {})
    if omnigraph.get("status") not in {"passed", "skipped"}:
        raise RuntimeError(f"omnigraph evidence failed: {omnigraph}")
    error_checks = evidence.get("error_checks", {})
    missing_error_checks = [
        name for name, message in sorted(error_checks.items()) if not message
    ]
    if missing_error_checks:
        raise RuntimeError(
            "Readable error checks did not record messages: " f"{missing_error_checks}"
        )
    manager_status = evidence.get("kit_extension_manager", {})
    if manager_status.get("status") != "enabled":
        raise RuntimeError(
            "Kit extension manager did not prove extension enabled: "
            f"{manager_status}"
        )
    generic_result = evidence.get("object_attach_live_qa", {}).get("generic_scene")
    if generic_result is None:
        raise RuntimeError("Missing generic object-attach scenario evidence.")
    _validate_attach_scenario("generic_scene", generic_result)


def _validate_attach_scenario(name: str, result: dict[str, Any]) -> None:
    if result.get("status") != "passed":
        raise RuntimeError(f"{name} scenario did not pass: {result}")
    artifacts = result.get("artifacts", {})
    latest_frame_path = Path(str(artifacts.get("latest_frame_path", "")))
    frame_trace_path = Path(str(artifacts.get("frame_trace_path", "")))
    config_path = Path(str(artifacts.get("config_path", "")))
    replicator_dir = Path(str(artifacts.get("replicator_dir", "")))
    for required_path in (latest_frame_path, frame_trace_path, config_path):
        if not required_path.is_file():
            raise RuntimeError(f"{name} evidence artifact is missing: {required_path}")
    trace_lines = frame_trace_path.read_text(encoding="utf-8").splitlines()
    frames = [frame_from_trace_dict(json.loads(line)) for line in trace_lines]
    if len(frames) < 7:
        raise RuntimeError(
            f"{name} JSONL trace must include source and array move/rotation frames."
        )
    selected_object = str(result.get("selected_object_path", ""))
    if not selected_object or selected_object == "/World":
        raise RuntimeError(f"{name} selected object is not a real object path.")
    discovery = result.get("discovery", {})
    if discovery.get("selected_object_found") is not True:
        raise RuntimeError(f"{name} discovery did not include selected object.")
    attachment = result.get("source_object_attachment", {})
    if attachment.get("source_attached_to_object") is not True:
        raise RuntimeError(f"{name} did not attach source to object: {attachment}")
    if attachment.get("attached_object_prim_path") != selected_object:
        raise RuntimeError(f"{name} attached wrong object: {attachment}")
    profile_selection = result.get("sound_profile_selection", {})
    if not profile_selection.get("selected_profile_id"):
        raise RuntimeError(f"{name} did not select a sound profile.")
    if profile_selection.get("error_message"):
        raise RuntimeError(f"{name} profile auto-match reported an error.")
    profile_application = result.get("sound_profile_application", {})
    applied_profile = profile_application.get("applied_source_profile", {})
    if applied_profile.get("profile_id") != profile_selection.get(
        "selected_profile_id"
    ):
        raise RuntimeError(
            f"{name} applied profile does not match selection: "
            f"{profile_application}"
        )
    authored_attrs = profile_application.get("authored_attrs", {})
    for attr_name in (
        "filePath",
        "ias:source_id",
        "ias:class_label",
        "ias:audio_asset_path",
        "ias:start_time_s",
        "ias:duration_s",
        "ias:gain_db",
        "ias:directivity",
    ):
        if attr_name not in authored_attrs:
            raise RuntimeError(
                f"{name} profile apply did not author {attr_name}: "
                f"{profile_application}"
            )
    object_move = result.get("object_move_changed_frame", {})
    if object_move.get("status") != "passed":
        raise RuntimeError(f"{name} parent move did not change frame: {object_move}")
    before = result.get("frame_before_parent_move", {})
    after = result.get("frame_after_parent_move", {})
    if before.get("class_label") != profile_application.get("class_label"):
        raise RuntimeError(f"{name} frame class label did not use profile metadata.")
    if before.get("audio_asset_path") != profile_application.get("audio_asset_path"):
        raise RuntimeError(f"{name} frame audio asset did not use profile metadata.")
    if before.get("sector") == after.get("sector"):
        raise RuntimeError(f"{name} parent move did not change bearing sector.")
    if before.get("bearing_deg") == after.get("bearing_deg"):
        raise RuntimeError(f"{name} parent move did not change bearing.")
    if before.get("source_position_m") == after.get("source_position_m"):
        raise RuntimeError(f"{name} parent move did not change source pose.")
    offset_before = result.get("source_transform_before_local_offset_change", {})
    offset_after = result.get("source_transform_after_local_offset_change", {})
    if offset_before.get("position_world") == offset_after.get("position_world"):
        raise RuntimeError(f"{name} local offset did not change source world pose.")
    array_rotation = result.get("array_rotation_changed_frame", {})
    if array_rotation.get("status") != "passed":
        raise RuntimeError(
            f"{name} array rotation did not change frame outputs: {array_rotation}"
        )
    array_move = result.get("array_move_changed_frame", {})
    if array_move.get("status") != "passed":
        raise RuntimeError(
            f"{name} array mount move did not change frame outputs: {array_move}"
        )
    array_attachment = result.get("array_object_attachment", {})
    if array_attachment.get("array_attached_to_object") is not True:
        raise RuntimeError(
            f"{name} did not attach array to mount: {array_attachment}"
        )
    if array_attachment.get("attached_object_prim_path") != ARRAY_MOUNT_PRIM_PATH:
        raise RuntimeError(
            f"{name} attached array to wrong mount: {array_attachment}"
        )
    rig_application = result.get("rig_profile_application", {})
    rig_attrs = rig_application.get("authored_attrs", {})
    if rig_attrs.get("ias:rig_profile_id") != ARRAY_RIG_PROFILE_ID:
        raise RuntimeError(
            f"{name} rig profile was not authored on the array: {rig_application}"
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    array_binding_config = config.get("array_binding", {})
    if array_binding_config.get("attached") is not True:
        raise RuntimeError(f"{name} config did not preserve array attachment.")
    if (
        array_binding_config.get("attached_object_prim_path")
        != ARRAY_MOUNT_PRIM_PATH
    ):
        raise RuntimeError(f"{name} config preserved wrong array mount binding.")
    if array_binding_config.get("array_local_offset_m") != list(
        ARRAY_MOUNT_LOCAL_OFFSET
    ):
        raise RuntimeError(f"{name} config preserved wrong array local offset.")
    rig_config = config.get("microphone_rig_profiles", {})
    if rig_config.get("selected_rig_profile_id") != ARRAY_RIG_PROFILE_ID:
        raise RuntimeError(
            f"{name} config did not preserve selected rig profile id."
        )
    if not rig_config.get("rig_library"):
        raise RuntimeError(f"{name} config did not export rig library.")
    applied_rig_config = rig_config.get("applied_array_rig_profile") or {}
    if applied_rig_config.get("profile_id") != ARRAY_RIG_PROFILE_ID:
        raise RuntimeError(
            f"{name} config did not preserve applied rig profile snapshot."
        )
    object_binding = config.get("object_binding", {})
    if object_binding.get("attached") is not True:
        raise RuntimeError(f"{name} config did not preserve object attachment.")
    if object_binding.get("attached_object_prim_path") != selected_object:
        raise RuntimeError(f"{name} config preserved wrong object binding.")
    if object_binding.get("source_local_offset_m") != result.get("local_offset_after"):
        raise RuntimeError(f"{name} config preserved wrong local offset.")
    sound_profiles = config.get("sound_profiles", {})
    if sound_profiles.get("selected_profile_id") != profile_selection.get(
        "selected_profile_id"
    ):
        raise RuntimeError(f"{name} config did not preserve selected profile id.")
    if not sound_profiles.get("profile_library"):
        raise RuntimeError(f"{name} config did not export profile library.")
    if not sound_profiles.get("object_profile_mappings"):
        raise RuntimeError(f"{name} config did not export object-profile mappings.")
    applied_config = sound_profiles.get("applied_source_profile") or {}
    if applied_config.get("profile_id") != profile_selection.get("selected_profile_id"):
        raise RuntimeError(f"{name} config did not preserve applied profile snapshot.")
    import_result = result.get("config_import_result", {})
    if import_result.get("status") != "passed":
        raise RuntimeError(f"{name} config import/update failed: {import_result}")
    if import_result.get("attached_object_prim_path") != selected_object:
        raise RuntimeError(f"{name} import did not preserve object path.")
    if import_result.get("source_local_offset_m") != result.get("local_offset_after"):
        raise RuntimeError(f"{name} import did not preserve local offset.")
    missing = result.get("missing_object_probe", {})
    if missing.get("status") != "passed":
        raise RuntimeError(f"{name} missing-object status failed: {missing}")
    replicator_status = (
        result.get("config_export", {})
        .get("recording", {})
        .get(
            "replicator",
            {},
        )
    )
    if int(replicator_status.get("write_count", 0)) < 1:
        raise RuntimeError(f"{name} Replicator did not record a frame.")
    payload_files = [
        path
        for path in sorted(replicator_dir.iterdir())
        if path.is_file() and path.name.startswith("audio_sensor_frame_")
    ]
    if not payload_files:
        raise RuntimeError(f"{name} has no Replicator frame payload artifact.")
    payload = json.loads(payload_files[0].read_text(encoding="utf-8"))
    if payload.get("frame", {}).get("schema_version") != frames[-1].schema_version:
        raise RuntimeError(f"{name} Replicator payload frame schema mismatch.")


def _try_enable_extension_manager(
    *,
    extension_id: str,
    extension_path: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "requested_extension_id": extension_id,
        "extension_path": str(extension_path),
    }
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        manager = app.get_extension_manager() if app is not None else None
        if manager is None:
            return {"status": "unavailable", "reason": "no extension manager"}
        result["manager_type"] = type(manager).__name__
        result["manager_methods"] = _extension_manager_methods(manager)
        for method_name in ("add_path", "add_search_path", "add_extension_search_path"):
            method = getattr(manager, method_name, None)
            if not callable(method):
                continue
            try:
                method(str(extension_path.parent))
                result["search_path_method"] = method_name
                break
            except Exception as exc:  # noqa: BLE001 - try next API name.
                result[f"{method_name}_error"] = f"{type(exc).__name__}: {exc}"
        enable_called = False
        for method_name in ("set_extension_enabled_immediate", "set_extension_enabled"):
            method = getattr(manager, method_name, None)
            if not callable(method):
                continue
            try:
                enable_result = method(extension_id, True)
                result["enable_method"] = method_name
                result["enable_result"] = str(enable_result)
                enable_called = True
                break
            except Exception as exc:  # noqa: BLE001 - direct startup may still work.
                result[f"{method_name}_error"] = f"{type(exc).__name__}: {exc}"
        result["kit_update_after_enable"] = _pump_kit_app(app)
        result["verification"] = _verify_extension_manager_load(
            manager=manager,
            extension_id=extension_id,
            extension_path=extension_path,
            module_name="isaac_audio_sensors_omni",
        )
        if result["verification"].get("enabled") is True:
            result["status"] = "enabled"
        elif enable_called:
            result["status"] = "enable_called_unverified"
        else:
            result["status"] = "enable_api_unavailable_or_failed"
        return result
    except Exception as exc:  # noqa: BLE001 - direct startup may still work.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _enabled_extension_id(evidence: dict[str, Any]) -> str | None:
    value = (
        evidence.get("kit_extension_manager", {})
        .get("verification", {})
        .get("enabled_extension_id")
    )
    if value:
        return str(value)
    return None


def _extension_manager_methods(manager: Any) -> list[str]:
    names = []
    for name in dir(manager):
        lowered = name.lower()
        if "extension" in lowered or "enabled" in lowered:
            names.append(name)
    return sorted(names)[:80]


def _pump_kit_app(app: Any, *, updates: int = 4) -> dict[str, Any]:
    result: dict[str, Any] = {"requested_updates": updates, "called_updates": 0}
    update = getattr(app, "update", None)
    if not callable(update):
        result["status"] = "update_unavailable"
        return result
    for _ in range(updates):
        try:
            update()
            result["called_updates"] += 1
        except Exception as exc:  # noqa: BLE001 - diagnostic only.
            result["status"] = f"{type(exc).__name__}: {exc}"
            return result
    result["status"] = "updated"
    return result


def _verify_extension_manager_load(
    *,
    manager: Any,
    extension_id: str,
    extension_path: Path,
    module_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"enabled": False, "checks": []}
    full_ids: list[str] = []

    for method_name in ("is_extension_enabled", "is_extension_enabled_immediate"):
        check = _call_manager_method(manager, method_name, extension_id)
        result["checks"].append(check)
        if check.get("value") is True:
            result["enabled"] = True

    enabled_id_check = _call_manager_method(
        manager,
        "get_enabled_extension_id",
        extension_id,
    )
    result["checks"].append(enabled_id_check)
    enabled_id = enabled_id_check.get("value")
    if enabled_id:
        result["enabled"] = True
        full_ids.append(str(enabled_id))
        result["enabled_extension_id"] = str(enabled_id)

    module_id_check = _call_manager_method(
        manager,
        "get_extension_id_by_module",
        module_name,
    )
    result["checks"].append(module_id_check)
    module_id = module_id_check.get("value")
    if module_id:
        result["enabled"] = True
        full_ids.append(str(module_id))
        result["module_extension_id"] = str(module_id)

    for candidate_id in (extension_id, *full_ids):
        dict_check = _call_manager_method(manager, "get_extension_dict", candidate_id)
        result["checks"].append(dict_check)
        entry = dict_check.get("value")
        if isinstance(entry, dict):
            summary = _extension_entry_summary(entry)
            result.setdefault("extension_dicts", []).append(summary)
            if _entry_says_enabled(summary):
                result["enabled"] = True

    list_method = getattr(manager, "get_extensions", None)
    if callable(list_method):
        try:
            entries = list_method()
        except Exception as exc:  # noqa: BLE001 - diagnostic only.
            result["checks"].append(
                {
                    "method": "get_extensions",
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            result["checks"].append(
                {
                    "method": "get_extensions",
                    "status": "called",
                    "value": f"{len(entries)} extension entries",
                }
            )
            result["extension_count"] = len(entries)
            matches = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                summary = _extension_entry_summary(entry)
                if _extension_entry_matches(
                    summary,
                    extension_id=extension_id,
                    extension_path=extension_path,
                    module_name=module_name,
                ):
                    matches.append(summary)
                    if _entry_says_enabled(summary):
                        result["enabled"] = True
            result["matched_extensions"] = matches
    else:
        result["checks"].append({"method": "get_extensions", "status": "missing"})

    return result


def _call_manager_method(manager: Any, method_name: str, *args: Any) -> dict[str, Any]:
    method = getattr(manager, method_name, None)
    if not callable(method):
        return {"method": method_name, "status": "missing"}
    try:
        value = method(*args)
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        return {
            "method": method_name,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "method": method_name,
        "status": "called",
        "value": _compact_manager_value(value),
    }


def _compact_manager_value(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return _extension_entry_summary(value)
    if isinstance(value, tuple | list):
        return [_compact_manager_value(item) for item in value[:50]]
    return str(value)


def _extension_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "name",
        "package_id",
        "version",
        "path",
        "enabled",
        "loaded",
        "state",
        "python_module",
        "python_modules",
        "modules",
    )
    return {key: _compact_manager_value(entry[key]) for key in keys if key in entry}


def _entry_says_enabled(entry: dict[str, Any]) -> bool:
    for key in ("enabled", "loaded"):
        if entry.get(key) is True:
            return True
    state = str(entry.get("state", "")).lower()
    return "enabled" in state or "loaded" in state or "started" in state


def _extension_entry_matches(
    entry: dict[str, Any],
    *,
    extension_id: str,
    extension_path: Path,
    module_name: str,
) -> bool:
    joined = json.dumps(entry, sort_keys=True)
    return (
        extension_id in joined or module_name in joined or str(extension_path) in joined
    )


def _prepare_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_file():
            item.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
