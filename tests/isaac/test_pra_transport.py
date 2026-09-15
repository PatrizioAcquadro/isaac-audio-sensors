"""Native diffuse transport gates; these do not admit shared pressure synthesis."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from tests.isaac.pra_transport_helpers import Transport, box, partition

pytest.importorskip("pyroomacoustics")


@pytest.fixture
def transport():
    library = Path(os.environ.get("IAS_PRA_LIBRARY", "build/native/libias_specular.so"))
    if not library.exists():
        pytest.skip("Native PRA library unavailable")
    engines = []

    def create(faces=None, absorption=0.2, scattering=0.3, order=3):
        faces = box() if faces is None else faces
        a = np.broadcast_to(
            np.atleast_1d(absorption), (len(faces), np.size(absorption))
        )
        s = np.broadcast_to(np.atleast_1d(scattering), a.shape)
        try:
            engine = Transport(library, faces, a, s, order)
        except AttributeError:
            pytest.skip("Native PRA transport ABI unavailable; rebuild the bridge")
        engines.append(engine)
        return engine

    yield create
    for engine in reversed(engines):
        engine.close()


def test_closed_open_closed_and_incident_hemisphere(transport):
    source, mic = [2, 3, 1.2], [[4, 3, 1.2]]
    for opened in (False, True, False):
        engine = transport(
            partition(opened), absorption=[0.1, 0.3], scattering=[0.2, 0.8]
        )
        events, energy = engine.trace(source, mic, rays=16384, horizon=0.3)
        received = events["kind"] == 1
        assert np.all(np.isfinite(energy)) and np.all(energy >= 0)
        assert bool(received.any()) == opened
        # Both-sided polygons must keep every reflected flight inside its compartment.
        if not opened:
            assert events["position"][:, 0].max() <= 3.0001
        parents = events["parent"]
        valid = parents >= 0
        assert np.all(events["ray"][parents[valid]] == events["ray"][valid])
        assert np.all(events["distance"][valid] >= events["distance"][parents[valid]])


def test_source_receiver_order_and_unchanged_refresh(transport):
    engine = transport()
    mics = np.array([[4, 3, 1.2], [4, 3, 1.2], [4, 3.2, 1.2]])
    first, energy = engine.trace([2, 3, 1.2], mics)
    again, repeated = engine.trace([2, 3, 1.2], mics)
    np.testing.assert_array_equal(first, again)
    np.testing.assert_array_equal(energy, repeated)
    for m in (0, 1):
        mask = first["receiver"] == m
        other = first["receiver"] == 1 - m
        np.testing.assert_array_equal(first["distance"][mask], first["distance"][other])
        np.testing.assert_array_equal(energy[mask], energy[other])
    reverse, reverse_energy = engine.trace([2, 3, 1.2], mics[::-1])
    for m in range(3):
        mask, other = first["receiver"] == m, reverse["receiver"] == 2 - m
        np.testing.assert_array_equal(
            first["distance"][mask], reverse["distance"][other]
        )
        np.testing.assert_array_equal(energy[mask], reverse_energy[other])
    alone, single_energy = engine.trace([2, 3, 1.2], mics[:1])
    np.testing.assert_array_equal(
        energy[first["receiver"] == 0], single_energy[alone["receiver"] == 0]
    )


def test_specular_ownership_and_band_branch_weights(transport):
    engine = transport(absorption=[0.2, 0.2, 0.2], scattering=[0, 0.4, 1], order=3)
    events, energy = engine.trace([2, 3, 1.2], [[4, 3, 1.2]], rays=16384)
    receiver = events["kind"] == 1
    assert not np.any(
        receiver & (events["bounce"] <= 3) & (events["diffuse_bounces"] == 0)
    )
    assert not np.any(energy[receiver & (events["diffuse_bounces"] > 0), 0])
    surface = events["kind"] == 0
    for bounce in (0, 1, 2, 3):
        # In a closed uniform room total wall flux is 2*(1-a)**(bounce+1).
        flux = energy[surface & (events["bounce"] == bounce)].sum(axis=0, dtype=float)
        np.testing.assert_allclose(flux, 2 * 0.8 ** (bounce + 1), rtol=0.055)


def test_trace_horizon_and_failure_clear_partial_capture(transport):
    engine = transport()
    events, _ = engine.trace([2, 3, 1.2], [[4, 3, 1.2]], horizon=0.03)
    assert np.all(events["distance"] <= 0.03 * 343 + 1e-5)
    with pytest.raises(RuntimeError, match="budget exceeded"):
        engine.trace([2, 3, 1.2], limit=1)
    with pytest.raises(RuntimeError, match="Invalid PRA trace"):
        engine.trace([2, 3, 1.2], rays=0)
    after, _ = engine.trace([2, 3, 1.2], horizon=0.03)
    assert len(after)


def test_distinct_scenes_have_isolated_random_streams(transport):
    first, second = transport(), transport(scattering=.8)
    args = ([2, 3, 1.2], [[4, 3, 1.2]])
    expected_a = first.trace(*args, seed=9)
    expected_b = second.trace(*args, seed=71)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.trace, *args, seed=9)
        b = pool.submit(second.trace, *args, seed=71)
        for actual, expected in ((a.result(), expected_a), (b.result(), expected_b)):
            for value, reference in zip(actual, expected, strict=True):
                np.testing.assert_array_equal(value, reference)
