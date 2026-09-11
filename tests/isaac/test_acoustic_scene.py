# ruff: noqa: E402
"""Real composed-USD preparation and native scene checks."""

import numpy as np
import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom, UsdShade

from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene.geometry import triangulate
from isaac_audio_sensors.isaac.acoustic_scene.session import INCLUDE, PARTITION
from isaac_audio_sensors.isaac.acoustic_scene.steam import converted_material
from tests.isaac.geometry_helpers import LIBRARY, stage


def plane(s, path, x=0):
    m = UsdGeom.Mesh.Define(s, path)
    m.CreateSubdivisionSchemeAttr("none")
    m.CreatePointsAttr([(x, -1, -1), (x, 1, -1), (x, 1, 1), (x, -1, 1)])
    m.CreateFaceVertexCountsAttr([4])
    m.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    return m


def test_concave_polygon_and_hole_faces():
    points = np.array(
        [[0, 0, 0], [3, 0, 0], [3, 1, 0], [1, 1, 0], [1, 3, 0], [0, 3, 0]], float
    )
    tri, faces = triangulate(points, [6], range(6))
    area = sum(
        np.linalg.norm(np.cross(points[b] - points[a], points[c] - points[a])) / 2
        for a, b, c in tri
    )
    assert area == pytest.approx(5)
    assert len(faces) == 4
    tri, _ = triangulate(points, [6], range(6), [0])
    assert len(tri) == 0


def test_automatic_geometry_material_and_selective_refresh():
    s = stage()
    plane(s, "/World/Wall")
    door = UsdGeom.Cube.Define(s, "/World/Door")
    translate = door.AddTranslateOp()
    translate.Set((3, 0, 1))
    UsdGeom.Cube.Define(s, "/World/Robot/visuals/Body")
    UsdGeom.Cube.Define(s, "/World/Robot/collisions/Body")
    UsdGeom.Xform.Define(s, "/World/Robot/AudioArray")
    UsdGeom.Cube.Define(s, "/World/Robot/AudioArray/Housing")
    session = AcousticSceneSession(s)
    assert session.refresh()["objects"] == 4
    assert len(session.excluded) == 1
    geometry = session.objects["/World/Wall"].points
    builds = session.geometry_builds
    translate.Set((4, 0, 1))
    session.refresh()
    assert session.geometry_builds == builds
    assert session.objects["/World/Wall"].points is geometry
    session.edit(["/World/Wall"], {"ias:transmission_loss_db": 12.0})
    assert session.geometry_builds == builds
    assert converted_material(session.objects["/World/Wall"].materials[0], True)[
        2
    ] == pytest.approx((10 ** (-12 / 20),) * 3)
    session.edit(["/World/Door"], {"ias:transmission_loss_db": 12.0})
    assert not session.objects["/World/Door"].planar
    assert converted_material(session.objects["/World/Door"].materials[0], False)[
        2
    ] == (0, 0, 0)
    s.RemovePrim("/World/Door")
    session.refresh()
    assert "/World/Door" not in session.objects
    session.close()
    session.close()


def test_bound_material_per_face_updates_and_explicit_precedence():
    s = stage()
    m = plane(s, "/World/Surface")
    mat = UsdShade.Material.Define(s, "/Materials/Fabric")
    attr = mat.GetPrim().CreateAttribute("ias:absorption", Sdf.ValueTypeNames.Double)
    attr.Set(0.8)
    UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(mat)
    session = AcousticSceneSession(s)
    session.refresh()
    assert session.objects[str(m.GetPath())].materials[0].absorption.values == (0.8,)
    builds = session.geometry_builds
    attr.Set(0.6)
    session.refresh()
    assert session.geometry_builds == builds
    assert session.objects[str(m.GetPath())].materials[0].absorption.values == (0.6,)
    session.edit([str(m.GetPath())], {"ias:absorption": 0.2})
    assert session.objects[str(m.GetPath())].materials[0].absorption.values == (0.2,)
    session.edit([str(m.GetPath())], {"ias:absorption": -1.0})
    assert session.issues
    session.close()


