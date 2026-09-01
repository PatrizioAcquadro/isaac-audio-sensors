from __future__ import annotations

import math
from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    AmbientNoiseConfig,
    ChannelEffectsChain,
    EffectsConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.effects.noise import (
    apply_clock_drift,
    decompose_drift_delay,
    design_noise_fir,
    drift_delay_samples,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.effects.streams import (
    SEED_DERIVATION_ID,
    named_generator,
    named_stream_descriptor,
)
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from tests.helpers import (
    MOTION_SEGMENTS,
    SAMPLE_RATE_HZ,
    CaptureSink,
    install_fake_pyroom,
    motion_plan,
    motion_room_fixture,
    quad_array,
    room_scene,
    source,
    time_window,
)

MIC_IDS = ("front", "right", "rear", "left")
SEED = 20_260_718
ALT_SEED = 20_260_719
FRAME_ID = "noise_frame_000000"
PSD_POINTS = (
    (100.0, -18.0),
    (500.0, -6.0),
    (2_000.0, 0.0),
    (8_000.0, -3.0),
    (20_000.0, -12.0),
)
AMBIENT_POINTS = (
    (100.0, -9.0),
    (1_000.0, 0.0),
    (8_000.0, -6.0),
    (20_000.0, -18.0),
)


def _points(values=PSD_POINTS):
    return tuple(
        NoiseSpectrumPointConfig(freq_hz=frequency, level_db=level)
        for frequency, level in values
    )


def _noise_effects(**kwargs) -> EffectsConfig:
    return EffectsConfig(noise=NoiseConfig(enabled=True, **kwargs))


def _apply(config: EffectsConfig, samples: np.ndarray, *, frame_id=FRAME_ID):
    return ChannelEffectsChain(config).apply(
        samples,
        mic_ids=MIC_IDS[: samples.shape[0]],
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=frame_id,
        backend_id="analytic_acoustics",
    )


def _rms_db(samples: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.sqrt(np.mean(samples * samples))))


def _periodic_hann_welch(samples: np.ndarray):
    nperseg = 8_192
    hop = 4_096
    window = np.hanning(nperseg + 1)[:-1]
    segments = np.lib.stride_tricks.sliding_window_view(samples, nperseg)[::hop]
    assert segments.shape[0] == 255
    segments = segments - np.mean(segments, axis=1, keepdims=True)
    spectrum = np.fft.rfft(segments * window, axis=1)
    psd = np.mean(np.abs(spectrum) ** 2, axis=0) / (
        SAMPLE_RATE_HZ * np.sum(window * window)
    )
    psd[1:-1] *= 2.0
    return np.fft.rfftfreq(nperseg, 1.0 / SAMPLE_RATE_HZ), psd


def _band_limited_probe() -> np.ndarray:
    sample_count = 16_384
    rng = np.random.default_rng(SEED)
    spectrum = np.fft.rfft(rng.standard_normal(sample_count))
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    spectrum[(frequencies < 300.0) | (frequencies > 18_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=sample_count) * np.hanning(sample_count)
    return np.asarray(probe / np.max(np.abs(probe)), dtype=np.float64)


def _fft_correlation_lag(output: np.ndarray, source: np.ndarray) -> float:
    full_size = output.size + source.size - 1
    transform_size = 1 << (full_size - 1).bit_length()
    circular = np.fft.irfft(
        np.fft.rfft(output, transform_size)
        * np.conj(np.fft.rfft(source, transform_size)),
        transform_size,
    )
    correlation = np.concatenate(
        (circular[-(source.size - 1) :], circular[: output.size])
    )
    magnitude = np.abs(correlation)
    peak = int(np.argmax(magnitude))
    left, center, right = magnitude[peak - 1 : peak + 2]
    offset = 0.5 * (left - right) / (left - 2.0 * center + right)
    return float(peak - (source.size - 1) + offset)


def _base_raw() -> dict[str, object]:
    return {
        "scene": {"scene_id": "noise_config"},
        "audio": {
            "default_backend": "analytic_acoustics",
            "runtime_profile": "waveform_fidelity",
        },
        "environment": {
            "environment_id": "noise_environment",
            "kind": "shoebox",
            "dimensions_m": [6.0, 6.0, 3.0],
        },
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig",
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "microphones": [
                    {"mic_id": mic_id, "self_noise_db": -54.0} for mic_id in MIC_IDS
                ],
            }
        },
    }


