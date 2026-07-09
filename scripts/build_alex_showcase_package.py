"""Package the Alex audio-detection showcase captured by the live script.

Consumes the per-step viewport frames, compass panels, session WAV, and
evidence JSON written by ``scripts/live_alex_audio_showcase.py`` and builds:

- ``media/videos/alex_audio_detection_demo.mp4`` — the full story with the
  live compass panel overlaid and the array session audio mixed to stereo.
- ``media/videos/alex_turn_to_sound_clip.mp4`` — the short "sound emitted ->
  bearing detected -> Alex turns" cut (phase A only).
- ``media/audio/detected_or_processed_demo.wav`` — stereo mixdown of the
  4-channel array session WAV.
- ``manifest.json`` — every artifact with dimensions/durations, poses,
  bearings, yaw errors, and real-capture vs fallback provenance.
- ``README.md`` — what to show a professor and what each artifact proves.

Runs on the host Python (no Isaac required); only needs ``ffmpeg``/``ffprobe``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

FPS = 20
SHOWCASE_ROOT = Path("outputs/isaac_audio_sensors/showcase")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def ffprobe_media(path: Path) -> dict[str, Any]:
    out = run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=width,height,sample_rate,channels,"
            "avg_frame_rate,codec_type",
            "-of", "json", str(path),
        ]
    ).stdout
    data = json.loads(out)
    record: dict[str, Any] = {}
    duration = data.get("format", {}).get("duration")
    if duration is not None:
        record["duration_s"] = round(float(duration), 3)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            record["width"] = stream.get("width")
            record["height"] = stream.get("height")
            rate = stream.get("avg_frame_rate", "0/1")
            try:
                num, den = rate.split("/")
                if float(den) > 0:
                    record["fps"] = round(float(num) / float(den), 3)
            except ValueError:
                pass
        elif stream.get("codec_type") == "audio":
            record["sample_rate_hz"] = int(stream.get("sample_rate", 0))
            record["channels"] = stream.get("channels")
    return record


def png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(26)
    if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", header[16:24])
        return int(width), int(height)
    return None


def latest_package_dir() -> Path:
    candidates = sorted(SHOWCASE_ROOT.glob("alex_audio_detection_*"))
    if not candidates:
        raise SystemExit(
            f"No alex_audio_detection_* package under {SHOWCASE_ROOT}; run "
            "scripts/live_alex_audio_showcase.py (make alex-audio-showcase) first."
        )
    return candidates[-1]


def upscale_compass_pngs(compass_dir: Path, factor: int = 2) -> None:
    """Nearest-neighbor upscale so the overlay stays legible in the video."""

    for path in sorted(compass_dir.glob("step_*.png")):
        raw = path.read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            continue
        width, height = struct.unpack(">II", raw[16:24])
        if width >= 400:  # already upscaled on a previous run
            return
        run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(path),
                "-vf", f"scale={width * factor}:{height * factor}:flags=neighbor",
                str(path),
            ]
        )


def build_videos(package: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    media = package / "media"
    frames = media / "frames"
    compass = media / "compass"
    audio_dir = media / "audio"
    videos = media / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    session_wavs = sorted(audio_dir.glob("*_session.wav"))
    if not frames.is_dir() or not list(frames.glob("step_*.png")):
        raise SystemExit(
            f"No captured frames under {frames}; rerun the live showcase script."
        )
    if not session_wavs:
        raise SystemExit(f"No *_session.wav under {audio_dir}.")
    session_wav = session_wavs[0]

    # Stereo mixdown of the 4-channel array session (front/right/rear/left).
    processed = audio_dir / "detected_or_processed_demo.wav"
    run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(session_wav),
            "-af",
            "pan=stereo|c0=0.7*c0+1.0*c3+0.35*c2|c1=0.7*c0+1.0*c1+0.35*c2,"
            "dynaudnorm=p=0.85",
            str(processed),
        ]
    )

    upscale_compass_pngs(compass)

    timeline = evidence.get("timeline", {})
    phase_b = float(timeline.get("phase_b_phone_s", 9.0))
    phase_c = float(timeline.get("phase_c_occlusion_s", 16.0))
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    captions = ""
    if font.is_file():
        oven_start = float(timeline.get("oven_start_s", 0.5))

        def caption(text: str, start: float, end: float) -> str:
            return (
                f",drawtext=fontfile={font}:text='{text}':x=24:y=24:"
                f"fontsize=30:fontcolor=white:box=1:boxcolor=black@0.45:"
                f"boxborderw=10:enable='between(t,{start},{end})'"
            )

        captions = (
            caption("Oven beeper starts - SRP-PHAT estimates bearing",
                    oven_start, phase_b - 0.05)
            + caption("Phone rings louder - Alex re-targets the new source",
                      phase_b, phase_c - 0.05)
            + caption("Panel occludes the phone - detection flagged OCCLUDED",
                      phase_c, 1e6)
        )

    main_video = videos / "alex_audio_detection_demo.mp4"
    run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-framerate", str(FPS), "-i", str(frames / "step_%04d.png"),
            "-framerate", str(FPS), "-i", str(compass / "step_%04d.png"),
            "-i", str(processed),
            "-filter_complex",
            f"[0:v][1:v]overlay=W-w-24:H-h-24:format=auto{captions}[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(main_video),
        ]
    )

    clip_frames = int(phase_b * FPS)
    short_clip = videos / "alex_turn_to_sound_clip.mp4"
    run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-framerate", str(FPS), "-i", str(frames / "step_%04d.png"),
            "-framerate", str(FPS), "-i", str(compass / "step_%04d.png"),
            "-i", str(processed),
            "-filter_complex",
            "[0:v][1:v]overlay=W-w-24:H-h-24:format=auto[v]",
            "-map", "[v]", "-map", "2:a",
            "-frames:v", str(clip_frames), "-t", f"{phase_b}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(short_clip),
        ]
    )
    return {
        "main_video": main_video,
        "short_clip": short_clip,
        "processed_wav": processed,
        "session_wav": session_wav,
    }


def build_manifest(package: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    story = evidence.get("story", {})
    robot_import = evidence.get("robot_import", {})
    scene_real = (
        evidence.get("scene_provenance") == "alex_robot_ithor_floorplan1"
    )
    robot_real = robot_import.get("provenance") == "real_urdf_import"
    capture_real = (
        evidence.get("capture_kind") == "real_isaac_sim_viewport_capture"
        and evidence.get("status") == "passed"
    )

    artifacts: list[dict[str, Any]] = []
    for path in sorted((package / "media").rglob("*")):
        if not path.is_file() or path.parent.name in {"frames", "compass"}:
            continue
        rel = path.relative_to(package).as_posix()
        entry: dict[str, Any] = {
            "path": rel,
            "size_bytes": path.stat().st_size,
        }
        if path.suffix == ".png":
            dims = png_dimensions(path)
            if dims:
                entry["width"], entry["height"] = dims
            entry["provenance"] = (
                "real_isaac_capture"
                if capture_real and "images/" in rel
                else "real_isaac_capture" if capture_real else "fallback"
            )
            if path.name == "04_doa_compass_panel.png":
                entry["provenance"] = "rendered_from_live_sensor_frame"
        elif path.suffix in {".mp4", ".wav"}:
            entry.update(ffprobe_media(path))
            if path.name in {"source_sound.wav", "phone_ring.wav"}:
                entry["provenance"] = (
                    "synthesized_source_asset_played_through_room_backend"
                )
            elif "session" in path.name or path.name == (
                "detected_or_processed_demo.wav"
            ):
                entry["provenance"] = (
                    "simulated_multichannel_array_audio_room_acoustics_srp"
                )
            else:
                entry["provenance"] = (
                    "encoded_from_real_isaac_viewport_frames"
                    if capture_real
                    else "fallback"
                )
        artifacts.append(entry)
    for name in ("evidence/showcase_evidence.json", "evidence/showcase.frames.jsonl"):
        path = package / name
        if path.is_file():
            artifacts.append(
                {
                    "path": name,
                    "size_bytes": path.stat().st_size,
                    "provenance": "live_sensor_evidence",
                }
            )

    residual_a = story.get("phase_a_residual_bearing_deg")
    residual_b = story.get("phase_b_residual_bearing_deg")
    manifest = {
        "package": package.name,
        "generated_by": [
            "scripts/live_alex_audio_showcase.py (Isaac Sim python)",
            "scripts/build_alex_showcase_package.py (host python + ffmpeg)",
        ],
        "isaac_command": (
            "make alex-audio-showcase "
            "ISAAC_SIM_COMMAND=/home/pacquadr/isaacsim/python.sh"
        ),
        "status": evidence.get("status"),
        "provenance": {
            "scene": evidence.get("scene_provenance"),
            "scene_is_real_ithor_floorplan": scene_real,
            "robot": robot_import.get("provenance"),
            "robot_is_real_urdf_import": robot_real,
            "viewport_capture_is_real_isaac": capture_real,
            "audio_pipeline": (
                "room_acoustics_srp backend: synthesized source WAVs "
                "propagated through a scene-anchored shoebox room to the "
                "4-mic head array; SRP-PHAT estimates the bearing"
            ),
            "occlusion": (
                "sensor occlusion pipeline driven by a scripted box "
                "raycaster (PhysX-free); PhysX raycast occlusion is "
                "separately proven by make live-isaac-occlusion"
            ),
            "robot_motion": (
                "scripted closed-loop yaw servo driven by the live "
                "SRP-PHAT bearing estimate"
            ),
        },
        "story": story,
        "sensor": evidence.get("sensor"),
        "summary_metrics": {
            "robot_initial_yaw_deg": story.get("robot_initial_yaw_deg"),
            "robot_final_yaw_deg": story.get("robot_final_yaw_deg"),
            "phase_a_final_bearing_error_deg": residual_a,
            "phase_b_final_bearing_error_deg": residual_b,
            "first_detection": story.get("first_detection"),
            "occluded_detection_seen": story.get("occluded_detection")
            is not None,
        },
        "artifacts": artifacts,
    }
    return manifest


README_TEMPLATE = """# Alex Audio-Detection Showcase ({package})

