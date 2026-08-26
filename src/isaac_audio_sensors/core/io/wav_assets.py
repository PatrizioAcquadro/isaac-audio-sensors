"""Generated-audio metadata."""

from __future__ import annotations


def generated_impulse_metadata(
    *,
    sample_rate_hz: int = 48_000,
    duration_s: float = 0.05,
) -> dict[str, object]:
    """Return metadata for a deterministic generated impulse."""

    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    if duration_s <= 0.0:
        raise ValueError("duration_s must be positive.")
    return {
        "asset_uri": "generated://impulse",
        "sample_rate_hz": sample_rate_hz,
        "duration_s": duration_s,
        "private_recording": False,
    }
