"""Simulation backend registry."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.backends.base import get_backend, registered_backend_ids
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend

__all__ = [
    "AnalyticAcoustics",
    "GeometryBackend",
    "RoomAcousticsBackend",
    "RoomAcousticsSrpBackend",
    "TdoaSyntheticBackend",
    "get_backend",
    "registered_backend_ids",
]
