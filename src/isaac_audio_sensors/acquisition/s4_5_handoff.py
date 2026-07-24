"""Additive, fail-closed S4.5 active-profile handoff and replay contract."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("configs/s4_5_active_handoff.v1.json")
SPEC_PATH = Path("docs/development/specs/s4_5_active_handoff.md")
CLOSEOUT_AMENDMENT_PATH = Path(
    "docs/development/closeouts/S4/s4_5_calibration_fit_amendment_01.md"
)
AUTHORITATIVE_CLOSEOUT_PATH = Path(
    "docs/development/closeouts/S4/s4_5_calibration_fit.md"
)
MODULE_PATH = Path("src/isaac_audio_sensors/acquisition/s4_5_handoff.py")
RUNNER_PATH = Path("scripts/run_s4_5_handoff.py")
VALIDATOR_PATH = Path("scripts/validate_s4_5_handoff.py")
REPLAY_PATH = Path("scripts/replay_s4_5_handoff.py")
TEST_PATH = Path("tests/test_s4_5_handoff.py")
OUTPUT_PATH = Path("outputs/isaac_audio_sensors/S4/S4.5_handoff_01")
ACTIVE_POINTER_PATH = Path("outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json")
TOOL_VERSION = "ias_s4_5_handoff/1.0.0"
EXACT_REPLAY_COMMAND = (
    "python3 scripts/replay_s4_5_handoff.py "
    "--canonical outputs/isaac_audio_sensors/S4/S4.5_handoff_01"
)
REQUIRED_FILES = frozenset(
    {
        "SHA256SUMS",
        "active_handoff.v1.json",
        "closeout_amendment.v1.json",
        "evidence_index.v1.json",
        "provenance.v1.json",
        "reproduction.v1.json",
    }
)
SOURCE_BOUND_FILES = (
    CONTRACT_PATH,
    SPEC_PATH,
    CLOSEOUT_AMENDMENT_PATH,
    MODULE_PATH,
    RUNNER_PATH,
    VALIDATOR_PATH,
    REPLAY_PATH,
    TEST_PATH,
    Path("docs/schemas/audio_calibration_profile.v1.schema.json"),
    Path("src/isaac_audio_sensors/core/calibration_profile.py"),
    Path("configs/s4_5_corrective_01.v1.json"),
    Path("configs/s4_5_corrective_01_package_location_amendment.v1.json"),
    Path("configs/s4_5_corrective_01_profile_frame_amendment.v1.json"),
    Path("docs/development/specs/s4_5_corrective_01.md"),
    Path("src/isaac_audio_sensors/acquisition/s4_5_corrective.py"),
    Path("scripts/run_s4_5_corrective.py"),
    Path("scripts/validate_s4_5_corrective.py"),
    Path("tests/test_s4_5_corrective.py"),
)
ROUTING_MARKER = (
    "<!-- S4.5_ACTIVE_HANDOFF_AUTHORITY: "
    "outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json -->"
)
ROUTING_TEXT = "\n".join(
    (
        "## Authoritative active-profile routing amendment",
        "",
        ROUTING_MARKER,
        "",
        "The historical closeout below is preserved, but its v1 profile routing is",
        "scientifically superseded. The authoritative S4.5 closeout is",
        "`docs/development/closeouts/S4/s4_5_calibration_fit_amendment_01.md`.",
        "The only S4.6 input authorized by S4.5 is the v2 profile together with the",
        "active handoff resolved through",
        "`outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json`. S4.6 has not",
        "started.",
        "",
    )
)

_EXPECTED_MAPPING = [
    {"channel_id": "ch0", "position_m": [-0.033, -0.033, 0.0]},
    {"channel_id": "ch1", "position_m": [-0.033, 0.033, 0.0]},
    {"channel_id": "ch2", "position_m": [0.033, 0.033, 0.0]},
    {"channel_id": "ch3", "position_m": [0.033, -0.033, 0.0]},
]
_EXPECTED_SCALARS = (
    ("relative_gain_db.ch1", -1.6020864972841506),
    ("polarity.ch1", 1.0),
    ("relative_gain_db.ch2", -1.2795753710282032),
    ("polarity.ch2", 1.0),
    ("relative_gain_db.ch3", -1.2135862725210074),
    ("polarity.ch3", 1.0),
)


class S45HandoffError(RuntimeError):
    """A fail-closed active handoff, provenance, or replay error."""


def load_json(path: Path, *, label: str = "JSON") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S45HandoffError(f"{label} is unreadable or malformed: {path}") from exc
    if not isinstance(value, dict):
        raise S45HandoffError(f"{label} must be an object: {path}")
    return value


def pretty_json(value: Any) -> str:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _verify_binding(repo_root: Path, path_value: Any, digest: Any, label: str) -> None:
    if not isinstance(path_value, str) or not re.fullmatch(
        r"[0-9a-f]{64}", str(digest)
    ):
        raise S45HandoffError(f"{label} binding is malformed")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise S45HandoffError(f"{label} binding path is unsafe")
    path = repo_root / relative
    if not path.is_file() or sha256_file(path) != digest:
        raise S45HandoffError(f"{label} binding changed")


def source_commit_is_valid(repo_root: Path, source_commit: str) -> None:
    """Require one ancestor commit to bind every replay source/input file."""

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise S45HandoffError("source commit must be a full lowercase Git hash")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0 or ancestor.returncode != 0:
        raise S45HandoffError("source commit is absent or not an ancestor of HEAD")
    for relative in SOURCE_BOUND_FILES:
        working = repo_root / relative
        blob = subprocess.run(
            ["git", "show", f"{source_commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            not working.is_file()
            or blob.returncode != 0
            or hashlib.sha256(blob.stdout).hexdigest() != sha256_file(working)
        ):
            raise S45HandoffError(
                f"source commit does not bind exact replay input {relative}"
            )


def validate_package_location_amendment_payload(payload: Mapping[str, Any]) -> None:
    expected = {
        "schema": "ias.s4_5.corrective_package_location_amendment.v1",
        "package_root": "outputs/isaac_audio_sensors/S4/S4.5_corrective_01",
        "scientific_binding_changed": False,
        "scientific_thresholds_changed": False,
        "selected_hypothesis_changed": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise S45HandoffError(f"package-location amendment changed {key}")


def load_contract(repo_root: Path) -> dict[str, Any]:
    contract = load_json(repo_root / CONTRACT_PATH, label="S4.5 handoff contract")
    if contract.get("schema") != "ias.s4_5.active_handoff_contract.v1":
        raise S45HandoffError("active handoff contract schema changed")
    if contract.get("status") != "frozen":
        raise S45HandoffError("active handoff contract is not frozen")
    active = contract.get("active_profile")
    if not isinstance(active, Mapping):
        raise S45HandoffError("active profile contract is missing")
    for key, expected in {
        "path": (
            "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/"
            "calibration_profile.v2.json"
        ),
        "sha256": "944dda1df3a2de720ab86a3f07f0ea545aa9abca676a003423b29221ca0d47c8",
        "profile_id": "respeaker_xvf3800_s4_5_functional_corrective_01",
        "profile_version": "v2",
        "device_id": "respeaker_xvf3800_114993701261100454",
        "array_id": "xvf3800_array",
        "sample_rate_hz": 16000,
        "channel_order": ["ch0", "ch1", "ch2", "ch3"],
        "array_frame": "xvf3800_array_corrective_01",
        "source_frame": "F_project",
    }.items():
        if active.get(key) != expected:
            raise S45HandoffError(f"active profile contract changed {key}")
    _verify_binding(repo_root, active["path"], active["sha256"], "active profile")
    historical = contract.get("historical_profile")
    if not isinstance(historical, Mapping):
        raise S45HandoffError("historical profile record is missing")
    if historical.get("active_for_s4_6") is not False:
        raise S45HandoffError("historical v1 profile became active")
    _verify_binding(
        repo_root, historical.get("path"), historical.get("sha256"), "historical v1"
    )
    evidence = contract.get("corrective_evidence")
    if not isinstance(evidence, Mapping):
        raise S45HandoffError("corrective evidence bindings are missing")
    for prefix in (
        "evidence_index",
        "package_checksum",
        "parameter_decisions",
        "selected_binding_source",
    ):
        _verify_binding(
            repo_root,
            evidence.get(f"{prefix}_path"),
            evidence.get(f"{prefix}_sha256"),
            prefix,
        )
    amendment = contract.get("package_location_amendment")
    if not isinstance(amendment, Mapping):
        raise S45HandoffError("package-location amendment binding is missing")
    _verify_binding(
        repo_root, amendment.get("path"), amendment.get("sha256"), "relocation"
    )
    validate_package_location_amendment_payload(
        load_json(repo_root / str(amendment["path"]), label="relocation amendment")
    )
    binding = contract.get("functional_channel_position_association")
    if not isinstance(binding, Mapping):
        raise S45HandoffError("functional association is missing")
    expected_binding = {
        "association_kind": "retained_functional_channel_position_association",
        "evidence_status": "supported_fitted_functional_evidence",
        "frame": "F_project",
        "geometry_measurement_status": "nominal_not_measured",
        "mapping": _EXPECTED_MAPPING,
        "not_measured_geometry": True,
        "not_mirrored_f_project": True,
        "not_physically_traced_wiring": True,
        "not_scalar_bearing_correction": True,
        "selected_hypothesis_id": "H2_x_reflection_front_back_position_binding",
        "selection_partition": "fit_a",
        "validation_partition": "fit_b",
    }
    if dict(binding) != expected_binding:
        raise S45HandoffError("functional association semantics changed")
    counts = contract.get("retained_count_semantics")
    expected_counts = {
        "legacy_profile_metric_name": "retained_parameter_count",
        "legacy_profile_metric_status": "superseded_ambiguous_total_do_not_apply",
        "legacy_profile_metric_value": 7,
        "retained_functional_association_count": 1,
        "retained_scalar_profile_parameter_count": 6,
        "retained_scientific_component_count": 7,
    }
    if counts != expected_counts:
        raise S45HandoffError("retained-count semantics changed")
    return contract


def _fit_metric(profile: Mapping[str, Any], name: str) -> Any:
    rows = profile.get("fit_metrics")
    if not isinstance(rows, list):
        raise S45HandoffError("profile fit_metrics is malformed")
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        raise S45HandoffError(f"profile metric {name!r} is absent or duplicated")
    return matches[0].get("value")


def validate_handoff_payload(
    profile: Mapping[str, Any], handoff: Mapping[str, Any]
) -> None:
    """Validate the machine contract without applying any S4.6 behavior."""

    if handoff.get("schema") != "ias.s4_5.active_profile_handoff.v1":
        raise S45HandoffError("handoff schema changed")
    if handoff.get("status") != "active":
        raise S45HandoffError("handoff status is not active")
    active = handoff.get("active_profile")
    if not isinstance(active, Mapping):
        raise S45HandoffError("handoff active profile is missing")
    if active.get("profile_version") != "v2":
        raise S45HandoffError("v1 is not an active S4.6 input")
    for key in (
        "profile_id",
        "profile_version",
        "device_id",
        "device_model",
        "array_id",
        "sample_rate_hz",
        "channel_order",
        "array_frame",
        "source_frame",
    ):
        if active.get(key) != profile.get(key):
            raise S45HandoffError(f"profile/handoff identity mismatch: {key}")
    geometry = profile.get("microphone_geometry")
    if not isinstance(geometry, list) or len(geometry) != 4:
        raise S45HandoffError("profile microphone geometry is malformed")
    if any(row.get("status") != "nominal_not_measured" for row in geometry):
        raise S45HandoffError("microphone geometry no longer remains nominal")
    if any(row.get("uncertainty_m") is not None for row in geometry):
        raise S45HandoffError("nominal microphone geometry acquired uncertainty")
    binding = handoff.get("functional_channel_position_association")
    if not isinstance(binding, Mapping):
        raise S45HandoffError("functional binding is absent")
    if binding.get("evidence_status") != "supported_fitted_functional_evidence":
        raise S45HandoffError("functional binding evidence status is incompatible")
    if binding.get("geometry_measurement_status") != "nominal_not_measured":
        raise S45HandoffError("functional binding was mislabeled as measured geometry")
    if binding.get("mapping") != _EXPECTED_MAPPING:
        raise S45HandoffError("functional channel-position mapping changed")
    if binding.get("frame") != "F_project":
        raise S45HandoffError("functional binding frame changed")
    for flag in (
        "not_measured_geometry",
        "not_mirrored_f_project",
        "not_physically_traced_wiring",
        "not_scalar_bearing_correction",
    ):
        if binding.get(flag) is not True:
            raise S45HandoffError(f"functional binding guard changed: {flag}")
    fitted = profile.get("fitted_model_parameters")
    if not isinstance(fitted, list) or len(fitted) != 6:
        raise S45HandoffError("profile does not serialize six scalar parameters")
    actual_scalars = tuple(
        (row.get("name"), row.get("estimate", {}).get("value")) for row in fitted
    )
    if actual_scalars != _EXPECTED_SCALARS:
        raise S45HandoffError("existing scientific scalar values changed")
    counts = handoff.get("retained_count_semantics")
    if not isinstance(counts, Mapping):
        raise S45HandoffError("retained-count semantics are absent")
    if (
        counts.get("retained_scalar_profile_parameter_count") != len(fitted)
        or counts.get("retained_functional_association_count") != 1
        or counts.get("retained_scientific_component_count") != len(fitted) + 1
        or counts.get("legacy_profile_metric_status")
        != "superseded_ambiguous_total_do_not_apply"
        or _fit_metric(profile, "retained_parameter_count") != 7.0
    ):
        raise S45HandoffError("retained-count semantics are inconsistent")
    guards = handoff.get("application_guards")
    if not isinstance(guards, Mapping) or guards.get("match_policy") != (
        "exact_profile_hash_device_array_sample_rate_channel_order_frames_environment"
    ):
        raise S45HandoffError("application guards are absent or weakened")
    if handoff.get("holdout_observations_accessed") != 0:
        raise S45HandoffError("handoff claims holdout access")
    if handoff.get("later_phases_started") != []:
        raise S45HandoffError("handoff claims later-phase work")


def _handoff_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    active = dict(contract["active_profile"])
    active["active_profile_count"] = 1
    return {
        "schema": "ias.s4_5.active_profile_handoff.v1",
        "status": "active",
        "active_profile": active,
        "application_guards": {
            "match_policy": (
                "exact_profile_hash_device_array_sample_rate_channel_order_"
                "frames_environment"
            ),
            "environment_tags": contract["applicability"]["environment_tags"],
            "mismatch_disposition": "reject_before_partial_use",
        },
        "corrective_evidence": contract["corrective_evidence"],
        "functional_channel_position_association": contract[
            "functional_channel_position_association"
        ],
        "historical_profile": contract["historical_profile"],
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
        "nominal_but_not_measured": [
            "microphone_geometry.*.position_m",
            "microphone_geometry.*.uncertainty_m",
            "channels.ch0.reference_gain_delay_polarity_convention",
        ],
        "retained_count_semantics": contract["retained_count_semantics"],
        "supported_for_later_application": contract["supported_for_later_application"],
        "unsupported_or_omitted": contract["unsupported_or_omitted"],
    }


def _closeout_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_5.closeout_amendment.v1",
        "status": "passed",
        "authoritative_closeout_path": CLOSEOUT_AMENDMENT_PATH.as_posix(),
        "active_pointer_path": ACTIVE_POINTER_PATH.as_posix(),
        "active_profile_path": contract["active_profile"]["path"],
        "active_handoff_path": (OUTPUT_PATH / "active_handoff.v1.json").as_posix(),
        "historical_v1_disposition": (
            "immutable_historical_scientifically_superseded_not_active_for_s4_6"
        ),
        "functional_binding_retained": True,
        "geometry_status": "nominal_not_measured",
        "omitted_or_later_phase_fields": contract["unsupported_or_omitted"],
        "s4_6_started": False,
        "s4_squadbot_ready": False,
        "s4_readiness_requires": ["S4.8", "S4.9"],
        "holdout_observations_accessed": 0,
        "push_performed": False,
    }


def evidence_records(output: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"SHA256SUMS", "evidence_index.v1.json"}
    ]


def checksum_text(output: Path) -> str:
    names = sorted(
        path.name
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    return "".join(f"{sha256_file(output / name)}  {name}\n" for name in names)


def build_handoff_package(
    *, repo_root: Path, output: Path, source_commit: str
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    source_commit_is_valid(repo_root, source_commit)
    contract = load_contract(repo_root)
    if output.exists() and any(output.iterdir()):
        raise S45HandoffError(f"handoff output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    profile = load_json(
        repo_root / contract["active_profile"]["path"], label="active v2 profile"
    )
    handoff = _handoff_payload(contract)
    validate_handoff_payload(profile, handoff)
    closeout = _closeout_payload(contract)
    source_records = [
        {"path": path.as_posix(), "sha256": sha256_file(repo_root / path)}
        for path in SOURCE_BOUND_FILES
    ]
    provenance = {
        "schema": "ias.s4_5.active_handoff_provenance.v1",
        "status": "passed",
        "source_commit": source_commit,
        "tool_version": TOOL_VERSION,
        "active_package_path": OUTPUT_PATH.as_posix(),
        "active_profile": contract["active_profile"],
        "active_profile_handoff_sha256": hashlib.sha256(
            pretty_json(handoff).encode()
        ).hexdigest(),
        "closeout_amendment": {
            "path": CLOSEOUT_AMENDMENT_PATH.as_posix(),
            "sha256": sha256_file(repo_root / CLOSEOUT_AMENDMENT_PATH),
            "machine_record_sha256": hashlib.sha256(
                pretty_json(closeout).encode()
            ).hexdigest(),
        },
        "package_location_amendment": contract["package_location_amendment"],
        "immutable_corrective_package": contract["corrective_evidence"],
        "immutable_original_profile": contract["historical_profile"],
        "implementation_and_contract_sources": source_records,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
        "push_performed": False,
    }
    reproduction = {
        "schema": "ias.s4_5.active_handoff_reproduction.v1",
        "status": "passed",
        "source_commit": source_commit,
        "command": EXACT_REPLAY_COMMAND,
        "clean_checkout_supported": True,
        "requires_historical_detached_checkout": False,
        "requires_holdout_or_raw_media": False,
        "comparison": "byte_for_byte_complete_package",
        "deterministic": True,
    }
    files = {
        "active_handoff.v1.json": handoff,
        "closeout_amendment.v1.json": closeout,
        "provenance.v1.json": provenance,
        "reproduction.v1.json": reproduction,
    }
    for name, value in files.items():
        _write_json(output / name, value)
    index = {
        "schema": "ias.s4_5.active_handoff_evidence_index.v1",
        "status": "passed",
        "source_commit": source_commit,
        "tool_version": TOOL_VERSION,
        "active_profile_path": contract["active_profile"]["path"],
        "active_profile_sha256": contract["active_profile"]["sha256"],
        "active_handoff_path": (OUTPUT_PATH / "active_handoff.v1.json").as_posix(),
        "records": evidence_records(output),
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    _write_json(output / "evidence_index.v1.json", index)
    (output / "SHA256SUMS").write_text(checksum_text(output), encoding="utf-8")
    return {
        "status": "passed",
        "output": str(output),
        "source_commit": source_commit,
        "file_count": len(REQUIRED_FILES),
    }


def active_pointer_payload(repo_root: Path, package: Path) -> dict[str, Any]:
    contract = load_contract(repo_root)
    handoff_path = package / "active_handoff.v1.json"
    return {
        "schema": "ias.s4_5.active_profile_pointer.v1",
        "status": "active",
        "active_profile_count": 1,
        "active_profile_path": contract["active_profile"]["path"],
        "active_profile_sha256": contract["active_profile"]["sha256"],
        "active_profile_id": contract["active_profile"]["profile_id"],
        "active_profile_version": contract["active_profile"]["profile_version"],
        "active_handoff_path": (OUTPUT_PATH / "active_handoff.v1.json").as_posix(),
        "active_handoff_sha256": sha256_file(handoff_path),
        "historical_v1_active": False,
        "s4_6_input_policy": "profile_and_handoff_required_together_fail_closed",
    }


def write_active_pointer(repo_root: Path, package: Path) -> Path:
    path = repo_root / ACTIVE_POINTER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, active_pointer_payload(repo_root, package))
    return path


def validate_closeout_routing_text(text: str) -> None:
    if text.count(ROUTING_MARKER) != 1:
        raise S45HandoffError(
            "authoritative closeout routing marker is absent/duplicated"
        )
    required = (
        CLOSEOUT_AMENDMENT_PATH.as_posix(),
        ACTIVE_POINTER_PATH.as_posix(),
        "only S4.6 input authorized by S4.5",
        "S4.6 has not",
    )
    if any(value not in text for value in required):
        raise S45HandoffError("authoritative closeout routing changed")


def route_authoritative_closeout(repo_root: Path) -> None:
    path = repo_root / AUTHORITATIVE_CLOSEOUT_PATH
    text = path.read_text(encoding="utf-8")
    if ROUTING_MARKER in text:
        validate_closeout_routing_text(text)
        return
    header = text.splitlines(keepends=True)[0]
    remainder = text[len(header) :]
    path.write_text(header + "\n" + ROUTING_TEXT + "\n" + remainder, encoding="utf-8")


def detect_later_phase_artifacts(repo_root: Path) -> list[str]:
    found: list[str] = []
    for phase in ("S4.6", "S4.7", "S4.8", "S4.9"):
        path = repo_root / "outputs/isaac_audio_sensors/S4" / phase
        if path.exists():
            found.append(path.relative_to(repo_root).as_posix())
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if tracked.returncode == 0:
        pattern = re.compile(r"(?:^|[/_.-])s?4[._-]?[6789](?:[/_.-]|$)", re.I)
        for path in tracked.stdout.splitlines():
            if pattern.search(path) and path not in found:
                found.append(path)
    return sorted(found)


def refresh_package_integrity(output: Path) -> None:
    index_path = output / "evidence_index.v1.json"
    index = load_json(index_path, label="handoff evidence index")
    index["records"] = evidence_records(output)
    _write_json(index_path, index)
    (output / "SHA256SUMS").write_text(checksum_text(output), encoding="utf-8")


def _checksum_issues(output: Path) -> list[str]:
    manifest = output / "SHA256SUMS"
    if not manifest.is_file():
        return ["SHA256SUMS missing"]
    issues: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            digest, name = line.split("  ", 1)
        except ValueError:
            issues.append("malformed checksum line")
            continue
        path = output / name
        if not path.is_file() or sha256_file(path) != digest:
            issues.append(f"checksum mismatch: {name}")
    return issues


def _expected_package(repo_root: Path, source_commit: str) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="ias-s4-5-handoff-validate-") as tmp:
        output = Path(tmp) / "package"
        build_handoff_package(
            repo_root=repo_root, output=output, source_commit=source_commit
        )
        return {path.name: path.read_bytes() for path in output.iterdir()}


def active_surface_paths(repo_root: Path, output: Path) -> list[str]:
    paths = [
        *(path.relative_to(repo_root).as_posix() for path in output.iterdir()),
        ACTIVE_POINTER_PATH.as_posix(),
        AUTHORITATIVE_CLOSEOUT_PATH.as_posix(),
        *[path.as_posix() for path in SOURCE_BOUND_FILES],
        "outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json",
        "outputs/isaac_audio_sensors/S4/S4.5/SHA256SUMS",
        "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json",
        "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/evidence_index.json",
        "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/SHA256SUMS",
        "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/parameter_decisions.json",
        (
            "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/"
            "physical_hypothesis_comparison.json"
        ),
    ]
    return sorted(set(paths))


def validate_handoff_package(
    repo_root: Path,
    output: Path,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    issues: list[str] = []
    present = {path.name for path in output.iterdir()} if output.is_dir() else set()
    if present != REQUIRED_FILES:
        issues.append(
            f"handoff file set mismatch: missing={sorted(REQUIRED_FILES - present)}, "
            f"extra={sorted(present - REQUIRED_FILES)}"
        )
    issues.extend(_checksum_issues(output) if output.is_dir() else ["output missing"])
    source_commit = ""
    try:
        provenance = load_json(output / "provenance.v1.json", label="provenance")
        source_commit = str(provenance.get("source_commit", ""))
        expected = _expected_package(repo_root, source_commit)
        for name in sorted(REQUIRED_FILES):
            path = output / name
            if not path.is_file() or path.read_bytes() != expected.get(name):
                issues.append(f"semantic regeneration mismatch: {name}")
    except S45HandoffError as exc:
        issues.append(f"semantic regeneration failed: {exc}")
    try:
        contract = load_contract(repo_root)
        profile = load_json(
            repo_root / contract["active_profile"]["path"], label="active profile"
        )
        handoff = load_json(output / "active_handoff.v1.json", label="active handoff")
        validate_handoff_payload(profile, handoff)
        pointer = load_json(repo_root / ACTIVE_POINTER_PATH, label="active pointer")
        if pointer != active_pointer_payload(repo_root, output):
            raise S45HandoffError("active pointer does not resolve exact v2 handoff")
        validate_closeout_routing_text(
            (repo_root / AUTHORITATIVE_CLOSEOUT_PATH).read_text(encoding="utf-8")
        )
    except (OSError, S45HandoffError) as exc:
        issues.append(f"active handoff surface failed: {exc}")
    later = detect_later_phase_artifacts(repo_root)
    if later:
        issues.append(f"S4.6-S4.9 artifacts present: {later}")
    surface = active_surface_paths(repo_root, output) if output.is_dir() else []
    if require_tracked and surface:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *surface],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if tracked.returncode != 0:
            issues.append("complete active handoff surface is not tracked")
    if require_committed and surface:
        changed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *surface],
            cwd=repo_root,
            check=False,
        )
        if changed.returncode != 0:
            issues.append("complete active handoff surface differs from HEAD")
    return {
        "schema": "ias.s4_5.active_handoff_validation.v1",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "active_profile_count": 1 if not issues else 0,
        "active_profile_path": (
            "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/"
            "calibration_profile.v2.json"
        ),
        "active_handoff_path": (
            "outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json"
        ),
        "source_commit": source_commit,
        "semantic_regeneration": not any(
            "semantic regeneration" in issue for issue in issues
        ),
        "complete_surface_file_count": len(surface),
        "holdout_observations_accessed": 0,
        "later_phase_artifacts": later,
        "require_tracked": require_tracked,
        "require_committed": require_committed,
    }
