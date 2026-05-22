"""Omniverse extension workflow for isaac_audio_sensors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.io.traces import write_frame_trace
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor


class Extension:
    """Kit extension entrypoint with lazy UI construction."""

    def on_startup(self, ext_id: str) -> None:
        self.ext_id = ext_id
        self.sensor: IsaacAudioArraySensor | None = None
        self.window: Any | None = None
        self.ui_available = False
        self.array_prim_path = "/World/Rig/AudioArray"
        self.backend = "tdoa_synthetic"
        self.update_period_s = 0.05
        self.max_events = 8
        self.debug_draw = True
        self.latest_frame_export_path = "outputs/isaac_audio_sensors/latest_frame.json"
        self._build_ui_if_available()

    def on_shutdown(self) -> None:
        if self.sensor is not None:
            self.sensor.close()
        self.sensor = None
        self.window = None
        self.ext_id = None

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
    ) -> IsaacAudioArraySensor:
        """Create or replace the live sensor for the current Isaac stage."""

        if self.sensor is not None:
            self.sensor.close()
        self.sensor = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=array_prim_path or self.array_prim_path,
            backend=backend or self.backend,
            update_period_s=update_period_s or self.update_period_s,
            max_events=self.max_events if max_events is None else max_events,
            debug_draw=self.debug_draw if debug_draw is None else debug_draw,
            writer_path=writer_path,
        )
        return self.sensor

    def start_sensor(self) -> None:
        """Start the configured sensor."""

        if self.sensor is not None:
            self.sensor.start(subscribe_to_update_stream=True)

    def stop_sensor(self) -> None:
        """Stop the configured sensor."""

        if self.sensor is not None:
            self.sensor.stop()

    def update_sensor(self, *, force: bool = True) -> None:
        """Manually capture one frame from the configured sensor."""

        if self.sensor is not None:
            self.sensor.update(force=force)

    def export_latest_frame(self, path: str | Path | None = None) -> Path | None:
        """Write the latest frame as JSON when one is available."""

        if self.sensor is None or self.sensor.latest_frame is None:
            return None
        return write_frame_trace(
            self.sensor.latest_frame,
            path or self.latest_frame_export_path,
        )

    def _build_ui_if_available(self) -> None:
        try:
            import omni.ui as ui  # type: ignore
        except ImportError:
            return
        self.ui_available = True
        self.window = ui.Window("Isaac Audio Sensors", width=380, height=260)
        with self.window.frame, ui.VStack(spacing=6):
            ui.Label("Audio array sensor")
            self._array_field = ui.StringField()
            self._array_field.model.set_value(self.array_prim_path)
            self._backend_field = ui.StringField()
            self._backend_field.model.set_value(self.backend)
            self._period_field = ui.FloatDrag()
            self._period_field.model.set_value(self.update_period_s)
            self._max_events_field = ui.IntDrag()
            self._max_events_field.model.set_value(self.max_events)
            self._debug_checkbox = ui.CheckBox()
            self._debug_checkbox.model.set_value(self.debug_draw)
            ui.Button("Start", clicked_fn=self.start_sensor)
            ui.Button("Stop", clicked_fn=self.stop_sensor)
            ui.Button("Update", clicked_fn=self.update_sensor)
            ui.Button("Export Latest", clicked_fn=self.export_latest_frame)
