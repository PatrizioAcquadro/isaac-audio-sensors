"""Exercise USD preparation, shared Kit edits and Steam scenes on live Isaac."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("build/validation/r10/scene"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    from live_isaac_sim_audio_smoke import _ensure_isaac_runtime, _record_gpu_preflight

    evidence = {}
    app = _ensure_isaac_runtime(evidence, headless=False)
    panel = None
    try:
        import carb
        import omni.kit.app
        import omni.kit.undo
        import omni.physx
        import omni.timeline
        import omni.ui as ui
        import omni.usd
        from pxr import UsdGeom, UsdPhysics

        from isaac_audio_sensors.kit.acoustic_scene import (
            AcousticScenePanel,
        )

        _record_gpu_preflight(evidence)
        assert evidence["gpu_visible"], evidence
        omni.usd.get_context().new_stage()
        stage = omni.usd.get_context().get_stage()
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, "Z")
        UsdPhysics.Scene.Define(stage, "/Physics")
        wall = UsdGeom.Mesh.Define(stage, "/World/Wall")
        wall.CreateSubdivisionSchemeAttr("none")
        wall.CreatePointsAttr([(0, -2, 0), (0, 2, 0), (0, 2, 3), (0, -2, 3)])
        wall.CreateFaceVertexCountsAttr([4])
        wall.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
        door = UsdGeom.Cube.Define(stage, "/World/Door")
        door.CreateSizeAttr(0.3)
        door.AddTranslateOp().Set((2, 0, 3))
        UsdPhysics.RigidBodyAPI.Apply(door.GetPrim())
        UsdPhysics.CollisionAPI.Apply(door.GetPrim())
        window = ui.Window("Acoustic Scene - 08.1 verification", width=750, height=1000)
        with window.frame, ui.ScrollingFrame():
            panel = AcousticScenePanel(ui)
            panel.build()
        panel.import_scene()
        session = panel.session
        assert not session.issues, session.issues
        assert len(session.objects) == 2
        omni.usd.get_context().get_selection().set_selected_prim_paths(
            ["/World/Wall"], False
        )
        panel.edit({"ias:absorption": 0.3})
        assert session.objects["/World/Wall"].materials[0].absorption.values == (0.3,)
        omni.kit.undo.undo()
        assert session.objects["/World/Wall"].materials[0].absorption.values != (0.3,)
        omni.kit.undo.redo()
        assert session.objects["/World/Wall"].materials[0].absorption.values == (0.3,)
        panel.library.set_value(str(args.library.resolve()))
        panel.verify()
        assert session.provider and session.provider.verified, panel.status.text
        static = session.objects["/World/Wall"].points
        builds = session.provider.builds
        timeline = omni.timeline.get_timeline_interface()
        carb.settings.get_settings().set_bool("/physics/updateToUsd", False)
        timeline.play()
        for _ in range(45):
            omni.kit.app.get_app().update()
        session.refresh(timeline.get_current_time() * stage.GetTimeCodesPerSecond())
        assert not session.issues, session.issues
        assert session.objects["/World/Wall"].points is static
        assert session.provider.builds == builds
        assert session.provider.updates > 0
        assert session.objects["/World/Door"].transform[3, 1] < 3
        timeline.stop()
        carb.settings.get_settings().set_bool("/physics/updateToUsd", True)
        session.refresh()
        panel._render()
        stage.GetRootLayer().Export(str(args.out / "scene.usda"))
        session.provider.export_geometry(args.out / "native.obj")
        import numpy as np

        vertices = np.array(
            [
                [float(v) for v in line.split()[1:]]
                for line in (args.out / "native.obj").read_text().splitlines()
                if line.startswith("v ")
            ]
        )
        expected = np.concatenate(
            [obj.world_points for obj in session.objects.values()]
        )
        np.testing.assert_allclose(vertices, expected, atol=1e-5)
        evidence["native_coordinate_max_error_m"] = float(
            np.max(np.abs(vertices - expected))
        )
        from live_omniverse_extension_ux import _capture_app_screenshot

        for _ in range(10):
            omni.kit.app.get_app().update()
        evidence["screenshot"] = _capture_app_screenshot(args.out / "panel.png")
        evidence["summary"] = session.summary()
        evidence["native_builds"] = session.provider.builds
        evidence["native_pose_updates"] = session.provider.updates
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = repr(exc)
        raise
    finally:
        if panel:
            panel.close()
        (args.out / "result.json").write_text(
            json.dumps(evidence, indent=2, default=str) + "\n"
        )
        if app:
            app.close()


if __name__ == "__main__":
    main()
