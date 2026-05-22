"""Isaac Lab-style audio sensor wrapper with lazy Lab availability checks."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.exceptions import IsaacLabUnavailable
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
)
from isaac_audio_sensors.lab.audio_array_sensor_cfg import AudioArraySensorCfg
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData


def isaac_lab_available() -> bool:
    """Return whether an Isaac Lab package name is importable."""

    return _find_spec("isaaclab") or _find_spec("omni.isaac.lab")


def require_isaac_lab() -> None:
    """Raise a clear error outside Isaac Lab."""

    if not isaac_lab_available():
        raise IsaacLabUnavailable(
            "Isaac Lab is unavailable. Use this wrapper inside an Isaac Lab "
            "environment, or use the pure core/backends for offline tests."
        )


def _find_spec(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


@dataclass(slots=True)
class AudioArraySensor:
    """Small SensorBase-like facade for audio observations."""

    cfg: AudioArraySensorCfg
    sensor: MicrophoneArraySpec | None = None
    scene_snapshot: AudioSceneSnapshot | None = None
    data: AudioArraySensorData = AudioArraySensorData.empty()
    last_update_time_s: float | None = None

    @classmethod
    def from_lab_scene(
        cls,
        *,
        cfg: AudioArraySensorCfg,
        scene: object,
    ) -> AudioArraySensor:
        """Construct from Isaac Lab scene objects when Lab is available.

        The MVP expects the Lab scene or task wrapper to expose a prepared
        ``audio_scene_snapshot`` and ``audio_array_spec``. That keeps live Lab
        extraction explicit while preserving the same update/buffer semantics
        used by the pure core tests.
        """

        require_isaac_lab()
        scene_snapshot = getattr(scene, "audio_scene_snapshot", None)
        sensor = getattr(scene, "audio_array_spec", None)
        if not isinstance(scene_snapshot, AudioSceneSnapshot):
            raise ValueError(
                "scene must expose audio_scene_snapshot: AudioSceneSnapshot."
            )
        if not isinstance(sensor, MicrophoneArraySpec):
            raise ValueError("scene must expose audio_array_spec: MicrophoneArraySpec.")
        return cls(cfg=cfg, sensor=sensor, scene_snapshot=scene_snapshot)

    @classmethod
    def from_scene_snapshot(
        cls,
        *,
        cfg: AudioArraySensorCfg,
        scene_snapshot: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
    ) -> AudioArraySensor:
        """Construct a bound Lab-style sensor for offline tests and examples."""

        return cls(
            cfg=cfg,
            sensor=sensor,
            scene_snapshot=scene_snapshot,
        )

    def update(
        self,
        *,
        scene_snapshot: AudioSceneSnapshot | None = None,
        sensor: MicrophoneArraySpec | None = None,
        sim_time_s: float,
        timestamp_ms: int,
    ) -> AudioArraySensorData:
        """Refresh the buffer when ``update_period`` has elapsed."""

        if (
            self.last_update_time_s is not None
            and sim_time_s - self.last_update_time_s < self.cfg.update_period
        ):
            return self.data

        frame = self.capture_frame(
            scene_snapshot=scene_snapshot,
            sensor=sensor,
            timestamp_ms=timestamp_ms,
            start_time_s=sim_time_s,
            end_time_s=sim_time_s + max(self.cfg.update_period, 1e-3),
        )
        self.data = AudioArraySensorData.from_frame(frame)
        self.last_update_time_s = sim_time_s
        return self.data

    def capture_frame(
        self,
        *,
        scene_snapshot: AudioSceneSnapshot | None = None,
        sensor: MicrophoneArraySpec | None = None,
        timestamp_ms: int,
        start_time_s: float,
        end_time_s: float,
    ) -> AudioSensorFrame:
        """Capture one core frame through the configured backend."""

        scene_snapshot = self._resolve_scene_snapshot(scene_snapshot)
        sensor = self._resolve_sensor(sensor)
        kwargs = {}
        if self.cfg.backend in {"tdoa_synthetic", "room_acoustics"}:
            kwargs = {"ambiguity_policy": "none"}
        backend = get_backend(self.cfg.backend, **kwargs)
        return backend.simulate(
            scene_snapshot,
            sensor,
            AudioTimeWindow(
                start_time_s=start_time_s,
                end_time_s=end_time_s,
                timestamp_ms=timestamp_ms,
                sample_rate_hz=sensor.sample_rate_hz,
                frame_index=0,
            ),
        )

    def _resolve_scene_snapshot(
        self,
        scene_snapshot: AudioSceneSnapshot | None,
    ) -> AudioSceneSnapshot:
        resolved = scene_snapshot or self.scene_snapshot
        if resolved is None:
            raise ValueError(
                "scene_snapshot is required unless the sensor was constructed "
                "with from_scene_snapshot or from_lab_scene."
            )
        return resolved

    def _resolve_sensor(
        self,
        sensor: MicrophoneArraySpec | None,
    ) -> MicrophoneArraySpec:
        resolved = sensor or self.sensor
        if resolved is None:
            raise ValueError(
                "sensor is required unless the sensor was constructed with "
                "from_scene_snapshot or from_lab_scene."
            )
        return resolved
