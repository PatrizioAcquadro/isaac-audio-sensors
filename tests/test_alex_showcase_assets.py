"""Pure tests for Alex V1/V2 showcase selection and provenance policy."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_assets_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "alex_showcase_assets.py"
    )
    spec = importlib.util.spec_from_file_location("alex_showcase_assets", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cli_defaults_to_validated_v2_and_decouples_scene(tmp_path):
    assets = _load_assets_module()

    defaults = assets.parse_arguments([])
    assert defaults.alex_model == "v2"
    assert defaults.scene_usd.name == "scene.usda"

    sdk_root = tmp_path / "sdk"
    scene_usd = tmp_path / "custom_scene.usda"
    args = assets.parse_arguments(
        [
            "--alex-model",
            "v2",
            "--alex-sdk-root",
            str(sdk_root),
            "--scene-usd",
            str(scene_usd),
            "--require-real-alex-v2",
        ]
    )

    assert args.alex_sdk_root == sdk_root
    assert args.scene_usd == scene_usd
    assert args.require_real_alex_v2 is True


def test_cli_rejects_strict_v2_mode_with_v1():
    assets = _load_assets_module()

    with pytest.raises(SystemExit) as exc_info:
        assets.parse_arguments(["--alex-model", "v1", "--require-real-alex-v2"])

    assert exc_info.value.code == 2


def test_v1_asset_resolution_is_deterministic_and_preserved(tmp_path):
    assets = _load_assets_module()
    urdf = tmp_path / "alex_v1.urdf"
    urdf.write_text("<robot name='AlexV1'/>", encoding="utf-8")

    first = assets.resolve_model_asset("v1", v1_urdf=urdf)
    second = assets.resolve_model_asset("v1", v1_urdf=urdf)

    assert first.model == "v1"
    assert first.urdf_path == urdf
    assert first.fingerprint == second.fingerprint
    assert first.manifest["urdf_sha256"] == assets.sha256_file(urdf)
    assert assets.importer_settings_for_model("v1")["merge_fixed_joints"] is False
    assert assets.importer_settings_for_model("v2")["merge_fixed_joints"] is True


def test_v2_asset_resolution_uses_shared_bridge_contract(tmp_path):
    assets = _load_assets_module()
    sdk_root = tmp_path / "ihmc-alex-sdk"
    sdk_root.mkdir()
    bridge = tmp_path / "builder.py"
    bridge.write_text(
        """
import json
from types import SimpleNamespace

PROFILE = "alex_v2_fullbody_standard_no_external_hands"

def build_alex_v2_asset(sdk_root=None, cache_root=None, strict_revision=True):
    output = sdk_root / "generated"
    output.mkdir(parents=True, exist_ok=True)
    urdf = output / "alex_v2.urdf"
    urdf.write_text("<robot name='AlexV2'/>", encoding="utf-8")
    manifest = {"profile": PROFILE, "sdk_sha": "0789e4d"}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return SimpleNamespace(
        urdf_path=urdf,
        manifest_path=manifest_path,
        manifest=manifest,
        fingerprint="v2-fingerprint",
    )
