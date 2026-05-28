"""Tests for the import-safe Omniverse reference extension UX."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback.
    import tomli as tomllib

from isaac_audio_sensors.isaac.extension_ui import (
    CurrentStageContext,
    ExtensionController,
    current_omni_stage_context,
)
from isaac_audio_sensors.isaac.replicator import PAYLOAD_SCHEMA_VERSION


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes or {}


class _FakeStage:
    def __init__(self, prims: tuple[_FakePrim, ...] = ()) -> None:
        self._prims = list(prims)

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)

    def DefinePrim(self, path: str, type_name: str) -> _FakePrim:
        existing = self.GetPrimAtPath(path)
        if existing is not None:
            existing.type_name = type_name
            return existing
        prim = _FakePrim(path, type_name)
        self._prims.append(prim)
        return prim

    def GetPrimAtPath(self, path: str) -> _FakePrim | None:
        for prim in self._prims:
            if prim.path == path:
                return prim
        return None


class _FakeModel:
    def __init__(self, value: object = None) -> None:
        self.value = value
        self.changed_fns: list[object] = []

    @property
    def as_string(self) -> str:
        return str(self.value or "")

    @property
    def as_float(self) -> float:
        return float(self.value or 0.0)

    @property
    def as_int(self) -> int:
        return int(self.value or 0)

    @property
    def as_bool(self) -> bool:
        return bool(self.value)

    def set_value(self, value: object) -> None:
        self.value = value
        for callback in self.changed_fns:
            callback(self)

    def get_value_as_string(self) -> str:
        return self.as_string

    def get_value_as_float(self) -> float:
        return self.as_float

    def get_value_as_int(self) -> int:
        return self.as_int

    def get_value_as_bool(self) -> bool:
        return self.as_bool

    def get_item_value_model(self) -> _FakeModel:
        return self

    def add_item_changed_fn(self, callback: object) -> None:
        self.changed_fns.append(callback)
        return callback

    def add_value_changed_fn(self, callback: object) -> object:
        self.changed_fns.append(callback)
        return callback


class _FakeWidget:
    _context_stack: list[_FakeWidget] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.kind = str(kwargs.pop("_kind", "Widget"))
        self.ui = kwargs.pop("_ui", None)
        self.args = args
        self.kwargs = kwargs
        self.model = kwargs.pop("model", None)
        if self.model is None and args and isinstance(args[0], _FakeModel):
            self.model = args[0]
        if self.model is None:
            self.model = _FakeModel(
                args[0] if args and isinstance(args[0], int) else None
            )
        self.frame = self
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.visible = True
        self.visibility_changed_fn = None
        self.children: list[_FakeWidget] = []
        self.parent = (
            _FakeWidget._context_stack[-1] if _FakeWidget._context_stack else None
        )
        if self.parent is not None:
            self.parent.children.append(self)
        if self.ui is not None:
            self.ui.created.append(self)

    def __enter__(self) -> _FakeWidget:
        _FakeWidget._context_stack.append(self)
        return self

    def __exit__(self, *exc_info: object) -> bool:
        _FakeWidget._context_stack.pop()
        return False

    def set_visibility_changed_fn(self, callback: object) -> None:
        self.visibility_changed_fn = callback


class _FakeUI(ModuleType):
    def __init__(self) -> None:
        super().__init__("omni.ui")
        _FakeWidget._context_stack = []
        self.created: list[_FakeWidget] = []
        self.Window = self._widget_factory("Window")
        self.ScrollingFrame = self._widget_factory("ScrollingFrame")
        self.VStack = self._widget_factory("VStack")
        self.HStack = self._widget_factory("HStack")
        self.CollapsableFrame = self._widget_factory("CollapsableFrame")
        self.Label = self._widget_factory("Label")
        self.StringField = self._widget_factory("StringField")
        self.FloatDrag = self._widget_factory("FloatDrag")
        self.IntDrag = self._widget_factory("IntDrag")
        self.CheckBox = self._widget_factory("CheckBox")
        self.ComboBox = self._widget_factory("ComboBox")
        self.Button = self._widget_factory("Button")
        self.SimpleStringModel = _FakeModel
        self.SimpleFloatModel = _FakeModel
        self.SimpleIntModel = _FakeModel
        self.SimpleBoolModel = _FakeModel
        self.Fraction = lambda value: value

    def _widget_factory(self, kind: str):
        def _create(*args: object, **kwargs: object) -> _FakeWidget:
            return _FakeWidget(*args, _kind=kind, _ui=self, **kwargs)

        return _create


class _FakeAction:
    def __init__(self, extension_id: str, action_id: str, callback: object) -> None:
        self.extension_id = extension_id
        self.id = action_id
        self.callback = callback

    def execute(self, *args: object, **kwargs: object) -> object:
        return self.callback(*args, **kwargs)


class _FakeActionRegistry:
    def __init__(self) -> None:
        self.actions: dict[tuple[str, str], _FakeAction] = {}
        self.deregistered: list[tuple[str, str]] = []

    def register_action(
        self,
        extension_id: str,
        action_id: str,
        python_object: object,
        **_kwargs: object,
    ) -> _FakeAction:
        action = _FakeAction(extension_id, action_id, python_object)
        self.actions[(extension_id, action_id)] = action
        return action

    def deregister_action(self, *args: object) -> object:
        if len(args) == 1 and isinstance(args[0], _FakeAction):
            key = (args[0].extension_id, args[0].id)
        elif len(args) >= 2:
            key = (str(args[0]), str(args[1]))
        else:
            return None
        self.deregistered.append(key)
        return self.actions.pop(key, None)

    def execute_action(
        self,
        extension_id: str,
        action_id: str,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.actions[(extension_id, action_id)].execute(*args, **kwargs)


class _FakeMenuItemDescription:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _FakeMenuUtils(ModuleType):
    def __init__(self) -> None:
        super().__init__("omni.kit.menu.utils")
        self.MenuItemDescription = _FakeMenuItemDescription
        self.added: list[tuple[str, list[object]]] = []
        self.removed: list[tuple[str, list[object]]] = []
        self.refreshed: list[str] = []

    def add_menu_items(
        self,
        items: list[object],
        name: str,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        self.added.append((name, items))

    def remove_menu_items(
        self,
        items: list[object],
        name: str,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        self.removed.append((name, items))

    def refresh_menu_items(self, name: str) -> None:
        self.refreshed.append(name)


class _FakeHotkey:
    def __init__(
        self,
        hotkey_ext_id: str,
        key: str,
        action_ext_id: str,
        action_id: str,
    ) -> None:
        self.hotkey_ext_id = hotkey_ext_id
        self.key = key
        self.action_ext_id = action_ext_id
        self.action_id = action_id


class _FakeHotkeyRegistry:
    def __init__(self) -> None:
        self.hotkeys: list[_FakeHotkey] = []
        self.last_error = "OK"

    def register_hotkey(
        self,
        hotkey_ext_id: str,
        key: str,
        action_ext_id: str,
        action_id: str,
        filter: object = None,  # noqa: A002 - mirrors Kit API.
    ) -> _FakeHotkey:
        _ = filter
        hotkey = _FakeHotkey(hotkey_ext_id, key, action_ext_id, action_id)
        self.hotkeys.append(hotkey)
        return hotkey

    def deregister_hotkey(self, hotkey: _FakeHotkey) -> bool:
        if hotkey in self.hotkeys:
            self.hotkeys.remove(hotkey)
            return True
        return False

    def deregister_hotkeys(self, hotkey_ext_id: str, key: str) -> None:
        self.hotkeys = [
            hotkey
            for hotkey in self.hotkeys
            if not (hotkey.hotkey_ext_id == hotkey_ext_id and hotkey.key == key)
        ]


class _FakeSettings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or {}

    def get(self, path: str) -> object:
        return self.values.get(path)


class _FakeWriterRegistry:
    registered: dict[str, type] = {}

    @classmethod
    def register(cls, writer_cls: type) -> None:
        cls.registered[writer_cls.__name__] = writer_cls

    @classmethod
    def get(cls, name: str) -> object:
        return cls.registered[name]()


class _FakeAnnotatorRegistry:
    registered: dict[str, object] = {}

    @classmethod
    def register(cls, name: str, annotator: object) -> None:
        cls.registered[name] = annotator


def _install_fake_replicator(monkeypatch):
    _FakeWriterRegistry.registered = {}
    _FakeAnnotatorRegistry.registered = {}
    omni = sys.modules.get("omni") or ModuleType("omni")
    replicator = ModuleType("omni.replicator")
    core = ModuleType("omni.replicator.core")
    core.Writer = object
    core.WriterRegistry = _FakeWriterRegistry
    core.AnnotatorRegistry = _FakeAnnotatorRegistry
    replicator.core = core
    omni.replicator = replicator
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.replicator", replicator)
    monkeypatch.setitem(sys.modules, "omni.replicator.core", core)
    return core


def _install_fake_kit_integrations(
    monkeypatch,
    *,
    install_hotkeys: bool = True,
    shortcut: str | None = None,
):
    omni = sys.modules.get("omni") or ModuleType("omni")
    omni.__path__ = []
    omni_ui = _FakeUI()
    omni.ui = omni_ui

    kit = ModuleType("omni.kit")
    kit.__path__ = []
    actions = ModuleType("omni.kit.actions")
    actions.__path__ = []
    actions_core = ModuleType("omni.kit.actions.core")
    action_registry = _FakeActionRegistry()
    actions_core.get_action_registry = lambda: action_registry
    actions.core = actions_core

    menu = ModuleType("omni.kit.menu")
    menu.__path__ = []
    menu_utils = _FakeMenuUtils()
    menu.utils = menu_utils

    kit.actions = actions
    kit.menu = menu
    omni.kit = kit

    settings_values = {}
    if shortcut is not None:
        settings_values["/exts/isaac_audio_sensors.omni/shortcut"] = shortcut
    fake_settings = _FakeSettings(settings_values)
    carb = ModuleType("carb")
    carb.__path__ = []
    carb_settings = ModuleType("carb.settings")
    carb_settings.get_settings = lambda: fake_settings
    carb.settings = carb_settings

    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    monkeypatch.setitem(sys.modules, "omni.kit", kit)
    monkeypatch.setitem(sys.modules, "omni.kit.actions", actions)
    monkeypatch.setitem(sys.modules, "omni.kit.actions.core", actions_core)
    monkeypatch.setitem(sys.modules, "omni.kit.menu", menu)
    monkeypatch.setitem(sys.modules, "omni.kit.menu.utils", menu_utils)
    monkeypatch.setitem(sys.modules, "carb", carb)
    monkeypatch.setitem(sys.modules, "carb.settings", carb_settings)

    hotkey_registry = None
    if install_hotkeys:
        hotkeys = ModuleType("omni.kit.hotkeys")
        hotkeys.__path__ = []
        hotkeys_core = ModuleType("omni.kit.hotkeys.core")
        hotkey_registry = _FakeHotkeyRegistry()
        hotkeys_core.get_hotkey_registry = lambda: hotkey_registry
        hotkeys.core = hotkeys_core
        kit.hotkeys = hotkeys
        monkeypatch.setitem(sys.modules, "omni.kit.hotkeys", hotkeys)
        monkeypatch.setitem(sys.modules, "omni.kit.hotkeys.core", hotkeys_core)

    return SimpleNamespace(
        ui=omni_ui,
        actions=action_registry,
        menu=menu_utils,
        hotkeys=hotkey_registry,
    )


def test_omni_extension_entrypoint_import_smoke_without_isaac_modules():
    repo = Path(__file__).resolve().parents[1]
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
        print(json.dumps({"ui_available": ext.ui_available}))
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

    assert json.loads(completed.stdout) == {"ui_available": False}


def test_omni_extension_entrypoint_import_smoke_from_extension_path_only():
    repo = Path(__file__).resolve().parents[1]
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
        print(json.dumps({"ui_available": ext.ui_available}))
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
    repo = Path(__file__).resolve().parents[1]
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


def test_extension_controller_authors_runs_overlays_and_exports(tmp_path):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.latest_frame_export_path = str(tmp_path / "latest.json")
    controller.state.config_export_path = str(tmp_path / "binding.json")

    array_record = controller.author_array(stage=stage)
    source_record = controller.author_source(stage=stage)
    discovered = controller.refresh_discovery(stage=stage)
    sensor = controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()
    latest_path = controller.export_latest_frame()
    config_path = controller.export_config_summary()
    imported = ExtensionController()
    imported_path = imported.import_config_summary(config_path)

    assert array_record is not None
    assert source_record is not None
    assert stage.GetPrimAtPath("/World/Sources/SpeakerA").attributes[
        "xformOp:translate"
    ] == (2.0, 0.0, 0.0)
    assert stage.GetPrimAtPath("/World/Sources/SpeakerA").attributes[
        "ias:position_world"
    ] == (2.0, 0.0, 0.0)
    assert {item.id for item in discovered} == {"rig_front", "speaker_a"}
    assert sensor is not None
    assert frame is not None
    assert controller.state.latest_detection_count == 1
    assert controller.state.latest_bearing_deg is not None
    assert abs(controller.state.latest_bearing_deg) <= 1e-6
    assert controller.state.latest_sector is not None
    assert controller.state.latest_overlay_primitive_count >= 4
    assert latest_path == tmp_path / "latest.json"
    assert config_path == tmp_path / "binding.json"
    assert json.loads(latest_path.read_text(encoding="utf-8"))["backend_id"] == (
        "geometry_only"
    )
    trace_lines = (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(trace_lines) == 1
    summary = json.loads(config_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == "ias.omni_extension_binding.v1"
    assert summary["array"]["prim_path"] == "/World/Rig/AudioArray"
    assert summary["source"]["prim_path"] == "/World/Sources/SpeakerA"
    assert summary["source"]["position_world"] == [2.0, 0.0, 0.0]
    assert summary["latest_frame"]["source_prim_path"] == "/World/Sources/SpeakerA"
    assert summary["latest_frame"]["source_position_m"] == [2.0, 0.0, 0.0]
    assert summary["lifecycle"]["writer_path"].endswith("frames.jsonl")
    assert summary["recording"]["package_jsonl"]["path"].endswith("frames.jsonl")
    assert summary["recording"]["replicator"]["enabled"] is False
    assert summary["overlay"]["primitive_count"] == (
        controller.state.latest_overlay_primitive_count
    )
    assert imported_path == config_path
    assert imported.state.array_prim_path == "/World/Rig/AudioArray"
    assert imported.state.source_prim_path == "/World/Sources/SpeakerA"
    assert imported.state.source_position_x_m == 2.0
    assert imported.state.source_position_y_m == 0.0
    assert imported.state.source_position_z_m == 0.0
    assert imported.state.jsonl_trace_path.endswith("frames.jsonl")


def test_extension_controller_source_position_read_apply_presets_and_drag_update(
    tmp_path,
):
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (3.0, 1.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            source,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    read_position = controller.read_selected_source_transform(
        stage=stage,
        selected_paths=("/World/Sources/SpeakerA",),
    )
    assert read_position == (3.0, 1.0, 0.0)
    assert controller.state.source_position_x_m == 3.0
    assert controller.state.source_position_y_m == 1.0
    assert controller.state.source_position_z_m == 0.0

    controller.state.source_position_x_m = 4.0
    controller.state.source_position_y_m = 0.0
    controller.state.source_position_z_m = 0.0
    applied = controller.apply_source_position(stage=stage)
    assert applied is not None
    assert source.attributes["ias:position_world"] == (4.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (4.0, 0.0, 0.0)

    assert controller.apply_source_position_preset("front", stage=stage) is not None
    assert source.attributes["xformOp:translate"] == (2.0, 0.0, 0.0)
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    front_frame = controller.update_sensor()
    assert front_frame is not None
    front_detection = front_frame.detections[0]
    assert front_detection.source_pose.position_m == (2.0, 0.0, 0.0)
    assert abs(front_detection.doa.estimated_bearing_deg) <= 1e-6
    assert front_detection.doa.bearing_sector == "straight"

    assert controller.apply_source_position_preset("right", stage=stage) is not None
    right_frame = controller.update_sensor()
    assert right_frame is not None
    right_detection = right_frame.detections[0]
    assert right_detection.source_pose.position_m == (0.0, 2.0, 0.0)
    assert abs(right_detection.doa.estimated_bearing_deg - 90.0) <= 1e-6
    assert right_detection.doa.bearing_sector == "right"

    source.attributes["xformOp:translate"] = (0.0, -2.0, 0.0)
    moved_frame = controller.update_sensor()
    assert moved_frame is not None
    moved_detection = moved_frame.detections[0]
    assert moved_detection.source_pose.position_m == (0.0, -2.0, 0.0)
    assert moved_detection.doa.estimated_bearing_deg != (
        right_detection.doa.estimated_bearing_deg
    )
    assert moved_detection.doa.bearing_sector == "left"
    assert controller.state.latest_source_position_m == (0.0, -2.0, 0.0)


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


def test_extension_ui_builds_against_fake_omni_ui(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    window = controller.build_ui_if_available()

    assert window is not None
    assert controller.ui_available is True
    assert controller._ui_window is not None
    assert set(controller._ui_window._combo_fields) == {
        "ambiguity_policy",
        "backend",
        "layout_name",
    }
    assert set(controller._ui_window._int_fields) == {
        "max_events",
        "sample_rate_hz",
    }
    assert set(controller._ui_window._float_fields) == {
        "source_position_x_m",
        "source_position_y_m",
        "source_position_z_m",
        "source_duration_s",
        "source_gain_db",
        "source_start_time_s",
        "update_period_s",
    }
    assert set(controller._ui_window._bool_fields) == {
        "author_child_microphones",
        "debug_overlay_enabled",
        "replicator_enabled",
        "trace_enabled",
    }
    assert "replicator_enabled" in controller._ui_window._bool_fields
    assert "replicator_output_dir" in controller._ui_window._string_fields
    assert "array_prim_path" in controller._ui_window._string_fields
    assert "source_prim_path" in controller._ui_window._string_fields
    assert "latest_frame_export_path" in controller._ui_window._string_fields
    assert {widget.kind for widget in controller._ui_window._float_fields.values()} == {
        "StringField"
    }
    assert {widget.kind for widget in controller._ui_window._int_fields.values()} == {
        "StringField"
    }
    assert controller._ui_window._sections == [
        "Stage",
        "Author Array",
        "Author Source",
        "Sensor",
        "Replicator",
        "Export",
    ]

    scrolling_frames = [
        widget for widget in omni_ui.created if widget.kind == "ScrollingFrame"
    ]
    assert len(scrolling_frames) == 1
    collapsable_frames = [
        widget for widget in omni_ui.created if widget.kind == "CollapsableFrame"
    ]
    assert [widget.text for widget in collapsable_frames] == [
        "Stage",
        "Author Array",
        "Author Source",
        "Sensor",
        "Replicator",
        "Export",
    ]
    for frame in collapsable_frames:
        assert [child.kind for child in frame.children] == ["VStack"]

    button_labels = {
        widget.text for widget in omni_ui.created if widget.kind == "Button"
    }
    assert {
        "Refresh",
        "Use Array",
        "Use Source",
        "Use Base",
        "Discover",
        "Create/Attach Array",
        "Read Selected Transform",
        "Apply Position",
        "Front",
        "Right",
        "Left",
        "Behind",
        "Create/Attach Source",
        "Start",
        "Stop",
        "Update",
        "Flush",
        "Export Latest",
        "Export Config",
        "Load Config",
    } <= button_labels
    assert {
        "Refresh",
        "Use Array",
        "Use Source",
        "Use Base",
        "Discover",
        "Create/Attach Array",
        "Read Selected Transform",
        "Apply Position",
        "Front",
        "Right",
        "Left",
        "Behind",
        "Create/Attach Source",
        "Start",
        "Stop",
        "Update",
        "Flush",
        "Export Latest",
        "Export Config",
        "Load Config",
    } <= set(controller._ui_window._buttons)


def test_extension_controller_registers_menu_action_hotkey_and_cleans_up(
    monkeypatch,
):
    kit = _install_fake_kit_integrations(monkeypatch)
    controller = ExtensionController()

    controller.on_startup("isaac_audio_sensors.omni")

    assert controller.window is not None
    assert controller.window.visible is True
    assert ("isaac_audio_sensors.omni", "toggle_window") in kit.actions.actions
    assert kit.menu.added[0][0] == "Window"
    menu_item = kit.menu.added[0][1][0]
    assert menu_item.name == "Isaac Audio Sensors"
    assert menu_item.onclick_action == ("isaac_audio_sensors.omni", "toggle_window")
    assert menu_item.ticked_fn() is True
    assert kit.hotkeys is not None
    assert [(item.key, item.action_id) for item in kit.hotkeys.hotkeys] == [
        ("CTRL + ALT + A", "toggle_window")
    ]

    kit.actions.execute_action("isaac_audio_sensors.omni", "toggle_window")
    assert controller.window.visible is False
    assert menu_item.ticked_fn() is False

    kit.actions.execute_action("isaac_audio_sensors.omni", "toggle_window")
    assert controller.window.visible is True

    controller.on_shutdown()

    assert kit.hotkeys.hotkeys == []
    assert kit.menu.removed[0][0] == "Window"
    assert ("isaac_audio_sensors.omni", "toggle_window") not in kit.actions.actions


def test_extension_controller_reopens_window_after_close_x(monkeypatch):
    kit = _install_fake_kit_integrations(monkeypatch)
    controller = ExtensionController()
    controller.on_startup("isaac_audio_sensors.omni")
    window = controller.window
    assert window is not None

    window.visible = False
    assert controller.is_window_visible() is False

    reopened = kit.actions.execute_action("isaac_audio_sensors.omni", "toggle_window")

    assert reopened is window
    assert window.visible is True


def test_extension_controller_keeps_menu_action_when_hotkeys_unavailable(monkeypatch):
    kit = _install_fake_kit_integrations(monkeypatch, install_hotkeys=False)
    controller = ExtensionController()

    controller.on_startup("isaac_audio_sensors.omni")

    assert ("isaac_audio_sensors.omni", "toggle_window") in kit.actions.actions
    assert kit.menu.added
    assert "hotkey unavailable" in controller.hotkey_status.lower()
    assert "menu/action remain registered" in controller.hotkey_status


def test_extension_controller_versioned_id_reads_base_shortcut_setting(monkeypatch):
    kit = _install_fake_kit_integrations(monkeypatch, shortcut="SHIFT + A")
    controller = ExtensionController()

    controller.on_startup("isaac_audio_sensors.omni-1.0.0")

    assert kit.hotkeys is not None
    assert [(item.key, item.action_id) for item in kit.hotkeys.hotkeys] == [
        ("SHIFT + A", "toggle_window")
    ]
    assert "SHIFT + A" in controller.hotkey_status


def test_omniverse_extension_manifest_metadata_files_exist():
    repo = Path(__file__).resolve().parents[1]
    ext_root = repo / "exts" / "isaac_audio_sensors.omni"
    manifest_path = ext_root / "config" / "extension.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    package = manifest["package"]
    dependencies = manifest["dependencies"]
    python_modules = manifest["python"]["module"]

    assert package["authors"] == ["Patrizio Acquadro"]
    assert package["author"] == "Patrizio Acquadro"
    assert package["trusted"] is False
    assert package["support_level"].lower() == "community"
    assert package["category"].lower() == "simulation"
    assert package["repository"] == (
        "https://github.com/PatrizioAcquadro/isaac-audio-sensors"
    )
    assert {
        "audio",
        "microphone",
        "microphone-array",
        "sensor",
        "robotics",
        "isaac-sim",
        "omniverse",
        "usd",
        "tdoa",
        "simulation",
    } <= set(package["keywords"])
    assert set(dependencies) == {
        "omni.kit.actions.core",
        "omni.kit.menu.utils",
        "omni.ui",
        "omni.usd",
        "omni.kit.hotkeys.core",
        "omni.replicator.core",
    }
    assert dependencies["omni.kit.hotkeys.core"]["optional"] is True
    assert dependencies["omni.replicator.core"]["optional"] is True
    for forbidden_dependency in ("isaaclab", "cuda", "torch", "pyroomacoustics"):
        assert not any(
            forbidden_dependency in dependency.lower() for dependency in dependencies
        )
    for key in ("readme", "changelog", "icon", "preview_image"):
        path = ext_root / package[key]
        assert path.exists(), f"{key} does not exist: {path}"
        assert path.stat().st_size > 0, f"{key} is empty: {path}"

    readme = (ext_root / package["readme"]).read_text(encoding="utf-8")
    for expected in (
        "Window -> Isaac Audio Sensors",
        "Ctrl+Alt+A",
        "isaac_audio_sensors.omni::toggle_window",
        "selected USD prim",
        "author `ias:*` microphone-array and sound-source metadata",
        "discover authored arrays and sources",
        "start, update, and stop the live `IsaacAudioArraySensor`",
        "export the latest frame as JSON and stream frames as JSONL",
        "export and import reusable extension/stage-binding config JSON",
        "optional `omni.replicator.core`",
        "one extension Python module",
        "This extension does not register OmniGraph nodes.",
    ):
        assert expected in readme
    preview_bytes = (ext_root / package["preview_image"]).read_bytes()
    assert preview_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(preview_bytes[16:20], "big") == 1600
    assert int.from_bytes(preview_bytes[20:24], "big") == 900
    assert python_modules == [{"name": "isaac_audio_sensors_omni"}]


def test_omniverse_extension_does_not_advertise_unsupported_packages_or_nodes():
    repo = Path(__file__).resolve().parents[1]
    ext_root = repo / "exts" / "isaac_audio_sensors.omni"
    manifest_path = ext_root / "config" / "extension.toml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = tomllib.loads(manifest_text)

    assert manifest["python"]["module"] == [{"name": "isaac_audio_sensors_omni"}]
    assert not list(ext_root.rglob("*.ogn"))
    assert "[[ogn" not in manifest_text.lower()
    assert "omni.graph" not in manifest_text.lower()

    for path in (ext_root / "isaac_audio_sensors_omni").rglob("*.py"):
        assert "omni.graph" not in path.read_text(encoding="utf-8").lower()


def test_omniverse_extension_manifest_is_third_party_by_kit_source_logic():
    repo = Path(__file__).resolve().parents[1]
    manifest_path = (
        repo / "exts" / "isaac_audio_sensors.omni" / "config" / "extension.toml"
    )
    package = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["package"]

    if package.get("exchange", False):
        author_group = "COMMUNITY_VERIFIED"
    elif not package.get("trusted", True):
        author_group = "COMMUNITY_UNVERIFIED"
    else:
        author_group = "NVIDIA"

    ext_source = "NVIDIA" if author_group == "NVIDIA" else "THIRD PARTY"

    assert author_group != "NVIDIA"
    assert ext_source == "THIRD PARTY"


def test_extension_ui_config_roundtrips_edited_widget_state(tmp_path, monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.config_export_path = str(tmp_path / "binding.json")
    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None

    window._string_fields["source_id"].model.set_value("edited_source")
    window._string_fields["array_prim_path"].model.set_value("/World/EditedArray")
    window._string_fields["source_prim_path"].model.set_value("/World/EditedSource")
    window._string_fields["jsonl_trace_path"].model.set_value(
        str(tmp_path / "edited.frames.jsonl")
    )
    window._string_fields["replicator_output_dir"].model.set_value(
        str(tmp_path / "replicator")
    )
    window._float_fields["source_duration_s"].model.set_value("60.0")
    window._float_fields["source_position_x_m"].model.set_value("0.0")
    window._float_fields["source_position_y_m"].model.set_value("2.0")
    window._float_fields["source_position_z_m"].model.set_value("0.5")
    window._int_fields["sample_rate_hz"].model.set_value("44100")
    backend_widget, backend_choices = window._combo_fields["backend"]
    backend_widget.model.set_value(backend_choices.index("geometry_only"))
    layout_widget, layout_choices = window._combo_fields["layout_name"]
    layout_widget.model.set_value(layout_choices.index("mono"))
    ambiguity_widget, ambiguity_choices = window._combo_fields["ambiguity_policy"]
    ambiguity_widget.model.set_value(len(ambiguity_choices) - 1)
    window._bool_fields["debug_overlay_enabled"].model.set_value(False)
    window._bool_fields["trace_enabled"].model.set_value(True)
    window._bool_fields["replicator_enabled"].model.set_value(True)
    window.sync_state_from_widgets()

    assert controller.state.source_id == "edited_source"
    assert controller.state.source_duration_s == 60.0
    assert controller.state.source_position_y_m == 2.0
    assert controller.state.sample_rate_hz == 44100
    assert controller.state.backend == "geometry_only"
    assert controller.state.layout_name == "mono"
    assert controller.state.debug_overlay_enabled is False
    assert controller.state.replicator_enabled is True

    path = controller.export_config_summary()
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["array"]["sample_rate_hz"] == 44100
    assert summary["array"]["prim_path"] == "/World/EditedArray"
    assert summary["array"]["layout_name"] == "mono"
    assert summary["source"]["source_id"] == "edited_source"
    assert summary["source"]["prim_path"] == "/World/EditedSource"
    assert summary["source"]["duration_s"] == 60.0
    assert summary["source"]["position_world"] == [0.0, 2.0, 0.5]
    assert summary["backend"] == "geometry_only"
    assert summary["lifecycle"]["debug_overlay_enabled"] is False
    assert summary["recording"]["package_jsonl"]["enabled"] is True
    assert summary["recording"]["replicator"]["enabled"] is True

    imported = ExtensionController()
    assert imported.build_ui_if_available() is not None
    imported_window = imported._ui_window
    assert imported_window is not None
    assert imported.import_config_summary(path) == path
    imported_window.push_state_to_widgets()
    imported_window.sync_state_from_widgets()

    assert imported.state.backend == "geometry_only"
    assert imported.state.layout_name == "mono"
    assert imported.state.source_id == "edited_source"
    assert imported.state.source_duration_s == 60.0
    assert imported.state.source_position_x_m == 0.0
    assert imported.state.source_position_y_m == 2.0
    assert imported.state.source_position_z_m == 0.5
    assert imported.state.sample_rate_hz == 44100
    assert imported.state.array_prim_path == "/World/EditedArray"
    assert imported.state.source_prim_path == "/World/EditedSource"
    assert imported.state.debug_overlay_enabled is False
    assert imported.state.trace_enabled is True
    assert imported.state.replicator_enabled is True
    imported_backend_widget, _ = imported_window._combo_fields["backend"]
    imported_layout_widget, _ = imported_window._combo_fields["layout_name"]
    assert imported_backend_widget.model.value == backend_choices.index("geometry_only")
    assert imported_layout_widget.model.value == layout_choices.index("mono")


def test_extension_ui_invalid_numeric_input_is_readable(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)

    controller = ExtensionController()
    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None
    called = False

    def _callback() -> None:
        nonlocal called
        called = True

    window._float_fields["source_duration_s"].model.set_value("not-a-number")
    window._action(_callback)()

    assert called is False
    assert controller.state.error_message is not None
    assert "UI input failed" in controller.state.error_message


def test_extension_controller_reports_visible_errors_without_raising():
    controller = ExtensionController()

    result = controller.start_sensor(subscribe_to_update_stream=False)

    assert result is None
    assert controller.state.error_message is not None
    assert "Sensor configure failed" in controller.state.error_message


def test_extension_controller_replicator_lifecycle_and_payload(
    monkeypatch,
    tmp_path,
):
    _install_fake_replicator(monkeypatch)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.ext_id = "test.ext"
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    status = controller.start_replicator()
    frame = controller.update_sensor()
    flushed = controller.flush_replicator()
    stopped = controller.stop_replicator()

    assert status is not None
    assert status["writer_registered"] is True
    assert status["annotator_registered"] is True
    assert frame is not None
    assert flushed is not None
    assert flushed["flushed"] is True
    assert stopped is not None
    assert stopped["stopped"] is True
    assert controller.state.replicator_write_count == 1
    payload_path = Path(controller.state.replicator_latest_write_path or "")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PAYLOAD_SCHEMA_VERSION
    assert payload["summary"]["backend_id"] == "geometry_only"
    assert payload["summary"]["detection_count"] == 1
    assert payload["metadata"]["extension_id"] == "test.ext"
    assert (tmp_path / "replicator" / "audio_sensor_frames.jsonl").exists()


def test_extension_controller_replicator_missing_runtime_is_readable(tmp_path):
    controller = ExtensionController()
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    status = controller.start_replicator()

    assert status is None
    assert controller.state.error_message is not None
    assert "Replicator start failed" in controller.state.error_message
    assert "omni.replicator.core" in controller.state.error_message
