"""Mixture parity and independence for CUDA audio computation."""

import numpy as np
import pytest
import torch

from isaac_audio_sensors.lab._torch_localizer import TorchEventLocalizer, dereverberate

LAYOUTS = (
    ((-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0)),
    ((-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0), (0.033, -0.033, 0)),
    (
        (-0.03, -0.03, 0),
        (-0.03, 0.03, 0),
        (0.03, 0.03, 0),
        (0.03, -0.03, 0),
        (0, 0, 0.04),
    ),
    (
        (0.03, 0.03, 0.03),
        (0.03, -0.03, -0.03),
        (-0.03, 0.03, -0.03),
        (-0.03, -0.03, 0.03),
    ),
)


def mixture(positions, count=2):
    rng = np.random.default_rng(72)
    positions = np.array(positions)
    result = np.zeros((len(positions), 12000))
    t = np.arange(12000) / 16000
    for az, el in ((20, 15), (100, -25))[:count]:
        az, el = np.radians([az, el if positions[:, 2].any() else 0])
        direction = np.array(
            [np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), np.sin(el)]
        )
        emitted = rng.normal(0, 0.08, 14000)
        for channel, position in enumerate(positions):
            result[channel] += np.interp(
                (t + position @ direction / 343) * 16000 + 1000,
                np.arange(len(emitted)),
                emitted,
            )
    return result.astype(np.float32)


@pytest.fixture
def cuda():
    if not torch.cuda.is_available():
        pytest.fail("CUDA audio validation requires the actual GPU.")
    return "cuda:0"


def test_wpe_batch_independence_and_silence(cuda):
    torch.manual_seed(72)
    samples = torch.randn(1, 4, 12000, device=cuda) * 0.08
    alone = dereverberate(samples)
    mixed = dereverberate(
        torch.cat([samples, samples * 1e-7, torch.zeros_like(samples)])
    )
    torch.testing.assert_close(mixed[:1], alone, atol=1e-6, rtol=1e-4)
    torch.testing.assert_close(mixed[1:2] / 1e-7, alone, atol=1e-6, rtol=1e-4)
    assert torch.isfinite(mixed).all()
    assert not mixed[2].any()


@pytest.mark.parametrize("positions", LAYOUTS[1:3])
@pytest.mark.parametrize("bearing", [0, 45, 90, 135])
def test_symmetric_direct_channels_preserve_wpe_and_direction(positions, bearing, cuda):
    from isaac_audio_sensors.core.plugins._multisource_sparse import (
        WpeSparseCovariance,
        _dereverberate,
    )

    positions = np.asarray(positions)
    azimuth = np.radians(bearing)
    direction = np.array([np.cos(azimuth), np.sin(azimuth), 0])
    distances = np.linalg.norm(3 * direction - positions, axis=1)
    emitted = np.random.default_rng(77101).normal(0, 0.1, 16000)
    samples = np.array(
        [
            np.interp(
                np.arange(12000) + 1000 - distance * 16000 / 343,
                np.arange(len(emitted)),
                emitted,
            )
            / (4 * np.pi * distance)
            for distance in distances
        ],
        dtype=np.float32,
    )
    expected_pcm = _dereverberate(samples, 16000)
    actual_pcm = (
        dereverberate(torch.tensor(samples[None], device=cuda))[0].cpu().numpy()
    )
    assert np.isfinite(actual_pcm).all()
    assert (
        np.linalg.norm(actual_pcm - expected_pcm) / np.linalg.norm(expected_pcm) < 1e-4
    )
    expected, _ = WpeSparseCovariance().localize(samples, positions, 16000)
    model = TorchEventLocalizer(positions, device=cuda)
    found, mask = model.localize(torch.tensor(samples[None], device=cuda))
    actual = found[0, mask[0]].cpu().numpy()
    assert len(actual) == len(expected) == 1
    assert actual[0] @ direction > np.cos(np.radians(5))
    assert np.linalg.norm(actual[0] - expected[0]) < 0.002


