"""Published direct-path features and TF-histogram alternatives, evaluation only.

DP-RTF: Li et al., JSTSP 2019, sections II–III (no tracking).
SRP histogram family: Grinstein et al., SRP review, section 5.4.
The confidence weights, arbitrary-array templates and batch CGMM fit are
explicit adaptations, not a reproduction of the authors' complete systems.
Both infer events from spatial evidence, never from a supplied source count.
"""

import numpy as np
from scipy.spatial import cKDTree

from isaac_audio_sensors.core.plugins._multisource_music import select_peaks
from isaac_audio_sensors.core.plugins.adapters import _validate_doa_inputs
from isaac_audio_sensors.core.plugins.pyroomacoustics import _stft

from .candidates import directions


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
                vectors = directions(False)
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


class WeightedHistogramSrp(SpatialEvidence):
    """Narrowband SRP votes weighted by their spatial agreement.

    No energy weighting across bins: a weak source can contribute independent
    directional votes. The exponent is a development-only confidence parameter.
    """

    def __init__(self, threshold=0.025, confidence_power=4, average_frames=3, **kwargs):
        super().__init__(threshold, **kwargs)
        self.confidence_power = confidence_power
        self.average_frames = average_frames

    def localize(self, samples, positions, sample_rate):
        x, (vectors, left, right, bins, steering, near) = self.prepare(
            samples, positions, sample_rate
        )
        cross = (x[left] * x[right].conj()).transpose(1, 2, 0)
        powers = (np.abs(x[left]) * np.abs(x[right])).transpose(1, 2, 0)
        if self.average_frames > 1:
            from scipy.ndimage import uniform_filter1d

            cross = uniform_filter1d(cross, self.average_frames, axis=1)
            powers = uniform_filter1d(powers, self.average_frames, axis=1)
        cross /= np.maximum(powers, 1e-20)
        energy = np.mean(np.abs(x) ** 2, axis=0)
        valid = energy > max(float(energy.max()) * 0.005, 1e-20)
        histogram = np.zeros(len(vectors))
        for f in range(len(bins)):
            score = (cross[f] @ steering[f].conj()).real / len(left)
            best = np.argmax(score, axis=1)
            weights = np.maximum(score[np.arange(len(best)), best], 0)
            weights = weights**self.confidence_power * valid[f]
            np.add.at(histogram, best, weights)
        histogram /= max(int(valid.sum()), 1)
        return self.events(
            vectors, histogram, near, {"valid_tf_bins": int(valid.sum())}
        )


