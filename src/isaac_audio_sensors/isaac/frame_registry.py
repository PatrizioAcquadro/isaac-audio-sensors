"""Process-wide latest-frame registry for graph consumers."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_frames: dict[str, Any] = {}
_last_key: str | None = None


def publish_latest_frame(key: str, frame: Any) -> None:
    """Publish ``frame`` under ``key`` and mark it as the most recent."""

    global _last_key
    normalized = str(key or "").strip()
    if not normalized:
        return
    with _lock:
        _frames[normalized] = frame
        _last_key = normalized


def get_latest_frame(key: str | None = None) -> Any | None:
    """Return the frame for ``key``, or the most recently published one."""

    with _lock:
        if key:
            return _frames.get(str(key).strip())
        if _last_key is None:
            return None
        return _frames.get(_last_key)


def clear_latest_frames(key: str | None = None) -> None:
    """Drop one published frame, or all of them."""

    global _last_key
    with _lock:
        if key is None:
            _frames.clear()
            _last_key = None
            return
        _frames.pop(str(key).strip(), None)
        if _last_key not in _frames:
            _last_key = next(reversed(_frames), None) if _frames else None
