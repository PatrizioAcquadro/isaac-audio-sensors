from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_gate_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/run_s2_review_remediation_gate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_s2_review_remediation_gate",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_path_supports_output_outside_repository(tmp_path: Path) -> None:
    gate = _load_gate_module()
    external_log = tmp_path / "outside" / "logs" / "gate.txt"

    assert gate._evidence_path(external_log) == str(external_log.resolve())


def test_evidence_path_keeps_repository_output_relative() -> None:
    gate = _load_gate_module()
    repository_log = gate.REPO_ROOT / "outputs/example/log.txt"

    assert gate._evidence_path(repository_log) == "outputs/example/log.txt"
