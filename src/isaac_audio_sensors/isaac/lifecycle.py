"""Lazy Isaac timeline and update-stream helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable


def current_timeline_time_s() -> float | None:
    try:
        import omni.timeline  # type: ignore
    except ImportError:
        return None
    timeline = omni.timeline.get_timeline_interface()
    if hasattr(timeline, "get_current_time"):
        return float(timeline.get_current_time())
    if hasattr(timeline, "get_current_time_seconds"):
        return float(timeline.get_current_time_seconds())
    return None


def subscribe_to_updates(callback: Callable[[Any], None], *, name: str) -> Any:
    try:
        import omni.kit.app  # type: ignore
    except ImportError as exc:
        raise IsaacIntegrationUnavailable(
            "Isaac update-stream subscription requires omni.kit.app inside "
            "an Isaac Sim Python environment."
        ) from exc
    get_stream = getattr(omni.kit.app.get_app(), "get_update_event_stream", None)
    if not callable(get_stream):
        raise IsaacIntegrationUnavailable(
            "Isaac update-stream subscription requires get_update_event_stream."
        )
    subscribe = getattr(get_stream(), "create_subscription_to_pop", None)
    if not callable(subscribe):
        raise IsaacIntegrationUnavailable(
            "Isaac update-stream subscription requires create_subscription_to_pop."
        )
    return subscribe(callback, name=name)


def subscribe_to_timeline_resets(
    callback: Callable[[], None],
    *,
    name: str,
) -> Any | None:
    try:
        import omni.timeline  # type: ignore
    except ImportError:
        return None
    timeline = omni.timeline.get_timeline_interface()
    get_stream = getattr(timeline, "get_timeline_event_stream", None)
    if not callable(get_stream):
        return None
    subscribe = getattr(get_stream(), "create_subscription_to_pop", None)
    if not callable(subscribe):
        return None

    def _on_event(event: Any) -> None:
        if _is_reset_event(event, omni.timeline):
            callback()

    return subscribe(_on_event, name=name)


def _is_reset_event(event: Any, timeline_module: Any) -> bool:
    event_type = getattr(event, "type", event)
    enum = getattr(timeline_module, "TimelineEventType", None)
    reset_values = {
        getattr(enum, value)
        for value in ("STOP", "RESET")
        if enum is not None and hasattr(enum, value)
    }
    if event_type in reset_values:
        return True
    text = str(event_type).upper()
    return text in {"STOP", "RESET"} or text.endswith((".STOP", ".RESET"))
