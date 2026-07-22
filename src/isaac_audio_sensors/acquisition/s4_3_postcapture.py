"""Fail-closed provenance checks for the S4.3 corrective-02 evidence build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import sha256_file
from isaac_audio_sensors.acquisition.s4_3 import S43Error, load_json

ORIGINAL_SCHEMA = "ias.s4_3.corrective_02_postcapture_evidence_manifest.v1"
CORRECTED_SCHEMA = "ias.s4_3.corrective_02_postcapture_provenance.v2"
ORIGINAL_MANIFEST_PATH = (
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "corrective_02_postcapture_evidence_manifest.json"
)
ORIGINAL_MANIFEST_SHA256 = (
    "bd81077d1339ddcac9351565d529f7eb0489f7a1c8c4c0b08fd39fedffeb57ef"
)
FREEZE_COMMIT = "c6bfc002a5b7a8656797cd308b710489860517cc"
AUTHORIZATION_COMMIT = "a7df16ebd214bfe9af65a699b3850ffe09ee6e45"
ORIGINAL_POSTCAPTURE_CHECKPOINT = "c52a205c4a3b9f1cfc91a2cc56cfe533af7d5543"
EXPECTED_TRIAL_ID = "s4_3_rob_silence_03_boundary_support_01"
EXPECTED_SCIENTIFIC_CHANGES = {
    "detector_changed_after_capture": False,
    "matrix_changed_after_capture": False,
    "threshold_changed_after_capture": False,
    "raw_evidence_modified": False,
    "unrelated_trial_repeated": False,
}
FREEZE_CONTENT_SHA256 = {
    "docs/development/specs/s4_3_pilot_corrective_02.md": (
        "754ae3368aeadb8cc8e8d4dbe3586e552ffa0e47d7027dd3558b5b0e6e2a0cad"
    ),
    "configs/s4_3_pilot_corrective_02.v1.json": (
        "af1a557c6f9504c4468515d2d1f1d1acb55e4bc13ba45adc30e0efad603ad311"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_corrective_02.json": (
        "59e3bb8652c9a40df01a2290ac9f9e9602e325721a228247a165243b9aeb1cce"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "transient_event_contract_02.json": (
        "bbc46e2091d5a872a093e59ca788a76137c042a2fb66758db3bd73d22be7b90a"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "boundary_defect_reproduction_02.json": (
        "35c8589abd6a2f2ec72b1361d2bfa35ca707e7e9fd5fbe08b8a4028a0e32bcd8"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "corrective_02_supersession.json": (
        "145f0804ca058b9feeb48ba49f957273b2608b191dd33ebe6a6db649c6e2d24c"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "trial_inventory_corrective_02_precollection.json": (
        "61a6e06aa235c20618d865b9dc0916d815579229a327f7a7de4c7540a62df46a"
    ),
    "src/isaac_audio_sensors/acquisition/s4_3.py": (
        "d2d2217674dd949c09c60ea9bcca6ad3792d5421c75428a626bfb81279d8c293"
    ),
    "scripts/run_s4_3_trial.py": (
        "1c27074e65a623135226adb3a2a3aff9df6b84c1740f4c75d70497125a3ab8cf"
    ),
    "scripts/build_s4_3_evidence.py": (
        "738f04c129b20564b77a4127d9a1d82bb2ac75b52dbb49a0075e2d0ee3e6d80f"
    ),
    "scripts/validate_s4_3_integrity.py": (
        "f172c9a35e69ab73e3217d1b4c12d202aeee3a6266a9edef0d9d708127d769ee"
    ),
    "tests/test_s4_3_pilot.py": (
        "444445c55869a5d1031c5ede86527221e2634f1de935e426a6044d529462fbb5"
    ),
}
AUTHORIZATION_CONTENT_SHA256 = {
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "corrective_02_failure_handling_01.json": (
        "3d1c0bf7d29b00e1226af4226de693e38f433ef8e140d704885a2395ab44ff39"
    ),
    "outputs/isaac_audio_sensors/S4/S4.3/diagnostics/"
    "corrective_02_failed_attempt_diagnosis.json": (
        "6493ab2ef72bd60fb68ef183146240f8c8d7586b5778f855ba326cc3526dbd17"
    ),
}
PREREGISTERED_IMPLEMENTATION_PATHS = {
    "src/isaac_audio_sensors/acquisition/s4_3.py",
    "scripts/run_s4_3_trial.py",
    "scripts/build_s4_3_evidence.py",
    "scripts/validate_s4_3_integrity.py",
    "tests/test_s4_3_pilot.py",
}
REQUIRED_IMPLEMENTATION_PATHS = {
    "src/isaac_audio_sensors/acquisition/s4_3.py",
    "src/isaac_audio_sensors/acquisition/s4_3_postcapture.py",
    "scripts/build_s4_3_evidence.py",
    "scripts/validate_s4_3_integrity.py",
    "tests/test_s4_3_pilot.py",
}
SCIENTIFIC_IMMUTABLE_PATHS = {
    "src/isaac_audio_sensors/acquisition/s4_3.py",
    "configs/s4_3_pilot_corrective_02.v1.json",
    "configs/s4_3_pilot_corrective_01.v1.json",
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "preregistration_corrective_02.json",
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
    "transient_event_contract_02.json",
    "outputs/isaac_audio_sensors/S4/S4.3/freeze/clipping_corrective_01.json",
}
EXPECTED_INVARIANTS = {
    "detector_sha256": FREEZE_CONTENT_SHA256[
        "src/isaac_audio_sensors/acquisition/s4_3.py"
    ],
    "configuration_sha256": FREEZE_CONTENT_SHA256[
        "configs/s4_3_pilot_corrective_02.v1.json"
    ],
    "matrix_canonical_sha256": (
        "0a8910e341a0d9fc2d41f3ba04164ad2f8703e0c97ab77dc9efb1843d28394dc"
    ),
    "maximum_sustained_clip_run_samples": 4000,
    "sustained_clip_failure_comparator": "greater_than_or_equal",
}
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def _require_commit_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise S43Error(f"corrective-02 {label} commit binding is invalid")
    return value


def _git(repo_root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise S43Error("Git is unavailable for corrective-02 provenance validation")
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.devnull,
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            [executable, "-C", str(repo_root), *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError as exc:
        raise S43Error(
            "Git execution failed for corrective-02 provenance validation"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise S43Error(
            "Git provenance command was inconclusive"
            + (f": {detail}" if detail else "")
        )
    return result.stdout


def _validate_repository(repo_root: Path) -> str:
    root = repo_root.resolve()
    top_level = _git(root, "rev-parse", "--show-toplevel").decode().strip()
    try:
        discovered = Path(top_level).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise S43Error("Git repository top-level is invalid") from exc
    if discovered != root:
        raise S43Error("corrective-02 validation requires the exact Git top-level")
    head = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    _require_commit_id(head, label="current HEAD")
    _require_commit_object(root, head, label="current HEAD")
    return head


def _require_commit_object(repo_root: Path, commit: str, *, label: str) -> None:
    try:
        object_type = _git(repo_root, "cat-file", "-t", commit).decode().strip()
    except S43Error as exc:
        raise S43Error(
            f"corrective-02 {label} commit does not exist or could not be verified"
        ) from exc
    if object_type != "commit":
        raise S43Error(f"corrective-02 {label} is not a commit object")


def _require_ancestor(repo_root: Path, ancestor: str, descendant: str) -> None:
    executable = shutil.which("git")
    if executable is None:
        raise S43Error("Git is unavailable for corrective-02 provenance validation")
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.devnull,
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            [
                executable,
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError as exc:
        raise S43Error("Git ancestry validation could not execute") from exc
    if result.returncode == 1:
        raise S43Error(
            f"corrective-02 commit ancestry is broken: {ancestor} !-> {descendant}"
        )
    if result.returncode != 0:
        raise S43Error("Git ancestry validation was inconclusive")


def _blob_oid(repo_root: Path, commit: str, path: str) -> str:
    output = _git(
        repo_root,
        "ls-tree",
        "-z",
        "--full-tree",
        commit,
        "--",
        path,
    )
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise S43Error(f"corrective-02 commit artifact is missing: {path}")
    try:
        metadata, recorded_path = records[0].split(b"\t", 1)
        _mode, object_type, encoded_oid = metadata.split(b" ", 2)
        oid = encoded_oid.decode("ascii")
        decoded_path = recorded_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise S43Error(
            f"malformed Git tree record for corrective-02 path: {path}"
        ) from exc
    if (
        object_type != b"blob"
        or decoded_path != path
        or _COMMIT_RE.fullmatch(oid) is None
    ):
        raise S43Error(f"invalid Git blob binding for corrective-02 path: {path}")
    return oid


def _blob_bytes(repo_root: Path, commit: str, path: str) -> bytes:
    return _git(repo_root, "cat-file", "blob", _blob_oid(repo_root, commit, path))


def _blob_sha256(repo_root: Path, commit: str, path: str) -> str:
    return hashlib.sha256(_blob_bytes(repo_root, commit, path)).hexdigest()


def _require_commit_content(
    repo_root: Path,
    commit: str,
    expected: dict[str, str],
    *,
    label: str,
) -> None:
    for path, expected_hash in expected.items():
        if _blob_sha256(repo_root, commit, path) != expected_hash:
            raise S43Error(
                f"corrective-02 {label} artifact SHA-256 differs: {path}"
            )


def _require_unchanged_science(
    repo_root: Path, freeze_commit: str, authorization_commit: str
) -> None:
    for path in sorted(SCIENTIFIC_IMMUTABLE_PATHS):
        if _blob_oid(repo_root, freeze_commit, path) != _blob_oid(
            repo_root, authorization_commit, path
        ):
            raise S43Error(
                "corrective-02 scientific detector/configuration/matrix/threshold "
                f"content changed between freeze and authorization: {path}"
            )


def _require_preregistered_implementation(repo_root: Path, commit: str) -> None:
    path = (
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/"
        "preregistration_corrective_02.json"
    )
    try:
        preregistration = json.loads(_blob_bytes(repo_root, commit, path))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise S43Error("corrective-02 commit preregistration JSON is invalid") from exc
    implementation = preregistration.get("implementation")
    if not isinstance(implementation, list):
        raise S43Error("corrective-02 preregistered implementation is absent")
    bindings = {
        item.get("path"): item.get("sha256")
        for item in implementation
        if isinstance(item, dict)
    }
    if set(bindings) != PREREGISTERED_IMPLEMENTATION_PATHS or len(bindings) != len(
        implementation
    ):
        raise S43Error("corrective-02 preregistered implementation is incomplete")
    for implementation_path in sorted(PREREGISTERED_IMPLEMENTATION_PATHS):
        if bindings[implementation_path] != FREEZE_CONTENT_SHA256[implementation_path]:
            raise S43Error(
                "corrective-02 preregistered implementation binding differs: "
                f"{implementation_path}"
            )
        if _blob_sha256(repo_root, commit, implementation_path) != bindings[
            implementation_path
        ]:
            raise S43Error(
                "corrective-02 preregistered implementation artifact differs: "
                f"{implementation_path}"
            )
    if (
        preregistration.get("matrix", {}).get("canonical_json_sha256")
        != EXPECTED_INVARIANTS["matrix_canonical_sha256"]
    ):
        raise S43Error("corrective-02 frozen matrix SHA-256 differs")


def _require_threshold_invariant(repo_root: Path, commit: str) -> None:
    path = (
        "outputs/isaac_audio_sensors/S4/S4.3/freeze/clipping_corrective_01.json"
    )
    try:
        clipping = json.loads(_blob_bytes(repo_root, commit, path))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise S43Error("corrective-02 clipping provenance JSON is invalid") from exc
    effective = clipping.get("corrected_effective_definition", {})
    if (
        effective.get("maximum_sustained_clip_run_samples")
        != EXPECTED_INVARIANTS["maximum_sustained_clip_run_samples"]
        or effective.get("failure_comparator")
        != EXPECTED_INVARIANTS["sustained_clip_failure_comparator"]
    ):
        raise S43Error("corrective-02 sustained-clipping threshold invariant differs")


def _require_file_binding(
    binding: Any,
    *,
    repo_root: Path,
    label: str,
) -> Path:
    if not isinstance(binding, dict):
        raise S43Error(f"post-capture manifest {label} binding must be an object")
    relative = binding.get("path")
    expected_hash = binding.get("sha256")
    if not isinstance(relative, str) or not relative:
        raise S43Error(f"post-capture manifest {label} path is missing")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise S43Error(f"post-capture manifest {label} SHA-256 is invalid")
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise S43Error(
            f"post-capture manifest {label} path escapes repository"
        ) from exc
    if not candidate.is_file():
        raise S43Error(f"post-capture manifest {label} file is absent: {relative}")
    if sha256_file(candidate) != expected_hash:
        raise S43Error(f"post-capture manifest {label} SHA-256 differs: {relative}")
    return candidate


def _require_historical_implementation(
    implementation: Any, *, repo_root: Path, checkpoint: str
) -> None:
    if not isinstance(implementation, list):
        raise S43Error("post-capture implementation bindings must be a list")
    bindings = {
        item.get("path"): item.get("sha256")
        for item in implementation
        if isinstance(item, dict)
    }
    if set(bindings) != REQUIRED_IMPLEMENTATION_PATHS or len(bindings) != len(
        implementation
    ):
        raise S43Error(
            "post-capture implementation bindings are incomplete or duplicated"
        )
    for path in sorted(REQUIRED_IMPLEMENTATION_PATHS):
        if _blob_sha256(repo_root, checkpoint, path) != bindings[path]:
            raise S43Error(f"post-capture historical implementation differs: {path}")


def _require_current_manifest_evidence(
    manifest: dict[str, Any], *, repo_root: Path
) -> None:
    frozen = manifest.get("frozen_contract")
    if not isinstance(frozen, dict) or set(frozen) != {
        "configuration",
        "preregistration",
        "detector_contract",
        "failure_handling",
    }:
        raise S43Error(
            "corrective-02 post-capture frozen-contract bindings are incomplete"
        )
    for label, binding in frozen.items():
        _require_file_binding(binding, repo_root=repo_root, label=label)

    operational = manifest.get("retained_operational_records")
    if not isinstance(operational, dict) or set(operational) != {
        "pre_acquisition_confirmation_rejection",
        "failed_attempt_diagnosis",
    }:
        raise S43Error(
            "corrective-02 retained operational-record bindings are incomplete"
        )
    for label, binding in operational.items():
        _require_file_binding(binding, repo_root=repo_root, label=label)

    attempts = manifest.get("retained_attempts")
    if not isinstance(attempts, list) or len(attempts) != 2:
        raise S43Error(
            "corrective-02 must bind exactly two retained acquisition attempts"
        )
    outcomes = []
    ids = set()
    for number, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise S43Error(f"retained_attempts[{number}] must be an object")
        attempt_id = attempt.get("attempt_id")
        outcome = attempt.get("outcome")
        if not isinstance(attempt_id, str) or not attempt_id.startswith(
            f"{EXPECTED_TRIAL_ID}_"
        ):
            raise S43Error(f"retained_attempts[{number}] has invalid attempt id")
        if attempt_id in ids:
            raise S43Error("corrective-02 retained attempt ids must be unique")
        ids.add(attempt_id)
        outcomes.append(outcome)
        lifecycle_path = _require_file_binding(
            attempt.get("lifecycle"),
            repo_root=repo_root,
            label=f"retained_attempts[{number}].lifecycle",
        )
        lifecycle = load_json(lifecycle_path)
        if lifecycle.get("state") != outcome:
            raise S43Error(f"retained_attempts[{number}] lifecycle outcome differs")
        if outcome == "accepted":
            _require_file_binding(
                attempt.get("manifest"),
                repo_root=repo_root,
                label=f"retained_attempts[{number}].manifest",
            )
            _require_file_binding(
                attempt.get("analysis"),
                repo_root=repo_root,
                label=f"retained_attempts[{number}].analysis",
            )
        elif outcome == "failed":
            _require_file_binding(
                attempt.get("failure"),
                repo_root=repo_root,
                label=f"retained_attempts[{number}].failure",
            )
        else:
            raise S43Error(f"retained_attempts[{number}] outcome is not terminal")
    if sorted(outcomes) != ["accepted", "failed"]:
        raise S43Error("corrective-02 must retain one failed and one accepted attempt")


def _validate_original_manifest(
    manifest: dict[str, Any], *, repo_root: Path, head: str
) -> None:
    if manifest.get("schema") != ORIGINAL_SCHEMA:
        raise S43Error("wrong original corrective-02 post-capture manifest schema")
    if manifest.get("status") != "frozen_post_capture_evidence_binding":
        raise S43Error("original corrective-02 post-capture manifest is not frozen")
    if manifest.get("s4_4_started") is not False:
        raise S43Error(
            "corrective-02 post-capture manifest must declare S4.4 untouched"
        )
    if manifest.get("scientific_changes") != EXPECTED_SCIENTIFIC_CHANGES:
        raise S43Error(
            "corrective-02 post-capture scientific-change declaration differs"
        )
    commits = manifest.get("provenance_commits")
    if not isinstance(commits, dict) or set(commits) != {
        "pre_capture_freeze_and_implementation",
        "replacement_authorization",
    }:
        raise S43Error("corrective-02 post-capture commit bindings are incomplete")
    freeze_commit = _require_commit_id(
        commits.get("pre_capture_freeze_and_implementation"), label="freeze"
    )
    authorization_commit = _require_commit_id(
        commits.get("replacement_authorization"), label="authorization"
    )
    for label, commit in (
        ("freeze", freeze_commit),
        ("authorization", authorization_commit),
        ("original post-capture checkpoint", ORIGINAL_POSTCAPTURE_CHECKPOINT),
    ):
        _require_commit_object(repo_root, commit, label=label)
    _require_ancestor(repo_root, freeze_commit, authorization_commit)
    _require_ancestor(
        repo_root, authorization_commit, ORIGINAL_POSTCAPTURE_CHECKPOINT
    )
    _require_ancestor(repo_root, ORIGINAL_POSTCAPTURE_CHECKPOINT, head)
    _require_commit_content(
        repo_root, freeze_commit, FREEZE_CONTENT_SHA256, label="freeze"
    )
    _require_commit_content(
        repo_root,
        authorization_commit,
        AUTHORIZATION_CONTENT_SHA256,
        label="authorization",
    )
    _require_preregistered_implementation(repo_root, freeze_commit)
    _require_threshold_invariant(repo_root, freeze_commit)
    _require_unchanged_science(repo_root, freeze_commit, authorization_commit)
    if freeze_commit != FREEZE_COMMIT or authorization_commit != AUTHORIZATION_COMMIT:
        raise S43Error("corrective-02 commit bindings differ from retained provenance")
    _require_current_manifest_evidence(manifest, repo_root=repo_root)
    _require_historical_implementation(
        manifest.get("post_capture_implementation"),
        repo_root=repo_root,
        checkpoint=ORIGINAL_POSTCAPTURE_CHECKPOINT,
    )


def _binding_map(value: Any, expected_paths: set[str], *, label: str) -> dict[str, str]:
    if not isinstance(value, list):
        raise S43Error(f"corrective-02 {label} bindings must be a list")
    bindings = {
        item.get("path"): item.get("sha256")
        for item in value
        if isinstance(item, dict)
    }
    if set(bindings) != expected_paths or len(bindings) != len(value):
        raise S43Error(f"corrective-02 {label} bindings are incomplete or duplicated")
    if any(
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for digest in bindings.values()
    ):
        raise S43Error(f"corrective-02 {label} binding SHA-256 is invalid")
    return bindings


def validate_corrective_02_postcapture_manifest(
    manifest: dict[str, Any], *, repo_root: Path
) -> None:
    """Raise when corrective-02 post-capture provenance is absent or inconsistent."""
    head = _validate_repository(repo_root)
    if manifest.get("schema") == ORIGINAL_SCHEMA:
        _validate_original_manifest(manifest, repo_root=repo_root, head=head)
        return
    if manifest.get("schema") != CORRECTED_SCHEMA:
        raise S43Error("wrong active corrective-02 post-capture provenance schema")
    if manifest.get("status") != "active_superseding_provenance_correction":
        raise S43Error("corrective-02 provenance correction is not active")
    if manifest.get("s4_4_started") is not False:
        raise S43Error("corrective-02 provenance correction must leave S4.4 untouched")
    if manifest.get("scientific_changes") != EXPECTED_SCIENTIFIC_CHANGES:
        raise S43Error("corrective-02 correction scientific-change declaration differs")
    if manifest.get("scientific_invariants") != EXPECTED_INVARIANTS:
        raise S43Error("corrective-02 correction scientific invariants differ")
    if manifest.get("new_acquisition_required") is not False:
        raise S43Error("corrective-02 provenance-only correction forbids acquisition")

    supersedes = manifest.get("supersedes")
    if not isinstance(supersedes, dict) or supersedes != {
        "path": ORIGINAL_MANIFEST_PATH,
        "sha256": ORIGINAL_MANIFEST_SHA256,
        "validated_checkpoint": ORIGINAL_POSTCAPTURE_CHECKPOINT,
        "original_record_preserved_unchanged": True,
    }:
        raise S43Error("corrective-02 superseded manifest binding differs")
    original_path = _require_file_binding(
        supersedes, repo_root=repo_root, label="superseded_original_manifest"
    )
    original = load_json(original_path)
    _validate_original_manifest(original, repo_root=repo_root, head=head)

    commits = manifest.get("provenance_commits")
    if not isinstance(commits, dict) or set(commits) != {
        "pre_capture_freeze_and_implementation",
        "replacement_authorization",
        "validated_checkpoint",
    }:
        raise S43Error("corrective-02 corrected commit bindings are incomplete")
    freeze_commit = _require_commit_id(
        commits.get("pre_capture_freeze_and_implementation"), label="freeze"
    )
    authorization_commit = _require_commit_id(
        commits.get("replacement_authorization"), label="authorization"
    )
    checkpoint = _require_commit_id(
        commits.get("validated_checkpoint"), label="validated checkpoint"
    )
    for label, commit in (
        ("freeze", freeze_commit),
        ("authorization", authorization_commit),
        ("validated checkpoint", checkpoint),
    ):
        _require_commit_object(repo_root, commit, label=label)
    _require_ancestor(repo_root, freeze_commit, authorization_commit)
    _require_ancestor(repo_root, authorization_commit, checkpoint)
    _require_ancestor(repo_root, checkpoint, head)
    if freeze_commit != FREEZE_COMMIT or authorization_commit != AUTHORIZATION_COMMIT:
        raise S43Error("corrective-02 corrected commit bindings differ")

    content = manifest.get("commit_content")
    if not isinstance(content, dict) or set(content) != {
        "pre_capture_freeze",
        "replacement_authorization",
        "scientific_unchanged_paths",
        "preregistered_implementation_paths",
    }:
        raise S43Error("corrective-02 corrected commit-content bindings are incomplete")
    freeze_bindings = _binding_map(
        content["pre_capture_freeze"], set(FREEZE_CONTENT_SHA256), label="freeze"
    )
    authorization_bindings = _binding_map(
        content["replacement_authorization"],
        set(AUTHORIZATION_CONTENT_SHA256),
        label="authorization",
    )
    if freeze_bindings != FREEZE_CONTENT_SHA256:
        raise S43Error("corrective-02 correction freeze hashes differ")
    if authorization_bindings != AUTHORIZATION_CONTENT_SHA256:
        raise S43Error("corrective-02 correction authorization hashes differ")
    if content["scientific_unchanged_paths"] != sorted(
        SCIENTIFIC_IMMUTABLE_PATHS
    ):
        raise S43Error("corrective-02 scientific unchanged-path set differs")
    if content["preregistered_implementation_paths"] != sorted(
        PREREGISTERED_IMPLEMENTATION_PATHS
    ):
        raise S43Error("corrective-02 preregistered implementation path set differs")
    _require_commit_content(
        repo_root, freeze_commit, freeze_bindings, label="freeze"
    )
    _require_commit_content(
        repo_root,
        authorization_commit,
        authorization_bindings,
        label="authorization",
    )
    _require_preregistered_implementation(repo_root, freeze_commit)
    _require_threshold_invariant(repo_root, freeze_commit)
    _require_unchanged_science(repo_root, freeze_commit, authorization_commit)

    active_implementation = _binding_map(
        manifest.get("active_postcapture_implementation"),
        REQUIRED_IMPLEMENTATION_PATHS,
        label="active implementation",
    )
    for path in sorted(REQUIRED_IMPLEMENTATION_PATHS):
        if _blob_sha256(repo_root, checkpoint, path) != active_implementation[path]:
            raise S43Error(f"corrective-02 checkpoint implementation differs: {path}")
        if sha256_file(repo_root / path) != active_implementation[path]:
            raise S43Error(f"corrective-02 current implementation differs: {path}")
