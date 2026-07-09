"""Runtime-registered OmniGraph node exposing the latest audio frame.

The node reads ``isaac_audio_sensors.isaac.frame_registry`` (which the GUI
controller publishes to on every recorded frame) so audio wires into Action
Graphs the way cameras and lidars do. Registration uses the pure-Python
``og.register_node_type`` path - no .ogn code generation - and is entirely
optional: every failure mode is reported as a human-readable status string
that the GUI and the live gate surface verbatim.
"""

from __future__ import annotations

import json
from typing import Any

NODE_TYPE_NAME = "isaac_audio_sensors.omni.IsaacAudioSensorFrame"
NODE_TYPE_VERSION = 1

# (name, omnigraph type, is_input)
NODE_ATTRIBUTES = (
    ("inputs:arrayKey", "token", True),
    ("outputs:frameId", "token", False),
    ("outputs:timestampMs", "int64", False),
    ("outputs:detectionCount", "int", False),
    ("outputs:bearingDeg", "double", False),
    ("outputs:sector", "token", False),
    ("outputs:micIds", "token[]", False),
    ("outputs:micRms", "double[]", False),
    ("outputs:occluded", "bool", False),
    ("outputs:frameJson", "token", False),
)


def frame_output_values(frame: Any | None) -> dict[str, Any]:
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
    detections = tuple(getattr(frame, "detections", ()) or ())
    first = detections[0] if detections else None
    doa = getattr(first, "doa", None)
    bearing = getattr(doa, "estimated_bearing_deg", None)
    aggregate_rms = dict(getattr(frame, "aggregate_per_mic_rms", {}) or {})
    mic_ids = sorted(aggregate_rms)
    try:
        from isaac_audio_sensors.core.io.traces import frame_to_trace_dict

        frame_json = json.dumps(frame_to_trace_dict(frame), sort_keys=True)
    except Exception:  # noqa: BLE001 - JSON payload is best-effort.
        frame_json = ""
    return {
        "outputs:frameId": str(getattr(frame, "frame_id", "") or ""),
        "outputs:timestampMs": int(getattr(frame, "timestamp_ms", 0) or 0),
        "outputs:detectionCount": len(detections),
        "outputs:bearingDeg": (
            float(bearing) if bearing is not None else float("nan")
        ),
        "outputs:sector": str(getattr(doa, "bearing_sector", "") or ""),
        "outputs:micIds": mic_ids,
        "outputs:micRms": [float(aggregate_rms[mic_id]) for mic_id in mic_ids],
        "outputs:occluded": bool(getattr(first, "occluded", False)),
        "outputs:frameJson": frame_json,
    }


class OgnIsaacAudioSensorFrame:
    """Pure-Python OmniGraph node type (runtime registration, no codegen)."""

    @staticmethod
    def get_node_type() -> str:
        return NODE_TYPE_NAME

    @staticmethod
    def initialize_type(node_type: Any) -> bool:
        for name, type_name, is_input in NODE_ATTRIBUTES:
            if is_input:
                node_type.add_input(name, type_name, False)
            else:
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


def register_omnigraph_node() -> str:
    """Register the node type; return a status string for GUI/evidence."""

    try:
        import omni.graph.core as og  # type: ignore
    except ImportError as exc:
        return f"OmniGraph unavailable: {exc}"
    get_node_type = getattr(og, "get_node_type", None)
    if callable(get_node_type):
        try:
            if get_node_type(NODE_TYPE_NAME):
                return (
                    f"OmniGraph node already registered: "
                    f"{NODE_TYPE_NAME} v{NODE_TYPE_VERSION}."
                )
        except Exception:
            pass
    register = getattr(og, "register_node_type", None)
    if not callable(register):
        return "OmniGraph registration failed: og.register_node_type is missing."
    try:
        register(OgnIsaacAudioSensorFrame, NODE_TYPE_VERSION)
    except Exception as exc:  # noqa: BLE001 - status string is the contract.
        if callable(get_node_type):
            try:
                if get_node_type(NODE_TYPE_NAME):
                    return (
                        f"OmniGraph node already registered: "
                        f"{NODE_TYPE_NAME} v{NODE_TYPE_VERSION}."
                    )
            except Exception:
                pass
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