def test_instances_units_and_grouped_partitions():
    s = stage()
    UsdGeom.SetStageMetersPerUnit(s, 0.01)
    plane(s, "/Source/Wall")
    root = s.DefinePrim("/World/Instance", "Xform")
    root.GetReferences().AddInternalReference("/Source")
    root.SetInstanceable(True)
    session = AcousticSceneSession(s, roots=("/World",))
    session.refresh()
    assert session.objects["/World/Instance/Wall"].world_points.max() == pytest.approx(
        0.01
    )
    session.edit(
        ["/World/Instance"], {PARTITION: "wall", "ias:transmission_loss_db": 12.0}
    )
    assert session.objects["/World/Instance/Wall"].partition == "wall"
    session.edit(["/World/Instance"], {INCLUDE: False})
    assert session.excluded
    session.edit(["/World/Instance"], {INCLUDE: None})
    assert session.objects
    session.close()


def test_native_scene_reuses_meshes_for_pose_updates(tmp_path):
    if not LIBRARY.exists():
        pytest.skip("Qualified native Steam artifact not installed")
    s = stage()
    plane(s, "/World/Wall")
    door = UsdGeom.Cube.Define(s, "/World/Door")
    op = door.AddTranslateOp()
    op.Set((3, 0, 0))
    session = AcousticSceneSession(s)
    session.refresh()
    assert session.verify_provider(LIBRARY)["state"] == "scene verified in provider"
    builds = session.provider.builds
    op.Set((4, 0, 0))
    session.refresh()
    assert session.provider.builds == builds
    assert session.provider.updates == 1
    session.provider.export_geometry(tmp_path / "scene")
    vertices = np.array(
        [
            [float(v) for v in line.split()[1:]]
            for line in (tmp_path / "scene").read_text().splitlines()
            if line.startswith("v ")
        ]
    )
    expected = np.concatenate([o.world_points for o in session.objects.values()])
    np.testing.assert_allclose(vertices, expected, atol=1e-6)
    s.RemovePrim("/World/Door")
    session.refresh()
    assert len(session.provider.entries) == 1
    session.close()


def test_material_subsets_and_native_refresh(tmp_path):
    s = stage()
    m = UsdGeom.Mesh.Define(s, "/World/Surface")
    m.CreateSubdivisionSchemeAttr("none")
    m.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    m.CreateFaceVertexCountsAttr([3, 3])
    m.CreateFaceVertexIndicesAttr([0, 1, 2, 0, 2, 3])
    mat = UsdShade.Material.Define(s, "/Materials/Absorber")
    mat.GetPrim().CreateAttribute("ias:absorption", Sdf.ValueTypeNames.Double).Set(0.9)
    binding = UsdShade.MaterialBindingAPI.Apply(m.GetPrim())
    subset = binding.CreateMaterialBindSubset("absorber", [1])
    UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(mat)
    session = AcousticSceneSession(s)
    session.refresh()
    obj = session.objects["/World/Surface"]
    assert obj.material_indices.tolist() == [0, 1]
    assert obj.materials[1].absorption.values == (0.9,)
    if LIBRARY.exists():
        session.verify_provider(LIBRARY)
        session.edit(["/Materials/Absorber"], {"ias:absorption": 0.7})
        session.provider.export_geometry(tmp_path / "surface.obj")
        assert (tmp_path / "surface.obj").is_file()
        assert session.provider.entries["/World/Surface"][6][1].absorption.values == (
            0.7,
        )
    session.close()


def test_partition_fragments_share_native_assembly_and_survive_reopen(tmp_path):
    s = stage()
    for name, y in [("Left", -1), ("Right", 1)]:
        p = plane(s, f"/World/{name}")
        p.AddTranslateOp().Set((0, y, 0))
    session = AcousticSceneSession(s)
    session.refresh()
    session.edit(
        ["/World/Left", "/World/Right"],
        {PARTITION: "wall", "ias:transmission_loss_db": 12.0},
    )
    assert all(o.planar for o in session.objects.values())
    if LIBRARY.exists():
        session.verify_provider(LIBRARY)
        assert len(session.provider.entries) == 1
        assert session.provider.entries["wall"][4]
    s.GetRootLayer().Export(str(tmp_path / "scene.usda"))
    session.close()
    reopened = AcousticSceneSession(Usd.Stage.Open(str(tmp_path / "scene.usda")))
    reopened.refresh()
    assert {o.partition for o in reopened.objects.values()} == {"wall"}
    reopened.close()


def test_bad_explicit_geometry_does_not_fall_back_to_visual():
    s = stage()
    cube = UsdGeom.Cube.Define(s, "/World/Box")
    cube.GetPrim().CreateRelationship("ias:acoustic_geometry").SetTargets(
        ["/World/Missing"]
    )
    session = AcousticSceneSession(s)
    summary = session.refresh()
    assert summary["state"] == "preparation with issues"
    assert not session.objects
    session.close()


