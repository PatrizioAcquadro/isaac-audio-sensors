"""Parity, dispatch, and perf tests for the batched Isaac Lab compute path."""

from __future__ import annotations

import math
import os
import time
from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.backends.amplitude import source_amplitude_at
from isaac_audio_sensors.core.backends.tdoa import _least_squares_direction
from isaac_audio_sensors.core.constants import SECTOR_ORDER
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    basis_from_quaternion,
    bearing_from_components,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import AudioSourceSpec, MicrophoneArraySpec
from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg
from isaac_audio_sensors.lab.entity_binding import (
    LabAudioEntityBindingCfg,
    LabAudioSourceEntityCfg,
)

BEARING_TOLERANCE_DEG = 5e-3
# Sensor-level parity runs end to end in float32; near-degenerate TDOA poses
# amplify rounding into the recovered direction, so the end-to-end bearing
# budget is looser than the function-level one (still ~40x tighter than the
# 2-degree accuracy the scalar backend itself asserts).
SENSOR_BEARING_TOLERANCE_DEG = 0.05
SENSOR_CONFIDENCE_ATOL = 5e-4
RMS_RTOL = 1e-4
RMS_ATOL = 1e-7


def _wxyz(xyzw: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (xyzw[3], xyzw[0], xyzw[1], xyzw[2])


def _random_unit_quats_wxyz(generator, count: int, device: str = "cpu"):
    import torch

    quats = torch.randn((count, 4), generator=generator, dtype=torch.float32)
    return (quats / torch.linalg.norm(quats, dim=-1, keepdim=True)).to(device)


def _entity(positions, quats_wxyz):
    return SimpleNamespace(
        data=SimpleNamespace(root_pos_w=positions, root_quat_w=quats_wxyz)
    )


def _random_scene(*, num_envs: int, seed: int, device: str = "cpu"):
    """Duck-typed entity scene with randomized robot and source poses."""

    import torch

    generator = torch.Generator().manual_seed(seed)

    def random_positions() -> object:
        return (
            (torch.rand((num_envs, 3), generator=generator) - 0.5) * 20.0
        ).to(device)

    entities = {
        "robot": _entity(
            random_positions(),
            _random_unit_quats_wxyz(generator, num_envs, device),
        ),
        "omni_speaker": _entity(
            random_positions(),
            _random_unit_quats_wxyz(generator, num_envs, device),
        ),
        "cardioid_speaker": _entity(
            random_positions(),
            _random_unit_quats_wxyz(generator, num_envs, device),
        ),
        "expired_speaker": _entity(
            random_positions(),
            _random_unit_quats_wxyz(generator, num_envs, device),
        ),
        "future_speaker": _entity(
            random_positions(),
            _random_unit_quats_wxyz(generator, num_envs, device),
        ),
    }
    return SimpleNamespace(
        num_envs=num_envs,
        articulations={"robot": entities["robot"]},
        rigid_objects={
            name: entity for name, entity in entities.items() if name != "robot"
        },
    )


def _source_entities() -> tuple[LabAudioSourceEntityCfg, ...]:
    # Intentionally not in active_sources order: sorted by
    # (start_time_s, source_id) this becomes alpha_omni, cardioid_src,
    # zeta_expired, future_src.
    return (
        LabAudioSourceEntityCfg(
            entity_name="expired_speaker",
            source_id="zeta_expired",
            class_label="Alarm",
            duration_s=0.043,
        ),
        LabAudioSourceEntityCfg(
            entity_name="omni_speaker",
            source_id="alpha_omni",
            class_label="Speech",
            duration_s=None,
        ),
        LabAudioSourceEntityCfg(
            entity_name="future_speaker",
            source_id="future_src",
            class_label="Music",
            start_time_s=1.0e6,
            duration_s=1.0,
        ),
        LabAudioSourceEntityCfg(
            entity_name="cardioid_speaker",
            source_id="cardioid_src",
            class_label="Speech",
            duration_s=None,
            directivity="cardioid",
            gain_db=3.0,
        ),
    )


def _binding_cfg(*, num_envs: int, device: str = "cpu", diagnostics: bool = False):
    return LabAudioEntityBindingCfg(
        num_envs=num_envs,
        robot_entity_name="robot",
        microphone_layout="quad_front",
        source_entities=_source_entities(),
        device=device,
        diagnostics=diagnostics,
    )


def _sensor(
    *,
    backend: str,
    compute_path: str,
    scene,
    binding_cfg,
    device: str = "cpu",
    max_events: int = 4,
) -> AudioArraySensor:
    return AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.0,
            backend=backend,
            microphone_layout="quad_front",
            max_events=max_events,
            device=device,
            compute_path=compute_path,
        )
    ).bind_lab_entities(scene=scene, binding_cfg=binding_cfg)


