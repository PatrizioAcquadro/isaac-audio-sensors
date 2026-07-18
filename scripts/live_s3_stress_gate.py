#!/usr/bin/env python3
"""Run the teardown-safe live Isaac S3.8 motion/effects stress gate."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
import traceback
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.8"
SUMMARY = "live_stress_summary.json"
FRAMES = "live_stress_frames.jsonl"
AUDIO = "live_stress_audio.wav"
TELEMETRY = "live_stress_telemetry.csv"
STAGE = "live_stress_stage.usda"
ENVIRONMENT = "live_stress_environment.json"
LOG = "live_stress.log"
HASHES = "live_stress_sha256.json"

ARRAY_PATH = "/World/Robot/AudioMount"
SOURCE_A_PATH = "/World/Audio/SourceA"
SOURCE_B_PATH = "/World/Audio/SourceB"
OCCLUDER_PATH = "/World/Occluder"
SAMPLE_RATE_HZ = 48_000
WINDOW_S = 0.05
WINDOW_SAMPLES = 2_400
SCHEDULED_SLOTS = 800
CAPTURED_FRAMES = 600
WARMUP_FRAMES = 60
TIMED_FRAMES = 540
MIC_IDS = ("front", "right", "rear", "left")


class LivePrerequisiteError(RuntimeError):
    """A required live dependency or device is absent."""


class GateAssertionError(RuntimeError):
    """The live runtime executed but violated a frozen invariant."""


class _LatestSink:
    def __init__(self, result_type: type) -> None:
        self._result_type = result_type
        self.mixture: np.ndarray | None = None

    def write_frame_mixture(self, **kwargs: object) -> object:
        self.mixture = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        return self._result_type(paths=())

    def close(self) -> None:
        self.mixture = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = _paths(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        if path.name == LOG:
            _atomic_bytes(path, b"")

    environment = _initial_environment()
    summary: dict[str, Any] = {
        "status": "started",
        "scenario": "S3.8_live_motion_multi_source_stress",
        "entry_revision": "44608130727c2466f29919c5521218228e3de56a",
        "counts": {
            "scheduled_slots_per_phase": SCHEDULED_SLOTS,
            "captured_frames_per_phase": CAPTURED_FRAMES,
            "warmup_frames_per_phase": WARMUP_FRAMES,
            "timed_frames_per_phase": TIMED_FRAMES,
        },
    }
    _atomic_json(paths["environment"], environment)
    _log(paths["log"], "gate_started", argv=sys.argv)

    simulation_app = None
    sensors: list[Any] = []
    stage = None
    baseline_rss: float | None = None
    exit_code = 2
    teardown_error = None
    try:
        simulation_app = _bootstrap_kit(environment)
        dependencies = _dependencies()
        _record_runtime(environment, dependencies)
        _require_runtime(environment, dependencies)
        stage, authored = _author_stage(dependencies)
        _export_stage(stage, paths["stage"])

        baseline_samples = [_vmrss_mib() for _ in range(3)]
        baseline_rss = float(np.mean(baseline_samples))
        all_telemetry: list[dict[str, Any]] = []
        all_frames: list[dict[str, Any]] = []
        effects_on_audio: np.ndarray | None = None
        phases = {}
        for effects_enabled in (False, True):
            phase_name = "effects_on" if effects_enabled else "effects_off"
            phase = _run_phase(
                stage=stage,
                authored=authored,
                dependencies=dependencies,
                phase_name=phase_name,
                effects_enabled=effects_enabled,
                baseline_rss_mib=baseline_rss,
            )
            sensors.append(phase.pop("sensor"))
            all_telemetry.extend(phase.pop("telemetry"))
            phase_frames = phase.pop("frames")
            if effects_enabled:
                all_frames.extend(phase_frames)
                effects_on_audio = phase.pop("scheduled_audio")
            else:
                phase.pop("scheduled_audio")
            phases[phase_name] = phase

        assert effects_on_audio is not None
        ambiguity = _run_two_mic_gcc_subcase(dependencies)
        _write_jsonl(paths["frames"], all_frames)
        _write_telemetry(paths["telemetry"], all_telemetry)
        dependencies["write_multichannel_wav"](
            paths["audio"],
            effects_on_audio,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        _fsync(paths["audio"])
        _export_stage(stage, paths["stage"])

        off_latency = phases["effects_off"]["latency_ms"]
        on_latency = phases["effects_on"]["latency_ms"]
        latency_passed = (
            on_latency["p95"] <= 2.0 * off_latency["p95"] + 5.0
            and all(
                math.isfinite(value)
                for value in (on_latency["p99"], on_latency["maximum"])
            )
            and off_latency["timed_frame_count"] == TIMED_FRAMES
            and on_latency["timed_frame_count"] == TIMED_FRAMES
        )
        _require(latency_passed, "paired live latency regression exceeded its bound")
        _require(ambiguity["status"] == "Passed", "two-mic GCC ambiguity failed")
        _require(
            all(phase["status"] == "Passed" for phase in phases.values()),
            "one or more live phases failed",
        )
        _require(
            effects_on_audio.shape == (4, SCHEDULED_SLOTS * WINDOW_SAMPLES),
            "scheduled live waveform shape is incorrect",
        )
        for slot in range(SCHEDULED_SLOTS):
            block = effects_on_audio[
                :, slot * WINDOW_SAMPLES : (slot + 1) * WINDOW_SAMPLES
            ]
            if slot % 4 == 3:
                _require(np.count_nonzero(block) == 0, f"gap slot {slot} is nonzero")

        summary.update(
            {
                "status": "passed",
                "effects_config": _canonical_effects(dependencies),
                "phases": phases,
                "two_mic_gcc": ambiguity,
                "latency_bound": {
                    "formula": "effects_on_p95_ms <= 2*effects_off_p95_ms + 5",
                    "passed": latency_passed,
                },
                "baseline_rss_mib": baseline_rss,
                "baseline_rss_samples_mib": baseline_samples,
                "finite_value_scan": "passed",
                "identity_invariant": "passed",
                "gap_invariant": "passed",
            }
        )
        exit_code = 0
        _log(paths["log"], "gate_passed")
    except BaseException as exc:  # noqa: BLE001 - durable exact live verdict.
        status = "blocked" if isinstance(exc, LivePrerequisiteError) else "failed"
        summary.update(
            {
                "status": status,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        _log(
            paths["log"],
            "gate_not_passed",
            status=status,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
    finally:
        for sensor in reversed(sensors):
            with suppress(Exception):
                sensor.close()
        if stage is not None:
            with suppress(Exception):
                _export_stage(stage, paths["stage"])
        gc.collect()
        final_post_teardown_rss = _vmrss_mib()
        summary["final_post_teardown_rss_mib"] = final_post_teardown_rss
        if baseline_rss is not None:
            final_post_teardown_delta = final_post_teardown_rss - baseline_rss
            final_post_teardown_passed = final_post_teardown_delta <= 64.0
            summary["final_post_teardown_rss_bound"] = {
                "delta_mib": final_post_teardown_delta,
                "maximum_delta_mib": 64.0,
                "passed": final_post_teardown_passed,
            }
            if summary["status"] == "passed" and not final_post_teardown_passed:
                summary["status"] = "failed"
                summary["error_type"] = "GateAssertionError"
                summary["error"] = (
                    "final post-teardown RSS delta exceeded the 64 MiB bound"
                )
                exit_code = 2
        environment["recorded_at_utc"] = _utc_now()
        environment["simulation_app_closed"] = simulation_app is None
        _atomic_json(paths["environment"], environment)
        summary["teardown"] = {
            "status": "provisional",
            "simulation_app_close_error": None,
        }
        summary["artifact_inventory"] = _inventory(paths, exclude=("summary", "hashes"))
        _atomic_json(paths["summary"], summary)
        sys.stdout.flush()

        if simulation_app is not None:
            try:
                simulation_app.close()
                environment["simulation_app_closed"] = True
            except Exception as exc:  # noqa: BLE001 - teardown evidence.
                teardown_error = f"{type(exc).__name__}: {exc}"
                if summary["status"] == "passed":
                    summary["status"] = "failed"
                    exit_code = 2
            environment["recorded_at_utc"] = _utc_now()
            _atomic_json(paths["environment"], environment)
        summary["teardown"] = {
            "status": "passed" if teardown_error is None else "failed",
            "simulation_app_close_error": teardown_error,
        }
        summary["artifact_inventory"] = _inventory(paths, exclude=("summary", "hashes"))
        _atomic_json(paths["summary"], summary)
        _write_hashes(paths)
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return exit_code


def _run_phase(
    *,
    stage: Any,
    authored: dict[str, Any],
    dependencies: dict[str, Any],
    phase_name: str,
    effects_enabled: bool,
    baseline_rss_mib: float,
) -> dict[str, Any]:
    effects = (
        _all_effects(dependencies)
        if effects_enabled
        else dependencies["EffectsConfig"]()
    )
    sink = _LatestSink(dependencies["WaveformWriteResult"])
    sensor = dependencies["IsaacAudioArraySensor"].from_stage(
        stage=stage,
        array_prim_path=ARRAY_PATH,
        backend="room_acoustics",
        update_period_s=WINDOW_S,
        max_events=8,
        room=dependencies["RoomAcousticsSpec"](
            room_id="s3_8_live_room",
            dimensions_m=(12.5, 4.0, 3.0),
            absorption="pra.rough_concrete",
            max_order=3,
            origin_m=(0.0, 0.0, 0.0),
        ),
        occlusion_enabled=True,
        effects=effects,
    ).start()
    sensor._waveform_sink = sink  # noqa: SLF001 - in-memory timed-path evidence.

    frames = []
    telemetry = []
    scheduled_audio = np.zeros(
        (4, SCHEDULED_SLOTS * WINDOW_SAMPLES), dtype=np.float32
    )
    latencies = []
    rss_samples = []
    capture_index = 0
    persistent_ids = {"source-a", "source-b"}
    for slot in range(SCHEDULED_SLOTS):
        _move_scene(authored, dependencies, slot)
        dependencies["app"].update()
        throttled = slot % 4 == 3
        row: dict[str, Any] = {
            "phase": phase_name,
            "scheduled_index": slot,
            "requested": not throttled,
            "captured": False,
            "throttled": throttled,
            "capture_index": None,
            "latency_ms": None,
            "rss_mib": None,
            "monotonic_s": time.monotonic(),
        }
        if throttled:
            telemetry.append(row)
            continue
        before = time.perf_counter_ns()
        frame = sensor.update(
            sim_time_s=(slot + 1) * WINDOW_S,
            timestamp_ms=slot * 50,
            force=True,
        )
        latency_ms = (time.perf_counter_ns() - before) / 1_000_000.0
        _require(sink.mixture is not None, "room backend did not expose a mixture")
        mixture = sink.mixture[:, :WINDOW_SAMPLES]
        _require(mixture.shape == (4, WINDOW_SAMPLES), "mixture shape changed")
        frame_payload = dependencies["frame_to_trace_dict"](frame)
        _require(not _contains_nonfinite(frame_payload), "non-finite frame")
        _require(np.isfinite(mixture).all(), "non-finite live waveform")
        ids = {detection.source_id for detection in frame.detections}
        _require(ids == persistent_ids, f"source identity changed: {ids!r}")
        scheduled_audio[
            :, slot * WINDOW_SAMPLES : (slot + 1) * WINDOW_SAMPLES
        ] = mixture.astype(np.float32)
        if effects_enabled:
            frames.append(
                {
                    "scheduled_index": slot,
                    "capture_index": capture_index,
                    "frame": frame_payload,
                }
            )
        row.update(
            {
                "captured": True,
                "capture_index": capture_index,
                "latency_ms": latency_ms,
            }
        )
        if capture_index >= WARMUP_FRAMES:
            latencies.append(latency_ms)
        if capture_index % 20 == 0 or capture_index == CAPTURED_FRAMES - 1:
            rss = _vmrss_mib()
            row["rss_mib"] = rss
            rss_samples.append(
                {
                    "frame_index": capture_index,
                    "monotonic_s": time.monotonic(),
                    "rss_mib": rss,
                }
            )
        telemetry.append(row)
        capture_index += 1

    _require(capture_index == CAPTURED_FRAMES, "captured frame count is not 600")
    _require(len(latencies) == TIMED_FRAMES, "timed frame count is not 540")
    measured_rss = [row for row in rss_samples if row["frame_index"] >= WARMUP_FRAMES]
    _require(len(measured_rss) >= 27, "live RSS sample count is below 27")
    rss_fit = _ols(measured_rss)
    peak_delta = max(row["rss_mib"] for row in rss_samples) - baseline_rss_mib
    rss_passed = rss_fit["slope_mib_per_1_000_frames"] <= 8.0 and peak_delta <= 256.0
    _require(rss_passed, "live RSS slope or peak bound exceeded")
    return {
        "status": "Passed",
        "sensor": sensor,
        "telemetry": telemetry,
        "frames": frames,
        "scheduled_audio": scheduled_audio,
        "scheduled_count": SCHEDULED_SLOTS,
        "captured_count": capture_index,
        "throttled_count": SCHEDULED_SLOTS - capture_index,
        "latency_ms": {
            "timed_frame_count": len(latencies),
            "mean": float(np.mean(latencies)),
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "p99": float(np.percentile(latencies, 99)),
            "maximum": float(np.max(latencies)),
        },
        "rss": {
            "sample_count": len(measured_rss),
            "ols": rss_fit,
            "peak_delta_mib": peak_delta,
            "bounds": {
                "slope_mib_per_1_000_frames_max": 8.0,
                "peak_delta_mib_max": 256.0,
            },
        },
    }


def _move_scene(
    authored: dict[str, Any], dependencies: dict[str, Any], slot: int
) -> None:
    phase = slot / (SCHEDULED_SLOTS - 1)
    triangle = 2.0 * phase if phase <= 0.5 else 2.0 * (1.0 - phase)
    range_a = 0.25 + 9.75 * triangle
    source_a = (1.0 + range_a, 2.0 - 0.5 + phase, 1.5)
    source_b = (4.0 + 2.0 * math.sin(2.0 * math.pi * phase), 3.0, 1.5)
    yaw_deg = -30.0 + 60.0 * triangle
    yaw = math.radians(yaw_deg)
    array = (1.0 + 0.5 * triangle, 2.0, 1.5)
    quaternion = (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))
    _set_pose(authored["source_a"], source_a, None, dependencies)
    _set_pose(authored["source_b"], source_b, None, dependencies)
    _set_pose(authored["array"], array, quaternion, dependencies)

    state = (slot // 160) % 5
    wall_y = (0.4, 2.25, 2.0, 2.0, 0.4)[state]
    authored["wall_translate"].Set(dependencies["Gf"].Vec3d(3.0, wall_y, 1.5))
    loss = 8.0 if state == 2 else 16.0 if state == 3 else 12.0
    authored["wall_loss"].Set(loss)


def _run_two_mic_gcc_subcase(dependencies: dict[str, Any]) -> dict[str, Any]:
    array = dependencies["create_microphone_array"](
        array_id="two_mic",
        prim_path="/World/TwoMic",
        layout_name="two_mic_y",
        position_world=(1.0, 2.0, 1.5),
    )
    source = dependencies["AudioSourceSpec"](
        source_id="ambiguity-source",
        prim_path="/World/AmbiguitySource",
        class_label="stress",
        audio_asset_path="generated://two_tone",
        position_world=(4.0, 2.0, 1.5),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
    )
    scene = dependencies["AudioSceneSnapshot"](
        stage_id="s3_8_two_mic_gcc",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
        room=dependencies["RoomAcousticsSpec"](
            room_id="s3_8_room",
            dimensions_m=(12.5, 4.0, 3.0),
            absorption=0.35,
            max_order=1,
            origin_m=(0.0, 0.0, 0.0),
        ),
    )
    surfaced = 0
    for frame_index in range(16):
        frame = dependencies["RoomAcousticsBackend"]().simulate(
            scene,
            array,
            dependencies["AudioTimeWindow"](
                start_time_s=frame_index * WINDOW_S,
                end_time_s=(frame_index + 1) * WINDOW_S,
                timestamp_ms=frame_index * 50,
                sample_rate_hz=SAMPLE_RATE_HZ,
                frame_index=frame_index,
                max_events=1,
            ),
        )
        doa = frame.detections[0].doa
        surfaced += int(
            doa.ambiguity_class is not None
            or len(doa.candidate_bearing_deg) > 1
        )
    return {
        "status": "Passed" if surfaced == 16 else "Failed",
        "frame_count": 16,
        "ambiguity_surfaced_count": surfaced,
    }


def _all_effects(dependencies: dict[str, Any]) -> object:
    point = dependencies["FrequencyResponsePointConfig"]
    response = {
        mic_id: dependencies["ChannelResponseMicConfig"](
            gain_db=(-1.5, 0.0, 1.0, -0.5)[index],
            delay_s=index / SAMPLE_RATE_HZ,
            polarity=1 if index % 2 == 0 else -1,
            frequency_response=(
                point(frequency_hz=500.0, magnitude_db=0.0),
                point(frequency_hz=2_000.0, magnitude_db=-1.0),
                point(frequency_hz=6_000.0, magnitude_db=0.5),
            ),
        )
        for index, mic_id in enumerate(MIC_IDS)
    }
    pattern = dependencies["DirectivityPatternConfig"](family="cardioid")
    return dependencies["EffectsConfig"](
        channel_response=dependencies["ChannelResponseConfig"](
            enabled=True, microphones=response
        ),
        noise=dependencies["NoiseConfig"](
            enabled=True,
            seed=38_017,
            self_noise=dependencies["SelfNoiseConfig"](
                default=dependencies["NoiseLevelSpecConfig"](level_db=-55.0)
            ),
            ambient=dependencies["AmbientNoiseConfig"](
                level_db=-50.0, coherent_fraction=0.25
            ),
        ),
        electronics=dependencies["ElectronicsConfig"](
            enabled=True,
            full_scale=1.0,
            bit_depth=16,
            dither_enabled=True,
            agc=dependencies["AgcConfig"](
                enabled=True,
                target_rms_dbfs=-18.0,
                attack_time_s=0.01,
                release_time_s=0.05,
                gain_floor_db=-12.0,
                gain_ceiling_db=12.0,
            ),
        ),
        directivity=dependencies["DirectivityConfig"](
            enabled=True,
            source_patterns=dependencies["DirectivityPatternSetConfig"](
                default=pattern
            ),
            mic_patterns=dependencies["DirectivityPatternSetConfig"](
                default=pattern
            ),
            mode="per_pair_direct_path",
        ),
        motion=dependencies["MotionEffectsConfig"](
            derive_velocity_from_poses=True,
            segments_per_window=8,
        ),
    )


def _canonical_effects(dependencies: dict[str, Any]) -> dict[str, Any]:
    effects = _all_effects(dependencies)
    return {
        "repr": repr(effects),
        "signal_seed": 20_260_718,
        "noise_seed": 38_017,
        "segments_per_window": effects.motion.segments_per_window,
        "all_disabled": effects.all_disabled,
    }


def _dependencies() -> dict[str, Any]:
    try:
        import omni.kit.app  # type: ignore
        import omni.usd  # type: ignore
        from pxr import Gf, Sdf, UsdGeom, UsdPhysics  # type: ignore

        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )
        from isaac_audio_sensors.core.effects import (
            AgcConfig,
            AmbientNoiseConfig,
            ChannelResponseConfig,
            ChannelResponseMicConfig,
            DirectivityConfig,
            DirectivityPatternConfig,
            DirectivityPatternSetConfig,
            EffectsConfig,
            ElectronicsConfig,
            FrequencyResponsePointConfig,
            MotionEffectsConfig,
            NoiseConfig,
            NoiseLevelSpecConfig,
            SelfNoiseConfig,
        )
        from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
        from isaac_audio_sensors.core.io.waveforms import (
            WaveformWriteResult,
            write_multichannel_wav,
        )
        from isaac_audio_sensors.core.microphone_array import (
            create_microphone_array,
        )
        from isaac_audio_sensors.core.types import (
            AudioSceneSnapshot,
            AudioSourceSpec,
            AudioTimeWindow,
            RoomAcousticsSpec,
        )
        from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
        from isaac_audio_sensors.isaac.stage_audio import (
            attach_microphone_array_attrs,
            attach_sound_source_attrs,
            create_sound_prim,
            set_prim_xform_pose,
        )
    except ImportError as exc:
        raise LivePrerequisiteError("Isaac/USD/package imports are incomplete") from exc
    app = omni.kit.app.get_app()
    if app is None:
        raise LivePrerequisiteError("Kit app is unavailable after bootstrap")
    return {
        "AgcConfig": AgcConfig,
        "AmbientNoiseConfig": AmbientNoiseConfig,
        "AudioSceneSnapshot": AudioSceneSnapshot,
        "AudioSourceSpec": AudioSourceSpec,
        "AudioTimeWindow": AudioTimeWindow,
        "ChannelResponseConfig": ChannelResponseConfig,
        "ChannelResponseMicConfig": ChannelResponseMicConfig,
        "DirectivityConfig": DirectivityConfig,
        "DirectivityPatternConfig": DirectivityPatternConfig,
        "DirectivityPatternSetConfig": DirectivityPatternSetConfig,
        "EffectsConfig": EffectsConfig,
        "ElectronicsConfig": ElectronicsConfig,
        "FrequencyResponsePointConfig": FrequencyResponsePointConfig,
        "Gf": Gf,
        "IsaacAudioArraySensor": IsaacAudioArraySensor,
        "MotionEffectsConfig": MotionEffectsConfig,
        "NoiseConfig": NoiseConfig,
        "NoiseLevelSpecConfig": NoiseLevelSpecConfig,
        "RoomAcousticsBackend": RoomAcousticsBackend,
        "RoomAcousticsSpec": RoomAcousticsSpec,
        "Sdf": Sdf,
        "SelfNoiseConfig": SelfNoiseConfig,
        "UsdGeom": UsdGeom,
        "UsdPhysics": UsdPhysics,
        "WaveformWriteResult": WaveformWriteResult,
        "app": app,
        "attach_microphone_array_attrs": attach_microphone_array_attrs,
        "attach_sound_source_attrs": attach_sound_source_attrs,
        "create_microphone_array": create_microphone_array,
        "create_sound_prim": create_sound_prim,
        "frame_to_trace_dict": frame_to_trace_dict,
        "omni": omni,
        "set_prim_xform_pose": set_prim_xform_pose,
        "write_multichannel_wav": write_multichannel_wav,
    }


def _author_stage(dependencies: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    UsdGeom = dependencies["UsdGeom"]
    UsdPhysics = dependencies["UsdPhysics"]
    Gf = dependencies["Gf"]
    Sdf = dependencies["Sdf"]
    context = dependencies["omni"].usd.get_context()
    context.new_stage()
    stage = context.get_stage()
    if stage is None:
        raise LivePrerequisiteError("omni.usd did not create a stage")
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")

    array = stage.DefinePrim(ARRAY_PATH, "Xform")
    dependencies["attach_microphone_array_attrs"](
        array,
        array_id="rig",
        sample_rate_hz=SAMPLE_RATE_HZ,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_cross",
        position_world=(1.0, 2.0, 1.5),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
    )
    for path, source_id, position in (
        (SOURCE_A_PATH, "source-a", (1.25, 1.5, 1.5)),
        (SOURCE_B_PATH, "source-b", (4.0, 3.0, 1.5)),
    ):
        dependencies["create_sound_prim"](
            stage,
            prim_path=path,
            audio_asset_path="generated://two_tone",
            spatial=True,
            loop=True,
            start_time_s=0.0,
            gain_db=0.0,
        )
        prim = stage.GetPrimAtPath(path)
        dependencies["attach_sound_source_attrs"](
            prim,
            source_id=source_id,
            class_label="stress",
            position_world=position,
            orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
            audio_asset_path="generated://two_tone",
            start_time_s=0.0,
            duration_s=None,
            gain_db=0.0,
            directivity="cardioid",
        )
    wall = UsdGeom.Cube.Define(stage, OCCLUDER_PATH)
    wall.CreateSizeAttr(1.0)
    xform = UsdGeom.Xformable(wall.GetPrim())
    translate = xform.AddTranslateOp()
    translate.Set(Gf.Vec3d(3.0, 0.4, 1.5))
    xform.AddScaleOp().Set(Gf.Vec3f(0.15, 1.0, 2.5))
    UsdPhysics.CollisionAPI.Apply(wall.GetPrim())
    from isaac_audio_sensors.isaac.occlusion import TRANSMISSION_LOSS_ATTR

    loss = wall.GetPrim().CreateAttribute(
        TRANSMISSION_LOSS_ATTR, Sdf.ValueTypeNames.Double
    )
    loss.Set(12.0)
    authored = {
        "array": array,
        "source_a": stage.GetPrimAtPath(SOURCE_A_PATH),
        "source_b": stage.GetPrimAtPath(SOURCE_B_PATH),
        "wall_translate": translate,
        "wall_loss": loss,
    }
    return stage, authored


def _set_pose(
    prim: Any,
    position: tuple[float, float, float],
    orientation: tuple[float, float, float, float] | None,
    dependencies: dict[str, Any],
) -> None:
    attr = prim.GetAttribute("ias:position_world")
    if attr.IsValid():
        attr.Set(dependencies["Gf"].Vec3d(*position))
    kwargs: dict[str, object] = {"position": position}
    if orientation is not None:
        kwargs["orientation"] = orientation
        orientation_attr = prim.GetAttribute("ias:orientation_world_quat")
        if orientation_attr.IsValid():
            orientation_attr.Set(
                dependencies["Gf"].Quatd(orientation[3], *orientation[:3])
            )
    dependencies["set_prim_xform_pose"](prim, **kwargs)


def _bootstrap_kit(environment: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        if omni.kit.app.get_app() is not None:
            environment["simulation_app_bootstrap"] = "attached"
            return None
    except Exception as exc:  # noqa: BLE001 - bootstrap diagnostic.
        environment["prebootstrap_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from isaacsim import SimulationApp  # type: ignore

        app = SimulationApp({"headless": True})
    except Exception as exc:  # noqa: BLE001 - prerequisite evidence.
        raise LivePrerequisiteError("Could not start headless SimulationApp") from exc
    environment["simulation_app_bootstrap"] = "created"
    return app


def _require_runtime(environment: dict[str, Any], dependencies: dict[str, Any]) -> None:
    if not dependencies["RoomAcousticsBackend"].is_available():
        raise LivePrerequisiteError("pyroomacoustics is unavailable")
    try:
        import torch  # type: ignore

        visible = bool(torch.cuda.is_available())
    except ImportError:
        visible = False
    environment["cuda_visible"] = visible
    if not visible:
        raise LivePrerequisiteError("No CUDA GPU is visible")
    if dependencies["app"] is None:
        raise LivePrerequisiteError("Kit update app is unavailable")


def _record_runtime(environment: dict[str, Any], dependencies: dict[str, Any]) -> None:
    environment["kit"] = {
        name: _safe_call(dependencies["app"], name)
        for name in ("get_app_version", "get_build_version", "get_version")
    }
    environment["dependencies"] = {
        name: _distribution_version(name)
        for name in ("isaac-audio-sensors", "numpy", "pyroomacoustics", "soundfile")
    }


def _initial_environment() -> dict[str, Any]:
    return {
        "command": sys.argv,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "revision": _git_output("rev-parse", "HEAD"),
        "dirty_tree": bool(_git_output("status", "--porcelain")),
        "non_secret_environment": {
            key: os.environ.get(key)
            for key in ("CUDA_VISIBLE_DEVICES", "OMNI_KIT_ACCEPT_EULA")
        },
    }


def _ols(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    x = np.asarray([row["frame_index"] for row in rows], dtype=float)
    y = np.asarray([row["rss_mib"] for row in rows], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    total = float(np.sum((y - np.mean(y)) ** 2))
    residual = float(np.sum((y - predicted) ** 2))
    return {
        "sample_count": len(rows),
        "slope_mib_per_1_000_frames": float(slope * 1_000.0),
        "intercept_mib": float(intercept),
        "r_squared": 1.0 if total == 0.0 else float(1.0 - residual / total),
    }


def _contains_nonfinite(value: object, *, key: str | None = None) -> bool:
    if key == "time_code":
        return False
    if isinstance(value, (float, np.floating)):
        return not math.isfinite(float(value))
    if isinstance(value, np.ndarray):
        return not bool(np.isfinite(value).all())
    if isinstance(value, dict):
        return any(
            _contains_nonfinite(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(child) for child in value)
    return False


def _paths(root: Path) -> dict[str, Path]:
    return {
        "summary": root / SUMMARY,
        "frames": root / FRAMES,
        "audio": root / AUDIO,
        "telemetry": root / TELEMETRY,
        "stage": root / STAGE,
        "environment": root / ENVIRONMENT,
        "log": root / LOG,
        "hashes": root / HASHES,
    }


def _atomic_json(path: Path, payload: object) -> None:
    _atomic_bytes(
        path,
        (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                allow_nan=False,
                default=str,
            )
            + "\n"
        ).encode(),
    )


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = b"".join(
        (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode()
        for row in rows
    )
    _atomic_bytes(path, payload)


def _write_telemetry(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_hashes(paths: dict[str, Path]) -> None:
    payload = {
        path.name: {
            "byte_count": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in paths.items()
        if name != "hashes" and path.is_file()
    }
    _atomic_json(paths["hashes"], payload)


def _inventory(
    paths: dict[str, Path], *, exclude: tuple[str, ...]
) -> dict[str, Any]:
    return {
        name: {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
        }
        for name, path in paths.items()
        if name not in exclude
    }


def _export_stage(stage: Any, path: Path) -> None:
    if not stage.GetRootLayer().Export(str(path.resolve())):
        raise GateAssertionError("stage export failed")
    _fsync(path)


def _fsync(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _log(path: Path, event: str, **fields: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        record = {"time_utc": _utc_now(), "event": event, **fields}
        stream.write(json.dumps(record, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _vmrss_mib() -> float:
    with Path("/proc/self/status").open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    raise RuntimeError("VmRSS is unavailable")


def _safe_call(owner: object, name: str) -> str:
    method = getattr(owner, name, None)
    if not callable(method):
        return "unavailable"
    with suppress(Exception):
        return str(method())
    return "unavailable"


def _distribution_version(name: str) -> str:
    with suppress(importlib.metadata.PackageNotFoundError):
        return importlib.metadata.version(name)
    return "not_installed"


def _git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateAssertionError(message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
