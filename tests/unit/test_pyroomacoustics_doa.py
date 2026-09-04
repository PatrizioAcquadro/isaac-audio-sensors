from __future__ import annotations

import importlib

import numpy as np
import pytest

from isaac_audio_sensors.core.plugins import (
    GccPhatLeastSquaresEstimator,
    PyroomacousticsSrpEstimator,
    SrpPhatEstimator,
)


def _plane_wave(
    positions: np.ndarray,
    *,
    bearing_deg: float,
    elevation_deg: float = 0.0,
    sample_rate_hz: int = 16_000,
    sample_count: int = 2048,
) -> np.ndarray:
    rng = np.random.default_rng(41)
    source = rng.standard_normal(sample_count + 128)
    azimuth = np.radians(bearing_deg)
    elevation = np.radians(elevation_deg)
    direction = np.asarray(
        (
            np.cos(elevation) * np.cos(azimuth),
            np.cos(elevation) * np.sin(azimuth),
            np.sin(elevation),
        )
    )
    time = np.arange(sample_count, dtype=float) + 64.0
    return np.stack(
        [
            np.interp(
                time + float(position @ direction) / 343.0 * sample_rate_hz,
                np.arange(source.size, dtype=float),
                source,
                left=0.0,
                right=0.0,
            )
            for position in positions
        ]
    )


@pytest.fixture
def planar_positions() -> np.ndarray:
    return np.asarray(
        (
            (-0.033, -0.033, 0.0),
            (-0.033, 0.033, 0.0),
            (0.033, 0.033, 0.0),
            (0.033, -0.033, 0.0),
        )
    )


def test_pyroom_srp_resolves_planar_direction(planar_positions: np.ndarray) -> None:
    pytest.importorskip("pyroomacoustics")
    estimator = PyroomacousticsSrpEstimator()

    estimate, diagnostics = estimator.estimate(
        _plane_wave(planar_positions, bearing_deg=46.0),
        planar_positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg == pytest.approx(46.0, abs=2.0)
    assert estimate.estimated_elevation_deg is None
    assert 0.0 < estimate.bearing_confidence <= 1.0
    assert diagnostics["doa_estimator"] == "pyroomacoustics_srp"
    assert diagnostics["stft"]["snapshot_count"] == 7
    assert diagnostics["resolved"] is True


def test_pyroom_srp_resolves_rank_three_direction() -> None:
    pytest.importorskip("pyroomacoustics")
    positions = np.asarray(
        (
            (-0.03, -0.03, 0.0),
            (-0.03, 0.03, 0.0),
            (0.03, 0.03, 0.0),
            (0.03, -0.03, 0.0),
            (0.0, 0.0, 0.04),
        )
    )

    estimate, diagnostics = PyroomacousticsSrpEstimator().estimate(
        _plane_wave(positions, bearing_deg=60.0, elevation_deg=25.0),
        positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg == pytest.approx(60.0, abs=2.0)
    assert estimate.estimated_elevation_deg == pytest.approx(25.0, abs=5.0)
    assert diagnostics["srp_phat"]["elevation_step_deg"] == 5.0


@pytest.mark.parametrize(
    ("samples", "positions", "ambiguity_class"),
    (
        (
            np.ones((4, 256)),
            np.asarray(
                ((0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.1, 0.1, 0.0), (0.1, 0.0, 0.0))
            ),
            "insufficient_context",
        ),
        (
            np.ones((3, 1024)),
            np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.0, 0.0))),
            "unsupported_geometry",
        ),
        (
            np.zeros((4, 1024)),
            np.asarray(
                ((0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.1, 0.1, 0.0), (0.1, 0.0, 0.0))
            ),
            "low_information",
        ),
        (
            np.tile(np.sin(np.arange(1024, dtype=float) / 10.0), (4, 1)),
            np.asarray(
                ((0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.1, 0.1, 0.0), (0.1, 0.0, 0.0))
            ),
            "unobservable_azimuth",
        ),
    ),
)
def test_pyroom_srp_abstains_without_importing_dependency(
    monkeypatch: pytest.MonkeyPatch,
    samples: np.ndarray,
    positions: np.ndarray,
    ambiguity_class: str,
) -> None:
    module = importlib.import_module(
        "isaac_audio_sensors.core.plugins.pyroomacoustics"
    )
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda _name: pytest.fail("dependency import was not expected"),
    )

    estimate, diagnostics = PyroomacousticsSrpEstimator().estimate(
        samples,
        positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.bearing_confidence == 0.0
    assert estimate.ambiguity_class == ambiguity_class
    assert diagnostics["resolved"] is False


def test_pyroom_srp_threshold_preserves_observed_candidate(
    planar_positions: np.ndarray,
) -> None:
    pytest.importorskip("pyroomacoustics")
    estimator = PyroomacousticsSrpEstimator(minimum_reliability=1.0)

    estimate, diagnostics = estimator.estimate(
        _plane_wave(planar_positions, bearing_deg=90.0),
        planar_positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.candidate_bearing_deg == pytest.approx((90.0,), abs=2.0)
    assert estimate.ambiguity_class == "low_information"
    assert estimate.bearing_confidence == 0.0
    assert 0.0 < diagnostics["reliability_score"] < 1.0


def test_pyroom_srp_is_deterministic(planar_positions: np.ndarray) -> None:
    pytest.importorskip("pyroomacoustics")
    samples = _plane_wave(planar_positions, bearing_deg=135.0)
    estimator = PyroomacousticsSrpEstimator()

    first = estimator.estimate(samples, planar_positions, 16_000)
    second = estimator.estimate(samples, planar_positions, 16_000)

    assert first == second


def test_pyroom_srp_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
    planar_positions: np.ndarray,
) -> None:
    module = importlib.import_module(
        "isaac_audio_sensors.core.plugins.pyroomacoustics"
    )
    real_import = module.importlib.import_module

    def _missing(name: str):
        if name == "pyroomacoustics":
            raise ImportError(name)
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", _missing)

    with pytest.raises(RuntimeError, match="optional dependencies"):
        PyroomacousticsSrpEstimator().estimate(
            _plane_wave(planar_positions, bearing_deg=0.0),
            planar_positions,
            16_000,
        )


def test_pyroom_srp_rejects_invalid_configuration(
    planar_positions: np.ndarray,
) -> None:
    with pytest.raises(ValueError, match="power of two"):
        PyroomacousticsSrpEstimator(nfft=500)
    with pytest.raises(ValueError, match="Nyquist"):
        PyroomacousticsSrpEstimator(frequency_range_hz=(9000.0, 10_000.0)).estimate(
            _plane_wave(planar_positions, bearing_deg=0.0),
            planar_positions,
            16_000,
        )


def test_internal_srp_abstains_on_unsupported_geometry() -> None:
    positions = np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.0, 0.0)))

    estimate, diagnostics = SrpPhatEstimator().estimate(
        np.ones((3, 1024)),
        positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.ambiguity_class == "unsupported_geometry"
    assert diagnostics["reliability_score"] == 0.0


def test_least_squares_threshold_preserves_candidate(
    planar_positions: np.ndarray,
) -> None:
    estimate, diagnostics = GccPhatLeastSquaresEstimator(
        minimum_reliability=1.0
    ).estimate(
        _plane_wave(planar_positions, bearing_deg=180.0),
        planar_positions,
        16_000,
    )

    assert estimate.estimated_bearing_deg is None
    assert estimate.candidate_bearing_deg
    assert estimate.ambiguity_class == "low_information"
    assert diagnostics["gcc_phat_pair_strength"] > 0.0