def _assert_observation_parity(scalar_data, batched_data) -> None:
    import torch

    assert torch.equal(scalar_data.event_presence, batched_data.event_presence)
    assert torch.equal(scalar_data.ambiguity_mask, batched_data.ambiguity_mask)
    scalar_nan = torch.isnan(scalar_data.bearing_deg)
    assert torch.equal(scalar_nan, torch.isnan(batched_data.bearing_deg))
    valid = ~scalar_nan
    if bool(valid.any()):
        delta = (
            scalar_data.bearing_deg[valid]
            - batched_data.bearing_deg[valid]
            + 180.0
        ) % 360.0 - 180.0
        assert float(delta.abs().max()) < SENSOR_BEARING_TOLERANCE_DEG
    assert torch.allclose(
        scalar_data.confidence,
        batched_data.confidence,
        atol=SENSOR_CONFIDENCE_ATOL,
    )
    assert torch.allclose(
        scalar_data.per_mic_rms,
        batched_data.per_mic_rms,
        rtol=RMS_RTOL,
        atol=RMS_ATOL,
    )
    assert torch.equal(scalar_data.sector_onehot, batched_data.sector_onehot)
    assert torch.allclose(
        scalar_data.last_update_time_s,
        batched_data.last_update_time_s,
        equal_nan=True,
    )


def _device_params() -> tuple[str, ...]:
    return ("cpu", "cuda:0")


def _skip_unless_device(device: str) -> None:
    import torch

    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA is not available.")


# ---------------------------------------------------------------------------
# Function-level parity against the scalar core helpers
# ---------------------------------------------------------------------------


def test_batched_basis_matches_scalar_helper():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import batched_basis_from_quat_xyzw

    generator = torch.Generator().manual_seed(7)
    quats = torch.randn((256, 4), generator=generator, dtype=torch.float32)
    quats = quats / torch.linalg.norm(quats, dim=-1, keepdim=True)
    axis_cases = torch.tensor(
        [
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, math.sin(math.pi / 4.0), math.cos(math.pi / 4.0)],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
        ],
        dtype=torch.float32,
    )
    quats = torch.cat((quats, axis_cases), dim=0)
    basis = batched_basis_from_quat_xyzw(quats)
    for index in range(quats.shape[0]):
        expected = basis_from_quaternion(tuple(quats[index].tolist()))
        for row, vector in enumerate(expected):
            assert basis[index, row].tolist() == pytest.approx(vector, abs=1e-5)


def test_batched_bearing_matches_scalar_helper():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import batched_bearing_deg

    cases = [
        (5.0, 0.0),
        (-5.0, 0.0),
        (0.0, 5.0),
        (0.0, -5.0),
        (1.0, -1e-7),
        (1.0, 1e-7),
        (-1.0, -1e-7),
        (3.0, 4.0),
        (0.0, 0.0),
    ]
    forward = torch.tensor([case[0] for case in cases], dtype=torch.float32)
    right = torch.tensor([case[1] for case in cases], dtype=torch.float32)
    bearing, valid = batched_bearing_deg(forward, right)
    for index, (forward_m, right_m) in enumerate(cases):
        expected = bearing_from_components(forward_m, right_m)
        if expected is None:
            assert not bool(valid[index])
            assert math.isnan(float(bearing[index]))
        else:
            assert bool(valid[index])
            assert (
                angular_error_deg(float(bearing[index]), expected)
                < BEARING_TOLERANCE_DEG
            )


def test_batched_normalize_bearing_never_returns_360():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import batched_normalize_bearing_deg

    values = torch.tensor(
        [-1e-6, -360.0, 360.0, 720.0, -0.0, 359.9999],
        dtype=torch.float32,
    )
    normalized = batched_normalize_bearing_deg(values)
    assert bool((normalized >= 0.0).all())
    assert bool((normalized < 360.0).all())