A self-contained demo package showing the **Isaac Audio Sensors** extension
detecting a sounding object in the Alex-robot iTHOR FloorPlan1 kitchen and
driving Alex to turn toward it.

## The 60-second pitch (what to show first)

1. Play `media/videos/alex_turn_to_sound_clip.mp4` (~{phase_b:.0f}s):
   the oven beeper starts, the compass overlay locks onto the bearing, and
   Alex turns until the bearing error reads ~0 deg.
2. Then `media/videos/alex_audio_detection_demo.mp4` (full story): a louder
   phone rings on the other side -> the strongest-source selection switches
   and Alex re-turns; finally a panel slides in and the detection is flagged
   **occluded** on the compass.

## What each artifact proves

| Artifact | Claim it backs |
| --- | --- |
| `media/images/01_scene_overview.png` | Real iTHOR kitchen, Alex, and \
the source object in one Isaac viewport. |
| `media/images/02_source_object_closeup.png` | The visible, pulsing \
source marker at the oven. |
| `media/images/03_alex_head_mic_array.png` | The quad microphone rig \
mounted on Alex's head link. |
| `media/images/04_doa_compass_panel.png` | The extension's compass/meter \
instruments rendered from a live frame. |
| `media/images/05_alex_before_turn.png` / `06_alex_after_turn.png` | \
Before/after poses of the DOA-driven turn. |
| `media/images/07_second_source_phone.png` | The second (stronger) source \
used for the source-switch scenario. |
| `media/images/08_occlusion_case.png` | The occlusion scenario (if the \
flag fired during the run). |
| `media/audio/source_sound.wav` | The emitted source signal \
({source_dur}). |
| `media/audio/detected_or_processed_demo.wav` | Stereo mix of the \
simulated 4-channel array recording ({processed_dur}). |
| `media/audio/*_session.wav` | Raw gapless 4-channel array session from \
the room-acoustics backend. |
| `evidence/showcase_evidence.json` | Poses, bearings, yaw trajectory, \
per-step log, provenance. |
| `evidence/showcase.frames.jsonl` | Every AudioSensorFrame the sensor \
emitted (schema v1). |
| `manifest.json` | Machine-readable index of all of the above. |

