"""Runtime OmniGraph node and frame-registry tests."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_ROOT = REPO_ROOT / "exts" / "isaac_audio_sensors.omni"
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from isaac_audio_sensors_omni.graph_node import (  # noqa: E402
    NODE_TYPE_NAME,
    NODE_TYPE_VERSION,
    OgnIsaacAudioSensorFrame,
    deregister_omnigraph_node,
    frame_output_values,
    register_omnigraph_node,
)

from isaac_audio_sensors.core.types import (  # noqa: E402
    AudioObservation,
    AudioSensorFrame,
    DoaEstimate,
    ObservationOrigin,
)
from isaac_audio_sensors.isaac import frame_registry  # noqa: E402


def _frame(frame_id: str = "frame_001", bearing: float = 90.0) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=frame_id,
        producer_id="analytic_acoustics",
        array_id="rig_front",
        channel_validity={"front": True, "left": True},
        start_time_s=1.5,
        end_time_s=1.6,
        sample_rate_hz=48_000,
        frame_index=0,
        aggregate_per_mic_rms={"front": 0.2, "left": 0.1},
        observations=(
            AudioObservation(
                observation_id="observation_0",
                origin=ObservationOrigin.SIGNAL_DERIVED,
                detector_id="auditok",
                doa=DoaEstimate(
                    estimated_bearing_deg=bearing,
                    bearing_sector="right",
                    bearing_confidence=0.8,
                ),
            ),
        ),
    )


def setup_function(_function) -> None:
    frame_registry.clear_latest_frames()


def test_frame_registry_publish_get_and_clear():
    frame = _frame()
    frame_registry.publish_latest_frame("/World/Rig/AudioArray", frame)
    assert frame_registry.get_latest_frame("/World/Rig/AudioArray") is frame
    assert frame_registry.get_latest_frame() is frame

    other = _frame(frame_id="frame_002")
    frame_registry.publish_latest_frame("/World/Other", other)
    assert frame_registry.get_latest_frame() is other
    frame_registry.clear_latest_frames("/World/Other")
    assert frame_registry.get_latest_frame() is frame
    frame_registry.clear_latest_frames()
    assert frame_registry.get_latest_frame() is None


def test_frame_output_values_maps_frame_and_none():
    values = frame_output_values(_frame())
    assert values["outputs:frameId"] == "frame_001"
    assert values["outputs:timestampMs"] == 1500
    assert values["outputs:observationCount"] == 1
    assert values["outputs:bearingDeg"] == 90.0
    assert values["outputs:sector"] == "right"
    assert values["outputs:micIds"] == ["front", "left"]
    assert values["outputs:micRms"] == [0.2, 0.1]
    payload = json.loads(values["outputs:frameJson"])
    assert payload["frame_id"] == "frame_001"

    empty = frame_output_values(None)
    assert empty["outputs:frameId"] == ""
    assert empty["outputs:observationCount"] == 0
    assert math.isnan(empty["outputs:bearingDeg"])
    assert empty["outputs:frameJson"] == ""


class _FakeAttribute:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _FakeNode:
    def __init__(self, inputs: dict[str, object] | None = None) -> None:
        self.attributes: dict[str, _FakeAttribute] = {
            name: _FakeAttribute(value) for name, value in (inputs or {}).items()
        }

    def get_attribute(self, name: str) -> _FakeAttribute:
        return self.attributes.setdefault(name, _FakeAttribute())


def test_compute_reads_registry_and_sets_outputs():
    frame_registry.publish_latest_frame("/World/Rig/AudioArray", _frame())
    node = _FakeNode({"inputs:arrayKey": ""})

    assert OgnIsaacAudioSensorFrame.compute(None, node) is True
    assert node.get_attribute("outputs:frameId").value == "frame_001"
    assert node.get_attribute("outputs:bearingDeg").value == 90.0
    assert node.get_attribute("outputs:micIds").value == ["front", "left"]

    keyed = _FakeNode({"inputs:arrayKey": "/World/Missing"})
    assert OgnIsaacAudioSensorFrame.compute(None, keyed) is True
    assert keyed.get_attribute("outputs:frameId").value == ""
    assert keyed.get_attribute("outputs:observationCount").value == 0


class _FakeNodeType:
    def __init__(self) -> None:
        self.inputs: list[tuple] = []
        self.outputs: list[tuple] = []

    def add_input(self, name, type_name, required) -> None:
        self.inputs.append((name, type_name, required))

    def add_output(self, name, type_name, required) -> None:
        self.outputs.append((name, type_name, required))


def test_initialize_type_declares_all_attributes():
    node_type = _FakeNodeType()
    assert OgnIsaacAudioSensorFrame.initialize_type(node_type) is True
    assert ("inputs:arrayKey", "token", False) in node_type.inputs
    output_names = {name for name, _, _ in node_type.outputs}
    assert {
        "outputs:frameId",
        "outputs:timestampMs",
        "outputs:observationCount",
        "outputs:bearingDeg",
        "outputs:sector",
        "outputs:micIds",
        "outputs:micRms",
        "outputs:frameJson",
    } <= output_names


def _install_fake_og(monkeypatch):
    calls: dict[str, object] = {}
    omni = sys.modules.get("omni") or ModuleType("omni")
    omni.__path__ = []
    graph = ModuleType("omni.graph")
    graph.__path__ = []
    core = ModuleType("omni.graph.core")
    core.register_node_type = lambda node_class, version: calls.update(
        {"registered": (node_class, version)}
    )
    core.deregister_node_type = lambda name: calls.update({"deregistered": name})
    graph.core = core
    omni.graph = graph
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.graph", graph)
    monkeypatch.setitem(sys.modules, "omni.graph.core", core)
    return calls


def test_register_and_deregister_with_fake_omnigraph(monkeypatch):
    calls = _install_fake_og(monkeypatch)
    status = register_omnigraph_node()
    assert "registered" in status
    assert NODE_TYPE_NAME in status
    assert calls["registered"] == (OgnIsaacAudioSensorFrame, NODE_TYPE_VERSION)

    stop_status = deregister_omnigraph_node()
    assert "deregistered" in stop_status
    assert calls["deregistered"] == NODE_TYPE_NAME


def test_register_is_idempotent_when_node_type_exists(monkeypatch):
    calls = _install_fake_og(monkeypatch)
    sys.modules["omni.graph.core"].get_node_type = lambda name: (
        object() if name == NODE_TYPE_NAME else None
    )

    status = register_omnigraph_node()

    assert "already registered" in status
    assert NODE_TYPE_NAME in status
    assert "registered" not in calls


def test_register_reports_unavailable_without_omnigraph(monkeypatch):
    monkeypatch.setitem(sys.modules, "omni.graph.core", None)
    status = register_omnigraph_node()
    assert "unavailable" in status


def test_register_reports_failure_message(monkeypatch):
    calls = _install_fake_og(monkeypatch)

    def _boom(node_class, version):
        raise RuntimeError("kaput")

    sys.modules["omni.graph.core"].register_node_type = _boom
    status = register_omnigraph_node()
    assert "failed" in status
    assert "kaput" in status
    assert "registered" not in calls
