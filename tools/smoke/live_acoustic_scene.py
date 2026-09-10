"""Exercise USD preparation, shared Kit edits and Steam scenes on live Isaac."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _representative_preparation(library):
    """Bounded authoring-cost fixture, not an audio/training throughput claim."""
    from time import perf_counter

    import numpy as np
    from pxr import Usd, UsdGeom, UsdPhysics

    from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    # Two open-front rooms, repeated referenced furniture, robot links and housing.
    for room, center in (("RoomA", -3), ("RoomB", 3)):
        for name, position, scale in (
            ("Floor", (center, 0, 0), (6, 6, 0.1)),
            ("Ceiling", (center, 0, 3), (6, 6, 0.1)),
            ("Back", (center, 3, 1.5), (6, 0.1, 3)),
        ):
            cube = UsdGeom.Cube.Define(stage, f"/World/{room}/{name}")
            cube.CreateSizeAttr(1)
            cube.AddTranslateOp().Set(position)
            cube.AddScaleOp().Set(scale)
    UsdGeom.Cube.Define(stage, "/Assets/Chair/Seat")
    UsdGeom.Cube.Define(stage, "/Assets/Chair/Back")
    for i in range(128):
        root = stage.DefinePrim(f"/World/Furniture/Chair{i}", "Xform")
        root.GetReferences().AddInternalReference("/Assets/Chair")
        root.SetInstanceable(True)
        UsdGeom.Xformable(root).AddTranslateOp().Set((i % 16, i // 16, 0))
    robot = stage.DefinePrim("/World/Robot", "Xform")
    UsdPhysics.ArticulationRootAPI.Apply(robot)
    UsdGeom.Cube.Define(stage, "/World/Robot/Link/visuals/Body")
    UsdGeom.Cube.Define(stage, "/World/Robot/Link/collisions/Body")
    UsdGeom.Cube.Define(stage, "/World/Robot/AudioArray/Housing")
    UsdGeom.Cube.Define(stage, "/World/Source/Housing")
    UsdGeom.Cube.Define(stage, "/World/IasAudioDebug/Marker")
    door = UsdGeom.Cube.Define(stage, "/World/Door")
    pose = door.AddTranslateOp()
    pose.Set((0, 0, 1.5))
    UsdPhysics.RigidBodyAPI.Apply(door.GetPrim())
    session = AcousticSceneSession(stage, roots=("/World",))
    try:
        start = perf_counter()
        session.refresh()
        import_ms = 1000 * (perf_counter() - start)
        assert not session.issues, session.issues
        assert len(session.objects) == 266
        assert "/World/Robot/AudioArray/Housing" in session.objects
        assert "/World/Robot/Link/collisions/Body" in session.excluded
        assert "/World/IasAudioDebug/Marker" in session.excluded
        session.verify_provider(library)
        native = session.provider
        builds = native.builds
        geometry = session.objects["/World/RoomA/Floor"].points
        idle = []
        for _ in range(30):
            start = perf_counter()
            session.refresh()
            idle.append(1000 * (perf_counter() - start))
        assert native.builds == builds
        start = perf_counter()
        pose.Set((0, 0.5, 1.5))
        session.refresh()
        movement_ms = 1000 * (perf_counter() - start)
        assert native.builds == builds
        assert session.objects["/World/RoomA/Floor"].points is geometry
        start = perf_counter()
        session.edit(["/World/RoomB/Back"], {"ias:absorption": 0.4})
        edit_ms = 1000 * (perf_counter() - start)
        assert native.builds == builds + 1
        assert session.objects["/World/RoomA/Floor"].points is geometry
        stage.RemovePrim("/World/Source")
        session.refresh()
        assert "/World/Source/Housing" not in session.objects
        result = dict(
            objects=266,
            triangles=266 * 12,
            import_ms=import_ms,
            idle_p95_ms=float(np.percentile(idle, 95)),
            movement_ms=movement_ms,
            material_edit_ms=edit_ms,
            unrelated_geometry_reused=True,
            note="Controlled USD/native preparation only; no audio or training",
        )
        session.reset()
        assert session.provider.verified
        return result
    finally:
        session.close()


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
        from pxr import UsdGeom, UsdLux, UsdPhysics

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
        UsdLux.DomeLight.Define(stage, "/Lighting/Dome").CreateIntensityAttr(500)
        UsdLux.DistantLight.Define(stage, "/Lighting/Sun").CreateIntensityAttr(1000)
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
        window = ui.Window("Acoustic Scene - 08.1 verification", width=850, height=1000)
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
        selection = omni.usd.get_context().get_selection()
        panel._render()
        assert panel.coefficient_fields["ias:absorption"].get_value_as_string() == "0.3"
        panel.coefficient_fields["ias:scattering"].set_value("0.4")
        panel.apply_coefficients()
        assert panel.last_error is None, panel.last_error
        material = session.objects["/World/Wall"].materials[0]
        assert material.absorption.values == (0.3,)
        assert material.scattering.values == (0.4,)
        assert not stage.GetPrimAtPath("/World/Wall").GetAttribute(
            "ias:transmission_loss_db"
        )
        # Invalid edits are atomic and keep the pending input for correction.
        layer_before = stage.GetRootLayer().ExportToString()
        panel.coefficient_fields["ias:absorption"].set_value("-0.1")
        panel.apply_coefficients()
        assert panel.last_error
        assert stage.GetRootLayer().ExportToString() == layer_before
        panel.coefficient_fields["ias:absorption"].set_value("0.3")
        panel.apply_coefficients()
        selection.set_selected_prim_paths(["/World/Wall", "/World/Door"], False)
        panel._render()
        assert (
            panel.coefficient_fields["ias:absorption"].get_value_as_string() == "Mixed"
        )
        panel.coefficient_fields["ias:scattering"].set_value("0.2")
        panel.apply_coefficients()
        assert panel.last_error is None, panel.last_error
        assert session.objects["/World/Wall"].materials[0].absorption.values == (0.3,)
        assert session.objects["/World/Door"].materials[0].absorption.values != (0.3,)
        panel.undo()
        assert session.objects["/World/Wall"].materials[0].scattering.values == (0.4,)
        panel.redo()
        selection.set_selected_prim_paths(["/World/Wall"], False)
        panel.use_selection_roots()
        assert panel.session.roots == ("/World/Wall",)
        assert len(panel.session.objects) == 1
        panel.use_entire_stage()
        session = panel.session
        assert len(session.objects) == 2
        # Undo/Redo survives session replacement when import roots change.
        panel.undo()
        assert panel.last_error is None, panel.last_error
        assert session.objects["/World/Wall"].materials[0].scattering.values == (0.4,)
        panel.redo()
        assert panel.last_error is None, panel.last_error
        assert session.objects["/World/Wall"].materials[0].scattering.values == (0.2,)
        panel.scattering_preset.get_item_value_model().set_value(
            panel.scatter_presets.index("pra.rpg_qrd")
        )
        panel.assign_scattering()
        assert panel.last_error is None, panel.last_error
        assert session.objects["/World/Wall"].materials[0].scattering.at((1000,)) == (
            0.95,
        )
        panel.undo()
        # Relations use the same undo command as coefficient edits.
        selection.set_selected_prim_paths(["/World/Wall"], False)
        panel.remember_proxy()
        selection.set_selected_prim_paths(["/World/Door"], False)
        panel.assign_proxy()
        assert panel.last_error is None, panel.last_error
        assert (
            stage.GetPrimAtPath("/World/Door")
            .GetRelationship("ias:acoustic_geometry")
            .GetTargets()
        )
        panel.undo()
        assert len(session.objects) == 2
        selection.set_selected_prim_paths(["/World/Wall"], False)
        panel._render()
        evidence["editor_checks"] = (
            "selection, mixed values, selective apply, invalid edit, roots, "
            "scattering, proxy relation, undo/redo"
        )
        robot = stage.DefinePrim("/World/Robot", "Xform")
        UsdPhysics.ArticulationRootAPI.Apply(robot)
        for name, x in (("Base", 4.0), ("Arm", 4.4)):
            link = UsdGeom.Cube.Define(stage, f"/World/Robot/{name}")
            link.CreateSizeAttr(0.2)
            link.AddTranslateOp().Set((x, 0, 3))
            UsdPhysics.RigidBodyAPI.Apply(link.GetPrim())
            UsdPhysics.CollisionAPI.Apply(link.GetPrim())
        joint = UsdPhysics.RevoluteJoint.Define(stage, "/World/Robot/Joint")
        joint.CreateBody0Rel().SetTargets(["/World/Robot/Base"])
        joint.CreateBody1Rel().SetTargets(["/World/Robot/Arm"])
        joint.CreateLocalPos0Attr((0.2, 0, 0))
        joint.CreateLocalPos1Attr((-0.2, 0, 0))
        housing = UsdGeom.Cube.Define(stage, "/World/Robot/Base/AudioArray/Housing")
        housing.CreateSizeAttr(0.05)
        housing.AddTranslateOp().Set((0, 0, 0.2))
        panel.library.set_value(str(args.library.resolve()))
        panel.verify()
        assert session.provider and session.provider.verified, panel.status.text
        static = session.objects["/World/Wall"].points
        builds = session.provider.builds
        timeline = omni.timeline.get_timeline_interface()
        carb.settings.get_settings().set_bool("/physics/updateToUsd", False)
        timeline.play()
        for _ in range(210):
            omni.kit.app.get_app().update()
        session.refresh(timeline.get_current_time() * stage.GetTimeCodesPerSecond())
        assert not session.issues, session.issues
        assert session.objects["/World/Wall"].points is static
        assert session.provider.builds == builds
        assert session.provider.updates > 0
        assert session.objects["/World/Door"].transform[3, 1] < 3
        assert session.objects["/World/Robot/Base"].transform[3, 1] < 3
        assert session.objects["/World/Robot/Arm"].transform[3, 1] < 3
        assert session.objects["/World/Robot/Base/AudioArray/Housing"].dynamic
        evidence["articulated_robot_pose_updates"] = True
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
        panel.section_frames["Scene"].collapsed = True
        panel.section_frames["Objects"].collapsed = True
        panel.section_frames["Selection"].collapsed = True
        panel.section_frames["Coefficient overrides"].collapsed = False
        for _ in range(10):
            omni.kit.app.get_app().update()
        evidence["editor_screenshot"] = _capture_app_screenshot(args.out / "editor.png")
        evidence["summary"] = session.summary()
        evidence["native_builds"] = session.provider.builds
        evidence["native_pose_updates"] = session.provider.updates
        evidence["preparation_cost"] = _representative_preparation(args.library)
        old_session = panel.session
        omni.usd.get_context().new_stage()
        panel.import_scene()
        assert old_session.closed and old_session.provider.closed
        assert not panel.session.objects
        evidence["stage_change_released"] = True
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
