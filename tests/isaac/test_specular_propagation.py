"""Physical controls for the bounded two-sided native specular adapter."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("pxr")
pytest.importorskip("pyroomacoustics")
from pxr import Sdf, UsdGeom  # noqa: E402

from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene._specular import SpecularScene
from tests.isaac.geometry_helpers import (
    LIBRARY,
    SPECULAR_LIBRARY,
    backend,
    scene,
    stage,
    window,
)


def face(stage, name, points, absorption=0.2):
    mesh = UsdGeom.Mesh.Define(stage, "/World/" + name)
    mesh.GetSubdivisionSchemeAttr().Set("none")
    mesh.GetPointsAttr().Set(points)
    mesh.GetFaceVertexCountsAttr().Set([len(points)])
    mesh.GetFaceVertexIndicesAttr().Set(list(range(len(points))))
    mesh.GetPrim().CreateAttribute("ias:absorption", Sdf.ValueTypeNames.Double).Set(
        absorption
    )
    mesh.GetPrim().CreateAttribute("ias:scattering", Sdf.ValueTypeNames.Double).Set(0.0)
    return mesh


@pytest.fixture
def native_scene():
    if not SPECULAR_LIBRARY.exists():
        pytest.skip("Optional native specular bridge unavailable")
    sessions = []

    def create(value, order=3):
        session = AcousticSceneSession(value)
        session.refresh()
        engine = SpecularScene(
            session, str(SPECULAR_LIBRARY), 16000, order, 343.0, 1_000_000
        )
        sessions.append((session, engine))
        return session, engine

    yield create
    for session, engine in reversed(sessions):
        engine.close()
        session.close()


def snapshot(source_position=(2, 3, 1.2), array_position=(4, 3, 1.2)):
    value = scene()
    return replace(
        value,
        arrays=(replace(value.arrays[0], position_world=array_position),),
        sources=(replace(value.sources[0], position_world=source_position),),
    )


def responses(engine, value):
    return engine.impulses(
        value.sources[0],
        value.arrays[0],
        list(microphone_world_positions(value.arrays[0]).values()),
        1.0,
    )


def test_single_plane_two_sides_timing_and_mesh_subdivision(native_scene):
    value = stage()
    mesh = face(
        value, "Plane", [(0, -10, -10), (0, 10, -10), (0, 10, 10), (0, -10, 10)]
    )
    session, engine = native_scene(value)
    for side in (1, -1):
        snap = snapshot((side * 2, 0, 0), (side * 3, 0, 0))
        pcm = responses(engine, snap)
        positions = np.array(list(microphone_world_positions(snap.arrays[0]).values()))
        mirrored = np.array([-side * 2, 0, 0])
        distances = np.linalg.norm(positions - mirrored, axis=1)
        peaks = np.array([np.argmax(abs(row)) for row in pcm])
        assert np.max(abs(peaks - distances / 343 * 16000)) <= 0.51
        areas = np.array([sum(row) for row in pcm])
        np.testing.assert_allclose(
            areas, np.sqrt(0.8) / (4 * np.pi * distances), rtol=0.005
        )
        original = pcm
        # A geometric plane must not gain energy when authored as two triangles.
        mesh.GetFaceVertexCountsAttr().Set([3, 3])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 0, 2, 3])
        session.refresh()
        split = responses(engine, snap)
        for before, after in zip(original, split, strict=True):
            np.testing.assert_allclose(after, before, atol=5e-7, rtol=1e-3)
        mesh.GetFaceVertexCountsAttr().Set([4])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
        session.refresh()


@pytest.mark.parametrize("offset", (0.0, 0.0001, 0.001, 0.01, 0.1))
def test_door_blocks_reflections_and_transmits_direct_then_reopens(
    native_scene, offset
):
    import pyroomacoustics as pra

    value = stage()
    for i, wall in enumerate(pra.ShoeBox([6, 6, 3]).walls):
        face(value, f"Wall{i}", wall.corners.T.tolist())
    for name, low, high in [("A", 0, 2.5), ("B", 3.5, 6), ("Door", 2.5, 3.5)]:
        mesh = face(value, name, [(3, low, 0), (3, high, 0), (3, high, 3), (3, low, 3)])
    mesh.GetPrim().CreateAttribute(
        "ias:transmission_loss_db", Sdf.ValueTypeNames.Double
    ).Set(12.0)
    move = mesh.AddTranslateOp()
    move.Set((0, 0, 0))
    session, engine = native_scene(value)
    snap = snapshot(source_position=(2, 3 + offset, 1.2))
    producer = backend(session)
    try:
        outputs = []
        for i, y in enumerate((0, 6, 0)):
            move.Set((0, y, 0))
            session.refresh()
            reflected = responses(engine, snap)
            if y == 0:
                assert max(np.max(abs(row)) for row in reflected) < 1e-7
            else:
                assert min(np.max(abs(row)) for row in reflected) > 0.001
            block = producer.propagate(snap, "array", window(i * 0.1, (i + 1) * 0.1, i))
            outputs.append(block.samples[:, 1000:])
        assert np.linalg.norm(outputs[1]) > 2 * np.linalg.norm(outputs[0])
        np.testing.assert_allclose(
            np.linalg.norm(outputs[2], axis=1),
            np.linalg.norm(outputs[0], axis=1),
            rtol=0.02,
        )
        mesh.GetPrim().GetAttribute("ias:transmission_loss_db").Set(120.0)
        opaque = producer.propagate(snap, "array", window(0.3, 0.4, 3))
        assert np.max(abs(opaque.samples[:, 1000:])) < 1e-7
    finally:
        producer.close()


def test_frequency_dependent_transmission_is_finite_and_has_expected_band_trend(
    native_scene,
):
    from scipy.signal import freqz

    from isaac_audio_sensors.isaac.acoustic_scene import GeometryAcousticsConfig
    from isaac_audio_sensors.isaac.acoustic_scene._steam_audio import Receiver

    value = stage()
    mesh = face(
        value, "Partition", [(3, -10, -10), (3, 10, -10), (3, 10, 10), (3, -10, 10)]
    )
    mesh.GetPrim().CreateAttribute(
        "ias:transmission_loss_db_bands", Sdf.ValueTypeNames.DoubleArray
    ).Set([3.0, 6.0, 12.0, 18.0, 24.0, 30.0])
    session, _ = native_scene(value)
    session.verify_provider(str(LIBRARY))
    config = GeometryAcousticsConfig(
        library_path=str(LIBRARY),
        specular_library_path=str(SPECULAR_LIBRARY),
    )
    receiver = Receiver(session.provider, 16000, config, ["tone"])
    try:
        receiver.refresh((4, 0, 0), snapshot((2, 0, 0), (4, 0, 0)).sources)
        response = receiver.impulse("tone")
        assert np.isfinite(response).all()
        assert np.max(abs(response[-128:])) < 1e-7
        _, gain = freqz(response, worN=np.array([250.0, 1000.0, 4000.0]), fs=16000)
        assert abs(gain[0]) > 2 * abs(gain[-1])
    finally:
        receiver.close()


def test_source_directivity_uses_first_reflected_segment(native_scene):
    value = stage()
    face(value, "Plane", [(0, -10, -10), (0, 10, -10), (0, 10, 10), (0, -10, 10)])
    _, engine = native_scene(value)
    snap = snapshot((2, 0, 1), (3, 0, 1))
    directional = replace(
        snap,
        sources=(
            replace(
                snap.sources[0],
                directivity="cardioid",
                orientation_world_quat=(0, 0, 0, 1),
            ),
        ),
    )
    baseline = responses(engine, snap)
    away = responses(engine, directional)
    toward = responses(
        engine,
        replace(
            directional,
            sources=(
                replace(directional.sources[0], orientation_world_quat=(0, 0, 1, 0)),
            ),
        ),
    )
    for full, low, high in zip(baseline, away, toward, strict=True):
        assert np.linalg.norm(low) < 0.001 * np.linalg.norm(full)
        assert np.linalg.norm(high) > 0.999 * np.linalg.norm(full)


def test_reflected_nlos_without_direct_leak(native_scene):
    import pyroomacoustics as pra

    value = stage()
    template = pra.Room.from_corners(
        np.array([[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]).T
    )
    template.extrude(3.0)
    for i, wall in enumerate(template.walls):
        face(value, f"Wall{i}", wall.corners.T.tolist())
    session, engine = native_scene(value)
    snap = snapshot((3.5, 1.5, 1.2), (1.5, 3.5, 1.2))
    pcm = responses(engine, snap)
    assert min(np.max(abs(r)) for r in pcm) > 0.001
    direct = backend(session, reflection_order=0)
    try:
        assert np.max(abs(direct.propagate(snap, "array", window()).samples)) < 1e-7
    finally:
        direct.close()


def test_banded_material_phase_is_independent_of_scalar_gain(native_scene):
    value = stage()
    mesh = face(
        value, "Plane", [(0, -10, -10), (0, 10, -10), (0, 10, 10), (0, -10, 10)]
    )
    mesh.GetPrim().CreateAttribute(
        "ias:absorption_bands", Sdf.ValueTypeNames.DoubleArray
    ).Set([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    _, engine = native_scene(value)
    snap = snapshot((2, 0, 1), (3, 0, 1))
    array = snap.arrays[0]
    microphones = tuple(
        replace(m, relative_position_m=(0, 0, 0)) for m in array.microphones[:3]
    )
    microphones = (
        microphones[0],
        replace(
            microphones[1],
            directivity="figure_eight",
            relative_orientation_quat=(0, 0, 0, 1),
        ),
        replace(
            microphones[2],
            directivity="cardioid",
            relative_orientation_quat=(0, 0, 2**-0.5, 2**-0.5),
        ),
    )
    snap = replace(snap, arrays=(replace(array, microphones=microphones),))
    near = responses(engine, snap)
    np.testing.assert_allclose(near[1], -near[0], atol=1e-9, rtol=1e-5)
    np.testing.assert_allclose(near[2], near[0] / 2, atol=1e-9, rtol=1e-5)

    # An extra 3.43 m adds exactly 160 samples at 16 kHz, without changing
    # the material filter. Only spreading and the physical delay change.
    far = responses(
        engine,
        replace(snap, arrays=(replace(snap.arrays[0], position_world=(6.43, 0, 1)),)),
    )
    scaled = far[0][160 : 160 + len(near[0])] * (8.43 / 5)
    assert np.linalg.norm(scaled - near[0]) / np.linalg.norm(near[0]) < 2e-4
