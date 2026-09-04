from __future__ import annotations

import numpy as np
import pytest

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.plugins.registry import PluginAvailability
from isaac_audio_sensors.core.plugins.standard_doa import MaintainedDoaEstimator


def _samples(channels: int, *, sample_rate_hz: int = 16_000) -> np.ndarray:
    rng = np.random.default_rng(91)
    source = rng.standard_normal(sample_rate_hz // 4)
    return np.stack([np.roll(source, index) for index in range(channels)])


def test_standard_selector_routes_two_microphones_without_pyroom() -> None:
    positions = np.asarray(((0.0, -0.05, 0.0), (0.0, 0.05, 0.0)))

    estimate, diagnostics = MaintainedDoaEstimator().estimate(
        _samples(2),
        positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.candidate_bearing_deg
    assert diagnostics["doa_estimator"] == "tdoa_least_squares"
    assert diagnostics["selection"] == {
        "policy": "maintained_roles_v1",
        "role": "two_microphone_ambiguity",
        "selected_estimator_id": "tdoa_least_squares",
    }


def test_standard_selector_routes_only_qualified_planar_geometry() -> None:
    pytest.importorskip("pyroomacoustics")
    positions = np.asarray(
        (
            (-0.03, -0.03, 0.0),
            (-0.03, 0.03, 0.0),
            (0.03, 0.03, 0.0),
            (0.03, -0.03, 0.0),
        )
    )

    _estimate, diagnostics = MaintainedDoaEstimator().estimate(
        _samples(4),
        positions,
        16_000,
    )

    assert diagnostics["doa_estimator"] == "pyroomacoustics_srp"
    assert diagnostics["selection"]["role"] == "primary_planar_doa"


@pytest.mark.parametrize(
    ("positions", "role"),
    (
        (
            np.asarray(
                (
                    (-0.03, -0.03, 0.0),
                    (-0.03, 0.03, 0.0),
                    (0.03, 0.03, 0.0),
                    (0.03, -0.03, 0.0),
                    (0.0, 0.0, 0.04),
                )
            ),
            "optional_3d_unselected",
        ),
        (
            np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.0, 0.0))),
            "unsupported_geometry",
        ),
        (
            np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.1), (0.0, 0.1, 0.1))),
            "unsupported_geometry",
        ),
    ),
)
def test_standard_selector_abstains_for_unselected_geometry(
    positions: np.ndarray,
    role: str,
) -> None:
    estimate, diagnostics = MaintainedDoaEstimator().estimate(
        _samples(len(positions)),
        positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.ambiguity_class == "unsupported_geometry"
    assert diagnostics["doa_estimator"] is None
    assert diagnostics["selection"]["role"] == role


def test_standard_selector_abstains_before_full_context() -> None:
    positions = np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)))

    estimate, diagnostics = MaintainedDoaEstimator().estimate(
        np.ones((3, 3999)),
        positions,
        16_000,
    )

    assert estimate.ambiguity_class == "insufficient_context"
    assert diagnostics["doa_estimator"] == "pyroomacoustics_srp"
    assert diagnostics["required_observation_samples"] == 4000
    assert diagnostics["available_observation_samples"] == 3999


def test_planar_selector_reports_actionable_room_extra(monkeypatch) -> None:
    from isaac_audio_sensors.core.plugins import registry as registry_module

    registry = registry_module.get_default_registry()
    monkeypatch.setattr(
        registry,
        "probe_availability",
        lambda kind, plugin_id: PluginAvailability(
            available=False,
            missing_dependencies=("pyroomacoustics",),
        ),
    )
    positions = np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)))

    with pytest.raises(
        OptionalDependencyUnavailable,
        match=r"isaac-audio-sensors\[room\]",
    ):
        MaintainedDoaEstimator().estimate(_samples(3), positions, 16_000)