@pytest.mark.parametrize("seed", [2, 10])
def test_equal_peak_plateaus_preserve_events_across_precision_and_device(seed, cuda):
    from isaac_audio_sensors.core.plugins._multisource_sparse import (
        GroupSparseCovariance,
    )

    positions = np.asarray(LAYOUTS[2])
    scalar = GroupSparseCovariance()
    _, (vectors, _, near) = scalar.prepare(np.zeros((5, 12000)), positions, 16000)
    rng = np.random.default_rng(seed)
    histogram = np.zeros(len(vectors), dtype=np.float32)
    # Sparse support creates equal neighborhood sums away from the threshold.
    histogram[rng.choice(len(vectors), 30, replace=False)] = rng.uniform(
        0.005, 0.05, 30
    )
    expected, _ = scalar.events(vectors, histogram.astype(np.float64), near, {})
    actual, _ = scalar.events(vectors, histogram, near, {})
    np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)
    model = TorchEventLocalizer(positions, device=cuda)
    found, mask = model._events(torch.tensor(histogram[None], device=cuda))
    actual = found[0, mask[0]].cpu().numpy()
    assert len(actual) == len(expected)
    distances = np.linalg.norm(actual[:, None] - expected, axis=-1)
    assert distances.min(axis=0).max() < 1e-12
    assert distances.min(axis=1).max() < 1e-12


@pytest.mark.parametrize("positions", LAYOUTS)
def test_cuda_localizer_matches_scalar_mixtures(positions, cuda):
    from isaac_audio_sensors.core.plugins._multisource_sparse import WpeSparseCovariance

    values = np.stack([mixture(positions, count) for count in (0, 1, 2)])
    localizer = TorchEventLocalizer(np.array(positions), device=cuda)
    directions, mask = localizer.localize(torch.tensor(values, device=cuda))
    for index, samples in enumerate(values):
        expected, _ = WpeSparseCovariance().localize(
            samples.astype(float), np.array(positions), 16000
        )
        actual = directions[index, mask[index]].cpu().numpy()
        assert len(actual) == len(expected)
        if len(actual):
            errors = np.degrees(np.arccos(np.clip(actual @ expected.T, -1, 1)))
            # Float32 spatial fitting and output vectors retain sub-grid agreement.
            assert errors.min(axis=0).max() < 0.1
    permutation = torch.tensor([2, 0, 1], device=cuda)
    shuffled, shuffled_mask = localizer.localize(
        torch.tensor(values, device=cuda)[permutation]
    )
    torch.testing.assert_close(mask[permutation], shuffled_mask)
    torch.testing.assert_close(
        directions[permutation][shuffled_mask],
        shuffled[shuffled_mask],
        atol=1e-5,
        rtol=1e-4,
    )
    alone, valid = localizer.localize(torch.tensor(values[2:3], device=cuda))
    torch.testing.assert_close(
        directions[2, mask[2]], alone[0, valid[0]], atol=1e-5, rtol=1e-4
    )


@pytest.mark.parametrize("capacity", [1, 3])
def test_cuda_bearing_order_and_truncation_match_core(cuda, capacity):
    from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer
    from isaac_audio_sensors.lab._torch_perception import TorchPerception

    positions = np.asarray(LAYOUTS[1])
    angle = np.radians(60)
    rotation = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle), np.cos(angle), 0],
            [0, 0, 1],
        ]
    )
    samples = mixture(positions @ rotation.T)
    events, _ = MaintainedEventLocalizer().localize(samples, positions, 16000)
    expected = sorted(event.estimated_bearing_deg for event in events)
    assert len(expected) == 2 and expected[0] < 180 < expected[1]
    p = TorchPerception(
        num_envs=1,
        positions=positions,
        threshold_dbfs=-60,
        doa_enabled=True,
        max_observations=capacity,
        max_doa_candidates=2,
        device=cuda,
    )
    ids = torch.tensor([0], device=cuda)
    p.ingest(
        ids,
        torch.tensor(samples[None], device=cuda),
        torch.tensor([12000], device=cuda),
    )
    data = p.observations(ids)
    actual = data.bearing_deg[0, data.bearing_deg_mask[0]].cpu().numpy()
    np.testing.assert_allclose(actual, expected[:capacity], atol=0.1, rtol=0)
    assert int(data.observations_truncated[0]) == max(0, len(expected) - capacity)


