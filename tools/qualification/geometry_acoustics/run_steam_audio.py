"""Requalify the selected Steam Audio provider in the intended Python runtime."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from tools.qualification.geometry_acoustics.evaluation import qualify_steam_audio
from tools.qualification.geometry_acoustics.fixtures import write_fixture_assets
from tools.qualification.geometry_acoustics.reporting import write_candidate_bundle
from tools.qualification.geometry_acoustics.steam_audio import SteamAudioAdapter
from tools.qualification.geometry_acoustics_contract import evaluate_report


def _default_root() -> Path:
    return Path(os.environ.get("IAS_R9_OUTPUT_ROOT", "build/validation/r9/rev2"))


def _cache_values(source_root: Path) -> dict[str, object]:
    candidates = (
        source_root / "core/build/r9-release/CMakeCache.txt",
        source_root / "core/build/linux-x64-release/CMakeCache.txt",
    )
    cache_path = next((path for path in candidates if path.is_file()), candidates[0])
    wanted = {
        "BUILD_SHARED_LIBS": "ON",
        "CMAKE_BUILD_TYPE": "Release",
        "STEAMAUDIO_BUILD_BENCHMARKS": "OFF",
        "STEAMAUDIO_BUILD_SAMPLES": "OFF",
        "STEAMAUDIO_BUILD_TESTS": "OFF",
        "STEAMAUDIO_ENABLE_AVX": "OFF",
        "STEAMAUDIO_ENABLE_EMBREE": "ON",
    }
    observed: dict[str, str] = {}
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if ":" not in line or "=" not in line:
                continue
            key = line.split(":", 1)[0]
            if key in wanted:
                observed[key] = line.split("=", 1)[1]
    return {
        "cache_path": str(cache_path),
        "expected": wanted,
        "observed": observed,
        "verified": observed == wanted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=_default_root())
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            os.environ.get("IAS_STEAM_AUDIO_ROOT", "build/qualification/r9/steam-audio")
        ),
    )
    parser.add_argument("--library", type=Path)
    parser.add_argument("--isaac-version", required=True)
    parser.add_argument("--kit-version", required=True)
    parser.add_argument("--hardware", default="CPU/Embree on qualification host")
    args = parser.parse_args(argv)
    source_commit = subprocess.check_output(
        ["git", "-C", str(args.source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    common_root = args.output_root / "common"
    write_fixture_assets(common_root)
    adapter = SteamAudioAdapter(
        library_path=args.library,
        source_root=args.source_root,
        signal_root=common_root / "signals",
        runtime={
            "hardware": args.hardware,
            "isaac_sim_version": args.isaac_version,
            "kit_version": args.kit_version,
            "platform": f"{platform.system().lower()}-{platform.machine()}",
        },
    )
    try:
        result = qualify_steam_audio(
            adapter,
            source_commit=source_commit,
            build_configuration=_cache_values(args.source_root),
        )
        output_dir = args.output_root / adapter.candidate_id
        write_candidate_bundle(
            output_dir,
            report=result.report,
            measurements=result.measurements,
            arrays=result.arrays,
            provenance=result.provenance,
            log_lines=result.log_lines,
        )
        evaluation = evaluate_report(result.report)
        print(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True))
        return 0 if not evaluation.full_r10_blocked_gates else 1
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
