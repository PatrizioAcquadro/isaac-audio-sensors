# ruff: noqa: F403, F405

from isaac_audio_sensors.kit.constants import GUIDED_COLLAPSED_SETTING
from isaac_audio_sensors.kit.workflow import GuidedStage, RecordingStatus

from ._kit_ui_support import *


def test_top_level_accordions_persist_guided_and_keep_status_fixed(monkeypatch):
    env = _install_fake_kit_integrations(monkeypatch)
    controller = ExtensionController()

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    guided = window._section_frames["Guided Workflow"]
    live = window._section_frames["Live Monitor"]
    advanced = window._section_frames["Advanced Tools"]
    assert guided.collapsed is False
    assert live.collapsed is False
    assert advanced.collapsed is True

    advanced.collapsed = False
    assert guided.collapsed is True
    assert env.settings.get(GUIDED_COLLAPSED_SETTING) is True

    status_parent = window._labels["status"].parent
    while status_parent is not None:
        assert status_parent.kind != "ScrollingFrame"
        status_parent = status_parent.parent

    second = ExtensionController()
    assert second.build_ui_if_available() is not None
    second_window = second._lifecycle._ui_window
    assert second_window is not None
    second_guided = second_window._section_frames["Guided Workflow"]
    second_advanced = second_window._section_frames["Advanced Tools"]
    assert second_guided.collapsed is True

    second_guided.collapsed = False
    assert second_advanced.collapsed is True
    assert env.settings.get(GUIDED_COLLAPSED_SETTING) is False


