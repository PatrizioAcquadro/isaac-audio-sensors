"""Frozen S3.6 waveform-directivity acceptance coverage."""

from __future__ import annotations

import math
from dataclasses import fields
from types import MappingProxyType

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.amplitude import directivity_factor
from isaac_audio_sensors.core.backends.room_acoustics import (
    _apply_directivity_to_premix,
)
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import (
    parse_effects_config,
    validate_effects_config,
)
from isaac_audio_sensors.core.effects.directivity import (
    apply_pair_directivity,
    directivity_diagnostics,
    evaluate_polar_pattern,
    microphone_polar_gain,
    microphone_world_orientation,
    resolve_pattern,
    source_polar_gain,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.core.types import (
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
)

SAMPLE_RATE_HZ = 48_000
R = math.sqrt(0.5)
CARDINAL_QUATERNIONS = (
    (0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, R, R),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, -R, R),
)
CARDINAL_TARGETS = {
    "omni": (1.0, 1.0, 1.0, 1.0),
    "cardioid": (1.0, 0.5, 0.0, 0.5),
    "figure_eight": (1.0, 0.0, -1.0, 0.0),
    "supercardioid": (1.0, 0.37, -0.26, 0.37),
}
FREQUENCY_POINTS = (
    DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=-6.0),
    DirectivityFrequencyPointConfig(freq_hz=1000.0, gain_db=0.0),
    DirectivityFrequencyPointConfig(freq_hz=8000.0, gain_db=-3.0),
    DirectivityFrequencyPointConfig(freq_hz=20_000.0, gain_db=-9.0),
)


def _pattern(
    family: str,
    *,
    frequency_points: tuple[DirectivityFrequencyPointConfig, ...] | None = None,
) -> DirectivityPatternConfig:
    return DirectivityPatternConfig(
        family=family,
        frequency_points=frequency_points,
    )


def _source(
    *,
    source_id: str = "talker",
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    orientation: tuple[float, float, float, float] | None = (0.0, 0.0, 0.0, 1.0),
    directivity: str = "omni",
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/{source_id}",
        class_label="speaker",
        audio_asset_path="generated://deterministic_pulse",
        position_world=position,
        orientation_world_quat=orientation,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
        directivity=directivity,
    )


def _array() -> MicrophoneArraySpec:
    microphones = (
        MicrophoneSpec(mic_id="front", relative_position_m=(0.0, 0.0, 0.0)),
        MicrophoneSpec(mic_id="right", relative_position_m=(0.0, 0.08, 0.0)),
        MicrophoneSpec(mic_id="rear", relative_position_m=(0.0, -0.08, 0.0)),
        MicrophoneSpec(mic_id="top", relative_position_m=(0.0, 0.0, 0.08)),
    )
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _active_config(
    *,
    source: DirectivityPatternConfig | None = None,
    microphone: DirectivityPatternConfig | None = None,
) -> DirectivityConfig:
    return DirectivityConfig(
        enabled=True,
        source_patterns=(
            None if source is None else DirectivityPatternSetConfig(default=source)
        ),
        mic_patterns=(
            None
            if microphone is None
            else DirectivityPatternSetConfig(default=microphone)
        ),
    )


def _validate(config: DirectivityConfig, **kwargs: object) -> None:
    defaults: dict[str, object] = {
        "microphone_orders": (("front", "right", "rear", "top"),),
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "backend_id": "room_acoustics",
        "runtime_profile": "waveform_fidelity",
        "source_ids": ("talker", "silent_later"),
        "source_orientations": {
            "talker": (0.0, 0.0, 0.0, 1.0),
            "silent_later": (0.0, 0.0, 0.0, 1.0),
        },
        "microphone_orientations": {
            mic_id: (0.0, 0.0, 0.0, 1.0) for mic_id in ("front", "right", "rear", "top")
        },
    }
    defaults.update(kwargs)
    validate_effects_config(EffectsConfig(directivity=config), **defaults)


