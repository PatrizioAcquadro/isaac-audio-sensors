import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.stage_context import current_omni_stage_context
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import (
    _FakePrim,
    _FakeStage,
    _FakeStageEventStream,
    _install_fake_kit_integrations,
    _install_fake_stage_events,
)


def test_shutdown_releases_all_resources_after_one_cleanup_failure(monkeypatch):
    controller = ExtensionController()
    lifecycle = controller._lifecycle
    controller._recording._guided_recorder = object()
    controller._recording._guided_workflow = SimpleNamespace(on_change=lambda: None)
    lifecycle.ext_id = "test.ext"
    lifecycle.window = object()
    lifecycle.ui_available = True
    calls: list[str] = []

    def cleanup(name, *, fail=False):
        def _run():
            calls.append(name)
            if fail:
                raise RuntimeError("planted")

        return _run

    monkeypatch.setattr(controller, "guided_cancel_recording", cleanup("recording"))
    monkeypatch.setattr(controller, "cleanup_kit_audio", cleanup("kit_audio"))
    monkeypatch.setattr(controller, "stop_audition", cleanup("audition", fail=True))
    monkeypatch.setattr(controller, "stop_replicator", cleanup("replicator"))
    monkeypatch.setattr(controller, "clear_usd_debug_geometry", cleanup("debug"))
    monkeypatch.setattr(controller, "close_sensor", cleanup("sensor"))
    monkeypatch.setattr(
        lifecycle, "_unregister_simulation_reset_callback", cleanup("reset")
    )
    monkeypatch.setattr(
        lifecycle, "_unregister_stage_event_subscription", cleanup("stage")
    )
    monkeypatch.setattr(
        lifecycle, "_stop_controller_update_subscription", cleanup("update")
    )
    monkeypatch.setattr(lifecycle, "_unregister_hotkey", cleanup("hotkey"))
    monkeypatch.setattr(lifecycle, "_unregister_menu", cleanup("menu"))
    monkeypatch.setattr(lifecycle, "_unregister_action", cleanup("action"))

    controller.on_shutdown()

    assert calls == [
        "recording",
        "kit_audio",
        "audition",
        "replicator",
        "debug",
        "sensor",
        "reset",
        "stage",
        "update",
        "hotkey",
        "menu",
        "action",
    ]
    assert lifecycle.ext_id is None
    assert lifecycle.window is None
    assert lifecycle.ui_available is False
    assert controller.state.error_message is not None
    assert "audition: planted" in controller.state.error_message


def test_omni_extension_entrypoint_import_smoke_from_extension_path_only():
    repo = Path(__file__).resolve().parents[2]
    code = textwrap.dedent("""
        import importlib
        import importlib.abc
        import json
        import sys

        blocked = ("omni", "pxr", "isaacsim")

        class OptionalRuntimeBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                for module_name in blocked:
                    if fullname == module_name or fullname.startswith(
                        module_name + "."
                    ):
                        raise ImportError(f"blocked optional module {fullname}")
                return None

        sys.meta_path.insert(0, OptionalRuntimeBlocker())
        module = importlib.import_module("isaac_audio_sensors_omni")
        ext = module.Extension()
        ext.on_startup("test.ext")
        ext.on_shutdown()
        print(json.dumps({"ui_available": ext.controller.ui_available}))
        """)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "exts" / "isaac_audio_sensors.omni")

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(completed.stdout) == {"ui_available": False}


def test_omni_extension_entrypoint_initializes_kit_iext_base():
    repo = Path(__file__).resolve().parents[2]
    code = textwrap.dedent("""
        import importlib
        import json
        import sys
        import types

        omni = types.ModuleType("omni")
        omni.__path__ = []
        omni_ext = types.ModuleType("omni.ext")

        class IExt:
            def __init__(self):
                self.iext_initialized = True

        omni_ext.IExt = IExt
        omni.ext = omni_ext
        sys.modules["omni"] = omni
        sys.modules["omni.ext"] = omni_ext

        module = importlib.import_module("isaac_audio_sensors_omni")
        ext = module.Extension()
        print(json.dumps({
            "iext_initialized": getattr(ext, "iext_initialized", False),
            "is_iext": isinstance(ext, IExt),
        }))
        """)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(repo / "src"),
            str(repo / "exts" / "isaac_audio_sensors.omni"),
            env.get("PYTHONPATH", ""),
        )
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(completed.stdout) == {
        "iext_initialized": True,
        "is_iext": True,
    }


def test_extension_controller_reads_fake_omni_usd_selection(monkeypatch):
    stage = _FakeStage()
    selection = SimpleNamespace(
        get_selected_prim_paths=lambda: ("/World/Robot", "/World/Speaker")
    )
    context = SimpleNamespace(
        get_stage=lambda: stage,
        get_selection=lambda: selection,
    )
    omni = ModuleType("omni")
    omni_usd = ModuleType("omni.usd")
    omni_usd.get_context = lambda: context
    omni.usd = omni_usd
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)

    current = current_omni_stage_context()
    controller = ExtensionController()
    selected = controller.refresh_stage_selection()
    array_path = controller.use_selected_as_array()

    assert current.stage is stage
    assert current.selected_prim_paths == ("/World/Robot", "/World/Speaker")
    assert selected == ("/World/Robot", "/World/Speaker")
    assert array_path == "/World/Robot"
    assert controller.state.array_prim_path == "/World/Robot"


