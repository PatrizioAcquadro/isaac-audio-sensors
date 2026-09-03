"""Public microphone-signal assembly for analytic propagation."""

from __future__ import annotations

from isaac_audio_sensors.core.backends._analytic.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends._analytic.rendering import RenderedRoom
from isaac_audio_sensors.core.types import MicrophoneSignalBlock


def assemble_signal_block(
    prepared: PreparedRoomFrame,
    rendered: RenderedRoom,
    *,
    backend_id: str,
    solver_id: str,
    core_solver: bool,
) -> MicrophoneSignalBlock:
    """Project one private analytic render into the public signal boundary."""

    provider = "core" if core_solver else "pyroomacoustics"
    rendered_sample_count = int(rendered.mixture.shape[1])
    diagnostics: dict[str, object] = {
        "analytic_solver": {
            "solver_id": solver_id,
            "provider": provider,
            "provider_version": str(getattr(prepared.pra, "__version__", "unknown")),
            "environment_kind": prepared.scene.environment.kind,
        },
        "rendered_sample_count": rendered_sample_count,
        "tail_sample_count": max(
            0,
            rendered_sample_count - prepared.window_sample_count,
        ),
    }
    effect_stages = tuple(sorted(rendered.effect_diagnostics))
    if effect_stages:
        diagnostics["effect_stages"] = effect_stages
    if prepared.segments_per_window > 1:
        diagnostics["motion_segments"] = prepared.segments_per_window

    return MicrophoneSignalBlock(
        samples=rendered.mixture[:, : prepared.window_sample_count],
        microphone_ids=prepared.mic_ids,
        array_id=prepared.sensor.array_id,
        sample_rate_hz=prepared.sample_rate_hz,
        time_window=prepared.time_window,
        channel_validity=tuple(True for _ in prepared.mic_ids),
        producer_id=backend_id,
        provenance="synthetic/core" if core_solver else "room_acoustics",
        diagnostics=diagnostics,
    )


__all__ = ["assemble_signal_block"]
