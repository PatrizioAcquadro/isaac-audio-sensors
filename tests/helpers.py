from __future__ import annotations

import sys
import types

import numpy as np

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
)

SAMPLE_RATE_HZ = 48_000
WINDOW_SAMPLE_COUNT = 2_400
MOTION_SEGMENTS = 8


class CaptureSink:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def write_frame_mixture(
        self,
        *,
        frame_id,
        mixture,
        sample_rate_hz,
        mic_ids,
        window_sample_count,
    ) -> WaveformWriteResult:
        self.calls.append(
            {
                "frame_id": frame_id,
                "mixture": np.asarray(mixture).copy(),
                "sample_rate_hz": sample_rate_hz,
                "mic_ids": mic_ids,
                "window_sample_count": window_sample_count,
            }
        )
        return WaveformWriteResult(
            paths=(f"stub://{frame_id}.wav",),
            diagnostics={"mode": "stub"},
        )

    def close(self) -> None:
        self.closed = True


def quad_array():
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )


def source(
    source_id: str,
    position: tuple[float, float, float],
    *,
    audio_asset_path: str | None = "generated://impulse",
    start_time_s: float = 0.0,
    duration_s: float | None = 1.0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=None,
        start_time_s=start_time_s,
        duration_s=duration_s,
        gain_db=0.0,
    )


def room_scene(*sources: AudioSourceSpec, array):
    return AudioSceneSnapshot(
        stage_id="room_backend_test",
        timestamp_ms=0,
        sources=sources,
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            max_order=1,
            origin_m=(-1.5, -1.0, -1.5),
        ),
    )


def time_window(
    *,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_events: int | None = None,
) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        max_events=max_events,
    )


def motion_plan(position, velocity):
    duration_s = WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ
    history = PoseHistory(teleport_speed_threshold_mps=100.0)
    history.observe("source", 0.0, position(0.0))
    history.observe("source", duration_s, position(duration_s))
    history.observe("array", 0.0, (4.0, 2.0, 1.0))
    history.observe("array", duration_s, (4.0, 2.0, 1.0))
    plan = build_window_motion(
        history,
        entities={
            "source": EntityMotionInput(
                position_world_m=position(duration_s),
                velocity_world_mps=velocity,
                velocity_source="derived",
            ),
            "array": EntityMotionInput(
                position_world_m=(4.0, 2.0, 1.0),
                velocity_world_mps=(0.0, 0.0, 0.0),
                velocity_source="derived",
            ),
        },
        start_time_s=0.0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        window_sample_count=WINDOW_SAMPLE_COUNT,
        segments_per_window=MOTION_SEGMENTS,
    )
    return history, plan


def motion_room_fixture():
    array = create_microphone_array(
        array_id="array",
        prim_path="/World/Array",
        layout_name="quad_front",
        position_world=(4.0, 2.0, 1.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    scene = AudioSceneSnapshot(
        stage_id="motion_test",
        timestamp_ms=0,
        sources=(source("source", (2.0, 2.0, 1.0)),),
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="room",
            dimensions_m=(8.0, 6.0, 3.0),
            absorption=0.35,
            max_order=0,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
    )
    return scene, array, window


def install_fake_pyroom(monkeypatch):
    module = types.ModuleType("pyroomacoustics")
    module.__version__ = "fake-test"
    module.Material = FakeMaterial
    module.MicrophoneArray = FakeMicrophoneArray
    module.ShoeBox = FakeShoeBox
    FakeShoeBox.instances = []
    monkeypatch.setitem(sys.modules, "pyroomacoustics", module)
    return module


class FakeMaterial:
    def __init__(self, absorption):
        self.absorption = absorption


class FakeMicrophoneArray:
    def __init__(self, positions, fs):
        self.R = np.asarray(positions, dtype=float)
        self.fs = int(fs)
        self.signals = np.zeros((self.R.shape[1], 0))


class FakeShoeBox:
    instances: list[FakeShoeBox] = []

    def __init__(self, dimensions, *, fs, max_order=0, c=343.0, **kwargs):
        self.dimensions = dimensions
        self.fs = int(fs)
        self.max_order = int(max_order)
        self.c = float(c)
        self.kwargs = dict(kwargs)
        self.sources: list[tuple[np.ndarray, np.ndarray]] = []
        self.mic_array = None
        self.rir = []
        type(self).instances.append(self)

    def add_source(self, position, signal):
        self.sources.append(
            (np.asarray(position, dtype=float), np.asarray(signal, dtype=float))
        )

    def add_microphone_array(self, mic_array):
        self.mic_array = mic_array

    def compute_rir(self):
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        self.rir = []
        for mic_position in self.mic_array.R.T:
            per_source = []
            for source_position, _ in self.sources:
                distance = float(np.linalg.norm(source_position - mic_position))
                delay_samples = max(0, int(round(distance / self.c * self.fs)))
                impulse = np.zeros(delay_samples + 24)
                impulse[delay_samples] = 1.0 / max(distance, 0.1)
                if self.max_order > 0:
                    impulse[delay_samples + 12] = 0.1 / max(distance, 0.1)
                per_source.append(impulse)
            self.rir.append(per_source)

    def simulate(self, return_premix=False):
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        convolved = [
            [
                np.convolve(signal, self.rir[mic_index][source_index])
                for mic_index in range(self.mic_array.R.shape[1])
            ]
            for source_index, (_, signal) in enumerate(self.sources)
        ]
        max_len = max(len(signal) for row in convolved for signal in row)
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], max_len))
        for source_index, row in enumerate(convolved):
            for mic_index, signal in enumerate(row):
                premix[source_index, mic_index, : len(signal)] = signal
        self.mic_array.signals = premix.sum(axis=0)
        return premix if return_premix else None
