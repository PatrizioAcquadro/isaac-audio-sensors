from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

import isaac_audio_sensors.core.effects.electronics as electronics_module
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    AgcConfig,
    ChannelEffectsChain,
    EffectsConfig,
    ElectronicsConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    SelfNoiseConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.electronics import (
    apply_agc,
    generate_tpdf_dither,
    quantize,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.effects.streams import named_stream_descriptor
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.microphone_array import create_microphone_array
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
FRAME_ID = "electronics_frame_000000"
FULL_SCALE = 1.0
BIT_DEPTH = 16
STEP = 1.0 / 32_768.0
TARGET_DB = -12.041199826559248


def _agc() -> AgcConfig:
    return AgcConfig(
        enabled=True,
        target_rms_dbfs=TARGET_DB,
        attack_time_s=0.010,
        release_time_s=0.050,
        gain_floor_db=TARGET_DB,
        gain_ceiling_db=-TARGET_DB,
    )


def _effects(*, dither: bool = False, agc: AgcConfig | None = None, seed=SEED):
    return EffectsConfig(
        noise=NoiseConfig(seed=seed),
        electronics=ElectronicsConfig(
            enabled=True,
            full_scale=FULL_SCALE,
            bit_depth=BIT_DEPTH,
            dither_enabled=dither,
            agc=agc,
        ),
    )


def _apply(
    samples: np.ndarray, config: EffectsConfig | None = None, *, frame_id=FRAME_ID
):
    return ChannelEffectsChain(_effects() if config is None else config).apply(
        samples,
        mic_ids=MIC_IDS[: samples.shape[0]],
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=frame_id,
        backend_id="room_acoustics",
    )


def _validate(config: EffectsConfig) -> None:
    validate_effects_config(
        config,
        microphone_orders=(MIC_IDS,),
        sample_rate_hz=SAMPLE_RATE_HZ,
        backend_id="room_acoustics",
        runtime_profile="waveform_fidelity",
        sample_count=16,
    )


def _base_raw() -> dict[str, object]:
    return {
        "scene": {"scene_id": "electronics_config"},
        "audio": {
            "default_backend": "room_acoustics",
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "effects": {
                "noise": {"seed": SEED},
                "electronics": {
                    "enabled": True,
                    "full_scale": FULL_SCALE,
                    "bit_depth": BIT_DEPTH,
                    "dither_enabled": True,
                    "agc": {
                        "enabled": True,
                        "target_rms_dbfs": TARGET_DB,
                        "attack_time_s": 0.010,
                        "release_time_s": 0.050,
                        "gain_floor_db": TARGET_DB,
                        "gain_ceiling_db": -TARGET_DB,
                    },
                },
            },
        },
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig",
                "microphones": [{"mic_id": mic_id} for mic_id in MIC_IDS],
            }
        },
    }


def test_defaults_toml_and_shared_seed_ownership():
    assert parse_effects_config({}).electronics == ElectronicsConfig()
    parsed = validate_audio_config(_base_raw()).effects
    assert parsed.electronics.agc == _agc()
    assert parsed.noise.enabled is False
    assert parsed.noise.seed == SEED


@pytest.mark.parametrize(
    ("electronics", "seed", "match"),
    [
        (ElectronicsConfig(enabled=1), None, "enabled"),
        (
            ElectronicsConfig(enabled=True, full_scale=None, bit_depth=16),
            None,
            "full_scale",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=None),
            None,
            "bit_depth",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=0.0, bit_depth=16),
            None,
            "full_scale",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=-1.0, bit_depth=16),
            None,
            "full_scale",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=math.nan, bit_depth=16),
            None,
            "full_scale",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=7),
            None,
            "bit_depth",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=33),
            None,
            "bit_depth",
        ),
        (
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=True),
            None,
            "bit_depth",
        ),
        (
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, dither_enabled=1
            ),
            SEED,
            "dither",
        ),
        (
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, dither_enabled=True
            ),
            None,
            "seed",
        ),
        (
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, dither_enabled=True
            ),
            True,
            "seed",
        ),
        (
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, agc=AgcConfig(enabled=True)
            ),
            None,
            "requires",
        ),
        (
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-121.0,
                    attack_time_s=1.0,
                    release_time_s=1.0,
                    gain_floor_db=-1.0,
                    gain_ceiling_db=1.0,
                ),
            ),
            None,
            "target",
        ),
        (
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-1.0,
                    attack_time_s=0.0,
                    release_time_s=1.0,
                    gain_floor_db=-1.0,
                    gain_ceiling_db=1.0,
                ),
            ),
            None,
            "attack",
        ),
        (
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-1.0,
                    attack_time_s=1.0,
                    release_time_s=61.0,
                    gain_floor_db=-1.0,
                    gain_ceiling_db=1.0,
                ),
            ),
            None,
            "release",
        ),
        (
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-1.0,
                    attack_time_s=1.0,
                    release_time_s=1.0,
                    gain_floor_db=1.0,
                    gain_ceiling_db=2.0,
                ),
            ),
            None,
            "bounds",
        ),
    ],
)
def test_fail_closed_validation_matrix(electronics, seed, match):
    config = EffectsConfig(noise=NoiseConfig(seed=seed), electronics=electronics)
    with pytest.raises(ConfigValidationError, match=match):
        _validate(config)


