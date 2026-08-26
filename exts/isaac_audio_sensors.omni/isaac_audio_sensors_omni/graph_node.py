"""Runtime OmniGraph node for the latest registered audio frame."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isaac_audio_sensors.core.types import AudioSensorFrame

NODE_TYPE_NAME = "isaac_audio_sensors.omni.IsaacAudioSensorFrame"
NODE_TYPE_VERSION = 1

_NODE_INPUTS = (("inputs:arrayKey", "token"),)
_NODE_OUTPUTS = (
    ("outputs:frameId", "token"),
    ("outputs:timestampMs", "int64"),
    ("outputs:detectionCount", "int"),
    ("outputs:bearingDeg", "double"),
    ("outputs:sector", "token"),
    ("outputs:micIds", "token[]"),
    ("outputs:micRms", "double[]"),
    ("outputs:occluded", "bool"),
    ("outputs:frameJson", "token"),
)


def frame_output_values(frame: AudioSensorFrame | None) -> dict[str, Any]:
    """Map an ``AudioSensorFrame`` (or ``None``) onto the node outputs."""

    if frame is None:
        return {
            "outputs:frameId": "",
            "outputs:timestampMs": 0,
            "outputs:detectionCount": 0,
            "outputs:bearingDeg": float("nan"),
            "outputs:sector": "",
            "outputs:micIds": [],
            "outputs:micRms": [],
            "outputs:occluded": False,
            "outputs:frameJson": "",
        }
    detections = frame.detections
    first = detections[0] if detections else None
    doa = first.doa if first is not None else None
    bearing = doa.estimated_bearing_deg if doa is not None else None
    aggregate_rms = frame.aggregate_per_mic_rms
    mic_ids = sorted(aggregate_rms)
    try:
        from isaac_audio_sensors.core.io.traces import frame_to_trace_dict

        frame_json = json.dumps(frame_to_trace_dict(frame), sort_keys=True)
    except Exception:  # noqa: BLE001 - optional output must not hide other fields.
        frame_json = ""
    return {
        "outputs:frameId": frame.frame_id,
        "outputs:timestampMs": frame.timestamp_ms,
        "outputs:detectionCount": len(detections),
        "outputs:bearingDeg": (float(bearing) if bearing is not None else float("nan")),
        "outputs:sector": "" if doa is None else str(doa.bearing_sector or ""),
        "outputs:micIds": mic_ids,
        "outputs:micRms": [float(aggregate_rms[mic_id]) for mic_id in mic_ids],
        "outputs:occluded": False if first is None else first.occluded,
        "outputs:frameJson": frame_json,
    }


class OgnIsaacAudioSensorFrame:
    """Pure-Python OmniGraph node type (runtime registration, no codegen)."""

    @staticmethod
    def get_node_type() -> str:
        return NODE_TYPE_NAME

    @staticmethod
    def initialize_type(node_type: Any) -> bool:
        for name, type_name in _NODE_INPUTS:
            node_type.add_input(name, type_name, False)
        for name, type_name in _NODE_OUTPUTS:
            node_type.add_output(name, type_name, False)
        return True

    @staticmethod
    def compute(graph_context: Any, node: Any) -> bool:
        from isaac_audio_sensors.isaac.frame_registry import get_latest_frame

        key = _attribute_value(node, "inputs:arrayKey")
        frame = get_latest_frame(str(key).strip() if key else None)
        values = frame_output_values(frame)
        ok = True
        for name, value in values.items():
            ok = _set_attribute_value(node, name, value) and ok
        return ok


def _attribute_value(node: Any, name: str) -> Any:
    try:
        attribute = node.get_attribute(name)
        return attribute.get()
    except Exception:  # noqa: BLE001 - absent inputs read as None.
        return None


def _set_attribute_value(node: Any, name: str, value: Any) -> bool:
    try:
        attribute = node.get_attribute(name)
        attribute.set(value)
        return True
    except Exception:  # noqa: BLE001 - report failure via compute result.
        return False


def _node_is_registered(og: Any) -> bool:
    get_node_type = getattr(og, "get_node_type", None)
    if not callable(get_node_type):
        return False
    try:
        return bool(get_node_type(NODE_TYPE_NAME))
    except Exception:  # noqa: BLE001 - optional API probe.
        return False


def register_omnigraph_node() -> str:
    """Register the node type; return a status string for GUI/evidence."""

    try:
        import omni.graph.core as og  # type: ignore
    except ImportError as exc:
        return f"OmniGraph unavailable: {exc}"
    already_registered = (
        f"OmniGraph node already registered: {NODE_TYPE_NAME} v{NODE_TYPE_VERSION}."
    )
    if _node_is_registered(og):
        return already_registered
    register = getattr(og, "register_node_type", None)
    if not callable(register):
        return "OmniGraph registration failed: og.register_node_type is missing."
    try:
        register(OgnIsaacAudioSensorFrame, NODE_TYPE_VERSION)
    except Exception as exc:  # noqa: BLE001 - status string is the contract.
        if _node_is_registered(og):
            return already_registered
        return f"OmniGraph registration failed: {type(exc).__name__}: {exc}"
    return f"OmniGraph node registered: {NODE_TYPE_NAME} v{NODE_TYPE_VERSION}."


def deregister_omnigraph_node() -> str:
    """Best-effort deregistration on extension shutdown."""

    try:
        import omni.graph.core as og  # type: ignore
    except ImportError as exc:
        return f"OmniGraph unavailable: {exc}"
    deregister = getattr(og, "deregister_node_type", None)
    if not callable(deregister):
        return "OmniGraph deregistration skipped: API is missing."
    try:
        deregister(NODE_TYPE_NAME)
    except Exception as exc:  # noqa: BLE001 - status string is the contract.
        return f"OmniGraph deregistration failed: {type(exc).__name__}: {exc}"
    return f"OmniGraph node deregistered: {NODE_TYPE_NAME}."
