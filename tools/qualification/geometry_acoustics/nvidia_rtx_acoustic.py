"""Temporary in-process NVIDIA RTX Acoustic 3.0.0 adapter for R9.2."""

from __future__ import annotations

import resource
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .fixtures import QUAD_FRONT_OFFSETS_M, FixtureSpec
from .gmo import GmoClassification, classify_acoustic_gmo, expand_signal_way_ids
from .models import FixtureRun, PerformanceRun, RuntimeProbe


@dataclass(slots=True)
class _GmoEvent:
    render_product: str
    timestamp_ns: int
    transmitter_ids: np.ndarray
    receiver_ids: np.ndarray
    channel_ids: np.ndarray
    amplitudes: np.ndarray


class _EventSink:
    def __init__(self) -> None:
        self.events: list[_GmoEvent] = []
        self.duplicate_event_keys: list[tuple[str, int]] = []
        self._keys: set[tuple[str, int]] = set()

    def clear(self) -> None:
        self.events.clear()
        self.duplicate_event_keys.clear()
        self._keys.clear()

    def append(self, event: _GmoEvent) -> None:
        key = (event.render_product, event.timestamp_ns)
        if key in self._keys:
            self.duplicate_event_keys.append(key)
            return
        self._keys.add(key)
        self.events.append(event)


_SINK = _EventSink()
_WRITER_REGISTERED = False