def test_batched_sector_onehot_matches_scalar_mapping():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import batched_sector_onehot

    bearings = [
        deg / 10.0
        for deg in range(0, 3600)
        if min(abs((deg / 10.0 + 22.5) % 45.0), abs(45.0 - (deg / 10.0 + 22.5) % 45.0))
        > 1e-3
    ]
    tensor = torch.tensor(bearings, dtype=torch.float32)
    onehot = batched_sector_onehot(tensor, torch.ones_like(tensor, dtype=torch.bool))
    indices = onehot.argmax(dim=-1)
    for position, bearing in enumerate(bearings):
        expected = SECTOR_ORDER.index(bearing_deg_to_sector_name(bearing))
        assert int(indices[position]) == expected
    invalid = batched_sector_onehot(
        torch.tensor([float("nan")]),
        torch.tensor([False]),
    )
    assert float(invalid.abs().sum()) == 0.0


def test_batched_amplitudes_match_scalar_helper():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import (
        batched_basis_from_quat_xyzw,
        batched_mic_world_positions,
        batched_source_amplitudes,
    )

    generator = torch.Generator().manual_seed(11)
    num_envs, num_sources = 8, 2
    array_positions = (torch.rand((num_envs, 3), generator=generator) - 0.5) * 10.0
    array_quats = torch.randn((num_envs, 4), generator=generator)
    array_quats = array_quats / torch.linalg.norm(array_quats, dim=-1, keepdim=True)
    source_positions = (
        torch.rand((num_envs, num_sources, 3), generator=generator) - 0.5
    ) * 10.0
    # Push one source inside the 0.1 m distance floor.
    source_positions[0, 0] = array_positions[0] + 0.01
    source_quats = torch.randn((num_envs, num_sources, 4), generator=generator)
    source_quats = source_quats / torch.linalg.norm(
        source_quats, dim=-1, keepdim=True
    )
    gain_scale = torch.tensor([1.0, 10.0 ** (3.0 / 20.0)])
    is_cardioid = torch.tensor([False, True])
    microphones = microphone_layout("quad_front")
    mic_offsets = torch.tensor(
        [microphone.relative_position_m for microphone in microphones],
        dtype=torch.float32,
    )
    mic_gains_db = torch.tensor([0.0, -1.5, 0.5, 2.0])

    basis = batched_basis_from_quat_xyzw(array_quats)
    mic_world = batched_mic_world_positions(array_positions, basis, mic_offsets)
    amplitudes = batched_source_amplitudes(
        source_positions=source_positions,
        source_quats_xyzw=source_quats,
        source_gain_scale=gain_scale,
        source_is_cardioid=is_cardioid,
        mic_world_positions=mic_world,
        mic_gains_db=mic_gains_db,
    )

    for env_id in range(num_envs):
        for source_index in range(num_sources):
            source = AudioSourceSpec(
                source_id=f"s{source_index}",
                prim_path=f"/World/s{source_index}",
                class_label="Speech",
                audio_asset_path="generated://impulse",
                position_world=tuple(source_positions[env_id, source_index].tolist()),
                orientation_world_quat=tuple(
                    source_quats[env_id, source_index].tolist()
                ),
                start_time_s=0.0,
                duration_s=None,
                gain_db=3.0 if source_index == 1 else 0.0,
                directivity="cardioid" if source_index == 1 else "omni",
            )
            for mic_index in range(mic_offsets.shape[0]):
                expected = source_amplitude_at(
                    source,
                    tuple(mic_world[env_id, mic_index].tolist()),
                    extra_gain_db=float(mic_gains_db[mic_index]),
                )
                assert float(
                    amplitudes[env_id, source_index, mic_index]
                ) == pytest.approx(expected, rel=RMS_RTOL, abs=RMS_ATOL)


