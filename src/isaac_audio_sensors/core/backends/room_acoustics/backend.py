"""Room-acoustics scene-to-frame backend orchestration."""

from __future__ import annotations

import importlib
import math
from typing import Any

from isaac_audio_sensors.core.backends.room_acoustics.assembly import assemble_frame
from isaac_audio_sensors.core.backends.room_acoustics.detections import (
    assemble_detections,
)
from isaac_audio_sensors.core.backends.room_acoustics.preparation import (
    prepare_room_frame,
)
from isaac_audio_sensors.core.backends.room_acoustics.rendering import (
    _import_pyroomacoustics,
    apply_room_effects,
    render_room,
)
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.motion import WindowMotionPlan
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
)

DOA_ESTIMATOR_IDS = ("tdoa_least_squares", "srp_phat")


class RoomAcousticsBackend:
    """Optional shoebox-room backend using pyroomacoustics and GCC-PHAT.

    All active sources share one room per frame, so microphone signals are
    true mixtures; per-source diagnostics come from the simulation premix.
    """

    backend_id = "room_acoustics"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        gcc_phat_interp: int = 8,
        waveform_writer: WaveformSink | None = None,
        doa_estimator: str = "tdoa_least_squares",
        max_order: int = 0,
        air_absorption: bool = False,
        ray_tracing: bool = False,
        effects: EffectsConfig | None = None,
        runtime_profile: str = "waveform_fidelity",
        window_motion: WindowMotionPlan | None = None,
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if doa_estimator not in DOA_ESTIMATOR_IDS:
            raise ValueError(
                f"doa_estimator must be one of {sorted(DOA_ESTIMATOR_IDS)}."
            )
        if isinstance(max_order, bool) or not isinstance(max_order, int):
            raise TypeError("max_order must be an integer.")
        if max_order < 0:
            raise ValueError("max_order must be non-negative.")
        if not isinstance(air_absorption, bool):
            raise TypeError("air_absorption must be a boolean.")
        if not isinstance(ray_tracing, bool):
            raise TypeError("ray_tracing must be a boolean.")
        _import_pyroomacoustics()
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
        self.gcc_phat_interp = int(gcc_phat_interp)
        self.waveform_writer = waveform_writer
        self.doa_estimator = doa_estimator
        self.max_order = max_order
        self.air_absorption = air_absorption
        self.ray_tracing = ray_tracing
        self.effects = EffectsConfig() if effects is None else effects
        self.runtime_profile = runtime_profile
        self.window_motion = window_motion
        self.effects_chain = ChannelEffectsChain(self.effects)

    @staticmethod
    def is_available() -> bool:
        """Return whether the optional pyroomacoustics dependency imports."""

        try:
            importlib.import_module("pyroomacoustics")
        except ImportError:
            return False
        return True

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        array_id: str,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        sensor = scene.array_by_id(array_id)
        prepared = prepare_room_frame(
            scene,
            sensor,
            time_window,
            backend_id=self.backend_id,
            effects=self.effects,
            runtime_profile=self.runtime_profile,
            max_order=self.max_order,
            air_absorption=self.air_absorption,
            ray_tracing=self.ray_tracing,
            window_motion=self.window_motion,
            import_pyroomacoustics=_import_pyroomacoustics,
        )
        rendered = render_room(
            prepared,
            effects=self.effects,
            speed_of_sound_mps=self.speed_of_sound_mps,
            window_motion=self.window_motion,
        )
        apply_room_effects(
            prepared,
            rendered,
            effects=self.effects,
            effects_chain=self.effects_chain,
            backend_id=self.backend_id,
            runtime_profile=self.runtime_profile,
        )
        detections, per_source_rir_summary = assemble_detections(
            prepared,
            rendered,
            backend_id=self.backend_id,
            speed_of_sound_mps=self.speed_of_sound_mps,
            ambiguity_policy=self.ambiguity_policy,
            gcc_phat_interp=self.gcc_phat_interp,
            doa_estimator=self.doa_estimator,
        )
        return assemble_frame(
            prepared,
            rendered,
            detections,
            per_source_rir_summary,
            backend_id=self.backend_id,
            speed_of_sound_mps=self.speed_of_sound_mps,
            ambiguity_policy=self.ambiguity_policy,
            doa_estimator=self.doa_estimator,
            waveform_writer=self.waveform_writer,
            window_motion=self.window_motion,
        )


class RoomAcousticsSrpBackend(RoomAcousticsBackend):
    """Room-acoustics backend variant with SRP-PHAT as the DOA estimator.

    Emits the same L2 frames as ``room_acoustics`` (shared room, premix
    diagnostics, waveform export) with the direction estimate steered over
    the SRP-PHAT grid instead of the GCC-PHAT least-squares path.
    """

    backend_id = "room_acoustics_srp"

    def __init__(self, **kwargs: Any) -> None:
        estimator = kwargs.setdefault("doa_estimator", "srp_phat")
        if estimator != "srp_phat":
            raise ValueError("room_acoustics_srp pins doa_estimator='srp_phat'.")
        super().__init__(**kwargs)


__all__ = ["RoomAcousticsBackend", "RoomAcousticsSrpBackend"]
