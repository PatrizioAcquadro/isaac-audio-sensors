"""Bearing-sector mapping for a conventional eight-sector robot audio display."""

from __future__ import annotations

from isaac_audio_sensors.core.constants import SECTOR_ORDER
from isaac_audio_sensors.core.math_utils import normalize_bearing_deg


def bearing_deg_to_sector_name(deg: float) -> str:
    """Map a clockwise bearing angle into the canonical 8-sector name."""

    normalized = normalize_bearing_deg(deg)
    sector_index = int(((normalized + 22.5) % 360.0) // 45.0)
    return SECTOR_ORDER[sector_index]


def sector_bounds_deg(sector_name: str) -> tuple[float, float]:
    """Return the half-open bearing bounds for a sector name."""

    if sector_name not in SECTOR_ORDER:
        raise ValueError(f"Unknown bearing sector {sector_name!r}.")
    center = SECTOR_ORDER.index(sector_name) * 45.0
    return ((center - 22.5) % 360.0, (center + 22.5) % 360.0)
