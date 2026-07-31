"""Pure structural profiles for S4.8 recovery amendment-02 results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

INPUT_CONTRACT_REJECTED_PROFILE = "evaluation_input_contract_rejected.v1"


def is_input_contract_rejected(evaluation: Mapping[str, Any]) -> bool:
    """Return whether an evaluation is the frozen adverse-input profile."""

    identity = evaluation.get("identity_summary")
    return (
        evaluation.get("status") == "failed"
        and evaluation.get("readiness_passed") is False
        and evaluation.get("failed_gating_criteria")
        == ["evaluation_input_contract_rejected"]
        and evaluation.get("criteria") == []
        and evaluation.get("comparison_classifications") == []
        and evaluation.get("categorical_take_results") == []
        and isinstance(evaluation.get("evaluation_error"), str)
        and bool(evaluation["evaluation_error"])
        and isinstance(identity, Mapping)
        and identity.get("input_contract_adverse") is True
        and evaluation.get("holdout_observations_accessed_by_evaluator") == 0
    )


def require_input_contract_rejected(evaluation: Mapping[str, Any]) -> str:
    """Require the frozen adverse-input profile and return its identifier."""

    if not is_input_contract_rejected(evaluation):
        raise ValueError("S4.8 recovery amendment-02 adverse profile mismatch")
    return INPUT_CONTRACT_REJECTED_PROFILE


__all__ = [
    "INPUT_CONTRACT_REJECTED_PROFILE",
    "is_input_contract_rejected",
    "require_input_contract_rejected",
]