@pytest.mark.parametrize("full_scale", [math.inf, -math.inf])
def test_nonfinite_full_scale_fails_closed(full_scale):
    with pytest.raises(ConfigValidationError, match="full_scale"):
        _validate(
            EffectsConfig(
                electronics=ElectronicsConfig(
                    enabled=True, full_scale=full_scale, bit_depth=16
                )
            )
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("target_rms_dbfs", 1.0),
        ("target_rms_dbfs", math.nan),
        ("attack_time_s", -1.0),
        ("attack_time_s", math.inf),
        ("release_time_s", math.nan),
        ("gain_floor_db", -121.0),
        ("gain_ceiling_db", 121.0),
    ],
)
def test_agc_nonfinite_and_out_of_range_values_fail_closed(field_name, value):
    with pytest.raises(ConfigValidationError, match=field_name):
        _validate(
            EffectsConfig(
                electronics=ElectronicsConfig(
                    enabled=True,
                    full_scale=1.0,
                    bit_depth=16,
                    agc=replace(_agc(), **{field_name: value}),
                )
            )
        )


@pytest.mark.parametrize("bit_depth", [8, 32])
@pytest.mark.parametrize("target", [-120.0, 0.0])
def test_frozen_inclusive_endpoints_validate(bit_depth, target):
    config = EffectsConfig(
        electronics=ElectronicsConfig(
            enabled=True,
            full_scale=1.0,
            bit_depth=bit_depth,
            agc=AgcConfig(
                enabled=True,
                target_rms_dbfs=target,
                attack_time_s=60.0,
                release_time_s=60.0,
                gain_floor_db=-120.0,
                gain_ceiling_db=120.0,
            ),
        )
    )
    _validate(config)


def test_bit_depth_non_integer_and_shared_seed_out_of_range_fail_closed():
    with pytest.raises(ConfigValidationError, match="bit_depth"):
        _validate(
            EffectsConfig(
                electronics=ElectronicsConfig(
                    enabled=True, full_scale=1.0, bit_depth=16.0
                )
            )
        )
    with pytest.raises(ConfigValidationError, match="seed"):
        _validate(_effects(dither=True, seed=2**63))


def test_boundary_clipping_counts_ratio_and_diagnostics_contract_are_exact():
    n = np.arange(16)
    samples = np.asarray(
        [
            (-1.0) ** n,
            (-1.0) ** n * (1.0 - STEP),
            (-1.0) ** n * 1.5,
            np.tile((1.0, -1.0, 1.5, -1.5), 4),
        ]
    )
    output, diagnostics = _apply(samples)
    electronics = diagnostics["electronics"]
    assert set(electronics) == {
        "clipping_count_per_mic",
        "saturated_sample_ratio",
        "agc_gain_trace_summary",
        "quantization_step",
    }
    assert electronics["clipping_count_per_mic"] == dict(
        zip(MIC_IDS, (0, 0, 16, 8), strict=True)
    )
    assert electronics["saturated_sample_ratio"] == 0.375
    assert electronics["quantization_step"] == STEP
    assert np.max(np.abs(output)) == 1.0


