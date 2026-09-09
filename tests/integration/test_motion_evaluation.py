"""Evaluation must distinguish extra lobes from independently localized sources."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("soundfile")

from tools.validation.motion_localization import score


def test_motion_scoring_requires_one_to_one_directions():
    truth = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    result = score(np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]), truth)
    assert result["count"]
    assert not result["exact"]
    assert result["misses"] == result["extras"] == 1
    assert result["matched"] == [0]
    assert max(result["errors"]) == pytest.approx(90.0)
    assert not score(np.array([[1.0, 0.0, 0.0]]), np.empty((0, 3)))["exact"]
    assert score(np.empty((0, 3)), np.empty((0, 3)))["exact"]
