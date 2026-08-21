"""Live Isaac Sim smoke validation for isaac_audio_sensors."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.io.traces import (
    append_frame_jsonl,
    frame_from_trace_dict,
)
from isaac_audio_sensors.core.io.waveforms import FrameWaveformWriter
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import AudioSensorFrame, RoomAcousticsSpec
from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_sound_source_attrs,
    create_listener_prim,
    create_sound_prim,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot
from isaac_audio_sensors.isaac.viz.overlays import debug_primitives_to_dicts

REQUIRED_BACKENDS = ("geometry_only", "tdoa_synthetic")
OPTIONAL_BACKENDS = ("room_acoustics",)
SMOKE_PHASES = (
    ("before", 0.0),
    ("moved", 0.1),
    ("inactive", 0.5),
)
WAVEFORM_EVIDENCE_DIR = Path(
    "build/validation/isaac_audio_sensors/live_waveforms"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "build/validation/isaac_audio_sensors/isaac_sim_live_smoke.json"
        ),
    )
    args = parser.parse_args()

    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    _remove_existing_artifacts(args.out, frame_trace_path, config_path)

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "required_backends": REQUIRED_BACKENDS,
        "optional_backends": OPTIONAL_BACKENDS,
        "evidence_path": str(args.out),
        "frame_trace_path": str(frame_trace_path),
        "config_path": str(config_path),
        "headless": True,
    }
    simulation_app = None
    exit_code = 0

    try:
        _record_isaacsim_preflight(evidence)
        _record_gpu_preflight(evidence)
        _record_nvidia_smi(evidence)
        simulation_app = _ensure_isaac_runtime(evidence)

        import omni  # type: ignore
        from pxr import Usd  # type: ignore

        evidence["pxr_imported"] = True
        evidence["omni_imported"] = True
        evidence["omni_module"] = str(getattr(omni, "__file__", "built-in"))
        _record_loaded_runtime_modules(evidence)
        _record_gpu_preflight(evidence)
        _validate_runtime(evidence)

        stage = Usd.Stage.CreateInMemory("isaac_audio_live_smoke.usda")
        _author_stage(stage)
        _update_kit_once(evidence)

        binding_cfg = _binding_cfg()
        room_spec = _room_spec()
        config = _write_config(
            evidence_path=args.out,
            config_path=config_path,
            frame_trace_path=frame_trace_path,
            binding_cfg=binding_cfg,
            room_spec=room_spec,
        )
        evidence["config"] = config

        initial_diagnostics: dict[str, Any] = {}
        initial_snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=0,
            stage_id="isaac_sim_live_smoke",
            robot_base_prim_path="/World/RobotBase",
            usd_time_code=0.0,
            discovery_cfg=binding_cfg.to_discovery_cfg(),
            preferred_array=binding_cfg.preferred_array,
            diagnostics_out=initial_diagnostics,
        )
        trace_record_index = 0
        backend_results: dict[str, Any] = {}
        for backend_id in REQUIRED_BACKENDS:
            result, trace_record_index = _run_backend_smoke(
                stage=stage,
                backend_id=backend_id,
                binding_cfg=binding_cfg,
                room_spec=None,
                frame_trace_path=frame_trace_path,
                config_path=config_path,
                start_record_index=trace_record_index,
                evidence=evidence,
            )
            _validate_backend_result(result)
            backend_results[backend_id] = result

        room_available = RoomAcousticsBackend.is_available()
        evidence["room_acoustics_available"] = room_available
        if room_available:
            result, trace_record_index = _run_backend_smoke(
                stage=stage,
                backend_id="room_acoustics",
                binding_cfg=binding_cfg,
                room_spec=room_spec,
                frame_trace_path=frame_trace_path,
                config_path=config_path,
                start_record_index=trace_record_index,
                evidence=evidence,
            )
            _validate_backend_result(result)
            backend_results["room_acoustics"] = result
        else:
            backend_results["room_acoustics"] = {
                "status": "skipped",
                "skip_reason": (
                    "pyroomacoustics is not importable in this Isaac Python "
                    "runtime; room_acoustics is optional for Task 6."
                ),
            }

        trace_summary = _validate_jsonl_frames(frame_trace_path)
        room_result = backend_results["room_acoustics"]
        evidence.update(
            {
                "status": "passed",
                "stage_id": initial_snapshot.stage_id,
                "stage_summary": {
                    "stage_id": initial_snapshot.stage_id,
                    "mode": config["stage"]["mode"],
                    "root": config["stage"]["root"],
                    "robot_base_prim_path": config["stage"]["robot_base_prim_path"],
                    "array_prim_path": config["stage"]["array_prim_path"],
                    "source_prim_path": config["stage"]["source_prim_path"],
                    "motion_time_codes": config["stage"]["motion_time_codes"],
                },
                "source_count": len(initial_snapshot.sources),
                "array_count": len(initial_snapshot.arrays),
                "microphone_count": len(initial_snapshot.arrays[0].microphones),
                "semantic_discovery": True,
                "selected_array_id": initial_snapshot.arrays[0].array_id,
                "selected_array_preference": binding_cfg.preferred_array,
                "selected_array": initial_diagnostics.get("selected_array"),
                "selected_source": initial_diagnostics.get("selected_source"),
                "array_ids": [array.array_id for array in initial_snapshot.arrays],
                "source_ids": [source.source_id for source in initial_snapshot.sources],
                "motion_authoring": "time_sampled_usd_xform_ops",
                "initial_stage_diagnostics": initial_diagnostics,
                "backend_results": backend_results,
                "backend_statuses": {
                    backend_id: result["status"]
                    for backend_id, result in backend_results.items()
                },
                "jsonl_frame_count": trace_summary["frame_count"],
                "jsonl_backend_frame_counts": trace_summary["backend_frame_counts"],
                "diagnostics_namespaces": trace_summary["diagnostics_namespaces"],
                "debug_primitive_count": sum(
                    int(result.get("debug_primitive_count", 0))
                    for result in backend_results.values()
                    if result.get("status") == "passed"
                ),
                "debug_primitive_kinds": _aggregate_backend_debug_field(
                    backend_results,
                    "debug_primitive_kinds",
                ),
                "debug_primitive_labels": _aggregate_backend_debug_field(
                    backend_results,
                    "debug_primitive_labels",
                ),
                "room_acoustics_status": room_result["status"],
                "room_acoustics_skip_reason": room_result.get("skip_reason"),
            }
        )
    except BaseException as exc:  # noqa: BLE001 - smoke evidence records exact error.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "smallest_next_fix": _smallest_next_fix(exc, evidence),
            }
        )
    finally:
        _write_evidence(args.out, evidence)
        if simulation_app is not None:
            try:
                simulation_app.close()
                evidence["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - shutdown diagnostic only.
                evidence["simulation_app_close_error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.flush()

    return exit_code


def _binding_cfg() -> IsaacAudioSceneBindingCfg:
    return IsaacAudioSceneBindingCfg(
        discovery_roots=("/World",),
        robot_base_prim_path="/World/RobotBase",
        restrict_arrays_to_robot=True,
        preferred_array="rig_front",
        required_arrays=True,
        required_sources=True,
    )


def _room_spec() -> RoomAcousticsSpec:
    return RoomAcousticsSpec(
        room_id="isaac_sim_live_smoke_room",
        dimensions_m=(6.0, 6.0, 3.0),
        absorption=0.35,
        max_order=0,
        air_absorption=False,
        ray_tracing=False,
        # Explicit placement: the robot moves to x=1 and the source between
        # (4,0,0) and (0,4,0); the room must contain both endpoints.
        origin_m=(-1.0, -1.0, -1.5),
    )


def _run_backend_smoke(
    *,
    stage: Any,
    backend_id: str,
    binding_cfg: IsaacAudioSceneBindingCfg,
    room_spec: RoomAcousticsSpec | None,
    frame_trace_path: Path,
    config_path: Path,
    start_record_index: int,
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        binding_cfg=binding_cfg,
        backend=backend_id,
        timestamp_ms=0,
        usd_time_code=0.0,
        usd_time_code_scale=1.0,
        update_period_s=0.05,
        max_events=1,
        room=room_spec,
        debug_draw=True,
        waveform_sink=(
            FrameWaveformWriter(WAVEFORM_EVIDENCE_DIR)
            if backend_id == "room_acoustics"
            else None
        ),
    )
    sensor.start()
    frames: dict[str, AudioSensorFrame] = {}
    debug_primitives: dict[str, list[dict[str, Any]]] = {}
    trace_record_index = start_record_index
    try:
        for phase, sim_time_s in SMOKE_PHASES:
            _update_kit_once(evidence)
            raw_frame = sensor.update(sim_time_s=sim_time_s, force=True)
            frame = _augment_live_frame(
                frame=raw_frame,
                phase=phase,
                reference_frame=frames.get("before"),
                frame_trace_path=frame_trace_path,
                config_path=config_path,
                record_index=trace_record_index,
            )
            append_frame_jsonl(frame, frame_trace_path)
            frames[phase] = frame
            debug_primitives[phase] = debug_primitives_to_dicts(
                sensor.latest_debug_primitives
            )
            trace_record_index += 1
    finally:
        sensor.close()

    result = _summarize_backend(
        backend_id=backend_id,
        frames=frames,
        debug_primitives=debug_primitives,
    )
    return result, trace_record_index


def _augment_live_frame(
    *,
    frame: AudioSensorFrame,
    phase: str,
    reference_frame: AudioSensorFrame | None,
    frame_trace_path: Path,
    config_path: Path,
    record_index: int,
) -> AudioSensorFrame:
    diagnostics = dict(frame.diagnostics)
    stage_snapshot = dict(diagnostics.get("stage_snapshot", {}))
    diagnostics.update(
        {
            "stage_snapshot": stage_snapshot,
            "discovery": {
                "selected_array": stage_snapshot.get("selected_array"),
                "selected_source": stage_snapshot.get("selected_source"),
                "array_count": stage_snapshot.get("array_count"),
                "source_count": stage_snapshot.get("source_count"),
                "discovery_roots": stage_snapshot.get("discovery_roots"),
                "metadata_precedence": stage_snapshot.get("metadata_precedence"),
            },
            "transforms": {
                "robot_base_transform": stage_snapshot.get("robot_base_transform"),
                "array_transforms": stage_snapshot.get("array_transforms", {}),
                "source_transforms": stage_snapshot.get("source_transforms", {}),
                "microphone_transforms": stage_snapshot.get(
                    "microphone_transforms",
                    {},
                ),
            },
            "backend_diagnostics": {
                "backend_id": frame.backend_id,
                "frame_backend": diagnostics.get("backend"),
                "active_source_count": diagnostics.get("active_source_count"),
                "detection_count": len(frame.detections),
            },
            "movement": _movement_diagnostics(
                phase=phase,
                frame=frame,
                reference_frame=reference_frame,
            ),
            "writer": {
                "format": "AudioSensorFrame v1 JSONL",
                "jsonl_path": str(frame_trace_path),
                "config_path": str(config_path),
                "record_index": record_index,
            },
        }
    )
    return replace(frame, diagnostics=diagnostics)


def _summarize_backend(
    *,
    backend_id: str,
    frames: dict[str, AudioSensorFrame],
    debug_primitives: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    before = frames["before"]
    moved = frames["moved"]
    inactive = frames["inactive"]
    before_detection = _first_detection(before)
    moved_detection = _first_detection(moved)
    before_bearing = _bearing(before)
    moved_bearing = _bearing(moved)
    before_source_pose = _first_source_pose(before)
    moved_source_pose = _first_source_pose(moved)
    before_array_pose = _array_pose(before)
    moved_array_pose = _array_pose(moved)
    moved_debug_primitives = debug_primitives.get("moved", [])
    moved_kinds = sorted({str(item.get("kind")) for item in moved_debug_primitives})
    moved_labels = sorted(
        {
            str(item["label"])
            for item in moved_debug_primitives
            if item.get("label") is not None
        }
    )
    moved_labels_by_kind: dict[str, list[str]] = {}
    for item in moved_debug_primitives:
        kind = item.get("kind")
        label = item.get("label")
        if kind is None or label is None:
            continue
        moved_labels_by_kind.setdefault(str(kind), []).append(str(label))
    moved_labels_by_kind = {
        kind: sorted(labels) for kind, labels in sorted(moved_labels_by_kind.items())
    }
    result: dict[str, Any] = {
        "status": "passed",
        "backend_id": backend_id,
        "frame_ids": {phase: frame.frame_id for phase, frame in frames.items()},
        "frame_indices": {phase: frame.frame_index for phase, frame in frames.items()},
        "timestamps_ms": {phase: frame.timestamp_ms for phase, frame in frames.items()},
        "stage_time_codes": {
            phase: frame.diagnostics.get("stage_snapshot", {}).get("time_code")
            for phase, frame in frames.items()
        },
        "before_source_pose": before_source_pose,
        "after_source_pose": moved_source_pose,
        "before_array_pose": before_array_pose,
        "after_array_pose": moved_array_pose,
        "before_bearing_deg": before_bearing,
        "after_bearing_deg": moved_bearing,
        "movement_changed_bearing": _changed_scalar(before_bearing, moved_bearing),
        "movement_changed_source_pose": _changed_pose(
            before_source_pose,
            moved_source_pose,
        ),
        "movement_changed_array_pose": _changed_pose(
            before_array_pose,
            moved_array_pose,
        ),
        "movement_changed_stage_time_code": (
            before.diagnostics.get("stage_snapshot", {}).get("time_code")
            != moved.diagnostics.get("stage_snapshot", {}).get("time_code")
        ),
        "backend_diagnostics_changed": (
            None
            if before_detection is None or moved_detection is None
            else before_detection.diagnostics != moved_detection.diagnostics
        ),
        "inactive_detection_count": len(inactive.detections),
        "debug_primitive_count": len(moved_debug_primitives),
        "debug_primitive_kinds": moved_kinds,
        "debug_primitive_labels": moved_labels,
        "debug_primitive_labels_by_kind": moved_labels_by_kind,
        "diagnostics_namespaces": sorted(moved.diagnostics),
        "jsonl_record_indices": {
            phase: frame.diagnostics["writer"]["record_index"]
            for phase, frame in frames.items()
        },
    }
    if backend_id == "tdoa_synthetic" and moved_detection is not None:
        result["tdoa_diagnostics_present"] = bool(
            moved_detection.per_mic_delay_s
            and moved_detection.diagnostics.get("tdoa_matrix_s")
        )
        result["tdoa_matrix_s"] = moved_detection.diagnostics.get("tdoa_matrix_s")
        result["per_mic_delay_s"] = moved_detection.per_mic_delay_s
    if backend_id == "room_acoustics" and moved_detection is not None:
        room_keys = (
            "room_config",
            "pyroomacoustics_version",
            "estimated_tdoa_matrix_s",
            "gcc_phat_peaks",
            "direct_path_delay_s",
            "per_mic_rms",
            "rir_length_samples",
            "rir_peak_delay_s",
            "waveform_sample_count",
        )
        result["room_diagnostics_present"] = all(
            key in moved_detection.diagnostics for key in room_keys
        )
        result["room_frame_diagnostics_present"] = bool(
            moved.diagnostics.get("physical_waveform")
            and moved.diagnostics.get("room_config")
            and moved.diagnostics.get("per_source_rir_summary")
        )
        result["room_config"] = moved.diagnostics.get("room_config")
        result["pyroomacoustics_version"] = moved.diagnostics.get(
            "pyroomacoustics_version"
        )
        result["rir_length_samples"] = moved_detection.diagnostics.get(
            "rir_length_samples"
        )
        result["rir_peak_delay_s"] = moved_detection.diagnostics.get("rir_peak_delay_s")
        result["waveform_sample_count"] = moved_detection.diagnostics.get(
            "waveform_sample_count"
        )
    if backend_id == "room_acoustics":
        result["waveform_roundtrip"] = _waveform_roundtrip_evidence(frames)
    return result


def _waveform_roundtrip_evidence(
    frames: dict[str, AudioSensorFrame],
) -> dict[str, Any]:
    """Prove each room frame wrote a WAV that round-trips through soundfile."""

    try:
        import numpy as np
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "room_acoustics live smoke requires soundfile for waveform "
            "round-trip evidence; install the 'room' extra in the Isaac "
            "Python environment."
        ) from exc
    evidence: dict[str, Any] = {}
    for phase, frame in frames.items():
        if not frame.waveform_paths:
            raise RuntimeError(
                f"room_acoustics frame for phase {phase!r} has empty "
                "waveform_paths."
            )
        path = Path(frame.waveform_paths[0])
        if not path.is_file():
            raise RuntimeError(
                f"room_acoustics waveform file {str(path)!r} is missing for "
                f"phase {phase!r}."
            )
        data, rate = sf.read(path, always_2d=True)
        mic_count = len(frame.aggregate_per_mic_rms)
        window_sample_count = int(frame.diagnostics.get("window_sample_count", 0))
        if int(rate) != int(frame.sample_rate_hz or 0):
            raise RuntimeError(
                f"waveform sample rate {rate} does not match frame rate "
                f"{frame.sample_rate_hz} for phase {phase!r}."
            )
        if data.shape[1] != mic_count:
            raise RuntimeError(
                f"waveform channel count {data.shape[1]} does not match "
                f"{mic_count} microphones for phase {phase!r}."
            )
        if data.shape[0] < window_sample_count:
            raise RuntimeError(
                f"waveform sample count {data.shape[0]} is shorter than the "
                f"window ({window_sample_count}) for phase {phase!r}."
            )
        if not np.all(np.isfinite(data)):
            raise RuntimeError(
                f"waveform for phase {phase!r} contains non-finite samples."
            )
        evidence[phase] = {
            "path": str(path),
            "sample_rate_hz": int(rate),
            "channels": int(data.shape[1]),
            "sample_count": int(data.shape[0]),
            "window_sample_count": window_sample_count,
        }
    return evidence


def _validate_backend_result(result: dict[str, Any]) -> None:
    backend_id = str(result.get("backend_id"))
    if result.get("status") != "passed":
        raise RuntimeError(f"{backend_id} did not pass the live smoke.")
    required_true = (
        "movement_changed_bearing",
        "movement_changed_source_pose",
        "movement_changed_array_pose",
        "movement_changed_stage_time_code",
    )
    missing = [key for key in required_true if not result.get(key)]
    if missing:
        raise RuntimeError(
            f"{backend_id} did not prove live movement changes: {missing}."
        )
    if result.get("inactive_detection_count") != 0:
        raise RuntimeError(f"{backend_id} emitted detections for an inactive source.")
    if int(result.get("debug_primitive_count", 0)) <= 0:
        raise RuntimeError(f"{backend_id} did not produce debug primitives.")
    debug_kinds = set(result.get("debug_primitive_kinds", ()))
    required_debug_kinds = {"microphone", "source", "bearing_ray", "sector_wedge"}
    missing_debug_kinds = sorted(required_debug_kinds - debug_kinds)
    if missing_debug_kinds:
        raise RuntimeError(
            f"{backend_id} did not produce required debug primitive kinds: "
            f"{missing_debug_kinds}."
        )
    debug_labels = tuple(
        str(label) for label in result.get("debug_primitive_labels", ())
    )
    if not debug_labels:
        raise RuntimeError(f"{backend_id} did not record debug primitive labels.")
    required_label_prefixes = ("mic:", "source:", "bearing:", "sector:")
    missing_label_prefixes = [
        prefix
        for prefix in required_label_prefixes
        if not any(label.startswith(prefix) for label in debug_labels)
    ]
    if missing_label_prefixes:
        raise RuntimeError(
            f"{backend_id} did not record required debug primitive labels: "
            f"{missing_label_prefixes}."
        )
    if backend_id == "tdoa_synthetic" and not result.get("tdoa_diagnostics_present"):
        raise RuntimeError("tdoa_synthetic did not expose TDOA diagnostics.")
    if backend_id == "room_acoustics" and not (
        result.get("room_diagnostics_present")
        and result.get("room_frame_diagnostics_present")
    ):
        raise RuntimeError("room_acoustics did not expose room/RIR diagnostics.")
    if backend_id == "room_acoustics" and not result.get("waveform_roundtrip"):
        raise RuntimeError(
            "room_acoustics did not produce waveform round-trip evidence."
        )


def _validate_jsonl_frames(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError("Expected at least one JSONL frame trace record.")
    backend_counts: dict[str, int] = {}
    diagnostics_namespaces: set[str] = set()
    for line in lines:
        frame = frame_from_trace_dict(json.loads(line))
        backend_counts[frame.backend_id] = backend_counts.get(frame.backend_id, 0) + 1
        diagnostics_namespaces.update(frame.diagnostics)
        for key in (
            "stage_snapshot",
            "discovery",
            "transforms",
            "backend_diagnostics",
            "movement",
            "writer",
        ):
            if key not in frame.diagnostics:
                raise RuntimeError(
                    f"Frame {frame.frame_id!r} is missing diagnostics namespace "
                    f"{key!r}."
                )
    return {
        "frame_count": len(lines),
        "backend_frame_counts": backend_counts,
        "diagnostics_namespaces": sorted(diagnostics_namespaces),
    }


def _aggregate_backend_debug_field(
    backend_results: dict[str, Any],
    field_name: str,
) -> list[str]:
    values: set[str] = set()
    for result in backend_results.values():
        if result.get("status") != "passed":
            continue
        for value in result.get(field_name, ()):
            values.add(str(value))
    return sorted(values)


def _author_stage(stage: Any) -> None:
    stage.DefinePrim("/World", "Xform")
    robot_base = stage.DefinePrim("/World/RobotBase", "Xform")
    _set_translate_samples(
        robot_base,
        {
            "default": (0.0, 0.0, 0.0),
            0.0: (0.0, 0.0, 0.0),
            0.1: (1.0, 0.0, 0.0),
            0.5: (1.0, 0.0, 0.0),
        },
    )
    stage.DefinePrim("/World/RobotBase/ArrayMount", "Xform")
    moving_source = stage.DefinePrim("/World/MovingSource", "Xform")
    _set_translate_samples(
        moving_source,
        {
            "default": (4.0, 0.0, 0.0),
            0.0: (4.0, 0.0, 0.0),
            0.1: (0.0, 4.0, 0.0),
            0.5: (0.0, 4.0, 0.0),
        },
    )
    create_sound_prim(
        stage,
        prim_path="/World/MovingSource/Sound",
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    sound = stage.GetPrimAtPath("/World/MovingSource/Sound")
    attach_sound_source_attrs(
        sound,
        source_id="speaker_front",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        start_time_s=0.0,
        duration_s=0.25,
        gain_db=0.0,
        directivity="omni",
    )
    array_prim = stage.DefinePrim("/World/RobotBase/ArrayMount/AudioArray", "Xform")
    _set_translate_samples(
        array_prim,
        {
            "default": (0.0, 0.0, 0.0),
            0.0: (0.0, 0.0, 0.0),
            0.1: (0.0, 0.0, 0.0),
            0.5: (0.0, 0.0, 0.0),
        },
    )
    _set_orient_samples(
        array_prim,
        {
            "default": quaternion_from_yaw_deg(0.0),
            0.0: quaternion_from_yaw_deg(0.0),
            0.1: quaternion_from_yaw_deg(90.0),
            0.5: quaternion_from_yaw_deg(90.0),
        },
    )
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
    )
    for microphone in microphone_layout("quad_front"):
        mic_prim = stage.DefinePrim(
            f"/World/RobotBase/ArrayMount/AudioArray/{microphone.mic_id}",
            "Xform",
        )
        moved_position = (
            (0.12, 0.0, 0.0)
            if microphone.mic_id == "front"
            else microphone.relative_position_m
        )
        _set_translate_samples(
            mic_prim,
            {
                "default": microphone.relative_position_m,
                0.0: microphone.relative_position_m,
                0.1: moved_position,
                0.5: moved_position,
            },
        )
        _set_custom_attr(mic_prim, "ias:microphone_id", microphone.mic_id)
        _set_custom_attr(mic_prim, "ias:gain_db", microphone.gain_db)
    create_listener_prim(
        stage,
        prim_path="/World/RobotBase/ArrayMount/AudioArray/Listener",
        array_id="rig_front",
    )


def _ensure_isaac_runtime(evidence: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        if app is not None:
            evidence["simulation_app_bootstrap"] = "attached_existing_kit_app"
            _record_kit_app_info(evidence, app)
            return None
    except Exception as exc:  # noqa: BLE001 - diagnostic before bootstrap.
        evidence["kit_app_prebootstrap_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from isaacsim import SimulationApp  # type: ignore
    except Exception as exc:  # noqa: BLE001 - evidence records exact blocker.
        raise RuntimeError(
            "Could not import isaacsim.SimulationApp from the requested Python runtime."
        ) from exc

    simulation_app = SimulationApp({"headless": True})
    evidence["simulation_app_bootstrap"] = "created"
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    if app is None:
        raise RuntimeError("SimulationApp started, but omni.kit.app.get_app() is None.")
    _record_kit_app_info(evidence, app)
    return simulation_app


def _record_kit_app_info(evidence: dict[str, Any], app: Any) -> None:
    evidence["kit_app_available"] = True
    for method_name, evidence_key in (
        ("get_app_version", "kit_app_version"),
        ("get_build_version", "kit_build_version"),
        ("get_version", "kit_version"),
    ):
        method = getattr(app, method_name, None)
        if not callable(method):
            evidence[evidence_key] = "unavailable"
            continue
        try:
            evidence[evidence_key] = str(method())
        except Exception as exc:  # noqa: BLE001 - diagnostic only.
            evidence[evidence_key] = f"unavailable: {type(exc).__name__}: {exc}"


def _update_kit_once(evidence: dict[str, Any]) -> None:
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        if app is not None and hasattr(app, "update"):
            app.update()
            evidence["kit_frame_update"] = "called"
            return
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        evidence["kit_frame_update_error"] = f"{type(exc).__name__}: {exc}"
        return
    evidence["kit_frame_update"] = "unavailable"


def _validate_runtime(evidence: dict[str, Any]) -> None:
    if not evidence.get("kit_app_available"):
        raise RuntimeError("No live Kit app was available for the Isaac Sim smoke.")
    if not evidence.get("pxr_imported") or not evidence.get("omni_imported"):
        raise RuntimeError("pxr and omni must import inside the Isaac Sim smoke.")
    if not evidence.get("gpu_visible"):
        raise RuntimeError("GPU is not visible to the Isaac Sim smoke runtime.")


def _set_translate_samples(prim: Any, samples: dict[Any, Any]) -> None:
    from pxr import Gf, Usd, UsdGeom  # type: ignore

    op = UsdGeom.Xformable(prim).AddTranslateOp()
    for time_code, position in samples.items():
        value = Gf.Vec3d(*position)
        if time_code == "default":
            op.Set(value)
        else:
            op.Set(value, Usd.TimeCode(float(time_code)))


def _set_orient_samples(prim: Any, samples: dict[Any, Any]) -> None:
    from pxr import Gf, Usd, UsdGeom  # type: ignore

    op = UsdGeom.Xformable(prim).AddOrientOp()
    for time_code, quat in samples.items():
        x, y, z, w = quat
        value = Gf.Quatf(float(w), Gf.Vec3f(float(x), float(y), float(z)))
        if time_code == "default":
            op.Set(value)
        else:
            op.Set(value, Usd.TimeCode(float(time_code)))


def _set_custom_attr(prim: Any, name: str, value: object) -> None:
    attr = prim.CreateAttribute(name, _value_type_name(value), custom=True)
    attr.Set(value)


def _value_type_name(value: object) -> Any:
    from pxr import Sdf  # type: ignore

    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int) and not isinstance(value, bool):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    return Sdf.ValueTypeNames.String


def _movement_diagnostics(
    *,
    phase: str,
    frame: AudioSensorFrame,
    reference_frame: AudioSensorFrame | None,
) -> dict[str, Any]:
    source_pose = _first_source_pose(frame)
    array_pose = _array_pose(frame)
    bearing = _bearing(frame)
    return {
        "phase": phase,
        "timestamp_ms": frame.timestamp_ms,
        "frame_index": frame.frame_index,
        "source_pose": source_pose,
        "array_pose": array_pose,
        "bearing_deg": bearing,
        "source_pose_changed_from_reference": (
            False
            if reference_frame is None
            else _changed_pose(_first_source_pose(reference_frame), source_pose)
        ),
        "array_pose_changed_from_reference": (
            False
            if reference_frame is None
            else _changed_pose(_array_pose(reference_frame), array_pose)
        ),
        "bearing_changed_from_reference": (
            False
            if reference_frame is None
            else _changed_scalar(_bearing(reference_frame), bearing)
        ),
    }


def _array_pose(frame: AudioSensorFrame) -> dict[str, Any] | None:
    if frame.array_pose is None:
        return None
    return {
        "position_m": frame.array_pose.position_m,
        "orientation_xyzw": frame.array_pose.orientation_xyzw,
        "frame": frame.array_pose.frame,
    }


def _first_source_pose(frame: AudioSensorFrame) -> dict[str, Any] | None:
    detection = _first_detection(frame)
    if detection is None or detection.source_pose is None:
        return None
    pose = detection.source_pose
    return {
        "position_m": pose.position_m,
        "orientation_xyzw": pose.orientation_xyzw,
        "frame": pose.frame,
    }


def _first_detection(frame: AudioSensorFrame) -> Any | None:
    return None if not frame.detections else frame.detections[0]


def _bearing(frame: AudioSensorFrame) -> float | None:
    detection = _first_detection(frame)
    if detection is None:
        return None
    return detection.doa.estimated_bearing_deg


def _changed_pose(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left != right
    return _changed_sequence(left.get("position_m"), right.get("position_m")) or (
        _changed_sequence(left.get("orientation_xyzw"), right.get("orientation_xyzw"))
    )


def _changed_sequence(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left != right
    return any(
        abs(float(a) - float(b)) > 1e-6 for a, b in zip(left, right, strict=True)
    )


def _changed_scalar(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left != right
    return abs(float(left) - float(right)) > 1e-6


def _record_isaacsim_preflight(evidence: dict[str, Any]) -> None:
    spec = importlib.util.find_spec("isaacsim")
    if spec is None or spec.origin is None:
        evidence["isaacsim_package"] = "not_found"
        return

    package_dir = Path(spec.origin).resolve().parent
    kit_dir = package_dir / "kit"
    eula_path = kit_dir / "EULA_ACCEPTED"
    env_value = os.environ.get("OMNI_KIT_ACCEPT_EULA")
    evidence.update(
        {
            "isaacsim_package": str(package_dir),
            "isaacsim_version_file": _read_first_line(package_dir / "VERSION"),
            "omni_kit_accept_eula_env_set": env_value is not None,
            "omni_kit_accept_eula_env_truthy": (env_value or "").lower()
            in {"y", "yes", "1"},
            "eula_accepted_file": str(eula_path),
            "eula_accepted_file_exists": eula_path.is_file(),
            "eula_accepted_file_truthy": _read_first_line(eula_path).lower()
            in {"y", "yes", "1"},
            "eula_preflight_note": (
                "Local Isaac Sim kit_app.py checks OMNI_KIT_ACCEPT_EULA or "
                "kit/EULA_ACCEPTED before prompting."
            ),
        }
    )


def _record_loaded_runtime_modules(evidence: dict[str, Any]) -> None:
    for module_name, evidence_key in (
        ("isaacsim", "isaacsim_version"),
        ("omni", "omni_version"),
        ("pxr", "pxr_version"),
    ):
        try:
            module = __import__(module_name)
        except Exception as exc:  # noqa: BLE001 - diagnostic only.
            evidence[evidence_key] = f"unavailable: {type(exc).__name__}: {exc}"
            continue
        evidence[evidence_key] = str(getattr(module, "__version__", "unavailable"))
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            evidence[f"{module_name}_module_file"] = str(module_file)


def _record_gpu_preflight(evidence: dict[str, Any]) -> None:
    try:
        import torch  # type: ignore

        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        evidence.update(
            {
                "gpu_probe": "torch.cuda",
                "gpu_visible": cuda_available and device_count > 0,
                "cuda_device_count": device_count,
                "cuda_device_names": [
                    torch.cuda.get_device_name(index) for index in range(device_count)
                ],
                "torch_version": str(getattr(torch, "__version__", "")),
                "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES"),
            }
        )
    except Exception as exc:  # noqa: BLE001 - smoke evidence records this.
        evidence.update(
            {
                "gpu_probe": "torch.cuda",
                "gpu_visible": False,
                "gpu_probe_error": f"{type(exc).__name__}: {exc}",
            }
        )


def _record_nvidia_smi(evidence: dict[str, Any]) -> None:
    nvidia_smi = shutil.which("nvidia-smi")
    evidence["nvidia_smi_path"] = nvidia_smi
    if nvidia_smi is None:
        evidence["nvidia_smi"] = "not_found"
        return
    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        evidence["nvidia_smi"] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        evidence["nvidia_smi"] = f"{type(exc).__name__}: {exc}"


def _write_config(
    *,
    evidence_path: Path,
    config_path: Path,
    frame_trace_path: Path,
    binding_cfg: IsaacAudioSceneBindingCfg,
    room_spec: RoomAcousticsSpec,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "stage": {
            "mode": "in_memory_usd_authored_inside_isaac_sim",
            "root": "/World",
            "robot_base_prim_path": "/World/RobotBase",
            "array_prim_path": "/World/RobotBase/ArrayMount/AudioArray",
            "source_prim_path": "/World/MovingSource/Sound",
            "motion_time_codes": [0.0, 0.1, 0.5],
            "motion": {
                "robot_base_translate_m": {
                    "0.0": [0.0, 0.0, 0.0],
                    "0.1": [1.0, 0.0, 0.0],
                },
                "source_translate_m": {
                    "0.0": [4.0, 0.0, 0.0],
                    "0.1": [0.0, 4.0, 0.0],
                },
                "array_yaw_deg": {"0.0": 0.0, "0.1": 90.0},
                "front_microphone_translate_m": {
                    "0.0": [0.08, 0.0, 0.0],
                    "0.1": [0.12, 0.0, 0.0],
                },
            },
        },
        "binding": {
            "discovery_roots": list(binding_cfg.discovery_roots),
            "robot_base_prim_path": binding_cfg.robot_base_prim_path,
            "restrict_arrays_to_robot": binding_cfg.restrict_arrays_to_robot,
            "preferred_array": binding_cfg.preferred_array,
            "required_arrays": binding_cfg.required_arrays,
            "required_sources": binding_cfg.required_sources,
        },
        "sensor": {
            "backends": list(REQUIRED_BACKENDS + OPTIONAL_BACKENDS),
            "required_backends": list(REQUIRED_BACKENDS),
            "optional_backends": list(OPTIONAL_BACKENDS),
            "usd_time_code_scale": 1.0,
            "update_period_s": 0.05,
            "max_events": 1,
            "debug_draw": True,
        },
        "room_acoustics": {
            "room_id": room_spec.room_id,
            "dimensions_m": list(room_spec.dimensions_m),
            "absorption": room_spec.absorption,
            "max_order": room_spec.max_order,
            "air_absorption": room_spec.air_absorption,
            "ray_tracing": room_spec.ray_tracing,
        },
        "outputs": {
            "evidence_json": str(evidence_path),
            "frames_jsonl": str(frame_trace_path),
            "config_json": str(config_path),
        },
    }
    _write_json(config_path, config)
    return config


def _remove_existing_artifacts(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def _read_first_line(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, UnicodeDecodeError, IndexError):
        return ""


def _smallest_next_fix(exc: BaseException, evidence: dict[str, Any]) -> str:
    message = str(exc)
    if "GPU is not visible" in message:
        return (
            "Rerun the live target in the host-visible Isaac Sim runtime with CUDA "
            "and NVIDIA devices exposed."
        )
    if "SimulationApp" in message:
        return (
            "Point ISAAC_SIM_COMMAND at an Isaac Sim Python that can import "
            "isaacsim.SimulationApp."
        )
    if evidence.get("room_acoustics_available") and "room_acoustics" in message:
        return (
            "Inspect the installed pyroomacoustics runtime and room diagnostics; "
            "Task 6 requires L2 only when the optional dependency is present."
        )
    return "Inspect the recorded traceback and rerun the exact live target."


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    _write_json(path, evidence)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
