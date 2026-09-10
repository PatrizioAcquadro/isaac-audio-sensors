"""Batched mixture-only adaptation of the maintained WPE/sparse localizer."""

from __future__ import annotations

import math

import numpy as np
import torch


def dereverberate(samples: torch.Tensor) -> torch.Tensor:
    """NARA WPE equations with independent floors and singular-system handling."""
    from nara_wpe.torch_wpe import build_y_tilde, hermite

    # Float32 WPE creates spurious events for near-degenerate 3D mixtures.
    samples = samples.double()
    batch, channels, length = samples.shape
    window = torch.hann_window(256, dtype=samples.dtype, device=samples.device)
    padded = torch.nn.functional.pad(samples, (0, (-length) % 64))
    spectrum = (
        torch.stft(
            padded.flatten(0, 1),
            256,
            64,
            window=window,
            center=True,
            pad_mode="constant",
            return_complex=True,
        )
        .reshape(batch, channels, 129, -1)
        .transpose(1, 2)
    )
    # SciPy's reference STFT uses spectrum scaling.
    spectrum = spectrum / window.sum()
    delayed = build_y_tilde(spectrum, taps=6, delay=2)
    result = spectrum
    for _ in range(3):
        power = result.abs().square().mean(dim=-2)
        floor = 1e-10 * power.amax(dim=(-2, -1), keepdim=True)
        inverse = torch.where(floor > 0, power.maximum(floor).reciprocal(), 1.0)
        weighted = delayed * inverse.unsqueeze(-2)
        covariance = weighted @ hermite(delayed)
        cross = weighted @ hermite(spectrum)
        solution, info = torch.linalg.solve_ex(covariance, cross)
        invalid = (info != 0) | ~torch.isfinite(solution).all(dim=(-2, -1))
        if invalid.any():
            solution[invalid] = torch.linalg.pinv(covariance[invalid]) @ cross[invalid]
        result = spectrum - hermite(solution) @ delayed
    restored = torch.istft(
        (result * window.sum()).transpose(1, 2).reshape(batch * channels, 129, -1),
        256,
        64,
        window=window,
        center=True,
        length=padded.shape[-1],
    ).reshape(batch, channels, -1)[..., :length]
    if not torch.isfinite(restored).all():
        raise ValueError("Non-finite CUDA dereverberation output.")
    return restored


