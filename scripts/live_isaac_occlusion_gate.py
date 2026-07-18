"""Live Isaac Sim occlusion gate: a wall attenuates RMS and flags detections.

Authors a real USD stage in the omni.usd context with a microphone array, a
sound source, and a collider wall. With the wall aside, the sensor sees a
clear direct path; with the wall between source and array, PhysX raycast
occlusion must attenuate per-mic RMS by the configured attenuation and set
the detection ``occluded`` flag. Authoring ``ias:transmission_loss_db`` on
the wall must change the measured attenuation to the material value, and a
sensor bound with ``rediscover_each_update=True`` must run full discovery on
every update. The gate also records live-path cache counters and captures a
viewport screenshot with the occlusion-colored bearing-ray overlay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import (
    WaveformWriteResult,
    write_multichannel_wav,
)
from isaac_audio_sensors.core.types import AudioSensorFrame, RoomAcousticsSpec
from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    attach_sound_source_attrs,
    create_sound_prim,
)
from isaac_audio_sensors.isaac.viz.overlays import debug_primitives_to_dicts

ARRAY_PRIM_PATH = "/World/AudioRig/AudioArray"
SOURCE_PRIM_PATH = "/World/Sources/SpeakerA"
WALL_PRIM_PATH = "/World/Wall"
GATE_CAMERA_PRIM_PATH = "/World/GateCamera"
ARRAY_POSITION = (0.0, 0.0, 1.0)
SOURCE_POSITION = (4.0, 0.0, 1.0)
WALL_BLOCKING_POSITION = (2.0, 0.0, 1.0)
WALL_CLEAR_POSITION = (2.0, 10.0, 1.0)
WALL_SCALE = (0.2, 4.0, 3.0)
OCCLUSION_MAX_ATTENUATION_DB = 20.0
MATERIAL_WALL_TRANSMISSION_DB = 12.0
ATTENUATION_TOLERANCE_DB = 0.5
SETTLE_UPDATE_COUNT = 12
POLICY_UPDATE_COUNT = 3
S3_7_OUTPUT = Path("outputs/isaac_audio_sensors/S3/S3.7")
MOVING_Y_POSITIONS = (0.25, 0.08, 0.0, -0.08, -0.25)
MOVING_BLOCKED_MIC_IDS = (
    (),
    ("right",),
    ("front", "right", "rear", "left"),
    ("left",),
    (),
)
MOVING_WALL_SCALE = (0.2, 0.11, 3.0)
MOVING_WINDOW_S = 0.05


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json"),
    )
    args = parser.parse_args()
    frame_trace_path = args.out.with_suffix(".frames.jsonl")
    config_path = args.out.with_suffix(".config.json")
    screenshot_path = args.out.with_suffix(".viewport.png")
    for path in (args.out, frame_trace_path, config_path, screenshot_path):
        with suppress(FileNotFoundError):
            path.unlink()

    evidence: dict[str, Any] = {
        "argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "status": "started",
        "headless": True,
        "evidence_path": str(args.out),
        "frame_trace_path": str(frame_trace_path),
        "config_path": str(config_path),
        "screenshot_path": str(screenshot_path),
        "occlusion_max_attenuation_db": OCCLUSION_MAX_ATTENUATION_DB,
        "attenuation_tolerance_db": ATTENUATION_TOLERANCE_DB,
    }
    simulation_app = None
    sensor = None
    exit_code = 0

    try:
        simulation_app = _ensure_isaac_runtime(evidence)

        import omni.timeline  # type: ignore
        import omni.usd  # type: ignore

        usd_context = omni.usd.get_context()
        usd_context.new_stage()
        stage = usd_context.get_stage()
        if stage is None:
            raise RuntimeError("omni.usd context has no stage after new_stage().")
        wall_translate_op, wall_scale_op = _author_stage(stage)
        _write_config_snapshot(config_path)
        evidence["stage_authored"] = True

        timeline = omni.timeline.get_timeline_interface()
        timeline.play()
        _update_app(SETTLE_UPDATE_COUNT)
        evidence["timeline_playing"] = True

        sensor = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            backend="geometry_only",
            update_period_s=0.05,
            debug_draw=True,
            occlusion_enabled=True,
            occlusion_max_attenuation_db=OCCLUSION_MAX_ATTENUATION_DB,
            writer_path=frame_trace_path,
        ).start()

        clear_frame = sensor.update(sim_time_s=0.0, force=True)
        evidence["clear_phase"] = _phase_evidence(clear_frame)
        _require(
            clear_frame.detections,
            "clear phase produced no detections",
        )
        clear_detection = clear_frame.detections[0]
        _require(
            clear_detection.occluded is False,
            "clear phase detection is unexpectedly occluded",
        )
        clear_occlusion = clear_detection.diagnostics.get("occlusion")
        _require(
            clear_occlusion is not None and clear_occlusion["occlusion_factor"] == 0.0,
            "clear phase occlusion was not computed with factor 0.0: "
            f"{clear_occlusion!r}",
        )

        from pxr import Gf  # type: ignore

        wall_translate_op.Set(Gf.Vec3d(*WALL_BLOCKING_POSITION))
        _update_app(SETTLE_UPDATE_COUNT)

        walled_frame = sensor.update(sim_time_s=0.2, force=True)
        final_frame = sensor.update(sim_time_s=0.4, force=True)
        evidence["walled_phase"] = _phase_evidence(walled_frame)
        walled_detection = walled_frame.detections[0]
        _require(
            walled_detection.occluded is True,
            "walled phase detection is not flagged occluded",
        )
        walled_occlusion = walled_detection.diagnostics["occlusion"]
        _require(
            all(walled_occlusion["per_mic_blocked"].values()),
            "walled phase did not block every source-to-mic ray: "
            f"{walled_occlusion['per_mic_blocked']!r}",
        )
        _require(
            WALL_PRIM_PATH in walled_occlusion["hit_prim_paths"],
            "wall prim is not among occlusion hit paths: "
            f"{walled_occlusion['hit_prim_paths']!r}",
        )

        measured = _measured_attenuation_db(clear_detection, walled_detection)
        evidence["measured_attenuation_db"] = measured
        for mic_id, attenuation_db in measured.items():
            _require(
                abs(attenuation_db - OCCLUSION_MAX_ATTENUATION_DB)
                <= ATTENUATION_TOLERANCE_DB,
                f"mic {mic_id!r} attenuated by {attenuation_db:.3f} dB, expected "
                f"{OCCLUSION_MAX_ATTENUATION_DB} +/- {ATTENUATION_TOLERANCE_DB} dB",
            )

        cache = sensor._stage_cache  # noqa: SLF001 - gate evidence introspection.
        cache_evidence = {
            "full_discovery_count": cache.full_discovery_count,
            "cached_tick_count": cache.cached_tick_count,
            "invalidation_reasons": list(cache.invalidation_reasons),
            "policy": "rediscover_each_update"
            if cache.rediscover_each_update
            else "cache_until_invalidated",
        }
        evidence["stage_cache"] = cache_evidence
        # Three sensor updates ran; steady-state ticks must come from the
        # cache instead of full stage traversals.
        _require(
            cache.cached_tick_count >= 1,
            f"live path never used the discovery cache: {cache_evidence!r}",
        )
        _require(
            cache.full_discovery_count < 3,
            f"every live tick re-ran full discovery: {cache_evidence!r}",
        )

        # Material phase: authoring an explicit transmission loss on the wall
        # must change the measured attenuation from the default to the
        # material value through the live transmission resolver.
        _author_wall_transmission_loss(stage, MATERIAL_WALL_TRANSMISSION_DB)
        _update_app(SETTLE_UPDATE_COUNT)
        material_frame = sensor.update(sim_time_s=0.5, force=True)
        evidence["material_phase"] = _phase_evidence(material_frame)
        material_detection = material_frame.detections[0]
        material_occlusion = material_detection.diagnostics["occlusion"]
        _require(
            material_occlusion.get("occlusion_model") == "raycast_transmission_v1",
            "material phase did not report the transmission occlusion model: "
            f"{material_occlusion!r}",
        )
        _require(
            material_occlusion.get("hit_materials", {}).get(WALL_PRIM_PATH)
            == "usd_attribute",
            "material phase did not resolve the authored USD attribute: "
            f"{material_occlusion.get('hit_materials')!r}",
        )
        measured_material = _measured_attenuation_db(
            clear_detection, material_detection
        )
        evidence["measured_material_attenuation_db"] = measured_material
        for mic_id, attenuation_db in measured_material.items():
            _require(
                abs(attenuation_db - MATERIAL_WALL_TRANSMISSION_DB)
                <= ATTENUATION_TOLERANCE_DB,
                f"mic {mic_id!r} attenuated by {attenuation_db:.3f} dB with the "
                f"material wall, expected {MATERIAL_WALL_TRANSMISSION_DB} +/- "
                f"{ATTENUATION_TOLERANCE_DB} dB",
            )

        # Cache-policy phase: a sensor bound with rediscover_each_update=True
        # must run one full discovery per update.
        policy_sensor = IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            binding_cfg=IsaacAudioSceneBindingCfg(
                rediscover_each_update=True,
                preferred_array="rig_front",
            ),
            backend="geometry_only",
            update_period_s=0.05,
        ).start()
        policy_frames = [
            policy_sensor.update(sim_time_s=tick * 0.2, force=True)
            for tick in range(POLICY_UPDATE_COUNT)
        ]
        policy_cache = policy_sensor._stage_cache  # noqa: SLF001 - evidence.
        policy_evidence = {
            "full_discovery_count": policy_cache.full_discovery_count,
            "cached_tick_count": policy_cache.cached_tick_count,
            "policy": policy_frames[-1].diagnostics["stage_snapshot"][
                "discovery_cache"
            ]["policy"],
        }
        evidence["cache_policy"] = policy_evidence
        _require(
            policy_cache.full_discovery_count == POLICY_UPDATE_COUNT,
            "rediscover_each_update did not force full discovery per update: "
            f"{policy_evidence!r}",
        )
        _require(
            policy_evidence["policy"] == "rediscover_each_update",
            f"policy diagnostics missing: {policy_evidence!r}",
        )
        policy_sensor.close()

        # Redraw the occlusion-colored overlay immediately before capture.
        sensor.update(sim_time_s=0.6, force=True)
        evidence["debug_primitives"] = debug_primitives_to_dicts(
            sensor.latest_debug_primitives
        )
        if sensor.debug_drawer is not None:
            evidence["debug_draw_status"] = sensor.debug_drawer.last_status
            evidence["debug_draw_error"] = sensor.debug_drawer.last_error
        evidence["screenshot"] = _capture_viewport_screenshot(
            screenshot_path,
            framed_paths=(ARRAY_PRIM_PATH, SOURCE_PRIM_PATH, WALL_PRIM_PATH),
        )
        _require(
            evidence["screenshot"]["status"] == "captured",
            f"viewport screenshot was not captured: {evidence['screenshot']!r}",
        )

        evidence["final_frame_index"] = final_frame.frame_index
        sensor.close()
        sensor = None
        moving = _run_moving_occluder_phase(
            stage=stage,
            wall_translate_op=wall_translate_op,
            wall_scale_op=wall_scale_op,
            screenshot_path=screenshot_path,
        )
        evidence["s3_7_moving_occluder"] = moving
        evidence["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 - gate evidence records the error.
        if isinstance(exc, KeyboardInterrupt):
            raise
        exit_code = 2
        evidence.update(
            {
                "status": "blocked" if _is_runtime_blocker(exc) else "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        if sensor is not None:
            with suppress(Exception):
                sensor.close()
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


class _MovingWaveformSink:
    """Retain float64 mixtures and write the exact S3.7 FLOAT WAV names."""

    def __init__(self, output_dir: Path, prefix: str) -> None:
        self.output_dir = output_dir
        self.prefix = prefix
        self.mixtures: list[Any] = []

    def write_frame_mixture(self, **kwargs: Any) -> WaveformWriteResult:
        import numpy as np

        mixture = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        index = len(self.mixtures)
        self.mixtures.append(mixture)
        path = self.output_dir / f"{self.prefix}_{index:02d}.wav"
        write_multichannel_wav(
            path,
            mixture,
            sample_rate_hz=int(kwargs["sample_rate_hz"]),
        )
        return WaveformWriteResult(
            paths=(str(path),),
            diagnostics={
                "mode": "per_frame",
                "channel_mic_ids": list(kwargs["mic_ids"]),
                "sample_count": int(mixture.shape[1]),
                "window_sample_count": int(kwargs["window_sample_count"]),
                "sample_rate_hz": int(kwargs["sample_rate_hz"]),
                "subtype": "FLOAT",
            },
        )

    def close(self) -> None:
        return None


def _run_moving_occluder_phase(
    *,
    stage: Any,
    wall_translate_op: Any,
    wall_scale_op: Any,
    screenshot_path: Path,
) -> dict[str, Any]:
    """Execute the additive five-state S3.7 live room-acoustics scenario."""

    import numpy as np
    import soundfile
    from pxr import Gf  # type: ignore

    output = S3_7_OUTPUT
    wav_dir = output / "live_moving_occluder_wavs"
    output.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": output / "live_moving_occluder_summary.json",
        "frames": output / "live_moving_occluder_frames.jsonl",
        "hashes": output / "live_moving_occluder_wav_sha256.json",
        "stage": output / "live_moving_occluder_stage.usda",
        "environment": output / "live_moving_occluder_environment.json",
        "log": output / "live_moving_occluder.log",
        "viewport": output / "live_moving_occluder_viewport.png",
    }
    for path in (*paths.values(), *wav_dir.glob("*.wav")):
        with suppress(FileNotFoundError):
            path.unlink()
    wall_scale_op.Set(Gf.Vec3f(*MOVING_WALL_SCALE))
    wall_translate_op.Set(Gf.Vec3d(2.0, MOVING_Y_POSITIONS[0], 1.0))
    _author_wall_transmission_loss(stage, MATERIAL_WALL_TRANSMISSION_DB)
    attach_sound_source_attrs(
        stage.GetPrimAtPath(SOURCE_PRIM_PATH),
        source_id="speaker_front",
        class_label="Tone",
        position_world=SOURCE_POSITION,
        audio_asset_path="generated://tone",
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        directivity="omni",
    )
    _update_app(SETTLE_UPDATE_COUNT)

    room = RoomAcousticsSpec(
        room_id="s3_7_live_room",
        dimensions_m=(6.0, 6.0, 3.0),
        origin_m=(-1.0, -3.0, 0.0),
        absorption="pra.rough_concrete",
        max_order=1,
        air_absorption=False,
        ray_tracing=False,
    )
    observed_sink = _MovingWaveformSink(wav_dir, "observed")
    reference_sink = _MovingWaveformSink(wav_dir, "reference")
    observed = None
    reference = None
    observations: list[dict[str, Any]] = []
    try:
        observed = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            source_prim_path=SOURCE_PRIM_PATH,
            backend="room_acoustics",
            update_period_s=MOVING_WINDOW_S,
            max_events=1,
            room=room,
            occlusion_enabled=True,
            occlusion_max_attenuation_db=OCCLUSION_MAX_ATTENUATION_DB,
            waveform_dir=wav_dir / "observed_internal",
        ).start()
        reference = IsaacAudioArraySensor.from_stage(
            stage=stage,
            array_prim_path=ARRAY_PRIM_PATH,
            source_prim_path=SOURCE_PRIM_PATH,
            backend="room_acoustics",
            update_period_s=MOVING_WINDOW_S,
            max_events=1,
            room=room,
            occlusion_enabled=False,
            waveform_dir=wav_dir / "reference_internal",
        ).start()
        observed._waveform_sink = observed_sink  # noqa: SLF001 - gate tee.
        reference._waveform_sink = reference_sink  # noqa: SLF001 - gate tee.
        for index, (y_position, expected_blocked) in enumerate(
            zip(MOVING_Y_POSITIONS, MOVING_BLOCKED_MIC_IDS, strict=True)
        ):
            if index:
                wall_translate_op.Set(Gf.Vec3d(2.0, y_position, 1.0))
                _update_app(SETTLE_UPDATE_COUNT)
            sim_time_s = 1.0 + index * 0.1
            observed_frame = observed.update(sim_time_s=sim_time_s, force=True)
            reference_frame = reference.update(sim_time_s=sim_time_s, force=True)
            observed_wave = observed_sink.mixtures[index]
            reference_wave = reference_sink.mixtures[index]
            observation = _validate_moving_frame(
                index=index,
                y_position=y_position,
                expected_blocked=expected_blocked,
                observed_frame=observed_frame,
                reference_frame=reference_frame,
                observed_wave=observed_wave,
                reference_wave=reference_wave,
            )
            observations.append(observation)
            with paths["frames"].open("a", encoding="utf-8") as stream:
                for kind, frame in (
                    ("observed", observed_frame),
                    ("reference", reference_frame),
                ):
                    payload = frame_to_trace_dict(frame)
                    payload["s3_7_role"] = kind
                    payload["s3_7_state_index"] = index
                    stream.write(json.dumps(payload, sort_keys=True) + "\n")
            with paths["log"].open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(observation, sort_keys=True) + "\n")
            if index == 2:
                screenshot = _capture_viewport_screenshot(
                    paths["viewport"],
                    framed_paths=(ARRAY_PRIM_PATH, SOURCE_PRIM_PATH, WALL_PRIM_PATH),
                )
                _require(
                    screenshot["status"] == "captured",
                    f"S3.7 moving viewport failed: {screenshot!r}",
                )
        observed_cache = observed._stage_cache  # noqa: SLF001 - gate evidence.
        full_counts = [row["full_discovery_count"] for row in observations]
        _require(
            max(full_counts) == min(full_counts),
            f"wall pose motion forced full rediscovery: {full_counts!r}",
        )
        _require(
            observed_cache.cached_tick_count >= 4,
            "moving phase did not use cached discovery for wall pose steps",
        )
    finally:
        if reference is not None:
            reference.close()
        if observed is not None:
            observed.close()

    stage.GetRootLayer().Export(str(paths["stage"]))
    wav_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(wav_dir.glob("*.wav"))
    }
    _write_evidence(paths["hashes"], wav_hashes)
    environment = {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "soundfile_version": soundfile.__version__,
        "numpy_version": np.__version__,
        "pyroomacoustics_version": __import__("pyroomacoustics").__version__,
        "headless": True,
    }
    _write_evidence(paths["environment"], environment)
    summary = {
        "status": "passed",
        "scenario": "S3.7_live_moving_occluder",
        "wall_y_positions_m": list(MOVING_Y_POSITIONS),
        "wall_scale": list(MOVING_WALL_SCALE),
        "expected_blocked_mic_ids": [list(row) for row in MOVING_BLOCKED_MIC_IDS],
        "observations": observations,
        "wav_sha256": wav_hashes,
        "screenshot": str(paths["viewport"]),
        "assertions": {
            "blocked_maps_exact": True,
            "waveform_rms_consistent": True,
            "attenuation_within_0_5_db": True,
            "occluder_moved_on_four_transitions": True,
            "pose_motion_kept_discovery_cached": True,
        },
    }
    _write_evidence(paths["summary"], summary)
    _ingest_moving_phase_into_dynamic_gate()
    return summary


def _ingest_moving_phase_into_dynamic_gate() -> None:
    gate_path = S3_7_OUTPUT / "dynamic_rooms_gate.json"
    if not gate_path.is_file():
        return
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    rows = dict(gate.get("rows", {}))
    rows["live_moving_occluder"] = "passed"
    gate["rows"] = rows
    gate["dependency_gated_rows"] = [
        name for name, status in rows.items() if status not in {"passed", "failed"}
    ]
    gate["failed_rows"] = [name for name, status in rows.items() if status == "failed"]
    gate["live_artifacts_pending"] = []
    gate["status"] = (
        "failed"
        if gate["failed_rows"]
        else "dependency_unavailable"
        if gate["dependency_gated_rows"]
        else "passed"
    )
    gate["artifact_sha256"] = {
        path.relative_to(S3_7_OUTPUT).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(S3_7_OUTPUT.rglob("*"))
        if path.is_file() and path != gate_path
    }
    _write_evidence(gate_path, gate)


def _validate_moving_frame(
    *,
    index: int,
    y_position: float,
    expected_blocked: tuple[str, ...],
    observed_frame: AudioSensorFrame,
    reference_frame: AudioSensorFrame,
    observed_wave: Any,
    reference_wave: Any,
) -> dict[str, Any]:
    import numpy as np

    detection = observed_frame.detections[0]
    occlusion = detection.diagnostics["occlusion"]
    expected_map = {
        mic_id: mic_id in expected_blocked
        for mic_id in ("front", "right", "rear", "left")
    }
    _require(occlusion["per_mic_blocked"] == expected_map, "blocked map mismatch")
    _require(
        occlusion["occlusion_factor"] == len(expected_blocked) / 4,
        "occlusion factor mismatch",
    )
    _require(
        occlusion["occlusion_model"] == "raycast_transmission_v1",
        "occlusion model mismatch",
    )
    state = observed_frame.diagnostics["acoustics_state"]
    _require(state["occlusion_recompute_count"] == 1, "recompute count mismatch")
    if index:
        _require(
            state["refresh_reasons"] == ["occluder_moved"],
            f"missing occluder_moved at state {index}: {state!r}",
        )
        _require(
            state["changed_occlusion_pairs"] == ["rig_front:speaker_front"],
            f"changed pair mismatch at state {index}: {state!r}",
        )
    evidence = state["material_evidence"].get(f"occluder:{WALL_PRIM_PATH}")
    if expected_blocked:
        _require(
            evidence is not None and evidence["evidence"] == "nominal",
            f"wall evidence missing at state {index}: {state!r}",
        )
    observed_rms = np.sqrt(np.mean(np.square(observed_wave), axis=1))
    reference_rms = np.sqrt(np.mean(np.square(reference_wave), axis=1))
    mic_ids = ("front", "right", "rear", "left")
    attenuation = {}
    for mic_index, mic_id in enumerate(mic_ids):
        frame_rms = observed_frame.aggregate_per_mic_rms[mic_id]
        detection_rms = detection.per_mic_rms[mic_id]
        _require(abs(frame_rms - observed_rms[mic_index]) <= 1e-12, "frame RMS drift")
        _require(
            abs(detection_rms - observed_rms[mic_index]) <= 1e-12,
            "detection RMS drift",
        )
        value = 20.0 * math.log10(reference_rms[mic_index] / observed_rms[mic_index])
        attenuation[mic_id] = value
        expected = MATERIAL_WALL_TRANSMISSION_DB if mic_id in expected_blocked else 0.0
        _require(
            abs(value - expected) <= ATTENUATION_TOLERANCE_DB,
            f"state {index} mic {mic_id} attenuation {value} != {expected}",
        )
    cache = observed_frame.diagnostics["stage_snapshot"]["discovery_cache"]
    return {
        "index": index,
        "wall_y_m": y_position,
        "expected_blocked": list(expected_blocked),
        "observed_blocked": [key for key, value in expected_map.items() if value],
        "occlusion_factor": occlusion["occlusion_factor"],
        "attenuation_db": attenuation,
        "aggregate_per_mic_rms": dict(observed_frame.aggregate_per_mic_rms),
        "reference_per_mic_rms": dict(reference_frame.aggregate_per_mic_rms),
        "refresh_reasons": state["refresh_reasons"],
        "changed_occlusion_pairs": state.get("changed_occlusion_pairs", []),
        "occlusion_recompute_count": state["occlusion_recompute_count"],
        "full_discovery_count": cache["full_discovery_count"],
        "cached_tick_count": cache["cached_tick_count"],
        "observed_waveform_sha256": hashlib.sha256(observed_wave.tobytes()).hexdigest(),
        "reference_waveform_sha256": hashlib.sha256(
            reference_wave.tobytes()
        ).hexdigest(),
    }


def _ensure_isaac_runtime(evidence: dict[str, Any]) -> Any | None:
    try:
        import omni.kit.app  # type: ignore

        if omni.kit.app.get_app() is not None:
            evidence["simulation_app_bootstrap"] = "attached_existing_kit_app"
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
    return simulation_app


def _author_stage(stage: Any) -> tuple[Any, Any]:
    """Author the gate scene and return the wall's translate op."""

    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics  # type: ignore

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(1_000.0)

    array_prim = stage.DefinePrim(ARRAY_PRIM_PATH, "Xform")
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=ARRAY_POSITION,
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
    )

    create_sound_prim(
        stage,
        prim_path=SOURCE_PRIM_PATH,
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=0.0,
        gain_db=0.0,
    )
    attach_sound_source_attrs(
        stage.GetPrimAtPath(SOURCE_PRIM_PATH),
        source_id="speaker_front",
        class_label="Speech",
        position_world=SOURCE_POSITION,
        audio_asset_path="generated://impulse",
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        directivity="omni",
    )

    wall = UsdGeom.Cube.Define(stage, WALL_PRIM_PATH)
    wall.CreateSizeAttr(1.0)
    wall.CreateDisplayColorAttr([(0.75, 0.2, 0.15)])
    wall_xform = UsdGeom.Xformable(wall.GetPrim())
    wall_translate_op = wall_xform.AddTranslateOp()
    wall_translate_op.Set(Gf.Vec3d(*WALL_CLEAR_POSITION))
    wall_scale_op = wall_xform.AddScaleOp()
    wall_scale_op.Set(Gf.Vec3f(*WALL_SCALE))
    UsdPhysics.CollisionAPI.Apply(wall.GetPrim())

    # Side-view camera perpendicular to the source-to-array axis so the
    # occlusion-colored bearing ray and the wall are both visible.
    camera = UsdGeom.Camera.Define(stage, GATE_CAMERA_PRIM_PATH)
    camera.CreateFocalLengthAttr(14.0)
    camera_xform = UsdGeom.Xformable(camera.GetPrim())
    camera_xform.AddTranslateOp().Set(Gf.Vec3d(2.0, -13.0, 2.0))
    camera_xform.AddRotateXYZOp().Set(Gf.Vec3f(85.0, 0.0, 0.0))
    return wall_translate_op, wall_scale_op


