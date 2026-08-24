"""Section builders for the Isaac Audio Sensors reference window."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constants import (
    AMBIGUITY_POLICY_CHOICES,
    BACKEND_CHOICES,
    LAYOUT_CHOICES,
    ROOM_OUT_OF_BOUNDS_CHOICES,
    SOURCE_POSITION_PRESETS,
    WAVEFORM_MODE_CHOICES,
)
from .instruments import (
    COMPASS_IMAGE_SIZE,
    METER_MAX_ROWS,
    compass_view_model,
    meter_view_models,
)
from .spectro import (
    SPECTROGRAM_IMAGE_HEIGHT,
    SPECTROGRAM_IMAGE_WIDTH,
    WAVEFORM_IMAGE_HEIGHT,
    WAVEFORM_IMAGE_WIDTH,
)
from .ui_models import _combo_index, _set_model_value, _set_widget_text, _ui_fraction
from .workflow import GUIDED_STAGE_ORDER, SAFE_PRESETS, GuidedStage, StageStatus

if TYPE_CHECKING:
    from .window import OmniReferenceWindow


_GUIDED_STEP_STYLES = {
    "complete": {
        "background_color": 0xFF315A3A,
        "color": 0xFFD7F3DD,
        "border_color": 0xFF4F9B62,
        "border_width": 1,
        "margin": 5,
    },
    "current": {
        "background_color": 0xFF5D3922,
        "color": 0xFFF4E3D5,
        "border_color": 0xFFD2782E,
        "border_width": 2,
        "margin": 5,
    },
    "blocked": {
        "background_color": 0xFF382426,
        "color": 0xFFF2D7D7,
        "border_color": 0xFF616AEF,
        "border_width": 2,
        "margin": 5,
    },
    "upcoming": {
        "background_color": 0xFF292725,
        "color": 0xFF8E8A86,
        "border_color": 0xFF3E3A37,
        "border_width": 1,
        "margin": 5,
    },
}


def _alignment(ui: Any, name: str) -> Any:
    """Return an omni.ui alignment while keeping lightweight UI fakes usable."""

    return getattr(getattr(ui, "Alignment", None), name, name.lower())


def _guided_prompt(window: OmniReferenceWindow, stage: GuidedStage) -> str:
    workflow = window.controller.guided_workflow
    status = workflow.status(stage)
    findings = workflow.findings_for_stage(stage)
    if findings:
        recovery = workflow.recovery_action(findings[0]).label
        suffix = "" if len(findings) == 1 else f" · {len(findings)} issues"
        return f"{recovery} to continue{suffix}."
    if status is StageStatus.BLOCKED:
        return "Review this step, then retry."
    if status is StageStatus.COMPLETE:
        return f"{stage.value.title()} complete. Continue when ready."
    if stage is GuidedStage.SETUP:
        return "Apply a safe preset to continue."
    if stage is GuidedStage.VALIDATE:
        return "Run validation to continue."
    if stage is GuidedStage.RUN:
        run = window.controller.guided_run_status
        if run.running:
            return f"Sensor running · {run.frame_count} frames observed."
        return "Start the sensor in Live Monitor."
    if stage is GuidedStage.INSPECT:
        if not window.controller.state.latest_frame_id:
            return "Capture a frame before inspection."
        return "Review the latest frame, then mark it inspected."
    if stage is GuidedStage.RECORD:
        recording = window.controller.guided_recording_status
        if recording.active:
            return (
                f"Recording · {recording.frames} frames · "
                f"{recording.dropped_frames} dropped."
            )
        return "Start recording to continue."
    return "Choose a destination, then export the dataset."


def build_guided_section(window: OmniReferenceWindow) -> None:
    """Build the complete guided Setup-through-Export workflow."""

    ui = window.ui
    workflow = window.controller.guided_workflow
    workflow.on_change = window.refresh_labels
    preset_ids = tuple(preset.preset_id for preset in SAFE_PRESETS)
    preset_labels = tuple(preset.label for preset in SAFE_PRESETS)
    selected_id = window.controller.state.guided_preset_id
    selected_index = preset_ids.index(selected_id) if selected_id in preset_ids else 0

    with ui.VStack(spacing=5, height=0) as root:
        step_labels: dict[GuidedStage, Any] = {}
        step_frames: dict[GuidedStage, Any] = {}
        with ui.HStack(spacing=4, height=26):
            for index, stage in enumerate(GUIDED_STAGE_ORDER, start=1):
                indicator = ui.ZStack(
                    width=_ui_fraction(ui, 1),
                    height=24,
                )
                with indicator:
                    background = ui.Rectangle()
                    step_labels[stage] = ui.Label(
                        f"{index} {stage.value.title()}",
                        height=24,
                        alignment=_alignment(ui, "CENTER"),
                        tooltip=stage.value.title(),
                    )
                step_frames[stage] = background
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
                "Apply Safe Preset",
                lambda: window.controller.guided_apply_preset(
                    window.controller.state.guided_preset_id or preset_ids[0]
                ),
                kind="primary",
            )
            setup_summary = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as validate_panel:
            window._button(
                "Validate Setup",
                window.controller.guided_validate,
                kind="primary",
            )
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
            ui.Label(
                "Use the canonical Start Sensor control in Live Monitor.",
                word_wrap=True,
            )
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
                kind="primary",
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
                start_recording_button = window._button(
                    "Start Recording",
                    lambda: window.controller.guided_start_recording(
                        window.controller.state.guided_session_dir,
                        window.controller.state.guided_dataset_id,
                        window.controller.state.guided_shard_max_frames,
                        window.controller.state.guided_record_aligned,
                    ),
                    kind="primary",
                )
                stop_recording_button = window._button(
                    "Stop & Finalize",
                    window.controller.guided_stop_recording,
                    kind="primary",
                )
                cancel_recording_button = window._button(
                    "Cancel",
                    window.controller.guided_cancel_recording,
                    kind="danger",
                )
            recording_progress = ui.Label("", word_wrap=True)
            recording_validation = ui.Label("", word_wrap=True)
        with ui.VStack(spacing=4, height=0) as export_panel:
            window._string_row("Export Dir", "guided_export_dir")
            export_dir_field = window._string_fields.pop("guided_export_dir")
            window._bool_row("Apply TVT Split", "guided_split_enabled")
            split_enabled_field = window._bool_fields.pop("guided_split_enabled")
            window._float_row("Train Ratio", "guided_split_train_ratio")
            train_ratio_field = window._float_fields.pop(
                "guided_split_train_ratio"
            )
            window._float_row("Validation Ratio", "guided_split_validation_ratio")
            validation_ratio_field = window._float_fields.pop(
                "guided_split_validation_ratio"
            )
            window._float_row("Test Ratio", "guided_split_test_ratio")
            test_ratio_field = window._float_fields.pop(
                "guided_split_test_ratio"
            )
            window._int_row("Split Seed", "guided_session_seed")
            split_seed_field = window._int_fields.pop("guided_session_seed")
            window._button(
                "Export Dataset",
                lambda: window.controller.guided_export(
                    window.controller.state.guided_export_dir
                ),
                kind="primary",
            )
            export_summary = ui.Label("", word_wrap=True)
            inventory_summary = ui.Label("", word_wrap=True)
            inventory_totals = ui.Label("", word_wrap=True)
        with ui.HStack(spacing=4, height=0):
            back_button = window._button("Back", window.controller.guided_back)
            continue_button = window._button(
                "Continue",
                window.controller.guided_advance,
            )

    panel = {
        "root": root,
        "step_labels": step_labels,
        "step_frames": step_frames,
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
        "start_recording_button": start_recording_button,
        "stop_recording_button": stop_recording_button,
        "cancel_recording_button": cancel_recording_button,
        "export_panel": export_panel,
        "export_dir_field": export_dir_field,
        "split_enabled_field": split_enabled_field,
        "train_ratio_field": train_ratio_field,
        "validation_ratio_field": validation_ratio_field,
        "test_ratio_field": test_ratio_field,
        "split_seed_field": split_seed_field,
        "export_summary": export_summary,
        "inventory_summary": inventory_summary,
        "inventory_totals": inventory_totals,
        "back_button": back_button,
        "continue_button": continue_button,
    }
    window._guided_panel = panel

    def _refresh() -> None:
        current = workflow.current_stage
        for stage, label in step_labels.items():
            status = workflow.status(stage)
            style_name = (
                "blocked"
                if stage is current and status is StageStatus.BLOCKED
                else (
                    "current"
                    if stage is current
                    else (
                        "complete"
                        if status is StageStatus.COMPLETE
                        else "upcoming"
                    )
                )
            )
            style = _GUIDED_STEP_STYLES[style_name]
            step_frames[stage].style = dict(style)
            label.style = {"color": style["color"], "margin": 5}
            label.tooltip = f"{stage.value.title()}: {status.value.replace('_', ' ')}"
        _set_widget_text(stage_title, current.value.title())
        _set_widget_text(stage_status, _guided_prompt(window, current))
        setup_panel.visible = current is GuidedStage.SETUP
        validate_panel.visible = current is GuidedStage.VALIDATE
        run_panel.visible = current is GuidedStage.RUN
        inspect_panel.visible = current is GuidedStage.INSPECT
        record_panel.visible = current is GuidedStage.RECORD
        export_panel.visible = current is GuidedStage.EXPORT
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
        start_recording_button.visible = not recording.active
        stop_recording_button.visible = recording.active
        cancel_recording_button.visible = recording.active
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
            window.controller.state.guided_shard_max_frames,
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
        state = window.controller.state
        _set_model_value(export_dir_field.model, state.guided_export_dir)
        _set_model_value(split_enabled_field.model, state.guided_split_enabled)
        _set_model_value(train_ratio_field.model, state.guided_split_train_ratio)
        _set_model_value(
            validation_ratio_field.model,
            state.guided_split_validation_ratio,
        )
        _set_model_value(test_ratio_field.model, state.guided_split_test_ratio)
        _set_model_value(split_seed_field.model, state.guided_session_seed)
        export = window.controller.guided_export_status
        _set_widget_text(
            export_summary,
            "Export: not run"
            if export.destination_dir is None
            else f"Export: {export.validation_status or 'in progress'} | "
            f"split={export.split_status} | destination={export.destination_dir}"
            + (f" | {export.note}" if export.note else ""),
        )
        inventory = window.controller.guided_output_inventory()
        _set_widget_text(
            inventory_summary,
            "Output inventory: none"
            if not inventory
            else "Output inventory:\n"
            + "\n".join(
                f"{item['path']} | {item['kind']} | {item['bytes']} bytes | "
                f"sha256={item['sha256']}"
                for item in inventory
            ),
        )
        _set_widget_text(
            inventory_totals,
            f"Totals: {export.inventory_entries} files | "
            f"{export.inventory_bytes} bytes",
        )
        back_button.visible = current is not GuidedStage.SETUP
        continue_button.visible = current is not GuidedStage.EXPORT

    window._refresh_guided_section = _refresh
    _refresh()


def build_live_monitor_section(window: OmniReferenceWindow) -> None:
    """Build the primary sensor lifecycle and live evidence surface."""

    ui = window.ui
    with ui.VStack(spacing=4, height=0):
        def _toggle_sensor() -> None:
            state = window.controller.state
            guided_run = (
                state.guided_mode_enabled
                and window.controller.guided_workflow.current_stage
                is GuidedStage.RUN
            )
            if state.sensor_running:
                if guided_run:
                    window.controller.guided_stop_run()
                else:
                    window.controller.stop_sensor()
            elif guided_run:
                window.controller.guided_start_run()
            else:
                window.controller.start_sensor()

        with ui.HStack(spacing=8, height=0):
            ui.Label("Sensor", width=86)
            window._readonly_label("live_status")
            sensor_button = window._button(
                "Start Sensor",
                _toggle_sensor,
                kind="primary",
                width=160,
            )
        for label, key in (
            ("Backend", "live_backend"),
            ("Last frame", "live_frame"),
            ("Detections", "live_detections"),
            ("Waveform", "live_waveform"),
        ):
            with ui.HStack(spacing=8, height=0):
                ui.Label(label, width=86)
                window._readonly_label(key)
        build_instruments_section(window)
        window._instruments["sensor_button"] = sensor_button


def build_advanced_section(window: OmniReferenceWindow) -> None:
    """Build specialist controls behind one advanced accordion."""

    build_stage_section(window)
    build_array_section(window)
    build_source_section(window)
    build_control_section(window)
    build_room_section(window)
    build_audio_output_section(window)
    build_kit_audio_section(window)
    build_replicator_section(window)
    build_export_section(window)


def build_stage_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._subsection("Stage & Selection", collapsed=False):
        window._readonly_label("stage")
        binding_roles = (
            ("Microphone Array", window.controller.use_selected_as_array),
            ("Audio Source", window.controller.use_selected_as_source),
            ("Object", window.controller.use_selected_as_object),
            ("Robot Base", window.controller.use_selected_as_robot_base),
        )
        with ui.HStack(spacing=4):
            window._button(
                "Refresh Selection",
                window.controller.refresh_stage_selection,
            )
        with ui.HStack(spacing=4):
            ui.Label("Bind selection as", width=120)
            binding_combo = ui.ComboBox(
                0,
                *(label for label, _action in binding_roles),
                width=220,
            )

            def _bind_selected() -> None:
                selected = _combo_index(binding_combo.model)
                if 0 <= selected < len(binding_roles):
                    binding_roles[selected][1]()

            window._button("Bind Selected", _bind_selected)
            window._stage_binding_combo = binding_combo
        window._bool_row("Follow Selection", "follow_viewport_selection")
        window._string_row("Discovery Roots", "discovery_roots_text")
        window._string_row("Robot/Base", "robot_base_prim_path")
        window._string_row("Object", "object_prim_path")
        with window.ui.HStack(spacing=4):
            window._button(
                "Create Demo Object",
                window.controller.create_demo_object,
            )
        window._readonly_label("object")
        window._button(
            "Discover Sensors",
            window.controller.refresh_discovery,
        )
        window._readonly_label("discovery")


def build_array_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._subsection("Microphone Array"):
        window._string_row("Target Prim", "array_prim_path")
        window._string_row("Array ID", "array_id")
        window._combo_row("Layout", "layout_name", LAYOUT_CHOICES)
        window._int_row("Sample Rate", "sample_rate_hz")
        window._readonly_label(
            "array_convention",
            f"Convention: {window.controller.state.coordinate_convention}",
        )
        window._bool_row("Child Mics", "author_child_microphones")
        window._button(
            "Create/Attach Array",
            window.controller.author_array,
        )
        rig_profile_ids = tuple(
            profile.profile_id
            for profile in window.controller.state.rig_profile_library
        )
        window._combo_row(
            "Rig Profile",
            "selected_rig_profile_id",
            rig_profile_ids,
        )
        window._readonly_label("rig_profile")
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
        window._readonly_label("array_latest")


def build_source_section(window: OmniReferenceWindow) -> None:
    with window._subsection("Audio Source"):
        window._string_row("Target Prim", "source_prim_path")
        window._string_row("Source ID", "source_id")
        window._string_row("Class", "source_class_label")
        window._string_row("Audio URI", "audio_asset_path")
        window._string_row("Directivity", "source_directivity")
        profile_ids = tuple(
            profile.profile_id for profile in window.controller.state.profile_library
        )
        window._combo_row("Sound Profile", "selected_profile_id", profile_ids)
        window._readonly_label("profile")
        with window.ui.HStack(spacing=4):
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
        position_presets = tuple(SOURCE_POSITION_PRESETS)
        with window.ui.HStack(spacing=4):
            window.ui.Label("Position Preset", width=120)
            preset_combo = window.ui.ComboBox(0, *position_presets, width=220)

            def _apply_position_preset() -> None:
                selected = _combo_index(preset_combo.model)
                if 0 <= selected < len(position_presets):
                    window.controller.apply_source_position_preset(
                        position_presets[selected]
                    )

            window._button("Apply Position Preset", _apply_position_preset)
            window._position_preset_combo = preset_combo
        window._float_row("Start", "source_start_time_s")
        window._float_row("Duration", "source_duration_s")
        window._float_row("Gain dB", "source_gain_db")
        window._int_row("Additional Loops", "source_loop_count")
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
    with window._subsection("Sensor Settings & Debug"):
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
        window._button(
            "Capture Once",
            window.controller.update_sensor,
        )
        with ui.HStack(spacing=4):
            window._button(
                "Clear Debug Geometry",
                window.controller.clear_usd_debug_geometry,
            )
        window._readonly_label("latest")
        window._readonly_label("overlay")
        window._readonly_label("usd_debug")
        window._readonly_label("omnigraph")
        ui.Label("Diagnostics")
        window._readonly_label("diagnostic")


def build_room_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._subsection("Room Acoustics"):
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
        window._readonly_label("room")


def build_replicator_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._subsection("Replicator"):
        window._bool_row("Enable", "replicator_enabled")
        window._string_row("Output Dir", "replicator_output_dir")
        window._string_row("Writer", "replicator_writer_name")
        window._string_row("Annotator", "replicator_annotator_name")
        with ui.HStack(spacing=4):
            window._button(
                "Start Replicator",
                window.controller.start_replicator,
            )
            window._button(
                "Flush Replicator",
                window.controller.flush_replicator,
            )
            window._button(
                "Stop Replicator",
                window.controller.stop_replicator,
            )
        window._readonly_label("replicator")


def build_export_section(window: OmniReferenceWindow) -> None:
    ui = window.ui
    with window._subsection("Export & Config"):
        window._string_row("Latest JSON", "latest_frame_export_path")
        window._string_row("Config JSON", "config_export_path")
        window._string_row("Load Config", "config_import_path")
        with ui.HStack(spacing=4):
            window._button(
                "Export Latest Frame",
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
    with ui.VStack(spacing=5, height=0):
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
                for label, key in (
                    ("Bearing", "compass_bearing"),
                    ("Sector", "compass_sector"),
                    ("Confidence", "compass_confidence"),
                    ("Occlusion", "compass_occlusion"),
                ):
                    with ui.HStack(spacing=4, height=0):
                        ui.Label(label, width=82)
                        value = window._readonly_label(key)
                        if key == "compass_bearing":
                            window._labels["compass"] = value
            with ui.VStack(spacing=3, height=0):
                ui.Label("Per-mic RMS (dBFS)")
                with ui.HStack(spacing=4, height=0):
                    ui.Spacer(width=48)
                    with ui.HStack(spacing=0, height=0):
                        meter_min_label = ui.Label(
                            "-60",
                            width=48,
                            alignment=_alignment(ui, "CENTER"),
                        )
                        ui.Spacer(width=_ui_fraction(ui, 1))
                        meter_max_label = ui.Label(
                            "0",
                            width=48,
                            alignment=_alignment(ui, "CENTER"),
                        )
                    ui.Spacer(width=48)
                meter_rows: list[dict[str, object]] = []
                for _ in range(METER_MAX_ROWS):
                    with ui.HStack(spacing=4, height=0) as meter_row:
                        label = ui.Label("", width=72)
                        fill = None
                        remaining = None
                        rectangle_cls = getattr(ui, "Rectangle", None)
                        zstack_cls = getattr(ui, "ZStack", None)
                        if rectangle_cls is not None and zstack_cls is not None:
                            with zstack_cls(height=14):
                                rectangle_cls(
                                    style={"background_color": 0xFF312C27}
                                )
                                with ui.HStack(spacing=0, height=14):
                                    fill = rectangle_cls(
                                        width=_ui_fraction(ui, 0),
                                        style={"background_color": 0xFF8CC14F},
                                    )
                                    remaining = ui.Spacer(width=_ui_fraction(ui, 1))
                        value = ui.Label("", width=72)
                    meter_row.visible = False
                    meter_rows.append(
                        {
                            "row": meter_row,
                            "label": label,
                            "fill": fill,
                            "remaining": remaining,
                            "value": value,
                        }
                    )
        empty_label = ui.Label("", word_wrap=True)
        ui.Spacer(height=7)
        ui.Label("Recent detections")
        timeline_labels: list[object] = []

        def _build_timeline_rows() -> None:
            for _ in range(3):
                row_label = ui.Label("")
                row_label.visible = False
                timeline_labels.append(row_label)

        with ui.VStack(spacing=1, height=0) as timeline_container:
            _build_timeline_rows()
        detection_empty_label = ui.Label("No recent detections.")
    window._instruments = {
        "compass": compass_image,
        "compass_provider": provider,
        "meter_min_label": meter_min_label,
        "meter_max_label": meter_max_label,
        "meters": meter_rows,
        "timeline": timeline_labels,
        "timeline_container": timeline_container,
        "detection_empty": detection_empty_label,
        "empty": empty_label,
    }


def build_audio_output_section(window: OmniReferenceWindow) -> None:
    """Build microphone-array WAV preview and playback controls."""

    ui = window.ui
    with window._subsection("Sensor WAV Output"):
        window._bool_row("WAV Export", "waveform_enabled")
        window._string_row("WAV Dir", "waveform_dir")
        window._combo_row("WAV Mode", "waveform_mode", WAVEFORM_MODE_CHOICES)
        window._readonly_label("waveform")
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
            window._button("Play Sensor WAV", window.controller.play_latest_waveform)
            window._button("Stop Sensor WAV", window.controller.stop_audition)
            window._button(
                "Open Sensor WAV Folder", window.controller.open_waveform_folder
            )
        window._readonly_label("audition")
    window._audio_panel = {
        "waveform_provider": waveform_provider,
        "spectrogram_provider": spectrogram_provider,
        "rendered_path": None,
    }


def build_kit_audio_section(window: OmniReferenceWindow) -> None:
    """Build separate Kit scene-listener audition and mix-capture actions."""

    with window._subsection("Kit Scene Audition"):
        window._readonly_label("kit_mix_kind")
        window._readonly_label("kit_timeline_policy")
        with window.ui.HStack(spacing=4):
            window._button(
                "Activate Array Listener", window.controller.activate_kit_listener
            )
            window._button(
                "Restore Previous Listener",
                window.controller.restore_previous_kit_listener,
            )
        window._readonly_label("kit_listener")
        with window.ui.HStack(spacing=4):
            window._button(
                "Start Kit Mix Capture", window.controller.start_kit_mix_capture
            )
            window._button(
                "Stop Kit Mix Capture", window.controller.stop_kit_mix_capture
            )
        window._readonly_label("kit_mix_capture")
