"""Section builders for the Isaac Audio Sensors reference window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import (
    AMBIGUITY_POLICY_CHOICES,
    BACKEND_CHOICES,
    LAYOUT_CHOICES,
    WAVEFORM_MODE_CHOICES,
)
from .instruments import COMPASS_IMAGE_SIZE, METER_MAX_ROWS, TIMELINE_MAX_ROWS
from .spectro import (
    SPECTROGRAM_IMAGE_HEIGHT,
    SPECTROGRAM_IMAGE_WIDTH,
    WAVEFORM_IMAGE_HEIGHT,
    WAVEFORM_IMAGE_WIDTH,
)

if TYPE_CHECKING:
    from .window import OmniReferenceWindow


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
        window._labels["latest"] = ui.Label("", word_wrap=True)
        window._labels["overlay"] = ui.Label("", word_wrap=True)


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
