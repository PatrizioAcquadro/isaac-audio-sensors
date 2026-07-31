"""One-shot execution adapter for the frozen S4.8 amendment-02 protocol."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery
from isaac_audio_sensors.acquisition import s4_8_recovery_02_evaluator as evaluator
from isaac_audio_sensors.acquisition.s4_4 import (
    GRANT_SCHEMA,
    append_ledger_event,
    canonical_sha256,
    validate_ledger,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as c2

TOOL_VERSION = "ias_s4_8_recovery_02_execution/1.0.0"
DERIVED_INPUT_SCHEMA = "ias.s4_8.recovery_02.derived_evaluation_input.v2"
PACKAGE_FILES = s4_8.PACKAGE_FILES
FULL_EVIDENCE_PROFILE = "recovery_02_full_evidence.v2"
TERMINAL_FAILURE_PROFILE = "recovery_02_terminal_failure.v2"

WAV_RELATIVE_PATH = Path("respeaker_audio.wav")
QA_RELATIVE_PATH = Path("technical_gate_report.json")
AV_CONFIRMATION_RELATIVE_PATH = Path("official_attempt_record.json")
AV_FRAMES_RELATIVE_PATH = Path("zed/frames.jsonl")
AV_PRODUCER_RELATIVE_PATH = Path("pi_producer_status.json")

SOURCE_BOUND_FILES = (
    Path("src/isaac_audio_sensors/acquisition/s4_8.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02_execution.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02_evaluator.py"),
    Path("scripts/run_s4_8_recovery_02.py"),
)


def _holdout_seal_path(repo_root: Path) -> Path:
    amendment = recovery.load_amendment(repo_root.resolve())
    return repo_root.resolve() / recovery._safe_relative(
        amendment["unseen_holdout"]["holdout_seal_path"]
    )


def _execution_contract(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    contract = deepcopy(s4_8.load_contract(root))
    unseen = amendment["unseen_holdout"]
    future = amendment["future_attempt"]
    seal_path = _holdout_seal_path(root)
    seal = s4_8.load_json(seal_path)
    bindings = seal["bindings"]
    contract["holdout"].update(
        {
            "bound_holdout_id": unseen["holdout_id"],
            "seal_path": unseen["holdout_seal_path"],
            "seal_file_sha256": s4_8.sha256_file(seal_path),
            "seal_payload_sha256": seal["seal_payload_sha256"],
            "partition_manifest_path": unseen["partition_manifest_path"],
            "partition_manifest_sha256": bindings["partition_manifest"]["file_sha256"],
            "split_plan_sha256": bindings["partition_manifest"]["payload_sha256"],
            "session_manifest_path": unseen["session_manifest_path"],
            "session_manifest_sha256": bindings["session_manifest"]["file_sha256"],
            "dataset_attempt_root": unseen["observation_root"],
            "planned_take_count": recovery.PLANNED_TAKE_COUNT,
            "leakage_group_count": recovery.LEAKAGE_GROUP_COUNT,
            "sealed_artifact_count": seal["artifact_count"],
            "planned_denominator_policy": "all_37_planned_takes_retained",
        }
    )
    contract["grant"].update(
        {
            "path": future["grant_path"],
            "ledger_path": future["ledger_path"],
            "grant_id_template": future["grant_id_template"],
            "consume_function": (
                "isaac_audio_sensors.acquisition."
                "s4_8_recovery_02_execution.consume_grant"
            ),
        }
    )
    contract["evidence"].update(
        {
            "derived_input_path": future["derived_input_path"],
            "run_journal_path": future["journal_path"],
            "output_path": future["output_path"],
            "closeout_path": future["closeout_path"],
            "deterministic_replay_required": False,
        }
    )
    contract["criteria"].update(
        {
            "readiness_count": 17,
            "stretch_count": 13,
            "readiness_pass_rule": "all_17_effective_gating_criteria_pass",
        }
    )
    return contract


def _authorization_prerequisite(
    repo_root: Path,
    *,
    source_commit: str,
    preopen: Mapping[str, Any],
) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    review_path = root / recovery._safe_relative(
        amendment["future_attempt"]["independent_review_path"]
    )
    evaluator_binding = preopen["evaluator_binding"]
    finalization = preopen["postcollection_finalization"]
    return {
        "schema": "ias.s4_8.recovery_02.authorization_prerequisite.v1",
        "amendment_id": amendment["amendment_id"],
        "revision_id": amendment["revision_id"],
        "source_commit": source_commit,
        "planned_take_count": recovery.PLANNED_TAKE_COUNT,
        "protocol_sha256": evaluator_binding["protocol_sha256"],
        "evaluator_binding_sha256": evaluator_binding["binding_sha256"],
        "holdout_seal_file_sha256": finalization["holdout_seal_file_sha256"],
        "holdout_seal_payload_sha256": finalization["holdout_seal_payload_sha256"],
        "holdout_binding_file_sha256": finalization["holdout_binding_file_sha256"],
        "independent_review_file_sha256": s4_8.sha256_file(review_path),
    }


def preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None,
    verify_prerequisite_replay: bool,
    require_access_paths_absent: bool,
) -> dict[str, Any]:
    """Adapt the authenticated amendment pre-open result for the state machine."""

    del verify_prerequisite_replay
    root = repo_root.resolve()
    resolved = source_commit or s4_8._git(root, "rev-parse", "HEAD")
    s4_8._validate_source_commit(root, resolved, require_current_head=True)
    result = recovery.recovery_preopen_validate(
        root,
        source_commit=resolved,
        require_access_paths_absent=require_access_paths_absent,
    )
    if (
        result["blockers"] != ["explicit_authorization_not_granted"]
        or result["evaluator_binding_authenticated"] is not True
        or result["holdout_seal_authenticated"] is not True
        or result["holdout_binding_authenticated"] is not True
        or result["independent_review_authenticated"] is not True
        or result["holdout_collection_complete"] is not True
        or result["source_commit_binds_protocol_revision"] is not True
    ):
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 is not authorization-ready: "
            f"{result['blockers']}"
        )
    if require_access_paths_absent and (
        result["new_grant_present"] or result["new_ledger_present"]
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 access state already exists")
    seal_path = _holdout_seal_path(root)
    seal = s4_8.load_json(seal_path)
    prerequisite = _authorization_prerequisite(
        root,
        source_commit=resolved,
        preopen=result,
    )
    return {
        **result,
        "seal_file_sha256": s4_8.sha256_file(seal_path),
        "seal_payload_sha256": seal["seal_payload_sha256"],
        "split_plan_sha256": seal["bindings"]["partition_manifest"]["payload_sha256"],
        "prerequisite": prerequisite,
    }


def consume_grant(
    repo_root: Path,
    *,
    grant_path: Path,
    ledger_path: Path,
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Consume the exact amendment grant into one new ledger."""

    root = repo_root.resolve()
    config = s4_8.load_contract(root)
    grant = s4_8.load_json(grant_path)
    authorization = s4_8.load_json(grant_path.with_name(s4_8.AUTHORIZATION_RECORD_NAME))
    current = preopen_validate(
        root,
        source_commit=source_commit,
        verify_prerequisite_replay=False,
        require_access_paths_absent=False,
    )
    required = {
        "schema",
        "grant_id",
        "purpose",
        "seal_sha256",
        "split_plan_sha256",
        "prerequisite",
        "single_use",
        "authorization",
        "grant_sha256",
    }
    payload = {key: value for key, value in grant.items() if key != "grant_sha256"}
    expected_id = config["grant"]["grant_id_template"].format(
        source_commit=source_commit
    )
    if (
        set(grant) != required
        or grant.get("schema") != GRANT_SCHEMA
        or grant.get("grant_id") != expected_id
        or grant.get("purpose") != "S4.8_evaluation"
        or grant.get("seal_sha256") != current["seal_file_sha256"]
        or grant.get("split_plan_sha256") != current["split_plan_sha256"]
        or grant.get("prerequisite") != current["prerequisite"]
        or grant.get("single_use") is not True
        or grant.get("authorization") != "explicit_user_authorization_required"
        or grant.get("grant_sha256") != canonical_sha256(payload)
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 grant mismatch")
    s4_8._validate_authorization_record(
        authorization,
        config=config,
        source_commit=source_commit,
        grant=grant,
    )
    validation = validate_ledger(
        ledger_path,
        expected_seal_sha256=current["seal_file_sha256"],
    )
    if validation["status"] != "passed" or validation["event_count"] != 0:
        raise s4_8.S48Error("S4.8 recovery amendment_02 ledger is already consumed")
    event = append_ledger_event(
        ledger_path,
        {
            "event": "holdout_open_authorized",
            "event_time_utc": event_time_utc,
            "seal_sha256": current["seal_file_sha256"],
            "split_plan_sha256": current["split_plan_sha256"],
            "grant_id": grant["grant_id"],
            "grant_sha256": grant["grant_sha256"],
            "prerequisite_sha256": canonical_sha256(current["prerequisite"]),
            "purpose": "S4.8_evaluation",
            "holdout_opened": True,
        },
    )
    return {
        "allowed": True,
        "mode": "S4.8_evaluation",
        "ledger_event": event,
    }


def _attempt_state(
    repo_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, c2.TakeIdentity],
    dict[str, set[Path]],
    dict[str, Path],
]:
    root = repo_root.resolve()
    seal = s4_8.load_json(_holdout_seal_path(root))
    amendment = recovery.load_amendment(root)
    observation_prefix = (
        f"{amendment['unseen_holdout']['observation_root'].rstrip('/')}/"
    )
    attempt_seal = {
        **seal,
        "artifacts": [
            artifact
            for artifact in seal["artifacts"]
            if str(artifact["path"]).startswith(observation_prefix)
        ],
    }
    registry = evaluator.build_identity_registry(root)
    candidates = s4_8._sealed_attempt_candidates(attempt_seal, set(registry))
    selected = s4_8._sealed_attempt_roots(root, attempt_seal, set(registry))
    if (
        len(candidates) != recovery.PLANNED_TAKE_COUNT
        or any(len(items) != 1 for items in candidates.values())
        or len(selected) != recovery.PLANNED_TAKE_COUNT
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 retained attempt census mismatch"
        )
    return seal, registry, candidates, selected


