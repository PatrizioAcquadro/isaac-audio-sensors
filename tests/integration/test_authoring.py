import sys
from types import ModuleType

import pytest

from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.sound_profiles import SoundProfile
from isaac_audio_sensors.kit.stage_context import _stage_has_prim
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import _FakePrim, _FakeStage


def test_non_omni_sound_profile_requires_orientation_before_mutation() -> None:
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    profile = SoundProfile(
        profile_id="directional",
        display_label="Directional",
        object_label_aliases=("speaker",),
        source_id_template="{object_slug}_source",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
        directivity="cardioid",
    )
    controller.state.profile_library = (profile,)
    controller.state.object_profile_mappings = {"speaker": "directional"}
    controller.state.selected_profile_id = "directional"
    original_source_id = controller.state.source_id

    assert controller.apply_selected_profile(stage=stage) is None
    assert controller.state.source_id == original_source_id
    assert stage.GetPrimAtPath(controller.state.source_prim_path) is None
    assert "orientation" in str(controller.state.error_message)


def test_kit_stage_has_prim_uses_sdf_path_for_strict_isaac_stage(
    monkeypatch,
):
    pxr = ModuleType("pxr")
    sdf = ModuleType("pxr.Sdf")

    class SdfPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    sdf.Path = SdfPath
    pxr.Sdf = sdf
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    monkeypatch.setitem(sys.modules, "pxr.Sdf", sdf)

    class StrictStage(_FakeStage):
        def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
            super().__init__(prims)
            self.calls: list[str] = []

        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            self.calls.append(type(path).__name__)
            if isinstance(path, str):
                raise TypeError("expected Sdf.Path")
            return super().GetPrimAtPath(str(path))

    stage = StrictStage((_FakePrim("/World/Room/Geometry/object", "Xform"),))

    assert _stage_has_prim(stage, "/World/Room/Geometry/object") is True
    assert stage.calls == ["SdfPath"]


def test_kit_stage_has_prim_falls_back_to_traverse_after_type_error():
    class RejectingStage(_FakeStage):
        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            raise TypeError(f"unsupported path type: {type(path).__name__}")

    stage = RejectingStage((_FakePrim("/World/Oven", "Xform"),))

    assert _stage_has_prim(stage, "/World/Oven") is True


def test_extension_controller_manual_profile_apply_authors_source_metadata():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),
            _FakePrim("/World/Sink", "Xform", {"xformOp:translate": (1, 0, 0)}),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.source_prim_path = "/World/Sources/SinkSpeaker"
    controller.state.source_position_x_m = 1.5
    controller.state.source_position_y_m = 0.25
    controller.state.source_position_z_m = 0.0
    controller.state.object_prim_path = "/World/Sink"
    controller.state.object_label = "Sink"
    controller.state.selected_profile_id = "sink_water"

    authored = controller.apply_selected_profile(stage=stage)

    assert authored is not None
    assert authored.kind == "source_profile"
    assert controller.state.source_prim_path == "/World/Sources/SinkSpeaker"
    assert controller.state.source_attached_to_object is False
    assert controller.state.source_id == "sink_source"
    assert controller.state.source_class_label == "Water"
    assert controller.state.audio_asset_path == "generated://pulse"
    assert controller.state.source_gain_db == -2.0
    source = stage.GetPrimAtPath("/World/Sources/SinkSpeaker")
    assert source is not None
    assert source.type_name == "OmniSound"
    assert "filePath" not in source.attributes
    assert source.attributes["ias:source_id"] == "sink_source"
    assert source.attributes["ias:class_label"] == "Water"
    assert source.attributes["ias:audio_asset_path"] == "generated://pulse"
    assert source.attributes["ias:start_time_s"] == 0.0
    assert source.attributes["ias:duration_s"] == 1.2
    assert source.attributes["ias:gain_db"] == -2.0
    assert source.attributes["loopCount"] == 0
    assert source.attributes["ias:directivity"] == "omni"
    assert source.attributes["ias:sound_profile_id"] == "sink_water"
    assert source.attributes["xformOp:translate"] == (1.5, 0.25, 0.0)
    assert controller.state.applied_source_profile["profile_id"] == "sink_water"