def test_frozen_config_defaults_fields_immutability_and_resolution() -> None:
    assert tuple(field.name for field in fields(DirectivityFrequencyPointConfig)) == (
        "freq_hz",
        "gain_db",
    )
    assert tuple(field.name for field in fields(DirectivityPatternConfig)) == (
        "family",
        "frequency_points",
    )
    assert tuple(field.name for field in fields(DirectivityPatternSetConfig)) == (
        "default",
        "overrides",
    )
    assert tuple(field.name for field in fields(DirectivityConfig)) == (
        "enabled",
        "source_patterns",
        "mic_patterns",
        "mode",
    )
    assert DirectivityConfig() == DirectivityConfig(
        enabled=False,
        source_patterns=None,
        mic_patterns=None,
        mode=None,
    )

    parsed = parse_effects_config(
        {
            "directivity": {
                "enabled": True,
                "source_patterns": {
                    "default": {"family": "omni"},
                    "overrides": {
                        "talker": {
                            "family": "cardioid",
                            "frequency_points": [
                                {"freq_hz": 100.0, "gain_db": -3.0},
                                {"freq_hz": 20_000.0, "gain_db": 0.0},
                            ],
                        }
                    },
                },
            }
        }
    ).directivity
    assert parsed.mode is None
    assert isinstance(parsed.source_patterns.overrides, MappingProxyType)
    assert isinstance(
        parsed.source_patterns.overrides["talker"].frequency_points,
        tuple,
    )
    assert resolve_pattern(parsed.source_patterns, "talker").family == "cardioid"
    assert resolve_pattern(parsed.source_patterns, "other").family == "omni"
    assert resolve_pattern(None, "other") == _pattern("omni")
    with pytest.raises(TypeError):
        parsed.source_patterns.overrides["other"] = _pattern("omni")


@pytest.mark.parametrize("family", tuple(CARDINAL_TARGETS))
def test_polar_cardinals_signed_lobes_and_scaled_quaternions(family: str) -> None:
    observed = tuple(
        evaluate_polar_pattern(
            family,
            orientation_xyzw=quaternion,
            direction=(1.0, 0.0, 0.0),
        )
        for quaternion in CARDINAL_QUATERNIONS
    )
    scaled = tuple(
        evaluate_polar_pattern(
            family,
            orientation_xyzw=tuple(3.0 * value for value in quaternion),
            direction=(1.0, 0.0, 0.0),
        )
        for quaternion in CARDINAL_QUATERNIONS
    )
    assert observed == pytest.approx(CARDINAL_TARGETS[family], abs=1e-12)
    assert scaled == pytest.approx(CARDINAL_TARGETS[family], abs=1e-12)


def test_source_and_microphone_frozen_angle_conventions_and_zero_direction() -> None:
    for family, targets in CARDINAL_TARGETS.items():
        source_values = tuple(
            source_polar_gain(
                family,
                source_position_world=(0.0, 0.0, 0.0),
                source_orientation_world_xyzw=quaternion,
                microphone_position_world=(1.0, 0.0, 0.0),
            )
            for quaternion in CARDINAL_QUATERNIONS
        )
        microphone_values = tuple(
            microphone_polar_gain(
                family,
                microphone_position_world=(0.0, 0.0, 0.0),
                microphone_orientation_world_xyzw=quaternion,
                source_position_world=(1.0, 0.0, 0.0),
            )
            for quaternion in CARDINAL_QUATERNIONS
        )
        assert source_values == pytest.approx(targets, abs=1e-12)
        assert microphone_values == pytest.approx(targets, abs=1e-12)
    assert (
        source_polar_gain(
            "figure_eight",
            source_position_world=(1.0, 2.0, 3.0),
            source_orientation_world_xyzw=(0.0, 0.0, 1.0, 0.0),
            microphone_position_world=(1.0, 2.0, 3.0),
        )
        == 1.0
    )


def test_microphone_quaternion_hamilton_composition() -> None:
    world = microphone_world_orientation(
        quaternion_from_yaw_deg(90.0),
        quaternion_from_yaw_deg(90.0),
    )
    assert microphone_polar_gain(
        "figure_eight",
        microphone_position_world=(0.0, 0.0, 0.0),
        microphone_orientation_world_xyzw=world,
        source_position_world=(1.0, 0.0, 0.0),
    ) == pytest.approx(-1.0, abs=1e-12)


