"""Thin Omniverse extension wrapper for isaac_audio_sensors."""

from __future__ import annotations


class Extension:
    """Minimal Kit extension entrypoint."""

    def on_startup(self, ext_id: str) -> None:
        self.ext_id = ext_id

    def on_shutdown(self) -> None:
        self.ext_id = None