def test_frozen_noise_records_toml_immutability_precedence_and_scalar_map_forms():
    raw = _base_raw()
    raw["audio"]["effects"] = {  # type: ignore[index]
        "noise": {
            "enabled": True,
            "seed": SEED,
            "clock_jitter_std_s": {"front": 10e-6, "right": 20e-6},
            "clock_drift_ppm": {"front": 125.0, "right": -80.0},
            "self_noise": {
                "default": {
                    "level_db": -48.0,
                    "spectrum": [
                        {"freq_hz": 100.0, "level_db": -18.0},
                        {"freq_hz": 20_000.0, "level_db": -12.0},
                    ],
                },
                "microphones": {"front": {"level_db": -42.0}},
            },
            "ambient": {
                "level_db": -36.0,
                "coherent_fraction": 0.25,
            },
        }
    }
    parsed = validate_audio_config(raw).effects.noise
    assert isinstance(parsed.self_noise.microphones, MappingProxyType)
    assert isinstance(parsed.clock_jitter_std_s, MappingProxyType)
    assert isinstance(parsed.clock_drift_ppm, MappingProxyType)
    assert isinstance(parsed.self_noise.default.spectrum, tuple)
    with pytest.raises(TypeError):
        parsed.clock_drift_ppm["rear"] = 1.0  # type: ignore[index]

    scalar = parse_effects_config(
        {"noise": {"enabled": True, "seed": SEED, "clock_jitter_std_s": 1e-6}}
    )
    assert scalar.noise.clock_jitter_std_s == 1e-6
    caller_owned = {"front": NoiseLevelSpecConfig(level_db=-30.0)}
    frozen = SelfNoiseConfig(microphones=caller_owned)
    caller_owned["right"] = NoiseLevelSpecConfig(level_db=-10.0)
    assert tuple(frozen.microphones) == ("front",)

    precedence = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-60.0),
            microphones={"front": NoiseLevelSpecConfig(level_db=-30.0)},
        ),
    )
    output, _ = ChannelEffectsChain(precedence).apply(
        np.zeros((2, 2**18)),
        mic_ids=("front", "right"),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=FRAME_ID,
        backend_id="analytic_acoustics",
        microphone_self_noise_db={"front": -10.0, "right": -10.0},
    )
    assert abs(_rms_db(output[0]) + 30.0) <= 0.15
    assert abs(_rms_db(output[1]) + 60.0) <= 0.15


def test_toml_self_noise_metadata_fallback_requires_seed_at_config_validation():
    raw = _base_raw()
    raw["audio"]["effects"] = {  # type: ignore[index]
        "noise": {"enabled": True, "self_noise": {}}
    }
    with pytest.raises(ConfigValidationError, match="seed"):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("config", "match"),
    [
        (NoiseConfig(enabled=1, clock_drift_ppm={"front": 0.0}), "enabled"),
        (NoiseConfig(enabled=True, seed=True, clock_jitter_std_s=1e-6), "seed"),
        (
            NoiseConfig(enabled=True, seed=2**63, clock_jitter_std_s=1e-6),
            "seed",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=None),
            ),
            "level_db",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=61.0),
            ),
            "level_db",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=1.01),
            ),
            "coherent_fraction",
        ),
        (
            NoiseConfig(enabled=True, seed=SEED, clock_jitter_std_s=-1.0),
            "clock_jitter",
        ),
        (
            NoiseConfig(enabled=True, seed=SEED, clock_jitter_std_s=0.251),
            "clock_jitter",
        ),
        (
            NoiseConfig(enabled=True, clock_drift_ppm={"front": 1000.1}),
            "clock_drift",
        ),
        (
            NoiseConfig(enabled=True, clock_drift_ppm={"right": 0, "front": 0}),
            "order mismatch",
        ),
        (
            NoiseConfig(enabled=True, clock_drift_ppm={"unknown": 0}),
            "unknown exact",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(
                        level_db=-48.0,
                        spectrum=(NoiseSpectrumPointConfig(freq_hz=1000, level_db=0),),
                    )
                ),
            ),
            "at least two",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(
                        level_db=-48.0,
                        spectrum=(
                            NoiseSpectrumPointConfig(freq_hz=1000, level_db=0),
                            NoiseSpectrumPointConfig(freq_hz=500, level_db=0),
                        ),
                    )
                ),
            ),
            "strictly increasing",
        ),
        (
            NoiseConfig(
                enabled=True,
                seed=SEED,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(
                        level_db=-48.0,
                        spectrum=(
                            NoiseSpectrumPointConfig(freq_hz=100, level_db=0),
                            NoiseSpectrumPointConfig(freq_hz=24001, level_db=0),
                        ),
                    )
                ),
            ),
            "freq_hz",
        ),
    ],
)
def test_noise_fail_closed_ranges_types_ids_and_spectra(config, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_effects_config(
            EffectsConfig(noise=config),
            microphone_orders=(MIC_IDS,),
            sample_rate_hz=SAMPLE_RATE_HZ,
            backend_id="analytic_acoustics",
            runtime_profile="waveform_fidelity",
            sample_count=48_000,
        )


def test_self_noise_psd_meets_exact_frozen_welch_protocol():
    sample_count = 2**20
    points = _points()
    output, _ = _apply(
        _noise_effects(
            seed=SEED,
            self_noise=SelfNoiseConfig(
                default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=points)
            ),
        ),
        np.zeros((1, sample_count), dtype=np.float64),
    )
    frequencies, measured = _periodic_hann_welch(output[0])
    taps = design_noise_fir(points, sample_rate_hz=SAMPLE_RATE_HZ)
    assert float(np.sum(taps * taps)) == pytest.approx(1.0, abs=1e-12)
    transfer = np.fft.rfft(taps, n=8_192)
    amplitude = 10.0 ** (-48.0 / 20.0)
    expected = 2.0 * amplitude**2 * np.abs(transfer) ** 2 / SAMPLE_RATE_HZ
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    error_db = 10.0 * np.log10(measured[accepted] / expected[accepted])
    assert float(np.max(np.abs(error_db))) <= 2.0


