"""Opt-in nominal indoor trial configuration; start AppLauncher before importing.

16 kHz; causal 200 ms context; no WPE; coherence .98; azimuth only.
Use exactly one active voice with a visible direct path. Runtime qualification
covers the measured scene and load in the readiness page; it is not a physical
array calibration. Preserve the declared quality and GPU-contention limits.
"""

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.effects import (
    EffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.types import MicrophoneSpec
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    EntityBindingCfg,
    SourceEntityCfg,
)

NOMINAL_SQUARE = tuple(
    MicrophoneSpec(mic_id=str(i), relative_position_m=position)
    for i, position in enumerate(
        ((-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0), (0.033, -0.033, 0))
    )
)


INDOOR_TEST_NOISE = EffectsConfig(
    noise=NoiseConfig(
        enabled=True,
        seed=11700,
        self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-65.0)),
    )
)


def bind_indoor_single_voice(
    scene,
    *,
    prim_path,
    head_body_name,
    acoustic_scenes,
    geometry_config,
    audio_asset_path,
    microphones=NOMINAL_SQUARE,
    array_relative_position_m=(0.0, 0.0, 0.0),
    array_relative_orientation_quat=(0.0, 0.0, 0.0, 1.0),
    effects=None,
):
    """Bind an observed head body and one emitter using consumer-owned mount data.

    prim_path must resolve once per environment; the binding selects the head body.
    Use indoor_single_voice_room.usda with roots ("/World/Room/Envelope",).
    The default synthetic -65 dBFS noise matches the test, not a calibration.
    Quality/performance qualification covers one environment only.
    Pass isolated prepared acoustic sessions, and GeometryAcousticsConfig with
    rebuilt libraries, order 3, max_delay_s=1, diffuse=None and nlos=None for the
    measured room domain. Different geometry/mounts need consumer validation.
    Call sensor.update(dt) on EVERY 60 Hz physics step; read sensor.data at 10 Hz.
    Preserve masks, ambiguity and truncation; confidence is unavailable.
    """
    return AudioArraySensor(
        AudioArraySensorCfg(
            prim_path=prim_path,
            backend="geometry_acoustics",
            geometry_config=geometry_config,
            update_period=0.1,
            energy_threshold_dbfs=-60.0,
            doa_enabled=True,
            max_observations=32,
            max_doa_candidates=2,
            localization_context_s=0.2,
            localization_dereverberation=False,
            localization_spatial_coherence=0.98,
            effects=effects if effects is not None else INDOOR_TEST_NOISE,
        )
    ).bind_entities(
        scene,
        EntityBindingCfg(
            environment=free_field_environment(environment_id="indoor_trial"),
            sample_rate_hz=16000,
            array_mount_body_name=head_body_name,
            array_relative_position_m=array_relative_position_m,
            array_relative_orientation_quat=array_relative_orientation_quat,
            microphones=microphones,
            source_entities=(
                SourceEntityCfg(
                    entity_name="speaker",
                    audio_asset_path=audio_asset_path,
                    duration_s=None,
                    loop_count=-1,
                ),
            ),
        ),
        acoustic_scenes=acoustic_scenes,
    )
