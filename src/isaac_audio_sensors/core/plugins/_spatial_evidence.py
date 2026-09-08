"""Angular neighborhoods and mixture STFT shared by spatial evidence models."""

from functools import lru_cache

import numpy as np
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


class SpatialEvidence:
    def __init__(
        self, threshold=0.025, nfft=512, hop=128, smoothing_deg=10, sphere_points=1650
    ):
        self.threshold = threshold
        self.nfft, self.hop = nfft, hop
        self.smoothing_deg = smoothing_deg
        self.sphere_points = sphere_points
        self.cache = {}

    def prepare(self, samples, positions, sample_rate):
        samples, positions = _validate_doa_inputs(samples, positions, sample_rate)
        rank = np.linalg.matrix_rank(positions - positions[0])
        if len(positions) < 3 or rank < 2:
            raise ValueError("Multisource evaluation requires non-collinear geometry")
        if rank == 2 and not np.allclose(positions[:, 2], positions[0, 2], atol=1e-9):
            raise ValueError("Planar evaluation requires array-local XY geometry")
        key = (positions.tobytes(), sample_rate)
        if key not in self.cache:
            three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
            if three_d:
                from pyroomacoustics.doa import GridSphere

                vectors = GridSphere(n_points=self.sphere_points).cartesian.T
            else:
                azimuth = np.radians(np.arange(0, 360, 5))
                vectors = np.column_stack(
                    [np.cos(azimuth), np.sin(azimuth), np.zeros_like(azimuth)]
                )
            left, right = np.triu_indices(len(positions), 1)
            frequencies = np.fft.rfftfreq(self.nfft, 1 / sample_rate)
            bins = np.flatnonzero((frequencies >= 300) & (frequencies <= 6000))
            delay = (positions[left] - positions[right]) @ vectors.T / 343
            steering = np.exp(2j * np.pi * frequencies[bins, None, None] * delay)
            near = cKDTree(vectors).query_ball_point(
                vectors, 2 * np.sin(np.radians(self.smoothing_deg) / 2)
            )
            self.cache[key] = vectors, left, right, bins, steering, near
        data = self.cache[key]
        return _stft(samples, self.nfft, self.hop)[:, data[3]], data

    def events(self, vectors, histogram, near, diagnostics):
        smooth = np.array([(histogram[n] - histogram.mean()).sum() for n in near])
        found, strengths = select_peaks(vectors, smooth, self.threshold)
        # A centroid avoids quantization without adding another DOA estimator.
        for i, v in enumerate(found):
            selected = vectors @ v >= np.cos(np.radians(self.smoothing_deg))
            center = histogram[selected] @ vectors[selected]
            found[i] = center / max(np.linalg.norm(center), 1e-20)
        return found, dict(
            status="events" if len(found) else "no_events",
            scores=strengths.tolist(),
            **diagnostics,
        )
