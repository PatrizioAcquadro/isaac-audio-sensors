"""Live Kit widgets, callbacks, window integration and instruments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kit_capture import (
    _capture_app_screenshot,
    _settle_kit_ui,
)
from kit_common import (
    _result_summary,
)
from live_isaac_sim_audio_smoke import (
    _update_kit_once,
)

from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.constants import (
    OMNI_ACTION_TOGGLE_WINDOW,
    OMNI_DEFAULT_HOTKEY,
    OMNI_MENU_GROUP,
    OMNI_WINDOW_TITLE,
)
from isaac_audio_sensors.kit.instruments import (
    compass_view_model,
    meter_view_models,
    perception_status_text,
    timeline_rows,
)
from isaac_audio_sensors.kit.window import _UiDiagnostic


def _reference_ui_window(controller: ExtensionController) -> Any | None:
    return controller._lifecycle._ui_window


def _push_state_to_widgets(controller: ExtensionController) -> None:
    window = _reference_ui_window(controller)
    if window is not None:
        window.push_state_to_widgets()


def _probe_window_integrations(controller: ExtensionController) -> dict[str, Any]:
    record: dict[str, Any] = {
        "window_title": OMNI_WINDOW_TITLE,
        "menu_path": f"{OMNI_MENU_GROUP} -> {OMNI_WINDOW_TITLE}",
        "action_id": f"{controller.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}",
        "default_hotkey": OMNI_DEFAULT_HOTKEY,
        "action_status": controller.action_status,
        "menu_status": controller.menu_status,
        "hotkey_status": controller.hotkey_status,
        "initial_visible": controller.is_window_visible(),
    }
    controller.hide_window()
    record["visible_after_close_probe"] = controller.is_window_visible()
    action_probe = _execute_toggle_window_action(controller)
    record["action_probe"] = action_probe
    record["visible_after_action_probe"] = controller.is_window_visible()
    controller.show_window()
    record["visible_after_restore"] = controller.is_window_visible()

    passed = (
        "registered" in controller.action_status.lower()
        and "registered" in controller.menu_status.lower()
        and record["visible_after_close_probe"] is False
        and action_probe.get("status") == "passed"
        and record["visible_after_action_probe"] is True
        and record["visible_after_restore"] is True
        and (
            "registered" in controller.hotkey_status.lower()
            or "unavailable" in controller.hotkey_status.lower()
            or "disabled" in controller.hotkey_status.lower()
        )
    )
    record["status"] = "passed" if passed else "failed"
    return record


def _execute_toggle_window_action(
    controller: ExtensionController,
) -> dict[str, Any]:
    try:
        import omni.kit.actions.core as actions_core  # type: ignore
    except ImportError as exc:
        return {"status": "failed", "reason": f"actions core unavailable: {exc}"}
    registry = actions_core.get_action_registry()
    if registry is None:
        return {"status": "failed", "reason": "action registry unavailable"}
    try:
        result = registry.execute_action(controller.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
    except Exception as exc:  # noqa: BLE001 - evidence records exact runtime issue.
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return {
        "status": "passed" if result is not None else "returned_none",
        "result_summary": _result_summary(result),
    }


def _probe_ui_editable_models(controller: ExtensionController) -> dict[str, Any]:
    window = _reference_ui_window(controller)
    if window is None:
        return {"status": "skipped", "reason": "ui_window_unavailable"}
    duration = window._float_fields.get("source_duration_s")
    position_x = window._float_fields.get("source_position_x_m")
    position_y = window._float_fields.get("source_position_y_m")
    position_z = window._float_fields.get("source_position_z_m")
    local_offset_x = window._float_fields.get("source_local_offset_x_m")
    local_offset_y = window._float_fields.get("source_local_offset_y_m")
    local_offset_z = window._float_fields.get("source_local_offset_z_m")
    sample_rate = window._int_fields.get("sample_rate_hz")
    source_id = window._string_fields.get("source_id")
    object_path = window._string_fields.get("object_prim_path")
    if (
        duration is None
        or position_x is None
        or position_y is None
        or position_z is None
        or local_offset_x is None
        or local_offset_y is None
        or local_offset_z is None
        or sample_rate is None
        or source_id is None
        or object_path is None
    ):
        return {"status": "failed", "reason": "expected editable fields missing"}
    duration.model.set_value(10.0)
    position_x.model.set_value(2.0)
    position_y.model.set_value(0.0)
    position_z.model.set_value(0.0)
    local_offset_x.model.set_value(0.0)
    local_offset_y.model.set_value(0.0)
    local_offset_z.model.set_value(0.0)
    sample_rate.model.set_value(44100)
    source_id.model.set_value("speaker_a")
    object_path.model.set_value("/World/Oven")
    window.sync_state_from_widgets()
    return {
        "status": "passed",
        "source_duration_s": controller.state.source_duration_s,
        "source_position_world": [
            controller.state.source_position_x_m,
            controller.state.source_position_y_m,
            controller.state.source_position_z_m,
        ],
        "source_local_offset_m": [
            controller.state.source_local_offset_x_m,
            controller.state.source_local_offset_y_m,
            controller.state.source_local_offset_z_m,
        ],
        "object_prim_path": controller.state.object_prim_path,
        "sample_rate_hz": controller.state.sample_rate_hz,
        "source_id": controller.state.source_id,
        "duration_widget_kind": getattr(duration, "kind", type(duration).__name__),
        "sample_rate_widget_kind": getattr(
            sample_rate, "kind", type(sample_rate).__name__
        ),
        "source_id_widget_kind": getattr(source_id, "kind", type(source_id).__name__),
    }


def _probe_ui_numeric_widgets(controller: ExtensionController) -> dict[str, Any]:
    window = _reference_ui_window(controller)
    if window is None:
        return {"status": "failed", "reason": "ui_window_unavailable"}
    duration = window._float_fields.get("source_duration_s")
    sample_rate = window._int_fields.get("sample_rate_hz")
    if duration is None or sample_rate is None:
        return {"status": "failed", "reason": "numeric fields missing"}
    previous_duration = controller.state.source_duration_s
    previous_sample_rate = controller.state.sample_rate_hz
    restore_error = None
    try:
        duration.model.set_value(2.5)
        sample_rate.model.set_value(48000)
        window.sync_state_from_widgets()
        observed_duration = controller.state.source_duration_s
        observed_sample_rate = controller.state.sample_rate_hz
        duration.model.set_value(previous_duration)
        sample_rate.model.set_value(previous_sample_rate)
        window.sync_state_from_widgets()
        window.refresh_labels()
    except Exception as exc:  # noqa: BLE001 - evidence should keep moving.
        restore_error = f"{type(exc).__name__}: {exc}"
        observed_duration = None
        observed_sample_rate = None
    duration_kind = type(duration).__name__
    sample_rate_kind = type(sample_rate).__name__
    passed = (
        observed_duration == 2.5
        and observed_sample_rate == 48000
        and "FloatDrag" in duration_kind
        and "IntDrag" in sample_rate_kind
        and restore_error is None
    )
    return {
        "status": "passed" if passed else "failed",
        "duration_widget_kind": duration_kind,
        "sample_rate_widget_kind": sample_rate_kind,
        "observed_duration": observed_duration,
        "observed_sample_rate": observed_sample_rate,
        "restore_error": restore_error,
    }


def _capture_advanced_error_evidence(
    controller: ExtensionController,
    *,
    screenshot_path: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Capture the field-specific error treatment with Advanced open."""

    window = _reference_ui_window(controller)
    if window is None:
        return {"status": "failed", "reason": "ui_window_unavailable"}
    duration = window._float_fields.get("source_duration_s")
    advanced = window._section_frames.get("Advanced Tools")
    live = window._section_frames.get("Live Monitor")
    guided = window._section_frames.get("Guided Workflow")
    audio_source = window._subsection_frames.get("Audio Source")
    if duration is None or advanced is None or live is None or audio_source is None:
        return {"status": "failed", "reason": "advanced error controls missing"}

    state = controller.state
    previous = {
        "duration": state.source_duration_s,
        "status": state.status_message,
        "error": state.error_message,
        "diagnostic": window._diagnostic,
        "invalid_field": window._invalid_field,
        "advanced_collapsed": bool(getattr(advanced, "collapsed", True)),
        "live_collapsed": bool(getattr(live, "collapsed", False)),
        "guided_collapsed": (
            bool(getattr(guided, "collapsed", True)) if guided is not None else None
        ),
        "subsections": {
            title: bool(getattr(frame, "collapsed", True))
            for title, frame in window._subsection_frames.items()
        },
        "scroll_y": getattr(window._scrolling_frame, "scroll_y", None),
    }
    record: dict[str, Any] = {}
    try:
        state.source_duration_s = 0.0
        duration.model.set_value(0.0)
        window._invalid_field = "source_duration_s"
        window._diagnostic = _UiDiagnostic(
            section="Audio Source",
            field="Duration",
            message="Duration must be greater than 0",
            recovery="Enter a positive number, then retry",
        )
        state.status_message = "Invalid source duration."
        state.error_message = "Invalid source duration."
        window._apply_field_style("source_duration_s")
        window._set_section_collapsed("Live Monitor", True)
        window._set_section_collapsed("Advanced Tools", False)
        for frame in window._subsection_frames.values():
            frame.collapsed = True
        audio_source.collapsed = False
        if window._scrolling_frame is not None:
            window._scrolling_frame.scroll_y = 10_000
        window.refresh_labels()
        _update_kit_once(evidence)
        _settle_kit_ui()

        footer = getattr(window._labels.get("status"), "text", "")
        screenshot = _capture_app_screenshot(screenshot_path)
        record = {
            "footer": footer,
            "advanced_open": not bool(getattr(advanced, "collapsed", True)),
            "audio_source_open": not bool(getattr(audio_source, "collapsed", True)),
            "duration_style": getattr(duration, "style", None),
            "screenshot": screenshot,
        }
        passed = (
            record["advanced_open"]
            and record["audio_source_open"]
            and "Audio Source > Duration" in footer
            and "Enter a positive number, then retry" in footer
            and screenshot.get("status") == "captured"
        )
        record["status"] = "passed" if passed else "failed"
        return record
    finally:
        state.source_duration_s = previous["duration"]
        duration.model.set_value(previous["duration"])
        state.status_message = previous["status"]
        state.error_message = previous["error"]
        window._diagnostic = previous["diagnostic"]
        window._invalid_field = previous["invalid_field"]
        window._apply_field_style("source_duration_s")
        window._set_section_collapsed(
            "Advanced Tools",
            previous["advanced_collapsed"],
        )
        window._set_section_collapsed("Live Monitor", previous["live_collapsed"])
        if previous["guided_collapsed"] is not None:
            window._set_section_collapsed(
                "Guided Workflow",
                previous["guided_collapsed"],
            )
        for title, collapsed in previous["subsections"].items():
            window._subsection_frames[title].collapsed = collapsed
        if window._scrolling_frame is not None and previous["scroll_y"] is not None:
            window._scrolling_frame.scroll_y = previous["scroll_y"]
        window.refresh_labels()


