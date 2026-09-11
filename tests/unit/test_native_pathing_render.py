"""Emission-clock controls for the experimental native route renderer."""

import numpy as np
import pytest

from tools.native.pathing import EmissionConvolution

pytest.importorskip("scipy")


def test_changed_route_does_not_retime_or_erase_existing_arrivals():
    stream = EmissionConvolution(1, 64)
    old = np.r_[np.zeros(20), 1.0, 0.2]
    new = np.r_[np.zeros(35), 0.5]
    # One sample already left on the old route; the second uses the new route.
    first = stream.process(np.r_[1.0, np.zeros(9)], [old])
    second = stream.process(np.r_[1.0, np.zeros(9)], [new])
    rest = stream.process(np.zeros(60), [np.zeros(1)])
    received = np.concatenate((first, second, rest), axis=1)[0]
    expected = np.zeros(80)
    expected[[20, 21, 45]] = [1, 0.2, 0.5]
    np.testing.assert_allclose(received, expected, atol=1e-7)
    stream.reset()
    np.testing.assert_array_equal(stream.process(np.zeros(80), [old]), 0)


def test_emission_convolution_block_equivalence_and_independence():
    rng = np.random.default_rng(7)
    x = rng.normal(size=200).astype(np.float32)
    impulses = [np.r_[np.zeros(20), 0.4], np.r_[np.zeros(30), 0.5]]
    full = EmissionConvolution(2, 64)
    expected = full.process(x, impulses)
    partial = EmissionConvolution(2, 64)
    actual = np.concatenate(
        [partial.process(y, impulses) for y in np.split(x, [11, 46, 152])], axis=1
    )
    np.testing.assert_allclose(actual, expected, atol=4e-7)
    partial.reset()
    assert np.max(abs(full.pending)) > 0.1
    with pytest.raises(ValueError, match="horizon"):
        full.process(x, [np.ones(65)] * 2)
    assert np.max(abs(full.pending)) > 0.1
