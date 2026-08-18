"""Pure tests for the static Alex V2 showcase asset and provenance policy."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _write_static_v2_asset(
    root: Path,
    *,
    mesh_bytes: bytes = b"v 0 0 0\n",
    mesh_name: str = "head.obj",
    include_imu_joint: bool = True,
) -> Path:
    meshes = root / "meshes"
    meshes.mkdir(parents=True, exist_ok=True)
    (meshes / mesh_name).write_bytes(mesh_bytes)
    urdf_dir = root / "urdf"
    urdf_dir.mkdir(parents=True, exist_ok=True)
    imu_joint = (
        """
        <joint name="HEAD_IMU_JOINT" type="fixed">
          <parent link="HEAD_LINK"/>
          <child link="HEAD_IMU_LINK"/>
          <origin xyz="-0.024326 -0.0022529 0.074258" rpy="0.0 0.0 0.0"/>
        </joint>
        <link name="HEAD_IMU_LINK"/>
        """
        if include_imu_joint
        else ""
    )
    urdf = urdf_dir / "alex_v2.urdf"
    urdf.write_text(
        f"""<robot name="AlexV2">
        <link name="HEAD_LINK">
          <visual><geometry>
            <mesh filename="../meshes/{mesh_name}"/>
          </geometry></visual>
        </link>
        <joint name="HEAD_ZED_X_MINI_JOINT" type="fixed">
          <parent link="HEAD_LINK"/>
          <child link="HEAD_ZED_X_MINI_LINK"/>
          <origin xyz="0.11603 0.009965 -0.02983" rpy="0.0 0.3633 0.0"/>
        </joint>
        <link name="HEAD_ZED_X_MINI_LINK"/>
        {imu_joint}
        </robot>""",
        encoding="utf-8",
    )
    return urdf


def test_cli_defaults_to_static_v2_and_decouples_scene(tmp_path):
    assets = _load_assets_module()

    defaults = assets.parse_arguments([])
    assert defaults.alex_root == (
        Path.home() / "Desktop" / "Alex" / "assets" / "robots" / "alex_v2"
    )
    assert defaults.scene_usd == (
        Path.home()
        / "Desktop"
        / "CombinedScene"
        / "FloorPlan1_updated_physics"
        / "scene.usda"
    )
    assert defaults.require_real_alex_v2 is False

    alex_root = tmp_path / "Alex"
    scene_usd = tmp_path / "custom_scene.usda"
    args = assets.parse_arguments(
        [
            "--alex-root",
            str(alex_root),
            "--scene-usd",
            str(scene_usd),
            "--require-real-alex-v2",
        ]
    )

    assert args.alex_root == alex_root
    assert args.scene_usd == scene_usd
    assert args.require_real_alex_v2 is True


def test_runtime_version_prefers_active_distribution_and_falls_back(
    tmp_path, monkeypatch
):
    assets = _load_assets_module()
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "VERSION").write_text("6.0.1-rc.7\n", encoding="utf-8")

    monkeypatch.setattr(assets.importlib.metadata, "version", lambda _name: "5.1.0.0")
    assert (
        assets.installed_runtime_version("isaacsim", "UNSET_RUNTIME_ROOT", root)
        == "5.1.0.0"
    )

    def missing(_name):
        raise assets.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(assets.importlib.metadata, "version", missing)
    assert (
        assets.installed_runtime_version("isaacsim", "UNSET_RUNTIME_ROOT", root)
        == "6.0.1-rc.7"
    )


def test_v2_static_asset_resolution_is_deterministic(tmp_path):
    assets = _load_assets_module()
    root = tmp_path / "Alex"
    urdf = _write_static_v2_asset(root)
    manifest_dir = tmp_path / "manifests"

    first = assets.resolve_v2_asset(alex_root=root, manifest_dir=manifest_dir)
    second = assets.resolve_v2_asset(alex_root=root, manifest_dir=manifest_dir)

    assert first.model == "v2"
    assert first.profile == assets.ALEX_V2_PROFILE
    assert first.urdf_path == urdf.resolve()
    assert first.fingerprint == second.fingerprint
    assert first.manifest_path.is_file()
    on_disk = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert on_disk == dict(first.manifest)
    assert first.manifest["source"] == "alex_v2_static_assets"
    assert first.manifest["urdf_sha256"] == assets.sha256_file(urdf)
    assert first.manifest["meshes"]["../meshes/head.obj"] == assets.sha256_file(
        root / "meshes" / "head.obj"
    )
    zed = first.manifest["sensor_frames"]["HEAD_ZED_X_MINI_FRAME"]
    assert zed["parent_link"] == "HEAD_LINK"
    assert zed["xyz"] == [0.11603, 0.009965, -0.02983]
    assert zed["rpy"] == [0.0, 0.3633, 0.0]
    assert "HEAD_IMU_FRAME" in first.manifest["sensor_frames"]

    (root / "meshes" / "head.obj").write_bytes(b"different bytes")
    changed = assets.resolve_v2_asset(alex_root=root, manifest_dir=manifest_dir)
    assert changed.fingerprint != first.fingerprint


def test_isaaclab_factory_bridge_is_lazy_and_binds_importer(tmp_path):
    assets = _load_assets_module()
    root = tmp_path / "Alex"
    _write_static_v2_asset(root)
    asset = assets.resolve_v2_asset(alex_root=root, manifest_dir=tmp_path / "manifests")
    calls = []

    def factory(path, *, fix_base, variant):
        calls.append((path, fix_base, variant))
        return SimpleNamespace(
            spawn=SimpleNamespace(
                asset_path=path,
                fix_base=fix_base,
                merge_fixed_joints=True,
                collision_from_visuals=False,
                self_collision=True,
            )
        )

    settings = assets.isaaclab_importer_settings(asset, cfg_factory=factory)

    assert calls == [(str(asset.urdf_path), True, "standard")]
    assert settings == {
        "merge_fixed_joints": True,
        "merge_mesh": False,
        "run_asset_transformer": False,
        "fix_base": True,
        "collision_from_visuals": False,
        "allow_self_collision": True,
    }


def test_v2_static_resolution_rejects_bad_assets(tmp_path):
    assets = _load_assets_module()
    manifest_dir = tmp_path / "manifests"

    with pytest.raises(FileNotFoundError):
        assets.resolve_v2_asset(
            alex_root=tmp_path / "nowhere", manifest_dir=manifest_dir
        )

    missing_mesh_root = tmp_path / "missing-mesh"
    _write_static_v2_asset(missing_mesh_root)
    (missing_mesh_root / "meshes" / "head.obj").unlink()
    with pytest.raises(RuntimeError, match="unresolved mesh"):
        assets.resolve_v2_asset(alex_root=missing_mesh_root, manifest_dir=manifest_dir)

    no_imu_root = tmp_path / "no-imu"
    _write_static_v2_asset(no_imu_root, include_imu_joint=False)
    with pytest.raises(RuntimeError, match="HEAD_IMU_FRAME"):
        assets.resolve_v2_asset(alex_root=no_imu_root, manifest_dir=manifest_dir)

    convex_root = tmp_path / "convex"
    _write_static_v2_asset(convex_root, mesh_name="head_convex.stl")
    with pytest.raises(RuntimeError, match="non-OBJ"):
        assets.resolve_v2_asset(alex_root=convex_root, manifest_dir=manifest_dir)


def test_rpy_to_quaternion_wxyz():
    assets = _load_assets_module()

    assert assets.rpy_to_quaternion_wxyz([0.0, 0.0, 0.0]) == (1.0, 0.0, 0.0, 0.0)

    w, x, y, z = assets.rpy_to_quaternion_wxyz([0.0, 0.3633, 0.0])
    assert w == pytest.approx(math.cos(0.18165), abs=1e-9)
    assert x == pytest.approx(0.0, abs=1e-12)
    assert y == pytest.approx(math.sin(0.18165), abs=1e-9)
    assert z == pytest.approx(0.0, abs=1e-12)

    def qmul(a, b):
        aw, ax, ay, az = a
        bw, bx, by, bz = b
        return (
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        )

    roll, pitch, yaw = 0.1, 0.2, 0.3
    qx = (math.cos(roll / 2), math.sin(roll / 2), 0.0, 0.0)
    qy = (math.cos(pitch / 2), 0.0, math.sin(pitch / 2), 0.0)
    qz = (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))
    expected = qmul(qmul(qz, qy), qx)
    assert assets.rpy_to_quaternion_wxyz([roll, pitch, yaw]) == pytest.approx(
        expected, abs=1e-12
    )


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
    settings = assets.importer_settings()
    assert settings["merge_fixed_joints"] is True
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
            "manifest": {
                "profile": assets.ALEX_V2_PROFILE,
                "source": "alex_v2_static_assets",
            },
        },
        "isaac_runtime": {
            "isaac_sim": "6.0.1-rc.7",
            "isaac_lab": "3.0.0",
        },
        "alex_usd_conversion": {
            "model": "v2",
            "model_fingerprint": fingerprint,
            "cache_key": "cache-key",
            "cache_provenance_path": "/cache/cache_provenance.json",
        },
        "scene_provenance": "ithor_floorplan1",
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

    no_runtime = {**evidence}
    del no_runtime["isaac_runtime"]
    assert "active Isaac runtime provenance is missing" in (
        assets.strict_v2_evidence_errors(no_runtime)
    )

    unknown_runtime = {**evidence, "isaac_runtime": {"isaac_sim": "unknown"}}
    assert "active isaac_sim version is missing" in (
        assets.strict_v2_evidence_errors(unknown_runtime)
    )

    no_imu_frame = {
        **evidence,
        "recreated_sensor_frames": {
            "frames": {
                "HEAD_ZED_X_MINI_FRAME": f"{head_path}/HEAD_ZED_X_MINI_FRAME",
            }
        },
    }
    assert "recreated HEAD_IMU_FRAME is missing" in (
        assets.strict_v2_evidence_errors(no_imu_frame)
    )


def test_strict_v2_file_gate_rechecks_manifest_cache_scene_and_meshes(tmp_path):
    assets = _load_assets_module()
    mesh = tmp_path / "head.obj"
    mesh.write_bytes(b"v 0 0 0\n")
    urdf = tmp_path / "alex_v2.urdf"
    urdf.write_text(
        f"<robot name='AlexV2'><link name='HEAD_LINK'><visual><geometry>"
        f"<mesh filename='{mesh.as_uri()}'/>"
        "</geometry></visual></link></robot>",
        encoding="utf-8",
    )
    manifest = {
        "profile": assets.ALEX_V2_PROFILE,
        "source": "alex_v2_static_assets",
        "urdf_sha256": assets.sha256_file(urdf),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    usd = tmp_path / "alex_v2.usda"
    usd.write_text("#usda 1.0", encoding="utf-8")
    fingerprint = "manifest-fingerprint"
    importer_settings = assets.importer_settings()
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
        "scene_provenance": "ithor_floorplan1",
        "isaac_runtime": {
            "isaac_sim": "6.0.1-rc.7",
            "isaac_lab": "3.0.0",
        },
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

    original_urdf = urdf.read_text(encoding="utf-8")
    urdf.write_text(original_urdf + "\n<!-- tampered -->\n", encoding="utf-8")
    assert "V2 URDF hash does not match the model manifest" in (
        assets.strict_v2_evidence_errors(evidence, check_files=True)
    )
    urdf.write_text(original_urdf, encoding="utf-8")

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
