from __future__ import annotations

import sys
import types

import numpy as np

from isaac_audio_sensors.core.acoustics.environments import shoebox_environment
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
)
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.simulation import simulate_frame
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneSignalBlock,
)

SAMPLE_RATE_HZ = 48_000
WINDOW_SAMPLE_COUNT = 2_400
MOTION_SEGMENTS = 8


class FakeUsdPrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.path = str(path)
        self.type_name = type_name
        self.attributes = attributes if attributes is not None else {}

    def IsValid(self) -> bool:
        return True

    def GetPath(self) -> str:
        return self.path


class FakeUsdStage:
    def __init__(
        self,
        prims: tuple[FakeUsdPrim, ...] = (),
        *,
        time_codes_per_second: float = 1.0,
    ) -> None:
        self.prims = {prim.path: prim for prim in prims}
        self.removed: list[str] = []
        self.traverse_count = 0
        self.time_codes_per_second = time_codes_per_second

    def Traverse(self) -> tuple[FakeUsdPrim, ...]:
        self.traverse_count += 1
        return tuple(self.prims.values())

    def DefinePrim(self, path: str, type_name: str = "") -> FakeUsdPrim:
        resolved = str(path)
        prim = self.prims.get(resolved)
        if prim is None:
            prim = FakeUsdPrim(resolved, type_name)
            self.prims[resolved] = prim
        else:
            prim.type_name = type_name
        return prim

    def GetPrimAtPath(self, path: object) -> FakeUsdPrim | None:
        return self.prims.get(str(path))

    def RemovePrim(self, path: object) -> bool:
        resolved = str(path)
        removed = [
            prim_path
            for prim_path in self.prims
            if prim_path == resolved or prim_path.startswith(f"{resolved}/")
        ]
        for prim_path in removed:
            del self.prims[prim_path]
        if removed:
            self.removed.append(resolved)
        return bool(removed)

    def GetTimeCodesPerSecond(self) -> float:
        return self.time_codes_per_second

    def add(self, prim: FakeUsdPrim) -> None:
        self.prims[prim.path] = prim


def motion_stage() -> tuple[FakeUsdStage, FakeUsdPrim, FakeUsdPrim]:
    source_prim = FakeUsdPrim(
        "/World/Speaker",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker",
            "ias:class_label": "Speech",
            "ias:position_world": (1.0, 0.0, 0.0),
            "ias:duration_s": 10.0,
        },
    )
    array_prim = FakeUsdPrim(
        "/World/Rig",
        "Xform",
        {
            "ias:array_id": "rig",
            "ias:position_world": (0.0, 0.0, 0.0),
            "ias:layout_name": "quad_front",
        },
    )
    return FakeUsdStage((source_prim, array_prim)), source_prim, array_prim


class CaptureSink:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def write_signal_block(
        self,
        *,
        frame_id,
        block,
    ) -> WaveformWriteResult:
        self.calls.append(
            {
                "frame_id": frame_id,
                "block": block,
                "mixture": np.asarray(block.samples).copy(),
                "sample_rate_hz": block.sample_rate_hz,
                "mic_ids": block.microphone_ids,
                "window_sample_count": block.samples.shape[1],
            }
        )
        return WaveformWriteResult(
            paths=(f"stub://{frame_id}.wav",),
            diagnostics={"mode": "stub"},
        )

    def close(self) -> None:
        self.closed = True


def run_frame_pipeline(
    backend,
    scene,
    array_id,
    time_window,
    *,
    waveform_sink=None,
    max_observations=None,
):
    """Run the maintained block-to-frame path for test composition."""

    return simulate_frame(
        backend,
        scene,
        array_id,
        time_window,
        perception=AudioPerceptionPipeline(max_observations=max_observations),
        waveform_sink=waveform_sink,
    )


def signal_block_for_frame(frame: AudioSensorFrame, samples) -> MicrophoneSignalBlock:
    """Build the recorder input matching one frame's signal contract."""

    return MicrophoneSignalBlock(
        samples=samples,
        microphone_ids=tuple(frame.channel_validity),
        array_id=frame.array_id,
        sample_rate_hz=frame.sample_rate_hz,
        time_window=AudioTimeWindow(
            start_time_s=frame.start_time_s,
            end_time_s=frame.end_time_s,
            frame_index=frame.frame_index,
        ),
        channel_validity=tuple(frame.channel_validity.values()),
        producer_id=frame.producer_id,
        provenance=frame.provenance,
    )


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
        sources=sources,
        arrays=(array,),
        environment=shoebox_environment(
            environment_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            position_world=(-1.5, -1.0, -1.5),
        ),
    )


def time_window(
    *,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        frame_index=0,
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
        sources=(source("source", (2.0, 2.0, 1.0)),),
        arrays=(array,),
        environment=shoebox_environment(
            environment_id="room",
            dimensions_m=(8.0, 6.0, 3.0),
            absorption=0.35,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ,
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

    def set_sound_speed(self, speed_of_sound_mps):
        self.c = float(speed_of_sound_mps)

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
