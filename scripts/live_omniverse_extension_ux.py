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
    CurrentStageContext,
    ExtensionController,
)
from isaac_audio_sensors.isaac.viz.overlays import debug_primitives_to_dicts

EXTENSION_ID = "isaac_audio_sensors.omni"


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
    latest_frame_path = args.out.with_suffix(".latest_frame.json")
    replicator_dir = args.out.with_suffix(".replicator")
    screenshot_path = args.out.with_suffix(".viewport.png")
    _remove_existing_artifacts(
        args.out,
        frame_trace_path,
        config_path,
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

        extension = Extension()
        extension.on_startup(EXTENSION_ID)
        controller = extension.controller
        controller.ext_id = EXTENSION_ID
        controller.state.backend = "tdoa_synthetic"
        controller.state.jsonl_trace_path = str(frame_trace_path)
        controller.state.latest_frame_export_path = str(latest_frame_path)
        controller.state.config_export_path = str(config_path)
        controller.state.config_import_path = str(config_path)
        controller.state.replicator_enabled = True
        controller.state.replicator_output_dir = str(replicator_dir)

        evidence["ui_available"] = extension.ui_available
        evidence["error_checks"] = _run_error_checks(stage)

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
        _step(evidence, "export_latest_frame", controller.export_latest_frame)
        _step(evidence, "flush_replicator", controller.flush_replicator)
        _step(evidence, "stop_sensor", lambda: (controller.stop_sensor() or "stopped"))
        _step(evidence, "stop_replicator", controller.stop_replicator)
        _step(evidence, "export_config_summary", controller.export_config_summary)
        import_probe = ExtensionController()
        _step(
            evidence,
            "import_config_summary_probe",
            lambda: import_probe.import_config_summary(config_path),
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

        xform = UsdGeom.Xformable(prim)
        op = xform.AddTranslateOp()
        op.Set(Gf.Vec3d(*position))
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
    trace_lines = frame_trace_path.read_text(encoding="utf-8").splitlines()
    if not trace_lines:
        raise RuntimeError("JSONL trace has no AudioSensorFrame records.")
    frames = [frame_from_trace_dict(json.loads(line)) for line in trace_lines]
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
    result: dict[str, Any] = {"requested_extension_id": extension_id}
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        manager = app.get_extension_manager() if app is not None else None
        if manager is None:
            return {"status": "unavailable", "reason": "no extension manager"}
        result["manager_type"] = type(manager).__name__
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
        for method_name in ("set_extension_enabled_immediate", "set_extension_enabled"):
            method = getattr(manager, method_name, None)
            if not callable(method):
                continue
            try:
                method(extension_id, True)
                result["enable_method"] = method_name
                result["status"] = "enable_called"
                return result
            except Exception as exc:  # noqa: BLE001 - direct startup may still work.
                result[f"{method_name}_error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "enable_api_unavailable_or_failed"
        return result
    except Exception as exc:  # noqa: BLE001 - direct startup may still work.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _prepare_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_file():
            item.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
