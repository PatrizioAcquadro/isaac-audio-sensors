"""Shared MUSIC computation; imported only by the optional localizer/tools."""

from functools import lru_cache

import numpy as np
import pyroomacoustics as pra
from scipy.spatial import cKDTree

from isaac_audio_sensors.core.plugins.adapters import _validate_doa_inputs
from isaac_audio_sensors.core.plugins.pyroomacoustics import _stft


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


class _FrequencyOrderMusic:
    """Fuse normalized MUSIC spectra with independently observed per-bin order."""

    def __init__(
        self,
        threshold=0.2,
        relative_loading=0.0,
        refit_threshold=None,
        refit_statistic="mean",
        refine_peaks=False,
        order_criterion="mdl",
        spectral_weighting=False,
    ):
        self.threshold, self.nfft, self.hop = threshold, 512, 128
        self.cache = {}
        self.relative_loading = relative_loading
        self.refit_threshold = refit_threshold
        self.refit_statistic = refit_statistic
        self.refine_peaks = refine_peaks
        self.order_criterion = order_criterion
        self.spectral_weighting = spectral_weighting

    def localize(self, samples, positions, sample_rate):
        samples, positions = _validate_doa_inputs(samples, positions, sample_rate)
        rank = np.linalg.matrix_rank(positions - positions[0])
        if len(positions) < 3 or rank < 2:
            raise ValueError("Multisource evaluation requires non-collinear geometry")
        if rank == 2 and not np.allclose(positions[:, 2], positions[0, 2], atol=1e-9):
            raise ValueError("Planar evaluation requires array-local XY geometry")
        x = _stft(samples, self.nfft, self.hop)
        frequencies = np.fft.rfftfreq(self.nfft, 1 / sample_rate)
        bins = np.flatnonzero((frequencies >= 300) & (frequencies <= 6000))
        energy = np.mean(np.abs(x[:, bins]) ** 2, axis=(0, 2))
        bins = bins[energy > max(1e-20, 0.005 * energy.max())]
        if not len(bins):
            return np.empty((0, 3)), {"status": "no_events", "scores": []}
        z = x[:, bins].transpose(1, 0, 2)
        eigen = np.maximum(
            np.linalg.eigvalsh(z @ z.conj().transpose(0, 2, 1) / z.shape[-1]),
            1e-20,
        )
        eigen += self.relative_loading * eigen[:, -1, None]
        n, m = z.shape[-1], z.shape[1]
        costs = []
        for order in range(m):
            noise = eigen[:, : m - order]
            costs.append(
                n
                * (m - order)
                * (np.log(noise.mean(axis=1)) - np.log(noise).mean(axis=1))
                + order
                * (2 * m - order)
                * (1 if self.order_criterion == "aic" else 0.5 * np.log(n))
            )
        counts = np.argmin(costs, axis=0)
        three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
        score = None
        vectors = None
        for k in range(1, m):
            selected_bins = bins[counts == k]
            if not len(selected_bins):
                continue
            key = (positions.tobytes(), sample_rate, k)
            if key not in self.cache:
                kwargs = {
                    "dim": 3 if three_d else 2,
                    "num_src": k,
                    "azimuth": np.radians(np.arange(0, 360, 5)),
                }
                if three_d:
                    kwargs["colatitude"] = np.radians(np.arange(0, 181, 5))
                estimator = pra.doa.MUSIC(
                    positions.T,
                    sample_rate,
                    self.nfft,
                    frequency_normalization=True,
                    **kwargs,
                )
                estimator.mode_vec = pra.doa.doa.ModeVector(
                    positions.T,
                    sample_rate,
                    self.nfft,
                    343,
                    estimator.grid,
                    precompute=True,
                )
                self.cache[key] = estimator
            estimator = self.cache[key]
            estimator.locate_sources(x, freq_bins=selected_bins)
            contrast = np.maximum(
                estimator.grid.values - np.median(estimator.grid.values), 0
            )
            normalization = (
                np.count_nonzero(counts) if self.spectral_weighting else len(bins)
            )
            contribution = contrast * len(selected_bins) / normalization
            score = contribution if score is None else score + contribution
            vectors = estimator.grid.cartesian.T
        if score is None:
            return np.empty((0, 3)), {"status": "no_events", "scores": []}
        found, strengths = select_peaks(vectors, score, self.threshold)
        if self.refit_threshold is not None and len(found):
            from scipy.optimize import nnls

            spatial_strengths = strengths.copy()
            if self.refine_peaks:
                refined = []
                for direction in found:
                    near = vectors @ direction >= np.cos(np.radians(8))
                    weights = score[near].copy()
                    if three_d:
                        weights *= np.maximum(
                            np.linalg.norm(vectors[near, :2], axis=1), 0.04
                        )
                    direction = np.sum(vectors[near] * weights[:, None], axis=0)
                    refined.append(direction / np.linalg.norm(direction))
                found = np.asarray(refined)
            left, right = np.triu_indices(m)
            observed = np.mean(x[left][:, bins] * x[right][:, bins].conj(), axis=2).T
            power = np.mean(np.abs(x[:, bins]) ** 2, axis=(0, 2))
            observed /= np.maximum(power[:, None], 1e-20)
            delay = (positions[left] - positions[right]) @ found.T / 343
            atoms = np.exp(2j * np.pi * frequencies[bins, None, None] * delay[None])
            white = np.broadcast_to(
                (left == right)[None, :, None], (len(bins), len(left), 1)
            )
            distance = np.linalg.norm(positions[left] - positions[right], axis=1)
            diffuse = np.sinc(2 * frequencies[bins, None] * distance[None] / 343)[
                :, :, None
            ]
            atoms = np.concatenate((atoms, white, diffuse), axis=2)
            coefficients = []
            for atom, target in zip(atoms, observed, strict=True):
                coeff, _ = nnls(
                    np.concatenate((atom.real, atom.imag)),
                    np.r_[target.real, target.imag],
                )
                coefficients.append(coeff)
            coefficients = np.asarray(coefficients)
            strengths = np.mean(coefficients[:, :-2], axis=0)
            if self.spectral_weighting:
                strengths = np.average(coefficients[:, :-2], axis=0, weights=power)
            if self.refit_statistic == "product":
                strengths *= spatial_strengths
            keep = strengths >= self.refit_threshold
            found, strengths = found[keep], strengths[keep]
        return found, {
            "status": "events" if len(found) else "abstained",
            "scores": strengths.tolist(),
            "frequency_order_counts": np.bincount(counts, minlength=m).tolist(),
        }
