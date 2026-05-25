"""Tests for local live-evidence report generation and docs guardrails."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_report_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "generate_live_evidence_report.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_live_evidence_report", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_evidence_report_extracts_runtime_paths_and_blockers(tmp_path):
    report = _load_report_module()
    _write_minimal_evidence(tmp_path)

    markdown = report.build_report(tmp_path)

    assert str(tmp_path / "isaac_sim_live_smoke.json") in markdown
    assert str(tmp_path / "isaac_lab_live_smoke_gpu.json") in markdown
    assert str(tmp_path / "omniverse_extension_live_ux.json") in markdown
    assert "/machine/isaac/bin/python" in markdown
    assert "Isaac Lab version | `0.54.2`" in markdown
    assert "NVIDIA GeForce RTX 4090" in markdown
    assert "PhysX CUDA illegal-memory errors" in markdown
    assert "No sim-real calibration is claimed." in markdown


def test_live_evidence_docs_reference_artifacts_and_avoid_overclaims():
    root = Path(__file__).resolve().parents[1]
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "README.md",
            root / "docs" / "README.md",
            root / "docs" / "validation.md",
            root / "docs" / "showcase.md",
            root / "docs" / "open_source_release_checklist.md",
        )
    )

    for artifact in (
        "outputs/isaac_audio_sensors/isaac_sim_live_smoke.json",
        "outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json",
        "outputs/isaac_audio_sensors/omniverse_extension_live_ux.json",
        "outputs/isaac_audio_sensors/live_validation_evidence.md",
        "outputs/isaac_audio_sensors/live_validation_evidence.pdf",
    ):
        assert artifact in docs_text

    assert "scripts/generate_live_evidence_report.py" in docs_text
    lowered = docs_text.lower()
    for unsupported_claim in (
        "sim-real calibration is validated",
        "real hardware benchmark passed",
        "is an official nvidia extension",
        "ros 2 validation passed",
        "complete l3 runtime validated",
        "complete l4 runtime validated",
    ):
        assert unsupported_claim not in lowered


def _write_minimal_evidence(root: Path) -> None:
    _write_json(
        root / "isaac_sim_live_smoke.json",
        {
            "status": "passed",
            "kit_app_version": "5.1.0",
            "isaacsim_version": "unavailable",
            "kit_build_version": "107.3.3+production.test",
            "python_executable": "/machine/isaac/bin/python",
            "python_version": "3.11.15",
            "torch_version": "2.7.0+cu128",
            "gpu_visible": True,
            "cuda_device_names": ["NVIDIA GeForce RTX 4090"],
            "nvidia_smi": {"stdout": "NVIDIA GeForce RTX 4090, 570.211.01"},
            "simulation_app_bootstrap": "created",
            "pxr_imported": True,
            "omni_imported": True,
            "selected_array": {"prim_path": "/World/Array"},
            "selected_array_id": "rig_front",
            "selected_source": {
                "prim_path": "/World/Sound",
                "source_id": "speaker_front",
            },
            "backend_statuses": {
                "geometry_only": "passed",
                "tdoa_synthetic": "passed",
                "room_acoustics": "skipped",
            },
            "jsonl_backend_frame_counts": {
                "geometry_only": 3,
                "tdoa_synthetic": 3,
            },
            "jsonl_frame_count": 6,
            "debug_primitive_count": 4,
            "debug_primitive_kinds": ["microphone", "source"],
            "diagnostics_namespaces": ["movement", "writer"],
            "room_acoustics_status": "skipped",
            "room_acoustics_skip_reason": "pyroomacoustics missing",
        },
    )
    _write_json(
        root / "isaac_sim_live_smoke.config.json",
        {
            "stage": {
                "mode": "in_memory_usd_authored_inside_isaac_sim",
                "array_prim_path": "/World/Array",
                "source_prim_path": "/World/Sound",
            },
            "sensor": {
                "required_backends": ["geometry_only", "tdoa_synthetic"],
                "optional_backends": ["room_acoustics"],
            },
        },
    )
    _write_jsonl(
        root / "isaac_sim_live_smoke.frames.jsonl",
        [
            {
                "schema_version": "ias.audio_sensor_frame.v1",
                "backend_id": "geometry_only",
            },
            {
                "schema_version": "ias.audio_sensor_frame.v1",
                "backend_id": "tdoa_synthetic",
            },
        ],
    )
    _write_json(
        root / "isaac_lab_live_smoke_gpu.json",
        {
            "status": "passed",
            "runtime": {
                "isaaclab_version": "0.54.2",
                "isaac_sim_version": "5.1.0",
                "kit_build_version": "107.3.3+production.test",
            },
            "python_executable": "/machine/isaac/bin/python",
            "device": "cuda:0",
            "cuda": {
                "torch_cuda_device_name": "NVIDIA GeForce RTX 4090",
                "nvidia_smi_stdout": (
                    "GPU 0: NVIDIA GeForce RTX 4090 "
                    "(UUID: GPU-test)"
                ),
                "torch_version": "2.7.0+cu128",
                "torch_cuda_available": True,
            },
            "class_resolution": {"classes_real": True},
            "cfg_is_sensorbasecfg_subclass": True,
            "sensor_is_sensorbase_subclass": True,
            "fallback_classes_used_in_lab": False,
            "event_presence_shape": [2, 2],
            "bearing_deg_shape": [2, 2],
            "confidence_shape": [2, 2],
            "sector_onehot_shape": [2, 2, 8],
            "per_mic_rms_shape": [2, 2, 4],
            "ambiguity_mask_shape": [2, 2],
            "buffer_device_map": {"event_presence": "cuda:0"},
            "selected_env_checks": {
                "explicit_env_binding": {
                    "selected_update": {"passed": True},
                    "selected_reset": {"passed": True},
                    "selected_repopulate": {"passed": True},
                }
            },
            "stage_kind": "pxr.Usd.Stage",
            "stage_auto_binding": {
                "semantic_discovery": True,
                "stage_ran_inside_kit_lab": True,
                "first_env_1_bearing_deg": 90.0,
                "moved_env_1_bearing_deg": 270.0,
            },
            "entity_binding": {
                "bearing_changed": True,
                "first_env_1_bearing_deg": 90.0,
                "moved_env_1_bearing_deg": 270.0,
                "entity_scene_evidence": {
                    "blocker_summary": "PhysX CUDA illegal-memory errors",
                    "real_lab_rigid_object_probe_status": "blocked",
                    "tensor_scene_device": "cuda:0",
                },
            },
            "observation_surface": {
                "rl_keys": [
                    "audio/event_presence",
                    "audio/bearing_deg",
                ]
            },
            "rl_observation_example": {
                "status": "passed",
                "device": "cuda:0",
            },
        },
    )
    _write_json(
        root / "omniverse_extension_live_ux.json",
        {
            "status": "passed",
            "kit_app_version": "5.1.0",
            "isaacsim_version": "unavailable",
            "kit_build_version": "107.3.3+production.test",
            "python_executable": "/machine/isaac/bin/python",
            "python_version": "3.11.15",
            "torch_version": "2.7.0+cu128",
            "gpu_visible": True,
            "cuda_device_names": ["NVIDIA GeForce RTX 4090"],
            "nvidia_smi": {"stdout": "NVIDIA GeForce RTX 4090, 570.211.01"},
            "kit_extension_manager": {
                "status": "enabled",
                "verification": {
                    "enabled_extension_id": (
                        "isaac_audio_sensors.omni-1.0.0"
                    )
                },
            },
            "stage_mode": "omni_usd_context_stage",
            "selection_api": [{"status": "set"}],
            "workflow_steps": [{"status": "passed"}, {"status": "passed"}],
            "jsonl_frame_count": 1,
            "jsonl_backend_ids": ["tdoa_synthetic"],
            "overlay_primitive_count": 7,
            "overlay_primitive_kinds": ["microphone", "source"],
            "screenshot": {
                "status": "unavailable",
                "reason": "active viewport has no capture_to_file method",
            },
        },
    )
    _write_json(
        root / "omniverse_extension_live_ux.config.json",
        {
            "schema_version": "ias.omni_extension_binding.v1",
            "backend": "tdoa_synthetic",
            "array": {"prim_path": "/World/Rig/AudioArray"},
            "source": {"prim_path": "/World/Sources/SpeakerA"},
            "overlay": {"primitive_count": 7},
        },
    )
    _write_jsonl(
        root / "omniverse_extension_live_ux.frames.jsonl",
        [
            {
                "schema_version": "ias.audio_sensor_frame.v1",
                "backend_id": "tdoa_synthetic",
            }
        ],
    )
    _write_json(
        root
        / "omniverse_extension_live_ux.replicator"
        / "audio_sensor_replicator_manifest.json",
        {
            "runtime_available": True,
            "runtime_module": "omni.replicator.core",
            "writer_registered": True,
            "annotator_status": (
                "unavailable: AnnotatorRegistry has no supported register method"
            ),
            "write_count": 1,
            "flush_count": 1,
            "stopped": True,
        },
    )


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
