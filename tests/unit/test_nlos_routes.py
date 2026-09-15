"""Route interpolation ownership and checked opt-in configuration."""

from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene import SteamNLOSConfig
from isaac_audio_sensors.isaac.acoustic_scene._nlos import endpoint_directions
from isaac_audio_sensors.isaac.acoustic_scene._paths import Route, canonical_routes


def test_probe_representations_preserve_interpolation_without_duplicate_energy():
    points = np.array([[2.0, 0, 0], [0, 1, 0], [-2.0, 0, 0]])
    first = Route((-1, 0, -2), points, 2 * np.sqrt(5), 0.3, (0.9, 0.8, 0.7))
    other = replace(first, probes=(-1, 1, -2), weight=0.7)
    canonical = canonical_routes([first, other])
    assert len(canonical) == 1 and canonical[0].weight == 1
    reverse = canonical_routes([other, first])
    np.testing.assert_array_equal(canonical[0].points, reverse[0].points)
    assert canonical[0].eq == reverse[0].eq
    assert canonical_routes([replace(first, probes=(-1, 99, -2))])[0].weight == 0.3
    with pytest.raises(RuntimeError, match="duplicate"):
        canonical_routes([first, first])
    opposite = replace(other, points=points * (1, -1, 1))
    assert len(canonical_routes([first, opposite])) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"probe_spacing_m": 0},
        {"probe_height_m": float("nan")},
        {"max_probes": True},
        {"update_hz": 0},
    ],
)
def test_nlos_invalid_configuration_fails(kwargs):
    with pytest.raises(ValueError):
        SteamNLOSConfig(**kwargs)


def test_directivity_uses_nonzero_leg_when_endpoint_meets_probe():
    points = np.array([[[0.0, 0, 0], [0.0, 0, 0], [1.0, 1, 0], [1.0, 1, 0]]])
    initial, final = endpoint_directions(points)
    np.testing.assert_array_equal(initial, [[1, 1, 0]])
    np.testing.assert_array_equal(final, [[-1, -1, 0]])
