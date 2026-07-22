"""Fail-closed provenance checks for the S4.3 corrective-02 evidence build."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import sha256_file
from isaac_audio_sensors.acquisition.s4_3 import S43Error, load_json

EXPECTED_SCHEMA = "ias.s4_3.corrective_02_postcapture_evidence_manifest.v1"
EXPECTED_TRIAL_ID = "s4_3_rob_silence_03_boundary_support_01"
EXPECTED_SCIENTIFIC_CHANGES = {
    "detector_changed_after_capture": False,
    "matrix_changed_after_capture": False,
    "threshold_changed_after_capture": False,
    "raw_evidence_modified": False,
    "unrelated_trial_repeated": False,
}
REQUIRED_IMPLEMENTATION_PATHS = {
    "src/isaac_audio_sensors/acquisition/s4_3.py",
    "src/isaac_audio_sensors/acquisition/s4_3_postcapture.py",
    "scripts/build_s4_3_evidence.py",
    "scripts/validate_s4_3_integrity.py",
    "tests/test_s4_3_pilot.py",
}


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


def validate_corrective_02_postcapture_manifest(
    manifest: dict[str, Any], *, repo_root: Path
) -> None:
    """Raise when corrective-02 post-capture provenance is absent or inconsistent."""
    if manifest.get("schema") != EXPECTED_SCHEMA:
        raise S43Error("wrong corrective-02 post-capture manifest schema")
    if manifest.get("status") != "frozen_post_capture_evidence_binding":
        raise S43Error("corrective-02 post-capture manifest is not frozen")
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
    if any(
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
        for value in commits.values()
    ):
        raise S43Error("corrective-02 post-capture commit binding is invalid")

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

    implementation = manifest.get("post_capture_implementation")
    if not isinstance(implementation, list):
        raise S43Error("post-capture implementation bindings must be a list")
    paths = {
        item.get("path") for item in implementation if isinstance(item, dict)
    }
    if paths != REQUIRED_IMPLEMENTATION_PATHS or len(implementation) != len(paths):
        raise S43Error(
            "post-capture implementation bindings are incomplete or duplicated"
        )
    for number, binding in enumerate(implementation):
        _require_file_binding(
            binding, repo_root=repo_root, label=f"post_capture_implementation[{number}]"
        )

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
