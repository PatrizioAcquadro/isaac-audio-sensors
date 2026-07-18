#!/usr/bin/env python3
"""Live Isaac Sim gate for GUI/headless guided-session semantic parity."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from compare_gui_headless_sessions import compare_sessions
from isaac_audio_sensors_omni import Extension
from live_endurance_capture_gate import (
    DEMO_CONFIG,
    _author_demo_scene,
    _bind_demo_room,
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
    _create_stage,
    _enabled_extension_id,
    _try_enable_extension_manager,
)

from isaac_audio_sensors.core.config import load_audio_config
from isaac_audio_sensors.core.dataset import validate_dataset
from isaac_audio_sensors.isaac.extension_ui import (
    CurrentStageContext,
    ExtensionController,
)
from isaac_audio_sensors.isaac.headless_workflow import HeadlessGuidedSession

DEFAULT_ROOT = Path("outputs/isaac_audio_sensors/S2/S2.8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_ROOT / "parity_gate.json")
    parser.add_argument("--frames", type=int, default=20)
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")

    root = args.out.parent
    config_path = root / "normalized_config.json"
    gui_session = root / "gui_recording_session"
    headless_session = root / "headless_recording_session"
    gui_export = root / "gui_exported_session"
    headless_export = root / "headless_exported_session"
    waveform_dir = root / "waveforms"
    root.mkdir(parents=True, exist_ok=True)
    for path in (
        gui_session,
        headless_session,
        gui_export,
        headless_export,
        waveform_dir,
    ):
        _remove_tree(path)
    for path in (args.out, config_path):
        if path.exists():
            path.unlink()

    evidence: dict[str, Any] = {
        "status": "started",
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "frames_requested": args.frames,
        "both_session_paths": {
            "gui": str(gui_export),
            "headless": str(headless_export),
        },
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
            stage = Usd.Stage.CreateInMemory("headless_parity_gate.usda")
            stage_mode = "pxr_usd_in_memory_fallback"
        evidence["stage_mode"] = stage_mode
        _author_minimal_stage(stage)
        _update_kit_once(evidence)

        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )

        if not RoomAcousticsBackend.is_available():
            raise RuntimeError(
                "S2.8 requires the real room_acoustics waveform backend; "
                "backend substitution is forbidden."
            )
        config = load_audio_config(DEMO_CONFIG)
        scene_adaptation = _room_scene_adaptation(config)

        extension = Extension()
        extension.on_startup(_enabled_extension_id(evidence) or EXTENSION_ID)
        gui_controller = extension.controller
        gui_controller.stage_context_provider = lambda: CurrentStageContext(stage, ())
        if (
            not extension.ui_available
            or getattr(gui_controller, "_ui_window", None) is None
        ):
            raise RuntimeError(
                "The real omni.ui guided extension window was unavailable."
            )

        _author_demo_scene(
            gui_controller,
            stage,
            config,
            "room_acoustics",
            scene_adaptation,
        )
        gui_controller.state.waveform_dir = str(waveform_dir.resolve())
        gui_controller.state.guided_dataset_id = "guided_headless_parity"
        gui_controller.state.guided_shard_max_frames = 7
        gui_controller.state.guided_record_aligned = False
        gui_controller.state.guided_scene_id = "parity_scene"
        gui_controller.state.guided_environment_id = "parity_environment"
        gui_controller.state.guided_split_group = "parity_scene"
        gui_controller.state.guided_session_seed = 28
        gui_controller.state.trace_enabled = False
        if gui_controller.export_config_summary(config_path) is None:
            raise RuntimeError("Could not write the normalized parity configuration.")
        evidence["config"] = {
            "path": str(config_path),
            "payload": json.loads(config_path.read_text(encoding="utf-8")),
        }
        evidence["waveform_backend"] = {
            "backend_id": "room_acoustics",
            "substitution": None,
            "waveform_dir": str(waveform_dir.resolve()),
            "scene_adaptation": scene_adaptation,
        }

        gui_summary = _run_gui_controller(
            gui_controller,
            config_path=config_path,
            session_dir=gui_session,
            export_dir=gui_export,
            frames=args.frames,
        )
        period = float(gui_controller.state.update_period_s)
        headless_controller = ExtensionController(
            stage_context_provider=lambda: CurrentStageContext(stage, ())
        )
        _bind_demo_room(headless_controller, config)
        headless = HeadlessGuidedSession(
            controller=headless_controller,
            frame_stepper=lambda controller, index: _capture_at_sim_time(
                controller,
                index * period,
            ),
        )
        headless_summary = headless.run_from_config(
            config_path,
            session_dir=headless_session,
            export_dir=headless_export,
            frames=args.frames,
        )
        semantic_diff = compare_sessions(gui_export, headless_export)
        evidence["semantic_diff"] = semantic_diff
        evidence["validator_summaries"] = {
            "gui": validate_dataset(gui_export).to_dict(),
            "headless": validate_dataset(headless_export).to_dict(),
        }
        evidence["recording_stats"] = {
            "gui": gui_summary["recording_stats"],
            "headless": headless_summary["recording_stats"],
        }
        evidence["gui_summary"] = gui_summary
        evidence["headless_summary"] = headless_summary
        if not semantic_diff["equal"]:
            raise RuntimeError(
                f"GUI/headless semantic mismatch: "
                f"{semantic_diff['difference_count']} difference(s)"
            )
        audio = semantic_diff["audio_parity"]
        expected_ranges = semantic_diff["frame_count"]["left"]
        if not (
            expected_ranges > 0
            and audio["ranges_compared"] == expected_ranges
            and audio["all_ranges_nonempty"]
            and audio["nonzero_audio"]
            and audio["exact"]
        ):
            raise RuntimeError(f"GUI/headless audio acceptance failed: {audio}")
        for surface, report in evidence["validator_summaries"].items():
            if report["error_count"] != 0:
                raise RuntimeError(
                    f"{surface} exported dataset is not validator-clean: {report}"
                )
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - live evidence retains blockers.
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
                evidence["simulation_app_close_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()
    return exit_code


def _run_gui_controller(
    controller: Any,
    *,
    config_path: Path,
    session_dir: Path,
    export_dir: Path,
    frames: int,
) -> dict[str, Any]:
    if controller.import_config_summary(config_path) is None:
        raise RuntimeError("GUI path could not import the normalized configuration.")
    if not controller.guided_advance():
        raise RuntimeError("GUI path could not enter Validate.")
    validation = controller.guided_validate()
    if not validation.ok:
        raise RuntimeError(f"GUI path validation failed: {validation}")
    if controller.guided_start_run() is None:
        raise RuntimeError("GUI path could not start Run.")
    _capture_at_sim_time(controller, 0.0)
    if not controller.guided_advance() or not controller.guided_mark_inspected():
        raise RuntimeError("GUI path could not complete Inspect.")
    if not controller.guided_advance():
        raise RuntimeError("GUI path could not enter Record.")
    state = controller.state
    if controller.guided_start_recording(
        session_dir,
        state.guided_dataset_id,
        state.guided_shard_max_frames,
        state.guided_record_aligned,
        scene_id=state.guided_scene_id,
        environment_id=state.guided_environment_id,
        split_group=state.guided_split_group,
        session_seed=state.guided_session_seed,
    ) is None:
        raise RuntimeError("GUI path could not start recording.")
    for index in range(frames):
        _capture_at_sim_time(controller, (index + 1) * state.update_period_s)
    if controller.guided_stop_recording() is None:
        raise RuntimeError("GUI path could not finalize recording.")
    if controller.guided_export(export_dir) is None:
        raise RuntimeError("GUI path could not export the session.")
    summary = {
        "recording_stats": asdict(controller.guided_recording_status),
        "export_status": asdict(controller.guided_export_status),
        "export_path": str(export_dir),
    }
    controller.guided_stop_run()
    controller.close_sensor()
    return summary


def _capture_at_sim_time(controller: Any, sim_time_s: float) -> Any:
    sensor = controller.sensor
    if sensor is None:
        raise RuntimeError("Guided sensor is unavailable during parity capture.")
    frame = sensor.update(sim_time_s=sim_time_s, force=True)
    controller._record_latest_frame(frame)
    return frame


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


if __name__ == "__main__":
    raise SystemExit(main())