@pytest.mark.parametrize("family", tuple(CARDINAL_TARGETS))
def test_cardinal_waveform_gain_sign_and_null_leakage(family: str) -> None:
    rng = np.random.default_rng(20260718)
    baseline = rng.normal(size=16_384)
    denominator = float(np.dot(baseline, baseline))
    for quaternion, target in zip(
        CARDINAL_QUATERNIONS,
        CARDINAL_TARGETS[family],
        strict=True,
    ):
        output = apply_pair_directivity(
            baseline,
            source_pattern=_pattern(family),
            microphone_pattern=_pattern("omni"),
            source_position_world=(0.0, 0.0, 0.0),
            source_orientation_world_xyzw=quaternion,
            microphone_position_world=(1.0, 0.0, 0.0),
            microphone_orientation_world_xyzw=(0.0, 0.0, 0.0, 1.0),
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        gain = float(np.dot(baseline, output) / denominator)
        if target == 0.0:
            assert abs(gain) <= 1e-6
            assert (
                np.sqrt(np.mean(output * output))
                / np.sqrt(np.mean(baseline * baseline))
                <= 1e-6
            )
        else:
            assert math.copysign(1.0, gain) == math.copysign(1.0, target)
            error_db = abs(20.0 * math.log10(abs(gain / target)))
            assert error_db <= 0.05


def _target_amplitude(frequencies: np.ndarray) -> np.ndarray:
    point_frequencies = np.asarray([point.freq_hz for point in FREQUENCY_POINTS])
    point_amplitudes = 10.0 ** (
        np.asarray([point.gain_db for point in FREQUENCY_POINTS]) / 20.0
    )
    return np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )


