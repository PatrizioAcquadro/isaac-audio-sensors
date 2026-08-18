"""Pure Alex model, cache, and provenance policy for the live showcase.

This module deliberately has no Isaac Sim imports.  The live script uses it to
resolve the static Alex V2 asset folder (URDF + OBJ meshes), and unit tests
can exercise the resolution and strict-evidence rules without starting Kit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ALEX_V2_PROFILE = "alex_v2_fullbody_standard_no_external_hands"
CACHE_SCHEMA_VERSION = 1
CACHE_PROVENANCE_FILENAME = "cache_provenance.json"
DEFAULT_MANIFEST_DIR = Path(
    "outputs/isaac_audio_sensors/showcase/_assets/alex_v2_manifests"
)
HEAD_SENSOR_FRAMES = {
    "HEAD_ZED_X_MINI_LINK": "HEAD_ZED_X_MINI_FRAME",
    "HEAD_IMU_LINK": "HEAD_IMU_FRAME",
}


def default_alex_root() -> Path:
    return Path.home() / "Desktop" / "Alex" / "assets" / "robots" / "alex_v2"


def default_v2_urdf(alex_root: Path | None = None) -> Path:
    return (alex_root or default_alex_root()) / "urdf" / "alex_v2.urdf"


def installed_runtime_version(
    distribution: str,
    environment_name: str,
    default_root: Path,
) -> str:
    """Return the active distribution version, with a source-tree fallback."""

    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        root = Path(os.environ.get(environment_name, default_root)).expanduser()
        try:
            value = (root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
        return value or "unknown"


def default_scene_usd() -> Path:
    return (
        Path.home()
        / "Desktop"
        / "CombinedScene"
        / "FloorPlan1_updated_physics"
        / "scene.usda"
    )


@dataclass(frozen=True)
class AlexModelAsset:
    """Resolved URDF plus immutable model provenance."""

    model: str
    profile: str
    urdf_path: Path
    manifest_path: Path
    manifest: Mapping[str, Any]
    fingerprint: str

    def evidence(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "profile": self.profile,
            "urdf_path": str(self.urdf_path),
            "manifest_path": str(self.manifest_path),
            "manifest": dict(self.manifest),
            "fingerprint": self.fingerprint,
        }


class CacheProvenanceError(RuntimeError):
    """Raised when an exact-key cache entry cannot prove its provenance."""


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/showcase")
        / f"alex_audio_detection_{date.today().isoformat()}",
    )
    parser.add_argument(
        "--alex-root",
        type=Path,
        default=default_alex_root(),
        help="Static Alex V2 asset folder (urdf/alex_v2.urdf + meshes/*.obj).",
    )
    parser.add_argument(
        "--scene-usd",
        type=Path,
        default=default_scene_usd(),
        help="iTHOR scene USD, independent of the robot asset.",
    )
    parser.add_argument(
        "--require-real-alex-v2",
        action="store_true",
        help=(
            "Reject proxy robots, fallback rooms, stale caches, missing HEAD_LINK, "
            "and incomplete V2 provenance."
        ),
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    args.alex_root = args.alex_root.expanduser()
    args.scene_usd = args.scene_usd.expanduser()
    return args


def mesh_inventory(urdf_path: Path) -> dict[str, str]:
    """Hash every URDF mesh reference; only local .obj meshes are allowed."""

    root = ET.parse(urdf_path).getroot()
    inventory: dict[str, str] = {}
    for mesh in root.findall(".//mesh"):
        reference = str(mesh.attrib.get("filename", "")).strip()
        candidate = Path(reference)
        if not candidate.is_absolute():
            candidate = urdf_path.parent / candidate
        if candidate.suffix.lower() != ".obj":
            raise RuntimeError(
                f"Alex V2 URDF references a non-OBJ mesh: {reference} "
                "(the convex-collision URDF variants are not supported)"
            )
        inventory[reference] = sha256_file(candidate)
    return dict(sorted(inventory.items()))


def parse_head_sensor_frames(urdf_path: Path) -> dict[str, dict[str, Any]]:
    """Read the fixed head sensor joint origins from the static URDF."""

    root = ET.parse(urdf_path).getroot()
    frames: dict[str, dict[str, Any]] = {}
    for joint in root.findall(".//joint"):
        if joint.attrib.get("type") != "fixed":
            continue
        parent = joint.find("parent")
        child = joint.find("child")
        if parent is None or child is None:
            continue
        parent_link = str(parent.attrib.get("link", ""))
        child_link = str(child.attrib.get("link", ""))
        frame_name = HEAD_SENSOR_FRAMES.get(child_link)
        if frame_name is None or parent_link != "HEAD_LINK":
            continue
        origin = joint.find("origin")
        xyz = [0.0, 0.0, 0.0]
        rpy = [0.0, 0.0, 0.0]
        if origin is not None:
            if origin.attrib.get("xyz"):
                xyz = [float(value) for value in origin.attrib["xyz"].split()]
            if origin.attrib.get("rpy"):
                rpy = [float(value) for value in origin.attrib["rpy"].split()]
        frames[frame_name] = {
            "parent_link": parent_link,
            "xyz": xyz,
            "rpy": rpy,
        }
    missing = sorted(set(HEAD_SENSOR_FRAMES.values()) - set(frames))
    if missing:
        raise RuntimeError(
            "Alex V2 URDF is missing fixed head sensor joints for: "
            + ", ".join(missing)
        )
    return frames


def rpy_to_quaternion_wxyz(
    rpy: Sequence[float],
) -> tuple[float, float, float, float]:
    """URDF fixed-axis RPY to a wxyz quaternion (q = qz(yaw)*qy(pitch)*qx(roll))."""

    roll, pitch, yaw = (float(value) for value in rpy)
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (
        cy * cp * cr + sy * sp * sr,
        cy * cp * sr - sy * sp * cr,
        cy * sp * cr + sy * cp * sr,
        sy * cp * cr - cy * sp * sr,
    )


def resolve_v2_asset(
    *,
    alex_root: Path | None = None,
    urdf_path: Path | None = None,
    manifest_dir: Path | None = None,
) -> AlexModelAsset:
    """Resolve the static Alex V2 asset without importing Isaac Sim."""

    selected_urdf = urdf_path if urdf_path is not None else default_v2_urdf(alex_root)
    selected_urdf = selected_urdf.expanduser().resolve()
    if not selected_urdf.is_file():
        raise FileNotFoundError(f"Alex V2 URDF not found: {selected_urdf}")
    unresolved_meshes = unresolved_urdf_mesh_references(selected_urdf)
    if unresolved_meshes:
        raise RuntimeError(
            "Alex V2 URDF has unresolved mesh references: "
            + ", ".join(unresolved_meshes)
        )
    manifest = {
        "schema_version": 2,
        "model": "v2",
        "profile": ALEX_V2_PROFILE,
        "source": "alex_v2_static_assets",
        "urdf_path": str(selected_urdf),
        "urdf_sha256": sha256_file(selected_urdf),
        "meshes": mesh_inventory(selected_urdf),
        "sensor_frames": parse_head_sensor_frames(selected_urdf),
    }
    manifest = _json_mapping(manifest)
    fingerprint = fingerprint_mapping(manifest)
    manifest_root = (manifest_dir or DEFAULT_MANIFEST_DIR).expanduser()
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = (manifest_root / f"{fingerprint}.json").resolve()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return AlexModelAsset(
        model="v2",
        profile=ALEX_V2_PROFILE,
        urdf_path=selected_urdf,
        manifest_path=manifest_path,
        manifest=manifest,
        fingerprint=fingerprint,
    )


def importer_settings() -> dict[str, Any]:
    return {
        "merge_fixed_joints": True,
        "merge_mesh": False,
        "run_asset_transformer": False,
    }


def isaaclab_importer_settings(
    asset: AlexModelAsset,
    *,
    cfg_factory: Any | None = None,
) -> dict[str, Any]:
    """Bind the direct importer to the shared Alex V2 Isaac Lab config.

    The factory import stays inside this function so importing the generic
    showcase helpers does not require Isaac Sim or Isaac Lab.
    """

    if cfg_factory is None:
        from ihmc_alex_isaaclab.robots.alex_v2 import make_alex_v2_cfg

        cfg_factory = make_alex_v2_cfg
    cfg = cfg_factory(str(asset.urdf_path), fix_base=True, variant="standard")
    configured_path = Path(cfg.spawn.asset_path).expanduser().resolve()
    if configured_path != asset.urdf_path.resolve():
        raise RuntimeError(
            "Alex V2 factory selected "
            f"{configured_path}, expected {asset.urdf_path.resolve()}"
        )
    settings = importer_settings()
    settings.update(
        {
            "fix_base": bool(cfg.spawn.fix_base),
            "merge_fixed_joints": bool(cfg.spawn.merge_fixed_joints),
            "collision_from_visuals": bool(cfg.spawn.collision_from_visuals),
            "allow_self_collision": bool(cfg.spawn.self_collision),
        }
    )
    return settings


def build_cache_descriptor(
    asset: AlexModelAsset,
    *,
    importer_settings: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the content-addressed USD cache descriptor."""

    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "model": asset.model,
        "profile": asset.profile,
        "model_fingerprint": asset.fingerprint,
        "urdf_sha256": sha256_file(asset.urdf_path),
        "importer_settings": _json_mapping(importer_settings),
        "runtime": _json_mapping(runtime),
    }
    return {**payload, "cache_key": fingerprint_mapping(payload)}