def test_batched_lstsq_matches_scalar_solver():
    torch = pytest.importorskip("torch")
    from isaac_audio_sensors.lab.batched_backend import precompute_lstsq_operator

    generator = torch.Generator().manual_seed(13)
    microphones = microphone_layout("quad_front")
    mic_offsets = torch.tensor(
        [microphone.relative_position_m for microphone in microphones],
        dtype=torch.float32,
    )
    solve_op, baseline, det = precompute_lstsq_operator(mic_offsets)
    assert abs(det) > 1e-9

    sensor = MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/rig",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=48_000,
    )
    for _ in range(32):
        delays = torch.rand((4,), generator=generator) * 1e-3
        per_mic_delay_s = {
            microphone.mic_id: float(delays[index])
            for index, microphone in enumerate(microphones)
        }
        expected = _least_squares_direction(sensor, per_mic_delay_s, 343.0)
        b = -343.0 * (delays[1:] - delays[0])
        direction = solve_op.matmul(b)
        length = float(torch.linalg.norm(direction))
        if expected is None:
            assert length <= 1e-9
            continue
        expected_ux, expected_uy, expected_uz, expected_residual = expected
        # quad_front is planar, so the scalar solver stays on the XY path.
        assert expected_uz is None
        unit = direction / length
        predicted = baseline.matmul(unit)
        residual = float(torch.sqrt(((predicted - b) ** 2).mean()))
        assert float(unit[0]) == pytest.approx(expected_ux, abs=1e-4)
        assert float(unit[1]) == pytest.approx(expected_uy, abs=1e-4)
        assert residual == pytest.approx(expected_residual, abs=1e-5)


# ---------------------------------------------------------------------------
# Sensor-level parity (the main gate)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["geometry_only", "tdoa_synthetic"])
@pytest.mark.parametrize("device", _device_params())
def test_sensor_parity_random_scene(backend: str, device: str):
    pytest.importorskip("torch")
    _skip_unless_device(device)
    num_envs = 64
    binding_cfg = _binding_cfg(num_envs=num_envs, device=device)
    scene = _random_scene(num_envs=num_envs, seed=23, device=device)
    scalar = _sensor(
        backend=backend,
        compute_path="scalar",
        scene=scene,
        binding_cfg=binding_cfg,
        device=device,
    )
    batched = _sensor(
        backend=backend,
        compute_path="batched",
        scene=scene,
        binding_cfg=binding_cfg,
        device=device,
    )
    for _ in range(3):
        scalar.update(dt=0.03, force_recompute=True)
        batched.update(dt=0.03, force_recompute=True)
    assert scalar._last_compute_path == "scalar"
    assert batched._last_compute_path == "batched"
    scalar_data = scalar.data
    batched_data = batched.data
    # The expired source must have dropped out and the future source must
    # never appear: with 4 configured sources only 2 stay active.
    assert int(scalar_data.event_presence[0].sum()) == 2
    _assert_observation_parity(scalar_data, batched_data)


@pytest.mark.parametrize("backend", ["geometry_only", "tdoa_synthetic"])
def test_sensor_parity_selected_envs_and_reset(backend: str):
    pytest.importorskip("torch")
    num_envs = 16
    binding_cfg = _binding_cfg(num_envs=num_envs)
    scene = _random_scene(num_envs=num_envs, seed=31)
    scalar = _sensor(
        backend=backend,
        compute_path="scalar",
        scene=scene,
        binding_cfg=binding_cfg,
    )
    batched = _sensor(
        backend=backend,
        compute_path="batched",
        scene=scene,
        binding_cfg=binding_cfg,
    )
    for sensor in (scalar, batched):
        sensor.update(dt=0.02, force_recompute=True)
        sensor.update(dt=0.02, force_recompute=True, env_ids=[3, 7])
        sensor.reset(env_ids=[5])
        sensor.update(dt=0.02, force_recompute=True, env_ids=[5])
    _assert_observation_parity(scalar.data, batched.data)


def test_sensor_parity_max_events_truncation():
    pytest.importorskip("torch")
    num_envs = 8
    binding_cfg = _binding_cfg(num_envs=num_envs)
    scene = _random_scene(num_envs=num_envs, seed=41)
    scalar = _sensor(
        backend="geometry_only",
        compute_path="scalar",
        scene=scene,
        binding_cfg=binding_cfg,
        max_events=1,
    )
    batched = _sensor(
        backend="geometry_only",
        compute_path="batched",
        scene=scene,
        binding_cfg=binding_cfg,
        max_events=1,
    )
    scalar.update(dt=0.01, force_recompute=True)
    batched.update(dt=0.01, force_recompute=True)
    # Two active sources, one slot: both paths must keep alpha_omni (the
    # first source in active_sources sort order).
    assert int(scalar.data.event_presence.sum()) == num_envs
    _assert_observation_parity(scalar.data, batched.data)