def test_extension_controller_auto_profile_match_uses_object_labels_and_aliases():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),
            _FakePrim(
                "/World/Kitchen/FixtureA",
                "Mesh",
                {
                    "xformOp:translate": (0, 0, 0),
                    "semantic:class": "Sink",
                },
            ),
            _FakePrim(
                "/World/Kitchen/Countertop",
                "Mesh",
                {"xformOp:translate": (0, 1, 0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )

    matched = controller.auto_select_profile_from_object(
        stage=stage,
        selected_paths=("/World/Kitchen/FixtureA",),
    )
    assert matched is not None
    assert matched.profile_id == "sink_water"
    assert controller.state.selected_profile_id == "sink_water"
    assert "Auto-selected" in controller.state.status_message

    controller.state.object_prim_path = ""
    controller.state.object_label = "none"
    controller.state.attached_object_prim_path = ""
    no_match = controller.auto_select_profile_from_object(
        stage=stage,
        selected_paths=("/World/Kitchen/Countertop",),
    )
    assert no_match is None
    assert controller.state.error_message is not None
    assert "No sound profile matches object labels" in controller.state.error_message


def test_extension_controller_profile_apply_preserves_attachment_and_frame_metadata(
    tmp_path,
):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Oven",),
        )
        == "/World/Oven"
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    controller.state.selected_profile_id = "oven_stove"
    applied = controller.apply_selected_profile(stage=stage)

    assert applied is not None
    assert controller.state.source_prim_path == "/World/Oven/SpeakerA"
    assert controller.state.source_attached_to_object is True
    assert controller.state.attached_object_prim_path == "/World/Oven"
    assert controller.state.source_id == "oven_source"
    source = stage.GetPrimAtPath("/World/Oven/SpeakerA")
    assert source is not None
    assert source.type_name == "OmniSound"
    assert "filePath" not in source.attributes
    assert source.attributes["ias:source_id"] == "oven_source"
    assert source.attributes["ias:class_label"] == "Appliance"
    assert source.attributes["ias:audio_asset_path"] == "generated://pulse"
    assert source.attributes["ias:attached_object_prim_path"] == "/World/Oven"
    assert source.attributes["ias:source_local_offset_m"] == (0.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (0.0, 0.0, 0.0)
    assert "ias:position_world" not in source.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    moved_frame = controller.update_sensor()

    assert first_frame is not None
    assert moved_frame is not None
    assert first_frame.observations == moved_frame.observations == ()
    assert moved_frame.aggregate_per_mic_rms != first_frame.aggregate_per_mic_rms
    assert source.attributes["ias:source_id"] == "oven_source"
    assert controller.state.latest_source_prim_path is None


def test_extension_controller_source_position_read_apply_presets_and_drag_update(
    tmp_path,
):
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (3.0, 1.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            source,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    read_position = controller.read_selected_source_transform(
        stage=stage,
        selected_paths=("/World/Sources/SpeakerA",),
    )
    assert read_position == (3.0, 1.0, 0.0)
    assert controller.state.source_position_x_m == 3.0
    assert controller.state.source_position_y_m == 1.0
    assert controller.state.source_position_z_m == 0.0

    controller.state.source_position_x_m = 4.0
    controller.state.source_position_y_m = 0.0
    controller.state.source_position_z_m = 0.0
    applied = controller.apply_source_position(stage=stage)
    assert applied is not None
    assert source.attributes["ias:position_world"] == (4.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (4.0, 0.0, 0.0)

    assert controller.apply_source_position_preset("front", stage=stage) is not None
    assert source.attributes["xformOp:translate"] == (2.0, 0.0, 0.0)
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    front_frame = controller.update_sensor()
    assert front_frame is not None
    assert front_frame.observations == ()

    assert controller.apply_source_position_preset("right", stage=stage) is not None
    right_frame = controller.update_sensor()
    assert right_frame is not None
    assert right_frame.observations == ()

    source.attributes["xformOp:translate"] = (0.0, -2.0, 0.0)
    moved_frame = controller.update_sensor()
    assert moved_frame is not None
    assert moved_frame.observations == ()
    assert moved_frame.aggregate_per_mic_rms != right_frame.aggregate_per_mic_rms
    assert source.attributes["xformOp:translate"] == (0.0, -2.0, 0.0)
    assert controller.state.latest_source_position_m is None


def test_extension_controller_attaches_source_to_object_and_motion_updates_frame(
    tmp_path,
):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Oven",),
        )
        == "/World/Oven"
    )
    attached = controller.attach_source_to_object(stage=stage)

    assert attached is not None
    assert attached.prim_path == "/World/Oven/SpeakerA"
    source = stage.GetPrimAtPath("/World/Oven/SpeakerA")
    assert source is not None
    assert source.attributes["ias:source_id"] == "speaker_a"
    assert source.attributes["ias:class_label"] == "Speech"
    assert source.attributes["ias:audio_asset_path"] == "generated://impulse"
    assert source.attributes["ias:attached_object_prim_path"] == "/World/Oven"
    assert source.attributes["ias:source_local_offset_m"] == (0.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (0.0, 0.0, 0.0)
    assert "ias:position_world" not in source.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    moved_frame = controller.update_sensor()

    assert first_frame is not None
    assert moved_frame is not None
    assert first_frame.observations == moved_frame.observations == ()
    assert moved_frame.aggregate_per_mic_rms != first_frame.aggregate_per_mic_rms
    assert controller.state.latest_source_prim_path is None
    assert controller.state.latest_source_position_m is None
    assert controller.state.latest_aggregate_rms == moved_frame.aggregate_per_mic_rms

    detached = controller.detach_source_from_object(stage=stage)
    assert detached is not None
    detached_source = stage.GetPrimAtPath("/World/Sources/SpeakerA")
    assert detached_source is not None
    assert stage.GetPrimAtPath("/World/Oven/SpeakerA") is None
    assert "ias:attached_object_prim_path" not in detached_source.attributes
    assert detached_source.attributes["ias:position_world"] == (0.0, 2.0, 0.0)
    assert detached_source.attributes["xformOp:translate"] == (0.0, 2.0, 0.0)

    oven.attributes["xformOp:translate"] = (5.0, 0.0, 0.0)
    after_detach_frame = controller.update_sensor()
    assert after_detach_frame is not None
    assert after_detach_frame.observations == ()
    assert detached_source.attributes["xformOp:translate"] == (0.0, 2.0, 0.0)


def test_extension_controller_array_pose_read_apply_and_drag_update(tmp_path):
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (2.0, 0.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            source,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    front_frame = controller.update_sensor()
    assert front_frame is not None
    assert front_frame.observations == ()
    assert controller.state.latest_array_position_m == (0.0, 0.0, 0.0)
    front_mics = dict(controller.state.latest_mic_world_positions)
    assert front_mics["front"] == pytest.approx((0.08, 0.0, 0.0))

    controller.state.array_yaw_deg = 90.0
    assert controller.apply_array_pose(stage=stage) is not None
    array_prim = stage.GetPrimAtPath("/World/Rig/AudioArray")
    assert array_prim is not None
    expected_quat = quaternion_from_yaw_deg(90.0)
    assert array_prim.attributes["ias:orientation_world_quat"] == pytest.approx(
        expected_quat
    )
    assert array_prim.attributes["xformOp:orient"] == pytest.approx(expected_quat)

    rotated_frame = controller.update_sensor()
    assert rotated_frame is not None
    assert rotated_frame.observations == ()
    assert rotated_frame.aggregate_per_mic_rms != front_frame.aggregate_per_mic_rms
    assert rotated_frame.array_pose is not None
    assert rotated_frame.array_pose.orientation_xyzw == pytest.approx(expected_quat)
    assert controller.state.latest_array_orientation_xyzw == pytest.approx(
        expected_quat
    )
    assert controller.state.latest_mic_world_positions != front_mics
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (0.0, 0.08, 0.0),
        abs=1e-9,
    )

    array_prim.attributes["xformOp:translate"] = (1.0, 1.0, 0.0)
    array_prim.attributes["xformOp:orient"] = (0.0, 0.0, 0.0, 1.0)
    dragged_frame = controller.update_sensor()
    assert dragged_frame is not None
    assert dragged_frame.array_pose is not None
    assert dragged_frame.array_pose.position_m == (1.0, 1.0, 0.0)
    assert dragged_frame.observations == ()
    assert array_prim.attributes["ias:position_world"] == (0.0, 0.0, 0.0)
    assert controller.state.latest_array_position_m == (1.0, 1.0, 0.0)
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (1.08, 1.0, 0.0)
    )

    read_position = controller.read_selected_array_transform(
        stage=stage,
        selected_paths=("/World/Rig/AudioArray",),
    )
    assert read_position == (1.0, 1.0, 0.0)
    assert controller.state.array_position_x_m == 1.0
    assert controller.state.array_position_y_m == 1.0
    assert controller.state.array_yaw_deg == pytest.approx(0.0)


def test_extension_controller_attaches_array_to_object_and_motion_updates_frame(
    tmp_path,
):
    mount_link = _FakePrim(
        "/World/Robot/mount_link",
        "Xform",
        {"xformOp:translate": (0.0, 0.0, 1.0)},
    )
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (2.0, 0.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            mount_link,
            source,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Robot/mount_link",),
        )
        == "/World/Robot/mount_link"
    )
    controller.state.array_local_offset_z_m = 0.1
    attached = controller.attach_array_to_object(stage=stage)

    assert attached is not None
    assert attached.prim_path == "/World/Robot/mount_link/AudioArray"
    assert controller.state.array_prim_path == "/World/Robot/mount_link/AudioArray"
    assert controller.state.array_attached_to_object is True
    array_prim = stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray")
    assert array_prim is not None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray") is None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/front") is None
    moved_mic = stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray/front")
    assert moved_mic is not None
    assert moved_mic.attributes["ias:microphone_id"] == "front"
    assert array_prim.attributes["ias:attached_object_prim_path"] == (
        "/World/Robot/mount_link"
    )
    assert array_prim.attributes["ias:array_local_offset_m"] == (0.0, 0.0, 0.1)
    assert array_prim.attributes["xformOp:translate"] == (0.0, 0.0, 0.1)
    assert "ias:position_world" not in array_prim.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    assert first_frame is not None
    assert first_frame.array_pose is not None
    assert first_frame.array_pose.position_m == pytest.approx((0.0, 0.0, 1.1))
    assert first_frame.observations == ()
    first_mics = dict(controller.state.latest_mic_world_positions)
    assert first_mics["front"] == pytest.approx((0.08, 0.0, 1.1))

    mount_link.attributes["xformOp:translate"] = (0.0, 2.0, 1.0)
    moved_frame = controller.update_sensor()
    assert moved_frame is not None
    assert moved_frame.array_pose is not None
    assert moved_frame.array_pose.position_m == pytest.approx((0.0, 2.0, 1.1))
    assert moved_frame.observations == ()
    assert moved_frame.aggregate_per_mic_rms != first_frame.aggregate_per_mic_rms
    assert controller.state.latest_array_position_m == pytest.approx((0.0, 2.0, 1.1))
    assert controller.state.latest_mic_world_positions != first_mics
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (0.08, 2.0, 1.1)
    )

    mount_link.attributes["xformOp:orient"] = quaternion_from_yaw_deg(90.0)
    rotated_frame = controller.update_sensor()
    assert rotated_frame is not None
    assert rotated_frame.array_pose is not None
    assert rotated_frame.array_pose.orientation_xyzw == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )
    assert rotated_frame.observations == ()

    detached = controller.detach_array_from_object(stage=stage)
    assert detached is not None
    detached_prim = stage.GetPrimAtPath("/World/AudioArrays/AudioArray")
    assert detached_prim is not None
    assert stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray") is None
    assert stage.GetPrimAtPath("/World/AudioArrays/AudioArray/front") is not None
    assert "ias:attached_object_prim_path" not in detached_prim.attributes
    assert detached_prim.attributes["ias:position_world"] == pytest.approx(
        (0.0, 2.0, 1.1)
    )
    assert detached_prim.attributes["xformOp:orient"] == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )
    assert controller.state.array_attached_to_object is False
    assert controller.state.array_prim_path == "/World/AudioArrays/AudioArray"

    mount_link.attributes["xformOp:translate"] = (5.0, 0.0, 1.0)
    after_detach_frame = controller.update_sensor()
    assert after_detach_frame is not None
    assert after_detach_frame.array_pose is not None
    assert after_detach_frame.array_pose.position_m == pytest.approx((0.0, 2.0, 1.1))


