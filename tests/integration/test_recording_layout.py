"""Session and shard layout tests."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
)
from isaac_audio_sensors.recording import (
    DATASET_FRAME_RECORD_VERSION,
    SHARD_COMPLETION_VERSION,
    DatasetLayoutError,
    ShardPlanner,
    build_dataset_frame_record,
    canonical_configuration_bytes,
    classify_session_lifecycle,
    configuration_sha256,
    episode_id,
    episode_seed,
    parse_dataset_frame_record,
    plan_shards,
    serialize_dataset_frame_record,
    shard_id,
    validate_record_sequence,
    validate_session_layout,
    validate_trace_projection,
    verify_shard_completion,
    verify_shard_tiling,
)
from isaac_audio_sensors.recording.layout import (
    MAX_STREAMING_WARNINGS_PER_SHARD,
)
from isaac_audio_sensors.recording.serialization import (
    manifest_to_dict,
    read_dataset_manifest,
    write_dataset_manifest,
)
from tests.recording_fixture import (
    CHANNEL_ORDER,
    _write_float32_wav,
    regenerate_reference_dataset,
)

REFERENCE_DIR = Path("tests/fixtures/recording/session")


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_pretty(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_canonical(path: Path, payload: dict) -> None:
    path.write_bytes(canonical_configuration_bytes(payload))


def _session(tmp_path: Path, name: str = "session") -> Path:
    return regenerate_reference_dataset(tmp_path / name)


def _refresh_asset(root: Path, shard_value: str, filename: str) -> None:
    shard_dir = root / "shards" / shard_value
    asset_path = shard_dir / filename
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    marker_path = shard_dir / "shard.complete.json"
    marker = _json(marker_path)
    entry = next(item for item in marker["files"] if item["path"] == filename)
    entry["bytes"] = asset_path.stat().st_size
    entry["sha256"] = digest
    _write_pretty(marker_path, marker)
    manifest_path = root / "manifest.json"
    manifest = _json(manifest_path)
    shard = next(item for item in manifest["shards"] if item["shard_id"] == shard_value)
    asset = next(
        item for item in shard["assets"] if item["path"].endswith(f"/{filename}")
    )
    asset["sha256"] = digest
    _write_pretty(manifest_path, manifest)


def _frame(
    *,
    frame_id: str = "producer_0",
    timestamp_ms: int = 0,
    waveform_paths: tuple[str, ...] = (),
    diagnostics: dict | None = None,
    detections: tuple[AudioDetection, ...] = (),
) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=frame_id,
        timestamp_ms=timestamp_ms,
        backend_id="tdoa_synthetic",
        array_id="array",
        sample_rate_hz=48_000,
        frame_index=0,
        provenance="synthetic/core",
        waveform_paths=waveform_paths,
        detections=detections,
        diagnostics={} if diagnostics is None else diagnostics,
    )


def _record(
    index: int,
    start: int,
    end: int,
    *,
    episode: str = "episode_00000",
    producer_id: str | None = None,
):
    return build_dataset_frame_record(
        dataset_frame_index=index,
        episode_id_value=episode,
        audio_start_sample=start,
        audio_end_sample=end,
        frame=_frame(
            frame_id=producer_id or f"producer_{index}",
            timestamp_ms=index,
        ),
    )


def _mutate_frame_line(
    root: Path,
    shard_value: str,
    line_index: int,
    mutate,
) -> None:
    path = root / "shards" / shard_value / "frames.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[line_index])
    mutate(payload)
    lines[line_index] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _refresh_asset(root, shard_value, "frames.jsonl")


def test_reference_regeneration_is_byte_identical_and_relocatable(tmp_path):
    first = regenerate_reference_dataset(tmp_path / "first")
    second = regenerate_reference_dataset(tmp_path / "second")

    assert _hash_tree(first) == _hash_tree(second)
    for relative in _hash_tree(first):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

    relocated = tmp_path / "relocated under a different absolute path"
    shutil.copytree(first, relocated)
    result = validate_session_layout(relocated)
    assert result.lifecycle_state == "complete"
    assert result.warnings == ()
    assert [item.marker["frame_count"] for item in result.shards] == [4, 3]


def test_reference_manifest_and_frames_round_trip_unchanged(tmp_path):
    root = _session(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = read_dataset_manifest(manifest_path)
    written = write_dataset_manifest(manifest, tmp_path / "round_trip.json")

    assert written.read_bytes() == manifest_path.read_bytes()
    assert manifest_to_dict(manifest) == _json(manifest_path)
    for trace_path in sorted(root.glob("shards/*/frames.jsonl")):
        for line_number, line in enumerate(
            trace_path.read_text(encoding="utf-8").splitlines(keepends=True), start=1
        ):
            record = parse_dataset_frame_record(
                line,
                location=f"{trace_path} line {line_number}",
                session_root=root,
            )
            restored = frame_from_trace_dict(record.frame)
            assert frame_to_trace_dict(restored) == record.frame
            assert serialize_dataset_frame_record(record) == line


def test_ids_planners_records_config_seed_and_import_safety(tmp_path):
    assert episode_id(0) == "episode_00000"
    assert episode_id(99_999) == "episode_99999"
    assert shard_id(7) == "shard_00007"
    with pytest.raises(ValueError, match="five-digit"):
        episode_id(100_000)
    with pytest.raises(ValueError, match="five-digit"):
        shard_id(100_000)

    aligned = plan_shards(
        ((0, "a", 2), (1, "a", 2), (2, "b", 3)),
        shard_max_frames=4,
    )
    assert [(item.start_frame, item.frame_count) for item in aligned] == [
        (0, 4),
        (4, 3),
    ]
    assert aligned[0].episode_ids == ("episode_00000", "episode_00001")
    unaligned = plan_shards(
        ((0, "a", 3), (1, "b", 4)),
        shard_max_frames=4,
        shard_episode_aligned=False,
    )
    assert [(item.start_frame, item.frame_count) for item in unaligned] == [
        (0, 4),
        (4, 3),
    ]
    assert unaligned[0].episode_ids == ("episode_00000", "episode_00001")

    record = _record(0, 0, 10)
    line = serialize_dataset_frame_record(record)
    assert line.endswith("\n") and " " not in line
    assert parse_dataset_frame_record(line, sample_count=10) == record
    assert json.loads(line)["record_version"] == DATASET_FRAME_RECORD_VERSION

    config = {"z": 1, "nested": {"asset_path": "assets/a.wav"}, "a": True}
    expected = b'{"a":true,"nested":{"asset_path":"assets/a.wav"},"z":1}\n'
    assert canonical_configuration_bytes(config) == expected
    assert configuration_sha256(config) == hashlib.sha256(expected).hexdigest()
    assert episode_seed("known_dataset", 123_456_789, 42) == 1_175_325_540_945_552_260

    before = sorted(tmp_path.iterdir())
    plan_shards(((0, "group", 7),), shard_max_frames=3)
    assert sorted(tmp_path.iterdir()) == before

    source_root = Path("src").resolve()
    code = (
        "import sys;"
        f"sys.path.insert(0,{str(source_root)!r});"
        "import isaac_audio_sensors.recording.layout;"
        "bad={'soundfile','omni','torch'} & set(sys.modules);"
        "raise SystemExit(1 if bad else 0)"
    )
    completed = subprocess.run([sys.executable, "-c", code], check=False)
    assert completed.returncode == 0


@pytest.mark.parametrize(
    ("records", "kwargs", "message"),
    [
        (
            (_record(0, 0, 400), _record(1, 100, 500)),
            {"max_overlap_samples": 160},
            "exceeds configured",
        ),
        (
            (_record(0, 0, 400), _record(1, 240, 640)),
            {"reset_frame_indices": (1,)},
            "reset boundary",
        ),
        (
            (_record(0, 0, 400), _record(1, 200, 300)),
            {},
            "audio_end_sample is non-monotonic",
        ),
        (
            (_record(0, 200, 400), _record(1, 100, 500)),
            {},
            "audio_start_sample is non-monotonic",
        ),
    ],
)
def test_join_sequence_adversaries_are_located(records, kwargs, message):
    with pytest.raises(DatasetLayoutError, match=message):
        validate_record_sequence(
            records, sample_count=1_000, location="shard x", **kwargs
        )


def test_join_bounds_empty_ranges_and_bad_json_records_are_enforced():
    empty = _record(0, 7, 7)
    validate_record_sequence((empty,), sample_count=7)

    with pytest.raises(DatasetLayoutError, match="exceeds sample_count"):
        validate_record_sequence((_record(0, 0, 11),), sample_count=10)
    with pytest.raises(DatasetLayoutError, match="non-negative"):
        build_dataset_frame_record(
            dataset_frame_index=0,
            episode_id_value="episode_00000",
            audio_start_sample=-1,
            audio_end_sample=1,
            frame=_frame(),
        )
    with pytest.raises(DatasetLayoutError, match="inverted"):
        build_dataset_frame_record(
            dataset_frame_index=0,
            episode_id_value="episode_00000",
            audio_start_sample=2,
            audio_end_sample=1,
            frame=_frame(),
        )
    with pytest.raises(DatasetLayoutError, match="newline-terminated"):
        parse_dataset_frame_record(serialize_dataset_frame_record(empty).rstrip("\n"))


def test_jsonl_line_count_indices_and_shard_tiling_fail_located(tmp_path):
    root = _session(tmp_path, "line_count")
    shard_dir = root / "shards" / "shard_00000"
    frames_path = shard_dir / "frames.jsonl"
    lines = frames_path.read_text(encoding="utf-8").splitlines(keepends=True)
    frames_path.write_text("".join(lines[:-1]), encoding="utf-8")
    _refresh_asset(root, "shard_00000", "frames.jsonl")
    with pytest.raises(DatasetLayoutError, match="line count 3.*frame_count 4"):
        verify_shard_completion(shard_dir)

    extra = _session(tmp_path, "extra_line")
    extra_path = extra / "shards/shard_00000/frames.jsonl"
    extra_lines = extra_path.read_text(encoding="utf-8").splitlines()
    extra_payload = json.loads(extra_lines[-1])
    extra_payload["dataset_frame_index"] = 4
    extra_payload["audio_start_sample"] = 1_280
    extra_payload["audio_end_sample"] = 1_280
    extra_payload["frame"]["frame_id"] = "extra_producer"
    extra_lines.append(
        json.dumps(extra_payload, sort_keys=True, separators=(",", ":"))
    )
    extra_path.write_text("\n".join(extra_lines) + "\n", encoding="utf-8")
    _refresh_asset(extra, "shard_00000", "frames.jsonl")
    with pytest.raises(DatasetLayoutError, match="line count 5.*frame_count 4"):
        verify_shard_completion(extra / "shards/shard_00000")

    for name, replacement in (("gap", 2), ("duplicate", 0)):
        altered = _session(tmp_path, name)
        _mutate_frame_line(
            altered,
            "shard_00000",
            1,
            lambda payload, value=replacement: payload.__setitem__(
                "dataset_frame_index", value
            ),
        )
        with pytest.raises(DatasetLayoutError, match="line 2.*dataset_frame_index"):
            verify_shard_completion(altered / "shards" / "shard_00000")

    with pytest.raises(DatasetLayoutError, match="breaks tiling"):
        verify_shard_tiling(
            (
                {"shard_id": "shard_00000", "start_frame": 0, "frame_count": 4},
                {"shard_id": "shard_00001", "start_frame": 5, "frame_count": 3},
            )
        )


@pytest.mark.parametrize(
    "case",
    [
        "shard_id",
        "missing_frames",
        "missing_audio",
        "duplicate_file",
        "extra_file",
        "traversal",
        "both_audio",
        "bytes",
        "sha256",
        "container",
        "subtype",
        "channels",
        "sample_rate_hz",
        "dtype",
        "sample_count",
    ],
)
def test_marker_schema_file_and_audio_adversaries_are_located(tmp_path, case):
    root = _session(tmp_path, case)
    shard_dir = root / "shards" / "shard_00000"
    marker_path = shard_dir / "shard.complete.json"
    marker = _json(marker_path)
    if case == "shard_id":
        marker["shard_id"] = "shard_00001"
    elif case == "missing_frames":
        marker["files"] = [
            item for item in marker["files"] if item["path"] != "frames.jsonl"
        ]
    elif case == "missing_audio":
        marker["files"] = [
            item for item in marker["files"] if item["path"] == "frames.jsonl"
        ]
    elif case == "duplicate_file":
        marker["files"].append(copy.deepcopy(marker["files"][0]))
    elif case == "extra_file":
        marker["files"].append({"path": "extra.bin", "bytes": 0, "sha256": "0" * 64})
    elif case == "traversal":
        marker["files"][0]["path"] = "../frames.jsonl"
    elif case == "both_audio":
        marker["files"].append({"path": "audio.flac", "bytes": 0, "sha256": "0" * 64})
    elif case == "bytes":
        marker["files"][0]["bytes"] += 1
    elif case == "sha256":
        marker["files"][0]["sha256"] = "0" * 64
    elif case == "container":
        marker["audio"]["container"] = "flac"
    elif case == "subtype":
        marker["audio"]["subtype"] = "PCM_16"
    elif case == "channels":
        marker["audio"]["channels"] = 5
    elif case == "sample_rate_hz":
        marker["audio"]["sample_rate_hz"] = 44_100
    elif case == "dtype":
        marker["audio"]["dtype"] = "int16"
    elif case == "sample_count":
        marker["audio"]["sample_count"] += 1
    _write_pretty(marker_path, marker)

    with pytest.raises(
        DatasetLayoutError, match="shard shard_00000|containing directory"
    ):
        verify_shard_completion(shard_dir)


def test_marker_manifest_channel_count_and_duplicate_producer_id(tmp_path):
    root = _session(tmp_path, "manifest_channels")
    payload = _json(root / "manifest.json")
    payload["channel_order"] = payload["channel_order"][:3]
    _write_pretty(root / "manifest.json", payload)
    manifest = read_dataset_manifest(root / "manifest.json")
    with pytest.raises(DatasetLayoutError, match="channel count.*channel_order"):
        verify_shard_completion(root / "shards" / "shard_00000", manifest=manifest)

    duplicate = _session(tmp_path, "duplicate_producer")
    first = json.loads(
        (duplicate / "shards/shard_00000/frames.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )["frame"]["frame_id"]
    _mutate_frame_line(
        duplicate,
        "shard_00000",
        1,
        lambda payload: payload["frame"].__setitem__("frame_id", first),
    )
    with pytest.raises(DatasetLayoutError, match="line 2.*duplicate producer"):
        verify_shard_completion(duplicate / "shards" / "shard_00000")


@pytest.mark.parametrize(
    "case",
    [
        "accepted",
        "warning",
        "line_count",
        "overlap",
        "index",
        "duplicate_producer",
        "tail",
    ],
)
def test_streaming_shard_verification_matches_retained_mode(tmp_path, case):
    root = _session(tmp_path, case)
    shard_dir = root / "shards/shard_00000"
    if case == "warning":
        _mutate_frame_line(
            root,
            "shard_00000",
            0,
            lambda payload: payload["frame"]["diagnostics"].__setitem__(
                "debug_path", "/tmp/diagnostic-only"
            ),
        )
    elif case == "line_count":
        frames_path = shard_dir / "frames.jsonl"
        lines = frames_path.read_text(encoding="utf-8").splitlines(keepends=True)
        frames_path.write_text("".join(lines[:-1]), encoding="utf-8")
        _refresh_asset(root, "shard_00000", "frames.jsonl")
    elif case == "overlap":
        _mutate_frame_line(
            root,
            "shard_00000",
            1,
            lambda payload: payload.__setitem__("audio_start_sample", 0),
        )
    elif case == "index":
        _mutate_frame_line(
            root,
            "shard_00000",
            1,
            lambda payload: payload.__setitem__("dataset_frame_index", 7),
        )
    elif case == "duplicate_producer":
        first_id = json.loads(
            (shard_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )["frame"]["frame_id"]
        _mutate_frame_line(
            root,
            "shard_00000",
            1,
            lambda payload: payload["frame"].__setitem__("frame_id", first_id),
        )
    elif case == "tail":
        marker_path = shard_dir / "shard.complete.json"
        marker = _json(marker_path)
        marker["tail_samples"] += 1
        _write_pretty(marker_path, marker)

    outcomes = []
    for retain_records in (True, False):
        try:
            outcomes.append(
                ("accepted", verify_shard_completion(
                    shard_dir, retain_records=retain_records
                ))
            )
        except DatasetLayoutError as exc:
            outcomes.append(("rejected", str(exc)))

    assert outcomes[0][0] == outcomes[1][0]
    if outcomes[0][0] == "rejected":
        assert outcomes[0][1] == outcomes[1][1]
    else:
        retained = outcomes[0][1]
        streamed = outcomes[1][1]
        assert retained.records
        assert streamed.records == ()
        assert streamed.marker == retained.marker
        assert streamed.warnings == retained.warnings


def test_streaming_session_validation_returns_empty_shard_records(tmp_path):
    root = _session(tmp_path, "streaming_session")

    retained = validate_session_layout(root)
    streamed = validate_session_layout(root, retain_records=False)

    assert streamed.manifest == retained.manifest
    assert streamed.warnings == retained.warnings
    assert [item.marker for item in streamed.shards] == [
        item.marker for item in retained.shards
    ]
    assert all(item.records == () for item in streamed.shards)


def test_streaming_warning_retention_is_bounded_counted_and_deterministic(tmp_path):
    root = _session(tmp_path, "streaming_warnings")
    warning_total = MAX_STREAMING_WARNINGS_PER_SHARD + 7
    diagnostics = {
        f"host_path_{index:03d}": f"/var/tmp/layout/diagnostic_{index:03d}.log"
        for index in range(warning_total)
    }
    _mutate_frame_line(
        root,
        "shard_00000",
        0,
        lambda payload: payload["frame"].__setitem__("diagnostics", diagnostics),
    )
    shard_dir = root / "shards/shard_00000"

    retained = verify_shard_completion(shard_dir)
    streamed = verify_shard_completion(shard_dir, retain_records=False)
    repeated = verify_shard_completion(shard_dir, retain_records=False)

    assert len(retained.warnings) == retained.warning_count == warning_total
    assert len(streamed.warnings) == MAX_STREAMING_WARNINGS_PER_SHARD
    assert streamed.warning_count == warning_total
    assert streamed.warnings == retained.warnings[:MAX_STREAMING_WARNINGS_PER_SHARD]
    assert repeated.warnings == streamed.warnings
    assert repeated.warning_count == streamed.warning_count

    retained_session = validate_session_layout(root)
    streamed_session = validate_session_layout(root, retain_records=False)
    assert retained_session.total_warning_count == warning_total
    assert streamed_session.total_warning_count == warning_total
    assert retained_session.warnings == retained.warnings
    assert streamed_session.warnings == streamed.warnings


def test_projection_paths_symlinks_diagnostics_and_identity(tmp_path):
    root = tmp_path / "portable"
    asset = root / "assets" / "sample.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"sample")
    detection = AudioDetection(
        detection_id="detection",
        source_id="source",
        class_label="tone",
        detection_mode="scheduled_known_source",
        timestamp_ms=0,
        ground_truth_bearing_deg=0.0,
        source_distance_m=1.0,
        doa=DoaEstimate(estimated_bearing_deg=0.0),
        audio_asset_path="generated://tone/440hz",
        diagnostics={},
    )
    payload = frame_to_trace_dict(
        _frame(waveform_paths=("assets/sample.bin",), detections=(detection,))
    )
    assert validate_trace_projection(payload, session_root=root) == ()
    record = build_dataset_frame_record(
        dataset_frame_index=0,
        episode_id_value="episode_00000",
        audio_start_sample=0,
        audio_end_sample=0,
        frame=payload,
        session_root=root,
    )
    assert record.frame is payload
    assert json.loads(serialize_dataset_frame_record(record))["frame"] == payload

    for bad in ("/tmp/host.wav", "C:\\capture\\host.wav", "assets\\host.wav"):
        changed = copy.deepcopy(payload)
        changed["waveform_paths"] = [bad]
        with pytest.raises(DatasetLayoutError, match=r"waveform_paths\[0\]"):
            validate_trace_projection(changed, session_root=root)

    changed = copy.deepcopy(payload)
    changed["detections"][0]["audio_asset_path"] = "/tmp/source.wav"
    with pytest.raises(DatasetLayoutError, match="audio_asset_path"):
        validate_trace_projection(changed, session_root=root)

    diagnostic = frame_to_trace_dict(
        _frame(diagnostics={"host_debug_path": "/tmp/allowed-in-diagnostics.wav"})
    )
    warnings = validate_trace_projection(diagnostic)
    assert len(warnings) == 1
    assert "absolute filesystem path" in warnings[0].message

    session = _session(tmp_path, "symlink")
    (session / "linked").symlink_to(session / "config")
    with pytest.raises(DatasetLayoutError, match="symlink"):
        validate_session_layout(session)


def test_profiles_and_lifecycle_signatures(tmp_path):
    no_manifest = tmp_path / "no_manifest"
    no_manifest.mkdir()
    assert classify_session_lifecycle(no_manifest) == "in-progress-or-aborted"
    with pytest.raises(DatasetLayoutError, match="in-progress or aborted"):
        validate_session_layout(no_manifest)

    unknown = _session(tmp_path, "unknown_root_entry")
    (unknown / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(DatasetLayoutError, match="unknown root entries"):
        validate_session_layout(unknown)

    staging = _session(tmp_path, "staging")
    (staging / "_staging").mkdir()
    with pytest.raises(DatasetLayoutError, match="alongside manifest"):
        validate_session_layout(staging)

    incomplete = _session(tmp_path, "incomplete")
    manifest = _json(incomplete / "manifest.json")
    manifest["completion_state"] = "incomplete"
    _write_pretty(incomplete / "manifest.json", manifest)
    result = validate_session_layout(incomplete)
    assert result.lifecycle_state == "finalized-incomplete"
    assert result.manifest.completion_state == "incomplete"
    with pytest.raises(DatasetLayoutError, match="finalized-incomplete"):
        validate_session_layout(incomplete, allow_incomplete=False)

    manifest_profile = _session(tmp_path, "manifest_profile")
    manifest = _json(manifest_profile / "manifest.json")
    manifest["runtime_profile"] = "training_features"
    _write_pretty(manifest_profile / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match="unsupported runtime profile"):
        validate_session_layout(manifest_profile)

    config_profile = _session(tmp_path, "config_profile")
    config_path = config_profile / "config/session_config.json"
    config = _json(config_path)
    config["runtime_profile"] = "training_features"
    _write_canonical(config_path, config)
    manifest = _json(config_profile / "manifest.json")
    manifest["configuration_sha256"] = hashlib.sha256(
        config_path.read_bytes()
    ).hexdigest()
    _write_pretty(config_profile / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match="unsupported runtime profile"):
        validate_session_layout(config_profile)


def test_config_hash_seed_and_split_group_safety(tmp_path):
    changed_config = _session(tmp_path, "changed_config")
    config_path = changed_config / "config/session_config.json"
    config = _json(config_path)
    config["session_seed"] += 1
    _write_canonical(config_path, config)
    with pytest.raises(DatasetLayoutError, match="configuration_sha256 mismatch"):
        validate_session_layout(changed_config)

    root = _session(tmp_path, "split_group")
    manifest = _json(root / "manifest.json")
    manifest["episodes"][1]["scene_id"] = "scene_b"
    manifest["episodes"][1]["split_group"] = "scene_b"
    _write_pretty(root / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match="spans multiple split_group"):
        validate_session_layout(root)

    stored = _json(REFERENCE_DIR / "config/session_config.json")
    reference_manifest = read_dataset_manifest(REFERENCE_DIR / "manifest.json")
    assert [episode.seed for episode in reference_manifest.episodes] == [
        episode_seed(stored["dataset_id"], stored["session_seed"], ordinal)
        for ordinal in range(3)
    ]


@pytest.mark.parametrize(
    "case", ["episode_tiling", "timestamp_length", "timestamp_value"]
)
def test_episode_correspondence_manifest_adversaries(tmp_path, case):
    root = _session(tmp_path, case)
    manifest = _json(root / "manifest.json")
    if case == "episode_tiling":
        episode = manifest["episodes"][1]
        episode["start_frame"] = 3
        episode["end_frame"] = 4
        episode["reset_markers"][0]["frame_index"] = 4
        message = "breaks episode tiling"
    elif case == "timestamp_length":
        manifest["episodes"][0]["timestamps_ms"].append(6)
        message = "timestamps_ms length"
    else:
        manifest["episodes"][0]["timestamps_ms"][1] = 6
        message = "timestamp mismatch"
    _write_pretty(root / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match=message):
        validate_session_layout(root)


def test_episode_interleaving_is_detected_at_first_frame(tmp_path):
    root = _session(tmp_path)
    _mutate_frame_line(
        root,
        "shard_00000",
        1,
        lambda payload: (
            payload.__setitem__("episode_id", "episode_00001"),
            payload["frame"].__setitem__("frame_id", "interleaved_unique"),
        ),
    )
    with pytest.raises(DatasetLayoutError, match="interleaved.*frame 1"):
        validate_session_layout(root)


def test_complete_session_missing_config_calibration_and_unlisted_shard(tmp_path):
    missing_config = _session(tmp_path, "missing_config")
    (missing_config / "config/session_config.json").unlink()
    with pytest.raises(DatasetLayoutError, match="config/session_config.json: missing"):
        validate_session_layout(missing_config)

    missing_calibration = _session(tmp_path, "missing_calibration")
    manifest = _json(missing_calibration / "manifest.json")
    manifest["calibration_profile"] = {
        "path": "calibration/missing.json",
        "profile_id": "missing",
        "profile_version": "v1",
        "sha256": "0" * 64,
    }
    _write_pretty(missing_calibration / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match="missing calibration profile"):
        validate_session_layout(missing_calibration)

    bad_calibration = _session(tmp_path, "bad_calibration")
    calibration_path = bad_calibration / "calibration/profile.json"
    calibration_path.parent.mkdir()
    calibration_path.write_text("{}\n", encoding="utf-8")
    manifest = _json(bad_calibration / "manifest.json")
    manifest["calibration_profile"] = {
        "path": "calibration/profile.json",
        "profile_id": "profile",
        "profile_version": "v1",
        "sha256": "0" * 64,
    }
    _write_pretty(bad_calibration / "manifest.json", manifest)
    with pytest.raises(DatasetLayoutError, match="calibration sha256 mismatch"):
        validate_session_layout(bad_calibration)

    unlisted = _session(tmp_path, "unlisted")
    (unlisted / "shards/shard_00002").mkdir()
    with pytest.raises(DatasetLayoutError, match="unlisted shard"):
        validate_session_layout(unlisted)


def test_manifest_marker_asset_correspondence_adversaries(tmp_path):
    missing = _session(tmp_path, "marker_absent_manifest")
    payload = _json(missing / "manifest.json")
    payload["shards"][0]["assets"] = payload["shards"][0]["assets"][:1]
    _write_pretty(missing / "manifest.json", payload)
    with pytest.raises(DatasetLayoutError, match="manifest/marker file mismatch"):
        validate_session_layout(missing)

    extra = _session(tmp_path, "manifest_absent_marker")
    payload = _json(extra / "manifest.json")
    payload["shards"][0]["assets"].append(
        {
            "asset_id": "shard_00000.visual",
            "kind": "visual_sync",
            "path": "shards/shard_00000/visual.json",
            "sha256": "0" * 64,
        }
    )
    _write_pretty(extra / "manifest.json", payload)
    with pytest.raises(DatasetLayoutError, match="manifest/marker file mismatch"):
        validate_session_layout(extra)

    bad_kind = _session(tmp_path, "bad_kind")
    payload = _json(bad_kind / "manifest.json")
    payload["shards"][0]["assets"][1]["kind"] = "audio_flac"
    _write_pretty(bad_kind / "manifest.json", payload)
    with pytest.raises(DatasetLayoutError, match="audio_flac assets must use .flac"):
        validate_session_layout(bad_kind)


def test_oversized_aligned_planning_is_bounded_and_repeatable():
    def run_once():
        planner = ShardPlanner(shard_max_frames=4, shard_episode_aligned=True)
        boundaries = []
        for _ in range(2):
            boundaries.extend(planner.feed_frame(0, "scene_a"))
        boundaries.extend(planner.end_episode(0))
        for _ in range(11):
            boundaries.extend(planner.feed_frame(1, "scene_a"))
            buffered, opened = planner.staging_inventory
            assert buffered <= 4
            assert opened <= 4
        boundaries.extend(planner.end_episode(1))
        boundaries.extend(planner.finish())
        return (
            tuple(boundaries),
            planner.max_buffered_frames,
            planner.max_open_shard_frames,
        )

    first = run_once()
    second = run_once()
    assert first == second
    boundaries = first[0]
    assert [(item.start_frame, item.frame_count) for item in boundaries] == [
        (0, 2),
        (2, 4),
        (6, 4),
        (10, 3),
    ]
    assert [item.exclusive_oversized_episode for item in boundaries] == [
        False,
        True,
        True,
        True,
    ]
    assert first[1:] == (4, 2)


def test_all_empty_and_zero_sample_tail_semantics(tmp_path):
    all_empty = _session(tmp_path, "all_empty")
    for line_index in range(3):
        _mutate_frame_line(
            all_empty,
            "shard_00001",
            line_index,
            lambda payload: (
                payload.__setitem__("audio_start_sample", 0),
                payload.__setitem__("audio_end_sample", 0),
            ),
        )
    marker_path = all_empty / "shards/shard_00001/shard.complete.json"
    marker = _json(marker_path)
    marker["tail_samples"] = marker["audio"]["sample_count"]
    _write_pretty(marker_path, marker)
    assert verify_shard_completion(marker_path.parent).marker["tail_samples"] == 720
    marker["tail_samples"] = 719
    _write_pretty(marker_path, marker)
    with pytest.raises(DatasetLayoutError, match="tail_samples"):
        verify_shard_completion(marker_path.parent)

    zero = _session(tmp_path, "zero")
    for line_index in range(3):
        _mutate_frame_line(
            zero,
            "shard_00001",
            line_index,
            lambda payload: (
                payload.__setitem__("audio_start_sample", 0),
                payload.__setitem__("audio_end_sample", 0),
            ),
        )
    audio_path = zero / "shards/shard_00001/audio.wav"
    _write_float32_wav(
        audio_path,
        np.zeros((0, len(CHANNEL_ORDER)), dtype=np.float32),
        sample_rate_hz=48_000,
    )
    _refresh_asset(zero, "shard_00001", "audio.wav")
    marker_path = zero / "shards/shard_00001/shard.complete.json"
    marker = _json(marker_path)
    marker["audio"]["sample_count"] = 0
    marker["tail_samples"] = 0
    _write_pretty(marker_path, marker)
    assert verify_shard_completion(marker_path.parent).marker["tail_samples"] == 0


def test_rotation_layout_primitives_preserve_concatenation_model():
    stream = np.arange(23, dtype=np.float32)
    single = stream.copy()

    oversized = plan_shards(
        ((0, "scene", 9),), shard_max_frames=4, shard_episode_aligned=True
    )
    assert [(item.start_frame, item.frame_count) for item in oversized] == [
        (0, 4),
        (4, 4),
        (8, 1),
    ]
    unaligned = plan_shards(
        ((0, "scene", 9),),
        shard_max_frames=4,
        shard_episode_aligned=False,
    )
    assert [(item.start_frame, item.frame_count) for item in unaligned] == [
        (0, 4),
        (4, 4),
        (8, 1),
    ]

    # Exact cut tiling must preserve every sample once.
    cuts = (0, 8, 15, len(stream))
    shards = [stream[start:end] for start, end in zip(cuts[:-1], cuts[1:], strict=True)]
    reconstructed = np.concatenate(shards)
    np.testing.assert_array_equal(reconstructed, single)
    assert sum(item.size for item in shards) == single.size


def test_checked_in_reference_fixture_is_complete_and_marker_versioned():
    result = validate_session_layout(REFERENCE_DIR)
    assert result.lifecycle_state == "complete"
    assert all(
        shard.marker["marker_version"] == SHARD_COMPLETION_VERSION
        for shard in result.shards
    )