class TorchEventLocalizer:
    """Same grids, frequency selection and event rules as the scalar reference.

    Geometry-only dictionaries are shared; mixture statistics and convergence
    are independent for every environment. No source state enters this class.
    """

    context_samples = 12000

    def __init__(self, positions: np.ndarray, *, device: str) -> None:
        from isaac_audio_sensors.core.plugins._multisource_sparse import (
            GroupSparseCovariance,
        )

        positions = np.asarray(positions, dtype=float)
        spatial = GroupSparseCovariance()
        _, (vectors, bins, neighbors) = spatial.prepare(
            np.zeros((len(positions), self.context_samples)), positions, 16000
        )
        self.three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
        self.vectors = torch.tensor(vectors, dtype=torch.float32, device=device)
        self.bins = torch.tensor(bins, device=device)
        # Build in reference precision once; runtime fitting uses float32.
        frequencies = np.fft.rfftfreq(1024, 1 / 16000)[bins]
        steering = np.exp(
            2j
            * np.pi
            * frequencies[:, None, None]
            * (positions @ vectors.T)[None]
            / 343
        )
        m = len(positions)
        atoms = np.einsum("fmg,fng->fmng", steering, steering.conj())
        distances = np.linalg.norm(positions[:, None] - positions[None], axis=-1)
        noise = np.stack(
            [
                np.broadcast_to(np.eye(m), (len(bins), m, m)),
                np.sinc(2 * frequencies[:, None, None] * distances / 343),
            ],
            axis=-1,
        )
        atoms = (
            np.concatenate([atoms, noise], axis=-1).reshape(len(bins), m * m, -1) / m
        )
        dictionary = np.concatenate([atoms.real, atoms.imag], axis=1).astype(np.float32)
        self.dictionary = torch.tensor(dictionary, device=device)
        gram = self.dictionary @ self.dictionary.transpose(-1, -2)
        identity = torch.eye(gram.shape[-1], device=device)
        self.correction = self.dictionary.transpose(-1, -2) @ torch.linalg.inv(
            gram + identity
        )
        # Reference neighborhoods include exact boundary points in float64.
        smoothing = np.zeros((len(vectors), len(vectors)), dtype=np.float32)
        for row, adjacent in enumerate(neighbors):
            smoothing[row, adjacent] = 1
        from scipy.spatial import cKDTree

        near = np.zeros_like(smoothing, dtype=bool)
        for row, adjacent in enumerate(
            cKDTree(vectors).query_ball_point(vectors, 2 * np.sin(np.radians(8) / 2))
        ):
            near[row, adjacent] = True
        self.smoothing = torch.tensor(smoothing, device=device)
        self.near = torch.tensor(near, device=device)
        self.centroid = torch.tensor(
            (vectors @ vectors.T >= np.cos(np.radians(10))).astype(np.float32),
            device=device,
        )
        self.exclusion = torch.tensor(
            vectors @ vectors.T >= np.cos(np.radians(20)), device=device
        )
        self.window = torch.hann_window(
            1024, periodic=False, dtype=torch.float64, device=device
        )

    def localize(self, samples: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        with torch.profiler.record_function("audio.wpe"):
            processed = dereverberate(samples)
        with torch.profiler.record_function("audio.sparse"):
            histogram = self._fit(processed)
        with torch.profiler.record_function("audio.peaks"):
            return self._events(histogram)

    def _fit(self, samples: torch.Tensor) -> torch.Tensor:
        b, m, _ = samples.shape
        spectrum = torch.stft(
            samples.flatten(0, 1),
            1024,
            128,
            window=self.window,
            center=False,
            return_complex=True,
        ).reshape(b, m, 513, -1)[:, :, self.bins]
        power = spectrum.abs().square().mean(dim=(1, 3))
        active = power > (power.amax(dim=-1, keepdim=True) * 1e-4).clamp_min(1e-20)
        count = active.sum(dim=-1)
        used = count.clamp(max=48)
        slots = torch.arange(48, device=samples.device)[None]
        valid = slots < used[:, None]
        ranks = (slots * (count[:, None] - 1) / (used[:, None] - 1).clamp_min(1)).long()
        ordered = (
            torch.where(
                active, self.bins.new_tensor(range(len(self.bins))), len(self.bins)
            )
            .sort(dim=-1)
            .values
        )
        indices = ordered.gather(1, ranks.clamp(min=0, max=len(self.bins) - 1)).clamp(
            max=len(self.bins) - 1
        )
        x = spectrum.gather(
            2, indices[:, None, :, None].expand(-1, m, -1, spectrum.shape[-1])
        )
        p = power.gather(1, indices).clamp_min(1e-20)
        x = x / p.sqrt()[:, None, :, None] * valid[:, None, :, None]
        covariance = (
            x.transpose(1, 2) @ x.transpose(1, 2).transpose(-1, -2).conj() / x.shape[-1]
        )
        covariance = covariance.reshape(b, 48, m * m) / m
        observed = torch.cat([covariance.real, covariance.imag], dim=-1).float()
        dictionary, correction = self.dictionary[indices], self.correction[indices]
        z = torch.zeros((b, 48, dictionary.shape[-1]), device=samples.device)
        dual = torch.zeros_like(z)
        penalty = 0.03 * used.float().sqrt()[:, None, None]
        finished = used == 0
        for iteration in range(100):
            value = z - dual
            residual = observed - (dictionary @ value.unsqueeze(-1)).squeeze(-1)
            fitted = value + (correction @ residual.unsqueeze(-1)).squeeze(-1)
            candidate = (fitted + dual).clamp_min(0) * valid[..., None]
            norms = torch.linalg.vector_norm(candidate[:, :, :-2], dim=1, keepdim=True)
            candidate[:, :, :-2] *= (1 - penalty / norms.clamp_min(1e-20)).clamp_min(0)
            primal = torch.linalg.vector_norm(fitted - candidate, dim=(1, 2))
            change = torch.linalg.vector_norm(candidate - z, dim=(1, 2))
            tolerance = 1e-5 * torch.linalg.vector_norm(
                candidate, dim=(1, 2)
            ).clamp_min(1e-20)
            dual = torch.where(finished[:, None, None], dual, dual + fitted - candidate)
            z = torch.where(finished[:, None, None], z, candidate)
            if iteration > 20:
                finished |= primal.maximum(change) < tolerance
                if finished.all():
                    break
        return z[:, :, :-2].sum(dim=1) / used.clamp_min(1)[:, None]

    def _events(self, histogram: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        smooth = (histogram - histogram.mean(dim=1, keepdim=True)) @ self.smoothing.T
        maxima = smooth[:, None, :].masked_fill(~self.near, -torch.inf).amax(dim=-1)
        eligible = (smooth >= 0.025) & (smooth >= maxima)
        batch, grid = eligible.shape
        directions = torch.zeros((batch, grid, 3), device=histogram.device)
        occupied = torch.zeros_like(eligible)
        slot = 0
        while eligible.any():
            present = eligible.any(dim=-1)
            index = smooth.masked_fill(~eligible, -torch.inf).argmax(dim=-1)
            weights = histogram * self.centroid[index]
            centers = weights @ self.vectors
            centers /= torch.linalg.vector_norm(
                centers, dim=-1, keepdim=True
            ).clamp_min(1e-20)
            separate = (
                (directions * centers[:, None]).sum(dim=-1) < math.cos(math.radians(30))
            ) | ~occupied
            accepted = present & separate.all(dim=-1)
            directions[:, slot] = centers
            occupied[:, slot] = accepted
            eligible &= ~self.exclusion[index] & present[:, None]
            slot += 1
        # Match Core event order; policy capacity is applied only after discovery.
        bearing = torch.atan2(directions[..., 1], directions[..., 0])
        order = bearing.masked_fill(~occupied, torch.inf).argsort(dim=-1, stable=True)
        return directions.gather(
            1, order[..., None].expand(-1, -1, 3)
        ), occupied.gather(1, order)
