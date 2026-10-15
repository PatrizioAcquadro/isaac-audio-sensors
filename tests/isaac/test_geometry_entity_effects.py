"""Native entity effects must reach CUDA PCM once and survive partial resets."""

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.effects import (
    EffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg
from isaac_audio_sensors.lab._geometry_audio import GeometryEntityAudio
from isaac_audio_sensors.lab.entity_binding import (
    EntityBinding,
    EntityBindingCfg,
    SourceEntityCfg,
)
from tests.isaac.geometry_helpers import LIBRARY, SPECULAR_LIBRARY, stage


def test_geometry_entity_noise_matches_core_and_partial_reset(tmp_path, monkeypatch):
    from scipy.io.wavfile import write

    from isaac_audio_sensors.isaac.acoustic_scene import (
        GeometryAcoustics,
        GeometryAcousticsConfig,
    )

    if not LIBRARY.exists() or not SPECULAR_LIBRARY.exists():
        pytest.skip("Native providers unavailable")
    assert torch.cuda.is_available(), "Actual CUDA required"
    monkeypatch.chdir(tmp_path)
    write(
        "voice.wav",
        16000,
        np.random.default_rng(2).normal(0, 0.05, 16000).astype(np.float32),
    )
    effects = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=19,
            self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-65)),
        )
    )
    cfg = AudioArraySensorCfg(
        prim_path="/World/Audio",
        backend="geometry_acoustics",
        update_period=0.1,
        energy_threshold_dbfs=-60.0,
        effects=effects,
        geometry_config=GeometryAcousticsConfig(
            library_path=str(LIBRARY),
            specular_library_path=str(SPECULAR_LIBRARY),
            reflection_order=0,
        ),
    )
    states = torch.zeros((2, 13), device="cuda:0")
    states[:, 3] = 1
    speakers = states.clone()
    speakers[:, 0] = 2
    entities = {
        k: SimpleNamespace(data=SimpleNamespace(root_state_w=v))
        for k, v in [("robot", states), ("speaker", speakers)]
    }
    binding = EntityBinding(
        entities,
        EntityBindingCfg(
            environment=free_field_environment(environment_id="test"),
            source_entities=(
                SourceEntityCfg(
                    entity_name="speaker", audio_asset_path="voice.wav", duration_s=None
                ),
            ),
        ),
    )
    from pxr import UsdGeom

    stages = [stage() for _ in range(2)]
    for value in stages:
        UsdGeom.Cube.Define(value, "/Remote").AddTranslateOp().Set((100, 100, -100))
    sessions = [AcousticSceneSession(value) for value in stages]
    fake = SimpleNamespace(
        cfg=cfg,
        _entity_binding=binding,
        _reference_backend=None,
        _acoustic_scenes=sessions,
        is_initialized=False,
    )
    AudioArraySensor._validate_bound_runtime(fake)
    backend = GeometryEntityAudio(binding, cfg, sessions)
    expected = GeometryAcoustics(
        acoustic_scene=sessions[0], geometry_config=cfg.geometry_config, effects=effects
    )
    try:
        from isaac_audio_sensors.core.types import AudioTimeWindow

        snapshot = backend.snapshots()[0]
        target = expected.propagate(
            snapshot,
            "array",
            AudioTimeWindow(start_time_s=0.0, end_time_s=0.1, frame_index=0),
        ).samples
        backend.acquire(torch.full((2,), 0.1, dtype=torch.float64, device="cuda:0"))
        np.testing.assert_array_equal(
            backend.perception.history[0, :, -1600:].cpu().numpy(), target
        )
        initial = backend.perception.history[0].clone()
        neighbor = backend.perception.history[1].clone()
        backend.reset(backend.ids[:1])
        backend.acquire(torch.tensor([0.1, 0.1], dtype=torch.float64, device="cuda:0"))
        torch.testing.assert_close(
            backend.perception.history[0], initial, atol=0, rtol=0
        )
        torch.testing.assert_close(
            backend.perception.history[1], neighbor, atol=0, rtol=0
        )
        assert backend.cursor.tolist() == [1600, 1600]
    finally:
        expected.close()
        backend.close()
        for session in sessions:
            session.close()
