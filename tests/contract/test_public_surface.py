from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from isaac_audio_sensors import __version__
from isaac_audio_sensors.cli import main

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "isaac_audio_sensors"
ALLOWED_DEPENDENCIES = {
    "core": frozenset(),
    "recording": frozenset({"core"}),
    "isaac": frozenset({"core"}),
    "lab": frozenset({"core"}),
    "kit": frozenset({"core", "recording", "isaac"}),
    "schemas": frozenset({"core", "recording"}),
    "cli": frozenset({"core", "recording", "kit", "schemas"}),
}
PUBLIC_API_V2 = {
    "isaac_audio_sensors": ("__version__",),
    "isaac_audio_sensors.core": (
        "AudioDetection",
        "AudioSceneSnapshot",
        "AudioSensorFrame",
        "AudioSourceSpec",
        "AudioTimeWindow",
        "DoaEstimate",
        "MicrophoneArraySpec",
        "MicrophoneSpec",
        "Pose3D",
        "RoomAcousticsSpec",
        "SourceOcclusion",
    ),
    "isaac_audio_sensors.recording": (
        "AppendFrameResult",
        "AudioDatasetManifest",
        "CreationProvenance",
        "DatasetLayoutError",
        "DatasetSplitError",
        "DeviceProvenance",
        "Finding",
        "LoadedFrame",
        "ReplayEvent",
        "SessionDataset",
        "SessionRecorder",
        "SessionRecorderError",
        "SplitPlan",
        "Statistics",
        "ValidationReport",
        "apply_split_plan",
        "build_split_plan",
        "export_session_flac",
        "manifest_from_dict",
        "manifest_to_dict",
        "read_dataset_manifest",
        "read_split_plan",
        "replay_session",
        "validate_dataset",
        "write_dataset_manifest",
        "write_split_plan",
    ),
    "isaac_audio_sensors.isaac": (
        "AudioSensorReplicatorRecorder",
        "DiscoveredAudioArray",
        "DiscoveredAudioSource",
        "IsaacAudioArraySensor",
        "IsaacAudioDiscoveryCfg",
        "IsaacAudioDiscoveryResult",
        "IsaacAudioSceneBindingCfg",
        "IsaacStagePoseResolver",
        "ReplicatorIntegrationError",
        "ReplicatorRecorderStatus",
        "StagePose",
        "audio_sensor_frame_replicator_payload",
        "attach_microphone_array_attrs",
        "attach_microphone_attrs",
        "attach_sound_source_attrs",
        "build_stage_snapshot",
        "create_listener_prim",
        "create_sound_prim",
        "discover_stage_audio",
        "require_isaac_usd",
        "require_replicator_core",
        "resolve_world_pose",
    ),
    "isaac_audio_sensors.lab": (
        "AudioArraySensor",
        "AudioArraySensorCfg",
        "AudioArraySensorData",
        "EntityBindingCfg",
        "SourceEntityCfg",
    ),
    "isaac_audio_sensors.kit": ("ExtensionController",),
    "isaac_audio_sensors.schemas": (),
    "isaac_audio_sensors.schemas.generate": (
        "audio_calibration_profile_json_schema",
        "audio_dataset_manifest_json_schema",
        "audio_sensor_frame_json_schema",
        "write_json_schema",
    ),
}


def _package_dependencies(package: str) -> set[str]:
    dependencies: set[str] = set()
    target = PACKAGE_ROOT / package
    paths = (target.with_suffix(".py"),) if package == "cli" else target.rglob("*.py")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = (node.module or "",)
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if len(parts) > 1 and parts[0] == "isaac_audio_sensors":
                    dependency = parts[1]
                    if dependency != package:
                        dependencies.add(dependency)
    return dependencies


def _run_fresh_process(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(PACKAGE_ROOT.parent), env.get("PYTHONPATH", ""))
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_public_package_and_cli_version_match():
    result = subprocess.run(
        [sys.executable, "-m", "isaac_audio_sensors", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == __version__


def test_cli_import_is_lazy():
    completed = _run_fresh_process(
        """
        import sys
        import isaac_audio_sensors.cli

        forbidden = (
            "numpy",
            "isaac_audio_sensors.core.backends",
            "isaac_audio_sensors.kit",
            "isaac_audio_sensors.recording",
            "isaac_audio_sensors.schemas.generate",
        )
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in sys.modules
            for prefix in forbidden
        )
        """
    )
    assert completed.stderr == ""


def test_semantic_packages_follow_the_r5_dependency_graph():
    for package, allowed in ALLOWED_DEPENDENCIES.items():
        assert _package_dependencies(package) <= allowed


@pytest.mark.parametrize(("module_name", "exports"), PUBLIC_API_V2.items())
def test_curated_v2_exports_in_fresh_process(module_name, exports):
    resolve_exports = module_name != "isaac_audio_sensors.lab"
    completed = _run_fresh_process(
        f"""
        import importlib
        import sys

        module = importlib.import_module({module_name!r})
        exports = {list(exports)!r}
        assert module.__all__ == exports
        if {resolve_exports!r}:
            assert all(hasattr(module, name) for name in exports)

        optional = ("omni", "pxr", "isaaclab", "torch")
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in sys.modules
            for prefix in optional
        )

        if {module_name!r} == "isaac_audio_sensors":
            assert not any(
                name.startswith("isaac_audio_sensors.") for name in sys.modules
            )
        if {module_name!r} == "isaac_audio_sensors.core":
            forbidden = (
                "numpy",
                "isaac_audio_sensors.recording",
                "isaac_audio_sensors.isaac",
                "isaac_audio_sensors.lab",
                "isaac_audio_sensors.kit",
                "isaac_audio_sensors.core.backends",
                "isaac_audio_sensors.core.effects",
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in sys.modules
                for prefix in forbidden
            )
        if {module_name!r} == "isaac_audio_sensors.isaac":
            forbidden = (
                "isaac_audio_sensors.kit",
                "isaac_audio_sensors.recording",
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in sys.modules
                for prefix in forbidden
            )
        """
    )
    assert completed.stderr == ""


def test_cli_exposes_current_product_operations(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert (
        "{validate-config,simulate,export-schema,capabilities,dataset,guided}"
        in help_text
    )
