#!/usr/bin/env python3
"""Read-only local ZED/GPU/USB preflight for S4.2."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pyzed.sl as sl


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return None


def _usb_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for device in Path("/sys/bus/usb/devices").glob("*"):
        vendor = _read(device / "idVendor")
        if vendor != "2b03":
            continue
        speed = _read(device / "speed")
        records.append(
            {
                "vendor_id": vendor,
                "product_id": _read(device / "idProduct"),
                "product": _read(device / "product"),
                "serial": _read(device / "serial"),
                "speed_mbps": float(speed) if speed is not None else None,
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-serial", required=True)
    parser.add_argument("--expected-sdk", required=True)
    parser.add_argument("--expected-camera-firmware", required=True)
    parser.add_argument("--expected-sensor-firmware", required=True)
    parser.add_argument("--minimum-usb-speed-mbps", type=float, required=True)
    args = parser.parse_args()
    protocol_stdout = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)

    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    usb = _usb_records()
    video_interfaces = [
        record
        for record in usb
        if record["product_id"] == "f880" and record["product"] == "ZED 2i"
    ]
    serial_interfaces = [
        record
        for record in usb
        if record["product_id"] == "f881" and record["serial"] == args.expected_serial
    ]
    result: dict[str, Any] = {
        "schema": "ias.s4_2.zed_preflight.v1",
        "requested_mode": {
            "resolution": "HD720",
            "fps": 30,
            "depth_mode": "PERFORMANCE",
            "coordinate_units": "m",
            "coordinate_system": "RIGHT_HANDED_Y_UP",
        },
        "gpu": {
            "available": gpu.returncode == 0,
            "inventory": [
                line.strip() for line in gpu.stdout.splitlines() if line.strip()
            ],
        },
        "usb": {
            "video_interface_present": bool(video_interfaces),
            "serial_interface_present": bool(serial_interfaces),
            "video_speed_mbps": max(
                (float(record["speed_mbps"] or 0) for record in video_interfaces),
                default=0.0,
            ),
        },
    }
    camera = sl.Camera()
    init = sl.InitParameters()
    init.camera_resolution = sl.RESOLUTION.HD720
    init.camera_fps = 30
    init.depth_mode = sl.DEPTH_MODE.PERFORMANCE
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
    open_status = camera.open(init)
    result["open_status"] = str(open_status)
    if open_status == sl.ERROR_CODE.SUCCESS:
        image = sl.Mat()
        depth = sl.Mat()
        sensors = sl.SensorsData()
        info = camera.get_camera_information()
        tracking = sl.PositionalTrackingParameters()
        tracking.enable_imu_fusion = True
        tracking.set_as_static = True
        tracking_status = camera.enable_positional_tracking(tracking)
        grab_status = camera.grab(sl.RuntimeParameters())
        if grab_status == sl.ERROR_CODE.SUCCESS:
            image_status = camera.retrieve_image(image, sl.VIEW.LEFT)
            depth_status = camera.retrieve_measure(depth, sl.MEASURE.DEPTH)
            sensor_status = camera.get_sensors_data(sensors, sl.TIME_REFERENCE.IMAGE)
        else:
            image_status = depth_status = sensor_status = grab_status
        result["identity"] = {
            "model": str(info.camera_model),
            "serial": str(info.serial_number),
            "camera_firmware": str(info.camera_configuration.firmware_version),
            "sensor_firmware": str(info.sensors_configuration.firmware_version),
            "sdk_version": sl.Camera.get_sdk_version(),
        }
        result["probe"] = {
            "tracking_status": str(tracking_status),
            "grab_status": str(grab_status),
            "image_status": str(image_status),
            "depth_status": str(depth_status),
            "sensor_status": str(sensor_status),
        }
        if tracking_status == sl.ERROR_CODE.SUCCESS:
            camera.disable_positional_tracking()
        camera.close()
    else:
        result["identity"] = {}
        result["probe"] = {}
    checks = {
        "gpu_available": result["gpu"]["available"],
        "usb_video_present": result["usb"]["video_interface_present"],
        "usb_serial_present": result["usb"]["serial_interface_present"],
        "usb_3_speed": result["usb"]["video_speed_mbps"] >= args.minimum_usb_speed_mbps,
        "camera_opened": open_status == sl.ERROR_CODE.SUCCESS,
        "serial_matches": result["identity"].get("serial") == args.expected_serial,
        "sdk_matches": result["identity"].get("sdk_version") == args.expected_sdk,
        "camera_firmware_matches": result["identity"].get("camera_firmware")
        == args.expected_camera_firmware,
        "sensor_firmware_matches": result["identity"].get("sensor_firmware")
        == args.expected_sensor_firmware,
        "tracking_available": result["probe"].get("tracking_status")
        == str(sl.ERROR_CODE.SUCCESS),
        "image_retrieved": result["probe"].get("image_status")
        == str(sl.ERROR_CODE.SUCCESS),
        "depth_retrieved": result["probe"].get("depth_status")
        == str(sl.ERROR_CODE.SUCCESS),
        "imu_retrieved": result["probe"].get("sensor_status")
        == str(sl.ERROR_CODE.SUCCESS),
    }
    result["checks"] = checks
    result["status"] = "passed" if all(checks.values()) else "failed"
    print(
        json.dumps(result, indent=2, sort_keys=True),
        file=protocol_stdout,
        flush=True,
    )
    protocol_stdout.close()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