def test_guided_setting_fallback_and_disabled_mode(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    broken_settings = ModuleType("carb.settings")
    broken_settings.get_settings = lambda: (_ for _ in ()).throw(RuntimeError())
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    monkeypatch.setitem(sys.modules, "carb.settings", broken_settings)

    controller = ExtensionController()
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    assert window._section_frames["Guided Workflow"].collapsed is False

    hidden = ExtensionController()
    hidden.state.guided_mode_enabled = False
    assert hidden.build_ui_if_available() is not None
    hidden_window = hidden._lifecycle._ui_window
    assert hidden_window is not None
    assert hidden_window._sections == ["Live Monitor", "Advanced Tools"]
    assert "Guided Workflow" not in hidden_window._section_frames


def test_compact_selection_controls_dispatch_existing_controller_actions(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    calls = []
    monkeypatch.setattr(
        controller,
        "use_selected_as_object",
        lambda: calls.append("object"),
    )
    monkeypatch.setattr(
        controller,
        "apply_source_position_preset",
        lambda preset: calls.append(preset),
    )

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    window._stage_binding_combo.model.set_value(2)
    bind_button = next(
        widget
        for widget in omni_ui.created
        if widget.kind == "Button" and widget.text == "Bind Selected"
    )
    bind_button.kwargs["clicked_fn"]()
    window._position_preset_combo.model.set_value(3)
    preset_button = next(
        widget
        for widget in omni_ui.created
        if widget.kind == "Button" and widget.text == "Apply Position Preset"
    )
    preset_button.kwargs["clicked_fn"]()

    assert calls == ["object", "behind"]


def test_live_sensor_button_reuses_guided_run_lifecycle(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    calls = []
    controller.guided_workflow.current_stage = GuidedStage.RUN

    def _start():
        calls.append("start")
        controller.state.sensor_running = True

    def _stop():
        calls.append("stop")
        controller.state.sensor_running = False

    monkeypatch.setattr(controller, "guided_start_run", _start)
    monkeypatch.setattr(controller, "guided_stop_run", _stop)
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    button = window._instruments["sensor_button"]

    button.kwargs["clicked_fn"]()
    assert button.text == "Stop Sensor"
    button.kwargs["clicked_fn"]()

    assert calls == ["start", "stop"]
    assert button.text == "Start Sensor"


def test_live_ux_screenshot_uses_viewport_utility_capture(monkeypatch, tmp_path):
    path = tmp_path / "utility.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    def capture_viewport_to_file(_viewport: object, *, file_path: str) -> object:
        _write_test_png(Path(file_path), width=31, height=19)
        return SimpleNamespace(wait_for_result=lambda: "done")

    env = _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        utility_capture=capture_viewport_to_file,
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(
        path,
        framed_paths=("/World/Oven", "/World/Oven/SpeakerA"),
    )

    assert record["status"] == "captured"
    assert record["path"] == str(path)
    assert record["method"] == "viewport_utility.capture_viewport_to_file"
    assert record["width"] == 31
    assert record["height"] == 19
    assert record["file_size_bytes"] > 0
    assert record["viewport_api_type"] == "SimpleNamespace"
    assert record["camera_path"] == "/World/Camera"
    assert record["framed_paths"] == ["/World/Oven", "/World/Oven/SpeakerA"]
    assert env.framed == [("/World/Oven", "/World/Oven/SpeakerA")]
    assert record["attempts"][0]["method"] == "viewport_utility.frame_viewport_prims"
    assert record["attempts"][1]["method"] == (
        "viewport_utility.capture_viewport_to_file"
    )


def test_live_ux_screenshot_falls_back_to_legacy_capture(monkeypatch, tmp_path):
    path = tmp_path / "legacy.viewport.png"

    class LegacyViewport:
        camera_path = SimpleNamespace(pathString="/World/LegacyCamera")

        def capture_to_file(self, file_path: str) -> object:
            _write_test_png(Path(file_path), width=23, height=29)
            return SimpleNamespace(wait=lambda: "done")

    _install_viewport_modules(monkeypatch, viewport=LegacyViewport())
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "viewport.capture_to_file"
    assert record["width"] == 23
    assert record["height"] == 29
    methods = [attempt["method"] for attempt in record["attempts"]]
    assert methods == [
        "viewport_utility.capture_viewport_to_file",
        "viewport.capture_to_file",
    ]


def test_live_ux_screenshot_waits_for_scheduled_kit_capture(monkeypatch, tmp_path):
    path = tmp_path / "scheduled.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    class App:
        updates = 0

        def update(self) -> None:
            self.updates += 1
            if self.updates == 3:
                _write_test_png(path, width=37, height=39)

    def capture_viewport_to_file(_viewport: object, *, file_path: str) -> object:
        assert file_path == str(path)
        return SimpleNamespace(wait_for_result=lambda: None)

    app = App()
    _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        utility_capture=capture_viewport_to_file,
        app=app,
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "viewport_utility.capture_viewport_to_file"
    assert record["width"] == 37
    assert record["height"] == 39
    assert record["attempts"][0]["file_wait"] == {"status": "ready", "updates": 3}


def test_live_ux_screenshot_falls_back_to_renderer_capture(monkeypatch, tmp_path):
    path = tmp_path / "renderer.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    class RendererCapture:
        def capture_next_frame_swapchain(self, file_path: str) -> object:
            _write_test_png(Path(file_path), width=41, height=43)
            return "scheduled"

        def wait_async_capture(self) -> object:
            return "done"

    _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        renderer=RendererCapture(),
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "renderer_capture.capture_next_frame_swapchain"
    assert record["width"] == 41
    assert record["height"] == 43
    methods = [attempt["method"] for attempt in record["attempts"]]
    assert methods == [
        "viewport_utility.capture_viewport_to_file",
        "viewport.capture_to_file",
        "renderer_capture.capture_next_frame_swapchain",
    ]


def test_live_ux_screenshot_records_no_active_viewport(monkeypatch, tmp_path):
    path = tmp_path / "missing.viewport.png"
    _install_viewport_modules(monkeypatch, viewport=None)
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "unavailable"
    assert record["path"] == str(path)
    assert record["reason"] == "no active viewport"
    assert record["file_size_bytes"] == 0
    assert record["width"] is None
    assert record["height"] is None
    assert record["attempts"] == []


def test_kit_builds_against_fake_omni_ui(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    window = controller.build_ui_if_available()

    assert window is not None
    assert controller.ui_available is True
    assert controller._lifecycle._ui_window is not None
    assert set(controller._lifecycle._ui_window._combo_fields) == {
        "ambiguity_policy",
        "backend",
        "layout_name",
        "room_out_of_bounds",
        "selected_profile_id",
        "selected_rig_profile_id",
        "waveform_mode",
    }
    assert set(controller._lifecycle._ui_window._int_fields) == {
        "max_events",
        "sample_rate_hz",
        "source_loop_count",
    }
    assert set(controller._lifecycle._ui_window._float_fields) == {
        "array_position_x_m",
        "array_position_y_m",
        "array_position_z_m",
        "array_yaw_deg",
        "array_pitch_deg",
        "array_roll_deg",
        "array_local_offset_x_m",
        "array_local_offset_y_m",
        "array_local_offset_z_m",
        "array_local_yaw_deg",
        "array_local_pitch_deg",
        "array_local_roll_deg",
        "source_local_offset_x_m",
        "source_local_offset_y_m",
        "source_local_offset_z_m",
        "source_position_x_m",
        "source_position_y_m",
        "source_position_z_m",
        "source_duration_s",
        "source_gain_db",
        "source_start_time_s",
        "update_period_s",
    }
    assert set(controller._lifecycle._ui_window._bool_fields) == {
        "author_child_microphones",
        "debug_overlay_enabled",
        "follow_viewport_selection",
        "live_sync_array_pose",
        "live_sync_source_pose",
        "occlusion_enabled",
        "replicator_enabled",
        "trace_enabled",
        "usd_debug_enabled",
        "waveform_enabled",
    }
    assert "replicator_enabled" in controller._lifecycle._ui_window._bool_fields
    assert "replicator_output_dir" in controller._lifecycle._ui_window._string_fields
    assert "array_prim_path" in controller._lifecycle._ui_window._string_fields
    assert "source_prim_path" in controller._lifecycle._ui_window._string_fields
    assert "source_directivity" in controller._lifecycle._ui_window._string_fields
    assert "selected_profile_id" in controller._lifecycle._ui_window._combo_fields
    assert "selected_rig_profile_id" in controller._lifecycle._ui_window._combo_fields
    assert "object_prim_path" in controller._lifecycle._ui_window._string_fields
    assert "latest_frame_export_path" in controller._lifecycle._ui_window._string_fields
    assert {
        widget.kind
        for widget in controller._lifecycle._ui_window._float_fields.values()
    } == {"FloatDrag"}
    assert {
        widget.kind for widget in controller._lifecycle._ui_window._int_fields.values()
    } == {"IntDrag"}
    assert controller._lifecycle._ui_window._sections == [
        "Guided Workflow",
        "Live Monitor",
        "Advanced Tools",
    ]

    scrolling_frames = [
        widget for widget in omni_ui.created if widget.kind == "ScrollingFrame"
    ]
    assert len(scrolling_frames) == 1
    timeline_container = controller._lifecycle._ui_window._instruments[
        "timeline_container"
    ]
    assert timeline_container.kind == "VStack"
    assert timeline_container.kwargs["height"] == 0
    collapsable_frames = [
        widget for widget in omni_ui.created if widget.kind == "CollapsableFrame"
    ]
    assert [widget.text for widget in collapsable_frames] == [
        "Guided Workflow",
        "Live Monitor",
        "Advanced Tools",
        "Stage & Selection",
        "Microphone Array",
        "Audio Source",
        "Sensor Settings & Debug",
        "Room Acoustics",
        "Sensor WAV Output",
        "Kit Scene Audition",
        "Replicator",
        "Export & Config",
    ]
    for frame in collapsable_frames:
        assert [child.kind for child in frame.children] == ["VStack"]

    button_labels = {
        widget.text for widget in omni_ui.created if widget.kind == "Button"
    }
    assert {
        "Refresh Selection",
        "Bind Selected",
        "Create Demo Object",
        "Discover Sensors",
        "Create/Attach Array",
        "Apply Rig Profile",
        "Read Array Transform",
        "Apply Array Pose",
        "Attach Array To Object",
        "Detach Array",
        "Read Selected Transform",
        "Apply Position",
        "Auto From Object",
        "Apply Profile",
        "Apply Position Preset",
        "Create/Attach Source",
        "Attach Source To Object",
        "Detach Source",
        "Start Sensor",
        "Capture Once",
        "Play Sensor WAV",
        "Stop Sensor WAV",
        "Open Sensor WAV Folder",
        "Activate Array Listener",
        "Restore Previous Listener",
        "Start Kit Mix Capture",
        "Stop Kit Mix Capture",
        "Start Replicator",
        "Flush Replicator",
        "Stop Replicator",
        "Export Latest Frame",
        "Export Config",
        "Load Config",
    } <= button_labels
    assert button_labels == set(controller._lifecycle._ui_window._buttons)
    assert {
        "Use Array",
        "Use Source",
        "Use Object",
        "Use Base",
        "Select Rig Profile",
        "Select Profile",
        "Front",
        "Right",
        "Left",
        "Behind",
        "Start Guided Run",
        "Stop Guided Run",
    }.isdisjoint(button_labels)


def test_kit_instruments_show_compass_meters_and_timeline(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    controller.state.latest_frame_id = "frame_001"
    controller.state.latest_detection_count = 1
    controller.state.latest_backend = "tdoa_synthetic"
    controller.state.latest_source_prim_path = "/World/Sources/SpeakerA"
    controller.state.latest_source_position_m = (1.0, 2.0, 0.0)
    controller.state.latest_bearing_deg = 90.0
    controller.state.latest_sector = "right"
    controller.state.latest_bearing_confidence = 0.8
    controller.state.latest_occluded = False
    controller.state.latest_aggregate_rms = {
        "left": 0.2,
        "front": 0.24,
        "rear": 0.18,
        "right": 0.22,
    }
    controller.state.detection_history = [
        {
            "frame_id": "frame_001",
            "timestamp_ms": 1500,
            "source_id": "speaker_a",
            "class_label": "speech_generic",
            "bearing_deg": 90.0,
            "sector": "right",
            "occluded": False,
        }
    ]

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    window.refresh_labels()

    latest = window._labels["latest"].text
    assert "Frame: frame_001" in latest
    assert "detections=1" in latest

    assert window._labels["compass_bearing"].text == "90.0 deg"
    assert window._labels["compass_sector"].text == "right"
    assert window._labels["compass_confidence"].text == "0.80"
    assert window._labels["compass_occlusion"].text == "Clear"
    provider = window._instruments["compass_provider"]
    assert provider.size == [192, 192]
    assert len(provider.data) == 192 * 192 * 4

    visible_meters = [
        row for row in window._instruments["meters"] if row["row"].visible
    ]
    assert [row["label"].text.split(":")[0] for row in visible_meters] == [
        "front",
        "right",
        "rear",
        "left",
    ]
    fractions = [row["fill"].width for row in visible_meters]
    assert all(0.0 < fraction <= 1.0 for fraction in fractions)
    assert fractions[0] == max(fractions)
    assert all(row["value"].text.endswith(" dB") for row in visible_meters)
    assert all("%" not in row["value"].text for row in visible_meters)
    assert window._instruments["meter_min_label"].text == "-60"
    assert window._instruments["meter_min_label"].kwargs["alignment"] == "center"
    assert window._instruments["meter_min_label"].kwargs["width"] == 48
    assert window._instruments["meter_max_label"].text == "0"
    assert window._instruments["meter_max_label"].kwargs["alignment"] == "center"
    assert window._instruments["meter_max_label"].kwargs["width"] == 48
    hidden_meters = [
        row for row in window._instruments["meters"] if not row["row"].visible
    ]
    assert hidden_meters

    timeline = [
        label.text for label in window._instruments["timeline"] if label.visible
    ]
    assert len(timeline) == 1
    assert "speech_generic" in timeline[0]
    assert "90.0 deg" in timeline[0]
    assert "clear" in timeline[0]


@pytest.mark.parametrize(
    ("mic_count", "detection_count"),
    [(0, 0), (4, 3), (8, 5)],
)
def test_live_monitor_bounds_meters_and_recent_detections(
    monkeypatch,
    mic_count,
    detection_count,
):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    if mic_count:
        controller.state.latest_frame_id = "frame_live"
        controller.state.latest_aggregate_rms = {
            f"mic_{index}": 0.1 + index * 0.01 for index in range(mic_count)
        }
    controller.state.detection_history = [
        {
            "frame_id": f"frame_{index}",
            "timestamp_ms": index * 10,
            "source_id": f"source_{index}",
            "class_label": "speech",
            "bearing_deg": float(index),
            "sector": "front",
            "occluded": False,
        }
        for index in range(detection_count)
    ]
    controller.state.latest_detection_count = detection_count

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    window.refresh_labels()

    visible_meters = [
        row for row in window._instruments["meters"] if row["row"].visible
    ]
    assert len(visible_meters) == mic_count
    visible_detections = [
        row for row in window._instruments["timeline"] if row.visible
    ]
    assert len(visible_detections) == min(detection_count, 3)
    assert window._instruments["empty"].visible is (mic_count == 0)
    assert window._instruments["detection_empty"].visible is (
        mic_count > 0 and detection_count == 0
    )
    assert window._instruments["sensor_button"].text == "Start Sensor"
    controller.state.sensor_running = True
    window.refresh_labels()
    assert window._instruments["sensor_button"].text == "Stop Sensor"
    assert "Active" in window._labels["live_status"].text


def test_live_monitor_freshness_and_footer_priority(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    now = [100.0]
    window._clock = lambda: now[0]
    controller.state.sensor_running = True
    controller.state.latest_frame_id = "frame_technical_identifier"
    controller.state.latest_timestamp_ms = 5000
    window.refresh_labels()

    assert window._labels["live_frame"].text == "Updated just now"
    assert window._labels["status_icon"].text == "ACTIVE"

    now[0] += 0.042
    window.refresh_labels()

    assert window._labels["live_frame"].text == "Updated 42 ms ago"
    assert "frame 42 ms ago" in window._labels["status"].text
    assert "frame_technical_identifier" in window._labels["latest"].text

    now[0] += 0.558
    window.refresh_labels()

    assert window._labels["status_icon"].text == "WARNING"
    assert "frame stale 600 ms ago" in window._labels["status"].text

    controller.guided_workflow._recording_status = RecordingStatus(
        active=True,
        dataset_id="guided_run",
        frames=12,
        dropped_frames=1,
    )
    window.refresh_labels()

    assert window._labels["status_icon"].text == "RECORDING"
    assert window._labels["status"].text == "guided_run · 12 frames · 1 dropped"

    controller.state.error_message = "Sensor failed: stage missing"
    window.refresh_labels()

    assert window._labels["status_icon"].text == "ERROR"
    assert window._labels["status"].text.startswith(
        "Sensor Settings & Debug > Diagnostics — Sensor failed"
    )

    controller.state.error_message = None
    controller.guided_workflow._recording_status = RecordingStatus()
    controller.state.sensor_running = False
    controller.state.status_message = "Window shown."
    window.refresh_labels()

    assert window._labels["status_icon"].text == "READY"
    assert window._labels["status"].text == "Ready for setup."


def test_advanced_field_styles_track_auto_fill_and_manual_edit(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    field = window._float_fields["source_duration_s"]

    assert field.style["border_color"] == 0xFF4A4541
    assert window._labels["latest"].style["color"] == 0xFFAAA6A2

    def _auto_fill() -> None:
        controller.state.source_duration_s = 2.5

    window._action(
        _auto_fill,
        action_label="Read Selected Transform",
        section="Audio Source",
    )()

    assert field.style["border_color"] == 0xFFD2782E

    field.model.set_value("3.0")

    assert controller.state.source_duration_s == 3.0
    assert field.style["border_color"] == 0xFF4A4541


def test_kit_audio_panel_renders_waveform_preview(monkeypatch, tmp_path):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    wav_path = tmp_path / "frame_000001.wav"
    wav_path.write_bytes(_float32_wav_bytes())
    controller.state.latest_waveform_paths = (str(wav_path),)

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    window.refresh_labels()

    label = window._labels["waveform"].text
    assert "frame_000001.wav" in label
    assert "1 ch" in label
    assert "8000 Hz" in label
    panel = window._audio_panel
    assert panel["rendered_path"] == str(wav_path)
    assert panel["waveform_provider"].size == [420, 96]
    assert panel["spectrogram_provider"].size == [420, 128]
    assert window._labels["audition"].text == "Sensor WAV audition idle."
    assert window._labels["kit_mix_kind"].text == (
        "Kit listener/device mix — qualitative, not microphone-array channels"
    )
    assert window._labels["kit_listener"].text == "Kit listener idle."
    assert window._labels["kit_mix_capture"].text == "Kit mix capture idle."


def test_kit_audio_panel_reports_missing_waveform(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    window.refresh_labels()

    assert "No waveform yet" in window._labels["waveform"].text


def test_kit_invalid_numeric_input_is_readable(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    called = False

    def _callback() -> None:
        nonlocal called
        called = True

    window._float_fields["source_duration_s"].model.set_value("not-a-number")
    window._action(_callback)()

    assert called is False
    assert controller.state.error_message is not None
    assert "UI input failed" in controller.state.error_message
    assert window._labels["status"].text == (
        "Audio Source > Duration — Invalid numeric value 'not-a-number'. "
        "Enter a number, then retry."
    )
    assert "not-a-number" in window._labels["diagnostic"].text
    invalid_style = window._float_fields["source_duration_s"].style
    assert invalid_style["border_color"] == 0xFF616AEF

    window._float_fields["source_duration_s"].model.set_value("2.5")

    assert controller.state.error_message is None
    assert window._labels["status"].text == "Corrected Duration."
    corrected_style = window._float_fields["source_duration_s"].style
    assert corrected_style["border_color"] == 0xFF4A4541


def test_extension_controller_reports_visible_errors_without_raising():
    controller = ExtensionController()

    result = controller.start_sensor(subscribe_to_update_stream=False)

    assert result is None
    assert controller.state.error_message is not None
    assert "Sensor configure failed" in controller.state.error_message
