"""High-level Isaac Sim-facing audio array sensor API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import AudioSensorConfig, build_scene_snapshot
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot


@dataclass(slots=True)
class IsaacAudioArraySensor:
    """Script-friendly sensor facade for Isaac Sim scenes."""

    array_id: str
    backend: str = "tdoa_synthetic"
    config: AudioSensorConfig | None = None
    stage_snapshot: AudioSceneSnapshot | None = None
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS
    ambiguity_policy: str = "none"

    @classmethod
    def from_stage(
        cls,
        *,
        stage: Any,
        array_prim_path: str,
        backend: str = "tdoa_synthetic",
        timestamp_ms: int = 0,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
    ) -> IsaacAudioArraySensor:
        """Create a sensor from a live or duck-typed static Isaac stage."""

        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=timestamp_ms,
            array_prim_path=array_prim_path,
        )
        if len(snapshot.arrays) != 1:
            raise ValueError(
                f"Expected exactly one array at {array_prim_path!r}, "
                f"found {len(snapshot.arrays)}."
            )
        return cls(
            array_id=snapshot.arrays[0].array_id,
            backend=backend,
            stage_snapshot=snapshot,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
        )

    @classmethod
    def from_config(
        cls,
        *,
        config: AudioSensorConfig,
        array_id: str,
        backend: str | None = None,
    ) -> IsaacAudioArraySensor:
        """Create an offline sensor facade from validated config."""

        if array_id not in config.arrays:
            raise KeyError(f"Unknown array id {array_id!r}.")
        return cls(
            array_id=array_id,
            backend=backend or config.default_backend,
            config=config,
            speed_of_sound_mps=config.speed_of_sound_mps,
            ambiguity_policy=config.tdoa_ambiguity_policy,
        )

    def capture(
        self,
        *,
        timestamp_ms: int,
        start_time_s: float = 0.0,
        end_time_s: float = 1.0,
        source_prim_path: str | None = None,
    ) -> AudioSensorFrame:
        """Capture one deterministic offline frame."""

        scene = self._scene_for_capture(
            timestamp_ms=timestamp_ms,
            source_prim_path=source_prim_path,
        )
        sensor = scene.array_by_id(self.array_id)
        time_window = AudioTimeWindow(
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            timestamp_ms=timestamp_ms,
            sample_rate_hz=sensor.sample_rate_hz,
            frame_index=0,
        )
        kwargs = {}
        if self.backend in {"tdoa_synthetic", "room_acoustics"}:
            kwargs = {
                "speed_of_sound_mps": self.speed_of_sound_mps,
                "ambiguity_policy": self.ambiguity_policy,
            }
        backend = get_backend(self.backend, **kwargs)
        return backend.simulate(scene, sensor, time_window)

    def _scene_for_capture(
        self,
        *,
        timestamp_ms: int,
        source_prim_path: str | None,
    ) -> AudioSceneSnapshot:
        if self.config is not None:
            scene = build_scene_snapshot(self.config, timestamp_ms=timestamp_ms)
        elif self.stage_snapshot is not None:
            scene = AudioSceneSnapshot(
                stage_id=self.stage_snapshot.stage_id,
                timestamp_ms=timestamp_ms,
                sources=self.stage_snapshot.sources,
                arrays=self.stage_snapshot.arrays,
                room=self.stage_snapshot.room,
            )
        else:
            raise RuntimeError("IsaacAudioArraySensor has no config or stage snapshot.")

        if source_prim_path is None:
            return scene
        sources = tuple(
            source for source in scene.sources if source.prim_path == source_prim_path
        )
        if not sources:
            raise ValueError(f"No source prim found at {source_prim_path!r}.")
        return AudioSceneSnapshot(
            stage_id=scene.stage_id,
            timestamp_ms=scene.timestamp_ms,
            sources=sources,
            arrays=scene.arrays,
            room=scene.room,
        )
