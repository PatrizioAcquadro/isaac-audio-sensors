"""Pure view-models and rasters for the GUI instruments.

Everything in this module is plain Python + numpy so the compass, per-mic
meters, and observation timeline can be unit-tested without ``omni.ui``. The
window layer maps these view-models onto widgets and degrades to text labels
when a widget class is unavailable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from isaac_audio_sensors.core.constants import SECTOR_ORDER

OBSERVATION_HISTORY_LIMIT = 50
RMS_METER_FLOOR_DB = -60.0
MIC_DISPLAY_ORDER = {"front": 0, "right": 1, "rear": 2, "left": 3}
COMPASS_IMAGE_SIZE = 192
METER_MAX_ROWS = 8
TIMELINE_MAX_ROWS = 12

# Matches the bearing-ray colors used by ``isaac.viz.overlays``.
COLOR_CLEAR = (0.05, 0.9, 0.35, 1.0)
COLOR_OCCLUDED = (0.95, 0.15, 0.1, 1.0)
COLOR_UNKNOWN = (0.65, 0.65, 0.65, 1.0)

_SECTOR_CENTER_DEG = {name: index * 45.0 for index, name in enumerate(SECTOR_ORDER)}


@dataclass(frozen=True, slots=True, kw_only=True)
class CompassNeedle:
    """One bearing needle in widget space (x right, y up, 0 deg = up)."""

    bearing_deg: float
    unit_xy: tuple[float, float]
    is_primary: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CompassViewModel:
    """Everything needed to draw the polar bearing compass."""

    needles: tuple[CompassNeedle, ...]
    sector: str | None
    sector_center_deg: float | None
    confidence: float
    occluded: bool | None
    color_rgba: tuple[float, float, float, float]
    summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MeterViewModel:
    """One per-microphone RMS meter row."""

    mic_id: str
    rms_linear: float
    db: float | None
    fraction: float
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineRow:
    """One rendered observation-timeline row (newest first)."""

    text: str
    occluded: bool


def compass_unit_xy(bearing_deg: float) -> tuple[float, float]:
    """Map a clockwise-from-forward bearing to widget space (0 deg = up)."""

    radians = math.radians(bearing_deg)
    return (math.sin(radians), math.cos(radians))


def compass_view_model(
    *,
    bearing_deg: float | None,
    candidate_bearings: Sequence[float] = (),
    sector: str | None = None,
    confidence: float | None = None,
    occluded: bool | None = None,
) -> CompassViewModel:
    """Build the compass view-model for the latest frame."""

    needles: list[CompassNeedle] = []
    if bearing_deg is not None and math.isfinite(float(bearing_deg)):
        primary = float(bearing_deg) % 360.0
        needles.append(
            CompassNeedle(
                bearing_deg=primary,
                unit_xy=compass_unit_xy(primary),
                is_primary=True,
            )
        )
        for candidate in candidate_bearings:
            value = float(candidate) % 360.0
            if math.isclose(value, primary, abs_tol=1e-6):
                continue
            needles.append(
                CompassNeedle(
                    bearing_deg=value,
                    unit_xy=compass_unit_xy(value),
                    is_primary=False,
                )
            )
    if occluded is True:
        color = COLOR_OCCLUDED
    elif occluded is False and needles:
        color = COLOR_CLEAR
    else:
        color = COLOR_UNKNOWN
    clamped_confidence = min(max(float(confidence or 0.0), 0.0), 1.0)
    if occluded is True:
        occlusion_text = "occluded"
    elif occluded is False:
        occlusion_text = "clear"
    else:
        occlusion_text = "occlusion unknown"
    if needles:
        summary = (
            f"bearing {needles[0].bearing_deg:.1f} deg"
            f" | sector {sector or 'none'}"
            f" | confidence {clamped_confidence:.2f}"
            f" | {occlusion_text}"
        )
    else:
        summary = "no bearing"
    return CompassViewModel(
        needles=tuple(needles),
        sector=sector,
        sector_center_deg=_SECTOR_CENTER_DEG.get(sector or ""),
        confidence=clamped_confidence,
        occluded=occluded,
        color_rgba=color,
        summary=summary,
    )


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
    for observation in getattr(frame, "observations", ()) or ():
        doa = getattr(observation, "doa", None)
        origin = getattr(observation, "origin", None)
        events.append(
            {
                "frame_id": frame_id,
                "producer_id": producer_id,
                "timestamp_ms": timestamp_ms,
                "observation_id": getattr(observation, "observation_id", None),
                "origin": getattr(origin, "value", origin),
                "detector_id": getattr(observation, "detector_id", None),
                "detection_score": getattr(
                    observation, "detection_score", None
                ),
                "bearing_deg": getattr(doa, "estimated_bearing_deg", None),
                "sector": getattr(doa, "bearing_sector", None),
                "confidence": getattr(doa, "bearing_confidence", None),
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
) -> tuple[TimelineRow, ...]:
    """Render the most recent observation events, newest first."""

    rows: list[TimelineRow] = []
    for event in reversed(history[-int(max_rows) :]):
        timestamp_ms = event.get("timestamp_ms")
        time_text = (
            f"{float(timestamp_ms) / 1000.0:8.2f}s"
            if isinstance(timestamp_ms, (int, float))
            else "       ?"
        )
        source = event.get("detector_id") or event.get("origin") or "unknown"
        bearing = event.get("bearing_deg")
        bearing_text = (
            f"{float(bearing):6.1f} deg"
            if isinstance(bearing, (int, float))
            else "ambiguous"
        )
        occluded = False
        sector = event.get("sector") or "none"
        rows.append(
            TimelineRow(
                text=f"{time_text}  {source}  {bearing_text}  {sector}",
                occluded=occluded,
            )
        )
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

    if view_model.sector_center_deg is not None:
        sector_mask = (radius <= ring_radius - 2.0) & (
            _angle_distance_deg(angles, view_model.sector_center_deg) <= 22.5
        )
        sector_color = (*view_model.color_rgba[:3], 0.25)
        _stamp(rgba, sector_mask, sector_color)

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
        _stamp(rgba, mask, (*view_model.color_rgba[:3], 0.45))
    for needle in view_model.needles:
        if not needle.is_primary:
            continue
        mask = needle_mask(needle.unit_xy, ring_radius * 0.9, 1.6)
        _stamp(rgba, mask, view_model.color_rgba)

    center_mask = radius <= 3.0
    _stamp(rgba, center_mask, (0.9, 0.9, 0.9, 1.0))
    return np.clip(np.rint(rgba), 0, 255).astype(np.uint8)