def test_quantization_noise_power_frozen_ramp():
    sample_count = 2**18
    n = np.arange(sample_count, dtype=np.float64)
    samples = -1.0 + STEP / 2.0 + (2.0 - STEP) * n / (sample_count - 1)
    output, _diagnostics = _apply(samples[None])
    ratio = float(np.mean((output[0] - samples) ** 2) / (STEP**2 / 12.0))
    assert 0.9 <= ratio <= 1.1


def test_tpdf_dither_named_stream_peak_to_peak_and_decorrelation():
    sample_count = 2**18
    n = np.arange(sample_count, dtype=np.float64)
    signal = 0.75 * np.sin(2.0 * np.pi * 5_445 * n / sample_count)
    output, _diagnostics = _apply(
        np.tile(signal, (4, 1)),
        _effects(dither=True),
        frame_id="electronics_dither_000000",
    )
    for mic_index, mic_id in enumerate(MIC_IDS):
        error = output[mic_index] - signal
        assert abs(float(np.corrcoef(signal, error)[0, 1])) <= 0.010
        dither, descriptor = generate_tpdf_dither(
            sample_count,
            step=STEP,
            seed=SEED,
            frame_id="electronics_dither_000000",
            mic_id=mic_id,
        )
        assert float(np.max(dither) - np.min(dither)) < STEP
        assert descriptor["key"].endswith(f":{mic_id}:tpdf_dither")
        assert (
            descriptor["derived_seed"]
            == named_stream_descriptor(
                SEED,
                domain="electronics",
                frame_id="electronics_dither_000000",
                mic_id=mic_id,
                effect="tpdf_dither",
            )[2]
        )


def test_agc_analytical_trace_settling_direction_silence_and_bounds():
    sample_count = 24_000
    levels = (0.5, 0.125, 1.0, 0.03125)
    stars = (0.5, 2.0, 0.25, 4.0)
    samples = np.asarray([np.full(sample_count, level) for level in levels])
    output, trace, detectors = apply_agc(
        samples,
        sample_rate_hz=SAMPLE_RATE_HZ,
        full_scale=FULL_SCALE,
        config=_agc(),
    )
    assert detectors == levels
    for index, star in enumerate(stars):
        tau = 0.010 if star < 1.0 else 0.050
        alpha = math.exp(-1.0 / (tau * SAMPLE_RATE_HZ))
        reference = star + (1.0 - star) * alpha ** np.arange(1, sample_count + 1)
        assert float(np.max(np.abs(trace[index] - reference))) <= 1e-12
        assert np.all(trace[index] >= 0.25)
        assert np.all(trace[index] <= 4.0)
        differences = np.diff(trace[index])
        assert np.all(differences <= 0.0) if star < 1.0 else np.all(differences >= 0.0)
    assert abs(20.0 * math.log10(trace[0, 3_839] / 0.5)) <= 0.01
    assert abs(20.0 * math.log10(trace[1, 19_199] / 2.0)) <= 0.01
    silent, silent_trace, silent_detectors = apply_agc(
        np.zeros_like(samples),
        sample_rate_hz=SAMPLE_RATE_HZ,
        full_scale=FULL_SCALE,
        config=_agc(),
    )
    assert silent.tobytes() == np.zeros_like(samples).tobytes()
    assert silent_trace.tobytes() == np.ones_like(samples).tobytes()
    assert silent_detectors == (0.0, 0.0, 0.0, 0.0)
    assert output.shape == samples.shape


def test_agc_disabled_and_single_sample_rules():
    samples = np.asarray([[0.5], [0.125], [1.0], [0.03125]])
    unchanged, unity, detectors = apply_agc(
        samples,
        sample_rate_hz=SAMPLE_RATE_HZ,
        full_scale=FULL_SCALE,
        config=None,
    )
    assert unchanged.tobytes() == samples.tobytes()
    assert unity.tobytes() == np.ones_like(samples).tobytes()
    assert detectors == (None, None, None, None)
    _output, observed, _detectors = apply_agc(
        samples,
        sample_rate_hz=SAMPLE_RATE_HZ,
        full_scale=FULL_SCALE,
        config=_agc(),
    )
    stars = (0.5, 2.0, 0.25, 4.0)
    for index, star in enumerate(stars):
        tau = 0.010 if star < 1.0 else 0.050
        reference = star + (1.0 - star) * math.exp(-1.0 / (tau * SAMPLE_RATE_HZ))
        assert abs(observed[index, 0] - reference) <= 1e-12


