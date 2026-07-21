#!/usr/bin/env python3
"""Replay a finalized S4.2 SVO2 with the ZED SDK and report what is readable."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pyzed.sl as sl

from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

SCHEMA = "ias.s4_2.svo_replay_validation.v1"


def _status(value: Any) -> str:
    return "SUCCESS" if value == sl.ERROR_CODE.SUCCESS else str(value).split(".")[-1]


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), file=_PROTOCOL_STDOUT, flush=True)


_PROTOCOL_STDOUT: Any = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("svo", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-serial", required=True)
    parser.add_argument("--resolution", required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--depth-mode", required=True)
    args = parser.parse_args()

    global _PROTOCOL_STDOUT
    _PROTOCOL_STDOUT = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)

    base: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "failed",
        "svo_path": args.svo.name,
        "capture": {
            "resolution": args.resolution,
            "fps": args.fps,
            "depth_mode": args.depth_mode,
        },
        "identity": {"serial": None},
        "declared_frame_count": 0,
        "replayed_frame_count": 0,
        "end_of_svo_reached": False,
        "representative_frames": [],
        "failure_reason": None,
    }
    if not args.svo.is_file() or args.svo.stat().st_size == 0:
        base["failure_reason"] = "SVO2 is missing or empty"
        write_json_atomic(args.output, base)
        _emit(base)
        return 2

    camera = sl.Camera()
    init = sl.InitParameters()
    init.set_from_svo_file(str(args.svo))
    init.svo_real_time_mode = False
    init.depth_mode = getattr(sl.DEPTH_MODE, args.depth_mode)
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
    opened = camera.open(init)
    if opened != sl.ERROR_CODE.SUCCESS:
        base["failure_reason"] = f"camera.open: {opened}"
        write_json_atomic(args.output, base)
        _emit(base)
        return 3

    tracking_enabled = False
    try:
        info = camera.get_camera_information()
        base["identity"] = {
            "serial": str(info.serial_number),
            "model": str(info.camera_model).split(".")[-1].replace("_", " "),
            "sdk_version": sl.Camera.get_sdk_version(),
        }
        width = int(info.camera_configuration.resolution.width)
        height = int(info.camera_configuration.resolution.height)
        base["decoded_dimensions_px"] = [width, height]
        base["decoded_fps"] = int(info.camera_configuration.fps)
        declared = int(camera.get_svo_number_of_frames())
        base["declared_frame_count"] = declared
        # The SDK can expose the final video frame after its paired motion-sensor
        # sample has reached end-of-stream. The penultimate frame is therefore
        # the frozen near-end representative for joint image/depth/IMU/pose QA.
        expected_indices = (
            sorted({0, declared // 2, max(0, declared - 2)}) if declared else []
        )

        tracking = sl.PositionalTrackingParameters()
        tracking.enable_imu_fusion = True
        tracking.set_as_static = True
        tracking_status = camera.enable_positional_tracking(tracking)
        tracking_enabled = tracking_status == sl.ERROR_CODE.SUCCESS
        base["tracking_enable_status"] = _status(tracking_status)

        runtime = sl.RuntimeParameters()
        image = sl.Mat()
        depth = sl.Mat()
        sensors = sl.SensorsData()
        pose = sl.Pose()
        replayed = 0
        representatives: list[dict[str, Any]] = []
        while True:
            grab = camera.grab(runtime)
            if grab == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                base["end_of_svo_reached"] = True
                break
            if grab != sl.ERROR_CODE.SUCCESS:
                base["failure_reason"] = f"camera.grab frame {replayed}: {grab}"
                break
            if replayed in expected_indices:
                image_status = camera.retrieve_image(image, sl.VIEW.LEFT)
                depth_status = camera.retrieve_measure(depth, sl.MEASURE.DEPTH)
                imu_status = camera.get_sensors_data(sensors, sl.TIME_REFERENCE.IMAGE)
                pose_status = camera.get_position(pose, sl.REFERENCE_FRAME.WORLD)
                representatives.append(
                    {
                        "frame_index": replayed,
                        "device_timestamp_ns": int(
                            camera.get_timestamp(
                                sl.TIME_REFERENCE.IMAGE
                            ).get_nanoseconds()
                        ),
                        "image_status": _status(image_status),
                        "depth_status": _status(depth_status),
                        "imu_status": _status(imu_status),
                        "pose_status": str(pose_status).split(".")[-1],
                    }
                )
            replayed += 1
        base["replayed_frame_count"] = replayed
        base["representative_frames"] = representatives
        dimensions_match = {
            "HD720": [1280, 720],
        }.get(args.resolution) == [width, height]
        passed = (
            base["identity"]["serial"] == args.expected_serial
            and dimensions_match
            and base["decoded_fps"] == args.fps
            and declared > 0
            and replayed == declared
            and base["end_of_svo_reached"]
            and [item["frame_index"] for item in representatives]
            == expected_indices
        )
        base["status"] = "passed" if passed else "failed"
        if not passed and base["failure_reason"] is None:
            base["failure_reason"] = "SVO2 replay contract mismatch"
    except BaseException as exc:
        base["failure_reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        if tracking_enabled:
            camera.disable_positional_tracking()
        camera.close()

    write_json_atomic(args.output, base)
    _emit(base)
    return 0 if base["status"] == "passed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
