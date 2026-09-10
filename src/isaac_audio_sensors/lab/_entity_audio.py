"""Batched free-field PCM production, separate from mixture-only perception."""

from __future__ import annotations

import math

import torch

from isaac_audio_sensors.core.backends._analytic.signals import _load_public_waveform
from isaac_audio_sensors.lab._torch_perception import TorchPerception
from isaac_audio_sensors.lab.entity_binding import _rotate


class EntityAudioBackend:
    """Reception-time distance/gain interpolation between observed physics poses.

    Static paths match Core fractional-delay free field. Moving paths are a
    quasi-static approximation, not Core's retarded-source trajectory solver.
    Missing pose intervals over 100 ms explicitly restart acoustic context.
    """

    def __init__(self, binding, cfg):
        from pathlib import Path

        self.binding = binding
        self.device = binding.device
        if torch.device(self.device).type != "cuda":
            raise ValueError("Entity audio requires a CUDA simulation device.")
        self.rate = binding.cfg.sample_rate_hz
        self.speed = cfg.speed_of_sound_mps
        self.assets = []
        for source in binding._source_cfgs:
            if not source.audio_asset_path or source.audio_asset_path.startswith(
                "generated://"
            ):
                raise ValueError(
                    "Entity audio requires an explicit audio file per source."
                )
            samples, _ = _load_public_waveform(
                Path(source.audio_asset_path), sample_rate_hz=self.rate
            )
            if len(samples) == 0:
                raise ValueError("Entity audio files must not be empty.")
            self.assets.append(
                torch.tensor(samples, dtype=torch.float32, device=self.device)
            )
        self.perception = TorchPerception(
            num_envs=binding.num_envs,
            positions=binding.static.mic_offsets_local.cpu().numpy(),
            threshold_dbfs=cfg.energy_threshold_dbfs,
            doa_enabled=cfg.doa_enabled,
            max_observations=cfg.max_observations,
            max_doa_candidates=cfg.max_doa_candidates,
            device=self.device,
            window_samples=max(1, round((cfg.update_period or 0.1) * self.rate)),
        )
        self.ids = torch.arange(binding.num_envs, device=self.device)
        self.cursor = torch.zeros(
            binding.num_envs, dtype=torch.int64, device=self.device
        )
        self.discontinuity_count = torch.zeros_like(self.cursor)
        self.time = torch.zeros(
            binding.num_envs, dtype=torch.float64, device=self.device
        )
        self.distance, self.gain = self._geometry(self.ids)

    def _geometry(self, ids):
        pose = self.binding.pose_batch(ids, device=self.device)
        b = len(ids)
        meta = pose.static
        m = len(meta.mic_offsets_local)
        orientations = pose.array_quats_xyzw[:, None].expand(-1, m, -1)
        microphones = pose.array_positions[:, None] + _rotate(
            meta.mic_offsets_local[None].expand(b, -1, -1), orientations
        )
        vector = microphones[:, None] - pose.source_positions[:, :, None]
        distance = torch.linalg.vector_norm(vector, dim=-1)
        if not torch.isfinite(distance).all() or (distance <= 1e-9).any():
            raise ValueError(
                "Sources and microphones require finite distinct positions."
            )
        direction = vector / distance[..., None]
        axis = torch.tensor([1.0, 0.0, 0.0], device=self.device)
        source_axis = _rotate(
            axis.expand_as(pose.source_positions), pose.source_quats_xyzw
        )
        mic_axis = _rotate(axis.expand(m, -1), meta.mic_relative_quats_xyzw)
        mic_axis = _rotate(mic_axis[None].expand(b, -1, -1), orientations)
        source_cosine = (direction * source_axis[:, :, None]).sum(dim=-1).clamp(-1, 1)
        mic_cosine = (-direction * mic_axis[:, None]).sum(dim=-1).clamp(-1, 1)
        source_coefficient = meta.source_directivity_coefficient[None, :, None]
        mic_coefficient = meta.mic_directivity_coefficient[None, None]
        gain = (source_coefficient + (1 - source_coefficient) * source_cosine) * (
            mic_coefficient + (1 - mic_coefficient) * mic_cosine
        )
        gain *= meta.source_gain_scale[None, :, None] * meta.mic_gain_scale[None, None]
        return distance, gain / (4 * math.pi * distance)

    def reset(self, ids):
        self.cursor[ids] = 0
        self.discontinuity_count[ids] = 0
        self.time[ids] = 0
        self.distance[ids], self.gain[ids] = self._geometry(ids)
        self.perception.reset(ids)

    def acquire(self, end_times):
        """Capture each physics interval even when policy reads are deferred."""
        end = torch.floor(end_times * self.rate + 1e-7).long()
        counts = end - self.cursor
        if (counts < 0).any():
            raise ValueError("Entity audio time moved backwards without reset.")
        with torch.profiler.record_function("audio.geometry"):
            distances, gains = self._geometry(self.ids)
        missing = end_times - self.time > 0.1 + 1e-9
        self.discontinuity_count += missing.long()
        if missing.any():
            self.perception.reset(self.ids[missing])
            counts = counts.masked_fill(missing, 0)
        self.perception.discontinuity.copy_(missing)
        max_count = int(counts.max().item())
        if max_count:
            with torch.profiler.record_function("audio.propagation"):
                # Bound temporary PCM independently from persistent environment state.
                for ids in self.ids.split(256):
                    n = counts[ids]
                    offsets = torch.arange(max_count, device=self.device)[None]
                    times = (self.cursor[ids, None] + offsets).double() / self.rate
                    alpha = (
                        (
                            (times - self.time[ids, None])
                            / (end_times[ids] - self.time[ids]).clamp_min(1e-12)[
                                :, None
                            ]
                        )
                        .clamp(0, 1)
                        .float()
                    )
                    mixture = torch.zeros(
                        (len(ids), self.binding.num_mics, max_count), device=self.device
                    )
                    for index, (asset, source) in enumerate(
                        zip(self.assets, self.binding._source_cfgs, strict=True)
                    ):
                        delay = (
                            torch.lerp(
                                self.distance[ids, index, :, None],
                                distances[ids, index, :, None],
                                alpha[:, None],
                            )
                            / self.speed
                        )
                        gain = torch.lerp(
                            self.gain[ids, index, :, None],
                            gains[ids, index, :, None],
                            alpha[:, None],
                        )
                        emission = (
                            times[:, None] - delay.double() - source.start_time_s
                        ) * self.rate
                        lower = emission.floor().long()
                        fraction = (emission - lower).float()
                        signal = torch.zeros_like(gain)
                        duration = (
                            math.inf
                            if source.duration_s is None
                            else round(source.duration_s * self.rate)
                        )
                        limit = (
                            math.inf
                            if source.loop_count == -1
                            else len(asset) * (source.loop_count + 1)
                        )
                        for step, weight in ((0, 1 - fraction), (1, fraction)):
                            sample = lower + step
                            valid = (sample >= 0) & (sample < min(duration, limit))
                            signal += (
                                asset[sample.remainder(len(asset))] * valid * weight
                            )
                        mixture += signal * gain
                    mixture *= (offsets < n[:, None])[:, None]
                    with torch.profiler.record_function("audio.buffers"):
                        self.perception.ingest(ids, mixture, n)
        self.cursor.copy_(end)
        self.time.copy_(end_times)
        self.distance, self.gain = distances, gains

    def observations(self, ids):
        return self.perception.observations(ids)
