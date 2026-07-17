"""Hermetic tests for the installed-artifact external-consumer harness."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_gate_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_installed_consumer_gate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_installed_consumer_gate", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake_consumer(tmp_path: Path) -> Path:
    """Build a committed consumer without importing the real external checkout."""

    consumer = tmp_path / "consumer"
    (consumer / "adapters").mkdir(parents=True)
    (consumer / "tests").mkdir()
    (consumer / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    (consumer / "adapters" / "fake_adapter.py").write_text(
        "def adapt(value):\n    return {'value': value}\n",
        encoding="utf-8",
    )
    (consumer / "tests" / "test_contract.py").write_text(
        "def test_minimal_contract():\n    assert {'value': 1} == {'value': 1}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(consumer)], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "config", "user.name", "Gate Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(consumer),
            "config",
            "user.email",
            "gate-test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(consumer), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "commit", "-q", "-m", "fake consumer"],
        check=True,
    )
    return consumer


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_consumer_snapshot_detects_worktree_modification(fake_consumer: Path):
    gate = _load_gate_module()
    before = gate.snapshot_consumer(fake_consumer)

    (fake_consumer / "gate-must-not-write.txt").write_text(
        "violation\n", encoding="utf-8"
    )
    after = gate.snapshot_consumer(fake_consumer)

    assert before.revision == after.revision
    assert before.status_porcelain == ""
    assert "gate-must-not-write.txt" in after.status_porcelain
    with pytest.raises(gate.ConsumerGateError, match="modified during gate"):
        gate.assert_consumer_unchanged(before, after)


def test_consumer_snapshot_detects_revision_change(fake_consumer: Path):
    gate = _load_gate_module()
    before = gate.snapshot_consumer(fake_consumer)
    marker = fake_consumer / "new-contract.txt"
    marker.write_text("new\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(fake_consumer), "add", marker.name], check=True)
    subprocess.run(
        ["git", "-C", str(fake_consumer), "commit", "-q", "-m", "new head"],
        check=True,
    )

    after = gate.snapshot_consumer(fake_consumer)

    with pytest.raises(gate.ConsumerGateError, match="revision changed"):
        gate.assert_consumer_unchanged(before, after)


def test_consumer_snapshot_allows_identical_preexisting_dirt(fake_consumer: Path):
    gate = _load_gate_module()
    dirty_path = fake_consumer / "preexisting-local-note.txt"
    dirty_path.write_text("keep me\n", encoding="utf-8")

    before = gate.snapshot_consumer(fake_consumer)
    after = gate.snapshot_consumer(fake_consumer)

    assert before.status_porcelain != ""
    gate.assert_consumer_unchanged(before, after)


def test_consumer_environment_is_sanitized():
    gate = _load_gate_module()
    source = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/sensor/checkout/src",
        "PYTHONHOME": "/host/python",
        "PIP_INDEX_URL": "https://example.invalid/simple",
        "PIP_REQUIRE_VIRTUALENV": "1",
        "KEEP_ME": "yes",
    }

    clean, delta = gate.build_sanitized_env(
        source,
        additions={
            "PYTHONPATH": "/external/consumer",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )

    assert clean["PYTHONPATH"] == "/external/consumer"
    assert clean["PYTHONDONTWRITEBYTECODE"] == "1"
    assert clean["PYTHONNOUSERSITE"] == "1"
    assert clean["KEEP_ME"] == "yes"
    assert "PYTHONHOME" not in clean
    assert not any(name.startswith("PIP_") for name in clean)
    assert delta["removed"] == [
        "PIP_INDEX_URL",
        "PIP_REQUIRE_VIRTUALENV",
        "PYTHONHOME",
        "PYTHONPATH",
    ]


def test_sha256sums_exact_wheel_verification(tmp_path: Path):
    gate = _load_gate_module()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel = dist_dir / "isaac_audio_sensors-9.8.7-py3-none-any.whl"
    wheel.write_bytes(b"synthetic wheel")
    (dist_dir / "SHA256SUMS").write_text(
        f"{_sha256(wheel)}  {wheel.name}\n", encoding="utf-8"
    )

    checksums = gate.parse_sha256sums(dist_dir / "SHA256SUMS")
    verified = gate.verify_wheel(dist_dir)

    assert checksums[wheel.name] == _sha256(wheel)
    assert verified["path"] == str(wheel)
    assert verified["sha256"] == _sha256(wheel)

    wheel.write_bytes(b"mutated")
    with pytest.raises(gate.ConsumerGateError, match="SHA-256 mismatch"):
        gate.verify_wheel(dist_dir)


@pytest.mark.parametrize(
    ("first", "second", "identical"),
    [(b'{"a":1}\n', b'{"a":1}\n', True), (b'{"a":1}\n', b'{"a":2}\n', False)],
)
def test_determinism_comparator(
    tmp_path: Path,
    first: bytes,
    second: bytes,
    identical: bool,
):
    gate = _load_gate_module()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_bytes(first)
    second_path.write_bytes(second)

    result = gate.compare_determinism_outputs(first_path, second_path)

    assert result["identical"] is identical
    assert result["first_sha256"] == hashlib.sha256(first).hexdigest()
    assert result["second_sha256"] == hashlib.sha256(second).hexdigest()


def test_boundary_scanner_reports_file_line_and_token(tmp_path: Path):
    gate = _load_gate_module()
    package_dir = tmp_path / "site-packages" / "isaac_audio_sensors"
    package_dir.mkdir(parents=True)
    (package_dir / "clean.py").write_text("GENERIC = True\n", encoding="utf-8")
    planted_token = "auditory" + "_cue"
    (package_dir / "leak.py").write_text(
        f"GENERIC = True\nLEAK = {planted_token!r}\n", encoding="utf-8"
    )

    result = gate.scan_installed_boundary(package_dir)

    assert result["passed"] is False
    assert result["files_scanned"] == 2
    assert result["hits"] == [
        {
            "file": "leak.py",
            "line": 2,
            "token": planted_token,
            "text": f"LEAK = {planted_token!r}",
        }
    ]


def test_blocked_and_failed_classification_are_distinct(tmp_path: Path):
    gate = _load_gate_module()

    with pytest.raises(gate.ConsumerGateBlocked, match="missing") as blocked:
        gate.snapshot_consumer(tmp_path / "missing-consumer")

    assert gate.classify_exception(blocked.value) == "blocked"
    assert (
        gate.classify_exception(gate.ConsumerGateBlocked("dependency unavailable"))
        == "blocked"
    )
    assert (
        gate.classify_exception(gate.ConsumerGateError("contract mismatch"))
        == "failed"
    )
