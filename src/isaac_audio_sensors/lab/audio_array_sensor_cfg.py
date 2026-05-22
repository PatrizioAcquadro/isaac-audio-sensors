"""Isaac Lab-style sensor config."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioArraySensorCfg:
    """Config object that mirrors Isaac Lab sensor configuration patterns."""

    prim_path: str
    update_period: float = 0.0
    backend: str = "tdoa_synthetic"
    microphone_layout: str = "quad_front"
    sample_rate_hz: int = 48_000
    debug_vis: bool = False
    write_waveforms: bool = False

    def __post_init__(self) -> None:
        if self.prim_path.strip() == "":
            raise ValueError("AudioArraySensorCfg.prim_path must be non-empty.")
        if self.update_period < 0.0:
            raise ValueError("AudioArraySensorCfg.update_period must be non-negative.")
        if self.sample_rate_hz <= 0:
            raise ValueError("AudioArraySensorCfg.sample_rate_hz must be positive.")
        if self.backend not in {"geometry_only", "tdoa_synthetic", "room_acoustics"}:
            raise ValueError("AudioArraySensorCfg.backend is unknown.")
        if self.microphone_layout.strip() == "":
            raise ValueError("AudioArraySensorCfg.microphone_layout must be non-empty.")
