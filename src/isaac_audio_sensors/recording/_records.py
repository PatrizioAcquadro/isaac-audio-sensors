"""Internal frame-record serialization and configuration primitives."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.types import AudioSensorFrame

DATASET_FRAME_RECORD_VERSION = "ias.dataset_frame_record.v1"

_EPISODE_ID_RE = re.compile(r"^episode_[0-9]{5}$")
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\\\/]|\\\\\\\\)")


class DatasetLayoutError(ValueError):
    """A machine-readable session-layout contract violation."""

    def __init__(
        self,
        detail: str,
        *,
        code: str = "layout_violation",
        location: str | None = None,
    ) -> None:
        self.code = code
        self.location = location or detail.split(":", 1)[0]
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class LayoutWarning:
    """A non-fatal portability observation."""

    location: str
    message: str


@dataclass(frozen=True, slots=True)
class DatasetFrameRecord:
    """One frame-to-shard-audio join record."""

    dataset_frame_index: int
    episode_id: str
    audio_start_sample: int
    audio_end_sample: int
    frame: dict[str, Any]
    record_version: str = DATASET_FRAME_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return the record without modifying its nested frame dictionary."""

        return {
            "record_version": self.record_version,
            "dataset_frame_index": self.dataset_frame_index,
            "episode_id": self.episode_id,
            "audio_start_sample": self.audio_start_sample,
            "audio_end_sample": self.audio_end_sample,
            "frame": self.frame,
        }


def build_dataset_frame_record(
    *,
    dataset_frame_index: int,
    episode_id_value: str,
    audio_start_sample: int,
    audio_end_sample: int,
    frame: AudioSensorFrame | dict[str, Any],
    session_root: str | Path | None = None,
    location: str = "dataset frame record",
) -> DatasetFrameRecord:
    """Build a record around an unmodified canonical frame-v1 trace dict."""

    frame_dict = (
        frame_to_trace_dict(frame) if isinstance(frame, AudioSensorFrame) else frame
    )
    validate_trace_projection(frame_dict, session_root=session_root, location=location)
    record = DatasetFrameRecord(
        dataset_frame_index=dataset_frame_index,
        episode_id=episode_id_value,
        audio_start_sample=audio_start_sample,
        audio_end_sample=audio_end_sample,
        frame=frame_dict,
    )
    _validate_record_fields(record, location=location, sample_count=None)
    return record


def serialize_dataset_frame_record(record: DatasetFrameRecord) -> str:
    """Serialize one compact canonical, newline-terminated JSON record."""

    _validate_record_fields(record, location="dataset frame record", sample_count=None)
    return json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def parse_dataset_frame_record(
    line: str | bytes,
    *,
    location: str = "dataset frame record",
    sample_count: int | None = None,
    session_root: str | Path | None = None,
) -> DatasetFrameRecord:
    """Parse and locally validate one frame record with a located error."""

    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DatasetLayoutError(f"{location}: invalid UTF-8: {exc}") from exc
    else:
        text = line
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise DatasetLayoutError(
            f"{location}: record must be exactly one newline-terminated JSON line."
        )
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DatasetLayoutError(f"{location}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: record must be a JSON object.")
    expected = {
        "record_version",
        "dataset_frame_index",
        "episode_id",
        "audio_start_sample",
        "audio_end_sample",
        "frame",
    }
    if set(payload) != expected:
        raise DatasetLayoutError(
            f"{location}: record fields must be exactly {sorted(expected)}."
        )
    frame_payload = payload["frame"]
    if not isinstance(frame_payload, dict):
        raise DatasetLayoutError(f"{location}.frame: must be an object.")
    record = DatasetFrameRecord(
        record_version=payload["record_version"],
        dataset_frame_index=payload["dataset_frame_index"],
        episode_id=payload["episode_id"],
        audio_start_sample=payload["audio_start_sample"],
        audio_end_sample=payload["audio_end_sample"],
        frame=frame_payload,
    )
    _validate_record_fields(record, location=location, sample_count=sample_count)
    validate_trace_projection(
        record.frame,
        session_root=session_root,
        location=f"{location}.frame",
    )
    if serialize_dataset_frame_record(record) != text:
        raise DatasetLayoutError(f"{location}: record is not canonical JSON.")
    return record