def test_extension_controller_create_demo_object_authors_visible_cube():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )

    assert controller.create_demo_object(stage=stage) == "/World/Oven"

    oven = stage.GetPrimAtPath("/World/Oven")
    assert oven is not None
    assert oven.type_name == "Cube"
    assert oven.attributes["xformOp:translate"] == (2.0, 0.0, 0.0)
    assert oven.attributes["size"] == 0.9
    assert oven.attributes["displayColor"] == (0.95, 0.48, 0.08)
    assert oven.attributes["displayOpacity"] == 1.0
    assert oven.attributes["doubleSided"] is True
    assert controller.state.object_prim_path == "/World/Oven"
    assert controller.state.object_label == "Oven"
    assert stage.GetPrimAtPath("/World/KeyLight") is not None
    assert stage.GetPrimAtPath("/World/DemoObjectDomeLight") is not None
    assert stage.GetPrimAtPath("/World/DemoObjectFillLight") is not None


def test_extension_controller_missing_attached_object_is_readable(tmp_path):
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Oven",
                "Xform",
                {"xformOp:translate": (2.0, 0.0, 0.0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.config_export_path = str(tmp_path / "binding.json")

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    path = controller.export_config_summary()

    missing_stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(missing_stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert "attached object is missing" in str(imported.state.error_message)
    assert "/World/Oven" in str(imported.state.error_message)

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    assert controller.update_sensor() is not None
    stage.RemovePrim("/World/Oven")
    assert controller.update_sensor() is None
    assert "Attached object no longer exists: /World/Oven" in str(
        controller.state.error_message
    )