class DirectPathRtf(SpatialEvidence):
    """Window-local CTF cross-relation RLS, consistency and sparse CGMM.

    Independently implemented from the published equations. All history is
    supplied past audio; calls retain geometry caches but no source identities.
    Stationary non-speech is not removed by a speech-only minimum-statistics VAD.
    """

    def __init__(
        self,
        threshold=0.05,
        taps=4,
        memory_frames=12,
        consistency=0.75,
        variance=0.1,
        entropy=0.1,
        iterations=60,
        joint=False,
        outlier=False,
        spectral_smoothing=0.0,
        **kwargs,
    ):
        super().__init__(threshold, nfft=256, **kwargs)
        self.taps, self.memory_frames = taps, memory_frames
        self.consistency, self.variance = consistency, variance
        self.entropy, self.iterations = entropy, iterations
        self.joint = joint
        self.outlier = outlier
        self.spectral_smoothing = spectral_smoothing

    def localize(self, samples, positions, sample_rate):
        x, (vectors, left, right, bins, steering, near) = self.prepare(
            samples, positions, sample_rate
        )
        m, nf, nt = x.shape
        power = np.mean(np.abs(x) ** 2, axis=(0, 2))
        use = power > max(float(power.max()) * 0.005, 1e-20)
        if not use.any():
            return self.events(vectors, np.zeros(len(vectors)), near, {"features": 0})
        x = x[:, use] / np.sqrt(np.maximum(power[use], 1e-20))[None, :, None]
        steering = steering[use]
        nf = x.shape[1]
        q = self.taps
        inverse = np.tile(np.eye(m * q, dtype=complex) * 1000, (nf, 1, 1))
        forgetting = (self.memory_frames - 1) / (self.memory_frames + 1)
        features, freq_indices, pair_indices = [], [], []
        joint_features, joint_valid = [], []
        smoothed = np.zeros((nf, m, q), complex)
        for t in range(q - 1, nt):
            history = x[:, :, t - q + 1 : t + 1][:, :, ::-1].transpose(1, 0, 2)
            if self.spectral_smoothing:
                smoothed = (
                    self.spectral_smoothing * smoothed
                    + (1 - self.spectral_smoothing)
                    * history
                    * x[0, :, t].conj()[:, None, None]
                )
                history = smoothed
            inverse /= forgetting
            for a, b in zip(left, right, strict=True):
                relation = np.zeros((nf, m, q), dtype=complex)
                relation[:, a] = history[:, b]
                relation[:, b] = -history[:, a]
                relation = relation.reshape(nf, m * q)
                gain = (inverse @ relation.conj()[..., None])[..., 0]
                denominator = 1 + np.sum(relation * gain, axis=1).real
                inverse -= (
                    gain[:, :, None]
                    * gain[:, None, :].conj()
                    / denominator[:, None, None]
                )
            if t < max(q * 2, 6):
                continue
            direct = inverse[:, ::q, ::q]
            frame_features = np.zeros((nf, len(left)), complex)
            frame_valid = np.zeros((nf, len(left)), bool)
            for p, (a, b) in enumerate(zip(left, right, strict=True)):
                # Two constrained solutions from the same Hermitian normal matrix.
                first = direct[:, b, a] / np.maximum(direct[:, a, a].real, 1e-20)
                denominator = direct[:, a, b]
                second = np.divide(
                    direct[:, b, b],
                    denominator,
                    out=np.zeros(nf, complex),
                    where=np.abs(denominator) > 1e-20,
                )
                agreement = np.abs(1 + first * second.conj()) / np.sqrt(
                    (1 + abs(first) ** 2) * (1 + abs(second) ** 2)
                )
                valid = (agreement >= self.consistency) & (np.abs(denominator) > 1e-20)
                estimate = (first + second) / 2
                estimate /= 1 + np.abs(estimate)
                frame_features[:, p] = estimate
                frame_valid[:, p] = valid
                indices = np.flatnonzero(valid)
                features.extend(estimate[indices])
                freq_indices.extend(indices)
                pair_indices.extend([p] * len(indices))
            joint_features.append(frame_features)
            joint_valid.append(frame_valid)
        if not features:
            return self.events(vectors, np.zeros(len(vectors)), near, {"features": 0})
        # Ratio right/left has the conjugate phase of the cross-spectrum atom.
        if self.joint:
            feature = np.array(joint_features)
            valid = np.array(joint_valid)
            errors = []
            for f in range(nf):
                e = np.abs(feature[:, f, :, None] - steering[f].conj()[None] * 0.5) ** 2
                e = np.sum(e * valid[:, f, :, None], axis=1)
                keep = valid[:, f].sum(axis=1) >= 2
                errors.extend(e[keep])
            if not errors:
                return self.events(
                    vectors, np.zeros(len(vectors)), near, {"features": 0}
                )
            error = np.array(errors)
        else:
            templates = (
                steering[np.array(freq_indices), np.array(pair_indices)].conj() * 0.5
            )
            error = np.abs(np.array(features)[:, None] - templates) ** 2
        likelihood = np.exp(-error / self.variance)
        if self.outlier:
            likelihood /= self.variance
            likelihood = np.column_stack([likelihood, np.ones(len(likelihood))])
        weights = np.full(likelihood.shape[1], 1 / likelihood.shape[1])
        for _ in range(self.iterations):
            denominator = np.maximum(likelihood @ weights, 1e-20)
            gradient = -(likelihood.T @ (1 / denominator)) / len(likelihood)
            gradient -= self.entropy * (1 + np.log(np.maximum(weights, 1e-20)))
            weights *= np.exp(np.clip(-0.07 * gradient, -10, 4.6))
            weights /= weights.sum()
        # The optional uniform component leaves inconsistent evidence unassigned.
        return self.events(
            vectors,
            weights[: len(vectors)],
            near,
            {
                "features": len(features),
                "outlier_weight": float(weights[-1]) if self.outlier else None,
            },
        )
