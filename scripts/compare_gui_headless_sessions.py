#!/usr/bin/env python3
"""Compare GUI and headless guided-session exports semantically.

Documented normalizations (field — reason):

* ``creation_timestamp_ms`` — sequential sessions have different wall-clock time.
* creation tool name/version — entry surfaces may label one producer differently.
* Isaac Sim/Lab and Kit versions — runtime provenance is environmental.
* ``device`` — host provenance may differ while simulation output stays equal.
* config hash/JSON bytes — session paths and ids intentionally change the digest.
* ``dataset_id`` — independently exported sessions require distinct portable identities.
* session-root substrings — relocation changes roots, not relative semantics.
* absolute diagnostic paths — machine-local locations are not signal data.
* asset/marker checksums and byte sizes — they derive from normalized raw bytes.
* stored audio tail counts — only frame-attributed sample ranges carry parity meaning.

Everything else is compared exactly, including schema/profile/convention fields,
episode and shard tiling, frame ids/timestamps/detections/ranges, channel order,
sample rate, dtype, split policy, and decoded per-frame audio ranges. Audio tails
outside attributed ranges are deliberately excluded.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.io.wave_read import read_wav

_NORMALIZED = "<normalized>"
_SESSION_ROOT = "<session-root>"
_ABSOLUTE_DIAGNOSTIC = "<absolute-diagnostic-path>"
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_USD_ROOTS = ("/World", "/Render", "/Looks", "/OmniverseKit")


def compare_sessions(left: str | Path, right: str | Path) -> dict[str, Any]:
    """Return a machine-readable semantic comparison for two session roots."""

    left_root = Path(left).expanduser().resolve()
    right_root = Path(right).expanduser().resolve()
    left_data = _load_session(left_root)
    right_data = _load_session(right_root)
    differences: list[dict[str, Any]] = []

    _diff(
        left_data["manifest"],
        right_data["manifest"],
        "manifest",
        differences,
    )
    _diff(left_data["config"], right_data["config"], "config", differences)
    _diff(left_data["markers"], right_data["markers"], "shards", differences)
    _diff(left_data["frames"], right_data["frames"], "frames", differences)
    audio_parity = _compare_audio(left_data, right_data, differences)

    return {
        "status": "equal" if not differences else "different",
        "equal": not differences,
        "left_session": str(left_root),
        "right_session": str(right_root),
        "frame_count": {
            "left": len(left_data["frames"]),
            "right": len(right_data["frames"]),
        },
        "difference_count": len(differences),
        "differences": differences,
        "audio_parity": audio_parity,
        "normalizations": [
            "creation_timestamp_ms",
            "creation tool/version runtime fields",
            "device provenance",
            "configuration_sha256 and normalized config JSON",
            "dataset_id",
            "session roots",
            "filesystem-absolute diagnostic strings",
            "derived asset/marker checksums and byte sizes",
            "stored audio tail counts",
        ],
    }


def _load_session(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    config_path = root / "config" / "session_config.json"
    manifest = _read_json(manifest_path)
    config = _read_json(config_path)
    if not isinstance(manifest, dict) or not isinstance(config, dict):
        raise ValueError(f"session {root}: manifest and config must be JSON objects")

    normalized_manifest = _normalize_manifest(manifest, root)
    normalized_config = _normalize_value(
        config,
        root=root,
        normalize_dataset_id=True,
    )
    frames: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    audio_by_shard: dict[str, Any] = {}

    for shard in manifest.get("shards", []):
        shard_id = str(shard.get("shard_id", ""))
        frame_asset = _asset_of_kind(shard, "frame_trace_jsonl")
        audio_asset = _asset_of_kind(shard, "audio_wav", "audio_flac")
        if frame_asset is None:
            raise ValueError(f"session {root}: shard {shard_id} has no frame trace")
        frame_path = root / str(frame_asset["path"])
        for _line_number, line in enumerate(
            frame_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            record = json.loads(line)
            record["semantic_shard_id"] = shard_id
            frames.append(
                _normalize_value(record, root=root, normalize_dataset_id=False)
            )
        shard_dir = frame_path.parent
        marker_path = shard_dir / "shard.complete.json"
        marker = _read_json(marker_path)
        markers.append(_normalize_marker(marker, root))
        if audio_asset is not None:
            audio_by_shard[shard_id] = read_wav(root / str(audio_asset["path"]))

    frames.sort(key=lambda item: int(item.get("dataset_frame_index", -1)))
    markers.sort(key=lambda item: str(item.get("shard_id", "")))
    return {
        "root": root,
        "manifest": normalized_manifest,
        "config": normalized_config,
        "frames": frames,
        "markers": markers,
        "audio": audio_by_shard,
    }


def _normalize_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    result["creation_timestamp_ms"] = _NORMALIZED
    result["dataset_id"] = _NORMALIZED
    result["configuration_sha256"] = _NORMALIZED
    creation = result.get("creation")
    if isinstance(creation, dict):
        for key in (
            "tool_name",
            "tool_version",
            "isaac_sim_version",
            "isaac_lab_version",
            "kit_version",
        ):
            creation[key] = _NORMALIZED
    result["device"] = _NORMALIZED
    for shard in result.get("shards", []):
        for asset in shard.get("assets", []):
            asset["sha256"] = _NORMALIZED
    return _normalize_value(result, root=root, normalize_dataset_id=False)


def _normalize_marker(marker: Any, root: Path) -> Any:
    if not isinstance(marker, dict):
        return marker
    semantic = copy.deepcopy(marker)
    semantic["tail_samples"] = _NORMALIZED
    audio = semantic.get("audio")
    if isinstance(audio, dict):
        audio["sample_count"] = _NORMALIZED
    for item in semantic.get("files", []):
        item["bytes"] = _NORMALIZED
        item["sha256"] = _NORMALIZED
    return _normalize_value(semantic, root=root, normalize_dataset_id=False)


def _normalize_value(
    value: Any,
    *,
    root: Path,
    normalize_dataset_id: bool,
    in_diagnostics: bool = False,
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child_diagnostics = in_diagnostics or key == "diagnostics"
            if normalize_dataset_id and key == "dataset_id":
                result[key] = _NORMALIZED
            else:
                result[key] = _normalize_value(
                    value[key],
                    root=root,
                    normalize_dataset_id=normalize_dataset_id,
                    in_diagnostics=child_diagnostics,
                )
        return result
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                root=root,
                normalize_dataset_id=normalize_dataset_id,
                in_diagnostics=in_diagnostics,
            )
            for item in value
        ]
    if isinstance(value, str):
        text = _normalize_root(value, root)
        if in_diagnostics and _looks_filesystem_absolute(text):
            return _ABSOLUTE_DIAGNOSTIC
        return text
    return value


def _normalize_root(value: str, root: Path) -> str:
    variants = {str(root), root.as_posix()}
    text = value
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            text = text.replace(variant, _SESSION_ROOT)
    return text


def _looks_filesystem_absolute(value: str) -> bool:
    if value.startswith(_USD_ROOTS) or value.startswith(_SESSION_ROOT):
        return False
    filesystem_roots = ("/home/", "/tmp/", "/var/", "/opt/", "/mnt/", "/usr/")
    return value.startswith(filesystem_roots) or bool(
        _WINDOWS_ABSOLUTE_RE.match(value)
    )


def _compare_audio(
    left: dict[str, Any],
    right: dict[str, Any],
    differences: list[dict[str, Any]],
) -> dict[str, Any]:
    ranges_compared = 0
    exact_ranges = 0
    nonempty_left = 0
    nonempty_right = 0
    nonzero_left = 0
    nonzero_right = 0
    for index, (left_record, right_record) in enumerate(
        zip(left["frames"], right["frames"], strict=False)
    ):
        left_frame = left_record.get("frame", {})
        right_frame = right_record.get("frame", {})
        if left_frame.get("backend_id") != right_frame.get("backend_id"):
            continue
        left_start = left_record.get("audio_start_sample")
        left_end = left_record.get("audio_end_sample")
        right_start = right_record.get("audio_start_sample")
        right_end = right_record.get("audio_end_sample")
        if not all(
            isinstance(item, int)
            for item in (left_start, left_end, right_start, right_end)
        ):
            continue
        left_audio = left["audio"].get(left_record.get("semantic_shard_id"))
        right_audio = right["audio"].get(right_record.get("semantic_shard_id"))
        if left_audio is None or right_audio is None:
            if left_audio is not right_audio:
                differences.append(
                    {
                        "name": "audio_presence_mismatch",
                        "path": f"audio.frames[{index}]",
                        "left": left_audio is not None,
                        "right": right_audio is not None,
                    }
                )
            continue
        left_samples = left_audio.samples[:, left_start:left_end]
        right_samples = right_audio.samples[:, right_start:right_end]
        ranges_compared += 1
        if left_samples.shape[1] > 0:
            nonempty_left += 1
        if right_samples.shape[1] > 0:
            nonempty_right += 1
        nonzero_left += int(np.count_nonzero(left_samples))
        nonzero_right += int(np.count_nonzero(right_samples))
        if (
            left_samples.shape != right_samples.shape
            or left_samples.dtype != right_samples.dtype
            or left_samples.tobytes() != right_samples.tobytes()
        ):
            differences.append(
                {
                    "name": "decoded_audio_mismatch",
                    "path": f"audio.frames[{index}].attributed_samples",
                    "left": {
                        "shape": list(left_samples.shape),
                        "dtype": str(left_samples.dtype),
                    },
                    "right": {
                        "shape": list(right_samples.shape),
                        "dtype": str(right_samples.dtype),
                    },
                }
            )
        else:
            exact_ranges += 1

    return {
        "ranges_compared": ranges_compared,
        "exact_ranges": exact_ranges,
        "nonempty_ranges": {
            "left": nonempty_left,
            "right": nonempty_right,
        },
        "nonzero_sample_values": {
            "left": nonzero_left,
            "right": nonzero_right,
        },
        "all_ranges_nonempty": (
            ranges_compared > 0
            and nonempty_left == ranges_compared
            and nonempty_right == ranges_compared
        ),
        "nonzero_audio": nonzero_left > 0 and nonzero_right > 0,
        "exact": ranges_compared > 0 and exact_ranges == ranges_compared,
    }


def _diff(left: Any, right: Any, path: str, out: list[dict[str, Any]]) -> None:
    if type(left) is not type(right):
        _append_difference(path, left, right, out)
        return
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left:
                _append_difference(child, "<missing>", right[key], out)
            elif key not in right:
                _append_difference(child, left[key], "<missing>", out)
            else:
                _diff(left[key], right[key], child, out)
        return
    if isinstance(left, list):
        if len(left) != len(right):
            _append_difference(f"{path}.length", len(left), len(right), out)
        for index, (left_item, right_item) in enumerate(
            zip(left, right, strict=False)
        ):
            _diff(left_item, right_item, f"{path}[{index}]", out)
        return
    if left != right:
        _append_difference(path, left, right, out)


def _append_difference(
    path: str,
    left: Any,
    right: Any,
    out: list[dict[str, Any]],
) -> None:
    name = "value_mismatch"
    lowered = path.lower()
    if "timestamp" in lowered:
        name = "timestamp_mismatch"
    elif "audio_start_sample" in lowered or "audio_end_sample" in lowered:
        name = "audio_range_mismatch"
    elif "detections" in lowered:
        name = "detection_mismatch"
    out.append({"name": name, "path": path, "left": left, "right": right})


def _asset_of_kind(shard: dict[str, Any], *kinds: str) -> dict[str, Any] | None:
    for asset in shard.get("assets", []):
        if asset.get("kind") in kinds:
            return asset
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gui_session", type=Path)
    parser.add_argument("headless_session", type=Path)
    parser.add_argument("--json", dest="json_path", default="-")
    args = parser.parse_args(argv)
    try:
        report = compare_sessions(args.gui_session, args.headless_session)
    except (OSError, ValueError) as exc:
        report = {
            "status": "error",
            "equal": False,
            "difference_count": 1,
            "differences": [
                {
                    "name": "comparison_error",
                    "path": "session",
                    "left": None,
                    "right": str(exc),
                }
            ],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_path == "-":
        sys.stdout.write(rendered)
    else:
        output = Path(args.json_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0 if report.get("equal") else 1


if __name__ == "__main__":
    raise SystemExit(main())
