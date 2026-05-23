"""Omniverse extension entrypoint for isaac_audio_sensors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.extension_ui import ExtensionController


def _i_ext_base() -> type:
    try:
        import omni.ext as omni_ext  # type: ignore
    except ImportError:
        return object
    return omni_ext.IExt


class Extension(_i_ext_base()):
    """Kit extension entrypoint backed by an import-safe controller."""

    def __init__(self) -> None:
        self.controller = ExtensionController()

    def on_startup(self, ext_id: str) -> None:
        """Kit startup hook."""

        self.controller.on_startup(ext_id)

    def on_shutdown(self) -> None:
        """Kit shutdown hook."""

        self.controller.on_shutdown()

    def configure_sensor(
        self,
        *,
        stage: Any,
        array_prim_path: str | None = None,
        backend: str | None = None,
        update_period_s: float | None = None,
        max_events: int | None = None,
        debug_draw: bool | None = None,
        writer_path: str | Path | None = None,
    ) -> IsaacAudioArraySensor | None:
        """Create or replace the live sensor for the current Isaac stage."""

        return self.controller.configure_sensor(
            stage=stage,
            array_prim_path=array_prim_path,
            backend=backend,
            update_period_s=update_period_s,
            max_events=max_events,
            debug_draw=debug_draw,
            writer_path=writer_path,
        )

    def start_sensor(self) -> IsaacAudioArraySensor | None:
        """Start the configured sensor."""

        return self.controller.start_sensor()

    def stop_sensor(self) -> None:
        """Stop the configured sensor."""

        self.controller.stop_sensor()

    def update_sensor(self, *, force: bool = True) -> Any | None:
        """Manually capture one frame from the configured sensor."""

        return self.controller.update_sensor(force=force)

    def export_latest_frame(self, path: str | Path | None = None) -> Path | None:
        """Write the latest frame as JSON when one is available."""

        return self.controller.export_latest_frame(path)

    def export_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Write a reusable extension config/stage-binding summary."""

        return self.controller.export_config_summary(path)

    @property
    def sensor(self) -> IsaacAudioArraySensor | None:
        """Return the active live sensor, if any."""

        return self.controller.sensor

    @sensor.setter
    def sensor(self, value: IsaacAudioArraySensor | None) -> None:
        self.controller.sensor = value

    @property
    def window(self) -> Any | None:
        """Return the Kit window, if UI construction succeeded."""

        return self.controller.window

    @property
    def ui_available(self) -> bool:
        """Return whether the UI was built in this process."""

        return self.controller.ui_available

    @property
    def array_prim_path(self) -> str:
        return self.controller.state.array_prim_path

    @array_prim_path.setter
    def array_prim_path(self, value: str) -> None:
        self.controller.state.array_prim_path = value

    @property
    def backend(self) -> str:
        return self.controller.state.backend

    @backend.setter
    def backend(self, value: str) -> None:
        self.controller.state.backend = value

    @property
    def update_period_s(self) -> float:
        return self.controller.state.update_period_s

    @update_period_s.setter
    def update_period_s(self, value: float) -> None:
        self.controller.state.update_period_s = float(value)

    @property
    def max_events(self) -> int:
        return self.controller.state.max_events

    @max_events.setter
    def max_events(self, value: int) -> None:
        self.controller.state.max_events = int(value)

    @property
    def debug_draw(self) -> bool:
        return self.controller.state.debug_overlay_enabled

    @debug_draw.setter
    def debug_draw(self, value: bool) -> None:
        self.controller.state.debug_overlay_enabled = bool(value)

    @property
    def latest_frame_export_path(self) -> str:
        return self.controller.state.latest_frame_export_path

    @latest_frame_export_path.setter
    def latest_frame_export_path(self, value: str) -> None:
        self.controller.state.latest_frame_export_path = value


__all__ = ["Extension"]