@pytest.mark.parametrize("kind", ["self", "ambient"])
@pytest.mark.parametrize("spectrum", [None, _points()])
@pytest.mark.parametrize("level_db", [-60.0, -42.0, -18.0])
def test_full_band_rms_levels_meet_frozen_bound(kind, spectrum, level_db):
    if kind == "self":
        kwargs = {
            "self_noise": SelfNoiseConfig(
                default=NoiseLevelSpecConfig(
                    level_db=level_db,
                    spectrum=spectrum,
                )
            )
        }
    else:
        kwargs = {
            "ambient": AmbientNoiseConfig(
                level_db=level_db,
                spectrum=spectrum,
                coherent_fraction=0.0,
            )
        }
    output, _ = _apply(
        _noise_effects(seed=SEED, **kwargs),
        np.zeros((4, 2**20), dtype=np.float64),
    )
    for channel in output:
        assert abs(_rms_db(channel) - level_db) <= 0.15


def test_exact_zero_is_distinct_from_disabled_and_makes_no_stream_draw():
    samples = np.zeros((4, 257), dtype=np.float64)
    disabled, disabled_diagnostics = ChannelEffectsChain(EffectsConfig()).apply(
        samples,
        mic_ids=MIC_IDS,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=FRAME_ID,
    )
    zero, diagnostics = _apply(
        _noise_effects(
            self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-math.inf))
        ),
        samples,
    )
    assert disabled is samples
    assert disabled_diagnostics == {}
    assert np.array_equal(zero, samples)
    assert diagnostics["noise"]["streams"] == {}
    assert diagnostics["noise"]["per_mic_rms"] == dict.fromkeys(MIC_IDS, 0.0)


@pytest.mark.parametrize("coherent_fraction", [0.0, 0.25, 1.0])
def test_ambient_coherent_power_fraction_matches_pairwise_correlation(
    coherent_fraction,
):
    output, _ = _apply(
        _noise_effects(
            seed=SEED,
            ambient=AmbientNoiseConfig(
                level_db=-36.0,
                spectrum=_points(AMBIENT_POINTS),
                coherent_fraction=coherent_fraction,
            ),
        ),
        np.zeros((4, 2**18), dtype=np.float64),
    )
    if coherent_fraction == 1.0:
        assert all(
            output[index].tobytes() == output[0].tobytes() for index in range(1, 4)
        )
        return
    correlation = np.corrcoef(output)
    pair_values = correlation[np.triu_indices(4, 1)]
    assert float(np.max(np.abs(pair_values - coherent_fraction))) <= 0.02