def cache_directory(cache_root: Path, descriptor: Mapping[str, Any]) -> Path:
    return cache_root / str(descriptor["model"]) / str(descriptor["cache_key"])


def load_cached_usd(
    cache_root: Path,
    descriptor: Mapping[str, Any],
    *,
    require_real_alex_v2: bool,
) -> tuple[Path, dict[str, Any]] | None:
    """Return only an exact, provenance-bearing cache entry."""

    directory = cache_directory(cache_root, descriptor)
    provenance_path = directory / CACHE_PROVENANCE_FILENAME
    if not provenance_path.is_file():
        return None
    try:
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
        validate_cache_record(
            record,
            descriptor,
            require_real_alex_v2=require_real_alex_v2,
        )
        relative_usd = record.get("usd_relative_path")
        if not isinstance(relative_usd, str) or not relative_usd.strip():
            raise CacheProvenanceError("cache record is missing usd_relative_path")
        usd_path = (directory / relative_usd).resolve()
        usd_path.relative_to(directory.resolve())
        if not usd_path.is_file():
            raise CacheProvenanceError(
                f"cache record references missing USD: {usd_path}"
            )
        if usd_path.suffix.lower() not in {".usd", ".usda", ".usdc"}:
            raise CacheProvenanceError(
                f"cache record references unsupported asset: {usd_path}"
            )
        return usd_path, dict(record)
    except (
        CacheProvenanceError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        if require_real_alex_v2:
            raise
        return None


def validate_cache_record(
    record: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    *,
    require_real_alex_v2: bool,
) -> None:
    if not isinstance(record, Mapping):
        raise CacheProvenanceError("cache provenance must be a JSON object")
    expected_fields = (
        "schema_version",
        "model",
        "profile",
        "model_fingerprint",
        "urdf_sha256",
        "importer_settings",
        "runtime",
        "cache_key",
    )
    missing = [name for name in expected_fields if name not in record]
    if missing:
        raise CacheProvenanceError(
            f"cache provenance is missing fields: {', '.join(missing)}"
        )
    for name in expected_fields:
        if record[name] != descriptor[name]:
            raise CacheProvenanceError(
                f"cache provenance mismatch for {name}: "
                f"{record[name]!r} != {descriptor[name]!r}"
            )
    if require_real_alex_v2 and record["model"] != "v2":
        raise CacheProvenanceError(
            "strict Alex V2 mode rejected a non-V2 USD cache entry"
        )
    if require_real_alex_v2 and not str(record["model_fingerprint"]).strip():
        raise CacheProvenanceError("strict Alex V2 mode requires a model fingerprint")


def write_cache_record(
    cache_root: Path,
    descriptor: Mapping[str, Any],
    usd_path: Path,
) -> Path:
    directory = cache_directory(cache_root, descriptor).resolve()
    resolved_usd = usd_path.resolve()
    try:
        relative_usd = resolved_usd.relative_to(directory)
    except ValueError as exc:
        raise ValueError(
            f"imported USD {resolved_usd} is outside cache directory {directory}"
        ) from exc
    directory.mkdir(parents=True, exist_ok=True)
    provenance_path = directory / CACHE_PROVENANCE_FILENAME
    record = {**dict(descriptor), "usd_relative_path": relative_usd.as_posix()}
    provenance_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return provenance_path


def strict_v2_evidence_errors(
    evidence: Mapping[str, Any],
    *,
    check_files: bool = False,
) -> tuple[str, ...]:
    """Return every reason the evidence cannot claim a real Alex V2 run."""

    errors: list[str] = []
    asset = evidence.get("model_asset")
    if not isinstance(asset, Mapping):
        errors.append("missing model_asset provenance")
        asset = {}
    if asset.get("model") != "v2":
        errors.append("model_asset is not V2")
    if asset.get("profile") != ALEX_V2_PROFILE:
        errors.append("model_asset has the wrong V2 profile")
    if not str(asset.get("fingerprint", "")).strip():
        errors.append("model_asset fingerprint is missing")
    if not isinstance(asset.get("manifest"), Mapping) or not asset.get("manifest"):
        errors.append("model_asset manifest is missing")
    if not str(asset.get("manifest_path", "")).strip():
        errors.append("model_asset manifest path is missing")
    actual_runtime = evidence.get("isaac_runtime", {})
    if not isinstance(actual_runtime, Mapping) or not actual_runtime:
        errors.append("active Isaac runtime provenance is missing")
    else:
        isaac_sim_version = str(actual_runtime.get("isaac_sim", "")).strip()
        if not isaac_sim_version or isaac_sim_version == "unknown":
            errors.append("active isaac_sim version is missing")

    conversion = evidence.get("alex_usd_conversion")
    if not isinstance(conversion, Mapping):
        errors.append("missing USD conversion provenance")
        conversion = {}
    if conversion.get("model") != "v2":
        errors.append("USD conversion/cache is not V2")
    if conversion.get("model_fingerprint") != asset.get("fingerprint"):
        errors.append("USD conversion fingerprint does not match the model manifest")
    if not str(conversion.get("cache_key", "")).strip():
        errors.append("USD cache key is missing")
    if not str(conversion.get("cache_provenance_path", "")).strip():
        errors.append("USD cache provenance path is missing")

    if evidence.get("scene_provenance") == "authored_fallback_room":
        errors.append("procedural fallback room is not allowed")
    if evidence.get("scene_provenance") != "ithor_floorplan1":
        errors.append("real iTHOR scene provenance is missing")

    robot = evidence.get("robot_import")
    if not isinstance(robot, Mapping):
        errors.append("missing robot import provenance")
        robot = {}
    if robot.get("provenance") != "real_urdf_import":
        errors.append("proxy robot is not allowed")
    if robot.get("model") != "v2":
        errors.append("imported robot is not V2")
    if robot.get("model_fingerprint") != asset.get("fingerprint"):
        errors.append("robot import fingerprint does not match the model manifest")
    head_path = str(robot.get("head_prim_path", ""))
    if not head_path or head_path.rsplit("/", 1)[-1] != "HEAD_LINK":
        errors.append("exact HEAD_LINK prim is missing")

    mount = evidence.get("microphone_mount")
    if not isinstance(mount, Mapping):
        errors.append("microphone mount transform is missing")
    elif mount.get("parent_prim_path") != head_path:
        errors.append("microphone array is not mounted below HEAD_LINK")

    recreated = evidence.get("recreated_sensor_frames")
    recreated_frames = (
        recreated.get("frames", {}) if isinstance(recreated, Mapping) else {}
    )
    if not isinstance(recreated_frames, Mapping):
        recreated_frames = {}
    for required_frame in ("HEAD_ZED_X_MINI_FRAME", "HEAD_IMU_FRAME"):
        if required_frame not in recreated_frames:
            errors.append(f"recreated {required_frame} is missing")
    if check_files:
        errors.extend(_strict_v2_file_errors(evidence, asset, conversion, robot))
    return tuple(errors)


def require_strict_v2_evidence(
    evidence: Mapping[str, Any],
    *,
    check_files: bool = False,
) -> None:
    errors = strict_v2_evidence_errors(evidence, check_files=check_files)
    if errors:
        raise RuntimeError("Strict Alex V2 evidence rejected: " + "; ".join(errors))


def unresolved_urdf_mesh_references(urdf_path: Path) -> tuple[str, ...]:
    """Return missing or non-local mesh references from a derived URDF."""

    try:
        root = ET.parse(urdf_path).getroot()
    except (ET.ParseError, OSError) as exc:
        return (f"invalid URDF {urdf_path}: {exc}",)
    unresolved: list[str] = []
    for mesh in root.findall(".//mesh"):
        reference = str(mesh.attrib.get("filename", "")).strip()
        if not reference:
            unresolved.append("<missing filename>")
            continue
        parsed = urlparse(reference)
        if parsed.scheme == "file":
            candidate = Path(unquote(parsed.path))
        elif parsed.scheme:
            unresolved.append(reference)
            continue
        else:
            candidate = Path(reference)
            if not candidate.is_absolute():
                candidate = urdf_path.parent / candidate
        if not candidate.is_file():
            unresolved.append(reference)
    return tuple(sorted(set(unresolved)))


def _strict_v2_file_errors(
    evidence: Mapping[str, Any],
    asset: Mapping[str, Any],
    conversion: Mapping[str, Any],
    robot: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    urdf_path = Path(str(asset.get("urdf_path", ""))).expanduser()
    if not urdf_path.is_file():
        errors.append("V2 URDF provenance path is missing")
    else:
        unresolved = unresolved_urdf_mesh_references(urdf_path)
        if unresolved:
            errors.append("V2 URDF has unresolved mesh references")
        manifest_value = asset.get("manifest", {})
        expected_sha = (
            str(manifest_value.get("urdf_sha256", ""))
            if isinstance(manifest_value, Mapping)
            else ""
        )
        if not expected_sha or sha256_file(urdf_path) != expected_sha:
            errors.append("V2 URDF hash does not match the model manifest")

    manifest_path = Path(str(asset.get("manifest_path", ""))).expanduser()
    if not manifest_path.is_file():
        errors.append("V2 manifest provenance file is missing")
    else:
        try:
            if _read_json_mapping(manifest_path) != _json_mapping(
                asset.get("manifest", {})
            ):
                errors.append("V2 manifest provenance changed during the run")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            errors.append("V2 manifest provenance is unreadable")

    provenance_path = Path(
        str(conversion.get("cache_provenance_path", ""))
    ).expanduser()
    if not provenance_path.is_file():
        errors.append("USD cache provenance file is missing")
    else:
        try:
            record = _read_json_mapping(provenance_path)
            descriptor_payload = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "model": asset.get("model"),
                "profile": asset.get("profile"),
                "model_fingerprint": asset.get("fingerprint"),
                "urdf_sha256": sha256_file(urdf_path),
                "importer_settings": _json_mapping(
                    conversion.get("importer_settings", {})
                ),
                "runtime": _json_mapping(conversion.get("runtime", {})),
            }
            expected_descriptor = {
                **descriptor_payload,
                "cache_key": fingerprint_mapping(descriptor_payload),
            }
            validate_cache_record(
                record,
                expected_descriptor,
                require_real_alex_v2=True,
            )
            if conversion.get("cache_key") != expected_descriptor["cache_key"]:
                errors.append("USD cache key no longer matches the V2 inputs")
        except (
            CacheProvenanceError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            errors.append("USD cache provenance is unreadable")

    usd_path = Path(str(conversion.get("usd_path", ""))).expanduser()
    if not usd_path.is_file():
        errors.append("imported V2 USD is missing")
    referenced_usd = Path(str(robot.get("referenced_usd", ""))).expanduser()
    if not referenced_usd.is_file():
        errors.append("robot referenced V2 USD is missing")
    elif usd_path.is_file() and referenced_usd.resolve() != usd_path.resolve():
        errors.append("robot referenced USD does not match the cache provenance")

    scene_path = Path(str(evidence.get("scene_usd", ""))).expanduser()
    if not scene_path.is_file():
        errors.append("real iTHOR scene provenance file is missing")
    return errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_mapping(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _json_mapping(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), sort_keys=True, default=str))


def _read_json_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"expected a JSON object in {path}")
    return _json_mapping(value)
