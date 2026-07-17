"""Canonical streaming validation for session-sharded audio datasets."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from isaac_audio_sensors.core.dataset import loader as _loader
from isaac_audio_sensors.core.dataset.layout import (
    DatasetLayoutError,
    LayoutWarning,
    validate_trace_projection,
)
from isaac_audio_sensors.core.dataset.loader import LoadedFrame, SessionDataset
from isaac_audio_sensors.core.dataset.statistics import Statistics, StatisticsBuilder
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)

FindingSeverity = Literal["error", "warning"]
ValidationStatus = Literal["passed", "passed_with_warnings", "failed"]
_DEEP_AUDIO_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Finding:
    """One stable, located dataset validation result."""

    code: str
    severity: FindingSeverity
    location: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        """Return the frozen finding schema."""

        return {
            "code": self.code,
            "detail": self.detail,
            "location": self.location,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Deterministic validation outcome and statistics."""

    status: ValidationStatus
    findings: tuple[Finding, ...]
    statistics: Statistics
    error_count: int
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return the full deterministic JSON report."""

        return {
            "error_count": self.error_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "statistics": self.statistics.to_dict(),
            "status": self.status,
            "warning_count": self.warning_count,
        }


def validate_dataset(
    session_root: str | Path,
    *,
    allow_incomplete: bool = False,
    deep_audio: bool = False,
) -> ValidationReport:
    """Validate one supported session without raising for dataset corruption.

    Nonexistent paths, non-session paths, and the unsupported
    ``training_features`` profile remain explicit input errors. All located
    loader/layout content failures become findings.
    """

    if not isinstance(allow_incomplete, bool):
        raise TypeError("allow_incomplete must be a bool.")
    if not isinstance(deep_audio, bool):
        raise TypeError("deep_audio must be a bool.")
    root = Path(session_root)
    _reject_unsupported_input(root)
    try:
        dataset = SessionDataset.open(root, allow_incomplete=allow_incomplete)
    except DatasetLayoutError as exc:
        return _report((_error_finding(exc),), Statistics.empty())

    findings: list[Finding] = []
    builder = StatisticsBuilder(dataset.manifest)
    verified_markers: dict[str, Mapping[str, Any]] = {}
    loadable_shards = tuple(
        shard
        for shard in dataset.manifest.shards
        if shard.completion_state == "complete"
    )
    for shard in loadable_shards:
        try:
            # A zero-length public range read enters the shard, invoking the
            # loader's bounded streaming verification without loading payload.
            dataset.read_shard_audio(shard.shard_id, 0, 0)
            marker = dataset._verified_markers[shard.shard_id]
        except DatasetLayoutError as exc:
            findings.append(_error_finding(exc))
            builder.add_skipped_shard()
            continue
        verified_markers[shard.shard_id] = marker
        builder.add_verified_shard(shard, marker)
        if deep_audio:
            deep_finding = _check_wav_finiteness(root, shard.shard_id, marker)
            if deep_finding is not None:
                findings.append(deep_finding)

    findings.extend(_split_group_findings(root, dataset, verified_markers))

    if len(verified_markers) == len(loadable_shards):
        try:
            for item in dataset.iter_records():
                builder.add_frame(item)
                findings.extend(_portability_findings(item, root))
        except DatasetLayoutError as exc:
            findings.append(_error_finding(exc))
    else:
        # Bad shards are isolated; records from independently verified shards
        # remain useful and are streamed without attempting cross-shard claims.
        for item, warnings in _iter_verified_shard_records(
            root, dataset, verified_markers
        ):
            builder.add_frame(item)
            findings.extend(_warning_findings(warnings))

    return _report(_deduplicate(findings), builder.finish())


def _reject_unsupported_input(root: Path) -> None:
    if not root.exists():
        raise DatasetLayoutError(f"session {root}: session root does not exist.")
    if not root.is_dir():
        raise DatasetLayoutError(f"session {root}: session root is not a directory.")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetLayoutError(
            f"session {root}: not a finalized session directory; "
            "manifest.json is missing."
        )
    try:
        payload = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if isinstance(payload, dict) and payload.get("runtime_profile") == (
        "training_features"
    ):
        raise DatasetLayoutError(
            f"session {root} file manifest.json: unsupported runtime profile "
            "for dataset layout v1."
        )
    config_path = root / "config" / "session_config.json"
    try:
        config = json.loads(config_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if isinstance(config, dict) and config.get("runtime_profile") == (
        "training_features"
    ):
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: unsupported runtime "
            "profile for dataset layout v1."
        )


def _portability_findings(item: LoadedFrame, root: Path) -> tuple[Finding, ...]:
    warnings = validate_trace_projection(
        frame_to_trace_dict(item.frame),
        session_root=root,
        location=(
            f"shard {item.shard_id} file frames.jsonl line {item.line_number}.frame"
        ),
    )
    return _warning_findings(warnings)


def _warning_findings(warnings: tuple[LayoutWarning, ...]) -> tuple[Finding, ...]:
    return tuple(
        Finding(
            code="portability_warning",
            severity="warning",
            location=warning.location,
            detail=warning.message,
        )
        for warning in warnings
    )


def _iter_verified_shard_records(
    root: Path,
    dataset: SessionDataset,
    markers: Mapping[str, Mapping[str, Any]],
) -> Iterator[tuple[LoadedFrame, tuple[LayoutWarning, ...]]]:
    for shard in dataset.manifest.shards:
        marker = markers.get(shard.shard_id)
        if marker is None:
            continue
        path = root / "shards" / shard.shard_id / "frames.jsonl"
        with path.open("rb") as stream:
            for line_number, line in enumerate(stream, start=1):
                location = (
                    f"shard {shard.shard_id} file frames.jsonl line {line_number}"
                )
                record = _loader._parse_record(line, location, marker, root)
                warnings = validate_trace_projection(
                    record.frame,
                    session_root=root,
                    location=f"{location}.frame",
                )
                yield (
                    LoadedFrame(
                        dataset_frame_index=record.dataset_frame_index,
                        episode_id=record.episode_id,
                        audio_start_sample=record.audio_start_sample,
                        audio_end_sample=record.audio_end_sample,
                        frame=frame_from_trace_dict(record.frame),
                        shard_id=shard.shard_id,
                        line_number=line_number,
                    ),
                    warnings,
                )


def _split_group_findings(
    root: Path,
    dataset: SessionDataset,
    markers: Mapping[str, Mapping[str, Any]],
) -> tuple[Finding, ...]:
    group_by_episode = {
        episode.episode_id: episode.split_group for episode in dataset.manifest.episodes
    }
    findings: list[Finding] = []
    for shard_id in sorted(markers):
        episode_ids = markers[shard_id]["episode_ids"]
        unknown = [value for value in episode_ids if value not in group_by_episode]
        if unknown:
            text = (
                f"session {root} shard {shard_id}: marker names episodes absent "
                f"from manifest {unknown}."
            )
            findings.append(
                Finding(
                    code="episode_correspondence_error",
                    severity="error",
                    location=text,
                    detail=text.split(": ", 1)[-1],
                )
            )
            continue
        groups = {group_by_episode[value] for value in episode_ids}
        if len(groups) > 1:
            text = (
                f"session {root} shard {shard_id}: spans multiple split_group "
                f"values {sorted(groups)}."
            )
            findings.append(
                Finding(
                    code="split_group_crossing_shard",
                    severity="error",
                    location=text,
                    detail=text.split(": ", 1)[-1],
                )
            )
    return tuple(findings)


def _check_wav_finiteness(
    root: Path, shard_id: str, marker: Mapping[str, Any]
) -> Finding | None:
    audio = marker["audio"]
    if audio["path"] != "audio.wav" or audio["dtype"] != "float32":
        return None
    path = root / "shards" / shard_id / "audio.wav"
    location = f"shard {shard_id} file audio.wav"
    try:
        with path.open("rb") as stream:
            riff = stream.read(12)
            if len(riff) != 12 or riff[:4] != b"RIFF" or riff[8:] != b"WAVE":
                raise OSError("cannot locate RIFF/WAVE payload")
            scalar_offset = 0
            while True:
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    raise OSError("WAV data chunk is missing")
                chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
                if chunk_id != b"data":
                    stream.seek(chunk_size + (chunk_size & 1), 1)
                    continue
                remaining = chunk_size
                while remaining:
                    size = min(remaining, _DEEP_AUDIO_CHUNK_BYTES)
                    payload = stream.read(size)
                    if len(payload) != size:
                        raise OSError("truncated WAV data payload")
                    samples = np.frombuffer(payload, dtype="<f4")
                    finite = np.isfinite(samples)
                    if not bool(finite.all()):
                        first = int(np.flatnonzero(~finite)[0]) + scalar_offset
                        sample_index = first // audio["channels"]
                        return Finding(
                            code="non_finite_audio",
                            severity="error",
                            location=location,
                            detail=(
                                "non-finite float32 payload value at sample "
                                f"{sample_index}"
                            ),
                        )
                    scalar_offset += samples.size
                    remaining -= size
                return None
    except (OSError, ValueError) as exc:
        text = f"{location}: deep audio scan failed: {exc}"
        return Finding(
            code="audio_payload_unreadable",
            severity="error",
            location=text,
            detail=text.split(": ", 1)[-1],
        )


def _error_finding(error: DatasetLayoutError) -> Finding:
    text = str(error)
    return Finding(
        code=_finding_code(text),
        severity="error",
        location=text,
        detail=text.split(": ", 1)[-1],
    )


def _finding_code(text: str) -> str:
    lowered = text.lower()
    rules = (
        (("schema_version", "marker_version", "record_version"), "unknown_version"),
        (("manifest/marker",), "manifest_marker_disagreement"),
        (("configuration_sha256 mismatch",), "configuration_mismatch"),
        (("calibration sha256 mismatch",), "calibration_mismatch"),
        (("sha256 mismatch",), "checksum_mismatch"),
        (("missing calibration profile",), "missing_asset"),
        (
            (
                "missing file",
                "missing completion marker",
                "on-disk entries must be exactly",
                "missing shard directories",
            ),
            "missing_asset",
        ),
        (("final line is not newline-terminated",), "truncated_record_file"),
        (("bytes mismatch",), "file_size_mismatch"),
        (("non-monotonic timestamp",), "non_monotonic_timestamp"),
        (("non-negative and monotonic",), "non_monotonic_timestamp"),
        (("dataset_frame_index",), "index_gap"),
        (("audio_end_sample", "audio sample range is inverted"), "range_out_of_bounds"),
        (("audio_start_sample is non-monotonic",), "non_monotonic_audio_range"),
        (("audio_end_sample is non-monotonic",), "non_monotonic_audio_range"),
        (("overlaps across a reset",), "reset_overlap"),
        (("audio overlap",), "overlap_out_of_bounds"),
        (("line count",), "line_count_mismatch"),
        (("tail_samples",), "tail_mismatch"),
        (("decoded audio header",), "audio_header_mismatch"),
        (("channel count",), "channel_mismatch"),
        (("sample rate changed", "sample_rate_hz"), "sample_rate_mismatch"),
        (("dtype",), "dtype_mismatch"),
        (("duplicate producer frame_id",), "duplicate_frame_id"),
        (("timestamp mismatch", "timestamps_ms"), "timestamp_mismatch"),
        (("episode tiling",), "episode_tiling_error"),
        (
            (
                "boundary crossing",
                "interleaved",
                "missing record",
                "extra dataset record",
            ),
            "episode_correspondence_error",
        ),
        (("breaks tiling", "expected ordinal id"), "shard_tiling_error"),
        (
            ("manifest kind", "asset_id", "invalid or duplicate asset"),
            "asset_metadata_mismatch",
        ),
        (("symlink", "symbolic links"), "symlink_forbidden"),
        (
            ("unknown root entries", "unlisted shard", "non-directory entries"),
            "unknown_entry",
        ),
        (
            ("finalized-incomplete", "_staging", "in-progress or aborted"),
            "lifecycle_violation",
        ),
        (("not canonical", "exact manifest-v1 projection"), "non_canonical_data"),
        (("invalid json",), "invalid_json"),
        (("invalid manifest",), "invalid_manifest"),
        (("invalid frame v1", "cannot reconstruct audiosensorframe"), "invalid_frame"),
        (("record fields", "record must", "blank lines"), "invalid_record"),
        (("marker",), "invalid_marker"),
    )
    for needles, code in rules:
        if any(needle.lower() in lowered for needle in needles):
            return code
    return "layout_violation"


def _deduplicate(findings: list[Finding]) -> tuple[Finding, ...]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.code, finding.severity, finding.location)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return tuple(result)


def _report(findings: tuple[Finding, ...], statistics: Statistics) -> ValidationReport:
    errors = sum(finding.severity == "error" for finding in findings)
    warnings = sum(finding.severity == "warning" for finding in findings)
    status: ValidationStatus
    if errors:
        status = "failed"
    elif warnings:
        status = "passed_with_warnings"
    else:
        status = "passed"
    return ValidationReport(
        status=status,
        findings=findings,
        statistics=statistics,
        error_count=errors,
        warning_count=warnings,
    )


__all__ = [
    "Finding",
    "FindingSeverity",
    "ValidationReport",
    "ValidationStatus",
    "validate_dataset",
]
