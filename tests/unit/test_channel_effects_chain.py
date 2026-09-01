from __future__ import annotations

import importlib
from types import MappingProxyType

import numpy as np
import pytest

from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    ChannelEffectsChain,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    FrequencyResponsePointConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.exceptions import ConfigValidationError

SAMPLE_RATE_HZ = 48_000


def _base_raw() -> dict[str, object]:
    return {
        "scene": {"scene_id": "effects_config"},
        "audio": {
            "default_backend": "analytic_acoustics",
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": SAMPLE_RATE_HZ,
        },
        "environment": {
            "environment_id": "effects_environment",
            "kind": "shoebox",
            "dimensions_m": [6.0, 6.0, 3.0],
        },
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig",
                "microphones": [
                    {"mic_id": "front"},
                    {"mic_id": "right"},
                    {"mic_id": "rear"},
                    {"mic_id": "left"},
                ],
            }
        },
    }


def _active_effects(mic: ChannelResponseMicConfig) -> EffectsConfig:
    return EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"front": mic},
        )
    )


def test_chain_all_disabled_returns_exact_input_identity_and_empty_diagnostics():
    owner = np.arange(64, dtype=np.float32).reshape(4, 16)
    samples = owner[:, ::-1]
    before = samples.tobytes(order="A")
    metadata = (samples.dtype, samples.shape, samples.strides)

    output, diagnostics = ChannelEffectsChain(EffectsConfig()).apply(
        samples,
        mic_ids=("front", "right", "rear", "left"),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="off_state",
    )

    assert output is samples
    assert diagnostics == {}
    assert (output.dtype, output.shape, output.strides) == metadata
    assert output.tobytes(order="A") == before


def test_absent_effects_table_normalizes_all_four_stages_disabled():
    config = validate_audio_config(_base_raw())
    assert isinstance(config.effects, EffectsConfig)
    assert config.effects.all_disabled
    assert not config.effects.channel_response.enabled
    assert not config.effects.noise.enabled
    assert not config.effects.electronics.enabled
    assert not hasattr(config.effects, "directivity")
    assert not config.effects.motion.derive_velocity_from_poses


def test_toml_shape_parses_to_immutable_mapping_and_tuple_records():
    raw = _base_raw()
    raw["audio"]["effects"] = {  # type: ignore[index]
        "channel_response": {
            "enabled": True,
            "microphones": {
                "front": {
                    "gain_db": -0.75,
                    "delay_s": 0.0000125,
                    "polarity": -1,
                    "frequency_response": [
                        {"frequency_hz": 100.0, "magnitude_db": -1.0},
                        {"frequency_hz": 1_000.0, "magnitude_db": 0.0},
                        {"frequency_hz": 16_000.0, "magnitude_db": -2.0},
                    ],
                }
            },
        }
    }
    config = validate_audio_config(raw)
    microphones = config.effects.channel_response.microphones
    assert isinstance(microphones, MappingProxyType)
    assert microphones["front"].frequency_response[1].frequency_hz == 1_000.0
    with pytest.raises(TypeError):
        microphones["front"] = ChannelResponseMicConfig()  # type: ignore[index]


def test_duplicate_microphone_id_after_normalization_fails_closed():
    with pytest.raises(ConfigValidationError, match="duplicate id '1'"):
        parse_effects_config(
            {
                "channel_response": {
                    "enabled": True,
                    "microphones": {
                        1: {"gain_db": -3.0},
                        "1": {"gain_db": 6.0},
                    },
                }
            }
        )


@pytest.mark.parametrize(
    ("microphones", "match"),
    [
        ({"unknown": {"gain_db": 1.0}}, "unknown exact"),
        (
            {"right": {"gain_db": 1.0}, "front": {"gain_db": 1.0}},
            "order mismatch",
        ),
    ],
)
def test_unknown_microphone_and_order_mismatch_fail_config(microphones, match):
    raw = _base_raw()
    raw["audio"]["effects"] = {  # type: ignore[index]
        "channel_response": {"enabled": True, "microphones": microphones}
    }
    with pytest.raises(ConfigValidationError, match=match):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("mic", "match"),
    [
        (ChannelResponseMicConfig(gain_db=float("nan")), "gain_db"),
        (ChannelResponseMicConfig(delay_s=float("inf")), "delay_s"),
        (ChannelResponseMicConfig(polarity=0), "polarity"),
        (
            ChannelResponseMicConfig(
                frequency_response=(
                    FrequencyResponsePointConfig(frequency_hz=100.0, magnitude_db=0.0),
                )
            ),
            "at least two",
        ),
        (
            ChannelResponseMicConfig(
                frequency_response=(
                    FrequencyResponsePointConfig(
                        frequency_hz=1_000.0, magnitude_db=0.0
                    ),
                    FrequencyResponsePointConfig(frequency_hz=500.0, magnitude_db=0.0),
                )
            ),
            "strictly increasing",
        ),
        (
            ChannelResponseMicConfig(
                frequency_response=(
                    FrequencyResponsePointConfig(frequency_hz=100.0, magnitude_db=0.0),
                    FrequencyResponsePointConfig(
                        frequency_hz=24_001.0, magnitude_db=0.0
                    ),
                )
            ),
            "Nyquist",
        ),
    ],
)
def test_invalid_channel_config_matrix_fails_before_processing(mic, match):
    samples = np.ones((1, 1_024), dtype=np.float64)
    with pytest.raises(ConfigValidationError, match=match):
        ChannelEffectsChain(_active_effects(mic)).apply(
            samples,
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id="invalid",
        )
    assert np.array_equal(samples, np.ones_like(samples))


