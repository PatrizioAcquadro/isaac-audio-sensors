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
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
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
    _record_gpu_preflight(evidence)
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
        if not evidence.get("gpu_visible"):
            raise RuntimeError("GPU is not visible to the Isaac Sim smoke runtime.")
        stage = Usd.Stage.CreateInMemory("isaac_audio_live_smoke.usda")
        _author_stage(stage)
        _update_kit_once(evidence)

        binding_cfg = IsaacAudioSceneBindingCfg(
            discovery_roots=("/World",),
            robot_base_prim_path="/World/RobotBase",
            restrict_arrays_to_robot=True,
            preferred_array="rig_front",
            required_arrays=True,
            required_sources=True,
        )
        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=0,
            stage_id="isaac_sim_live_smoke",
            robot_base_prim_path="/World/RobotBase",
            usd_time_code=0.0,
            discovery_cfg=binding_cfg.to_discovery_cfg(),
            preferred_array=binding_cfg.preferred_array,
        )
        sensor = IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            binding_cfg=binding_cfg,
            backend="geometry_only",
            timestamp_ms=0,
            usd_time_code=0.0,
            usd_time_code_scale=1.0,
            update_period_s=0.1,
            max_events=1,
            debug_draw=True,
            writer_path=args.out.with_suffix(".frames.jsonl"),
        )
        sensor.start()
        first_frame = sensor.update(sim_time_s=0.0)
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
                "semantic_discovery": True,
                "selected_array_id": sensor.array_id,
                "selected_array_preference": binding_cfg.preferred_array,
                "motion_authoring": "time_sampled_usd_xform_ops",
                "before_source_pose": _first_source_pose(first_frame),
                "after_source_pose": _first_source_pose(moved_frame),
                "before_array_pose": _array_pose(first_frame),
                "after_array_pose": _array_pose(moved_frame),
                "before_bearing_deg": (
                    first_frame.detections[0].doa.estimated_bearing_deg
                ),
                "after_bearing_deg": (
                    moved_frame.detections[0].doa.estimated_bearing_deg
                ),
                "before_stage_diagnostics": first_frame.diagnostics.get(
                    "stage_snapshot",
                    {},
                ),
                "after_stage_diagnostics": moved_frame.diagnostics.get(
                    "stage_snapshot",
                    {},
                ),
                "inactive_stage_diagnostics": inactive_frame.diagnostics.get(
                    "stage_snapshot",
                    {},
                ),
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
    robot_base = stage.DefinePrim("/World/RobotBase", "Xform")
    _set_translate_samples(
        robot_base,
        {
            "default": (0.0, 0.0, 0.0),
            0.0: (0.0, 0.0, 0.0),
            0.1: (1.0, 0.0, 0.0),
            0.5: (1.0, 0.0, 0.0),
        },
    )
    stage.DefinePrim("/World/RobotBase/ArrayMount", "Xform")
    moving_source = stage.DefinePrim("/World/MovingSource", "Xform")
    _set_translate_samples(
        moving_source,
        {
            "default": (4.0, 0.0, 0.0),
            0.0: (4.0, 0.0, 0.0),
            0.1: (0.0, 4.0, 0.0),
            0.5: (0.0, 4.0, 0.0),
        },
    )
    create_sound_prim(
        stage,
        prim_path="/World/MovingSource/Sound",
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    sound = stage.GetPrimAtPath("/World/MovingSource/Sound")
    _set_custom_attr(sound, "ias:source_id", "speaker_front")
    _set_custom_attr(sound, "ias:class_label", "Speech")
    _set_custom_attr(sound, "ias:start_time_s", 0.0)
    _set_custom_attr(sound, "ias:duration_s", 0.25)
    _set_custom_attr(sound, "ias:gain_db", 0.0)
    _set_custom_attr(sound, "ias:directivity", "omni")
    array_prim = stage.DefinePrim("/World/RobotBase/ArrayMount/AudioArray", "Xform")
    _set_translate_samples(
        array_prim,
        {
            "default": (0.0, 0.0, 0.0),
            0.0: (0.0, 0.0, 0.0),
            0.1: (0.0, 0.0, 0.0),
            0.5: (0.0, 0.0, 0.0),
        },
    )
    _set_orient_samples(
        array_prim,
        {
            "default": quaternion_from_yaw_deg(0.0),
            0.0: quaternion_from_yaw_deg(0.0),
            0.1: quaternion_from_yaw_deg(90.0),
            0.5: quaternion_from_yaw_deg(90.0),
        },
    )
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
    )
    for microphone in microphone_layout("quad_front"):
        mic_prim = stage.DefinePrim(
            f"/World/RobotBase/ArrayMount/AudioArray/{microphone.mic_id}",
            "Xform",
        )
        moved_position = (
            (0.12, 0.0, 0.0)
            if microphone.mic_id == "front"
            else microphone.relative_position_m
        )
        _set_translate_samples(
            mic_prim,
            {
                "default": microphone.relative_position_m,
                0.0: microphone.relative_position_m,
                0.1: moved_position,
                0.5: moved_position,
            },
        )
        _set_custom_attr(mic_prim, "ias:microphone_id", microphone.mic_id)
        _set_custom_attr(mic_prim, "ias:gain_db", microphone.gain_db)
    create_listener_prim(
        stage,
        prim_path="/World/RobotBase/ArrayMount/AudioArray/Listener",
        array_id="rig_front",
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


def _set_translate_samples(prim, samples) -> None:
    from pxr import Gf, Usd, UsdGeom  # type: ignore

    op = UsdGeom.Xformable(prim).AddTranslateOp()
    for time_code, position in samples.items():
        value = Gf.Vec3d(*position)
        if time_code == "default":
            op.Set(value)
        else:
            op.Set(value, Usd.TimeCode(float(time_code)))


def _set_orient_samples(prim, samples) -> None:
    from pxr import Gf, Usd, UsdGeom  # type: ignore

    op = UsdGeom.Xformable(prim).AddOrientOp()
    for time_code, quat in samples.items():
        x, y, z, w = quat
        value = Gf.Quatf(float(w), Gf.Vec3f(float(x), float(y), float(z)))
        if time_code == "default":
            op.Set(value)
        else:
            op.Set(value, Usd.TimeCode(float(time_code)))


def _set_custom_attr(prim, name: str, value: object) -> None:
    attr = prim.CreateAttribute(name, _value_type_name(value), custom=True)
    attr.Set(value)


def _value_type_name(value: object):
    from pxr import Sdf  # type: ignore

    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int) and not isinstance(value, bool):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    return Sdf.ValueTypeNames.String


