"""Live Isaac Lab smoke validation for isaac_audio_sensors."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/isaac_lab_live_smoke.json"),
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="Fail unless CUDA is visible and all audio buffers are on CUDA.",
    )
    args, unknown_args = parser.parse_known_args()
    evidence: dict[str, object] = {
        "python_executable": sys.executable,
        "argv": sys.argv,
        "unknown_launcher_args": unknown_args,
        "require_gpu": args.require_gpu,
        "status": "started",
    }
    simulation_app = None
    try:
        lab_module, simulation_app = _import_lab_runtime()
        evidence["lab_module"] = lab_module
        evidence["runtime"] = _runtime_evidence()
        from isaac_audio_sensors.lab import (
            LabAudioEntityBindingCfg,
            LabAudioSourceEntityCfg,
            LabAudioStageBindingCfg,
            ensure_isaac_lab_sensor_classes,
        )

        classes = ensure_isaac_lab_sensor_classes()
        AudioArraySensor = classes.sensor
        AudioArraySensorCfg = classes.cfg
        sensor_base, sensor_base_cfg = _import_sensor_bases()
        evidence["class_resolution"] = {
            "classes_real": bool(classes.real),
            "fallback_classes_used_in_lab": not bool(classes.real),
            "sensor_class_module": AudioArraySensor.__module__,
            "cfg_class_module": AudioArraySensorCfg.__module__,
            "sensor_base_module": sensor_base.__module__,
            "sensor_base_cfg_module": sensor_base_cfg.__module__,
        }
        evidence["sensor_is_sensorbase_subclass"] = issubclass(
            AudioArraySensor,
            sensor_base,
        )
        evidence["cfg_is_sensorbasecfg_subclass"] = issubclass(
            AudioArraySensorCfg,
            sensor_base_cfg,
        )
        if (
            not evidence["sensor_is_sensorbase_subclass"]
            or not evidence["cfg_is_sensorbasecfg_subclass"]
        ):
            raise RuntimeError("Resolved Lab classes are not real SensorBase classes.")

        cuda_evidence = _cuda_evidence()
        evidence["cuda"] = cuda_evidence
        device = "cpu"
        if args.require_gpu:
            if not cuda_evidence["torch_cuda_available"]:
                raise RuntimeError(
                    "CUDA is unavailable in the Isaac Lab runtime; GPU validation "
                    "cannot pass on CPU."
                )
            if int(cuda_evidence["torch_cuda_device_count"]) <= 0:
                raise RuntimeError("No CUDA devices are visible to torch.")
            device = "cuda:0"

        array = create_microphone_array(
            array_id="rig_front",
            prim_path="/World/Rig/AudioArray",
            layout_name="quad_front",
        )
        snapshots = (
            _snapshot(
                "isaac_lab_live_smoke_env_0",
                "speaker_front",
                (4.0, 0.0, 0.0),
                array,
            ),
            _snapshot(
                "isaac_lab_live_smoke_env_1",
                "speaker_right",
                (0.0, 4.0, 0.0),
                array,
            ),
        )
        scene = SimpleNamespace(
            audio_scene_snapshots=snapshots,
            audio_array_specs=(array, array),
        )
        wrapper = AudioArraySensor.from_lab_scene(
            cfg=AudioArraySensorCfg(
                prim_path="/World/envs/env_.*/Robot/audio_array",
                update_period=0.05,
                backend="tdoa_synthetic",
                microphone_layout="quad_front",
                max_events=2,
                device=device,
                debug_vis=True,
            ),
            scene=scene,
        )
        wrapper.update(dt=0.05, force_recompute=True)
        data = wrapper.data
        explicit_initial_state = _clone_observation_state(wrapper, data)
        wrapper.bind_env(
            env_id=1,
            scene_snapshot=_snapshot(
                "isaac_lab_live_smoke_env_1_moved",
                "speaker_right_moved",
                (0.0, -4.0, 0.0),
                array,
            ),
            sensor=array,
        )
        wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        data = wrapper.data
        explicit_after_selected_update = _clone_observation_state(wrapper, data)
        explicit_selected_update = _selected_update_report(
            before=explicit_initial_state,
            after=explicit_after_selected_update,
            selected_env_ids=(1,),
        )
        wrapper.reset(env_ids=[1])
        explicit_after_reset = _clone_observation_state(wrapper, data)
        explicit_selected_reset = _selected_reset_report(
            before=explicit_after_selected_update,
            after=explicit_after_reset,
            selected_env_ids=(1,),
        )
        reset_env_1_presence = _tensor_to_json(data.event_presence[1])
        wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        data = wrapper.data
        explicit_after_repopulate = _clone_observation_state(wrapper, data)
        explicit_selected_repopulate = _selected_update_report(
            before=explicit_after_reset,
            after=explicit_after_repopulate,
            selected_env_ids=(1,),
        )
        explicit_devices = _buffer_devices(wrapper, data)
        explicit_buffer_summary = _buffer_summary(wrapper, data)
        if args.require_gpu:
            _assert_cuda_buffers(explicit_devices)

        stage, stage_kind = _create_audio_stage()
        evidence["stage_kind"] = stage_kind
        stage_wrapper = AudioArraySensor(
            cfg=AudioArraySensorCfg(
                prim_path="/World/envs/env_.*/Robot/audio_array",
                update_period=0.05,
                backend="tdoa_synthetic",
                microphone_layout="quad_front",
                max_events=2,
                device=device,
                debug_vis=True,
            )
        ).bind_lab_stage(
            stage=stage,
            binding_cfg=LabAudioStageBindingCfg(
                num_envs=2,
                env_namespace_pattern="/World/envs/env_{env_id}",
                discover_arrays=True,
                array_discovery_root_path="Robot",
                preferred_array="audio_array",
                discover_sources=True,
                source_discovery_root_path="Sources",
                microphone_layout="quad_front",
            ),
        )
        stage_wrapper.update(dt=0.05, force_recompute=True)
        stage_data = stage_wrapper.data
        stage_initial_state = _clone_observation_state(stage_wrapper, stage_data)
        first_stage_bearing = _tensor_scalar(stage_data.bearing_deg[1, 0])
        first_stage_diagnostics = stage_data.latest_frames[1].diagnostics.get(
            "stage_binding",
            {},
        )
        _set_stage_translate(
            stage,
            "/World/envs/env_1/Sources/speaker",
            (0.0, -4.0, 0.0),
        )
        stage_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        stage_data = stage_wrapper.data
        stage_after_selected_update = _clone_observation_state(
            stage_wrapper,
            stage_data,
        )
        stage_selected_update = _selected_update_report(
            before=stage_initial_state,
            after=stage_after_selected_update,
            selected_env_ids=(1,),
        )
        moved_stage_bearing = _tensor_scalar(stage_data.bearing_deg[1, 0])
        moved_stage_diagnostics = stage_data.latest_frames[1].diagnostics.get(
            "stage_binding",
            {},
        )
        stage_wrapper.reset(env_ids=[1])
        stage_after_reset = _clone_observation_state(stage_wrapper, stage_data)
        stage_selected_reset = _selected_reset_report(
            before=stage_after_selected_update,
            after=stage_after_reset,
            selected_env_ids=(1,),
        )
        stage_reset_presence = _tensor_to_json(stage_data.event_presence[1])
        stage_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        stage_data = stage_wrapper.data
        stage_after_repopulate = _clone_observation_state(stage_wrapper, stage_data)
        stage_selected_repopulate = _selected_update_report(
            before=stage_after_reset,
            after=stage_after_repopulate,
            selected_env_ids=(1,),
        )
        stage_devices = _buffer_devices(stage_wrapper, stage_data)
        stage_buffer_summary = _buffer_summary(stage_wrapper, stage_data)
        if args.require_gpu:
            _assert_cuda_buffers(stage_devices)

        entity_scene_info = _create_entity_scene_with_blocker_evidence(device)
        entity_scene = entity_scene_info.scene
        entity_binding_cfg = LabAudioEntityBindingCfg(
            num_envs=2,
            robot_entity_name="robot",
            array_mount_body_name="head",
            array_relative_position_m=(0.0, 0.0, 0.0),
            microphone_layout="quad_front",
            source_entities=(
                LabAudioSourceEntityCfg(
                    entity_name="speaker",
                    source_id="entity_speaker",
                    class_label="Speech",
                    duration_s=1.0,
                ),
            ),
            device=device,
        )
        entity_wrapper = AudioArraySensor(
            cfg=AudioArraySensorCfg(
                prim_path="/World/envs/env_.*/Robot/head/audio_array",
                update_period=0.05,
                backend="tdoa_synthetic",
                microphone_layout="quad_front",
                max_events=2,
                device=device,
                debug_vis=True,
            )
        ).bind_lab_entities(
            scene=entity_scene,
            binding_cfg=entity_binding_cfg,
        )
        entity_wrapper.update(dt=0.05, force_recompute=True)
        entity_data = entity_wrapper.data
        entity_initial_state = _clone_observation_state(entity_wrapper, entity_data)
        first_entity_bearing = _tensor_scalar(entity_data.bearing_deg[1, 0])
        first_entity_diag = entity_data.latest_frames[1].diagnostics.get(
            "entity_binding",
            {},
        )
        _set_entity_source_position(
            entity_scene,
            env_id=1,
            local_position=(0.0, -4.0, 0.0),
        )
        entity_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        entity_data = entity_wrapper.data
        entity_after_selected_update = _clone_observation_state(
            entity_wrapper,
            entity_data,
        )
        entity_selected_update = _selected_update_report(
            before=entity_initial_state,
            after=entity_after_selected_update,
            selected_env_ids=(1,),
        )
        moved_entity_bearing = _tensor_scalar(entity_data.bearing_deg[1, 0])
        moved_entity_diag = entity_data.latest_frames[1].diagnostics.get(
            "entity_binding",
            {},
        )
        entity_wrapper.reset(env_ids=[1])
        entity_after_reset = _clone_observation_state(entity_wrapper, entity_data)
        entity_selected_reset = _selected_reset_report(
            before=entity_after_selected_update,
            after=entity_after_reset,
            selected_env_ids=(1,),
        )
        entity_reset_presence = _tensor_to_json(entity_data.event_presence[1])
        entity_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        entity_data = entity_wrapper.data
        entity_after_repopulate = _clone_observation_state(
            entity_wrapper,
            entity_data,
        )
        entity_selected_repopulate = _selected_update_report(
            before=entity_after_reset,
            after=entity_after_repopulate,
            selected_env_ids=(1,),
        )
        entity_devices = _buffer_devices(entity_wrapper, entity_data)
        entity_buffer_summary = _buffer_summary(entity_wrapper, entity_data)
        if args.require_gpu:
            _assert_cuda_buffers(entity_devices)

        selected_env_checks = {
            "explicit_env_binding": {
                "selected_update": explicit_selected_update,
                "selected_reset": explicit_selected_reset,
                "selected_repopulate": explicit_selected_repopulate,
            },
            "stage_binding": {
                "selected_update": stage_selected_update,
                "selected_reset": stage_selected_reset,
                "selected_repopulate": stage_selected_repopulate,
            },
            "entity_binding": {
                "selected_update": entity_selected_update,
                "selected_reset": entity_selected_reset,
                "selected_repopulate": entity_selected_repopulate,
            },
        }
        _assert_selected_env_reports(selected_env_checks)
        rl_observation_example = _rl_observation_example_evidence(wrapper)

        evidence.update(
            {
                "status": "passed",
                "event_presence_shape": list(data.event_presence.shape),
                "bearing_deg_shape": list(data.bearing_deg.shape),
                "confidence_shape": list(data.confidence.shape),
                "sector_onehot_shape": list(data.sector_onehot.shape),
                "per_mic_rms_shape": list(data.per_mic_rms.shape),
                "ambiguity_mask_shape": list(data.ambiguity_mask.shape),
                "device": str(data.event_presence.device),
                "explicit_buffer_devices": explicit_devices,
                "explicit_buffer_summary": explicit_buffer_summary,
                "event_presence": _tensor_to_json(data.event_presence),
                "bearing_deg": _tensor_to_json(data.bearing_deg),
                "confidence": _tensor_to_json(data.confidence),
                "ambiguity_mask": _tensor_to_json(data.ambiguity_mask),
                "metadata_summary": _metadata_summary(data),
                "reset_env_1_presence_before_selected_update": reset_env_1_presence,
                "frame_ids": data.frame_ids,
                "source_ids": data.source_ids,
                "selected_env_checks": selected_env_checks,
                "rl_observation_example": rl_observation_example,
                "stage_auto_binding": {
                    "buffer_devices": stage_devices,
                    "buffer_summary": stage_buffer_summary,
                    "semantic_discovery": True,
                    "stage_ran_inside_kit_lab": stage_kind == "pxr.Usd.Stage",
                    "event_presence_shape": list(stage_data.event_presence.shape),
                    "bearing_deg": _tensor_to_json(stage_data.bearing_deg),
                    "event_presence": _tensor_to_json(stage_data.event_presence),
                    "source_ids": stage_data.source_ids,
                    "first_env_1_bearing_deg": first_stage_bearing,
                    "moved_env_1_bearing_deg": moved_stage_bearing,
                    "first_env_1_stage_binding_diagnostics": (first_stage_diagnostics),
                    "moved_env_1_stage_binding_diagnostics": (moved_stage_diagnostics),
                    "reset_env_1_presence_before_selected_update": (
                        stage_reset_presence
                    ),
                },
                "entity_binding": {
                    "mode": "lab_entity_binding",
                    "scene_type": type(entity_scene).__name__,
                    "scene_module": type(entity_scene).__module__,
                    "entity_scene_evidence": entity_scene_info.evidence,
                    "robot_entity": "robot",
                    "robot_body": "head",
                    "source_entities": (
                        {
                            "entity_name": "speaker",
                            "body_name": None,
                            "source_id": "entity_speaker",
                        },
                    ),
                    "env_ids": [0, 1],
                    "buffer_devices": entity_devices,
                    "buffer_summary": entity_buffer_summary,
                    "event_presence_shape": list(entity_data.event_presence.shape),
                    "bearing_deg": _tensor_to_json(entity_data.bearing_deg),
                    "event_presence": _tensor_to_json(entity_data.event_presence),
                    "source_ids": entity_data.source_ids,
                    "first_env_1_bearing_deg": first_entity_bearing,
                    "moved_env_1_bearing_deg": moved_entity_bearing,
                    "bearing_changed": not math.isclose(
                        first_entity_bearing,
                        moved_entity_bearing,
                        rel_tol=0.0,
                        abs_tol=1e-5,
                    ),
                    "first_env_1_entity_binding_diagnostics": first_entity_diag,
                    "moved_env_1_entity_binding_diagnostics": moved_entity_diag,
                    "reset_env_1_presence_before_selected_update": (
                        entity_reset_presence
                    ),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001 - smoke evidence records exact error.
        evidence.update(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        _write_evidence(args.out, evidence)
        print(json.dumps(_json_safe(evidence), indent=2, sort_keys=True))
        _close_simulation_app(simulation_app)
        return 2

    _write_evidence(args.out, evidence)
    print(json.dumps(_json_safe(evidence), indent=2, sort_keys=True))
    _close_simulation_app(simulation_app)
    return 0


_TENSOR_FIELDS = (
    "event_presence",
    "bearing_deg",
    "confidence",
    "sector_onehot",
    "per_mic_rms",
    "ambiguity_mask",
    "last_update_time_s",
)
_BOOKKEEPING_FIELDS = ("_timestamp", "_timestamp_last_update", "_is_outdated")


def _runtime_evidence() -> dict[str, object]:
    evidence: dict[str, object] = {
        "pxr_available": _module_available("pxr"),
        "omni_available": _module_available("omni"),
    }
    try:
        import isaaclab  # type: ignore

        evidence["isaaclab_file"] = getattr(isaaclab, "__file__", None)
        evidence["isaaclab_version"] = getattr(isaaclab, "__version__", None)
    except Exception as exc:  # noqa: BLE001 - evidence only.
        evidence["isaaclab_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from isaaclab.utils.version import get_isaac_sim_version  # type: ignore

        evidence["isaac_sim_version"] = str(get_isaac_sim_version())
    except Exception as exc:  # noqa: BLE001 - evidence only.
        evidence["isaac_sim_version_error"] = f"{type(exc).__name__}: {exc}"
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        get_version = getattr(app, "get_build_version", None)
        if callable(get_version):
            evidence["kit_build_version"] = str(get_version())
    except Exception as exc:  # noqa: BLE001 - evidence only.
        evidence["kit_version_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _buffer_summary(sensor: object, data: object) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for field in _TENSOR_FIELDS:
        value = getattr(data, field)
        if hasattr(value, "shape"):
            summary[field] = _tensor_summary(value)
    for field in _BOOKKEEPING_FIELDS:
        value = getattr(sensor, field, None)
        if hasattr(value, "shape"):
            summary[field] = _tensor_summary(value)
    return summary


def _tensor_summary(value: object) -> dict[str, object]:
    return {
        "shape": list(value.shape),  # type: ignore[attr-defined]
        "dtype": str(value.dtype),  # type: ignore[attr-defined]
        "device": str(value.device),  # type: ignore[attr-defined]
    }


def _metadata_summary(data: object) -> dict[str, object]:
    source_ids = tuple(getattr(data, "source_ids", ()))
    class_labels = tuple(getattr(data, "class_labels", ()))
    return {
        "frame_ids_len": len(tuple(getattr(data, "frame_ids", ()))),
        "frame_names_len": len(tuple(getattr(data, "frame_names", ()))),
        "latest_frames_len": len(tuple(getattr(data, "latest_frames", ()))),
        "latest_frame_present": tuple(
            frame is not None for frame in getattr(data, "latest_frames", ())
        ),
        "source_ids_shape": _tuple_matrix_shape(source_ids),
        "class_labels_shape": _tuple_matrix_shape(class_labels),
        "microphone_ids_len": len(tuple(getattr(data, "microphone_ids", ()))),
        "sector_order": tuple(getattr(data, "sector_order", ())),
        "waveform_paths_len": len(tuple(getattr(data, "waveform_paths", ()))),
    }


def _tuple_matrix_shape(rows: tuple[tuple[object, ...], ...]) -> list[int]:
    if not rows:
        return [0, 0]
    return [len(rows), max(len(row) for row in rows)]


def _clone_observation_state(sensor: object, data: object) -> dict[str, object]:
    tensors = {}
    for field in _TENSOR_FIELDS:
        value = getattr(data, field)
        if hasattr(value, "detach"):
            tensors[field] = value.detach().clone()
    bookkeeping = {}
    for field in _BOOKKEEPING_FIELDS:
        value = getattr(sensor, field, None)
        if hasattr(value, "detach"):
            bookkeeping[field] = value.detach().clone()
    return {
        "tensors": tensors,
        "bookkeeping": bookkeeping,
        "metadata": {
            "frame_ids": tuple(getattr(data, "frame_ids", ())),
            "frame_names": tuple(getattr(data, "frame_names", ())),
            "source_ids": tuple(
                tuple(row) for row in getattr(data, "source_ids", ())
            ),
            "class_labels": tuple(
                tuple(row) for row in getattr(data, "class_labels", ())
            ),
            "latest_frame_present": tuple(
                frame is not None for frame in getattr(data, "latest_frames", ())
            ),
            "waveform_paths": tuple(
                tuple(row) for row in getattr(data, "waveform_paths", ())
            ),
        },
    }


def _selected_update_report(
    *,
    before: dict[str, object],
    after: dict[str, object],
    selected_env_ids: tuple[int, ...],
) -> dict[str, object]:
    num_envs = _state_num_envs(after)
    selected = tuple(int(env_id) for env_id in selected_env_ids)
    unselected = tuple(env_id for env_id in range(num_envs) if env_id not in selected)
    unchanged = {
        str(env_id): _row_equal(before, after, env_id) for env_id in unselected
    }
    changed = {
        str(env_id): not _row_equal(before, after, env_id) for env_id in selected
    }
    return {
        "selected_env_ids": selected,
        "unselected_env_ids": unselected,
        "selected_rows_changed": changed,
        "unselected_rows_unchanged": unchanged,
        "passed": all(changed.values()) and all(unchanged.values()),
        "before": _row_summaries(before, selected + unselected),
        "after": _row_summaries(after, selected + unselected),
    }


def _selected_reset_report(
    *,
    before: dict[str, object],
    after: dict[str, object],
    selected_env_ids: tuple[int, ...],
) -> dict[str, object]:
    num_envs = _state_num_envs(after)
    selected = tuple(int(env_id) for env_id in selected_env_ids)
    unselected = tuple(env_id for env_id in range(num_envs) if env_id not in selected)
    unchanged = {
        str(env_id): _row_equal(before, after, env_id) for env_id in unselected
    }
    cleared = {str(env_id): _row_cleared(after, env_id) for env_id in selected}
    return {
        "selected_env_ids": selected,
        "unselected_env_ids": unselected,
        "selected_rows_cleared": cleared,
        "unselected_rows_unchanged": unchanged,
        "passed": all(cleared.values()) and all(unchanged.values()),
        "before": _row_summaries(before, selected + unselected),
        "after": _row_summaries(after, selected + unselected),
    }


def _state_num_envs(state: dict[str, object]) -> int:
    tensors = state["tensors"]  # type: ignore[index]
    event_presence = tensors["event_presence"]  # type: ignore[index]
    return int(event_presence.shape[0])


def _row_equal(
    before: dict[str, object],
    after: dict[str, object],
    env_id: int,
) -> bool:
    for group_name in ("tensors", "bookkeeping"):
        before_group = before[group_name]  # type: ignore[index]
        after_group = after[group_name]  # type: ignore[index]
        for field, before_tensor in before_group.items():
            after_tensor = after_group[field]
            if not _tensor_values_equal(before_tensor[env_id], after_tensor[env_id]):
                return False
    before_metadata = before["metadata"]  # type: ignore[index]
    after_metadata = after["metadata"]  # type: ignore[index]
    for field, before_values in before_metadata.items():
        if before_values[env_id] != after_metadata[field][env_id]:
            return False
    return True


def _tensor_values_equal(before: Any, after: Any) -> bool:
    import torch  # type: ignore

    if before.dtype.is_floating_point:
        return bool(torch.allclose(before, after, equal_nan=True))
    return bool(torch.equal(before, after))


def _row_cleared(state: dict[str, object], env_id: int) -> bool:
    import torch  # type: ignore

    tensors = state["tensors"]  # type: ignore[index]
    bookkeeping = state["bookkeeping"]  # type: ignore[index]
    metadata = state["metadata"]  # type: ignore[index]
    checks = [
        not bool(tensors["event_presence"][env_id].any().item()),
        bool(torch.isnan(tensors["bearing_deg"][env_id]).all().item()),
        bool((tensors["confidence"][env_id] == 0.0).all().item()),
        bool((tensors["sector_onehot"][env_id] == 0.0).all().item()),
        bool((tensors["per_mic_rms"][env_id] == 0.0).all().item()),
        not bool(tensors["ambiguity_mask"][env_id].any().item()),
        bool(torch.isnan(tensors["last_update_time_s"][env_id]).item()),
        float(bookkeeping["_timestamp"][env_id].item()) == 0.0,
        float(bookkeeping["_timestamp_last_update"][env_id].item()) == 0.0,
        bool(bookkeeping["_is_outdated"][env_id].item()),
        metadata["frame_ids"][env_id] is None,
        metadata["frame_names"][env_id] is None,
        all(value is None for value in metadata["source_ids"][env_id]),
        all(value is None for value in metadata["class_labels"][env_id]),
        not bool(metadata["latest_frame_present"][env_id]),
        tuple(metadata["waveform_paths"][env_id]) == (),
    ]
    return all(checks)


def _row_summaries(
    state: dict[str, object],
    env_ids: tuple[int, ...],
) -> dict[str, dict[str, object]]:
    return {str(env_id): _row_summary(state, env_id) for env_id in env_ids}


def _row_summary(state: dict[str, object], env_id: int) -> dict[str, object]:
    tensors = state["tensors"]  # type: ignore[index]
    bookkeeping = state["bookkeeping"]  # type: ignore[index]
    metadata = state["metadata"]  # type: ignore[index]
    return {
        "event_presence": _tensor_to_json(tensors["event_presence"][env_id]),
        "bearing_deg": _tensor_to_json(tensors["bearing_deg"][env_id]),
        "confidence": _tensor_to_json(tensors["confidence"][env_id]),
        "ambiguity_mask": _tensor_to_json(tensors["ambiguity_mask"][env_id]),
        "timestamp": _tensor_to_json(bookkeeping["_timestamp"][env_id]),
        "timestamp_last_update": _tensor_to_json(
            bookkeeping["_timestamp_last_update"][env_id]
        ),
        "is_outdated": _tensor_to_json(bookkeeping["_is_outdated"][env_id]),
        "frame_id": metadata["frame_ids"][env_id],
        "source_ids": metadata["source_ids"][env_id],
        "latest_frame_present": metadata["latest_frame_present"][env_id],
    }


def _assert_selected_env_reports(
    selected_env_checks: dict[str, dict[str, dict[str, object]]],
) -> None:
    failures = []
    for binding_name, reports in selected_env_checks.items():
        for report_name, report in reports.items():
            if not report["passed"]:
                failures.append(f"{binding_name}.{report_name}")
    if failures:
        raise RuntimeError(
            "Selected-env update/reset proof failed for: " + ", ".join(failures)
        )


def _rl_observation_example_evidence(sensor: object) -> dict[str, object]:
    path = Path("examples/isaac_lab/isaac_lab_audio_observation.py")
    spec = importlib.util.spec_from_file_location("isaac_lab_audio_observation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load RL observation example from {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    obs = module.audio_observation(sensor, dt=0.0, update_env_ids=[1])
    ambiguity = module.ambiguity_observation(obs)
    expected_keys = tuple(module.AUDIO_OBSERVATION_KEYS)
    missing = [key for key in expected_keys if key not in obs]
    if missing:
        raise RuntimeError(f"RL observation example missing keys: {missing}")
    summaries = {key: _tensor_summary(value) for key, value in obs.items()}
    devices = {summary["device"] for summary in summaries.values()}
    return {
        "path": str(path),
        "keys": expected_keys,
        "all_expected_keys_present": not missing,
        "single_device": len(devices) == 1,
        "device": next(iter(devices)) if len(devices) == 1 else sorted(devices),
        "tensor_summaries": summaries,
        "ambiguity_keys": tuple(ambiguity),
        "ambiguous_event_presence_shape": list(
            ambiguity["audio/ambiguous_event_presence"].shape
        ),
    }


def _snapshot(
    stage_id: str,
    source_id: str,
    position_world: tuple[float, float, float],
    array,
) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id=stage_id,
        timestamp_ms=0,
        sources=(
            AudioSourceSpec(
                source_id=source_id,
                prim_path=f"/World/Sources/{source_id}",
                class_label="Speech",
                audio_asset_path="generated://impulse",
                position_world=position_world,
                orientation_world_quat=None,
                start_time_s=0.0,
                duration_s=1.0,
                gain_db=0.0,
            ),
        ),
        arrays=(array,),
    )


def _import_lab_runtime() -> tuple[str, object]:
    try:
        from isaaclab.app import AppLauncher  # type: ignore

        app_launcher = AppLauncher(headless=True)
        import isaaclab  # type: ignore

        return f"isaaclab:{getattr(isaaclab, '__file__', 'built-in')}", app_launcher.app
    except ImportError:
        pass
    try:
        from omni.isaac.lab.app import AppLauncher  # type: ignore

        app_launcher = AppLauncher(headless=True)
        import omni.isaac.lab  # type: ignore  # noqa: F401

        return "omni.isaac.lab", app_launcher.app
    except ImportError as exc:
        raise RuntimeError(
            "Neither isaaclab nor omni.isaac.lab imported in this Python runtime."
        ) from exc


def _import_sensor_bases() -> tuple[type, type]:
    try:
        from isaaclab.sensors import SensorBase, SensorBaseCfg  # type: ignore

        return SensorBase, SensorBaseCfg
    except ImportError:
        from omni.isaac.lab.sensors import SensorBase, SensorBaseCfg  # type: ignore

        return SensorBase, SensorBaseCfg


def _cuda_evidence() -> dict[str, object]:
    import torch  # type: ignore

    evidence: dict[str, object] = {
        "torch_cuda_available": bool(torch.cuda.is_available()),
        "torch_cuda_device_count": int(torch.cuda.device_count()),
        "torch_version": str(torch.__version__),
    }
    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        current = int(torch.cuda.current_device())
        evidence.update(
            {
                "torch_cuda_current_device": current,
                "torch_cuda_device_name": torch.cuda.get_device_name(current),
            }
        )
    try:
        completed = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        evidence["nvidia_smi_returncode"] = completed.returncode
        evidence["nvidia_smi_stdout"] = completed.stdout.strip()
        evidence["nvidia_smi_stderr"] = completed.stderr.strip()
    except Exception as exc:  # noqa: BLE001 - evidence should record blockers.
        evidence["nvidia_smi_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def _buffer_devices(sensor: object, data: object) -> dict[str, str]:
    fields = (
        "event_presence",
        "bearing_deg",
        "confidence",
        "sector_onehot",
        "per_mic_rms",
        "ambiguity_mask",
        "last_update_time_s",
    )
    devices = {}
    for field in fields:
        value = getattr(data, field)
        if hasattr(value, "device"):
            devices[field] = str(value.device)
    for field in ("_timestamp", "_timestamp_last_update", "_is_outdated"):
        value = getattr(sensor, field, None)
        if hasattr(value, "device"):
            devices[field] = str(value.device)
    return devices


def _assert_cuda_buffers(devices: dict[str, str]) -> None:
    bad = {
        field: device
        for field, device in devices.items()
        if not device.startswith("cuda")
    }
    if bad:
        raise RuntimeError(f"GPU validation found non-CUDA audio buffers: {bad}")
    unique_devices = set(devices.values())
    if len(unique_devices) != 1:
        raise RuntimeError(f"Audio buffers are split across devices: {devices}")


def _tensor_to_json(value):
    if hasattr(value, "detach"):
        return _json_safe(value.detach().cpu().tolist())
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    return _json_safe(value)


def _tensor_scalar(value) -> float:
    if hasattr(value, "detach"):
        return float(value.detach().cpu().item())
    if hasattr(value, "item"):
        return float(value.item())
    return float(value)


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object],
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    identifier = "duck_typed_live_lab_stage"

    def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
        self._prims = list(prims)

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)


def _create_audio_stage() -> tuple[object, str]:
    try:
        from pxr import Usd, UsdGeom  # type: ignore

        stage = Usd.Stage.CreateInMemory("isaac_audio_lab_smoke.usda")
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Xform.Define(stage, "/World/envs")
        for env_id, source_position in (
            (0, (4.0, 0.0, 0.0)),
            (1, (0.0, 4.0, 0.0)),
        ):
            env_ns = f"/World/envs/env_{env_id}"
            env_prim = UsdGeom.Xform.Define(stage, env_ns).GetPrim()
            _set_usd_translate(env_prim, (float(env_id) * 10.0, 0.0, 0.0))
            UsdGeom.Xform.Define(stage, f"{env_ns}/Robot")
            UsdGeom.Xform.Define(stage, f"{env_ns}/Sources")
            array = UsdGeom.Xform.Define(stage, f"{env_ns}/Robot/audio_array").GetPrim()
            _set_usd_translate(array, (0.0, 0.0, 0.0))
            _set_usd_attr(array, "ias:array_id", f"rig_front_{env_id}")
            _set_usd_attr(array, "ias:sample_rate_hz", 48_000)
            source = UsdGeom.Xform.Define(stage, f"{env_ns}/Sources/speaker").GetPrim()
            _set_usd_translate(source, source_position)
            _set_usd_attr(source, "filePath", "generated://impulse")
            _set_usd_attr(source, "ias:source_id", f"stage_speaker_{env_id}")
            _set_usd_attr(source, "ias:class_label", "Speech")
            _set_usd_attr(source, "ias:start_time_s", 0.0)
            _set_usd_attr(source, "ias:duration_s", 1.0)
        return stage, "pxr.Usd.Stage"
    except Exception:
        return _create_fake_audio_stage(), "duck-typed stage"


def _create_fake_audio_stage() -> _FakeStage:
    prims: list[_FakePrim] = []
    for env_id, source_position in (
        (0, (4.0, 0.0, 0.0)),
        (1, (0.0, 4.0, 0.0)),
    ):
        env_ns = f"/World/envs/env_{env_id}"
        prims.append(
            _FakePrim(
                f"{env_ns}/Robot/audio_array",
                "Xform",
                {
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                    "ias:array_id": f"rig_front_{env_id}",
                    "ias:sample_rate_hz": 48_000,
                },
            )
        )
        prims.append(
            _FakePrim(
                f"{env_ns}/Sources/speaker",
                "Xform",
                {
                    "filePath": "generated://impulse",
                    "ias:position_world": source_position,
                    "ias:source_id": f"stage_speaker_{env_id}",
                    "ias:class_label": "Speech",
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 1.0,
                },
            )
        )
    return _FakeStage(tuple(prims))


def _create_entity_scene_with_blocker_evidence(device: str) -> SimpleNamespace:
    scene = _create_entity_scene(device)
    return SimpleNamespace(
        scene=scene,
        evidence={
            "scene_is_interactive_scene": False,
            "used_synthetic_tensor_scene": True,
            "tensor_scene_device": device,
            "real_lab_rigid_object_probe_status": "blocked",
            "blocker_summary": (
                "A real Isaac Lab InteractiveScene/RigidObject probe was attempted "
                "in this runtime. The GPU SimulationContext path raised PhysX CUDA "
                "illegal-memory errors; moving that probe to a CPU SimulationContext "
                "produced passed JSON but hung during Kit shutdown, so it is not "
                "kept inside the required make target."
            ),
            "smallest_next_fix": (
                "Run the real RigidObject entity probe in an isolated Isaac Lab "
                "process with a hard timeout and artifact handoff, or use a stable "
                "pre-existing InteractiveScene fixture from the downstream task."
            ),
        },
    )


def _create_real_lab_entity_scene(device: str) -> SimpleNamespace:
    import isaaclab.sim as sim_utils  # type: ignore
    from isaaclab.assets import RigidObjectCfg  # type: ignore
    from isaaclab.scene import InteractiveScene, InteractiveSceneCfg  # type: ignore
    from isaaclab.sim import SimulationContext  # type: ignore
    from isaaclab.utils import configclass  # type: ignore

    sim = SimulationContext.instance()
    sim_device = "cpu"
    if sim is None:
        sim = SimulationContext(sim_utils.SimulationCfg(device=sim_device))
    else:
        sim_device = str(sim.device)

    @configclass
    class AudioEntitySceneCfg(InteractiveSceneCfg):
        """Tiny real Isaac Lab scene with rigid-object entities."""

        robot = RigidObjectCfg(
            prim_path="{ENV_REGEX_NS}/Robot",
            spawn=sim_utils.CuboidCfg(
                size=(0.20, 0.20, 0.20),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True,
                ),
                mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.2, 0.5, 1.0),
                ),
            ),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(0.0, 0.0, 0.5)),
        )
        speaker = RigidObjectCfg(
            prim_path="{ENV_REGEX_NS}/Speaker",
            spawn=sim_utils.SphereCfg(
                radius=0.08,
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True,
                ),
                mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(1.0, 0.4, 0.1),
                ),
            ),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(4.0, 0.0, 0.5)),
        )

    scene = InteractiveScene(
        AudioEntitySceneCfg(
            num_envs=2,
            env_spacing=10.0,
            replicate_physics=True,
            filter_collisions=False,
        )
    )
    sim.reset()
    _set_real_lab_rigid_object_positions(
        scene,
        entity_name="robot",
        local_positions=((0.0, 0.0, 0.5), (0.0, 0.0, 0.5)),
    )
    _set_real_lab_rigid_object_positions(
        scene,
        entity_name="speaker",
        local_positions=((4.0, 0.0, 0.5), (0.0, 4.0, 0.5)),
    )
    scene.write_data_to_sim()
    sim.step()
    scene.update(sim.get_physics_dt())
    robot = scene.rigid_objects["robot"]
    speaker = scene.rigid_objects["speaker"]
    evidence = {
        "scene_is_interactive_scene": isinstance(scene, InteractiveScene),
        "scene_class": f"{type(scene).__module__}.{type(scene).__name__}",
        "robot_class": f"{type(robot).__module__}.{type(robot).__name__}",
        "speaker_class": f"{type(speaker).__module__}.{type(speaker).__name__}",
        "robot_is_real_lab_rigid_object": type(robot).__module__.startswith(
            "isaaclab.assets"
        ),
        "speaker_is_real_lab_rigid_object": type(speaker).__module__.startswith(
            "isaaclab.assets"
        ),
        "num_envs": int(scene.num_envs),
        "env_origins": _tensor_to_json(scene.env_origins),
        "device": str(scene.device),
        "simulation_device": sim_device,
        "audio_binding_device": device,
        "robot_root_pos_w": _tensor_to_json(robot.data.root_pos_w),
        "speaker_root_pos_w": _tensor_to_json(speaker.data.root_pos_w),
    }
    return SimpleNamespace(scene=scene, evidence=evidence)


def _set_real_lab_rigid_object_positions(
    scene: object,
    *,
    entity_name: str,
    local_positions: tuple[tuple[float, float, float], ...],
) -> None:
    import torch  # type: ignore

    entity = scene.rigid_objects[entity_name]
    local = torch.tensor(
        local_positions,
        dtype=torch.float32,
        device=scene.device,
    )
    root_state = entity.data.default_root_state.clone()
    root_state[:, :3] = scene.env_origins + local
    entity.write_root_pose_to_sim(root_state[:, :7])
    entity.write_root_velocity_to_sim(root_state[:, 7:])


def _create_entity_scene(device: str) -> SimpleNamespace:
    import torch  # type: ignore

    identity = _wxyz((0.0, 0.0, 0.0, 1.0))
    robot = SimpleNamespace(
        data=SimpleNamespace(
            body_names=("base", "head"),
            body_pos_w=torch.tensor(
                [
                    [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                    [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                ],
                dtype=torch.float32,
                device=device,
            ),
            body_quat_w=torch.tensor(
                [[identity, identity], [identity, identity]],
                dtype=torch.float32,
                device=device,
            ),
        )
    )
    speaker = SimpleNamespace(
        data=SimpleNamespace(
            root_pos_w=torch.tensor(
                [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0]],
                dtype=torch.float32,
                device=device,
            ),
            root_quat_w=torch.tensor(
                [identity, identity],
                dtype=torch.float32,
                device=device,
            ),
        )
    )
    return SimpleNamespace(
        num_envs=2,
        articulations={"robot": robot},
        rigid_objects={"speaker": speaker},
    )


def _set_entity_source_position(
    scene: object,
    *,
    env_id: int,
    local_position: tuple[float, float, float],
) -> None:
    import torch  # type: ignore

    env_id = int(env_id)
    if hasattr(scene, "rigid_objects"):
        speaker = scene.rigid_objects["speaker"]
        if hasattr(speaker, "write_root_pose_to_sim"):
            root_state = speaker.data.root_state_w.clone()
            target = torch.tensor(
                local_position,
                dtype=root_state.dtype,
                device=root_state.device,
            )
            env_origins = getattr(scene, "env_origins", None)
            if env_origins is not None:
                target = target + env_origins[env_id]
            root_state[env_id, :3] = target
            speaker.write_root_pose_to_sim(root_state[:, :7])
            speaker.write_root_velocity_to_sim(root_state[:, 7:])
            speaker.update(0.0)
            update_scene = getattr(scene, "update", None)
            if callable(update_scene):
                update_scene(0.0)
            return
        tensor = speaker.data.root_pos_w
        tensor[env_id] = torch.tensor(
            local_position,
            dtype=tensor.dtype,
            device=tensor.device,
        )
        return
    raise RuntimeError("Entity scene does not expose rigid_objects['speaker'].")


def _wxyz(xyzw: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (xyzw[3], xyzw[0], xyzw[1], xyzw[2])


def _set_stage_attr(stage: object, prim_path: str, name: str, value: object) -> None:
    if hasattr(stage, "GetPrimAtPath"):
        prim = stage.GetPrimAtPath(prim_path)
        if not prim:
            raise RuntimeError(f"No prim found at {prim_path}")
        attr = prim.GetAttribute(name)
        if not attr:
            _set_usd_attr(prim, name, value)
        else:
            attr.Set(_usd_value(value))
        return
    for prim in stage.Traverse():
        if getattr(prim, "path", None) == prim_path:
            prim.attributes[name] = value
            return
    raise RuntimeError(f"No prim found at {prim_path}")


def _set_stage_translate(
    stage: object,
    prim_path: str,
    value: tuple[float, float, float],
) -> None:
    if hasattr(stage, "GetPrimAtPath"):
        prim = stage.GetPrimAtPath(prim_path)
        if not prim:
            raise RuntimeError(f"No prim found at {prim_path}")
        _set_usd_translate(prim, value)
        return
    for prim in stage.Traverse():
        if getattr(prim, "path", None) == prim_path:
            prim.attributes["xformOp:translate"] = value
            prim.attributes.pop("ias:position_world", None)
            return
    raise RuntimeError(f"No prim found at {prim_path}")


def _set_usd_translate(prim: object, value: tuple[float, float, float]) -> None:
    attr = prim.GetAttribute("xformOp:translate")
    if not attr:
        from pxr import UsdGeom  # type: ignore

        attr = UsdGeom.Xformable(prim).AddTranslateOp()
    attr.Set(_usd_vec3(value))


def _set_usd_attr(prim: object, name: str, value: object) -> None:
    attr = prim.CreateAttribute(name, _usd_value_type(value), custom=True)
    attr.Set(_usd_value(value))


def _usd_value_type(value: object):
    from pxr import Sdf  # type: ignore

    if isinstance(value, str):
        return Sdf.ValueTypeNames.String
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Float
    if isinstance(value, tuple) and len(value) == 3:
        return Sdf.ValueTypeNames.Float3
    if isinstance(value, tuple) and len(value) == 4:
        return Sdf.ValueTypeNames.Float4
    return Sdf.ValueTypeNames.String


def _usd_value(value: object) -> object:
    if isinstance(value, tuple) and len(value) == 3:
        return _usd_vec3(value)
    if isinstance(value, tuple) and len(value) == 4:
        from pxr import Gf  # type: ignore

        return Gf.Vec4f(*value)
    return value


def _usd_vec3(value: tuple[float, float, float]) -> object:
    from pxr import Gf  # type: ignore

    return Gf.Vec3d(float(value[0]), float(value[1]), float(value[2]))


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(evidence), allow_nan=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _close_simulation_app(simulation_app: object | None) -> None:
    if simulation_app is None:
        return
    close = getattr(simulation_app, "close", None)
    if close is not None:
        try:
            close()
        except SystemExit:
            return


def _json_safe(value):
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
