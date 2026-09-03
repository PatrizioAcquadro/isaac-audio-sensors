"""Run the bounded R9.4 Steam Audio qualification in the Isaac Lab runtime."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.qualification.geometry_acoustics.evaluation_r9_4 import (
    qualify_steam_audio_r9_4,
)
from tools.qualification.geometry_acoustics.r9_4 import (
    write_bundle,
    write_fixture_assets,
)
from tools.qualification.geometry_acoustics.run_steam_audio import _cache_values
from tools.qualification.geometry_acoustics.steam_audio_r9_4 import (
    SteamAudioR94Adapter,
)

_OFFICIAL_REMOTE = "https://github.com/ValveSoftware/steam-audio.git"
_STABLE_TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def _git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args], text=True, timeout=30
    ).strip()


def _release_check() -> dict[str, object]:
    output = subprocess.check_output(
        ["git", "ls-remote", "--tags", "--refs", _OFFICIAL_REMOTE],
        text=True,
        timeout=60,
    )
    releases = []
    for line in output.splitlines():
        commit, reference = line.split(maxsplit=1)
        match = _STABLE_TAG.fullmatch(reference)
        if match:
            releases.append((tuple(int(part) for part in match.groups()), commit))
    if not releases:
        raise RuntimeError("official Steam Audio remote returned no stable tags")
    version, commit = max(releases)
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_stable_commit": commit,
        "latest_stable_tag": "v" + ".".join(str(part) for part in version),
        "official_remote": _OFFICIAL_REMOTE,
    }


def _default_output_root() -> Path:
    return Path(
        os.environ.get(
            "IAS_R94_OUTPUT_ROOT",
            "build/validation/r9/r9.4-v1/steam_audio",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=_default_output_root())
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

    source_commit = _git("rev-parse", "HEAD", cwd=args.source_root)
    source_tag = _git(
        "describe", "--tags", "--exact-match", "HEAD", cwd=args.source_root
    )
    source_remote = _git("remote", "get-url", "origin", cwd=args.source_root)
    release_check = _release_check()
    build_configuration = _cache_values(args.source_root)
    build_configuration["source_remote"] = source_remote
    write_fixture_assets(args.output_root)

    adapter = SteamAudioR94Adapter(
        library_path=args.library,
        source_root=args.source_root,
        signal_root=args.output_root / "signals",
        runtime={
            "hardware": args.hardware,
            "isaac_sim_version": args.isaac_version,
            "kit_version": args.kit_version,
            "platform": f"{platform.system().lower()}-{platform.machine()}",
            "python": sys.executable,
        },
    )
    try:
        result = qualify_steam_audio_r9_4(
            adapter,
            source_commit=source_commit,
            source_tag=source_tag,
            release_check=release_check,
            build_configuration=build_configuration,
        )
        write_bundle(args.output_root, result)
        print(json.dumps(result.evaluation, indent=2, sort_keys=True))
        return 1 if result.evaluation["execution_status"] == "blocked" else 0
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
