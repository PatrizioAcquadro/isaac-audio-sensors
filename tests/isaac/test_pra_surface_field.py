"""Essential shared-field controls before admitting the diffuse producer."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene._diffuse import (
    PRADiffuseConfig,
    SurfaceField,
    signs,
)
from isaac_audio_sensors.isaac.acoustic_scene._specular import SpecularScene
from isaac_audio_sensors.isaac.acoustic_scene.geometry import triangulate
from isaac_audio_sensors.isaac.acoustic_scene.materials import AcousticMaterial, Curve
from isaac_audio_sensors.isaac.acoustic_scene.session import AcousticObject
from tests.helpers import source
from tests.isaac.pra_transport_helpers import partition

pytest.importorskip("pyroomacoustics")


@pytest.fixture
def field_factory():
    from pathlib import Path

    library = Path("build/native/libias_specular.so")
    if not library.exists():
        pytest.skip("Optional native PRA library unavailable")
    engines = []

    def create(faces, scattering=1.0, horizon=0.15):
        objects = {}

        def curve(value):
            return Curve((value,), (1000.0,), "test", "analytic")

        material = AcousticMaterial(curve(0.2), curve(scattering), curve(200.0))
        for i, points in enumerate(faces):
            points = np.asarray(points, float)
            triangles, face_ids = triangulate(points, [len(points)], range(len(points)))
            objects[str(i)] = AcousticObject(
                str(i),
                str(i),
                points,
                triangles,
                face_ids,
                np.eye(4),
                (material,),
                np.zeros(len(triangles), int),
                False,
            )
        engine = SpecularScene(
            SimpleNamespace(objects=objects), library, 16000, 3, 343.0, 10_000_000
        )
        engines.append(engine)
        return SurfaceField(
            engine, PRADiffuseConfig(rays=4096, surface_spacing_m=0.5), horizon
        )

    yield create
    for engine in engines:
        engine.close()


def api(points):
    points = np.asarray(points)
    return points[..., [0, 2, 1]] * [1, -1, 1]


def modal(field, src, mics):
    components = list(field.components(src, api(mics)))
    return (
        np.concatenate([v[0] for v in components]),
        np.concatenate([v[1] for v in components], axis=1),
        np.concatenate([v[2] for v in components], axis=1),
    )


def plane():
    return np.array([[0, -6, -4.8], [0, 6, -4.8], [0, 6, 7.2], [0, -6, 7.2]])


def test_plane_energy_covariance_and_source_motion(field_factory):
    field = field_factory([plane()])
    p = np.array([2.0, -0.7, 1.2])
    mics = np.array([[4, 0.1, 1.2], [4, 0.166, 1.2]])
    src = source("a", tuple(api(p)))
    ids, lengths, amplitude = modal(field, src, mics)
    shifted = p + [0.05, 0, 0]
    ids2, lengths2, amplitude2 = modal(
        field, replace(src, position_world=tuple(api(shifted))), mics
    )
    # Dense independent Lambertian surface quadrature.
    axis = (np.arange(240) + 0.5) * 0.05 - 6
    y, z = np.meshgrid(axis, axis + 1.2)
    q = np.c_[np.zeros(y.size), y.ravel(), z.ravel()]

    def reference(p):
        first = np.linalg.norm(q - p, axis=1)
        last = np.linalg.norm(mics[:, None] - q[None], axis=-1)
        power = 0.8 * 0.05**2 / (16 * np.pi**3) * abs(p[0]) / first**3
        power = power[None] * abs(mics[:, None, 0]) / last**3
        return first[None] + last, np.sqrt(power)

    d, a = reference(p)
    d2, a2 = reference(shifted)
    np.testing.assert_allclose(
        np.sum(amplitude**2, axis=1),
        np.broadcast_to(np.sum(a**2, axis=1)[:, None], (2, 7)),
        rtol=0.02,
    )
    ka = {tuple(v): i for i, v in enumerate(ids)}
    pairs = [(ka[tuple(v)], j) for j, v in enumerate(ids2) if tuple(v) in ka]
    ix, iy = np.asarray(pairs).T

    def coherence(a, b, delta, hz):
        return np.sum(a * b * np.exp(-2j * np.pi * hz / 343 * delta)) / np.sqrt(
            np.sum(a * a) * np.sum(b * b)
        )

    for hz in (500, 1000, 4000):
        actual = coherence(
            amplitude[0, :, 0], amplitude[1, :, 0], lengths[1] - lengths[0], hz
        )
        expected = coherence(a[0], a[1], d[1] - d[0], hz)
        assert abs(actual - expected) < 0.1
        actual = np.sum(
            amplitude[0, ix, 0]
            * amplitude2[0, iy, 0]
            * np.exp(-2j * np.pi * hz / 343 * (lengths2[0, iy] - lengths[0, ix]))
        ) / np.sqrt(np.sum(amplitude[0, :, 0] ** 2) * np.sum(amplitude2[0, :, 0] ** 2))
        expected = coherence(a[0], a2[0], d2[0] - d[0], hz)
        assert abs(actual - expected) < 0.1


def test_closed_open_closed_projection_and_shared_receivers(field_factory):
    src = source("a", tuple(api([2, 3, 1.2])))
    for opened in (False, True, False):
        field = field_factory(partition(opened), horizon=0.03)
        mics = np.array([[4, 3, 1.2], [4, 3, 1.2], [4, 3.066, 1.2]])
        first = modal(field, src, mics)
        again = modal(field, replace(src, source_id="equivalent"), mics[::-1])
        np.testing.assert_array_equal(first[0], again[0])
        for a, b in zip(first[1:], again[1:], strict=True):
            np.testing.assert_array_equal(a, b[::-1])
            np.testing.assert_array_equal(a[0], a[1])
        assert bool(np.any(first[2])) == opened
        alone = modal(field, src, mics[:1])
        np.testing.assert_array_equal(first[2][:1], alone[2])


def test_pressure_filters_share_realization_and_preserve_energy(field_factory):
    from isaac_audio_sensors.core.microphone_array import create_microphone_array

    field = field_factory([plane()])
    src = source("a", tuple(api([2, -0.7, 1.2])))
    array = create_microphone_array(
        array_id="test",
        prim_path="/Array",
        layout_name="quad_cross",
        sample_rate_hz=16000,
    )
    positions = api([[4, 0.1, 1.2]] * len(array.microphones))
    energies = []
    for seed in range(32):
        field.config = replace(field.config, seed=seed)
        response = np.asarray(field.impulses(src, array, positions))
        np.testing.assert_array_equal(response[0], response[1])
        assert np.isfinite(response).all()
        energies.append(float(np.sum(response[0] ** 2)))
    expected = field.diagnostics["expected_rir_energy"][0]
    # Independent material realizations fluctuate; compare their ensemble mean.
    mean = np.mean(energies)
    uncertainty = 1.96 * np.std(energies, ddof=1) / np.sqrt(len(energies))
    assert abs(mean - expected) < max(uncertainty, 0.03 * expected)
    assert abs(mean - expected) < 0.15 * expected


def test_surface_elements_follow_pose_and_return_to_same_field(field_factory):
    field = field_factory([plane()])
    src = source("a", tuple(api([2, -0.7, 1.2])))
    mics = [[4, 0.1, 1.2], [4, 0.166, 1.2]]
    first = modal(field, src, mics)
    local = field.ordered[0]["local"].copy()
    obj = field.scene.session.objects["0"]
    theta = np.deg2rad(5)
    obj.transform[:3, :3] = [
        [np.cos(theta), -np.sin(theta), 0],
        [np.sin(theta), np.cos(theta), 0],
        [0, 0, 1],
    ]
    obj.transform[3, :3] = [0.1, 0, 0]
    changed = modal(field, src, mics)
    np.testing.assert_array_equal(local, field.ordered[0]["local"])
    assert not np.array_equal(first[2], changed[2])
    obj.transform[:] = np.eye(4)
    returned = modal(field, src, mics)
    for a, b in zip(first, returned, strict=True):
        np.testing.assert_array_equal(a, b)


def test_filter_power_partition_and_native_impulse_timing(field_factory):
    from isaac_audio_sensors.core.microphone_array import create_microphone_array

    field = field_factory([plane()])
    src = source("a", tuple(api([2, -0.7, 1.2])))
    array = create_microphone_array(
        array_id="test",
        prim_path="/Array",
        layout_name="quad_cross",
        sample_rate_hz=16000,
    )
    field.impulses(src, array, api([[4, 0.1, 1.2]] * 4))
    spectral = np.abs(np.fft.rfft(field.filters, axis=-1)) ** 2
    np.testing.assert_allclose(spectral.sum(axis=0), 1, atol=1e-3)
    assert abs(field.filter_power.sum() - 1) < 1e-6

    # One isolated mode checks fractional delay independently of room interference.
    def single(*_):
        yield (
            np.zeros((1, 7), np.int64),
            np.full((4, 1), 343 * 0.01),
            np.ones((4, 1, 7)),
            np.broadcast_to([1.0, 0, 0], (4, 1, 3)),
        )

    field.components = single
    response = np.asarray(field.impulses(src, array, api([[4, 0.1, 1.2]] * 4)))
    # Correlation against known filters detects removing physical delay twice.
    keys = np.zeros((1, 7), np.int64)
    polarity = np.array([signs(keys, 0, b)[0] for b in range(7)])
    expected = np.sum(field.filters * polarity[:, None], axis=0)
    peak = np.argmax(np.correlate(response[0], expected, "full")) - (len(expected) - 1)
    assert abs(peak - 160) <= 1


def test_existing_and_new_array_fields_agree_after_object_motion(field_factory):
    # Mirrors must not acquire different modal phases when another array joins.
    faces = partition(True)
    existing = field_factory(faces, horizon=0.03)
    src = source("a", tuple(api([2, 3, 1.2])))
    src = replace(src, orientation_world_quat=np.array([0.0, 0, 0, 1]))
    mics = [[4, 3, 1.2]]
    modal(existing, src, mics)
    obj = existing.scene.session.objects["0"]
    obj.transform[3, 2] = -0.05
    before = modal(existing, src, mics)
    fresh = SurfaceField(existing.scene, existing.config, existing.horizon)
    after = modal(
        fresh, replace(src, orientation_world_quat=np.array([0.0, 0, 0, 1])), mics
    )
    for a, b in zip(before, after, strict=True):
        np.testing.assert_array_equal(a, b)
