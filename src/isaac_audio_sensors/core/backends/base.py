"""Backend interface and registry."""

from __future__ import annotations

from typing import Protocol

from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
)


class AudioSimulationBackend(Protocol):
    """Simulation backend interface shared by all layers."""

    backend_id: str

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        """Simulate one array observation frame."""


def get_backend(backend_id: str, **kwargs: object) -> AudioSimulationBackend:
    """Instantiate a backend by public id."""

    if backend_id == "geometry_only":
        from isaac_audio_sensors.core.backends.geometry import GeometryBackend

        return GeometryBackend(**kwargs)
    if backend_id == "tdoa_synthetic":
        from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend

        return TdoaSyntheticBackend(**kwargs)
    if backend_id == "room_acoustics":
        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )

        return RoomAcousticsBackend(**kwargs)
    if backend_id == "room_acoustics_srp":
        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsSrpBackend,
        )

        return RoomAcousticsSrpBackend(**kwargs)
    raise ValueError(f"Unknown audio simulation backend {backend_id!r}.")
