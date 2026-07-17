"""Section builders for the Isaac Audio Sensors reference window."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constants import (
    AMBIGUITY_POLICY_CHOICES,
    BACKEND_CHOICES,
    LAYOUT_CHOICES,
    ROOM_OUT_OF_BOUNDS_CHOICES,
    WAVEFORM_MODE_CHOICES,
)
from .instruments import (
    COMPASS_IMAGE_SIZE,
    METER_MAX_ROWS,
    TIMELINE_MAX_ROWS,
    compass_view_model,
    meter_view_models,
)
from .spectro import (
    SPECTROGRAM_IMAGE_HEIGHT,
    SPECTROGRAM_IMAGE_WIDTH,
    WAVEFORM_IMAGE_HEIGHT,
    WAVEFORM_IMAGE_WIDTH,
)
from .ui_models import _combo_index, _set_model_value, _set_widget_text
from .workflow import GUIDED_STAGE_ORDER, SAFE_PRESETS, GuidedStage

if TYPE_CHECKING:
    from .window import OmniReferenceWindow


def build_guided_section(window: OmniReferenceWindow) -> None:
    """Build the guided breadcrumb and operational Run B panels."""

    ui = window.ui
    workflow = window.controller.guided_workflow
    workflow.on_change = window.refresh_labels
    preset_ids = tuple(preset.preset_id for preset in SAFE_PRESETS)
    preset_labels = tuple(preset.label for preset in SAFE_PRESETS)
    selected_id = window.controller.state.guided_preset_id
    selected_index = preset_ids.index(selected_id) if selected_id in preset_ids else 0

    with ui.VStack(spacing=4, height=0) as root:
        ui.Label("Guided Workflow")
        breadcrumb = ui.Label("", word_wrap=True)
        stage_title = ui.Label("")
        stage_status = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as setup_panel:
            ui.Label("Choose a safe scene preset")
            preset_combo = ui.ComboBox(selected_index, *preset_labels, width=260)

            def _preset_changed(model: Any, _item: Any = None) -> None:
                index = _combo_index(model)
                if 0 <= index < len(preset_ids):
                    window.controller.state.guided_preset_id = preset_ids[index]

            if hasattr(preset_combo.model, "add_item_changed_fn"):
                window._model_change_subscriptions.append(
                    preset_combo.model.add_item_changed_fn(_preset_changed)
                )
            if hasattr(preset_combo.model, "add_value_changed_fn"):
                window._model_change_subscriptions.append(
                    preset_combo.model.add_value_changed_fn(_preset_changed)
                )
            window._button(
                "Apply Guided Preset",
                lambda: window.controller.guided_apply_preset(
                    window.controller.state.guided_preset_id or preset_ids[0]
                ),
            )
            setup_summary = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as validate_panel:
            window._button("Validate now", window.controller.guided_validate)
            findings_summary = ui.Label("", word_wrap=True)
            finding_rows: list[dict[str, Any]] = []
            for index in range(12):
                with ui.HStack(spacing=4, height=0) as row:
                    issue_label = ui.Label("", word_wrap=True)

                    def _recover(row_index: int = index) -> None:
                        findings = workflow.findings_for_stage(GuidedStage.VALIDATE)
                        if row_index < len(findings):
                            workflow.recovery_action(findings[row_index])()

                    action_button = window._button("Recover", _recover)
                row.visible = False
                finding_rows.append(
                    {"row": row, "label": issue_label, "button": action_button}
                )
        with ui.VStack(spacing=4, height=0) as run_panel:
            with ui.HStack(spacing=4, height=0):
                window._button("Start Guided Run", window.controller.guided_start_run)
                window._button("Stop Guided Run", window.controller.guided_stop_run)
            run_lifecycle = ui.Label("", word_wrap=True)
            run_frames = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as inspect_panel:
            inspect_summary = ui.Label("", word_wrap=True)
            inspect_compass = ui.Label("", word_wrap=True)
            inspect_meters = ui.Label("", word_wrap=True)
            inspect_spectrogram = ui.Label("", word_wrap=True)
            window._button(
                "Mark Inspected",
                window.controller.guided_mark_inspected,
            )
        with ui.VStack(spacing=4, height=0) as record_panel:
            window._string_row("Session Dir", "guided_session_dir")
            session_dir_field = window._string_fields.pop("guided_session_dir")
            window._string_row("Dataset ID", "guided_dataset_id")
            dataset_id_field = window._string_fields.pop("guided_dataset_id")
            window._int_row("Shard Frames", "guided_shard_max_frames")
            shard_frames_field = window._int_fields.pop("guided_shard_max_frames")
            window._bool_row("Episode Aligned", "guided_record_aligned")
            aligned_field = window._bool_fields.pop("guided_record_aligned")
            with ui.HStack(spacing=4, height=0):
                window._button(
                    "Start Recording",
                    lambda: window.controller.guided_start_recording(
                        window.controller.state.guided_session_dir,
                        window.controller.state.guided_dataset_id,
                        window.controller.state.guided_shard_max_frames,
                        window.controller.state.guided_record_aligned,
                    ),
                )
                window._button(
                    "Cancel Recording",
                    window.controller.guided_cancel_recording,
                )
                window._button(
                    "Stop and Finalize",
                    window.controller.guided_stop_recording,
                )
            recording_progress = ui.Label("", word_wrap=True)
            recording_validation = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as future_panel:
            future_summary = ui.Label("", word_wrap=True)
        with ui.HStack(spacing=4, height=0):
            window._button("Guided Back", window.controller.guided_back)
            window._button("Guided Next", window.controller.guided_advance)

    panel = {
        "root": root,
        "breadcrumb": breadcrumb,
        "stage_title": stage_title,
        "stage_status": stage_status,
        "setup_panel": setup_panel,
        "setup_summary": setup_summary,
        "preset_combo": preset_combo,
        "validate_panel": validate_panel,
        "findings_summary": findings_summary,
        "finding_rows": finding_rows,
        "run_panel": run_panel,
        "run_lifecycle": run_lifecycle,
        "run_frames": run_frames,
        "inspect_panel": inspect_panel,
        "inspect_summary": inspect_summary,
        "inspect_compass": inspect_compass,
        "inspect_meters": inspect_meters,
        "inspect_spectrogram": inspect_spectrogram,
        "record_panel": record_panel,
        "session_dir_field": session_dir_field,
        "dataset_id_field": dataset_id_field,
        "shard_frames_field": shard_frames_field,
        "aligned_field": aligned_field,
        "recording_progress": recording_progress,
        "recording_validation": recording_validation,
        "future_panel": future_panel,
        "future_summary": future_summary,
    }
    window._guided_panel = panel

    def _refresh() -> None:
        current = workflow.current_stage
        crumbs = " > ".join(
            f"{stage.value.title()} [{workflow.status(stage).value}]"
            for stage in GUIDED_STAGE_ORDER
        )
        _set_widget_text(breadcrumb, crumbs)
        _set_widget_text(stage_title, f"Current stage: {current.value.title()}")
        current_findings = workflow.findings_for_stage(current)
        _set_widget_text(
            stage_status,
            f"Status: {workflow.current_status.value}"
            + (
                ""
                if not current_findings
                else " | " + " | ".join(item.message for item in current_findings)
            ),
        )
        setup_panel.visible = current is GuidedStage.SETUP
        validate_panel.visible = current is GuidedStage.VALIDATE
        run_panel.visible = current is GuidedStage.RUN
        inspect_panel.visible = current is GuidedStage.INSPECT
        record_panel.visible = current is GuidedStage.RECORD
        future_panel.visible = current is GuidedStage.EXPORT
        chosen = window.controller.state.guided_preset_id
        preset = next((item for item in SAFE_PRESETS if item.preset_id == chosen), None)
        _set_widget_text(
            setup_summary,
            "No preset applied."
            if preset is None
            else f"{preset.label}: {preset.summary}",
        )
        findings = workflow.findings_for_stage(GuidedStage.VALIDATE)
        _set_widget_text(
            findings_summary,
            "Validation clean."
            if not findings
            and workflow.status(GuidedStage.VALIDATE).value == "complete"
            else f"{len(findings)} validation issue(s).",
        )
        for index, row in enumerate(finding_rows):
            visible = index < len(findings)
            row["row"].visible = visible
            if not visible:
                _set_widget_text(row["label"], "")
                continue
            finding = findings[index]
            field = finding.field or (
                "stage" if finding.check_id == "stage_present" else "guided_stage"
            )
            _set_widget_text(row["label"], f"{field}: {finding.message}")
            _set_widget_text(
                row["button"], workflow.recovery_action(finding).label
            )
        run_status = window.controller.guided_run_status
        _set_widget_text(
            run_lifecycle,
            "Lifecycle: "
            f"{run_status.lifecycle} | configured={run_status.configured} | "
            f"running={run_status.running} | stopped={run_status.stopped}",
        )
        _set_widget_text(
            run_frames,
            f"Observed frames: {run_status.frame_count} | "
            f"last timestamp: {run_status.last_timestamp_ms}",
        )
        summary = window.controller.guided_inspect_summary()
        _set_widget_text(
            inspect_summary,
            "Frame: "
            f"{summary['latest_frame_id'] or 'none'} | "
            f"timestamp={summary['latest_timestamp_ms']} | "
            f"detections={summary['detection_count']} | "
            f"backend={summary['backend']} | "
            f"capabilities={summary['capability_generation']}",
        )
        compass = compass_view_model(
            bearing_deg=window.controller.state.latest_bearing_deg,
            candidate_bearings=window.controller.state.latest_candidate_bearings,
            sector=window.controller.state.latest_sector,
            confidence=window.controller.state.latest_bearing_confidence,
            occluded=window.controller.state.latest_occluded,
        )
        _set_widget_text(inspect_compass, f"Bearing: {compass.summary}")
        meters = meter_view_models(window.controller.state.latest_aggregate_rms)
        _set_widget_text(
            inspect_meters,
            "Per-mic RMS: "
            + (" | ".join(meter.text for meter in meters) or "none"),
        )
        _set_widget_text(
            inspect_spectrogram,
            "Spectrogram: "
            + (
                "available"
                if window.controller.state.latest_waveform_paths
                else "unavailable"
            ),
        )
        recording = window.controller.guided_recording_status
        _set_model_value(
            session_dir_field.model,
            window.controller.state.guided_session_dir,
        )
        _set_model_value(
            dataset_id_field.model,
            window.controller.state.guided_dataset_id,
        )
        _set_model_value(
            shard_frames_field.model,
            str(window.controller.state.guided_shard_max_frames),
        )
        _set_model_value(
            aligned_field.model,
            window.controller.state.guided_record_aligned,
        )
        _set_widget_text(
            recording_progress,
            f"Recording: {'active' if recording.active else 'idle'} | "
            f"episode={recording.current_episode or 'none'} | "
            f"frames={recording.frames} | dropped={recording.dropped_frames} | "
            f"shards={recording.shards_promoted} | bytes={recording.bytes_written}",
        )
        report = window.controller.guided_dataset_validation_report
        _set_widget_text(
            recording_validation,
            "Validation: not run"
            if report is None
            else f"Validation: {report.status} | "
            f"errors={report.error_count} | warnings={report.warning_count}",
        )
        _set_widget_text(
            future_summary,
            "Export is delivered in Run C.",
        )

    window._refresh_guided_section = _refresh
    _refresh()


def build_stage_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Stage"):
        window._labels["stage"] = ui.Label("", word_wrap=True)
        with ui.HStack(spacing=4):
            window._button(
                "Refresh",
                window.controller.refresh_stage_selection,
            )
            window._button(
                "Use Array",
                window.controller.use_selected_as_array,
            )
            window._button(
                "Use Source",
                window.controller.use_selected_as_source,
            )
            window._button(
                "Use Object",
                window.controller.use_selected_as_object,
            )
            window._button(
                "Use Base",
                window.controller.use_selected_as_robot_base,
            )
        window._bool_row("Follow Selection", "follow_viewport_selection")
        window._string_row("Discovery Roots", "discovery_roots_text")
        window._string_row("Robot/Base", "robot_base_prim_path")
        window._string_row("Object", "object_prim_path")
        with window.ui.HStack(spacing=4):
            window._button(
                "Create Demo Object",
                window.controller.create_demo_object,
            )
        window._labels["object"] = ui.Label("", word_wrap=True)
        window._button(
            "Discover",
            window.controller.refresh_discovery,
        )
        window._labels["discovery"] = ui.Label("", word_wrap=True)


def build_array_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Author Array"):
        window._string_row("Target Prim", "array_prim_path")
        window._string_row("Array ID", "array_id")
        window._combo_row("Layout", "layout_name", LAYOUT_CHOICES)
        window._int_row("Sample Rate", "sample_rate_hz")
        ui.Label(f"Convention: {window.controller.state.coordinate_convention}")
        window._bool_row("Child Mics", "author_child_microphones")
        window._button(
            "Create/Attach Array",
            window.controller.author_array,
        )
        window._string_row("Rig Profile ID", "selected_rig_profile_id")
        window._labels["rig_profile"] = ui.Label("", word_wrap=True)
        with ui.HStack(spacing=4):
            window._button(
                "Select Rig Profile",
                window.controller.select_rig_profile,
            )
            window._button(
                "Apply Rig Profile",
                window.controller.apply_selected_rig_profile,
            )
        window._float_row("Array Pos X", "array_position_x_m")
        window._float_row("Array Pos Y", "array_position_y_m")
        window._float_row("Array Pos Z", "array_position_z_m")
        window._float_row("Array Yaw", "array_yaw_deg")
        window._float_row("Array Pitch", "array_pitch_deg")
        window._float_row("Array Roll", "array_roll_deg")
        window._bool_row("Live Sync Pose", "live_sync_array_pose")
        with ui.HStack(spacing=4):
            window._button(
                "Read Array Transform",
                window.controller.read_selected_array_transform,
            )
            window._button(
                "Apply Array Pose",
                window.controller.apply_array_pose,
            )
        window._float_row("Array Offset X", "array_local_offset_x_m")
        window._float_row("Array Offset Y", "array_local_offset_y_m")
        window._float_row("Array Offset Z", "array_local_offset_z_m")
        window._float_row("Array Local Yaw", "array_local_yaw_deg")
        window._float_row("Array Local Pitch", "array_local_pitch_deg")
        window._float_row("Array Local Roll", "array_local_roll_deg")
        with ui.HStack(spacing=4):
            window._button(
                "Attach Array To Object",
                window.controller.attach_array_to_object,
            )
            window._button(
                "Detach Array",
                window.controller.detach_array_from_object,
            )
        window._labels["array_latest"] = ui.Label("", word_wrap=True)


def build_source_section(window: OmniReferenceWindow) -> None:
    with window._section("Author Source"):
        window._string_row("Target Prim", "source_prim_path")
        window._string_row("Source ID", "source_id")
        window._string_row("Class", "source_class_label")
        window._string_row("Audio URI", "audio_asset_path")
        window._string_row("Directivity", "source_directivity")
        window._string_row("Profile ID", "selected_profile_id")
        window._labels["profile"] = window.ui.Label("", word_wrap=True)
        with window.ui.HStack(spacing=4):
            window._button(
                "Select Profile",
                window.controller.select_sound_profile,
            )
            window._button(
                "Auto From Object",
                window.controller.auto_select_profile_from_object,
            )
            window._button(
                "Apply Profile",
                window.controller.apply_selected_profile,
            )
        window._float_row("Position X", "source_position_x_m")
        window._float_row("Position Y", "source_position_y_m")
        window._float_row("Position Z", "source_position_z_m")
        window._float_row("Local Offset X", "source_local_offset_x_m")
        window._float_row("Local Offset Y", "source_local_offset_y_m")
        window._float_row("Local Offset Z", "source_local_offset_z_m")
        window._bool_row("Live Sync Pose", "live_sync_source_pose")
        with window.ui.HStack(spacing=4):
            window._button(
                "Read Selected Transform",
                window.controller.read_selected_source_transform,
            )
            window._button(
                "Apply Position",
                window.controller.apply_source_position,
            )
        with window.ui.HStack(spacing=4):
            window._button(
                "Front",
                lambda: window.controller.apply_source_position_preset("front"),
            )
            window._button(
                "Right",
                lambda: window.controller.apply_source_position_preset("right"),
            )
            window._button(
                "Left",
                lambda: window.controller.apply_source_position_preset("left"),
            )
            window._button(
                "Behind",
                lambda: window.controller.apply_source_position_preset("behind"),
            )
        window._float_row("Start", "source_start_time_s")
        window._float_row("Duration", "source_duration_s")
        window._float_row("Gain dB", "source_gain_db")
        window._button(
            "Create/Attach Source",
            window.controller.author_source,
        )
        with window.ui.HStack(spacing=4):
            window._button(
                "Attach Source To Object",
                window.controller.attach_source_to_object,
            )
            window._button(
                "Detach Source",
                window.controller.detach_source_from_object,
            )


def build_control_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Sensor"):
        window._combo_row("Backend", "backend", BACKEND_CHOICES)
        window._combo_row("Ambiguity", "ambiguity_policy", AMBIGUITY_POLICY_CHOICES)
        window._float_row("Period s", "update_period_s")
        window._int_row("Max Events", "max_events")
        window._bool_row("Overlay", "debug_overlay_enabled")
        window._bool_row("Occlusion", "occlusion_enabled")
        window._bool_row("USD Debug", "usd_debug_enabled")
        window._string_row("Debug Root", "usd_debug_root")
        window._bool_row("JSONL", "trace_enabled")
        window._string_row("Writer Path", "jsonl_trace_path")
        with ui.HStack(spacing=4):
            window._button(
                "Start",
                window.controller.start_sensor,
            )
            window._button("Stop", window.controller.stop_sensor)
            window._button(
                "Update",
                window.controller.update_sensor,
            )
        with ui.HStack(spacing=4):
            window._button(
                "Clear Debug Geometry",
                window.controller.clear_usd_debug_geometry,
            )
        window._labels["latest"] = ui.Label("", word_wrap=True)
        window._labels["overlay"] = ui.Label("", word_wrap=True)
        window._labels["usd_debug"] = ui.Label("", word_wrap=True)
        window._labels["omnigraph"] = ui.Label("", word_wrap=True)


def build_room_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Room"):
        window._string_row("Anchor Prim", "room_anchor_prim_path")
        window._combo_row(
            "Out Of Bounds",
            "room_out_of_bounds",
            ROOM_OUT_OF_BOUNDS_CHOICES,
        )
        ui.Label(
            "Anchor derives the room from the prim's world bounding box; "
            "leave empty to center the default room on the array.",
            word_wrap=True,
        )
        window._labels["room"] = ui.Label("", word_wrap=True)


def build_replicator_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Replicator"):
        window._bool_row("Enable", "replicator_enabled")
        window._string_row("Output Dir", "replicator_output_dir")
        window._string_row("Writer", "replicator_writer_name")
        window._string_row("Annotator", "replicator_annotator_name")
        with ui.HStack(spacing=4):
            window._button(
                "Start",
                window.controller.start_replicator,
            )
            window._button(
                "Flush",
                window.controller.flush_replicator,
            )
            window._button(
                "Stop",
                window.controller.stop_replicator,
            )
        window._labels["replicator"] = ui.Label("", word_wrap=True)


def build_export_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._section("Export"):
        window._string_row("Latest JSON", "latest_frame_export_path")
        window._string_row("Config JSON", "config_export_path")
        window._string_row("Load Config", "config_import_path")
        with ui.HStack(spacing=4):
            window._button(
                "Export Latest",
                window.controller.export_latest_frame,
            )
            window._button(
                "Export Config",
                window.controller.export_config_summary,
            )
            window._button(
                "Load Config",
                window.controller.import_config_summary,
            )


def build_instruments_section(window: OmniReferenceWindow) -> None:
    """Build the compass, per-mic RMS meters, and detection timeline."""

    ui = window.ui
    with window._section("Instruments"):
        with ui.HStack(spacing=8, height=0):
            with ui.VStack(spacing=4, width=0):
                provider = None
                compass_image = None
                provider_cls = getattr(ui, "ByteImageProvider", None)
                image_cls = getattr(ui, "ImageWithProvider", None)
                if provider_cls is not None and image_cls is not None:
                    provider = provider_cls()
                    compass_image = image_cls(
                        provider,
                        width=COMPASS_IMAGE_SIZE,
                        height=COMPASS_IMAGE_SIZE,
                    )
                window._labels["compass"] = ui.Label("no bearing", word_wrap=True)
            with ui.VStack(spacing=2, height=0):
                ui.Label("Per-mic RMS")
                progress_cls = getattr(ui, "ProgressBar", None)
                meter_rows: list[dict[str, object]] = []
                for _ in range(METER_MAX_ROWS):
                    with ui.HStack(spacing=4, height=0) as meter_row:
                        label = ui.Label("", width=150)
                        bar = progress_cls() if progress_cls is not None else None
                    meter_row.visible = False
                    meter_rows.append({"row": meter_row, "label": label, "bar": bar})
        ui.Label("Detection timeline (newest first)")
        timeline_labels: list[object] = []

        def _build_timeline_rows() -> None:
            for _ in range(TIMELINE_MAX_ROWS):
                row_label = ui.Label("")
                row_label.visible = False
                timeline_labels.append(row_label)

        scrolling_cls = getattr(ui, "ScrollingFrame", None)
        if scrolling_cls is None:
            with ui.VStack(spacing=1, height=0):
                _build_timeline_rows()
        else:
            with scrolling_cls(height=140), ui.VStack(spacing=1, height=0):
                _build_timeline_rows()
    window._instruments = {
        "compass": compass_image,
        "compass_provider": provider,
        "meters": meter_rows,
        "timeline": timeline_labels,
    }


def build_audio_output_section(window: OmniReferenceWindow) -> None:
    """Build the waveform/spectrogram preview and audition controls."""

    ui = window.ui
    with window._section("Audio Output"):
        window._bool_row("WAV Export", "waveform_enabled")
        window._string_row("WAV Dir", "waveform_dir")
        window._combo_row("WAV Mode", "waveform_mode", WAVEFORM_MODE_CHOICES)
        window._labels["waveform"] = ui.Label("", word_wrap=True)
        waveform_provider = None
        spectrogram_provider = None
        provider_cls = getattr(ui, "ByteImageProvider", None)
        image_cls = getattr(ui, "ImageWithProvider", None)
        if provider_cls is not None and image_cls is not None:
            waveform_provider = provider_cls()
            image_cls(
                waveform_provider,
                width=WAVEFORM_IMAGE_WIDTH,
                height=WAVEFORM_IMAGE_HEIGHT,
            )
            spectrogram_provider = provider_cls()
            image_cls(
                spectrogram_provider,
                width=SPECTROGRAM_IMAGE_WIDTH,
                height=SPECTROGRAM_IMAGE_HEIGHT,
            )
        with ui.HStack(spacing=4):
            window._button("Play", window.controller.play_latest_waveform)
            window._button("Stop Audio", window.controller.stop_audition)
            window._button("Open WAV Folder", window.controller.open_waveform_folder)
        window._labels["audition"] = ui.Label("", word_wrap=True)
    window._audio_panel = {
        "waveform_provider": waveform_provider,
        "spectrogram_provider": spectrogram_provider,
        "rendered_path": None,
    }
