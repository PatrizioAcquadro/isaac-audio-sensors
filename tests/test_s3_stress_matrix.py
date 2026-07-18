"""S3.8 motion, multi-source, resource, and fail-closed stress tests."""

from __future__ import annotations

import json
import math
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import isaac_audio_sensors.isaac.extension as extension_module
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import (
    AgcConfig,
    AmbientNoiseConfig,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    DirectivityConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    ElectronicsConfig,
    FrequencyResponsePointConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    SelfNoiseConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
    SourceOcclusion,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor

SAMPLE_RATE_HZ = 48_000
WINDOW_DURATION_S = 0.05
WINDOW_SAMPLE_COUNT = 2_400
MIC_IDS = ("front", "right", "rear", "left")


class _CaptureSink:
    def __init__(self) -> None:
        self.mixtures: list[np.ndarray] = []

    def write_frame_mixture(self, **kwargs: object) -> WaveformWriteResult:
        self.mixtures.append(
            np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        )
        return WaveformWriteResult(paths=("memory://s3_8.wav",))

    def close(self) -> None:
        return None


class _FakeMaterial:
    def __init__(self, absorption: object) -> None:
        self.absorption = absorption


class _FakeMicrophoneArray:
    def __init__(self, positions: object, fs: int) -> None:
        self.R = np.asarray(positions, dtype=float)
        self.fs = int(fs)
        self.signals = np.zeros((self.R.shape[1], 0))


class _FakeShoeBox:
    def __init__(
        self,
        dimensions: object,
        *,
        fs: int,
        max_order: int = 0,
        c: float = 343.0,
        **_kwargs: object,
    ) -> None:
        self.dimensions = dimensions
        self.fs = int(fs)
        self.max_order = int(max_order)
        self.c = float(c)
        self.sources: list[tuple[np.ndarray, np.ndarray]] = []
        self.mic_array: _FakeMicrophoneArray | None = None
        self.rir: list[list[np.ndarray]] = []

    def add_source(self, position: object, signal: object) -> None:
        self.sources.append(
            (np.asarray(position, dtype=float), np.asarray(signal, dtype=float))
        )

    def add_microphone_array(self, mic_array: _FakeMicrophoneArray) -> None:
        self.mic_array = mic_array

    def compute_rir(self) -> None:
        assert self.mic_array is not None
        self.rir = []
        for mic_position in self.mic_array.R.T:
            per_source = []
            for source_position, _signal in self.sources:
                distance = float(np.linalg.norm(source_position - mic_position))
                delay = max(0, int(round(distance / self.c * self.fs)))
                rir = np.zeros(delay + 24 + self.max_order)
                rir[delay] = 1.0 / max(distance, 0.1)
                for order in range(1, self.max_order + 1):
                    rir[delay + 12 + order] = 0.1 / (order * max(distance, 0.1))
                per_source.append(rir)
            self.rir.append(per_source)

    def simulate(self, return_premix: bool = False) -> np.ndarray | None:
        assert self.mic_array is not None
        convolved = [
            [
                np.convolve(signal, self.rir[mic_index][source_index])
                for mic_index in range(self.mic_array.R.shape[1])
            ]
            for source_index, (_position, signal) in enumerate(self.sources)
        ]
        maximum = max(len(signal) for row in convolved for signal in row)
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], maximum))
        for source_index, row in enumerate(convolved):
            for mic_index, signal in enumerate(row):
                premix[source_index, mic_index, : len(signal)] = signal
        self.mic_array.signals = premix.sum(axis=0)
        return premix if return_premix else None


@pytest.fixture
def fake_room(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("pyroomacoustics")
    fake.__version__ = "fake-s3.8"
    fake.Material = _FakeMaterial
    fake.MicrophoneArray = _FakeMicrophoneArray
    fake.ShoeBox = _FakeShoeBox
    monkeypatch.setitem(sys.modules, "pyroomacoustics", fake)


def _array(**changes: object):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Robot/AudioMount",
        layout_name="quad_cross",
        spacing_m=0.08,
        position_world=(1.0, 2.0, 1.5),
    )
    return replace(array, **changes) if changes else array


