#!/usr/bin/env python3
"""Fail-closed integrity validator for the S4.1 evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
S4_ROOT = Path("outputs/isaac_audio_sensors/S4/S4.1")
INDEX_PATH = S4_ROOT / "evidence_index.json"
MANIFEST_PATH = S4_ROOT / "evidence_manifest.sha256"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
EXPECTED_PATHS = {
    "docs/README.md",
    "docs/development/closeouts/S3_closeout.md",
    "docs/development/closeouts/S4/s4_1_bom_frame_lock.md",
    "docs/development/closeouts/S4/s4_1_evidence_index.md",
    "docs/development/specs/s0_final_public_release_acceptance.md",
    "docs/development/specs/s0_squadbot_readiness_acceptance.md",
    "docs/evidence/2026-07-16_reference_rig_hardware_bringup.md",
    "docs/final_sensor_development_plan.md",
    "docs/reference_rig_hardware_environment.md",
    "docs/roadmap.md",
    "docs/zed_respeaker_mount_model_handoff.md",
    "scripts/run_s4_1_zed_fixture_check.py",
    "scripts/validate_s4_1_integrity.py",
    f"{S4_ROOT}/evidence/current_fixture_audio_6ch.wav",
    f"{S4_ROOT}/evidence/fixture_top_axes_xy.png",
    f"{S4_ROOT}/evidence/zed_fixture_rerun_raw.json",
    f"{S4_ROOT}/evidence/zed_fov_final_privacy_clean.png",
    f"{S4_ROOT}/evidence/zed_fov_initial_obstructed.png",
    f"{S4_ROOT}/live_fixture_gate.json",
    f"{S4_ROOT}/future_printed_mount_reference.json",
    f"{S4_ROOT}/rig_frame_lock.json",
    "tests/test_s4_1_integrity_validator.py",
}
REQUIRED_ROLES = {
    "authoritative_document",
    "closeout",
    "future_mount_handoff",
    "future_mount_reference",
    "integrity_validator",
    "machine_record",
    "raw_machine_log",
    "retained_media",
    "run_tool",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, findings: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(f"cannot read JSON {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        findings.append(f"{path} must contain a JSON object")
        return {}
    return value


def safe_repo_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def parse_manifest(path: Path, findings: list[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        findings.append(f"cannot read hash manifest {path}: {exc}")
        return rows
    for number, line in enumerate(lines, 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            findings.append(f"invalid hash manifest line {number}: {line!r}")
            continue
        digest, item = match.groups()
        if item in rows:
            findings.append(f"duplicate hash manifest path: {item}")
        rows[item] = digest
    return rows


def is_git_tracked(repo_root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def require_equal(
    findings: list[str], label: str, actual: object, expected: object
) -> None:
    if actual != expected:
        findings.append(f"{label}: expected {expected!r}, got {actual!r}")


def validate_index(
    repo_root: Path, index: dict[str, Any], findings: list[str]
) -> dict[str, dict[str, Any]]:
    require_equal(
        findings,
        "index schema",
        index.get("schema"),
        "ias.s4_1.evidence_index.v1",
    )
    require_equal(findings, "index status", index.get("status"), "passed")
    require_equal(findings, "index blockers", index.get("blockers"), [])

    acceptance_revision = index.get("acceptance_revision")
    if not isinstance(acceptance_revision, str) or not re.fullmatch(
        r"[0-9a-f]{40}", acceptance_revision
    ):
        findings.append("index acceptance_revision must be a full Git SHA")
    else:
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", acceptance_revision, "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if ancestry.returncode != 0:
            findings.append(
                f"acceptance revision {acceptance_revision} is not an ancestor of HEAD"
            )

    archive = index.get("archive")
    if not isinstance(archive, dict):
        findings.append("index archive must be an object")
    else:
        require_equal(findings, "archive kind", archive.get("kind"), "git_tracked")
        git_ref = archive.get("git_ref")
        if not isinstance(git_ref, str) or not git_ref.startswith("refs/tags/"):
            findings.append("archive git_ref must name an exact refs/tags/ locator")
        steps = archive.get("retrieval_steps")
        if not isinstance(steps, list) or not steps or not all(
            isinstance(step, str) and step for step in steps
        ):
            findings.append("archive retrieval_steps must be a non-empty string list")

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        findings.append("index artifacts must be a list")
        return {}

    by_path: dict[str, dict[str, Any]] = {}
    roles: set[str] = set()
    for number, row in enumerate(artifacts):
        if not isinstance(row, dict):
            findings.append(f"artifact {number} must be an object")
            continue
        relative = row.get("path")
        if not safe_repo_path(relative):
            findings.append(f"artifact {number} has unsafe path: {relative!r}")
            continue
        assert isinstance(relative, str)
        if relative in by_path:
            findings.append(f"duplicate artifact path: {relative}")
            continue
        by_path[relative] = row
        role = row.get("role")
        if isinstance(role, str):
            roles.add(role)
        digest = row.get("sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            findings.append(f"artifact {relative} has no valid SHA-256")
        absolute = repo_root / relative
        if not absolute.is_file():
            findings.append(f"artifact is missing: {relative}")
        else:
            actual = sha256(absolute)
            if digest != actual:
                findings.append(
                    f"artifact hash mismatch for {relative}: {digest!r} != {actual}"
                )
        if row.get("git_tracked") is not True:
            findings.append(f"artifact is not declared git_tracked: {relative}")
        elif not is_git_tracked(repo_root, relative):
            findings.append(f"artifact is not present in the Git index: {relative}")

    missing_paths = sorted(EXPECTED_PATHS - by_path.keys())
    extra_paths = sorted(by_path.keys() - EXPECTED_PATHS)
    if missing_paths:
        findings.append(f"evidence index missing required paths: {missing_paths}")
    if extra_paths:
        findings.append(f"evidence index has undeclared paths: {extra_paths}")
    missing_roles = sorted(REQUIRED_ROLES - roles)
    if missing_roles:
        findings.append(f"evidence index missing required roles: {missing_roles}")
    return by_path


def validate_manifest(
    repo_root: Path,
    rows: dict[str, str],
    artifacts: dict[str, dict[str, Any]],
    findings: list[str],
) -> None:
    expected = set(artifacts)
    if set(rows) != expected:
        findings.append(
            "hash manifest coverage mismatch: "
            f"missing={sorted(expected - rows.keys())}, "
            f"extra={sorted(rows.keys() - expected)}"
        )
    for relative, digest in rows.items():
        absolute = repo_root / relative
        if not absolute.is_file():
            findings.append(f"hash manifest artifact is missing: {relative}")
            continue
        actual = sha256(absolute)
        if actual != digest:
            findings.append(
                f"hash manifest mismatch for {relative}: {digest} != {actual}"
            )
        index_digest = artifacts.get(relative, {}).get("sha256")
        if index_digest != digest:
            findings.append(
                f"index/manifest hash mismatch for {relative}: "
                f"{index_digest!r} != {digest}"
            )


def validate_semantics(repo_root: Path, findings: list[str]) -> None:
    rig = load_json(repo_root / S4_ROOT / "rig_frame_lock.json", findings)
    live = load_json(repo_root / S4_ROOT / "live_fixture_gate.json", findings)
    raw = load_json(
        repo_root / S4_ROOT / "evidence/zed_fixture_rerun_raw.json", findings
    )
    future_mount = load_json(
        repo_root / S4_ROOT / "future_printed_mount_reference.json", findings
    )

    require_equal(
        findings,
        "rig schema",
        rig.get("schema"),
        "ias.s4_1.rig_frame_lock.v1",
    )
    require_equal(findings, "rig S4.1 status", rig.get("status"), "passed")
    require_equal(
        findings,
        "fixture id",
        rig.get("fixture_id"),
        "S4_TEMP_DESKTOP_FIXTURE_REV0",
    )
    axes = rig.get("actual_fixture", {}).get("axes_marked")
    if set(axes or []) != {"+X", "+Y", "+Z"}:
        findings.append("rig axes_marked must contain exactly +X, +Y, and +Z")
    channel_order = (
        rig.get("device_lock", {})
        .get("respeaker", {})
        .get("native_capture", {})
        .get("channel_order")
    )
    expected_channels = {
        "0": "Conference",
        "1": "ASR",
        "2": "raw microphone 0",
        "3": "raw microphone 1",
        "4": "raw microphone 2",
        "5": "raw microphone 3",
    }
    require_equal(findings, "ReSpeaker channel order", channel_order, expected_channels)
    actual_fixture = rig.get("actual_fixture", {})
    require_equal(
        findings,
        "installed fixture classification",
        actual_fixture.get("classification"),
        "as-built handmade desktop fixture",
    )
    require_equal(
        findings,
        "installed fixture authority",
        actual_fixture.get("authority"),
        "installed S4.1 mount",
    )
    as_used = rig.get("approximate_as_used_geometry", {})
    require_equal(
        findings,
        "as-used geometry authority",
        as_used.get("authority"),
        "installed handmade fixture S4_TEMP_DESKTOP_FIXTURE_REV0",
    )
    translation = as_used.get("array_center_position_from_zed_stereo_midpoint_m")
    uncertainty = as_used.get("component_uncertainty_m")
    if not isinstance(translation, list) or len(translation) != 3 or not all(
        isinstance(value, (int, float)) for value in translation
    ):
        findings.append("as-used array-center translation must contain 3 numbers")
    if not isinstance(uncertainty, list) or len(uncertainty) != 3 or not all(
        isinstance(value, (int, float)) and value > 0 for value in uncertainty
    ):
        findings.append("as-used component uncertainty must contain 3 positive numbers")
    printed = rig.get("future_printed_mount", {})
    require_equal(
        findings,
        "future printed mount installed",
        printed.get("installed"),
        False,
    )
    require_equal(
        findings,
        "future printed mount S4.1 effect",
        printed.get("s4_1_gate_effect"),
        "non_blocking",
    )
    require_equal(
        findings,
        "future CAD applies to installed fixture",
        printed.get("cad_values_apply_to_installed_fixture"),
        False,
    )
    require_equal(findings, "rig blockers", rig.get("blockers"), [])

    require_equal(
        findings,
        "live schema",
        live.get("schema"),
        "ias.s4_1.live_fixture_gate.v1",
    )
    require_equal(findings, "live status", live.get("status"), "passed")
    installed_mount = live.get("installed_mount", {})
    require_equal(
        findings,
        "live installed mount classification",
        installed_mount.get("classification"),
        "as-built handmade desktop fixture",
    )
    require_equal(
        findings,
        "live printed CAD mount used",
        installed_mount.get("printed_cad_mount_used"),
        False,
    )
    initial = live.get("zed_initial_host_check", {})
    require_equal(
        findings,
        "initial FOV status",
        initial.get("status"),
        "failed_then_corrected",
    )
    rerun = live.get("zed_host_rerun", {})
    require_equal(findings, "rerun status", rerun.get("status"), "passed")
    frames = rerun.get("frames")
    if not isinstance(frames, int) or frames < 250:
        findings.append("rerun must retain at least 250 frames")
    for field in ("image_reads", "depth_reads", "sensor_reads"):
        if rerun.get(field) != frames:
            findings.append(f"rerun {field} must equal frames")
    require_equal(findings, "rerun grab failures", rerun.get("grab_failures"), 0)
    require_equal(
        findings,
        "rerun timestamp monotonicity",
        rerun.get("timestamps_strictly_monotonic"),
        True,
    )
    privacy = rerun.get("privacy_review", {})
    require_equal(
        findings,
        "final-frame privacy review",
        privacy.get("status"),
        "passed",
    )
    require_equal(findings, "raw rerun passed", raw.get("passed"), True)
    for field in (
        "frames",
        "grab_failures",
        "image_reads",
        "depth_reads",
        "sensor_reads",
        "timestamps_strictly_monotonic",
        "sdk_version",
        "serial_number",
    ):
        if rerun.get(field) != raw.get(field):
            findings.append(f"live/raw rerun mismatch for {field}")

    require_equal(
        findings,
        "future mount reference schema",
        future_mount.get("schema"),
        "ias.s4_1.future_printed_mount_reference.v1",
    )
    require_equal(
        findings,
        "future mount status",
        future_mount.get("status"),
        "documented_future_option",
    )
    require_equal(
        findings,
        "future mount installed for S4.1",
        future_mount.get("installed_for_s4_1"),
        False,
    )
    require_equal(
        findings,
        "future mount fixture assignment",
        future_mount.get("applies_to_fixture_id"),
        None,
    )
    require_equal(
        findings,
        "future mount S4.1 gate effect",
        future_mount.get("s4_1_gate_effect"),
        "non_blocking",
    )
    boundary = future_mount.get("boundary", {})
    require_equal(
        findings,
        "future CAD values apply to installed fixture",
        boundary.get("cad_values_apply_to_installed_fixture"),
        False,
    )
    require_equal(
        findings,
        "missing future CAD blocks S4.1",
        boundary.get("missing_cad_source_blocks_s4_1"),
        False,
    )
    transition = future_mount.get("future_transition_requirements")
    if not isinstance(transition, list) or len(transition) < 4 or not all(
        isinstance(item, str) and item for item in transition
    ):
        findings.append("future printed mount requires explicit transition checks")


def validate(repo_root: Path) -> list[str]:
    findings: list[str] = []
    index = load_json(repo_root / INDEX_PATH, findings)
    artifacts = validate_index(repo_root, index, findings)
    rows = parse_manifest(repo_root / MANIFEST_PATH, findings)
    validate_manifest(repo_root, rows, artifacts, findings)
    validate_semantics(repo_root, findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    findings = validate(repo_root)
    payload = {
        "schema": "ias.s4_1.integrity_report.v1",
        "status": "passed" if not findings else "failed",
        "finding_count": len(findings),
        "findings": findings,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif findings:
        for finding in findings:
            print(f"[s4.1-integrity] ERROR: {finding}")
    else:
        print("[s4.1-integrity] OK")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
