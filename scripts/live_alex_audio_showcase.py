"""Live Isaac Sim showcase: Alex detects a sounding object and turns to it.

Authors the Alex-robot iTHOR FloorPlan1 kitchen, imports the Alex robot from
its URDF, mounts the ``alex_head_quad`` microphone rig on the head link, and
drives the real ``room_acoustics_srp`` backend (SRP-PHAT direction estimation
over simulated multichannel room audio) through a three-phase story:

1. A visible oven "beeper" source starts emitting; the sensor estimates the
   bearing and Alex servo-turns toward it using only the estimated DOA.
2. A louder phone starts ringing on the other side; the strongest-source
   selection switches and Alex re-turns.
3. A partition panel slides between Alex and the phone; the detection is
   flagged occluded through the sensor's occlusion pipeline (driven by a
   scripted axis-aligned-box raycaster so the robot stays physics-free).

Every simulation step captures a viewport frame and a rendered compass/meter
panel; the sensor writes a gapless multichannel session WAV plus a JSONL
frame trace. ``scripts/build_alex_showcase_package.py`` turns the captures
into the final videos, manifest, and README.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import math
import os
import platform
import shutil
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np
from alex_showcase_assets import (
    CACHE_PROVENANCE_FILENAME,
    AlexModelAsset,
    build_cache_descriptor,
    cache_directory,
    importer_settings_for_model,
    load_cached_usd,
    parse_arguments,
    require_strict_v2_evidence,
    resolve_model_asset,
    write_cache_record,
)

from isaac_audio_sensors.core.room_anchor import room_spec_from_bounds
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.extension_ui.instruments import (
    compass_view_model,
    meter_view_models,
    render_instruments_panel_rgba,
    write_rgba_png,
)
from isaac_audio_sensors.isaac.occlusion import OcclusionHit
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_sound_source_attrs,
    create_sound_prim,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OVEN_PRIM_HINT = "oven_"
ISLAND_PRIM_HINT = "standardislandheight_"
GEOMETRY_ROOT = "/FloorPlan1_physics/Geometry"

ARRAY_ID = "alex_head_quad"
ARRAY_CHILD_NAME = "AlexHeadAudioArray"
MIC_IDS = ("front", "right", "rear", "left")
MIC_OFFSETS_M = (
    (0.06, 0.0, 0.0),
    (0.0, 0.06, 0.0),
    (-0.06, 0.0, 0.0),
    (0.0, -0.06, 0.0),
)
MIC_MOUNT_LOCAL_OFFSET_M = (0.0, 0.0, 0.12)
MIC_MOUNT_LOCAL_ORIENTATION_XYZW = (0.0, 0.0, 0.0, 1.0)
SAMPLE_RATE_HZ = 48_000
COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"

STEP_S = 0.05
CAPTURE_RESOLUTION = (1280, 720)
SERVO_MAX_STEP_DEG = 2.4
SERVO_GAIN = 0.6
SERVO_MIN_CONFIDENCE = 0.12
ALIGNED_TOLERANCE_DEG = 3.0

# Story timeline (simulated seconds).
T_OVEN_START = 0.5
T_SERVO_A_START = 1.0
T_PHASE_B = 9.0            # phone starts ringing
T_SERVO_B_START = 9.5
T_OVEN_STOP = 11.0
T_PHASE_C = 16.0           # occluder slides into place
T_END = 20.0
OVEN_GAIN_DB = 0.0
PHONE_GAIN_DB = 6.0

OCCLUSION_MAX_ATTENUATION_DB = 18.0

SETTLE_UPDATES = 12


# --------------------------------------------------------------------------
# Audio synthesis for the two visible sources.
# --------------------------------------------------------------------------


def synthesize_oven_beep(duration_s: float = 12.0) -> np.ndarray:
    """Kitchen-timer beep: 880 Hz bursts over a faint hum, never fully silent."""

    t = np.arange(int(duration_s * SAMPLE_RATE_HZ)) / SAMPLE_RATE_HZ
    cycle = t % 0.6
    burst = np.clip((cycle < 0.28).astype(float), 0.18, 1.0)
    edge = np.minimum(cycle / 0.012, np.maximum(0.0, (0.28 - cycle) / 0.012))
    burst = np.where(cycle < 0.28, 0.18 + 0.82 * np.clip(edge, 0.0, 1.0), 0.18)
    tone = np.sin(2.0 * math.pi * 880.0 * t) + 0.35 * np.sin(
        2.0 * math.pi * 1760.0 * t
    )
    hum = 0.12 * np.sin(2.0 * math.pi * 220.0 * t)
    signal = 0.62 * burst * tone / 1.35 + hum
    fade = np.minimum(t / 0.05, np.maximum(0.0, (duration_s - t) / 0.05))
    return (signal * np.clip(fade, 0.0, 1.0)).astype(np.float64)


def synthesize_phone_ring(duration_s: float = 10.0) -> np.ndarray:
    """Telephone-style warble: 1209+1477 Hz, ring cadence with a low keep-alive."""

    t = np.arange(int(duration_s * SAMPLE_RATE_HZ)) / SAMPLE_RATE_HZ
    cadence = (t % 2.0) < 1.2
    warble = 0.5 * (1.0 + np.sign(np.sin(2.0 * math.pi * 10.0 * t)))
    envelope = np.where(cadence, 0.25 + 0.75 * warble, 0.15)
    tone = np.sin(2.0 * math.pi * 1209.0 * t) + np.sin(2.0 * math.pi * 1477.0 * t)
    signal = 0.55 * envelope * tone / 2.0
    fade = np.minimum(t / 0.05, np.maximum(0.0, (duration_s - t) / 0.05))
    return (signal * np.clip(fade, 0.0, 1.0)).astype(np.float64)


def write_wav(path: Path, mono: np.ndarray) -> None:
    import soundfile

    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(path, mono, SAMPLE_RATE_HZ, subtype="FLOAT")


# --------------------------------------------------------------------------
# Scripted occlusion raycaster (axis-aligned box; no PhysX required).
# --------------------------------------------------------------------------


class ScriptedBoxRaycaster:
    """Closest-hit raycasts against one movable axis-aligned box.

    Drives the sensor's real occlusion pipeline (per-mic rays, attenuation,
    detection flags, debug-ray coloring) without a running PhysX scene, so
    the robot prim can stay purely USD-posed during the showcase.
    """

    def __init__(self, prim_path: str) -> None:
        self.prim_path = prim_path
        self.active = False
        self.box_min = (0.0, 0.0, 0.0)
        self.box_max = (0.0, 0.0, 0.0)

    def set_box(self, center: tuple[float, float, float],
                half_extents: tuple[float, float, float]) -> None:
        self.box_min = tuple(center[i] - half_extents[i] for i in range(3))
        self.box_max = tuple(center[i] + half_extents[i] for i in range(3))

    def raycast_closest(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        max_distance_m: float,
    ) -> OcclusionHit | None:
        if not self.active:
            return None
        t_near, t_far = 0.0, float(max_distance_m)
        for axis in range(3):
            o, d = float(origin[axis]), float(direction[axis])
            lo, hi = self.box_min[axis], self.box_max[axis]
            if abs(d) < 1e-12:
                if o < lo or o > hi:
                    return None
                continue
            t0, t1 = (lo - o) / d, (hi - o) / d
            if t0 > t1:
                t0, t1 = t1, t0
            t_near, t_far = max(t_near, t0), min(t_far, t1)
            if t_near > t_far:
                return None
        if t_near <= 1e-9 or t_near > max_distance_m:
            return None
        return OcclusionHit(prim_path=self.prim_path, distance_m=t_near)


# --------------------------------------------------------------------------
# USD helpers.
# --------------------------------------------------------------------------


def set_prim_pose(prim: Any, position: tuple[float, float, float],
                  yaw_deg: float) -> None:
    """Author a clean translate + Z-rotation transform stack on a prim."""

    from pxr import Gf, UsdGeom  # type: ignore

    xformable = UsdGeom.Xformable(prim)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(*position))
    xformable.AddRotateZOp().Set(float(yaw_deg))


def prim_world_position(prim: Any) -> tuple[float, float, float]:
    from pxr import Usd, UsdGeom  # type: ignore

    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default()
    )
    translation = matrix.ExtractTranslation()
    return (float(translation[0]), float(translation[1]), float(translation[2]))


def prim_world_bbox(stage: Any, prim_path: str) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
] | None:
    from pxr import Usd, UsdGeom  # type: ignore

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return None
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )
    bound = cache.ComputeWorldBound(prim)
    box = bound.ComputeAlignedRange()
    if box.IsEmpty():
        return None
    lo, hi = box.GetMin(), box.GetMax()
    return (
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )


def find_geometry_prim(stage: Any, name_hint: str) -> str | None:
    root = stage.GetPrimAtPath(GEOMETRY_ROOT)
    if not root or not root.IsValid():
        return None
    for child in root.GetChildren():
        if child.GetName().startswith(name_hint):
            return str(child.GetPath())
    return None


def collect_floor_obstacles(
    stage: Any,
    *,
    z_low: float = 0.05,
    z_high: float = 1.7,
    max_span_m: float = 4.0,
) -> list[tuple[float, float, float, float]]:
    """XY bounding rectangles of scene geometry that blocks robot placement.

    Uses leaf ``Mesh`` prims rather than the top-level grouping Xforms: the
    iTHOR groups are concave (L-shaped counter runs, whole-wall shells) and
    their combined boxes would blanket the entire walkable floor.
    """

    from pxr import Usd, UsdGeom  # type: ignore

    root = stage.GetPrimAtPath(GEOMETRY_ROOT)
    obstacles: list[tuple[float, float, float, float]] = []
    if not root or not root.IsValid():
        return obstacles
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if box.IsEmpty():
            continue
        lo, hi = box.GetMin(), box.GetMax()
        x0, y0, z0 = float(lo[0]), float(lo[1]), float(lo[2])
        x1, y1, z1 = float(hi[0]), float(hi[1]), float(hi[2])
        if z1 < z_low or z0 > z_high:
            continue  # flat on the floor or up at the ceiling
        if (x1 - x0) > max_span_m or (y1 - y0) > max_span_m:
            continue  # wall/floor shells; grid candidates stay inset anyway
        obstacles.append((x0, y0, x1, y1))
    return obstacles


def collect_tall_boxes(
    stage: Any,
    *,
    min_top_z: float = 1.4,
    max_span_m: float = 4.0,
) -> list[tuple[float, float, float, float, float, float]]:
    """3D bounding boxes of tall leaf meshes (camera sightline blockers)."""

    from pxr import Usd, UsdGeom  # type: ignore

    root = stage.GetPrimAtPath(GEOMETRY_ROOT)
    boxes: list[tuple[float, float, float, float, float, float]] = []
    if not root or not root.IsValid():
        return boxes
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if box.IsEmpty():
            continue
        lo, hi = box.GetMin(), box.GetMax()
        if float(hi[2]) < min_top_z:
            continue
        if (
            float(hi[0]) - float(lo[0]) > max_span_m
            or float(hi[1]) - float(lo[1]) > max_span_m
        ):
            continue
        boxes.append(
            (
                float(lo[0]), float(lo[1]), float(lo[2]),
                float(hi[0]), float(hi[1]), float(hi[2]),
            )
        )
    return boxes


def rect_clearance(x: float, y: float,
                   rect: tuple[float, float, float, float]) -> float:
    """Horizontal distance from a point to an XY rectangle (0 inside)."""

    x0, y0, x1, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def find_open_floor_position(
    obstacles: list[tuple[float, float, float, float]],
    *,
    room_min: tuple[float, float, float],
    room_max: tuple[float, float, float],
    anchor_xy: tuple[float, float],
    anchor_distance_range: tuple[float, float],
    min_clearance: float = 0.34,
) -> tuple[float, float] | None:
    """Grid-search the room floor for the most open standing spot.

    Keeps candidates whose distance to ``anchor_xy`` lies in the requested
    range and whose clearance to every obstacle rectangle is at least
    ``min_clearance``; among those prefers the largest clearance.
    """

    best: tuple[float, tuple[float, float]] | None = None
    xs = np.arange(room_min[0] + 0.55, room_max[0] - 0.55, 0.12)
    ys = np.arange(room_min[1] + 0.55, room_max[1] - 0.55, 0.12)
    lo, hi = anchor_distance_range
    for x in xs:
        for y in ys:
            anchor_d = math.hypot(x - anchor_xy[0], y - anchor_xy[1])
            if not (lo <= anchor_d <= hi):
                continue
            clearance = min(
                (rect_clearance(float(x), float(y), rect)
                 for rect in obstacles),
                default=10.0,
            )
            if clearance < min_clearance:
                continue
            score = clearance
            if best is None or score > best[0]:
                best = (score, (float(x), float(y)))
    return None if best is None else best[1]


def author_lookat_camera(stage: Any, path: str,
                         eye: tuple[float, float, float],
                         target: tuple[float, float, float],
                         focal_length_mm: float = 16.0) -> str:
    from pxr import Gf, UsdGeom  # type: ignore

    camera = UsdGeom.Camera.Define(stage, path)
    camera.CreateFocalLengthAttr(float(focal_length_mm))
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.02, 100.0))
    view = Gf.Matrix4d()
    view.SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0.0, 0.0, 1.0))
    xformable = UsdGeom.Xformable(camera.GetPrim())
    xformable.ClearXformOpOrder()
    xformable.AddTransformOp().Set(view.GetInverse())
    return path


def author_marker_sphere(stage: Any, path: str,
                         position: tuple[float, float, float],
                         radius: float,
                         color: tuple[float, float, float]) -> Any:
    from pxr import Gf, UsdGeom  # type: ignore

    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(float(radius))
    sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    xformable = UsdGeom.Xformable(sphere.GetPrim())
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(*position))
    scale_op = xformable.AddScaleOp()
    scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))
    return sphere


def author_panel(stage: Any, path: str, position: tuple[float, float, float],
                 scale: tuple[float, float, float], yaw_deg: float) -> Any:
    from pxr import Gf, UsdGeom  # type: ignore

    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.45, 0.32, 0.2)])
    xformable = UsdGeom.Xformable(cube.GetPrim())
    xformable.ClearXformOpOrder()
    translate_op = xformable.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(*position))
    xformable.AddRotateZOp().Set(float(yaw_deg))
    xformable.AddScaleOp().Set(Gf.Vec3f(*scale))
    return translate_op


def signed_deg(bearing_deg: float) -> float:
    value = float(bearing_deg) % 360.0
    return value - 360.0 if value > 180.0 else value


def world_azimuth_deg(from_pos: tuple[float, float, float],
                      to_pos: tuple[float, float, float]) -> float:
    return math.degrees(
        math.atan2(to_pos[1] - from_pos[1], to_pos[0] - from_pos[0])
    )


# --------------------------------------------------------------------------
# Isaac runtime bootstrap and capture (patterned on the live gates).
# --------------------------------------------------------------------------


def ensure_isaac_runtime(evidence: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        if omni.kit.app.get_app() is not None:
            evidence["simulation_app_bootstrap"] = "attached_existing_kit_app"
            return None
    except Exception as exc:  # noqa: BLE001 - diagnostic before bootstrap.
        evidence["kit_app_prebootstrap_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from isaacsim import SimulationApp  # type: ignore
    except Exception as exc:  # noqa: BLE001 - records the exact blocker.
        raise RuntimeError(
            "Could not import isaacsim.SimulationApp from this Python runtime."
        ) from exc
    simulation_app = SimulationApp(
        {
            "headless": True,
            "width": CAPTURE_RESOLUTION[0],
            "height": CAPTURE_RESOLUTION[1],
        }
    )
    evidence["simulation_app_bootstrap"] = "created"
    return simulation_app


def update_app(count: int) -> None:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    for _ in range(count):
        app.update()


class ViewportCapture:
    """Camera-switching viewport screenshot helper."""

    def __init__(self) -> None:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        self._utility = viewport_utility
        self.viewport = viewport_utility.get_active_viewport()
        if self.viewport is None:
            raise RuntimeError("No active viewport is available for capture.")
        with suppress(Exception):
            self.viewport.resolution = CAPTURE_RESOLUTION
        self._camera_path: str | None = None

    def set_camera(self, camera_path: str, *, settle: int = SETTLE_UPDATES) -> None:
        if camera_path == self._camera_path:
            return
        self.viewport.camera_path = camera_path
        self._camera_path = camera_path
        update_app(settle)

    def capture(self, path: Path, *, max_wait_updates: int = 240) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        capture = self._utility.capture_viewport_to_file(
            self.viewport, file_path=str(path)
        )
        wait_for_result = getattr(capture, "wait_for_result", None)
        if callable(wait_for_result):
            with suppress(Exception):
                wait_result = wait_for_result()
                # Isaac Sim 6 returns an awaitable here.  This synchronous
                # capture loop already polls the output file while updating
                # Kit, so close the coroutine instead of leaking it.
                if inspect.isawaitable(wait_result):
                    wait_result.close()
        for _ in range(max_wait_updates):
            if path.is_file() and path.stat().st_size > 0:
                return {
                    "status": "captured",
                    "path": str(path),
                    "camera": self._camera_path,
                    "size_bytes": path.stat().st_size,
                }
            update_app(1)
        return {"status": "failed", "path": str(path), "camera": self._camera_path}


# --------------------------------------------------------------------------
# Robot import.
# --------------------------------------------------------------------------


ALEX_USD_CACHE = Path("outputs/isaac_audio_sensors/showcase/_assets/alex_urdf_usd")


def isaac_runtime_identity() -> dict[str, str]:
    """Return stable runtime fields that participate in the USD cache key."""

    versions: dict[str, str] = {"python": platform.python_version()}
    sim_version = _runtime_version_file("ISAAC_SIM_ROOT", Path.home() / "isaacsim")
    lab_version = _runtime_version_file("ISAAC_LAB_ROOT", Path.home() / "IsaacLab")
    if sim_version is None:
        try:
            from isaaclab.utils.version import get_isaac_sim_version  # type: ignore

            sim_version = str(get_isaac_sim_version())
        except Exception:  # noqa: BLE001 - evidence fallback only.
            sim_version = "unknown"
    versions["isaac_sim"] = sim_version
    versions["isaac_lab"] = lab_version or "unknown"
    try:
        import omni.kit.app  # type: ignore

        get_build_version = getattr(omni.kit.app.get_app(), "get_build_version", None)
        if callable(get_build_version):
            versions["kit_build"] = str(get_build_version())
    except Exception:  # noqa: BLE001 - optional cache discriminator only.
        pass
    return versions


def _runtime_version_file(environment_name: str, default_root: Path) -> str | None:
    root = Path(os.environ.get(environment_name, default_root)).expanduser()
    version_file = root / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def convert_alex_urdf_to_usd(
    evidence: dict[str, Any],
    asset: AlexModelAsset,
    *,
    runtime: dict[str, str],
    require_real_alex_v2: bool,
) -> Path | None:
    """Convert the Alex URDF to a USD file (cached across runs).

    Must run before the showcase scene is opened: the Isaac Sim 6 URDF
    importer opens its own working stage during conversion.
    """

    importer_settings = importer_settings_for_model(asset.model)
    descriptor = build_cache_descriptor(
        asset,
        importer_settings=importer_settings,
        runtime=runtime,
    )
    target_dir = cache_directory(ALEX_USD_CACHE, descriptor)
    cached = load_cached_usd(
        ALEX_USD_CACHE,
        descriptor,
        require_real_alex_v2=require_real_alex_v2,
    )
    if cached is not None:
        cached_usd, _ = cached
        evidence["alex_usd_conversion"] = {
            "status": "cache_hit",
            "model": asset.model,
            "profile": asset.profile,
            "model_fingerprint": asset.fingerprint,
            "urdf_path": str(asset.urdf_path),
            "usd_path": str(cached_usd),
            "cache_key": descriptor["cache_key"],
            "cache_provenance_path": str(
                target_dir / CACHE_PROVENANCE_FILENAME
            ),
            "importer_settings": importer_settings,
            "runtime": runtime,
        }
        return cached_usd
    try:
        import omni.kit.app  # type: ignore

        manager = omni.kit.app.get_app().get_extension_manager()
        manager.set_extension_enabled_immediate(
            "isaacsim.asset.importer.urdf", True
        )
        update_app(4)
        from isaacsim.asset.importer.urdf import (  # type: ignore
            URDFImporter,
            URDFImporterConfig,
        )

        target_dir.mkdir(parents=True, exist_ok=True)
        config = URDFImporterConfig(
            urdf_path=str(asset.urdf_path),
            usd_path=str(target_dir),
            merge_fixed_joints=bool(importer_settings["merge_fixed_joints"]),
            merge_mesh=bool(importer_settings["merge_mesh"]),
        )
        with suppress(Exception):
            config.run_asset_transformer = bool(
                importer_settings["run_asset_transformer"]
            )
        final_path = Path(URDFImporter(config).import_urdf())
        if not final_path.is_file():
            raise RuntimeError(f"Importer returned missing file {final_path}.")
        provenance_path = write_cache_record(
            ALEX_USD_CACHE,
            descriptor,
            final_path,
        )
        evidence["alex_usd_conversion"] = {
            "status": "converted",
            "model": asset.model,
            "profile": asset.profile,
            "model_fingerprint": asset.fingerprint,
            "urdf_path": str(asset.urdf_path),
            "usd_path": str(final_path),
            "cache_key": descriptor["cache_key"],
            "cache_provenance_path": str(provenance_path),
            "importer_settings": importer_settings,
            "runtime": runtime,
        }
        return final_path
    except Exception as exc:  # noqa: BLE001 - proxy fallback records blocker.
        evidence["alex_usd_conversion"] = {
            "status": "failed",
            "model": asset.model,
            "profile": asset.profile,
            "model_fingerprint": asset.fingerprint,
            "urdf_path": str(asset.urdf_path),
            "cache_key": descriptor["cache_key"],
            "importer_settings": importer_settings,
            "runtime": runtime,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if require_real_alex_v2:
            raise
        return None


def import_alex_robot(
    stage: Any,
    evidence: dict[str, Any],
    alex_usd: Path | None,
    asset: AlexModelAsset,
    *,
    require_real_alex_v2: bool,
) -> tuple[str, str, str]:
    """Reference the converted Alex USD; fall back to a labeled proxy figure.

    Returns ``(robot_root_path, head_prim_path, provenance)`` where
    provenance is ``"real_urdf_import"`` or ``"fallback_proxy"``.
    """

    try:
        if alex_usd is None:
            raise RuntimeError(
                "URDF conversion unavailable: "
                f"{evidence.get('alex_usd_conversion')!r}"
            )
        robot_path = "/World/Alex"
        robot_prim = stage.DefinePrim(robot_path, "Xform")
        robot_prim.GetReferences().AddReference(str(alex_usd.resolve()))
        update_app(4)
        if not robot_prim.GetChildren():
            raise RuntimeError(
                f"Referencing {alex_usd} produced no child prims."
            )
        head_path = _find_head_prim(
            robot_prim,
            require_exact_head_link=require_real_alex_v2,
        )
        evidence["robot_import"] = {
            "provenance": "real_urdf_import",
            "model": asset.model,
            "profile": asset.profile,
            "model_fingerprint": asset.fingerprint,
            "urdf_path": str(asset.urdf_path),
            "referenced_usd": str(alex_usd),
            "robot_prim_path": robot_path,
            "head_prim_path": head_path,
        }
        return robot_path, head_path, "real_urdf_import"
    except Exception as exc:  # noqa: BLE001 - fall back to a labeled proxy.
        evidence["robot_import"] = {
            "provenance": "fallback_proxy",
            "model": asset.model,
            "profile": asset.profile,
            "model_fingerprint": asset.fingerprint,
            "urdf_path": str(asset.urdf_path),
            "error": f"{type(exc).__name__}: {exc}",
        }
        if require_real_alex_v2:
            raise
        return _author_proxy_robot(stage)


def recreate_v2_sensor_frames(
    stage: Any,
    evidence: dict[str, Any],
    robot_path: str,
    asset: AlexModelAsset,
) -> None:
    """Use the shared bridge to restore fixed camera/IMU mount Xforms."""

    if asset.model != "v2":
        return
    if asset.bridge_root is None:
        raise RuntimeError("Alex V2 asset has no shared bridge provenance")
    helper_path = asset.bridge_root / "sensor_frames.py"
    if not helper_path.is_file():
        raise FileNotFoundError(f"Alex V2 sensor-frame helper not found: {helper_path}")
    module_name = "_isaac_audio_alex_v2_sensor_frames"
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Alex V2 sensor frames from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    author = getattr(module, "author_sensor_mount_xforms", None)
    if not callable(author):
        raise RuntimeError(
            "Alex V2 helper has no author_sensor_mount_xforms(): "
            f"{helper_path}"
        )
    frames = author(stage, robot_path, asset.manifest)
    evidence["recreated_sensor_frames"] = {
        "helper_path": str(helper_path),
        "non_physics_xforms": True,
        "frames": dict(frames),
    }


def _find_head_prim(
    robot_prim: Any,
    *,
    require_exact_head_link: bool,
) -> str:
    from pxr import Usd  # type: ignore

    exact: list[str] = []
    candidates: list[str] = []
    for prim in Usd.PrimRange(robot_prim):
        if prim.GetName() == "HEAD_LINK":
            exact.append(str(prim.GetPath()))
        name = prim.GetName().lower()
        if "head" in name and "link" in name:
            candidates.append(str(prim.GetPath()))
    if exact:
        exact.sort(key=len)
        return exact[0]
    if require_exact_head_link:
        raise RuntimeError("Imported Alex V2 hierarchy has no exact HEAD_LINK prim.")
    if candidates:
        candidates.sort(key=len)
        return candidates[0]
    # No explicit head link: mount on the robot root.
    return str(robot_prim.GetPath())


def _author_proxy_robot(stage: Any) -> tuple[str, str, str]:
    """Author a simple visible robot proxy (clearly labeled fallback)."""

    from pxr import Gf, UsdGeom  # type: ignore

    root = "/World/AlexProxy"
    UsdGeom.Xform.Define(stage, root)
    body = UsdGeom.Cylinder.Define(stage, f"{root}/Body")
    body.CreateHeightAttr(1.1)
    body.CreateRadiusAttr(0.18)
    body.CreateAxisAttr("Z")
    body.CreateDisplayColorAttr([Gf.Vec3f(0.25, 0.28, 0.35)])
    body_xf = UsdGeom.Xformable(body.GetPrim())
    body_xf.ClearXformOpOrder()
    body_xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.55))
    head = UsdGeom.Xform.Define(stage, f"{root}/HEAD_LINK")
    head_xf = UsdGeom.Xformable(head.GetPrim())
    head_xf.ClearXformOpOrder()
    head_xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 1.25))
    skull = UsdGeom.Sphere.Define(stage, f"{root}/HEAD_LINK/Skull")
    skull.CreateRadiusAttr(0.14)
    skull.CreateDisplayColorAttr([Gf.Vec3f(0.75, 0.78, 0.82)])
    nose = UsdGeom.Cone.Define(stage, f"{root}/HEAD_LINK/Nose")
    nose.CreateHeightAttr(0.12)
    nose.CreateRadiusAttr(0.05)
    nose.CreateAxisAttr("X")
    nose.CreateDisplayColorAttr([Gf.Vec3f(0.9, 0.45, 0.1)])
    nose_xf = UsdGeom.Xformable(nose.GetPrim())
    nose_xf.ClearXformOpOrder()
    nose_xf.AddTranslateOp().Set(Gf.Vec3d(0.16, 0.0, 0.0))
    return root, f"{root}/HEAD_LINK", "fallback_proxy"


# --------------------------------------------------------------------------
# Main showcase run.
# --------------------------------------------------------------------------


def main() -> int:
    args = parse_arguments()
    out_dir: Path = args.out_dir
    scene_usd: Path = args.scene_usd
    media = out_dir / "media"
    dirs = {
        "images": media / "images",
        "videos": media / "videos",
        "audio": media / "audio",
        "frames": media / "frames",
        "compass": media / "compass",
        "evidence": out_dir / "evidence",
    }
    for path in dirs.values():
        if path.name in {"frames", "compass"} and path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "headless": True,
        "capture_kind": "real_isaac_sim_viewport_capture",
        "out_dir": str(out_dir),
        "alex_model": args.alex_model,
        "alex_sdk_root": str(args.alex_sdk_root),
        "require_real_alex_v2": args.require_real_alex_v2,
        "scene_usd": str(scene_usd),
        "step_s": STEP_S,
        "timeline": {
            "oven_start_s": T_OVEN_START,
            "servo_a_start_s": T_SERVO_A_START,
            "phase_b_phone_s": T_PHASE_B,
            "oven_stop_s": T_OVEN_STOP,
            "phase_c_occlusion_s": T_PHASE_C,
            "end_s": T_END,
        },
    }
    steps_log: list[dict[str, Any]] = []
    simulation_app = None
    exit_code = 0
    sensor = None

    try:
        model_asset = resolve_model_asset(
            args.alex_model,
            sdk_root=args.alex_sdk_root,
        )
        evidence["model_asset"] = model_asset.evidence()
        simulation_app = ensure_isaac_runtime(evidence)
        runtime = isaac_runtime_identity()
        evidence["isaac_runtime"] = runtime

        import omni.usd  # type: ignore

        usd_context = omni.usd.get_context()

        # URDF -> USD conversion must precede opening the showcase scene:
        # the importer works in its own stage.
        alex_usd = convert_alex_urdf_to_usd(
            evidence,
            model_asset,
            runtime=runtime,
            require_real_alex_v2=args.require_real_alex_v2,
        )

        # --- Scene -------------------------------------------------------
        scene_provenance = "authored_fallback_room"
        if scene_usd.is_file():
            opened = usd_context.open_stage(str(scene_usd))
            if opened:
                scene_provenance = "alex_robot_ithor_floorplan1"
        evidence["scene_provenance"] = scene_provenance
        if (
            args.require_real_alex_v2
            and scene_provenance == "authored_fallback_room"
        ):
            raise RuntimeError(
                "Strict Alex V2 mode requires an openable real iTHOR scene: "
                f"{scene_usd}"
            )
        stage = usd_context.get_stage()
        if stage is None or scene_provenance == "authored_fallback_room":
            usd_context.new_stage()
            stage = usd_context.get_stage()
            _author_fallback_room(stage)
        update_app(SETTLE_UPDATES)

        from pxr import Gf, UsdGeom, UsdLux  # type: ignore

        UsdGeom.Xform.Define(stage, "/World")
        light = UsdLux.DomeLight.Define(stage, "/World/ShowcaseDomeLight")
        light.CreateIntensityAttr(1_800.0)

        # --- Anchor object positions to the real scene geometry ----------
        oven_path = find_geometry_prim(stage, OVEN_PRIM_HINT)
        island_path = find_geometry_prim(stage, ISLAND_PRIM_HINT)
        evidence["oven_prim_path"] = oven_path
        evidence["island_prim_path"] = island_path
        oven_bbox = prim_world_bbox(stage, oven_path) if oven_path else None
        if oven_bbox is not None:
            oven_center = tuple(
                (oven_bbox[0][i] + oven_bbox[1][i]) / 2.0 for i in range(3)
            )
        else:
            oven_center = (2.2, -1.4, 0.9)
        scene_bbox = prim_world_bbox(stage, "/FloorPlan1_physics")
        if scene_bbox is None:
            scene_bbox = ((-2.5, -2.9, -0.1), (2.47, 2.56, 2.6))
        room_min, room_max = scene_bbox
        room_center = tuple(
            (room_min[i] + room_max[i]) / 2.0 for i in range(3)
        )
        evidence["scene_world_bounds"] = {"min": room_min, "max": room_max}

        # Oven beeper sits just in front of the oven face, toward the room,
        # near the top of the oven where a control-panel beeper would live.
        to_center = np.array(room_center[:2]) - np.array(oven_center[:2])
        to_center = to_center / (np.linalg.norm(to_center) + 1e-9)
        oven_top_z = (
            float(oven_bbox[1][2]) if oven_bbox is not None else 1.0
        )
        oven_source_pos = (
            float(oven_center[0] + 0.42 * to_center[0]),
            float(oven_center[1] + 0.42 * to_center[1]),
            min(oven_top_z + 0.06, 1.35),
        )

        # Alex stands on open floor 1.6-2.6 m from the oven (grid search that
        # avoids counters, the island, and other furniture), initially facing
        # ~150 deg away from it so the turn is clearly visible.
        obstacles = collect_floor_obstacles(stage)
        evidence["floor_obstacle_count"] = len(obstacles)
        open_xy = find_open_floor_position(
            obstacles,
            room_min=room_min,
            room_max=room_max,
            anchor_xy=oven_source_pos[:2],
            anchor_distance_range=(1.6, 2.6),
        )
        if open_xy is None:
            open_xy = tuple(
                np.clip(
                    np.array(oven_source_pos[:2]) + 2.2 * to_center,
                    np.array(room_min[:2]) + 0.7,
                    np.array(room_max[:2]) - 0.7,
                )
            )
            evidence["robot_placement"] = "clamped_fallback"
        else:
            evidence["robot_placement"] = "open_floor_grid_search"
        robot_pos = (float(open_xy[0]), float(open_xy[1]), 0.0)
        azimuth_to_oven = world_azimuth_deg(robot_pos, oven_source_pos)
        initial_yaw_deg = (azimuth_to_oven + 150.0) % 360.0

        # Phone rings from a clearly different direction: prefer the island
        # counter edge nearest an angular separation of ~90-180 deg from the
        # oven as seen from the robot, at least 1.2 m away.
        island_bbox = prim_world_bbox(stage, island_path) if island_path else None
        perp = np.array([-to_center[1], to_center[0]])
        phone_pos = None
        if island_bbox is not None:
            (ix0, iy0, _), (ix1, iy1, iz1) = island_bbox
            inset = 0.10
            edge_candidates = [
                (ix0 + inset, (iy0 + iy1) / 2.0),
                (ix1 - inset, (iy0 + iy1) / 2.0),
                ((ix0 + ix1) / 2.0, iy0 + inset),
                ((ix0 + ix1) / 2.0, iy1 - inset),
                (ix0 + inset, iy0 + inset),
                (ix0 + inset, iy1 - inset),
                (ix1 - inset, iy0 + inset),
                (ix1 - inset, iy1 - inset),
            ]
            best_edge = None
            for ex, ey in edge_candidates:
                distance = math.hypot(ex - robot_pos[0], ey - robot_pos[1])
                if distance < 1.2:
                    continue
                separation = abs(
                    signed_deg(
                        world_azimuth_deg(robot_pos, (ex, ey, 0.0))
                        - azimuth_to_oven
                    )
                )
                if best_edge is None or separation > best_edge[0]:
                    best_edge = (separation, (ex, ey))
            if best_edge is not None and best_edge[0] >= 50.0:
                phone_pos = (
                    float(best_edge[1][0]),
                    float(best_edge[1][1]),
                    float(iz1) + 0.07,
                )
                evidence["phone_placement"] = {
                    "kind": "island_edge",
                    "angular_separation_deg": best_edge[0],
                }
        if phone_pos is None:
            phone_xy = np.clip(
                np.array(robot_pos[:2]) + 1.9 * perp,
                np.array(room_min[:2]) + 0.55,
                np.array(room_max[:2]) - 0.55,
            )
            phone_pos = (float(phone_xy[0]), float(phone_xy[1]), 1.0)
            evidence["phone_placement"] = {"kind": "perpendicular_fallback"}

        # --- Robot -------------------------------------------------------
        robot_root, head_path, _robot_provenance = import_alex_robot(
            stage,
            evidence,
            alex_usd,
            model_asset,
            require_real_alex_v2=args.require_real_alex_v2,
        )
        recreate_v2_sensor_frames(stage, evidence, robot_root, model_asset)
        robot_prim = stage.GetPrimAtPath(robot_root)
        set_prim_pose(robot_prim, robot_pos, initial_yaw_deg)
        update_app(2)
        # Drop the robot so its bounding box rests on the floor.
        robot_bbox = prim_world_bbox(stage, robot_root)
        if robot_bbox is not None:
            robot_pos = (
                robot_pos[0],
                robot_pos[1],
                robot_pos[2] - robot_bbox[0][2] + max(room_min[2], 0.0),
            )
            set_prim_pose(robot_prim, robot_pos, initial_yaw_deg)
            update_app(2)

        # --- Microphone array on the head --------------------------------
        array_path = f"{head_path}/{ARRAY_CHILD_NAME}"
        array_prim = stage.DefinePrim(array_path, "Xform")
        array_xf = UsdGeom.Xformable(array_prim)
        array_xf.ClearXformOpOrder()
        array_xf.AddTranslateOp().Set(Gf.Vec3d(*MIC_MOUNT_LOCAL_OFFSET_M))
        attach_microphone_array_attrs(
            array_prim,
            array_id=ARRAY_ID,
            sample_rate_hz=SAMPLE_RATE_HZ,
            coordinate_convention=COORDINATE_CONVENTION,
            layout_name="quad_cross",
            microphone_ids=MIC_IDS,
            microphone_relative_offsets_m=MIC_OFFSETS_M,
        )
        # Visible mic pucks so close-ups show the physical rig.
        for mic_id, offset in zip(MIC_IDS, MIC_OFFSETS_M, strict=True):
            author_marker_sphere(
                stage,
                f"{array_path}/mic_{mic_id}",
                offset,
                0.016,
                (0.08, 0.85, 0.95),
            )
        evidence["microphone_mount"] = {
            "array_prim_path": array_path,
            "parent_prim_path": head_path,
            "local_translation_m": list(MIC_MOUNT_LOCAL_OFFSET_M),
            "local_orientation_xyzw": list(MIC_MOUNT_LOCAL_ORIENTATION_XYZW),
            "microphone_ids": list(MIC_IDS),
            "microphone_relative_offsets_m": [list(value) for value in MIC_OFFSETS_M],
        }
        if args.require_real_alex_v2:
            require_strict_v2_evidence(evidence, check_files=True)
            evidence["strict_v2_validation"] = {"post_mount": "passed"}

        # --- Sound sources ------------------------------------------------
        oven_wav = dirs["audio"] / "source_sound.wav"
        write_wav(oven_wav, synthesize_oven_beep())
        phone_wav = dirs["audio"] / "phone_ring.wav"
        write_wav(phone_wav, synthesize_phone_ring())
        oven_wav_rel = oven_wav.resolve().relative_to(Path.cwd().resolve())
        phone_wav_rel = phone_wav.resolve().relative_to(Path.cwd().resolve())

        oven_source_path = "/World/Sfx/OvenBeeper"
        create_sound_prim(
            stage,
            prim_path=oven_source_path,
            audio_asset_path=str(oven_wav_rel),
            spatial=True,
            start_time_s=T_OVEN_START,
            gain_db=OVEN_GAIN_DB,
        )
        attach_sound_source_attrs(
            stage.GetPrimAtPath(oven_source_path),
            source_id="oven_beeper",
            class_label="Appliance",
            position_world=oven_source_pos,
            audio_asset_path=str(oven_wav_rel),
            start_time_s=T_OVEN_START,
            duration_s=T_OVEN_STOP - T_OVEN_START,
            gain_db=OVEN_GAIN_DB,
            directivity="omni",
        )
        oven_marker = author_marker_sphere(
            stage,
            "/World/Markers/OvenBeeperMarker",
            oven_source_pos,
            0.06,
            (1.0, 0.55, 0.05),
        )

        phone_source_path = "/World/Sfx/CounterPhone"
        create_sound_prim(
            stage,
            prim_path=phone_source_path,
            audio_asset_path=str(phone_wav_rel),
            spatial=True,
            start_time_s=T_PHASE_B,
            gain_db=PHONE_GAIN_DB,
        )
        attach_sound_source_attrs(
            stage.GetPrimAtPath(phone_source_path),
            source_id="counter_phone",
            class_label="Phone",
            position_world=phone_pos,
            audio_asset_path=str(phone_wav_rel),
            start_time_s=T_PHASE_B,
            duration_s=T_END - T_PHASE_B,
            gain_db=PHONE_GAIN_DB,
            directivity="omni",
        )
        phone_marker = author_marker_sphere(
            stage,
            "/World/Markers/CounterPhoneMarker",
            phone_pos,
            0.055,
            (0.15, 0.9, 0.25),
        )

        # --- Occluder panel (phase C) -------------------------------------
        occluder_path = "/World/OcclusionPanel"
        robot_to_phone = np.array(phone_pos[:2]) - np.array(robot_pos[:2])
        occluder_center_xy = np.array(robot_pos[:2]) + 0.55 * robot_to_phone
        occluder_yaw = world_azimuth_deg(robot_pos, phone_pos) + 90.0
        occluder_scale = (1.5, 0.08, 2.2)
        occluder_park = (
            float(occluder_center_xy[0]),
            float(occluder_center_xy[1]),
            -5.0,
        )
        occluder_place = (
            float(occluder_center_xy[0]),
            float(occluder_center_xy[1]),
            1.1,
        )
        occluder_translate_op = author_panel(
            stage, occluder_path, occluder_park, occluder_scale, occluder_yaw
        )
        raycaster = ScriptedBoxRaycaster(occluder_path)
        # World-aligned bound of the yaw-rotated panel footprint (exact
        # rotated-rectangle extents; keeps the source and mics outside).
        yaw_rad = math.radians(occluder_yaw)
        half_x = 0.5 * (
            abs(math.cos(yaw_rad)) * occluder_scale[0]
            + abs(math.sin(yaw_rad)) * occluder_scale[1]
        )
        half_y = 0.5 * (
            abs(math.sin(yaw_rad)) * occluder_scale[0]
            + abs(math.cos(yaw_rad)) * occluder_scale[1]
        )
        raycaster.set_box(
            occluder_place, (half_x, half_y, occluder_scale[2] / 2.0)
        )

        # --- Cameras -------------------------------------------------------
        def clamp_into_room(point: tuple[float, float, float],
                            margin: float = 0.35) -> tuple[float, float, float]:
            return (
                float(np.clip(point[0], room_min[0] + margin, room_max[0] - margin)),
                float(np.clip(point[1], room_min[1] + margin, room_max[1] - margin)),
                float(np.clip(point[2], 0.3, room_max[2] - 0.15)),
            )

        head_now = prim_world_position(stage.GetPrimAtPath(head_path))
        away = np.array(robot_pos[:2]) - np.array(oven_source_pos[:2])
        away = away / (np.linalg.norm(away) + 1e-9)
        # Main camera: the room corner or wall midpoint that (a) is not
        # parked against tall furniture, (b) has the fewest 3D sightlines
        # to robot/oven/phone blocked by tall boxes, and (c) keeps the most
        # distance from all of them, so everything fits one wide-angle view.
        interest = (
            (robot_pos[0], robot_pos[1], 1.2),
            oven_source_pos,
            phone_pos,
        )
        tall_boxes = collect_tall_boxes(stage)

        def near_tall_furniture(candidate: tuple[float, float]) -> bool:
            return any(
                box[0] - 0.3 <= candidate[0] <= box[3] + 0.3
                and box[1] - 0.3 <= candidate[1] <= box[4] + 0.3
                and box[5] > 1.6
                for box in tall_boxes
            )

        def blocked_sightlines(candidate: tuple[float, float]) -> int:
            eye = (candidate[0], candidate[1], 2.15)
            blocked = 0
            for poi in interest:
                for fraction in np.linspace(0.05, 0.95, 24):
                    x = eye[0] + fraction * (poi[0] - eye[0])
                    y = eye[1] + fraction * (poi[1] - eye[1])
                    z = eye[2] + fraction * (poi[2] - eye[2])
                    if any(
                        box[0] <= x <= box[3]
                        and box[1] <= y <= box[4]
                        and box[2] <= z <= box[5]
                        for box in tall_boxes
                    ):
                        blocked += 1
                        break
            return blocked

        corner_inset = 0.4
        cx0, cy0 = room_min[0] + corner_inset, room_min[1] + corner_inset
        cx1, cy1 = room_max[0] - corner_inset, room_max[1] - corner_inset
        candidates = [
            (cx0, cy0), (cx0, cy1), (cx1, cy0), (cx1, cy1),
            ((cx0 + cx1) / 2.0, cy0), ((cx0 + cx1) / 2.0, cy1),
            (cx0, (cy0 + cy1) / 2.0), (cx1, (cy0 + cy1) / 2.0),
        ]
        usable = [c for c in candidates if not near_tall_furniture(c)]
        main_eye_xy = max(
            usable or candidates,
            key=lambda c: (
                -blocked_sightlines(c),
                min(math.hypot(c[0] - p[0], c[1] - p[1]) for p in interest),
            ),
        )
        evidence["main_camera_corner"] = {
            "xy": main_eye_xy,
            "blocked_sightlines": blocked_sightlines(main_eye_xy),
            "candidates_rejected_near_furniture": len(candidates)
            - len(usable),
        }
        main_eye = (main_eye_xy[0], main_eye_xy[1], 2.15)
        main_target = (
            sum(p[0] for p in interest) / 3.0,
            sum(p[1] for p in interest) / 3.0,
            0.9,
        )
        main_cam = author_lookat_camera(
            stage, "/World/Cameras/ShowcaseMain", main_eye, main_target, 14.0
        )
        source_eye = clamp_into_room(
            (
                oven_source_pos[0] + 1.35 * to_center[0] + 0.5 * perp[0],
                oven_source_pos[1] + 1.35 * to_center[1] + 0.5 * perp[1],
                oven_source_pos[2] + 0.45,
            )
        )
        source_cam = author_lookat_camera(
            stage, "/World/Cameras/SourceCloseup", source_eye, oven_source_pos, 20.0
        )
        head_eye = clamp_into_room(
            (
                head_now[0] + 0.75 * to_center[0] + 0.55 * perp[0],
                head_now[1] + 0.75 * to_center[1] + 0.55 * perp[1],
                head_now[2] + 0.45,
            )
        )
        head_cam = author_lookat_camera(
            stage,
            "/World/Cameras/HeadArrayCloseup",
            head_eye,
            (head_now[0], head_now[1], head_now[2] + 0.12),
            26.0,
        )
        phone_eye = clamp_into_room(
            (
                phone_pos[0] - 1.1 * perp[0] + 0.5 * away[0],
                phone_pos[1] - 1.1 * perp[1] + 0.5 * away[1],
                phone_pos[2] + 0.55,
            )
        )
        phone_cam = author_lookat_camera(
            stage, "/World/Cameras/PhoneCloseup", phone_eye, phone_pos, 22.0
        )
        update_app(SETTLE_UPDATES)

        # --- Sensor ---------------------------------------------------------
        room_spec = room_spec_from_bounds(
            min_world=(room_min[0] - 0.1, room_min[1] - 0.1, min(room_min[2], -0.1)),
            max_world=(room_max[0] + 0.1, room_max[1] + 0.1, room_max[2] + 0.1),
            room_id="floorplan1_kitchen",
            absorption=0.42,
            max_order=1,
            out_of_bounds="clamp",
            anchor_prim_path="/FloorPlan1_physics",
        )
        frame_trace_path = dirs["evidence"] / "showcase.frames.jsonl"
        with suppress(FileNotFoundError):
            frame_trace_path.unlink()
        with suppress(FileNotFoundError):
            (dirs["audio"] / f"{ARRAY_ID}_session.wav").unlink()
        sensor = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=array_path,
            robot_base_prim_path=robot_root,
            backend="room_acoustics_srp",
            room=room_spec,
            update_period_s=STEP_S,
            debug_draw=True,
            occlusion_enabled=True,
            occlusion_max_attenuation_db=OCCLUSION_MAX_ATTENUATION_DB,
            occlusion_raycaster=raycaster,
            writer_path=frame_trace_path,
            waveform_dir=dirs["audio"],
            waveform_mode="session",
        ).start()
        evidence["sensor"] = {
            "backend": "room_acoustics_srp",
            "array_prim_path": array_path,
            "array_id": ARRAY_ID,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "room": {
                "room_id": room_spec.room_id,
                "dimensions_m": room_spec.dimensions_m,
                "origin_m": room_spec.origin_m,
                "absorption": room_spec.absorption,
                "max_order": room_spec.max_order,
            },
            "occlusion_raycaster": "scripted_box_raycaster",
            "occlusion_max_attenuation_db": OCCLUSION_MAX_ATTENUATION_DB,
        }

        capturer = ViewportCapture()
        capturer.set_camera(main_cam)

        # --- Story loop ------------------------------------------------------
        current_yaw = initial_yaw_deg
        stills: dict[str, dict[str, Any]] = {}
        total_steps = int(round(T_END / STEP_S))
        first_detection: dict[str, Any] | None = None
        phase_b_first_switch: dict[str, Any] | None = None
        occluded_seen: dict[str, Any] | None = None

        def marker_pulse(marker: Any, active: bool, t: float) -> None:
            xformable = UsdGeom.Xformable(marker.GetPrim())
            for op in xformable.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeScale:
                    scale = 1.0 + (0.55 * (0.5 + 0.5 * math.sin(t * 14.0))
                                   if active else 0.0)
                    op.Set(Gf.Vec3f(scale, scale, scale))

        def take_still(name: str, camera: str, filename: str) -> None:
            capturer.set_camera(camera)
            stills[name] = capturer.capture(dirs["images"] / filename)
            capturer.set_camera(main_cam)

        for step in range(total_steps):
            t = step * STEP_S

            # Scenario events.
            if not raycaster.active and t >= T_PHASE_C - 1e-9:
                occluder_translate_op.Set(Gf.Vec3d(*occluder_place))
                raycaster.active = True

            marker_pulse(oven_marker, T_OVEN_START <= t < T_OVEN_STOP, t)
            marker_pulse(phone_marker, t >= T_PHASE_B, t)

            update_app(1)
            frame = sensor.update(sim_time_s=t, force=True)

            # Strongest detection drives the compass; the servo follows the
            # phase's target source (oven in A, phone in B) so a brief
            # selection flicker cannot ping-pong the turn.
            selected = None
            by_source: dict[str, Any] = {}
            for detection in frame.detections:
                power = (
                    sum(detection.per_mic_rms.values())
                    / max(len(detection.per_mic_rms), 1)
                )
                if detection.source_id is not None:
                    by_source[detection.source_id] = detection
                if selected is None or power > selected[0]:
                    selected = (power, detection)
            detection = selected[1] if selected else None

            bearing = None
            confidence = 0.0
            occluded_flag = None
            sector = None
            candidates: tuple[float, ...] = ()
            if detection is not None:
                bearing = detection.doa.estimated_bearing_deg
                confidence = detection.doa.bearing_confidence
                occluded_flag = detection.occluded
                sector = detection.doa.bearing_sector
                candidates = detection.doa.candidate_bearing_deg

            # Servo phases: A tracks the oven, B the phone. The estimated
            # bearing is clockwise-from-array-forward, so facing the source
            # means adding the signed bearing to the yaw (verified against
            # ground-truth azimuths in the evidence JSON).
            servo_source = None
            if T_SERVO_A_START <= t < T_PHASE_B:
                servo_source = "oven_beeper"
            elif T_SERVO_B_START <= t < T_PHASE_C:
                servo_source = "counter_phone"
            servo_detection = by_source.get(servo_source)
            servo_bearing = None
            if servo_detection is not None:
                servo_bearing = servo_detection.doa.estimated_bearing_deg
                servo_confidence = servo_detection.doa.bearing_confidence
                if (
                    servo_bearing is not None
                    and servo_confidence >= SERVO_MIN_CONFIDENCE
                ):
                    error = signed_deg(servo_bearing)
                    if abs(error) > ALIGNED_TOLERANCE_DEG:
                        step_deg = float(
                            np.clip(
                                SERVO_GAIN * error,
                                -SERVO_MAX_STEP_DEG,
                                SERVO_MAX_STEP_DEG,
                            )
                        )
                        current_yaw = (current_yaw + step_deg) % 360.0
                        set_prim_pose(robot_prim, robot_pos, current_yaw)

            # Compass/meter panel for this step.
            view_model = compass_view_model(
                bearing_deg=bearing,
                candidate_bearings=candidates,
                sector=sector,
                confidence=confidence,
                occluded=occluded_flag,
            )
            meters = meter_view_models(frame.aggregate_per_mic_rms)
            write_rgba_png(
                dirs["compass"] / f"step_{step:04d}.png",
                render_instruments_panel_rgba(view_model, meters),
            )

            # Milestone evidence and stills.
            if (
                first_detection is None
                and detection is not None
                and detection.source_id == "oven_beeper"
                and bearing is not None
                and confidence >= SERVO_MIN_CONFIDENCE
            ):
                first_detection = {
                    "t_s": t,
                    "bearing_deg": bearing,
                    "confidence": confidence,
                    "source_id": detection.source_id,
                }
                take_still(
                    "compass_moment", main_cam, "05_alex_before_turn.png"
                )
            if (
                phase_b_first_switch is None
                and t >= T_PHASE_B
                and detection is not None
                and detection.source_id == "counter_phone"
            ):
                phase_b_first_switch = {
                    "t_s": t,
                    "bearing_deg": bearing,
                    "confidence": confidence,
                }
            if (
                occluded_seen is None
                and t >= T_PHASE_C
                and occluded_flag is True
            ):
                occluded_seen = {
                    "t_s": t,
                    "bearing_deg": bearing,
                    "confidence": confidence,
                    "occlusion": detection.diagnostics.get("occlusion"),
                }
                take_still("occlusion", main_cam, "08_occlusion_case.png")

            steps_log.append(
                {
                    "step": step,
                    "t_s": round(t, 4),
                    "robot_yaw_deg": round(current_yaw, 3),
                    "servo_source": servo_source,
                    "servo_bearing_deg": (
                        None if servo_bearing is None else round(servo_bearing, 3)
                    ),
                    "bearing_deg": None if bearing is None else round(bearing, 3),
                    "confidence": round(float(confidence), 4),
                    "sector": sector,
                    "occluded": occluded_flag,
                    "selected_source": (
                        None if detection is None else detection.source_id
                    ),
                    "detection_count": len(frame.detections),
                }
            )

            # Scheduled stills.
            if step == int(0.4 / STEP_S):
                take_still("overview", main_cam, "01_scene_overview.png")
            if step == int(1.2 / STEP_S):
                take_still("source", source_cam, "02_source_object_closeup.png")
            if step == int(2.0 / STEP_S):
                take_still("head", head_cam, "03_alex_head_mic_array.png")
            if step == int((T_PHASE_B - 0.4) / STEP_S):
                take_still("after_turn", main_cam, "06_alex_after_turn.png")
            if step == int((T_PHASE_B + 1.2) / STEP_S):
                take_still("phone", phone_cam, "07_second_source_phone.png")
            if step == int((T_PHASE_C + 1.6) / STEP_S) and occluded_seen is None:
                # Visual of the occlusion scenario even if the flag never
                # fired; the evidence JSON stays honest about the flag.
                take_still("occlusion_visual", main_cam, "08_occlusion_case.png")

            # Main video frame.
            capturer.capture(dirs["frames"] / f"step_{step:04d}.png")

        # Final poses and error metrics. Residuals use the servo target
        # source's own bearing so a stronger co-active source cannot skew
        # the alignment claim.
        final_head = prim_world_position(stage.GetPrimAtPath(head_path))
        azimuth_to_phone = world_azimuth_deg(robot_pos, phone_pos)
        last_bearings = [
            entry["servo_bearing_deg"]
            for entry in steps_log
            if entry["servo_bearing_deg"] is not None
            and entry["servo_source"] == "counter_phone"
            and T_PHASE_C - 1.5 <= entry["t_s"] < T_PHASE_C
        ]
        phase_a_bearings = [
            entry["servo_bearing_deg"]
            for entry in steps_log
            if entry["servo_bearing_deg"] is not None
            and entry["servo_source"] == "oven_beeper"
            and T_PHASE_B - 1.5 <= entry["t_s"] < T_PHASE_B
        ]
        evidence["story"] = {
            "robot_initial_yaw_deg": initial_yaw_deg,
            "robot_final_yaw_deg": current_yaw,
            "robot_position_world": robot_pos,
            "head_position_world": final_head,
            "oven_source": {
                "prim_path": oven_source_path,
                "source_id": "oven_beeper",
                "position_world": oven_source_pos,
                "world_azimuth_from_robot_deg": azimuth_to_oven,
                "emission_window_s": [T_OVEN_START, T_OVEN_STOP],
                "gain_db": OVEN_GAIN_DB,
            },
            "phone_source": {
                "prim_path": phone_source_path,
                "source_id": "counter_phone",
                "position_world": phone_pos,
                "world_azimuth_from_robot_deg": azimuth_to_phone,
                "emission_window_s": [T_PHASE_B, T_END],
                "gain_db": PHONE_GAIN_DB,
            },
            "first_detection": first_detection,
            "phase_b_first_phone_selection": phase_b_first_switch,
            "occluded_detection": occluded_seen,
            "phase_a_residual_bearing_deg": (
                signed_deg(float(np.median(phase_a_bearings)))
                if phase_a_bearings
                else None
            ),
            "phase_b_residual_bearing_deg": (
                signed_deg(float(np.median(last_bearings)))
                if last_bearings
                else None
            ),
            "servo": {
                "gain": SERVO_GAIN,
                "max_step_deg_per_tick": SERVO_MAX_STEP_DEG,
                "min_confidence": SERVO_MIN_CONFIDENCE,
                "aligned_tolerance_deg": ALIGNED_TOLERANCE_DEG,
            },
        }
        evidence["stills"] = stills
        evidence["frame_count"] = total_steps
        evidence["session_wav"] = str(dirs["audio"] / f"{ARRAY_ID}_session.wav")

        # 04: compass panel at the first-detection step (copied before the
        # alignment gate so the artifact survives a failed run for triage).
        first_step = (
            int(round(first_detection["t_s"] / STEP_S))
            if first_detection
            else 0
        )
        compass_src = dirs["compass"] / f"step_{first_step:04d}.png"
        if compass_src.is_file():
            shutil.copyfile(
                compass_src, dirs["images"] / "04_doa_compass_panel.png"
            )

        # A residual bearing near zero after each servo phase is the core
        # "Alex turned toward the sound" claim; require it for phase A.
        residual = evidence["story"]["phase_a_residual_bearing_deg"]
        if residual is None or abs(residual) > 15.0:
            raise RuntimeError(
                f"Phase A servo did not align with the source: residual "
                f"bearing {residual!r} deg."
            )

        sensor.close()
        sensor = None
        if args.require_real_alex_v2:
            require_strict_v2_evidence(evidence, check_files=True)
            evidence["strict_v2_validation"]["final_evidence"] = "passed"
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - evidence records the error.
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
        if sensor is not None:
            with suppress(Exception):
                sensor.close()
        evidence["steps"] = steps_log
        evidence_path = out_dir / "evidence" / "showcase_evidence.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        if simulation_app is not None:
            with suppress(Exception):
                simulation_app.close()
        summary = {
            key: evidence.get(key)
            for key in ("status", "error", "scene_provenance", "out_dir")
        }
        summary["robot_import"] = (
            evidence.get("robot_import", {}).get("provenance")
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        sys.stdout.flush()

    return exit_code


def _author_fallback_room(stage: Any) -> None:
    """Minimal kitchen-like room used only when the iTHOR scene is missing."""

    from pxr import Gf, UsdGeom  # type: ignore

    world = UsdGeom.Xform.Define(stage, "/FloorPlan1_physics")
    stage.SetDefaultPrim(world.GetPrim())
    geometry = UsdGeom.Xform.Define(stage, GEOMETRY_ROOT)
    del geometry
    floor = UsdGeom.Cube.Define(stage, f"{GEOMETRY_ROOT}/floor_fallback")
    floor.CreateSizeAttr(1.0)
    floor.CreateDisplayColorAttr([Gf.Vec3f(0.6, 0.55, 0.5)])
    xf = UsdGeom.Xformable(floor.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.05))
    xf.AddScaleOp().Set(Gf.Vec3f(5.0, 5.5, 0.1))
    oven = UsdGeom.Cube.Define(stage, f"{GEOMETRY_ROOT}/oven_fallback")
    oven.CreateSizeAttr(1.0)
    oven.CreateDisplayColorAttr([Gf.Vec3f(0.2, 0.2, 0.22)])
    oven_xf = UsdGeom.Xformable(oven.GetPrim())
    oven_xf.AddTranslateOp().Set(Gf.Vec3d(2.0, -1.4, 0.45))
    oven_xf.AddScaleOp().Set(Gf.Vec3f(0.6, 0.75, 0.9))


def _is_runtime_blocker(exc: BaseException) -> bool:
    message = str(exc)
    return "SimulationApp" in message or "isaacsim" in message


if __name__ == "__main__":
    raise SystemExit(main())
