"""Isolated candidates; no scene or evaluator input crosses this boundary."""

import re
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
from scipy.spatial import cKDTree

from isaac_audio_sensors.core.plugins.pyroomacoustics import _stft

ROOT = Path(__file__).resolve().parents[3] / "build/qualification/doa/04_4"


def directions(three_d, step=5):
    az = np.arange(0, 360, step)
    if three_d:
        az, el = np.meshgrid(az, np.arange(-85, 90, step))
        az, el = az.ravel(), el.ravel()
        az = np.r_[az, 0, 0]
        el = np.r_[el, -90, 90]
    else:
        el = np.zeros_like(az)
    a, e = np.radians(az), np.radians(el)
    return np.column_stack([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])


@lru_cache(maxsize=12)
def neighborhoods(data, shape):
    vectors = np.frombuffer(data, dtype=np.float64).reshape(shape)
    near = cKDTree(vectors).query_ball_point(vectors, 2 * np.sin(np.radians(8) / 2))
    return np.concatenate(near), np.r_[0, np.cumsum([len(n) for n in near])][:-1]


def select_peaks(vectors, scores, threshold, separation=20):
    vectors = np.asarray(vectors, dtype=np.float64)
    indices, offsets = neighborhoods(vectors.tobytes(), vectors.shape)
    maxima = np.maximum.reduceat(scores[indices], offsets)
    peaks = np.flatnonzero((scores >= threshold) & (scores >= maxima)).tolist()
    peaks.sort(key=lambda i: (-scores[i], i))
    selected = []
    for i in peaks:
        if all(
            vectors[i] @ vectors[j] < np.cos(np.radians(separation)) for j in selected
        ):
            selected.append(i)
    return vectors[selected], scores[selected]


class PyroomCandidate:
    def __init__(self, method, threshold=0.15, nfft=512, hop=128, normalized=False):
        self.normalized = normalized
        self.method, self.threshold, self.nfft, self.hop = method, threshold, nfft, hop
        self.cache = {}

    def localize(self, samples, positions, sample_rate):
        if np.max(np.sqrt(np.mean(samples**2, axis=1))) < 1e-5:
            return np.empty((0, 3)), {"status": "no_events"}
        x = _stft(samples, self.nfft, self.hop)
        three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
        freqs = np.fft.rfftfreq(self.nfft, 1 / sample_rate)
        bins = np.flatnonzero((freqs >= 300) & (freqs <= 6000))
        energy = np.mean(np.abs(x[:, bins]) ** 2, axis=(0, 2))
        bins = bins[energy > 0.005 * energy.max()]
        k = 1
        if self.method == "MUSIC":
            z = x[:, bins].transpose(1, 0, 2)
            eigen = np.maximum(
                np.linalg.eigvalsh(z @ z.conj().transpose(0, 2, 1) / z.shape[-1]), 1e-20
            )
            n, m = z.shape[-1], z.shape[1]
            mdl = []
            for order in range(m):
                noise = eigen[:, : m - order]
                mdl.append(
                    n
                    * (m - order)
                    * (np.log(noise.mean(axis=1)) - np.log(noise).mean(axis=1))
                    + 0.5 * order * (2 * m - order) * np.log(n)
                )
            counts = np.argmin(mdl, axis=0)
            k = int(np.bincount(counts, minlength=m).argmax())
            if k == 0:
                return np.empty((0, 3)), {"status": "no_events", "mdl_count": 0}
        key = (positions.tobytes(), sample_rate, k)
        if key not in self.cache:
            kwargs = dict(
                dim=3 if three_d else 2,
                num_src=k,
                azimuth=np.radians(np.arange(0, 360, 5)),
            )
            if three_d:
                kwargs["colatitude"] = np.radians(np.arange(0, 181, 5))
            self.cache[key] = getattr(pra.doa, self.method)(
                positions.T,
                sample_rate,
                self.nfft,
                frequency_normalization=self.normalized,
                **kwargs,
            )
        doa = self.cache[key]
        if not doa.mode_vec.precompute:
            doa.mode_vec = pra.doa.doa.ModeVector(
                positions.T, sample_rate, self.nfft, 343, doa.grid, precompute=True
            )
        doa.locate_sources(x, freq_bins=bins)
        grid = np.asarray(doa.grid.values)
        if self.method == "SRP":
            m = len(positions)
            pairs = m * (m - 1) / 2
            score = (grid - m / pairs) / (m * m / pairs - m / pairs)
        else:
            score = (grid - np.median(grid)) / max(grid.max() - np.median(grid), 1e-20)
        found, strength = select_peaks(doa.grid.cartesian.T, score, self.threshold)
        if self.method == "MUSIC":
            found, strength = found[:k], strength[:k]
        return found, {
            "status": "events" if len(found) else "abstained",
            "scores": strength.tolist(),
            "mdl_count": k if self.method == "MUSIC" else None,
        }


