"""Isolated WPE + group-sparse covariance fitting; not yet a runtime selection.

Pejoski and Kafedziski, Telfor Journal 2014, equation (9), solved with ADMM.
Adaptations: geometry-derived 3D atoms, fitted white/diffuse noise powers,
frequency normalization/thinning, finite iterations and angular event rejection.
"""

import numpy as np

from .indoor_candidates import SpatialEvidence


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


class GroupSparseCovariance(SpatialEvidence):
    def __init__(self, threshold=0.015, regularization=0.03, energy_floor=0.0001):
        super().__init__(threshold, nfft=1024, sphere_points=642)
        self.regularization = regularization
        self.energy_floor = energy_floor

    def localize(self, samples, positions, sample_rate):
        x, (vectors, _, _, bins, _, near) = self.prepare(
            samples, positions, sample_rate
        )
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

    def events(self, vectors, histogram, near, diagnostic):
        found, diagnostic = super().events(vectors, histogram, near, diagnostic)
        # Refinement can bring formerly distinct grid peaks into the same lobe.
        selected = []
        for index in np.argsort(-np.array(diagnostic["scores"])):
            if all(found[index] @ found[j] < np.cos(np.radians(30)) for j in selected):
                selected.append(index)
        diagnostic["scores"] = [diagnostic["scores"][i] for i in selected]
        return found[selected], diagnostic


class WpeSparseCovariance:
    """Fit current supplied past audio without accumulating overlapping windows."""

    def __init__(self, threshold=0.015, taps=6, regularization=0.03):
        self.taps = taps
        self.spatial = GroupSparseCovariance(threshold, regularization)

    def localize(self, samples, positions, sample_rate):
        from nara_wpe.wpe import wpe_v7

        from .dereverberation import preprocess

        processed = preprocess(
            samples,
            self.taps,
            wpe_v7,
            nfft=256,
            hop=64,
            delay=2,
            output_samples=12000,
        )
        return self.spatial.localize(processed, positions, sample_rate)