def _source(
    index: int,
    position: tuple[float, float, float],
    *,
    velocity: tuple[float, float, float] | None = None,
    gain_db: float = 0.0,
    source_id: str | None = None,
) -> AudioSourceSpec:
    resolved_id = source_id or f"source-{index:02d}"
    return AudioSourceSpec(
        source_id=resolved_id,
        prim_path=f"/World/Audio/Source{index:02d}",
        class_label="stress",
        audio_asset_path="generated://two_tone",
        position_world=position,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        start_time_s=0.0,
        duration_s=None,
        gain_db=gain_db,
        directivity="cardioid",
        velocity_world_mps=velocity,
    )


def _scene(
    sources: tuple[AudioSourceSpec, ...],
    *,
    array=None,
    max_order: int = 1,
    occlusion: tuple[SourceOcclusion, ...] | None = None,
) -> AudioSceneSnapshot:
    selected = array or _array()
    return AudioSceneSnapshot(
        stage_id="s3_8_stress",
        timestamp_ms=0,
        sources=sources,
        arrays=(selected,),
        room=RoomAcousticsSpec(
            room_id="s3_8_room",
            dimensions_m=(12.5, 4.0, 3.0),
            absorption=0.35,
            max_order=max_order,
            origin_m=(0.0, 0.0, 0.0),
        ),
        occlusion=occlusion,
    )


def _window(*, frame_index: int = 0, max_events: int = 8) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=frame_index * WINDOW_DURATION_S,
        end_time_s=(frame_index + 1) * WINDOW_DURATION_S,
        timestamp_ms=frame_index * 50,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=frame_index,
        max_events=max_events,
    )


def _ids(frame: object) -> tuple[str, ...]:
    return tuple(detection.source_id for detection in frame.detections)