def validate_record_sequence(
    records: Sequence[DatasetFrameRecord],
    *,
    sample_count: int,
    reset_frame_indices: Iterable[int] = (),
    max_overlap_samples: int | None = None,
    location: str = "frames.jsonl",
) -> None:
    """Validate local bounds, ordering, overlap, reset, and empty-range rules."""

    resets = _prepare_sequence_validation(
        sample_count=sample_count,
        reset_frame_indices=reset_frame_indices,
        max_overlap_samples=max_overlap_samples,
    )
    previous: DatasetFrameRecord | None = None
    for line_number, record in enumerate(records, start=1):
        _validate_record_pair(
            previous,
            record,
            line_number=line_number,
            sample_count=sample_count,
            reset_frame_indices=resets,
            max_overlap_samples=max_overlap_samples,
            location=location,
        )
        previous = record


def _prepare_sequence_validation(
    *,
    sample_count: int,
    reset_frame_indices: Iterable[int],
    max_overlap_samples: int | None,
) -> set[int]:
    _require_non_negative_int(sample_count, "sample_count")
    if max_overlap_samples is not None:
        _require_non_negative_int(max_overlap_samples, "max_overlap_samples")
    resets = set(reset_frame_indices)
    for reset in resets:
        _require_non_negative_int(reset, "reset frame index")
    return resets


def _validate_record_pair(
    previous: DatasetFrameRecord | None,
    record: DatasetFrameRecord,
    *,
    line_number: int,
    sample_count: int,
    reset_frame_indices: set[int],
    max_overlap_samples: int | None,
    location: str,
) -> None:
    record_location = f"{location} line {line_number}"
    _validate_record_fields(record, location=record_location, sample_count=sample_count)
    if previous is None:
        return
    if record.audio_start_sample < previous.audio_start_sample:
        raise DatasetLayoutError(
            f"{record_location}: audio_start_sample is non-monotonic."
        )
    if record.audio_end_sample < previous.audio_end_sample:
        raise DatasetLayoutError(
            f"{record_location}: audio_end_sample is non-monotonic."
        )
    overlap = previous.audio_end_sample - record.audio_start_sample
    if record.dataset_frame_index in reset_frame_indices and overlap > 0:
        raise DatasetLayoutError(
            f"{record_location}: audio range overlaps across a reset boundary."
        )
    if max_overlap_samples is not None and overlap > max_overlap_samples:
        raise DatasetLayoutError(
            f"{record_location}: audio overlap {overlap} exceeds configured "
            f"maximum {max_overlap_samples}."
        )


def _validate_record_fields(
    record: DatasetFrameRecord,
    *,
    location: str,
    sample_count: int | None,
) -> None:
    if record.record_version != DATASET_FRAME_RECORD_VERSION:
        raise DatasetLayoutError(
            f"{location}: record_version must be {DATASET_FRAME_RECORD_VERSION!r}.",
            code="unknown_version",
            location=location,
        )
    _located_non_negative_int(
        record.dataset_frame_index, f"{location}.dataset_frame_index"
    )
    if not isinstance(record.episode_id, str) or not _EPISODE_ID_RE.fullmatch(
        record.episode_id
    ):
        raise DatasetLayoutError(f"{location}.episode_id: expected episode_<NNNNN>.")
    _located_non_negative_int(
        record.audio_start_sample, f"{location}.audio_start_sample"
    )
    _located_non_negative_int(record.audio_end_sample, f"{location}.audio_end_sample")
    if record.audio_end_sample < record.audio_start_sample:
        raise DatasetLayoutError(
            f"{location}: audio sample range is inverted.",
            code="range_out_of_bounds",
            location=location,
        )
    if sample_count is not None and record.audio_end_sample > sample_count:
        raise DatasetLayoutError(
            f"{location}: audio_end_sample {record.audio_end_sample} exceeds "
            f"sample_count {sample_count}.",
            code="range_out_of_bounds",
            location=location,
        )


def validate_trace_projection(
    frame: AudioSensorFrame | dict[str, Any],
    *,
    session_root: str | Path | None = None,
    location: str = "frame",
) -> tuple[LayoutWarning, ...]:
    """Accept or reject the §4.5 projection without rewriting the frame."""

    payload = (
        frame_to_trace_dict(frame) if isinstance(frame, AudioSensorFrame) else frame
    )
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: frame must be an object.")
    try:
        rebuilt = frame_from_trace_dict(payload)
        canonical = frame_to_trace_dict(rebuilt)
    except (KeyError, TypeError, ValueError) as exc:
        raise DatasetLayoutError(f"{location}: invalid frame v1: {exc}") from exc
    if canonical != payload:
        raise DatasetLayoutError(
            f"{location}: frame is not an unmodified canonical frame v1 trace dict."
        )
    root = None if session_root is None else Path(session_root)
    waveform_paths = payload.get("waveform_paths", [])
    if not isinstance(waveform_paths, list):
        raise DatasetLayoutError(f"{location}.waveform_paths: must be an array.")
    for index, value in enumerate(waveform_paths):
        _validate_session_path(
            value,
            session_root=root,
            location=f"{location}.waveform_paths[{index}]",
        )
    detections = payload.get("detections", [])
    for index, detection in enumerate(detections):
        value = detection.get("audio_asset_path")
        if value is not None and not (isinstance(value, str) and _URI_RE.match(value)):
            _validate_session_path(
                value,
                session_root=root,
                location=f"{location}.detections[{index}].audio_asset_path",
            )
    warnings: list[LayoutWarning] = []
    warnings.extend(
        _diagnostic_path_warnings(
            payload.get("diagnostics", {}), f"{location}.diagnostics"
        )
    )
    for index, detection in enumerate(detections):
        warnings.extend(
            _diagnostic_path_warnings(
                detection.get("diagnostics", {}),
                f"{location}.detections[{index}].diagnostics",
            )
        )
    return tuple(warnings)