def test_declared_associations_and_fallbacks_are_persistent():
    s = stage()
    UsdGeom.Cube.Define(s, "/World/Unclassified")
    session = AcousticSceneSession(s)
    session.refresh()
    assert (
        session.objects["/World/Unclassified"]
        .materials[0]
        .absorption.origin.startswith("fallback:")
    )
    session.configure(
        associations={"unclassified": "pra.ceramic_tiles"}, fallback_scattering=0.1
    )
    material = session.objects["/World/Unclassified"].materials[0]
    assert material.absorption.origin == "association:pra.ceramic_tiles"
    assert material.absorption.evidence == "nominal"
    session.close()


def test_containment_keeps_connected_scene_and_external_sources():
    from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec
    from isaac_audio_sensors.isaac.stage_audio import attach_acoustic_environment_attrs

    s = stage()
    for name, x in [("A", 0), ("B", 6)]:
        room = UsdGeom.Cube.Define(s, f"/World/Room{name}")
        room.CreateSizeAttr(4.0)
        room.AddTranslateOp().Set((x, 0, 0))
        room.GetPrim().CreateAttribute(INCLUDE, Sdf.ValueTypeNames.Bool).Set(False)
        attach_acoustic_environment_attrs(
            room.GetPrim(), environment_id=name, kind="shoebox"
        )
        room.GetPrim().CreateAttribute(
            "ias:environment_min_world", Sdf.ValueTypeNames.Double3
        ).Set((x - 2, -2, -2))
        room.GetPrim().CreateAttribute(
            "ias:environment_max_world", Sdf.ValueTypeNames.Double3
        ).Set((x + 2, 2, 2))
        plane(s, f"/World/Room{name}/Wall", 0)
        s.GetPrimAtPath(f"/World/Room{name}/Wall").CreateAttribute(
            INCLUDE, Sdf.ValueTypeNames.Bool
        ).Set(True)
    source = s.DefinePrim("/World/RoomB/Source", "Xform")
    source.CreateAttribute("ias:source_id", Sdf.ValueTypeNames.String).Set("external")
    array = MicrophoneArraySpec(
        array_id="array",
        prim_path="/World/Array",
        position_world=(0, 0, 0),
        orientation_world_quat=(0, 0, 0, 1),
        microphones=(
            MicrophoneSpec(mic_id="a", relative_position_m=(0, 0, 0)),
            MicrophoneSpec(mic_id="b", relative_position_m=(0.1, 0, 0)),
        ),
    )
    session = AcousticSceneSession(s)
    session.refresh()
    from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
    from isaac_audio_sensors.isaac.stage_audio import attach_microphone_array_attrs

    array_prim = UsdGeom.Xform.Define(s, "/World/Array")
    attach_microphone_array_attrs(
        array_prim.GetPrim(),
        array_id="array",
        sample_rate_hz=48000,
        coordinate_convention=COORDINATE_CONVENTION,
        layout_name="custom",
        position_world=(0, 0, 0),
        orientation_world_quat=(0, 0, 0, 1),
        microphone_relative_offsets_m=((0, 0, 0), (0.1, 0, 0)),
        microphone_ids=("a", "b"),
    )
    session.refresh()
    assert session.containment["array"]["state"] == "contained"
    result = session.resolve_containment([array])
    assert result["array"]["state"] == "contained"
    assert result["array"]["environment_id"] == "A"
    assert "/World/RoomB/Wall" in session.objects
    assert s.GetPrimAtPath("/World/RoomB/Source")
    session.close()


@pytest.mark.parametrize(
    "schema",
    [UsdGeom.Cube, UsdGeom.Sphere, UsdGeom.Cylinder, UsdGeom.Cone, UsdGeom.Capsule],
)
def test_standard_primitives_have_finite_nondegenerate_geometry(schema):
    s = stage()
    schema.Define(s, "/World/Object")
    session = AcousticSceneSession(s)
    session.refresh()
    assert not session.issues
    obj = session.objects["/World/Object"]
    vertices = obj.points[obj.triangles]
    area = np.linalg.norm(
        np.cross(vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0]),
        axis=1,
    )
    assert np.all(area > 1e-9)
    assert np.isfinite(obj.points).all()
    session.close()


