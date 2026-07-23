#!/usr/bin/env python3
"""Build the additive same-amendment multiday continuation package."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    build_source_checkpoint,
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    LOGICAL_COUNTS,
    S44AmendmentError,
    build_precollection_seal,
    load_configuration,
    validate_configuration,
    validate_future_attempt_census,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_predecessor_bytes,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic
from scripts.build_s4_4_amendment_03 import DELIVERY_PATHS, SOURCE_PATHS

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_03"
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
DEFAULT_OUTPUT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments" / AMENDMENT_ID
CHECKPOINT_PATH = "freeze/source_checkpoint.v2.json"
CONTINUATION_PATH = "freeze/multiday_session_continuation.v2.json"
SEAL_PATH = "precollection_seal.v2.json"
INDEX_PATH = "evidence_index.v2.json"
CHECKSUM_PATH = "SHA256SUMS.v2"
SOURCE_PATHS_V2 = (*SOURCE_PATHS, "scripts/build_s4_4_amendment_03_multiday.py")
V1_PACKAGE_SHA256 = {
    "SHA256SUMS": "c804c3697f8d015c10ad9589e544f155aeedac0fabaa6d500072ae8bea94de2a",
    "access_policy.v1.json": (
        "11919c3c40a41e2334fb1673d3cf80d3b7596a3cc53ba0b91279dd175dd7773c"
    ),
    "aggregate_index.v1.json": (
        "3cd01680fed7be5483d3d11e49216ff6f02b03fb21058188e453646ea314bd81"
    ),
    "evidence_index.v1.json": (
        "5b3bd0b2bf720e8e6d1ff6cef1ebfaf7f40f21184451df9b98296c5af6c90f6a"
    ),
    "freeze/amendment_02_continuation.v1.json": (
        "4efb3dc183fdbd760f77573b497dbc756c09698283aeeb62b146d30bafda3d6c"
    ),
    "freeze/config.v1.json": (
        "0574db845e9c0d07779a440b468eb4eb73056e88b8fba04814f409b4e4e25c52"
    ),
    "freeze/source_checkpoint.v1.json": (
        "6dd5b010dcc33b72ab1bd99459056d6965abc35bfdbb565499bba980c7816c20"
    ),
    "inheritance/inherited_fit_a.v1.json": (
        "2b9cb2a91a7c0a9a7af208631b9d3370e8cee887f842769e77fae417e3db9212"
    ),
    "manifests/fit_b_manifest.v1.json": (
        "6bead6134592cbe9f784a0eb8657533b74cf90e5d215f3005e8c3fdf02a22bb0"
    ),
    "manifests/prospective_holdout_manifest.v1.json": (
        "377c53d868dea4a89329a925763734da6a38920c7246821c902807c1667e0320"
    ),
    "manifests/sessions/fit_b.json": (
        "5f06c4b51583516a4a96d96d7230231f2437c784d253d158d6c061387194a74a"
    ),
    "manifests/sessions/prospective_holdout.json": (
        "587c7ff093f086f304e12a7e55459bf8b19d326132cd0550c7218b6cf38c84d3"
    ),
    "precollection_seal.v1.json": (
        "10e0513a7893cd241fa05d99b29daa46264e9d852c1864c2dbdcf3be70ffbf6d"
    ),
    "prospective_holdout_seal_intent.v1.json": (
        "34b6bc2fe49c493809b55902da93d7e0d5973d8dd941c94955894627b76f46a3"
    ),
    "validation/precollection_validation.json": (
        "efd777a7867fd40b92569c540fe690113f0cae888327d2773a89f4e2e582dbad"
    ),
}


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _artifact(path: Path, relative: str, role: str) -> dict[str, Any]:
    return {
        "path": relative,
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "retention": "tracked_metadata_only",
    }


def _canonical_path(config: dict[str, Any], relative: str) -> str:
    return f"{config['retention']['tracked_evidence_root']}/{relative}"


def _materialize_v1_package(output: Path, canonical_root: Path) -> None:
    for relative, expected in sorted(V1_PACKAGE_SHA256.items()):
        source = canonical_root / relative
        if not source.is_file() or sha256_file(source) != expected:
            raise S44AmendmentError(
                f"immutable amendment_03 v1 package mismatch: {relative}"
            )
        destination = output / relative
        if output.resolve() == canonical_root.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha256_file(destination) != expected:
            raise S44AmendmentError(
                f"refusing to replace different v1 package file: {relative}"
            )
        if not destination.exists():
            shutil.copyfile(source, destination)


def _file_record(path: Path, repo_root: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(repo_root.resolve()).as_posix(),
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_cutoff_inventory(
    config: dict[str, Any], repo_root: Path = ROOT
) -> dict[str, Any]:
    evidence_root = repo_root / config["retention"]["tracked_evidence_root"]
    attempt_root = repo_root / config["retention"]["attempt_root"]
    manifest = load_json(evidence_root / "manifests/sessions/fit_b.json")
    planned_ids = [take["planned_take_id"] for take in manifest["takes"][:34]]
    attempt_records: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for planned_id in planned_ids:
        planned_root = attempt_root / planned_id
        directories = sorted(path for path in planned_root.iterdir() if path.is_dir())
        if [path.name for path in directories] != [f"{planned_id}__attempt_01"]:
            raise S44AmendmentError(
                f"multiday cutoff attempt identity mismatch: {planned_id}"
            )
        attempt_dir = directories[0]
        attempt = load_json(attempt_dir / "manifest.json")
        if (
            attempt.get("planned_take_id") != planned_id
            or attempt.get("attempt_id") != attempt_dir.name
            or attempt.get("outcome") != "valid"
            or attempt.get("retained") is not True
            or attempt.get("precollection_seal_sha256")
            != V1_PACKAGE_SHA256["precollection_seal.v1.json"]
        ):
            raise S44AmendmentError(
                f"multiday cutoff retained-attempt contract mismatch: {planned_id}"
            )
        attempts.append(attempt)
        files = [
            _file_record(path, repo_root)
            for path in sorted(attempt_dir.rglob("*"))
            if path.is_file()
        ]
        attempt_records.append(
            {
                "planned_take_id": planned_id,
                "attempt_id": attempt_dir.name,
                "files": files,
                "file_count": len(files),
                "attempt_tree_sha256": canonical_sha256(files),
            }
        )
    inherited = load_json(evidence_root / "inheritance/inherited_fit_a.v1.json")
    validate_inherited_fit_a(inherited, config)
    manifests = {
        "fit_b": manifest,
        "prospective_holdout": load_json(
            evidence_root / "manifests/sessions/prospective_holdout.json"
        ),
    }
    census = validate_future_attempt_census(inherited, manifests, attempts)
    if (
        census["attempts_total"] != 86
        or census["valid_cells_total"] != 85
        or census["failures_total"] != 1
        or census["replacements_total"] != 1
    ):
        raise S44AmendmentError("multiday cutoff census mismatch")
    session_root = repo_root / config["retention"]["session_root"] / "fit_b"
    session_records = [
        _file_record(path, repo_root)
        for path in sorted(session_root.rglob("*.json"))
        if path.is_file()
    ]
    payload = {
        "schema": "ias.s4_4.amendment_03_multiday_cutoff.v1",
        "amendment_id": AMENDMENT_ID,
        "status": "immutable_cutoff_after_fit_b_take_034",
        "last_completed_planned_take_id": planned_ids[-1],
        "next_planned_take_id": manifest["takes"][34]["planned_take_id"],
        "completed_fit_b_cells": 34,
        "fit_b_attempts": 34,
        "fit_b_failures": 0,
        "fit_b_replacements": 0,
        "aggregate_census": census,
        "planned_take_ids": planned_ids,
        "attempt_records": attempt_records,
        "session_records": session_records,
        "v1_precollection_seal_sha256": V1_PACKAGE_SHA256["precollection_seal.v1.json"],
    }
    return {**payload, "cutoff_sha256": canonical_sha256(payload)}


def _continuation(config: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    cutoff = build_cutoff_inventory(config, repo_root)
    payload = {
        "schema": "ias.s4_4.amendment_03_multiday_continuation.v2",
        "status": "prospective_continuation_within_same_amendment",
        "amendment_id": AMENDMENT_ID,
        "new_amendment_created": False,
        "scientific_condition_matrix_changed": False,
        "future_take_identities_changed": False,
        "immutable_v1_package_sha256": dict(sorted(V1_PACKAGE_SHA256.items())),
        "cutoff": cutoff,
        "calendar_policy": {
            "same_local_calendar_date_permitted": True,
            "one_session_may_span_multiple_local_dates": True,
            "one_preflight_per_session_and_local_date_segment": True,
            "one_readiness_record_per_active_date_segment": True,
            "truthful_dates_and_timezone_aware_timestamps_required": True,
            "fit_b_and_prospective_holdout_session_ids_remain_distinct": True,
            "fit_b_and_holdout_preflight_and_readiness_remain_separate": True,
        },
        "device_restart_or_reconnection_required": False,
        "live_readiness_required_before_attempt_allocation": True,
        "replacement_limit_changed": False,
        "holdout_scientifically_opened": False,
        "s4_5_or_later_started": False,
    }
    return {**payload, "continuation_sha256": canonical_sha256(payload)}


def build(*, output: Path, config_path: Path, repo_root: Path = ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    config = load_configuration(config_path, repo_root)
    validate_configuration(config)
    validate_predecessor_bytes(config, repo_root, require_machine_local=True)
    canonical_root = repo_root / config["retention"]["tracked_evidence_root"]
    output.mkdir(parents=True, exist_ok=True)
    _materialize_v1_package(output, canonical_root)
    continuation = _continuation(config, repo_root)
    write_json_atomic(output / CONTINUATION_PATH, continuation)
    checkpoint_path = output / CHECKPOINT_PATH
    checkpoint = load_json(checkpoint_path) if checkpoint_path.is_file() else None
    bindings = {
        "immutable_v1_package_map_sha256": canonical_sha256(V1_PACKAGE_SHA256),
        "v1_evidence_index_file_sha256": V1_PACKAGE_SHA256["evidence_index.v1.json"],
        "v1_precollection_seal_file_sha256": V1_PACKAGE_SHA256[
            "precollection_seal.v1.json"
        ],
        "v1_sha256sums_file_sha256": V1_PACKAGE_SHA256["SHA256SUMS"],
        "multiday_continuation_file_sha256": sha256_file(output / CONTINUATION_PATH),
        "fit_b_manifest_file_sha256": V1_PACKAGE_SHA256[
            "manifests/sessions/fit_b.json"
        ],
        "prospective_holdout_manifest_file_sha256": V1_PACKAGE_SHA256[
            "manifests/sessions/prospective_holdout.json"
        ],
    }
    seal = build_precollection_seal(bindings=bindings, checkpoint=checkpoint)
    validate_precollection_seal(
        seal, repo_root=repo_root, require_committed=checkpoint is not None
    )
    write_json_atomic(output / SEAL_PATH, seal)

    artifacts: list[dict[str, Any]] = []
    for relative in sorted(V1_PACKAGE_SHA256):
        artifacts.append(
            _artifact(
                output / relative,
                _canonical_path(config, relative),
                "immutable_amendment_03_v1_package",
            )
        )
    generated_roles = {
        CONTINUATION_PATH: "same_amendment_multiday_continuation",
        SEAL_PATH: "active_precollection_seal",
    }
    if checkpoint_path.is_file():
        generated_roles[CHECKPOINT_PATH] = "active_source_checkpoint"
    for relative, role in sorted(generated_roles.items()):
        artifacts.append(
            _artifact(output / relative, _canonical_path(config, relative), role)
        )
    for relative in SOURCE_PATHS_V2:
        artifacts.append(_artifact(repo_root / relative, relative, "amendment_source"))
    for relative in DELIVERY_PATHS:
        artifacts.append(
            _artifact(repo_root / relative, relative, "amendment_closeout")
        )
    artifacts.sort(key=lambda item: item["path"])
    index = {
        "schema": "ias.s4_4.amendment_03_evidence_index.v2",
        "status": "precollection_frozen",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "amendment_id": AMENDMENT_ID,
        "new_amendment_created": False,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "logical_counts": LOGICAL_COUNTS,
        "new_planned_counts": {"fit_b": 51, "prospective_holdout": 47},
        "precollection_seal_sha256": sha256_file(output / SEAL_PATH),
        "continuation_sha256": continuation["continuation_sha256"],
        "v1_package_sha256": dict(sorted(V1_PACKAGE_SHA256.items())),
        "prospective_holdout_scientifically_opened": False,
        "amendment_01_unchanged": True,
        "amendment_02_unchanged": True,
        "raw_media_tracked": False,
        "S4.5_or_later_started": False,
    }
    write_json_atomic(output / INDEX_PATH, index)
    (output / CHECKSUM_PATH).write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in artifacts),
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "amendment_id": AMENDMENT_ID,
        "new_amendment_created": False,
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "logical_counts": LOGICAL_COUNTS,
        "completed_fit_b_cells_at_cutoff": 34,
        "next_planned_take_id": "s44a03_fit_b_035_conf",
        "continuation_file_sha256": sha256_file(output / CONTINUATION_PATH),
        "precollection_seal_file_sha256": sha256_file(output / SEAL_PATH),
        "evidence_index_file_sha256": sha256_file(output / INDEX_PATH),
        "checksum_file_sha256": sha256_file(output / CHECKSUM_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--freeze-source-checkpoint", action="store_true")
    args = parser.parse_args()
    try:
        if args.freeze_source_checkpoint:
            checkpoint_path = args.output / CHECKPOINT_PATH
            checkpoint = build_source_checkpoint(ROOT, _git_head(ROOT), SOURCE_PATHS_V2)
            if checkpoint_path.is_file() and load_json(checkpoint_path) != checkpoint:
                raise S44AmendmentError(
                    "refusing to replace a different amendment_03 v2 checkpoint"
                )
            write_json_atomic(checkpoint_path, checkpoint)
        summary = build(output=args.output, config_path=args.config)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            f"S4.4 amendment-03 multiday continuation build failed: {exc}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
