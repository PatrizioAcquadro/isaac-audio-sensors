"""Live SDK latency and throughput; run with Isaac Lab's Python runtime."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import platform
import resource
import shutil
import subprocess
import threading
import time
import traceback
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace


def distribution(values):
    """Linear percentiles, retaining sample count and maximum for finite runs."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def percentile(q):
        index = (len(ordered) - 1) * q
        lo = int(index)
        return ordered[lo] + (ordered[math.ceil(index)] - ordered[lo]) * (index - lo)

    return dict(
        n=len(ordered),
        mean=sum(ordered) / len(ordered),
        p50=percentile(0.5),
        p95=percentile(0.95),
        p99=percentile(0.99),
        maximum=ordered[-1],
    )


def summarize(rows, envs, elapsed_s):
    updates = [r for r in rows if "sdk_ready_ms" in r]
    steady = [r for r in updates if r["phase"] == "steady"]
    active = [r for r in steady if r["events"] > 0]
    keys = (
        "sdk_ready_ms",
        "pcm_to_sdk_gpu_ms",
        "acquire_wall_ms",
        "consumer_cpu_ms",
        "deadline_to_sdk_ms",
        "window_age_wall_ms",
    )
    result = {
        "updates": len(updates),
        "steady_updates": len(steady),
        "steady_active_updates": len(active),
        "steady": {k: distribution([r[k] for r in steady]) for k in keys},
        "steady_active": {k: distribution([r[k] for r in active]) for k in keys},
        "startup_updates": [r for r in updates if r["phase"] != "steady"],
        "first_activity_update": next(
            (r for r in updates if r.get("activity_detected", r["events"] > 0)), None
        ),
        "first_direction_update": next((r for r in updates if r["events"] > 0), None),
        "simulation_step_ms": distribution([r["simulation_ms"] for r in rows]),
        "acquisition_ms": distribution([r["acquire_wall_ms"] for r in rows]),
        "max_tick_backlog": max(r["overdue_ticks"] for r in rows),
        "last_tick_backlog": rows[-1]["overdue_ticks"],
        "discontinuities": max(r.get("discontinuities", 0) for r in updates),
        "missed_audio_updates": sum(r.get("skipped_windows", 0) for r in updates),
        "steady_sdk_over_50ms": sum(r["sdk_ready_ms"] > 50 for r in steady),
        "steady_delivery_over_100ms": sum(
            r["deadline_to_sdk_ms"] > 100 for r in steady
        ),
        "wall_elapsed_s": elapsed_s,
        "simulated_s": len(rows) / 60,
        "aggregate_simulated_s_per_wall_s": envs * len(rows) / 60 / elapsed_s,
        "updates_per_wall_s": len(updates) / elapsed_s,
        "acquired_minus_processed_samples": rows[-1]["unprocessed_samples"],
        "deadline_drift_ms": (
            steady[-1]["deadline_to_sdk_ms"] - steady[0]["deadline_to_sdk_ms"]
        )
        if steady
        else None,
    }
    result["interactive_timing_pass"] = bool(
        steady
        and result["steady"]["sdk_ready_ms"]["p95"] <= 50
        and not result["missed_audio_updates"]
        and not result["discontinuities"]
        and result["last_tick_backlog"] <= 5
        and result["deadline_drift_ms"] <= 100
        and result["updates_per_wall_s"] >= 9.8
        and result["steady_delivery_over_100ms"] == 0
    )
    return result


def direction_lag(rows):
    """Past-direction fit is diagnostic; current-time errors remain unchanged."""
    import numpy as np

    selected = [
        r
        for r in rows
        if r.get("events") == 1
        and abs(35 / 2.25 * math.cos(r["audio_s"] / 2.25) - 60 * math.cos(r["audio_s"]))
        >= 20
    ]
    if len(selected) < 5:
        return {"status": "unidentifiable", "windows": len(selected)}
    times = np.array([r["audio_s"] for r in selected])
    bearings = np.array([r["bearings"][0] for r in selected])
    scan = []
    for lag in np.arange(0, 0.401, 0.01):
        past = times - lag
        expected = 35 * np.sin(past / 2.25) - 60 * np.sin(past)
        error = np.abs((bearings - expected + 180) % 360 - 180)
        scan.append(
            dict(
                lag_ms=float(lag * 1000),
                mean_error_deg=float(error.mean()),
                p95_error_deg=float(np.percentile(error, 95)),
            )
        )
    return dict(
        status="diagnostic_single_voice",
        windows=len(selected),
        fit=min(scan, key=lambda r: r["mean_error_deg"]),
        scan=scan,
    )