def _author_wall_transmission_loss(stage: Any, loss_db: float) -> None:
    """Author an explicit transmission-loss attribute on the wall prim."""

    from pxr import Sdf  # type: ignore

    from isaac_audio_sensors.isaac.occlusion import TRANSMISSION_LOSS_ATTR

    wall_prim = stage.GetPrimAtPath(WALL_PRIM_PATH)
    attribute = wall_prim.CreateAttribute(
        TRANSMISSION_LOSS_ATTR,
        Sdf.ValueTypeNames.Double,
    )
    attribute.Set(float(loss_db))


def _update_app(count: int) -> None:
    import omni.kit.app  # type: ignore

    app = omni.kit.app.get_app()
    for _ in range(count):
        app.update()


def _phase_evidence(frame: AudioSensorFrame) -> dict[str, Any]:
    detections = [
        {
            "detection_id": detection.detection_id,
            "source_id": detection.source_id,
            "occluded": detection.occluded,
            "per_mic_rms": dict(detection.per_mic_rms),
            "occlusion": detection.diagnostics.get("occlusion"),
        }
        for detection in frame.detections
    ]
    return {
        "frame_id": frame.frame_id,
        "frame_index": frame.frame_index,
        "aggregate_per_mic_rms": dict(frame.aggregate_per_mic_rms),
        "detections": detections,
        "stage_occlusion_diagnostics": frame.diagnostics.get(
            "stage_snapshot",
            {},
        ).get("occlusion"),
    }


