"""Observed-only, finite tensor buffers for Isaac Lab."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import torch

from isaac_audio_sensors.core.types import AudioObservation

_SCALARS = ("detection_score", "bearing_deg", "elevation_deg", "bearing_confidence")
_CANDIDATES = ("candidate_bearing_deg", "candidate_elevation_deg")


def _validate_capacity(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")


def _finite_float32(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or abs(value) > torch.finfo(torch.float32).max:
        raise ValueError("Observation values must be representable as finite float32.")
    return value


@dataclass(slots=True, kw_only=True)
class AudioArraySensorData:
    """Policy-safe tensors; masks, not zero values, determine availability.

    Scalar fields are [N,E], candidates [N,E,K]. Truncation counts are [N]
    for observations and [N,E] for each independent candidate axis.
    ``ambiguity_mask`` preserves any declared ambiguity class, including
    unresolved results such as insufficient context or low information.
    """

    observation_mask: torch.Tensor
    doa_mask: torch.Tensor
    detection_score: torch.Tensor
    detection_score_mask: torch.Tensor
    bearing_deg: torch.Tensor
    bearing_deg_mask: torch.Tensor
    elevation_deg: torch.Tensor
    elevation_deg_mask: torch.Tensor
    bearing_confidence: torch.Tensor
    bearing_confidence_mask: torch.Tensor
    candidate_bearing_deg: torch.Tensor
    candidate_bearing_deg_mask: torch.Tensor
    candidate_elevation_deg: torch.Tensor
    candidate_elevation_deg_mask: torch.Tensor
    ambiguity_mask: torch.Tensor
    observations_truncated: torch.Tensor
    candidate_bearings_truncated: torch.Tensor
    candidate_elevations_truncated: torch.Tensor

    @classmethod
    def allocate(
        cls,
        *,
        num_envs: int,
        max_observations: int = 1,
        max_doa_candidates: int = 2,
        device: str,
    ) -> AudioArraySensorData:
        for name, value in (
            ("num_envs", num_envs),
            ("max_observations", max_observations),
            ("max_doa_candidates", max_doa_candidates),
        ):
            _validate_capacity(value, name)
        shape = (num_envs, max_observations)
        values = {
            name: torch.zeros(shape, dtype=torch.bool, device=device)
            for name in ("observation_mask", "doa_mask", "ambiguity_mask")
        }
        for name in (*_SCALARS, *_CANDIDATES):
            field_shape = (*shape, max_doa_candidates) if name in _CANDIDATES else shape
            values[name] = torch.zeros(field_shape, dtype=torch.float32, device=device)
            values[name + "_mask"] = torch.zeros(
                field_shape, dtype=torch.bool, device=device
            )
        values["observations_truncated"] = torch.zeros(
            num_envs, dtype=torch.int64, device=device
        )
        for name in ("candidate_bearings_truncated", "candidate_elevations_truncated"):
            values[name] = torch.zeros(shape, dtype=torch.int64, device=device)
        return cls(**values)

    @classmethod
    def from_observations(
        cls,
        observations: Sequence[Sequence[AudioObservation]],
        *,
        max_observations: int = 1,
        max_doa_candidates: int = 2,
        device: str,
    ) -> AudioArraySensorData:
        """Project ordered observations only, with explicit capacity loss.

        Scalar reference data is packed on the host and transferred once per
        field. No scene metadata, IDs, diagnostics, or truth enter the tensors.
        """

        result = cls.allocate(
            num_envs=len(observations),
            max_observations=max_observations,
            max_doa_candidates=max_doa_candidates,
            device="cpu",
        )
        for row, items in enumerate(observations):
            if not all(isinstance(item, AudioObservation) for item in items):
                raise TypeError("observations must contain AudioObservation values.")
            result.observations_truncated[row] = max(0, len(items) - max_observations)
            for slot, observation in enumerate(items[:max_observations]):
                result.observation_mask[row, slot] = True
                doa = observation.doa
                result.doa_mask[row, slot] = doa is not None
                result.ambiguity_mask[row, slot] = (
                    doa is not None and doa.ambiguity_class is not None
                )
                scalars = (
                    observation.detection_score,
                    None if doa is None else doa.estimated_bearing_deg,
                    None if doa is None else doa.estimated_elevation_deg,
                    None if doa is None else doa.bearing_confidence,
                )
                for name, value in zip(_SCALARS, scalars, strict=True):
                    if value is not None:
                        getattr(result, name)[row, slot] = _finite_float32(value)
                        getattr(result, name + "_mask")[row, slot] = True
                if doa is None:
                    continue
                for name, count_name in zip(
                    _CANDIDATES,
                    ("candidate_bearings_truncated", "candidate_elevations_truncated"),
                    strict=True,
                ):
                    candidates = getattr(doa, name)
                    kept = candidates[:max_doa_candidates]
                    getattr(result, count_name)[row, slot] = len(candidates) - len(kept)
                    getattr(result, name)[row, slot, : len(kept)] = torch.tensor(
                        [_finite_float32(value) for value in kept], dtype=torch.float32
                    )
                    getattr(result, name + "_mask")[row, slot, : len(kept)] = True
        return cls(
            **{
                name: getattr(result, name).to(device=device)
                for name in cls.__dataclass_fields__
            }
        )

    def reset(self, env_mask: torch.Tensor) -> None:
        for name in self.__dataclass_fields__:
            getattr(self, name)[env_mask] = 0

    def write(self, env_ids: torch.Tensor, observations: AudioArraySensorData) -> None:
        for name in self.__dataclass_fields__:
            getattr(self, name).index_copy_(0, env_ids, getattr(observations, name))