def test_jitter_named_draw_mean_and_std_over_deterministic_sample():
    sample_count = 10_000
    sigmas = (10e-6, 20e-6, 30e-6, 40e-6)
    for mic_id, sigma in zip(MIC_IDS, sigmas, strict=True):
        draws = np.fromiter(
            (
                named_generator(
                    SEED,
                    domain="noise",
                    frame_id=f"noise_jitter_{index:06d}",
                    mic_id=mic_id,
                    effect="clock_jitter",
                ).normal(0.0, sigma)
                for index in range(sample_count)
            ),
            dtype=np.float64,
            count=sample_count,
        )
        assert abs(float(np.mean(draws))) <= 0.025 * sigma
        assert abs(float(np.std(draws, ddof=1)) / sigma - 1.0) <= 0.01


def test_first_256_jitter_waveform_draws_recover_within_point_one_sample():
    probe = _band_limited_probe()
    config = _noise_effects(seed=SEED, clock_jitter_std_s=20e-6)
    errors = []
    for index in range(256):
        frame_id = f"noise_jitter_waveform_{index:03d}"
        output, _ = _apply(config, np.asarray([probe]), frame_id=frame_id)
        expected = float(
            named_generator(
                SEED,
                domain="noise",
                frame_id=frame_id,
                mic_id="front",
                effect="clock_jitter",
            ).normal(0.0, 20e-6)
            * SAMPLE_RATE_HZ
        )
        errors.append(abs(_fft_correlation_lag(output[0], probe) - expected))
    assert max(errors) <= 0.10


def test_drift_slope_and_long_session_phase_arithmetic_meet_frozen_bounds():
    sample_count = 2**20
    probe = np.random.default_rng(SEED).standard_normal(sample_count)
    starts = np.arange(0, sample_count - 32_768 + 1, 16_384)
    centers = starts + (32_768 - 1) / 2.0
    for ppm in (125.0, -80.0, 0.0, 37.5):
        output = apply_clock_drift(probe, q0=0, ppm=ppm)
        lags = np.asarray(
            [
                _fft_correlation_lag(
                    output[start : start + 32_768],
                    probe[start : start + 32_768],
                )
                for start in starts
            ]
        )
        slope = float(np.polyfit(centers, lags, 1)[0])
        recovered_ppm = slope / (1.0 - slope) * 1e6
        assert abs(recovered_ppm - ppm) <= 0.50

        magnitudes = []
        for q in (
            0,
            3_600 * SAMPLE_RATE_HZ,
            86_400 * SAMPLE_RATE_HZ,
            30 * 86_400 * SAMPLE_RATE_HZ,
        ):
            slip, phase = decompose_drift_delay(q, ppm)
            delay = float(drift_delay_samples(q, ppm))
            assert 0.0 <= phase < 1.0
            assert abs((slip + phase) - delay) <= 1e-6
            magnitudes.append(abs(delay))
        assert magnitudes == sorted(magnitudes)


def test_seed_replay_separation_diagnostics_and_configuration_isolation():
    config = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points())
        ),
        ambient=AmbientNoiseConfig(
            level_db=-36.0,
            spectrum=_points(AMBIENT_POINTS),
            coherent_fraction=0.25,
        ),
        clock_jitter_std_s=20e-6,
        clock_drift_ppm=dict(zip(MIC_IDS, (125.0, -80.0, 0.0, 37.5), strict=True)),
    )
    samples = np.zeros((4, 2**18), dtype=np.float64)
    first, first_diagnostics = _apply(config, samples)
    second, second_diagnostics = _apply(config, samples)
    assert first.tobytes() == second.tobytes()
    assert first_diagnostics == second_diagnostics
    assert set(first_diagnostics["noise"]) == {
        "streams",
        "per_mic_rms",
        "seed_derivation_id",
    }
    assert first_diagnostics["noise"]["seed_derivation_id"] == SEED_DERIVATION_ID
    assert tuple(first_diagnostics["noise"]["per_mic_rms"]) == MIC_IDS

    alternate = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=ALT_SEED,
            self_noise=config.noise.self_noise,
            ambient=config.noise.ambient,
            clock_jitter_std_s=config.noise.clock_jitter_std_s,
            clock_drift_ppm=config.noise.clock_drift_ppm,
        )
    )
    third, third_diagnostics = _apply(alternate, samples)
    assert first.tobytes() != third.tobytes()
    first_seeds = {
        label: record.get("derived_seed")
        for label, record in first_diagnostics["noise"]["streams"].items()
        if record["stochastic"]
    }
    third_seeds = {
        label: record.get("derived_seed")
        for label, record in third_diagnostics["noise"]["streams"].items()
        if record["stochastic"]
    }
    assert all(first_seeds[label] != third_seeds[label] for label in first_seeds)

    changed_front = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points()),
            microphones={"front": NoiseLevelSpecConfig(level_db=-18.0)},
        ),
    )
    baseline = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points())
        ),
    )
    base_output, _ = _apply(baseline, samples)
    changed_output, _ = _apply(changed_front, samples)
    assert all(
        base_output[index].tobytes() == changed_output[index].tobytes()
        for index in range(1, 4)
    )


