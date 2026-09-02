from __future__ import annotations

import math

import numpy as np
import pytest

from isaac_audio_sensors.core.doa.srp_phat import (
    SrpPhatResult,
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.math_utils import angular_error_deg
from isaac_audio_sensors.core.microphone_array import microphone_layout

SAMPLE_RATE_HZ = 48_000
SPEED_OF_SOUND_MPS = 343.0


def _direction_unit(bearing_deg: float, elevation_deg: float):
    bearing = math.radians(bearing_deg)
    elevation = math.radians(elevation_deg)
    return np.asarray(
        (
            math.cos(elevation) * math.cos(bearing),
            math.cos(elevation) * math.sin(bearing),
            math.sin(elevation),
        )
    )


def _layout_positions(layout_name: str) -> dict[str, tuple[float, float, float]]:
    return {
        microphone.mic_id: microphone.relative_position_m
        for microphone in microphone_layout(layout_name)
    }


def _plane_wave_waveforms(
    positions: dict[str, tuple[float, float, float]],
    *,
    bearing_deg: float,
    elevation_deg: float,
    sample_count: int = 4096,
    seed: int = 1234,
) -> dict[str, np.ndarray]:
    """Synthesize per-mic noise delayed by exact fractional plane-wave lags."""

    rng = np.random.default_rng(seed)
    signal = rng.standard_normal(sample_count)
    spectrum = np.fft.rfft(signal)
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / SAMPLE_RATE_HZ)
    direction = _direction_unit(bearing_deg, elevation_deg)
    waveforms: dict[str, np.ndarray] = {}
    for mic_id, position in positions.items():
        delay_s = -float(np.dot(np.asarray(position), direction)) / SPEED_OF_SOUND_MPS
        shifted = spectrum * np.exp(-2j * math.pi * frequencies * delay_s)
        waveforms[mic_id] = np.fft.irfft(shifted, n=sample_count)
    return waveforms


@pytest.mark.parametrize(
    ("bearing_deg", "elevation_deg"),
    [
        (0.0, 0.0),
        (40.0, 30.0),
        (130.0, -25.0),
        (270.0, 60.0),
    ],
)
def test_srp_phat_tetrahedral_recovers_bearing_and_elevation(
    bearing_deg, elevation_deg
):
    positions = _layout_positions("tetrahedral")
    waveforms = _plane_wave_waveforms(
        positions, bearing_deg=bearing_deg, elevation_deg=elevation_deg
    )

    result = srp_phat_direction(
        waveforms,
        mic_positions_m=positions,
        sample_rate_hz=SAMPLE_RATE_HZ,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )

    assert isinstance(result, SrpPhatResult)
    assert angular_error_deg(result.bearing_deg, bearing_deg) <= (
        result.azimuth_step_deg
    )
    assert result.elevation_deg is not None
    assert abs(result.elevation_deg - elevation_deg) <= result.elevation_step_deg
    assert result.pair_count == 6
    assert result.peak_power > result.mean_power
    assert 0.0 < srp_phat_confidence(result) <= 1.0


@pytest.mark.parametrize("bearing_deg", [0.0, 90.0, 210.0])
def test_srp_phat_planar_array_steers_azimuth_only(bearing_deg):
    positions = _layout_positions("quad_front")
    waveforms = _plane_wave_waveforms(
        positions, bearing_deg=bearing_deg, elevation_deg=0.0
    )

    result = srp_phat_direction(
        waveforms,
        mic_positions_m=positions,
        sample_rate_hz=SAMPLE_RATE_HZ,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )

    assert angular_error_deg(result.bearing_deg, bearing_deg) <= (
        result.azimuth_step_deg
    )
    assert result.elevation_deg is None
    assert result.elevation_step_deg is None
    assert result.grid_point_count == int(360.0 / result.azimuth_step_deg)


def test_srp_phat_rejects_degenerate_inputs():
    positions = _layout_positions("quad_front")
    waveforms = _plane_wave_waveforms(positions, bearing_deg=0.0, elevation_deg=0.0)

    with pytest.raises(ValueError, match="at least three microphones"):
        srp_phat_direction(
            {"front": waveforms["front"]},
            mic_positions_m=positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
    collinear_positions = {
        "left": (0.0, -0.05, 0.0),
        "center": (0.0, 0.0, 0.0),
        "right": (0.0, 0.05, 0.0),
    }
    collinear_waveforms = _plane_wave_waveforms(
        collinear_positions,
        bearing_deg=0.0,
        elevation_deg=0.0,
    )
    with pytest.raises(ValueError, match="non-collinear"):
        srp_phat_direction(
            collinear_waveforms,
            mic_positions_m=collinear_positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
    with pytest.raises(ValueError, match="missing microphone ids"):
        srp_phat_direction(
            waveforms,
            mic_positions_m={"front": positions["front"]},
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        srp_phat_direction(
            {**waveforms, "front": np.asarray([])},
            mic_positions_m=positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
    with pytest.raises(ValueError, match="non-zero sample"):
        srp_phat_direction(
            {**waveforms, "front": np.zeros(64)},
            mic_positions_m=positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
    with pytest.raises(ValueError, match="sample_rate_hz"):
        srp_phat_direction(
            waveforms,
            mic_positions_m=positions,
            sample_rate_hz=0,
        )
    with pytest.raises(ValueError, match="azimuth_step_deg"):
        srp_phat_direction(
            waveforms,
            mic_positions_m=positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
            azimuth_step_deg=0.0,
        )
