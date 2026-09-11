"""Isolated native geometry PCM feeding the maintained CUDA perception."""

from dataclasses import replace

import numpy as np
import torch

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from isaac_audio_sensors.lab._entity_audio import initialize_perception
from isaac_audio_sensors.lab.entity_binding import _source_id


class GeometryEntityAudio:
    def __init__(self, binding, cfg, sessions):
        self.binding, self.device = binding, binding.device
        self.rate = binding.cfg.sample_rate_hz
        if torch.device(self.device).type != "cuda":
            raise ValueError("Geometry Lab perception requires CUDA.")
        initialize_perception(self, binding, cfg)
        self.producers = []
        try:
            for session in sessions:
                self.producers.append(
                    get_backend(
                        "geometry_acoustics",
                        acoustic_scene=session,
                        geometry_config=cfg.geometry_config,
                        effects=cfg.effects,
                        speed_of_sound_mps=cfg.speed_of_sound_mps,
                    )
                )
        except Exception:
            self.close()
            raise
        self.array = create_microphone_array(
            array_id="array",
            prim_path="/Array",
            layout_name=binding.cfg.microphone_layout or "quad_front",
            sample_rate_hz=self.rate,
        )
        if binding.cfg.microphones is not None:
            self.array = replace(self.array, microphones=binding.cfg.microphones)

    def snapshots(self):
        pose = self.binding.pose_batch(self.ids, device=self.device)
        ap, aq, sp, sq = [
            v.detach().cpu().numpy()
            for v in (
                pose.array_positions,
                pose.array_quats_xyzw,
                pose.source_positions,
                pose.source_quats_xyzw,
            )
        ]
        result = []
        for env in range(self.binding.num_envs):
            array = replace(
                self.array, position_world=ap[env], orientation_world_quat=aq[env]
            )
            sources = tuple(
                AudioSourceSpec(
                    source_id=_source_id(c),
                    prim_path=f"/Source{i}",
                    class_label="audio",
                    audio_asset_path=c.audio_asset_path,
                    position_world=sp[env, i],
                    orientation_world_quat=sq[env, i],
                    start_time_s=c.start_time_s,
                    duration_s=c.duration_s,
                    gain_db=c.gain_db,
                    loop_count=c.loop_count,
                    directivity=c.directivity,
                )
                for i, c in enumerate(self.binding._source_cfgs)
            )
            result.append(
                AudioSceneSnapshot(
                    stage_id=f"geometry-env-{env}",
                    arrays=(array,),
                    sources=sources,
                    environment=self.binding.cfg.environment,
                )
            )
        return result

    def acquire(self, end_times):
        end = torch.floor(end_times * self.rate + 1e-7).long()
        counts = end - self.cursor
        if (counts < 0).any():
            raise ValueError("Geometry entity time moved backwards without reset.")
        missing = end_times - self.time > 0.1 + 1e-9
        self.discontinuity_count += missing.long()
        self.perception.discontinuity.copy_(missing)
        maximum = int(counts.max().item())
        if maximum:
            starts, ends, missing_cpu = (
                self.cursor.cpu().tolist(),
                end.cpu().tolist(),
                missing.cpu().tolist(),
            )
            with torch.profiler.record_function("audio.geometry"):
                snapshots = self.snapshots()
            values = np.zeros(
                (len(snapshots), self.binding.num_mics, maximum), np.float32
            )
            for i, (snapshot, producer) in enumerate(
                zip(snapshots, self.producers, strict=True)
            ):
                if missing_cpu[i]:
                    producer.reset()
                    counts[i] = 0
                    self.perception.reset(self.ids[i : i + 1])
                    continue
                if ends[i] > starts[i]:
                    with torch.profiler.record_function("audio.native_pcm"):
                        block = producer.propagate(
                            snapshot,
                            "array",
                            AudioTimeWindow(
                                start_time_s=starts[i] / self.rate,
                                end_time_s=ends[i] / self.rate,
                                frame_index=starts[i],
                            ),
                        )
                    if block.discontinuity:
                        self.perception.reset(self.ids[i : i + 1])
                        self.perception.discontinuity[i] = True
                        self.discontinuity_count[i] += 1
                    values[i, :, : ends[i] - starts[i]] = block.samples
            with torch.profiler.record_function("audio.transfer_and_ingest"):
                self.perception.ingest(
                    self.ids, torch.as_tensor(values, device=self.device), counts
                )
        self.cursor.copy_(end)
        self.time.copy_(end_times)

    def observations(self, ids):
        return self.perception.observations(ids)

    def reset(self, ids):
        for i in ids.cpu().tolist():
            self.producers[i].reset()
        self.cursor[ids] = 0
        self.time[ids] = 0
        self.discontinuity_count[ids] = 0
        self.perception.reset(ids)

    def close(self):
        for producer in self.producers:
            producer.close()
