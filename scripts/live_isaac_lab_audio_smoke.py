"""Live Isaac Lab smoke validation for isaac_audio_sensors."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

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
                prim_path="{ENV_REGEX_NS}/Robot/audio_array",
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
        wrapper.reset(env_ids=[1])
        reset_env_1_presence = _tensor_to_json(data.event_presence[1])
        wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        data = wrapper.data
        explicit_devices = _buffer_devices(wrapper, data)
        if args.require_gpu:
            _assert_cuda_buffers(explicit_devices)

        stage, stage_kind = _create_audio_stage()
        evidence["stage_kind"] = stage_kind
        stage_wrapper = AudioArraySensor(
            cfg=AudioArraySensorCfg(
                prim_path="{ENV_REGEX_NS}/Robot/audio_array",
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
        moved_stage_bearing = _tensor_scalar(stage_data.bearing_deg[1, 0])
        moved_stage_diagnostics = stage_data.latest_frames[1].diagnostics.get(
            "stage_binding",
            {},
        )
        stage_wrapper.reset(env_ids=[1])
        stage_reset_presence = _tensor_to_json(stage_data.event_presence[1])
        stage_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        stage_data = stage_wrapper.data
        stage_devices = _buffer_devices(stage_wrapper, stage_data)
        if args.require_gpu:
            _assert_cuda_buffers(stage_devices)

        entity_scene = _create_entity_scene(device)
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
                prim_path="{ENV_REGEX_NS}/Robot/head/audio_array",
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
        first_entity_bearing = _tensor_scalar(entity_data.bearing_deg[1, 0])
        first_entity_diag = entity_data.latest_frames[1].diagnostics.get(
            "entity_binding",
            {},
        )
        _set_entity_source_position(entity_scene, env_id=1, position=(0.0, -4.0, 0.0))
        entity_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        entity_data = entity_wrapper.data
        moved_entity_bearing = _tensor_scalar(entity_data.bearing_deg[1, 0])
        moved_entity_diag = entity_data.latest_frames[1].diagnostics.get(
            "entity_binding",
            {},
        )
        entity_wrapper.reset(env_ids=[1])
        entity_reset_presence = _tensor_to_json(entity_data.event_presence[1])
        entity_wrapper.update(dt=0.05, force_recompute=True, env_ids=[1])
        entity_data = entity_wrapper.data
        entity_devices = _buffer_devices(entity_wrapper, entity_data)
        if args.require_gpu:
            _assert_cuda_buffers(entity_devices)

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
                "event_presence": _tensor_to_json(data.event_presence),
                "bearing_deg": _tensor_to_json(data.bearing_deg),
                "confidence": _tensor_to_json(data.confidence),
                "ambiguity_mask": _tensor_to_json(data.ambiguity_mask),
                "reset_env_1_presence_before_selected_update": reset_env_1_presence,
                "frame_ids": data.frame_ids,
                "source_ids": data.source_ids,
                "stage_auto_binding": {
                    "buffer_devices": stage_devices,
                    "semantic_discovery": True,
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
    scene: SimpleNamespace,
    *,
    env_id: int,
    position: tuple[float, float, float],
) -> None:
    import torch  # type: ignore

    tensor = scene.rigid_objects["speaker"].data.root_pos_w
    tensor[int(env_id)] = torch.tensor(
        position,
        dtype=tensor.dtype,
        device=tensor.device,
    )


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
