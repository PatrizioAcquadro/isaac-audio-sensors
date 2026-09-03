"""Shared constants for the Isaac Audio Sensors extension GUI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.directivity import DirectivityPattern

BACKEND_CHOICES = registered_backend_ids()
DIRECTIVITY_CHOICES = tuple(pattern.value for pattern in DirectivityPattern)
LAYOUT_CHOICES = (
    "quad_front",
    "quad_cross",
    "tetrahedral",
    "stereo_y",
    "two_mic_y",
    "mono",
)
WAVEFORM_MODE_CHOICES = ("per_frame", "session")
ENVIRONMENT_MODE_CHOICES = (
    "unconfigured",
    "manual_free_field",
    "anchor",
    "auto",
)
DEFAULT_FREE_FIELD_ENVIRONMENT_ID = "ias_kit_free_field"
SOURCE_POSITION_PRESETS: Mapping[str, tuple[float, float, float]] = {
    "front": (2.0, 0.0, 0.0),
    "right": (0.0, 2.0, 0.0),
    "left": (0.0, -2.0, 0.0),
    "behind": (-2.0, 0.0, 0.0),
}
OUTPUT_ROOT_ENV_VAR = "ISAAC_AUDIO_SENSORS_OUTPUT_ROOT"
PROJECT_NAME = "isaac-audio-sensors"
DEFAULT_OUTPUT_ROOT = Path("build/validation/isaac_audio_sensors")
DEFAULT_TRACE_FILENAME = "extension_trace.frames.jsonl"
DEFAULT_LATEST_FRAME_FILENAME = "extension_latest_frame.json"
DEFAULT_CONFIG_FILENAME = "extension_binding.json"
DEFAULT_REPLICATOR_DIRNAME = "replicator"
DEFAULT_KIT_AUDIO_CAPTURE_DIRNAME = "kit_audio_captures"
KIT_AUDIO_MIX_LABEL = (
    "Kit listener/device mix — qualitative, not microphone-array channels"
)
OMNI_WINDOW_TITLE = "Isaac Audio Sensors"
OMNI_MENU_GROUP = "Window"
OMNI_ACTION_TOGGLE_WINDOW = "toggle_window"
OMNI_DEFAULT_HOTKEY = "CTRL + ALT + A"
OMNI_DEFAULT_HOTKEY_DISPLAY = "Ctrl+Alt+A"
GUIDED_COLLAPSED_SETTING = (
    "/persistent/exts/isaac_audio_sensors.omni/ui/guided_collapsed"
)
