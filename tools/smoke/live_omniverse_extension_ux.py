"""Live Kit gate: run maintained scenarios and aggregate their results."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

from isaac_audio_sensors_omni import Extension
from kit_common import (
    _prepare_output_dir,
    _step,
)
from kit_distribution import (
    EXTENSION_ID,
    _destroy_workspace_extension_window,
    _enabled_extension_id,
    _probe_dependency_origins,
    _probe_extension_manager_metadata,
    _probe_package_origin,
    _try_disable_extension_manager,
    _try_enable_extension_manager,
)
from kit_outputs import (
    _collect_audio_output_evidence,
    _collect_omnigraph_evidence,
)
from kit_scenario import (
    _author_minimal_stage,
    _create_stage,
    _probe_export_latest_without_frame,
    _run_error_checks,
    _run_object_attach_scenario,
    _validate_attach_scenario,
)
from kit_ui import (
    _capture_advanced_error_evidence,
    _probe_ui_editable_models,
    _probe_ui_numeric_widgets,
    _probe_window_integrations,
    _push_state_to_widgets,
)
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "build/validation/isaac_audio_sensors/omniverse_extension_live_ux.json"
        ),
    )
    parser.add_argument(
        "--require-screenshot",
        action="store_true",
        help="Fail the live gate if any required viewport screenshot is unavailable.",
    )
    parser.add_argument(
        "--extension-path",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "exts" / EXTENSION_ID,
        help="Extension directory discovered by Kit.",
    )
    parser.add_argument("--geometry-library", type=Path)
    parser.add_argument("--specular-library", type=Path)
    args = parser.parse_args()
    if args.geometry_library and not args.specular_library:
        parser.error("--geometry-library requires --specular-library")
    args.out = args.out.resolve()
    args.extension_path = args.extension_path.resolve()

    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    pre_frame_config_path = args.out.with_suffix(".pre_frame.config.json")
    latest_frame_path = args.out.with_suffix(".latest_frame.json")
    replicator_dir = args.out.with_suffix(".replicator")
    screenshot_path = args.out.with_suffix(".viewport.png")
    advanced_error_screenshot_path = args.out.with_suffix(".advanced-error.png")
    flac_session_path = args.out.with_suffix(".flac-session")
    kit_audio_source_path = args.out.with_suffix(".kit-audio-source.wav")
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
        advanced_error_screenshot_path,
        kit_audio_source_path,
    )
    _prepare_output_dir(replicator_dir)
    shutil.rmtree(flac_session_path, ignore_errors=True)

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
        "advanced_error_screenshot_path": str(advanced_error_screenshot_path),
        "flac_session_path": str(flac_session_path),
        "kit_audio_source_path": str(kit_audio_source_path),
        "extension_id": EXTENSION_ID,
        "extension_path": str(args.extension_path),
        "headless": False,
        "viewport_mode": "windowed_ui",
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
        simulation_app = _ensure_isaac_runtime(evidence, headless=False)

        import omni  # type: ignore

        importlib.import_module("pxr")
        evidence["pxr_imported"] = True
        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        _record_loaded_runtime_modules(evidence)
        _record_gpu_preflight(evidence)
        stage = _create_stage(evidence)
        evidence["stage_mode"] = "omni_usd_context_stage"
        _author_minimal_stage(stage)
        _update_kit_once(evidence)

        startup_ext_id = EXTENSION_ID
        evidence["manual_extension_startup_id"] = startup_ext_id
        extension = Extension()
        extension.on_startup(startup_ext_id)
        evidence["package_origin"] = _probe_package_origin(
            Path(evidence["extension_path"])
        )
        evidence["dependency_origins"] = _probe_dependency_origins(
            Path(evidence["extension_path"])
        )

        controller = extension.controller
        controller.ext_id = startup_ext_id
        controller.state.backend = "analytic_acoustics"
        controller.state.jsonl_trace_path = str(frame_trace_path)
        controller.state.latest_frame_export_path = str(latest_frame_path)
        controller.state.config_export_path = str(config_path)
        controller.state.config_import_path = str(config_path)
        controller.state.replicator_enabled = True
        controller.state.replicator_output_dir = str(replicator_dir)
        controller.state.usd_debug_enabled = True
        _push_state_to_widgets(controller)

        evidence["ui_available"] = extension.controller.ui_available
        evidence["omnigraph"] = _collect_omnigraph_evidence(controller)
        evidence["window_integration"] = _probe_window_integrations(controller)
        evidence["extension_manager_metadata"] = _probe_extension_manager_metadata(
            Path(evidence["extension_path"]),
            extension_id=EXTENSION_ID,
        )
        evidence["ui_editable_model_probe"] = _probe_ui_editable_models(controller)
        evidence["ui_numeric_widget_probe"] = _probe_ui_numeric_widgets(controller)
        evidence["advanced_error_ui"] = _capture_advanced_error_evidence(
            controller,
            screenshot_path=advanced_error_screenshot_path,
            evidence=evidence,
        )
        evidence["export_latest_without_frame"] = _probe_export_latest_without_frame(
            controller
        )
        evidence["error_checks"] = _run_error_checks(stage)

        controller.state.config_export_path = str(pre_frame_config_path)
        _push_state_to_widgets(controller)
        _step(
            evidence,
            "export_config_summary_before_frame",
            controller.export_config_summary,
        )
        controller.state.config_export_path = str(config_path)
        _push_state_to_widgets(controller)

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

        evidence["audio_output"] = _step(
            evidence,
            "audio_output_live_qa",
            lambda: _collect_audio_output_evidence(
                controller,
                stage=stage,
                flac_destination=flac_session_path,
                source_wav_path=kit_audio_source_path,
            ),
        )
        evidence["kit_audio_mix"] = evidence["audio_output"].get(
            "kit_audio_mix",
            {"status": "failed", "reason": "audio output did not complete"},
        )

        # Kit unloads package modules on disable; finish the manual client first.
        if args.geometry_library:
            from geometry_operating import run_geometry_operating

            evidence["geometry_operating"] = _step(
                evidence,
                "geometry_sensor_to_instruments",
                lambda: run_geometry_operating(
                    controller, args.geometry_library, args.specular_library, args.out
                ),
            )
        extension.on_shutdown()
        evidence["extension_shutdown"] = "ok"
        extension = None
        evidence["manual_window_cleanup"] = _destroy_workspace_extension_window()
        if evidence["manual_window_cleanup"].get("status") == "failed":
            raise RuntimeError(
                "Could not remove the manual window: "
                f"{evidence['manual_window_cleanup']}"
            )
        evidence["kit_extension_manager"] = _try_enable_extension_manager(
            extension_id=EXTENSION_ID,
            extension_path=args.extension_path,
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
        if (
            simulation_app is not None
            and evidence.get("kit_extension_manager", {}).get("status") == "enabled"
        ):
            manager_disable = _try_disable_extension_manager(
                extension_id=_enabled_extension_id(evidence) or EXTENSION_ID,
            )
            evidence["kit_extension_manager_disable"] = manager_disable
            if manager_disable.get("status") != "disabled" and exit_code == 0:
                exit_code = 2
                evidence.update(
                    {
                        "status": "blocked",
                        "error_type": "RuntimeError",
                        "error": (
                            "Kit extension manager did not prove extension disabled: "
                            f"{manager_disable}"
                        ),
                    }
                )
        _write_evidence(args.out, evidence)
        if simulation_app is not None:
            try:
                simulation_app.close(exit_code=exit_code)
                evidence["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown diagnostic only.
                evidence["simulation_app_close_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()

    return exit_code


def _validate_live_extension_outputs(
    *,
    evidence: dict[str, Any],
) -> None:
    for probe_name in (
        "package_origin",
        "dependency_origins",
        "ui_editable_model_probe",
        "ui_numeric_widget_probe",
        "advanced_error_ui",
        "export_latest_without_frame",
        "instruments",
        "usd_debug",
    ):
        probe = evidence.get(probe_name, {})
        if probe.get("status") != "passed":
            raise RuntimeError(f"{probe_name} failed: {probe}")
    audio_output = evidence.get("audio_output", {})
    packaged = evidence.get("package_origin", {}).get("mode") == "packaged"
    allowed_audio_status = {"passed"} if packaged else {"passed", "skipped"}
    if audio_output.get("status") not in allowed_audio_status:
        raise RuntimeError(f"audio_output evidence failed: {audio_output}")
    kit_audio_mix = evidence.get("kit_audio_mix", {})
    if kit_audio_mix.get("status") != "passed":
        raise RuntimeError(f"kit_audio_mix evidence failed: {kit_audio_mix}")
    omnigraph = evidence.get("omnigraph", {})
    if omnigraph.get("status") not in {"passed", "skipped"}:
        raise RuntimeError(f"omnigraph evidence failed: {omnigraph}")
    error_checks = evidence.get("error_checks", {})
    missing_error_checks = [
        name for name, message in sorted(error_checks.items()) if not message
    ]
    if missing_error_checks:
        raise RuntimeError(
            f"Readable error checks did not record messages: {missing_error_checks}"
        )
    manager_status = evidence.get("kit_extension_manager", {})
    if manager_status.get("status") != "enabled":
        raise RuntimeError(
            f"Kit extension manager did not prove extension enabled: {manager_status}"
        )
    generic_result = evidence.get("object_attach_live_qa", {}).get("generic_scene")
    if generic_result is None:
        raise RuntimeError("Missing generic object-attach scenario evidence.")
    roundtrip_probe = generic_result.get("config_import_result", {}).get(
        "roundtrip_probe", {}
    )
    if roundtrip_probe.get("status") != "passed":
        raise RuntimeError(f"config_roundtrip_probe failed: {roundtrip_probe}")
    _validate_attach_scenario("generic_scene", generic_result)


if __name__ == "__main__":
    raise SystemExit(main())
