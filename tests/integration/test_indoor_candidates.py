"""Geometry, mixture-only and evaluation contracts for isolated indoor trials."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")

from tools.qualification.doa_04_4.cases import ARRAYS, FS, match
from tools.qualification.doa_04_4.indoor_candidates import (
    DirectPathRtf,
    WeightedHistogramSrp,
)


@pytest.mark.parametrize("factory", (DirectPathRtf, WeightedHistogramSrp))
@pytest.mark.parametrize("array", ("triangle", "tetra"))
def test_candidates_reject_silence_and_unsupported_geometry(factory, array):
    positions = ARRAYS[array]
    silence = np.zeros((len(positions), 4000))
    silence.setflags(write=False)
    estimator = factory()
    found, diagnostic = estimator.localize(silence, positions, FS)
    assert found.shape == (0, 3)
    assert diagnostic["status"] == "no_events"
    with pytest.raises(ValueError, match="non-collinear"):
        estimator.localize(silence[:2], positions[:2], FS)


@pytest.mark.parametrize("array", ("triangle", "tetra"))
def test_angular_histogram_has_no_two_source_cap(array):
    estimator = WeightedHistogramSrp()
    _, (vectors, _, _, _, _, near) = estimator.prepare(
        np.zeros((len(ARRAYS[array]), 4000)), ARRAYS[array], FS
    )
    # Include the azimuth seam and a polar direction in the spherical case.
    truth = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0]])
    if array == "tetra":
        truth[2] = [0, 0, 1]
    histogram = np.zeros(len(vectors))
    histogram[np.argmax(vectors @ truth.T, axis=0)] = 1 / 3
    found, _ = estimator.events(vectors, histogram, near, {})
    assert match(found, truth)["tp"] == 3
    assert len(found) == 3


def test_pair_matching_cannot_pass_by_returning_two_wrong_directions():
    from tools.qualification.doa_04_4.progressive import grouped

    truth = np.array([[1, 0, 0], [0, 1, 0]])
    rows = [
        dict(
            candidate="trial",
            array="triangle",
            stage="room",
            content="noise",
            count=count,
            compute_ms=1,
            **match(-truth[:count], truth[:count]),
        )
        for count in (0, 1, 2)
    ]
    protocol = dict(
        stages=[dict(name="room")],
        contents=["noise"],
        quality_reference=dict(
            minimum_precision=0.95,
            minimum_recall=0.85,
            minimum_pair_count_accuracy=0.8,
            minimum_count_accuracy=0.85,
            minimum_both_localized_without_extras=0.8,
            maximum_angular_p95_deg=15,
        ),
    )
    result = grouped(rows, protocol)["trial"]["triangle"]["room"]
    assert result["exact_pair_count"] == 1
    assert result["both_localized_without_extras"] == 0
    assert result["second_source_recall"] == 0
    assert "both_localized_without_extras" in result["below_reference"]
