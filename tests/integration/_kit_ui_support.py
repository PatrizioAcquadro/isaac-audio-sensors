# ruff: noqa: F401

"""Shared fakes for focused Kit service tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.isaac.replicator import PAYLOAD_SCHEMA_VERSION
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.constants import OUTPUT_ROOT_ENV_VAR
from isaac_audio_sensors.kit.microphone_rig_profiles import (
    default_microphone_rig_profiles,
)
from isaac_audio_sensors.kit.paths import _gui_output_root, _resolve_gui_output_path
from isaac_audio_sensors.kit.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
)
from isaac_audio_sensors.kit.stage_context import (
    _stage_has_prim,
    current_omni_stage_context,
)
from isaac_audio_sensors.kit.state import CurrentStageContext


def _write_test_png(path: Path, *, width: int = 13, height: int = 17) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\r"
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _load_live_ux_script(monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo / "tools" / "smoke"))
    monkeypatch.syspath_prepend(str(repo / "exts" / "isaac_audio_sensors.omni"))
    script_path = repo / "tools" / "smoke" / "live_omniverse_extension_ux.py"
    spec = importlib.util.spec_from_file_location(
        "live_omniverse_extension_ux_for_tests",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_viewport_modules(
    monkeypatch,
    *,
    viewport: object | None,
    utility_capture: object | None = None,
    renderer: object | None = None,
    app: object | None = None,
) -> SimpleNamespace:
    omni = ModuleType("omni")
    omni.__path__ = []
    kit = ModuleType("omni.kit")
    kit.__path__ = []
    omni_ext = ModuleType("omni.ext")
    viewport_pkg = ModuleType("omni.kit.viewport")
    viewport_pkg.__path__ = []
    utility = ModuleType("omni.kit.viewport.utility")
    framed: list[tuple[str, ...]] = []

    class IExt:
        pass

    omni_ext.IExt = IExt
    utility.get_active_viewport = lambda: viewport

    def frame_viewport_prims(_viewport: object, *, prims: list[str]) -> bool:
        framed.append(tuple(prims))
        return True

    utility.frame_viewport_prims = frame_viewport_prims
    if utility_capture is not None:
        utility.capture_viewport_to_file = utility_capture
    viewport_pkg.utility = utility
    kit.viewport = viewport_pkg
    omni.kit = kit
    omni.ext = omni_ext
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ext", omni_ext)
    monkeypatch.setitem(sys.modules, "omni.kit", kit)
    monkeypatch.setitem(sys.modules, "omni.kit.viewport", viewport_pkg)
    monkeypatch.setitem(sys.modules, "omni.kit.viewport.utility", utility)

    if renderer is not None:
        renderer_module = ModuleType("omni.kit.renderer_capture")
        renderer_module.acquire_renderer_capture_interface = lambda: renderer
        kit.renderer_capture = renderer_module
        monkeypatch.setitem(sys.modules, "omni.kit.renderer_capture", renderer_module)

    if app is not None:
        app_module = ModuleType("omni.kit.app")
        app_module.get_app = lambda: app
        kit.app = app_module
        monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)

    return SimpleNamespace(framed=framed)


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

    def RemovePrim(self, path: object) -> bool:
        path_string = str(path)
        before = len(self._prims)
        self._prims = [
            prim
            for prim in self._prims
            if prim.path != path_string and not prim.path.startswith(f"{path_string}/")
        ]
        return len(self._prims) != before


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
        self._collapsed = bool(kwargs.get("collapsed", False))
        self.collapsed_changed_fn = None
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

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool) -> None:
        changed = self._collapsed != bool(value)
        self._collapsed = bool(value)
        if changed and callable(self.collapsed_changed_fn):
            self.collapsed_changed_fn(self._collapsed)

    def set_collapsed_changed_fn(self, callback: object) -> None:
        self.collapsed_changed_fn = callback


class _FakeByteImageProvider:
    def __init__(self) -> None:
        self.data: list[int] | None = None
        self.size: list[int] | None = None

    def set_bytes_data(self, data: object, size: object) -> None:
        self.data = list(data)
        self.size = list(size)


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
        self.ProgressBar = self._widget_factory("ProgressBar")
        self.ImageWithProvider = self._widget_factory("ImageWithProvider")
        self.ByteImageProvider = _FakeByteImageProvider
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

    def set_bool(self, path: str, value: bool) -> None:
        self.values[path] = bool(value)


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


class _FakeUpdateStream:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def create_subscription_to_pop(self, callback: object, **_kwargs: object) -> object:
        self.callbacks.append(callback)
        return SimpleNamespace(callback=callback)

    def trigger(self) -> None:
        for callback in tuple(self.callbacks):
            callback(SimpleNamespace())


def _install_fake_kit_update_stream(
    monkeypatch,
    *,
    timeline_time_s: float | None = None,
) -> _FakeUpdateStream:
    omni = sys.modules.get("omni") or ModuleType("omni")
    omni.__path__ = []
    kit = getattr(omni, "kit", ModuleType("omni.kit"))
    kit.__path__ = []
    stream = _FakeUpdateStream()
    app_module = ModuleType("omni.kit.app")
    app_module.get_app = lambda: SimpleNamespace(get_update_event_stream=lambda: stream)
    kit.app = app_module
    omni.kit = kit

    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.kit", kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)

    if timeline_time_s is not None:
        clock = SimpleNamespace(time_s=float(timeline_time_s))
        timeline = ModuleType("omni.timeline")
        timeline.get_timeline_interface = lambda: SimpleNamespace(
            get_current_time=lambda: clock.time_s
        )
        omni.timeline = timeline
        monkeypatch.setitem(sys.modules, "omni.timeline", timeline)
        stream.timeline_clock = clock

    return stream


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
        settings=fake_settings,
        actions=action_registry,
        menu=menu_utils,
        hotkeys=hotkey_registry,
    )


class _FakeStageEventStream:
    SELECTION_CHANGED = 2
    OPENED = 1

    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def create_subscription_to_pop(self, callback, name=None):
        self.callbacks.append(callback)
        return SimpleNamespace(name=name)

    def trigger(self, event_type: int) -> None:
        for callback in list(self.callbacks):
            callback(SimpleNamespace(type=int(event_type)))


def _install_fake_stage_events(monkeypatch):
    omni = sys.modules.get("omni") or ModuleType("omni")
    omni.__path__ = []
    stream = _FakeStageEventStream()
    omni_usd = ModuleType("omni.usd")
    omni_usd.StageEventType = SimpleNamespace(
        SELECTION_CHANGED=_FakeStageEventStream.SELECTION_CHANGED,
        OPENED=_FakeStageEventStream.OPENED,
    )
    omni_usd.get_context = lambda: SimpleNamespace(
        get_stage_event_stream=lambda: stream
    )
    omni.usd = omni_usd
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)
    return stream


def _float32_wav_bytes(frames: int = 512, sample_rate: int = 8000) -> bytes:
    import math
    import struct

    data = b"".join(
        struct.pack("<f", 0.25 * math.sin(2 * math.pi * 440 * i / sample_rate))
        for i in range(frames)
    )
    fmt = struct.pack("<HHIIHH", 3, 1, sample_rate, sample_rate * 4, 4, 32)
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


__all__ = [name for name in globals() if not name.startswith("__")]
