"""Canonical streaming validation for session-sharded audio datasets."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
)
from isaac_audio_sensors.recording import loader as _loader
from isaac_audio_sensors.recording.layout import (
    DatasetLayoutError,
    LayoutWarning,
    VerifiedShard,
    verify_shard_completion,
)
from isaac_audio_sensors.recording.loader import LoadedFrame, SessionDataset
from isaac_audio_sensors.recording.statistics import Statistics, StatisticsBuilder
from isaac_audio_sensors.recording.time_gaps import (
    TimeGapCursor,
    advance_time_gap_cursor,
    plan_time_gap,
)

FindingSeverity = Literal["error", "warning"]
ValidationStatus = Literal["passed", "passed_with_warnings", "failed"]
_DEEP_AUDIO_CHUNK_BYTES = 1024 * 1024
MAX_FINDINGS_PER_CODE = 100


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
    finding_totals: dict[str, int]
    truncated_codes: tuple[str, ...]
    error_count: int
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return the full deterministic JSON report."""

        return {
            "error_count": self.error_count,
            "finding_totals": dict(self.finding_totals),
            "findings": [finding.to_dict() for finding in self.findings],
            "statistics": self.statistics.to_dict(),
            "status": self.status,
            "truncated_codes": list(self.truncated_codes),
            "warning_count": self.warning_count,
        }


class _FindingAccumulator:
    """Count every finding while retaining bounded deterministic examples."""

    def __init__(self, findings: Iterable[Finding] = ()) -> None:
        self._findings: list[Finding] = []
        self._totals: dict[tuple[str, FindingSeverity], int] = {}
        self._retained_counts: dict[tuple[str, FindingSeverity], int] = {}
        self._seen: set[tuple[str, FindingSeverity, str]] = set()
        self._truncated_codes: set[str] = set()
        self.extend(findings)

    def add(self, finding: Finding) -> None:
        """Count one finding and retain its first unique located example."""

        group = (finding.code, finding.severity)
        self._totals[group] = self._totals.get(group, 0) + 1
        retained_count = self._retained_counts.get(group, 0)
        if retained_count < MAX_FINDINGS_PER_CODE:
            deduplication_key = (
                finding.code,
                finding.severity,
                finding.location,
            )
            if deduplication_key in self._seen:
                return
            self._seen.add(deduplication_key)
            self._findings.append(finding)
            self._retained_counts[group] = retained_count + 1
        else:
            self._truncated_codes.add(finding.code)

    def add_unretained_occurrences(
        self,
        code: str,
        severity: FindingSeverity,
        count: int,
    ) -> None:
        """Count occurrences omitted by an upstream bounded result."""

        if count <= 0:
            return
        group = (code, severity)
        self._totals[group] = self._totals.get(group, 0) + count
        self._truncated_codes.add(code)

    def extend(self, findings: Iterable[Finding]) -> None:
        """Add findings in encounter order."""

        for finding in findings:
            self.add(finding)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(self._findings)

    @property
    def finding_totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for (code, _severity), count in sorted(self._totals.items()):
            totals[code] = totals.get(code, 0) + count
        return totals

    @property
    def truncated_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._truncated_codes))

    def severity_count(self, severity: FindingSeverity) -> int:
        return sum(
            count
            for (_code, finding_severity), count in self._totals.items()
            if finding_severity == severity
        )


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
    preserve_time_gaps = _preserve_time_gaps_enabled(root)
    try:
        dataset = SessionDataset.open(root, allow_incomplete=allow_incomplete)
    except DatasetLayoutError as exc:
        return _report(
            _FindingAccumulator(
                (_error_finding(exc, time_gap_mode=preserve_time_gaps),)
            ),
            Statistics.empty(),
        )

    findings = _FindingAccumulator()
    builder = StatisticsBuilder(dataset.manifest)
    verified_markers: dict[str, Mapping[str, Any]] = {}
    loadable_shards = tuple(
        shard
        for shard in dataset.manifest.shards
        if shard.completion_state == "complete"
    )
    for shard in loadable_shards:
        try:
            verified = verify_shard_completion(
                root / "shards" / shard.shard_id,
                manifest=dataset.manifest,
                max_overlap_samples=dataset._max_overlap_samples,
                retain_records=False,
            )
            marker = verified.marker
            dataset._verified_markers[shard.shard_id] = marker
        except DatasetLayoutError as exc:
            findings.add(
                _error_finding(exc, time_gap_mode=preserve_time_gaps)
            )
            builder.add_skipped_shard()
            continue
        verified_markers[shard.shard_id] = marker
        builder.add_verified_shard(shard, marker)
        _add_layout_warning_findings(findings, verified)
        if deep_audio:
            deep_finding = _check_wav_finiteness(root, shard.shard_id, marker)
            if deep_finding is not None:
                findings.add(deep_finding)

    findings.extend(_split_group_findings(root, dataset, verified_markers))
    time_gap_layout_error = False
    if preserve_time_gaps and len(verified_markers) == len(loadable_shards):
        try:
            findings.extend(_time_gap_findings(root, dataset, verified_markers))
        except DatasetLayoutError as exc:
            findings.add(_error_finding(exc, time_gap_mode=True))
            time_gap_layout_error = True

    if len(verified_markers) == len(loadable_shards) and not time_gap_layout_error:
        try:
            for item in dataset.iter_records():
                builder.add_frame(item)
        except DatasetLayoutError as exc:
            findings.add(
                _error_finding(exc, time_gap_mode=preserve_time_gaps)
            )
    else:
        # Bad shards are isolated; records from independently verified shards
        # remain useful and are streamed without attempting cross-shard claims.
        for item in _iter_verified_shard_records(root, dataset, verified_markers):
            builder.add_frame(item)

    return _report(findings, builder.finish())


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


