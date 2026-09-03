from __future__ import annotations

import math
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
import torch
from isaaclab.sensors import SensorBase, SensorBaseCfg

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_layout,
)
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioSceneSnapshot,
    AudioSourceSpec,
)
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    AudioArraySensorData,
    EntityBindingCfg,
    SourceEntityCfg,
)
from isaac_audio_sensors.lab.entity_binding import EntityBinding
from isaac_audio_sensors.lab.reference_backend import ReferenceBackend

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
    environment: AcousticEnvironmentSpec | None = None,
) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="reference",
        arrays=(array,),
        sources=sources,
        environment=(
            environment
            if environment is not None
            else free_field_environment(environment_id="reference_free_field")
        ),
    )


def test_reference_backend_resolves_selected_array_from_each_snapshot() -> None:
    first = create_microphone_array(
        array_id="first",
        prim_path="/World/First",
        layout_name="mono",
    )
    selected = create_microphone_array(
        array_id="selected",
        prim_path="/World/Selected",
        layout_name="quad_front",
    )
    snapshot = replace(_snapshot(selected, ()), arrays=(first, selected))

    reference = ReferenceBackend(
        backend_id="analytic_acoustics",
        max_observations=8,
        effects=AudioArraySensorCfg(prim_path="/World/Audio").effects,
        snapshots=(snapshot,),
        array_ids=("selected",),
    )

    assert reference.array_ids == ("selected",)
    assert reference.num_mics == len(selected.microphones)


def test_reference_backend_rejects_array_id_absent_from_snapshot() -> None:
    array = create_microphone_array(
        array_id="array",
        prim_path="/World/Array",
        layout_name="quad_front",
    )

    with pytest.raises(KeyError, match="AudioSceneSnapshot has no array 'missing'"):
        ReferenceBackend(
            backend_id="analytic_acoustics",
            max_observations=8,
            effects=AudioArraySensorCfg(prim_path="/World/Audio").effects,
            snapshots=(_snapshot(array, ()),),
            array_ids=("missing",),
        )


def test_runtime_uses_real_isaac_lab_bases():
    assert issubclass(AudioArraySensor, SensorBase)
    assert issubclass(AudioArraySensorCfg, SensorBaseCfg)


def test_cfg_and_data_contract_are_minimal_and_fixed_shape():
    cfg = AudioArraySensorCfg(prim_path="/World/Audio", max_observations=2)
    cfg.validate()

    data = AudioArraySensorData.allocate(
        num_envs=2, max_observations=2, num_mics=4, device="cpu"
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
        AudioArraySensorCfg(prim_path="/World/Audio", max_observations=1.5).validate()
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
            environment=free_field_environment(environment_id="entity_origin"),
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


def test_reference_path_emits_zero_observations_until_phase_03():
    backend_id = "analytic_acoustics"
    env_ids = torch.tensor([0])

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
        max_observations=1,
        effects=AudioArraySensorCfg(
            prim_path="/World/Audio", backend=backend_id
        ).effects,
        snapshots=(_snapshot(array, sources),),
        array_ids=(array.array_id,),
    )
    reference_result = reference.observations(
        env_ids=env_ids,
        timestamps_s=torch.tensor([0.5]),
        frame_indices=torch.tensor([0]),
        update_period=0.1,
        device="cpu",
    )

    expected_padding = AudioArraySensorData.allocate(
        num_envs=1,
        max_observations=1,
        num_mics=4,
        device="cpu",
    )
    for item in fields(expected_padding):
        torch.testing.assert_close(
            getattr(reference_result, item.name),
            getattr(expected_padding, item.name),
            equal_nan=True,
        )


def test_entity_binding_rejects_bad_shapes_dtypes_and_layouts():
    with pytest.raises(ValueError, match="source_entities"):
        EntityBindingCfg(environment=free_field_environment(environment_id="empty"))
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
            environment=free_field_environment(environment_id="legacy_field"),
            source_entities=(SourceEntityCfg(entity_name="speaker"),),
            microphone_relative_offsets_m=((0.0, 0.0, 0.0),),
        )

    bad_state = torch.zeros((1, 6), dtype=torch.float32)
    scene = _Scene(robot=_entity(bad_state), speaker=_entity(bad_state))
    with pytest.raises(ValueError, match="seven state columns"):
        EntityBinding(
            scene,
            EntityBindingCfg(
                environment=free_field_environment(environment_id="bad_shape"),
                source_entities=(SourceEntityCfg(entity_name="speaker"),),
            ),
        )

    double_state = _root_state(((0.0, 0.0, 0.0),)).double()
    scene = _Scene(robot=_entity(double_state), speaker=_entity(double_state))
    with pytest.raises(TypeError, match="float32"):
        EntityBinding(
            scene,
            EntityBindingCfg(
                environment=free_field_environment(environment_id="bad_dtype"),
                source_entities=(SourceEntityCfg(entity_name="speaker"),),
            ),
        )

    valid_state = _root_state(((0.0, 0.0, 0.0),))
    valid_scene = _Scene(
        robot=_entity(valid_state), speaker=_entity(valid_state.clone())
    )
    binding = EntityBinding(
        valid_scene,
        EntityBindingCfg(
            environment=free_field_environment(environment_id="device"),
            source_entities=(SourceEntityCfg(entity_name="speaker"),),
        ),
    )
    with pytest.raises(ValueError, match="sensor is on cuda"):
        binding.pose_batch(torch.tensor([0]), device="cuda:0")


def test_entity_binding_rejects_non_free_field_analytic_environment() -> None:
    binding_cfg = EntityBindingCfg(
        environment=shoebox_environment(
            environment_id="room",
            dimensions_m=(4.0, 4.0, 3.0),
        ),
        source_entities=(SourceEntityCfg(entity_name="speaker"),),
    )
    sensor = SimpleNamespace(
        _entity_binding=SimpleNamespace(cfg=binding_cfg),
        _reference_backend=None,
        cfg=SimpleNamespace(
            backend="analytic_acoustics",
            analytic_max_order=0,
            analytic_air_absorption=False,
            analytic_ray_tracing=False,
            effects=AudioArraySensorCfg(prim_path="/World/Audio").effects,
        ),
        is_initialized=False,
        _bound_num_mics=lambda: 4,
    )

    with pytest.raises(ValueError, match="explicit free_field"):
        AudioArraySensor._validate_bound_runtime(sensor)


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
            environment=free_field_environment(environment_id="entity_directivity"),
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