def _array_pose(frame) -> dict[str, object] | None:
    if frame.array_pose is None:
        return None
    return {
        "position_m": frame.array_pose.position_m,
        "orientation_xyzw": frame.array_pose.orientation_xyzw,
        "frame": frame.array_pose.frame,
    }


def _first_source_pose(frame) -> dict[str, object] | None:
    if not frame.detections or frame.detections[0].source_pose is None:
        return None
    pose = frame.detections[0].source_pose
    return {
        "position_m": pose.position_m,
        "orientation_xyzw": pose.orientation_xyzw,
        "frame": pose.frame,
    }


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


def _record_gpu_preflight(evidence: dict[str, object]) -> None:
    try:
        import torch  # type: ignore

        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        evidence.update(
            {
                "gpu_probe": "torch.cuda",
                "gpu_visible": cuda_available and device_count > 0,
                "cuda_device_count": device_count,
                "cuda_device_names": [
                    torch.cuda.get_device_name(index) for index in range(device_count)
                ],
                "torch_version": str(getattr(torch, "__version__", "")),
            }
        )
    except Exception as exc:  # noqa: BLE001 - smoke evidence records this.
        evidence.update(
            {
                "gpu_probe": "torch.cuda",
                "gpu_visible": False,
                "gpu_probe_error": f"{type(exc).__name__}: {exc}",
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
