"""Prepared USD geometry to continuous physical microphone signals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.backends._analytic.signals import _scheduled_window_signal
from isaac_audio_sensors.core.directivity import (
    microphone_world_orientation,
    pair_directivity_gain,
)
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import MicrophoneSignalBlock

from ._convolution import ConvolutionStream
from ._nlos import NLOSScene, NLOSStream, SteamNLOSConfig
from ._specular import SpecularScene
from ._steam_audio import Receiver


@dataclass(frozen=True, slots=True)
class GeometryAcousticsConfig:
    """Explicit optional native providers for the intermediate specular domain."""

    library_path: str
    specular_library_path: str
    frame_samples: int = 128
    reflection_order: int = 3
    max_image_candidates: int = 1_000_000
    max_delay_s: float = 1.0
    transition_samples: int = 32
    air_absorption: bool = False
    diagnostics: bool = False
    nlos: SteamNLOSConfig | None = None

    def __post_init__(self):
        if self.nlos is not None and not isinstance(self.nlos, SteamNLOSConfig):
            raise TypeError("nlos must be SteamNLOSConfig or None.")
        if not self.library_path or not self.specular_library_path:
            raise ValueError(
                "Geometry requires explicit Steam and specular library paths."
            )
        for name in ("frame_samples", "max_image_candidates"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        for name in ("reflection_order", "transition_samples"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        if self.frame_samples & (self.frame_samples - 1):
            raise ValueError("frame_samples must be a power of two.")
        if not math.isfinite(self.max_delay_s) or self.max_delay_s <= 0:
            raise ValueError("max_delay_s must be finite and positive.")
        if type(self.air_absorption) is not bool or type(self.diagnostics) is not bool:
            raise TypeError("air_absorption and diagnostics must be booleans.")
        if self.air_absorption:
            raise ValueError(
                "Air absorption is not yet qualified for the hybrid specular domain."
            )


class GeometryAcoustics:
    """One acoustically isolated scene with independent receiver-clock streams."""

    backend_id = "geometry_acoustics"

    def __init__(
        self,
        *,
        acoustic_scene,
        geometry_config,
        effects=None,
        speed_of_sound_mps=343.0,
        runtime_profile="waveform_fidelity",
        window_motion=None,
    ):
        if not isinstance(geometry_config, GeometryAcousticsConfig):
            raise TypeError("geometry_config must be GeometryAcousticsConfig.")
        if not math.isfinite(speed_of_sound_mps) or speed_of_sound_mps <= 0:
            raise ValueError("speed_of_sound_mps must be finite and positive.")
        if runtime_profile != "waveform_fidelity":
            raise ValueError("Geometry requires waveform_fidelity.")
        self.session, self.config = acoustic_scene, geometry_config
        self.speed = speed_of_sound_mps
        self.effects = effects or EffectsConfig()
        self.chain = ChannelEffectsChain(self.effects)
        self.streams = {}
        self.closed = False
        self._reset_notice = False
        self.window_motion = window_motion
        self.nlos = None
        acoustic_scene.refresh()
        self._check_scene()
        if acoustic_scene.provider is None:
            acoustic_scene.verify_provider(geometry_config.library_path)
        if (
            Path(acoustic_scene.provider.library_path)
            != Path(geometry_config.library_path).resolve()
        ):
            raise ValueError(
                "Prepared scene and geometry_config select different libraries."
            )
        self.provider = acoustic_scene.provider
        if geometry_config.nlos is not None:
            self.nlos = NLOSScene(acoustic_scene, geometry_config.nlos)

    def _check_scene(self):
        if self.session.issues:
            raise ValueError(
                f"Acoustic scene preparation failed: {self.session.issues}"
            )

    @staticmethod
    def _release(stream):
        if stream.get("nlos"):
            stream["nlos"].close()
        for receiver in stream["receivers"]:
            receiver.close()
        stream["specular"].close()

    def reset(self):
        self._reset_notice = True
        for stream in self.streams.values():
            self._release(stream)
        self.streams.clear()
        if self.nlos:
            self.nlos.close()
            self.nlos = None

    def close(self):
        self.reset()
        self.closed = True

    def _response_margin(self, rate):
        if not self.effects.channel_response.enabled:
            return 1024
        delays = [
            abs(float(m.delay_s or 0))
            for m in (self.effects.channel_response.microphones or {}).values()
        ]
        delay = max(delays, default=0.0)
        if not math.isfinite(delay) or delay > self.config.max_delay_s:
            raise ValueError("Microphone response delay exceeds max_delay_s.")
        return 1024 + math.ceil(delay * rate)

    def _create(self, scene, array, signature, start):
        rate = array.sample_rate_hz
        receivers = []
        specular = None
        try:
            specular = SpecularScene(
                self.session,
                self.config.specular_library_path,
                rate,
                self.config.reflection_order,
                self.speed,
                self.config.max_image_candidates,
            )
            for _ in array.microphones:
                receivers.append(
                    Receiver(
                        self.provider,
                        rate,
                        self.config,
                        [s.source_id for s in scene.sources],
                    )
                )
        except Exception:
            for receiver in receivers:
                receiver.close()
            if specular:
                specular.close()
            raise
        nlos = None
        try:
            if self.nlos:
                nlos = NLOSStream(self.nlos, array, self.config, start, self.speed)
        except Exception:
            for receiver in receivers:
                receiver.close()
            specular.close()
            raise
        return dict(
            nlos=nlos,
            signature=signature,
            receivers=receivers,
            specular=specular,
            cursor=start,
            pose=None,
            convolvers={
                s.source_id: ConvolutionStream(
                    len(receivers),
                    math.ceil((self.config.max_delay_s + 0.3) * rate)
                    + self._response_margin(rate),
                    self.config.transition_samples,
                )
                for s in scene.sources
            },
        )

    def _responses(self, stream, scene, array, positions):
        from scipy.signal import fftconvolve

        rate = array.sample_rate_hz
        specular = stream["specular"]
        for receiver, position in zip(stream["receivers"], positions, strict=True):
            receiver.refresh(position, scene.sources)
        for source in scene.sources:
            responses = specular.impulses(
                source, array, positions, self.config.max_delay_s
            )
            for i, (mic, position, receiver) in enumerate(
                zip(array.microphones, positions, stream["receivers"], strict=True)
            ):
                distance = np.linalg.norm(np.asarray(position) - source.position_world)
                if distance <= 1e-6:
                    raise ValueError(
                        "Source and microphone positions must be distinct."
                    )
                delay = distance / self.speed
                if delay > self.config.max_delay_s:
                    raise ValueError("Direct arrival exceeds max_delay_s.")
                sample = delay * rate
                integer = math.floor(sample)
                kernel = np.zeros((1, 81), np.float32)
                specular.pra.libroom.fractional_delay(
                    kernel, np.array([sample - integer], np.float32), 20, 1
                )
                direct = fftconvolve(receiver.impulse(source.source_id), kernel[0])
                direct = np.pad(direct, (integer, 0))[40:]
                gain = pair_directivity_gain(
                    source_pattern=source.directivity,
                    microphone_pattern=mic.directivity,
                    source_position_world=source.position_world,
                    source_orientation_world_xyzw=source.orientation_world_quat,
                    microphone_position_world=position,
                    microphone_orientation_world_xyzw=microphone_world_orientation(
                        array.orientation_world_quat, mic.relative_orientation_quat
                    ),
                )
                direct *= gain / (4 * math.pi)
                length = max(len(direct), len(responses[i]))
                responses[i] = np.pad(direct, (0, length - len(direct))) + np.pad(
                    responses[i], (0, length - len(responses[i]))
                )
            if self.effects.channel_response.enabled:
                length = max(map(len, responses)) + self._response_margin(rate)
                matrix = np.array([np.pad(r, (0, length - len(r))) for r in responses])
                matrix, _ = self.chain.apply_premix(
                    matrix,
                    mic_ids=[m.mic_id for m in array.microphones],
                    sample_rate_hz=rate,
                    frame_id="geometry-response",
                    backend_id=self.backend_id,
                    runtime_profile="waveform_fidelity",
                    microphone_self_noise_db={
                        m.mic_id: m.self_noise_db for m in array.microphones
                    },
                )
                responses = list(matrix)
            stream["convolvers"][source.source_id].update(responses)

    def propagate(self, scene, array_id, time_window):
        if self.closed or self.session.closed:
            raise RuntimeError("GeometryAcoustics or its acoustic scene is closed.")
        if self.session.provider is not self.provider:
            self.reset()
            self.provider = self.session.provider
        if self.provider is None or self.provider.closed:
            raise RuntimeError("Geometry requires an active verified scene provider.")
        if scene.occlusion:
            raise ValueError("GeometryAcoustics rejects precomputed SourceOcclusion.")
        array = scene.array_by_id(array_id)
        rate = array.sample_rate_hz
        start, end = (
            round(t * rate) for t in (time_window.start_time_s, time_window.end_time_s)
        )
        if (
            start < 0
            or end <= start
            or any(
                abs(t * rate - n) > 1e-6
                for t, n in (
                    (time_window.start_time_s, start),
                    (time_window.end_time_s, end),
                )
            )
        ):
            raise ValueError("Geometry windows must use the nonnegative sample clock.")
        self.session.refresh(self.session._last_time)
        self._check_scene()
        if self.config.nlos is not None:
            if self.nlos is None:
                self.nlos = NLOSScene(self.session, self.config.nlos)
            self.nlos.refresh(start / rate)
        key = (scene.stage_id, array_id)
        signature = (rate, array.microphones, tuple(s.source_id for s in scene.sources))
        stream = self.streams.get(key)
        discontinuity = stream is None and (self._reset_notice or start > 0)
        if stream and start < stream["cursor"]:
            raise ValueError("Geometry time moved backwards without reset.")
        if (
            stream is None
            or signature != stream["signature"]
            or start != stream["cursor"]
        ):
            replacement = self._create(scene, array, signature, start)
            if stream:
                self._release(stream)
                discontinuity = True
            stream = self.streams[key] = replacement
        positions_by_id = microphone_world_positions(array)
        positions = [positions_by_id[m.mic_id] for m in array.microphones]
        pose = (
            tuple(tuple(p) for p in positions),
            None
            if array.orientation_world_quat is None
            else tuple(array.orientation_world_quat),
            tuple(
                (
                    tuple(s.position_world),
                    None
                    if s.orientation_world_quat is None
                    else tuple(s.orientation_world_quat),
                    s.directivity,
                )
                for s in scene.sources
            ),
            self.provider.builds,
            self.provider.updates,
        )
        if pose != stream["pose"]:
            self._responses(stream, scene, array, positions)
            stream["pose"] = pose
        count = end - start
        output = np.zeros((len(positions), count), np.float32)
        emissions = {}
        for source in scene.sources:
            emission = _scheduled_window_signal(
                source, time_window=time_window, sample_rate_hz=rate
            ).signal
            emission = np.pad(emission[:count], (0, max(0, count - len(emission))))
            emissions[source.source_id] = emission
            output += stream["convolvers"][source.source_id].process(emission)
        if stream["nlos"]:
            nlos_stream = stream["nlos"]
            try:
                nlos_stream.observe(scene, array, start / rate, self.window_motion)
                indirect = nlos_stream.process(scene, array, start, emissions, count)
                output += self._nlos_response(stream, array, indirect)
            except Exception:
                self._release(stream)
                del self.streams[key]
                self._reset_notice = True
                raise
            before = min(s["cursor"] / s["signature"][0] for s in self.streams.values())
            self.nlos.history.prune(before - self.config.max_delay_s - 1 / rate)
        output *= np.asarray([10 ** (m.gain_db / 20) for m in array.microphones])[
            :, None
        ]
        output, diagnostics = self.chain.apply_mixture(
            output,
            mic_ids=[m.mic_id for m in array.microphones],
            sample_rate_hz=rate,
            frame_id=f"{scene.stage_id}:{array_id}",
            backend_id=self.backend_id,
            runtime_profile="waveform_fidelity",
            nominal_window_start_sample=start,
            microphone_self_noise_db={
                m.mic_id: m.self_noise_db for m in array.microphones
            },
        )
        stream["cursor"] = end
        if self.config.diagnostics:
            diagnostics["geometry"] = dict(
                provider="steam_audio+pyroomacoustics_ism",
                domain="intermediate_specular",
                reflection_order=self.config.reflection_order,
            )
            if stream["nlos"]:
                diagnostics["geometry"].update(
                    domain="intermediate_specular+nlos",
                    nlos=dict(
                        probes=self.nlos.paths.count,
                        bakes=self.nlos.bakes,
                        coverage=stream["nlos"].states,
                    ),
                )
        return MicrophoneSignalBlock(
            samples=output,
            microphone_ids=tuple(m.mic_id for m in array.microphones),
            microphone_positions_m=tuple(
                m.relative_position_m for m in array.microphones
            ),
            array_id=array_id,
            sample_rate_hz=rate,
            time_window=time_window,
            clock_domain="simulation",
            discontinuity=discontinuity,
            channel_validity=(True,) * len(positions),
            channel_clipping=(None,) * len(positions),
            producer_id=self.backend_id,
            provenance="room_acoustics",
            diagnostics=diagnostics,
        )

    def _nlos_response(self, stream, array, samples):
        """Apply the deterministic microphone response once to the NLOS mixture."""
        if not self.effects.channel_response.enabled:
            return samples
        if "nlos_response" not in stream:
            for response in (self.effects.channel_response.microphones or {}).values():
                if (
                    response.frequency_response is not None
                    or (response.delay_s or 0) < 0
                ):
                    raise ValueError(
                        "NLOS streaming requires causal microphone response: gain, "
                        "polarity and nonnegative delay; zero-phase FIR is unqualified."
                    )
            length = self._response_margin(array.sample_rate_hz)
            impulses = np.zeros((len(array.microphones), length), np.float32)
            impulses[:, 0] = 1
            impulses, _ = self.chain.apply_premix(
                impulses,
                mic_ids=[m.mic_id for m in array.microphones],
                sample_rate_hz=array.sample_rate_hz,
                frame_id="nlos-response",
                backend_id=self.backend_id,
                runtime_profile="waveform_fidelity",
                microphone_self_noise_db={
                    m.mic_id: m.self_noise_db for m in array.microphones
                },
            )
            responses = []
            for impulse in impulses:
                convolver = ConvolutionStream(1, length, 0)
                convolver.update([impulse])
                responses.append(convolver)
            stream["nlos_response"] = responses
        return np.array(
            [
                response.process(row)[0]
                for response, row in zip(stream["nlos_response"], samples, strict=True)
            ]
        )
