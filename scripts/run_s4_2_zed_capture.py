#!/usr/bin/env python3
"""Bounded local ZED 2i producer for the maintained S4.2 orchestrator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyzed.sl as sl

from isaac_audio_sensors.core.dataset.atomic import JsonlShardFile, write_json_atomic

_STOP_REQUESTED = False
_PROTOCOL_STDOUT: Any = None


def _request_stop(_signum: int, _frame: Any) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _vector(value: Any) -> list[float]:
    raw = value.get() if hasattr(value, "get") else value
    return [float(component) for component in raw]


def _timestamp() -> tuple[str, int]:
    return datetime.now(timezone.utc).isoformat(), time.monotonic_ns()


def _event(kind: str, **fields: Any) -> None:
    wall, monotonic = _timestamp()
    print(
        json.dumps(
            {
                "event": kind,
                "host_wall_time_utc": wall,
                "host_monotonic_ns": monotonic,
                **fields,
            },
            sort_keys=True,
        ),
        file=_PROTOCOL_STDOUT,
        flush=True,
    )


def _camera_identity(info: Any) -> dict[str, Any]:
    return {
        "model": str(info.camera_model).split(".")[-1].replace("_", " "),
        "serial": str(info.serial_number),
        "camera_firmware": str(info.camera_configuration.firmware_version),
        "sensor_firmware": str(info.sensors_configuration.firmware_version),
        "sdk_version": sl.Camera.get_sdk_version(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-serial", required=True)
    parser.add_argument("--expected-sdk", required=True)
    parser.add_argument("--expected-camera-firmware", required=True)
    parser.add_argument("--expected-sensor-firmware", required=True)
    args = parser.parse_args()
    global _PROTOCOL_STDOUT
    _PROTOCOL_STDOUT = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    if not 15 <= args.duration <= 60:
        parser.error("--duration must be within [15, 60] seconds")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("--output-dir must not contain existing files")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    summary_path = args.output_dir / "producer_summary.json"
    svo_path = args.output_dir / "capture.svo2"
    frames_path = args.output_dir / "frames.jsonl"
    camera = sl.Camera()
    init = sl.InitParameters()
    init.camera_resolution = sl.RESOLUTION.HD720
    init.camera_fps = 30
    init.depth_mode = sl.DEPTH_MODE.PERFORMANCE
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
    open_status = camera.open(init)
    if open_status != sl.ERROR_CODE.SUCCESS:
        payload = {
            "schema": "ias.s4_2.zed_producer_summary.v1",
            "status": "failed",
            "failure_reason": f"camera.open: {open_status}",
        }
        write_json_atomic(summary_path, payload)
        _event("failed", reason=payload["failure_reason"])
        return 2

    jsonl: JsonlShardFile | None = None
    recording_enabled = False
    tracking_enabled = False
    started_monotonic = time.monotonic()
    frame_count = 0
    grab_failures = 0
    retrieval_failures: list[dict[str, Any]] = []
    result_status = "failed"
    failure_reason: str | None = None
    identity: dict[str, Any] = {}
    first_device_timestamp_ns: int | None = None
    last_device_timestamp_ns: int | None = None
    image = sl.Mat()
    depth = sl.Mat()
    sensors = sl.SensorsData()
    pose = sl.Pose()
    runtime = sl.RuntimeParameters()
    try:
        info = camera.get_camera_information()
        identity = _camera_identity(info)
        expected = {
            "serial": args.expected_serial,
            "camera_firmware": args.expected_camera_firmware,
            "sensor_firmware": args.expected_sensor_firmware,
            "sdk_version": args.expected_sdk,
        }
        mismatches = {
            key: {"expected": value, "actual": identity.get(key)}
            for key, value in expected.items()
            if identity.get(key) != value
        }
        if mismatches:
            failure_reason = f"ZED identity mismatch: {mismatches}"
            return_code = 3
        else:
            tracking = sl.PositionalTrackingParameters()
            tracking.enable_imu_fusion = True
            tracking.set_as_static = True
            tracking_status = camera.enable_positional_tracking(tracking)
            if tracking_status != sl.ERROR_CODE.SUCCESS:
                failure_reason = f"enable_positional_tracking: {tracking_status}"
                return_code = 4
            else:
                tracking_enabled = True
                recording = sl.RecordingParameters(
                    str(svo_path), sl.SVO_COMPRESSION_MODE.H265
                )
                recording_status = camera.enable_recording(recording)
                if recording_status != sl.ERROR_CODE.SUCCESS:
                    failure_reason = f"enable_recording: {recording_status}"
                    return_code = 5
                else:
                    recording_enabled = True
                    jsonl = JsonlShardFile(
                        args.output_dir / "_staging_frames",
                        filename="frames.jsonl",
                    )
                    _event("ready", identity=identity, duration_s=args.duration)
                    started_monotonic = time.monotonic()
                    return_code = 0
                    while time.monotonic() - started_monotonic < args.duration:
                        if _STOP_REQUESTED:
                            failure_reason = "producer interrupted by signal"
                            return_code = 130
                            break
                        grab_status = camera.grab(runtime)
                        if grab_status != sl.ERROR_CODE.SUCCESS:
                            grab_failures += 1
                            retrieval_failures.append(
                                {
                                    "frame_index": frame_count,
                                    "kind": "grab",
                                    "status": str(grab_status),
                                }
                            )
                            continue
                        wall, host_monotonic_ns = _timestamp()
                        device_timestamp_ns = int(
                            camera.get_timestamp(
                                sl.TIME_REFERENCE.IMAGE
                            ).get_nanoseconds()
                        )
                        if first_device_timestamp_ns is None:
                            first_device_timestamp_ns = device_timestamp_ns
                        last_device_timestamp_ns = device_timestamp_ns
                        image_status = camera.retrieve_image(image, sl.VIEW.LEFT)
                        depth_status = camera.retrieve_measure(depth, sl.MEASURE.DEPTH)
                        imu_status = camera.get_sensors_data(
                            sensors, sl.TIME_REFERENCE.IMAGE
                        )
                        pose_status = camera.get_position(
                            pose, sl.REFERENCE_FRAME.WORLD
                        )

                        image_signature = None
                        if image_status == sl.ERROR_CODE.SUCCESS:
                            image_array = image.get_data()
                            sample = np.ascontiguousarray(image_array[::64, ::64, :3])
                            image_signature = hashlib.sha256(
                                sample.tobytes()
                            ).hexdigest()
                        depth_finite_ratio = None
                        depth_min_m = None
                        depth_max_m = None
                        depth_sample_grid_m = None
                        depth_sample_grid_shape = None
                        if depth_status == sl.ERROR_CODE.SUCCESS:
                            depth_array = depth.get_data()
                            finite = np.isfinite(depth_array)
                            depth_finite_ratio = float(finite.mean())
                            if finite.any():
                                depth_min_m = float(depth_array[finite].min())
                                depth_max_m = float(depth_array[finite].max())
                            sampled_depth = depth_array[::60, ::64]
                            depth_sample_grid_shape = list(sampled_depth.shape)
                            depth_sample_grid_m = [
                                float(value) if math.isfinite(float(value)) else None
                                for value in sampled_depth.reshape(-1)
                            ]

                        imu_payload: dict[str, Any] | None = None
                        imu_timestamp_ns = 0
                        if imu_status == sl.ERROR_CODE.SUCCESS:
                            imu = sensors.get_imu_data()
                            imu_timestamp_ns = int(imu.timestamp.get_nanoseconds())
                            imu_pose = imu.get_pose()
                            imu_payload = {
                                "linear_acceleration_m_s2": _vector(
                                    imu.get_linear_acceleration()
                                ),
                                "angular_velocity_rad_s": _vector(
                                    imu.get_angular_velocity()
                                ),
                                "orientation_xyzw": _vector(imu_pose.get_orientation()),
                            }
                        pose_payload = {
                            "translation_xyz_m": _vector(pose.get_translation()),
                            "orientation_xyzw": _vector(pose.get_orientation()),
                            "confidence_percent": int(pose.pose_confidence),
                            "valid": bool(pose.valid),
                        }
                        record = {
                            "schema": "ias.s4_2.zed_frame.v1",
                            "frame_index": frame_count,
                            "device_timestamp_ns": device_timestamp_ns,
                            "host_wall_time_utc": wall,
                            "host_monotonic_ns": host_monotonic_ns,
                            "image_status": "SUCCESS"
                            if image_status == sl.ERROR_CODE.SUCCESS
                            else str(image_status),
                            "image_signature_sha256": image_signature,
                            "depth_status": "SUCCESS"
                            if depth_status == sl.ERROR_CODE.SUCCESS
                            else str(depth_status),
                            "depth_finite_ratio": depth_finite_ratio,
                            "depth_min_m": depth_min_m,
                            "depth_max_m": depth_max_m,
                            "depth_sample_grid_m": depth_sample_grid_m,
                            "depth_sample_grid_shape": depth_sample_grid_shape,
                            "depth_sample_stride_px": [60, 64],
                            "imu_status": "SUCCESS"
                            if imu_status == sl.ERROR_CODE.SUCCESS
                            else str(imu_status),
                            "imu_timestamp_ns": imu_timestamp_ns,
                            "imu": imu_payload,
                            "pose_status": str(pose_status).split(".")[-1],
                            "pose_timestamp_ns": int(pose.timestamp.get_nanoseconds()),
                            "pose": pose_payload,
                            "frame_name": "F_zed_world_y_up",
                            "units": {
                                "position": "m",
                                "time": "ns",
                                "angle": "rad",
                            },
                        }
                        jsonl.append(json.dumps(record, sort_keys=True) + "\n")
                        frame_count += 1
                    if return_code == 0:
                        result_status = "complete"
    except BaseException as exc:  # preserve producer evidence before propagating
        failure_reason = f"{type(exc).__name__}: {exc}"
        return_code = 10
    finally:
        if recording_enabled:
            camera.disable_recording()
        if tracking_enabled:
            camera.disable_positional_tracking()
        camera.close()
        if jsonl is not None:
            try:
                jsonl.publish(frames_path)
            except BaseException as exc:
                result_status = "failed"
                failure_reason = (
                    f"frames publication failed: {type(exc).__name__}: {exc}"
                )
                return_code = 11

    elapsed_s = time.monotonic() - started_monotonic
    if result_status == "complete" and (
        not svo_path.is_file()
        or svo_path.stat().st_size == 0
        or not frames_path.is_file()
        or retrieval_failures
        or grab_failures
    ):
        result_status = "failed"
        failure_reason = "producer output incomplete or contains retrieval failures"
        return_code = 12
    summary = {
        "schema": "ias.s4_2.zed_producer_summary.v1",
        "status": result_status,
        "failure_reason": failure_reason,
        "identity": identity,
        "requested_duration_s": args.duration,
        "elapsed_s": elapsed_s,
        "frame_count": frame_count,
        "grab_failures": grab_failures,
        "retrieval_failures": retrieval_failures,
        "first_device_timestamp_ns": first_device_timestamp_ns,
        "last_device_timestamp_ns": last_device_timestamp_ns,
        "svo_path": svo_path.name,
        "frames_path": frames_path.name,
        "svo_byte_size": svo_path.stat().st_size if svo_path.is_file() else 0,
    }
    write_json_atomic(summary_path, summary)
    _event(result_status, summary=summary)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
