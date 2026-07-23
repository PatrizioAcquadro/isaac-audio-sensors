#!/usr/bin/env python3
"""Validate amendment-03 without opening the prospective holdout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    LOGICAL_COUNTS,
    S44AmendmentError,
    build_aggregate_index,
    build_continuation_reference,
    build_future_manifests,
    build_inherited_fit_a,
    combined_future_manifest,
    load_configuration,
    validate_configuration,
    validate_future_attempt_census,
    validate_future_manifests,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_predecessor_bytes,
)

try:
    from scripts.build_s4_4_amendment_03_multiday import (
        CHECKSUM_PATH as CHECKSUM_PATH_V2,
    )
    from scripts.build_s4_4_amendment_03_multiday import (
        CONTINUATION_PATH,
        V1_PACKAGE_SHA256,
        V2_PACKAGE_SHA256,
        V3_PACKAGE_SHA256,
        V4_PACKAGE_SHA256,
    )
    from scripts.build_s4_4_amendment_03_multiday import (
        SEAL_PATH as SEAL_PATH_V2,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from build_s4_4_amendment_03_multiday import (
        CHECKSUM_PATH as CHECKSUM_PATH_V2,
    )
    from build_s4_4_amendment_03_multiday import (
        CONTINUATION_PATH,
        V1_PACKAGE_SHA256,
        V2_PACKAGE_SHA256,
        V3_PACKAGE_SHA256,
        V4_PACKAGE_SHA256,
    )
    from build_s4_4_amendment_03_multiday import SEAL_PATH as SEAL_PATH_V2

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
DEFAULT_INDEX = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/evidence_index.v1.json"
)
MEDIA_SUFFIXES = {".wav", ".svo", ".svo2", ".png", ".jpg", ".jpeg", ".mp4"}


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _tracked(repo_root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _committed_exact(repo_root: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False
    if not _tracked(repo_root, relative):
        return False
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _checksums(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            raise S44AmendmentError(f"{path}:{number}: malformed checksum")
        digest, relative = line.split("  ", 1)
        if relative in records:
            raise S44AmendmentError(f"{path}:{number}: duplicate checksum path")
        records[relative] = digest
    return records


def _resolve_artifact(
    relative: str, repo_root: Path, evidence_root: Path, canonical_output: Path
) -> Path:
    prefix = canonical_output.as_posix() + "/"
    return (
        evidence_root / relative[len(prefix) :]
        if relative.startswith(prefix)
        else repo_root / relative
    )


def _future_attempts(config: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    attempt_root = repo_root / config["retention"]["attempt_root"]
    return [
        load_json(path)
        for path in sorted(attempt_root.glob("*/*/manifest.json"))
        if path.is_file()
    ]


def _validate_cutoff_inventory(
    cutoff: dict[str, Any], config: dict[str, Any], repo_root: Path
) -> None:
    payload = {key: value for key, value in cutoff.items() if key != "cutoff_sha256"}
    if cutoff.get("cutoff_sha256") != canonical_sha256(payload):
        raise S44AmendmentError("multiday cutoff self-hash mismatch")
    evidence_root = repo_root / config["retention"]["tracked_evidence_root"]
    manifest = load_json(evidence_root / "manifests/sessions/fit_b.json")
    expected_ids = [take["planned_take_id"] for take in manifest["takes"][:34]]
    if (
        cutoff.get("status") != "immutable_cutoff_after_fit_b_take_034"
        or cutoff.get("completed_fit_b_cells") != 34
        or cutoff.get("fit_b_attempts") != 34
        or cutoff.get("fit_b_failures") != 0
        or cutoff.get("fit_b_replacements") != 0
        or cutoff.get("cutoff_basis") != "fit_b_retained_attempt_count"
        or cutoff.get("date_segments_remain_within_same_fit_b_session") is not True
        or cutoff.get("all_session_records_present_at_cutoff_included") is not True
        or cutoff.get("planned_take_ids") != expected_ids
        or cutoff.get("last_completed_planned_take_id") != expected_ids[-1]
        or cutoff.get("next_planned_take_id")
        != manifest["takes"][34]["planned_take_id"]
        or cutoff.get("v1_precollection_seal_sha256")
        != V1_PACKAGE_SHA256["precollection_seal.v1.json"]
    ):
        raise S44AmendmentError("multiday cutoff identity/census mismatch")
    attempt_records = cutoff.get("attempt_records")
    if not isinstance(attempt_records, list) or len(attempt_records) != 34:
        raise S44AmendmentError("multiday cutoff attempt records mismatch")
    if [record.get("planned_take_id") for record in attempt_records] != expected_ids:
        raise S44AmendmentError("multiday cutoff planned-attempt order mismatch")
    for attempt_record in attempt_records:
        files = attempt_record.get("files")
        if (
            not isinstance(files, list)
            or attempt_record.get("file_count") != len(files)
            or attempt_record.get("attempt_tree_sha256") != canonical_sha256(files)
        ):
            raise S44AmendmentError("multiday cutoff attempt tree mismatch")
        for record in files:
            path = repo_root / str(record.get("path"))
            if (
                not path.is_file()
                or path.stat().st_size != record.get("byte_size")
                or sha256_file(path) != record.get("sha256")
            ):
                raise S44AmendmentError(
                    f"multiday cutoff file mismatch: {record.get('path')}"
                )
    session_records = cutoff.get("session_records")
    if not isinstance(session_records, list) or not session_records:
        raise S44AmendmentError("multiday cutoff session records absent")
    for record in session_records:
        relative = str(record.get("path"))
        path = repo_root / relative
        if (
            "/sessions/fit_b/" not in f"/{relative}"
            or not path.is_file()
            or path.stat().st_size != record.get("byte_size")
            or sha256_file(path) != record.get("sha256")
        ):
            raise S44AmendmentError(
                f"multiday cutoff session record mismatch: {relative}"
            )


def validate(
    index_path: Path,
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    require_tracked: bool,
    require_committed: bool,
    require_machine_local: bool,
    require_final: bool,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    evidence_root = index_path.resolve().parent
    issues: list[dict[str, str]] = []
    config = load_configuration(config_path, repo_root)
    try:
        validate_configuration(config)
        predecessor_validation = validate_predecessor_bytes(
            config, repo_root, require_machine_local=require_machine_local
        )
    except S44AmendmentError as exc:
        predecessor_validation = None
        issues.append(
            _issue("configuration_or_predecessor_invalid", str(config_path), str(exc))
        )
    canonical_output = Path(config["retention"]["tracked_evidence_root"])
    index = load_json(index_path)
    index_schema = index.get("schema")
    if (
        index_schema
        not in {
            "ias.s4_4.amendment_03_evidence_index.v1",
            "ias.s4_4.amendment_03_evidence_index.v2",
            "ias.s4_4.amendment_03_evidence_index.v3",
            "ias.s4_4.amendment_03_evidence_index.v4",
            "ias.s4_4.amendment_03_evidence_index.v5",
        }
        or index.get("logical_counts") != LOGICAL_COUNTS
        or index.get("new_planned_counts") != {"fit_b": 51, "prospective_holdout": 47}
        or index.get("prospective_holdout_scientifically_opened") is not False
        or index.get("amendment_01_unchanged") is not True
        or index.get("amendment_02_unchanged") is not True
        or index.get("raw_media_tracked") is not False
        or index.get("S4.5_or_later_started") is not False
    ):
        issues.append(
            _issue("evidence_index_invalid", str(index_path), "contract mismatch")
        )
    if index_schema in {
        "ias.s4_4.amendment_03_evidence_index.v2",
        "ias.s4_4.amendment_03_evidence_index.v3",
        "ias.s4_4.amendment_03_evidence_index.v4",
        "ias.s4_4.amendment_03_evidence_index.v5",
    } and (
        index.get("amendment_id") != "s4_4_data_expansion_amendment_03"
        or index.get("new_amendment_created") is not False
        or index.get("v1_package_sha256") != V1_PACKAGE_SHA256
        or (
            index_schema == "ias.s4_4.amendment_03_evidence_index.v3"
            and index.get("v2_package_sha256") != V2_PACKAGE_SHA256
        )
        or (
            index_schema == "ias.s4_4.amendment_03_evidence_index.v4"
            and (
                index.get("v2_package_sha256") != V2_PACKAGE_SHA256
                or index.get("v3_package_sha256") != V3_PACKAGE_SHA256
            )
        )
        or (
            index_schema == "ias.s4_4.amendment_03_evidence_index.v5"
            and (
                index.get("v2_package_sha256") != V2_PACKAGE_SHA256
                or index.get("v3_package_sha256") != V3_PACKAGE_SHA256
                or index.get("v4_package_sha256") != V4_PACKAGE_SHA256
            )
        )
    ):
        issues.append(
            _issue(
                "multiday_evidence_index_invalid",
                str(index_path),
                "same-amendment continuation contract mismatch",
            )
        )

    artifacts = (
        index.get("artifacts") if isinstance(index.get("artifacts"), list) else []
    )
    expected_checksums: dict[str, str] = {}
    seen: set[str] = set()
    for number, record in enumerate(artifacts):
        if not isinstance(record, dict):
            issues.append(_issue("invalid_artifact", str(number), "not an object"))
            continue
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            issues.append(
                _issue("invalid_or_duplicate_path", str(number), str(relative))
            )
            continue
        seen.add(relative)
        expected_checksums[relative] = str(record.get("sha256"))
        if Path(relative).suffix.lower() in MEDIA_SUFFIXES:
            issues.append(_issue("tracked_media_forbidden", relative, "metadata only"))
        if any(
            f"/S4/{phase}/" in relative for phase in ("S4.5", "S4.6", "S4.7", "S4.8")
        ):
            issues.append(_issue("later_phase_artifact", relative, "forbidden"))
        candidate = _resolve_artifact(
            relative, repo_root, evidence_root, canonical_output
        )
        if not candidate.is_file():
            issues.append(_issue("missing_artifact", relative, "file absent"))
            continue
        if candidate.stat().st_size != record.get("byte_size"):
            issues.append(_issue("artifact_size_mismatch", relative, "size differs"))
        if sha256_file(candidate) != record.get("sha256"):
            issues.append(_issue("artifact_hash_mismatch", relative, "hash differs"))
        if require_tracked and candidate.resolve().is_relative_to(repo_root):
            repo_relative = candidate.resolve().relative_to(repo_root).as_posix()
            if not _tracked(repo_root, repo_relative):
                issues.append(_issue("artifact_not_tracked", relative, "not in Git"))
    checksum_name = {
        "ias.s4_4.amendment_03_evidence_index.v2": "SHA256SUMS.v2",
        "ias.s4_4.amendment_03_evidence_index.v3": "SHA256SUMS.v3",
        "ias.s4_4.amendment_03_evidence_index.v4": "SHA256SUMS.v4",
        "ias.s4_4.amendment_03_evidence_index.v5": CHECKSUM_PATH_V2,
    }.get(index_schema, "SHA256SUMS")
    checksum_path = evidence_root / checksum_name
    try:
        if _checksums(checksum_path) != expected_checksums:
            issues.append(
                _issue(
                    "checksum_coverage_mismatch", str(checksum_path), "index differs"
                )
            )
    except (OSError, S44AmendmentError) as exc:
        issues.append(_issue("checksums_invalid", str(checksum_path), str(exc)))
    if require_tracked:
        for metadata_path in (index_path, checksum_path):
            if not _committed_exact(repo_root, metadata_path):
                issues.append(
                    _issue(
                        "evidence_metadata_not_committed_exact",
                        str(metadata_path),
                        "must be tracked and byte-identical to HEAD",
                    )
                )

    inherited_path = evidence_root / "inheritance/inherited_fit_a.v1.json"
    fit_b_path = evidence_root / "manifests/sessions/fit_b.json"
    holdout_path = evidence_root / "manifests/sessions/prospective_holdout.json"
    continuation_path = evidence_root / "freeze/amendment_02_continuation.v1.json"
    aggregate_path = evidence_root / "aggregate_index.v1.json"
    try:
        inherited = load_json(inherited_path)
        validate_inherited_fit_a(inherited, config)
        manifests = {
            "fit_b": load_json(fit_b_path),
            "prospective_holdout": load_json(holdout_path),
        }
        validate_future_manifests(manifests, config)
        expected_manifests = build_future_manifests(config, repo_root)
        if manifests != expected_manifests:
            raise S44AmendmentError("future manifest deterministic rebuild differs")
        if load_json(
            evidence_root / "manifests/fit_b_manifest.v1.json"
        ) != combined_future_manifest(manifests, "fit"):
            raise S44AmendmentError("future Fit B partition manifest differs")
        if load_json(
            evidence_root / "manifests/prospective_holdout_manifest.v1.json"
        ) != combined_future_manifest(manifests, "prospective_holdout"):
            raise S44AmendmentError("future holdout partition manifest differs")
        expected_continuation = build_continuation_reference(config, inherited)
        if load_json(continuation_path) != expected_continuation:
            raise S44AmendmentError("continuation reference differs")
        expected_aggregate = build_aggregate_index(
            config, inherited, manifests["fit_b"], manifests["prospective_holdout"]
        )
        if load_json(aggregate_path) != expected_aggregate:
            raise S44AmendmentError("aggregate logical index differs")
        if require_machine_local:
            rebuilt_inherited = build_inherited_fit_a(config, repo_root)
            if rebuilt_inherited != inherited:
                raise S44AmendmentError("inherited Fit A live byte rebuild differs")
    except (OSError, KeyError, S44AmendmentError) as exc:
        inherited = None
        manifests = None
        issues.append(
            _issue("amendment_03_contract_invalid", str(evidence_root), str(exc))
        )

    if index_schema in {
        "ias.s4_4.amendment_03_evidence_index.v2",
        "ias.s4_4.amendment_03_evidence_index.v3",
        "ias.s4_4.amendment_03_evidence_index.v4",
        "ias.s4_4.amendment_03_evidence_index.v5",
    }:
        try:
            active_continuation_path = {
                "ias.s4_4.amendment_03_evidence_index.v2": (
                    "freeze/multiday_session_continuation.v2.json"
                ),
                "ias.s4_4.amendment_03_evidence_index.v3": (
                    "freeze/multiday_session_continuation.v3.json"
                ),
                "ias.s4_4.amendment_03_evidence_index.v4": (
                    "freeze/multiday_session_continuation.v4.json"
                ),
                "ias.s4_4.amendment_03_evidence_index.v5": CONTINUATION_PATH,
            }[index_schema]
            continuation = load_json(evidence_root / active_continuation_path)
            expected_schema = {
                "ias.s4_4.amendment_03_evidence_index.v2": (
                    "ias.s4_4.amendment_03_multiday_continuation.v2"
                ),
                "ias.s4_4.amendment_03_evidence_index.v3": (
                    "ias.s4_4.amendment_03_multiday_continuation.v3"
                ),
                "ias.s4_4.amendment_03_evidence_index.v4": (
                    "ias.s4_4.amendment_03_multiday_continuation.v4"
                ),
                "ias.s4_4.amendment_03_evidence_index.v5": (
                    "ias.s4_4.amendment_03_multiday_continuation.v5"
                ),
            }[index_schema]
            if (
                continuation.get("schema") != expected_schema
                or continuation.get("amendment_id")
                != "s4_4_data_expansion_amendment_03"
                or continuation.get("new_amendment_created") is not False
                or continuation.get("scientific_condition_matrix_changed") is not False
                or continuation.get("future_take_identities_changed") is not False
                or continuation.get("immutable_v1_package_sha256") != V1_PACKAGE_SHA256
                or (
                    index_schema == "ias.s4_4.amendment_03_evidence_index.v3"
                    and continuation.get("immutable_v2_package_sha256")
                    != V2_PACKAGE_SHA256
                )
                or (
                    index_schema == "ias.s4_4.amendment_03_evidence_index.v4"
                    and (
                        continuation.get("immutable_v2_package_sha256")
                        != V2_PACKAGE_SHA256
                        or continuation.get("immutable_v3_package_sha256")
                        != V3_PACKAGE_SHA256
                    )
                )
                or (
                    index_schema == "ias.s4_4.amendment_03_evidence_index.v5"
                    and (
                        continuation.get("immutable_v2_package_sha256")
                        != V2_PACKAGE_SHA256
                        or continuation.get("immutable_v3_package_sha256")
                        != V3_PACKAGE_SHA256
                        or continuation.get("immutable_v4_package_sha256")
                        != V4_PACKAGE_SHA256
                        or continuation.get("mac_power_policy")
                        != {
                            "ac_power_required": False,
                            "battery_operation_permitted": True,
                            "truthful_power_source_required": True,
                            "truthful_charging_state_required": True,
                            "truthful_battery_percentage_required": True,
                        }
                    )
                )
                or continuation.get("calendar_policy", {}).get(
                    "one_session_may_span_multiple_local_dates"
                )
                is not True
                or continuation.get("calendar_policy", {}).get(
                    "one_preflight_per_session_and_local_date_segment"
                )
                is not True
                or continuation.get("continuation_sha256")
                != canonical_sha256(
                    {
                        key: value
                        for key, value in continuation.items()
                        if key != "continuation_sha256"
                    }
                )
            ):
                raise S44AmendmentError("same-amendment multiday continuation differs")
            _validate_cutoff_inventory(continuation["cutoff"], config, repo_root)
        except (OSError, KeyError, S44AmendmentError) as exc:
            issues.append(
                _issue(
                    "multiday_continuation_invalid",
                    str(evidence_root / active_continuation_path),
                    str(exc),
                )
            )

    seal_name = {
        "ias.s4_4.amendment_03_evidence_index.v2": "precollection_seal.v2.json",
        "ias.s4_4.amendment_03_evidence_index.v3": "precollection_seal.v3.json",
        "ias.s4_4.amendment_03_evidence_index.v4": "precollection_seal.v4.json",
        "ias.s4_4.amendment_03_evidence_index.v5": SEAL_PATH_V2,
    }.get(index_schema, "precollection_seal.v1.json")
    seal_path = evidence_root / seal_name
    try:
        seal = load_json(seal_path)
        validate_precollection_seal(
            seal, repo_root=repo_root, require_committed=require_committed
        )
        if sha256_file(seal_path) != index.get("precollection_seal_sha256"):
            raise S44AmendmentError("precollection seal/index hash mismatch")
        if require_committed and index.get("collection_allowed") is not True:
            raise S44AmendmentError("collection remains disabled")
    except (OSError, S44AmendmentError) as exc:
        issues.append(_issue("precollection_seal_invalid", str(seal_path), str(exc)))

    census = None
    if (
        require_machine_local
        and isinstance(inherited, dict)
        and isinstance(manifests, dict)
    ):
        try:
            census = validate_future_attempt_census(
                inherited, manifests, _future_attempts(config, repo_root)
            )
            if require_final and census["status"] != "passed":
                raise S44AmendmentError(
                    f"amendment_03 final census is {census['status']}"
                )
        except S44AmendmentError as exc:
            issues.append(
                _issue(
                    "future_attempt_census_invalid",
                    config["retention"]["attempt_root"],
                    str(exc),
                )
            )

    tracked_dataset = subprocess.run(
        ["git", "ls-files", "dataset"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked_dataset:
        issues.append(_issue("raw_dataset_tracked", "dataset", tracked_dataset))
    for phase in ("S4.5", "S4.6", "S4.7", "S4.8"):
        if (repo_root / f"outputs/isaac_audio_sensors/S4/{phase}").exists():
            issues.append(_issue("later_phase_directory_present", phase, "forbidden"))
    return {
        "schema": "ias.s4_4.amendment_03_integrity_validation.v1",
        "status": "passed" if not issues else "failed",
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "require_machine_local": require_machine_local,
        "require_final": require_final,
        "checked_artifact_count": len(artifacts),
        "logical_counts": LOGICAL_COUNTS,
        "predecessor_validation": predecessor_validation,
        "attempt_census": census,
        "same_calendar_date_permitted": True,
        "restart_or_reconnection_required": False,
        "prospective_holdout_scientifically_opened": False,
        "scientific_outcomes_returned": False,
        "S4.5_or_later_started": False,
        "issues": issues,
    }


def require_capture_ready_package(
    index_path: Path, *, repo_root: Path, config_path: Path
) -> dict[str, Any]:
    """Require the committed, exact, machine-local precollection package."""

    result = validate(
        index_path,
        repo_root=repo_root,
        config_path=config_path,
        require_tracked=True,
        require_committed=True,
        require_machine_local=True,
        require_final=False,
    )
    if result["status"] != "passed":
        codes = sorted({issue["code"] for issue in result["issues"]})
        raise S44AmendmentError(
            "capture denied: amendment_03 committed evidence package invalid: "
            + ", ".join(codes)
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--require-machine-local", action="store_true")
    parser.add_argument("--require-final", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(
            args.index,
            repo_root=args.repo_root,
            config_path=args.config,
            require_tracked=args.require_tracked,
            require_committed=args.require_committed,
            require_machine_local=args.require_machine_local,
            require_final=args.require_final,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment-03 validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
