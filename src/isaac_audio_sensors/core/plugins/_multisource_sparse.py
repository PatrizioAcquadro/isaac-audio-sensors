"""WPE + group-sparse covariance fitting; optional mixture-only computation.

Pejoski and Kafedziski, Telfor Journal 2014, equation (9), solved with ADMM.
Adaptations: geometry-derived 3D atoms, fitted white/diffuse noise powers,
frequency normalization/thinning, finite iterations and angular event rejection.
"""

from functools import lru_cache

import numpy as np
from scipy.spatial import cKDTree

from isaac_audio_sensors.core.plugins.adapters import _validate_doa_inputs
from isaac_audio_sensors.core.plugins.pyroomacoustics import _stft


def fit_groups(dictionary, observed, penalty, *, rho=1.0, iterations=100):
    """Nonnegative group Lasso; the final two columns are unpenalized noise."""
    dictionary = np.asarray(dictionary, dtype=np.float32)
    observed = np.asarray(observed, dtype=np.float32)
    gram = dictionary @ dictionary.transpose(0, 2, 1)
    inverse = np.linalg.inv(gram + rho * np.eye(gram.shape[-1], dtype=np.float32))
    correction = dictionary.transpose(0, 2, 1) @ inverse
    z = np.zeros((len(dictionary), dictionary.shape[-1]), dtype=np.float32)
    dual = np.zeros_like(z)
    converged = False
    for iteration in range(iterations):
        previous = z
        value = z - dual
        residual = observed - (dictionary @ value[..., None])[..., 0]
        fitted = value + (correction @ residual[..., None])[..., 0]
        z = np.maximum(fitted + dual, 0)
        norms = np.linalg.norm(z[:, :-2], axis=0)
        z[:, :-2] *= np.maximum(1 - penalty / rho / np.maximum(norms, 1e-20), 0)
        dual += fitted - z
        primal_error = np.linalg.norm(fitted - z)
        change = np.linalg.norm(z - previous)
        tolerance = 1e-5 * max(np.linalg.norm(z), 1e-20)
        if iteration > 20 and max(primal_error, rho * change) < tolerance:
            converged = True
            break
    return z, dict(
        solver_iterations=iteration + 1,
        solver_converged=converged,
        solver_primal_residual=float(primal_error),
        solver_dual_residual=float(rho * change),
    )


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


