"""Trace-oriented overlay records for manual Isaac review."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class BearingOverlayRecord:
    """Serializable description of a source-to-array or estimated bearing ray."""

    label: str
    start_world: tuple[float, float, float]
    bearing_deg: float | None
    confidence: float
    ambiguity_class: str | None = None
