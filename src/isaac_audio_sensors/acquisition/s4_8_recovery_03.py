"""Frozen S4.8 amendment-03 release candidate and engineering replay."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_evaluator as historical_evaluator,
)
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_execution as historical_execution,
)
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_terminalizer as historical_terminalizer,
)
from isaac_audio_sensors.acquisition.s4_8_recovery_02_profiles import (
    is_input_contract_rejected,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as c2

POLICY_PATH = Path("configs/s4_8_reference_tdoa_boundary_policy.v1.json")
POLICY_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_reference_tdoa_boundary_policy.v1.schema.json"
)
RELEASE_CANDIDATE_PATH = Path("configs/s4_8_recovery_amendment_03.v1.json")
RELEASE_CANDIDATE_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_amendment_03.v1.schema.json"
)
TERMINALIZATION_CONTRACT_PATH = Path(
    "configs/s4_8_recovery_amendment_02_terminalization.v1.json"
)

POLICY_ID = "s4_8_geometric_reference_tdoa_one_ulp_v1"
RELEASE_CANDIDATE_ID = "s4_8_recovery_amendment_03_rc1"
TOOL_VERSION = "ias_s4_8_recovery_03/1.0.0"
DERIVED_INPUT_SCHEMA = "ias.s4_8.recovery_03.derived_evaluation_input.v1"
VALIDATOR_IDENTITY = "ias_s4_8_recovery_03_validator/1.0.0"
TERMINAL_JOURNAL_RECORD_COUNT = 5845

FULL_EVALUATED_PROFILE = "recovery_03_full_evaluated_evidence.v1"
INPUT_CONTRACT_REJECTION_PROFILE = (
    "recovery_03_terminal_input_contract_rejection.v1"
)
PRE_EVALUATION_FAILURE_PROFILE = (
    "recovery_03_pre_evaluation_terminal_failure.v1"
)
ENGINEERING_REPLAY_PROFILE = "recovery_03_engineering_replay_non_official.v1"
REFERENCE_ORIGIN = "internally_calculated_geometric_reference"
EVALUATION_SCHEMA = "ias.s4_8.recovery_02.criteria_evaluation_result.v2"
EVALUATION_FIELDS = frozenset(
    {
        "categorical_take_results",
        "comparison_classifications",
        "config_identity",
        "criteria",
        "evaluation_error",
        "evaluation_invocation_count",
        "failed_gating_criteria",
        "holdout_observations_accessed_by_evaluator",
        "identity_summary",
        "readiness_passed",
        "schema",
        "status",
    }
)


class S48Recovery03Error(RuntimeError):
    """Raised when the amendment-03 release-candidate boundary fails closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S48Recovery03Error(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S48Recovery03Error(f"{path} must contain one JSON object")
    return value


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "." in candidate.parts
    ):
        raise S48Recovery03Error(f"unsafe release-candidate path: {value!r}")
    return Path(*candidate.parts)


def _repo_file(repo_root: Path, value: str | Path) -> Path:
    relative = _safe_relative(Path(value).as_posix())
    return repo_root.resolve() / relative


def _validate_schema(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    label: str,
) -> None:
    try:
        jsonschema.validate(dict(payload), dict(schema))
    except jsonschema.ValidationError as exc:
        raise S48Recovery03Error(f"{label} schema mismatch: {exc.message}") from exc


def _require_file_hash(repo_root: Path, binding: Mapping[str, Any]) -> None:
    path = _repo_file(repo_root, str(binding["path"]))
    if not path.is_file() or _sha256_file(path) != binding.get("sha256"):
        raise S48Recovery03Error(f"hash binding mismatch: {binding['path']}")


