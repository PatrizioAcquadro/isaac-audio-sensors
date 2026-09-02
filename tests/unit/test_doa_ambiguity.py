from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.backends._analytic.doa import (
    estimate_doa_from_delays,
)
from isaac_audio_sensors.core.microphone_array import validate_tdoa_array
from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec

SPEED_OF_SOUND_MPS = 343.0


def _array(*positions: tuple[float, float, float]) -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="array",
        prim_path="/World/Array",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=tuple(
            MicrophoneSpec(mic_id=f"mic_{index}", relative_position_m=position)
            for index, position in enumerate(positions)
        ),
    )


def _plane_wave_delays(
    sensor: MicrophoneArraySpec,
    bearing_deg: float,
) -> dict[str, float]:
    angle = math.radians(bearing_deg)
    direction = (math.cos(angle), math.sin(angle))
    return {
        microphone.mic_id: -(
            microphone.relative_position_m[0] * direction[0]
            + microphone.relative_position_m[1] * direction[1]
        )
        / SPEED_OF_SOUND_MPS
        for microphone in sensor.microphones
    }


def test_two_mic_tdoa_returns_both_compatible_azimuths_without_estimate():
    sensor = _array((0.0, -0.05, 0.0), (0.0, 0.05, 0.0))

    result = estimate_doa_from_delays(
        sensor=sensor,
        per_mic_delay_s=_plane_wave_delays(sensor, 0.0),
    )

    assert result.estimated_bearing_deg is None
    assert result.candidate_bearing_deg == (0.0, 180.0)
    assert result.bearing_sector is None
    assert result.bearing_confidence == 0.0
    assert result.estimated_elevation_deg is None
    assert result.ambiguity_class == "ambiguous_front_back"
    assert "prior" not in str(result.ambiguity_reason).lower()


def test_two_mic_endpoint_has_one_physically_unique_azimuth():
    sensor = _array((0.0, -0.05, 0.0), (0.0, 0.05, 0.0))

    result = estimate_doa_from_delays(
        sensor=sensor,
        per_mic_delay_s=_plane_wave_delays(sensor, 90.0),
    )

    assert result.estimated_bearing_deg == pytest.approx(90.0)
    assert result.candidate_bearing_deg == pytest.approx((90.0,))
    assert result.bearing_sector == "right"
    assert result.ambiguity_class is None


@pytest.mark.parametrize("bearing_deg", (0.0, 75.0, 210.0, 359.0))
def test_three_non_collinear_mics_recover_unique_azimuth(bearing_deg):
    sensor = _array((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0))

    result = estimate_doa_from_delays(
        sensor=sensor,
        per_mic_delay_s=_plane_wave_delays(sensor, bearing_deg),
    )

    assert result.estimated_bearing_deg == pytest.approx(bearing_deg)
    assert result.candidate_bearing_deg == pytest.approx((bearing_deg,))
    assert result.ambiguity_class is None


def test_three_or_more_collinear_mics_fail_closed():
    sensor = _array(
        (0.0, -0.05, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.05, 0.0),
        (0.0, 0.1, 0.0),
    )

    with pytest.raises(ValueError, match="non-collinear"):
        validate_tdoa_array(sensor)
