"""Live Isaac Sim/Kit smoke for the Omniverse extension reference UX."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import traceback
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
from isaac_audio_sensors.isaac.extension_ui import (
    OMNI_ACTION_TOGGLE_WINDOW,
    OMNI_DEFAULT_HOTKEY,
    OMNI_MENU_GROUP,
    OMNI_WINDOW_TITLE,
    CurrentStageContext,
    ExtensionController,
)
from isaac_audio_sensors.isaac.viz.overlays import debug_primitives_to_dicts

EXTENSION_ID = "isaac_audio_sensors.omni"
EXPECTED_UI_SECTIONS = (
    "Stage",
    "Author Array",
    "Author Source",
    "Sensor",
    "Replicator",
    "Export",
)
EXPECTED_UI_BUTTONS = (
    "Refresh",
    "Use Array",
    "Use Source",
    "Use Base",
    "Discover",
    "Create/Attach Array",
    "Read Selected Transform",
    "Apply Position",
    "Front",
    "Right",
    "Left",
    "Behind",
    "Create/Attach Source",
    "Start",
    "Stop",
    "Update",
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
    "replicator_annotator_name",
    "replicator_output_dir",
    "replicator_writer_name",
    "robot_base_prim_path",
    "source_class_label",
    "source_id",
    "source_prim_path",
)
EXPECTED_FLOAT_FIELDS = (
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
    "replicator_enabled",
    "trace_enabled",
)
EXPECTED_COMBO_FIELDS = ("ambiguity_policy", "backend", "layout_name")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/omniverse_extension_live_ux.json"),
    )
    args = parser.parse_args()

    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    pre_frame_config_path = args.out.with_suffix(".pre_frame.config.json")
    latest_frame_path = args.out.with_suffix(".latest_frame.json")
    replicator_dir = args.out.with_suffix(".replicator")
    screenshot_path = args.out.with_suffix(".viewport.png")
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
            Path(__file__).resolve().parents[1] / "exts" / EXTENSION_ID
        ),
        "headless": True,
        "viewport_mode": "headless_or_existing_viewport",
        "workflow_steps": [],
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
        if getattr(controller, "_ui_window", None) is not None:
            controller._ui_window.push_state_to_widgets()

        evidence["ui_available"] = extension.ui_available
        evidence["ui_control_inventory"] = _inventory_ui_controls(controller)
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

        _step(
            evidence,
            "refresh_stage_selection_array",
            lambda: controller.refresh_stage_selection(
                stage=stage,
                selected_paths=("/World/Rig/AudioArray",),
            ),
        )
        _set_context_selection(("/World/Rig/AudioArray",), evidence)
        _step(
            evidence,
            "use_selected_as_array",
            lambda: controller.use_selected_as_array(
                stage=stage,
                selected_paths=("/World/Rig/AudioArray",),
            ),
        )
        _step(evidence, "author_array", lambda: controller.author_array(stage=stage))
        _set_context_selection(("/World/Sources/SpeakerA",), evidence)
        _step(
            evidence,
            "use_selected_as_source",
            lambda: controller.use_selected_as_source(
                stage=stage,
                selected_paths=("/World/Sources/SpeakerA",),
            ),
        )
        _step(
            evidence,
            "read_selected_source_transform",
            lambda: controller.read_selected_source_transform(
                stage=stage,
                selected_paths=("/World/Sources/SpeakerA",),
            ),
        )
        evidence["source_position_after_read"] = _source_position_state(controller)
        _step(
            evidence,
            "apply_source_front_preset",
            lambda: controller.apply_source_position_preset("front", stage=stage),
        )
        evidence["source_position_after_front_preset"] = _source_position_state(
            controller
        )
        _step(evidence, "author_source", lambda: controller.author_source(stage=stage))
        _set_context_selection(("/World/Rig",), evidence)
        _step(
            evidence,
            "use_selected_as_robot_base",
            lambda: controller.use_selected_as_robot_base(
                stage=stage,
                selected_paths=("/World/Rig",),
            ),
        )
        _step(
            evidence,
            "refresh_discovery",
            lambda: controller.refresh_discovery(stage=stage),
        )
        _step(
            evidence,
            "start_sensor",
            lambda: controller.start_sensor(
                stage=stage,
                subscribe_to_update_stream=False,
            ),
        )
        _step(evidence, "start_replicator", controller.start_replicator)
        frame = _step(evidence, "update_sensor", controller.update_sensor)
        if frame is None:
            message = controller.state.error_message or "Update returned None."
            raise RuntimeError(message)
        evidence["source_frame_before_move"] = _frame_source_summary(frame)
        source_prim = stage.GetPrimAtPath("/World/Sources/SpeakerA")
        _set_translate(source_prim, (0.0, 2.0, 0.0))
        evidence["source_transform_move_command"] = {
            "prim_path": "/World/Sources/SpeakerA",
            "position_world": [0.0, 2.0, 0.0],
        }
        _update_kit_once(evidence)
        moved_frame = _step(
            evidence,
            "update_sensor_after_source_move",
            controller.update_sensor,
        )
        if moved_frame is None:
            message = controller.state.error_message or "Moved update returned None."
            raise RuntimeError(message)
        evidence["source_frame_after_move"] = _frame_source_summary(moved_frame)
        evidence["source_move_changed_frame"] = _source_frame_changed(
            frame,
            moved_frame,
        )
        _step(evidence, "export_latest_frame", controller.export_latest_frame)
        _step(evidence, "flush_replicator", controller.flush_replicator)
        _step(evidence, "stop_sensor", lambda: (controller.stop_sensor() or "stopped"))
        _step(evidence, "stop_replicator", controller.stop_replicator)
        _step(evidence, "export_config_summary", controller.export_config_summary)
        import_probe = ExtensionController()
        import_probe.build_ui_if_available()
        _step(
            evidence,
            "import_config_summary_probe",
            lambda: import_probe.import_config_summary(config_path),
        )
        evidence["config_roundtrip_probe"] = _probe_config_roundtrip(
            import_probe,
            config_path,
        )

        screenshot = _capture_viewport_screenshot(screenshot_path)
        evidence["screenshot"] = screenshot

        _validate_live_extension_outputs(
            evidence=evidence,
            controller=controller,
            latest_frame_path=latest_frame_path,
            frame_trace_path=frame_trace_path,
            config_path=config_path,
            replicator_dir=replicator_dir,
        )
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


def _inventory_ui_controls(controller: ExtensionController) -> dict[str, Any]:
    window = getattr(controller, "_ui_window", None)
    if window is None:
        return {"status": "failed", "reason": "ui_window_unavailable"}
    sections = tuple(getattr(window, "_sections", ()))
    buttons = tuple(getattr(window, "_buttons", ()))
    inventory = {
        "sections": list(sections),
        "buttons": list(buttons),
        "string_fields": sorted(window._string_fields),
        "float_fields": sorted(window._float_fields),
        "int_fields": sorted(window._int_fields),
        "bool_fields": sorted(window._bool_fields),
        "combo_fields": sorted(window._combo_fields),
        "labels": sorted(window._labels),
    }
    missing = {
        "sections": _missing(EXPECTED_UI_SECTIONS, sections),
        "buttons": _missing(EXPECTED_UI_BUTTONS, buttons),
        "string_fields": _missing(EXPECTED_STRING_FIELDS, window._string_fields),
        "float_fields": _missing(EXPECTED_FLOAT_FIELDS, window._float_fields),
        "int_fields": _missing(EXPECTED_INT_FIELDS, window._int_fields),
        "bool_fields": _missing(EXPECTED_BOOL_FIELDS, window._bool_fields),
        "combo_fields": _missing(EXPECTED_COMBO_FIELDS, window._combo_fields),
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
    sample_rate = window._int_fields.get("sample_rate_hz")
    source_id = window._string_fields.get("source_id")
    if (
        duration is None
        or position_x is None
        or position_y is None
        or position_z is None
        or sample_rate is None
        or source_id is None
    ):
        return {"status": "failed", "reason": "expected editable fields missing"}
    duration.model.set_value("10.0")
    position_x.model.set_value("2.0")
    position_y.model.set_value("0.0")
    position_z.model.set_value("0.0")
    sample_rate.model.set_value("44100")
    source_id.model.set_value("speaker_a")
    window.sync_state_from_widgets()
    return {
        "status": "passed",
        "source_duration_s": controller.state.source_duration_s,
        "source_position_world": [
            controller.state.source_position_x_m,
            controller.state.source_position_y_m,
            controller.state.source_position_z_m,
        ],
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


def _frame_source_summary(frame: Any) -> dict[str, Any]:
    detections = tuple(getattr(frame, "detections", ()))
    detection = detections[0] if detections else None
    source_pose = None if detection is None else detection.source_pose
    return {
        "frame_id": getattr(frame, "frame_id", None),
        "frame_index": getattr(frame, "frame_index", None),
        "detection_count": len(detections),
        "source_id": None if detection is None else detection.source_id,
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
    lifecycle = payload.get("lifecycle", {})
    recording = payload.get("recording", {})
    package_jsonl = recording.get("package_jsonl", {})
    replicator = recording.get("replicator", {})
    return {
        "backend": payload.get("backend"),
        "array_prim_path": array.get("prim_path"),
        "source_prim_path": source.get("prim_path"),
        "source_id": source.get("source_id"),
        "source_position_world": source.get("position_world"),
        "source_duration_s": source.get("duration_s"),
        "sample_rate_hz": array.get("sample_rate_hz"),
        "jsonl_trace_path": package_jsonl.get("path"),
        "trace_enabled": package_jsonl.get("enabled"),
        "debug_overlay_enabled": lifecycle.get("debug_overlay_enabled"),
        "replicator_enabled": replicator.get("enabled"),
        "replicator_output_dir": replicator.get("output_dir"),
        "replicator_writer_name": replicator.get("writer_name"),
        "replicator_annotator_name": replicator.get("annotator_name"),
    }


def _observed_config_state(controller: ExtensionController) -> dict[str, Any]:
    state = controller.state
    return {
        "backend": state.backend,
        "array_prim_path": state.array_prim_path,
        "source_prim_path": state.source_prim_path,
        "source_id": state.source_id,
        "source_position_world": [
            state.source_position_x_m,
            state.source_position_y_m,
            state.source_position_z_m,
        ],
        "source_duration_s": state.source_duration_s,
        "sample_rate_hz": state.sample_rate_hz,
        "jsonl_trace_path": state.jsonl_trace_path,
        "trace_enabled": state.trace_enabled,
        "debug_overlay_enabled": state.debug_overlay_enabled,
        "replicator_enabled": state.replicator_enabled,
        "replicator_output_dir": state.replicator_output_dir,
        "replicator_writer_name": state.replicator_writer_name,
        "replicator_annotator_name": state.replicator_annotator_name,
    }


def _state_mismatches(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    mismatches = {}
    for key, expected_value in expected.items():
        observed_value = observed.get(key)
        if isinstance(expected_value, float):
            try:
                matched = abs(float(observed_value) - expected_value) <= 1e-9
            except (TypeError, ValueError):
                matched = False
        else:
            matched = observed_value == expected_value
        if not matched:
            mismatches[key] = {
                "expected": expected_value,
                "observed": observed_value,
            }
    return mismatches


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
    for path in (
        "/World",
        "/World/Rig",
        "/World/Rig/AudioArray",
        "/World/Sources",
        "/World/Sources/SpeakerA",
    ):
        if not _stage_has_prim(stage, path):
            stage.DefinePrim(path, "Xform")
    source = stage.GetPrimAtPath("/World/Sources/SpeakerA")
    _set_translate(source, (2.0, 1.0, 0.0))


def _set_translate(prim: Any, position: tuple[float, float, float]) -> None:
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
    if hasattr(stage, "GetPrimAtPath"):
        prim = stage.GetPrimAtPath(path)
        if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
            return True
    return False


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


def _capture_viewport_screenshot(path: Path) -> dict[str, Any]:
    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        if viewport is None:
            return {"status": "unavailable", "reason": "no active viewport"}
        capture = getattr(viewport, "capture_to_file", None)
        if not callable(capture):
            return {
                "status": "unavailable",
                "reason": "active viewport has no capture_to_file method",
            }
        result = capture(str(path))
        wait = getattr(result, "wait", None)
        if callable(wait):
            wait()
        return {
            "status": "captured" if path.exists() else "capture_called_no_file",
            "path": str(path),
            "result": str(result),
        }
    except Exception as exc:  # noqa: BLE001 - screenshot is optional evidence.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _validate_live_extension_outputs(
    *,
    evidence: dict[str, Any],
    controller: ExtensionController,
    latest_frame_path: Path,
    frame_trace_path: Path,
    config_path: Path,
    replicator_dir: Path,
) -> None:
    if not latest_frame_path.is_file():
        raise RuntimeError(f"Latest frame export is missing: {latest_frame_path}")
    if not frame_trace_path.is_file():
        raise RuntimeError(f"JSONL trace export is missing: {frame_trace_path}")
    if not config_path.is_file():
        raise RuntimeError(f"Config export is missing: {config_path}")
    for probe_name in (
        "ui_control_inventory",
        "ui_editable_model_probe",
        "ui_invalid_numeric_probe",
        "export_latest_without_frame",
        "config_roundtrip_probe",
    ):
        probe = evidence.get(probe_name, {})
        if probe.get("status") != "passed":
            raise RuntimeError(f"{probe_name} failed: {probe}")
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
    trace_lines = frame_trace_path.read_text(encoding="utf-8").splitlines()
    if not trace_lines:
        raise RuntimeError("JSONL trace has no AudioSensorFrame records.")
    frames = [frame_from_trace_dict(json.loads(line)) for line in trace_lines]
    if len(frames) < 2:
        raise RuntimeError("JSONL trace must include pre- and post-move frames.")
    source_move = evidence.get("source_move_changed_frame", {})
    if source_move.get("status") != "passed":
        raise RuntimeError(f"Source move did not change the next frame: {source_move}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    primitives = (
        ()
        if controller.sensor is None
        else tuple(controller.sensor.latest_debug_primitives)
    )
    primitive_kinds = sorted({primitive.kind for primitive in primitives})
    for required_kind in ("microphone", "source", "bearing_ray", "sector_wedge"):
        if required_kind not in primitive_kinds:
            raise RuntimeError(f"Overlay primitive kind missing: {required_kind}")
    replicator_status = config.get("recording", {}).get("replicator", {})
    if int(replicator_status.get("write_count", 0)) < 1:
        raise RuntimeError("Replicator did not record a frame.")
    replicator_files = sorted(
        path for path in replicator_dir.iterdir() if path.is_file()
    )
    payload_files = [
        path for path in replicator_files if path.name.startswith("audio_sensor_frame_")
    ]
    if not payload_files:
        raise RuntimeError("Replicator output has no frame payload artifact.")
    payload = json.loads(payload_files[0].read_text(encoding="utf-8"))
    if payload.get("frame", {}).get("schema_version") != frames[-1].schema_version:
        raise RuntimeError("Replicator payload does not carry AudioSensorFrame v1.")

    evidence.update(
        {
            "exported_latest_frame_path": str(latest_frame_path),
            "exported_jsonl_path": str(frame_trace_path),
            "exported_config_path": str(config_path),
            "jsonl_frame_count": len(frames),
            "jsonl_backend_ids": sorted({frame.backend_id for frame in frames}),
            "latest_frame_id": frames[-1].frame_id,
            "overlay_primitive_count": len(primitives),
            "overlay_primitive_kinds": primitive_kinds,
            "overlay_primitives": debug_primitives_to_dicts(primitives),
            "replicator_status": replicator_status,
            "replicator_artifacts": [str(path) for path in replicator_files],
            "replicator_payload_schema": payload.get("schema_version"),
            "replicator_payload_frame_schema": payload.get("frame", {}).get(
                "schema_version"
            ),
            "controller_status_message": controller.state.status_message,
            "controller_error_message": controller.state.error_message,
        }
    )


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