def _validate_session_path(
    value: object,
    *,
    session_root: Path | None,
    location: str,
) -> None:
    if not isinstance(value, str) or not value:
        raise DatasetLayoutError(f"{location}: must be a non-empty path string.")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "\\" in value
    ):
        raise DatasetLayoutError(
            f"{location}: must be a session-relative POSIX path without traversal."
        )
    if session_root is not None:
        candidate = session_root.joinpath(*posix.parts)
        try:
            root_resolved = session_root.resolve(strict=True)
            candidate_resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise DatasetLayoutError(
                f"{location}: referenced file does not exist."
            ) from exc
        if not candidate_resolved.is_relative_to(root_resolved):
            raise DatasetLayoutError(f"{location}: path escapes the session root.")
        if not candidate_resolved.is_file():
            raise DatasetLayoutError(f"{location}: referenced path is not a file.")
        current = session_root
        for part in posix.parts:
            current = current / part
            if current.is_symlink():
                raise DatasetLayoutError(f"{location}: symbolic links are forbidden.")


def _diagnostic_path_warnings(value: object, location: str) -> list[LayoutWarning]:
    warnings: list[LayoutWarning] = []
    if isinstance(value, dict):
        for key in sorted(value):
            warnings.extend(_diagnostic_path_warnings(value[key], f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            warnings.extend(_diagnostic_path_warnings(item, f"{location}[{index}]"))
    elif isinstance(value, str) and (
        value.startswith("/") or _WINDOWS_ABSOLUTE_RE.match(value)
    ):
        warnings.append(
            LayoutWarning(
                location=location,
                message="diagnostic string looks like an absolute filesystem path",
            )
        )
    return warnings


def canonical_configuration_bytes(configuration: Mapping[str, Any]) -> bytes:
    """Return the exact UTF-8 canonical configuration byte contract."""

    normalized = _normalize_configuration(configuration, key=None, location="config")
    try:
        text = (
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"configuration is not canonical JSON data: {exc}") from exc
    return text.encode("utf-8")


def configuration_sha256(configuration: Mapping[str, Any] | bytes) -> str:
    """Hash canonical configuration bytes, or exact already-canonical bytes."""

    data = (
        canonical_configuration_bytes(configuration)
        if isinstance(configuration, Mapping)
        else configuration
    )
    if not isinstance(data, bytes):
        raise TypeError("configuration_sha256 expects a mapping or bytes.")
    return hashlib.sha256(data).hexdigest()


def _normalize_configuration(value: Any, *, key: str | None, location: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): _normalize_configuration(
                child_value,
                key=str(child_key),
                location=f"{location}.{child_key}",
            )
            for child_key, child_value in sorted(
                value.items(), key=lambda item: str(item[0])
            )
        }
    if isinstance(value, (tuple, list)):
        return [
            _normalize_configuration(item, key=key, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Path):
        value = value.as_posix()
    if isinstance(value, str) and key is not None and _is_path_key(key):
        if _URI_RE.match(value):
            return value
        _validate_portable_relative_path(value, location)
    return value


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered == "path" or lowered.endswith("_path") or lowered.endswith("_paths")


def _validate_portable_relative_path(value: str, location: str) -> None:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "\\" in value
    ):
        raise ValueError(
            f"{location} must be a relative POSIX path without parent traversal."
        )


def _require_non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def _located_non_negative_int(value: object, location: str) -> None:
    try:
        _require_non_negative_int(value, location)
    except ValueError as exc:
        raise DatasetLayoutError(str(exc)) from exc


def _located_positive_int(value: object, location: str) -> None:
    try:
        _require_positive_int(value, location)
    except ValueError as exc:
        raise DatasetLayoutError(str(exc)) from exc


__all__: list[str] = []