def test_quantizer_ties_endpoints_idempotence_and_full_scale_not_clipped():
    ties = np.asarray([-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]) * STEP
    assert np.array_equal(
        quantize(ties, full_scale=1.0, step=STEP) / STEP,
        np.asarray([-2.0, -2.0, -0.0, 0.0, 2.0, 2.0]),
    )
    levels = np.arange(-32_768, 32_769, dtype=np.float64) * STEP
    first, _ = _apply(levels[None])
    second, _ = _apply(first)
    assert first.tobytes() == second.tobytes()
    signs = np.tile((-1.0, 1.0), 2_048)[None]
    output, diagnostics = _apply(signs)
    assert output.tobytes() == signs.tobytes()
    assert diagnostics["electronics"]["clipping_count_per_mic"] == {"front": 0}


def test_empty_dc_nonfinite_and_enabled_agc_empty_edge_rules(monkeypatch):
    monkeypatch.setattr(
        electronics_module,
        "named_generator",
        lambda *_args, **_kwargs: pytest.fail("empty input consumed a dither draw"),
    )
    empty, diagnostics = _apply(np.empty((1, 0)), _effects(dither=True))
    assert empty.shape == (1, 0)
    assert diagnostics["electronics"]["saturated_sample_ratio"] == 0.0
    assert diagnostics["electronics"]["clipping_count_per_mic"] == {"front": 0}
    with pytest.raises(ConfigValidationError, match="non-empty"):
        _apply(np.empty((1, 0)), _effects(agc=_agc()))
    dc = np.full((1, 4), 0.5)
    _output, diagnostics = _apply(dc, _effects(agc=_agc()))
    assert (
        diagnostics["electronics"]["agc_gain_trace_summary"]["front"]["detector_rms"]
        == 0.5
    )
    original = np.asarray([[math.nan]])
    before = original.tobytes()
    with pytest.raises(ConfigValidationError, match="non-finite"):
        _apply(original)
    assert original.tobytes() == before


@pytest.mark.parametrize("backend", [GeometryBackend, TdoaSyntheticBackend])
def test_enabled_electronics_is_typed_unsupported_on_l0_l1(backend):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array)
    with pytest.raises(UnsupportedEffectError, match="electronics"):
        backend(effects=_effects()).simulate(scene, array, time_window())


def _primary_premix(_room, *, source_count: int, mic_count: int):
    n = np.arange(48_000, dtype=np.float64)
    frequencies = (997.0, 1_499.0, 2_203.0, 3_301.0)
    mixture = np.asarray(
        [
            0.9 * np.sin(2.0 * np.pi * frequency * n / SAMPLE_RATE_HZ)
            + 0.6 * np.sin(2.0 * np.pi * (frequency + 211.0) * n / SAMPLE_RATE_HZ)
            for frequency in frequencies[:mic_count]
        ]
    )
    if source_count == 1:
        return mixture[None]
    premix = np.zeros((source_count, mic_count, n.size), dtype=np.float64)
    for source_index in range(source_count):
        premix[source_index, :, source_index::source_count] = mixture[
            :, source_index::source_count
        ]
    return premix


