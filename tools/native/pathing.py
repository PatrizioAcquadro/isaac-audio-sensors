"""Experimental rendering of selected Steam routes on an emission sample clock.

This consumes steam_paths.h ABI 1. It does not discover/bake probes, establish
coverage, or qualify moving geometry. Callers own those admission boundaries.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass

import numpy as np

from isaac_audio_sensors.isaac.acoustic_scene._steam_audio import audio_buffer
from isaac_audio_sensors.isaac.acoustic_scene._steam_audio_types import (
    _AudioSettings,
    _PathEffectParams,
)
from isaac_audio_sensors.isaac.acoustic_scene.steam import Handle


@dataclass(frozen=True)
class Route:
    """One interpolation contribution; coordinates stay in Steam's metre frame."""

    probes: tuple[int, ...]
    points: np.ndarray
    length_m: float
    weight: float
    eq: tuple[float, float, float]


_CALLBACK = C.CFUNCTYPE(
    None,
    C.c_int,
    C.POINTER(C.c_int),
    C.POINTER(C.c_float),
    C.c_float,
    C.c_float,
    C.POINTER(C.c_float),
    Handle,
)


def _require_abi(lib):
    try:
        lib.ias_path_abi.argtypes = []
        lib.ias_path_abi.restype = C.c_int
        version = lib.ias_path_abi()
    except AttributeError as exc:
        raise RuntimeError("Steam selected-route extension is unavailable.") from exc
    if version != 1:
        raise RuntimeError("Unsupported Steam selected-route ABI.")


def capture(lib, simulate):
    """Copy selected contributions synchronously, unregister even on failure.

    Not reentrant: the caller must serialize captures on this thread. An empty
    result means no exported route; it does not certify complete probe coverage.
    """
    _require_abi(lib)
    lib.ias_path_capture.argtypes = [Handle, Handle]
    lib.ias_path_capture.restype = None
    routes = []

    @_CALLBACK
    def receive(count, ids, xyz, length, weight, eq, _user):
        points = np.ctypeslib.as_array(xyz, shape=(count * 3,)).copy().reshape(-1, 3)
        routes.append(Route(tuple(ids[:count]), points, length, weight, tuple(eq[:3])))

    lib.ias_path_capture(C.cast(receive, Handle), None)
    try:
        simulate()
    finally:
        lib.ias_path_capture(None, None)
    for route in routes:
        if (
            len(route.points) < 3
            or not np.isfinite(route.points).all()
            or not np.isfinite((route.length_m, route.weight, *route.eq)).all()
            or route.length_m <= 0
            or route.weight < 0
            or min(route.eq) < 0
            or abs(
                np.linalg.norm(np.diff(route.points, axis=0), axis=1).sum()
                - route.length_m
            )
            > max(1e-5, 1e-5 * route.length_m)
        ):
            raise RuntimeError("Invalid selected Steam route.")
    return routes


class _SpeakerLayout(C.Structure):
    _fields_ = [("type", C.c_int), ("count", C.c_int32), ("speakers", Handle)]


class _PathSettings(C.Structure):
    _fields_ = [
        ("order", C.c_int32),
        ("spatialize", C.c_int),
        ("layout", _SpeakerLayout),
        ("hrtf", Handle),
    ]


