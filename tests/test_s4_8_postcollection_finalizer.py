from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from isaac_audio_sensors.acquisition import s4_8_postcollection_finalizer as finalizer
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

ROOT = Path(__file__).resolve().parents[1]
SEAL_PATH = ROOT / (
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_04/holdout_seal.v2.json"
)
BINDING_PATH = ROOT / (
    "configs/s4_8_recovery_amendment_02_holdout_binding.v2.json"
)


def _documents(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], dict[str, object]]:
    monkeypatch.setattr(finalizer, "_require_finalizer_source", lambda *_a: None)
    return finalizer.build_postcollection_documents(
        ROOT,
        finalizer_source_commit="a" * 40,
    )


def test_real_collection_build_is_complete_deterministic_and_outcome_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seal, binding = _documents(monkeypatch)
    repeated_seal, repeated_binding = _documents(monkeypatch)

    assert seal == repeated_seal
    assert binding == repeated_binding
    assert seal["artifact_count"] == 374
    assert seal["collection"] == {
        "observation_root": (
            "dataset/S4.4/amendments/"
            "s4_4_data_expansion_amendment_04/attempts"
        ),
        "attempt_ledger_path": (
            "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
            "s4_4_data_expansion_amendment_04/acquisition/attempt_ledger.jsonl"
        ),
        "planned_take_count": 37,
        "completed_take_count": 37,
        "retained_attempt_count": 37,
        "pass_attempt_count": 37,
        "retry_required_attempt_count": 0,
        "ledger_record_count": 37,
        "ledger_file_sha256": (
            "905da302647cf3844cedf77fbacae94bf2d521964ee4fdbb2daea6e75cea0ded"
        ),
        "ledger_head_sha256": (
            "df52d66e02763e197c375a4a120bff059eccdfb821e3d66c0e696d1c1c770f8c"
        ),
        "authorization_record_count": 37,
        "attempt_artifact_count": 336,
        "collection_artifact_count": 374,
    }
    assert seal["scientifically_opened"] is False
    assert seal["scientific_artifact_contents_parsed"] is False
    assert seal["scientific_outcomes_derived"] is False
    assert seal["scientific_outputs_returned"] is False
    assert all(value is False for value in seal["authority"].values())
    assert binding["preregistration_commit"] == (
        "80ad1dcd23b08e31316505a18d0a3fa1fc02ea50"
    )
    assert binding["scientifically_opened"] is False

    seal_schema = json.loads(
        (ROOT / finalizer.SEAL_SCHEMA_PATH).read_text(encoding="utf-8")
    )
    binding_schema = json.loads(
        (ROOT / recovery.HOLDOUT_BINDING_SCHEMA_PATH).read_text(encoding="utf-8")
    )
    jsonschema.validate(seal, seal_schema)
    jsonschema.validate(binding, binding_schema)


def test_collection_builder_parses_only_allowlisted_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed: list[Path] = []
    original = finalizer._load_metadata_json

    def record(path: Path) -> dict[str, object]:
        parsed.append(path)
        return original(path)

    monkeypatch.setattr(finalizer, "_require_finalizer_source", lambda *_a: None)
    monkeypatch.setattr(finalizer, "_load_metadata_json", record)
    finalizer.build_postcollection_documents(
        ROOT,
        finalizer_source_commit="a" * 40,
    )

    assert parsed
    assert not ({path.name for path in parsed} & finalizer.SCIENTIFIC_CONTENT_FILENAMES)
    parsed_metadata = {
        path.name for path in parsed if path.name in finalizer.METADATA_FILENAMES
    }
    assert parsed_metadata == finalizer.METADATA_FILENAMES


@pytest.mark.parametrize(
    "filename",
    sorted(finalizer.SCIENTIFIC_CONTENT_FILENAMES),
)
def test_scientific_content_parse_is_refused(
    tmp_path: Path,
    filename: str,
) -> None:
    path = tmp_path / filename
    path.write_text('{"outcome": "must not be read"}\n', encoding="utf-8")

    with pytest.raises(
        finalizer.S48PostcollectionFinalizerError,
        match="parse refused",
    ):
        finalizer._load_metadata_json(path)


def test_holdout_seal_tamper_and_unsafe_path_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seal, _binding = _documents(monkeypatch)
    altered = copy.deepcopy(seal)
    altered["artifacts"][0]["byte_size"] += 1

    with pytest.raises(
        finalizer.S48PostcollectionFinalizerError,
        match="self-hash mismatch",
    ):
        finalizer._validate_seal_document(ROOT, altered)

    target = tmp_path / "target"
    target.write_bytes(b"opaque")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(
        finalizer.S48PostcollectionFinalizerError,
        match="symlink refused",
    ):
        finalizer._artifact_record(tmp_path, Path("link"), "test")
    with pytest.raises(
        finalizer.S48PostcollectionFinalizerError,
        match="unsafe path",
    ):
        finalizer._safe_relative("../escape", "test")


def test_exclusive_pair_write_cleans_only_new_partial_file(
    tmp_path: Path,
) -> None:
    seal = tmp_path / "seal.json"
    binding = tmp_path / "binding.json"
    binding.write_text('{"preserve": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        finalizer._write_pair_exclusive(
            seal,
            binding,
            seal={"schema": "seal"},
            binding={"schema": "binding"},
        )

    assert not seal.exists()
    assert binding.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_preopen_removes_only_collection_binding_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "_source_binds_protocol_revision",
        lambda *_a, **_k: True,
    )
    before = recovery.recovery_preopen_validate(ROOT)
    assert before["blockers"] == [
        "new_unseen_holdout_not_collected_or_bound",
        "evaluator_not_bound_to_37_take_protocol",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]

    original_exists = Path.exists

    def exists(path: Path) -> bool:
        if path in {SEAL_PATH, BINDING_PATH}:
            return True
        return original_exists(path)

    authenticated = {
        "status": "passed",
        "holdout_collection_complete": True,
        "holdout_seal_authenticated": True,
        "holdout_binding_authenticated": True,
        "scientifically_opened": False,
        "scientific_artifact_contents_parsed": False,
        "scientific_outcomes_derived": False,
        "scientific_outputs_returned": False,
        "grant_created": False,
        "grant_consumed": False,
        "evaluation_run": False,
    }
    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(
        finalizer,
        "authenticate_existing_finalization",
        lambda _root: authenticated,
    )
    after = recovery.recovery_preopen_validate(ROOT)

    assert after["blockers"] == [
        "evaluator_not_bound_to_37_take_protocol",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    assert after["official_readiness"] == "no_go"
    assert after["holdout_collection_complete"] is True
    assert after["holdout_seal_authenticated"] is True
    assert after["holdout_binding_authenticated"] is True
    assert after["grant_creation_authorized"] is False
    assert after["grant_consumption_authorized"] is False
    assert after["evaluation_execution_authorized"] is False
    assert after["holdout_observation_opened"] is False
    assert after["content_derived_values_returned"] is False


def test_preopen_rejects_partial_finalization_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "_source_binds_protocol_revision",
        lambda *_a, **_k: True,
    )
    original_exists = Path.exists

    def exists(path: Path) -> bool:
        if path == SEAL_PATH:
            return True
        if path == BINDING_PATH:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(
        recovery.s4_8.S48Error,
        match="seal and binding are incomplete",
    ):
        recovery.recovery_preopen_validate(ROOT)