def _measured_attenuation_db(clear_detection, walled_detection) -> dict[str, float]:
    measured: dict[str, float] = {}
    for mic_id, clear_rms in clear_detection.per_mic_rms.items():
        walled_rms = walled_detection.per_mic_rms[mic_id]
        if clear_rms <= 0.0 or walled_rms <= 0.0:
            raise RuntimeError(
                f"non-positive RMS for mic {mic_id!r}: "
                f"clear={clear_rms}, walled={walled_rms}"
            )
        measured[mic_id] = 20.0 * math.log10(clear_rms / walled_rms)
    return measured


def _capture_viewport_screenshot(
    path: Path,
    *,
    framed_paths: tuple[str, ...],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "framed_paths": list(framed_paths),
    }
    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        if viewport is None:
            record.update({"status": "unavailable", "reason": "no active viewport"})
            return record
        try:
            viewport.camera_path = GATE_CAMERA_PRIM_PATH
            record["camera"] = GATE_CAMERA_PRIM_PATH
        except Exception as exc:  # noqa: BLE001 - fall back to prim framing.
            record["camera"] = f"failed: {type(exc).__name__}: {exc}"
            frame_prims = getattr(viewport_utility, "frame_viewport_prims", None)
            if callable(frame_prims):
                try:
                    frame_prims(viewport, prim_paths=list(framed_paths))
                    record["framed"] = True
                except Exception as frame_exc:  # noqa: BLE001 - best-effort.
                    record["framed"] = (
                        f"failed: {type(frame_exc).__name__}: {frame_exc}"
                    )
        # Let the renderer settle on the framed view before capturing.
        _update_app(SETTLE_UPDATE_COUNT)
        path.parent.mkdir(parents=True, exist_ok=True)
        capture = viewport_utility.capture_viewport_to_file(
            viewport,
            file_path=str(path),
        )
        wait_for_result = getattr(capture, "wait_for_result", None)
        if callable(wait_for_result):
            with suppress(Exception):
                wait_for_result()
        for _ in range(200):
            if path.is_file() and path.stat().st_size > 0:
                record["status"] = "captured"
                record["size_bytes"] = path.stat().st_size
                return record
            _update_app(1)
        record.update({"status": "failed", "reason": "capture file never materialized"})
    except Exception as exc:  # noqa: BLE001 - screenshot evidence records error.
        record.update(
            {
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
    return record


def _write_config_snapshot(config_path: Path) -> None:
    config = {
        "scenario": "isaac_occlusion_live_gate",
        "backend": "geometry_only",
        "array": {
            "prim_path": ARRAY_PRIM_PATH,
            "array_id": "rig_front",
            "layout_name": "quad_front",
            "position_world": ARRAY_POSITION,
        },
        "source": {
            "prim_path": SOURCE_PRIM_PATH,
            "source_id": "speaker_front",
            "position_world": SOURCE_POSITION,
        },
        "wall": {
            "prim_path": WALL_PRIM_PATH,
            "clear_position": WALL_CLEAR_POSITION,
            "blocking_position": WALL_BLOCKING_POSITION,
            "scale": WALL_SCALE,
            "collision_api": "UsdPhysics.CollisionAPI",
        },
        "occlusion": {
            "enabled": True,
            "max_attenuation_db": OCCLUSION_MAX_ATTENUATION_DB,
            "material_wall_transmission_db": MATERIAL_WALL_TRANSMISSION_DB,
            "occlusion_model": "raycast_transmission_v1",
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_runtime_blocker(exc: BaseException) -> bool:
    message = str(exc).lower()
    blockers = (
        "simulationapp",
        "isaacsim",
        "pyroomacoustics",
        "soundfile",
        "physx",
        "gpu",
        "display",
        "viewport",
    )
    return isinstance(exc, ModuleNotFoundError) or any(
        token in message for token in blockers
    )


if __name__ == "__main__":
    raise SystemExit(main())