def test_non_null_phase_is_typed_unsupported_error():
    mic = ChannelResponseMicConfig(
        frequency_response=(
            FrequencyResponsePointConfig(
                frequency_hz=100.0,
                magnitude_db=0.0,
                phase_deg=1.0,
            ),
            FrequencyResponsePointConfig(
                frequency_hz=1_000.0,
                magnitude_db=0.0,
            ),
        )
    )
    with pytest.raises(UnsupportedEffectError, match="phase_deg"):
        ChannelEffectsChain(_active_effects(mic)).apply(
            np.ones((1, 1_024), dtype=np.float64),
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id="phase",
        )


def test_waveform_response_fails_under_training_features_profile():
    raw = _base_raw()
    raw["audio"]["runtime_profile"] = "training_features"  # type: ignore[index]
    raw["audio"]["effects"] = {  # type: ignore[index]
        "channel_response": {
            "enabled": True,
            "microphones": {
                "front": {
                    "frequency_response": [
                        {"frequency_hz": 100.0, "magnitude_db": -1.0},
                        {"frequency_hz": 1_000.0, "magnitude_db": 0.0},
                    ]
                }
            },
        }
    }
    with pytest.raises(UnsupportedEffectError, match="training_features"):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("samples", "mic_ids", "match"),
    [
        (np.ones(16), ("front",), "microphone-major"),
        (np.ones((0, 16)), (), "at least one channel"),
        (np.ones((2, 16)), ("front",), "microphone-count/order"),
        (np.ones((1, 16), dtype=np.int16), ("front",), "floating dtype"),
        (np.asarray([[float("nan")]]), ("front",), "non-finite"),
    ],
)
def test_active_chain_rejects_invalid_runtime_arrays(samples, mic_ids, match):
    effects = _active_effects(ChannelResponseMicConfig(gain_db=1.0))
    with pytest.raises(ConfigValidationError, match=match):
        ChannelEffectsChain(effects).apply(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id="invalid_array",
        )


def test_delay_larger_than_usable_window_fails_closed():
    samples = np.ones((1, 16), dtype=np.float64)
    effects = _active_effects(ChannelResponseMicConfig(delay_s=16 / SAMPLE_RATE_HZ))
    with pytest.raises(ConfigValidationError, match="no non-empty valid region"):
        ChannelEffectsChain(effects).apply(
            samples,
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id="delay_too_large",
        )


@pytest.mark.parametrize("sample_count", [0, 1])
def test_empty_and_one_sample_gain_inputs_do_not_invent_samples(sample_count):
    samples = np.ones((1, sample_count), dtype=np.float64)
    output, diagnostics = ChannelEffectsChain(
        _active_effects(ChannelResponseMicConfig(gain_db=-6.0))
    ).apply(
        samples,
        mic_ids=("front",),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="minimum_window",
    )
    assert output.shape == samples.shape
    assert diagnostics["channel_response"]["gain_delta_db"] == {"front": -6.0}


@pytest.mark.parametrize("stage", ["noise", "electronics"])
def test_later_effect_stages_fail_typed_instead_of_silently_running(stage):
    raw = {stage: {"enabled": True}}
    effects = parse_effects_config(raw)
    with pytest.raises(UnsupportedEffectError, match=stage):
        ChannelEffectsChain(effects).apply(
            np.ones((1, 16), dtype=np.float64),
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id="deferred_stage",
        )


def test_removed_directivity_effect_is_an_unknown_config_key() -> None:
    with pytest.raises(ConfigValidationError, match="unsupported fields.*directivity"):
        parse_effects_config({"directivity": {"enabled": True}})

    raw = _base_raw()
    raw["audio"]["effects"] = {"directivity": {"enabled": True}}
    with pytest.raises(ConfigValidationError, match="unsupported fields.*directivity"):
        validate_audio_config(raw)


def test_removed_directivity_effect_has_no_import_or_export_surface() -> None:
    effects = importlib.import_module("isaac_audio_sensors.core.effects")
    config = importlib.import_module("isaac_audio_sensors.core.effects.config")

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("isaac_audio_sensors.core.effects.directivity")
    for removed_name in (
        "DirectivityConfig",
        "DirectivityFrequencyPointConfig",
        "DirectivityPatternConfig",
        "DirectivityPatternSetConfig",
    ):
        assert not hasattr(effects, removed_name)
        assert not hasattr(config, removed_name)


def test_enabled_noop_channel_is_not_reported_as_applied():
    effects = _active_effects(ChannelResponseMicConfig())
    samples = np.ones((1, 16), dtype=np.float64)
    output, diagnostics = ChannelEffectsChain(effects).apply(
        samples,
        mic_ids=("front",),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="noop",
    )
    assert output is samples
    assert diagnostics == {}