def test_sensor_parity_degenerate_overhead_source():
    torch = pytest.importorskip("torch")
    num_envs = 2
    identity = _wxyz((0.0, 0.0, 0.0, 1.0))
    robot_positions = torch.zeros((num_envs, 3))
    quats = torch.tensor([identity, identity], dtype=torch.float32)
    scene = SimpleNamespace(
        num_envs=num_envs,
        articulations={"robot": _entity(robot_positions, quats)},
        rigid_objects={
            "overhead": _entity(
                robot_positions + torch.tensor([0.0, 0.0, 5.0]),
                quats,
            ),
        },
    )
    binding_cfg = LabAudioEntityBindingCfg(
        num_envs=num_envs,
        robot_entity_name="robot",
        microphone_layout="quad_front",
        source_entities=(
            LabAudioSourceEntityCfg(
                entity_name="overhead",
                source_id="overhead_src",
                class_label="Alarm",
                duration_s=None,
            ),
        ),
        diagnostics=False,
    )
    scalar = _sensor(
        backend="geometry_only",
        compute_path="scalar",
        scene=scene,
        binding_cfg=binding_cfg,
    )
    batched = _sensor(
        backend="geometry_only",
        compute_path="batched",
        scene=scene,
        binding_cfg=binding_cfg,
    )
    scalar.update(dt=0.01, force_recompute=True)
    batched.update(dt=0.01, force_recompute=True)
    assert bool(batched.data.event_presence[0, 0])
    assert math.isnan(float(batched.data.bearing_deg[0, 0]))
    assert float(batched.data.confidence[0, 0]) == 0.0
    assert float(batched.data.sector_onehot[0, 0].sum()) == 0.0
    assert float(batched.data.per_mic_rms[0, 0].sum()) > 0.0
    _assert_observation_parity(scalar.data, batched.data)


# ---------------------------------------------------------------------------
# Dispatch decisions
# ---------------------------------------------------------------------------


def test_dispatch_auto_uses_batched_only_without_diagnostics():
    pytest.importorskip("torch")
    scene = _random_scene(num_envs=4, seed=51)
    quiet = _sensor(
        backend="geometry_only",
        compute_path="auto",
        scene=scene,
        binding_cfg=_binding_cfg(num_envs=4, diagnostics=False),
    )
    quiet.update(dt=0.01, force_recompute=True)
    assert quiet._last_compute_path == "batched"
    assert quiet.data.latest_frames[0] is None

    diagnosed = _sensor(
        backend="geometry_only",
        compute_path="auto",
        scene=scene,
        binding_cfg=_binding_cfg(num_envs=4, diagnostics=True),
    )
    diagnosed.update(dt=0.01, force_recompute=True)
    assert diagnosed._last_compute_path == "scalar"
    assert diagnosed.data.latest_frames[0] is not None


def test_dispatch_explicit_batched_overrides_diagnostics():
    pytest.importorskip("torch")
    scene = _random_scene(num_envs=4, seed=53)
    sensor = _sensor(
        backend="geometry_only",
        compute_path="batched",
        scene=scene,
        binding_cfg=_binding_cfg(num_envs=4, diagnostics=True),
    )
    sensor.update(dt=0.01, force_recompute=True)
    assert sensor._last_compute_path == "batched"
    assert sensor.data.latest_frames[0] is None


def test_dispatch_scalar_forces_reference_path():
    pytest.importorskip("torch")
    scene = _random_scene(num_envs=4, seed=55)
    sensor = _sensor(
        backend="geometry_only",
        compute_path="scalar",
        scene=scene,
        binding_cfg=_binding_cfg(num_envs=4, diagnostics=False),
    )
    sensor.update(dt=0.01, force_recompute=True)
    assert sensor._last_compute_path == "scalar"


