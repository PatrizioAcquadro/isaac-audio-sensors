from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_AUDIO_SENSORS_OUTPUT_ROOT", str(tmp_path / "outputs"))