def _combo_model_values(window: Any) -> dict[str, dict[str, Any]]:
    values = {}
    for attr_name, (widget, choices) in window._combo_fields.items():
        index = _combo_index(widget.model)
        model_value = choices[index] if 0 <= index < len(choices) else None
        values[attr_name] = {
            "index": index,
            "model_value": model_value,
            "state_value": getattr(window.controller.state, attr_name),
        }
    return values


def _combo_index(model: Any) -> int:
    if hasattr(model, "get_item_value_model"):
        item_model = model.get_item_value_model()
        try:
            as_int = item_model.as_int
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            return int(as_int)
        get_value = getattr(item_model, "get_value_as_int", None)
        if callable(get_value):
            return int(get_value())
    get_value = getattr(model, "get_value_as_int", None)
    if callable(get_value):
        return int(get_value())
    try:
        as_int = model.as_int
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        return int(as_int)
    return int(getattr(model, "value", 0) or 0)


def _collect_instruments_evidence(
    controller: ExtensionController,
    *,
    screenshot_path: Path,
) -> dict[str, Any]:
    """Verify inactive instruments after repeated paused-timeline snapshots."""

    state = controller.state
    window = _reference_ui_window(controller)
    view_model = compass_view_model(
        ()
        if state.latest_frame is None
        else tuple(o.doa for o in state.latest_frame.observations)
    )
    meters = meter_view_models(state.latest_aggregate_rms)
    rows = timeline_rows(state.observation_history)
    record: dict[str, Any] = {
        "scenario": "contiguous_activity_then_paused_snapshots",
        "frame_id": state.latest_frame_id,
        "observation_count": state.latest_observation_count,
        "history_count": len(state.observation_history),
        "compass": {
            "needle_count": len(view_model.needles),
            "needle_unit_xy": (
                list(view_model.needles[0].unit_xy) if view_model.needles else None
            ),
            "summary": view_model.summary,
        },
        "meters": [
            {"mic_id": meter.mic_id, "db": meter.db, "fraction": meter.fraction}
            for meter in meters
        ],
        "timeline_row_count": len(rows),
    }
    widget_record: dict[str, Any] = {"available": False}
    if window is not None:
        instruments = getattr(window, "_instruments", {}) or {}
        meter_rows = instruments.get("meters") or []
        timeline_labels = instruments.get("timeline") or []
        observation_empty = instruments.get("observation_empty")
        compass_label = window._labels.get("compass")
        widget_record = {
            "available": True,
            "compass_image": instruments.get("compass") is not None,
            "compass_label_text": getattr(compass_label, "text", None),
            "visible_meter_rows": sum(
                1 for row in meter_rows if getattr(row.get("row"), "visible", False)
            ),
            "visible_timeline_rows": sum(
                1 for label in timeline_labels if getattr(label, "visible", False)
            ),
            "observation_empty_visible": bool(
                getattr(observation_empty, "visible", False)
            ),
        }
    record["widgets"] = widget_record
    guided = (
        window._section_frames.get("Guided Workflow") if window is not None else None
    )
    if window is not None:
        window._set_section_collapsed("Guided Workflow", True)
        if window._scrolling_frame is not None:
            window._scrolling_frame.scroll_y = 0
        window.refresh_labels()
        _settle_kit_ui()
        record["guided_collapsed_at_capture"] = bool(getattr(guided, "collapsed", True))
        record["footer_at_capture"] = getattr(
            window._labels.get("status"),
            "text",
            "",
        )
    record["app_screenshot"] = _capture_app_screenshot(screenshot_path)
    passed = (
        not view_model.needles
        and bool(record["meters"])
        and record["observation_count"] == 0
        and record["history_count"] > 0
        and record["timeline_row_count"] > 0
        and widget_record.get("available") is True
        and widget_record.get("compass_image") is True
        and int(widget_record.get("visible_meter_rows", 0)) > 0
        and int(widget_record.get("visible_timeline_rows", 0)) > 0
        and widget_record.get("observation_empty_visible") is False
        and record["app_screenshot"].get("status") == "captured"
    )
    record["status"] = "passed" if passed else "failed"
    return record


