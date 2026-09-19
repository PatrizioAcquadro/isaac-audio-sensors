"""Bounded native NLOS producer with live Isaac GPU simulation and door updates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--specular-library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--combined", action="store_true")
    args = parser.parse_args()
    from isaacsim import SimulationApp

    app = SimulationApp(
        {
            "headless": True,
            "width": 1280,
            "height": 720,
            "renderer": "RayTracedLighting",
        }
    )
    backend = session = None
    try:
        import numpy as np
        import omni.timeline
        import omni.usd
        from isaacsim.core.simulation_manager import SimulationManager
        from pxr import Sdf, UsdGeom, UsdLux, UsdPhysics

        from isaac_audio_sensors.core.acoustics import free_field_environment
        from isaac_audio_sensors.core.microphone_array import create_microphone_array
        from isaac_audio_sensors.core.types import (
            AudioSceneSnapshot,
            AudioSourceSpec,
            AudioTimeWindow,
        )
        from isaac_audio_sensors.isaac.acoustic_scene import (
            AcousticSceneSession,
            GeometryAcoustics,
            GeometryAcousticsConfig,
            PRADiffuseConfig,
            SteamNLOSConfig,
        )
        from isaac_audio_sensors.isaac.acoustic_scene.session import DYNAMIC

        print("NLOS live: authoring stage", flush=True)
        omni.usd.get_context().new_stage()
        stage = omni.usd.get_context().get_stage()
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, "Z")
        UsdLux.DomeLight.Define(stage, "/Dome").CreateIntensityAttr(300)
        UsdLux.DistantLight.Define(stage, "/Sun").CreateIntensityAttr(1000)
        door_op = None
        for name, position, scale in (
            ("Floor", (0, 0, -0.05), (6, 6, 0.1)),
            ("Door", (0, 0, 1.5), (0.05, 1.2, 3)),
        ):
            cube = UsdGeom.Cube.Define(stage, "/World/" + name)
            cube.CreateSizeAttr(1.0)
            op = cube.AddTranslateOp()
            op.Set(position)
            cube.AddScaleOp().Set(scale)
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
            if name == "Door":
                door_op = op
                cube.GetPrim().CreateAttribute(DYNAMIC, Sdf.ValueTypeNames.Token).Set(
                    "dynamic"
                )
                body = UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())
                body.CreateKinematicEnabledAttr(True)
            if args.combined:
                cube.GetPrim().CreateAttribute(
                    "ias:absorption", Sdf.ValueTypeNames.Float
                ).Set(0.4)
                cube.GetPrim().CreateAttribute(
                    "ias:scattering", Sdf.ValueTypeNames.Float
                ).Set(0.35)
        if args.combined:
            wall = UsdGeom.Mesh.Define(stage, "/World/RearWall")
            wall.GetSubdivisionSchemeAttr().Set("none")
            wall.GetPointsAttr().Set([(-3, -2, 0), (3, -2, 0), (3, -2, 3), (-3, -2, 3)])
            wall.GetFaceVertexCountsAttr().Set([4])
            wall.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
            wall.GetPrim().CreateAttribute(
                "ias:absorption", Sdf.ValueTypeNames.Float
            ).Set(0.4)
            wall.GetPrim().CreateAttribute(
                "ias:scattering", Sdf.ValueTypeNames.Float
            ).Set(0.35)
        for _ in range(3):
            app.update()
        print("NLOS live: initializing physics", flush=True)
        SimulationManager.setup_simulation(dt=1 / 60, device="cuda:0")
        omni.timeline.get_timeline_interface().play()
        for _ in range(3):
            app.update()
        print("NLOS live: physics initialized", flush=True)
        import torch

        assert torch.cuda.is_available(), "Actual CUDA GPU is required."
        tensor = torch.arange(64, device="cuda")
        assert tensor.sum().item() == 2016
        omni.timeline.get_timeline_interface().pause()
        device = str(SimulationManager.get_physics_sim_device())
        assert "cuda" in device, device
        array = create_microphone_array(
            array_id="array",
            prim_path="/Array",
            layout_name="quad_cross",
            position_world=(-2, 0, 1.2),
            sample_rate_hz=16000,
        )
        source = AudioSourceSpec(
            source_id="tone",
            prim_path="/Source",
            class_label="test",
            audio_asset_path="generated://tone",
            position_world=(2, 0, 1.2),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=3.6 if args.combined else None,
            gain_db=0.0,
        )
        snapshot = AudioSceneSnapshot(
            stage_id="live-nlos",
            sources=(source,),
            arrays=(array,),
            environment=free_field_environment(environment_id="free"),
        )
        session = AcousticSceneSession(stage, roots=("/World",))
        backend = GeometryAcoustics(
            acoustic_scene=session,
            geometry_config=GeometryAcousticsConfig(
                library_path=str(args.library),
                specular_library_path=str(args.specular_library),
                reflection_order=1 if args.combined else 0,
                max_delay_s=0.1 if args.combined else 1.0,
                nlos=SteamNLOSConfig(probe_spacing_m=0.5),
                diffuse=PRADiffuseConfig(rays=4096, surface_spacing_m=0.5)
                if args.combined
                else None,
                diagnostics=True,
            ),
        )
        states, peaks = [], []
        print("NLOS live: starting producer", flush=True)
        for tick in range(240):
            if tick % 60 == 0:
                print(f"NLOS live: tick {tick}", flush=True)
            # Ordinary 1.5-second opening and closing, with settled end states.
            time = tick / 60
            fraction = (
                np.clip((time - 0.25) / 1.5, 0.0, 1.0)
                if time < 2
                else 1 - np.clip((time - 2) / 1.5, 0.0, 1.0)
            )
            door_op.Set((0, 2 * fraction, 1.5))
            SimulationManager.step()
            if tick % 6 == 0:
                app.update()
            start, end = round(tick * 16000 / 60), round((tick + 1) * 16000 / 60)
            block = backend.propagate(
                snapshot,
                "array",
                AudioTimeWindow(
                    start_time_s=start / 16000, end_time_s=end / 16000, frame_index=tick
                ),
            )
            assert np.isfinite(block.samples).all()
            if args.combined:
                assert (
                    block.diagnostics["geometry"]["domain"]
                    == "direct+specular+diffuse+nlos"
                )
                assert block.diagnostics["geometry"]["diffuse"]["modes"] > 0
            states.append(block.diagnostics["geometry"]["nlos"]["coverage"]["tone"])
            peaks.append(float(np.max(abs(block.samples))))
        assert "selected" in states[0] and "selected" in states[-1]
        assert any("los" in state for state in states)
        assert backend.nlos.bakes == 1
        if args.combined:
            assert max(peaks[216:218]) > 1e-5  # In-flight sound after emission stops.
            assert max(peaks[234:]) < 1e-7
        backend.reset()
        reset = backend.propagate(
            snapshot,
            "array",
            AudioTimeWindow(start_time_s=0.0, end_time_s=0.05, frame_index=0),
        )
        assert reset.discontinuity and np.isfinite(reset.samples).all()
        result = dict(
            status="passed",
            gpu=torch.cuda.get_device_name(),
            physics_device=device,
            simulation_s=4,
            native_updates=session.provider.updates,
            states=states,
            peaks=peaks,
            reset=True,
            combined=args.combined,
            source_stop_tail=args.combined,
            scope="Combined producer lifecycle"
            if args.combined
            else "NLOS producer lifecycle",
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in ("states", "peaks")}
            )
        )
    finally:
        if backend:
            backend.close()
        if session:
            session.close()
        app.close()


if __name__ == "__main__":
    main()
