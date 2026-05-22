"""Generated-audio fixture metadata for examples."""

from __future__ import annotations


def generated_impulse_metadata(
    *,
    sample_rate_hz: int = 48_000,
    duration_s: float = 0.05,
) -> dict[str, object]:
    """Return metadata for deterministic generated impulse examples.

    The MVP does not package private recordings or large waveform artifacts.
    Examples refer to generated impulse or pulse assets instead.
    """

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
