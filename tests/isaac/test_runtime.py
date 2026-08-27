from __future__ import annotations

import math
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
import torch
from isaaclab.sensors import SensorBase, SensorBaseCfg

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_layout,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    AudioArraySensorData,
    EntityBindingCfg,
    SourceEntityCfg,
)
from isaac_audio_sensors.lab.batched_backend import (
    compact_active_events,
    geometry_observations,
    precompute_tdoa_operator,
    tdoa_observations,
)
from isaac_audio_sensors.lab.entity_binding import EntityBinding
from isaac_audio_sensors.lab.reference_backend import ReferenceBackend
from tests.helpers import install_fake_pyroom

DB_DOUBLE = 20.0 * math.log10(2.0)


class _Scene(dict):
    def __init__(self, *args, env_origins=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.env_origins = env_origins


def _entity(root_state: torch.Tensor, body_state: torch.Tensor | None = None):
    data = SimpleNamespace(root_state_w=root_state)
    if body_state is not None:
        data.body_state_w = body_state
    return SimpleNamespace(data=data, body_names=("head",))


def _root_state(positions: tuple[tuple[float, float, float], ...]) -> torch.Tensor:
    state = torch.zeros((len(positions), 13), dtype=torch.float32)
    state[:, :3] = torch.tensor(positions)
    state[:, 3] = 1.0
    return state


def _snapshot(
    array,
    sources: tuple[AudioSourceSpec, ...],
    *,
    room: RoomAcousticsSpec | None = None,
) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="reference",
        timestamp_ms=0,
        arrays=(array,),
        sources=sources,
        room=room,
    )


def test_runtime_uses_real_isaac_lab_bases():
    assert issubclass(AudioArraySensor, SensorBase)
    assert issubclass(AudioArraySensorCfg, SensorBaseCfg)


def test_cfg_and_data_contract_are_minimal_and_fixed_shape():
    cfg = AudioArraySensorCfg(prim_path="/World/Audio", max_events=2)
    cfg.validate()

    data = AudioArraySensorData.allocate(
        num_envs=2, max_events=2, num_mics=4, device="cpu"
    )
    assert [field.name for field in fields(data)] == [
        "event_presence",
        "bearing_deg",
        "confidence",
        "sector_onehot",
        "per_mic_rms",
        "ambiguity_mask",
    ]
    assert data.event_presence.shape == (2, 2)
    assert data.sector_onehot.shape == (2, 2, 8)
    assert data.per_mic_rms.shape == (2, 2, 4)
    assert data.event_presence.dtype == torch.bool
    assert data.bearing_deg.dtype == torch.float32
    assert data.event_presence.device.type == "cpu"
    assert torch.isnan(data.bearing_deg).all()

    data.event_presence[:] = True
    data.confidence[:] = 1.0
    data.reset(torch.tensor([False, True]))
    assert data.event_presence[0].all()
    assert not data.event_presence[1].any()
    assert data.confidence[0].eq(1.0).all()
    assert data.confidence[1].eq(0.0).all()

    with pytest.raises(ValueError, match="Unknown backend"):
        AudioArraySensorCfg(prim_path="/World/Audio", backend="unknown").validate()
    with pytest.raises(TypeError, match="integer"):
        AudioArraySensorCfg(prim_path="/World/Audio", max_events=1.5).validate()
    with pytest.raises(ValueError, match="finite"):
        AudioArraySensorCfg(
            prim_path="/World/Audio", update_period=float("nan")
        ).validate()
    with pytest.raises(NotImplementedError, match="visualization"):
        AudioArraySensorCfg(prim_path="/World/Audio", debug_vis=True).validate()


