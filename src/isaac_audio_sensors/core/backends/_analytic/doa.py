"""Direct-path TDOA localization used internally by AnalyticAcoustics."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS, EPSILON
from isaac_audio_sensors.core.doa.ambiguity import (
    TWO_MIC_ENDPOINT_TOLERANCE,
    choose_front_hemisphere_candidate,
    deduplicate_candidate_bearings,
    two_mic_candidate_bearings,
)
from isaac_audio_sensors.core.doa.least_squares import least_squares_direction
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import bearing_from_components, clamp
from isaac_audio_sensors.core.types import DoaEstimate, MicrophoneArraySpec


def estimate_doa_from_delays(
    *,
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
    ambiguity_policy: str = "none",
) -> DoaEstimate:
    """Estimate direction from direct-path per-microphone delays."""

    if len(sensor.microphones) == 2:
        return _estimate_two_mic(
            sensor,
            per_mic_delay_s,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
        )
    result = least_squares_direction(
        sensor,
        per_mic_delay_s,
        speed_of_sound_mps,
    )
    if result is None:
        return DoaEstimate(
            estimated_bearing_deg=None,
            bearing_confidence=0.0,
            ambiguity_class="degenerate_array",
            ambiguity_reason="Microphone layout cannot solve a 2D direction.",
        )
    ux, uy, uz, residual = result
    bearing = bearing_from_components(ux, uy)
    if bearing is None:
        return DoaEstimate(
            estimated_bearing_deg=None,
            bearing_confidence=0.0,
            ambiguity_class="degenerate_solution",
            ambiguity_reason="Least-squares direction has zero horizontal norm.",
        )
    elevation = (
        None if uz is None else math.degrees(math.asin(clamp(uz, -1.0, 1.0)))
    )
    confidence = 0.95 / (1.0 + residual * 40.0)
    return DoaEstimate(
        estimated_bearing_deg=bearing,
        candidate_bearing_deg=deduplicate_candidate_bearings((bearing,)),
        bearing_sector=bearing_deg_to_sector_name(bearing),
        bearing_confidence=clamp(confidence, 0.0, 1.0),
        ambiguity_class=None,
        ambiguity_reason=None,
        estimated_elevation_deg=elevation,
        candidate_elevation_deg=(() if elevation is None else (elevation,)),
    )


def _estimate_two_mic(
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    *,
    speed_of_sound_mps: float,
    ambiguity_policy: str,
) -> DoaEstimate:
    first, second = sensor.microphones
    baseline = (
        second.relative_position_m[0] - first.relative_position_m[0],
        second.relative_position_m[1] - first.relative_position_m[1],
    )
    spacing = math.hypot(*baseline)
    if spacing <= EPSILON:
        return DoaEstimate(
            estimated_bearing_deg=None,
            bearing_confidence=0.0,
            ambiguity_class="degenerate_array",
            ambiguity_reason="Two microphones are coincident in local XY.",
        )
    delay_s = per_mic_delay_s[second.mic_id] - per_mic_delay_s[first.mic_id]
    projection = -speed_of_sound_mps * delay_s / spacing
    if abs(projection) > 1.0 + TWO_MIC_ENDPOINT_TOLERANCE:
        return DoaEstimate(
            estimated_bearing_deg=None,
            bearing_confidence=0.0,
            ambiguity_class="invalid_tdoa_delay",
            ambiguity_reason=(
                "Observed delay exceeds the physical two-microphone aperture."
            ),
        )
    candidates = two_mic_candidate_bearings(
        baseline_unit_xy=(baseline[0] / spacing, baseline[1] / spacing),
        projection=clamp(projection, -1.0, 1.0),
    )
    if len(candidates) <= 1:
        return DoaEstimate(
            estimated_bearing_deg=candidates[0] if candidates else None,
            candidate_bearing_deg=candidates,
            bearing_confidence=0.9,
        )
    if ambiguity_policy == "front_hemisphere":
        return DoaEstimate(
            estimated_bearing_deg=choose_front_hemisphere_candidate(candidates),
            candidate_bearing_deg=candidates,
            bearing_confidence=0.65,
            ambiguity_class="front_hemisphere_prior",
            ambiguity_reason=(
                "Two-mic TDOA is front/back ambiguous; selected a bearing using "
                "the explicit front_hemisphere prior."
            ),
        )
    return DoaEstimate(
        estimated_bearing_deg=None,
        candidate_bearing_deg=candidates,
        bearing_confidence=0.35,
        ambiguity_class="ambiguous_front_back",
        ambiguity_reason=(
            "Two-mic linear TDOA cannot distinguish mirrored front/back bearings "
            "without an explicit prior."
        ),
    )


__all__ = ["estimate_doa_from_delays"]
