"""Section builders for the Isaac Audio Sensors reference window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import AMBIGUITY_POLICY_CHOICES, BACKEND_CHOICES, LAYOUT_CHOICES

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