## Key numbers from this run

- Robot initial yaw: **{initial_yaw:.1f} deg**, final yaw: **{final_yaw:.1f} deg**
- First detection: t={first_t}s, bearing {first_bearing} deg (source `{first_source}`)
- Phase A residual bearing error after the turn: **{residual_a} deg**
- Phase B (phone) residual bearing error: **{residual_b} deg**
- Occluded detection observed: **{occluded}**

## Provenance (read before presenting)

- Scene: `{scene_prov}`
- Robot: `{robot_prov}`
- Viewport captures: {capture_note}
- Bearing estimation: `room_acoustics_srp` backend — the synthesized source
  WAVs are propagated through a scene-anchored shoebox room model to the
  4-microphone array and SRP-PHAT estimates the direction. The robot turn is
  a scripted yaw servo **driven by that live estimate** (no ground-truth
  shortcut); the residual bearing numbers above are the honest closed-loop
  errors.
- Occlusion: the sensor's real occlusion pipeline, fed by a scripted
  box raycaster so the robot needs no PhysX articulation. PhysX raycast
  occlusion is separately proven by `make live-isaac-occlusion`.

## Regenerate

```bash
make alex-audio-showcase ISAAC_SIM_COMMAND=/home/pacquadr/isaacsim/python.sh
```

