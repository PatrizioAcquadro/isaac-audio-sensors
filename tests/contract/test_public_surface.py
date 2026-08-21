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

    assert __version__ == "2.0.0"
    assert result.stdout.strip() == __version__


def test_semantic_packages_follow_the_r5_dependency_graph():
    for package, allowed in ALLOWED_DEPENDENCIES.items():
        assert _package_dependencies(package) <= allowed


def test_minimal_root_and_v2_public_surfaces_in_fresh_process():
    completed = _run_fresh_process(
        """
        import importlib
        import sys

        package = importlib.import_module("isaac_audio_sensors")
        assert package.__all__ == ["__version__"]
        assert not hasattr(package, "AudioSensorFrame")
        assert not any(
            name.startswith("isaac_audio_sensors.") for name in sys.modules
        )

        core = importlib.import_module("isaac_audio_sensors.core")
        assert core.__all__ == [
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
        ]
        assert core.AudioSensorFrame.__module__ == "isaac_audio_sensors.core.types"
        forbidden = (
            "numpy",
            "torch",
            "omni",
            "pxr",
            "isaaclab",
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

        recording = importlib.import_module("isaac_audio_sensors.recording")
        assert recording.__all__ == [
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
        ]
        assert recording.AudioDatasetManifest.__module__.endswith(".manifest")
        assert callable(recording.manifest_from_dict)
        assert callable(recording.manifest_to_dict)

        schemas = importlib.import_module("isaac_audio_sensors.schemas.generate")
        assert callable(schemas.audio_sensor_frame_json_schema)

        for optional in ("omni", "pxr", "isaaclab", "torch"):
            assert optional not in sys.modules
        """
    )
    assert completed.stderr == ""


def test_cli_exposes_current_product_operations(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for command in (
        "validate-config",
        "simulate",
        "export-trace",
        "export-schema",
        "capabilities",
        "dataset",
        "guided",
    ):
        assert command in help_text
    assert "s4" + "-2" not in help_text


def test_isaac_and_lab_import_without_loading_optional_runtimes():
    _run_fresh_process(
        """
        import sys
        import isaac_audio_sensors.isaac as isaac

        assert isaac.__all__ == [
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
        ]
        forbidden = (
            "omni",
            "pxr",
            "isaaclab",
            "torch",
            "isaac_audio_sensors.kit",
            "isaac_audio_sensors.recording",
        )
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in sys.modules
            for prefix in forbidden
        )

        import isaac_audio_sensors.lab as lab
        assert lab.__all__ == [
            "AudioArraySensor",
            "AudioArraySensorCfg",
            "AudioArraySensorData",
            "EntityBindingCfg",
            "SourceEntityCfg",
        ]
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in sys.modules
            for prefix in forbidden
        )
        """
    )
