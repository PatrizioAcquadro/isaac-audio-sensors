"""Pure Alex model, cache, and provenance policy for the live showcase.

This module deliberately has no Isaac Sim imports.  The live script uses it to
select either the preserved Alex V1 asset or the shared IHMC Alex V2 bridge,
and unit tests can exercise the selection and strict-evidence rules without
starting Kit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ALEX_V2_PROFILE = "alex_v2_fullbody_standard_no_external_hands"
V1_PROFILE = "alex_v1_fullbody_robot_accurate_full_collisions"
CACHE_SCHEMA_VERSION = 1
CACHE_PROVENANCE_FILENAME = "cache_provenance.json"


def default_alex_root() -> Path:
    return Path.home() / "Desktop" / "Alex-robot"


def default_sdk_root() -> Path:
    configured = os.environ.get("IHMC_ALEX_SDK_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Desktop" / "ihmc-alex-sdk"


def default_scene_usd() -> Path:
    return (
        default_alex_root()
        / "assets"
        / "usd"
        / "scenes"
        / "ithor"
        / "FloorPlan1_physics"
        / "scene.usda"
    )


def default_v1_urdf() -> Path:
    return (
        default_alex_root()
        / "alex_models"
        / "alex_V1_description"
        / "rl_urdf"
        / "alex_v1.rlModel_fullBody_robotAccurate_fullCollisions.urdf"
    )


@dataclass(frozen=True)
class AlexModelAsset:
    """Resolved URDF plus immutable model provenance."""

    model: str
    profile: str
    urdf_path: Path
    manifest_path: Path | None
    manifest: Mapping[str, Any]
    fingerprint: str
    bridge_root: Path | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "profile": self.profile,
            "urdf_path": str(self.urdf_path),
            "manifest_path": (
                None if self.manifest_path is None else str(self.manifest_path)
            ),
            "manifest": dict(self.manifest),
            "fingerprint": self.fingerprint,
            "bridge_root": (
                None if self.bridge_root is None else str(self.bridge_root)
            ),
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
        "--alex-model",
        choices=("v1", "v2"),
        default="v2",
        help=(
            "Alex generation to import (default: validated V2; use V1 to "
            "reproduce legacy runs)."
        ),
    )
    parser.add_argument(
        "--alex-sdk-root",
        type=Path,
        default=default_sdk_root(),
        help="Full IHMC Alex SDK checkout used by the V2 asset bridge.",
    )
    parser.add_argument(
        "--scene-usd",
        type=Path,
        default=default_scene_usd(),
        help="iTHOR scene USD, independent of the selected robot model.",
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
    try:
        validate_request(args.alex_model, args.require_real_alex_v2)
    except ValueError as exc:
        parser.error(str(exc))
    args.alex_sdk_root = args.alex_sdk_root.expanduser()
    args.scene_usd = args.scene_usd.expanduser()
    return args


def validate_request(alex_model: str, require_real_alex_v2: bool) -> None:
    if alex_model not in {"v1", "v2"}:
        raise ValueError(f"unsupported Alex model {alex_model!r}")
    if require_real_alex_v2 and alex_model != "v2":
        raise ValueError("--require-real-alex-v2 requires --alex-model v2")


def resolve_model_asset(
    model: str,
    *,
    sdk_root: Path | None = None,
    v1_urdf: Path | None = None,
    bridge_path: Path | None = None,
    strict_revision: bool = True,
) -> AlexModelAsset:
    """Resolve the selected Alex asset without importing Isaac Sim."""

    validate_request(model, False)
    if model == "v1":
        urdf_path = (v1_urdf or default_v1_urdf()).expanduser().resolve()
        if not urdf_path.is_file():
            raise FileNotFoundError(f"Alex V1 URDF not found: {urdf_path}")
        manifest = {
            "schema_version": 1,
            "model": "v1",
            "profile": V1_PROFILE,
            "source": "preserved_alex_robot_checkout",
            "urdf_sha256": sha256_file(urdf_path),
        }
        return AlexModelAsset(
            model="v1",
            profile=V1_PROFILE,
            urdf_path=urdf_path,
            manifest_path=None,
            manifest=manifest,
            fingerprint=fingerprint_mapping(manifest),
        )

    selected_bridge = bridge_path or (
        default_alex_root() / "alex_models" / "alex_V2_isaacsim" / "builder.py"
    )
    selected_bridge = selected_bridge.expanduser().resolve()
    if not selected_bridge.is_file():
        raise FileNotFoundError(
            "Alex V2 bridge not found: "
            f"{selected_bridge}. Keep Alex-robot in place and add the shared bridge."
        )
    module_name = "_isaac_audio_alex_v2_builder"
    spec = importlib.util.spec_from_file_location(module_name, selected_bridge)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Alex V2 bridge from {selected_bridge}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    build_asset = getattr(module, "build_alex_v2_asset", None)
    if not callable(build_asset):
        raise RuntimeError(
            f"Alex V2 bridge {selected_bridge} has no build_alex_v2_asset()"
        )
    built = build_asset(
        sdk_root=(sdk_root or default_sdk_root()).expanduser(),
        cache_root=None,
        strict_revision=strict_revision,
    )
    urdf_path = Path(built.urdf_path).expanduser().resolve()
    manifest_path = Path(built.manifest_path).expanduser().resolve()
    manifest = _json_mapping(built.manifest)
    fingerprint = str(built.fingerprint).strip()
    if not urdf_path.is_file():
        raise RuntimeError(f"Alex V2 bridge returned missing URDF: {urdf_path}")
    if not manifest_path.is_file():
        raise RuntimeError(f"Alex V2 bridge returned missing manifest: {manifest_path}")
    if not manifest:
        raise RuntimeError("Alex V2 bridge returned an empty manifest")
    if not fingerprint:
        raise RuntimeError("Alex V2 bridge returned an empty fingerprint")
    manifest_profile = str(manifest.get("profile", ALEX_V2_PROFILE))
    if manifest_profile != ALEX_V2_PROFILE:
        raise RuntimeError(
            "Alex V2 bridge returned unexpected profile "
            f"{manifest_profile!r}; expected {ALEX_V2_PROFILE!r}"
        )
    manifest_on_disk = _read_json_mapping(manifest_path)
    if manifest_on_disk != manifest:
        raise RuntimeError(
            "Alex V2 bridge return value does not match its manifest on disk: "
            f"{manifest_path}"
        )
    unresolved_meshes = unresolved_urdf_mesh_references(urdf_path)
    if unresolved_meshes:
        raise RuntimeError(
            "Alex V2 bridge returned unresolved URDF mesh references: "
            + ", ".join(unresolved_meshes)
        )
    return AlexModelAsset(
        model="v2",
        profile=ALEX_V2_PROFILE,
        urdf_path=urdf_path,
        manifest_path=manifest_path,
        manifest=manifest,
        fingerprint=fingerprint,
        bridge_root=selected_bridge.parent,
    )


def importer_settings_for_model(model: str) -> dict[str, Any]:
    validate_request(model, False)
    return {
        "merge_fixed_joints": model == "v2",
        "merge_mesh": False,
        "run_asset_transformer": False,
    }


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
    if evidence.get("scene_provenance") != "alex_robot_ithor_floorplan1":
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