def test_dispatch_non_entity_binding_stays_scalar():
    torch = pytest.importorskip("torch")
    del torch
    from isaac_audio_sensors.core.microphone_array import create_microphone_array
    from isaac_audio_sensors.core.types import AudioSceneSnapshot

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/rig",
        layout_name="quad_front",
    )
    snapshot = AudioSceneSnapshot(
        stage_id="dispatch_test",
        timestamp_ms=0,
        sources=(
            AudioSourceSpec(
                source_id="speaker",
                prim_path="/World/speaker",
                class_label="Speech",
                audio_asset_path="generated://impulse",
                position_world=(4.0, 0.0, 0.0),
                orientation_world_quat=None,
                start_time_s=0.0,
                duration_s=None,
                gain_db=0.0,
            ),
        ),
        arrays=(array,),
    )
    sensor = AudioArraySensor.from_scene_snapshot(
        cfg=AudioArraySensorCfg(
            prim_path="/World/rig",
            update_period=0.0,
            backend="geometry_only",
            max_events=2,
            compute_path="auto",
        ),
        scene_snapshot=snapshot,
        sensor=array,
    )
    sensor.update(dt=0.01, force_recompute=True)
    assert sensor._last_compute_path == "scalar"


@pytest.mark.parametrize(
    ("cfg_overrides", "binding_overrides", "match"),
    [
        ({"backend": "room_acoustics"}, {}, "no batched implementation"),
        ({"write_waveforms": True}, {}, "scalar frame pipeline"),
        (
            {"backend": "tdoa_synthetic", "microphone_layout": "stereo"},
            {
                "microphone_layout": None,
                "microphone_relative_offsets_m": (
                    ("left", (0.0, -0.08, 0.0)),
                    ("right", (0.0, 0.08, 0.0)),
                ),
            },
            "at least 3 microphones",
        ),
    ],
)
def test_dispatch_explicit_batched_raises_on_unmet_prerequisite(
    cfg_overrides: dict,
    binding_overrides: dict,
    match: str,
):
    pytest.importorskip("torch")
    scene = _random_scene(num_envs=4, seed=57)
    binding_kwargs = dict(
        num_envs=4,
        robot_entity_name="robot",
        microphone_layout="quad_front",
        source_entities=_source_entities(),
        diagnostics=False,
    )
    binding_kwargs.update(binding_overrides)
    cfg_kwargs = dict(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.0,
        backend="geometry_only",
        microphone_layout="quad_front",
        max_events=4,
        compute_path="batched",
    )
    cfg_kwargs.update(cfg_overrides)
    sensor = AudioArraySensor(cfg=AudioArraySensorCfg(**cfg_kwargs)).bind_lab_entities(
        scene=scene,
        binding_cfg=LabAudioEntityBindingCfg(**binding_kwargs),
    )
    with pytest.raises(ValueError, match=match):
        sensor.update(dt=0.01, force_recompute=True)


def test_cfg_rejects_unknown_compute_path():
    with pytest.raises(ValueError, match="compute_path"):
        AudioArraySensorCfg(
            prim_path="/World/rig",
            compute_path="warp_speed",
        )


# ---------------------------------------------------------------------------
# Perf smoke (GPU only; the live gate runs the full-size budget check)
# ---------------------------------------------------------------------------


def test_batched_perf_smoke_cuda():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is not available.")
    num_envs = 4096
    device = "cuda:0"
    binding_cfg = _binding_cfg(num_envs=num_envs, device=device)
    scene = _random_scene(num_envs=num_envs, seed=61, device=device)
    sensor = _sensor(
        backend="tdoa_synthetic",
        compute_path="batched",
        scene=scene,
        binding_cfg=binding_cfg,
        device=device,
    )
    for _ in range(5):
        sensor.update(dt=0.02, force_recompute=True)
    torch.cuda.synchronize()
    steps = 20
    started = time.perf_counter()
    for _ in range(steps):
        sensor.update(dt=0.02, force_recompute=True)
    torch.cuda.synchronize()
    ms_per_step = (time.perf_counter() - started) * 1000.0 / steps
    budget_ms = float(os.environ.get("ISAAC_AUDIO_LAB_PERF_BUDGET_MS", "20.0"))
    assert sensor._last_compute_path == "batched"
    assert ms_per_step < budget_ms, (
        f"batched path took {ms_per_step:.3f} ms/step for {num_envs} envs "
        f"(budget {budget_ms} ms)"
    )
