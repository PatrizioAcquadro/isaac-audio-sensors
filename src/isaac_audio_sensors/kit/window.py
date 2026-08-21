"""``omni.ui`` window adapter for ``ExtensionUiState``."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

from .constants import OMNI_WINDOW_TITLE
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
    TIMELINE_MAX_ROWS,
    compass_view_model,
    meter_view_models,
    render_compass_rgba,
    timeline_rows,
)
from .sections import (
    build_array_section,
    build_audio_output_section,
    build_control_section,
    build_export_section,
    build_guided_section,
    build_instruments_section,
    build_replicator_section,
    build_room_section,
    build_source_section,
    build_stage_section,
)
from .spectro import render_spectrogram_rgba, render_waveform_rgba
from .ui_models import (
    _combo_index,
    _format_edit_value,
    _model_bool,
    _model_float,
    _model_int,
    _model_string,
    _new_simple_model,
    _set_combo_index,
    _set_model_value,
    _set_widget_text,
    _set_window_visibility_changed_fn,
    _set_window_visible,
    _ui_fraction,
)

if TYPE_CHECKING:
    from .controller import ExtensionController


class OmniReferenceWindow:
    """Small adapter from ``ExtensionUiState`` to ``omni.ui`` widgets."""

    def __init__(self, controller: ExtensionController, ui: Any) -> None:
        self.controller = controller
        self.ui = ui
        self.window: Any | None = None
        self._string_fields: dict[str, Any] = {}
        self._float_fields: dict[str, Any] = {}
        self._int_fields: dict[str, Any] = {}
        self._bool_fields: dict[str, Any] = {}
        self._combo_fields: dict[str, tuple[Any, tuple[str, ...]]] = {}
        self._labels: dict[str, Any] = {}
        self._model_change_subscriptions: list[Any] = []
        self._sections: list[str] = []
        self._buttons: list[str] = []
        self._instruments: dict[str, Any] = {}
        self._audio_panel: dict[str, Any] = {}

    def build(self) -> Any:
        """Build a compact task-oriented Kit window."""

        ui = self.ui
        self.window = ui.Window(OMNI_WINDOW_TITLE, width=620, height=760)
        _set_window_visibility_changed_fn(
            self.window,
            self.controller.handle_window_visibility_changed,
        )
        with self.window.frame:
            scrolling_frame = getattr(ui, "ScrollingFrame", None)
            if scrolling_frame is None:
                with ui.VStack(spacing=6):
                    self._build_body()
            else:
                with scrolling_frame(), ui.VStack(spacing=6, height=0):
                    self._build_body()
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
        self._instruments.clear()
        self._audio_panel.clear()

    def _build_body(self) -> None:
        if self.controller.state.guided_mode_enabled:
            build_guided_section(self)
        build_stage_section(self)
        build_array_section(self)
        build_source_section(self)
        build_control_section(self)
        build_room_section(self)
        build_instruments_section(self)
        build_audio_output_section(self)
        build_replicator_section(self)
        build_export_section(self)
        self._labels["status"] = self.ui.Label(
            self.controller.state.status_message,
            word_wrap=True,
        )

    def refresh_labels(self) -> None:
        """Push current state summaries to visible labels."""

        state = self.controller.state
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
            f"detections={state.latest_detection_count} | "
            f"backend={state.latest_backend or state.backend} | "
            f"source={state.latest_source_prim_path or state.source_prim_path} | "
            f"pos={_optional_vec3_text(state.latest_source_position_m)}",
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
        self._set_label("status", state.status_message)
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
        self._set_label("compass", view_model.summary)
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
            _set_widget_text(row.get("label"), meter.text)
            bar = row.get("bar")
            if bar is not None:
                _set_model_value(bar.model, meter.fraction)
        rows = timeline_rows(state.detection_history, max_rows=TIMELINE_MAX_ROWS)
        for index, label in enumerate(self._instruments.get("timeline", ())):
            visible = index < len(rows)
            label.visible = visible
            _set_widget_text(label, rows[index].text if visible else "")

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
            setattr(state, attr_name, _model_float(widget.model))
        for attr_name, widget in self._int_fields.items():
            setattr(state, attr_name, _model_int(widget.model))
        for attr_name, widget in self._bool_fields.items():
            setattr(state, attr_name, _model_bool(widget.model))
        for attr_name, (widget, choices) in self._combo_fields.items():
            index = _combo_index(widget.model)
            if 0 <= index < len(choices):
                setattr(state, attr_name, choices[index])

    def push_state_to_widgets(self) -> None:
        """Push state values into editable widgets after action-side updates."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, widget in self._float_fields.items():
            _set_model_value(
                widget.model, _format_edit_value(getattr(state, attr_name))
            )
        for attr_name, widget in self._int_fields.items():
            _set_model_value(
                widget.model, _format_edit_value(getattr(state, attr_name))
            )
        for attr_name, widget in self._bool_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, (widget, choices) in self._combo_fields.items():
            current = getattr(state, attr_name)
            if current in choices:
                _set_combo_index(widget.model, choices.index(current))

    @contextmanager
    def _section(self, title: str) -> Any:
        self._sections.append(title)
        frame_type = getattr(self.ui, "CollapsableFrame", None)
        if frame_type is None:
            with self.ui.VStack(spacing=4) as stack:
                yield stack
            return
        frame = frame_type(title, collapsed=False, height=0)
        with frame, self.ui.VStack(spacing=4, height=0) as stack:
            yield stack

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
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_string(model),
                ),
            )
            self._string_fields[attr_name] = widget

    def _float_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                _format_edit_value(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_float_state(
                    name,
                    model,
                ),
            )
            self._float_fields[attr_name] = widget

    def _int_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                _format_edit_value(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_int_state(name, model),
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
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_bool(model),
                ),
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

            def _on_changed(model: Any, _item: Any = None) -> None:
                selected = _combo_index(model)
                if 0 <= selected < len(choices):
                    setattr(self.controller.state, attr_name, choices[selected])

            if hasattr(widget.model, "add_item_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_item_changed_fn(_on_changed)
                )
            if hasattr(widget.model, "add_value_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_value_changed_fn(_on_changed)
                )

    def _button(self, label: str, callback: Callable[..., Any]) -> Any:
        self._buttons.append(label)
        return self.ui.Button(label, clicked_fn=self._action(callback))

    def _action(self, callback: Callable[..., Any]) -> Callable[[], None]:
        def _wrapped() -> None:
            try:
                self.sync_state_from_widgets()
            except Exception as exc:
                self.controller.report_error("UI input failed", exc)
                self.refresh_labels()
                return
            callback()
            self.push_state_to_widgets()
            self.refresh_labels()

        return _wrapped

    def _bind_model_change(
        self,
        model: Any,
        callback: Callable[[Any], None],
    ) -> None:
        if hasattr(model, "add_value_changed_fn"):
            self._model_change_subscriptions.append(
                model.add_value_changed_fn(callback)
            )

    def _try_update_float_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_float(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)

    def _try_update_int_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_int(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)

    def _set_label(self, name: str, text: str) -> None:
        _set_widget_text(self._labels.get(name), text)
