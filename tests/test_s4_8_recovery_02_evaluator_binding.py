"""Outcome-blind authentication tests for the 37-take evaluator binding."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

ROOT = Path(__file__).resolve().parents[1]


def _allow_uncommitted_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = recovery._source_contains_files

    def source_contains(
        repo_root: Path,
        *,
        source_commit: str,
        paths: dict[Path, str],
    ) -> bool:
        if set(paths) == {
            recovery.EVALUATOR_BINDING_PATH,
            recovery.EVALUATOR_BINDING_SCHEMA_PATH,
        }:
            return True
        return original(
            repo_root,
            source_commit=source_commit,
            paths=paths,
        )

    monkeypatch.setattr(recovery, "_source_contains_files", source_contains)


def test_binding_authenticates_without_scientific_or_authority_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_uncommitted_binding(monkeypatch)

    result = recovery.authenticate_evaluator_binding(
        ROOT,
        source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
    )

    assert result is not None
    assert result["status"] == "authenticated"
    assert result["planned_take_count"] == 37
    assert result["primary_metric"] == "squadbot_categorical_direction_accuracy"
    assert result["primary_threshold"] == 0.75
    assert result["primary_denominator"] == 28
    assert result["effective_gating_criterion_count"] == 17
    assert result["scientifically_opened"] is False
    assert result["scientific_outcomes_derived"] is False
    assert result["grant_created"] is False
    assert result["grant_consumed"] is False
    assert result["evaluation_run"] is False


def test_binding_hash_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = s4_8.sha256_file

    def altered(path: Path) -> str:
        if path == ROOT / recovery.EVALUATOR_BINDING_PATH:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(s4_8, "sha256_file", altered)
    with pytest.raises(s4_8.S48Error, match="binding hash mismatch"):
        recovery.authenticate_evaluator_binding(
            ROOT,
            source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
        )


def test_schema_and_protocol_role_tamper_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_uncommitted_binding(monkeypatch)
    original = s4_8.load_json
    binding_path = ROOT / recovery.EVALUATOR_BINDING_PATH
    binding = original(binding_path)
    altered = copy.deepcopy(binding)
    altered["protocol"]["primary_threshold"] = 0.5

    def load(path: Path) -> dict[str, Any]:
        return altered if path == binding_path else original(path)

    monkeypatch.setattr(s4_8, "load_json", load)
    with pytest.raises(s4_8.S48Error, match="binding schema failure"):
        recovery.authenticate_evaluator_binding(
            ROOT,
            source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
        )


def test_unsafe_bound_path_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_uncommitted_binding(monkeypatch)
    original = s4_8.load_json
    binding_path = ROOT / recovery.EVALUATOR_BINDING_PATH
    altered = copy.deepcopy(original(binding_path))
    altered["bindings"]["design_manifest"]["path"] = "../outside.json"

    def load(path: Path) -> dict[str, Any]:
        return altered if path == binding_path else original(path)

    monkeypatch.setattr(s4_8, "load_json", load)
    with pytest.raises(s4_8.S48Error, match="unsafe amendment_02 path"):
        recovery.authenticate_evaluator_binding(
            ROOT,
            source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
        )


def test_evaluator_source_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def source_contains(
        _repo_root: Path,
        *,
        source_commit: str,
        paths: dict[Path, str],
    ) -> bool:
        nonlocal calls
        calls += 1
        assert source_commit
        assert paths
        return calls == 1

    monkeypatch.setattr(recovery, "_source_contains_files", source_contains)
    with pytest.raises(s4_8.S48Error, match="source authentication failed"):
        recovery.authenticate_evaluator_binding(
            ROOT,
            source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
        )


def test_opened_holdout_claim_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_uncommitted_binding(monkeypatch)
    original = s4_8.load_json
    holdout_path = ROOT / (
        "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
        "s4_4_data_expansion_amendment_04/holdout_seal.v2.json"
    )
    opened = copy.deepcopy(original(holdout_path))
    opened["scientifically_opened"] = True

    def load(path: Path) -> dict[str, Any]:
        return opened if path == holdout_path else original(path)

    monkeypatch.setattr(s4_8, "load_json", load)
    with pytest.raises(s4_8.S48Error, match="sealed-holdout identity"):
        recovery.authenticate_evaluator_binding(
            ROOT,
            source_commit="1d97ba8690a08911d91abd2e32aa1c265808c8c3",
        )


def test_preopen_removes_only_evaluator_blocker_when_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated = {
        "status": "authenticated",
        "scientifically_opened": False,
        "scientific_outcomes_derived": False,
        "grant_created": False,
        "grant_consumed": False,
        "evaluation_run": False,
    }
    monkeypatch.setattr(
        recovery,
        "_source_binds_protocol_revision",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        recovery,
        "authenticate_evaluator_binding",
        lambda *_args, **_kwargs: authenticated,
    )

    result = recovery.recovery_preopen_validate(ROOT)

    assert result["blockers"] == [
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    assert result["official_readiness"] == "no_go"
    assert result["evaluator_binding_authenticated"] is True
    assert result["evaluator_binding"] == authenticated
    assert result["grant_creation_authorized"] is False
    assert result["grant_consumption_authorized"] is False
    assert result["evaluation_execution_authorized"] is False
    assert result["holdout_observation_opened"] is False
    assert result["content_derived_values_returned"] is False


def test_absent_binding_retains_only_its_named_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "_source_binds_protocol_revision",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        recovery,
        "authenticate_evaluator_binding",
        lambda *_args, **_kwargs: None,
    )

    result = recovery.recovery_preopen_validate(ROOT)

    assert result["blockers"] == [
        "evaluator_not_bound_to_37_take_protocol",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    assert result["evaluator_binding_authenticated"] is False
    assert result["evaluator_binding"] is None
