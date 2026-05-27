"""Security-focused tests for support-tool redaction."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script(module_name: str, relative_path: str):
    script_path = Path(__file__).resolve().parents[1] / relative_path
    scripts_dir = script_path.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discover_redacts_sensitive_isaac_and_omni_environment(monkeypatch):
    discover_module = _load_script(
        "discover_isaac_runtimes_test",
        "scripts/discover_isaac_runtimes.py",
    )
    monkeypatch.setenv("ISAAC_SECRET_TOKEN", "isaac-token-secret")
    monkeypatch.setenv("OMNI_API_KEY", "omni-api-key-secret")
    monkeypatch.setenv("ISAAC_SIM_PATH", "/opt/isaac-sim")

    result = discover_module.discover()
    environment = result["environment"]

    assert environment["ISAAC_SECRET_TOKEN"] == "<redacted>"
    assert environment["OMNI_API_KEY"] == "<redacted>"
    assert environment["ISAAC_SIM_PATH"] == "/opt/isaac-sim"


def test_diagnostic_command_output_is_redacted_before_json_collection():
    diagnose_module = _load_script(
        "diagnose_isaac_gpu_audio_test",
        "scripts/diagnose_isaac_gpu_audio.py",
    )
    spec = diagnose_module.CommandSpec(
        "python_secret",
        (
            sys.executable,
            "-c",
            "import sys; print('TOKEN=diagnostic-secret-token'); "
            "print('Bearer stderr-secret-token', file=sys.stderr)",
        ),
        timeout_s=10,
    )

    result = diagnose_module._run_command(spec)

    assert result["status"] == "ran"
    assert "diagnostic-secret-token" not in result["stdout"]
    assert "stderr-secret-token" not in result["stderr"]
    assert "<redacted>" in result["stdout"]
    assert "<redacted>" in result["stderr"]


def test_diagnostic_text_artifacts_are_redacted(tmp_path):
    diagnose_module = _load_script(
        "diagnose_isaac_gpu_audio_artifact_test",
        "scripts/diagnose_isaac_gpu_audio.py",
    )
    spec = diagnose_module.CommandSpec("secret_command", ("secret-command",))
    output_path = tmp_path / "secret_command.txt"

    diagnose_module._write_command_text(
        output_path,
        spec,
        {
            "status": "ran",
            "exit_code": 0,
            "stdout": "OMNI_API_KEY=raw-command-secret",
            "stderr": "Bearer another-command-secret",
        },
    )

    text = output_path.read_text(encoding="utf-8")
    assert "raw-command-secret" not in text
    assert "another-command-secret" not in text
    assert text.count("<redacted>") == 2


def test_diagnostic_environment_and_file_reads_are_redacted(
    monkeypatch,
    tmp_path,
):
    diagnose_module = _load_script(
        "diagnose_isaac_gpu_audio_env_test",
        "scripts/diagnose_isaac_gpu_audio.py",
    )
    monkeypatch.setenv("XAUTHORITY", "raw-xauthority-secret")
    monkeypatch.setenv("OMNI_KIT_ACCEPT_EULA", "YES")

    environment = diagnose_module._collect_environment()

    assert environment["XAUTHORITY"] == "<redacted>"
    assert environment["OMNI_KIT_ACCEPT_EULA"] == "YES"

    probed_file = tmp_path / "driver-info.txt"
    probed_file.write_text("password=raw-file-secret\n", encoding="utf-8")

    text = diagnose_module._read_text(probed_file)
    assert "raw-file-secret" not in text
    assert "password=<redacted>" in text
