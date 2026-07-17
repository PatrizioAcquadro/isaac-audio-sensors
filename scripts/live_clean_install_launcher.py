"""Bootstrap S1.6 through Kit's isolated embedded Python interpreter."""

from __future__ import annotations

import argparse
import runpy
import site
import sys
from pathlib import Path


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isaac-root", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--ext-folder", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--kit-path", action="append", type=Path, default=[])
    args = parser.parse_args()

    isaac_root = args.isaac_root.resolve()
    ext_folder = args.ext_folder.resolve()
    for path in args.kit_path:
        resolved = path.resolve()
        if not _under(resolved, isaac_root) or not resolved.exists():
            raise RuntimeError(f"unverified Kit Python path: {resolved}")
        sys.path.append(str(resolved))
    if not _under(ext_folder, args.output.resolve().parent):
        raise RuntimeError(f"staged extension folder is not output-local: {ext_folder}")
    site.ENABLE_USER_SITE = False

    from isaacsim import SimulationApp  # type: ignore

    extra_args = [
        "--ext-folder",
        str(ext_folder),
        "--enable",
        "isaac_audio_sensors.omni",
    ]
    app = SimulationApp(
        {
            "headless": not args.gui,
            "extra_args": extra_args,
            "fast_shutdown": True,
        },
        experience=str(args.app.resolve()),
    )
    try:
        sys.argv = [str(args.probe.resolve()), str(args.output.resolve())]
        namespace = runpy.run_path(
            str(args.probe.resolve()), run_name="ias_clean_install_probe"
        )
        result = namespace.get("main")
        return int(result()) if callable(result) else 0
    finally:
        close = getattr(app, "close", None)
        if callable(close):
            close(wait_for_replicator=False)


if __name__ == "__main__":
    raise SystemExit(main())
