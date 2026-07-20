#!/usr/bin/env python3
"""Run the bounded live ZED check used by the S4.1 fixture gate."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pyzed.sl as sl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--frame", type=Path, required=True)
    args = parser.parse_args()

    camera = sl.Camera()
    init = sl.InitParameters()
    init.camera_resolution = sl.RESOLUTION.HD720
    init.camera_fps = 30
    init.depth_mode = sl.DEPTH_MODE.PERFORMANCE
    init.coordinate_units = sl.UNIT.METER

    open_status = camera.open(init)
    if open_status != sl.ERROR_CODE.SUCCESS:
        print(json.dumps({"open_status": str(open_status), "passed": False}))
        return 2

    image = sl.Mat()
    depth = sl.Mat()
    sensors = sl.SensorsData()
    runtime = sl.RuntimeParameters()
    image_timestamps: list[int] = []
    grab_failures = 0
    image_reads = 0
    depth_reads = 0
    sensor_reads = 0
    finite_depth_ratios: list[float] = []
    frame_write_status = "not_written"

    started = time.monotonic()
    try:
        while time.monotonic() - started < args.duration:
            status = camera.grab(runtime)
            if status != sl.ERROR_CODE.SUCCESS:
                grab_failures += 1
                continue

            timestamp_ns = camera.get_timestamp(
                sl.TIME_REFERENCE.IMAGE
            ).get_nanoseconds()
            image_timestamps.append(int(timestamp_ns))

            if camera.retrieve_image(image, sl.VIEW.LEFT) == sl.ERROR_CODE.SUCCESS:
                image_reads += 1
                if image_reads == 1:
                    frame_write_status = str(image.write(str(args.frame)))

            if (
                camera.retrieve_measure(depth, sl.MEASURE.DEPTH)
                == sl.ERROR_CODE.SUCCESS
            ):
                depth_reads += 1
                if depth_reads % 30 == 1:
                    depth_array = depth.get_data()
                    finite_depth_ratios.append(
                        float(np.isfinite(depth_array).mean())
                    )

            if (
                camera.get_sensors_data(sensors, sl.TIME_REFERENCE.IMAGE)
                == sl.ERROR_CODE.SUCCESS
            ):
                sensor_reads += 1
    finally:
        info = camera.get_camera_information()
        camera.close()

    gaps_ms = [
        (later - earlier) / 1_000_000.0
        for earlier, later in zip(
            image_timestamps, image_timestamps[1:], strict=False
        )
    ]
    monotonic = all(gap > 0 for gap in gaps_ms)
    mean_finite_depth = (
        sum(finite_depth_ratios) / len(finite_depth_ratios)
        if finite_depth_ratios
        else math.nan
    )
    passed = (
        len(image_timestamps) >= 250
        and grab_failures == 0
        and image_reads == len(image_timestamps)
        and depth_reads == len(image_timestamps)
        and sensor_reads > 0
        and monotonic
        and args.frame.is_file()
    )
    result = {
        "passed": passed,
        "sdk_version": sl.Camera.get_sdk_version(),
        "serial_number": int(info.serial_number),
        "requested_duration_s": args.duration,
        "elapsed_s": time.monotonic() - started,
        "frames": len(image_timestamps),
        "grab_failures": grab_failures,
        "image_reads": image_reads,
        "depth_reads": depth_reads,
        "sensor_reads": sensor_reads,
        "timestamps_strictly_monotonic": monotonic,
        "max_timestamp_gap_ms": max(gaps_ms, default=math.nan),
        "mean_sampled_finite_depth_ratio": mean_finite_depth,
        "frame_path": str(args.frame),
        "frame_write_status": frame_write_status,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