""",
        encoding="utf-8",
    )

    resolved = assets.resolve_model_asset(
        "v2",
        sdk_root=sdk_root,
        bridge_path=bridge,
    )

    assert resolved.model == "v2"
    assert resolved.profile == assets.ALEX_V2_PROFILE
    assert resolved.urdf_path.is_file()
    assert resolved.manifest_path.is_file()
    assert resolved.manifest["sdk_sha"] == "0789e4d"
    assert resolved.fingerprint == "v2-fingerprint"


def test_usd_cache_is_exactly_keyed_by_model_importer_and_runtime(tmp_path):
    assets = _load_assets_module()
    urdf = tmp_path / "alex_v2.urdf"
    urdf.write_text("<robot name='AlexV2'/>", encoding="utf-8")
    asset = assets.AlexModelAsset(
        model="v2",
        profile=assets.ALEX_V2_PROFILE,
        urdf_path=urdf,
        manifest_path=tmp_path / "manifest.json",
        manifest={"profile": assets.ALEX_V2_PROFILE},
        fingerprint="model-fingerprint",
    )
    settings = assets.importer_settings_for_model("v2")
    descriptor = assets.build_cache_descriptor(
        asset,
        importer_settings=settings,
        runtime={"isaacsim": "6.0.1", "python": "3.12.0"},
    )
    cache_root = tmp_path / "cache"
    directory = assets.cache_directory(cache_root, descriptor)
    directory.mkdir(parents=True)
    usd = directory / "alex_v2.usda"
    usd.write_text("#usda 1.0", encoding="utf-8")
    provenance = assets.write_cache_record(cache_root, descriptor, usd)

    hit = assets.load_cached_usd(
        cache_root,
        descriptor,
        require_real_alex_v2=True,
    )
    assert hit is not None
    assert hit[0] == usd
    assert hit[1]["model_fingerprint"] == "model-fingerprint"

    other_runtime = assets.build_cache_descriptor(
        asset,
        importer_settings=settings,
        runtime={"isaacsim": "6.1.0", "python": "3.12.0"},
    )
    assert other_runtime["cache_key"] != descriptor["cache_key"]
    assert (
        assets.load_cached_usd(
            cache_root,
            other_runtime,
            require_real_alex_v2=True,
        )
        is None
    )

    poisoned = json.loads(provenance.read_text(encoding="utf-8"))
    poisoned["model"] = "v1"
    provenance.write_text(json.dumps(poisoned), encoding="utf-8")
    with pytest.raises(assets.CacheProvenanceError, match="mismatch for model"):
        assets.load_cached_usd(
            cache_root,
            descriptor,
            require_real_alex_v2=True,
        )


def test_strict_v2_evidence_accepts_only_real_provenanced_hierarchy():
    assets = _load_assets_module()
    fingerprint = "manifest-fingerprint"
    head_path = "/World/Alex/PELVIS_LINK/TORSO_LINK/NECK_Z_LINK/HEAD_LINK"
    evidence = {
        "model_asset": {
            "model": "v2",
            "profile": assets.ALEX_V2_PROFILE,
            "fingerprint": fingerprint,
            "manifest_path": "/cache/manifest.json",
            "manifest": {"profile": assets.ALEX_V2_PROFILE},
        },
        "alex_usd_conversion": {
            "model": "v2",
            "model_fingerprint": fingerprint,
            "cache_key": "cache-key",
            "cache_provenance_path": "/cache/cache_provenance.json",
        },
        "scene_provenance": "alex_robot_ithor_floorplan1",
        "robot_import": {
            "provenance": "real_urdf_import",
            "model": "v2",
            "model_fingerprint": fingerprint,
            "head_prim_path": head_path,
        },
        "microphone_mount": {
            "parent_prim_path": head_path,
            "local_translation_m": [0.0, 0.0, 0.12],
        },
        "recreated_sensor_frames": {
            "frames": {
                "HEAD_ZED_X_MINI_FRAME": f"{head_path}/HEAD_ZED_X_MINI_FRAME",
                "HEAD_IMU_FRAME": f"{head_path}/HEAD_IMU_FRAME",
            }
        },
    }

    assert assets.strict_v2_evidence_errors(evidence) == ()
    assets.require_strict_v2_evidence(evidence)

    proxy = {**evidence, "robot_import": {**evidence["robot_import"]}}
    proxy["robot_import"]["provenance"] = "fallback_proxy"
    assert "proxy robot is not allowed" in assets.strict_v2_evidence_errors(proxy)

    fallback = {**evidence, "scene_provenance": "authored_fallback_room"}
    assert "procedural fallback room is not allowed" in (
        assets.strict_v2_evidence_errors(fallback)
    )

    no_head = {**evidence, "robot_import": {**evidence["robot_import"]}}
    no_head["robot_import"]["head_prim_path"] = "/World/Alex"
    errors = assets.strict_v2_evidence_errors(no_head)
    assert "exact HEAD_LINK prim is missing" in errors
    assert "microphone array is not mounted below HEAD_LINK" in errors

    missing_manifest = {**evidence, "model_asset": {**evidence["model_asset"]}}
    missing_manifest["model_asset"]["manifest"] = {}
    assert "model_asset manifest is missing" in (
        assets.strict_v2_evidence_errors(missing_manifest)
    )


def test_strict_v2_file_gate_rechecks_manifest_cache_scene_and_meshes(tmp_path):
    assets = _load_assets_module()
    mesh = tmp_path / "head.stl"
    mesh.write_bytes(b"solid head\nendsolid head\n")
    urdf = tmp_path / "alex_v2.urdf"
    urdf.write_text(
        f"<robot name='AlexV2'><link name='HEAD_LINK'><visual><geometry>"
        f"<mesh filename='{mesh.as_uri()}'/>"
        "</geometry></visual></link></robot>",
        encoding="utf-8",
    )
    manifest = {
        "profile": assets.ALEX_V2_PROFILE,
        "urdf_sha256": assets.sha256_file(urdf),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    usd = tmp_path / "alex_v2.usda"
    usd.write_text("#usda 1.0", encoding="utf-8")
    fingerprint = "manifest-fingerprint"
    importer_settings = assets.importer_settings_for_model("v2")
    runtime = {"isaac_sim": "6.0.1-rc.7", "isaac_lab": "3.0.0"}
    descriptor = assets.build_cache_descriptor(
        assets.AlexModelAsset(
            model="v2",
            profile=assets.ALEX_V2_PROFILE,
            urdf_path=urdf,
            manifest_path=manifest_path,
            manifest=manifest,
            fingerprint=fingerprint,
        ),
        importer_settings=importer_settings,
        runtime=runtime,
    )
    cache_provenance = tmp_path / "cache_provenance.json"
    cache_provenance.write_text(
        json.dumps(descriptor),
        encoding="utf-8",
    )
    scene = tmp_path / "scene.usda"
    scene.write_text("#usda 1.0", encoding="utf-8")
    head_path = "/World/Alex/PELVIS_LINK/TORSO_LINK/NECK_Z_LINK/HEAD_LINK"
    evidence = {
        "scene_usd": str(scene),
        "scene_provenance": "alex_robot_ithor_floorplan1",
        "model_asset": {
            "model": "v2",
            "profile": assets.ALEX_V2_PROFILE,
            "fingerprint": fingerprint,
            "urdf_path": str(urdf),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
        },
        "alex_usd_conversion": {
            "model": "v2",
            "model_fingerprint": fingerprint,
            "cache_key": descriptor["cache_key"],
            "cache_provenance_path": str(cache_provenance),
            "usd_path": str(usd),
            "importer_settings": importer_settings,
            "runtime": runtime,
        },
        "robot_import": {
            "provenance": "real_urdf_import",
            "model": "v2",
            "model_fingerprint": fingerprint,
            "head_prim_path": head_path,
            "referenced_usd": str(usd),
        },
        "microphone_mount": {
            "parent_prim_path": head_path,
            "local_translation_m": [0.0, 0.0, 0.12],
        },
        "recreated_sensor_frames": {
            "frames": {
                "HEAD_ZED_X_MINI_FRAME": f"{head_path}/HEAD_ZED_X_MINI_FRAME",
                "HEAD_IMU_FRAME": f"{head_path}/HEAD_IMU_FRAME",
            }
        },
    }

    assets.require_strict_v2_evidence(evidence, check_files=True)

    mesh.unlink()
    assert "V2 URDF has unresolved mesh references" in (
        assets.strict_v2_evidence_errors(evidence, check_files=True)
    )


def test_unresolved_mesh_gate_rejects_package_and_missing_file_references(tmp_path):
    assets = _load_assets_module()
    urdf = tmp_path / "alex_v2.urdf"
    urdf.write_text(
        """<robot name="AlexV2">
        <link name="HEAD_LINK">
          <visual><geometry><mesh filename="package://alex/missing.stl"/></geometry></visual>
          <collision>
            <geometry><mesh filename="also_missing.stl"/></geometry>
          </collision>
        </link>
        </robot>""",
        encoding="utf-8",
    )

    assert assets.unresolved_urdf_mesh_references(urdf) == (
        "also_missing.stl",
        "package://alex/missing.stl",
    )