def test_raised_correlated_channels_preserve_reference_events(cuda):
    from isaac_audio_sensors.core.plugins._multisource_sparse import WpeSparseCovariance

    # Nearby channels make WPE ill-conditioned with independent emitters.
    rng = np.random.default_rng(72)
    azimuth = rng.uniform(-np.pi, np.pi, 4096)
    radius = rng.uniform(1.5, 3, 4096)
    height = radius * np.tan(rng.uniform(-np.pi / 6, np.pi / 6, 4096))
    rng = np.random.default_rng(350)
    assets = rng.normal(0, 0.08, (2, 32000)).astype(np.float32)
    positions = np.asarray(LAYOUTS[2], dtype=np.float32)
    values = []
    times = np.arange(13600, 25600) / 16000
    for index in (9, 12, 46, 62):
        x, y = radius[index] * np.array(
            [np.cos(azimuth[index]), np.sin(azimuth[index])]
        )
        sources = np.array(
            [[x, y, height[index]], [-y, x, height[index]]], dtype=np.float32
        )
        samples = np.zeros((5, 12000), dtype=np.float32)
        for source, asset in zip(sources, assets, strict=True):
            distance = np.linalg.norm(source - positions, axis=1)
            for channel, d in enumerate(distance):
                samples[channel] += np.interp(
                    (times - float(d / np.float32(343))) * 16000,
                    np.arange(len(asset)),
                    asset,
                ).astype(np.float32) / (4 * np.pi * d)
        values.append(samples)
    localizer = TorchEventLocalizer(positions, device=cuda)
    vectors, mask = localizer.localize(torch.tensor(np.stack(values), device=cuda))
    for row, samples in enumerate(values):
        expected, _ = WpeSparseCovariance().localize(
            samples.astype(float), positions, 16000
        )
        actual = vectors[row, mask[row]].cpu().numpy()
        assert len(actual) == len(expected)
        errors = np.degrees(np.arccos(np.clip(actual @ expected.T, -1, 1)))
        assert errors.min(axis=0).max() < 0.5


@pytest.mark.parametrize("block_size", [267, 800, 1600])
def test_cuda_activity_matches_auditok_tokens(cuda, block_size):
    from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector
    from isaac_audio_sensors.lab._torch_perception import activity

    rng = np.random.default_rng(18)
    # Include isolated short activity, tolerated gaps, tails and channel-any energy.
    signals = rng.choice([0.0, 0.1], size=(24, 2, 12))
    signals = np.repeat(signals, 800, axis=-1).astype(np.float32)
    detectors = [AuditokActivityDetector(energy_threshold_dbfs=-40) for _ in signals]
    history = torch.zeros((24, 2, 16000), device=cuda)
    for start in range(0, signals.shape[-1], block_size):
        block = signals[..., start : start + block_size]
        n = block.shape[-1]
        history = torch.cat(
            [history[..., n:], torch.tensor(block, device=cuda)], dim=-1
        )
        actual = activity(
            history,
            torch.full((24,), start + n, device=cuda),
            torch.full((24,), start, device=cuda),
            -40,
        )
        expected = [
            detector.detect(samples, 16000).active
            for detector, samples in zip(detectors, block, strict=True)
        ]
        assert actual.tolist() == expected


@pytest.mark.parametrize("capacity", [0, 1, 3])
def test_perception_partial_reset_and_capacity(cuda, capacity):
    from isaac_audio_sensors.lab._torch_perception import TorchPerception

    p = TorchPerception(
        num_envs=2,
        positions=LAYOUTS[1],
        threshold_dbfs=-60,
        doa_enabled=True,
        max_observations=capacity,
        max_doa_candidates=2,
        device=cuda,
    )
    samples = torch.tensor(np.stack([mixture(LAYOUTS[1])] * 2), device=cuda)
    ids = torch.arange(2, device=cuda)
    for start in range(0, 12000, 1600):
        values = samples[..., start : start + 1600]
        p.ingest(ids, values, torch.full((2,), values.shape[-1], device=cuda))
        result = p.observations(ids)
        if start + values.shape[-1] < 12000:
            assert not result.observation_mask.any()
    assert (result.observation_mask.sum(dim=1) == min(2, capacity)).all()
    assert (result.observations_truncated == max(0, 2 - capacity)).all()
    assert not result.bearing_confidence_mask.any()
    untouched = p.history[0].clone()
    p.reset(ids[1:])
    torch.testing.assert_close(p.history[0], untouched)
    assert p.samples.tolist() == [12000, 0]
    result = p.observations(ids)
    assert result.observation_mask.sum(dim=1).tolist() == [min(2, capacity), 0]


