"""Persistent native point receivers sharing the prepared Embree scene."""

from __future__ import annotations

import ctypes as C

import numpy as np

from ._steam_audio_types import (
    _AirAbsorptionModel,
    _AudioBuffer,
    _AudioSettings,
    _CoordinateSpace3,
    _DirectEffectParams,
    _DirectEffectSettings,
    _Directivity,
    _DistanceAttenuationModel,
    _SimulationInputs,
    _SimulationOutputs,
    _SimulationSettings,
    _SimulationSharedInputs,
    _SourceSettings,
    _Vector3,
)
from .steam import Handle


def coordinates(position):
    """Canonical metre/Z-up audio coordinates to native metre/Y-up."""
    x, y, z = position
    return _CoordinateSpace3(
        _Vector3(1, 0, 0),
        _Vector3(0, 1, 0),
        _Vector3(0, 0, -1),
        _Vector3(x, z, -y),
    )


def audio_buffer(values):
    values = np.ascontiguousarray(values, dtype=np.float32).reshape(
        -1, values.shape[-1]
    )
    pointer = C.POINTER(C.c_float)
    channels = (pointer * len(values))(*(row.ctypes.data_as(pointer) for row in values))
    return _AudioBuffer(len(values), values.shape[1], channels), (values, channels)


def bind_audio(lib):
    p = C.POINTER
    specs = {
        "iplSimulatorCreate": (C.c_int, [Handle, p(_SimulationSettings), p(Handle)]),
        "iplSimulatorRelease": (None, [p(Handle)]),
        "iplSimulatorSetScene": (None, [Handle, Handle]),
        "iplSimulatorSetSharedInputs": (
            None,
            [Handle, C.c_int, p(_SimulationSharedInputs)],
        ),
        "iplSimulatorCommit": (None, [Handle]),
        "iplSimulatorRunDirect": (None, [Handle]),
        "iplDirectEffectReset": (None, [Handle]),
        "iplSourceCreate": (C.c_int, [Handle, p(_SourceSettings), p(Handle)]),
        "iplSourceRelease": (None, [p(Handle)]),
        "iplSourceAdd": (None, [Handle, Handle]),
        "iplSourceRemove": (None, [Handle, Handle]),
        "iplSourceSetInputs": (None, [Handle, C.c_int, p(_SimulationInputs)]),
        "iplSourceGetOutputs": (None, [Handle, C.c_int, p(_SimulationOutputs)]),
    }
    for name, settings, params in (
        ("Direct", _DirectEffectSettings, _DirectEffectParams),
    ):
        specs[f"ipl{name}EffectCreate"] = (
            C.c_int,
            [Handle, p(_AudioSettings), p(settings), p(Handle)],
        )
        specs[f"ipl{name}EffectRelease"] = (None, [p(Handle)])
        specs[f"ipl{name}EffectApply"] = (
            C.c_int,
            [Handle, p(params), p(_AudioBuffer), p(_AudioBuffer)],
        )
    for name, (result, args) in specs.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args


