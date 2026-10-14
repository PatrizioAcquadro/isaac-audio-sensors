"""Lazy selection and availability semantics without optional dependencies."""

import builtins

import numpy as np
import pytest

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer


def test_default_profile_keeps_historical_wpe_and_disables_coherence():
    localizer = MaintainedEventLocalizer()
    assert localizer.consumer_context_duration_s == 0.75
    assert localizer.dereverberation_enabled is True
    assert localizer.spatial_coherence_threshold is None


@pytest.mark.parametrize("duration", [0, 0.149, 0.751, float("nan"), float("inf")])
def test_context_duration_rejects_unsupported_values(duration):
    with pytest.raises(ValueError, match="context"):
        MaintainedEventLocalizer(context_duration_s=duration)


@pytest.mark.parametrize("duration", [True, "0.25", None])
def test_context_duration_rejects_coercion(duration):
    with pytest.raises(TypeError, match="context"):
        MaintainedEventLocalizer(context_duration_s=duration)


def test_selected_context_controls_readiness_without_changing_stereo():
    localizer = MaintainedEventLocalizer(context_duration_s=0.25)
    assert localizer.consumer_context_duration_s_for(16000, 4) == 0.25
    assert localizer.consumer_context_duration_s_for(8000, 2) == 0.25
    events, diagnostic = localizer.localize(
        np.ones((3, 3999)),
        np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]]),
        16000,
    )
    assert not events and diagnostic["reason"] == "insufficient_context"


def test_dereverberation_flag_rejects_non_boolean():
    with pytest.raises(TypeError, match="dereverberation_enabled"):
        MaintainedEventLocalizer(dereverberation_enabled=0)


@pytest.mark.parametrize("threshold", [0, -0.1, 1.01, float("nan"), float("inf")])
def test_spatial_coherence_rejects_invalid_threshold(threshold):
    with pytest.raises(ValueError, match="spatial coherence"):
        MaintainedEventLocalizer(spatial_coherence_threshold=threshold)


@pytest.mark.parametrize("threshold", [True, "0.98"])
def test_spatial_coherence_rejects_coercion(threshold):
    with pytest.raises(TypeError, match="spatial coherence"):
        MaintainedEventLocalizer(spatial_coherence_threshold=threshold)


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
    events, diagnostics = MaintainedEventLocalizer(
        spatial_coherence_threshold=0.98
    ).localize(
        np.stack([source, np.roll(source, 2)]),
        np.array([[0, -0.05, 0], [0, 0.05, 0]]),
        16000,
    )
    assert len(events) == 1
    assert len(events[0].candidate_bearing_deg) == 2
    assert diagnostics["single_event_policy"]