def test_entity_received_pcm_matches_core_and_partial_reset(
    cuda, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import soundfile as sf

    from isaac_audio_sensors.core.acoustics import free_field_environment
    from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
    from isaac_audio_sensors.core.types import (
        AudioSceneSnapshot,
        AudioSourceSpec,
        AudioTimeWindow,
        MicrophoneArraySpec,
        MicrophoneSpec,
    )
    from isaac_audio_sensors.lab._entity_audio import EntityAudioBackend
    from isaac_audio_sensors.lab.entity_binding import (
        EntityBinding,
        EntityBindingCfg,
        SourceEntityCfg,
    )

    monkeypatch.chdir(tmp_path)
    sf.write(
        "sound.wav",
        np.random.default_rng(2).normal(0, 0.1, 4500),
        16000,
        subtype="FLOAT",
    )
    robot = torch.zeros((2, 13), device=cuda)
    robot[:, 3] = 1
    source_state = robot.clone()
    source_state[:, :3] = torch.tensor([[1.5, 0.5, 0], [0, 2, 0]], device=cuda)
    scene = {
        name: SimpleNamespace(data=SimpleNamespace(root_state_w=state))
        for name, state in (("robot", robot), ("speaker", source_state))
    }
    microphones = tuple(
        MicrophoneSpec(mic_id=str(i), relative_position_m=p)
        for i, p in enumerate(LAYOUTS[1])
    )
    environment = free_field_environment(environment_id="test")
    binding = EntityBinding(
        scene,
        EntityBindingCfg(
            environment=environment,
            microphones=microphones,
            source_entities=(
                SourceEntityCfg(
                    entity_name="speaker",
                    audio_asset_path="sound.wav",
                    start_time_s=0.05,
                    duration_s=0.5,
                    loop_count=1,
                ),
            ),
        ),
    )
    cfg = SimpleNamespace(
        speed_of_sound_mps=343,
        update_period=0.1,
        energy_threshold_dbfs=-60,
        doa_enabled=False,
        max_observations=1,
        max_doa_candidates=2,
    )
    gpu = EntityAudioBackend(binding, cfg)
    array = MicrophoneArraySpec(
        array_id="a",
        prim_path="/a",
        position_world=(0, 0, 0),
        orientation_world_quat=(0, 0, 0, 1),
        sample_rate_hz=16000,
        microphones=microphones,
    )
    snapshot = AudioSceneSnapshot(
        stage_id="test",
        arrays=(array,),
        environment=environment,
        sources=(
            AudioSourceSpec(
                source_id="s",
                prim_path="/s",
                class_label="Sound",
                audio_asset_path="sound.wav",
                position_world=(1.5, 0.5, 0),
                orientation_world_quat=(0, 0, 0, 1),
                start_time_s=0.05,
                duration_s=0.5,
                gain_db=0,
                loop_count=1,
            ),
        ),
    )
    core = AnalyticAcoustics()
    previous = 0
    times = torch.zeros(2, dtype=torch.float64, device=cuda)
    for tick in range(40):
        times += 1 / 60
        gpu.acquire(times)
        end = int(gpu.cursor[0])
        block = core.propagate(
            snapshot,
            "a",
            AudioTimeWindow(
                start_time_s=previous / 16000, end_time_s=end / 16000, frame_index=tick
            ),
        )
        actual = gpu.perception.history[0, :, -(end - previous) :].cpu().numpy()
        np.testing.assert_allclose(actual, block.samples, rtol=2e-4, atol=2e-7)
        previous = end
    retained = gpu.perception.history[0].clone()
    gpu.reset(torch.tensor([1], device=cuda))
    torch.testing.assert_close(gpu.perception.history[0], retained)
    assert gpu.cursor[1] == 0
    times[1] = 0
    times += 0.2
    gpu.acquire(times)
    assert gpu.perception.discontinuity.all()
    assert not gpu.perception.history.any()
    times += 1 / 60
    gpu.acquire(times)
    assert not gpu.perception.discontinuity.any()
    assert gpu.discontinuity_count.tolist() == [1, 1]
    gpu.reset(torch.tensor([1], device=cuda))
    assert gpu.discontinuity_count.tolist() == [1, 0]


@pytest.mark.parametrize("threshold", [-1e6, 1e6])
def test_activity_extreme_finite_thresholds_match_reference(cuda, threshold):
    from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector
    from isaac_audio_sensors.lab._torch_perception import activity

    values = np.zeros((2, 1600), dtype=np.float32)
    history = torch.zeros((1, 2, 16000), device=cuda)
    actual = activity(
        history,
        torch.tensor([1600], device=cuda),
        torch.tensor([0], device=cuda),
        threshold,
    )
    expected = AuditokActivityDetector(energy_threshold_dbfs=threshold).detect(
        values, 16000
    )
    assert bool(actual[0]) == expected.active