class Receiver:
    """One physical microphone; source/effect state is never shared across mics."""

    def __init__(self, scene, rate, cfg, sources):
        if scene.closed:
            raise RuntimeError("A verified native acoustic scene is required.")
        self.scene, self.cfg, self.rate = scene, cfg, rate
        self.native_rate = max(48000, rate)
        self.lib = scene.lib
        self.simulator = Handle()
        self.sources = {}
        self.closed = False
        self.flags = 1
        bind_audio(self.lib)
        settings = _SimulationSettings(
            self.flags,
            1,
            0,
            32,
            1,
            32,
            0.1,
            0,
            max(1, len(sources)),
            1,
            16,
            16,
            self.native_rate,
            cfg.frame_samples,
            None,
            None,
            None,
        )
        try:
            scene._check(
                self.lib.iplSimulatorCreate(
                    scene.context, C.byref(settings), C.byref(self.simulator)
                )
            )
            self.lib.iplSimulatorSetScene(self.simulator, scene.scene)
            audio = _AudioSettings(self.native_rate, cfg.frame_samples)
            for source_id in sources:
                state = {
                    "source": Handle(),
                    "direct": Handle(),
                    "output": _SimulationOutputs(),
                }
                self.sources[source_id] = state
                scene._check(
                    self.lib.iplSourceCreate(
                        self.simulator,
                        C.byref(_SourceSettings(self.flags)),
                        C.byref(state["source"]),
                    )
                )
                self.lib.iplSourceAdd(state["source"], self.simulator)
                scene._check(
                    self.lib.iplDirectEffectCreate(
                        scene.context,
                        C.byref(audio),
                        C.byref(_DirectEffectSettings(1)),
                        C.byref(state["direct"]),
                    )
                )
            self.lib.iplSimulatorCommit(self.simulator)
        except Exception:
            self.close()
            raise

    def refresh(self, microphone, sources):
        if self.scene.closed or self.closed:
            raise RuntimeError("Native acoustic receiver is closed.")
        cfg = self.cfg
        shared = _SimulationSharedInputs(
            coordinates(microphone),
            1,
            1,
            0.1,
            0,
            1.0,
            None,
            None,
        )
        self.lib.iplSimulatorSetSharedInputs(
            self.simulator, self.flags, C.byref(shared)
        )
        for source in sources:
            inputs = _SimulationInputs()
            inputs.flags = self.flags
            inputs.direct_flags = 1 | 8 | 16 | (2 if cfg.air_absorption else 0)
            inputs.source = coordinates(source.position_world)
            inputs.distance_attenuation_model = _DistanceAttenuationModel(
                1, 1e-6, None, None, 0
            )
            inputs.air_absorption_model = _AirAbsorptionModel()
            inputs.directivity = _Directivity(0.0, 1.0, None, None)
            inputs.num_occlusion_samples = 1
            inputs.occlusion_radius = 0.1
            inputs.reverb_scale[:] = (1.0, 1.0, 1.0)
            inputs.num_transmission_rays = 8
            self.lib.iplSourceSetInputs(
                self.sources[source.source_id]["source"], self.flags, C.byref(inputs)
            )
        self.lib.iplSimulatorRunDirect(self.simulator)
        for state in self.sources.values():
            self.lib.iplSourceGetOutputs(
                state["source"], self.flags, C.byref(state["output"])
            )

    def render(self, source_id, emission):
        state = self.sources[source_id]
        params = state["output"].direct
        params.flags = 1 | 8 | 16 | (2 if self.cfg.air_absorption else 0)
        params.transmission_type = int(
            self.cfg.air_absorption or len(set(params.transmission)) != 1
        )
        inp, keep = audio_buffer(emission)
        direct = np.zeros(self.cfg.frame_samples, dtype=np.float32)
        out, out_keep = audio_buffer(direct)
        self.lib.iplDirectEffectApply(
            state["direct"], C.byref(params), C.byref(inp), C.byref(out)
        )
        return direct

    def impulse(self, source_id):
        self.lib.iplDirectEffectReset(self.sources[source_id]["direct"])
        zeros = np.zeros(self.cfg.frame_samples, np.float32)
        params = self.sources[source_id]["output"].direct
        if not self.cfg.air_absorption and len(set(params.transmission)) == 1:
            # Native frequency-independent direct rendering is a memoryless gain.
            emission = zeros.copy()
            emission[0] = 1.0
            return self.render(source_id, emission)[:1].copy()
        self.render(source_id, zeros)
        self.render(source_id, zeros)
        emission = zeros.copy()
        emission[0] = 1.0
        rows = [self.render(source_id, emission)]
        for _ in range(max(1, self.native_rate // self.cfg.frame_samples // 5)):
            rows.append(self.render(source_id, zeros))
        response = np.concatenate(rows)
        if np.max(abs(response[-self.cfg.frame_samples :])) > max(
            1e-9, 1e-6 * np.max(abs(response))
        ):
            raise RuntimeError("Native direct response exceeds its settling horizon.")
        if self.native_rate != self.rate:
            from math import gcd

            from scipy.signal import resample_poly

            divisor = gcd(self.rate, self.native_rate)
            # Preserve discrete impulse area when changing the filter sample grid.
            response = resample_poly(
                response, self.rate // divisor, self.native_rate // divisor
            ) * (self.native_rate / self.rate)
        return response

    def close(self):
        if self.closed:
            return
        for state in self.sources.values():
            for key, name in (
                ("direct", "DirectEffect"),
                ("source", "Source"),
            ):
                if state[key]:
                    getattr(self.lib, f"ipl{name}Release")(C.byref(state[key]))
        self.sources.clear()
        if self.simulator:
            self.lib.iplSimulatorRelease(C.byref(self.simulator))
        self.closed = True
