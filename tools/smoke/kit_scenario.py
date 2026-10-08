"""Live source/array authoring, attachment and configuration scenario."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from kit_capture import (
    _capture_viewport_screenshot,
    _enforce_required_screenshot,
)
from kit_common import (
    _require_stage_prim,
    _result_summary,
    _stage_get_prim_at_path,
    _stage_has_prim,
    _step,
    _stringify_artifacts,
)
from kit_outputs import (
    _collect_usd_debug_evidence,
)
from kit_ui import (
    _collect_instruments_evidence,
    _collect_observed_gui_evidence,
    _combo_model_values,
    _push_state_to_widgets,
    _reference_ui_window,
)
from live_isaac_sim_audio_smoke import (
    _update_kit_once,
)

from isaac_audio_sensors.core.io.traces import frame_from_trace_dict
from isaac_audio_sensors.core.math_utils import quaternion_from_euler_deg
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    prim_path,
    prim_type_name,
)
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.state import CurrentStageContext

ARRAY_RIG_PROFILE_ID = "quad_cross_120mm"


ARRAY_MOUNT_PRIM_PATH = "/World/Rig/RobotMount"


ARRAY_MOUNT_POSITION_BEFORE = (0.0, -1.0, 0.0)


ARRAY_MOUNT_POSITION_AFTER = (1.5, -2.0, 0.5)


ARRAY_MOUNT_LOCAL_OFFSET = (0.0, 0.0, 0.1)


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
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
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
    _push_state_to_widgets(controller)

    result: dict[str, Any] = {
        "status": "started",
        "fixture_kind": fixture_kind,
        "usd_path": str(usd_path) if usd_path is not None else None,
        "artifacts": _stringify_artifacts(artifacts),
        "stage_open": stage_open,
        "stage_summary": _stage_summary(stage),
        "selected_object_path": object_path,
        "selected_object_label": _path_name(object_path),
        "selected_object_type": prim_type_name(object_prim),
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
    # Activity requires new contiguous samples, not repeated paused snapshots.
    import omni.timeline

    timeline = omni.timeline.get_timeline_interface()
    timeline.set_current_time(before_frame.end_time_s)
    timeline.commit()
    before_frame = _step(
        evidence,
        f"{label}_contiguous_activity_window",
        controller.update_sensor,
    )
    if not before_frame.observations:
        raise RuntimeError("Contiguous reference windows did not produce activity.")
    result["frame_before_parent_move"] = _frame_signal_summary(before_frame)

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
    result["frame_after_parent_move"] = _frame_signal_summary(after_move_frame)
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
    _push_state_to_widgets(controller)
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
    result["frame_after_local_offset_change"] = _frame_signal_summary(
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
    _push_state_to_widgets(controller)
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
    _push_state_to_widgets(controller)
    _step(
        evidence,
        f"{label}_attach_array_to_object",
        lambda: controller.attach_array_to_object(stage=stage),
    )
    controller.state.object_prim_path = saved_object_path
    controller.state.object_label = saved_object_label
    _push_state_to_widgets(controller)
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

    if fixture_kind == "generic_scene":
        # Capture valid instruments before intentionally invalidating acquisition.
        evidence["instruments"] = _step(
            evidence,
            "instruments_live_qa",
            lambda: _collect_instruments_evidence(
                controller,
                screenshot_path=Path(evidence["evidence_path"]).with_suffix(
                    ".instruments.png"
                ),
            ),
        )
        evidence["observed_gui"] = _collect_observed_gui_evidence(
            controller, Path(evidence["evidence_path"]).parent / "observed_gui"
        )
        evidence["usd_debug"] = _step(
            evidence,
            "usd_debug_live_qa",
            lambda: _collect_usd_debug_evidence(controller, stage=stage),
        )

    result["missing_object_probe"] = _probe_missing_object_status(
        controller=controller,
        stage=stage,
        object_path=object_path,
    )
    _step(
        evidence,
        f"{label}_stop_sensor",
        lambda: controller.stop_sensor() or "stopped",
    )
    result["replicator_status"] = _step(
        evidence,
        f"{label}_stop_replicator",
        controller.stop_replicator,
    )
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
        ("/World/IasAcousticEnvironment", "Cube"),
    ):
        if not _stage_has_prim(stage, path):
            stage.DefinePrim(path, prim_type)
    source = _require_stage_prim(stage, source_prim_path)
    _set_translate(source, (2.0, 0.0, 0.0))
    mount = _require_stage_prim(stage, ARRAY_MOUNT_PRIM_PATH)
    _set_translate(mount, ARRAY_MOUNT_POSITION_BEFORE)
    with suppress(Exception):
        from pxr import UsdGeom  # type: ignore

        environment = _require_stage_prim(stage, "/World/IasAcousticEnvironment")
        UsdGeom.Cube(environment).CreateSizeAttr(12.0)


def _stage_summary(stage: Any) -> dict[str, Any]:
    default_prim = None
    with_default = getattr(stage, "GetDefaultPrim", None)
    if callable(with_default):
        prim = with_default()
        if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
            default_prim = prim_path(prim)
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
        "activity_detection": payload.get("activity_detection", {}),
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
    try:
        roundtrip = _probe_config_roundtrip(imported, config_path)
    finally:
        imported._lifecycle._ui_window.close()
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
            None if frame is None else _frame_signal_summary(frame)
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
            if (
                frame is None
                and message
                and expected_path in message
                and controller.state.latest_frame_id is None
                and not controller.state.latest_aggregate_rms
                and not controller.state.sensor_running
            )
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
        return {
            "removed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
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


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


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
        "prim_type": None if prim is None else prim_type_name(prim),
        "file_path_authored": (
            False if prim is None else _prim_attr_is_authored(prim, "filePath")
        ),
        "authored_attrs": {
            key: _jsonable_value(attrs.get(key))
            for key in (
                "auralMode",
                "loopCount",
                "startTime",
                "endTime",
                "gain",
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
            if key in attrs and _prim_attr_is_authored(prim, key)
        },
        "status_message": state.status_message,
        "error_message": state.error_message,
    }


def _frame_signal_summary(frame: Any) -> dict[str, Any]:
    observations = tuple(getattr(frame, "observations", ()))
    return {
        "frame_id": getattr(frame, "frame_id", None),
        "frame_index": getattr(frame, "frame_index", None),
        "observation_count": len(observations),
        "observation_origins": [item.origin.value for item in observations],
        "observation_detector_ids": [item.detector_id for item in observations],
        "observation_scores": [item.detection_score for item in observations],
        "observation_has_doa": [item.doa is not None for item in observations],
        "aggregate_per_mic_rms": dict(getattr(frame, "aggregate_per_mic_rms", {})),
    }


def _source_frame_changed(before: Any, after: Any) -> dict[str, Any]:
    before_summary = _frame_signal_summary(before)
    after_summary = _frame_signal_summary(after)
    return {
        "status": (
            "passed"
            if before_summary["aggregate_per_mic_rms"]
            != after_summary["aggregate_per_mic_rms"]
            and _valid_activity_summary(before_summary)
            and _valid_activity_summary(after_summary)
            else "failed"
        ),
        "before": before_summary,
        "after": after_summary,
    }


def _valid_activity_summary(summary: dict[str, Any]) -> bool:
    count = int(summary.get("observation_count", 0))
    if count == 0:
        return True
    return (
        count == 1
        and summary.get("observation_origins") == ["signal_derived"]
        and summary.get("observation_detector_ids") == ["auditok"]
        and summary.get("observation_scores") == [None]
        and summary.get("observation_has_doa") == [False]
    )


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
    summary = _frame_signal_summary(frame)
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
        "rms_changed": (
            before.get("aggregate_per_mic_rms") != after.get("aggregate_per_mic_rms")
        ),
        "valid_activity_output": (
            _valid_activity_summary(before) and _valid_activity_summary(after)
        ),
    }
    passed = (
        checks["orientation_changed"]
        and checks["mic_world_positions_changed"]
        and checks["rms_changed"]
        and checks["valid_activity_output"]
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
        "rms_changed": (
            before.get("aggregate_per_mic_rms") != after.get("aggregate_per_mic_rms")
        ),
        "valid_activity_output": (
            _valid_activity_summary(before) and _valid_activity_summary(after)
        ),
    }
    passed = (
        checks["array_position_changed"]
        and checks["mic_world_positions_changed"]
        and checks["rms_changed"]
        and checks["valid_activity_output"]
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
    window = _reference_ui_window(controller)
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
    activity_detection = payload.get("activity_detection", {})
    direction_estimation = payload.get("direction_estimation", {})
    return {
        "backend": payload.get("backend"),
        "energy_threshold_dbfs": activity_detection.get("energy_threshold_dbfs"),
        "doa_enabled": direction_estimation.get("enabled"),
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
        "energy_threshold_dbfs": state.energy_threshold_dbfs,
        "doa_enabled": state.doa_enabled,
        "array_prim_path": state.array_prim_path,
        "array_position_world": [
            state.array_position_x_m,
            state.array_position_y_m,
            state.array_position_z_m,
        ],
        "array_orientation_world_quat": list(
            quaternion_from_euler_deg(
                roll_deg=state.array_roll_deg,
                pitch_deg=state.array_pitch_deg,
                yaw_deg=state.array_yaw_deg,
            )
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


def _create_stage(evidence: dict[str, Any]) -> Any:
    import omni.usd  # type: ignore

    context = omni.usd.get_context()
    context.new_stage()
    _update_kit_once(evidence)
    stage = context.get_stage()
    if stage is None:
        raise RuntimeError("omni.usd did not provide a stage after new_stage().")
    return stage


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


def _prim_attr_is_authored(prim: Any, name: str) -> bool:
    if hasattr(prim, "attributes"):
        return name in prim.attributes
    get_attribute = getattr(prim, "GetAttribute", None)
    if not callable(get_attribute):
        return False
    attr = get_attribute(name)
    has_authored_value = getattr(attr, "HasAuthoredValueOpinion", None)
    return bool(callable(has_authored_value) and has_authored_value())


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
    controller.state.environment_resolution_mode = "manual_free_field"
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
            f"{name} applied profile does not match selection: {profile_application}"
        )
    authored_attrs = profile_application.get("authored_attrs", {})
    for attr_name in (
        "auralMode",
        "loopCount",
        "startTime",
        "endTime",
        "gain",
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
    if profile_application.get("prim_type") != "OmniSound":
        raise RuntimeError(
            f"{name} profile apply did not migrate to OmniSound: {profile_application}"
        )
    if profile_application.get("file_path_authored") is not False:
        raise RuntimeError(
            f"{name} generated audio unexpectedly authored filePath: "
            f"{profile_application}"
        )
    object_move = result.get("object_move_changed_frame", {})
    if object_move.get("status") != "passed":
        raise RuntimeError(f"{name} parent move did not change frame: {object_move}")
    before = result.get("frame_before_parent_move", {})
    after = result.get("frame_after_parent_move", {})
    if not _valid_activity_summary(before):
        raise RuntimeError(f"{name} emitted an invalid warm-up observation.")
    if not _valid_activity_summary(after):
        raise RuntimeError(f"{name} emitted an invalid activity observation.")
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
        raise RuntimeError(f"{name} did not attach array to mount: {array_attachment}")
    if array_attachment.get("attached_object_prim_path") != ARRAY_MOUNT_PRIM_PATH:
        raise RuntimeError(f"{name} attached array to wrong mount: {array_attachment}")
    rig_application = result.get("rig_profile_application", {})
    rig_attrs = rig_application.get("authored_attrs", {})
    if rig_attrs.get("ias:rig_profile_id") != ARRAY_RIG_PROFILE_ID:
        raise RuntimeError(
            f"{name} rig profile was not authored on the array: {rig_application}"
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "ias.omni_extension_binding.v7":
        raise RuntimeError(f"{name} did not export binding v7.")
    if config.get("activity_detection") != {
        "detector_id": "auditok",
        "energy_threshold_dbfs": -60.0,
    }:
        raise RuntimeError(f"{name} did not preserve Auditok activity settings.")
    if config.get("direction_estimation") != {"enabled": False}:
        raise RuntimeError(f"{name} did not preserve DOA opt-in state.")
    array_binding_config = config.get("array_binding", {})
    if array_binding_config.get("attached") is not True:
        raise RuntimeError(f"{name} config did not preserve array attachment.")
    if array_binding_config.get("attached_object_prim_path") != ARRAY_MOUNT_PRIM_PATH:
        raise RuntimeError(f"{name} config preserved wrong array mount binding.")
    if array_binding_config.get("array_local_offset_m") != list(
        ARRAY_MOUNT_LOCAL_OFFSET
    ):
        raise RuntimeError(f"{name} config preserved wrong array local offset.")
    rig_config = config.get("microphone_rig_profiles", {})
    if rig_config.get("selected_rig_profile_id") != ARRAY_RIG_PROFILE_ID:
        raise RuntimeError(f"{name} config did not preserve selected rig profile id.")
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
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in payload_files]
    if payloads[-1].get("frame", {}).get("schema_version") != frames[-1].schema_version:
        raise RuntimeError(f"{name} Replicator payload frame schema mismatch.")
    observed_payloads = [
        payload
        for payload in payloads
        if payload.get("summary", {}).get("observation_count") == 1
    ]
    if not observed_payloads:
        raise RuntimeError(f"{name} Replicator did not preserve activity observations.")
    observation = observed_payloads[-1].get("frame", {}).get("observations", [{}])[0]
    if (
        observation.get("origin") != "signal_derived"
        or observation.get("detector_id") != "auditok"
    ):
        raise RuntimeError(f"{name} Replicator activity observation is invalid.")
