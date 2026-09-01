"""Batched tensor backend for Isaac Lab entity observations."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from isaac_audio_sensors.core.backends.amplitude import DISTANCE_FLOOR_M
from isaac_audio_sensors.core.constants import (
    DEFAULT_SPEED_OF_SOUND_MPS,
    EPSILON,
    SECTOR_ORDER,
)
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData
from isaac_audio_sensors.lab.entity_binding import EntityPoseTensorBatch


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchedObservations:
    bearing_deg: torch.Tensor
    confidence: torch.Tensor
    ambiguity: torch.Tensor
    per_mic_rms: torch.Tensor


def basis_from_quat_xyzw(quats: torch.Tensor) -> torch.Tensor:
    quats = quats / torch.linalg.vector_norm(quats, dim=-1, keepdim=True)
    x, y, z, w = quats.unbind(dim=-1)
    forward = torch.stack(
        (
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y + w * z),
            2.0 * (x * z - w * y),
        ),
        dim=-1,
    )
    right = torch.stack(
        (
            2.0 * (x * y - w * z),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z + w * x),
        ),
        dim=-1,
    )
    up = torch.stack(
        (
            2.0 * (x * z + w * y),
            2.0 * (y * z - w * x),
            1.0 - 2.0 * (x * x + y * y),
        ),
        dim=-1,
    )
    return torch.stack((forward, right, up), dim=-2)


def _bearing(
    forward_m: torch.Tensor, right_m: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    horizontal = torch.hypot(forward_m, right_m)
    valid = horizontal > EPSILON
    bearing = torch.remainder(torch.rad2deg(torch.atan2(right_m, forward_m)), 360.0)
    bearing = torch.where(bearing >= 360.0, torch.zeros_like(bearing), bearing)
    return torch.where(valid, bearing, bearing.new_full((), float("nan"))), valid


def _sector_onehot(bearing: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    safe = torch.where(valid, bearing, torch.zeros_like(bearing))
    index = torch.div(
        torch.remainder(safe + 22.5, 360.0), 45.0, rounding_mode="floor"
    ).long()
    result = torch.zeros(
        (*bearing.shape, len(SECTOR_ORDER)),
        dtype=torch.float32,
        device=bearing.device,
    )
    result.scatter_(-1, index.unsqueeze(-1), 1.0)
    return result * valid.unsqueeze(-1)


def _mic_world_positions(
    array_positions: torch.Tensor,
    basis: torch.Tensor,
    mic_offsets_local: torch.Tensor,
) -> torch.Tensor:
    return array_positions.unsqueeze(1) + mic_offsets_local.unsqueeze(0).matmul(basis)


def _source_amplitudes(
    batch: EntityPoseTensorBatch,
    mic_world_positions: torch.Tensor,
) -> torch.Tensor:
    to_mic = mic_world_positions.unsqueeze(1) - batch.source_positions.unsqueeze(2)
    distance = torch.linalg.vector_norm(to_mic, dim=-1)
    source_forward = basis_from_quat_xyzw(batch.source_quats_xyzw)[..., 0, :]
    cosine = torch.clamp(
        (source_forward.unsqueeze(2) * to_mic).sum(dim=-1)
        / torch.clamp(distance, min=EPSILON),
        -1.0,
        1.0,
    )
    source_coefficient = batch.static.source_directivity_coefficient.view(1, -1, 1)
    source_directivity = source_coefficient + (1.0 - source_coefficient) * cosine
    mic_world_quats = _quat_mul(
        batch.array_quats_xyzw.unsqueeze(1),
        batch.static.mic_relative_quats_xyzw.unsqueeze(0),
    )
    mic_forward = basis_from_quat_xyzw(mic_world_quats)[..., 0, :]
    mic_cosine = torch.clamp(
        (mic_forward.unsqueeze(1) * -to_mic).sum(dim=-1)
        / torch.clamp(distance, min=EPSILON),
        -1.0,
        1.0,
    )
    mic_coefficient = batch.static.mic_directivity_coefficient.view(1, 1, -1)
    microphone_directivity = mic_coefficient + (1.0 - mic_coefficient) * mic_cosine
    directivity = torch.abs(source_directivity * microphone_directivity)
    directivity = torch.where(
        distance > EPSILON, directivity, torch.ones_like(directivity)
    )
    amplitude = (
        batch.static.source_gain_scale.view(1, -1, 1)
        * directivity
        / torch.clamp(distance, min=DISTANCE_FLOOR_M)
        * batch.static.mic_gain_scale.view(1, 1, -1)
    )
    return amplitude


def _quat_mul(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    lx, ly, lz, lw = left.unbind(dim=-1)
    rx, ry, rz, rw = right.unbind(dim=-1)
    return torch.stack(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dim=-1,
    )


def geometry_observations(batch: EntityPoseTensorBatch) -> BatchedObservations:
    basis = basis_from_quat_xyzw(batch.array_quats_xyzw)
    delta = batch.source_positions - batch.array_positions.unsqueeze(1)
    components = torch.einsum("nsd,nkd->nsk", delta, basis)
    forward = components[..., 0]
    right = components[..., 1]
    distance = torch.linalg.vector_norm(delta, dim=-1)
    horizontal = torch.hypot(forward, right)
    bearing, valid = _bearing(forward, right)
    confidence = torch.where(
        valid & (distance > 0.0),
        horizontal / torch.clamp(distance, min=EPSILON),
        torch.zeros_like(distance),
    )
    mic_world = _mic_world_positions(
        batch.array_positions, basis, batch.static.mic_offsets_local
    )
    return BatchedObservations(
        bearing_deg=bearing,
        confidence=confidence,
        ambiguity=torch.zeros_like(valid),
        per_mic_rms=_source_amplitudes(batch, mic_world),
    )


def precompute_tdoa_operator(
    mic_offsets_local: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, float]:
    baseline_xyz = mic_offsets_local[1:] - mic_offsets_local[0:1]
    dimensions = 3 if int(torch.linalg.matrix_rank(baseline_xyz).item()) >= 3 else 2
    baseline = baseline_xyz[:, :dimensions]
    normal = baseline.T @ baseline
    determinant = float(torch.linalg.det(normal).item())
    if abs(determinant) <= EPSILON:
        return baseline.new_zeros((2, baseline.shape[0])), baseline, determinant
    return torch.linalg.solve(normal, baseline.T), baseline, determinant


def analytic_free_field_observations(
    batch: EntityPoseTensorBatch,
    *,
    solve_operator: torch.Tensor,
    baseline_matrix: torch.Tensor,
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
) -> BatchedObservations:
    basis = basis_from_quat_xyzw(batch.array_quats_xyzw)
    mic_world = _mic_world_positions(
        batch.array_positions, basis, batch.static.mic_offsets_local
    )
    to_mic = mic_world.unsqueeze(1) - batch.source_positions.unsqueeze(2)
    delays = torch.linalg.vector_norm(to_mic, dim=-1) / speed_of_sound_mps
    rhs = -speed_of_sound_mps * (delays[..., 1:] - delays[..., 0:1])
    direction = rhs @ solve_operator.T
    length = torch.linalg.vector_norm(direction, dim=-1)
    unit = direction / torch.clamp(length, min=EPSILON).unsqueeze(-1)
    residual = torch.sqrt(((unit @ baseline_matrix.T - rhs) ** 2).mean(dim=-1))
    bearing, valid = _bearing(unit[..., 0], unit[..., 1])
    invalid = (length <= EPSILON) | ~valid
    bearing = torch.where(invalid, bearing.new_full((), float("nan")), bearing)
    confidence = torch.where(
        invalid,
        torch.zeros_like(residual),
        torch.clamp(0.95 / (1.0 + residual * 40.0), 0.0, 1.0),
    )
    return BatchedObservations(
        bearing_deg=bearing,
        confidence=confidence,
        ambiguity=invalid,
        per_mic_rms=_source_amplitudes(batch, mic_world),
    )


def compact_active_events(
    observations: BatchedObservations,
    *,
    active_mask: torch.Tensor,
    max_events: int,
) -> AudioArraySensorData:
    num_envs, num_sources = active_mask.shape
    num_mics = observations.per_mic_rms.shape[-1]
    ranks = active_mask.long().cumsum(dim=1) - 1
    keep = active_mask & (ranks < max_events)
    destination = torch.where(keep, ranks, torch.full_like(ranks, max_events))
    shape = (num_envs, max_events + 1)

    presence = torch.zeros(shape, dtype=torch.bool, device=active_mask.device)
    presence.scatter_(1, destination, keep)
    bearing = torch.full(
        shape, float("nan"), dtype=torch.float32, device=active_mask.device
    )
    bearing.scatter_(1, destination, observations.bearing_deg)
    confidence = torch.zeros(shape, dtype=torch.float32, device=active_mask.device)
    confidence.scatter_(1, destination, observations.confidence)
    ambiguity = torch.zeros(shape, dtype=torch.bool, device=active_mask.device)
    ambiguity.scatter_(1, destination, observations.ambiguity & keep)
    rms = torch.zeros(
        (*shape, num_mics), dtype=torch.float32, device=active_mask.device
    )
    rms.scatter_(
        1,
        destination.unsqueeze(-1).expand(num_envs, num_sources, num_mics),
        observations.per_mic_rms,
    )

    presence = presence[:, :max_events]
    bearing = torch.where(
        presence,
        bearing[:, :max_events],
        torch.full_like(bearing[:, :max_events], float("nan")),
    )
    confidence = torch.where(
        presence, confidence[:, :max_events], torch.zeros_like(bearing)
    )
    return AudioArraySensorData(
        event_presence=presence,
        bearing_deg=bearing,
        confidence=confidence,
        sector_onehot=_sector_onehot(bearing, presence & ~torch.isnan(bearing)),
        per_mic_rms=rms[:, :max_events] * presence.unsqueeze(-1),
        ambiguity_mask=ambiguity[:, :max_events] & presence,
    )
