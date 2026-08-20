from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.recording import export_session_flac

REFERENCE_SESSION = Path("tests/fixtures/recording/session")


def test_flac_export_missing_dependency_is_explicit_and_atomic(monkeypatch, tmp_path):
    destination = tmp_path / "missing_dependency"
    original_import = builtins.__import__

    def missing(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "soundfile":
            raise ImportError("soundfile unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "soundfile", raising=False)
    monkeypatch.setattr(builtins, "__import__", missing)

    with pytest.raises(OptionalDependencyUnavailable, match="soundfile"):
        export_session_flac(REFERENCE_SESSION, destination, dataset_id="missing_codec")
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".missing_dependency.flac-export-*"))


@pytest.mark.parametrize("dtype", ("float32", "int32", "bad"))
def test_flac_export_rejects_unsupported_dtype(monkeypatch, tmp_path, dtype):
    monkeypatch.setitem(sys.modules, "soundfile", types.ModuleType("soundfile"))
    with pytest.raises(ValueError, match="int16.*int24"):
        export_session_flac(
            REFERENCE_SESSION,
            tmp_path / dtype,
            dataset_id=f"invalid_{dtype}",
            dtype=dtype,
        )
