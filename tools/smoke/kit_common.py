"""Shared live Kit execution and USD helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isaac_audio_sensors.isaac.pose_resolver import (
    prim_path,
)


def _step(evidence: dict[str, Any], name: str, callback: Any) -> Any:
    try:
        result = callback()
    except Exception as exc:
        record = {
            "name": name,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        evidence["workflow_steps"].append(record)
        raise
    record = {
        "name": name,
        "status": "passed" if result is not None else "returned_none",
        "result_summary": _result_summary(result),
    }
    evidence["workflow_steps"].append(record)
    if result is None:
        raise RuntimeError(f"Workflow step {name!r} returned None.")
    return result


def _stringify_artifacts(artifacts: dict[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in sorted(artifacts.items())}


def _require_stage_prim(stage: Any, path: str) -> Any:
    prim = _stage_get_prim_at_path(stage, path)
    if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
        raise RuntimeError(f"Required prim is missing from live stage: {path}")
    return prim


def _result_summary(result: Any) -> Any:
    if isinstance(result, Path):
        return str(result)
    if isinstance(result, str | int | float | bool):
        return result
    if isinstance(result, tuple | list):
        return {"count": len(result), "items": [str(item) for item in result[:8]]}
    if isinstance(result, dict):
        return {
            str(key): _result_summary(value)
            for key, value in sorted(result.items())
            if key in {"enabled", "started", "writer_registered", "write_count"}
        }
    return type(result).__name__


def _stage_has_prim(stage: Any, path: str) -> bool:
    prim = _stage_get_prim_at_path(stage, path)
    if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
        return True
    if hasattr(stage, "Traverse"):
        return any(prim_path(prim) == path for prim in stage.Traverse())
    return False


def _stage_get_prim_at_path(stage: Any, path: str) -> Any | None:
    if not hasattr(stage, "GetPrimAtPath"):
        return None
    for candidate_path in (_usd_path(path), path):
        try:
            return stage.GetPrimAtPath(candidate_path)
        except TypeError:
            continue
    return None


def _usd_path(path: str) -> Any:
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return path
    try:
        return Sdf.Path(path)
    except Exception:
        return path


def _pump_kit_app(app: Any, *, updates: int = 4) -> dict[str, Any]:
    result: dict[str, Any] = {"requested_updates": updates, "called_updates": 0}
    update = getattr(app, "update", None)
    if not callable(update):
        result["status"] = "update_unavailable"
        return result
    for _ in range(updates):
        try:
            update()
            result["called_updates"] += 1
        except Exception as exc:  # noqa: BLE001 - diagnostic only.
            result["status"] = f"{type(exc).__name__}: {exc}"
            return result
    result["status"] = "updated"
    return result


def _prepare_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_file():
            item.unlink()
