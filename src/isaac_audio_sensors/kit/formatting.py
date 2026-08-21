"""Human-readable summary/formatting helpers for GUI labels."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from isaac_audio_sensors.isaac.pose_resolver import quat_from_any, vec3_from_any

from .state import DiscoveredPrimSummary, ExtensionUiState


def _summary_ids(items: tuple[DiscoveredPrimSummary, ...]) -> str:
    return ", ".join(f"{item.id}@{item.prim_path}" for item in items) or "none"


def _profile_summary_text(state: ExtensionUiState) -> str:
    selected = next(
        (
            profile
            for profile in state.profile_library
            if profile.profile_id == state.selected_profile_id
        ),
        None,
    )
    selected_text = (
        "none"
        if selected is None
        else (
            f"{selected.display_label} | class={selected.class_label} | "
            f"asset={selected.audio_asset_path}"
        )
    )
    library_ids = ", ".join(profile.profile_id for profile in state.profile_library)
    applied = state.applied_source_profile.get("profile_id") or "none"
    return (
        f"Profile: {selected_text} | selected={state.selected_profile_id or 'none'} | "
        f"applied={applied} | library={library_ids or 'none'}"
    )


def _rig_profile_summary_text(state: ExtensionUiState) -> str:
    selected = next(
        (
            profile
            for profile in state.rig_profile_library
            if profile.profile_id == state.selected_rig_profile_id
        ),
        None,
    )
    selected_text = (
        "none"
        if selected is None
        else (
            f"{selected.display_label} | mics={len(selected.microphone_ids)} | "
            f"mount={selected.recommended_mount_prim_path or 'none'}"
        )
    )
    library_ids = ", ".join(profile.profile_id for profile in state.rig_profile_library)
    applied = state.applied_array_rig_profile.get("profile_id") or "none"
    return (
        f"Rig: {selected_text} | "
        f"selected={state.selected_rig_profile_id or 'none'} | "
        f"applied={applied} | library={library_ids or 'none'}"
    )


def _optional_quat_text(value: Iterable[float] | None) -> str:
    if value is None:
        return "none"
    x, y, z, w = quat_from_any(value)
    return f"({x:.2f}, {y:.2f}, {z:.2f}, {w:.2f})"


def _format_mic_positions_summary(
    values: Mapping[str, tuple[float, float, float]],
) -> str:
    if not values:
        return "none"
    order = {"front": 0, "right": 1, "rear": 2, "left": 3}
    items = sorted(values.items(), key=lambda item: (order.get(item[0], 99), item[0]))
    return "; ".join(f"{mic_id}:{_format_vec3(value)}" for mic_id, value in items)


def _frame_is_new(previous_frame: Any | None, frame: Any) -> bool:
    if previous_frame is None:
        return True
    previous_id = getattr(previous_frame, "frame_id", None)
    current_id = getattr(frame, "frame_id", None)
    if previous_id is None or current_id is None:
        return frame is not previous_frame
    return current_id != previous_id


def _aggregate_rms_from_frame(frame: Any) -> dict[str, float]:
    raw = getattr(frame, "aggregate_per_mic_rms", {}) or {}
    rms: dict[str, float] = {}
    for mic_id, value in dict(raw).items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            rms[str(mic_id)] = numeric
    return rms


def _optional_vec3_text(value: tuple[float, float, float] | None) -> str:
    return "none" if value is None else _format_vec3(value)


def _format_vec3(value: Iterable[float]) -> str:
    x, y, z = vec3_from_any(value)
    return f"({x:.2f}, {y:.2f}, {z:.2f})"


def _vec_close(
    left: Iterable[float],
    right: Iterable[float],
    *,
    tolerance: float = 1e-6,
) -> bool:
    """Component-wise closeness for position/quaternion change detection."""

    left_values = tuple(float(value) for value in left)
    right_values = tuple(float(value) for value in right)
    if len(left_values) != len(right_values):
        return False
    return all(
        abs(a - b) <= tolerance for a, b in zip(left_values, right_values, strict=True)
    )
