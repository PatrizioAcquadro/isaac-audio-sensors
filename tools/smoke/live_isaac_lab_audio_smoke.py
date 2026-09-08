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
        _create_env_prims(sim_utils, "/World/reference", 2)
        _create_env_prims(sim_utils, "/World/perf", args.perf_envs)
        evidence["phase"] = "sensor_setup"
        _write_evidence(args.out, evidence)

        entity_scene = _entity_scene(
            torch,
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ((4.0, 0.0, 0.0), (0.0, 4.0, 0.0)),
        )
        array_ids, snapshots = _reference_scenes()
        sensor_pairs = []
        for backend_id in ("analytic_acoustics",):
            entity_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/reference/env_.*/AudioSensor",
                    backend=backend_id,
                    max_observations=2,
                )
            ).bind_entities(
                entity_scene,
                EntityBindingCfg(
                    environment=free_field_environment(
                        environment_id="lab_parity_free_field"
                    ),
                    source_entities=(SourceEntityCfg(entity_name="speaker"),),
                ),
            )
            reference_sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/reference/env_.*/AudioSensor",
                    backend=backend_id,
                    max_observations=2,
                    update_period=0.05,
                    energy_threshold_dbfs=-60.0,
                    doa_enabled=True,
                )
            ).bind_reference(snapshots, array_ids)
            sensor_pairs.append((backend_id, entity_sensor, reference_sensor))

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

        from multisource_reference import reference_scenes

        multisource_scenes = reference_scenes(args.out.parent / "multisource_signals")
        multisource_scenes = (multisource_scenes[1], multisource_scenes[3])
        multisource_ids = tuple(
            scene.arrays[0].array_id for scene in multisource_scenes
        )
        multisource_sensor = AudioArraySensor(
            AudioArraySensorCfg(
                prim_path="/World/reference/env_.*/AudioSensor",
                backend="analytic_acoustics",
                max_observations=3,
                update_period=0.05,
                energy_threshold_dbfs=-60.0,
                doa_enabled=True,
            )
        ).bind_reference(multisource_scenes, multisource_ids)

        simulation_context.reset()
        evidence["phase"] = "observed_reference"
        _write_evidence(args.out, evidence)
        from isaac_audio_sensors.core.backends.base import get_backend
        from isaac_audio_sensors.core.perception import (
            _build_standard_perception_pipeline,
        )
        from isaac_audio_sensors.core.simulation import simulate_frame
        from isaac_audio_sensors.core.types import AudioTimeWindow
        from isaac_audio_sensors.lab import AudioArraySensorData

        scalar_backend = get_backend("analytic_acoustics")
        scalar_pipelines = [
            _build_standard_perception_pipeline(
                energy_threshold_dbfs=-60.0, doa_enabled=True
            )
            for _ in snapshots
        ]
        reference_parity = {}
        for backend_id, entity_sensor, reference_sensor in sensor_pairs:
            resolved = False
            for tick in range(6):
                entity_sensor.update(0.0 if tick == 0 else 0.05, force_recompute=True)
                reference_sensor.update(
                    0.0 if tick == 0 else 0.05, force_recompute=True
                )
                entity_data = entity_sensor.data
                reference_data = reference_sensor.data
                _assert_contract(entity_data, num_envs=2, max_observations=2)
                _assert_contract(reference_data, num_envs=2, max_observations=2)
                if entity_data.observation_mask.any():
                    raise RuntimeError("Entity binding fabricated observations.")
                frames = [
                    simulate_frame(
                        scalar_backend,
                        snapshot,
                        array_id,
                        AudioTimeWindow(
                            start_time_s=tick * 0.05,
                            end_time_s=(tick + 1) * 0.05,
                            frame_index=tick,
                        ),
                        perception=pipeline,
                    )[0]
                    for snapshot, array_id, pipeline in zip(
                        snapshots, array_ids, scalar_pipelines, strict=True
                    )
                ]
                expected = AudioArraySensorData.from_observations(
                    [frame.observations for frame in frames],
                    max_observations=2,
                    device="cuda:0",
                )
                _assert_same(torch, reference_data, expected)
                if tick >= 1 and not reference_data.observation_mask[:, 0].all():
                    raise RuntimeError("Reference activity never reached the tensors.")
                if tick == 1 and (
                    reference_data.bearing_deg_mask.any()
                    or not reference_data.ambiguity_mask[:, 0].all()
                ):
                    raise RuntimeError("DOA warm-up did not remain unresolved.")
                resolved |= bool(reference_data.bearing_deg_mask.any())
            if not resolved:
                raise RuntimeError("Reference DOA never resolved after warm-up.")
            reference_parity[backend_id] = True

        reset_sensor = sensor_pairs[-1][2]
        reset_data = reset_sensor.data
        untouched = {
            name: getattr(reset_data, name)[0].clone()
            for name in reset_data.__dataclass_fields__
        }
        untouched_index = reset_sensor._reference_frame_indices[0].clone()
        reset_sensor.reset([1])
        for name, expected in untouched.items():
            torch.testing.assert_close(getattr(reset_data, name)[0], expected)
            if getattr(reset_data, name)[1].any():
                raise RuntimeError(f"Partial reset did not clear {name}.")
        reset_data = reset_sensor.data
        for name, expected in untouched.items():
            torch.testing.assert_close(getattr(reset_data, name)[0], expected)
        torch.testing.assert_close(
            reset_sensor._reference_frame_indices[0], untouched_index
        )
        if reset_data.observation_mask[1].any():
            raise RuntimeError("Reset did not clear the detector's minimum context.")
        reset_sensor.update(0.05, force_recompute=True)
        reset_data = reset_sensor.data
        if (
            not reset_data.observation_mask[1, 0]
            or reset_data.bearing_deg_mask[1].any()
        ):
            raise RuntimeError("Reset reference did not restart active DOA warm-up.")
        if not reset_data.doa_mask[1, 0] or not reset_data.ambiguity_mask[1, 0]:
            raise RuntimeError("Reset reference lost unresolved DOA evidence.")
        reset_sensor.update(1.1, force_recompute=True)
        if reset_sensor.data.observation_mask.any():
            raise RuntimeError("Reference activity did not clear after source end.")

        evidence["phase"] = "multisource_reference"
        _write_evidence(args.out, evidence)
        multi_pipelines = [
            _build_standard_perception_pipeline(
                energy_threshold_dbfs=-60, doa_enabled=True
            )
            for _ in multisource_scenes
        ]
        multi_compute_ms = []
        for tick in range(8):
            started = time.perf_counter()
            multisource_sensor.update(0.0 if tick == 0 else 0.05, force_recompute=True)
            data = multisource_sensor.data
            torch.cuda.synchronize()
            multi_compute_ms.append((time.perf_counter() - started) * 1000)
            frames = [
                simulate_frame(
                    scalar_backend,
                    scene,
                    array_id,
                    AudioTimeWindow(
                        start_time_s=tick * 0.05,
                        end_time_s=(tick + 1) * 0.05,
                        frame_index=tick,
                    ),
                    perception=pipeline,
                )[0]
                for scene, array_id, pipeline in zip(
                    multisource_scenes, multisource_ids, multi_pipelines, strict=True
                )
            ]
            expected = AudioArraySensorData.from_observations(
                [frame.observations for frame in frames],
                max_observations=3,
                device="cuda:0",
            )
            _assert_same(torch, data, expected)
            if tick < 4:
                if data.observation_mask.any():
                    raise RuntimeError("Multisource warm-up invented an event.")
                continue
            if not torch.equal(
                data.observation_mask.sum(dim=1), torch.tensor([2, 2], device="cuda:0")
            ):
                raise RuntimeError(
                    "Distinct simultaneous events did not reach both Lab environments."
                )
            if data.detection_score_mask.any() or data.ambiguity_mask.any():
                raise RuntimeError(
                    "Global activity or ambiguous candidates became individual events."
                )
            if (
                data.elevation_deg_mask[0].any()
                or not data.elevation_deg_mask[1, :2].all()
            ):
                raise RuntimeError(
                    "Planar and rank-3 elevation observability were mixed."
                )
            if data.observation_mask[:, 2].any() or data.bearing_deg[:, 2].any():
                raise RuntimeError("Padding is not empty and finite.")
            for capacity in (0, 1):
                capped = AudioArraySensorData.from_observations(
                    [frame.observations for frame in frames],
                    max_observations=capacity,
                    device="cuda:0",
                )
                if not (capped.observations_truncated == 2 - capacity).all():
                    raise RuntimeError("Multisource truncation was hidden.")
        retained = multisource_sensor.data.bearing_deg[0].clone()
        multisource_sensor.reset([1])
        torch.testing.assert_close(multisource_sensor.data.bearing_deg[0], retained)
        if multisource_sensor.data.observation_mask[1].any():
            raise RuntimeError("Multisource partial reset retained old events.")
        for _ in range(4):
            multisource_sensor.update(0.05, force_recompute=True)
        if not multisource_sensor.data.observation_mask[1, :2].all():
            raise RuntimeError(
                "Reset multisource environment did not recover its events."
            )

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
        )
        if mean_ms >= args.perf_budget_ms:
            raise RuntimeError(
                f"Mean step time {mean_ms:.3f} ms exceeds {args.perf_budget_ms:.3f} ms."
            )

        evidence = {
            "status": "passed",
            "phase": "complete",
            "gpu": gpu_name,
            "scalar_reference_parity": reference_parity,
            "multisource_planar_and_3d": True,
            "multisource_masks_capacity_and_partial_reset": True,
            "multisource_two_environment_update_ms": multi_compute_ms,
            "multisource_compute_device": "CPU MUSIC; CUDA tensor projection",
            "reference_activity_and_doa": True,
            "reference_warmup_and_silence": True,
            "performance_role": "empty_entity_lifecycle_only",
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


def _assert_same(torch, actual, expected) -> None:
    for name in actual.__dataclass_fields__:
        torch.testing.assert_close(
            getattr(actual, name),
            getattr(expected, name),
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


def _assert_contract(data, *, num_envs: int, max_observations: int) -> None:
    import torch

    from isaac_audio_sensors.lab import AudioArraySensorData

    expected = AudioArraySensorData.allocate(
        num_envs=num_envs, max_observations=max_observations, device="cuda:0"
    )
    for name in expected.__dataclass_fields__:
        value = getattr(data, name)
        template = getattr(expected, name)
        if value.shape != template.shape or value.dtype != template.dtype:
            raise RuntimeError(f"Invalid {name} contract.")
        if value.device != template.device:
            raise RuntimeError(f"{name} is not on the sensor CUDA device.")
        if not torch.isfinite(value).all():
            raise RuntimeError(f"{name} contains non-finite policy input.")
        if name.endswith("_mask") or name.endswith("_truncated"):
            continue
        if value[~getattr(data, name + "_mask")].any():
            raise RuntimeError(f"{name} contains nonzero padding.")


if __name__ == "__main__":
    raise SystemExit(main())
