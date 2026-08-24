"""``omni.ui`` window adapter for ``ExtensionUiState``."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any

from .constants import GUIDED_COLLAPSED_SETTING, OMNI_WINDOW_TITLE
from .formatting import (
    _format_mic_positions_summary,
    _format_vec3,
    _optional_quat_text,
    _optional_vec3_text,
    _profile_summary_text,
    _rig_profile_summary_text,
    _summary_ids,
)
from .instruments import (
    COMPASS_IMAGE_SIZE,
    compass_view_model,
    meter_view_models,
    render_compass_rgba,
    timeline_rows,
)
from .sections import (
    build_advanced_section,
    build_guided_section,
    build_live_monitor_section,
)
from .spectro import render_spectrogram_rgba, render_waveform_rgba
from .ui_models import (
    _combo_index,
    _get_bool_setting,
    _model_bool,
    _model_float,
    _model_int,
    _model_string,
    _new_simple_model,
    _set_bool_setting,
    _set_combo_index,
    _set_model_value,
    _set_widget_text,
    _set_window_visibility_changed_fn,
    _set_window_visible,
    _ui_fraction,
)

if TYPE_CHECKING:
    from .controller import ExtensionController


_FIELD_STYLES = {
    "editable": {
        "background_color": 0xFF24211F,
        "border_color": 0xFF4A4541,
        "border_width": 1,
    },
    "auto": {
        "background_color": 0xFF302A24,
        "border_color": 0xFFD2782E,
        "border_width": 1,
    },
    "invalid": {
        "background_color": 0xFF302020,
        "border_color": 0xFF616AEF,
        "border_width": 1,
    },
}
_READ_ONLY_STYLE = {
    "background_color": 0xFF262422,
    "color": 0xFFAAA6A2,
    "margin": 4,
}
_STATUS_COLORS = {
    "ERROR": 0xFF616AEF,
    "RECORDING": 0xFF65A5EA,
    "WARNING": 0xFF5BB9E4,
    "ACTIVE": 0xFF8CC14F,
    "READY": 0xFFAAA6A2,
}


@dataclass(frozen=True, slots=True)
class _UiDiagnostic:
    section: str
    field: str
    message: str
    recovery: str


class _UiFieldInputError(ValueError):
    def __init__(
        self,
        *,
        attr_name: str,
        section: str,
        label: str,
        message: str,
        recovery: str,
    ) -> None:
        super().__init__(message)
        self.attr_name = attr_name
        self.section = section
        self.label = label
        self.recovery = recovery


class OmniReferenceWindow:
    """Small adapter from ``ExtensionUiState`` to ``omni.ui`` widgets."""

    def __init__(
        self,
        controller: ExtensionController,
        ui: Any,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.controller = controller
        self.ui = ui
        self._clock = clock or monotonic
        self.window: Any | None = None
        self._string_fields: dict[str, Any] = {}
        self._float_fields: dict[str, Any] = {}
        self._int_fields: dict[str, Any] = {}
        self._bool_fields: dict[str, Any] = {}
        self._combo_fields: dict[str, tuple[Any, tuple[str, ...]]] = {}
        self._labels: dict[str, Any] = {}
        self._model_change_subscriptions: list[Any] = []
        self._sections: list[str] = []
        self._section_frames: dict[str, Any] = {}
        self._buttons: list[str] = []
        self._instruments: dict[str, Any] = {}
        self._audio_panel: dict[str, Any] = {}
        self._active_section = ""
        self._active_subsection = ""
        self._field_metadata: dict[str, tuple[str, str]] = {}
        self._auto_filled_fields: set[str] = set()
        self._invalid_field: str | None = None
        self._diagnostic: _UiDiagnostic | None = None
        self._pushing_state = False
        self._last_frame_key: tuple[str, int | None] | None = None
        self._last_frame_received_s: float | None = None

    def build(self) -> Any:
        """Build a compact task-oriented Kit window."""

        ui = self.ui
        self.window = ui.Window(OMNI_WINDOW_TITLE, width=680, height=740)
        _set_window_visibility_changed_fn(
            self.window,
            self.controller.handle_window_visibility_changed,
        )
        with self.window.frame, ui.VStack(spacing=6):
            scrolling_frame = getattr(ui, "ScrollingFrame", None)
            if scrolling_frame is None:
                with ui.VStack(spacing=6, height=0):
                    self._build_body()
            else:
                with scrolling_frame(
                    height=_ui_fraction(ui, 1)
                ), ui.VStack(spacing=6, height=0):
                    self._build_body()
            with ui.HStack(spacing=8, height=32):
                self._labels["status_icon"] = ui.Label("READY", width=82)
                self._labels["status"] = ui.Label(
                    self.controller.state.status_message,
                    word_wrap=True,
                )
        self.refresh_labels()
        return self.window

    def close(self) -> None:
        """Detach callbacks and release widget references."""

        self.controller.detach_window_callbacks()
        for subscription in self._model_change_subscriptions:
            for method_name in ("unsubscribe", "revoke"):
                method = getattr(subscription, method_name, None)
                if callable(method):
                    with suppress(Exception):
                        method()
                    break
        self._model_change_subscriptions.clear()
        if self.window is not None:
            _set_window_visibility_changed_fn(self.window, None)
            _set_window_visible(self.window, False)
            destroy = getattr(self.window, "destroy", None)
            if callable(destroy):
                with suppress(Exception):
                    destroy()
        self.window = None
        self._string_fields.clear()
        self._float_fields.clear()
        self._int_fields.clear()
        self._bool_fields.clear()
        self._combo_fields.clear()
        self._labels.clear()
        self._section_frames.clear()
        self._instruments.clear()
        self._audio_panel.clear()
        self._field_metadata.clear()
        self._auto_filled_fields.clear()
        self._invalid_field = None
        self._diagnostic = None
        self._last_frame_key = None
        self._last_frame_received_s = None

    def _build_body(self) -> None:
        if self.controller.state.guided_mode_enabled:
            with self._section(
                "Guided Workflow",
                collapsed=_get_bool_setting(GUIDED_COLLAPSED_SETTING, False),
                on_collapsed_changed=self._guided_collapsed_changed,
            ):
                build_guided_section(self)
        with self._section("Live Monitor", collapsed=False):
            build_live_monitor_section(self)
        with self._section(
            "Advanced Tools",
            collapsed=True,
            on_collapsed_changed=self._advanced_collapsed_changed,
        ):
            build_advanced_section(self)

    def _guided_collapsed_changed(self, collapsed: bool) -> None:
        _set_bool_setting(GUIDED_COLLAPSED_SETTING, collapsed)
        if not collapsed:
            self._set_section_collapsed("Advanced Tools", True)

    def _advanced_collapsed_changed(self, collapsed: bool) -> None:
        if not collapsed:
            self._set_section_collapsed("Guided Workflow", True)

    def _set_section_collapsed(self, title: str, collapsed: bool) -> None:
        frame = self._section_frames.get(title)
        if frame is None or not hasattr(frame, "collapsed"):
            return
        with suppress(Exception):
            frame.collapsed = collapsed

    def refresh_labels(self) -> None:
        """Push current state summaries to visible labels."""

        state = self.controller.state
        self._refresh_frame_receipt()
        source_offset = (
            state.source_local_offset_x_m,
            state.source_local_offset_y_m,
            state.source_local_offset_z_m,
        )
        self._set_label("stage", state.stage_status)
        self._set_label(
            "discovery",
            f"Arrays: {_summary_ids(state.discovered_arrays)} | "
            f"Sources: {_summary_ids(state.discovered_sources)} | "
            f"Objects: {_summary_ids(state.discovered_objects)}",
        )
        self._set_label(
            "object",
            "Object: "
            f"{state.object_label or 'none'} | "
            f"path={state.object_prim_path or 'none'} | "
            f"attached={state.source_attached_to_object} | "
            f"offset={_format_vec3(source_offset)}",
        )
        self._set_label("profile", _profile_summary_text(state))
        self._set_label("rig_profile", _rig_profile_summary_text(state))
        self._set_label(
            "array_latest",
            "Array: "
            f"{state.latest_array_prim_path or state.array_prim_path} | "
            f"pos={_optional_vec3_text(state.latest_array_position_m)} | "
            f"quat={_optional_quat_text(state.latest_array_orientation_xyzw)} | "
            f"attached={state.array_attached_to_object} | "
            f"mics={_format_mic_positions_summary(state.latest_mic_world_positions)}",
        )
        self._set_label(
            "latest",
            "Frame: "
            f"{state.latest_frame_id or 'none'} | "
            f"timestamp={state.latest_timestamp_ms} | "
            f"detections={state.latest_detection_count} | "
            f"backend={state.latest_backend or state.backend} | "
            f"source={state.latest_source_prim_path or state.source_prim_path} | "
            f"pos={_optional_vec3_text(state.latest_source_position_m)}",
        )
        self._set_label(
            "live_status",
            "Active" if state.sensor_running else "Stopped",
        )
        self._set_label("live_backend", state.latest_backend or state.backend)
        self._set_label(
            "live_frame",
            self._frame_freshness_text(),
        )
        self._set_label("live_detections", str(state.latest_detection_count))
        self._set_label(
            "live_waveform",
            "Available"
            if state.latest_waveform_paths
            else "None yet",
        )
        room = state.latest_room_summary
        if room:
            self._set_label(
                "room",
                "Room: "
                f"{room.get('room_id', 'unknown')} | "
                f"dims={_optional_vec3_text(room.get('dimensions_m'))} | "
                f"origin={_optional_vec3_text(room.get('origin_m'))} | "
                f"absorption={room.get('absorption')} "
                f"({room.get('absorption_provenance', 'config')}) | "
                f"anchor={room.get('anchor_prim_path') or 'centered on array'}",
            )
        else:
            self._set_label(
                "room",
                "Room: inactive | "
                f"anchor={state.room_anchor_prim_path or 'centered on array'} | "
                "used by the room_acoustics backend",
            )
        self.refresh_instruments()
        self.refresh_audio_panel()
        self._set_label("audition", state.audition_status)
        self._set_label(
            "overlay",
            "Overlay: "
            f"{state.latest_overlay_primitive_count} primitive(s) | "
            f"{', '.join(state.latest_overlay_labels) or 'none'} | "
            f"{state.latest_overlay_status}",
        )
        self._set_label(
            "usd_debug",
            "USD debug: "
            f"{len(state.latest_usd_debug_prim_paths)} prim(s) | "
            f"root={state.usd_debug_root} | "
            f"{'enabled' if state.usd_debug_enabled else 'disabled'}",
        )
        self._set_label("omnigraph", state.omnigraph_status)
        self._set_label(
            "replicator",
            f"{state.replicator_status_message} | "
            f"latest={state.replicator_latest_write_path or 'none'}",
        )
        self._set_label(
            "diagnostic",
            state.error_message or "No active diagnostic error.",
        )
        status_kind, status_text = self._footer_status()
        self._set_label("status", self._compact_status(status_text))
        self._set_label("status_icon", status_kind)
        status_icon = self._labels.get("status_icon")
        if status_icon is not None:
            with suppress(Exception):
                status_icon.style = {"color": _STATUS_COLORS[status_kind]}
        sensor_button = self._instruments.get("sensor_button")
        if sensor_button is not None:
            _set_widget_text(
                sensor_button,
                "Stop Sensor" if state.sensor_running else "Start Sensor",
            )
        guided_refresh = getattr(self, "_refresh_guided_section", None)
        if callable(guided_refresh):
            guided_refresh()

    def refresh_instruments(self) -> None:
        """Push the latest frame snapshot into the instrument widgets."""

        if not self._instruments:
            return
        state = self.controller.state
        view_model = compass_view_model(
            bearing_deg=state.latest_bearing_deg,
            candidate_bearings=state.latest_candidate_bearings,
            sector=state.latest_sector,
            confidence=state.latest_bearing_confidence,
            occluded=state.latest_occluded,
        )
        self._set_label(
            "compass_bearing",
            (
                "—"
                if not view_model.needles
                else f"{view_model.needles[0].bearing_deg:.1f} deg"
            ),
        )
        self._set_label("compass_sector", view_model.sector or "—")
        self._set_label(
            "compass_confidence",
            "—" if not view_model.needles else f"{view_model.confidence:.2f}",
        )
        self._set_label(
            "compass_occlusion",
            (
                "Occluded"
                if view_model.occluded is True
                else ("Clear" if view_model.occluded is False else "Unknown")
            ),
        )
        provider = self._instruments.get("compass_provider")
        if provider is not None and hasattr(provider, "set_bytes_data"):
            image = render_compass_rgba(view_model, size=COMPASS_IMAGE_SIZE)
            with suppress(Exception):
                provider.set_bytes_data(
                    image.flatten().tolist(),
                    [image.shape[1], image.shape[0]],
                )
        meters = meter_view_models(state.latest_aggregate_rms)
        for index, row in enumerate(self._instruments.get("meters", ())):
            visible = index < len(meters)
            if row.get("row") is not None:
                row["row"].visible = visible
            if not visible:
                _set_widget_text(row.get("label"), "")
                continue
            meter = meters[index]
            _set_widget_text(row.get("label"), meter.mic_id)
            _set_widget_text(
                row.get("value"),
                "silent" if meter.db is None else f"{meter.db:.1f} dB",
            )
            fill = row.get("fill")
            remaining = row.get("remaining")
            if fill is not None:
                fill.width = _ui_fraction(self.ui, meter.fraction)
            if remaining is not None:
                remaining.width = _ui_fraction(self.ui, 1.0 - meter.fraction)
        rows = timeline_rows(state.detection_history, max_rows=3)
        for index, label in enumerate(self._instruments.get("timeline", ())):
            visible = index < len(rows)
            label.visible = visible
            _set_widget_text(label, rows[index].text if visible else "")
        empty = self._instruments.get("empty")
        if empty is not None:
            empty.visible = not bool(state.latest_frame_id)
            _set_widget_text(
                empty,
                "No sensor frame yet. Start the sensor to monitor audio.",
            )
        detection_empty = self._instruments.get("detection_empty")
        if detection_empty is not None:
            detection_empty.visible = bool(state.latest_frame_id) and not bool(rows)

    def refresh_audio_panel(self) -> None:
        """Refresh the waveform/spectrogram preview for the latest WAV."""

        panel = self._audio_panel
        if not panel:
            return
        state = self.controller.state
        paths = state.latest_waveform_paths
        if not paths:
            self._set_label(
                "waveform",
                "No waveform yet. Enable WAV Export and use the "
                "room_acoustics backend.",
            )
            return
        latest = paths[-1]
        if panel.get("rendered_path") == latest:
            return
        waveform_provider = panel.get("waveform_provider")
        spectrogram_provider = panel.get("spectrogram_provider")
        try:
            data = self.controller.latest_waveform_data()
            if data is None:
                return
        except Exception as exc:
            self._set_label(
                "waveform",
                f"Latest WAV: {latest} | preview failed: {exc}",
            )
            return
        self._set_label(
            "waveform",
            f"Latest WAV: {latest} | {data.channel_count} ch | "
            f"{data.sample_rate_hz} Hz | {data.duration_s:.2f} s",
        )
        if waveform_provider is not None and hasattr(
            waveform_provider, "set_bytes_data"
        ):
            image = render_waveform_rgba(data.samples)
            with suppress(Exception):
                waveform_provider.set_bytes_data(
                    image.flatten().tolist(),
                    [image.shape[1], image.shape[0]],
                )
        if spectrogram_provider is not None and hasattr(
            spectrogram_provider, "set_bytes_data"
        ):
            image = render_spectrogram_rgba(data.samples)
            with suppress(Exception):
                spectrogram_provider.set_bytes_data(
                    image.flatten().tolist(),
                    [image.shape[1], image.shape[0]],
                )
        panel["rendered_path"] = latest

    def sync_state_from_widgets(self) -> None:
        """Read widget models into the pure state before actions."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            setattr(state, attr_name, _model_string(widget.model))
        for attr_name, widget in self._float_fields.items():
            try:
                value = _model_float(widget.model)
            except (TypeError, ValueError) as exc:
                raise self._field_input_error(
                    attr_name,
                    widget,
                    message="Invalid numeric value",
                    recovery="Enter a number, then retry",
                ) from exc
            setattr(state, attr_name, value)
        for attr_name, widget in self._int_fields.items():
            try:
                value = _model_int(widget.model)
            except (TypeError, ValueError) as exc:
                raise self._field_input_error(
                    attr_name,
                    widget,
                    message="Invalid integer value",
                    recovery="Enter a whole number, then retry",
                ) from exc
            setattr(state, attr_name, value)
        for attr_name, widget in self._bool_fields.items():
            setattr(state, attr_name, _model_bool(widget.model))
        for attr_name, (widget, choices) in self._combo_fields.items():
            index = _combo_index(widget.model)
            if 0 <= index < len(choices):
                setattr(state, attr_name, choices[index])

    def push_state_to_widgets(self) -> None:
        """Push state values into editable widgets after action-side updates."""

        state = self.controller.state
        self._pushing_state = True
        try:
            for attr_name, widget in self._string_fields.items():
                _set_model_value(widget.model, getattr(state, attr_name))
            for attr_name, widget in self._float_fields.items():
                _set_model_value(widget.model, float(getattr(state, attr_name)))
            for attr_name, widget in self._int_fields.items():
                _set_model_value(widget.model, int(getattr(state, attr_name)))
            for attr_name, widget in self._bool_fields.items():
                _set_model_value(widget.model, getattr(state, attr_name))
            for attr_name, (widget, choices) in self._combo_fields.items():
                current = getattr(state, attr_name)
                if current in choices:
                    _set_combo_index(widget.model, choices.index(current))
        finally:
            self._pushing_state = False
        self._apply_all_field_styles()

    def _field_input_error(
        self,
        attr_name: str,
        widget: Any,
        *,
        message: str,
        recovery: str,
    ) -> _UiFieldInputError:
        section, label = self._field_metadata.get(
            attr_name,
            ("Advanced Tools", attr_name),
        )
        value = self._compact_status(_model_string(widget.model), limit=32)
        return _UiFieldInputError(
            attr_name=attr_name,
            section=section,
            label=label,
            message=f"{message} {value!r}",
            recovery=recovery,
        )

    def _field_widget(self, attr_name: str) -> Any | None:
        if attr_name in self._combo_fields:
            return self._combo_fields[attr_name][0]
        for fields in (
            self._string_fields,
            self._float_fields,
            self._int_fields,
            self._bool_fields,
        ):
            if attr_name in fields:
                return fields[attr_name]
        return None

    def _register_field(self, attr_name: str, label: str, widget: Any) -> None:
        section = self._active_subsection or self._active_section or "Advanced Tools"
        self._field_metadata[attr_name] = (section, label)
        self._apply_field_style(attr_name, widget)

    def _apply_field_style(self, attr_name: str, widget: Any | None = None) -> None:
        widget = widget or self._field_widget(attr_name)
        if widget is None:
            return
        style_name = (
            "invalid"
            if attr_name == self._invalid_field
            else ("auto" if attr_name in self._auto_filled_fields else "editable")
        )
        with suppress(Exception):
            widget.style = dict(_FIELD_STYLES[style_name])

    def _apply_all_field_styles(self) -> None:
        for attr_name in self._field_metadata:
            self._apply_field_style(attr_name)

    def _editable_state_snapshot(self) -> dict[str, Any]:
        state = self.controller.state
        return {
            attr_name: getattr(state, attr_name)
            for attr_name in self._field_metadata
        }

    def _mark_auto_filled_changes(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        self._auto_filled_fields.update(
            attr_name
            for attr_name in before.keys() & after.keys()
            if before[attr_name] != after[attr_name]
        )

    def _manual_field_changed(self, attr_name: str) -> None:
        if self._pushing_state:
            return
        self._auto_filled_fields.discard(attr_name)
        self._apply_field_style(attr_name)

    def _clear_field_error(self, attr_name: str) -> None:
        if self._invalid_field != attr_name:
            return
        _section, label = self._field_metadata.get(
            attr_name,
            ("Advanced Tools", attr_name),
        )
        self._invalid_field = None
        self._diagnostic = None
        self.controller.state.error_message = None
        self.controller.state.status_message = f"Corrected {label}."
        self._apply_field_style(attr_name)
        self.refresh_labels()

    def _refresh_frame_receipt(self) -> None:
        state = self.controller.state
        if not state.latest_frame_id:
            self._last_frame_key = None
            self._last_frame_received_s = None
            return
        key = (state.latest_frame_id, state.latest_timestamp_ms)
        if key != self._last_frame_key:
            self._last_frame_key = key
            self._last_frame_received_s = self._clock()

    def _frame_age_s(self) -> float | None:
        if self._last_frame_received_s is None:
            return None
        return max(0.0, self._clock() - self._last_frame_received_s)

    def _frame_freshness_text(self) -> str:
        if not self.controller.state.latest_frame_id:
            return "No frame yet"
        age_s = self._frame_age_s()
        if age_s is None or age_s < 0.01:
            return "Updated just now"
        if age_s < 1.0:
            return f"Updated {round(age_s * 1000.0):d} ms ago"
        if age_s < 60.0:
            return f"Updated {age_s:.1f} s ago"
        minutes, seconds = divmod(int(age_s), 60)
        return f"Updated {minutes}m {seconds:02d}s ago"

    def _footer_status(self) -> tuple[str, str]:
        state = self.controller.state
        if state.error_message:
            diagnostic = self._diagnostic or _UiDiagnostic(
                section="Sensor Settings & Debug",
                field="Diagnostics",
                message=state.error_message,
                recovery="Correct the reported issue, then retry.",
            )
            location = f"{diagnostic.section} > {diagnostic.field}"
            message = diagnostic.message.rstrip(".")
            recovery = diagnostic.recovery.rstrip(".")
            return "ERROR", f"{location} — {message}. {recovery}."

        recording = self.controller.guided_recording_status
        if recording.active:
            dataset_id = recording.dataset_id or "dataset"
            return (
                "RECORDING",
                f"{dataset_id} · {recording.frames} frames · "
                f"{recording.dropped_frames} dropped",
            )

        if state.sensor_running:
            age_s = self._frame_age_s()
            backend = state.latest_backend or state.backend
            if age_s is None:
                return (
                    "WARNING",
                    f"{state.array_id} · waiting for first frame · {backend}",
                )
            stale_after_s = max(0.5, 3.0 * float(state.update_period_s))
            freshness = self._frame_freshness_text().removeprefix("Updated ")
            if age_s > stale_after_s:
                return (
                    "WARNING",
                    f"{state.array_id} · frame stale {freshness} · {backend}",
                )
            return "ACTIVE", f"{state.array_id} · frame {freshness} · {backend}"

        message = " ".join(str(state.status_message).split())
        if (
            not message
            or message == "Ready."
            or message.startswith("Window shown")
            or message.startswith("Window hidden")
            or message.startswith("Loaded ")
        ):
            message = "Ready for setup."
        return "READY", message

    @staticmethod
    def _compact_status(message: str, limit: int = 150) -> str:
        summary = " ".join(str(message).split())
        return summary if len(summary) <= limit else summary[: limit - 3] + "..."

    @contextmanager
    def _section(
        self,
        title: str,
        *,
        collapsed: bool = False,
        on_collapsed_changed: Callable[[bool], None] | None = None,
    ) -> Any:
        self._sections.append(title)
        previous = self._active_section
        self._active_section = title
        try:
            frame_type = getattr(self.ui, "CollapsableFrame", None)
            if frame_type is None:
                with self.ui.VStack(spacing=4) as stack:
                    yield stack
                return
            frame = frame_type(title, collapsed=collapsed, height=0)
            self._section_frames[title] = frame
            setter = getattr(frame, "set_collapsed_changed_fn", None)
            if callable(setter) and on_collapsed_changed is not None:
                setter(on_collapsed_changed)
            with frame, self.ui.VStack(spacing=4, height=0) as stack:
                yield stack
        finally:
            self._active_section = previous

    @contextmanager
    def _subsection(self, title: str, *, collapsed: bool = True) -> Any:
        previous = self._active_subsection
        self._active_subsection = title
        try:
            frame_type = getattr(self.ui, "CollapsableFrame", None)
            if frame_type is None:
                with self.ui.VStack(spacing=4, height=0) as stack:
                    yield stack
                return
            frame = frame_type(title, collapsed=collapsed, height=0)
            with frame, self.ui.VStack(spacing=4, height=0) as stack:
                yield stack
        finally:
            self._active_subsection = previous

    def _string_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                str(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._register_field(attr_name, label, widget)
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_string(model),
                ),
                attr_name=attr_name,
            )
            self._string_fields[attr_name] = widget

    def _float_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "float",
                float(getattr(self.controller.state, attr_name)),
            )
            widget_type = getattr(self.ui, "FloatDrag", self.ui.StringField)
            widget = widget_type(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
            )
            self._register_field(attr_name, label, widget)
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_float_state(
                    name,
                    model,
                ),
                attr_name=attr_name,
            )
            self._float_fields[attr_name] = widget

    def _int_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "int",
                int(getattr(self.controller.state, attr_name)),
            )
            widget_type = getattr(self.ui, "IntDrag", self.ui.StringField)
            widget = widget_type(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
            )
            self._register_field(attr_name, label, widget)
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_int_state(name, model),
                attr_name=attr_name,
            )
            self._int_fields[attr_name] = widget

    def _bool_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "bool",
                bool(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.CheckBox(model=model)
            self._register_field(attr_name, label, widget)
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_bool(model),
                ),
                attr_name=attr_name,
            )
            self._bool_fields[attr_name] = widget

    def _combo_row(
        self,
        label: str,
        attr_name: str,
        choices: tuple[str, ...],
    ) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            current = getattr(self.controller.state, attr_name)
            index = choices.index(current) if current in choices else 0
            widget = self.ui.ComboBox(index, *choices, width=220)
            self._combo_fields[attr_name] = (widget, choices)
            self._register_field(attr_name, label, widget)

            def _on_changed(model: Any, _item: Any = None) -> None:
                selected = _combo_index(model)
                if 0 <= selected < len(choices):
                    setattr(self.controller.state, attr_name, choices[selected])
                    self._manual_field_changed(attr_name)

            if hasattr(widget.model, "add_item_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_item_changed_fn(_on_changed)
                )
            if hasattr(widget.model, "add_value_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_value_changed_fn(_on_changed)
                )

    def _readonly_label(
        self,
        name: str,
        text: str = "",
        *,
        word_wrap: bool = True,
    ) -> Any:
        widget = self.ui.Label(text, word_wrap=word_wrap)
        with suppress(Exception):
            widget.style = dict(_READ_ONLY_STYLE)
        self._labels[name] = widget
        return widget

    def _button(
        self,
        label: str,
        callback: Callable[..., Any],
        *,
        kind: str = "secondary",
        width: Any | None = None,
    ) -> Any:
        self._buttons.append(label)
        colors = {
            "primary": 0xFFD2782E,
            "danger": 0xFF3D47B8,
            "secondary": 0xFF52463D,
        }
        kwargs = {
            "clicked_fn": self._action(
                callback,
                action_label=label,
                section=(
                    self._active_subsection
                    or self._active_section
                    or "Advanced Tools"
                ),
            ),
            "height": 28,
            "style": {"Button": {"background_color": colors[kind]}},
        }
        if width is not None:
            kwargs["width"] = width
        return self.ui.Button(
            label,
            **kwargs,
        )

    def _action(
        self,
        callback: Callable[..., Any],
        *,
        action_label: str = "Action",
        section: str = "Advanced Tools",
    ) -> Callable[[], None]:
        def _wrapped() -> None:
            try:
                self.sync_state_from_widgets()
            except _UiFieldInputError as exc:
                self._invalid_field = exc.attr_name
                self._diagnostic = _UiDiagnostic(
                    section=exc.section,
                    field=exc.label,
                    message=str(exc),
                    recovery=exc.recovery,
                )
                self.controller.state.status_message = f"UI input failed: {exc}"
                self.controller.state.error_message = f"UI input failed: {exc}"
                self._apply_field_style(exc.attr_name)
                self.refresh_labels()
                return
            except Exception as exc:
                self.controller.report_error("UI input failed", exc)
                self.refresh_labels()
                return

            before = self._editable_state_snapshot()
            try:
                callback()
            except Exception as exc:
                self.controller.report_error(f"{action_label} failed", exc)
            after = self._editable_state_snapshot()
            if self.controller.state.error_message:
                self._diagnostic = _UiDiagnostic(
                    section=section,
                    field=action_label,
                    message=self.controller.state.error_message,
                    recovery="Correct the reported issue, then retry this action",
                )
            else:
                self._diagnostic = None
                self._invalid_field = None
                self._mark_auto_filled_changes(before, after)
            self.push_state_to_widgets()
            self.refresh_labels()

        return _wrapped

    def _bind_model_change(
        self,
        model: Any,
        callback: Callable[[Any], None],
        *,
        attr_name: str | None = None,
    ) -> None:
        if hasattr(model, "add_value_changed_fn"):
            def _changed(changed_model: Any) -> None:
                callback(changed_model)
                if attr_name is not None:
                    self._manual_field_changed(attr_name)

            self._model_change_subscriptions.append(
                model.add_value_changed_fn(_changed)
            )

    def _try_update_float_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_float(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)
        self._clear_field_error(attr_name)

    def _try_update_int_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_int(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)
        self._clear_field_error(attr_name)

    def _set_label(self, name: str, text: str) -> None:
        _set_widget_text(self._labels.get(name), text)