def _assert_finite(value: object, *, key: str | None = None) -> None:
    if key == "time_code":
        return
    if isinstance(value, (float, np.floating)):
        assert math.isfinite(float(value))
    elif isinstance(value, np.ndarray):
        assert bool(np.isfinite(value).all())
    elif isinstance(value, dict):
        for child_key, child in value.items():
            _assert_finite(child, key=str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_finite(child)


def _payload(frame: object) -> bytes:
    return json.dumps(
        frame_to_trace_dict(frame),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _all_effects(*, segments: int = 1) -> EffectsConfig:
    channel = {
        mic_id: ChannelResponseMicConfig(
            gain_db=(-1.5, 0.0, 1.0, -0.5)[index],
            delay_s=index / SAMPLE_RATE_HZ,
            polarity=1 if index % 2 == 0 else -1,
            frequency_response=(
                FrequencyResponsePointConfig(frequency_hz=500.0, magnitude_db=0.0),
                FrequencyResponsePointConfig(frequency_hz=2_000.0, magnitude_db=-1.0),
                FrequencyResponsePointConfig(frequency_hz=6_000.0, magnitude_db=0.5),
            ),
        )
        for index, mic_id in enumerate(MIC_IDS)
    }
    pattern = DirectivityPatternConfig(family="cardioid")
    return EffectsConfig(
        channel_response=ChannelResponseConfig(enabled=True, microphones=channel),
        noise=NoiseConfig(
            enabled=True,
            seed=38_017,
            self_noise=SelfNoiseConfig(
                default=NoiseLevelSpecConfig(level_db=-55.0)
            ),
            ambient=AmbientNoiseConfig(level_db=-50.0, coherent_fraction=0.25),
        ),
        electronics=ElectronicsConfig(
            enabled=True,
            full_scale=1.0,
            bit_depth=16,
            dither_enabled=True,
            agc=AgcConfig(
                enabled=True,
                target_rms_dbfs=-18.0,
                attack_time_s=0.01,
                release_time_s=0.05,
                gain_floor_db=-12.0,
                gain_ceiling_db=12.0,
            ),
        ),
        directivity=DirectivityConfig(
            enabled=True,
            source_patterns=DirectivityPatternSetConfig(default=pattern),
            mic_patterns=DirectivityPatternSetConfig(default=pattern),
            mode="per_pair_direct_path",
        ),
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=segments > 1,
            segments_per_window=segments,
        ),
    )


def _motion_plan(scene: AudioSceneSnapshot, *, segments: int = 8):
    history = PoseHistory()
    entities = {
        source.source_id: EntityMotionInput(
            position_world_m=source.position_world,
            velocity_world_mps=source.velocity_world_mps,
            velocity_source="authored",
        )
        for source in scene.sources
    }
    array = scene.arrays[0]
    entities[array.array_id] = EntityMotionInput(
        position_world_m=array.position_world,
        velocity_world_mps=array.velocity_world_mps,
        velocity_source="authored" if array.velocity_world_mps else "none",
    )
    for entity_id, entity in entities.items():
        velocity = entity.velocity_world_mps or (0.0, 0.0, 0.0)
        previous = tuple(
            entity.position_world_m[index] - velocity[index] * WINDOW_DURATION_S
            for index in range(3)
        )
        history.observe(entity_id, 0.0, previous)
        history.observe(entity_id, WINDOW_DURATION_S, entity.position_world_m)
    return build_window_motion(
        history,
        entities=entities,
        start_time_s=0.0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        window_sample_count=WINDOW_SAMPLE_COUNT,
        segments_per_window=segments,
    )


def test_p01_p02_authored_and_pose_derived_doppler_are_finite() -> None:
    radial_velocities = (-5.0, -1.0, 0.0, 1.0, 5.0)
    factors = []
    for frame_index in range(64):
        radial_mps = radial_velocities[frame_index % len(radial_velocities)]
        array_velocity = (-1.0, 0.0, 1.0)[frame_index % 3]
        array = _array(velocity_world_mps=(array_velocity, 0.0, 0.0))
        source = _source(0, (5.0, 2.0, 1.5), velocity=(radial_mps, 0.0, 0.0))
        frame = TdoaSyntheticBackend().simulate(
            _scene((source,), array=array), array, _window(frame_index=frame_index)
        )
        factor = frame.detections[0].diagnostics["doppler_factor"]
        factors.append(factor)
        assert factor > 0.0 and math.isfinite(factor)
    assert min(factors) < 1.0 < max(factors)

    history = PoseHistory()
    for frame_index in range(66):
        time_s = frame_index * WINDOW_DURATION_S
        derived = history.observe(
            "source-00", time_s, (5.0 + 5.0 * time_s, 2.0, 1.5)
        )
        if frame_index == 0:
            assert derived.velocity_world_mps is None
        else:
            assert derived.velocity_world_mps == pytest.approx((5.0, 0.0, 0.0))
            assert derived.reason == "derived"


@pytest.mark.parametrize("backend", (GeometryBackend(), TdoaSyntheticBackend()))
@pytest.mark.parametrize("count", (2, 4, 8))
def test_p03_overlap_ladder_keeps_every_source(backend: object, count: int) -> None:
    array = _array()
    sources = tuple(
        _source(index, (2.0 + index, 0.5 + (index % 4), 1.5))
        for index in reversed(range(count))
    )
    for frame_index in range(32):
        frame = backend.simulate(
            _scene(sources, array=array),
            array,
            _window(frame_index=frame_index),
        )
        assert set(_ids(frame)) == {
            f"source-{index:02d}" for index in range(count)
        }
        assert len(frame.detections) == count
        _assert_finite(frame_to_trace_dict(frame))


def test_p04_p05_coincident_and_near_far_identity_never_merge() -> None:
    array = _array()
    coincident = (_source(0, (3.0, 2.0, 1.5)), _source(1, (3.0, 2.0, 1.5)))
    near_far = (
        _source(0, (1.1, 2.0, 1.5)),
        _source(1, (11.0, 2.0, 1.5), gain_db=40.0),
    )
    for frame_index in range(64):
        for sources in (
            coincident,
            near_far if frame_index < 32 else tuple(reversed(near_far)),
        ):
            frame = TdoaSyntheticBackend().simulate(
                _scene(sources, array=array),
                array,
                _window(frame_index=frame_index),
            )
            assert _ids(frame) == ("source-00", "source-01")
            assert len({detection.detection_id for detection in frame.detections}) == 2


def test_p06_reverberation_ladder_changes_real_backend_output(fake_room: None) -> None:
    array = _array()
    source = _source(0, (4.0, 2.0, 1.5))
    hashes = []
    for order in (0, 1, 3, 6):
        repeated = []
        for _frame_index in range(16):
            sink = _CaptureSink()
            frame = RoomAcousticsBackend(waveform_writer=sink).simulate(
                _scene((source,), array=array, max_order=order), array, _window()
            )
            _assert_finite(frame_to_trace_dict(frame))
            _assert_finite(sink.mixtures[0])
            repeated.append(sink.mixtures[0].tobytes())
        assert len(set(repeated)) == 1
        hashes.append(repeated[0])
    assert len(set(hashes)) == 4


def test_p07_p08_current_occlusion_and_moving_mount_state() -> None:
    source = _source(0, (5.0, 2.0, 1.5))
    observed = []
    for frame_index in range(80):
        index = frame_index // 16
        factor = (0.0, 0.25, 1.0, 0.25, 0.0)[index]
        array = _array(position_world=(1.0 + 0.1 * index, 2.0, 1.5))
        blocked = factor > 0.0
        record = SourceOcclusion(
            array_id="rig",
            source_id="source-00",
            per_mic_blocked={mic_id: blocked for mic_id in MIC_IDS},
            occlusion_factor=factor,
            attenuation_db=12.0 * factor,
            hit_prim_paths=() if not blocked else ("/World/Occluder",),
        )
        frame = GeometryBackend().simulate(
            _scene((source,), array=array, occlusion=(record,)),
            array,
            _window(frame_index=frame_index),
        )
        observed.append(
            frame.detections[0].diagnostics["occlusion"]["occlusion_factor"]
        )
    assert observed == [
        value
        for value in (0.0, 0.25, 1.0, 0.25, 0.0)
        for _ in range(16)
    ]

    bearings = []
    for frame_index in range(128):
        phase = frame_index / 127.0
        yaw_deg = -30.0 + 120.0 * phase if phase <= 0.5 else 90.0 - 120.0 * phase
        half = math.radians(yaw_deg) / 2.0
        array = create_microphone_array(
            array_id="rig",
            prim_path="/World/Robot/AudioMount",
            layout_name="quad_cross",
            spacing_m=0.08,
            position_world=(1.0, 2.0, 1.5),
            orientation_world_quat=(0.0, 0.0, math.sin(half), math.cos(half)),
        )
        frame = GeometryBackend().simulate(
            _scene((source,), array=array),
            array,
            _window(frame_index=frame_index),
        )
        bearings.append(frame.detections[0].doa.estimated_bearing_deg)
    assert bearings[0] != bearings[64]
    assert bearings[0] == pytest.approx(bearings[-1])


def test_p09_identity_persistence_under_256_frame_churn() -> None:
    array = _array()
    persistent = (_source(0, (4.0, 1.0, 1.5)), _source(1, (4.0, 3.0, 1.5)))
    removed: set[str] = set()
    for frame_index in range(256):
        churn_index = 2 + (frame_index // 16) % 6
        transient = _source(churn_index, (3.0 + churn_index, 2.0, 1.5))
        sources = (*persistent, transient)
        frame = GeometryBackend().simulate(
            _scene(sources, array=array), array, _window(frame_index=frame_index)
        )
        ids = set(_ids(frame))
        assert {"source-00", "source-01"} <= ids
        assert not (removed & ids)
        if frame_index % 16 == 15:
            removed.add(transient.source_id)
            removed.discard(f"source-{2 + ((frame_index // 16 + 1) % 6):02d}")


def test_p10_all_effects_l2_and_complete_live_forwarding(
    fake_room: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    array = _array(velocity_world_mps=(0.5, 0.0, 0.0))
    sources = tuple(
        _source(index, (2.0 + index, 1.0 + (index % 3), 1.5), velocity=(1.0, 0.0, 0.0))
        for index in range(8)
    )
    scene = _scene(sources, array=array, max_order=3)
    effects = _all_effects(segments=8)
    for _frame_index in range(32):
        sink = _CaptureSink()
        frame = RoomAcousticsBackend(
            effects=effects,
            window_motion=_motion_plan(scene),
            waveform_writer=sink,
        ).simulate(scene, array, _window())
        assert set(frame.diagnostics["effects"]) == {
            "channel_response",
            "noise",
            "electronics",
            "directivity",
        }
        assert frame.diagnostics["motion"]["segments_per_window"] == 8
        _assert_finite(sink.mixtures[0])

    captured: dict[str, object] = {}

    class _Backend:
        def simulate(self, scene: object, sensor: object, window: object):
            captured["simulated"] = True
            return GeometryBackend().simulate(scene, sensor, window)

    def _get_backend(_backend_id: str, **kwargs: object) -> _Backend:
        captured.update(kwargs)
        return _Backend()

    monkeypatch.setattr(extension_module, "get_backend", _get_backend)
    forwarded_effects = replace(effects, motion=MotionEffectsConfig())
    live = IsaacAudioArraySensor(
        array_id="rig",
        backend="room_acoustics",
        effects=forwarded_effects,
        stage_snapshot=scene,
        room=scene.room,
    )
    live.capture(timestamp_ms=0, start_time_s=0.0, end_time_s=0.05)
    assert captured["effects"] is forwarded_effects
    assert captured["simulated"] is True


def test_p11_4096_frame_rss_sampling_and_ols_bounds() -> None:
    samples = []
    retained = None
    baseline = None
    for frame_index in range(4_096):
        retained = np.full((2, 4, 16), frame_index % 17, dtype=np.float32)
        if frame_index % 64 == 0 or frame_index == 4_095:
            rss_mib = _vmrss_mib()
            baseline = rss_mib if baseline is None else baseline
            samples.append((frame_index, rss_mib))
    assert retained is not None and len(samples) >= 65
    post = np.asarray([row for row in samples if row[0] >= 512], dtype=float)
    slope, intercept = np.polyfit(post[:, 0], post[:, 1], 1)
    predicted = slope * post[:, 0] + intercept
    residual = float(np.sum((post[:, 1] - predicted) ** 2))
    total = float(np.sum((post[:, 1] - np.mean(post[:, 1])) ** 2))
    r_squared = 1.0 if total == 0.0 else 1.0 - residual / total
    assert math.isfinite(r_squared)
    assert slope * 1_000.0 <= 4.0
    assert max(row[1] for row in samples) - float(baseline) <= 128.0


def test_p12_gap_preservation_and_p13_determinism_replay() -> None:
    blocks = [np.full(4, index + 1.0) for index in range(72)]
    preserved = np.zeros(96 * 4)
    captured_index = 0
    for slot in range(96):
        if slot % 4 == 3:
            continue
        preserved[slot * 4 : (slot + 1) * 4] = blocks[captured_index]
        captured_index += 1
    compact = np.concatenate(blocks)
    assert captured_index == 72
    assert np.count_nonzero(preserved.reshape(96, 4).sum(axis=1) == 0.0) == 24
    assert compact.shape == (72 * 4,)

    array = _array()
    scene = _scene((_source(0, (4.0, 2.0, 1.5)),), array=array)
    first = _payload(TdoaSyntheticBackend().simulate(scene, array, _window()))
    second = _payload(TdoaSyntheticBackend().simulate(scene, array, _window()))
    assert first == second


def test_matrix_profiles_and_explicit_unsupported_cells() -> None:
    base = EffectsConfig()
    for backend_id in ("geometry_only", "tdoa_synthetic"):
        for profile in ("training_features", "waveform_fidelity"):
            validate_effects_config(
                base,
                microphone_orders=(MIC_IDS,),
                sample_rate_hz=SAMPLE_RATE_HZ,
                backend_id=backend_id,
                runtime_profile=profile,
            )
    with pytest.raises(UnsupportedEffectError, match="segments_per_window>1"):
        validate_effects_config(
            EffectsConfig(
                motion=MotionEffectsConfig(
                    derive_velocity_from_poses=True, segments_per_window=8
                )
            ),
            microphone_orders=(MIC_IDS,),
            sample_rate_hz=SAMPLE_RATE_HZ,
            backend_id="tdoa_synthetic",
            runtime_profile="waveform_fidelity",
        )
    with pytest.raises(
        UnsupportedEffectError,
        match="room_acoustics_srp requires at least three microphones",
    ):
        two_mic = create_microphone_array(
            array_id="rig",
            prim_path="/World/Rig",
            layout_name="two_mic_y",
        )
        RoomAcousticsSrpBackend().simulate(
            _scene((_source(0, (4.0, 2.0, 1.5)),), array=two_mic),
            two_mic,
            _window(),
        )


@pytest.mark.parametrize(
    ("effects", "message"),
    (
        (
            EffectsConfig(
                motion=MotionEffectsConfig(derive_velocity_from_poses=True)
            ),
            "derive_velocity_from_poses=true is unsupported by Isaac Lab "
            "batched compute in Stage 1",
        ),
        (
            EffectsConfig(motion=MotionEffectsConfig(segments_per_window=8)),
            "audio.effects.motion.segments_per_window>1 is unsupported by "
            "Isaac Lab batched compute",
        ),
        (
            EffectsConfig(channel_response=ChannelResponseConfig(enabled=True)),
            "audio.effects.channel_response is unsupported by Isaac Lab "
            "batched compute",
        ),
        (
            EffectsConfig(noise=NoiseConfig(enabled=True)),
            "audio.effects.noise is unsupported by Isaac Lab batched compute",
        ),
        (
            EffectsConfig(electronics=ElectronicsConfig(enabled=True)),
            "audio.effects.electronics is unsupported by Isaac Lab batched compute",
        ),
        (
            EffectsConfig(directivity=DirectivityConfig(enabled=True)),
            "audio.effects.directivity is unsupported by Isaac Lab batched compute",
        ),
    ),
)
def test_lab_batched_failures_precede_output(
    effects: EffectsConfig, message: str
) -> None:
    sensor = object.__new__(AudioArraySensor)
    sensor.cfg = SimpleNamespace(effects=effects)
    with pytest.raises(UnsupportedEffectError, match=message):
        sensor._validate_batched_effects()  # noqa: SLF001 - proof obligation.


def test_lab_authored_scalar_path_and_batched_rejection() -> None:
    array = _array(velocity_world_mps=(0.0, 0.0, 0.0))
    scene = _scene(
        (_source(0, (4.0, 2.0, 1.5), velocity=(1.0, 0.0, 0.0)),),
        array=array,
    )
    scalar = object.__new__(AudioArraySensor)
    scalar.cfg = SimpleNamespace(
        backend="tdoa_synthetic",
        ambiguity_policy="none",
        max_events=8,
        compute_path="scalar",
        effects=EffectsConfig(),
    )
    scalar._frame_indices = [0]
    scalar._waveform_sinks = {}
    frame = scalar.capture_frame(
        scene_snapshot=scene,
        sensor=array,
        timestamp_ms=0,
        start_time_s=0.0,
        end_time_s=0.05,
    )
    assert frame.detections[0].diagnostics["doppler_factor"] != 1.0

    scalar.cfg.compute_path = "batched"
    with pytest.raises(
        UnsupportedEffectError,
        match="authored velocity Doppler semantics require the Lab scalar frame path",
    ):
        scalar.capture_frame(
            scene_snapshot=scene,
            sensor=array,
            timestamp_ms=0,
            start_time_s=0.0,
            end_time_s=0.05,
        )


def test_lab_batched_occlusion_and_material_failures_precede_output() -> None:
    array = _array()
    source = _source(0, (4.0, 2.0, 1.5))
    occlusion = SourceOcclusion(
        array_id="rig",
        source_id=source.source_id,
        per_mic_blocked={mic_id: True for mic_id in MIC_IDS},
        occlusion_factor=0.5,
        attenuation_db=6.0,
        hit_prim_paths=("/World/Occluder",),
    )
    sensor = object.__new__(AudioArraySensor)
    sensor.cfg = SimpleNamespace(effects=EffectsConfig())
    sensor._scene_provider = None
    sensor._bound_scene_snapshots = {
        0: _scene((source,), array=array, occlusion=(occlusion,))
    }
    with pytest.raises(
        UnsupportedEffectError,
        match=(
            "AudioSceneSnapshot.occlusion is unsupported by Isaac Lab batched "
            "compute"
        ),
    ):
        sensor._validate_batched_effects()  # noqa: SLF001 - proof obligation.

    sensor._bound_scene_snapshots = {0: _scene((source,), array=array)}
    with pytest.raises(
        UnsupportedEffectError,
        match="AudioSceneSnapshot.room is unsupported by Isaac Lab batched compute",
    ):
        sensor._validate_batched_effects()  # noqa: SLF001 - proof obligation.


def test_edges_zero_saturation_silence_duplicate_and_subsample() -> None:
    array = _array()
    empty = GeometryBackend().simulate(_scene((), array=array), array, _window())
    assert empty.detections == ()
    _assert_finite(frame_to_trace_dict(empty))

    sources = tuple(
        _source(index, (2.0 + index, 1.0, 1.5)) for index in reversed(range(10))
    )
    saturated = GeometryBackend().simulate(
        _scene(sources, array=array), array, _window(max_events=8)
    )
    assert _ids(saturated) == tuple(f"source-{index:02d}" for index in range(8))

    silent = tuple(replace(source, gain_db=-10_000.0) for source in sources[:2])
    silent_frame = TdoaSyntheticBackend().simulate(
        _scene(silent, array=array), array, _window()
    )
    assert all(
        all(value == 0.0 for value in detection.per_mic_rms.values())
        for detection in silent_frame.detections
    )

    duplicate = _source(0, (3.0, 2.0, 1.5), source_id="same")
    with pytest.raises(ValueError, match="Duplicate source id 'same'."):
        _scene((duplicate, duplicate), array=array)

    with pytest.raises(
        UnsupportedEffectError,
        match="must be no greater than window_sample_count=0",
    ):
        validate_effects_config(
            EffectsConfig(
                motion=MotionEffectsConfig(
                    derive_velocity_from_poses=True, segments_per_window=2
                )
            ),
            microphone_orders=(MIC_IDS,),
            sample_rate_hz=SAMPLE_RATE_HZ,
            backend_id="room_acoustics",
            runtime_profile="waveform_fidelity",
            sample_count=0,
        )


def _vmrss_mib() -> float:
    with open("/proc/self/status", encoding="utf-8") as status:  # noqa: PTH123
        for line in status:
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    raise RuntimeError("/proc/self/status did not report VmRSS")