def test_all_named_latent_streams_are_unique_and_below_correlation_limit():
    rows = []
    descriptors = []
    for effect in ("self_noise", "ambient"):
        for mic_id in MIC_IDS:
            descriptors.append(
                named_stream_descriptor(
                    SEED,
                    domain="noise",
                    frame_id="noise_independence",
                    mic_id=mic_id,
                    effect=effect,
                )
            )
            rows.append(
                named_generator(
                    SEED,
                    domain="noise",
                    frame_id="noise_independence",
                    mic_id=mic_id,
                    effect=effect,
                ).standard_normal(2**18)
            )
    descriptors.append(
        named_stream_descriptor(
            SEED,
            domain="noise",
            frame_id="noise_independence",
            mic_id="__common__",
            effect="ambient_common",
        )
    )
    rows.append(
        named_generator(
            SEED,
            domain="noise",
            frame_id="noise_independence",
            mic_id="__common__",
            effect="ambient_common",
        ).standard_normal(2**18)
    )
    for mic_id in MIC_IDS:
        descriptors.append(
            named_stream_descriptor(
                SEED,
                domain="noise",
                frame_id="noise_independence",
                mic_id=mic_id,
                effect="clock_jitter",
            )
        )
        rows.append(
            named_generator(
                SEED,
                domain="noise",
                frame_id="noise_independence",
                mic_id=mic_id,
                effect="clock_jitter",
            ).standard_normal(2**18)
        )
    assert len({item[0] for item in descriptors}) == len(descriptors)
    assert len({item[2] for item in descriptors}) == len(descriptors)
    matrix = np.corrcoef(np.asarray(rows))
    off_diagonal = np.abs(matrix - np.eye(matrix.shape[0]))
    assert float(np.max(off_diagonal)) <= 0.010


def _controlled_premix(_room, *, source_count: int, mic_count: int):
    time = np.arange(48_000, dtype=np.float64) / SAMPLE_RATE_HZ
    base = np.asarray(
        [
            0.05 * np.sin(2.0 * np.pi * (700.0 + 100.0 * index) * time)
            for index in range(mic_count)
        ]
    )
    return np.repeat((base / source_count)[None, :, :], source_count, axis=0)


def test_room_noise_is_dispatched_once_on_equal_summed_mixtures(monkeypatch):
    fake = install_fake_pyroom(monkeypatch)
    base_shoebox = fake.ShoeBox

    class ControlledShoebox(base_shoebox):
        def simulate(self, return_premix=False):
            premix = _controlled_premix(
                self,
                source_count=len(self.sources),
                mic_count=self.mic_array.R.shape[1],
            )
            self.mic_array.signals = premix.sum(axis=0)
            return premix if return_premix else None

    fake.ShoeBox = ControlledShoebox
    array = quad_array()
    noise = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-48.0)),
        ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=0.25),
        clock_jitter_std_s=20e-6,
    )
    deltas = []
    for source_count in (1, 4):
        sources = tuple(
            source(f"speaker_{index}", (3.0, 0.1 * index, 0.0))
            for index in range(source_count)
        )
        scene = room_scene(*sources, array=array)
        baseline_sink = CaptureSink()
        effected_sink = CaptureSink()
        AnalyticAcoustics(waveform_writer=baseline_sink).simulate(
            scene, array.array_id, time_window()
        )
        effected = AnalyticAcoustics(
            waveform_writer=effected_sink,
            effects=noise,
        ).simulate(scene, array.array_id, time_window())
        baseline_mix = baseline_sink.calls[0]["mixture"]
        effected_mix = effected_sink.calls[0]["mixture"]
        deltas.append(effected_mix - baseline_mix)
        for mic_index, mic_id in enumerate(MIC_IDS):
            rms = float(np.sqrt(np.mean(effected_mix[mic_index] ** 2)))
            assert abs(effected.aggregate_per_mic_rms[mic_id] - rms) <= 1e-12
        assert set(effected.diagnostics["effects"]["noise"]) == {
            "streams",
            "per_mic_rms",
            "seed_derivation_id",
        }
    assert deltas[0].tobytes() == deltas[1].tobytes()