def test_extension_controller_follows_viewport_selection_via_stage_events(
    monkeypatch,
):
    from isaac_audio_sensors.kit.state import DiscoveredPrimSummary

    _install_fake_kit_integrations(monkeypatch)
    stream = _install_fake_stage_events(monkeypatch)
    array_prim = _FakePrim(
        "/World/Rig/AudioArray",
        "Xform",
        {"xformOp:translate": (0.0, 0.0, 0.0)},
    )
    oven = _FakePrim("/World/Oven", "Xform", {"xformOp:translate": (1.0, 0.0, 0.0)})
    stage = _FakeStage((array_prim, oven))
    selection: list[str] = []
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, tuple(selection))
    )
    cleanup_reasons: list[str] = []
    monkeypatch.setattr(
        controller,
        "cleanup_kit_audio",
        lambda *, reason="cleanup": cleanup_reasons.append(reason),
    )
    controller.state.follow_viewport_selection = True
    controller.state.discovered_arrays = (
        DiscoveredPrimSummary(
            id="rig_front",
            prim_path="/World/Rig/AudioArray",
            reasons=("name",),
        ),
    )
    controller.on_startup("isaac_audio_sensors.omni")
    assert controller._lifecycle._stage_event_subscription is not None

    selection[:] = ["/World/Rig/AudioArray"]
    stream.trigger(_FakeStageEventStream.SELECTION_CHANGED)
    assert controller.state.array_prim_path == "/World/Rig/AudioArray"
    assert "adopted as array" in controller.state.status_message

    selection[:] = ["/World/Oven"]
    stream.trigger(_FakeStageEventStream.SELECTION_CHANGED)
    assert controller.state.object_prim_path == "/World/Oven"

    # Non-selection events and disabled follow do not adopt anything.
    selection[:] = ["/World/Rig/AudioArray"]
    stream.trigger(_FakeStageEventStream.OPENED)
    assert controller.state.object_prim_path == "/World/Oven"
    assert cleanup_reasons == ["USD stage opened"]
    controller.state.follow_viewport_selection = False
    stream.trigger(_FakeStageEventStream.SELECTION_CHANGED)
    assert controller.state.object_prim_path == "/World/Oven"
    controller.on_shutdown()
    assert controller._lifecycle._stage_event_subscription is None


def test_extension_controller_polling_fallback_follows_selection():
    from isaac_audio_sensors.kit.state import DiscoveredPrimSummary

    source_prim = _FakePrim(
        "/World/Sources/SpeakerA",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage((source_prim,))
    selection: list[str] = []
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, tuple(selection))
    )
    controller.state.follow_viewport_selection = True
    controller.state.discovered_sources = (
        DiscoveredPrimSummary(
            id="speaker_a",
            prim_path="/World/Sources/SpeakerA",
            reasons=("name",),
        ),
    )
    assert controller._lifecycle._stage_event_subscription is None

    selection[:] = ["/World/Sources/SpeakerA"]
    controller._lifecycle._viewport_follow_tick()
    assert controller.state.source_prim_path == "/World/Sources/SpeakerA"
    assert "adopted as source" in controller.state.status_message


def test_extension_controller_live_sync_pose_follows_prim_moves():
    source_prim = _FakePrim(
        "/World/Sources/SpeakerA",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    array_prim = _FakePrim(
        "/World/Rig/AudioArray",
        "Xform",
        {"xformOp:translate": (0.0, 0.0, 1.0)},
    )
    stage = _FakeStage((source_prim, array_prim))
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.source_prim_path = "/World/Sources/SpeakerA"
    controller.state.array_prim_path = "/World/Rig/AudioArray"
    controller.state.live_sync_source_pose = True
    controller.state.live_sync_array_pose = True

    controller._lifecycle._viewport_follow_tick()
    assert controller.state.source_position_x_m == 2.0
    assert controller.state.array_position_z_m == 1.0

    source_prim.attributes["xformOp:translate"] = (3.5, -1.0, 0.5)
    array_prim.attributes["xformOp:translate"] = (0.0, 2.0, 1.5)
    controller._lifecycle._viewport_follow_tick()
    assert controller.state.source_position_x_m == 3.5
    assert controller.state.source_position_y_m == -1.0
    assert controller.state.array_position_y_m == 2.0

    controller.state.live_sync_source_pose = False
    source_prim.attributes["xformOp:translate"] = (9.0, 9.0, 9.0)
    controller._lifecycle._viewport_follow_tick()
    assert controller.state.source_position_x_m == 3.5


def test_extension_controller_keeps_menu_action_when_hotkeys_unavailable(monkeypatch):
    kit = _install_fake_kit_integrations(monkeypatch, install_hotkeys=False)
    controller = ExtensionController()

    controller.on_startup("isaac_audio_sensors.omni")

    assert ("isaac_audio_sensors.omni", "toggle_window") in kit.actions.actions
    assert kit.menu.added
    assert "hotkey unavailable" in controller.hotkey_status.lower()
    assert "menu/action remain registered" in controller.hotkey_status
