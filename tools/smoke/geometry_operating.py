"""Bounded Geometry sensor-to-instrument scenario for the actual Kit gate."""


def run_geometry_operating(controller, library, specular_library, output):
    import time

    import numpy as np
    import omni.kit.app
    import omni.usd
    from kit_capture import _capture_app_screenshot
    from pxr import Sdf, UsdGeom, UsdLux

    from isaac_audio_sensors.core.directivity import DirectivityPattern
    from isaac_audio_sensors.kit.instruments import meter_view_models
    from isaac_audio_sensors.kit.state import CurrentStageContext

    context = omni.usd.get_context()
    context.new_stage()
    stage = context.get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdLux.DomeLight.Define(stage, "/Lighting/Sky").CreateIntensityAttr(500)
    UsdLux.DistantLight.Define(stage, "/Lighting/Sun").CreateIntensityAttr(1000)
    for name, position, scale in (
        ("Floor", (0, 0, -0.05), (6, 6, 0.1)),
        ("Screen", (0, 0, 1.5), (0.02, 1.2, 3)),
        ("RearWall", (0, 2, 1.5), (6, 0.02, 3)),
    ):
        cube = UsdGeom.Cube.Define(stage, f"/Acoustics/{name}")
        cube.CreateSizeAttr(1)
        cube.AddTranslateOp().Set(position)
        cube.AddScaleOp().Set(scale)
        for attr, value in (("ias:absorption", 0.4), ("ias:scattering", 0.35)):
            cube.GetPrim().CreateAttribute(attr, Sdf.ValueTypeNames.Float).Set(value)
        if name == "Screen":
            cube.GetPrim().CreateAttribute(
                "ias:acoustic_dynamic", Sdf.ValueTypeNames.Token
            ).Set("dynamic")
    controller.close_sensor()
    controller.stage_context_provider = lambda: CurrentStageContext(stage)
    state = controller.state
    state.backend = "geometry_acoustics"
    state.sample_rate_hz = 16000
    state.layout_name = "quad_front"
    state.array_yaw_deg = state.array_pitch_deg = state.array_roll_deg = 0.0
    state.source_directivity = DirectivityPattern.OMNI
    state.environment_resolution_mode = "manual_free_field"
    state.geometry_roots = "/Acoustics"
    state.geometry_library_path = str(library.resolve())
    state.geometry_specular_library_path = str(specular_library.resolve())
    state.geometry_nlos_enabled = state.geometry_diffuse_enabled = True
    state.geometry_nlos_probe_spacing_m = 0.5
    state.geometry_diffuse_rays = 4096
    state.geometry_diffuse_surface_spacing_m = 0.5
    state.geometry_reflection_order = 1
    state.geometry_max_delay_s = 0.1
    state.geometry_diagnostics = True
    state.array_prim_path = "/World/Array"
    state.array_attached_to_object = state.source_attached_to_object = False
    state.robot_base_prim_path = ""
    state.discovery_roots_text = "/World"
    state.array_position_x_m, state.array_position_y_m, state.array_position_z_m = (
        -2,
        0,
        1.2,
    )
    state.source_prim_path = "/World/Emitter/Sound"
    UsdGeom.Xform.Define(stage, "/World/Emitter").AddTranslateOp().Set((2, 0, 1.2))
    state.source_position_x_m, state.source_position_y_m, state.source_position_z_m = (
        2,
        0,
        1.2,
    )
    state.source_gain_db = 0
    state.source_start_time_s = 0
    state.source_duration_s = 3.6
    state.audio_asset_path = "generated://tone"
    state.trace_enabled = state.replicator_enabled = state.waveform_enabled = False
    state.doa_enabled = True
    state.energy_threshold_dbfs = -60
    state.occlusion_enabled = False
    assert controller.author_array(stage=stage), state.error_message
    assert controller.apply_array_pose(stage=stage), state.error_message
    assert controller.author_source(stage=stage), state.error_message
    # The parent supplies the position in both schema-loaded and plain USD runtimes.
    UsdGeom.Xformable(stage.GetPrimAtPath(state.source_prim_path)).ClearXformOpOrder()
    view = controller._lifecycle._ui_window
    view.push_state_to_widgets()
    panel = view._acoustic_scene_panel
    panel.import_scene()
    assert not panel.last_error, panel.last_error
    prepared = panel.session
    sensor = controller.configure_sensor(stage=stage)
    assert sensor is not None, state.error_message
    assert sensor.acoustic_scene is prepared
    controller.start_sensor(subscribe_to_update_stream=False)
    assert state.sensor_running, state.error_message
    door = stage.GetPrimAtPath("/Acoustics/Screen").GetAttribute("xformOp:translate")
    coverage, peaks, times, counts = [], [], [], []
    for tick in range(80):
        door.Set((0, 5 if 20 <= tick < 40 else 0, 1.5))
        started = time.perf_counter()
        frame = sensor.capture(
            start_time_s=tick / 20,
            end_time_s=(tick + 1) / 20,
            frame_index=tick,
            usd_time_code=0,
        )
        controller._sensor_session._record_latest_frame(frame)
        view.refresh_labels()
        times.append((time.perf_counter() - started) * 1000)
        diagnostic = state.latest_geometry_diagnostics
        assert diagnostic["domain"] == "direct+specular+diffuse+nlos"
        coverage.append(diagnostic["nlos"]["coverage"])
        peaks.append(float(np.max(abs(sensor.latest_signal_block.samples))))
        counts.append(len(frame.observations))
        assert meter_view_models(state.latest_aggregate_rms)
        if tick == 10:
            # Rebuilding the actual widgets must not close the borrowing producer.
            view.close()
            controller._lifecycle.window = view.build()
            assert view._acoustic_scene_panel.session is prepared
            assert not prepared.closed
        omni.kit.app.get_app().update()
        if tick == 30:
            active_screenshot = _capture_app_screenshot(
                output.with_suffix(".geometry-active.png")
            )
    states = [
        set(value for row in entry.values() for value in row) for entry in coverage
    ]
    assert (
        "selected" in states[10] and "los" in states[30] and "selected" in states[50]
    ), states
    assert any(counts), counts
    assert peaks[72] > 1e-6 and max(peaks[-4:]) < 1e-7, peaks[-10:]
    view._set_section_collapsed("Live Monitor", True)
    view._set_section_collapsed("Advanced Tools", False)
    for title, subsection in view._subsection_frames.items():
        subsection.collapsed = title not in {"Sensor Settings & Debug", "Geometry"}
    screenshot = _capture_app_screenshot(output.with_suffix(".geometry.png"))
    producer = sensor._propagation_backend
    controller.close_sensor()
    assert producer.closed and not prepared.closed
    state.geometry_specular_library_path = "/missing/pra.so"
    assert controller.configure_sensor(stage=stage) is None
    assert state.latest_frame is None and not state.latest_geometry_diagnostics
    state.geometry_specular_library_path = str(specular_library.resolve())
    assert controller.configure_sensor(stage=stage), state.error_message
    controller.sensor.reset()
    controller._sensor_session.invalidate_frame()
    controller.close_sensor()
    context.new_stage()
    omni.kit.app.get_app().update()
    assert prepared.closed and controller._geometry.session is None
    controller.stage_context_provider = None
    return dict(
        status="passed",
        simulated_seconds=4,
        observations=counts,
        peaks=peaks,
        mean_ms=float(np.mean(times)),
        p95_ms=float(np.percentile(times, 95)),
        widget_rebuild_preserves_session=True,
        stage_change_releases_session=True,
        configuration_failure_clears_results=True,
        source_stop_tail=True,
        coverage=coverage,
        screenshot=screenshot,
        active_screenshot=active_screenshot,
    )