class RouteFilter:
    """Native per-route deviation EQ, with one physical delay and one weight."""

    def __init__(self, lib, context, rate=16000, frame_samples=128):
        _require_abi(lib)
        if (
            type(rate) is not int
            or rate <= 0
            or type(frame_samples) is not int
            or frame_samples <= 0
            or frame_samples & (frame_samples - 1)
        ):
            raise ValueError("Positive rate and power-of-two native frame required.")
        self.lib, self.rate, self.frame = lib, rate, frame_samples
        self.native_rate = max(48000, rate)
        self.handle = Handle()
        p = C.POINTER
        lib.iplPathEffectCreate.argtypes = [
            Handle,
            p(_AudioSettings),
            p(_PathSettings),
            p(Handle),
        ]
        lib.iplPathEffectCreate.restype = C.c_int
        lib.iplPathEffectReset.argtypes = [Handle]
        lib.iplPathEffectReset.restype = None
        lib.iplPathEffectRelease.argtypes = [p(Handle)]
        lib.iplPathEffectRelease.restype = None
        from isaac_audio_sensors.isaac.acoustic_scene._steam_audio_types import (
            _AudioBuffer,
        )

        lib.iplPathEffectApply.argtypes = [
            Handle,
            p(_PathEffectParams),
            p(_AudioBuffer),
            p(_AudioBuffer),
        ]
        lib.iplPathEffectApply.restype = C.c_int
        result = lib.iplPathEffectCreate(
            context,
            C.byref(_AudioSettings(self.native_rate, self.frame)),
            C.byref(_PathSettings()),
            C.byref(self.handle),
        )
        if result:
            raise RuntimeError(f"Native path filter creation failed ({result}).")

    def close(self):
        if self.handle:
            self.lib.iplPathEffectRelease(C.byref(self.handle))

    def impulse(self, route, *, gain=1.0, speed=343.0, max_delay_s=1.0):
        """gain contains source/microphone directivity, without distance or weight.

        Pressure convention matches Geometry: 1/(4*pi*r). Native probe deviation
        EQ is an approximation to bending loss, not a calibrated diffraction law.
        """
        import math

        import pyroomacoustics as pra
        from scipy.signal import fftconvolve, resample_poly

        if not self.handle:
            raise RuntimeError("Native path filter is closed.")
        if not np.isfinite((gain, speed, max_delay_s)).all() or speed <= 0:
            raise ValueError("Finite gain and positive speed/horizon required.")
        delay = route.length_m / speed
        if not math.isfinite(delay) or not 0 < delay <= max_delay_s:
            raise ValueError("Selected route exceeds its physical delay horizon.")
        sh = (C.c_float * 1)(1.0)
        params = _PathEffectParams()
        params.eq_coeffs[:] = route.eq
        params.sh_coeffs = sh
        self.lib.iplPathEffectReset(self.handle)
        emission = np.zeros(self.frame, np.float32)

        def render():
            result = np.zeros(self.frame, np.float32)
            inp, keep = audio_buffer(emission)
            out, out_keep = audio_buffer(result)
            self.lib.iplPathEffectApply(
                self.handle, C.byref(params), C.byref(inp), C.byref(out)
            )
            return result

        render()
        render()  # Settle native parameter ramps before measuring the filter.
        emission[0] = 1
        response = [render()]
        emission[0] = 0
        for _ in range(math.ceil(0.2 * self.native_rate / self.frame)):
            response.append(render())
        response = np.concatenate(response)
        if np.max(abs(response[-self.frame :])) > max(
            1e-9, 1e-6 * np.max(abs(response))
        ):
            raise RuntimeError("Native path filter exceeds its settling horizon.")
        if self.native_rate != self.rate:
            divisor = math.gcd(self.rate, self.native_rate)
            response = (
                resample_poly(
                    response, self.rate // divisor, self.native_rate // divisor
                )
                * self.native_rate
                / self.rate
            )
        sample = delay * self.rate
        integer = math.floor(sample)
        kernel = np.zeros((1, 81), np.float32)
        pra.libroom.fractional_delay(
            kernel, np.array([sample - integer], np.float32), 20, 1
        )
        response = np.pad(fftconvolve(response, kernel[0]), (integer, 0))[40:]
        return response * (route.weight * gain / (4 * math.pi * route.length_m))


class EmissionConvolution:
    """Overlap-add native responses without retiming already emitted samples.

    Responses describe the geometry at emission. Updating them affects only new
    input; existing arrivals drain. This is exact for stationary paths. Motion
    between updates and later interception by a moving obstacle are NOT solved.
    """

    def __init__(self, microphones, horizon_samples):
        if microphones <= 0 or horizon_samples <= 0:
            raise ValueError("Positive channel count and arrival horizon required.")
        self.pending = np.zeros((microphones, horizon_samples), np.float32)

    def reset(self):
        self.pending.fill(0)

    def process(self, emission, responses):
        from scipy.signal import fftconvolve

        values = np.asarray(emission, np.float32)
        if values.ndim != 1 or not np.isfinite(values).all():
            raise ValueError("Emission must be a finite mono signal.")
        if len(responses) != len(self.pending):
            raise ValueError("Response microphone count changed.")
        length = max(map(len, responses))
        if length > self.pending.shape[1]:
            raise ValueError("Response exceeds the arrival horizon.")
        if not len(values):
            return np.zeros((len(responses), 0), np.float32)
        impulse = np.array([np.pad(r, (0, length - len(r))) for r in responses])
        future = fftconvolve(values[None], impulse, axes=-1).astype(np.float32)
        size = max(future.shape[1], self.pending.shape[1] + len(values))
        future = np.pad(future, ((0, 0), (0, size - future.shape[1])))
        future[:, : self.pending.shape[1]] += self.pending
        output = future[:, : len(values)].copy()
        self.pending[:] = future[:, len(values) : len(values) + self.pending.shape[1]]
        return output
