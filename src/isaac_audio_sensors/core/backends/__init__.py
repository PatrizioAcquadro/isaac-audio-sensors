"""Simulation backend registry."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.base import (
    AudioSimulationBackend,
    get_backend,
)
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend

__all__ = [
    "AudioSimulationBackend",
    "GeometryBackend",
    "RoomAcousticsBackend",
    "TdoaSyntheticBackend",
    "get_backend",
]