class GroupSparseCovariance:
    def __init__(self, threshold=0.025, regularization=0.03, energy_floor=0.0001):
        self.threshold = threshold
        self.nfft, self.hop = 1024, 128
        self.smoothing_deg = 10
        self.sphere_points = 642
        self.cache = {}
        self.regularization = regularization
        self.energy_floor = energy_floor

    def prepare(self, samples, positions, sample_rate):
        samples, positions = _validate_doa_inputs(samples, positions, sample_rate)
        rank = np.linalg.matrix_rank(positions - positions[0])
        if len(positions) < 3 or rank < 2:
            raise ValueError("Multisource localization requires non-collinear geometry")
        if rank == 2 and not np.allclose(positions[:, 2], positions[0, 2], atol=1e-9):
            raise ValueError("Planar localization requires array-local XY geometry")
        key = (positions.tobytes(), sample_rate)
        if key not in self.cache:
            three_d = rank == 3
            if three_d:
                from pyroomacoustics.doa import GridSphere

                vectors = GridSphere(n_points=self.sphere_points).cartesian.T
            else:
                azimuth = np.radians(np.arange(0, 360, 5))
                vectors = np.column_stack(
                    [np.cos(azimuth), np.sin(azimuth), np.zeros_like(azimuth)]
                )
            frequencies = np.fft.rfftfreq(self.nfft, 1 / sample_rate)
            bins = np.flatnonzero((frequencies >= 300) & (frequencies <= 6000))
            near = cKDTree(vectors).query_ball_point(
                vectors, 2 * np.sin(np.radians(self.smoothing_deg) / 2)
            )
            self.cache[key] = vectors, bins, near
        data = self.cache[key]
        return _stft(samples, self.nfft, self.hop)[:, data[1]], data

    def localize(self, samples, positions, sample_rate):
        x, (vectors, bins, near) = self.prepare(samples, positions, sample_rate)
        microphones, _, snapshots = x.shape
        power = np.mean(np.abs(x) ** 2, axis=(0, 2))
        active = np.flatnonzero(power > max(power.max() * self.energy_floor, 1e-20))
        if not len(active):
            return self.events(vectors, np.zeros(len(vectors)), near, {})
        active = active[
            np.unique(np.linspace(0, len(active) - 1, min(len(active), 48)).astype(int))
        ]
        x = x[:, active] / np.sqrt(power[active])[None, :, None]
        frequencies = np.fft.rfftfreq(self.nfft, 1 / sample_rate)[bins][active]
        steering = np.exp(
            2j
            * np.pi
            * frequencies[:, None, None]
            * (positions @ vectors.T)[None]
            / 343
        )
        covariance = x.transpose(1, 0, 2) @ x.transpose(1, 2, 0).conj() / snapshots
        atoms = np.einsum("fmg,fng->fmng", steering, steering.conj())
        distances = np.linalg.norm(positions[:, None] - positions[None, :], axis=-1)
        noise = np.stack(
            [
                np.broadcast_to(np.eye(microphones), covariance.shape),
                np.sinc(2 * frequencies[:, None, None] * distances / 343),
            ],
            axis=-1,
        )
        atoms = np.concatenate([atoms, noise], axis=-1)
        atoms = atoms.reshape(len(frequencies), microphones**2, -1) / microphones
        covariance = covariance.reshape(len(frequencies), microphones**2) / microphones
        dictionary = np.concatenate([atoms.real, atoms.imag], axis=1)
        observed = np.concatenate([covariance.real, covariance.imag], axis=1)
        coefficients, diagnostic = fit_groups(
            dictionary, observed, self.regularization * np.sqrt(len(frequencies))
        )
        diagnostic["frequency_bins"] = len(frequencies)
        return self.events(vectors, coefficients[:, :-2].mean(axis=0), near, diagnostic)

    def events(self, vectors, histogram, near, diagnostics):
        smooth = np.array([(histogram[n] - histogram.mean()).sum() for n in near])
        found, strengths = select_peaks(vectors, smooth, self.threshold)
        # A centroid avoids quantization without adding another DOA estimator.
        for i, v in enumerate(found):
            selected = vectors @ v >= np.cos(np.radians(self.smoothing_deg))
            center = histogram[selected] @ vectors[selected]
            found[i] = center / max(np.linalg.norm(center), 1e-20)
        diagnostic = dict(
            status="events" if len(found) else "no_events",
            scores=strengths.tolist(),
            **diagnostics,
        )
        # Refinement can bring formerly distinct grid peaks into the same lobe.
        selected = []
        for index in np.argsort(-np.array(diagnostic["scores"])):
            if all(found[index] @ found[j] < np.cos(np.radians(30)) for j in selected):
                selected.append(index)
        diagnostic["scores"] = [diagnostic["scores"][i] for i in selected]
        return found[selected], diagnostic


class WpeSparseCovariance:
    """Fit current supplied past audio without accumulating overlapping windows."""

    def __init__(self, threshold=0.025, taps=6, regularization=0.03):
        self.taps = taps
        self.spatial = GroupSparseCovariance(threshold, regularization)

    def localize(self, samples, positions, sample_rate):
        from nara_wpe.wpe import wpe_v7
        from scipy.signal import istft, stft

        _, _, spectrum = stft(
            samples,
            fs=sample_rate,
            nperseg=256,
            noverlap=192,
            boundary="zeros",
            padded=True,
        )
        spectrum = wpe_v7(
            spectrum.transpose(1, 0, 2),
            taps=self.taps,
            delay=2,
            iterations=3,
        ).transpose(1, 0, 2)
        _, processed = istft(
            spectrum,
            fs=sample_rate,
            nperseg=256,
            noverlap=192,
            boundary=True,
        )
        processed = np.ascontiguousarray(processed[:, : samples.shape[-1]][:, -12000:])
        if not np.isfinite(processed).all():
            raise ValueError("Non-finite dereverberation output")
        return self.spatial.localize(processed, positions, sample_rate)