(Live capture step needs this machine's Isaac Sim + the Alex-robot checkout;
the packaging step reruns standalone as
`python scripts/build_alex_showcase_package.py`.)
"""


def write_readme(package: Path, evidence: dict[str, Any],
                 manifest: dict[str, Any]) -> None:
    story = evidence.get("story", {})
    first = story.get("first_detection") or {}
    timeline = evidence.get("timeline", {})

    def duration_of(name: str) -> str:
        for artifact in manifest["artifacts"]:
            if artifact["path"].endswith(name) and "duration_s" in artifact:
                return f"{artifact['duration_s']:.2f}s"
        return "n/a"

    def fmt(value: Any, spec: str = ".1f") -> str:
        return format(value, spec) if isinstance(value, (int, float)) else "n/a"

    capture_real = manifest["provenance"]["viewport_capture_is_real_isaac"]
    readme = README_TEMPLATE.format(
        package=package.name,
        phase_b=float(timeline.get("phase_b_phone_s", 9.0)),
        source_dur=duration_of("source_sound.wav"),
        processed_dur=duration_of("detected_or_processed_demo.wav"),
        initial_yaw=float(story.get("robot_initial_yaw_deg", 0.0)),
        final_yaw=float(story.get("robot_final_yaw_deg", 0.0)),
        first_t=fmt(first.get("t_s"), ".2f"),
        first_bearing=fmt(first.get("bearing_deg")),
        first_source=first.get("source_id", "n/a"),
        residual_a=fmt(story.get("phase_a_residual_bearing_deg")),
        residual_b=fmt(story.get("phase_b_residual_bearing_deg")),
        occluded="yes" if story.get("occluded_detection") else "no",
        scene_prov=evidence.get("scene_provenance"),
        robot_prov=manifest["provenance"]["robot"],
        capture_note=(
            "**real Isaac Sim (RTX) viewport captures** from this machine"
            if capture_real
            else "**FALLBACK/CONCEPT — not real Isaac captures** "
            "(see evidence JSON for the blocker)"
        ),
    )
    (package / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=None)
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep the per-step frame/compass PNG directories after encoding.",
    )
    args = parser.parse_args()
    package = args.package_dir or latest_package_dir()
    evidence_path = package / "evidence" / "showcase_evidence.json"
    if not evidence_path.is_file():
        raise SystemExit(f"Missing {evidence_path}; run the live script first.")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    build_videos(package, evidence)
    manifest = build_manifest(package, evidence)
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_readme(package, evidence, manifest)

    commands = package / "scripts_or_commands.md"
    commands.write_text(
        "# Reproduce this package\n\n"
        "```bash\n"
        "# 1. Live Isaac capture (writes media/frames, compass, audio, evidence)\n"
        "PYTHONPATH=$PWD/src:$PYTHONPATH \\\n"
        "  /home/pacquadr/isaacsim/python.sh scripts/live_alex_audio_showcase.py"
        f" \\\n  --out-dir {package.as_posix()}\n\n"
        "# 2. Package videos + manifest + README (host python)\n"
        f"python scripts/build_alex_showcase_package.py --package-dir "
        f"{package.as_posix()}\n\n"
        "# Or both via make:\n"
        "make alex-audio-showcase "
        "ISAAC_SIM_COMMAND=/home/pacquadr/isaacsim/python.sh\n"
        "```\n",
        encoding="utf-8",
    )

    if not args.keep_frames:
        for name in ("frames", "compass"):
            directory = package / "media" / name
            if directory.is_dir():
                shutil.rmtree(directory)

    print(
        json.dumps(
            {
                "package": str(package),
                "status": evidence.get("status"),
                "artifacts": len(manifest["artifacts"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