def test_entity_binding_applies_env_origin_body_mount_and_wxyz_conversion():
    root = _root_state(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
    body = root[:, None, :].clone()
    body[:, 0, :3] = torch.tensor(((1.0, 2.0, 0.0), (2.0, 3.0, 0.0)))
    half = math.sqrt(0.5)
    body[:, 0, 3:7] = torch.tensor((half, 0.0, 0.0, half))
    source = _root_state(((3.0, 0.0, 0.0), (4.0, 0.0, 0.0)))
    origins = torch.tensor(((10.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    scene = _Scene(
        robot=_entity(root, body),
        speaker=_entity(source),
        env_origins=origins,
    )
    binding = EntityBinding(
        scene,
        EntityBindingCfg(
            array_mount_body_name="head",
            array_relative_position_m=(1.0, 0.0, 0.0),
            source_entities=(SourceEntityCfg(entity_name="speaker"),),
            state_position_frame="env",
        ),
    )

    batch = binding.pose_batch(torch.tensor([0, 1]), device="cpu")

    torch.testing.assert_close(
        batch.array_positions,
        torch.tensor(((11.0, 3.0, 0.0), (22.0, 4.0, 0.0))),
    )
    torch.testing.assert_close(
        batch.array_quats_xyzw,
        torch.tensor(((0.0, 0.0, half, half), (0.0, 0.0, half, half))),
    )
    torch.testing.assert_close(
        batch.source_positions[:, 0],
        torch.tensor(((13.0, 0.0, 0.0), (24.0, 0.0, 0.0))),
    )


@pytest.mark.parametrize("backend_id", ["geometry_only", "tdoa_synthetic"])
def test_entity_and_reference_paths_match_with_schedule_and_truncation(backend_id):
    robot_state = _root_state(((0.0, 0.0, 0.0),))
    front_state = _root_state(((4.0, 0.0, 0.0),))
    right_state = _root_state(((0.0, 4.0, 0.0),))
    scene = _Scene(
        robot=_entity(robot_state),
        front=_entity(front_state),
        right=_entity(right_state),
    )
    cfg = EntityBindingCfg(
        source_entities=(
            SourceEntityCfg(entity_name="right", source_id="b", start_time_s=0.5),
            SourceEntityCfg(entity_name="front", source_id="a", start_time_s=0.0),
        )
    )
    binding = EntityBinding(scene, cfg)
    env_ids = torch.tensor([0])
    batch = binding.pose_batch(env_ids, device="cpu")
    if backend_id == "geometry_only":
        source_observations = geometry_observations(batch)
    else:
        solve, baseline, determinant = precompute_tdoa_operator(
            binding.static.mic_offsets_local
        )
        assert determinant > 0.0
        source_observations = tdoa_observations(
            batch, solve_operator=solve, baseline_matrix=baseline
        )
    active = (binding.static.source_start_s.unsqueeze(0) < 0.6) & (
        binding.static.source_end_s.unsqueeze(0) > 0.5
    )
    entity_result = compact_active_events(
        source_observations, active_mask=active, max_events=1
    )

    array = create_microphone_array(
        array_id="array", prim_path="/World/Array", layout_name="quad_front"
    )
    sources = (
        AudioSourceSpec(
            source_id="b",
            prim_path="/World/right",
            class_label="Sound",
            audio_asset_path="generated://impulse",
            position_world=(0.0, 4.0, 0.0),
            orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
            start_time_s=0.5,
            duration_s=1.0,
            gain_db=0.0,
        ),
        AudioSourceSpec(
            source_id="a",
            prim_path="/World/front",
            class_label="Sound",
            audio_asset_path="generated://impulse",
            position_world=(4.0, 0.0, 0.0),
            orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    )
    reference = ReferenceBackend(
        backend_id=backend_id,
        ambiguity_policy="none",
        effects=AudioArraySensorCfg(
            prim_path="/World/Audio", backend=backend_id
        ).effects,
        snapshots=(_snapshot(array, sources),),
        array_specs=(array,),
    )
    reference_result = reference.observations(
        env_ids=env_ids,
        timestamps_s=torch.tensor([0.5]),
        frame_indices=torch.tensor([0]),
        max_events=1,
        update_period=0.1,
        device="cpu",
    )

    for item in fields(entity_result):
        torch.testing.assert_close(
            getattr(entity_result, item.name),
            getattr(reference_result, item.name),
            equal_nan=True,
            atol=1e-4,
            rtol=1e-4,
        )

    padded_result = reference.observations(
        env_ids=env_ids,
        timestamps_s=torch.tensor([2.0]),
        frame_indices=torch.tensor([1]),
        max_events=2,
        update_period=0.1,
        device="cpu",
    )
    expected_padding = AudioArraySensorData.allocate(
        num_envs=1,
        max_events=2,
        num_mics=4,
        device="cpu",
    )
    for item in fields(expected_padding):
        torch.testing.assert_close(
            getattr(padded_result, item.name),
            getattr(expected_padding, item.name),
            equal_nan=True,
        )


def test_entity_binding_rejects_bad_shapes_dtypes_and_layouts():
    with pytest.raises(ValueError, match="source_entities"):
        EntityBindingCfg()
    with pytest.raises(ValueError, match="directivity"):
        SourceEntityCfg(entity_name="speaker", directivity="unknown")
    with pytest.raises((TypeError, ValueError), match="relative_orientation_quat"):
        SourceEntityCfg(
            entity_name="speaker",
            directivity=DirectivityPattern.CARDIOID,
            relative_orientation_quat=None,
        )
    assert "microphone_relative_offsets_m" not in {
        field.name for field in fields(EntityBindingCfg)
    }
    with pytest.raises(TypeError, match="microphone_relative_offsets_m"):
        EntityBindingCfg(
            source_entities=(SourceEntityCfg(entity_name="speaker"),),
            microphone_relative_offsets_m=((0.0, 0.0, 0.0),),
        )

    bad_state = torch.zeros((1, 6), dtype=torch.float32)
    scene = _Scene(robot=_entity(bad_state), speaker=_entity(bad_state))
    with pytest.raises(ValueError, match="seven state columns"):
        EntityBinding(
            scene,
            EntityBindingCfg(source_entities=(SourceEntityCfg(entity_name="speaker"),)),
        )

    double_state = _root_state(((0.0, 0.0, 0.0),)).double()
    scene = _Scene(robot=_entity(double_state), speaker=_entity(double_state))
    with pytest.raises(TypeError, match="float32"):
        EntityBinding(
            scene,
            EntityBindingCfg(source_entities=(SourceEntityCfg(entity_name="speaker"),)),
        )

    valid_state = _root_state(((0.0, 0.0, 0.0),))
    valid_scene = _Scene(
        robot=_entity(valid_state), speaker=_entity(valid_state.clone())
    )
    binding = EntityBinding(
        valid_scene,
        EntityBindingCfg(source_entities=(SourceEntityCfg(entity_name="speaker"),)),
    )
    with pytest.raises(ValueError, match="sensor is on cuda"):
        binding.pose_batch(torch.tensor([0]), device="cuda:0")


@pytest.mark.parametrize("backend_id", ["geometry_only", "tdoa_synthetic"])
@pytest.mark.parametrize(
    ("gain_target", "gain_db", "expected_ratio"),
    (
        ("source", DB_DOUBLE, 2.0),
        ("source", -DB_DOUBLE, 0.5),
        ("microphone", DB_DOUBLE, 2.0),
        ("microphone", -DB_DOUBLE, 0.5),
    ),
)
def test_entity_modes_apply_source_and_microphone_gain_once(
    backend_id: str,
    gain_target: str,
    gain_db: float,
    expected_ratio: float,
) -> None:
    baseline = _entity_mode_rms(backend_id)
    changed = _entity_mode_rms(
        backend_id,
        source_gain_db=gain_db if gain_target == "source" else 0.0,
        microphone_gain_db=gain_db if gain_target == "microphone" else 0.0,
    )

    assert changed / baseline == pytest.approx(expected_ratio, rel=1e-5)


@pytest.mark.parametrize(
    "backend_id",
    [
        "geometry_only",
        "tdoa_synthetic",
        "room_acoustics",
        "room_acoustics_srp",
    ],
)
@pytest.mark.parametrize(
    ("gain_target", "gain_db", "expected_ratio"),
    (
        ("source", DB_DOUBLE, 2.0),
        ("source", -DB_DOUBLE, 0.5),
        ("microphone", DB_DOUBLE, 2.0),
        ("microphone", -DB_DOUBLE, 0.5),
    ),
)
def test_reference_mode_preserves_relative_gain_ratios(
    monkeypatch,
    backend_id: str,
    gain_target: str,
    gain_db: float,
    expected_ratio: float,
) -> None:
    if backend_id.startswith("room_acoustics"):
        install_fake_pyroom(monkeypatch)
    baseline = _reference_mode_rms(backend_id)
    changed = _reference_mode_rms(
        backend_id,
        source_gain_db=gain_db if gain_target == "source" else 0.0,
        microphone_gain_db=gain_db if gain_target == "microphone" else 0.0,
    )

    assert changed / baseline == pytest.approx(expected_ratio, rel=1e-5)


def test_entity_binding_uses_canonical_entity_directivity_and_microphone_gain() -> None:
    state = _root_state(((0.0, 0.0, 0.0),))
    microphones = tuple(
        replace(
            microphone,
            gain_db=DB_DOUBLE,
            directivity=DirectivityPattern.SUPERCARDIOID,
            relative_orientation_quat=(0.0, 0.0, 0.0, 1.0),
        )
        for microphone in microphone_layout("quad_front")
    )
    binding = EntityBinding(
        _Scene(robot=_entity(state), speaker=_entity(state.clone())),
        EntityBindingCfg(
            microphone_layout=None,
            microphones=microphones,
            source_entities=(
                SourceEntityCfg(
                    entity_name="speaker",
                    gain_db=DB_DOUBLE,
                    directivity=DirectivityPattern.FIGURE_EIGHT,
                ),
            ),
        ),
    )

    torch.testing.assert_close(
        binding.static.mic_gain_scale,
        torch.full((4,), 2.0),
    )
    torch.testing.assert_close(
        binding.static.mic_directivity_coefficient,
        torch.full((4,), 0.37),
    )
    torch.testing.assert_close(binding.static.source_gain_scale, torch.tensor([2.0]))
    torch.testing.assert_close(
        binding.static.source_directivity_coefficient,
        torch.tensor([0.0]),
    )


def _entity_mode_rms(
    backend_id: str,
    *,
    source_gain_db: float = 0.0,
    microphone_gain_db: float = 0.0,
) -> float:
    robot = _root_state(((0.0, 0.0, 0.0),))
    source = _root_state(((4.0, 0.0, 0.0),))
    microphones = tuple(
        replace(microphone, gain_db=microphone_gain_db)
        for microphone in microphone_layout("quad_front")
    )
    binding = EntityBinding(
        _Scene(robot=_entity(robot), speaker=_entity(source)),
        EntityBindingCfg(
            microphone_layout=None,
            microphones=microphones,
            source_entities=(
                SourceEntityCfg(entity_name="speaker", gain_db=source_gain_db),
            ),
        ),
    )
    batch = binding.pose_batch(torch.tensor([0]), device="cpu")
    if backend_id == "geometry_only":
        observations = geometry_observations(batch)
    else:
        solve, baseline, determinant = precompute_tdoa_operator(
            binding.static.mic_offsets_local
        )
        assert determinant > 0.0
        observations = tdoa_observations(
            batch,
            solve_operator=solve,
            baseline_matrix=baseline,
        )
    return float(observations.per_mic_rms[0, 0, 0].item())


def _reference_mode_rms(
    backend_id: str,
    *,
    source_gain_db: float = 0.0,
    microphone_gain_db: float = 0.0,
) -> float:
    array = create_microphone_array(
        array_id="array",
        prim_path="/World/Array",
        layout_name="quad_front",
    )
    array = replace(
        array,
        microphones=tuple(
            replace(microphone, gain_db=microphone_gain_db)
            for microphone in array.microphones
        ),
    )
    source = AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=(4.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=source_gain_db,
    )
    room = None
    if backend_id.startswith("room_acoustics"):
        room = RoomAcousticsSpec(
            room_id="room",
            dimensions_m=(20.0, 20.0, 20.0),
            origin_m=(-10.0, -10.0, -10.0),
            absorption=0.2,
            max_order=1,
        )
    reference = ReferenceBackend(
        backend_id=backend_id,
        ambiguity_policy="none",
        effects=AudioArraySensorCfg(
            prim_path="/World/Audio",
            backend=backend_id,
        ).effects,
        snapshots=(_snapshot(array, (source,), room=room),),
        array_specs=(array,),
    )
    result = reference.observations(
        env_ids=torch.tensor([0]),
        timestamps_s=torch.tensor([0.0]),
        frame_indices=torch.tensor([0]),
        max_events=1,
        update_period=0.05,
        device="cpu",
    )
    return float(result.per_mic_rms[0, 0, 0].item())