def _collect_observed_gui_evidence(
    controller: ExtensionController, root: Path
) -> dict[str, Any]:
    """Exercise real waveform perception through the live Kit widgets."""
    from dataclasses import replace

    from multisource_reference import reference_scenes

    from isaac_audio_sensors.core.backends.base import get_backend
    from isaac_audio_sensors.core.io.traces import write_frame_trace
    from isaac_audio_sensors.core.perception import _build_standard_perception_pipeline
    from isaac_audio_sensors.core.simulation import simulate_frame
    from isaac_audio_sensors.core.types import AudioTimeWindow

    scenes = reference_scenes(root / "signals")
    scene = scenes[2]
    stereo = replace(
        scenes[0],
        arrays=(
            replace(
                scenes[0].arrays[0], microphones=scenes[0].arrays[0].microphones[:2]
            ),
        ),
        sources=scenes[0].sources[:1],
    )
    frames = {}
    for name, current_scene, capacity, enabled in (
        ("simultaneous", scene, 8, True),
        ("ambiguous", stereo, 8, True),
        ("truncated", scene, 1, True),
        ("zero_capacity", scene, 0, True),
        ("disabled", scene, 8, False),
        (
            "unavailable",
            replace(scene, arrays=(replace(scene.arrays[0], sample_rate_hz=48000),)),
            8,
            True,
        ),
    ):
        backend = get_backend("analytic_acoustics")
        pipeline = _build_standard_perception_pipeline(
            energy_threshold_dbfs=-60, doa_enabled=enabled, max_observations=capacity
        )
        for index in range(20):
            frame, _ = simulate_frame(
                backend,
                current_scene,
                current_scene.arrays[0].array_id,
                AudioTimeWindow(
                    start_time_s=index * 0.05,
                    end_time_s=(index + 1) * 0.05,
                    frame_index=index,
                ),
                perception=pipeline,
            )
            if name == "simultaneous" and index == 0:
                frames["warmup"] = frame
        frames[name] = frame
        if name == "simultaneous":
            for index in range(20, 40):
                frame, _ = simulate_frame(
                    backend,
                    replace(current_scene, sources=()),
                    current_scene.arrays[0].array_id,
                    AudioTimeWindow(
                        start_time_s=index * 0.05,
                        end_time_s=(index + 1) * 0.05,
                        frame_index=index,
                    ),
                    perception=pipeline,
                )
            frames["inactive"] = frame
    if len(frames["simultaneous"].observations) < 2:
        raise RuntimeError("GUI waveform control did not produce simultaneous events.")
    ambiguous = [o.doa for o in frames["ambiguous"].observations]
    if not any(
        d is not None and d.estimated_bearing_deg is None and d.candidate_bearing_deg
        for d in ambiguous
    ):
        raise RuntimeError(
            "GUI stereo control did not preserve unresolved alternatives."
        )
    window = _reference_ui_window(controller)
    window._set_section_collapsed("Guided Workflow", True)
    window._scrolling_frame.scroll_y = 0
    saved = controller.state.latest_frame
    saved_history = list(controller.state.observation_history)
    records = {}
    try:
        for name, frame in frames.items():
            controller.state.latest_frame = frame
            window.refresh_labels()
            _settle_kit_ui()
            view = compass_view_model(tuple(o.doa for o in frame.observations))
            write_frame_trace(frame, root / f"{name}.json")
            image = _capture_app_screenshot(root / f"{name}.png")
            records[name] = {
                "events": len(frame.observations),
                "needles": len(view.needles),
                "details": view.summary,
                "perception": perception_status_text(frame),
                "screenshot": image,
            }
            if image.get("status") != "captured":
                raise RuntimeError(f"GUI {name} capture failed: {image}")
        assert "Truncated: 1" in records["truncated"]["perception"]
        assert "Capacity: 0 | Truncated: 2" in records["zero_capacity"]["perception"]
        assert "Localization: warm-up" in records["warmup"]["perception"]
        assert "Activity: inactive" in records["inactive"]["perception"]
        assert records["inactive"]["events"] == 0
        return {
            "status": "passed",
            "scope": "scalar waveform frames to live Kit widgets",
            "cases": records,
        }
    finally:
        controller.state.latest_frame = saved
        controller.state.observation_history[:] = saved_history
        window.refresh_labels()
