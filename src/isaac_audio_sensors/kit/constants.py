"""Shared constants for the Isaac Audio Sensors extension GUI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.constants import TDOA_AMBIGUITY_POLICIES

BACKEND_CHOICES = registered_backend_ids()
AMBIGUITY_POLICY_CHOICES = tuple(sorted(TDOA_AMBIGUITY_POLICIES))
LAYOUT_CHOICES = (
    "quad_front",
    "quad_cross",
    "tetrahedral",
    "stereo_y",
    "two_mic_y",
    "mono",
)
WAVEFORM_MODE_CHOICES = ("per_frame", "session")
ROOM_OUT_OF_BOUNDS_CHOICES = ("error", "clamp")
# Default shoebox used by the room_acoustics backend when no anchor prim is
# designated; it is centered on the array at configure time since rooms no
# longer refit themselves to the scene.
DEFAULT_ROOM_ID = "ias_gui_default_room"
DEFAULT_ROOM_DIMENSIONS_M = (6.0, 6.0, 3.0)
DEFAULT_ROOM_ABSORPTION = 0.35
DEFAULT_ROOM_MAX_ORDER = 0
SOURCE_POSITION_PRESETS: Mapping[str, tuple[float, float, float]] = {
    "front": (2.0, 0.0, 0.0),
    "right": (0.0, 2.0, 0.0),
    "left": (0.0, -2.0, 0.0),
    "behind": (-2.0, 0.0, 0.0),
}
OUTPUT_ROOT_ENV_VAR = "ISAAC_AUDIO_SENSORS_OUTPUT_ROOT"
PROJECT_NAME = "isaac-audio-sensors"
DEFAULT_OUTPUT_ROOT = Path("outputs/isaac_audio_sensors")
DEFAULT_TRACE_FILENAME = "extension_trace.frames.jsonl"
DEFAULT_LATEST_FRAME_FILENAME = "extension_latest_frame.json"
DEFAULT_CONFIG_FILENAME = "extension_binding.json"
DEFAULT_REPLICATOR_DIRNAME = "replicator"
OMNI_WINDOW_TITLE = "Isaac Audio Sensors"
OMNI_MENU_GROUP = "Window"
OMNI_ACTION_TOGGLE_WINDOW = "toggle_window"
OMNI_DEFAULT_HOTKEY = "CTRL + ALT + A"
OMNI_DEFAULT_HOTKEY_DISPLAY = "Ctrl+Alt+A"
