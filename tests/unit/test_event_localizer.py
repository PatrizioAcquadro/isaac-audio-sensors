"""Lazy selection and availability semantics without optional dependencies."""

import builtins

import numpy as np
import pytest

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer


@pytest.mark.parametrize(
    "samples,positions,rate,reason",
    [
        (
            np.ones((3, 4000)),
            [[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0]],
            16000,
            "unsupported_geometry",
        ),
        (
            np.ones((3, 4000)),
            [[0, 0, 0], [0.1, 0, 0.1], [0, 0.1, 0.1]],
            16000,
            "unsupported_geometry",
        ),
        (
            np.ones((4, 4000)),
            [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1]],
            8000,
            "unsupported_sample_rate",
        ),
        (
            np.ones((3, 11999)),
            [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]],
            16000,
            "insufficient_context",
        ),
    ],
)
def test_event_localizer_unavailable(samples, positions, rate, reason):
    events, diagnostics = MaintainedEventLocalizer().localize(
        samples, np.asarray(positions), rate
    )
    assert events == ()
    assert diagnostics == {"status": "unavailable", "reason": reason}


def test_missing_optional_dependencies_are_actionable(monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "nara_wpe.wpe":
            raise ImportError("blocked optional stack")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(
        OptionalDependencyUnavailable, match=r"isaac-audio-sensors\[room\]"
    ):
        MaintainedEventLocalizer().localize(
            np.ones((3, 12000)),
            np.asarray([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]]),
            16000,
        )


def test_stereo_remains_one_ambiguous_event_without_optional_stack():
    source = np.random.default_rng(31).normal(size=4000)
    events, diagnostics = MaintainedEventLocalizer().localize(
        np.stack([source, np.roll(source, 2)]),
        np.array([[0, -0.05, 0], [0, 0.05, 0]]),
        16000,
    )
    assert len(events) == 1
    assert len(events[0].candidate_bearing_deg) == 2
    assert diagnostics["single_event_policy"]