class GpuMonitor:
    """Retain per-process activity; never terminate another GPU client."""

    def __init__(self):
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        raw = subprocess.check_output(
            ["nvidia-smi", "pmon", "-c", "1", "-s", "um"],
            text=True,
            timeout=10,
        )
        processes = []
        for line in raw.splitlines():
            fields = line.split()
            if len(fields) < 12 or line.lstrip().startswith("#"):
                continue
            if fields[1].isdigit():
                processes.append(
                    dict(
                        pid=int(fields[1]),
                        kind=fields[2],
                        sm=int(fields[3]) if fields[3].isdigit() else 0,
                        framebuffer_mb=int(fields[9]) if fields[9].isdigit() else 0,
                        command=" ".join(fields[11:]),
                    )
                )
        sample = {"wall": time.perf_counter(), "processes": processes}
        self.samples.append(sample)
        return sample

    def run(self):
        while not self.stop.is_set():
            try:
                self.sample()
            except Exception as exc:
                self.samples.append({"wall": time.perf_counter(), "error": str(exc)})
            self.stop.wait(0.5)

    def assessment(self, start, end):
        selected = [s for s in self.samples if start <= s["wall"] <= end]
        external = [
            p
            for s in selected
            for p in s.get("processes", [])
            if p["pid"] != os.getpid() and ("C" in p["kind"] or p["sm"] >= 5)
        ]
        return dict(
            samples=len(selected),
            external_active=external,
            own_framebuffer_peak_mb=max(
                (
                    p["framebuffer_mb"]
                    for s in selected
                    for p in s.get("processes", [])
                    if p["pid"] == os.getpid()
                ),
                default=None,
            ),
            clean=bool(selected)
            and not external
            and not any("error" in s for s in selected),
        )


