from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]


def _original_artifacts_present() -> bool:
    amendment = recovery.load_amendment(ROOT)
    return all(
        (ROOT / record["path"]).is_file()
        for record in amendment["original_run"]["artifacts"].values()
    )


@pytest.mark.skipif(
    not _original_artifacts_present(),
    reason="machine-local immutable first-run artifacts are unavailable",
)
def test_recovery_gate_authenticates_exact_original_without_observations() -> None:
    result = recovery.validate_original_failure(ROOT)
    assert result["status"] == "passed"
    assert result["terminal_status"] == "failed"
    assert result["evaluation_state"] == "not_evaluated"
    assert result["completed_observation_count"] == 0
    assert result["derived_observation_count"] == 0
    assert result["raw_holdout_read"] is False


@pytest.fixture
def original_failure_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object]]:
    if not _original_artifacts_present():
        pytest.skip("machine-local immutable first-run artifacts are unavailable")
    amendment = copy.deepcopy(recovery.load_amendment(ROOT))
    paths = amendment["original_run"]["artifacts"]
    for record in paths.values():
        source = ROOT / record["path"]
        destination = tmp_path / record["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    package = ROOT / "outputs/isaac_audio_sensors/S4/S4.8"
    destination_package = tmp_path / "outputs/isaac_audio_sensors/S4/S4.8"
    for source in package.iterdir():
        if source.is_file():
            destination = destination_package / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    base = s4_8.load_contract(ROOT)
    monkeypatch.setattr(recovery, "load_amendment", lambda _root: amendment)
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: copy.deepcopy(base))
    return tmp_path, amendment


@pytest.mark.parametrize(
    "artifact",
    [
        "grant",
        "authorization",
        "ledger",
        "journal",
        "derived_terminal_state",
        "terminal_manifest",
        "final_validation",
    ],
)
def test_recovery_gate_rejects_original_artifact_tampering(
    original_failure_root: tuple[Path, dict[str, object]],
    artifact: str,
) -> None:
    root, amendment = original_failure_root
    path = root / amendment["original_run"]["artifacts"][artifact]["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(s4_8.S48Error, match="original artifact mismatch"):
        recovery.validate_original_failure(root)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "scientific_observation_opened", True
        ),
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "scientific_observations_derived", True
        ),
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "analysis_completed", True
        ),
        lambda derived: derived["payload"]["takes"].append({"derived": True}),
        lambda derived: derived.__setitem__("evaluation_state", "evaluation_completed"),
        lambda derived: derived["run_failure"].__setitem__(
            "error", "different failure"
        ),
    ],
    ids=[
        "observation-opened",
        "observation-derived",
        "analysis-completed",
        "payload-derived",
        "evaluation-completed",
        "different-failure",
    ],
)
def test_recovery_gate_rejects_ineligible_scientific_state(
    original_failure_root: tuple[Path, dict[str, object]],
    mutation,
) -> None:
    root, amendment = original_failure_root
    record = amendment["original_run"]["artifacts"]["derived_terminal_state"]
    path = root / record["path"]
    derived = s4_8.load_json(path)
    mutation(derived)
    if "payload" in derived:
        derived["payload_sha256"] = s4_8.canonical_sha256(derived["payload"])
    path.write_text(s4_8.pretty_json(derived), encoding="utf-8")
    record["sha256"] = s4_8.sha256_file(path)
    with pytest.raises(
        s4_8.S48Error,
        match="FAILED/NOT_EVALUATED|ineligible",
    ):
        recovery.validate_original_failure(root)


def test_recovery_gate_rejects_progress_or_provisional_state(
    original_failure_root: tuple[Path, dict[str, object]],
) -> None:
    root, amendment = original_failure_root
    journal = (
        root / amendment["original_run"]["artifacts"]["journal"]["path"]
    )
    progress = journal.with_name(s4_8.POST_CONSUMPTION_PROGRESS_NAME)
    progress.mkdir()
    with pytest.raises(s4_8.S48Error, match="progress or provisional"):
        recovery.validate_original_failure(root)


def test_recovery_amendment_uses_new_paths_and_keeps_authority_closed() -> None:
    amendment = recovery.load_amendment(ROOT)
    original_paths = {
        record["path"]
        for record in amendment["original_run"]["artifacts"].values()
    }
    future = amendment["future_attempt"]
    assert {
        future["grant_path"],
        future["ledger_path"],
        future["journal_path"],
        future["derived_input_path"],
        future["output_path"],
    }.isdisjoint(original_paths)
    assert future["grant_creation_authorized"] is False
    assert future["grant_consumption_authorized"] is False
    assert future["automatic_retry_of_original"] is False
    assert future["independent_review_required"] is True
    assert future["new_explicit_authorization_required"] is True


def test_grant_creation_requires_future_independent_review(
    tmp_path: Path,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    with pytest.raises(
        (OSError, s4_8.S48Error),
        match="independent_review|No such file",
    ):
        recovery._validate_independent_review(
            tmp_path,
            amendment=amendment,
            source_commit="a" * 40,
        )


def test_independent_review_must_bind_exact_candidate_source(
    tmp_path: Path,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    path = tmp_path / amendment["future_attempt"]["independent_review_path"]
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "ias.s4_8.independent_recovery_review.v1",
                "amendment_id": amendment["amendment_id"],
                "source_commit": "b" * 40,
                "decision": "approved",
                "independent": True,
                "reviewer_id": "reviewer",
                "reviewed_at_utc": "2030-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(s4_8.S48Error, match="independent review"):
        recovery._validate_independent_review(
            tmp_path,
            amendment=amendment,
            source_commit="a" * 40,
        )
