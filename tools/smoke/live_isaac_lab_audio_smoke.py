"""Direct RTX 4090 gate for Isaac Lab audio observations."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perf-envs", type=int, default=4096)
    parser.add_argument("--perf-steps", type=int, default=50)
    parser.add_argument("--perf-budget-ms", type=float, default=20.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("build/validation/isaac_audio_sensors/isaac_lab_live_smoke.json"),
    )
    args = parser.parse_args()
    evidence = {"status": "started", "phase": "app_launcher"}
    _write_evidence(args.out, evidence)

    from isaaclab.app import AppLauncher

    launcher = AppLauncher(headless=True)
    simulation_app = launcher.app
    simulation_context = None
    gate_exit_code = 0
    try:
        evidence["phase"] = "runtime_imports"
        _write_evidence(args.out, evidence)
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
        evidence.update({"phase": "scene_setup", "gpu": gpu_name})
        _write_evidence(args.out, evidence)

        from isaac_audio_sensors.core.acoustics import free_field_environment
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
        evidence["phase"] = "sensor_setup"
        _write_evidence(args.out, evidence)

        parity_scene = _entity_scene(
            torch,
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ((4.0, 0.0, 0.0), (0.0, 4.0, 0.0)),
        )
        array_ids, snapshots = _reference_scenes()
        parity_sensors = []
        for backend_id in ("analytic_acoustics",):
            entity_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/parity/env_.*/AudioSensor",
                    backend=backend_id,
                    max_observations=2,
                )
            ).bind_entities(
                parity_scene,
                EntityBindingCfg(
                    environment=free_field_environment(
                        environment_id="lab_parity_free_field"
                    ),
                    source_entities=(SourceEntityCfg(entity_name="speaker"),),
                ),
            )
            reference_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/parity/env_.*/AudioSensor",
                    backend=backend_id,
                    max_observations=2,
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
                backend="analytic_acoustics",
                max_observations=1,
            )
        ).bind_entities(
            perf_scene,
            EntityBindingCfg(
                environment=free_field_environment(
                    environment_id="lab_performance_free_field"
                ),
                source_entities=(SourceEntityCfg(entity_name="speaker"),),
            ),
        )

        simulation_context.reset()
        evidence["phase"] = "parity"
        _write_evidence(args.out, evidence)
        parity = {}
        for backend_id, entity_sensor, reference_sensor in parity_sensors:
            entity_sensor.update(0.0, force_recompute=True)
            reference_sensor.update(0.0, force_recompute=True)
            entity_data = entity_sensor.data
            reference_data = reference_sensor.data
            _assert_contract(entity_data, num_envs=2, max_observations=2, num_mics=4)
            _assert_parity(torch, entity_data, reference_data)
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
        evidence["phase"] = "performance"
        _write_evidence(args.out, evidence)
        torch.cuda.synchronize()
        started = time.perf_counter()
        for _ in range(args.perf_steps):
            perf_sensor.update(1.0 / 60.0, force_recompute=True)
        torch.cuda.synchronize()
        mean_ms = (time.perf_counter() - started) * 1000.0 / args.perf_steps
        _assert_contract(
            perf_sensor.data,
            num_envs=args.perf_envs,
            max_observations=1,
            num_mics=4,
        )
        if mean_ms >= args.perf_budget_ms:
            raise RuntimeError(
                f"Mean step time {mean_ms:.3f} ms exceeds {args.perf_budget_ms:.3f} ms."
            )

        evidence = {
            "status": "passed",
            "phase": "complete",
            "gpu": gpu_name,
            "parity": parity,
            "partial_reset": True,
            "perf_envs": args.perf_envs,
            "perf_steps": args.perf_steps,
            "mean_ms_per_step": mean_ms,
            "budget_ms_per_step": args.perf_budget_ms,
        }
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, sort_keys=True))
        return 0
    except BaseException as exc:  # noqa: BLE001 - preserve gate diagnostics.
        gate_exit_code = 1
        evidence.update(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        _write_evidence(args.out, evidence)
        if isinstance(exc, KeyboardInterrupt):
            raise
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            raise RuntimeError("Isaac Lab exited before completing the gate.") from exc
        raise
    finally:
        if simulation_context is not None:
            with suppress(Exception):
                simulation_context.stop()
            with suppress(Exception):
                simulation_context.clear_instance()
        simulation_app.close(exit_code=gate_exit_code)


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def _assert_parity(torch, entity_data, reference_data) -> None:
    for name in entity_data.__dataclass_fields__:
        torch.testing.assert_close(
            getattr(entity_data, name),
            getattr(reference_data, name),
            equal_nan=True,
            msg=name,
        )


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
    from isaac_audio_sensors.core.acoustics import free_field_environment
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
            environment=free_field_environment(
                environment_id=f"reference_{env_id}_free_field"
            ),
        )
        for env_id in range(2)
    )
    return tuple(array.array_id for array in arrays), snapshots


def _assert_contract(
    data,
    *,
    num_envs: int,
    max_observations: int,
    num_mics: int,
) -> None:
    import torch

    expected = {
        "event_presence": ((num_envs, max_observations), torch.bool),
        "bearing_deg": ((num_envs, max_observations), torch.float32),
        "confidence": ((num_envs, max_observations), torch.float32),
        "sector_onehot": ((num_envs, max_observations, 8), torch.float32),
        "per_mic_rms": ((num_envs, max_observations, num_mics), torch.float32),
        "ambiguity_mask": ((num_envs, max_observations), torch.bool),
    }
    for name, (shape, dtype) in expected.items():
        value = getattr(data, name)
        if tuple(value.shape) != shape or value.dtype != dtype:
            raise RuntimeError(f"Invalid {name} contract.")
        if value.device.type != "cuda":
            raise RuntimeError(f"{name} is not on the sensor CUDA device.")
    if data.event_presence.any():
        raise RuntimeError("Phase 02.2 Lab output must contain zero observations.")
    if data.confidence.any() or data.per_mic_rms.any() or data.sector_onehot.any():
        raise RuntimeError("Phase 02.2 Lab observation payload must be zero-filled.")
    if not torch.isnan(data.bearing_deg).all():
        raise RuntimeError("Phase 02.2 Lab bearing padding must remain NaN.")


if __name__ == "__main__":
    raise SystemExit(main())