def load_policy(repo_root: Path) -> dict[str, Any]:
    """Load and authenticate the one-ULP geometric-reference policy."""

    root = repo_root.resolve()
    policy = _load_json(root / POLICY_PATH)
    schema = _load_json(root / POLICY_SCHEMA_PATH)
    _validate_schema(policy, schema, label="S4.8 reference TDOA policy")
    sources = policy["frozen_sources"]
    _require_file_hash(root, sources["tdoa_domain"])
    geometry = sources["geometry"]
    _require_file_hash(
        root,
        {
            "path": geometry["profile_application_path"],
            "sha256": geometry["profile_application_sha256"],
        },
    )
    formula = sources["reference_formula"]
    _require_file_hash(
        root,
        {
            "path": formula["source_path"],
            "sha256": formula["source_sha256"],
        },
    )
    config = c2.load_corrective_config(root)
    domain = config.get("physical_domains", {}).get("tdoa_us")
    if (
        not isinstance(domain, Mapping)
        or not isinstance(domain.get("minimum"), (int, float))
        or isinstance(domain.get("minimum"), bool)
        or not isinstance(domain.get("maximum"), (int, float))
        or isinstance(domain.get("maximum"), bool)
    ):
        raise S48Recovery03Error("frozen TDOA domain is unavailable")
    return policy


def load_release_candidate(repo_root: Path) -> dict[str, Any]:
    """Load and authenticate the additive amendment-03 preregistration."""

    root = repo_root.resolve()
    release_candidate = _load_json(root / RELEASE_CANDIDATE_PATH)
    schema = _load_json(root / RELEASE_CANDIDATE_SCHEMA_PATH)
    _validate_schema(
        release_candidate,
        schema,
        label="S4.8 recovery amendment-03 release candidate",
    )
    policy_binding = release_candidate["reference_policy"]
    _require_file_hash(root, policy_binding)
    _require_file_hash(
        root,
        {
            "path": policy_binding["schema_path"],
            "sha256": policy_binding["schema_sha256"],
        },
    )
    policy = load_policy(root)
    if policy.get("policy_id") != policy_binding["policy_id"]:
        raise S48Recovery03Error("release-candidate reference policy mismatch")
    inherited = release_candidate["inherited_protocol"]
    _require_file_hash(
        root,
        {
            "path": inherited["amendment_path"],
            "sha256": inherited["amendment_sha256"],
        },
    )
    _require_file_hash(
        root,
        {
            "path": inherited["evaluator_binding_path"],
            "sha256": inherited["evaluator_binding_sha256"],
        },
    )
    return release_candidate


def _tdoa_domain(repo_root: Path) -> tuple[float, float]:
    load_policy(repo_root)
    domain = c2.load_corrective_config(repo_root.resolve())["physical_domains"][
        "tdoa_us"
    ]
    minimum = float(domain["minimum"])
    maximum = float(domain["maximum"])
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum >= maximum
    ):
        raise S48Recovery03Error("frozen TDOA domain is invalid")
    return minimum, maximum


