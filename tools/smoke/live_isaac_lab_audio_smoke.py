"""Live CUDA gate for Isaac Lab audio observations."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import traceback
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perf-envs", type=int, default=16)
    parser.add_argument("--perf-steps", type=int, default=5)
    parser.add_argument("--perf-substeps", type=int, default=1)
    parser.add_argument("--perf-reference-check", action="store_true")
    parser.add_argument("--perf-budget-ms", type=float, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("build/validation/isaac_audio_sensors/isaac_lab_live_smoke.json"),
    )
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--perf-sources", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--perf-layout",
        choices=("quad_front", "triangle", "square", "raised", "tetra"),
        default="quad_front",
    )
    args = parser.parse_args()
    if args.perf_envs < 2 or args.perf_steps < 1 or args.perf_substeps < 1:
        parser.error(
            "Performance checks require two environments and positive steps/substeps."
        )
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
        import numpy as np
        import torch
        from isaaclab.sensors import SensorBase, SensorBaseCfg
        from isaaclab.sim import SimulationContext

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable; the Isaac Lab gate cannot use CPU."
            )
        gpu_name = torch.cuda.get_device_name(0)
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

        from multisource_reference import reference_scenes

        source_scenes = reference_scenes(args.out.parent / "multisource_signals")
        asset = source_scenes[1].sources[0].audio_asset_path
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
                    energy_threshold_dbfs=-60.0,
                    update_period=0.1,
                )
            ).bind_entities(
                entity_scene,
                EntityBindingCfg(
                    environment=free_field_environment(
                        environment_id="lab_parity_free_field"
                    ),
                    source_entities=(
                        SourceEntityCfg(
                            entity_name="speaker",
                            audio_asset_path=asset,
                            duration_s=None,
                            loop_count=-1,
                        ),
                    ),
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

        rng = np.random.default_rng(72)
        angles = rng.uniform(-np.pi, np.pi, args.perf_envs)
        radii = rng.uniform(1.5, 3.0, args.perf_envs)
        heights = (
            radii * np.tan(rng.uniform(-np.pi / 6, np.pi / 6, args.perf_envs))
            if args.perf_layout in ("raised", "tetra")
            else np.zeros_like(radii)
        )
        perf_scene = _entity_scene(
            torch,
            tuple((0.0, 0.0, 0.0) for _ in range(args.perf_envs)),
            tuple(
                (float(r * np.cos(a)), float(r * np.sin(a)), float(z))
                for r, a, z in zip(radii, angles, heights, strict=True)
            ),
        )
        perf_sources = [
            SourceEntityCfg(
                entity_name="speaker",
                audio_asset_path=asset,
                duration_s=None,
                loop_count=-1,
            )
        ]
        if args.perf_sources == 2:
            state = perf_scene["speaker"].data.root_state_w.clone()
            x, y = state[:, 0].clone(), state[:, 1].clone()
            state[:, 0], state[:, 1] = -y, x
            perf_scene["second_speaker"] = SimpleNamespace(
                data=SimpleNamespace(root_state_w=state)
            )
            perf_sources.append(
                SourceEntityCfg(
                    entity_name="second_speaker",
                    audio_asset_path=source_scenes[1].sources[1].audio_asset_path,
                    duration_s=None,
                    loop_count=-1,
                )
            )
        perf_microphones = None
        if args.perf_layout != "quad_front":
            layout_index = ("triangle", "square", "raised", "tetra").index(
                args.perf_layout
            )
            perf_microphones = source_scenes[layout_index].arrays[0].microphones
        perf_sensor = AudioArraySensor(
            AudioArraySensorCfg(
                prim_path="/World/perf/env_.*/AudioSensor",
                backend="analytic_acoustics",
                max_observations=3,
                energy_threshold_dbfs=-60.0,
                doa_enabled=True,
                update_period=0.1,
            )
        ).bind_entities(
            perf_scene,
            EntityBindingCfg(
                environment=free_field_environment(
                    environment_id="lab_performance_free_field"
                ),
                source_entities=tuple(perf_sources),
                microphones=perf_microphones,
            ),
        )

        multisource_scenes = source_scenes
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
                entity_sensor.update(0.05, force_recompute=True)
                reference_sensor.update(0.05, force_recompute=True)
                entity_data = entity_sensor.data
                reference_data = reference_sensor.data
                _assert_contract(entity_data, num_envs=2, max_observations=2)
                _assert_contract(reference_data, num_envs=2, max_observations=2)
                if tick >= 1 and not entity_data.observation_mask[:, 0].all():
                    raise RuntimeError(
                        "Entity PCM activity did not reach observations."
                    )
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
        untouched_index = reset_sensor._audio_time[0].clone()
        reset_sensor.reset([1])
        for name, expected in untouched.items():
            torch.testing.assert_close(getattr(reset_data, name)[0], expected)
            if getattr(reset_data, name)[1].any():
                raise RuntimeError(f"Partial reset did not clear {name}.")
        reset_data = reset_sensor.data
        for name, expected in untouched.items():
            torch.testing.assert_close(getattr(reset_data, name)[0], expected)
        torch.testing.assert_close(reset_sensor._audio_time[0], untouched_index)
        if reset_data.observation_mask[1].any():
            raise RuntimeError("Reset did not clear the detector's minimum context.")
        reset_sensor.update(0.1, force_recompute=True)
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
        for tick in range(18):
            started = time.perf_counter()
            multisource_sensor.update(0.05, force_recompute=True)
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
            if tick < 14:
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
        for _ in range(15):
            multisource_sensor.update(0.05, force_recompute=True)
        if not multisource_sensor.data.observation_mask[1, :2].all():
            raise RuntimeError(
                "Reset multisource environment did not recover its events."
            )

        for _ in range(10):
            _advance_audio(perf_sensor, args.perf_substeps)
        before = perf_sensor._audio_last_update.clone()
        for _ in range(6):
            perf_sensor.update(1 / 60)
        torch.testing.assert_close(perf_sensor._audio_last_update, before)
        data = perf_sensor.data
        torch.testing.assert_close(perf_sensor._audio_last_update, before + 0.1)
        samples_before_read = perf_sensor._entity_backend.perception.samples.clone()
        _assert_same(torch, data, perf_sensor.data)
        torch.testing.assert_close(
            perf_sensor._entity_backend.perception.samples, samples_before_read
        )
        evidence["phase"] = "performance"
        _write_evidence(args.out, evidence)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        step_ms = []
        for _ in range(args.perf_steps):
            started = time.perf_counter()
            _advance_audio(perf_sensor, args.perf_substeps)
            torch.cuda.synchronize()
            step_ms.append((time.perf_counter() - started) * 1000)
        mean_ms = statistics.mean(step_ms)
        _assert_contract(perf_sensor.data, num_envs=args.perf_envs, max_observations=3)
        if not perf_sensor.data.observation_mask.any():
            raise RuntimeError(
                "Active perception benchmark returned only empty observations."
            )
        if args.perf_budget_ms is not None and mean_ms >= args.perf_budget_ms:
            raise RuntimeError(
                f"Mean step time {mean_ms:.3f} ms exceeds requested budget."
            )
        stages = {}
        if args.profile:
            with torch.profiler.profile(
                activities=[
                    torch.profiler.ProfilerActivity.CPU,
                    torch.profiler.ProfilerActivity.CUDA,
                ]
            ) as profile:
                _advance_audio(perf_sensor, args.perf_substeps)
                torch.cuda.synchronize()
            stages = {
                event.key: {
                    "cpu_total_ms": event.cpu_time_total / 1000
                    if event.cpu_time_total
                    else None,
                    "cuda_total_ms": event.device_time_total / 1000,
                }
                for event in profile.key_averages()
                if event.key.startswith("audio.")
            }
        quality = _entity_quality(torch, perf_sensor, perf_scene, args.perf_sources)
        # Snapshot memory before the optional, untimed scalar verification.
        peak_allocated_mib = torch.cuda.max_memory_allocated() / 2**20
        reference_quality = (
            _entity_reference_parity(perf_sensor) if args.perf_reference_check else None
        )
        evidence = {
            "status": "measured",
            "phase": "quality_and_reset",
            "gpu": gpu_name,
            "scalar_reference_parity": reference_parity,
            "multisource_planar_and_3d": True,
            "multisource_masks_capacity_and_partial_reset": True,
            "multisource_two_environment_update_ms": multi_compute_ms,
            "multisource_compute_device": (
                "CPU WPE/group-sparse covariance; CUDA tensor projection"
            ),
            "reference_activity_and_doa": True,
            "reference_warmup_and_silence": True,
            "performance_role": "active_cuda_free_field_waveforms_and_perception",
            "partial_reset": False,
            "perf_envs": args.perf_envs,
            "perf_sources": args.perf_sources,
            "perf_layout": args.perf_layout,
            "perf_steps": args.perf_steps,
            "perf_substeps": args.perf_substeps,
            "simulated_acquisition_hz": 10 * args.perf_substeps,
            "mean_ms_per_step": mean_ms,
            "p95_ms_per_step": sorted(step_ms)[math.ceil(0.95 * len(step_ms)) - 1],
            "step_ms": step_ms,
            "profile_stages": stages,
            "entity_quality": quality,
            "entity_reference_parity": reference_quality,
            "quality_gate": (
                "reference_preservation" if args.perf_reference_check else "nominal"
            ),
            "input_randomization": (
                "seed 72; 360-degree azimuth and 1.5-3 m range; "
                "raised/tetra elevation in [-30, 30] degrees"
            ),
            "peak_allocated_mib": peak_allocated_mib,
            "simulated_seconds_per_wall_second": 100.0 / mean_ms,
            "aggregate_env_updates_per_wall_second": args.perf_envs * 1000 / mean_ms,
            "aggregate_env_seconds_per_wall_second": args.perf_envs * 100 / mean_ms,
            "simulated_audio_hz": 10,
            "entity_observation_fraction": float(
                perf_sensor.data.observation_mask.any(dim=1).float().mean()
            ),
            "budget_ms_per_step": args.perf_budget_ms,
        }
        _write_evidence(args.out, evidence)
        if reference_quality is not None and not reference_quality["passed"]:
            raise RuntimeError(f"Reference preservation failed: {reference_quality}")
        if reference_quality is None and quality["complete_sets_within_20deg"] < 0.95:
            raise RuntimeError(f"Nominal free-field event-set gate failed: {quality}")
        sample_clock = perf_sensor._audio_time.clone()
        untouched = perf_sensor._entity_backend.perception.history[0].clone()
        torch.cuda.synchronize()
        reset_started = time.perf_counter()
        perf_sensor.reset([1])
        torch.cuda.synchronize()
        evidence["single_environment_reset_ms"] = (
            time.perf_counter() - reset_started
        ) * 1000
        torch.testing.assert_close(perf_sensor._audio_time[0], sample_clock[0])
        torch.testing.assert_close(
            perf_sensor._entity_backend.perception.history[0], untouched
        )
        if perf_sensor.data.observation_mask[1].any():
            raise RuntimeError("Entity reset retained old observations.")

        evidence.update(status="passed", phase="complete", partial_reset=True)
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


def _advance_audio(sensor, substeps):
    """Advance 100 ms of audio; physics and policy learning are not timed here."""
    for step in range(substeps):
        sensor.update(0.1 / substeps, force_recompute=step == substeps - 1)


def _entity_reference_parity(sensor):
    """Untimed scalar check on identical PCM, preserving existing false events."""
    import numpy as np

    from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer

    backend = sensor._entity_backend
    samples = backend.perception.history[:, :, -12000:].cpu().numpy()
    positions = backend.binding.static.mic_offsets_local.cpu().numpy()
    data = sensor.data
    localizer = MaintainedEventLocalizer()
    counts, matches, errors = [], [], []
    for row, values in enumerate(samples):
        events, _ = localizer.localize(values, positions, 16000)
        events = sorted(
            events,
            key=lambda event: (
                event.estimated_bearing_deg,
                event.estimated_elevation_deg or 0,
            ),
        )
        counts.append(len(events))
        valid = data.observation_mask[row]
        observed_count = int(valid.sum() + data.observations_truncated[row])
        matches.append(observed_count == len(events))
        expected = events[: data.observation_mask.shape[1]]
        if len(expected) != int(valid.sum()):
            continue
        actual = np.radians(
            np.stack(
                [
                    data.bearing_deg[row, valid].cpu().numpy(),
                    data.elevation_deg[row, valid].cpu().numpy(),
                ],
                axis=-1,
            )
        )
        for (azimuth, elevation), event in zip(actual, expected, strict=True):
            ref_az, ref_el = np.radians(
                [event.estimated_bearing_deg, event.estimated_elevation_deg or 0]
            )
            cosine = np.cos(elevation) * np.cos(ref_el) * np.cos(
                azimuth - ref_az
            ) + np.sin(elevation) * np.sin(ref_el)
            errors.append(float(np.degrees(np.arccos(np.clip(cosine, -1, 1)))))
    maximum_error = max(errors, default=0)
    p95_error = float(np.percentile(errors, 95)) if errors else 0.0
    count_agreement = sum(matches) / len(samples)
    return {
        "environments": len(samples),
        "count_matches": sum(matches),
        "count_agreement": count_agreement,
        "scalar_count_distribution": np.bincount(counts).tolist(),
        "max_retained_direction_difference_deg": maximum_error,
        "retained_direction_difference_p95_deg": p95_error,
        "direction_p95_tolerance_deg": 5.0,
        "passed": count_agreement >= 0.97 and p95_error <= 5.0,
    }


def _entity_quality(torch, sensor, scene, sources):
    """Evaluate nominal observed sets; scene truth never enters perception."""
    names = ("speaker", "second_speaker")[:sources]
    positions = torch.stack(
        [scene[name].data.root_state_w[:, :3] for name in names], dim=1
    )
    expected = torch.nn.functional.normalize(positions, dim=-1)
    observed = sensor.data
    az, el = torch.deg2rad(observed.bearing_deg), torch.deg2rad(observed.elevation_deg)
    vectors = torch.stack(
        [torch.cos(az) * torch.cos(el), torch.sin(az) * torch.cos(el), torch.sin(el)],
        dim=-1,
    )
    difference = torch.rad2deg(
        torch.acos((vectors @ expected.transpose(-1, -2)).clamp(-1, 1))
    )
    errors = difference.masked_fill(
        ~observed.bearing_deg_mask[..., None], torch.inf
    ).amin(dim=1)
    counts = observed.observation_mask.sum(dim=1)
    complete = (counts == sources) & (errors <= 20).all(dim=1)
    finite = errors[torch.isfinite(errors)]
    return {
        "complete_sets_within_20deg": float(complete.float().mean()),
        "observed_count_distribution": torch.bincount(counts, minlength=4).tolist(),
        "nearest_direction_p95_deg": float(torch.quantile(finite, 0.95))
        if finite.numel()
        else None,
    }


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
