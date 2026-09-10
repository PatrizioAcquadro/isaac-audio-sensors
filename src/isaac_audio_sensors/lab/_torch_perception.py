"""Device-resident causal mixture context and observation projection."""

from __future__ import annotations

import numpy as np
import torch

from isaac_audio_sensors.lab._torch_localizer import TorchEventLocalizer
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData


def activity(
    history, stream_end, current_start, threshold_dbfs, *, max_block_samples=1600
):
    """Replay the maintained 50/100/100 ms fixed-threshold token rule on CUDA."""
    window = 800
    start = ((current_start - 4000).clamp_min(0) // window) * window
    token_length = torch.zeros_like(stream_end)
    silence = torch.zeros_like(stream_end)
    token_end = start.clone()
    detected = torch.zeros_like(stream_end, dtype=torch.bool)
    samples = torch.arange(window, device=history.device)[None]
    for frame in range((4000 + 799 + max_block_samples + 799) // 800):
        offset = start + frame * window
        size = (stream_end - offset).clamp(min=0, max=window)
        indices = offset[:, None] + samples - stream_end[:, None] + history.shape[-1]
        values = history.gather(
            2,
            indices.clamp(0, history.shape[-1] - 1)[:, None].expand(
                -1, history.shape[1], -1
            ),
        )
        values = values * (samples < size[:, None])[:, None]
        power = values.double().square().sum(dim=-1) / size.clamp_min(1)[:, None]
        # Match Auditok's float32 PCM scaling and energy floor without overflow.
        energy = 10 * torch.log10(power.amax(dim=1).clamp_min((1e-10 / 32768) ** 2))
        valid = (energy >= threshold_dbfs) & (size > 0)
        closing = (token_length > 0) & ~valid & (silence >= 2) & (size > 0)
        detected |= closing & (token_length >= 2) & (token_end > current_start)
        token_length = torch.where(closing, 0, token_length)
        ongoing = (valid | (token_length > 0)) & ~closing & (size > 0)
        token_length += ongoing.long()
        silence = torch.where(valid | closing, 0, silence + ongoing.long())
        token_end = torch.where(ongoing, offset + size, token_end)
    detected |= (
        (token_length >= 2) & (token_length > silence) & (token_end > current_start)
    )
    return detected


class TorchPerception:
    """Per-environment context; no producer, scene or source metadata is accepted."""

    def __init__(
        self,
        *,
        num_envs,
        positions,
        threshold_dbfs,
        doa_enabled,
        max_observations,
        max_doa_candidates,
        device,
        window_samples=1600,
    ):
        self.device = device
        self.threshold = threshold_dbfs
        self.max_observations = max_observations
        self.max_candidates = max_doa_candidates
        self.window_samples = window_samples
        self.history = torch.zeros(
            (num_envs, len(positions), max(16000, 4800 + window_samples)), device=device
        )
        self.samples = torch.zeros(num_envs, dtype=torch.int64, device=device)
        self.last_processed = torch.zeros_like(self.samples)
        self.active = torch.zeros(num_envs, dtype=torch.bool, device=device)
        self.discontinuity = torch.zeros_like(self.active)
        self.localizer = (
            TorchEventLocalizer(np.asarray(positions), device=device)
            if doa_enabled
            else None
        )

    def reset(self, env_ids):
        self.history[env_ids] = 0
        self.samples[env_ids] = 0
        self.last_processed[env_ids] = 0
        self.active[env_ids] = False
        self.discontinuity[env_ids] = True

    def ingest(self, env_ids, values, counts):
        """Append already received PCM; all padded samples are excluded."""
        if values.dtype != torch.float32 or values.device != self.history.device:
            raise ValueError("Mixtures must be float32 on the perception device.")
        if not torch.isfinite(values).all():
            raise ValueError("Mixtures must be finite.")
        combined = torch.cat([self.history[env_ids], values], dim=-1)
        index = (
            torch.arange(self.history.shape[-1], device=self.device)[None]
            + counts[:, None]
        )
        self.history[env_ids] = combined.gather(
            2, index[:, None].expand(-1, values.shape[1], -1)
        )
        self.samples[env_ids] += counts

    def observations(self, env_ids):
        result = AudioArraySensorData.allocate(
            num_envs=len(env_ids),
            max_observations=self.max_observations,
            max_doa_candidates=self.max_candidates,
            device=self.device,
        )
        counts = self.samples[env_ids]
        current_start = self.last_processed[env_ids].maximum(
            (counts - self.window_samples).clamp_min(0)
        )
        with torch.profiler.record_function("audio.detector"):
            active = activity(
                self.history[env_ids],
                counts,
                current_start,
                self.threshold,
                max_block_samples=self.window_samples,
            )
        active = torch.where(
            counts > self.last_processed[env_ids], active, self.active[env_ids]
        )
        self.active[env_ids] = active
        self.last_processed[env_ids] = counts
        if self.localizer is None:
            if self.max_observations:
                result.observation_mask[:, 0] = active
            else:
                result.observations_truncated[:] = active.long()
            return result
        ready = active & (counts >= self.localizer.context_samples)
        rows = torch.nonzero(ready).flatten()
        # Chunking bounds solver workspaces without changing environment semantics.
        for chunk in rows.split(128):
            if len(chunk) == 0:
                continue
            vectors, mask = self.localizer.localize(
                self.history[env_ids[chunk], :, -12000:]
            )
            with torch.profiler.record_function("audio.projection"):
                found = mask.sum(dim=-1)
                result.observations_truncated[chunk] = (
                    found - self.max_observations
                ).clamp_min(0)
                keep = min(self.max_observations, mask.shape[1])
                mask = mask[:, :keep]
                v = vectors[:, :keep]
                result.observation_mask[chunk, :keep] = mask
                result.doa_mask[chunk, :keep] = mask
                result.bearing_deg_mask[chunk, :keep] = mask
                result.bearing_deg[chunk, :keep] = (
                    torch.rad2deg(torch.atan2(v[..., 1], v[..., 0])).remainder(360)
                    * mask
                )
                if self.localizer.three_d:
                    result.elevation_deg_mask[chunk, :keep] = mask
                    result.elevation_deg[chunk, :keep] = (
                        torch.rad2deg(
                            torch.atan2(
                                v[..., 2], torch.linalg.vector_norm(v[..., :2], dim=-1)
                            )
                        )
                        * mask
                    )
        return result
