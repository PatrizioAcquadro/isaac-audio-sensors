"""Observed-event compass, mixture meters and bounded frame history."""

from __future__ import annotations

import colorsys
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from isaac_audio_sensors.core.types import DoaEstimate

OBSERVATION_HISTORY_LIMIT = 50
RMS_METER_FLOOR_DB = -60.0
MIC_DISPLAY_ORDER = {"front": 0, "right": 1, "rear": 2, "left": 3}
COMPASS_IMAGE_SIZE = 192
METER_MAX_ROWS = 8


def event_color(index: int) -> tuple[float, float, float, float]:
    """Frame-local colors; they do not imply persistent event identities."""
    return (*colorsys.hsv_to_rgb((0.36 + index * 0.618) % 1, 0.65, 0.95), 1.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompassNeedle:
    """One bearing needle in widget space (x right, y up, 0 deg = up)."""

    bearing_deg: float
    unit_xy: tuple[float, float]
    is_primary: bool
    event_index: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CompassViewModel:
    """Everything needed to draw the polar bearing compass."""

    needles: tuple[CompassNeedle, ...]
    event_rows: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MeterViewModel:
    """One per-microphone RMS meter row."""

    mic_id: str
    rms_linear: float
    db: float | None
    fraction: float
    text: str


def compass_unit_xy(bearing_deg: float) -> tuple[float, float]:
    """Map a clockwise-from-forward bearing to widget space (0 deg = up)."""

    radians = math.radians(bearing_deg)
    return (math.sin(radians), math.cos(radians))


def direction_text(doa: DoaEstimate | None) -> str:
    if doa is None:
        return "DOA unavailable"
    bearing = doa.estimated_bearing_deg
    elevation = doa.estimated_elevation_deg
    parts = ["bearing unavailable" if bearing is None else f"bearing {bearing:.1f} deg"]
    if elevation is not None:
        parts.append(f"elevation {elevation:.1f} deg")
    if doa.candidate_bearing_deg:
        parts.append(
            "bearing alternatives "
            + ", ".join(f"{angle:.1f}" for angle in doa.candidate_bearing_deg)
            + " deg"
        )
    if doa.candidate_elevation_deg:
        parts.append(
            "elevation alternatives "
            + ", ".join(f"{angle:.1f}" for angle in doa.candidate_elevation_deg)
            + " deg"
        )
    if doa.ambiguity_class is not None:
        parts.append(f"{doa.ambiguity_class}: {doa.ambiguity_reason or 'unresolved'}")
    confidence = doa.bearing_confidence
    parts.append(
        "confidence N/A" if confidence is None else f"confidence {confidence:.2f}"
    )
    return " | ".join(parts)


def compass_view_model(directions: Sequence[DoaEstimate | None]) -> CompassViewModel:
    """Group primary and alternative bearings by their current-frame event."""
    needles = []
    rows = []
    for index, doa in enumerate(directions):
        rows.append(f"Event {index + 1}: {direction_text(doa)}")
        if doa is None:
            continue
        primary = doa.estimated_bearing_deg
        angles = ([] if primary is None else [(primary, True)]) + [
            (angle, False) for angle in doa.candidate_bearing_deg
        ]
        seen = set()
        for angle, is_primary in angles:
            value = float(angle) % 360.0
            if value in seen:
                continue
            seen.add(value)
            needles.append(
                CompassNeedle(
                    bearing_deg=value,
                    unit_xy=compass_unit_xy(value),
                    is_primary=is_primary,
                    event_index=index,
                )
            )
    return CompassViewModel(
        needles=tuple(needles),
        event_rows=tuple(rows),
        summary="\n".join(rows) or "No current observations",
    )


def perception_status_text(frame: Any | None) -> str:
    """Explain observed availability without treating missing diagnostics as silence."""
    if frame is None:
        return "No sensor frame yet. Start the sensor to monitor audio."
    perception = frame.diagnostics.get("perception", {})
    active = perception.get("activity_detected")
    activity = "unavailable" if active is None else "detected" if active else "inactive"
    localization = perception.get("localization", {})
    status = localization.get("status", "unavailable")
    reason = localization.get("reason")
    context = perception.get("doa_context", {})
    if status != "disabled" and (
        reason == "insufficient_context" or context.get("complete") is False
    ):
        status = "warm-up"
    method = localization.get("doa_estimator", "not reported")
    role = localization.get(
        "localization_scope", localization.get("role", "not reported")
    )
    lines = [
        f"Activity: {activity} | Localization: {status}"
        + (f" ({reason})" if reason else ""),
        f"{frame.sample_rate_hz} Hz | Method: {method} | Role: {role}",
    ]
    if context:
        lines.append(
            f"Causal context: {context['available_duration_s']:.3f} / "
            f"{context['required_duration_s']:.3f} s; not a response-delay measurement"
        )
    truncated = perception.get("truncated_observation_count")
    count = len(frame.observations)
    capacity = (
        "unlimited" if frame.max_observations is None else str(frame.max_observations)
    )
    lines.append(
        f"Current events: {count} | Capacity: {capacity} | Truncated: "
        + ("not reported" if truncated is None else str(truncated))
    )
    return "\n".join(lines)


def rms_db(rms_linear: float) -> float | None:
    """Convert linear RMS to dBFS-style dB; ``None`` for silence."""

    value = float(rms_linear)
    if value <= 0.0 or not math.isfinite(value):
        return None
    return 20.0 * math.log10(value)


def meter_fraction(db: float | None, *, floor_db: float = RMS_METER_FLOOR_DB) -> float:
    """Map dB onto a 0..1 meter fill with a fixed floor."""

    if db is None:
        return 0.0
    return min(max(1.0 - (db / floor_db), 0.0), 1.0)


def meter_view_models(
    aggregate_rms: Mapping[str, float],
    *,
    floor_db: float = RMS_METER_FLOOR_DB,
) -> tuple[MeterViewModel, ...]:
    """Build per-mic meter rows in front/right/rear/left display order."""

    rows: list[MeterViewModel] = []
    items = sorted(
        aggregate_rms.items(),
        key=lambda item: (MIC_DISPLAY_ORDER.get(item[0], 99), item[0]),
    )
    for mic_id, value in items:
        rms_linear = float(value)
        if not math.isfinite(rms_linear) or rms_linear < 0.0:
            continue
        db = rms_db(rms_linear)
        db_text = f"{db:.1f} dBFS" if db is not None else "silent"
        rows.append(
            MeterViewModel(
                mic_id=str(mic_id),
                rms_linear=rms_linear,
                db=db,
                fraction=meter_fraction(db, floor_db=floor_db),
                text=f"{mic_id}: {db_text}",
            )
        )
    return tuple(rows)


def record_observation_events(frame: Any) -> list[dict[str, Any]]:
    """Flatten one frame's observations into JSON-friendly history entries."""

    events: list[dict[str, Any]] = []
    frame_id = getattr(frame, "frame_id", None)
    producer_id = getattr(frame, "producer_id", None)
    timestamp_ms = getattr(frame, "timestamp_ms", None)
    for index, observation in enumerate(frame.observations):
        events.append(
            {
                "frame_id": frame_id,
                "producer_id": producer_id,
                "timestamp_ms": timestamp_ms,
                "observation_id": observation.observation_id,
                "text": f"Event {index + 1}: {direction_text(observation.doa)}",
            }
        )
    return events


def append_observation_history(
    history: list[dict[str, Any]],
    frame: Any,
    *,
    limit: int = OBSERVATION_HISTORY_LIMIT,
) -> None:
    """Append one frame's observations to ``history`` and trim to ``limit``."""

    history.extend(record_observation_events(frame))
    overflow = len(history) - int(limit)
    if overflow > 0:
        del history[:overflow]


def timeline_rows(
    history: Sequence[Mapping[str, Any]],
    *,
    max_rows: int = 12,
) -> tuple[str, ...]:
    """Render the most recent observation events, newest first."""

    rows: list[str] = []
    for event in reversed(history[-int(max_rows) :]):
        timestamp_ms = event.get("timestamp_ms")
        time_text = (
            f"{float(timestamp_ms) / 1000.0:8.2f}s"
            if isinstance(timestamp_ms, (int, float))
            else "       ?"
        )
        rows.append(f"{time_text}  {event['text']}")
    return tuple(rows)


def _angle_distance_deg(angles: np.ndarray, center_deg: float) -> np.ndarray:
    return np.abs((angles - center_deg + 180.0) % 360.0 - 180.0)


def _stamp(
    rgba: np.ndarray,
    mask: np.ndarray,
    color: tuple[float, float, float, float],
) -> None:
    alpha = float(color[3])
    channels = np.array(
        [color[0] * 255.0, color[1] * 255.0, color[2] * 255.0], dtype=np.float64
    )
    region = rgba[mask]
    region[:, :3] = (1.0 - alpha) * region[:, :3] + alpha * channels
    region[:, 3] = np.maximum(region[:, 3], alpha * 255.0)
    rgba[mask] = region


def render_compass_rgba(
    view_model: CompassViewModel,
    *,
    size: int = 192,
) -> np.ndarray:
    """Rasterize the compass into an RGBA uint8 image of ``size`` x ``size``.

    Widget convention: 0 deg (array forward) points up; bearings increase
    clockwise, matching the v1 coordinate convention.
    """

    size = int(size)
    rgba = np.zeros((size, size, 4), dtype=np.float64)
    rgba[..., :3] = 30.0
    rgba[..., 3] = 255.0

    center = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size]
    dx = xx - center
    dy = center - yy  # y up
    radius = np.hypot(dx, dy)
    angles = np.degrees(np.arctan2(dx, dy)) % 360.0
    ring_radius = size * 0.46

    ring_mask = np.abs(radius - ring_radius) <= 1.2
    _stamp(rgba, ring_mask, (0.63, 0.63, 0.63, 1.0))
    for cardinal in (0.0, 90.0, 180.0, 270.0):
        tick_mask = (
            (radius >= ring_radius - 10.0)
            & (radius <= ring_radius - 1.0)
            & (_angle_distance_deg(angles, cardinal) <= 3.0)
        )
        _stamp(rgba, tick_mask, (0.63, 0.63, 0.63, 1.0))

    def needle_mask(unit_xy: tuple[float, float], length: float, width: float) -> Any:
        ux, uy = unit_xy
        along = dx * ux + dy * uy
        t = np.clip(along, 0.0, length)
        return np.hypot(dx - t * ux, dy - t * uy) <= width

    for needle in view_model.needles:
        if needle.is_primary:
            continue
        mask = needle_mask(needle.unit_xy, ring_radius * 0.8, 1.0)
        mask &= (radius.astype(int) // 5) % 2 == 0
        _stamp(rgba, mask, event_color(needle.event_index))
    for needle in view_model.needles:
        if not needle.is_primary:
            continue
        mask = needle_mask(needle.unit_xy, ring_radius * 0.9, 1.6)
        _stamp(rgba, mask, event_color(needle.event_index))

    center_mask = radius <= 3.0
    _stamp(rgba, center_mask, (0.9, 0.9, 0.9, 1.0))
    return np.clip(np.rint(rgba), 0, 255).astype(np.uint8)
