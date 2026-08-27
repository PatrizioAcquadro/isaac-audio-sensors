"""Direct RTX 4090 gate for Isaac Lab audio observations."""

from __future__ import annotations

import argparse
import json
import time
from contextlib import suppress
from types import SimpleNamespace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perf-envs", type=int, default=4096)
    parser.add_argument("--perf-steps", type=int, default=50)
    parser.add_argument("--perf-budget-ms", type=float, default=20.0)
    args = parser.parse_args()

    from isaaclab.app import AppLauncher

    launcher = AppLauncher(headless=True)
    simulation_app = launcher.app
    simulation_context = None
    try:
        import isaaclab.sim as sim_utils
        import torch
        from isaaclab.sensors import SensorBase, SensorBaseCfg
        from isaaclab.sim import SimulationContext

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable; the Isaac Lab gate cannot use CPU."
            )
        gpu_name = torch.cuda.get_device_name(0)
        if "RTX 4090" not in gpu_name:
            raise RuntimeError(f"Expected RTX 4090, found {gpu_name!r}.")

        from isaac_audio_sensors.lab import (
            AudioArraySensor,
            AudioArraySensorCfg,
            EntityBindingCfg,
            SourceEntityCfg,
        )

        if not issubclass(AudioArraySensor, SensorBase):
            raise RuntimeError("AudioArraySensor does not inherit SensorBase.")
        if not issubclass(AudioArraySensorCfg, SensorBaseCfg):
            raise RuntimeError("AudioArraySensorCfg does not inherit SensorBaseCfg.")

        simulation_context = SimulationContext(sim_utils.SimulationCfg(device="cuda:0"))
        _create_env_prims(sim_utils, "/World/parity", 2)
        _create_env_prims(sim_utils, "/World/perf", args.perf_envs)

        parity_scene = _entity_scene(
            torch,
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ((4.0, 0.0, 0.0), (0.0, 4.0, 0.0)),
        )
        array_ids, snapshots = _reference_scenes()
        parity_sensors = []
        for backend_id in ("geometry_only", "tdoa_synthetic"):
            entity_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/parity/env_.*/AudioSensor",
                    backend=backend_id,
                    max_events=2,
                )
            ).bind_entities(
                parity_scene,
                EntityBindingCfg(
                    source_entities=(SourceEntityCfg(entity_name="speaker"),)
                ),
            )
            reference_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/parity/env_.*/AudioSensor",
                    backend=backend_id,
                    max_events=2,
                )
            ).bind_reference(snapshots, array_ids)
            parity_sensors.append((backend_id, entity_sensor, reference_sensor))

        perf_scene = _entity_scene(
            torch,
            tuple((0.0, 0.0, 0.0) for _ in range(args.perf_envs)),
            tuple((4.0, 1.0, 0.0) for _ in range(args.perf_envs)),
        )
        perf_sensor = AudioArraySensor(
            AudioArraySensorCfg(
                prim_path="/World/perf/env_.*/AudioSensor",
                backend="tdoa_synthetic",
                max_events=1,
            )
        ).bind_entities(
            perf_scene,
            EntityBindingCfg(source_entities=(SourceEntityCfg(entity_name="speaker"),)),
        )

        simulation_context.reset()
        parity = {}
        for backend_id, entity_sensor, reference_sensor in parity_sensors:
            entity_sensor.update(0.0, force_recompute=True)
            reference_sensor.update(0.0, force_recompute=True)
            entity_data = entity_sensor.data
            reference_data = reference_sensor.data
            _assert_contract(entity_data, num_envs=2, max_events=2, num_mics=4)
            for name in (
                "event_presence",
                "bearing_deg",
                "confidence",
                "sector_onehot",
                "per_mic_rms",
                "ambiguity_mask",
            ):
                torch.testing.assert_close(
                    getattr(entity_data, name),
                    getattr(reference_data, name),
                    equal_nan=True,
                    atol=1e-4,
                    rtol=1e-4,
                )
            parity[backend_id] = True

        reset_sensor = parity_sensors[-1][1]
        reset_data = reset_sensor.data
        untouched = {
            name: getattr(reset_data, name)[0].clone()
            for name in reset_data.__dataclass_fields__
        }
        reset_sensor.reset([1])
        for name, expected in untouched.items():
            torch.testing.assert_close(
                getattr(reset_data, name)[0], expected, equal_nan=True
            )
        if reset_data.event_presence[1].any():
            raise RuntimeError("Partial reset did not clear the selected row.")
        if not torch.isnan(reset_data.bearing_deg[1]).all():
            raise RuntimeError("Partial reset did not restore bearing padding.")

        for _ in range(10):
            perf_sensor.update(1.0 / 60.0, force_recompute=True)
        torch.cuda.synchronize()
        started = time.perf_counter()
        for _ in range(args.perf_steps):
            perf_sensor.update(1.0 / 60.0, force_recompute=True)
        torch.cuda.synchronize()
        mean_ms = (time.perf_counter() - started) * 1000.0 / args.perf_steps
        _assert_contract(
            perf_sensor.data,
            num_envs=args.perf_envs,
            max_events=1,
            num_mics=4,
        )
        if mean_ms >= args.perf_budget_ms:
            raise RuntimeError(
                f"Mean step time {mean_ms:.3f} ms exceeds {args.perf_budget_ms:.3f} ms."
            )

        print(
            json.dumps(
                {
                    "status": "passed",
                    "gpu": gpu_name,
                    "parity": parity,
                    "partial_reset": True,
                    "perf_envs": args.perf_envs,
                    "perf_steps": args.perf_steps,
                    "mean_ms_per_step": mean_ms,
                    "budget_ms_per_step": args.perf_budget_ms,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        if simulation_context is not None:
            with suppress(Exception):
                simulation_context.stop()
            with suppress(Exception):
                simulation_context.clear_instance()
        simulation_app.close()


def _create_env_prims(sim_utils, root: str, count: int) -> None:
    sim_utils.create_prim(root, "Xform")
    for env_id in range(count):
        sim_utils.create_prim(f"{root}/env_{env_id}", "Xform")


def _entity_scene(torch, robot_positions, source_positions):
    def entity(positions):
        state = torch.zeros((len(positions), 13), dtype=torch.float32, device="cuda:0")
        state[:, :3] = torch.tensor(positions, dtype=torch.float32, device="cuda:0")
        state[:, 3] = 1.0
        return SimpleNamespace(data=SimpleNamespace(root_state_w=state))

    class Scene(dict):
        pass

    return Scene(robot=entity(robot_positions), speaker=entity(source_positions))


def _reference_scenes():
    from isaac_audio_sensors.core.microphone_array import create_microphone_array
    from isaac_audio_sensors.core.types import AudioSceneSnapshot, AudioSourceSpec

    arrays = tuple(
        create_microphone_array(
            array_id=f"array_{env_id}",
            prim_path=f"/World/array_{env_id}",
            layout_name="quad_front",
        )
        for env_id in range(2)
    )
    positions = ((4.0, 0.0, 0.0), (0.0, 4.0, 0.0))
    snapshots = tuple(
        AudioSceneSnapshot(
            stage_id=f"reference_{env_id}",
            timestamp_ms=0,
            arrays=(arrays[env_id],),
            sources=(
                AudioSourceSpec(
                    source_id="speaker",
                    prim_path=f"/World/speaker_{env_id}",
                    class_label="Sound",
                    audio_asset_path="generated://impulse",
                    position_world=positions[env_id],
                    orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
                    start_time_s=0.0,
                    duration_s=1.0,
                    gain_db=0.0,
                ),
            ),
        )
        for env_id in range(2)
    )
    return tuple(array.array_id for array in arrays), snapshots


def _assert_contract(data, *, num_envs: int, max_events: int, num_mics: int) -> None:
    import torch

    expected = {
        "event_presence": ((num_envs, max_events), torch.bool),
        "bearing_deg": ((num_envs, max_events), torch.float32),
        "confidence": ((num_envs, max_events), torch.float32),
        "sector_onehot": ((num_envs, max_events, 8), torch.float32),
        "per_mic_rms": ((num_envs, max_events, num_mics), torch.float32),
        "ambiguity_mask": ((num_envs, max_events), torch.bool),
    }
    for name, (shape, dtype) in expected.items():
        value = getattr(data, name)
        if tuple(value.shape) != shape or value.dtype != dtype:
            raise RuntimeError(f"Invalid {name} contract.")
        if value.device.type != "cuda":
            raise RuntimeError(f"{name} is not on the sensor CUDA device.")


if __name__ == "__main__":
    raise SystemExit(main())
