#!/usr/bin/env python3
"""Delete explicitly authorized privacy-violating S4.2 visual evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_2 import load_json, sha256_file
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic


def delete_privacy_visuals(attempt_root: Path, *, authorization: str) -> dict:
    """Hash, record, then delete only SVO2/PNG files in one rejected attempt."""

    resolved = attempt_root.resolve()
    required_fragment = Path("dataset/S4.2/attempts")
    if required_fragment.as_posix() not in resolved.as_posix():
        raise ValueError("attempt must be under dataset/S4.2/attempts")
    lifecycle = load_json(resolved / "lifecycle.json")
    if lifecycle.get("state") != "rejected":
        raise ValueError("privacy deletion requires a rejected lifecycle")
    targets = sorted(
        path
        for path in resolved.rglob("*")
        if path.is_file() and path.suffix.lower() in {".svo2", ".png"}
    )
    if not targets:
        raise ValueError("no privacy visual targets found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pre_path = resolved / f"privacy_deletion_{stamp}_pre.json"
    post_path = resolved / f"privacy_deletion_{stamp}_post.json"
    records = [
        {
            "path": path.relative_to(resolved).as_posix(),
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in targets
    ]
    write_json_atomic(
        pre_path,
        {
            "schema": "ias.s4_2.privacy_deletion_pre.v1",
            "attempt_id": lifecycle["attempt_id"],
            "authorization": authorization,
            "reason": "person/hand visible contrary to frozen S4.2 privacy rule",
            "target_count": len(records),
            "targets": records,
        },
    )
    deleted: list[str] = []
    for path in targets:
        path.unlink()
        deleted.append(path.relative_to(resolved).as_posix())
    remaining = [
        record["path"]
        for record in records
        if (resolved / record["path"]).exists()
    ]
    report = {
        "schema": "ias.s4_2.privacy_deletion_post.v1",
        "attempt_id": lifecycle["attempt_id"],
        "status": "passed" if not remaining else "failed",
        "pre_deletion_manifest": pre_path.name,
        "deleted": deleted,
        "remaining": remaining,
        "nonvisual_evidence_retained": True,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(post_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt_root", type=Path)
    parser.add_argument("--authorized-by-operator", required=True)
    args = parser.parse_args()
    report = delete_privacy_visuals(
        args.attempt_root,
        authorization=args.authorized_by_operator,
    )
    print(report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
