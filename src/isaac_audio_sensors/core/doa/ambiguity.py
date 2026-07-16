"""DOA ambiguity helpers, especially for two-microphone arrays."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.math_utils import (
    Vector3,
    bearing_from_components,
    clamp,
    normalize,
    normalize_bearing_deg,
)

# Eight binary64 ULPs admit only arithmetic noise at the physical endpoint;
# this is not a sensor-resolution band around the microphone baseline axis.
TWO_MIC_ENDPOINT_TOLERANCE = 8 * math.ulp(1.0)


def deduplicate_candidate_bearings(
    candidates: tuple[float, ...],
    *,
    tolerance_deg: float = 1e-6,
) -> tuple[float, ...]:
    """Normalize and remove duplicate candidate bearings."""

    unique: list[float] = []
    for candidate in candidates:
        normalized = normalize_bearing_deg(candidate)
        if all(
            _angular_distance(normalized, existing) > tolerance_deg
            for existing in unique
        ):
            unique.append(normalized)
    return tuple(sorted(unique))


def two_mic_candidate_bearings(
    *,
    baseline_unit_xy: tuple[float, float],
    projection: float,
) -> tuple[float, ...]:
    """Return symmetric candidate bearings from a two-mic TDOA projection.

    ``projection`` is the source direction projected onto the microphone
    baseline unit vector. A two-mic linear array cannot distinguish the two
    directions mirrored across the baseline without an additional prior.
    """

    bx, by = baseline_unit_xy
    baseline_norm = math.hypot(bx, by)
    if baseline_norm <= 0.0:
        raise ValueError("baseline_unit_xy must be non-zero.")
    bx /= baseline_norm
    by /= baseline_norm

    perpendicular = (by, -bx)
    clipped_projection = clamp(projection, -1.0, 1.0)
    if math.isclose(
        abs(clipped_projection),
        1.0,
        rel_tol=0.0,
        abs_tol=TWO_MIC_ENDPOINT_TOLERANCE,
    ):
        # Exact baseline-axis delays can land a few ULPs inside the endpoint.
        direction = math.copysign(1.0, clipped_projection)
        bearing = bearing_from_components(direction * bx, direction * by)
        return () if bearing is None else (normalize_bearing_deg(bearing),)

    perpendicular_scale = math.sqrt(max(0.0, 1.0 - clipped_projection**2))

    candidates: list[float] = []
    for sign in (1.0, -1.0):
        ux = clipped_projection * bx + sign * perpendicular_scale * perpendicular[0]
        uy = clipped_projection * by + sign * perpendicular_scale * perpendicular[1]
        bearing = bearing_from_components(ux, uy)
        if bearing is not None:
            candidates.append(bearing)
    return deduplicate_candidate_bearings(tuple(candidates))


def choose_front_hemisphere_candidate(candidates: tuple[float, ...]) -> float | None:
    """Choose the candidate in the local front hemisphere when available."""

    if not candidates:
        return None
    front = [
        candidate for candidate in candidates if candidate <= 90.0 or candidate >= 270.0
    ]
    if not front:
        return candidates[0]
    return min(front, key=lambda candidate: min(candidate, 360.0 - candidate))


def direction_vector_from_bearing_deg(bearing_deg: float) -> Vector3:
    """Return a local unit direction vector for a clockwise bearing."""

    rad = math.radians(normalize_bearing_deg(bearing_deg))
    return normalize((math.cos(rad), math.sin(rad), 0.0), "bearing direction")


def _angular_distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)
