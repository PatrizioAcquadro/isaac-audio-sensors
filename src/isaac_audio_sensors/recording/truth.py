"""Dataset-owned supervision, independent of observed sensor frames."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

from isaac_audio_sensors.core.math_utils import as_quaternion_xyzw, as_vector3
from isaac_audio_sensors.core.types import (
    AudioSensorFrame,
    AudioTimeWindow,
    SourceOcclusion,
)
from isaac_audio_sensors.recording.serialization import _serialize


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text.")


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number.")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}.")
    return float(value)


def _rms_map(value: Mapping[str, float], name: str) -> Mapping[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must contain microphone RMS values.")
    result = {}
    for key, item in value.items():
        _text(key, f"{name} microphone id")
        result[key] = _number(item, name)
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True, kw_only=True)
class TruthEvent:
    """One source's snapshot geometry and evidence over the complete frame window.

    Received RMS is after linear channel effects, before mixture noise/electronics.
    It is evidence, not a task-independent audibility decision.
    """

    source_id: str
    class_label: str
    position_world_m: tuple[float, float, float]
    orientation_world_xyzw: tuple[float, float, float, float] | None
    bearing_deg: float | None
    elevation_deg: float | None
    distance_m: float
    prim_path: str
    audio_asset_path: str | None
    schedule_overlap: bool
    emission_rms: float
    received_rms: Mapping[str, float]
    occlusion: SourceOcclusion | None = None

    @property
    def emitting(self) -> bool:
        """Whether the scheduled, gained source waveform contains nonzero energy."""
        return self.emission_rms > 0.0

    def __post_init__(self) -> None:
        for name in ("source_id", "class_label", "prim_path"):
            _text(getattr(self, name), name)
        if self.audio_asset_path is not None:
            _text(self.audio_asset_path, "audio_asset_path")
        object.__setattr__(
            self,
            "position_world_m",
            as_vector3(self.position_world_m, "position_world_m"),
        )
        if self.orientation_world_xyzw is not None:
            quaternion = tuple(float(value) for value in self.orientation_world_xyzw)
            normalized = as_quaternion_xyzw(quaternion, "orientation_world_xyzw")
            # Preserve already-unit values so canonical JSON survives repeated reads.
            if math.isclose(
                sum(value * value for value in quaternion),
                1.0,
                abs_tol=1e-12,
                rel_tol=0.0,
            ):
                normalized = quaternion
            object.__setattr__(
                self,
                "orientation_world_xyzw",
                normalized,
            )
        for name in ("distance_m", "emission_rms"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if type(self.schedule_overlap) is not bool:
            raise ValueError("schedule_overlap must be a Boolean.")
        if not self.schedule_overlap and self.emitting:
            raise ValueError("Emission requires schedule overlap.")
        for name, minimum, maximum in (
            ("bearing_deg", 0.0, 360.0),
            ("elevation_deg", -90.0, 90.0),
        ):
            value = getattr(self, name)
            if value is not None:
                value = _number(value, name, minimum=minimum)
                if value > maximum or (name == "bearing_deg" and value == maximum):
                    raise ValueError(f"{name} is out of range.")
                object.__setattr__(self, name, value)
        if self.distance_m == 0.0 and (
            self.bearing_deg is not None or self.elevation_deg is not None
        ):
            raise ValueError("Coincident source direction must be undefined.")
        object.__setattr__(
            self, "received_rms", _rms_map(self.received_rms, "received_rms")
        )
        if self.occlusion is not None:
            if not isinstance(self.occlusion, SourceOcclusion):
                raise TypeError("occlusion must be SourceOcclusion or None.")
            occlusion = _occlusion_from_dict(_occlusion_to_dict(self.occlusion))
            if occlusion.source_id != self.source_id:
                raise ValueError("Occlusion source identity does not match truth.")
            if set(occlusion.per_mic_blocked) != set(self.received_rms):
                raise ValueError("Occlusion microphone identities do not match truth.")
            for name in (
                "per_mic_blocked",
                "per_mic_attenuation_db",
                "per_mic_band_attenuation_db",
            ):
                object.__setattr__(
                    occlusion, name, MappingProxyType(dict(getattr(occlusion, name)))
                )
            object.__setattr__(self, "occlusion", occlusion)


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameTruth:
    """Privileged dataset record aligned with one frame, including empty scenes.

    Mixture residual RMS includes stochastic and nonlinear mixture effects; it
    must not be interpreted as pure noise or a per-source SNR.
    """

    frame_id: str
    array_id: str
    time_window: AudioTimeWindow
    sample_rate_hz: int
    truth_events: tuple[TruthEvent, ...]
    mixture_residual_rms: Mapping[str, float]

    def __post_init__(self) -> None:
        _text(self.frame_id, "frame_id")
        _text(self.array_id, "array_id")
        if not isinstance(self.time_window, AudioTimeWindow):
            raise TypeError("time_window must be AudioTimeWindow.")
        for name in ("start_time_s", "end_time_s"):
            _number(getattr(self.time_window, name), name, minimum=-math.inf)
        if type(self.sample_rate_hz) is not int or self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be a positive integer.")
        events = tuple(self.truth_events)
        if not all(isinstance(event, TruthEvent) for event in events):
            raise TypeError("truth_events must contain TruthEvent values.")
        if len({event.source_id for event in events}) != len(events):
            raise ValueError("Truth source IDs must be unique within a frame.")
        residual = _rms_map(self.mixture_residual_rms, "mixture_residual_rms")
        for event in events:
            if set(event.received_rms) != set(residual):
                raise ValueError(
                    "Truth event microphone identities must match the frame."
                )
            if (
                event.occlusion is not None
                and event.occlusion.array_id != self.array_id
            ):
                raise ValueError("Occlusion array identity does not match truth.")
        object.__setattr__(self, "truth_events", events)
        object.__setattr__(self, "mixture_residual_rms", residual)


@dataclass(frozen=True, slots=True, kw_only=True)
class AnnotationRecord:
    """Caller-authored label and provenance, with optional explicit references."""

    annotation_id: str
    label: str
    provenance: str
    source_id: str | None = None
    observation_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("annotation_id", "label", "provenance"):
            _text(getattr(self, name), name)
        for name in ("source_id", "observation_id"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)


def _validate_supervision(
    frame: AudioSensorFrame,
    truth: FrameTruth | None,
    annotations: Sequence[AnnotationRecord],
) -> tuple[AnnotationRecord, ...]:
    if truth is not None:
        if not isinstance(truth, FrameTruth):
            raise TypeError("truth must be FrameTruth or None.")
        if any(
            getattr(truth, name) != getattr(frame, name)
            for name in ("frame_id", "array_id", "sample_rate_hz")
        ):
            raise ValueError(
                "Truth identity, time window, and sample rate must match the frame."
            )
        if any(
            getattr(truth.time_window, name) != getattr(frame, name)
            for name in ("start_time_s", "end_time_s", "frame_index")
        ):
            raise ValueError("Truth time window must match the frame.")
        if set(truth.mixture_residual_rms) != set(frame.channel_validity):
            raise ValueError("Truth microphone identities must match the frame.")
    result = tuple(annotations)
    if not all(isinstance(item, AnnotationRecord) for item in result):
        raise TypeError("annotations must contain AnnotationRecord values.")
    if len({item.annotation_id for item in result}) != len(result):
        raise ValueError("Annotation IDs must be unique within a frame.")
    observation_ids = {item.observation_id for item in frame.observations}
    source_ids = (
        None if truth is None else {event.source_id for event in truth.truth_events}
    )
    for item in result:
        if (
            item.observation_id is not None
            and item.observation_id not in observation_ids
        ):
            raise ValueError("Annotation references an absent observation.")
        if (
            source_ids is not None
            and item.source_id is not None
            and item.source_id not in source_ids
        ):
            raise ValueError("Annotation references an absent truth source.")
    return result


def _exact(payload: Any, model: type) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        item.name for item in fields(model)
    }:
        raise ValueError(
            f"{model.__name__} fields must match the canonical model exactly."
        )
    return dict(payload)


def _occlusion_to_dict(value: SourceOcclusion) -> dict[str, Any]:
    return _serialize(value)


def _occlusion_from_dict(payload: dict[str, Any]) -> SourceOcclusion:
    values = _exact(payload, SourceOcclusion)
    if not isinstance(values["per_mic_blocked"], dict) or any(
        type(value) is not bool for value in values["per_mic_blocked"].values()
    ):
        raise ValueError("Occlusion blocked values must be Booleans.")
    return SourceOcclusion(**values)


def _truth_to_dict(value: FrameTruth | None) -> dict[str, Any] | None:
    return _serialize(value)


def _truth_from_dict(payload: dict[str, Any] | None) -> FrameTruth | None:
    if payload is None:
        return None
    values = _exact(payload, FrameTruth)
    values["time_window"] = AudioTimeWindow(
        **_exact(values["time_window"], AudioTimeWindow)
    )
    events = []
    if not isinstance(values["truth_events"], list):
        raise ValueError("truth_events must be an array.")
    for payload_event in values["truth_events"]:
        event = _exact(payload_event, TruthEvent)
        if event["occlusion"] is not None:
            event["occlusion"] = _occlusion_from_dict(event["occlusion"])
        events.append(TruthEvent(**event))
    values["truth_events"] = tuple(events)
    return FrameTruth(**values)


def _annotations_to_dict(values: Sequence[AnnotationRecord]) -> list[dict[str, Any]]:
    return [_serialize(value) for value in values]


def _annotations_from_dict(
    payload: list[dict[str, Any]],
) -> tuple[AnnotationRecord, ...]:
    if not isinstance(payload, list):
        raise ValueError("annotations must be an array.")
    return tuple(
        AnnotationRecord(**_exact(value, AnnotationRecord)) for value in payload
    )


__all__ = ["AnnotationRecord", "FrameTruth", "TruthEvent"]