class OdasCandidate:
    def __init__(self, threshold=0.15):
        self.threshold = threshold
        self.template = (
            ROOT / "vendor/odas/config/odaslive/respeaker_4_mic_array.cfg"
        ).read_text()
        import ctypes

        self.native = ctypes.CDLL(str(ROOT / "native_ssl.so"))
        self.native.ssl_create.argtypes = [ctypes.c_char_p]
        self.native.ssl_create.restype = ctypes.c_void_p
        self.native.ssl_process.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.native.ssl_destroy.argtypes = [ctypes.c_void_p]
        self.handles = {}

    def close(self):
        for handle in self.handles.values():
            self.native.ssl_destroy(handle)
        self.handles.clear()

    def localize(self, samples, positions, sample_rate):
        if sample_rate != 16000:
            raise ValueError("ODAS trial currently requires 16 kHz")
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            cfg = folder / "input.cfg"
            text = re.sub(r"#.*", "", self.template)
            text = re.sub(r"nChannels = 4;", f"nChannels = {len(positions)};", text)
            text = re.sub(
                r"map: \(.*?\);",
                f"map: ({', '.join(str(i + 1) for i in range(len(positions)))});",
                text,
            )
            microphones = []
            for p in positions:
                microphones.append(
                    "{ mu = (" + ",".join(str(float(v)) for v in p) + "); "
                    "sigma2 = (0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0); "
                    "direction = (0.0,0.0,1.0); angle = (180.0,180.0); }"
                )
            text = re.sub(
                r"mics = \(.*?\);\s*spatialfilters",
                "mics = (" + ",\n".join(microphones) + ");\nspatialfilters",
                text,
                flags=re.S,
            )
            text = re.sub(
                r"spatialfilters = \(.*?nThetas",
                "spatialfilters = ();\nnThetas",
                text,
                flags=re.S,
            )
            cfg.write_text(text)
            start = time.perf_counter()
            key = positions.tobytes()
            if key not in self.handles:
                self.handles[key] = self.native.ssl_create(str(cfg).encode())
            padded = np.ascontiguousarray(
                np.pad(samples, ((0, 0), ((-samples.shape[1]) % 128, 0))),
                dtype=np.float32,
            )
            pots = np.empty((padded.shape[1] // 128, 4, 4), dtype=np.float32)
            self.native.ssl_process(
                self.handles[key], padded.ctypes.data, padded.shape[1], pots.ctypes.data
            )
            elapsed = time.perf_counter() - start
            # Pool potential powers over the causal block.
            three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
            vectors = directions(three_d)
            powers = np.zeros(len(vectors))
            # Fixed spatial support; no track identities.
            for frame in pots[2:]:
                frame_power = np.zeros(len(vectors))
                for pot in frame:
                    d = pot[:3].astype(float)
                    if not three_d:
                        d[2] = 0
                    if np.linalg.norm(d) < 1e-10:
                        continue
                    d /= np.linalg.norm(d)
                    near = (vectors @ d) >= np.cos(np.radians(12))
                    frame_power[near] = np.maximum(frame_power[near], float(pot[3]))
                powers += frame_power
            powers /= max(1, len(pots) - 2)
            found, scores = select_peaks(vectors, powers, self.threshold, 25)
            return found, {
                "status": "events" if len(found) else "abstained",
                "scores": scores.tolist(),
                "native_wall_ms": elapsed * 1000,
                "native_hops": len(pots),
            }


class CovarianceCandidate:
    """Greedy direction selection with per-bin nonnegative covariance refits."""

    def __init__(self, threshold=0.1):
        self.threshold = threshold
        self.cache = {}

    def localize(self, samples, positions, sample_rate):
        from scipy.optimize import nnls

        x = _stft(samples, 512, 128)
        f = np.fft.rfftfreq(512, 1 / sample_rate)
        bins = np.flatnonzero((f >= 300) & (f <= 6000))
        x = x[:, bins, :]
        power = np.mean(np.abs(x) ** 2, axis=(0, 2))
        active = power > 0.005 * max(power.max(), 1e-20)
        if active.sum() < 4:
            return np.empty((0, 3)), {"status": "insufficient_spectrum"}
        left, right = np.triu_indices(len(positions), 1)
        y = np.mean(x[left] * x[right].conj(), axis=2).T / np.maximum(
            power[:, None], 1e-20
        )
        y[~active] = 0
        three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
        key = (positions.tobytes(), sample_rate)
        if key not in self.cache:
            vectors = directions(three_d)
            delay = (positions[left] - positions[right]) @ vectors.T / 343
            atoms = np.exp(2j * np.pi * f[bins, None, None] * delay[None])
            real = np.ascontiguousarray(atoms.real.reshape(-1, len(vectors)))
            imag = np.ascontiguousarray(atoms.imag.reshape(-1, len(vectors)))
            self.cache[key] = (vectors, atoms, real, imag)
        vectors, atoms, real, imag = self.cache[key]
        residual = y.copy()
        selected = []
        strengths = []
        for _ in range(len(positions) - 1):
            scores = (
                real.T @ residual.real.ravel() + imag.T @ residual.imag.ravel()
            ) / max(1, active.sum() * len(left))
            for old in selected:
                scores[vectors @ vectors[old] > np.cos(np.radians(20))] = -np.inf
            best = int(np.argmax(scores))
            if scores[best] < self.threshold:
                break
            selected.append(best)
            strengths.append(float(scores[best]))
            coefficients = np.zeros((len(bins), len(selected)))

            def refit(coefficients=coefficients):
                for fi in np.flatnonzero(active):
                    a = atoms[fi][:, selected]
                    b = y[fi]
                    coeff, _ = nnls(
                        np.concatenate((a.real, a.imag)), np.r_[b.real, b.imag]
                    )
                    coefficients[fi] = coeff
                    residual[fi] = b - a @ coeff

            refit()
            if len(selected) > 1:
                for _sweep in range(2):
                    for source in range(len(selected)):
                        old = selected[source]
                        contribution = atoms[:, :, old] * coefficients[:, source, None]
                        target = (residual + contribution) * coefficients[
                            :, source, None
                        ]
                        merit = (
                            real.T @ target.real.ravel() + imag.T @ target.imag.ravel()
                        )
                        allowed = vectors @ vectors[old] >= np.cos(np.radians(20))
                        for j, other in enumerate(selected):
                            if j != source:
                                allowed &= vectors @ vectors[other] < np.cos(
                                    np.radians(15)
                                )
                        merit[~allowed] = -np.inf
                        selected[source] = int(np.argmax(merit))
                        refit()
        return vectors[selected], {
            "status": "events" if selected else "abstained",
            "scores": strengths,
        }
