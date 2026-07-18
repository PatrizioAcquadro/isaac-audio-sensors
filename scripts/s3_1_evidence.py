#!/usr/bin/env python3
"""Generate deterministic pure S3.1 pose-derived velocity evidence."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import platform
import struct
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import PoseHistory
from isaac_audio_sensors.core.plugins.registry import (
    get_default_registry,
    validate_declaration,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.stage_cache import StageAudioCache
from isaac_audio_sensors.isaac.stage_snapshot import enrich_snapshot_motion

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.1"
ENTRY_REVISION = "839fe906ac3f65ed24e60a4ddca9b5c999923eb3"
RAW_TOLERANCE_MPS = 1e-9
SMOOTHING_TOLERANCE_MPS = 1e-9
DEFAULT_MOTION = MotionEffectsConfig(derive_velocity_from_poses=True)


def _write_json(name: str, payload: object) -> Path:
    path = OUTPUT / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _frame_bytes(frame: object) -> bytes:
    return (
        json.dumps(
            frame_to_trace_dict(frame),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _constant_velocity_evidence() -> tuple[dict[str, object], float, str]:
    fixtures = (
        ("source", (1.0, -2.0, 0.5), (20.0, -7.5, 0.125)),
        ("array", (-3.0, 4.0, 1.0), (-2.0, 1.25, 0.0)),
    )
    rows: list[dict[str, object]] = []
    fixture_hash = hashlib.sha256()
    maximum = 0.0
    for entity_id, origin, velocity in fixtures:
        history = PoseHistory()
        first = history.observe(entity_id, 0.0, origin)
        fixture_hash.update(struct.pack(">ddd", *origin))
        fixture_hash.update(struct.pack(">ddd", *velocity))
        if first.reason != "first_sample" or first.velocity_world_mps is not None:
            raise RuntimeError("constant-velocity first-sample policy failed")
        for step in range(1, 41):
            time_s = 0.05 * step
            position = tuple(
                origin[index] + velocity[index] * time_s for index in range(3)
            )
            result = history.observe(entity_id, time_s, position)
            observed = result.velocity_world_mps
            if observed is None:
                raise RuntimeError("constant-velocity fixture did not derive")
            errors = tuple(abs(observed[i] - velocity[i]) for i in range(3))
            maximum = max(maximum, *errors)
            rows.append(
                {
                    "entity_id": entity_id,
                    "derived_update": step,
                    "time_s": time_s,
                    "observed_x_mps": observed[0],
                    "observed_y_mps": observed[1],
                    "observed_z_mps": observed[2],
                    "maximum_component_error_mps": max(errors),
                    "reason": result.reason,
                }
            )
    with (OUTPUT / "constant_velocity_trace.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        writer = csv.DictWriter(output_file, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "derived_sample_count": len(rows),
        "entity_count": len(fixtures),
        "tolerance_mps": RAW_TOLERANCE_MPS,
        "maximum_absolute_component_error_mps": maximum,
        "status": "passed" if maximum <= RAW_TOLERANCE_MPS else "failed",
    }
    _write_json("constant_velocity_results.json", payload)
    return payload, maximum, fixture_hash.hexdigest()


def _smoothing_evidence() -> tuple[dict[str, object], float, str]:
    origin = (1.0, -2.0, 0.5)
    velocity = (20.0, -7.5, 0.125)
    history = PoseHistory(smoothing_alpha=0.5)
    history.observe("source", 0.0, origin)
    rows: list[dict[str, object]] = []
    maximum_recurrence_error = 0.0
    final_error = math.inf
    for step in range(1, 41):
        time_s = 0.05 * step
        position = tuple(
            origin[index] + velocity[index] * time_s for index in range(3)
        )
        result = history.observe("source", time_s, position)
        observed = result.velocity_world_mps
        if observed is None:
            raise RuntimeError("smoothing fixture did not derive")
        expected = tuple((1.0 - 0.5**step) * value for value in velocity)
        recurrence_error = max(abs(observed[i] - expected[i]) for i in range(3))
        truth_error = max(abs(observed[i] - velocity[i]) for i in range(3))
        maximum_recurrence_error = max(maximum_recurrence_error, recurrence_error)
        final_error = truth_error
        rows.append(
            {
                "derived_update": step,
                "time_s": time_s,
                "observed_x_mps": observed[0],
                "observed_y_mps": observed[1],
                "observed_z_mps": observed[2],
                "analytical_maximum_error_mps": recurrence_error,
                "true_velocity_maximum_error_mps": truth_error,
            }
        )
    with (OUTPUT / "smoothing_settling_trace.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        writer = csv.DictWriter(output_file, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "alpha": 0.5,
        "derived_update_count": 40,
        "tolerance_mps": SMOOTHING_TOLERANCE_MPS,
        "maximum_recurrence_error_mps": maximum_recurrence_error,
        "error_after_40_updates_mps": final_error,
        "status": "passed" if final_error <= SMOOTHING_TOLERANCE_MPS else "failed",
    }
    _write_json("smoothing_settling_results.json", payload)
    fixture = struct.pack(">ddddddd", *origin, *velocity, 0.5)
    return payload, final_error, _sha256(fixture)


def _policy_evidence() -> dict[str, object]:
    rows: list[dict[str, object]] = []

    def row(name: str, result: object, expected_reason: str, expected_velocity: object):
        if result.velocity_world_mps is None or expected_velocity is None:
            velocity_matches = result.velocity_world_mps is expected_velocity
        else:
            velocity_matches = max(
                abs(result.velocity_world_mps[index] - expected_velocity[index])
                for index in range(3)
            ) <= RAW_TOLERANCE_MPS
        passed = (
            result.reason == expected_reason
            and velocity_matches
        )
        rows.append(
            {
                "name": name,
                "reason": result.reason,
                "velocity_world_mps": result.velocity_world_mps,
                "expected_reason": expected_reason,
                "expected_velocity_world_mps": expected_velocity,
                "passed": passed,
            }
        )

    history = PoseHistory()
    first = history.observe("first", 0.0, (0.0, 0.0, 0.0))
    row("first_sample", first, "first_sample", None)
    row(
        "duplicate_after_first",
        history.observe("first", 0.0, (9.0, 0.0, 0.0)),
        "first_sample",
        None,
    )
    history.observe("duplicate", 0.0, (0.0, 0.0, 0.0))
    derived = history.observe("duplicate", 0.1, (1.0, 0.0, 0.0))
    row("derived", derived, "derived", (10.0, 0.0, 0.0))
    row(
        "duplicate_after_derived",
        history.observe("duplicate", 0.1, (99.0, 0.0, 0.0)),
        "derived",
        (10.0, 0.0, 0.0),
    )
    row(
        "strict_decrease",
        history.observe("duplicate", -1.0, (5.0, 0.0, 0.0)),
        "time_reset",
        None,
    )
    row(
        "time_reset_recovery",
        history.observe("duplicate", -0.9, (5.1, 0.0, 0.0)),
        "derived",
        (1.0, 0.0, 0.0),
    )
    exact_stale = PoseHistory()
    exact_stale.observe("entity", 0.0, (0.0, 0.0, 0.0))
    row(
        "gap_exactly_0_5_s",
        exact_stale.observe("entity", 0.5, (1.0, 0.0, 0.0)),
        "derived",
        (2.0, 0.0, 0.0),
    )
    over_stale = PoseHistory()
    over_stale.observe("entity", 0.0, (0.0, 0.0, 0.0))
    row(
        "gap_above_0_5_s",
        over_stale.observe(
            "entity", math.nextafter(0.5, math.inf), (100.0, 0.0, 0.0)
        ),
        "stale_pose",
        None,
    )
    row(
        "stale_recovery",
        over_stale.observe("entity", 0.6, (100.1, 0.0, 0.0)),
        "derived",
        (1.0000000000000853, 0.0, 0.0),
    )
    exact_speed = PoseHistory()
    exact_speed.observe("entity", 0.0, (0.0, 0.0, 0.0))
    row(
        "speed_exactly_50_mps",
        exact_speed.observe("entity", 0.1, (5.0, 0.0, 0.0)),
        "derived",
        (50.0, 0.0, 0.0),
    )
    above_speed = PoseHistory()
    above_speed.observe("entity", 0.0, (0.0, 0.0, 0.0))
    row(
        "speed_above_50_mps",
        above_speed.observe(
            "entity", 0.1, (math.nextafter(5.0, math.inf), 0.0, 0.0)
        ),
        "teleport",
        None,
    )
    row(
        "teleport_recovery",
        above_speed.observe("entity", 0.2, (5.1, 0.0, 0.0)),
        "derived",
        ((5.1 - math.nextafter(5.0, math.inf)) / 0.1, 0.0, 0.0),
    )
    payload = {
        "rows": rows,
        "status": "passed" if all(item["passed"] for item in rows) else "failed",
    }
    _write_json("pose_policy_matrix.json", payload)
    return payload


def _base_raw() -> dict[str, Any]:
    return {
        "scene": {"scene_id": "s3_1_config"},
        "audio": {
            "default_backend": "tdoa_synthetic",
            "tdoa_ambiguity_policy": "none",
        },
        "sources": [
            {
                "source_id": "speaker",
                "prim_path": "/World/Speaker",
                "class_label": "Speech",
            }
        ],
        "arrays": {
            "rig": {
                "array_id": "rig",
                "prim_path": "/World/Rig",
                "microphones": [{"mic_id": "left"}, {"mic_id": "right"}],
            }
        },
    }


def _invalid_evidence() -> tuple[dict[str, object], dict[str, object]]:
    config_cases = (
        ("unknown", {"unknown": 1}),
        ("non_boolean", {"derive_velocity_from_poses": 1}),
        ("teleport_zero", {"teleport_speed_threshold_mps": 0.0}),
        ("teleport_nonfinite", {"teleport_speed_threshold_mps": math.nan}),
        ("stale_above_range", {"stale_time_s": 60.1}),
        ("alpha_zero", {"smoothing_alpha": 0.0}),
    )
    config_rows = []
    for name, motion in config_cases:
        raw = _base_raw()
        raw["audio"]["effects"] = {"motion": motion}
        try:
            validate_audio_config(raw)
        except ConfigValidationError as exc:
            config_rows.append(
                {
                    "name": name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "passed": True,
                }
            )
        else:
            config_rows.append({"name": name, "passed": False})
    collision = _base_raw()
    collision["sources"][0]["source_id"] = "rig"
    collision["audio"]["effects"] = {
        "motion": {"derive_velocity_from_poses": True}
    }
    try:
        validate_audio_config(collision)
    except ConfigValidationError as exc:
        config_rows.append(
            {
                "name": "source_array_collision",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "passed": True,
            }
        )
    else:
        config_rows.append({"name": "source_array_collision", "passed": False})
    config_payload = {
        "rows": config_rows,
        "status": (
            "passed" if all(row["passed"] for row in config_rows) else "failed"
        ),
    }
    _write_json("invalid_motion_config_matrix.json", config_payload)

    pose_cases = (
        ("empty_id", {"entity_id": ""}),
        ("time_nan", {"time_s": math.nan}),
        ("time_bool", {"time_s": True}),
        ("position_short", {"position_world_m": (0.0, 0.0)}),
        ("position_inf", {"position_world_m": (0.0, math.inf, 0.0)}),
        ("quaternion_short", {"orientation_world_xyzw": (0.0, 0.0, 1.0)}),
    )
    pose_rows = []
    for name, override in pose_cases:
        history = PoseHistory()
        history.observe("entity", 0.0, (0.0, 0.0, 0.0))
        kwargs = {
            "entity_id": "entity",
            "time_s": 0.1,
            "position_world_m": (1.0, 0.0, 0.0),
            "orientation_world_xyzw": None,
        }
        kwargs.update(override)
        try:
            history.observe(**kwargs)
        except ValueError as exc:
            recovered = history.observe("entity", 0.1, (1.0, 0.0, 0.0))
            pose_rows.append(
                {
                    "name": name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "history_preserved": recovered.velocity_world_mps
                    == (10.0, 0.0, 0.0),
                    "passed": recovered.velocity_world_mps == (10.0, 0.0, 0.0),
                }
            )
        else:
            pose_rows.append({"name": name, "passed": False})
    pose_payload = {
        "rows": pose_rows,
        "status": "passed" if all(row["passed"] for row in pose_rows) else "failed",
    }
    _write_json("invalid_pose_matrix.json", pose_payload)
    return config_payload, pose_payload


def _array(*, position=(1.0, 1.0, 1.0), velocity=None):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=position,
        sample_rate_hz=8_000,
    )
    return replace(array, velocity_world_mps=velocity)


def _source(*, position=(2.0, 1.0, 1.0), velocity=None):
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=10.0,
        gain_db=0.0,
        velocity_world_mps=velocity,
    )


def _scene(*, source=None, array=None, room=False):
    source = _source() if source is None else source
    array = _array() if array is None else array
    return AudioSceneSnapshot(
        stage_id="s3_1_evidence",
        timestamp_ms=1_100,
        sources=(source,),
        arrays=(array,),
        room=(
            RoomAcousticsSpec(
                room_id="s3_1_room",
                dimensions_m=(8.0, 5.0, 3.0),
                absorption=0.35,
                max_order=0,
            )
            if room
            else None
        ),
    )


def _snapshot_evidence() -> tuple[dict[str, object], dict[str, object]]:
    source_velocity = (-0.0, 7.25, -3.5)
    array_velocity = (1.25, -0.0, 4.5)
    authored = _scene(
        source=_source(velocity=source_velocity),
        array=_array(velocity=array_velocity),
    )
    history = PoseHistory(smoothing_alpha=0.5)
    first, first_diag = enrich_snapshot_motion(
        authored,
        selected_array_id="rig",
        time_s=1.0,
        pose_history=history,
        motion_config=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            smoothing_alpha=0.5,
        ),
    )
    source_bits = struct.pack(">ddd", *first.sources[0].velocity_world_mps)
    array_bits = struct.pack(">ddd", *first.arrays[0].velocity_world_mps)
    source_exact = source_bits == struct.pack(">ddd", *source_velocity)
    array_exact = array_bits == struct.pack(">ddd", *array_velocity)
    bits_payload = {
        "source_velocity_hex": source_bits.hex(),
        "source_authored_hex": struct.pack(">ddd", *source_velocity).hex(),
        "array_velocity_hex": array_bits.hex(),
        "array_authored_hex": struct.pack(">ddd", *array_velocity).hex(),
        "source_bit_exact": source_exact,
        "array_bit_exact": array_exact,
        "velocity_source": first_diag,
        "status": "passed" if source_exact and array_exact else "failed",
    }
    _write_json("authored_precedence_bits.json", bits_payload)

    moved = _scene(
        source=_source(position=(2.2, 1.0, 1.0)),
        array=_array(position=(1.0, 1.1, 1.0)),
    )
    second, second_diag = enrich_snapshot_motion(
        moved,
        selected_array_id="rig",
        time_s=1.1,
        pose_history=history,
        motion_config=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            smoothing_alpha=0.5,
        ),
    )
    payload = {
        "first_velocity_source": first_diag,
        "second_velocity_source": second_diag,
        "derived_source_velocity_world_mps": second.sources[0].velocity_world_mps,
        "derived_array_velocity_world_mps": second.arrays[0].velocity_world_mps,
        "status": (
            "passed"
            if second_diag == {"speaker": "derived", "rig": "derived"}
            and second.sources[0].velocity_world_mps is not None
            and second.arrays[0].velocity_world_mps is not None
            else "failed"
        ),
    }
    _write_json("stage_snapshot_velocity_results.json", payload)
    return payload, bits_payload


class _FakePrim:
    def __init__(self, path: str, type_name: str, attributes: dict[str, object]):
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    def __init__(self, prims: tuple[_FakePrim, ...]):
        self.prims = list(prims)
        self.traverse_count = 0

    def Traverse(self):
        self.traverse_count += 1
        return tuple(self.prims)

    def GetPrimAtPath(self, path: str):
        return next((prim for prim in self.prims if prim.path == path), None)


def _cache_evidence() -> tuple[dict[str, object], dict[str, object]]:
    source = _FakePrim(
        "/World/Speaker",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker",
            "ias:position_world": (2.0, 1.0, 1.0),
        },
    )
    array = _FakePrim(
        "/World/Rig",
        "Xform",
        {
            "ias:array_id": "rig",
            "ias:position_world": (1.0, 1.0, 1.0),
            "ias:layout_name": "quad_front",
        },
    )
    stage = _FakeStage((source, array))
    cache = StageAudioCache(stage)
    diagnostics = {}
    first = cache.snapshot(
        timestamp_ms=0,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        diagnostics_out=diagnostics,
    )
    history = PoseHistory()
    _, first_motion = enrich_snapshot_motion(
        first,
        selected_array_id="rig",
        time_s=0.0,
        pose_history=history,
        motion_config=DEFAULT_MOTION,
    )
    source.attributes["ias:position_world"] = (2.1, 1.0, 1.0)
    second = cache.snapshot(
        timestamp_ms=50,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        diagnostics_out=diagnostics,
    )
    _, second_motion = enrich_snapshot_motion(
        second,
        selected_array_id="rig",
        time_s=0.05,
        pose_history=history,
        motion_config=DEFAULT_MOTION,
    )
    cache.rediscover()
    source.attributes["ias:position_world"] = (2.2, 1.0, 1.0)
    third = cache.snapshot(
        timestamp_ms=100,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        diagnostics_out=diagnostics,
    )
    _, third_motion = enrich_snapshot_motion(
        third,
        selected_array_id="rig",
        time_s=0.1,
        pose_history=history,
        motion_config=DEFAULT_MOTION,
    )
    cache_payload = {
        "first_motion": first_motion,
        "cached_pose_edit_motion": second_motion,
        "structural_rediscovery_motion": third_motion,
        "full_discovery_count": cache.full_discovery_count,
        "cached_tick_count": cache.cached_tick_count,
        "traverse_count": stage.traverse_count,
        "status": (
            "passed"
            if second_motion["speaker"] == "derived"
            and third_motion["speaker"] == "derived"
            else "failed"
        ),
    }
    _write_json("stage_cache_motion_trace.json", cache_payload)

    history.remove_entity("speaker")
    reused = history.observe("speaker", 0.2, (6.0, 1.0, 1.0))
    history.reset()
    reset = history.observe("rig", 0.3, (1.0, 1.0, 1.0))
    lifecycle_payload = {
        "entity_reuse_after_remove": reused.reason,
        "first_after_reset": reset.reason,
        "structural_rediscovery_preserved_survivor": (
            third_motion["speaker"] == "derived"
        ),
        "status": (
            "passed"
            if reused.reason == "first_sample"
            and reset.reason == "first_sample"
            and third_motion["speaker"] == "derived"
            else "failed"
        ),
    }
    _write_json("pose_history_lifecycle.json", lifecycle_payload)
    cache.close()
    return cache_payload, lifecycle_payload


def _teleport_scene(*, room: bool) -> tuple[AudioSceneSnapshot, dict[str, str]]:
    history = PoseHistory()
    for time_s, position in (
        (1.0, (2.0, 1.0, 1.0)),
        (1.05, (2.0, 1.0, 1.0)),
    ):
        enrich_snapshot_motion(
            _scene(source=_source(position=position), room=room),
            selected_array_id="rig",
            time_s=time_s,
            pose_history=history,
            motion_config=DEFAULT_MOTION,
        )
    return enrich_snapshot_motion(
        _scene(source=_source(position=(5.0, 1.0, 1.0)), room=room),
        selected_array_id="rig",
        time_s=1.10,
        pose_history=history,
        motion_config=DEFAULT_MOTION,
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=1.10,
        end_time_s=1.12,
        timestamp_ms=1_100,
        sample_rate_hz=8_000,
        frame_index=2,
    )


def _tdoa_evidence() -> dict[str, object]:
    scene, motion = _teleport_scene(room=False)
    sensor = scene.array_by_id("rig")
    frame = TdoaSyntheticBackend(
        effects=EffectsConfig(motion=DEFAULT_MOTION)
    ).simulate(scene, sensor, _window())
    detection = frame.detections[0]
    per_mic = detection.diagnostics["per_mic_doppler_factor"]
    payload = {
        "velocity_source": motion,
        "snapshot_source_velocity_world_mps": scene.sources[0].velocity_world_mps,
        "doppler_factor": detection.diagnostics["doppler_factor"],
        "per_mic_doppler_factor": per_mic,
        "doppler_waveform_rendered": detection.diagnostics[
            "doppler_waveform_rendered"
        ],
        "status": (
            "passed"
            if motion["speaker"] == "none:teleport"
            and detection.diagnostics["doppler_factor"] == 1.0
            and set(per_mic.values()) == {1.0}
            and detection.diagnostics["doppler_waveform_rendered"] is False
            else "failed"
        ),
    }
    _write_json("tdoa_teleport_no_spike.json", payload)
    return payload


class _CaptureSink:
    def __init__(self):
        self.mixture: np.ndarray | None = None

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        del sample_rate_hz, mic_ids, window_sample_count
        self.mixture = np.array(mixture, copy=True)
        return WaveformWriteResult(
            paths=(f"evidence://{frame_id}.wav",),
            diagnostics={"mode": "s3_1_capture"},
        )


class _FakeMaterial:
    def __init__(self, absorption: object):
        self.absorption = absorption


class _FakeMicrophoneArray:
    def __init__(self, positions: object, fs: int):
        self.R = np.asarray(positions, dtype=float)
        self.fs = int(fs)
        self.signals = np.zeros((self.R.shape[1], 0))


class _FakeShoeBox:
    def __init__(self, dimensions: object, *, fs: int, max_order=0, c=343.0, **kwargs):
        self.dimensions = dimensions
        self.fs = int(fs)
        self.max_order = int(max_order)
        self.c = float(c)
        self.kwargs = kwargs
        self.sources: list[tuple[np.ndarray, np.ndarray]] = []
        self.mic_array: _FakeMicrophoneArray | None = None
        self.rir: list[list[np.ndarray]] = []

    def add_source(self, position: object, signal: object):
        self.sources.append(
            (np.asarray(position, dtype=float), np.asarray(signal, dtype=float))
        )

    def add_microphone_array(self, mic_array: _FakeMicrophoneArray):
        self.mic_array = mic_array

    def compute_rir(self):
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        self.rir = []
        for mic_position in self.mic_array.R.T:
            per_source = []
            for source_position, _ in self.sources:
                distance = float(np.linalg.norm(source_position - mic_position))
                delay = max(0, int(round(distance / self.c * self.fs)))
                rir = np.zeros(delay + 24)
                rir[delay] = 1.0 / max(distance, 0.1)
                per_source.append(rir)
            self.rir.append(per_source)

    def simulate(self, return_premix=False):
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        convolved = [
            [
                np.convolve(signal, self.rir[mic_index][source_index])
                for mic_index in range(self.mic_array.R.shape[1])
            ]
            for source_index, (_, signal) in enumerate(self.sources)
        ]
        max_length = max(len(signal) for row in convolved for signal in row)
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], max_length))
        for source_index, row in enumerate(convolved):
            for mic_index, signal in enumerate(row):
                premix[source_index, mic_index, : len(signal)] = signal
        self.mic_array.signals = premix.sum(axis=0)
        return premix if return_premix else None


def _install_fake_pyroom() -> types.ModuleType:
    module = types.ModuleType("pyroomacoustics")
    module.__version__ = "s3_1_deterministic_test_double"
    module.Material = _FakeMaterial
    module.MicrophoneArray = _FakeMicrophoneArray
    module.ShoeBox = _FakeShoeBox
    sys.modules["pyroomacoustics"] = module
    return module


def _room_evidence() -> tuple[dict[str, object], str]:
    dependency_available = importlib.util.find_spec("pyroomacoustics") is not None
    previous_module = sys.modules.get("pyroomacoustics")
    if not dependency_available:
        _install_fake_pyroom()
    import isaac_audio_sensors.core.backends.room_acoustics as room_module

    original_resampler = room_module._doppler_resampled_signal
    resample_calls = 0

    def _counted_resampler(*args: object, **kwargs: object):
        nonlocal resample_calls
        resample_calls += 1
        return original_resampler(*args, **kwargs)

    room_module._doppler_resampled_signal = _counted_resampler
    try:
        scene, motion = _teleport_scene(room=True)
        sensor = scene.array_by_id("rig")
        sink = _CaptureSink()
        frame = RoomAcousticsBackend(
            effects=EffectsConfig(motion=DEFAULT_MOTION),
            waveform_writer=sink,
        ).simulate(scene, sensor, _window())
    finally:
        room_module._doppler_resampled_signal = original_resampler
        if not dependency_available:
            if previous_module is None:
                sys.modules.pop("pyroomacoustics", None)
            else:
                sys.modules["pyroomacoustics"] = previous_module
    if sink.mixture is None:
        raise RuntimeError("room evidence did not capture a waveform")
    waveform_hash = _sha256(sink.mixture.tobytes(order="C"))
    detection = frame.detections[0]
    payload = {
        "dependency_available": dependency_available,
        "execution_dependency": (
            "installed_pyroomacoustics"
            if dependency_available
            else "transparent_deterministic_test_double"
        ),
        "velocity_source": motion,
        "doppler_factor": detection.diagnostics["doppler_factor"],
        "doppler_waveform_rendered": detection.diagnostics[
            "doppler_waveform_rendered"
        ],
        "doppler_resample_call_count": resample_calls,
        "waveform_sha256": waveform_hash,
        "waveform_shape": sink.mixture.shape,
        "status": (
            "passed"
            if motion["speaker"] == "none:teleport"
            and detection.diagnostics["doppler_factor"] == 1.0
            and detection.diagnostics["doppler_waveform_rendered"] is False
            and resample_calls == 0
            else "failed"
        ),
    }
    _write_json("room_teleport_no_spike.json", payload)
    (OUTPUT / "room_teleport_waveform_sha256.json").write_text(
        json.dumps(
            {
                "sha256": waveform_hash,
                "dtype": "float64",
                "order": "C",
                "shape": sink.mixture.shape,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload, waveform_hash


def _off_state_evidence() -> tuple[dict[str, object], dict[str, object]]:
    scene = _scene()
    sensor = scene.array_by_id("rig")
    baseline = TdoaSyntheticBackend().simulate(scene, sensor, _window())
    disabled = TdoaSyntheticBackend(
        effects=EffectsConfig(motion=MotionEffectsConfig())
    ).simulate(scene, sensor, _window())
    baseline_bytes = _frame_bytes(baseline)
    disabled_bytes = _frame_bytes(disabled)
    payload = {
        "frame_sha256": _sha256(baseline_bytes),
        "disabled_frame_sha256": _sha256(disabled_bytes),
        "frame_bytes_identical": baseline_bytes == disabled_bytes,
        "motion_key_absent": (
            "motion" not in baseline.diagnostics
            and "motion" not in disabled.diagnostics
        ),
        "doppler_key_absent": (
            "doppler_factor" not in baseline.detections[0].diagnostics
            and "doppler_factor" not in disabled.detections[0].diagnostics
        ),
    }
    payload["status"] = (
        "passed"
        if payload["frame_bytes_identical"]
        and payload["motion_key_absent"]
        and payload["doppler_key_absent"]
        else "failed"
    )
    _write_json("motion_off_state_golden_sha256.json", payload)
    frame_payload = frame_to_trace_dict(baseline)
    _write_json("motion_off_state_frame.json", frame_payload)
    return payload, frame_payload


def _registry_evidence() -> dict[str, object]:
    declaration = next(
        declaration
        for declaration in get_default_registry().declarations("propagation_backend")
        if declaration.plugin_id == "tdoa_synthetic"
    )
    validate_declaration(declaration, TdoaSyntheticBackend)
    scene, _ = _teleport_scene(room=False)
    sensor = scene.array_by_id("rig")
    effects = EffectsConfig(motion=DEFAULT_MOTION)
    first = TdoaSyntheticBackend(effects=effects).simulate(scene, sensor, _window())
    second = TdoaSyntheticBackend(effects=effects).simulate(scene, sensor, _window())
    first_bytes = _frame_bytes(first)
    second_bytes = _frame_bytes(second)
    payload = {
        "registry_twice_run_self_test": "passed",
        "first_sha256": _sha256(first_bytes),
        "second_sha256": _sha256(second_bytes),
        "exact": first_bytes == second_bytes,
        "status": "passed" if first_bytes == second_bytes else "failed",
    }
    _write_json("registry_determinism.json", payload)
    return payload


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _live_evidence() -> tuple[str, object, dict[str, object]]:
    required_files = [
        "live_isaac_teleport_summary.json",
        "live_isaac_teleport_frames.jsonl",
        "live_isaac_teleport.log",
        "live_isaac_teleport_stage.usda",
        "live_isaac_environment.json",
    ]
    summary_path = OUTPUT / required_files[0]
    if not summary_path.is_file():
        return "pending_live", None, {
            "status": "pending_live",
            "owner": "orchestrator",
            "required_files": required_files,
        }
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return "failed", None, {
            "status": "failed",
            "owner": "orchestrator",
            "required_files": required_files,
            "error": f"invalid live summary: {type(exc).__name__}: {exc}",
        }
    status = summary.get("status")
    if status not in {"passed", "failed", "blocked"}:
        status = "failed"
    missing_files = [name for name in required_files if not (OUTPUT / name).is_file()]
    if status == "passed" and missing_files:
        status = "failed"
    environment_path = OUTPUT / "live_isaac_environment.json"
    environment: object = None
    if environment_path.is_file():
        try:
            environment = json.loads(environment_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            environment = {"error": f"{type(exc).__name__}: {exc}"}
            if status == "passed":
                status = "failed"
    return status, environment, {
        "status": status,
        "owner": "orchestrator",
        "required_files": required_files,
        "missing_files": missing_files,
        "summary_status": summary.get("status"),
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    constant, raw_maximum, constant_fixture_hash = _constant_velocity_evidence()
    smoothing, smoothing_maximum, smoothing_fixture_hash = _smoothing_evidence()
    policy = _policy_evidence()
    invalid_config, invalid_pose = _invalid_evidence()
    snapshot, bits = _snapshot_evidence()
    cache, lifecycle = _cache_evidence()
    tdoa = _tdoa_evidence()
    room, room_waveform_hash = _room_evidence()
    off_state, _ = _off_state_evidence()
    registry = _registry_evidence()
    live_status, live_environment, live_artifacts = _live_evidence()

    rows = {
        "raw_constant_velocity": constant["status"],
        "smoothing_settling": smoothing["status"],
        "policy_order_and_boundaries": policy["status"],
        "invalid_motion_config": invalid_config["status"],
        "invalid_pose_atomicity": invalid_pose["status"],
        "snapshot_velocity_selection": snapshot["status"],
        "authored_precedence_bits": bits["status"],
        "stage_cache_continuity": cache["status"],
        "pose_history_lifecycle": lifecycle["status"],
        "tdoa_teleport_no_spike": tdoa["status"],
        "room_teleport_no_spike": room["status"],
        "motion_off_state": off_state["status"],
        "registry_twice_run_determinism": registry["status"],
        "live_isaac_teleport": live_status,
    }
    artifact_hashes = {
        path.name: _file_sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file()
        and path.name != "pose_velocity_gate.json"
    }
    pure_statuses = {
        status for name, status in rows.items() if not name.startswith("live")
    }
    gate = {
        "subphase": "S3.1",
        "entry_revision": ENTRY_REVISION,
        "implementation_base_revision": _git_revision(),
        "package_version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "pyroomacoustics_available": room["dependency_available"],
        },
        "normalized_motion_config": {
            "derive_velocity_from_poses": True,
            "teleport_speed_threshold_mps": 50.0,
            "stale_time_s": 0.5,
            "smoothing_alpha": None,
        },
        "frozen_defaults": {
            "derive_velocity_from_poses": False,
            "teleport_speed_threshold_mps": 50.0,
            "stale_time_s": 0.5,
            "smoothing_alpha": None,
        },
        "fixtures": {
            "constant_velocity_sha256": constant_fixture_hash,
            "smoothing_sha256": smoothing_fixture_hash,
            "constant_velocity_derived_sample_count": 80,
            "smoothing_derived_sample_count": 40,
            "room_teleport_waveform_sha256": room_waveform_hash,
        },
        "tolerances": {
            "raw_maximum_absolute_component_error_mps": RAW_TOLERANCE_MPS,
            "smoothing_error_after_40_updates_mps": SMOOTHING_TOLERANCE_MPS,
            "teleport_boundary_mps": 50.0,
            "teleport_comparison": "strict_greater_than",
            "tdoa_doppler_factor": "exactly 1.0",
            "room_doppler_factor": "exactly 1.0 and no resample call",
            "authored_precedence": "packed IEEE-754 bytes exact",
            "off_state": "serialized frame bytes exact",
        },
        "measured_maxima": {
            "raw_absolute_component_error_mps": raw_maximum,
            "smoothing_error_after_40_updates_mps": smoothing_maximum,
        },
        "exact_equality": {
            "teleport_boundary_derived": next(
                row["passed"]
                for row in policy["rows"]
                if row["name"] == "speed_exactly_50_mps"
            ),
            "tdoa_unity": tdoa["doppler_factor"] == 1.0,
            "room_unity": room["doppler_factor"] == 1.0,
            "room_resample_calls_zero": room["doppler_resample_call_count"] == 0,
            "authored_source_bits": bits["source_bit_exact"],
            "authored_array_bits": bits["array_bit_exact"],
            "off_state_frame_bytes": off_state["frame_bytes_identical"],
        },
        "rows": {name: {"status": status} for name, status in rows.items()},
        "commands": [
            ".venv/bin/python -m pytest -q tests/test_pose_history.py "
            "tests/test_motion_stage_snapshot.py "
            "tests/test_motion_doppler_integration.py",
            "make test",
            "make lint",
            "make check-version",
            "make live-s3-1-pose-velocity",
            ".venv/bin/python scripts/s3_1_evidence.py",
        ],
        "live_environment_identity": live_environment,
        "live_artifacts": live_artifacts,
        "artifact_sha256": artifact_hashes,
        "status": (
            live_status
            if pure_statuses == {"passed"}
            else "failed"
        ),
    }
    _write_json("pose_velocity_gate.json", gate)
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "status": gate["status"],
                "measured_maxima": gate["measured_maxima"],
                "live": live_status,
            },
            sort_keys=True,
        )
    )
    return 0 if pure_statuses == {"passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
