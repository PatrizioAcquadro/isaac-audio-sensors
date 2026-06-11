"""Live Isaac Sim occlusion gate: a wall attenuates RMS and flags detections.

Authors a real USD stage in the omni.usd context with a microphone array, a
sound source, and a collider wall. With the wall aside, the sensor sees a
clear direct path; with the wall between source and array, PhysX raycast
occlusion must attenuate per-mic RMS by the configured attenuation and set
the detection ``occluded`` flag. Authoring ``ias:transmission_loss_db`` on
the wall must change the measured attenuation to the material value, and a
sensor bound with ``rediscover_each_update=True`` must run full discovery on
every update. The gate also records live-path cache counters and captures a
viewport screenshot with the occlusion-colored bearing-ray overlay.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_sound_source_attrs,
    create_sound_prim,
)
from isaac_audio_sensors.isaac.viz.overlays import debug_primitives_to_dicts

ARRAY_PRIM_PATH = "/World/AudioRig/AudioArray"
SOURCE_PRIM_PATH = "/World/Sources/SpeakerA"
WALL_PRIM_PATH = "/World/Wall"
GATE_CAMERA_PRIM_PATH = "/World/GateCamera"
ARRAY_POSITION = (0.0, 0.0, 1.0)
SOURCE_POSITION = (4.0, 0.0, 1.0)
WALL_BLOCKING_POSITION = (2.0, 0.0, 1.0)
WALL_CLEAR_POSITION = (2.0, 10.0, 1.0)
WALL_SCALE = (0.2, 4.0, 3.0)
OCCLUSION_MAX_ATTENUATION_DB = 20.0
MATERIAL_WALL_TRANSMISSION_DB = 12.0
ATTENUATION_TOLERANCE_DB = 0.5
SETTLE_UPDATE_COUNT = 12
POLICY_UPDATE_COUNT = 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json"),
    )
    args = parser.parse_args()
    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    screenshot_path = args.out.with_suffix(".viewport.png")
    for path in (args.out, frame_trace_path, config_path, screenshot_path):
        with suppress(FileNotFoundError):
            path.unlink()

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "headless": True,
        "evidence_path": str(args.out),
        "frame_trace_path": str(frame_trace_path),
        "config_path": str(config_path),
        "screenshot_path": str(screenshot_path),
        "occlusion_max_attenuation_db": OCCLUSION_MAX_ATTENUATION_DB,
        "attenuation_tolerance_db": ATTENUATION_TOLERANCE_DB,
    }
    simulation_app = None
    exit_code = 0

    try:
        simulation_app = _ensure_isaac_runtime(evidence)

        import omni.timeline  # type: ignore
        import omni.usd  # type: ignore

        usd_context = omni.usd.get_context()
        usd_context.new_stage()
        stage = usd_context.get_stage()
        if stage is None:
            raise RuntimeError("omni.usd context has no stage after new_stage().")
        wall_translate_op = _author_stage(stage)
        _write_config_snapshot(config_path)
        evidence["stage_authored"] = True

        timeline = omni.timeline.get_timeline_interface()
        timeline.play()
        _update_app(SETTLE_UPDATE_COUNT)
        evidence["timeline_playing"] = True

        sensor = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            backend="geometry_only",
            update_period_s=0.05,
            debug_draw=True,
            occlusion_enabled=True,
            occlusion_max_attenuation_db=OCCLUSION_MAX_ATTENUATION_DB,
            writer_path=frame_trace_path,
        ).start()

        clear_frame = sensor.update(sim_time_s=0.0, force=True)
        evidence["clear_phase"] = _phase_evidence(clear_frame)
        _require(
            clear_frame.detections,
            "clear phase produced no detections",
        )
        clear_detection = clear_frame.detections[0]
        _require(
            clear_detection.occluded is False,
            "clear phase detection is unexpectedly occluded",
        )
        clear_occlusion = clear_detection.diagnostics.get("occlusion")
        _require(
            clear_occlusion is not None and clear_occlusion["occlusion_factor"] == 0.0,
            "clear phase occlusion was not computed with factor 0.0: "
            f"{clear_occlusion!r}",
        )

        from pxr import Gf  # type: ignore

        wall_translate_op.Set(Gf.Vec3d(*WALL_BLOCKING_POSITION))
        _update_app(SETTLE_UPDATE_COUNT)

        walled_frame = sensor.update(sim_time_s=0.2, force=True)
        final_frame = sensor.update(sim_time_s=0.4, force=True)
        evidence["walled_phase"] = _phase_evidence(walled_frame)
        walled_detection = walled_frame.detections[0]
        _require(
            walled_detection.occluded is True,
            "walled phase detection is not flagged occluded",
        )
        walled_occlusion = walled_detection.diagnostics["occlusion"]
        _require(
            all(walled_occlusion["per_mic_blocked"].values()),
            "walled phase did not block every source-to-mic ray: "
            f"{walled_occlusion['per_mic_blocked']!r}",
        )
        _require(
            WALL_PRIM_PATH in walled_occlusion["hit_prim_paths"],
            "wall prim is not among occlusion hit paths: "
            f"{walled_occlusion['hit_prim_paths']!r}",
        )

        measured = _measured_attenuation_db(clear_detection, walled_detection)
        evidence["measured_attenuation_db"] = measured
        for mic_id, attenuation_db in measured.items():
            _require(
                abs(attenuation_db - OCCLUSION_MAX_ATTENUATION_DB)
                <= ATTENUATION_TOLERANCE_DB,
                f"mic {mic_id!r} attenuated by {attenuation_db:.3f} dB, expected "
                f"{OCCLUSION_MAX_ATTENUATION_DB} +/- {ATTENUATION_TOLERANCE_DB} dB",
            )

        cache = sensor._stage_cache  # noqa: SLF001 - gate evidence introspection.
        cache_evidence = {
            "full_discovery_count": cache.full_discovery_count,
            "cached_tick_count": cache.cached_tick_count,
            "invalidation_reasons": list(cache.invalidation_reasons),
            "policy": "rediscover_each_update"
            if cache.rediscover_each_update
            else "cache_until_invalidated",
        }
        evidence["stage_cache"] = cache_evidence
        # Three sensor updates ran; steady-state ticks must come from the
        # cache instead of full stage traversals.
        _require(
            cache.cached_tick_count >= 1,
            f"live path never used the discovery cache: {cache_evidence!r}",
        )
        _require(
            cache.full_discovery_count < 3,
            f"every live tick re-ran full discovery: {cache_evidence!r}",
        )

        # Material phase: authoring an explicit transmission loss on the wall
        # must change the measured attenuation from the default to the
        # material value through the live transmission resolver.
        _author_wall_transmission_loss(stage, MATERIAL_WALL_TRANSMISSION_DB)
        _update_app(SETTLE_UPDATE_COUNT)
        material_frame = sensor.update(sim_time_s=0.5, force=True)
        evidence["material_phase"] = _phase_evidence(material_frame)
        material_detection = material_frame.detections[0]
        material_occlusion = material_detection.diagnostics["occlusion"]
        _require(
            material_occlusion.get("occlusion_model") == "raycast_transmission_v1",
            "material phase did not report the transmission occlusion model: "
            f"{material_occlusion!r}",
        )
        _require(
            material_occlusion.get("hit_materials", {}).get(WALL_PRIM_PATH)
            == "usd_attribute",
            "material phase did not resolve the authored USD attribute: "
            f"{material_occlusion.get('hit_materials')!r}",
        )
        measured_material = _measured_attenuation_db(
            clear_detection, material_detection
        )
        evidence["measured_material_attenuation_db"] = measured_material
        for mic_id, attenuation_db in measured_material.items():
            _require(
                abs(attenuation_db - MATERIAL_WALL_TRANSMISSION_DB)
                <= ATTENUATION_TOLERANCE_DB,
                f"mic {mic_id!r} attenuated by {attenuation_db:.3f} dB with the "
                f"material wall, expected {MATERIAL_WALL_TRANSMISSION_DB} +/- "
                f"{ATTENUATION_TOLERANCE_DB} dB",
            )

        # Cache-policy phase: a sensor bound with rediscover_each_update=True
        # must run one full discovery per update.
        policy_sensor = IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            binding_cfg=IsaacAudioSceneBindingCfg(
                rediscover_each_update=True,
                preferred_array="rig_front",
            ),
            backend="geometry_only",
            update_period_s=0.05,
        ).start()
        policy_frames = [
            policy_sensor.update(sim_time_s=tick * 0.2, force=True)
            for tick in range(POLICY_UPDATE_COUNT)
        ]
        policy_cache = policy_sensor._stage_cache  # noqa: SLF001 - evidence.
        policy_evidence = {
            "full_discovery_count": policy_cache.full_discovery_count,
            "cached_tick_count": policy_cache.cached_tick_count,
            "policy": policy_frames[-1]
            .diagnostics["stage_snapshot"]["discovery_cache"]["policy"],
        }
        evidence["cache_policy"] = policy_evidence
        _require(
            policy_cache.full_discovery_count == POLICY_UPDATE_COUNT,
            "rediscover_each_update did not force full discovery per update: "
            f"{policy_evidence!r}",
        )
        _require(
            policy_evidence["policy"] == "rediscover_each_update",
            f"policy diagnostics missing: {policy_evidence!r}",
        )
        policy_sensor.close()

        # Redraw the occlusion-colored overlay immediately before capture.
        sensor.update(sim_time_s=0.6, force=True)
        evidence["debug_primitives"] = debug_primitives_to_dicts(
            sensor.latest_debug_primitives
        )
        if sensor.debug_drawer is not None:
            evidence["debug_draw_status"] = sensor.debug_drawer.last_status
            evidence["debug_draw_error"] = sensor.debug_drawer.last_error
        evidence["screenshot"] = _capture_viewport_screenshot(
            screenshot_path,
            framed_paths=(ARRAY_PRIM_PATH, SOURCE_PRIM_PATH, WALL_PRIM_PATH),
        )
        _require(
            evidence["screenshot"]["status"] == "captured",
            f"viewport screenshot was not captured: {evidence['screenshot']!r}",
        )

        evidence["final_frame_index"] = final_frame.frame_index
        sensor.close()
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - gate evidence records the error.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "blocked" if _is_runtime_blocker(exc) else "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
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


def _ensure_isaac_runtime(evidence: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        if omni.kit.app.get_app() is not None:
            evidence["simulation_app_bootstrap"] = "attached_existing_kit_app"
            return None
    except Exception as exc:  # noqa: BLE001 - diagnostic before bootstrap.
        evidence["kit_app_prebootstrap_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from isaacsim import SimulationApp  # type: ignore
    except Exception as exc:  # noqa: BLE001 - evidence records exact blocker.
        raise RuntimeError(
            "Could not import isaacsim.SimulationApp from the requested Python runtime."
        ) from exc

    simulation_app = SimulationApp({"headless": True})
    evidence["simulation_app_bootstrap"] = "created"
    return simulation_app


def _author_stage(stage: Any) -> Any:
    """Author the gate scene and return the wall's translate op."""

    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics  # type: ignore

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(1_000.0)

    array_prim = stage.DefinePrim(ARRAY_PRIM_PATH, "Xform")
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=ARRAY_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
    )

    create_sound_prim(
        stage,
        prim_path=SOURCE_PRIM_PATH,
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    attach_sound_source_attrs(
        stage.GetPrimAtPath(SOURCE_PRIM_PATH),
        source_id="speaker_front",
        class_label="Speech",
        position_world=SOURCE_POSITION,
        audio_asset_path="generated://impulse",
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        directivity="omni",
    )

    wall = UsdGeom.Cube.Define(stage, WALL_PRIM_PATH)
    wall.CreateSizeAttr(1.0)
    wall.CreateDisplayColorAttr([(0.75, 0.2, 0.15)])
    wall_xform = UsdGeom.Xformable(wall.GetPrim())
    wall_translate_op = wall_xform.AddTranslateOp()
    wall_translate_op.Set(Gf.Vec3d(*WALL_CLEAR_POSITION))
    wall_xform.AddScaleOp().Set(Gf.Vec3f(*WALL_SCALE))
    UsdPhysics.CollisionAPI.Apply(wall.GetPrim())

    # Side-view camera perpendicular to the source-to-array axis so the
    # occlusion-colored bearing ray and the wall are both visible.
    camera = UsdGeom.Camera.Define(stage, GATE_CAMERA_PRIM_PATH)
    camera.CreateFocalLengthAttr(14.0)
    camera_xform = UsdGeom.Xformable(camera.GetPrim())
    camera_xform.AddTranslateOp().Set(Gf.Vec3d(2.0, -13.0, 2.0))
    camera_xform.AddRotateXYZOp().Set(Gf.Vec3f(85.0, 0.0, 0.0))
    return wall_translate_op


def _author_wall_transmission_loss(stage: Any, loss_db: float) -> None:
    """Author an explicit transmission-loss attribute on the wall prim."""

    from pxr import Sdf  # type: ignore

    from isaac_audio_sensors.isaac.occlusion import TRANSMISSION_LOSS_ATTR

    wall_prim = stage.GetPrimAtPath(WALL_PRIM_PATH)
    attribute = wall_prim.CreateAttribute(
        TRANSMISSION_LOSS_ATTR,
        Sdf.ValueTypeNames.Double,
    )
    attribute.Set(float(loss_db))


def _update_app(count: int) -> None:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    for _ in range(count):
        app.update()


def _phase_evidence(frame: AudioSensorFrame) -> dict[str, Any]:
    detections = [
        {
            "detection_id": detection.detection_id,
            "source_id": detection.source_id,
            "occluded": detection.occluded,
            "per_mic_rms": dict(detection.per_mic_rms),
            "occlusion": detection.diagnostics.get("occlusion"),
        }
        for detection in frame.detections
    ]
    return {
        "frame_id": frame.frame_id,
        "frame_index": frame.frame_index,
        "aggregate_per_mic_rms": dict(frame.aggregate_per_mic_rms),
        "detections": detections,
        "stage_occlusion_diagnostics": frame.diagnostics.get(
            "stage_snapshot",
            {},
        ).get("occlusion"),
    }


def _measured_attenuation_db(clear_detection, walled_detection) -> dict[str, float]:
    measured: dict[str, float] = {}
    for mic_id, clear_rms in clear_detection.per_mic_rms.items():
        walled_rms = walled_detection.per_mic_rms[mic_id]
        if clear_rms <= 0.0 or walled_rms <= 0.0:
            raise RuntimeError(
                f"non-positive RMS for mic {mic_id!r}: "
                f"clear={clear_rms}, walled={walled_rms}"
            )
        measured[mic_id] = 20.0 * math.log10(clear_rms / walled_rms)
    return measured


def _capture_viewport_screenshot(
    path: Path,
    *,
    framed_paths: tuple[str, ...],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "framed_paths": list(framed_paths),
    }
    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        if viewport is None:
            record.update({"status": "unavailable", "reason": "no active viewport"})
            return record
        try:
            viewport.camera_path = GATE_CAMERA_PRIM_PATH
            record["camera"] = GATE_CAMERA_PRIM_PATH
        except Exception as exc:  # noqa: BLE001 - fall back to prim framing.
            record["camera"] = f"failed: {type(exc).__name__}: {exc}"
            frame_prims = getattr(viewport_utility, "frame_viewport_prims", None)
            if callable(frame_prims):
                try:
                    frame_prims(viewport, prim_paths=list(framed_paths))
                    record["framed"] = True
                except Exception as frame_exc:  # noqa: BLE001 - best-effort.
                    record["framed"] = (
                        f"failed: {type(frame_exc).__name__}: {frame_exc}"
                    )
        # Let the renderer settle on the framed view before capturing.
        _update_app(SETTLE_UPDATE_COUNT)
        path.parent.mkdir(parents=True, exist_ok=True)
        capture = viewport_utility.capture_viewport_to_file(
            viewport,
            file_path=str(path),
        )
        wait_for_result = getattr(capture, "wait_for_result", None)
        if callable(wait_for_result):
            with suppress(Exception):
                wait_for_result()
        for _ in range(200):
            if path.is_file() and path.stat().st_size > 0:
                record["status"] = "captured"
                record["size_bytes"] = path.stat().st_size
                return record
            _update_app(1)
        record.update({"status": "failed", "reason": "capture file never materialized"})
    except Exception as exc:  # noqa: BLE001 - screenshot evidence records error.
        record.update(
            {
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
    return record


def _write_config_snapshot(config_path: Path) -> None:
    config = {
        "scenario": "isaac_occlusion_live_gate",
        "backend": "geometry_only",
        "array": {
            "prim_path": ARRAY_PRIM_PATH,
            "array_id": "rig_front",
            "layout_name": "quad_front",
            "position_world": ARRAY_POSITION,
        },
        "source": {
            "prim_path": SOURCE_PRIM_PATH,
            "source_id": "speaker_front",
            "position_world": SOURCE_POSITION,
        },
        "wall": {
            "prim_path": WALL_PRIM_PATH,
            "clear_position": WALL_CLEAR_POSITION,
            "blocking_position": WALL_BLOCKING_POSITION,
            "scale": WALL_SCALE,
            "collision_api": "UsdPhysics.CollisionAPI",
        },
        "occlusion": {
            "enabled": True,
            "max_attenuation_db": OCCLUSION_MAX_ATTENUATION_DB,
            "material_wall_transmission_db": MATERIAL_WALL_TRANSMISSION_DB,
            "occlusion_model": "raycast_transmission_v1",
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_runtime_blocker(exc: BaseException) -> bool:
    message = str(exc)
    return "SimulationApp" in message or "isaacsim" in message


if __name__ == "__main__":
    raise SystemExit(main())