def test_explicit_proxy_outside_roots_is_included_even_when_invisible():
    s = stage()
    owner = UsdGeom.Cube.Define(s, "/World/Wall")
    proxy = plane(s, "/Acoustics/Wall")
    proxy.CreateVisibilityAttr("invisible")
    owner.GetPrim().CreateRelationship("ias:acoustic_geometry").SetTargets(
        ["/Acoustics/Wall"]
    )
    session = AcousticSceneSession(s, roots=("/World",))
    session.refresh()
    assert set(session.objects) == {"/Acoustics/Wall"}
    assert not session.issues
    session.close()


@pytest.mark.parametrize("kind", ["point_instancer", "skinned_mesh"])
def test_unsupported_dynamic_representation_prevents_ready_state(kind):
    from pxr import UsdSkel

    s = stage()
    UsdGeom.Cube.Define(s, "/World/Usable")
    if kind == "point_instancer":
        UsdGeom.PointInstancer.Define(s, "/World/Unsupported")
    else:
        mesh = plane(s, "/World/Unsupported")
        UsdSkel.BindingAPI.Apply(mesh.GetPrim())
    session = AcousticSceneSession(s)
    assert session.refresh()["state"] == "preparation with issues"
    assert any("/World/Unsupported" in issue for issue in session.issues)
    session.close()


def test_scattering_family_assignment_and_conservative_inference():
    s = stage()
    plane(s, "/World/wood")
    session = AcousticSceneSession(s)
    session.refresh()
    material = session.objects["/World/wood"].materials[0]
    assert material.absorption.origin == "fallback:pra.hard_surface"
    assert material.transmission_db is None
    session.edit(["/World/wood"], {"ias:scattering_material_id": "pra.rpg_qrd"})
    material = session.objects["/World/wood"].materials[0]
    assert material.scattering.values == (0.06, 0.15, 0.45, 0.95, 0.88, 0.91)
    assert material.scattering.evidence == "measured"
    assert material.absorption.origin == "fallback:pra.hard_surface"
    session.edit(["/World/wood"], {"ias:scattering": 0.2})
    assert session.objects["/World/wood"].materials[0].scattering.values == (0.2,)
    session.close()


def test_shared_selection_editor_mixed_values_and_selective_edit():
    from isaac_audio_sensors.kit.acoustic_scene_editor import (
        coefficient_changes,
        selected_objects,
        selection_curves,
    )

    s = stage()
    plane(s, "/World/Robot/Body")
    plane(s, "/World/Robot/Housing", x=2)
    session = AcousticSceneSession(s)
    session.refresh()
    session.edit(["/World/Robot/Body"], {"ias:absorption": 0.2})
    selected = selected_objects(session, ["/World/Robot"])
    assert len(selected) == 2
    assert selection_curves(selected)["ias:absorption"] == "mixed"
    before = session.objects["/World/Robot/Body"].materials[0].absorption
    values = coefficient_changes(
        {"ias:scattering": "0.4"}, {"ias:scattering": ""}, {"ias:scattering"}
    )
    session.edit(["/World/Robot"], values)
    assert session.objects["/World/Robot/Body"].materials[0].absorption == before
    assert all(
        o.materials[0].scattering.values == (0.4,) for o in session.objects.values()
    )
    for text, frequencies in [("nan", ""), ("1.1", ""), ("0.1 0.2", "1000"), ("", "")]:
        with pytest.raises(ValueError):
            coefficient_changes(
                {"ias:scattering": text},
                {"ias:scattering": frequencies},
                {"ias:scattering"},
            )
    session.close()


def test_author_acoustic_representation_through_shared_service(tmp_path):
    from isaac_audio_sensors.isaac.acoustic_scene.session import REPRESENTATION

    s = stage()
    UsdGeom.Cube.Define(s, "/World/Owner")
    plane(s, "/Proxies/Wall")
    session = AcousticSceneSession(s, roots=("/World",))
    session.refresh()
    session.edit(["/World/Owner"], {REPRESENTATION: ("/Proxies/Wall",)})
    assert set(session.objects) == {"/Proxies/Wall"}
    path = tmp_path / "proxy.usda"
    s.GetRootLayer().Export(str(path))
    reopened = AcousticSceneSession(Usd.Stage.Open(str(path)), roots=("/World",))
    reopened.refresh()
    assert set(reopened.objects) == {"/Proxies/Wall"}
    with pytest.raises(ValueError, match="owner"):
        session.edit(["/World/Owner"], {REPRESENTATION: ("/World/Owner",)})
    session.edit(["/World/Owner"], {REPRESENTATION: None})
    assert set(session.objects) == {"/World/Owner"}
    reopened.close()
    session.close()