def _preserve_time_gaps_enabled(root: Path) -> bool:
    try:
        payload = json.loads((root / "config/session_config.json").read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("preserve_time_gaps") is True


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


def _add_layout_warning_findings(
    findings: _FindingAccumulator, verified: VerifiedShard
) -> None:
    findings.extend(_warning_findings(verified.warnings))
    findings.add_unretained_occurrences(
        "portability_warning",
        "warning",
        verified.warning_count - len(verified.warnings),
    )


def _iter_verified_shard_records(
    root: Path,
    dataset: SessionDataset,
    markers: Mapping[str, Mapping[str, Any]],
) -> Iterator[LoadedFrame]:
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
                yield LoadedFrame(
                    dataset_frame_index=record.dataset_frame_index,
                    episode_id=record.episode_id,
                    audio_start_sample=record.audio_start_sample,
                    audio_end_sample=record.audio_end_sample,
                    frame=frame_from_trace_dict(record.frame),
                    shard_id=shard.shard_id,
                    line_number=line_number,
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


def _time_gap_findings(
    root: Path,
    dataset: SessionDataset,
    markers: Mapping[str, Mapping[str, Any]],
) -> tuple[Finding, ...]:
    """Reconcile sample placement, diagnostics and shard offsets."""

    config = json.loads((root / "config/session_config.json").read_bytes())
    sample_rate_hz = int(config["sample_rate_hz"])
    window_sample_count = int(config["window_sample_count"])
    hop_sample_count = int(config["hop_sample_count"])
    shard_bases: dict[str, int] = {}
    audio_cursor = 0
    for shard in dataset.manifest.shards:
        marker = markers.get(shard.shard_id)
        if marker is None:
            continue
        shard_bases[shard.shard_id] = audio_cursor
        audio_cursor += int(marker["audio"]["sample_count"])

    cursors: dict[str, TimeGapCursor] = {}
    next_audio_before_gap: dict[str, int] = {}
    findings: list[Finding] = []
    for item in dataset.iter_records():
        location = (
            f"shard {item.shard_id} file frames.jsonl line {item.line_number}"
        )
        cursor = cursors.get(item.episode_id, TimeGapCursor())
        actual_start = shard_bases[item.shard_id] + item.audio_start_sample
        before_gap = next_audio_before_gap.get(item.episode_id, actual_start)
        frame = item.frame
        try:
            plan = plan_time_gap(
                cursor,
                placement_sequence=item.dataset_frame_index,
                start_time_s=frame.start_time_s,
                end_time_s=frame.end_time_s,
                timestamp_ms=frame.timestamp_ms,
                sample_rate_hz=sample_rate_hz,
                window_sample_count=window_sample_count,
                hop_sample_count=hop_sample_count,
                session_audio_start_sample=before_gap,
            )
        except (TypeError, ValueError) as exc:
            detail = str(exc)
            code = (
                "non_monotonic_window_placement"
                if "non-monotonic timestamp" in detail
                or "overlapping window placement" in detail
                else "time_gap_metadata_mismatch"
            )
            findings.append(
                Finding(
                    code=code,
                    severity="error",
                    location=location,
                    detail=detail,
                )
            )
            continue

        if actual_start != plan.session_audio_start_sample:
            findings.append(
                Finding(
                    code="unexpected_audio_gap",
                    severity="error",
                    location=location,
                    detail=(
                        f"audio starts at concatenated sample {actual_start}, "
                        f"expected {plan.session_audio_start_sample}"
                    ),
                )
            )
        recording = frame.diagnostics.get("recording")
        attached = (
            recording.get("time_gap")
            if isinstance(recording, dict)
            else None
        )
        if attached != plan.diagnostic():
            findings.append(
                Finding(
                    code="time_gap_metadata_mismatch",
                    severity="error",
                    location=location,
                    detail="recording.time_gap disagrees with recomputed placement",
                )
            )
        cursors[item.episode_id] = advance_time_gap_cursor(
            cursor,
            plan,
            timestamp_ms=frame.timestamp_ms,
            hop_sample_count=hop_sample_count,
        )
        next_audio_before_gap[item.episode_id] = (
            plan.session_audio_start_sample + hop_sample_count
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


def _error_finding(
    error: DatasetLayoutError,
    *,
    time_gap_mode: bool = False,
) -> Finding:
    text = str(error)
    return Finding(
        code=_finding_code(text, time_gap_mode=time_gap_mode),
        severity="error",
        location=text,
        detail=text.split(": ", 1)[-1],
    )


def _finding_code(text: str, *, time_gap_mode: bool = False) -> str:
    lowered = text.lower()
    if time_gap_mode and (
        "non-monotonic timestamp" in lowered
        or "non-negative and monotonic" in lowered
    ):
        return "non_monotonic_window_placement"
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


def _report(
    findings: _FindingAccumulator, statistics: Statistics
) -> ValidationReport:
    errors = findings.severity_count("error")
    warnings = findings.severity_count("warning")
    status: ValidationStatus
    if errors:
        status = "failed"
    elif warnings:
        status = "passed_with_warnings"
    else:
        status = "passed"
    return ValidationReport(
        status=status,
        findings=findings.findings,
        statistics=statistics,
        finding_totals=findings.finding_totals,
        truncated_codes=findings.truncated_codes,
        error_count=errors,
        warning_count=warnings,
    )


__all__ = [
    "Finding",
    "FindingSeverity",
    "MAX_FINDINGS_PER_CODE",
    "ValidationReport",
    "ValidationStatus",
    "validate_dataset",
]
