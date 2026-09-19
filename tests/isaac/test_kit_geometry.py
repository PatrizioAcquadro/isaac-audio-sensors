"""Real USD/native configuration and controller-owned scene lifecycle."""

import numpy as np
import pytest

pytest.importorskip("pxr")

from isaac_audio_sensors.kit.acoustic_scene import AcousticScenePanel  # noqa: E402
from isaac_audio_sensors.kit.controller import ExtensionController  # noqa: E402
from isaac_audio_sensors.kit.state import CurrentStageContext  # noqa: E402
from tests.isaac.geometry_helpers import SPECULAR_LIBRARY  # noqa: E402
from tests.isaac.test_geometry_nlos import LIBRARY, fixture_scene  # noqa: E402


@pytest.fixture
def controller():
    if not LIBRARY.exists() or not SPECULAR_LIBRARY.exists():
        pytest.skip("Qualified native libraries are required")
    stage, _ = fixture_scene()
    from pxr import UsdGeom

    UsdGeom.Xform.Define(stage, "/World/Emitter").AddTranslateOp().Set((2, 0, 1.2))
    host = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage)
    )
    state = host.state
    state.backend = "geometry_acoustics"
    state.environment_resolution_mode = "manual_free_field"
    state.geometry_library_path = str(LIBRARY)
    state.geometry_specular_library_path = str(SPECULAR_LIBRARY)
    state.geometry_reflection_order = 1
    state.geometry_max_delay_s = 0.1
    state.geometry_diagnostics = True
    state.geometry_nlos_probe_spacing_m = 0.5
    state.geometry_diffuse_rays = 256
    state.geometry_diffuse_surface_spacing_m = 0.5
    state.geometry_roots = "/Floor /Screen"
    state.source_prim_path = "/World/Emitter/Sound"
    state.source_position_z_m = 1.2
    state.array_position_x_m = -2
    state.array_position_z_m = 1.2
    state.audio_asset_path = "generated://tone"
    state.trace_enabled = False
    assert host.author_array(stage=stage), state.error_message
    assert host.apply_array_pose(stage=stage), state.error_message
    assert host.author_source(stage=stage), state.error_message
    yield host, stage
    host._geometry.close()


@pytest.mark.parametrize(
    "nlos,diffuse,discovery",
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, False),
    ],
)
def test_controller_geometry_configuration_and_pcm(
    controller, nlos, diffuse, discovery
):
    host, stage = controller
    host.state.geometry_nlos_enabled = nlos
    host.state.geometry_diffuse_enabled = diffuse
    prepared = host._geometry.prepare(stage)
    if discovery:
        host.state.array_prim_path = ""
    sensor = host.configure_sensor(stage=stage)
    assert sensor is not None, host.state.error_message
    assert sensor.acoustic_scene is prepared
    assert host.start_sensor(subscribe_to_update_stream=False), host.state.error_message
    frame = sensor.capture(start_time_s=0, end_time_s=0.1, usd_time_code=0)
    host._sensor_session._record_latest_frame(frame)
    assert np.isfinite(sensor.latest_signal_block.samples).all()
    assert host.state.latest_geometry_diagnostics
    assert "PCM active" in host._geometry.status_text()
    panel = AcousticScenePanel(None, host._geometry)
    panel.close()
    assert not prepared.closed
    sensor.capture(start_time_s=0.1, end_time_s=0.2, usd_time_code=0)
    old_producer = sensor._propagation_backend
    host.close_sensor()
    assert old_producer.closed and not prepared.closed
    host._geometry.close()
    assert prepared.closed
    assert not host.state.latest_geometry_diagnostics


def test_reconfigure_failure_clears_old_results(controller):
    host, stage = controller
    sensor = host.configure_sensor(stage=stage)
    assert sensor, host.state.error_message
    host._sensor_session._record_latest_frame(
        sensor.capture(start_time_s=0, end_time_s=0.1)
    )
    producer = sensor._propagation_backend
    host.state.geometry_library_path = "/missing/provider.so"
    assert host.configure_sensor(stage=stage) is None
    assert producer.closed
    assert host.sensor is None
    assert host.state.latest_frame is None
    assert not host.state.latest_geometry_diagnostics
    assert host.state.error_message


def test_scene_replacement_closes_borrowing_producer_first(controller):
    host, stage = controller
    sensor = host.configure_sensor(stage=stage)
    assert sensor, host.state.error_message
    sensor.capture(start_time_s=0, end_time_s=0.1)
    producer, old = sensor._propagation_backend, host._geometry.session
    host._geometry.prepare(stage, ("/Floor",))
    assert producer.closed and old.closed and host.sensor is None
    assert host._geometry.session.roots == ("/Floor",)


@pytest.mark.parametrize("failure", ["nlos_abi", "floor_coverage"])
def test_enabled_capability_failures_are_actionable(controller, failure):
    from tests.isaac.geometry_helpers import LIBRARY as DIRECT_LIBRARY

    host, stage = controller
    host.state.geometry_nlos_enabled = True
    if failure == "nlos_abi":
        host.state.geometry_library_path = str(DIRECT_LIBRARY)
    else:
        host.state.geometry_roots = "/Screen"
    assert host.configure_sensor(stage=stage) is None
    assert host.sensor is None
    assert host.state.error_message
    assert any(
        word in host.state.error_message.lower()
        for word in ("extension", "probe", "floor")
    )
    assert not host.state.latest_geometry_diagnostics


def test_pending_settings_require_configure_and_analytic_stays_available(controller):
    host, stage = controller
    sensor = host.configure_sensor(stage=stage)
    assert sensor, host.state.error_message
    prepared = sensor.acoustic_scene
    host.state.geometry_reflection_order = 0
    assert host.start_sensor(subscribe_to_update_stream=False) is None
    assert "Configure" in host.state.error_message
    host.state.backend = "analytic_acoustics"
    sensor = host.configure_sensor(stage=stage)
    assert sensor, host.state.error_message
    assert sensor.backend == "analytic_acoustics"
    assert not prepared.closed
    sensor.capture(start_time_s=0, end_time_s=0.1)