def _canonicalize_take(
    take: dict[str, Any],
    *,
    minimum_us: float,
    maximum_us: float,
) -> int:
    records = take.get("tdoa")
    if not isinstance(records, list):
        raise S48Recovery03Error("TDOA records must be a list")
    before: list[tuple[dict[str, Any], Any, Any, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise S48Recovery03Error("TDOA record must be an object")
        before.append(
            (
                record,
                record.get("reference_tdoa_us"),
                record.get("tdoa_us"),
                record.get("absolute_error_us"),
            )
        )
    historical_execution._canonicalize_reference_tdoa_boundaries(
        take,
        minimum_us=minimum_us,
        maximum_us=maximum_us,
    )
    changed = 0
    for record, reference_before, measured_before, error_before in before:
        if record.get("tdoa_us") != measured_before:
            raise S48Recovery03Error("measured TDOA was modified")
        if record.get("reference_tdoa_us") != reference_before:
            changed += 1
        elif record.get("absolute_error_us") != error_before:
            raise S48Recovery03Error(
                "absolute error changed without reference canonicalization"
            )
    return changed


def canonicalize_geometric_reference_tdoa(
    take: dict[str, Any],
    *,
    repo_root: Path,
    reference_origin: str,
) -> int:
    """Canonicalize only trusted geometric references exactly one ULP out."""

    if reference_origin != REFERENCE_ORIGIN:
        raise S48Recovery03Error("reference origin is not geometric and trusted")
    minimum, maximum = _tdoa_domain(repo_root.resolve())
    return _canonicalize_take(
        take,
        minimum_us=minimum,
        maximum_us=maximum,
    )


def apply_reference_policy(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    reference_origin: str,
) -> int:
    """Apply the frozen policy to a producer-owned derived payload."""

    if reference_origin != REFERENCE_ORIGIN:
        raise S48Recovery03Error("reference origin is not geometric and trusted")
    minimum, maximum = _tdoa_domain(repo_root.resolve())
    takes = payload.get("takes")
    if not isinstance(takes, list):
        raise S48Recovery03Error("derived payload takes must be a list")
    changed = 0
    for take in takes:
        if not isinstance(take, dict):
            raise S48Recovery03Error("derived payload take must be an object")
        changed += _canonicalize_take(
            take,
            minimum_us=minimum,
            maximum_us=maximum,
        )
    return changed


def _full_evaluation_is_consistent(evaluation: Mapping[str, Any]) -> bool:
    if (
        set(evaluation) != EVALUATION_FIELDS
        or evaluation.get("schema") != EVALUATION_SCHEMA
        or not isinstance(evaluation.get("config_identity"), Mapping)
        or not isinstance(evaluation.get("identity_summary"), Mapping)
    ):
        return False
    criteria = evaluation.get("criteria")
    if not isinstance(criteria, list):
        return False
    gating = [
        item
        for item in criteria
        if isinstance(item, Mapping) and item.get("gating") is True
    ]
    if len(gating) != 17 or len(gating) == 0:
        return False
    failed = [
        item.get("criterion_id")
        for item in gating
        if item.get("passed") is not True
    ]
    readiness = not failed
    return (
        evaluation.get("evaluation_error") is None
        and evaluation.get("failed_gating_criteria") == failed
        and evaluation.get("readiness_passed") is readiness
        and evaluation.get("status") == ("passed" if readiness else "failed")
        and isinstance(evaluation.get("comparison_classifications"), list)
        and isinstance(evaluation.get("categorical_take_results"), list)
        and evaluation.get("holdout_observations_accessed_by_evaluator") == 0
    )


def classify_package_profile(derived: Mapping[str, Any]) -> str:
    """Return the only package profile valid for one derived terminal state."""

    evaluation = derived.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise S48Recovery03Error("derived evaluation is unavailable")
    state = derived.get("evaluation_state")
    invocation_count = evaluation.get("evaluation_invocation_count", 0)
    run_failure = derived.get("run_failure")
    if state == "evaluation_completed":
        if invocation_count != 1 or run_failure is not None:
            raise S48Recovery03Error("completed evaluation state/count mismatch")
        if is_input_contract_rejected(evaluation):
            if (
                set(evaluation) != EVALUATION_FIELDS
                or evaluation.get("schema") != EVALUATION_SCHEMA
                or not isinstance(evaluation.get("config_identity"), Mapping)
            ):
                raise S48Recovery03Error(
                    "terminal input-contract rejection profile mismatch"
                )
            return INPUT_CONTRACT_REJECTION_PROFILE
        if not _full_evaluation_is_consistent(evaluation):
            raise S48Recovery03Error("full evaluated evidence profile mismatch")
        return FULL_EVALUATED_PROFILE
    if state == "not_evaluated":
        if (
            invocation_count != 0
            or not isinstance(run_failure, Mapping)
            or run_failure.get("terminal") is not True
            or run_failure.get("automatic_retry_forbidden") is not True
            or evaluation.get("status") != "not_evaluated"
            or evaluation.get("readiness_passed") is not False
            or evaluation.get("failed_gating_criteria") != []
            or evaluation.get("criteria") != []
            or evaluation.get("holdout_observations_accessed_by_evaluator") != 0
        ):
            raise S48Recovery03Error(
                "pre-evaluation terminal failure profile mismatch"
            )
        return PRE_EVALUATION_FAILURE_PROFILE
    raise S48Recovery03Error("evaluation state has no release-candidate profile")


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    shared = min(len(left_parts), len(right_parts))
    return left_parts[:shared] == right_parts[:shared]


def _snapshot_historical_state(
    repo_root: Path,
    release_candidate: Mapping[str, Any],
) -> dict[str, str]:
    root = repo_root.resolve()
    snapshot: dict[str, str] = {}
    historical = release_candidate["historical_amendment_02"]
    for binding in historical["protected_files"]:
        path = _repo_file(root, binding["path"])
        if not path.is_file():
            raise S48Recovery03Error(f"historical file is missing: {binding['path']}")
        snapshot[binding["path"]] = _sha256_file(path)
    package = historical["published_terminal_package"]
    package_root = _repo_file(root, package["root"])
    for name in package["files"]:
        path = package_root / name
        if not path.is_file():
            raise S48Recovery03Error(f"terminal package file is missing: {name}")
        snapshot[f"{package['root']}/{name}"] = _sha256_file(path)
    terminalization = _load_json(root / TERMINALIZATION_CONTRACT_PATH)
    for binding in terminalization.get("allowed_inputs", []):
        if not isinstance(binding, Mapping):
            raise S48Recovery03Error("terminalization input binding is invalid")
        path = _repo_file(root, str(binding["path"]))
        if not path.is_file():
            raise S48Recovery03Error(
                f"terminalization input is missing: {binding['path']}"
            )
        snapshot[str(binding["path"])] = _sha256_file(path)
    return dict(sorted(snapshot.items()))


def validate_release_candidate(repo_root: Path) -> dict[str, Any]:
    """Authenticate the RC without reading any raw observation."""

    root = repo_root.resolve()
    release_candidate = load_release_candidate(root)
    historical = release_candidate["historical_amendment_02"]
    snapshot = _snapshot_historical_state(root, release_candidate)
    expected = {
        binding["path"]: binding["sha256"]
        for binding in historical["protected_files"]
    }
    package = historical["published_terminal_package"]
    expected.update(
        {
            f"{package['root']}/{name}": sha256
            for name, sha256 in package["files"].items()
        }
    )
    terminalization = _load_json(root / TERMINALIZATION_CONTRACT_PATH)
    expected.update(
        {
            binding["path"]: binding["sha256"]
            for binding in terminalization["allowed_inputs"]
        }
    )
    mismatches = {
        path: {"expected": sha256, "actual": snapshot.get(path)}
        for path, sha256 in expected.items()
        if snapshot.get(path) != sha256
    }
    if mismatches:
        raise S48Recovery03Error(
            f"historical amendment-02 hash mismatch: {sorted(mismatches)}"
        )
    future = release_candidate["future_holdout"]
    future_paths = {
        key: _repo_file(root, future[key])
        for key in (
            "raw_observation_root",
            "evaluation_state_root",
            "official_output_root",
        )
    }
    present = {key: path.exists() for key, path in future_paths.items()}
    if any(present.values()):
        raise S48Recovery03Error("amendment-03 future namespace is not empty")
    disjoint = future["disjoint_from_observation_roots"]
    if any(
        _paths_overlap(future["raw_observation_root"], consumed)
        for consumed in disjoint
    ):
        raise S48Recovery03Error("future raw observation namespace overlaps history")
    replay = release_candidate["engineering_replay"]
    if not replay["output_root"].startswith(".local/s4_8/"):
        raise S48Recovery03Error("engineering replay output is not isolated")
    if _paths_overlap(replay["output_root"], future["official_output_root"]):
        raise S48Recovery03Error("engineering and official outputs overlap")
    return {
        "schema": "ias.s4_8.recovery_03.release_candidate_validation.v1",
        "status": "passed",
        "validator_identity": VALIDATOR_IDENTITY,
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "release_candidate_status": release_candidate["status"],
        "reference_policy_id": POLICY_ID,
        "historical_preservation_passed": True,
        "historical_snapshot_sha256": _canonical_sha256(snapshot),
        "future_holdout_id": future["holdout_id"],
        "future_namespaces_present": present,
        "engineering_replay_profile": replay["profile"],
        "engineering_replay_output": replay["output_root"],
        "ready_for_engineering_replay": True,
        "ready_for_new_holdout_collection": False,
        "official_evaluation_authorized": False,
        "raw_observations_read": False,
    }


def _authenticate_terminal_amendment_02_state(
    repo_root: Path,
    config: Mapping[str, Any],
) -> None:
    root = repo_root.resolve()
    validate_release_candidate(root)
    release_candidate = load_release_candidate(root)
    try:
        contract, *_schemas = historical_terminalizer._load_contract(root)
        snapshots = historical_terminalizer._snapshot_inputs(root, contract)
        historical_terminalizer._validate_scientific_state(
            contract,
            snapshots,
        )
        journal = historical_terminalizer._json_lines(
            snapshots["scientific_journal"].data,
            label=snapshots["scientific_journal"].relative_path,
        )
        expected_paths = {
            ("grant", "path"): snapshots["scientific_grant"].relative_path,
            ("grant", "ledger_path"): snapshots["scientific_ledger"].relative_path,
            ("evidence", "run_journal_path"): (
                snapshots["scientific_journal"].relative_path
            ),
            ("evidence", "derived_input_path"): (
                snapshots["derived_state"].relative_path
            ),
            ("evidence", "output_path"): contract["publication"]["output_path"],
        }
        if any(
            config.get(section, {}).get(field) != expected
            for (section, field), expected in expected_paths.items()
        ):
            raise S48Recovery03Error(
                "engineering replay amendment-02 path binding mismatch"
            )
        package_binding = release_candidate["historical_amendment_02"][
            "published_terminal_package"
        ]
        if package_binding["root"] != contract["publication"]["output_path"]:
            raise S48Recovery03Error(
                "engineering replay terminal package binding mismatch"
            )
    except historical_terminalizer.S48TerminalizationError as exc:
        raise S48Recovery03Error(
            f"terminal amendment-02 authentication failed: {exc}"
        ) from exc
    if len(journal) != TERMINAL_JOURNAL_RECORD_COUNT:
        raise S48Recovery03Error(
            "engineering replay terminal journal record count mismatch"
        )


@contextmanager
def _engineering_replay_opening_check(repo_root: Path) -> Iterator[None]:
    official_check = s4_8._require_consumed_ledger

    def authenticate_terminal_state(
        root: Path,
        config: Mapping[str, Any],
    ) -> None:
        _authenticate_terminal_amendment_02_state(root, config)

    s4_8._require_consumed_ledger = authenticate_terminal_state
    try:
        yield
    finally:
        s4_8._require_consumed_ledger = official_check


def _build_engineering_payload(
    repo_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = repo_root.resolve()
    lock_path = root / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    with (
        s4_8._exclusive_execution_lock(lock_path),
        historical_execution.execution_context(root),
        _engineering_replay_opening_check(root),
    ):
        return historical_execution.build_real_payload(root)


def _evaluate_engineering_payload(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    report = historical_evaluator.evaluate_payload(
        payload,
        repo_root=repo_root.resolve(),
    ).report()
    return {**report, "evaluation_invocation_count": 1}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(s4_8.pretty_json(dict(payload)), encoding="utf-8")


def _write_replay_output(
    destination: Path,
    *,
    derived: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    report: Mapping[str, Any],
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    files = {
        "derived_evaluation_input.v1.json": derived,
        "criteria_results.v1.json": evaluation,
        "engineering_replay_report.v1.json": report,
    }
    for name, payload in files.items():
        _write_json(destination / name, payload)
    manifest = "".join(
        f"{_sha256_file(destination / name)}  {name}\n" for name in sorted(files)
    )
    (destination / "SHA256SUMS").write_text(manifest, encoding="utf-8")
    return _sha256_file(destination / "SHA256SUMS")


def run_engineering_replay(repo_root: Path) -> dict[str, Any]:
    """Run the explicit non-official raw replay into its isolated namespace."""

    root = repo_root.resolve()
    validation = validate_release_candidate(root)
    release_candidate = load_release_candidate(root)
    replay = release_candidate["engineering_replay"]
    destination = _repo_file(root, replay["output_root"])
    if destination.exists():
        raise S48Recovery03Error("engineering replay output already exists")
    before = _snapshot_historical_state(root, release_candidate)
    payload, inventory = _build_engineering_payload(root)
    if (
        not isinstance(payload.get("takes"), list)
        or len(payload["takes"]) != replay["planned_take_count"]
        or len(inventory) != replay["planned_take_count"]
    ):
        raise S48Recovery03Error("engineering replay 37-take census mismatch")
    replay_payload = deepcopy(payload)
    canonicalized = apply_reference_policy(
        replay_payload,
        repo_root=root,
        reference_origin=REFERENCE_ORIGIN,
    )
    evaluation = _evaluate_engineering_payload(replay_payload, repo_root=root)
    derived = {
        "schema": DERIVED_INPUT_SCHEMA,
        "mode": ENGINEERING_REPLAY_PROFILE,
        "status": "non_official_engineering_replay",
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "tool_version": TOOL_VERSION,
        "source_commit": s4_8._git(root, "rev-parse", "HEAD"),
        "source_raw_observation_root": replay["source_raw_observation_root"],
        "raw_take_read_count": replay["planned_take_count"],
        "payload": replay_payload,
        "evaluation_state": "evaluation_completed",
        "evaluation": evaluation,
        "evaluation_sha256": _canonical_sha256(evaluation),
        "run_failure": None,
        "reference_policy_id": POLICY_ID,
        "canonicalized_reference_count": canonicalized,
    }
    package_profile = classify_package_profile(derived)
    after = _snapshot_historical_state(root, release_candidate)
    if after != before:
        raise S48Recovery03Error(
            "official or historical evidence changed during replay"
        )
    report = {
        "schema": "ias.s4_8.recovery_03.engineering_replay_report.v1",
        "status": evaluation["status"],
        "mode": ENGINEERING_REPLAY_PROFILE,
        "official_evidence": False,
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "reference_policy_id": POLICY_ID,
        "package_profile_preview": package_profile,
        "raw_take_read_count": replay["planned_take_count"],
        "evaluator_invocation_count": 1,
        "canonicalized_reference_count": canonicalized,
        "historical_preservation_passed": True,
        "historical_snapshot_sha256": _canonical_sha256(after),
        "grant_created": False,
        "grant_consumed": False,
        "existing_raw_observations_read": True,
        "new_holdout_opening_event_created": False,
        "official_evaluation_executed": False,
        "future_holdout_collection_authorized": False,
        "validation": validation,
    }
    manifest_sha256 = _write_replay_output(
        destination,
        derived=derived,
        evaluation=evaluation,
        report=report,
    )
    return {
        **report,
        "output": destination.relative_to(root).as_posix(),
        "manifest_sha256": manifest_sha256,
    }


__all__ = [
    "DERIVED_INPUT_SCHEMA",
    "ENGINEERING_REPLAY_PROFILE",
    "FULL_EVALUATED_PROFILE",
    "INPUT_CONTRACT_REJECTION_PROFILE",
    "POLICY_ID",
    "PRE_EVALUATION_FAILURE_PROFILE",
    "REFERENCE_ORIGIN",
    "RELEASE_CANDIDATE_ID",
    "S48Recovery03Error",
    "TOOL_VERSION",
    "apply_reference_policy",
    "canonicalize_geometric_reference_tdoa",
    "classify_package_profile",
    "load_policy",
    "load_release_candidate",
    "run_engineering_replay",
    "validate_release_candidate",
]