def input_rejection_inventory(
    repo_root: Path,
    error: Exception,
) -> list[dict[str, Any]]:
    root = repo_root.resolve()
    seal, registry, candidates, selected = _attempt_state(root)
    records = s4_8._initial_observation_inventory(
        root,
        seal=seal,
        registry=registry,
        attempt_candidates=candidates,
        attempt_roots=selected,
        wav_relative_path=WAV_RELATIVE_PATH,
        qa_relative_path=QA_RELATIVE_PATH,
    )
    for record in records:
        record.update(
            {
                "rejected": True,
                "failed": True,
                "failure_reasons": ["evaluation_input_contract_rejected"],
                "terminal_error_type": type(error).__name__,
                "terminal_error": str(error),
            }
        )
    return records


def input_rejection_payload(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    return {
        "schema": evaluator.PAYLOAD_SCHEMA,
        "contract": evaluator._expected_contract(root),
        "takes": [],
        "sim_vs_real": [],
    }


def _partial_payload(
    repo_root: Path,
    *,
    takes: Sequence[Mapping[str, Any]],
    simulation: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": evaluator.PAYLOAD_SCHEMA,
        "contract": evaluator._expected_contract(repo_root.resolve()),
        "takes": [dict(item) for item in takes],
        "sim_vs_real": [dict(item) for item in simulation],
    }


def _simulation_comparisons(
    repo_root: Path,
    registry: Mapping[str, c2.TakeIdentity],
) -> list[dict[str, Any]]:
    root = repo_root.resolve()
    paths = {
        mode: s4_8._simulate_path(root, registry, mode) for mode in ("off", "apply")
    }
    _corrective_03, config = evaluator._adapted_configs(root)
    comparisons: list[dict[str, Any]] = []
    for entry in config["sim_vs_real"]["comparison_registry"]:
        conditions = []
        for condition_id in sorted(
            c2._expected_comparison_conditions(entry, registry, config)
        ):
            conditions.append(
                {
                    "condition_id": condition_id,
                    "unadjusted_simulation": paths["off"][entry["comparison_id"]][
                        condition_id
                    ],
                    "adjusted_simulation": paths["apply"][entry["comparison_id"]][
                        condition_id
                    ],
                }
            )
        comparisons.append(
            {
                "comparison_id": entry["comparison_id"],
                "conditions": conditions,
            }
        )
    return comparisons


def _valid_av_confirmation(
    record: Mapping[str, Any],
    take_id: str,
    attempt_root: Path,
) -> bool:
    return (
        record.get("schema") == "ias.s4_8.recovery_02_official_attempt.v1"
        and record.get("planned_take_id") == take_id
        and record.get("decision") == "PASS"
        and record.get("retained") is True
        and record.get("counts_as_official_attempt") is True
        and record.get("automatic_retry") is False
        and record.get("automatic_continuation") is False
        and record.get("controller_failure") is None
        and record.get("start_state", {}).get("zed_recording_started") is True
        and record.get("attempt_number") == 1
        and attempt_root.name.endswith("__attempt_01")
    )


def build_real_payload(
    repo_root: Path,
    *,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open the authenticated 37 retained attempts after grant consumption."""

    root = repo_root.resolve()
    s4_8._require_execution_lock(root)
    config = s4_8.load_contract(root)
    s4_8._require_consumed_ledger(root, config)
    finalization = recovery.recovery_preopen_validate(
        root,
        source_commit=s4_8._git(root, "rev-parse", "HEAD"),
        require_access_paths_absent=False,
    )["postcollection_finalization"]
    if finalization is None or finalization["status"] != "passed":
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 finalization is not authenticated"
        )
    seal, registry, candidates, selected = _attempt_state(root)
    profile = s4_8._profile_runtime(root)
    simulation = _simulation_comparisons(root, registry)
    takes: list[dict[str, Any]] = []
    inventory = s4_8._initial_observation_inventory(
        root,
        seal=seal,
        registry=registry,
        attempt_candidates=candidates,
        attempt_roots=selected,
        wav_relative_path=WAV_RELATIVE_PATH,
        qa_relative_path=QA_RELATIVE_PATH,
    )
    by_root = {record["attempt_root"]: record for record in inventory}
    s4_8._emit_observation_progress(
        progress_callback,
        inventory=inventory,
        payload=_partial_payload(root, takes=takes, simulation=simulation),
        current_take=None,
    )
    for take_id in sorted(registry):
        identity = registry[take_id]
        attempt_root = selected[take_id]
        relative_root = attempt_root.relative_to(root).as_posix()
        progress_record = by_root[relative_root]
        expected_windows = {15: 119, 20: 159}[identity.duration_s]
        latest = {
            "expected_window_count": expected_windows,
            "completed_window_count": 0,
            "completed_windows": [],
            "failed_window_index": None,
        }
        progress_record["scientific_observation_opened"] = True
        s4_8._emit_observation_progress(
            progress_callback,
            inventory=inventory,
            payload=_partial_payload(root, takes=takes, simulation=simulation),
            current_take={
                "planned_take_id": take_id,
                "attempt_root": relative_root,
                **latest,
            },
        )

        def record_window(
            window_progress: Mapping[str, Any],
            *,
            current_take_id: str = take_id,
            current_attempt_root: str = relative_root,
        ) -> None:
            nonlocal latest
            latest = dict(window_progress)
            s4_8._emit_observation_progress(
                progress_callback,
                inventory=inventory,
                payload=_partial_payload(
                    root,
                    takes=takes,
                    simulation=simulation,
                ),
                current_take={
                    "planned_take_id": current_take_id,
                    "attempt_root": current_attempt_root,
                    **latest,
                },
            )

        try:
            take, record = s4_8._analyze_real_take(
                root,
                attempt_root,
                identity,
                profile=profile,
                seal=seal,
                window_progress_callback=(
                    record_window if progress_callback is not None else None
                ),
                wav_relative_path=WAV_RELATIVE_PATH,
                qa_relative_path=QA_RELATIVE_PATH,
                qa_pass_field="decision",
                qa_pass_value="PASS",
                av_confirmation_relative_path=AV_CONFIRMATION_RELATIVE_PATH,
                av_frames_relative_path=AV_FRAMES_RELATIVE_PATH,
                av_producer_relative_path=AV_PRODUCER_RELATIVE_PATH,
                av_confirmation_validator=_valid_av_confirmation,
            )
        except Exception as exc:
            progress_record.update(
                {
                    "analysis_completed": False,
                    "failed": True,
                    "failure_reasons": ["observation_analysis_failed"],
                    "rejected": True,
                    "scientific_observations_derived": bool(
                        latest["completed_windows"]
                    ),
                    "partial_window_count": len(latest["completed_windows"]),
                    "expected_window_count": latest["expected_window_count"],
                    "failed_window_index": latest["failed_window_index"],
                    "terminal_error_type": type(exc).__name__,
                    "terminal_error": str(exc),
                }
            )
            partial = _partial_payload(
                root,
                takes=takes,
                simulation=simulation,
            )
            inventory.sort(key=lambda item: item["attempt_root"])
            raise s4_8.S48PartialAnalysisError(
                f"{take_id}: observation analysis failed after "
                f"{len(takes)} completed takes",
                payload=partial,
                observation_inventory=inventory,
                cause=exc,
            ) from exc
        takes.append(take)
        progress_record.update(record)
        progress_record.update(
            {
                "selected_for_evaluation": True,
                "scientific_observation_opened": True,
                "scientific_observations_derived": True,
                "analysis_completed": True,
            }
        )
        s4_8._emit_observation_progress(
            progress_callback,
            inventory=inventory,
            payload=_partial_payload(root, takes=takes, simulation=simulation),
            current_take=None,
        )
    inventory.sort(key=lambda item: item["attempt_root"])
    return (
        _partial_payload(root, takes=takes, simulation=simulation),
        inventory,
    )


def _evaluation_callback(
    counter: dict[str, int],
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    counter["count"] += 1
    if counter["count"] != 1:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 evaluator invocation already consumed"
        )
    report = evaluator.evaluate_payload(payload, repo_root=repo_root).report()
    return {**report, "evaluation_invocation_count": counter["count"]}


def _authorization_report(derived: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_8.authorization_access.v1",
        "status": "passed",
        "authorization_record": derived["authorization_record"],
        "grant": derived["grant"],
        "ledger_event": derived["ledger_event"],
        "run_journal": derived.get("run_journal"),
        "grant_consumed_exactly_once": True,
        "holdout_opening_event_count": 1,
        "raw_content_included": False,
    }


def _package_reports(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    source_commit: str,
    package_profile: str,
) -> dict[str, dict[str, Any]]:
    root = repo_root.resolve()
    evaluation = dict(derived["evaluation"])
    payload = dict(derived["payload"])
    takes = payload.get("takes", [])
    if not isinstance(takes, list):
        raise s4_8.S48Error("S4.8 recovery amendment_02 payload takes must be a list")
    inventory = derived.get("observation_inventory", [])
    if not isinstance(inventory, list):
        raise s4_8.S48Error("S4.8 recovery amendment_02 inventory must be a list")
    run_failure = derived.get("run_failure")
    gating = [
        item for item in evaluation.get("criteria", []) if item.get("gating") is True
    ]
    nongating = [
        item for item in evaluation.get("criteria", []) if item.get("gating") is False
    ]
    scientific_passed = (
        derived.get("evaluation_state") == "evaluation_completed"
        and evaluation.get("readiness_passed") is True
        and len(gating) == 17
        and all(item.get("passed") is True for item in gating)
    )
    final_status = "passed" if scientific_passed and run_failure is None else "failed"
    preservation = s4_8.preservation_report(root)
    failures = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "failed": take["failed"],
            "failure_reasons": take["failure_reasons"],
        }
        for take in takes
        if take.get("failed") is True
    ]
    windows = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "stratum_id": take["identity"]["stratum_id"],
            "windows": take.get("bearing_windows", []),
            "window_summary": take.get("window_summary"),
        }
        for take in takes
    ]
    reports: dict[str, dict[str, Any]] = {
        "authorization_access.json": _authorization_report(derived),
        "criteria_results.json": evaluation,
        "derived_evaluation_input.json": dict(derived),
        "failure_inventory.json": {
            "schema": "ias.s4_8.failure_inventory.v1",
            "status": "complete",
            "planned_take_count": recovery.PLANNED_TAKE_COUNT,
            "failed_take_count": len(failures),
            "failures": failures,
            "run_failure": run_failure,
            "rejected_attempts": [
                record for record in inventory if record.get("rejected") is True
            ],
            "all_planned_takes_retained": True,
        },
        "preservation_report.json": preservation,
        "provenance.json": s4_8._provenance_report(
            root,
            derived=derived,
            source_commit=source_commit,
            status="passed",
        ),
        "reproduction.json": {
            "schema": "ias.s4_8.reproduction.v1",
            "status": "disabled_by_one_shot_contract",
            "source_commit": source_commit,
            "scientific_recomputation": "forbidden",
            "opens_raw_holdout": False,
            "consumes_grant": False,
        },
        "robustness.json": {
            "schema": "ias.s4_8.robustness.v1",
            "status": "not_evaluable",
            "denominator": 0,
            "gating": False,
            "quantities": [],
        },
        "sim_vs_real.json": {
            "schema": "ias.s4_8.sim_vs_real.v1",
            "status": "complete",
            "comparison_classifications": evaluation.get(
                "comparison_classifications", []
            ),
            "condition_inputs": payload.get("sim_vs_real", []),
            "paths": ["real", "unadjusted_simulation", "adjusted_simulation"],
            "unadjusted_profile_mode": "off",
            "adjusted_profile_mode": "apply",
        },
        "supported_unsupported.json": {
            "schema": "ias.s4_8.supported_unsupported.v1",
            "status": "complete",
            "supported_envelope": "frozen_recovery_02_37_take_protocol",
            "supported_metrics": [
                "squadbot_categorical_direction_accuracy",
                "candidate_coverage",
                "tdoa",
                "confidence",
                "abstention",
                "relative_latency",
                "channel_health",
                "clipping",
                "coarse_audio_video_association",
            ],
            "unsupported": ["robustness_generalization"],
        },
        "take_inventory.json": {
            "schema": "ias.s4_8.take_inventory.v1",
            "status": "complete",
            "planned_take_count": recovery.PLANNED_TAKE_COUNT,
            "leakage_group_count": recovery.LEAKAGE_GROUP_COUNT,
            "sealed_attempt_count": len(inventory),
            "selected_attempt_count": sum(
                record.get("selected_for_evaluation") is True for record in inventory
            ),
            "unselected_attempt_count": sum(
                record.get("selected_for_evaluation") is False for record in inventory
            ),
            "attempt_records": inventory,
            "records": [
                {key: take[key] for key in take if key != "bearing_windows"}
                for take in takes
            ],
        },
        "window_results.json": {
            "schema": "ias.s4_8.window_results.v1",
            "status": (
                "complete" if len(takes) == recovery.PLANNED_TAKE_COUNT else "partial"
            ),
            "record_count": sum(len(item["windows"]) for item in windows),
            "takes": windows,
        },
        "final_validation.json": {
            "schema": "ias.s4_8.recovery_02.final_validation.v2",
            "package_profile": package_profile,
            "status": final_status,
            "readiness_passed": final_status == "passed",
            "scientific_readiness_passed": scientific_passed,
            "scientific_evaluation_state": derived.get("evaluation_state"),
            "scientific_evaluation_status": evaluation.get("status"),
            "run_failure": run_failure,
            "terminal": True,
            "automatic_retry_forbidden": True,
            "readiness_criterion_count": len(gating),
            "nongating_criterion_count": len(nongating),
            "planned_take_count": recovery.PLANNED_TAKE_COUNT,
            "historical_preservation_passed": preservation["status"] == "passed",
            "evaluator_invocation_count": evaluation.get(
                "evaluation_invocation_count", 0
            ),
            "holdout_opening_event_count": 1,
            "scientific_recomputation_count": 0,
            "s4_complete": False,
            "s4_9_started": False,
            "later_phases_started": [],
        },
        "determinism_report.json": {
            "schema": "ias.s4_8.determinism.v1",
            "status": "not_replayed_one_shot_contract",
            "source_commit": source_commit,
            "canonical_file_count": len(PACKAGE_FILES),
            "raw_holdout_reopened": False,
            "grant_reconsumed": False,
            "scientific_recomputation_count": 0,
            "evaluator_invocation_count": evaluation.get(
                "evaluation_invocation_count", 0
            ),
        },
    }
    return reports


def _build_package(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    destination: Path,
    source_commit: str,
    validate_result: bool,
    package_profile: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    s4_8._validate_authorization_evidence(
        derived,
        config=s4_8.load_contract(root),
    )
    reports = _package_reports(
        root,
        derived,
        source_commit=source_commit,
        package_profile=package_profile,
    )
    if set(reports) != PACKAGE_FILES - {
        "SHA256SUMS",
        "evidence_index.json",
    }:
        raise s4_8.S48Error("S4.8 recovery amendment_02 report set mismatch")
    for name, report in reports.items():
        (destination / name).write_text(
            s4_8.pretty_json(report),
            encoding="utf-8",
        )
    s4_8._write_index_and_manifest(destination, source_commit)
    if validate_result:
        validate_evidence_package(destination, repo_root=root)
    s4_8._fsync_package_tree(destination)
    final = reports["final_validation.json"]
    return {
        "status": final["status"],
        "output": destination.as_posix(),
        "file_count": len(PACKAGE_FILES),
        "manifest_sha256": s4_8.sha256_file(destination / "SHA256SUMS"),
        "package_profile": package_profile,
        "scientific_recomputed": False,
    }


def build_evidence_package(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    destination: Path,
    source_commit: str,
    validate_result: bool = True,
) -> dict[str, Any]:
    return _build_package(
        repo_root,
        derived,
        destination=destination,
        source_commit=source_commit,
        validate_result=validate_result,
        package_profile=FULL_EVIDENCE_PROFILE,
    )


def build_terminal_failure_package(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    destination: Path,
    source_commit: str,
    validate_result: bool = True,
) -> dict[str, Any]:
    if not isinstance(derived.get("run_failure"), Mapping):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 terminal package lacks run failure"
        )
    return _build_package(
        repo_root,
        derived,
        destination=destination,
        source_commit=source_commit,
        validate_result=validate_result,
        package_profile=TERMINAL_FAILURE_PROFILE,
    )


def validate_evidence_package(
    package: Path,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Validate hashes and terminal invariants without evaluator recomputation."""

    root = repo_root.resolve()
    package = package.resolve()
    if not package.is_dir():
        raise s4_8.S48Error("S4.8 recovery amendment_02 package is not a directory")
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != PACKAGE_FILES:
        raise s4_8.S48Error("S4.8 recovery amendment_02 package file set mismatch")
    s4_8._validate_manifest(package)
    index = s4_8.load_json(package / "evidence_index.json")
    if index.get("record_count") != len(PACKAGE_FILES) - 3:
        raise s4_8.S48Error("S4.8 recovery amendment_02 evidence index count mismatch")
    for record in index.get("records", []):
        path = package / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != record["byte_size"]
            or s4_8.sha256_file(path) != record["sha256"]
        ):
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 index mismatch: {record['path']}"
            )
    derived = s4_8.load_json(package / "derived_evaluation_input.json")
    s4_8._validate_authorization_evidence(
        derived,
        config=s4_8.load_contract(root),
    )
    criteria = s4_8.load_json(package / "criteria_results.json")
    final = s4_8.load_json(package / "final_validation.json")
    authorization = s4_8.load_json(package / "authorization_access.json")
    inventory = s4_8.load_json(package / "take_inventory.json")
    if (
        criteria != derived.get("evaluation")
        or derived.get("evaluation_sha256") != canonical_sha256(criteria)
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
        or final.get("evaluator_invocation_count") not in {0, 1}
        or final.get("scientific_recomputation_count") != 0
        or final.get("holdout_opening_event_count") != 1
        or authorization.get("grant_consumed_exactly_once") is not True
        or authorization.get("holdout_opening_event_count") != 1
        or inventory.get("planned_take_count") != recovery.PLANNED_TAKE_COUNT
        or inventory.get("leakage_group_count") != recovery.LEAKAGE_GROUP_COUNT
        or inventory.get("sealed_attempt_count") != recovery.PLANNED_TAKE_COUNT
        or inventory.get("selected_attempt_count") != recovery.PLANNED_TAKE_COUNT
        or inventory.get("unselected_attempt_count") != 0
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 terminal invariants mismatch")
    ledger_event = authorization.get("ledger_event")
    if (
        not isinstance(ledger_event, Mapping)
        or ledger_event.get("sequence") != 0
        or ledger_event.get("event") != "holdout_open_authorized"
        or ledger_event.get("holdout_opened") is not True
        or ledger_event.get("event_sha256")
        != canonical_sha256(
            {key: value for key, value in ledger_event.items() if key != "event_sha256"}
        )
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 ledger evidence mismatch")
    gating = [
        item for item in criteria.get("criteria", []) if item.get("gating") is True
    ]
    if derived.get("evaluation_state") == "evaluation_completed" and (
        final.get("evaluator_invocation_count") != 1 or len(gating) != 17
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 completed evaluation mismatch")
    provenance = s4_8.load_json(package / "provenance.json")
    source_commit = s4_8._validate_provenance(
        provenance,
        derived=derived,
        repo_root=root,
    )
    scientific_passed = (
        derived.get("evaluation_state") == "evaluation_completed"
        and criteria.get("readiness_passed") is True
        and len(gating) == 17
        and all(item.get("passed") is True for item in gating)
    )
    expected_status = (
        "passed"
        if scientific_passed and derived.get("run_failure") is None
        else "failed"
    )
    if (
        final.get("status") != expected_status
        or final.get("readiness_passed") is not (expected_status == "passed")
        or final.get("scientific_readiness_passed") is not scientific_passed
        or final.get("run_failure") != derived.get("run_failure")
    ):
        raise s4_8.S48Error("S4.8 recovery amendment_02 verdict is contradictory")
    return {
        "schema": "ias.s4_8.recovery_02.package_validation.v1",
        "status": "passed",
        "source_commit": source_commit,
        "file_count": len(PACKAGE_FILES),
        "manifest_sha256": s4_8.sha256_file(package / "SHA256SUMS"),
        "readiness_passed": final["readiness_passed"],
        "final_status": final["status"],
        "scientific_recomputed": False,
        "evaluator_invocation_count": final["evaluator_invocation_count"],
        "holdout_opening_event_count": 1,
    }


def _closeout_markdown(
    repo_root: Path,
    *,
    package: Path,
) -> str:
    del repo_root
    criteria = s4_8.load_json(package / "criteria_results.json")
    final = s4_8.load_json(package / "final_validation.json")
    derived = s4_8.load_json(package / "derived_evaluation_input.json")
    gating = [
        item for item in criteria.get("criteria", []) if item.get("gating") is True
    ]
    rows = [
        "| Criterion | Comparator | Threshold | Observed | N | Result |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in gating:
        rows.append(
            "| {criterion_id} | {comparator} | {threshold} | {observed} | "
            "{sample_count} | {result} |".format(
                **item,
                result="PASS" if item["passed"] else "FAIL",
            )
        )
    verdict = "GO" if final["readiness_passed"] else "NO-GO"
    return "\n".join(
        [
            "# S4.8 recovery amendment-02 37-take closeout",
            "",
            f"Official verdict: **{verdict}**.",
            "",
            f"Source commit: `{derived['source_commit']}`.",
            f"Package manifest SHA-256: `{s4_8.sha256_file(package / 'SHA256SUMS')}`.",
            f"Derived input SHA-256: "
            f"`{s4_8.sha256_file(package / 'derived_evaluation_input.json')}`.",
            f"Evaluation SHA-256: `{derived['evaluation_sha256']}`.",
            "",
            "The authorization grant was consumed exactly once, the holdout "
            "ledger contains one opening event, and the bound evaluator was "
            f"invoked `{final['evaluator_invocation_count']}` time.",
            "",
            "## Gating criteria",
            "",
            *rows,
            "",
            "No replay or scientific recomputation was performed.",
            "",
        ]
    )


def _write_closeout(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    package = root / recovery._safe_relative(amendment["future_attempt"]["output_path"])
    closeout = root / recovery._safe_relative(
        amendment["future_attempt"]["closeout_path"]
    )
    if closeout.exists():
        raise s4_8.S48Error("S4.8 recovery amendment_02 closeout already exists")
    s4_8._atomic_write_text(
        closeout,
        _closeout_markdown(root, package=package),
    )
    return {
        "path": closeout.relative_to(root).as_posix(),
        "sha256": s4_8.sha256_file(closeout),
    }


def _adapter(counter: dict[str, int]) -> dict[str, Any]:
    return {
        "tool_version": TOOL_VERSION,
        "derived_input_schema": DERIVED_INPUT_SCHEMA,
        "preopen_validate": preopen_validate,
        "consume_grant": consume_grant,
        "build_real_payload": build_real_payload,
        "evaluate_payload": (
            lambda payload, *, repo_root: _evaluation_callback(
                counter,
                payload,
                repo_root=repo_root,
            )
        ),
        "input_rejection_payload": input_rejection_payload,
        "input_rejection_inventory": input_rejection_inventory,
        "build_evidence_package": build_evidence_package,
        "build_terminal_failure_package": build_terminal_failure_package,
        "validate_evidence_package": validate_evidence_package,
    }


@contextmanager
def execution_context(repo_root: Path) -> Iterator[dict[str, int]]:
    root = repo_root.resolve()
    counter = {"count": 0}
    contract = _execution_contract(root)
    with (
        s4_8._use_contract(
            contract,
            contract_path=recovery.AMENDMENT_PATH,
            extra_source_bound_files=SOURCE_BOUND_FILES,
        ),
        s4_8._use_execution_adapter(_adapter(counter)),
    ):
        yield counter


def create_recovery_grant(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    with execution_context(root):
        preopen_validate(
            root,
            source_commit=source_commit,
            verify_prerequisite_replay=False,
            require_access_paths_absent=True,
        )
        result = s4_8.create_grant(
            root,
            source_commit=source_commit,
            authorization_id=authorization_id,
        )
    return {
        **result,
        "amendment_id": recovery.load_amendment(root)["amendment_id"],
        "holdout_opened": False,
        "evaluation_run": False,
    }


def run_recovery_evaluation_once(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
    event_time_utc: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    grant_path = root / recovery._safe_relative(
        amendment["future_attempt"]["grant_path"]
    )
    authorization = s4_8.load_json(grant_path.with_name(s4_8.AUTHORIZATION_RECORD_NAME))
    if (
        authorization.get("source_commit") != source_commit
        or authorization.get("authorization_id") != authorization_id
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 authorization identity mismatch"
        )
    with execution_context(root) as counter:
        result = s4_8.run_authorized_evaluation_once(
            root,
            source_commit=source_commit,
            event_time_utc=event_time_utc,
        )
        if counter["count"] not in {0, 1}:
            raise s4_8.S48Error("S4.8 recovery amendment_02 evaluator count is invalid")
        closeout = _write_closeout(root)
    return {
        **result,
        "closeout": closeout,
        "evaluator_invocation_count": counter["count"],
        "holdout_opening_event_count": 1,
        "scientific_recomputed": False,
    }


def validate_recovery_evidence_package(
    repo_root: Path,
    *,
    package: Path | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    selected = package or Path(amendment["future_attempt"]["output_path"])
    selected = selected if selected.is_absolute() else root / selected
    with execution_context(root):
        return s4_8.validate_evidence_package(selected, repo_root=root)


__all__ = [
    "create_recovery_grant",
    "run_recovery_evaluation_once",
    "validate_recovery_evidence_package",
]
