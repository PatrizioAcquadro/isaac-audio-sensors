"""In-Kit probe used by the S1.6 clean-install gate."""

from __future__ import annotations

import importlib
import json
import os
import site
import sys
import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import tomllib

EXTENSION_ID = "isaac_audio_sensors.omni"
EXPECTED_VERSION = "1.8.0"
PROVENANCE_MODULES = (
    "isaac_audio_sensors",
    "numpy",
    "scipy",
    "soundfile",
    "pyroomacoustics",
    "typing_extensions",
)


def _origin_record(name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - absence/broken optional imports are evidence.
        return {
            "status": "absent",
            "origin": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "present",
        "origin": getattr(module, "__file__", None),
        "version": getattr(module, "__version__", None),
    }


def _is_under(path: str | None, root: str | Path | None) -> bool:
    if not path or not root:
        return False
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    for attribute in ("to_dict", "as_dict"):
        method = getattr(value, attribute, None)
        if callable(method):
            with suppress(Exception):
                return _json_ready(method())
    fields = {}
    for name in ("id", "prim_path", "backend", "frame_id", "schema_version"):
        if hasattr(value, name):
            fields[name] = _json_ready(getattr(value, name))
    return fields or repr(value)


def _write_json(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_ready(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _pump_app(updates: int = 4) -> int:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    update = getattr(app, "update", None) if app is not None else None
    if not callable(update):
        return 0
    completed = 0
    for _ in range(updates):
        update()
        completed += 1
    return completed


def _run_step(
    evidence: dict[str, Any], name: str, action: Callable[[], Any]
) -> Any | None:
    record: dict[str, Any] = {"status": "started"}
    evidence["steps"][name] = record
    try:
        result = action()
        if result is None or result is False:
            raise RuntimeError(f"{name} returned {result!r}")
        record["result"] = _json_ready(result)
        record["status"] = "passed"
        return result
    except Exception as exc:  # noqa: BLE001 - every live step must be recorded.
        record.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return None


def _manager_call(manager: Any, name: str, *args: Any) -> Any:
    method = getattr(manager, name, None)
    if not callable(method):
        return None
    return method(*args)


def _extension_path(manager: Any, extension_id: str, entry: Any) -> str | None:
    for method_name in ("get_extension_path", "get_extension_path_by_id"):
        with suppress(Exception):
            value = _manager_call(manager, method_name, extension_id)
            if value:
                return str(value)
    if isinstance(entry, dict):
        for key in ("path", "extension_path"):
            if entry.get(key):
                return str(entry[key])
    return None


def _extension_version(entry: Any, extension_id: str) -> str | None:
    if isinstance(entry, dict):
        if entry.get("version"):
            return str(entry["version"])
        package = entry.get("package")
        if isinstance(package, dict) and package.get("version"):
            return str(package["version"])
    prefix = f"{EXTENSION_ID}-"
    if extension_id.startswith(prefix):
        return extension_id[len(prefix) :]
    return None


def _extension_manager_state() -> tuple[Any, dict[str, Any]]:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    manager = app.get_extension_manager() if app is not None else None
    if manager is None:
        raise RuntimeError("Kit extension manager is unavailable")
    enabled_id = None
    with suppress(Exception):
        enabled_id = _manager_call(manager, "get_enabled_extension_id", EXTENSION_ID)
    candidate = str(enabled_id or EXTENSION_ID)
    enabled = False
    for method_name in ("is_extension_enabled", "is_extension_enabled_immediate"):
        with suppress(Exception):
            enabled = bool(_manager_call(manager, method_name, candidate)) or enabled
            enabled = bool(_manager_call(manager, method_name, EXTENSION_ID)) or enabled
    enabled = bool(enabled_id) or enabled
    entry = None
    with suppress(Exception):
        entry = _manager_call(manager, "get_extension_dict", candidate)
    path = _extension_path(manager, candidate, entry)
    path_source = "extension_manager"
    if not path:
        module = importlib.import_module("isaac_audio_sensors_omni")
        module_file = getattr(module, "__file__", None)
        if module_file:
            path = str(Path(module_file).resolve().parents[1])
            path_source = "enabled_extension_module"
    version = _extension_version(entry, candidate)
    version_source = "extension_manager"
    if version is None and path:
        manifest_path = Path(path) / "config" / "extension.toml"
        with suppress(OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            version = str(manifest["package"]["version"])
            version_source = "enabled_extension_manifest"
    expected_folder = os.environ.get("IAS_CLEAN_EXT_FOLDER")
    record = {
        "requested_id": EXTENSION_ID,
        "enabled_id": candidate,
        "enabled": enabled,
        "version": version,
        "version_source": version_source,
        "path": path,
        "path_source": path_source,
        "expected_ext_folder": expected_folder,
    }
    errors = []
    if not enabled:
        errors.append("extension is not enabled")
    if version != EXPECTED_VERSION:
        errors.append(
            f"extension version is {version!r}, expected {EXPECTED_VERSION!r}"
        )
    if not _is_under(path, expected_folder):
        errors.append(f"extension path is outside the clean folder: {path}")
    record["errors"] = errors
    record["status"] = "failed" if errors else "passed"
    return manager, record


def _create_empty_stage() -> Any:
    import omni.usd  # type: ignore

    context = omni.usd.get_context()
    created = context.new_stage()
    _pump_app()
    stage = context.get_stage()
    if stage is None:
        raise RuntimeError(
            f"omni.usd did not provide a stage after new_stage(): {created!r}"
        )
    return stage


def _capture_gui_screenshot(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        path.unlink()
    attempts: list[dict[str, Any]] = []
    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        capture = getattr(viewport_utility, "capture_viewport_to_file", None)
        if viewport is not None and callable(capture):
            result = capture(viewport, file_path=str(path))
            attempts.append(
                {
                    "method": "viewport_utility.capture_viewport_to_file",
                    "result": str(result),
                }
            )
            for _ in range(180):
                _pump_app(1)
                if path.is_file() and path.stat().st_size > 10 * 1024:
                    return {
                        "status": "captured",
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
                        "attempts": attempts,
                    }
    except Exception as exc:  # noqa: BLE001 - renderer fallback is attempted.
        attempts.append(
            {
                "method": "viewport_utility.capture_viewport_to_file",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    try:
        import omni.renderer_capture  # type: ignore

        renderer = omni.renderer_capture.acquire_renderer_capture_interface()
        capture = getattr(renderer, "capture_next_frame_swapchain", None)
        if callable(capture):
            result = capture(str(path))
            attempts.append(
                {
                    "method": "renderer_capture.capture_next_frame_swapchain",
                    "result": str(result),
                }
            )
            for _ in range(180):
                _pump_app(1)
                if path.is_file() and path.stat().st_size > 10 * 1024:
                    return {
                        "status": "captured",
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
                        "attempts": attempts,
                    }
    except Exception as exc:  # noqa: BLE001 - exact failure is evidence.
        attempts.append(
            {
                "method": "renderer_capture.capture_next_frame_swapchain",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    return {
        "status": "failed",
        "path": str(path),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "attempts": attempts,
    }


def _lifecycle(manager: Any) -> dict[str, Any]:
    enabled_id = _manager_call(manager, "get_enabled_extension_id", EXTENSION_ID)
    target = str(enabled_id or EXTENSION_ID)
    setter_name = None
    for name in ("set_extension_enabled_immediate", "set_extension_enabled"):
        if callable(getattr(manager, name, None)):
            setter_name = name
            break
    if setter_name is None:
        raise RuntimeError("extension manager has no enable/disable method")
    setter = getattr(manager, setter_name)
    disabled_result = setter(target, False)
    _pump_app()
    disabled = not bool(_manager_call(manager, "is_extension_enabled", target))
    enabled_result = setter(target, True)
    _pump_app()
    enabled = bool(_manager_call(manager, "is_extension_enabled", target))
    if not enabled:
        enabled = bool(_manager_call(manager, "get_enabled_extension_id", EXTENSION_ID))
    package = importlib.import_module("isaac_audio_sensors")
    origin = getattr(package, "__file__", None)
    if not disabled or not enabled or "_vendor" not in Path(str(origin)).parts:
        raise RuntimeError(
            f"lifecycle verification failed: disabled={disabled}, enabled={enabled}, "
            f"origin={origin}"
        )
    return {
        "method": setter_name,
        "extension_id": target,
        "disable_result": str(disabled_result),
        "disabled_confirmed": disabled,
        "enable_result": str(enabled_result),
        "enabled_confirmed": enabled,
        "package_origin_after_reenable": origin,
    }


def _request_kit_quit() -> None:
    with suppress(Exception):
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        post_quit = getattr(app, "post_quit", None) if app is not None else None
        if callable(post_quit):
            post_quit(0)
            return
        quit_app = getattr(app, "quit", None) if app is not None else None
        if callable(quit_app):
            quit_app()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        raise SystemExit("usage: live_clean_install_probe.py OUTPUT_JSON")
    output_path = Path(arguments[0]).expanduser().resolve()
    gui_mode = os.environ.get("IAS_CLEAN_INSTALL_GUI") == "1"
    evidence: dict[str, Any] = {
        "status": "started",
        "argv": sys.argv,
        "sys_executable": sys.executable,
        "sys_path": list(sys.path),
        "cwd": os.getcwd(),
        "gui_mode": gui_mode,
        "environment": {
            "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE"),
            "PYTHONPATH_absent": "PYTHONPATH" not in os.environ,
            "PYTHONHOME_absent": "PYTHONHOME" not in os.environ,
            "PIP_variables_present": sorted(
                key for key in os.environ if key.startswith("PIP_")
            ),
        },
        "site_ENABLE_USER_SITE": site.ENABLE_USER_SITE,
        "imports": {},
        "extension_manager": {},
        "steps": {},
        "errors": [],
    }
    try:
        evidence["imports"] = {
            name: _origin_record(name) for name in PROVENANCE_MODULES
        }
        package = evidence["imports"]["isaac_audio_sensors"]
        package_origin = package.get("origin")
        if package.get("status") != "present":
            evidence["errors"].append("isaac_audio_sensors is not importable")
        elif "_vendor" not in Path(str(package_origin)).parts:
            evidence["errors"].append(
                f"isaac_audio_sensors did not resolve from _vendor: {package_origin}"
            )
        if package.get("version") != EXPECTED_VERSION:
            evidence["errors"].append(
                f"isaac_audio_sensors version is {package.get('version')!r}, "
                f"expected {EXPECTED_VERSION!r}"
            )
        if evidence["imports"]["numpy"].get("status") != "present":
            evidence["errors"].append("numpy is not importable in Kit")
        environment = evidence["environment"]
        if (
            environment["PYTHONNOUSERSITE"] != "1"
            or not environment["PYTHONPATH_absent"]
            or not environment["PYTHONHOME_absent"]
            or environment["PIP_variables_present"]
            or site.ENABLE_USER_SITE is not False
        ):
            evidence["errors"].append("subprocess environment is not fully sanitized")

        manager, manager_record = _extension_manager_state()
        evidence["extension_manager"] = manager_record
        if manager_record["status"] != "passed":
            evidence["errors"].extend(manager_record["errors"])

        stage = _run_step(evidence, "new_empty_stage", _create_empty_stage)

        from isaac_audio_sensors_omni import Extension

        extension = Extension()
        if stage is not None:
            _run_step(
                evidence, "author_array", lambda: extension.author_array(stage=stage)
            )
            _run_step(
                evidence, "author_source", lambda: extension.author_source(stage=stage)
            )

            def configure() -> Any:
                extension.controller.state.trace_enabled = False
                extension.controller.state.debug_overlay_enabled = False
                sensor = extension.configure_sensor(
                    stage=stage,
                    backend="geometry_only",
                    debug_draw=False,
                )
                if sensor is None:
                    raise RuntimeError(extension.controller.state.error_message)
                return {"backend": sensor.backend, "array_id": sensor.array_id}

            _run_step(evidence, "configure_geometry_sensor", configure)
            _run_step(evidence, "start_sensor", extension.start_sensor)
            frame = _run_step(
                evidence, "capture_frame", lambda: extension.update_sensor(force=True)
            )
            if frame is not None:
                _run_step(
                    evidence,
                    "export_latest_frame",
                    lambda: extension.export_latest_frame(
                        output_path.parent / "latest_frame.json"
                    ),
                )
            _run_step(
                evidence,
                "export_config_summary",
                lambda: extension.export_config_summary(
                    output_path.parent / "config_summary.json"
                ),
            )
            with suppress(Exception):
                extension.stop_sensor()

        def capabilities() -> dict[str, Any]:
            from isaac_audio_sensors.core.capabilities import discover_capabilities

            report = discover_capabilities().to_dict()
            by_id = {item["capability_id"]: item for item in report["fidelity_levels"]}
            for level in ("L0", "L1"):
                if by_id.get(level, {}).get("status") != "available":
                    raise RuntimeError(
                        f"required base capability {level} is unavailable"
                    )
            return report

        _run_step(evidence, "capability_report", capabilities)
        _run_step(evidence, "extension_lifecycle", lambda: _lifecycle(manager))

        if gui_mode:
            screenshot = _capture_gui_screenshot(
                output_path.parent / "gui_screenshot.png"
            )
            evidence["steps"]["gui_screenshot"] = screenshot

        required_steps = {
            "new_empty_stage",
            "author_array",
            "author_source",
            "configure_geometry_sensor",
            "start_sensor",
            "capture_frame",
            "export_latest_frame",
            "export_config_summary",
            "capability_report",
            "extension_lifecycle",
        }
        if gui_mode:
            required_steps.add("gui_screenshot")
        failed_steps = sorted(
            name
            for name in required_steps
            if evidence["steps"].get(name, {}).get("status") != "passed"
            and evidence["steps"].get(name, {}).get("status") != "captured"
        )
        if failed_steps:
            evidence["errors"].append(
                "required probe steps failed: " + ", ".join(failed_steps)
            )
    except Exception as exc:  # noqa: BLE001 - top-level evidence must survive.
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        evidence["fatal_traceback"] = traceback.format_exc()
    finally:
        evidence["status"] = "failed" if evidence["errors"] else "passed"
        _write_json(output_path, evidence)
        _request_kit_quit()
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    main()
