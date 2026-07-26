from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_4 import consume_s4_8_grant
from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    CANONICAL_PREREQUISITE,
    PREREQUISITE_BINDING_FIELDS,
    S47PrerequisiteError,
    validate_grant_prerequisite_binding,
    validate_s4_7_corrective_03_prerequisite,
)

ROOT = Path(__file__).resolve().parents[1]
SEAL = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/holdout_seal.v1.json"
)


def test_s4_8_consumer_requires_corrective_03_authenticator() -> None:
    source = inspect.getsource(consume_s4_8_grant)
    assert "s4_7_prerequisite_corrective_03" in source
    assert "validate_s4_7_corrective_03_prerequisite" in source
    assert "validate_s4_7_corrective_02_prerequisite" not in source


def test_corrective_02_prerequisite_is_stale_for_canonical_consumer() -> None:
    stale = (
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.7_corrective_02/"
        "holdout_acceptance.json"
    )
    with pytest.raises(S47PrerequisiteError, match="path must be canonical"):
        validate_s4_7_corrective_03_prerequisite(
            stale,
            seal_path=SEAL,
            require_committed=False,
            verify_replay=False,
        )


def test_grant_binding_includes_exact_scientific_semantics_hash() -> None:
    assert "scientific_semantics_sha256" in PREREQUISITE_BINDING_FIELDS
    authenticated = {
        key: f"value-{key}" for key in PREREQUISITE_BINDING_FIELDS
    }
    validate_grant_prerequisite_binding(dict(authenticated), authenticated)
    altered = dict(authenticated)
    altered["scientific_semantics_sha256"] = "0" * 64
    with pytest.raises(S47PrerequisiteError, match="identity binding mismatch"):
        validate_grant_prerequisite_binding(altered, authenticated)


def test_minimal_or_arbitrary_grant_prerequisite_binding_is_rejected() -> None:
    authenticated = {
        key: f"value-{key}" for key in PREREQUISITE_BINDING_FIELDS
    }
    with pytest.raises(S47PrerequisiteError, match="fields mismatch"):
        validate_grant_prerequisite_binding(
            {"schema": "passed", "effective_semantics": "anything"},
            authenticated,
        )


def test_canonical_path_is_versioned_corrective_03() -> None:
    assert CANONICAL_PREREQUISITE.as_posix() == (
        "outputs/isaac_audio_sensors/S4/S4.7_corrective_03/"
        "holdout_acceptance.json"
    )