@contextmanager
def gpu_lock(path):
    with path.open("a+") as handle:
        print(f"Waiting for exclusive GPU lock: {path}", flush=True)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def scene(sim_utils, envs, workload):
    """Local primitives keep the declared load independent of asset downloads."""
    import omni.usd
    import torch
    from pxr import Gf, UsdPhysics

    root = "/World/Benchmark"
    sim_utils.create_prim(root, "Xform")
    for i in range(envs):
        sim_utils.create_prim(f"{root}/env_{i}", "Xform")
        sim_utils.create_prim(f"{root}/env_{i}/Audio", "Xform")
    if workload != "audio":
        ground = sim_utils.GroundPlaneCfg()
        ground.func("/World/Ground", ground)
        shape = sim_utils.CuboidCfg(
            size=(0.16, 0.16, 0.16),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(disable_gravity=True),
            mass_props=sim_utils.MassPropertiesCfg(mass=1),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.2, 0.6, 0.8)),
        )
        for i in range(envs):
            for j in range(64):
                shape.func(
                    f"{root}/env_{i}/Body{j}",
                    shape,
                    translation=(i * 4 + (j % 8) * 0.25, (j // 8) * 0.25, 1),
                )
                prim = (
                    omni.usd.get_context()
                    .get_stage()
                    .GetPrimAtPath(f"{root}/env_{i}/Body{j}")
                )
                UsdPhysics.RigidBodyAPI(prim).CreateVelocityAttr().Set(
                    Gf.Vec3f(0.12 if j % 2 else -0.12, 0.07, 0.03)
                )
    for name, cfg in (
        ("Dome", sim_utils.DomeLightCfg(intensity=1000)),
        ("Sun", sim_utils.DistantLightCfg(intensity=2000)),
    ):
        cfg.func(f"/World/{name}", cfg)

    def entity(position):
        state = torch.zeros((envs, 13), device="cuda:0")
        state[:, :3] = torch.tensor(position, device="cuda:0")
        state[:, 3] = 1
        return SimpleNamespace(data=SimpleNamespace(root_state_w=state))

    return dict(robot=entity((0, 0, 1.2)), speaker=entity((2.25, 0, 1.2)))


def onsets(pcm, rows, origin):
    """10 ms received-energy onset screen; private PCM is scoring only."""
    import numpy as np

    block = 160
    power = np.square(pcm[:, : pcm.shape[-1] // block * block].astype(float))
    audible = power.reshape(len(pcm), -1, block).mean(-1).max(0) >= 1e-6
    starts, last = [], -1000
    for index, active in enumerate(audible):
        if active:
            if index - last > 20:
                starts.append(index * 0.01)
            last = index
    updates = [r for r in rows if "sdk_ready_ms" in r]
    result = []
    for onset in starts:
        tick = min(int(onset * 60), len(rows) - 1)
        # Receipt is bracketed by that acquisition call, not audio-time == wall-time.
        lower, upper = rows[tick]["window_end_wall"], rows[tick]["acquired_wall"]
        next_onset = next((s for s in starts if s > onset), len(rows) / 60)
        response = next(
            (
                r
                for r in updates
                if onset <= r["audio_s"] < min(next_onset, onset + 2)
                and r["source_correct"]
            ),
            None,
        )
        result.append(
            dict(
                received_audio_onset_s=onset,
                acquisition_wall_lower_s=lower - origin,
                acquisition_wall_upper_s=upper - origin,
                already_acquiring=onset >= 0.2,
                audio_response_ms=None
                if response is None
                else (response["audio_s"] - onset) * 1000,
                wall_response_lower_ms=None
                if response is None
                else (response["ready_wall"] - upper) * 1000,
                wall_response_upper_ms=None
                if response is None
                else (response["ready_wall"] - lower) * 1000,
                scheduled_response_ms=None
                if response is None
                else (response["ready_wall"] - origin - onset) * 1000,
            )
        )
    return result


def acoustic_rooms(envs, library, specular_library, order):
    """Isolated six-wall native fixture for remeasuring a selected indoor profile."""
    import omni.usd
    from pxr import Sdf, UsdGeom

    from isaac_audio_sensors.isaac.acoustic_scene import (
        AcousticSceneSession,
        GeometryAcousticsConfig,
    )

    stage = omni.usd.get_context().get_stage()
    sessions = []
    for env in range(envs):
        root = f"/World/Benchmark/env_{env}/Room"
        for i, (position, scale) in enumerate(
            (
                ((0, 0, -0.05), (6, 5, 0.1)),
                ((0, 0, 3.05), (6, 5, 0.1)),
                ((-3.05, 0, 1.5), (0.1, 5, 3)),
                ((3.05, 0, 1.5), (0.1, 5, 3)),
                ((0, -2.55, 1.5), (6, 0.1, 3)),
                ((0, 2.55, 1.5), (6, 0.1, 3)),
            )
        ):
            cube = UsdGeom.Cube.Define(stage, f"{root}/Wall{i}")
            cube.CreateSizeAttr(1.0)
            cube.AddTranslateOp().Set(position)
            cube.AddScaleOp().Set(scale)
            cube.GetPrim().CreateAttribute(
                "ias:absorption", Sdf.ValueTypeNames.Float
            ).Set(0.4)
            cube.GetPrim().CreateAttribute(
                "ias:scattering", Sdf.ValueTypeNames.Float
            ).Set(0.0)
        sessions.append(AcousticSceneSession(stage, roots=(root,)))
    config = GeometryAcousticsConfig(
        library_path=str(library),
        specular_library_path=str(specular_library or ""),
        reflection_order=order,
        max_delay_s=1.0,
    )
    return config, sessions


def run(sensor, sim, camera, args, monitor, *, reset=False):
    import numpy as np
    import torch

    backend = sensor._entity_backend
    chunks = []
    observation_frames = []
    ingest = backend.perception.ingest

    def capture(ids, values, counts):
        # All environments share acquisition clocks; row zero has no padded samples.
        chunks.append(values[:1].clone())
        return ingest(ids, values, counts)

    backend.perception.ingest = capture
    seconds = args.reset_seconds if reset else args.seconds
    rows = []
    torch.cuda.synchronize()
    origin = time.perf_counter()
    previous_sample = 0
    radii = torch.linspace(1.5, 3.0, args.envs, device="cuda:0")
    radii[0] = 2.25
    phases = torch.arange(args.envs, device="cuda:0") * 0.3
    for tick in range(round(seconds * 60)):
        deadline = origin + (tick + 1) / 60
        if args.paced:
            time.sleep(max(0, deadline - time.perf_counter()))
        before_sim = time.perf_counter()
        sim.step(render=camera is not None)
        if camera is not None:
            camera.update(1 / 60)
            _ = camera.data.output["rgb"]
        # A moving source and rotating receiver expose stale direction information.
        audio_s = (tick + 1) / 60
        yaw = math.radians(60 * math.sin(audio_s))
        angle = math.radians(35 * math.sin(audio_s / 2.25))
        state = backend.binding._robot.data.root_state_w
        yaws = torch.deg2rad(60 * torch.sin(audio_s + phases))
        angles = torch.deg2rad(35 * torch.sin(audio_s / radii + phases))
        state[:, 3] = torch.cos(yaws / 2)
        state[:, 6] = torch.sin(yaws / 2)
        source = backend.binding._sources[0].data.root_state_w
        source[:, 0] = radii * torch.cos(angles)
        source[:, 1] = radii * torch.sin(angles)
        torch.cuda.synchronize()
        window_end = time.perf_counter()
        sensor.update(1 / 60)
        acquired_event = torch.cuda.Event(enable_timing=True)
        acquired_event.record()
        # Complete acquisition before marking PCM availability (conservative fence).
        torch.cuda.synchronize()
        acquired = time.perf_counter()
        row = dict(
            tick=tick,
            audio_s=audio_s,
            simulated_s=sim.get_physics_step_count() * sim.get_physics_dt(),
            phase="reset" if reset else "startup" if audio_s <= 1 else "steady",
            simulation_ms=(window_end - before_sim) * 1000,
            window_end_wall=window_end,
            acquired_wall=acquired,
            acquire_wall_ms=(acquired - window_end) * 1000,
            unprocessed_samples=int(
                backend.perception.samples[0] - backend.perception.last_processed[0]
            ),
        )
        if (tick + 1) % 6 == 0:
            data = sensor.data
            ready_event = torch.cuda.Event(enable_timing=True)
            ready_event.record()
            torch.cuda.synchronize()
            ready = time.perf_counter()
            cpu_start = time.perf_counter()
            fields = {
                name: getattr(data, name).cpu().numpy().copy()
                for name in data.__dataclass_fields__
            }
            observation_frames.append(fields)
            cpu_ready = time.perf_counter()
            mask = fields["bearing_deg_mask"][0]
            bearings = fields["bearing_deg"][0, mask].tolist()
            truth = math.degrees(angle - yaw) % 360
            errors = [abs((b - truth + 180) % 360 - 180) for b in bearings]
            sample = int(backend.perception.last_processed[0])
            row.update(
                ready_wall=ready,
                sdk_ready_ms=(ready - window_end) * 1000,
                pcm_to_sdk_gpu_ms=acquired_event.elapsed_time(ready_event),
                consumer_cpu_ms=(cpu_ready - cpu_start) * 1000,
                deadline_to_sdk_ms=(ready - deadline) * 1000,
                window_age_wall_ms=(
                    ready - (rows[-6]["window_end_wall"] if len(rows) >= 6 else origin)
                )
                * 1000,
                observation_audio_age_ms=100.0,
                localization_history_ms=args.context_s * 1000,
                events=int(fields["observation_mask"][0].sum()),
                activity_detected=bool(backend.perception.active[0]),
                bearings=bearings,
                angular_errors_deg=errors,
                source_correct=bool(errors and min(errors) <= 20),
                complete_set=bool(len(errors) == 1 and errors[0] <= 20),
                skipped_windows=max(0, (sample - previous_sample) // 1600 - 1),
                discontinuities=int(backend.discontinuity_count.max()),
                unprocessed_samples=int(
                    backend.perception.samples[0] - backend.perception.last_processed[0]
                ),
            )
            previous_sample = sample
        row["overdue_ticks"] = max(0, math.floor((time.perf_counter() - deadline) * 60))
        rows.append(row)
    torch.cuda.synchronize()
    end = time.perf_counter()
    backend.perception.ingest = ingest
    pcm = torch.cat(chunks, dim=-1)[0].cpu().numpy()
    np.savez(args.out / ("reset-pcm.npz" if reset else "received-pcm.npz"), samples=pcm)
    np.savez(
        args.out / ("reset-observations.npz" if reset else "observations.npz"),
        **{
            name: np.stack([frame[name] for frame in observation_frames])
            for name in observation_frames[0]
        },
    )
    result = summarize(rows, args.envs, end - origin)
    expected_samples = round(len(rows) / 60 * 16000)
    clock_samples = backend.cursor.cpu().tolist()
    result["audio_clock_samples"] = clock_samples
    result["expected_audio_clock_samples"] = expected_samples
    if any(c != expected_samples for c in clock_samples):
        raise RuntimeError("Acquired sample clocks disagree with elapsed audio time")
    active_rows = [r for r in rows if r.get("events", 0) > 0]
    result["active_complete_set_rate"] = (
        sum(r["complete_set"] for r in active_rows) / len(active_rows)
        if active_rows
        else None
    )
    result["current_direction_error_deg"] = distribution(
        [error for r in active_rows for error in r["angular_errors_deg"]]
    )
    result.update(
        rows=rows,
        onsets=onsets(pcm, rows, origin),
        directional_lag=direction_lag(rows),
        gpu_load=monitor.assessment(origin, end),
    )
    return result


def diagnostics(sensor, updates):
    """Separate synchronized stage attribution; never mix into latency gates."""
    import torch

    from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData

    sensor.reset()
    # Leading silence must not turn an inference profile into a silence profile.
    for _ in range(120):
        sensor.update(1 / 60)
        _ = sensor.data
    stages = {}
    patches = []

    def wrap(obj, name, label):
        original = getattr(obj, name)

        def measured(*args, **kwargs):
            torch.cuda.synchronize()
            start = time.perf_counter()
            value = original(*args, **kwargs)
            torch.cuda.synchronize()
            stages.setdefault(label, []).append((time.perf_counter() - start) * 1000)
            return value

        patches.append((obj, name, original))
        setattr(obj, name, measured)

    backend = sensor._entity_backend
    if hasattr(backend, "_geometry"):
        wrap(backend, "_geometry", "geometry")
    else:
        wrap(backend, "snapshots", "pose_device_to_host")
        for producer in backend.producers:
            wrap(producer, "propagate", "cpu_native_generation")
    wrap(backend.perception, "ingest", "buffering")
    wrap(backend, "acquire", "acquisition_including_buffering")
    wrap(backend.perception, "observations", "perception_including_projection")
    wrap(AudioArraySensorData, "write", "sdk_write")
    # Existing record_function scopes identify propagation, activity and sparse fit.
    try:
        with torch.profiler.profile(
            activities=[
                torch.profiler.ProfilerActivity.CPU,
                torch.profiler.ProfilerActivity.CUDA,
            ]
        ) as profiler:
            for _ in range(updates * 6):
                sensor.update(1 / 60)
                _ = sensor.data
        profiler.export_chrome_trace(str(sensor.cfg._performance_trace))
        events = [
            dict(
                name=e.key,
                cpu_total_ms=e.cpu_time_total / 1000,
                device_total_ms=e.device_time_total / 1000,
                calls=e.count,
            )
            for e in profiler.key_averages()
            if e.key.startswith("audio.") or "Memcpy" in e.key
        ]
    finally:
        for obj, name, original in reversed(patches):
            setattr(obj, name, original)
    return dict(
        stage_wall_ms={k: distribution(v) for k, v in stages.items()},
        profiler_scopes=events,
        cuda_profiler_status="available"
        if any(e["device_total_ms"] > 0 for e in events)
        else "unavailable; use fenced wall stages and CUDA event endpoints",
        scope="synchronized diagnostic, not qualification",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory; never overwritten"
    )
    parser.add_argument("--envs", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--reset-seconds", type=float, default=3)
    parser.add_argument("--paced", action="store_true")
    parser.add_argument(
        "--workload", choices=("audio", "physics", "render"), default="render"
    )
    parser.add_argument("--context-s", type=float, default=0.2)
    parser.add_argument("--wpe", action="store_true")
    parser.add_argument("--geometry-library", type=Path)
    parser.add_argument("--specular-library", type=Path)
    parser.add_argument("--reflection-order", type=int, default=3)
    parser.add_argument("--diagnostic-updates", type=int, default=5)
    parser.add_argument("--profile-initialization", action="store_true")
    parser.add_argument(
        "--gpu-lock", type=Path, default=Path("/tmp/isaac-audio-sensors-gpu.lock")
    )
    args = parser.parse_args()
    if args.envs < 1 or args.seconds < 3 or args.reset_seconds < 1:
        parser.error(
            "Positive environments, >=3 s measurement and >=1 s reset required"
        )
    if any(
        abs(s * 10 - round(s * 10)) > 1e-8 for s in (args.seconds, args.reset_seconds)
    ):
        parser.error("Measurement durations must end on a 100 ms observation boundary")
    args.asset = args.asset.resolve(strict=True)
    args.out.mkdir(parents=True, exist_ok=False)
    # Public source paths must stay inside this checkout. Preserve the input bytes.
    copied_asset = args.out / "source.wav"
    shutil.copyfile(args.asset, copied_asset)
    public_asset = copied_asset.resolve().relative_to(Path.cwd().resolve())
    evidence = dict(
        status="started",
        args={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    )
    output = args.out / "report.json"
    write(output, evidence)
    with gpu_lock(args.gpu_lock):
        monitor = GpuMonitor()
        monitor.sample()
        monitor.thread.start()
        app, sim, sensor = None, None, None
        sessions = []
        try:
            started = time.perf_counter()
            from isaaclab.app import AppLauncher

            app = AppLauncher(
                headless=True,
                enable_cameras=args.workload == "render",
                width=640,
                height=480,
            ).app
            evidence["app_startup_s"] = time.perf_counter() - started
            import isaaclab.sim as sim_utils
            import torch

            import isaac_audio_sensors
            from isaac_audio_sensors.core.acoustics import free_field_environment
            from isaac_audio_sensors.core.types import MicrophoneSpec
            from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg
            from isaac_audio_sensors.lab.entity_binding import (
                EntityBindingCfg,
                SourceEntityCfg,
            )

            if not torch.cuda.is_available():
                raise RuntimeError("Actual CUDA GPU required; no CPU fallback")
            root = Path(__file__).resolve().parents[2]
            module = Path(isaac_audio_sensors.__file__).resolve()
            if not module.is_relative_to(root / "src"):
                raise RuntimeError(f"Wrong SDK import: {module}")
            evidence.update(
                sdk_import=str(module),
                branch=subprocess.check_output(
                    ["git", "branch", "--show-current"], text=True
                ).strip(),
                commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                gpu=torch.cuda.get_device_name(),
                torch=torch.__version__,
                cuda=torch.version.cuda,
                host=platform.platform(),
                pid=os.getpid(),
                hardware=subprocess.check_output(["nvidia-smi"], text=True),
                workload=dict(
                    physics_hz=60,
                    observation_hz=10,
                    rigid_bodies=64 * args.envs if args.workload != "audio" else 0,
                    camera="one shared 640x480 RGB at 60 Hz"
                    if args.workload == "render"
                    else None,
                    backend="CUDA free-field analytic; mixture perception CUDA",
                    max_observations=32,
                    max_doa_candidates=2,
                    threshold_dbfs=-60,
                ),
            )
            sim = sim_utils.SimulationContext(
                sim_utils.SimulationCfg(device="cuda:0", dt=1 / 60, render_interval=1)
            )
            entities = scene(sim_utils, args.envs, args.workload)
            geometry_config = None
            if args.geometry_library:
                geometry_config, sessions = acoustic_rooms(
                    args.envs,
                    args.geometry_library,
                    args.specular_library,
                    args.reflection_order,
                )
                evidence["workload"]["backend"] = (
                    "CPU native geometry generation; H2D PCM; CUDA perception"
                )
            camera = None
            if args.workload == "render":
                from isaaclab.sensors import Camera, CameraCfg

                camera = Camera(
                    CameraCfg(
                        prim_path="/World/Camera",
                        width=640,
                        height=480,
                        data_types=["rgb"],
                        spawn=sim_utils.PinholeCameraCfg(),
                    )
                )
            sensor = AudioArraySensor(
                AudioArraySensorCfg(
                    prim_path="/World/Benchmark/env_.*/Audio",
                    update_period=0.1,
                    energy_threshold_dbfs=-60.0,
                    doa_enabled=True,
                    max_observations=32,
                    max_doa_candidates=2,
                    localization_context_s=args.context_s,
                    localization_dereverberation=args.wpe,
                    backend="geometry_acoustics"
                    if geometry_config
                    else "analytic_acoustics",
                    geometry_config=geometry_config,
                )
            ).bind_entities(
                entities,
                EntityBindingCfg(
                    environment=free_field_environment(environment_id="performance"),
                    microphones=tuple(
                        MicrophoneSpec(mic_id=str(i), relative_position_m=p)
                        for i, p in enumerate(
                            (
                                (-0.033, -0.033, 0),
                                (-0.033, 0.033, 0),
                                (0.033, 0.033, 0),
                                (0.033, -0.033, 0),
                            )
                        )
                    ),
                    source_entities=(
                        SourceEntityCfg(
                            entity_name="speaker",
                            audio_asset_path=str(public_asset),
                            duration_s=None,
                            loop_count=-1,
                        ),
                    ),
                ),
                acoustic_scenes=sessions or None,
            )
            start = time.perf_counter()
            if args.profile_initialization:
                with torch.profiler.profile(
                    activities=[
                        torch.profiler.ProfilerActivity.CPU,
                        torch.profiler.ProfilerActivity.CUDA,
                    ]
                ) as init_profiler:
                    sim.reset()
                    torch.cuda.synchronize()
                evidence["initialization_transfers"] = [
                    dict(
                        name=e.key, calls=e.count, device_ms=e.device_time_total / 1000
                    )
                    for e in init_profiler.key_averages()
                    if "Memcpy" in e.key
                ]
                evidence["initialization_transfer_status"] = (
                    "available"
                    if evidence["initialization_transfers"]
                    else "unavailable; missing CUPTI events, not zero transfer cost"
                )
            else:
                sim.reset()
            torch.cuda.synchronize()
            evidence["simulation_sensor_initialization_ms"] = (
                time.perf_counter() - start
            ) * 1000
            if camera is not None:
                camera.set_world_poses_from_view(
                    eyes=torch.tensor([[4.0, 4.0, 4.0]], device="cuda:0"),
                    targets=torch.tensor([[0.8, 0.8, 1.0]], device="cuda:0"),
                )
            for _ in range(180):
                sim.step(render=camera is not None)
            if camera is not None:
                camera.update(3.0)
                image = camera.data.output["rgb"].torch.float()
                evidence["render_check"] = dict(
                    shape=list(image.shape),
                    mean=float(image[..., :3].mean()),
                    variance=float(image[..., :3].var()),
                )
                if (
                    evidence["render_check"]["mean"] < 30
                    or evidence["render_check"]["variance"] < 15
                ):
                    raise RuntimeError("Rendering load produced black/flat frames")
            torch.cuda.reset_peak_memory_stats()
            evidence["measurement"] = run(sensor, sim, camera, args, monitor)
            write(output, evidence)
            start = time.perf_counter()
            sensor.reset()
            torch.cuda.synchronize()
            evidence["reset_ms"] = (time.perf_counter() - start) * 1000
            evidence["after_reset"] = run(
                sensor, sim, camera, args, monitor, reset=True
            )
            evidence["torch_peak_allocated_mb"] = (
                torch.cuda.max_memory_allocated() / 1e6
            )
            evidence["torch_peak_reserved_mb"] = torch.cuda.max_memory_reserved() / 1e6
            evidence["process_peak_rss_mb"] = (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            )
            if args.diagnostic_updates:
                sensor.cfg._performance_trace = args.out / "trace.json"
                evidence["diagnostics"] = diagnostics(sensor, args.diagnostic_updates)
            clean = evidence["measurement"]["gpu_load"]["clean"]
            evidence.update(
                status="measured",
                qualification="contaminated"
                if not clean
                else "pass"
                if args.paced
                and args.envs == 1
                and evidence["measurement"]["interactive_timing_pass"]
                else "measurement_only",
            )
            write(output, evidence)
            print(
                json.dumps(
                    {
                        k: evidence[k]
                        for k in ("status", "qualification", "torch_peak_allocated_mb")
                    }
                ),
                flush=True,
            )
        except BaseException as exc:
            evidence.update(
                status="failed", error=str(exc), traceback=traceback.format_exc()
            )
            write(output, evidence)
            raise
        finally:
            monitor.stop.set()
            monitor.thread.join(timeout=10)
            write(args.out / "gpu-monitor.json", monitor.samples)
            if sim is not None:
                if sensor is not None and hasattr(sensor._entity_backend, "close"):
                    sensor._entity_backend.close()
                for session in sessions:
                    session.close()
                with suppress(Exception):
                    sim.stop()
                    sim.clear_instance()
            if app is not None:
                app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
