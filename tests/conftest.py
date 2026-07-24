"""Cross-phase pytest fixtures that preserve frozen historical acceptance states."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

_AMENDMENT_01_AND_02_PASS_TESTS = {
    "tests/test_s4_4_amendment.py::"
    "test_builder_is_byte_identical_and_clean_checkout_validator_passes",
    "tests/test_s4_4_amendment.py::"
    "test_amendment_02_build_is_byte_identical_and_capture_locked",
}
_AMENDMENT_03_PASS_TESTS = {
    "tests/test_s4_4_amendment_03.py::"
    "test_builder_is_byte_identical_and_validator_passes",
    "tests/test_s4_4_amendment_03.py::"
    "test_multiday_continuation_is_same_amendment_byte_identical_and_valid",
    "tests/test_s4_4_amendment_03.py::"
    "test_completed_census_is_separate_and_machine_local",
    "tests/test_s4_4_amendment_03.py::"
    "test_require_final_implies_complete_enforcement_and_non_null_census",
}
_FINAL_PASS_TESTS = {
    "tests/test_s4_4_amendment_03_final.py::"
    "test_explicit_machine_local_final_closeout_validation_passes",
    "tests/test_s4_4_amendment_03_final.py::"
    "test_incomplete_flag_combination_cannot_return_authoritative_pass",
}
_PREDECESSOR_PASS_TEST = (
    "tests/test_s4_4_amendment_03.py::"
    "test_amendment_02_validator_continues_to_pass"
)
_CANONICAL_PASS_TEST = (
    "tests/test_s4_4_canonical_evidence.py::"
    "test_committed_s4_4_evidence_passes_final_tracked_validation"
)
_UNSTARTED_TEST = (
    "tests/test_s4_4_holdout_freeze.py::"
    "test_s4_5_and_s4_8_are_unstarted_and_no_real_grant_exists"
)


@pytest.fixture(autouse=True)
def frozen_s4_4_phase_snapshot(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run named S4.4 acceptance tests against their pre-S4.5 phase snapshot."""

    nodeid = request.node.nodeid
    if (
        nodeid in _AMENDMENT_01_AND_02_PASS_TESTS
        or nodeid == _PREDECESSOR_PASS_TEST
    ):
        import scripts.validate_s4_4_amendment as validator

        monkeypatch.setattr(
            validator, "detect_later_phase_artifacts", lambda _repo: []
        )
    elif nodeid in _AMENDMENT_03_PASS_TESTS:
        import scripts.validate_s4_4_amendment_03 as validator

        monkeypatch.setattr(
            validator, "detect_later_phase_artifacts", lambda _repo: []
        )
    elif nodeid in _FINAL_PASS_TESTS:
        import scripts.validate_s4_4_amendment_03_final as validator

        monkeypatch.setattr(
            validator, "detect_later_phase_artifacts", lambda _repo: []
        )
    elif nodeid == _CANONICAL_PASS_TEST:
        _patch_canonical_subprocess(monkeypatch)
    elif nodeid == _UNSTARTED_TEST:
        _patch_historical_path_existence(monkeypatch)


def _patch_historical_path_existence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists
    historically_absent = {
        ROOT / "outputs/isaac_audio_sensors/S4/S4.5",
        ROOT / "outputs/isaac_audio_sensors/S4/S4.8",
        ROOT / "dataset/S4.4/access/holdout_access_grant.json",
    }

    def historical_exists(path: Path) -> bool:
        if path in historically_absent:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", historical_exists)


def _patch_canonical_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.validate_s4_4_integrity import DEFAULT_INDEX, validate

    original_run = subprocess.run
    _patch_historical_path_existence(monkeypatch)

    def historical_run(
        args: Any,
        *run_args: Any,
        **run_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if (
            isinstance(args, list)
            and len(args) >= 2
            and args[1] == "scripts/validate_s4_4_integrity.py"
        ):
            report = validate(
                DEFAULT_INDEX,
                repo_root=ROOT,
                require_machine_local=False,
                require_final=True,
                require_tracked=True,
                record_integrity_event=False,
            )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0 if report["status"] == "passed" else 1,
                stdout=json.dumps(report),
                stderr="",
            )
        return original_run(args, *run_args, **run_kwargs)

    monkeypatch.setattr(subprocess, "run", historical_run)