def test_self_noise_metadata_fallback_requires_seed_before_room_synthesis(
    monkeypatch,
):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    array = replace(
        array,
        microphones=tuple(
            replace(microphone, self_noise_db=-48.0) for microphone in array.microphones
        ),
    )
    scene = room_scene(
        source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )

    effects = _noise_effects(self_noise=SelfNoiseConfig())
    with pytest.raises(ConfigValidationError, match="seed"):
        AnalyticAcoustics(effects=effects).simulate(
            scene, array.array_id, time_window()
        )


def test_segmented_room_paths_compose_with_one_mixture_noise_dispatch(monkeypatch):
    install_fake_pyroom(monkeypatch)
    scene, array, window = motion_room_fixture()
    _history, plan = motion_plan(
        lambda time_s: (1.0 + 20.0 * time_s, 2.0, 1.0),
        (20.0, 0.0, 0.0),
    )
    effects = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=SEED,
            self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-48.0)),
            ambient=AmbientNoiseConfig(
                level_db=-36.0,
                coherent_fraction=0.25,
            ),
            clock_jitter_std_s=20e-6,
        ),
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=MOTION_SEGMENTS,
        ),
    )
    sinks = (CaptureSink(), CaptureSink())
    frames = tuple(
        AnalyticAcoustics(
            effects=effects,
            window_motion=plan,
            waveform_writer=sink,
        ).simulate(scene, array.array_id, window)
        for sink in sinks
    )
    assert frames[0] == frames[1]
    assert frames[0].diagnostics["motion"]["segments_per_window"] == MOTION_SEGMENTS
    assert "noise" in frames[0].diagnostics["effects"]
    assert (
        sinks[0].calls[0]["mixture"].tobytes() == sinks[1].calls[0]["mixture"].tobytes()
    )


def test_backend_off_state_and_enabled_determinism(monkeypatch):
    install_fake_pyroom(monkeypatch)
    array = quad_array()
    scene = room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array)
    baseline_sink = CaptureSink()
    baseline = AnalyticAcoustics(waveform_writer=baseline_sink).simulate(
        scene, array.array_id, time_window()
    )
    assert baseline_sink.calls[0]["mixture"].size > 0
    assert "effects" not in baseline.diagnostics

    effects = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-48.0)),
        ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=0.25),
        clock_jitter_std_s=20e-6,
    )
    sinks = (CaptureSink(), CaptureSink())
    frames = tuple(
        AnalyticAcoustics(waveform_writer=sink, effects=effects).simulate(
            scene, array.array_id, time_window()
        )
        for sink in sinks
    )
    assert frames[0] == frames[1]
    assert (
        sinks[0].calls[0]["mixture"].tobytes() == sinks[1].calls[0]["mixture"].tobytes()
    )


def test_minimum_windows_nonfinite_and_timing_history_fail_closed():
    self_noise = _noise_effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points())
        ),
    )
    empty, diagnostics = _apply(self_noise, np.zeros((1, 0), dtype=np.float64))
    assert empty.shape == (1, 0)
    assert diagnostics["noise"]["per_mic_rms"] == {"front": 0.0}
    one, _ = _apply(self_noise, np.zeros((1, 1), dtype=np.float64))
    assert one.shape == (1, 1)
    assert np.isfinite(one[0, 0])

    jitter = _noise_effects(seed=SEED, clock_jitter_std_s=20e-6)
    with pytest.raises(ConfigValidationError, match=r"ceil\(6"):
        _apply(jitter, np.zeros((1, 1), dtype=np.float64))
    with pytest.raises(ConfigValidationError, match="non-finite"):
        _apply(self_noise, np.asarray([[math.nan]], dtype=np.float64))

    drift = _noise_effects(clock_drift_ppm={"front": 125.0})
    with pytest.raises(ConfigValidationError, match="no non-empty valid"):
        ChannelEffectsChain(drift).apply(
            np.ones((1, 128), dtype=np.float64),
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id=FRAME_ID,
            backend_id="analytic_acoustics",
            nominal_window_start_sample=30 * 86_400 * SAMPLE_RATE_HZ,
        )
