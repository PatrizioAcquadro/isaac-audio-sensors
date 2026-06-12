"""Tests for Isaac Lab scene/entity tensor audio binding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    LabAudioEntityBindingCfg,
    LabAudioSourceEntityCfg,
    LabAudioStageBindingCfg,
)
from isaac_audio_sensors.lab.entity_binding import resolve_scene_entity


def _wxyz(xyzw: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (xyzw[3], xyzw[0], xyzw[1], xyzw[2])


def _entity(**fields):
    return SimpleNamespace(data=SimpleNamespace(**fields))


class _DictScene:
    def __init__(self, entities: dict[str, object], *, num_envs: int) -> None:
        self.entities = entities
        self.num_envs = num_envs

    def __getitem__(self, name: str) -> object:
        return self.entities[name]


def _cfg(
    *,
    sources: tuple[LabAudioSourceEntityCfg, ...],
    num_envs: int = 2,
    body_name: str | None = "head",
    state_position_frame: str = "world",
) -> LabAudioEntityBindingCfg:
    return LabAudioEntityBindingCfg(
        num_envs=num_envs,
        robot_entity_name="robot",
        array_mount_body_name=body_name,
        array_relative_position_m=(1.0, 0.0, 0.0),
        microphone_layout="quad_front",
        source_entities=sources,
        state_position_frame=state_position_frame,  # type: ignore[arg-type]
    )


def _sensor(device: str = "cpu") -> AudioArraySensor:
    return AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.0,
            backend="geometry_only",
            max_events=3,
            device=device,
        )
    )


def test_lab_entity_binding_passes_explicit_room_to_snapshots():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.core.types import RoomAcousticsSpec

    robot = _entity(
        root_pos_w=torch.zeros((1, 3)),
        root_quat_w=torch.tensor([_wxyz((0.0, 0.0, 0.0, 1.0))]),
    )
    speaker = _entity(
        root_pos_w=torch.tensor([[3.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor([_wxyz((0.0, 0.0, 0.0, 1.0))]),
    )
    scene = _DictScene({"robot": robot, "speaker": speaker}, num_envs=1)
    room = RoomAcousticsSpec(
        room_id="entity_room",
        dimensions_m=(8.0, 6.0, 3.0),
        absorption=0.35,
        max_order=1,
        origin_m=(-2.0, -3.0, -1.5),
    )
    cfg = LabAudioEntityBindingCfg(
        num_envs=1,
        robot_entity_name="robot",
        microphone_layout="quad_front",
        source_entities=(
            LabAudioSourceEntityCfg(
                entity_name="speaker",
                source_id="speaker",
                class_label="Speech",
            ),
        ),
        room=room,
    )

    from isaac_audio_sensors.lab.entity_binding import build_lab_entity_provider

    provider = build_lab_entity_provider(scene=scene, binding_cfg=cfg)
    snapshot, _array_spec = provider([0])[0]

    assert snapshot.room == room


def test_lab_entity_lookup_supports_dict_attr_and_containers():
    torch = pytest.importorskip("torch")
    robot = _entity(
        root_pos_w=torch.zeros((1, 3)),
        root_quat_w=torch.tensor([_wxyz((0.0, 0.0, 0.0, 1.0))]),
    )
    speaker = _entity(
        root_pos_w=torch.tensor([[5.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor([_wxyz((0.0, 0.0, 0.0, 1.0))]),
    )
    dict_scene = _DictScene({"robot": robot, "speaker": speaker}, num_envs=1)
    attr_scene = SimpleNamespace(
        num_envs=1,
        robot=robot,
        rigid_objects={"speaker": speaker},
        articulations={"robot": robot},
    )

    assert resolve_scene_entity(dict_scene, "robot") is robot
    assert resolve_scene_entity(attr_scene, "robot") is robot
    assert resolve_scene_entity(attr_scene, "speaker") is speaker
    with pytest.raises(ValueError, match="missing"):
        resolve_scene_entity(attr_scene, "missing")


def test_lab_entity_robot_body_array_pose_rotation_and_source_body_pose():
    torch = pytest.importorskip("torch")
    robot = _entity(
        body_names=("base", "head"),
        body_pos_w=torch.tensor(
            [
                [[0.0, 0.0, 0.0], [1.0, 2.0, 0.0]],
                [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
            ],
            dtype=torch.float32,
        ),
        body_quat_w=torch.tensor(
            [
                [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz(quaternion_from_yaw_deg(90.0))],
                [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            ],
            dtype=torch.float32,
        ),
    )
    speaker = _entity(
        body_names=("root", "speaker_link"),
        body_state_w=torch.tensor(
            [
                [
                    [0.0, 0.0, 0.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
                    [1.0, 8.0, 1.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
                ],
                [
                    [0.0, 0.0, 0.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
                    [15.0, 0.0, 0.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
                ],
            ],
            dtype=torch.float32,
        ),
    )
    scene = _DictScene({"robot": robot, "speaker": speaker}, num_envs=2)

    sensor = _sensor().bind_lab_entities(
        scene=scene,
        binding_cfg=_cfg(
            sources=(
                LabAudioSourceEntityCfg(
                    entity_name="speaker",
                    body_name="speaker_link",
                    source_id="speaker",
                    class_label="Speech",
                ),
            )
        ),
    )
    sensor.update(dt=0.0, force_recompute=True, env_ids=[0])
    frame = sensor.data.latest_frames[0]
    diag = frame.diagnostics["entity_binding"]

    assert frame.array_pose.position_m == pytest.approx((1.0, 3.0, 0.0))
    assert frame.array_pose.orientation_xyzw == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )
    assert frame.detections[0].source_pose.position_m == pytest.approx((1.0, 8.0, 1.0))
    assert frame.detections[0].doa.estimated_bearing_deg == pytest.approx(0.0)
    assert diag["robot_entity_name"] == "robot"
    assert diag["array_mount_body_name"] == "head"
    assert diag["array_body_pose_source"] == "body_pos_w+body_quat_w[head]"
    assert diag["array_relative_pose"]["position_m"] == pytest.approx((1.0, 0.0, 0.0))
    assert diag["source_entities"][0]["pose_source"] == "body_state_w[speaker_link]"


def test_lab_entity_multiple_sources_active_windows_and_selected_env_reads():
    torch = pytest.importorskip("torch")
    robot = _entity(
        root_state_w=torch.tensor(
            [
                [0.0, 0.0, 0.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
                [0.0, 0.0, 0.0, *_wxyz((0.0, 0.0, 0.0, 1.0))],
            ],
            dtype=torch.float32,
        )
    )
    speaker_a = _entity(
        root_pos_w=torch.tensor([[5.0, 0.0, 0.0], [0.0, 5.0, 0.0]]),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
        ),
    )
    speaker_b = _entity(
        root_pos_w=torch.tensor([[0.0, -5.0, 0.0], [5.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
        ),
    )
    scene = SimpleNamespace(
        num_envs=2,
        articulations={"robot": robot},
        rigid_objects={"speaker_a": speaker_a, "speaker_b": speaker_b},
    )
    sensor = _sensor().bind_lab_entities(
        scene=scene,
        binding_cfg=_cfg(
            body_name=None,
            sources=(
                LabAudioSourceEntityCfg(
                    entity_name="speaker_a",
                    source_id="speaker_a",
                    class_label="Speech",
                    start_time_s=0.0,
                    duration_s=0.2,
                ),
                LabAudioSourceEntityCfg(
                    entity_name="speaker_b",
                    source_id="speaker_b",
                    class_label="Alarm",
                    start_time_s=1.0,
                    duration_s=1.0,
                    gain_db=-3.0,
                    directivity="cardioid",
                ),
            ),
        ),
    )

    sensor.update(dt=0.0, force_recompute=True)
    provider = sensor._scene_provider
    first = sensor.data.bearing_deg.clone()
    assert sensor.data.source_ids == (
        ("speaker_a", None, None),
        ("speaker_a", None, None),
    )
    assert provider.read_counts == {0: 1, 1: 1}

    speaker_a.data.root_pos_w[1] = torch.tensor([-5.0, 0.0, 0.0])
    sensor.update(dt=0.0, force_recompute=True, env_ids=[1])
    assert provider.read_counts == {0: 1, 1: 2}
    assert sensor.data.bearing_deg[0, 0].item() == first[0, 0].item()
    assert sensor.data.bearing_deg[1, 0].item() == pytest.approx(180.0)

    data = sensor.update(sim_time_s=1.0, timestamp_ms=1000, env_ids=[1], force=True)
    assert data.source_ids[1] == ("speaker_b", None, None)
    assert data.class_labels[1] == ("Alarm", None, None)
    assert data.latest_frames[1].detections[0].source_id == "speaker_b"


def test_lab_entity_env_origins_are_applied_only_for_env_frame_state():
    torch = pytest.importorskip("torch")
    robot = _entity(
        root_pos_w=torch.tensor([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
        ),
    )
    speaker = _entity(
        root_pos_w=torch.tensor([[5.0, 0.0, 0.0], [5.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
        ),
    )
    scene = SimpleNamespace(
        num_envs=2,
        env_origins=torch.tensor([[10.0, 0.0, 0.0], [100.0, 0.0, 0.0]]),
        robot=robot,
        speaker=speaker,
    )
    source = (
        LabAudioSourceEntityCfg(
            entity_name="speaker",
            source_id="speaker",
            class_label="Speech",
        ),
    )

    world_sensor = _sensor().bind_lab_entities(
        scene=scene,
        binding_cfg=_cfg(body_name=None, sources=source),
    )
    world_sensor.update(dt=0.0, force_recompute=True, env_ids=[1])
    world_frame = world_sensor.data.latest_frames[1]

    env_sensor = _sensor().bind_lab_entities(
        scene=scene,
        binding_cfg=_cfg(
            body_name=None,
            sources=source,
            state_position_frame="env",
        ),
    )
    env_sensor.update(dt=0.0, force_recompute=True, env_ids=[1])
    env_frame = env_sensor.data.latest_frames[1]

    assert world_frame.array_pose.position_m == pytest.approx((1.0, 0.0, 0.0))
    assert world_frame.detections[0].source_pose.position_m == pytest.approx(
        (5.0, 0.0, 0.0)
    )
    assert not world_frame.diagnostics["entity_binding"]["env_origin_applied"]
    assert env_frame.array_pose.position_m == pytest.approx((101.0, 0.0, 0.0))
    assert env_frame.detections[0].source_pose.position_m == pytest.approx(
        (105.0, 0.0, 0.0)
    )
    assert env_frame.diagnostics["entity_binding"]["env_origin_applied"]


def test_lab_entity_cuda_state_and_buffers_when_available():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is not available.")
    device = "cuda:0"
    robot = _entity(
        root_pos_w=torch.zeros((2, 3), device=device),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
            device=device,
        ),
    )
    speaker = _entity(
        root_pos_w=torch.tensor(
            [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0]],
            dtype=torch.float32,
            device=device,
        ),
        root_quat_w=torch.tensor(
            [_wxyz((0.0, 0.0, 0.0, 1.0)), _wxyz((0.0, 0.0, 0.0, 1.0))],
            dtype=torch.float32,
            device=device,
        ),
    )
    scene = SimpleNamespace(num_envs=2, robot=robot, speaker=speaker)

    sensor = _sensor(device=device).bind_lab_entities(
        scene=scene,
        binding_cfg=_cfg(
            body_name=None,
            sources=(
                LabAudioSourceEntityCfg(
                    entity_name="speaker",
                    source_id="speaker",
                    class_label="Speech",
                ),
            ),
            num_envs=2,
        ),
    )
    sensor.update(dt=0.0, force_recompute=True)

    assert str(sensor.data.event_presence.device).startswith("cuda")
    assert (
        sensor.data.latest_frames[1]
        .diagnostics["entity_binding"]["tensor_device"]
        .startswith("cuda")
    )


def test_lab_entity_binding_reports_missing_entity_body_and_pose_tensors():
    torch = pytest.importorskip("torch")
    robot = _entity(
        body_names=("base",),
        body_pos_w=torch.zeros((1, 1, 3)),
        body_quat_w=torch.tensor([[_wxyz((0.0, 0.0, 0.0, 1.0))]]),
    )
    speaker = _entity(
        root_pos_w=torch.tensor([[5.0, 0.0, 0.0]]),
        root_quat_w=torch.tensor([_wxyz((0.0, 0.0, 0.0, 1.0))]),
    )
    scene = SimpleNamespace(num_envs=1, robot=robot, speaker=speaker)
    source = (
        LabAudioSourceEntityCfg(
            entity_name="speaker",
            source_id="speaker",
            class_label="Speech",
        ),
    )

    with pytest.raises(ValueError, match="body/link 'head'"):
        _sensor().bind_lab_entities(
            scene=scene,
            binding_cfg=_cfg(num_envs=1, sources=source),
        ).update(dt=0.0, force_recompute=True)

    with pytest.raises(ValueError, match="Could not resolve scene entity"):
        _sensor().bind_lab_entities(
            scene=scene,
            binding_cfg=LabAudioEntityBindingCfg(
                num_envs=1,
                robot_entity_name="missing_robot",
                source_entities=source,
            ),
        ).update(dt=0.0, force_recompute=True)

    missing_pose_scene = SimpleNamespace(
        num_envs=1,
        robot=SimpleNamespace(data=SimpleNamespace()),
        speaker=speaker,
    )
    with pytest.raises(ValueError, match="missing pose tensors"):
        _sensor().bind_lab_entities(
            scene=missing_pose_scene,
            binding_cfg=LabAudioEntityBindingCfg(
                num_envs=1,
                robot_entity_name="robot",
                source_entities=source,
            ),
        ).update(dt=0.0, force_recompute=True)


def test_lab_stage_binding_still_uses_stage_provider_after_entity_addition():
    pytest.importorskip("torch")

    class FakePrim:
        def __init__(self, path: str, attributes: dict[str, object]) -> None:
            self.path = path
            self.type_name = "Xform"
            self.attributes = attributes

    class FakeStage:
        def Traverse(self):
            return (
                FakePrim(
                    "/World/envs/env_0/Robot/audio_array",
                    {
                        "ias:position_world": (0.0, 0.0, 0.0),
                        "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                    },
                ),
                FakePrim(
                    "/World/envs/env_0/Sources/speaker",
                    {
                        "ias:position_world": (5.0, 0.0, 0.0),
                        "ias:source_id": "speaker",
                        "ias:class_label": "Speech",
                        "ias:duration_s": 1.0,
                    },
                ),
            )

    sensor = _sensor().bind_lab_stage(
        stage=FakeStage(),
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
            microphone_layout="quad_front",
        ),
    )
    sensor.update(dt=0.0, force_recompute=True)

    assert "stage_binding" in sensor.data.latest_frames[0].diagnostics
    assert "entity_binding" not in sensor.data.latest_frames[0].diagnostics
