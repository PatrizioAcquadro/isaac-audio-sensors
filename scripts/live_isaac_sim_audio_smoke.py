"""Live Isaac Sim smoke validation for isaac_audio_sensors."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    create_listener_prim,
    create_sound_prim,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/isaac_sim_live_smoke.json"),
    )
    args = parser.parse_args()
    evidence: dict[str, object] = {
        "python_executable": sys.executable,
        "argv": sys.argv,
        "status": "started",
    }
    _record_isaacsim_preflight(evidence)
    simulation_app = None
    try:
        try:
            import omni  # type: ignore
            from pxr import Usd  # type: ignore
        except ModuleNotFoundError:
            from isaacsim import SimulationApp  # type: ignore

            simulation_app = SimulationApp({"headless": True})
            evidence["simulation_app_bootstrap"] = "created"
            import omni  # type: ignore
            from pxr import Usd  # type: ignore

        evidence["pxr_imported"] = True
        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        stage = Usd.Stage.CreateInMemory("isaac_audio_live_smoke.usda")
        _author_stage(stage)
        _update_kit_once(evidence)

        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=0,
            stage_id="isaac_sim_live_smoke",
            array_prim_path="/World/Rig/AudioArray",
        )
        sensor = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path="/World/Rig/AudioArray",
            backend="geometry_only",
            timestamp_ms=0,
            update_period_s=0.1,
            max_events=1,
            debug_draw=True,
            writer_path=args.out.with_suffix(".frames.jsonl"),
        )
        sensor.start()
        first_frame = sensor.update(sim_time_s=0.0)
        _move_authored_stage(stage)
        _update_kit_once(evidence)
        moved_frame = sensor.update(sim_time_s=0.1)
        inactive_frame = sensor.update(sim_time_s=0.5)
        sensor.close()
        evidence.update(
            {
                "status": "passed",
                "stage_id": snapshot.stage_id,
                "source_count": len(snapshot.sources),
                "array_count": len(snapshot.arrays),
                "microphone_count": len(snapshot.arrays[0].microphones),
                "first_frame": frame_to_trace_dict(first_frame),
                "moved_frame": frame_to_trace_dict(moved_frame),
                "inactive_frame": frame_to_trace_dict(inactive_frame),
                "movement_changed_bearing": (
                    first_frame.detections[0].doa.estimated_bearing_deg
                    != moved_frame.detections[0].doa.estimated_bearing_deg
                ),
                "inactive_detection_count": len(inactive_frame.detections),
                "debug_primitive_count": len(sensor.latest_debug_primitives),
                "jsonl_writer_path": str(args.out.with_suffix(".frames.jsonl")),
            }
        )
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()
    except BaseException as exc:  # noqa: BLE001 - smoke evidence records exact error.
        if isinstance(exc, KeyboardInterrupt):
            raise
        evidence.update(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 2
    finally:
        if simulation_app is not None:
            try:
                simulation_app.close()
            except Exception as exc:  # noqa: BLE001 - shutdown diagnostic only.
                evidence["simulation_app_close_error"] = f"{type(exc).__name__}: {exc}"

    _write_evidence(args.out, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


def _author_stage(stage) -> None:
    stage.DefinePrim("/World", "Xform")
    stage.DefinePrim("/World/Sources", "Xform")
    stage.DefinePrim("/World/Rig", "Xform")
    create_sound_prim(
        stage,
        prim_path="/World/Sources/SpeakerFront/Sound",
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    sound = stage.GetPrimAtPath("/World/Sources/SpeakerFront/Sound")
    attach_sound_source_attrs(
        sound,
        source_id="speaker_front",
        class_label="Speech",
        position_world=(4.0, 0.0, 0.0),
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )
    array_prim = stage.DefinePrim("/World/Rig/AudioArray", "Xform")
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
    )
    for microphone in microphone_layout("quad_front"):
        mic_prim = stage.DefinePrim(
            f"/World/Rig/AudioArray/{microphone.mic_id}",
            "Xform",
        )
        attach_microphone_attrs(
            mic_prim,
            mic_id=microphone.mic_id,
            relative_position_m=microphone.relative_position_m,
            gain_db=microphone.gain_db,
        )
    create_listener_prim(
        stage,
        prim_path="/World/Rig/AudioArray/Listener",
        array_id="rig_front",
    )


def _move_authored_stage(stage) -> None:
    sound = stage.GetPrimAtPath("/World/Sources/SpeakerFront/Sound")
    attach_sound_source_attrs(
        sound,
        source_id="speaker_front",
        class_label="Speech",
        position_world=(0.0, 4.0, 0.0),
        start_time_s=0.0,
        duration_s=0.25,
        gain_db=0.0,
    )
    array_prim = stage.GetPrimAtPath("/World/Rig/AudioArray")
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
    )


def _update_kit_once(evidence: dict[str, object]) -> None:
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        if app is not None and hasattr(app, "update"):
            app.update()
            evidence["kit_frame_update"] = "called"
            return
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        evidence["kit_frame_update_error"] = f"{type(exc).__name__}: {exc}"
        return
    evidence["kit_frame_update"] = "unavailable"


def _record_isaacsim_preflight(evidence: dict[str, object]) -> None:
    spec = importlib.util.find_spec("isaacsim")
    if spec is None or spec.origin is None:
        evidence["isaacsim_package"] = "not_found"
        return

    package_dir = Path(spec.origin).resolve().parent
    kit_dir = package_dir / "kit"
    eula_path = kit_dir / "EULA_ACCEPTED"
    env_value = os.environ.get("OMNI_KIT_ACCEPT_EULA")
    evidence.update(
        {
            "isaacsim_package": str(package_dir),
            "isaacsim_version_file": _read_first_line(package_dir / "VERSION"),
            "omni_kit_accept_eula_env_set": env_value is not None,
            "omni_kit_accept_eula_env_truthy": (env_value or "").lower()
            in {"y", "yes", "1"},
            "eula_accepted_file": str(eula_path),
            "eula_accepted_file_exists": eula_path.is_file(),
            "eula_accepted_file_truthy": _read_first_line(eula_path).lower()
            in {"y", "yes", "1"},
            "eula_preflight_note": (
                "Local Isaac Sim kit_app.py checks OMNI_KIT_ACCEPT_EULA or "
                "kit/EULA_ACCEPTED before prompting."
            ),
        }
    )


def _read_first_line(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, UnicodeDecodeError, IndexError):
        return ""


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