class RtxAcousticAdapter:
    """Collect acoustic GMO only from event-driven Replicator writer callbacks."""

    candidate_id = "nvidia_rtx_acoustic"
    candidate_version = "3.0.0"

    def __init__(
        self,
        *,
        simulation_app: Any,
        runtime: dict[str, str],
        motion_bvh_enabled: bool,
    ) -> None:
        self._simulation_app = simulation_app
        self._runtime = runtime
        self._motion_bvh_enabled = motion_bvh_enabled
        self._sensors: list[Any] = []
        self._timeline: Any = None
        self._parse_gmo: Any = None
        self._last_classification: GmoClassification | None = None

    def _register_writer(self) -> None:
        global _WRITER_REGISTERED
        if _WRITER_REGISTERED:
            return
        import omni.replicator.core as rep
        from isaacsim.sensors.experimental.rtx import parse_generic_model_output_data
        from omni.replicator.core import Writer

        self._parse_gmo = parse_generic_model_output_data

        class R92AcousticWriter(Writer):
            def __init__(self) -> None:
                self.version = "1.0.0"
                self.data_structure = "renderProduct"
                self.annotators = [rep.annotators.get("GenericModelOutput")]

            def write_metadata(self) -> None:
                pass

            def write(self, data: dict[str, object]) -> None:
                render_products = data.get("renderProducts")
                if not isinstance(render_products, dict):
                    return
                for render_product, raw_product in render_products.items():
                    if not isinstance(raw_product, dict):
                        continue
                    raw_gmo = raw_product.get("GenericModelOutput")
                    if isinstance(raw_gmo, dict):
                        raw_gmo = raw_gmo.get("data")
                    gmo = parse_generic_model_output_data(raw_gmo)
                    if gmo.numElements <= 0:
                        continue
                    count = int(gmo.numElements)
                    signal_way_count = int(gmo.numSgws)
                    samples_per_way = int(gmo.numSamplesPerSgw)
                    if (
                        signal_way_count <= 0
                        or samples_per_way <= 0
                        or signal_way_count * samples_per_way != count
                    ):
                        continue
                    transmitter_ids, receiver_ids, channel_ids = expand_signal_way_ids(
                        gmo.x,
                        gmo.y,
                        gmo.z,
                        signal_way_count=signal_way_count,
                        samples_per_way=samples_per_way,
                    )
                    _SINK.append(
                        _GmoEvent(
                            str(render_product),
                            int(gmo.timestampNs),
                            transmitter_ids.copy(),
                            receiver_ids.copy(),
                            channel_ids.copy(),
                            np.asarray(gmo.scalar)[:count].copy(),
                        )
                    )

        rep.WriterRegistry.register(R92AcousticWriter)
        _WRITER_REGISTERED = True

    def _create_sensor(self, index: int, signal_mode: str) -> Any:
        from isaacsim.core.experimental.objects import Cube
        from isaacsim.sensors.experimental.rtx import Acoustic, AcousticSensor

        y_offset = float(index * 5)
        Cube(
            f"/World/r9_target_{index}",
            positions=np.array([3.0, y_offset, 1.2]),
            scales=np.array([0.5, 2.0, 2.0]),
        )
        attributes: dict[str, object] = {
            "omni:sensor:WpmAcoustic:centerFrequency": 40000.0,
            "omni:sensor:WpmAcoustic:signalMode": signal_mode,
            "omni:sensor:WpmAcoustic:rxGroup:g001:receiverIndices": [0, 1, 2, 3],
        }
        for mount_index, offset in enumerate(QUAD_FRONT_OFFSETS_M, start=1):
            mount_id = f"m{mount_index:03d}"
            attributes[f"omni:sensor:WpmAcoustic:sensorMount:{mount_id}:position"] = (
                offset
            )
            attributes[f"omni:sensor:WpmAcoustic:sensorMount:{mount_id}:rotation"] = (
                0.0,
                0.0,
                0.0,
            )
        acoustic = Acoustic(
            f"/World/r9_acoustic_{index}",
            aux_output_level="BASIC",
            tick_rate=50.0,
            translations=np.array([0.0, y_offset, 1.2]),
            attributes=attributes,
        )
        sensor = AcousticSensor(acoustic, annotators=[])
        sensor.attach_writer("R92AcousticWriter")
        return sensor

    def _ensure_sensors(self, count: int) -> None:
        self._register_writer()
        while len(self._sensors) < count:
            index = len(self._sensors)
            mode = "CHIRP" if index % 2 == 0 else "AM"
            self._sensors.append(self._create_sensor(index, mode))
        if self._timeline is None:
            import omni.timeline

            self._timeline = omni.timeline.get_timeline_interface()
            self._timeline.play()

    def _capture(self, frames: int) -> tuple[_GmoEvent, ...]:
        _SINK.clear()
        for _ in range(frames):
            self._simulation_app.update()
        return tuple(_SINK.events)

    def probe_runtime(self) -> RuntimeProbe:
        try:
            self._ensure_sensors(2)
            events = self._capture(20)
        except (ImportError, RuntimeError) as error:
            return RuntimeProbe(
                available=False,
                provider_version=self.candidate_version,
                runtime=self._runtime,
                capabilities={},
                details={"motion_bvh_enabled": self._motion_bvh_enabled},
                external_blocker=str(error),
            )
        if not events:
            return RuntimeProbe(
                available=True,
                provider_version=self.candidate_version,
                runtime=self._runtime,
                capabilities={
                    "active_signal_ways": False,
                    "passive_file_or_generated_content": False,
                    "raw_phase_coherent_microphones": False,
                },
                details={
                    "motion_bvh_enabled": self._motion_bvh_enabled,
                    "writer_callback_events": 0,
                },
            )
        event = events[-1]
        classification = classify_acoustic_gmo(
            event.transmitter_ids, event.receiver_ids, event.channel_ids
        )
        self._last_classification = classification
        return RuntimeProbe(
            available=True,
            provider_version=self.candidate_version,
            runtime=self._runtime,
            capabilities={
                "active_signal_ways": bool(classification.signal_ways),
                "passive_file_or_generated_content": False,
                "raw_phase_coherent_microphones": False,
            },
            details={
                "duplicate_callback_events": len(_SINK.duplicate_event_keys),
                "motion_bvh_enabled": self._motion_bvh_enabled,
                "sample_count": int(event.amplitudes.size),
                "semantic": classification.semantic,
                "signal_modes": ["CHIRP", "AM"],
                "signal_ways": [
                    {
                        "channel_id": way.channel_id,
                        "receiver_id": way.receiver_id,
                        "sample_count": way.sample_count,
                        "transmitter_id": way.transmitter_id,
                    }
                    for way in classification.signal_ways
                ],
                "writer_callback_events": len(events),
            },
        )

    def run_fixture(
        self, fixture: FixtureSpec, *, repetition: int, diagnostics: bool = False
    ) -> FixtureRun:
        self._ensure_sensors(2)
        start = time.perf_counter_ns()
        events = self._capture(2)
        complete_ms = (time.perf_counter_ns() - start) / 1e6
        measurements: dict[str, object] = {
            "complete_update_ms": complete_ms,
            "diagnostics_requested": diagnostics,
            "duplicate_callback_events": len(_SINK.duplicate_event_keys),
            "passive_input_accepted": False,
            "writer_callback_events": len(events),
        }
        if events:
            event = events[-1]
            classification = classify_acoustic_gmo(
                event.transmitter_ids, event.receiver_ids, event.channel_ids
            )
            self._last_classification = classification
            measurements.update(
                {
                    "active_sample_count": int(event.amplitudes.size),
                    "semantic": classification.semantic,
                    "signal_way_count": len(classification.signal_ways),
                }
            )
        return FixtureRun(
            fixture.fixture_id,
            repetition,
            None,
            measurements,
            compatible=False,
            incompatibility=(
                "CHIRP/AM GMO contains active transmitter-receiver signal ways, "
                "not passive raw microphone PCM."
            ),
        )

    def run_performance(
        self, *, environment_count: int, diagnostics: bool
    ) -> PerformanceRun:
        if environment_count not in (1, 4):
            raise ValueError("environment_count must be one or four.")
        self._ensure_sensors(environment_count)
        for _ in range(20):
            self._simulation_app.update()
        timings: list[float] = []
        for _ in range(200):
            start = time.perf_counter_ns()
            self._simulation_app.update()
            timings.append((time.perf_counter_ns() - start) / 1e6)
        peak_memory_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        return PerformanceRun(
            environment_count,
            diagnostics,
            20,
            200,
            tuple(timings),
            peak_memory_mib,
        )

    def captured_arrays(self) -> dict[str, np.ndarray]:
        if not _SINK.events:
            return {
                "gmo_amplitudes": np.empty(0, dtype=np.float32),
                "gmo_channel_ids": np.empty(0, dtype=np.int32),
                "gmo_receiver_ids": np.empty(0, dtype=np.int32),
                "gmo_transmitter_ids": np.empty(0, dtype=np.int32),
            }
        event = _SINK.events[-1]
        return {
            "gmo_amplitudes": event.amplitudes,
            "gmo_channel_ids": event.channel_ids,
            "gmo_receiver_ids": event.receiver_ids,
            "gmo_transmitter_ids": event.transmitter_ids,
        }

    def close(self) -> None:
        if self._timeline is not None:
            self._timeline.stop()
        self._sensors.clear()
