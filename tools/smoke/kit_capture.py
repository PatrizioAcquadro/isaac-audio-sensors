"""Viewport and application capture in the live Kit gate."""

from __future__ import annotations

import asyncio
import inspect
import json
import struct
from contextlib import suppress
from pathlib import Path
from typing import Any

from kit_common import (
    _result_summary,
)


def _capture_app_screenshot(path: Path) -> dict[str, Any]:
    """Capture the whole app swapchain (viewport plus Kit UI windows)."""

    attempts: list[dict[str, Any]] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        path.unlink()
    attempts.append(_attempt_renderer_swapchain_capture(path))
    record = _captured_screenshot_record(
        path=path,
        method="renderer_capture.capture_next_frame_swapchain",
        attempts=attempts,
        framed_paths=(),
    )
    if record is not None:
        return record
    return _screenshot_unavailable(
        path,
        reason=_last_attempt_reason(attempts),
        attempts=attempts,
        framed_paths=(),
    )


def _settle_kit_ui(*, updates: int = 4) -> None:
    with suppress(Exception):
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        for _ in range(updates):
            app.update()


def _capture_viewport_screenshot(
    path: Path,
    *,
    framed_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    framed = tuple(path for path in framed_paths if path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        path.unlink()

    try:
        import omni.kit.viewport.utility as viewport_utility  # type: ignore

        viewport = viewport_utility.get_active_viewport()
        if viewport is None:
            return _screenshot_unavailable(
                path,
                reason="no active viewport",
                attempts=attempts,
                framed_paths=framed,
            )
        viewport_info = _viewport_info(viewport)
        _frame_viewport_paths(
            viewport_utility=viewport_utility,
            viewport=viewport,
            framed_paths=framed,
            attempts=attempts,
        )
        attempts.append(
            _attempt_viewport_utility_capture(
                utility_capture=viewport_utility.capture_viewport_to_file,
                viewport=viewport,
                path=path,
            )
        )
        record = _captured_screenshot_record(
            path=path,
            method="viewport_utility.capture_viewport_to_file",
            attempts=attempts,
            framed_paths=framed,
            viewport_info=viewport_info,
        )
        if record is not None:
            return record
        return _screenshot_unavailable(
            path,
            reason=_last_attempt_reason(attempts),
            attempts=attempts,
            framed_paths=framed,
            viewport_info=viewport_info,
        )
    except Exception as exc:  # noqa: BLE001 - screenshot is optional evidence.
        attempts.append(
            {
                "method": "capture_viewport_screenshot",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return _screenshot_unavailable(
            path,
            reason=f"{type(exc).__name__}: {exc}",
            attempts=attempts,
            framed_paths=framed,
        )


def _frame_viewport_paths(
    *,
    viewport_utility: Any,
    viewport: Any,
    framed_paths: tuple[str, ...],
    attempts: list[dict[str, Any]],
) -> None:
    if not framed_paths:
        return
    frame = getattr(viewport_utility, "frame_viewport_prims", None)
    if not callable(frame):
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "unavailable",
                "reason": "frame_viewport_prims is not callable",
                "framed_paths": list(framed_paths),
            }
        )
        return
    try:
        framed = frame(viewport, prims=list(framed_paths))
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "passed" if framed else "returned_false",
                "framed_paths": list(framed_paths),
            }
        )
    except Exception as exc:  # noqa: BLE001 - framing failure is diagnostic only.
        attempts.append(
            {
                "method": "viewport_utility.frame_viewport_prims",
                "status": "failed",
                "framed_paths": list(framed_paths),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )


def _attempt_viewport_utility_capture(
    *,
    utility_capture: Any,
    viewport: Any,
    path: Path,
) -> dict[str, Any]:
    try:
        result = utility_capture(viewport, file_path=str(path))
        wait_result = _wait_for_capture_result(result)
        return {
            "method": "viewport_utility.capture_viewport_to_file",
            "status": "called",
            "result": str(result),
            "wait_result": _result_summary(wait_result),
            "file_wait": _wait_for_screenshot_file(path),
        }
    except Exception as exc:  # noqa: BLE001 - record current API failure.
        return {
            "method": "viewport_utility.capture_viewport_to_file",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _attempt_renderer_swapchain_capture(path: Path) -> dict[str, Any]:
    try:
        import omni.kit.renderer_capture as renderer_capture  # type: ignore

        renderer = renderer_capture.acquire_renderer_capture_interface()
        capture = getattr(renderer, "capture_next_frame_swapchain", None)
        if not callable(capture):
            return {
                "method": "renderer_capture.capture_next_frame_swapchain",
                "status": "unavailable",
                "reason": "capture_next_frame_swapchain is not callable",
            }
        result = capture(str(path))
        wait_async = getattr(renderer, "wait_async_capture", None)
        wait_result = _wait_for_capture_result(
            wait_async() if callable(wait_async) else None
        )
        return {
            "method": "renderer_capture.capture_next_frame_swapchain",
            "status": "called",
            "result": str(result),
            "wait_result": _result_summary(wait_result),
            "file_wait": _wait_for_screenshot_file(path),
        }
    except Exception as exc:  # noqa: BLE001 - report the exact renderer error.
        return {
            "method": "renderer_capture.capture_next_frame_swapchain",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _wait_for_capture_result(result: Any) -> Any:
    if result is None:
        return None
    for method_name in ("wait", "wait_for_result"):
        method = getattr(result, method_name, None)
        if callable(method):
            value = method()
            if inspect.isawaitable(value):
                return _run_capture_awaitable(value)
            return value
    if inspect.isawaitable(result):
        return _run_capture_awaitable(result)
    return None


def _run_capture_awaitable(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        return "event_loop_running_wait_skipped"
    return loop.run_until_complete(awaitable)


def _wait_for_screenshot_file(path: Path, *, max_updates: int = 240) -> dict[str, Any]:
    if _png_info(path) is not None:
        return {"status": "ready", "updates": 0}
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        update = getattr(app, "update", None) if app is not None else None
        if not callable(update):
            return {
                "status": "unavailable",
                "reason": "omni.kit.app.get_app().update is not callable",
                "updates": 0,
            }
        for index in range(max_updates):
            update()
            if _png_info(path) is not None:
                return {"status": "ready", "updates": index + 1}
        return {"status": "not_ready", "updates": max_updates}
    except Exception as exc:  # noqa: BLE001 - screenshot waiting is diagnostic.
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _captured_screenshot_record(
    *,
    path: Path,
    method: str,
    attempts: list[dict[str, Any]],
    framed_paths: tuple[str, ...],
    viewport_info: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    png = _png_info(path)
    if png is None:
        return None
    return {
        "status": "captured",
        "path": str(path),
        "method": method,
        "file_size_bytes": path.stat().st_size,
        "width": png["width"],
        "height": png["height"],
        "viewport_api_type": (viewport_info or {}).get("viewport_api_type"),
        "camera_path": (viewport_info or {}).get("camera_path"),
        "framed_paths": list(framed_paths),
        "attempts": attempts,
    }


def _screenshot_unavailable(
    path: Path,
    *,
    reason: str,
    attempts: list[dict[str, Any]],
    framed_paths: tuple[str, ...],
    viewport_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    png = _png_info(path)
    return {
        "status": "unavailable",
        "path": str(path),
        "reason": reason,
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
        "width": None if png is None else png["width"],
        "height": None if png is None else png["height"],
        "viewport_api_type": (viewport_info or {}).get("viewport_api_type"),
        "camera_path": (viewport_info or {}).get("camera_path"),
        "framed_paths": list(framed_paths),
        "attempts": attempts,
    }


def _viewport_info(viewport: Any) -> dict[str, Any]:
    camera = getattr(viewport, "camera_path", None)
    return {
        "viewport_api_type": type(viewport).__name__,
        "camera_path": str(getattr(camera, "pathString", camera or "")) or None,
    }


def _png_info(path: Path) -> dict[str, int] | None:
    if not path.is_file() or path.stat().st_size < 24:
        return None
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _last_attempt_reason(attempts: list[dict[str, Any]]) -> str:
    for attempt in reversed(attempts):
        if attempt.get("error"):
            return f"{attempt.get('method')}: {attempt.get('error')}"
        if attempt.get("reason"):
            return f"{attempt.get('method')}: {attempt.get('reason')}"
        if attempt.get("status") == "called":
            return f"{attempt.get('method')} did not create a readable PNG"
    return "no screenshot capture attempts were available"


def _enforce_required_screenshot(record: dict[str, Any], fixture_kind: str) -> None:
    if record.get("status") == "captured":
        return
    raise RuntimeError(
        "Viewport screenshot capture is required for "
        f"{fixture_kind} but failed: {json.dumps(record, sort_keys=True)}"
    )