def test_frequency_response_single_and_cascaded_recovery() -> None:
    sample_count = 2**18
    impulse = np.zeros(sample_count, dtype=np.float64)
    impulse[sample_count // 2] = 1.0
    omni = _pattern("omni")
    shaped = _pattern("omni", frequency_points=FREQUENCY_POINTS)
    single = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=omni,
        source_position_world=(0.0, 0.0, 0.0),
        source_orientation_world_xyzw=None,
        microphone_position_world=(1.0, 0.0, 0.0),
        microphone_orientation_world_xyzw=(0.0, 0.0, 0.0, 1.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    cascaded = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=shaped,
        source_position_world=(0.0, 0.0, 0.0),
        source_orientation_world_xyzw=None,
        microphone_position_world=(1.0, 0.0, 0.0),
        microphone_orientation_world_xyzw=(0.0, 0.0, 0.0, 1.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    target = _target_amplitude(frequencies)
    single_magnitude = np.abs(np.fft.rfft(np.roll(single, sample_count // 2)))
    cascaded_magnitude = np.abs(np.fft.rfft(np.roll(cascaded, sample_count // 2)))
    single_error = np.max(
        np.abs(20.0 * np.log10(single_magnitude[accepted] / target[accepted]))
    )
    cascaded_error = np.max(
        np.abs(20.0 * np.log10(cascaded_magnitude[accepted] / target[accepted] ** 2))
    )
    assert single_error <= 0.25
    assert cascaded_error <= 0.50


@pytest.mark.parametrize(
    ("source_family", "mic_family", "source_quat", "mic_quat", "target"),
    [
        (
            "figure_eight",
            "omni",
            CARDINAL_QUATERNIONS[2],
            CARDINAL_QUATERNIONS[0],
            -1.0,
        ),
        (
            "figure_eight",
            "figure_eight",
            CARDINAL_QUATERNIONS[2],
            CARDINAL_QUATERNIONS[0],
            1.0,
        ),
        ("cardioid", "omni", CARDINAL_QUATERNIONS[2], CARDINAL_QUATERNIONS[0], 0.0),
        (
            "supercardioid",
            "cardioid",
            CARDINAL_QUATERNIONS[2],
            CARDINAL_QUATERNIONS[2],
            -0.26,
        ),
    ],
)
def test_source_microphone_signed_product(
    source_family: str,
    mic_family: str,
    source_quat: tuple[float, float, float, float],
    mic_quat: tuple[float, float, float, float],
    target: float,
) -> None:
    baseline = np.linspace(-1.0, 1.0, 4096)
    output = apply_pair_directivity(
        baseline,
        source_pattern=_pattern(source_family),
        microphone_pattern=_pattern(mic_family),
        source_position_world=(0.0, 0.0, 0.0),
        source_orientation_world_xyzw=source_quat,
        microphone_position_world=(1.0, 0.0, 0.0),
        microphone_orientation_world_xyzw=mic_quat,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    assert output == pytest.approx(baseline * target, abs=1e-12)


def test_full_pair_stem_weighted_once_before_sum_and_tail_changes() -> None:
    array = _array()
    sources = (
        _source(source_id="talker", orientation=(0.0, 0.0, 1.0, 0.0)),
        _source(source_id="second", orientation=(0.0, 0.0, 0.0, 1.0)),
    )
    rng = np.random.default_rng(20260718)
    premix = rng.normal(size=(2, 4, 4096))
    premix[:, :, :32] = 0.0
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(default=_pattern("figure_eight")),
    )
    output, diagnostics = _apply_directivity_to_premix(
        premix,
        active=sources,
        sensor=array,
        microphone_positions_world={
            "front": (1.0, 0.0, 0.0),
            "right": (1.0, 0.08, 0.0),
            "rear": (1.0, -0.08, 0.0),
            "top": (1.0, 0.0, 0.08),
        },
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=config,
    )
    for source_index, source in enumerate(sources):
        for mic_index, mic_id in enumerate(("front", "right", "rear", "top")):
            gain = source_polar_gain(
                "figure_eight",
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world={
                    "front": (1.0, 0.0, 0.0),
                    "right": (1.0, 0.08, 0.0),
                    "rear": (1.0, -0.08, 0.0),
                    "top": (1.0, 0.0, 0.08),
                }[mic_id],
            )
            assert np.array_equal(
                output[source_index, mic_index], premix[source_index, mic_index] * gain
            )
    assert diagnostics["mode"] == "per_pair_direct_path"
    assert np.array_equal(output.sum(axis=0), np.sum(output, axis=0))
    assert np.any(output[:, :, -256:] != premix[:, :, -256:])


@pytest.mark.parametrize(
    "family", ("omni", "cardioid", "figure_eight", "supercardioid")
)
def test_l0_l1_helper_agrees_with_l2_signed_polar_gain(family: str) -> None:
    for quaternion in CARDINAL_QUATERNIONS:
        source = _source(
            orientation=quaternion,
            directivity=family,
        )
        metadata = directivity_factor(source, (1.0, 0.0, 0.0))
        waveform = source_polar_gain(
            family,
            source_position_world=source.position_world,
            source_orientation_world_xyzw=source.orientation_world_quat,
            microphone_position_world=(1.0, 0.0, 0.0),
        )
        if waveform == 0.0:
            assert abs(metadata - waveform) <= 1e-6
        else:
            assert math.copysign(1.0, metadata) == math.copysign(1.0, waveform)
            assert abs(20.0 * math.log10(abs(metadata / waveform))) <= 0.05


@pytest.mark.parametrize(
    ("config", "overrides", "error", "match"),
    [
        (
            _active_config(source=_pattern("Cardioid")),
            {},
            ConfigValidationError,
            "family",
        ),
        (
            _active_config(source=DirectivityPatternConfig()),
            {},
            ConfigValidationError,
            "family",
        ),
        (
            DirectivityConfig(
                enabled=True,
                mode="native",
                source_patterns=DirectivityPatternSetConfig(default=_pattern("omni")),
            ),
            {},
            UnsupportedEffectError,
            "mode",
        ),
        (
            _active_config(source=_pattern("cardioid")),
            {
                "source_orientations": {
                    "talker": None,
                    "silent_later": (0.0, 0.0, 0.0, 1.0),
                }
            },
            ConfigValidationError,
            "orientation",
        ),
        (
            DirectivityConfig(
                enabled=True,
                source_patterns=DirectivityPatternSetConfig(
                    overrides={"unknown": _pattern("omni")}
                ),
            ),
            {},
            ConfigValidationError,
            "unknown",
        ),
        (
            DirectivityConfig(
                enabled=True,
                mic_patterns=DirectivityPatternSetConfig(
                    overrides={"rear": _pattern("omni"), "front": _pattern("omni")}
                ),
            ),
            {},
            ConfigValidationError,
            "order",
        ),
        (
            _active_config(
                source=_pattern(
                    "omni",
                    frequency_points=(
                        DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=0.0),
                    ),
                )
            ),
            {},
            ConfigValidationError,
            "at least two",
        ),
        (
            _active_config(
                source=_pattern(
                    "omni",
                    frequency_points=(
                        DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=0.0),
                        DirectivityFrequencyPointConfig(
                            freq_hz=24_000.000001, gain_db=0.0
                        ),
                    ),
                )
            ),
            {},
            ConfigValidationError,
            "Nyquist",
        ),
    ],
)
def test_fail_closed_invalid_matrix(
    config: DirectivityConfig,
    overrides: dict[str, object],
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        _validate(config, **overrides)


@pytest.mark.parametrize(
    ("backend_id", "runtime_profile"),
    [
        ("geometry_only", "training_features"),
        ("tdoa_synthetic", "waveform_fidelity"),
        ("room_acoustics", "training_features"),
        ("waveform", "waveform_fidelity"),
    ],
)
def test_directivity_rejects_unsupported_backend_profile_before_synthesis(
    backend_id: str,
    runtime_profile: str,
) -> None:
    with pytest.raises(UnsupportedEffectError, match="waveform-only"):
        _validate(
            _active_config(source=_pattern("omni")),
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )


def test_core_config_rejects_unknown_ids_and_missing_orientation() -> None:
    raw = {
        "scene": {"scene_id": "s3_6"},
        "audio": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "default_backend": "room_acoustics",
            "runtime_profile": "waveform_fidelity",
            "effects": {
                "directivity": {
                    "enabled": True,
                    "source_patterns": {
                        "overrides": {"talker": {"family": "cardioid"}}
                    },
                }
            },
        },
        "sources": [
            {
                "source_id": "talker",
                "prim_path": "/World/Talker",
                "class_label": "speaker",
            }
        ],
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig",
                "microphones": [
                    {"mic_id": "front", "relative_position_m": [0.0, 0.0, 0.0]},
                    {"mic_id": "rear", "relative_position_m": [0.0, 0.1, 0.0]},
                ],
            }
        },
        "room": {
            "room_id": "room",
            "dimensions_m": [10.0, 8.0, 3.0],
        },
    }
    with pytest.raises(ConfigValidationError, match="orientation"):
        validate_audio_config(raw)
    raw["sources"][0]["orientation_world_quat"] = [0.0, 0.0, 0.0, 1.0]
    raw["audio"]["effects"]["directivity"]["source_patterns"]["overrides"] = {
        "unknown": {"family": "cardioid"}
    }
    with pytest.raises(ConfigValidationError, match="unknown"):
        validate_audio_config(raw)


def test_diagnostics_exact_schema_order_and_explicit_omni_off_state() -> None:
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(
            default=_pattern("omni"),
            overrides={
                "talker": _pattern("cardioid", frequency_points=FREQUENCY_POINTS)
            },
        ),
        mic_patterns=DirectivityPatternSetConfig(default=_pattern("supercardioid")),
    )
    diagnostics = directivity_diagnostics(
        config,
        active_source_ids=("talker", "other"),
        microphone_ids=("front", "rear"),
    )
    assert tuple(diagnostics) == ("source_pattern", "mic_pattern", "mode")
    assert tuple(diagnostics["source_pattern"]) == ("talker", "other")
    assert tuple(diagnostics["mic_pattern"]) == ("front", "rear")
    assert diagnostics["mode"] == "per_pair_direct_path"
    assert diagnostics["source_pattern"]["talker"]["frequency_points"][0] == {
        "freq_hz": 100.0,
        "gain_db": -6.0,
    }

    explicit_omni = _active_config(source=_pattern("omni"))
    assert (
        directivity_diagnostics(
            explicit_omni,
            active_source_ids=("talker",),
            microphone_ids=("front",),
        )
        == {}
    )
    baseline = np.arange(64, dtype=np.float64).reshape(1, 1, 64)
    output, stage = _apply_directivity_to_premix(
        baseline,
        active=(_source(),),
        sensor=MicrophoneArraySpec(
            array_id="mono",
            prim_path="/World/Mono",
            position_world=(1.0, 0.0, 0.0),
            orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
            forward_vec_world=(1.0, 0.0, 0.0),
            right_vec_world=(0.0, 1.0, 0.0),
            up_vec_world=(0.0, 0.0, 1.0),
            microphones=(
                MicrophoneSpec(mic_id="front", relative_position_m=(0.0, 0.0, 0.0)),
            ),
        ),
        microphone_positions_world={"front": (1.0, 0.0, 0.0)},
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=explicit_omni,
    )
    assert output is baseline
    assert stage == {}


def test_enabled_directivity_replay_is_byte_deterministic() -> None:
    rng = np.random.default_rng(20260718)
    baseline = rng.normal(size=8192)
    kwargs = {
        "source_pattern": _pattern("figure_eight", frequency_points=FREQUENCY_POINTS),
        "microphone_pattern": _pattern(
            "supercardioid", frequency_points=FREQUENCY_POINTS
        ),
        "source_position_world": (0.0, 0.0, 0.0),
        "source_orientation_world_xyzw": (0.0, 0.0, 1.0, 0.0),
        "microphone_position_world": (1.0, 0.0, 0.0),
        "microphone_orientation_world_xyzw": (0.0, 0.0, 1.0, 0.0),
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    first = apply_pair_directivity(baseline, **kwargs)
    second = apply_pair_directivity(baseline, **kwargs)
    assert first.tobytes() == second.tobytes()


def test_real_room_and_estimator_rows_are_dependency_gated() -> None:
    pytest.importorskip("pyroomacoustics")
    # Real pyroomacoustics cardinal/reverberant/SRP/GCC fixtures are generated
    # by scripts/s3_6_evidence.py in the dependency-capable environment.
