#!/usr/bin/env python3
"""Extract a bounded, labeled SVO review sheet for manual S4.2 alignment."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyzed.sl as sl
from PIL import Image, ImageDraw


def extract_review_sheet(
    svo_path: Path,
    output_dir: Path,
    *,
    start_frame: int,
    end_frame: int,
    stride: int,
) -> Path:
    """Extract requested LEFT frames without modifying the SVO."""

    if output_dir.exists():
        raise FileExistsError(f"review output already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    camera = sl.Camera()
    init = sl.InitParameters()
    init.set_from_svo_file(str(svo_path.resolve()))
    init.svo_real_time_mode = False
    status = camera.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"cannot open SVO: {status}")
    images: list[tuple[int, Image.Image]] = []
    try:
        for frame_index in range(start_frame, end_frame + 1, stride):
            camera.set_svo_position(frame_index)
            grab = camera.grab(sl.RuntimeParameters())
            if grab != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"frame {frame_index}: grab failed: {grab}")
            mat = sl.Mat()
            retrieved = camera.retrieve_image(mat, sl.VIEW.LEFT)
            if retrieved != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(
                    f"frame {frame_index}: image retrieval failed: {retrieved}"
                )
            bgra = np.asarray(mat.get_data())
            rgba = bgra[:, :, [2, 1, 0, 3]]
            image = Image.fromarray(rgba, mode="RGBA").convert("RGB")
            image_path = output_dir / f"frame_{frame_index:06d}.png"
            image.save(image_path)
            images.append((frame_index, image))
    finally:
        camera.close()
    if not images:
        raise RuntimeError("no review frames extracted")
    thumbnail_size = (320, 180)
    label_height = 24
    columns = 4
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * thumbnail_size[0], rows * (thumbnail_size[1] + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, (frame_index, image) in enumerate(images):
        column = index % columns
        row = index // columns
        x = column * thumbnail_size[0]
        y = row * (thumbnail_size[1] + label_height)
        thumbnail = image.copy()
        thumbnail.thumbnail(thumbnail_size)
        sheet.paste(thumbnail, (x, y))
        draw.text(
            (x + 4, y + thumbnail_size[1] + 4),
            f"frame {frame_index}",
            fill="black",
        )
    sheet_path = output_dir / "contact_sheet.png"
    sheet.save(sheet_path)
    return sheet_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("svo", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--start-frame", type=int, required=True)
    parser.add_argument("--end-frame", type=int, required=True)
    parser.add_argument("--stride", type=int, default=2)
    args = parser.parse_args()
    if args.start_frame < 0 or args.end_frame < args.start_frame or args.stride <= 0:
        parser.error("invalid frame bounds or stride")
    sheet = extract_review_sheet(
        args.svo,
        args.output_dir,
        start_frame=args.start_frame,
        end_frame=args.end_frame,
        stride=args.stride,
    )
    print(sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
