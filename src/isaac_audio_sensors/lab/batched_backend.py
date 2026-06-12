"""Batched torch L0/L1 math for the Isaac Lab fast path.

Each function mirrors one piece of the scalar reference implementation in
``core/backends`` (geometry.py, tdoa.py, amplitude.py) as tensor ops over
``[num_envs, num_sources, num_mics]`` batches. The scalar path remains the
behavioral reference; parity tests pin these functions to it.

The Lab sensor constructs backends with default stress parameters (no delay
noise, clock jitter, gain mismatch, or air absorption) and entity binding
never produces occlusion, so those terms are intentionally absent here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.backends.amplitude import DISTANCE_FLOOR_M
from isaac_audio_sensors.core.constants import (
    DEFAULT_SPEED_OF_SOUND_MPS,
    EPSILON,
    SECTOR_ORDER,
)
from isaac_audio_sensors.lab.entity_binding import EntityPoseTensorBatch


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchedObservations:
    """Per-source observation tensors before event compaction."""

    bearing_deg: Any
    confidence: Any
    ambiguity: Any
    per_mic_rms: Any


def batched_basis_from_quat_xyzw(quats: Any) -> Any:
    """Return ``[..., 3, 3]`` basis rows (forward, right, up) per quaternion.

    Mirrors ``core.math_utils.basis_from_quaternion``: row ``k`` is the local
    unit axis ``e_k`` rotated into world space.
    """

    torch = _require_torch()
    normalized = quats / torch.linalg.norm(quats, dim=-1, keepdim=True)
    x, y, z, w = normalized.unbind(dim=-1)
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


def batched_normalize_bearing_deg(bearing_deg: Any) -> Any:
    """Normalize bearings into ``[0, 360)`` like ``normalize_bearing_deg``."""

    torch = _require_torch()
    normalized = torch.remainder(bearing_deg, 360.0)
    # float32 remainder of tiny negative angles can land exactly on 360.0.
    return torch.where(
        normalized >= 360.0,
        torch.zeros_like(normalized),
        normalized,
    )


def batched_bearing_deg(forward_m: Any, right_m: Any) -> tuple[Any, Any]:
    """Return ``(bearing_deg, valid_mask)`` like ``bearing_from_components``.

    Bearings are NaN wherever the horizontal norm is degenerate.
    """

    torch = _require_torch()
    horizontal = torch.hypot(forward_m, right_m)
    valid = horizontal > EPSILON
    bearing = batched_normalize_bearing_deg(
        torch.rad2deg(torch.atan2(right_m, forward_m))
    )
    bearing = torch.where(valid, bearing, bearing.new_full((), float("nan")))
    return bearing, valid


def batched_sector_onehot(bearing_deg: Any, valid: Any) -> Any:
    """One-hot ``[..., len(SECTOR_ORDER)]`` like ``bearing_deg_to_sector_name``."""

    torch = _require_torch()
    safe_bearing = torch.where(valid, bearing_deg, torch.zeros_like(bearing_deg))
    index = (
        torch.div(
            torch.remainder(safe_bearing + 22.5, 360.0),
            45.0,
            rounding_mode="floor",
        )
        .long()
        .clamp(0, len(SECTOR_ORDER) - 1)
    )
    onehot = torch.zeros(
        (*bearing_deg.shape, len(SECTOR_ORDER)),
        dtype=bearing_deg.dtype,
        device=bearing_deg.device,
    )
    onehot.scatter_(-1, index.unsqueeze(-1), 1.0)
    return onehot * valid.unsqueeze(-1).to(onehot.dtype)


def batched_mic_world_positions(
    array_positions: Any,
    basis: Any,
    mic_offsets_local: Any,
) -> Any:
    """World mic positions ``[N, M, 3]`` like ``microphone_world_positions``."""

    offsets_world = mic_offsets_local.unsqueeze(0).matmul(basis)
    return array_positions.unsqueeze(1) + offsets_world


def batched_source_amplitudes(
    *,
    source_positions: Any,
    source_quats_xyzw: Any,
    source_gain_scale: Any,
    source_is_cardioid: Any,
    mic_world_positions: Any,
    mic_gains_db: Any | None = None,
) -> Any:
    """Synthetic RMS amplitudes ``[N, S, M]`` like ``source_amplitude_at``.

    ``mic_gains_db`` is applied by the TDOA backend but not by geometry;
    pass ``None`` for geometry parity.
    """

    torch = _require_torch()
    to_mic = mic_world_positions.unsqueeze(1) - source_positions.unsqueeze(2)
    distance = torch.linalg.norm(to_mic, dim=-1)
    source_forward = batched_basis_from_quat_xyzw(source_quats_xyzw)[..., 0, :]
    cos_theta = torch.clamp(
        (source_forward.unsqueeze(2) * to_mic).sum(dim=-1)
        / torch.clamp(distance, min=EPSILON),
        -1.0,
        1.0,
    )
    cardioid = (1.0 + cos_theta) / 2.0
    use_cardioid = source_is_cardioid.view(1, -1, 1) & (distance > EPSILON)
    directivity = torch.where(
        use_cardioid,
        cardioid,
        torch.ones_like(cardioid),
    )
    amplitude = (
        source_gain_scale.view(1, -1, 1)
        * directivity
        / torch.clamp(distance, min=DISTANCE_FLOOR_M)
    )
    if mic_gains_db is not None:
        amplitude = amplitude * (10.0 ** (mic_gains_db / 20.0)).view(1, 1, -1)
    return amplitude


def batched_geometry_observations(
    batch: EntityPoseTensorBatch,
) -> BatchedObservations:
    """L0 (geometry_only) observations; mirrors ``GeometryBackend.simulate``."""

    torch = _require_torch()
    basis = batched_basis_from_quat_xyzw(batch.array_quats_xyzw)
    delta = batch.source_positions - batch.array_positions.unsqueeze(1)
    components = torch.einsum("nsd,nkd->nsk", delta, basis)
    forward = components[..., 0]
    right = components[..., 1]
    distance = torch.linalg.norm(delta, dim=-1)
    horizontal = torch.hypot(forward, right)
    bearing, valid = batched_bearing_deg(forward, right)
    confidence = torch.where(
        valid & (distance > 0.0),
        horizontal / torch.clamp(distance, min=EPSILON),
        torch.zeros_like(distance),
    )
    mic_world = batched_mic_world_positions(
        batch.array_positions,
        basis,
        batch.static.mic_offsets_local,
    )
    per_mic_rms = batched_source_amplitudes(
        source_positions=batch.source_positions,
        source_quats_xyzw=batch.source_quats_xyzw,
        source_gain_scale=batch.static.source_gain_scale,
        source_is_cardioid=batch.static.source_is_cardioid,
        mic_world_positions=mic_world,
        mic_gains_db=None,
    )
    return BatchedObservations(
        bearing_deg=bearing,
        confidence=confidence,
        ambiguity=torch.zeros_like(valid),
        per_mic_rms=per_mic_rms,
    )


def precompute_lstsq_operator(mic_offsets_local: Any) -> tuple[Any, Any, float]:
    """Static least-squares pieces mirroring ``_least_squares_direction``.

    Returns ``(solve_op [2, M-1], baseline_matrix [M-1, 2], det)``. The 2x2
    normal-equation determinant is a one-time degeneracy check: callers must
    fall back to the scalar path when ``det <= EPSILON``.
    """

    baseline = mic_offsets_local[1:, :2] - mic_offsets_local[0:1, :2]
    normal = baseline.T.matmul(baseline)
    det = float(normal[0, 0] * normal[1, 1] - normal[0, 1] * normal[1, 0])
    if abs(det) <= EPSILON:
        return baseline.new_zeros((2, baseline.shape[0])), baseline, det
    inverse = (
        baseline.new_tensor(
            [
                [float(normal[1, 1]), -float(normal[0, 1])],
                [-float(normal[1, 0]), float(normal[0, 0])],
            ]
        )
        / det
    )
    return inverse.matmul(baseline.T), baseline, det


def batched_tdoa_observations(
    batch: EntityPoseTensorBatch,
    *,
    solve_op: Any,
    baseline_matrix: Any,
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
) -> BatchedObservations:
    """L1 (tdoa_synthetic) observations; mirrors ``TdoaSyntheticBackend``.

    Stress parameters are zero in Lab sensor usage, so delays are exact
    ``distance / c`` and the confidence stress penalty is 1.0.
    """

    torch = _require_torch()
    basis = batched_basis_from_quat_xyzw(batch.array_quats_xyzw)
    mic_world = batched_mic_world_positions(
        batch.array_positions,
        basis,
        batch.static.mic_offsets_local,
    )
    to_mic = mic_world.unsqueeze(1) - batch.source_positions.unsqueeze(2)
    delays = torch.linalg.norm(to_mic, dim=-1) / speed_of_sound_mps
    b = -speed_of_sound_mps * (delays[..., 1:] - delays[..., 0:1])
    direction = b.matmul(solve_op.T)
    length = torch.linalg.norm(direction, dim=-1)
    degenerate = length <= EPSILON
    unit = direction / torch.clamp(length, min=EPSILON).unsqueeze(-1)
    predicted = unit.matmul(baseline_matrix.T)
    residual = torch.sqrt(((predicted - b) ** 2).mean(dim=-1))
    bearing, valid = batched_bearing_deg(unit[..., 0], unit[..., 1])
    invalid = degenerate | ~valid
    nan = bearing.new_full((), float("nan"))
    bearing = torch.where(invalid, nan, bearing)
    confidence = torch.where(
        invalid,
        torch.zeros_like(residual),
        torch.clamp(0.95 / (1.0 + residual * 40.0), 0.0, 1.0),
    )
    per_mic_rms = batched_source_amplitudes(
        source_positions=batch.source_positions,
        source_quats_xyzw=batch.source_quats_xyzw,
        source_gain_scale=batch.static.source_gain_scale,
        source_is_cardioid=batch.static.source_is_cardioid,
        mic_world_positions=mic_world,
        mic_gains_db=batch.static.mic_gains_db,
    )
    return BatchedObservations(
        bearing_deg=bearing,
        confidence=confidence,
        ambiguity=invalid,
        per_mic_rms=per_mic_rms,
    )


def compact_active_events(
    observations: BatchedObservations,
    *,
    active_mask: Any,
    max_events: int,
) -> dict[str, Any]:
    """Pack active sources into event slots like ``active_sources`` truncation.

    The source axis is pre-sorted (see ``EntityStaticBatchMeta``), so packing
    active sources in order and truncating to ``max_events`` reproduces the
    scalar event layout exactly.
    """

    torch = _require_torch()
    num_envs, num_sources = active_mask.shape
    num_mics = observations.per_mic_rms.shape[-1]
    events = int(max_events)
    device = active_mask.device
    dtype = observations.bearing_deg.dtype

    ranks = active_mask.long().cumsum(dim=1) - 1
    keep = active_mask & (ranks < events)
    # Scatter through one extra trash slot so non-kept sources never land in
    # a real event column.
    dest = torch.where(keep, ranks, torch.full_like(ranks, events))

    presence = torch.zeros(
        (num_envs, events + 1),
        dtype=torch.bool,
        device=device,
    )
    presence.scatter_(1, dest, keep)
    bearing = torch.full(
        (num_envs, events + 1),
        float("nan"),
        dtype=dtype,
        device=device,
    )
    bearing.scatter_(1, dest, observations.bearing_deg)
    confidence = torch.zeros((num_envs, events + 1), dtype=dtype, device=device)
    confidence.scatter_(1, dest, observations.confidence)
    ambiguity = torch.zeros(
        (num_envs, events + 1),
        dtype=torch.bool,
        device=device,
    )
    ambiguity.scatter_(1, dest, observations.ambiguity & keep)
    per_mic_rms = torch.zeros(
        (num_envs, events + 1, num_mics),
        dtype=dtype,
        device=device,
    )
    per_mic_rms.scatter_(
        1,
        dest.unsqueeze(-1).expand(num_envs, num_sources, num_mics),
        observations.per_mic_rms,
    )

    presence = presence[:, :events]
    bearing = bearing[:, :events]
    # Restore pad sentinels: scatter writes raw values into the trash-free
    # slots only for kept sources, but a kept degenerate bearing is already
    # NaN, matching the scalar buffer contract.
    bearing = torch.where(presence, bearing, torch.full_like(bearing, float("nan")))
    confidence = torch.where(
        presence,
        confidence[:, :events],
        torch.zeros_like(bearing),
    )
    valid = presence & ~torch.isnan(bearing)
    sector_onehot = batched_sector_onehot(bearing, valid)
    return {
        "event_presence": presence,
        "bearing_deg": bearing,
        "confidence": confidence,
        "sector_onehot": sector_onehot,
        "per_mic_rms": per_mic_rms[:, :events]
        * presence.unsqueeze(-1).to(dtype),
        "ambiguity_mask": ambiguity[:, :events] & presence,
    }


def _require_torch() -> Any:
    try:
        import torch  # type: ignore

        return torch
    except ImportError as exc:
        raise RuntimeError(
            "The batched audio compute path requires torch."
        ) from exc