def test_room_electronics_once_on_mixture_rms_export_and_seed_replay(monkeypatch):
    fake = install_fake_pyroom(monkeypatch)
    base_shoebox = fake.ShoeBox

    class ControlledShoebox(base_shoebox):
        def simulate(self, return_premix=False):
            premix = _primary_premix(
                self,
                source_count=len(self.sources),
                mic_count=self.mic_array.R.shape[1],
            )
            self.mic_array.signals = premix.sum(axis=0)
            return premix if return_premix else None

    fake.ShoeBox = ControlledShoebox
    array = quad_array()
    results = []
    for source_count in (1, 4):
        scene = room_scene(
            *(
                source(f"speaker_{index}", (3.0, 0.1 * index, 0.0))
                for index in range(source_count)
            ),
            array=array,
        )
        sink = CaptureSink()
        frame = RoomAcousticsBackend(
            waveform_writer=sink,
            effects=_effects(dither=True, agc=_agc()),
        ).simulate(scene, array, time_window())
        mixture = sink.calls[0]["mixture"]
        electronics = frame.diagnostics["effects"]["electronics"]
        results.append((mixture, electronics))
        for mic_index, mic_id in enumerate(MIC_IDS):
            rms = float(np.sqrt(np.mean(mixture[mic_index] ** 2)))
            assert abs(frame.aggregate_per_mic_rms[mic_id] - rms) <= 1e-12
    assert results[0][0].tobytes() == results[1][0].tobytes()
    assert results[0][1] == results[1][1]

    replay_sinks = (CaptureSink(), CaptureSink())
    replay_frames = tuple(
        RoomAcousticsBackend(
            waveform_writer=sink,
            effects=_effects(dither=True, agc=_agc()),
        ).simulate(
            room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array),
            array,
            time_window(),
        )
        for sink in replay_sinks
    )
    assert replay_frames[0] == replay_frames[1]
    assert (
        replay_sinks[0].calls[0]["mixture"].tobytes()
        == replay_sinks[1].calls[0]["mixture"].tobytes()
    )


def test_segmented_room_noise_and_electronics_compose_once(monkeypatch):
    install_fake_pyroom(monkeypatch)
    scene, array, window = motion_room_fixture()
    _history, plan = motion_plan(
        lambda time_s: (1.0 + 20.0 * time_s, 2.0, 1.0),
        (20.0, 0.0, 0.0),
    )
    effects = _effects(dither=True, agc=_agc())
    effects = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=SEED,
            self_noise=SelfNoiseConfig(default=NoiseLevelSpecConfig(level_db=-48.0)),
        ),
        electronics=effects.electronics,
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=MOTION_SEGMENTS,
        ),
    )
    frame = RoomAcousticsBackend(effects=effects, window_motion=plan).simulate(
        scene, array, window
    )
    assert frame.diagnostics["motion"]["segments_per_window"] == MOTION_SEGMENTS
    assert "noise" in frame.diagnostics["effects"]
    assert "electronics" in frame.diagnostics["effects"]


def test_off_state_identity_backend_has_no_effects_key(monkeypatch):
    samples = np.asarray([[1.0, -0.0]], dtype=np.float64)
    output, diagnostics = ChannelEffectsChain().apply(
        samples,
        mic_ids=("front",),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="off",
    )
    assert output is samples
    assert diagnostics == {}

    install_fake_pyroom(monkeypatch)
    array = quad_array()
    sink = CaptureSink()
    frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
        room_scene(source("speaker", (3.0, 0.0, 0.0)), array=array),
        array,
        time_window(),
    )
    assert sink.calls[0]["mixture"].size > 0
    assert "effects" not in frame.diagnostics


def test_seed_replay_and_separation_change_every_active_derived_seed():
    sample_count = 48_000
    n = np.arange(sample_count, dtype=np.float64)
    samples = np.asarray(
        [
            0.9 * np.sin(2 * np.pi * frequency * n / SAMPLE_RATE_HZ)
            for frequency in (997, 1499, 2203, 3301)
        ]
    )
    first, first_diagnostics = _apply(samples, _effects(dither=True, agc=_agc()))
    replay, replay_diagnostics = _apply(samples, _effects(dither=True, agc=_agc()))
    alternate, _ = _apply(samples, _effects(dither=True, agc=_agc(), seed=ALT_SEED))
    assert first.tobytes() == replay.tobytes()
    assert first_diagnostics == replay_diagnostics
    assert first.tobytes() != alternate.tobytes()
    primary_seeds = {
        named_stream_descriptor(
            SEED,
            domain="electronics",
            frame_id=FRAME_ID,
            mic_id=mic_id,
            effect="tpdf_dither",
        )[2]
        for mic_id in MIC_IDS
    }
    alternate_seeds = {
        named_stream_descriptor(
            ALT_SEED,
            domain="electronics",
            frame_id=FRAME_ID,
            mic_id=mic_id,
            effect="tpdf_dither",
        )[2]
        for mic_id in MIC_IDS
    }
    assert len(primary_seeds) == len(alternate_seeds) == 4
    assert primary_seeds.isdisjoint(alternate_seeds)
