"""Public microphone-signal assembly for analytic propagation."""

from __future__ import annotations

from isaac_audio_sensors.core.backends._analytic.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends._analytic.rendering import RenderedRoom
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.types import MicrophoneSignalBlock


def assemble_signal_block(
    prepared: PreparedRoomFrame,
    rendered: RenderedRoom,
    *,
    backend_id: str,
    solver_id: str,
    core_solver: bool,
    effects: EffectsConfig,
) -> MicrophoneSignalBlock:
    """Project one private analytic render into the public signal boundary."""

    provider = "core" if core_solver else "pyroomacoustics"
    diagnostics: dict[str, object] = {
        "acquisition": {
            "clock_drift_ppm": {
                mic_id: float((effects.noise.clock_drift_ppm or {}).get(mic_id, 0.0))
                if effects.noise.enabled
                else 0.0
                for mic_id in prepared.mic_ids
            },
            "clock_drift_status": "configured",
            "buffer_latency_s": None,
            "nominal_gain_db": {
                mic.mic_id: mic.gain_db for mic in prepared.sensor.microphones
            },
            "calibration": None,
            "applied_corrections": rendered.effect_diagnostics.get(
                "channel_response", {}
            ),
        },
        "analytic_solver": {
            "solver_id": solver_id,
            "provider": provider,
            "provider_version": str(getattr(prepared.pra, "__version__", "unknown")),
            "environment_kind": prepared.scene.environment.kind,
        },
    }
    effect_stages = tuple(sorted(rendered.effect_diagnostics))
    if effect_stages:
        diagnostics["effect_stages"] = effect_stages
    if prepared.segments_per_window > 1:
        diagnostics["motion_segments"] = prepared.segments_per_window

    electronics = rendered.effect_diagnostics.get("electronics")
    clipping = (
        tuple(electronics["observed_channel_clipping"][mic] for mic in prepared.mic_ids)
        if electronics is not None
        else tuple(False for _ in prepared.mic_ids)
    )
    return MicrophoneSignalBlock(
        samples=rendered.mixture[:, : prepared.window_sample_count],
        microphone_ids=prepared.mic_ids,
        microphone_positions_m=tuple(
            mic.relative_position_m for mic in prepared.sensor.microphones
        ),
        array_id=prepared.sensor.array_id,
        sample_rate_hz=prepared.sample_rate_hz,
        time_window=prepared.time_window,
        clock_domain=f"simulation:{prepared.scene.stage_id}",
        discontinuity=False,
        channel_clipping=clipping,
        channel_validity=tuple(True for _ in prepared.mic_ids),
        producer_id=backend_id,
        provenance="synthetic/core" if core_solver else "room_acoustics",
        diagnostics=diagnostics,
    )


__all__ = ["assemble_signal_block"]
