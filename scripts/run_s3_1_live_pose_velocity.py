#!/usr/bin/env python3
"""Run the live Isaac S3.1 teleport/no-Doppler-spike acceptance gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import traceback
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs/isaac_audio_sensors/S3/S3.1"
SUMMARY_NAME = "live_isaac_teleport_summary.json"
FRAMES_NAME = "live_isaac_teleport_frames.jsonl"
LOG_NAME = "live_isaac_teleport.log"
STAGE_NAME = "live_isaac_teleport_stage.usda"
ENVIRONMENT_NAME = "live_isaac_environment.json"

ARRAY_PRIM_PATH = "/World/AudioRig"
SOURCE_PRIM_PATH = "/World/ActiveSource"
ARRAY_ID = "rig_front"
SOURCE_ID = "speaker_front"
ARRAY_POSITION = (0.0, 0.0, 1.0)
SOURCE_PRE_POSITION = (4.0, 0.0, 1.0)
SOURCE_TELEPORT_POSITION = (7.0, 0.0, 1.0)
UPDATE_PERIOD_S = 0.05
TELEPORT_DISTANCE_M = 3.0
TELEPORT_THRESHOLD_MPS = 50.0
STALE_TIME_S = 0.5
EXTREME_DOPPLER_FACTORS = (1.0 / 8.0, 8.0)
PHASES = (
    ("pre_1", 1.00),
    ("pre_2", 1.05),
    ("teleport", 1.10),
    ("recovery_1", 1.15),
    ("recovery_2", 1.20),
)


class LivePrerequisiteError(RuntimeError):
    """A required live-runtime capability is unavailable."""


class GateAssertionError(RuntimeError):
    """The live runtime ran, but an S3.1 assertion failed."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the S3.1 live Isaac pose-velocity teleport gate."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the five spec-named live evidence artifacts.",
    )
    args = parser.parse_args()

    paths = _artifact_paths(args.out_dir)
    _initialize_artifacts(paths)
    environment = _initial_environment()
    summary: dict[str, Any] = {
        "status": "started",
        "scenario": "S3.1_live_isaac_teleport",
        "spec": "docs/development/specs/s3_motion_policies.md sections 7 and 7.1",
        "headless": True,
        "output_directory": str(args.out_dir),
        "artifacts": {name: str(path) for name, path in paths.items()},
        "source_id": SOURCE_ID,
        "array_id": ARRAY_ID,
        "backend": "tdoa_synthetic",
        "room_backend": "room_acoustics",
        "update_times_s": [time_s for _, time_s in PHASES],
        "source_pre_position_world_m": list(SOURCE_PRE_POSITION),
        "source_teleport_position_world_m": list(SOURCE_TELEPORT_POSITION),
        "teleport_distance_m": TELEPORT_DISTANCE_M,
        "normalized_motion_config": {
            "derive_velocity_from_poses": True,
            "teleport_speed_threshold_mps": TELEPORT_THRESHOLD_MPS,
            "stale_time_s": STALE_TIME_S,
            "smoothing_alpha": None,
        },
    }
    _write_json(paths["environment"], environment)
    _log(paths["log"], "gate_started", argv=sys.argv)

    simulation_app = None
    sensor = None
    stage = None
    exit_code = 2
    try:
        _record_isaacsim_preflight(environment)
        _record_gpu(environment)
        _record_nvidia_smi(environment)
        _write_json(paths["environment"], environment)

        simulation_app = _ensure_isaac_runtime(environment)
        dependencies = _load_live_dependencies()
        _record_loaded_runtime(environment, dependencies)
        _record_gpu(environment)
        _validate_runtime(environment)
        _require_room_backend(dependencies)
        _write_json(paths["environment"], environment)

        stage = dependencies["Usd"].Stage.CreateInMemory(STAGE_NAME)
        source_prim = _author_stage(stage, dependencies)
        _export_stage(stage, paths["stage"])
        _update_kit_once(environment)
        _log(paths["log"], "stage_authored", stage_path=str(paths["stage"]))

        motion = dependencies["MotionEffectsConfig"](derive_velocity_from_poses=True)
        effects = dependencies["EffectsConfig"](motion=motion)
        _require(
            motion.teleport_speed_threshold_mps == TELEPORT_THRESHOLD_MPS
            and motion.stale_time_s == STALE_TIME_S
            and motion.smoothing_alpha is None,
            f"motion defaults are not frozen S3.1 values: {motion!r}",
        )
        room = dependencies["RoomAcousticsSpec"](
            room_id="s3_1_live_room",
            dimensions_m=(10.0, 4.0, 3.0),
            absorption=0.35,
            max_order=0,
            air_absorption=False,
            ray_tracing=False,
            origin_m=(-1.0, -2.0, 0.0),
        )
        sensor = (
            dependencies["IsaacAudioArraySensor"]
            .from_stage(
                stage=stage,
                array_prim_path=ARRAY_PRIM_PATH,
                source_prim_path=SOURCE_PRIM_PATH,
                backend="tdoa_synthetic",
                update_period_s=UPDATE_PERIOD_S,
                max_events=1,
                room=room,
                effects=effects,
            )
            .start()
        )

        observations: list[dict[str, Any]] = []
        teleport_snapshot = None
        teleport_frame = None
        for phase, sim_time_s in PHASES:
            if phase == "teleport":
                _set_source_pose_both_representations(
                    source_prim,
                    SOURCE_TELEPORT_POSITION,
                    dependencies,
                )
                _update_kit_once(environment)
                _log(
                    paths["log"],
                    "source_teleported",
                    distance_m=TELEPORT_DISTANCE_M,
                    position_world_m=SOURCE_TELEPORT_POSITION,
                    sim_time_s=sim_time_s,
                )
            else:
                _update_kit_once(environment)

            raw_frame = sensor.update(
                sim_time_s=sim_time_s,
                usd_time_code=dependencies["Usd"].TimeCode.Default(),
                force=True,
            )
            snapshot = sensor._latest_scene  # noqa: SLF001 - gate evidence.
            _require(snapshot is not None, f"{phase} has no captured scene snapshot")
            frame, observation = _augment_and_observe_frame(
                raw_frame,
                snapshot=snapshot,
                phase=phase,
                sim_time_s=sim_time_s,
                dependencies=dependencies,
            )
            dependencies["append_frame_jsonl"](frame, paths["frames"])
            observations.append(observation)
            _log(paths["log"], "frame_captured", **observation)
            if phase == "teleport":
                teleport_snapshot = snapshot
                teleport_frame = frame

        _require(teleport_snapshot is not None, "teleport snapshot was not retained")
        _require(teleport_frame is not None, "teleport frame was not retained")
        room_frame, room_observation = _run_room_teleport_check(
            teleport_snapshot,
            teleport_frame=teleport_frame,
            effects=effects,
            dependencies=dependencies,
        )
        dependencies["append_frame_jsonl"](room_frame, paths["frames"])
        _log(paths["log"], "room_teleport_snapshot_rendered", **room_observation)

        assertions = _validate_scenario(
            observations,
            room_observation=room_observation,
            frame_trace_path=paths["frames"],
        )
        _export_stage(stage, paths["stage"])
        summary.update(
            {
                "status": "passed",
                "frame_count": len(observations) + 1,
                "tdoa_frame_count": len(observations),
                "room_frame_count": 1,
                "observations": observations,
                "room_teleport_observation": room_observation,
                "assertions": assertions,
            }
        )
        exit_code = 0
        _log(paths["log"], "gate_passed", assertions=assertions)
    except BaseException as exc:  # noqa: BLE001 - exact gate evidence.
        if isinstance(exc, KeyboardInterrupt):
            raise
        status = "blocked" if isinstance(exc, LivePrerequisiteError) else "failed"
        summary.update(
            {
                "status": status,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "smallest_next_fix": _smallest_next_fix(exc),
            }
        )
        _log(
            paths["log"],
            "gate_not_passed",
            status=status,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
    finally:
        if sensor is not None:
            with suppress(Exception):
                sensor.close()
        if stage is not None:
            try:
                _export_stage(stage, paths["stage"])
            except Exception as exc:  # noqa: BLE001 - best-effort failure artifact.
                summary["stage_export_close_error"] = f"{type(exc).__name__}: {exc}"
        environment["status"] = "recorded"
        environment["recorded_at_utc"] = _utc_now()
        if simulation_app is not None:
            environment["simulation_app_closed"] = False
        _write_json(paths["environment"], environment)
        summary["artifact_inventory"] = _artifact_inventory(paths, omit="summary")
        _write_json(paths["summary"], summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        sys.stdout.flush()

        if simulation_app is not None:
            try:
                simulation_app.close()
                environment["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown evidence only.
                environment["simulation_app_close_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            with suppress(Exception):
                environment["recorded_at_utc"] = _utc_now()
                _write_json(paths["environment"], environment)
                summary["artifact_inventory"] = _artifact_inventory(
                    paths, omit="summary"
                )
                _write_json(paths["summary"], summary)

    return exit_code


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "summary": output_dir / SUMMARY_NAME,
        "frames": output_dir / FRAMES_NAME,
        "log": output_dir / LOG_NAME,
        "stage": output_dir / STAGE_NAME,
        "environment": output_dir / ENVIRONMENT_NAME,
    }


def _initialize_artifacts(paths: dict[str, Path]) -> None:
    next(iter(paths.values())).parent.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        with suppress(FileNotFoundError):
            path.unlink()
    paths["frames"].write_text("", encoding="utf-8")
    paths["log"].write_text("", encoding="utf-8")
    paths["stage"].write_text(
        '#usda 1.0\n(\n    documentation = "Live stage was not authored."\n)\n',
        encoding="utf-8",
    )


def _initial_environment() -> dict[str, Any]:
    extension_manifest = ROOT / "exts/isaac_audio_sensors.omni/config/extension.toml"
    package_init = ROOT / "src/isaac_audio_sensors/__init__.py"
    repository_revision = _git_output("rev-parse", "HEAD")
    return {
        "status": "started",
        "headless": True,
        "started_at_utc": _utc_now(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "implementation": platform.python_implementation(),
        },
        "platform": platform.platform(),
        "display": {
            "DISPLAY": os.environ.get("DISPLAY"),
            "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
        },
        "repository": {
            "root": str(ROOT),
            "revision": repository_revision,
            "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
        },
        "extension": {
            "id": "isaac_audio_sensors.omni",
            "manifest": str(extension_manifest),
            "manifest_sha256": _file_sha256_or_unavailable(extension_manifest),
            "manifest_version": _manifest_version(extension_manifest),
            "repository_revision": repository_revision,
        },
        "package": {
            "name": "isaac-audio-sensors",
            "source_init": str(package_init),
            "source_init_sha256": _file_sha256_or_unavailable(package_init),
            "distribution_versions": _distribution_versions(),
        },
    }


def _record_isaacsim_preflight(environment: dict[str, Any]) -> None:
    spec = importlib.util.find_spec("isaacsim")
    if spec is None or spec.origin is None:
        environment["isaac_sim_preflight"] = {"package": "not_found"}
        return
    package_dir = Path(spec.origin).resolve().parent
    environment["isaac_sim_preflight"] = {
        "package": str(package_dir),
        "module_origin": str(spec.origin),
        "version_file": _read_first_line(package_dir / "VERSION"),
        "eula_environment_set": os.environ.get("OMNI_KIT_ACCEPT_EULA") is not None,
    }


def _record_gpu(environment: dict[str, Any]) -> None:
    try:
        import torch  # type: ignore

        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if available else 0
        environment["gpu"] = {
            "probe": "torch.cuda",
            "visible": available and count > 0,
            "device_count": count,
            "device_names": [torch.cuda.get_device_name(i) for i in range(count)],
            "torch_version": str(getattr(torch, "__version__", "unavailable")),
            "torch_cuda_version": str(getattr(torch.version, "cuda", "unavailable")),
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
        }
    except Exception as exc:  # noqa: BLE001 - prerequisite evidence.
        environment["gpu"] = {
            "probe": "torch.cuda",
            "visible": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _record_nvidia_smi(environment: dict[str, Any]) -> None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        environment["nvidia_smi"] = {"path": None, "status": "not_found"}
        return
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,uuid,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        environment["nvidia_smi"] = {
            "path": executable,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - prerequisite evidence.
        environment["nvidia_smi"] = {
            "path": executable,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _ensure_isaac_runtime(environment: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        if app is not None:
            environment["simulation_app_bootstrap"] = "attached_existing_kit_app"
            _record_kit(environment, app)
            return None
    except Exception as exc:  # noqa: BLE001 - bootstrap diagnostic.
        environment["kit_prebootstrap_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from isaacsim import SimulationApp  # type: ignore

        simulation_app = SimulationApp({"headless": True})
    except Exception as exc:  # noqa: BLE001 - missing live runtime is blocked.
        raise LivePrerequisiteError(
            "Could not start isaacsim.SimulationApp in headless mode."
        ) from exc

    try:
        import omni.kit.app  # type: ignore
    except ImportError as exc:
        simulation_app.close()
        raise LivePrerequisiteError(
            "SimulationApp started, but omni.kit.app could not be imported."
        ) from exc

    app = omni.kit.app.get_app()
    if app is None:
        simulation_app.close()
        raise LivePrerequisiteError(
            "SimulationApp started, but omni.kit.app.get_app() is unavailable."
        )
    environment["simulation_app_bootstrap"] = "created"
    _record_kit(environment, app)
    return simulation_app


def _load_live_dependencies() -> dict[str, Any]:
    try:
        from dataclasses import replace

        import omni  # type: ignore
        from pxr import Gf, Usd  # type: ignore

        from isaac_audio_sensors import __version__
        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )
        from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
        from isaac_audio_sensors.core.io.traces import append_frame_jsonl
        from isaac_audio_sensors.core.microphone_array import microphone_layout
        from isaac_audio_sensors.core.types import AudioTimeWindow, RoomAcousticsSpec
        from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
        from isaac_audio_sensors.isaac.stage_audio import (
            attach_microphone_array_attrs,
            attach_sound_source_attrs,
            create_sound_prim,
            set_prim_xform_pose,
        )
    except ImportError as exc:
        raise LivePrerequisiteError(
            "Isaac/USD or isaac_audio_sensors imports are incomplete in this runtime."
        ) from exc

    return {
        "AudioTimeWindow": AudioTimeWindow,
        "EffectsConfig": EffectsConfig,
        "Gf": Gf,
        "IsaacAudioArraySensor": IsaacAudioArraySensor,
        "MotionEffectsConfig": MotionEffectsConfig,
        "RoomAcousticsBackend": RoomAcousticsBackend,
        "RoomAcousticsSpec": RoomAcousticsSpec,
        "Usd": Usd,
        "__version__": __version__,
        "append_frame_jsonl": append_frame_jsonl,
        "attach_microphone_array_attrs": attach_microphone_array_attrs,
        "attach_sound_source_attrs": attach_sound_source_attrs,
        "create_sound_prim": create_sound_prim,
        "microphone_layout": microphone_layout,
        "omni": omni,
        "replace": replace,
        "set_prim_xform_pose": set_prim_xform_pose,
    }


def _record_loaded_runtime(
    environment: dict[str, Any], dependencies: dict[str, Any]
) -> None:
    omni = dependencies["omni"]
    Usd = dependencies["Usd"]
    package_module = sys.modules["isaac_audio_sensors"]
    environment["isaac_sim_loaded"] = {
        name: _module_identity(name) for name in ("isaacsim", "omni", "pxr")
    }
    environment["usd_version"] = str(Usd.GetVersion())
    environment["omni_module"] = str(getattr(omni, "__file__", "built-in"))
    environment["package"].update(
        {
            "version": dependencies["__version__"],
            "module_file": str(getattr(package_module, "__file__", "unavailable")),
            "repository_revision": environment["repository"]["revision"],
        }
    )


def _record_kit(environment: dict[str, Any], app: Any) -> None:
    kit: dict[str, Any] = {"available": True}
    for method_name in ("get_app_version", "get_build_version", "get_version"):
        method = getattr(app, method_name, None)
        if not callable(method):
            kit[method_name] = "unavailable"
            continue
        try:
            kit[method_name] = str(method())
        except Exception as exc:  # noqa: BLE001 - identity evidence only.
            kit[method_name] = f"unavailable: {type(exc).__name__}: {exc}"
    environment["kit"] = kit


def _validate_runtime(environment: dict[str, Any]) -> None:
    if not environment.get("kit", {}).get("available"):
        raise LivePrerequisiteError("No running Kit app is available.")
    if not environment.get("gpu", {}).get("visible"):
        raise LivePrerequisiteError("No CUDA GPU is visible to the Isaac runtime.")


def _require_room_backend(dependencies: dict[str, Any]) -> None:
    backend = dependencies["RoomAcousticsBackend"]
    if not backend.is_available():
        raise LivePrerequisiteError(
            "pyroomacoustics is unavailable; the S3.1 live room no-render check "
            "cannot be skipped."
        )


def _author_stage(stage: Any, dependencies: dict[str, Any]) -> Any:
    world = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(world)
    stage.SetStartTimeCode(PHASES[0][1])
    stage.SetEndTimeCode(PHASES[-1][1])
    stage.SetTimeCodesPerSecond(20.0)

    microphones = dependencies["microphone_layout"]("quad_front")
    _require(len(microphones) == 4, "quad_front did not resolve exactly four mics")
    array_prim = stage.DefinePrim(ARRAY_PRIM_PATH, "Xform")
    dependencies["attach_microphone_array_attrs"](
        array_prim,
        array_id=ARRAY_ID,
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=ARRAY_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphone_relative_offsets_m=tuple(
            microphone.relative_position_m for microphone in microphones
        ),
        microphone_ids=tuple(microphone.mic_id for microphone in microphones),
    )
    dependencies["set_prim_xform_pose"](
        array_prim,
        position=ARRAY_POSITION,
        orientation=(0.0, 0.0, 0.0, 1.0),
    )

    dependencies["create_sound_prim"](
        stage,
        prim_path=SOURCE_PRIM_PATH,
        audio_asset_path="generated://deterministic_pulse",
        spatial=True,
        loop=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    source_prim = stage.GetPrimAtPath(SOURCE_PRIM_PATH)
    dependencies["attach_sound_source_attrs"](
        source_prim,
        source_id=SOURCE_ID,
        class_label="Speech",
        position_world=SOURCE_PRE_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        audio_asset_path="generated://deterministic_pulse",
        start_time_s=0.0,
        gain_db=0.0,
        directivity="omni",
    )
    dependencies["set_prim_xform_pose"](
        source_prim,
        position=SOURCE_PRE_POSITION,
        orientation=(0.0, 0.0, 0.0, 1.0),
    )
    return source_prim


def _set_source_pose_both_representations(
    prim: Any,
    position: tuple[float, float, float],
    dependencies: dict[str, Any],
) -> None:
    attr = prim.GetAttribute("ias:position_world")
    _require(attr.IsValid(), "source has no ias:position_world attribute")
    attr.Set(dependencies["Gf"].Vec3d(*position))
    dependencies["set_prim_xform_pose"](prim, position=position)


def _augment_and_observe_frame(
    frame: Any,
    *,
    snapshot: Any,
    phase: str,
    sim_time_s: float,
    dependencies: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    source = next(
        source for source in snapshot.sources if source.source_id == SOURCE_ID
    )
    array = snapshot.array_by_id(ARRAY_ID)
    detection = next(
        detection for detection in frame.detections if detection.source_id == SOURCE_ID
    )
    velocity_source = frame.diagnostics["motion"]["velocity_source"][SOURCE_ID]
    gate_diagnostics = {
        "phase": phase,
        "sim_time_s": sim_time_s,
        "source_position_world_m": list(source.position_world),
        "array_position_world_m": list(array.position_world),
        "microphone_count": len(array.microphones),
        "snapshot_source_velocity_world_mps": (
            None
            if source.velocity_world_mps is None
            else list(source.velocity_world_mps)
        ),
        "snapshot_array_velocity_world_mps": (
            None if array.velocity_world_mps is None else list(array.velocity_world_mps)
        ),
    }
    augmented = dependencies["replace"](
        frame,
        diagnostics={**frame.diagnostics, "s3_1_live": gate_diagnostics},
    )
    observation = {
        **gate_diagnostics,
        "frame_id": frame.frame_id,
        "backend_id": frame.backend_id,
        "source_velocity_source": velocity_source,
        "doppler_factor": detection.diagnostics.get("doppler_factor"),
        "per_mic_doppler_factor": detection.diagnostics.get(
            "per_mic_doppler_factor", {}
        ),
        "doppler_waveform_rendered": detection.diagnostics.get(
            "doppler_waveform_rendered"
        ),
    }
    return augmented, observation


def _run_room_teleport_check(
    snapshot: Any,
    *,
    teleport_frame: Any,
    effects: Any,
    dependencies: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    sensor = snapshot.array_by_id(ARRAY_ID)
    window = dependencies["AudioTimeWindow"](
        start_time_s=1.10,
        end_time_s=1.15,
        timestamp_ms=1_100,
        sample_rate_hz=sensor.sample_rate_hz,
        frame_index=2,
        max_events=1,
    )
    frame = dependencies["RoomAcousticsBackend"](effects=effects).simulate(
        snapshot, sensor, window
    )
    detection = next(
        detection for detection in frame.detections if detection.source_id == SOURCE_ID
    )
    observation = {
        "phase": "teleport_room_snapshot",
        "frame_id": frame.frame_id,
        "backend_id": frame.backend_id,
        "source_velocity_source": teleport_frame.diagnostics["motion"][
            "velocity_source"
        ][SOURCE_ID],
        "snapshot_source_velocity_world_mps": None,
        "doppler_factor": detection.diagnostics.get("doppler_factor"),
        "doppler_waveform_rendered": detection.diagnostics.get(
            "doppler_waveform_rendered"
        ),
    }
    augmented = dependencies["replace"](
        frame,
        provenance="room_acoustics",
        diagnostics={
            **frame.diagnostics,
            "motion": teleport_frame.diagnostics["motion"],
            "s3_1_live": observation,
        },
    )
    return augmented, observation


def _validate_scenario(
    observations: list[dict[str, Any]],
    *,
    room_observation: dict[str, Any],
    frame_trace_path: Path,
) -> dict[str, bool]:
    times = [float(observation["sim_time_s"]) for observation in observations]
    monotonic_spacing = all(
        later > earlier
        and math.isclose(later - earlier, UPDATE_PERIOD_S, abs_tol=1e-12)
        for earlier, later in zip(times, times[1:], strict=False)
    )
    _require(monotonic_spacing, f"updates are not monotonic 0.05 s steps: {times}")
    _require(len(observations) == 5, "the gate did not retain exactly five live frames")
    _require(
        all(item["microphone_count"] == 4 for item in observations),
        "a live frame did not resolve exactly four microphones",
    )
    _require(
        all(
            item["array_position_world_m"] == list(ARRAY_POSITION)
            for item in observations
        ),
        "the microphone array did not remain static",
    )

    by_phase = {str(item["phase"]): item for item in observations}
    displacement = math.dist(
        by_phase["pre_2"]["source_position_world_m"],
        by_phase["teleport"]["source_position_world_m"],
    )
    _require(displacement == TELEPORT_DISTANCE_M, f"teleport was {displacement!r} m")
    teleport = by_phase["teleport"]
    _require(
        teleport["source_velocity_source"] == "none:teleport",
        f"teleport policy tag is {teleport['source_velocity_source']!r}",
    )
    _require(
        teleport["snapshot_source_velocity_world_mps"] is None,
        "teleport snapshot velocity is present instead of absent",
    )
    _require(
        teleport["doppler_factor"] == 1.0,
        f"teleport Doppler factor is {teleport['doppler_factor']!r}",
    )
    _require(
        set(teleport["per_mic_doppler_factor"].values()) == {1.0}
        and len(teleport["per_mic_doppler_factor"]) == 4,
        "teleport per-microphone Doppler factors are not exactly four unity values",
    )
    _require(
        teleport["doppler_waveform_rendered"] is False,
        "TDOA teleport frame claims a rendered Doppler shift",
    )
    _require(
        room_observation["source_velocity_source"] == "none:teleport"
        and room_observation["snapshot_source_velocity_world_mps"] is None
        and room_observation["doppler_factor"] == 1.0
        and room_observation["doppler_waveform_rendered"] is False,
        f"room teleport no-render assertion failed: {room_observation!r}",
    )
    _require(
        by_phase["recovery_1"]["source_velocity_source"] == "derived",
        "first recovery frame did not derive from the teleport anchor",
    )

    serialized_frames = [
        json.loads(line)
        for line in frame_trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _require(
        len(serialized_frames) == 6,
        "JSONL did not retain five live plus room frame",
    )
    _require(
        not any(_contains_nonfinite(frame) for frame in serialized_frames),
        "a retained frame contains NaN or infinity",
    )
    factors = [
        float(value)
        for observation in observations
        for value in (
            observation["doppler_factor"],
            *observation["per_mic_doppler_factor"].values(),
        )
    ] + [float(room_observation["doppler_factor"])]
    _require(
        all(factor not in EXTREME_DOPPLER_FACTORS for factor in factors),
        f"an extreme Doppler clamp factor was emitted: {factors!r}",
    )
    return {
        "strictly_monotonic_0_05_s_updates": True,
        "one_continuously_active_source": True,
        "static_four_microphone_array": True,
        "exact_3_0_m_translation": True,
        "teleport_tag_none_teleport": True,
        "teleport_snapshot_velocity_absent": True,
        "tdoa_central_doppler_exactly_1_0": True,
        "tdoa_per_mic_doppler_exactly_1_0": True,
        "tdoa_doppler_waveform_not_rendered": True,
        "room_doppler_exactly_1_0": True,
        "room_doppler_waveform_not_rendered": True,
        "recovery_derived": True,
        "no_nonfinite_frame_values": True,
        "no_extreme_clamp_factor": True,
    }


def _contains_nonfinite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(
            _contains_nonfinite(item)
            for key, item in value.items()
            # USD serializes Usd.TimeCode.Default() as NaN; the frozen
            # stage-snapshot diagnostics record it under time_code keys.
            if key != "time_code"
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _update_kit_once(environment: dict[str, Any]) -> None:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    if app is None or not hasattr(app, "update"):
        raise LivePrerequisiteError("Kit app update() is unavailable.")
    app.update()
    environment["kit_update_called"] = True


def _export_stage(stage: Any, path: Path) -> None:
    if not stage.GetRootLayer().Export(str(path.resolve())):
        raise RuntimeError(f"USD root layer export failed for {path}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateAssertionError(message)


def _artifact_inventory(paths: dict[str, Path], *, omit: str) -> dict[str, Any]:
    return {
        name: {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": _file_sha256_or_unavailable(path),
        }
        for name, path in paths.items()
        if name != omit
    }


def _log(path: Path, event: str, **fields: Any) -> None:
    record = {"timestamp_utc": _utc_now(), "event": event, **fields}
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        output.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _module_identity(module_name: str) -> dict[str, str]:
    module = sys.modules.get(module_name)
    return {
        "version": str(getattr(module, "__version__", "unavailable")),
        "file": str(getattr(module, "__file__", "built-in")),
    }


def _distribution_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("isaac-audio-sensors", "isaacsim", "isaac-sim", "numpy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    return versions


def _manifest_version(path: Path) -> str:
    if not path.is_file():
        return "unavailable"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"')
    return "unavailable"


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return completed.stdout.strip()
    except Exception as exc:  # noqa: BLE001 - environment evidence only.
        return f"unavailable: {type(exc).__name__}: {exc}"


def _file_sha256_or_unavailable(path: Path) -> str:
    if not path.is_file():
        return "unavailable"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_first_line(path: Path) -> str:
    if not path.is_file():
        return ""
    with suppress(OSError, UnicodeDecodeError, IndexError):
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    return ""


def _smallest_next_fix(exc: BaseException) -> str:
    message = str(exc)
    if "SimulationApp" in message or "Isaac/USD" in message:
        return "Run the target with ISAAC_SIM_COMMAND set to Isaac Sim Python."
    if "CUDA GPU" in message:
        return "Expose an NVIDIA GPU and CUDA driver to the Isaac Sim runtime."
    if "pyroomacoustics" in message:
        return "Install the supported room-acoustics dependency in Isaac Sim Python."
    return "Inspect live_isaac_teleport.log and rerun the exact live target."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
