"""Tests for the import-safe Omniverse reference extension UX."""

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

from isaac_audio_sensors.core.config import load_audio_config
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.microphone_rig_profiles import (
    default_microphone_rig_profiles,
)
from isaac_audio_sensors.isaac.replicator import PAYLOAD_SCHEMA_VERSION
from isaac_audio_sensors.isaac.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
)
from isaac_audio_sensors.kit import (
    OUTPUT_ROOT_ENV_VAR,
    CurrentStageContext,
    ExtensionController,
    _gui_output_root,
    _resolve_gui_output_path,
    _stage_has_prim,
    current_omni_stage_context,
)


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
        renderer_module = ModuleType("omni.renderer_capture")
        renderer_module.acquire_renderer_capture_interface = lambda: renderer
        omni.renderer_capture = renderer_module
        monkeypatch.setitem(sys.modules, "omni.renderer_capture", renderer_module)

    if app is not None:
        app_module = ModuleType("omni.kit.app")
        app_module.get_app = lambda: app
        kit.app = app_module
        monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)

    return SimpleNamespace(framed=framed)


def test_live_ux_screenshot_uses_viewport_utility_capture(monkeypatch, tmp_path):
    path = tmp_path / "utility.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    def capture_viewport_to_file(_viewport: object, *, file_path: str) -> object:
        _write_test_png(Path(file_path), width=31, height=19)
        return SimpleNamespace(wait_for_result=lambda: "done")

    env = _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        utility_capture=capture_viewport_to_file,
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(
        path,
        framed_paths=("/World/Oven", "/World/Oven/SpeakerA"),
    )

    assert record["status"] == "captured"
    assert record["path"] == str(path)
    assert record["method"] == "viewport_utility.capture_viewport_to_file"
    assert record["width"] == 31
    assert record["height"] == 19
    assert record["file_size_bytes"] > 0
    assert record["viewport_api_type"] == "SimpleNamespace"
    assert record["camera_path"] == "/World/Camera"
    assert record["framed_paths"] == ["/World/Oven", "/World/Oven/SpeakerA"]
    assert env.framed == [("/World/Oven", "/World/Oven/SpeakerA")]
    assert record["attempts"][0]["method"] == "viewport_utility.frame_viewport_prims"
    assert record["attempts"][1]["method"] == (
        "viewport_utility.capture_viewport_to_file"
    )


def test_live_ux_screenshot_falls_back_to_legacy_capture(monkeypatch, tmp_path):
    path = tmp_path / "legacy.viewport.png"

    class LegacyViewport:
        camera_path = SimpleNamespace(pathString="/World/LegacyCamera")

        def capture_to_file(self, file_path: str) -> object:
            _write_test_png(Path(file_path), width=23, height=29)
            return SimpleNamespace(wait=lambda: "done")

    _install_viewport_modules(monkeypatch, viewport=LegacyViewport())
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "viewport.capture_to_file"
    assert record["width"] == 23
    assert record["height"] == 29
    methods = [attempt["method"] for attempt in record["attempts"]]
    assert methods == [
        "viewport_utility.capture_viewport_to_file",
        "viewport.capture_to_file",
    ]


def test_live_ux_screenshot_waits_for_scheduled_kit_capture(monkeypatch, tmp_path):
    path = tmp_path / "scheduled.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    class App:
        updates = 0

        def update(self) -> None:
            self.updates += 1
            if self.updates == 3:
                _write_test_png(path, width=37, height=39)

    def capture_viewport_to_file(_viewport: object, *, file_path: str) -> object:
        assert file_path == str(path)
        return SimpleNamespace(wait_for_result=lambda: None)

    app = App()
    _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        utility_capture=capture_viewport_to_file,
        app=app,
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "viewport_utility.capture_viewport_to_file"
    assert record["width"] == 37
    assert record["height"] == 39
    assert record["attempts"][0]["file_wait"] == {"status": "ready", "updates": 3}


def test_live_ux_screenshot_falls_back_to_renderer_capture(monkeypatch, tmp_path):
    path = tmp_path / "renderer.viewport.png"
    viewport = SimpleNamespace(camera_path=SimpleNamespace(pathString="/World/Camera"))

    class RendererCapture:
        def capture_next_frame_swapchain(self, file_path: str) -> object:
            _write_test_png(Path(file_path), width=41, height=43)
            return "scheduled"

        def wait_async_capture(self) -> object:
            return "done"

    _install_viewport_modules(
        monkeypatch,
        viewport=viewport,
        renderer=RendererCapture(),
    )
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "captured"
    assert record["method"] == "renderer_capture.capture_next_frame_swapchain"
    assert record["width"] == 41
    assert record["height"] == 43
    methods = [attempt["method"] for attempt in record["attempts"]]
    assert methods == [
        "viewport_utility.capture_viewport_to_file",
        "viewport.capture_to_file",
        "renderer_capture.capture_next_frame_swapchain",
    ]


def test_live_ux_screenshot_records_no_active_viewport(monkeypatch, tmp_path):
    path = tmp_path / "missing.viewport.png"
    _install_viewport_modules(monkeypatch, viewport=None)
    live_ux = _load_live_ux_script(monkeypatch)

    record = live_ux._capture_viewport_screenshot(path)

    assert record["status"] == "unavailable"
    assert record["path"] == str(path)
    assert record["reason"] == "no active viewport"
    assert record["file_size_bytes"] == 0
    assert record["width"] is None
    assert record["height"] is None
    assert record["attempts"] == []


def test_live_ux_required_screenshot_raises_for_unavailable(monkeypatch):
    live_ux = _load_live_ux_script(monkeypatch)

    with pytest.raises(RuntimeError, match="Viewport screenshot capture is required"):
        live_ux._enforce_required_screenshot(
            {"status": "unavailable", "reason": "no active viewport"},
            "generic_scene",
        )


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


def test_kit_stage_has_prim_uses_sdf_path_for_strict_isaac_stage(
    monkeypatch,
):
    pxr = ModuleType("pxr")
    sdf = ModuleType("pxr.Sdf")

    class SdfPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    sdf.Path = SdfPath
    pxr.Sdf = sdf
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    monkeypatch.setitem(sys.modules, "pxr.Sdf", sdf)

    class StrictStage(_FakeStage):
        def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
            super().__init__(prims)
            self.calls: list[str] = []

        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            self.calls.append(type(path).__name__)
            if isinstance(path, str):
                raise TypeError("expected Sdf.Path")
            return super().GetPrimAtPath(str(path))

    stage = StrictStage((_FakePrim("/World/Room/Geometry/object", "Xform"),))

    assert _stage_has_prim(stage, "/World/Room/Geometry/object") is True
    assert stage.calls == ["SdfPath"]


def test_kit_stage_has_prim_falls_back_to_traverse_after_type_error():
    class RejectingStage(_FakeStage):
        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            raise TypeError(f"unsupported path type: {type(path).__name__}")

    stage = RejectingStage((_FakePrim("/World/Oven", "Xform"),))

    assert _stage_has_prim(stage, "/World/Oven") is True


def test_live_ux_stage_helpers_use_sdf_path_for_strict_isaac_stage(
    monkeypatch,
):
    live_ux = _load_live_ux_script(monkeypatch)
    pxr = ModuleType("pxr")
    sdf = ModuleType("pxr.Sdf")

    class SdfPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    sdf.Path = SdfPath
    pxr.Sdf = sdf
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    monkeypatch.setitem(sys.modules, "pxr.Sdf", sdf)

    class StrictStage(_FakeStage):
        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            if isinstance(path, str):
                raise TypeError("expected Sdf.Path")
            return super().GetPrimAtPath(str(path))

    prim = _FakePrim("/World/Oven", "Xform")
    stage = StrictStage((prim,))

    assert live_ux._stage_get_prim_at_path(stage, "/World/Oven") is prim
    assert live_ux._stage_has_prim(stage, "/World/Oven") is True


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
        actions=action_registry,
        menu=menu_utils,
        hotkeys=hotkey_registry,
    )


def test_omni_extension_entrypoint_import_smoke_without_isaac_modules():
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


def test_kit_resolves_relative_outputs_against_repo(monkeypatch):
    monkeypatch.delenv(OUTPUT_ROOT_ENV_VAR, raising=False)
    repo = Path(__file__).resolve().parents[2]
    root = (repo / "outputs" / "isaac_audio_sensors").resolve()

    assert _gui_output_root() == root
    assert _resolve_gui_output_path("gui_manual_binding.json") == (
        root / "gui_manual_binding.json"
    )
    assert _resolve_gui_output_path("manual/binding.json") == (
        root / "manual" / "binding.json"
    )
    assert _resolve_gui_output_path(
        "outputs/isaac_audio_sensors/gui_manual_binding.json"
    ) == (root / "gui_manual_binding.json")


def test_extension_controller_config_paths_use_output_root_env(
    monkeypatch,
    tmp_path,
):
    output_root = tmp_path / "ias_outputs"
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(output_root))
    controller = ExtensionController()
    controller.state.source_prim_path = "/World/Oven/SpeakerA"
    controller.state.object_prim_path = "/World/Oven"
    controller.state.object_label = "Oven"
    controller.state.source_attached_to_object = True
    controller.state.attached_object_prim_path = "/World/Oven"
    controller.state.source_local_offset_x_m = 0.25
    controller.state.source_local_offset_y_m = 0.5
    controller.state.source_local_offset_z_m = 0.75

    controller.state.config_export_path = "gui_manual_binding.json"
    path = controller.export_config_summary()

    assert path == output_root / "gui_manual_binding.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["source"]["prim_path"] == "/World/Oven/SpeakerA"
    assert summary["object_binding"] == {
        "attached": True,
        "attached_object_prim_path": "/World/Oven",
        "selected_object_label": "Oven",
        "selected_object_prim_path": "/World/Oven",
        "source_local_offset_m": [0.25, 0.5, 0.75],
    }
    assert summary["lifecycle"]["writer_path"] == str(
        output_root / "extension_trace.frames.jsonl"
    )

    imported = ExtensionController()
    imported.state.config_import_path = "gui_manual_binding.json"
    assert imported.import_config_summary() == path
    assert imported.state.config_import_path == "gui_manual_binding.json"
    assert imported.state.array_prim_path == "/World/Rig/AudioArray"
    assert imported.state.source_prim_path == "/World/Oven/SpeakerA"
    assert imported.state.object_prim_path == "/World/Oven"
    assert imported.state.source_attached_to_object is True
    assert imported.state.attached_object_prim_path == "/World/Oven"
    assert imported.state.source_local_offset_x_m == 0.25
    assert imported.state.source_local_offset_y_m == 0.5
    assert imported.state.source_local_offset_z_m == 0.75

    controller.state.config_export_path = "manual/binding.json"
    assert controller.export_config_summary() == output_root / "manual" / "binding.json"

    absolute_path = tmp_path / "absolute_binding.json"
    controller.state.config_export_path = str(absolute_path)
    assert controller.export_config_summary() == absolute_path


def test_sound_profiles_validate_default_library_and_safe_assets():
    profiles = default_sound_profiles()
    profile_ids = tuple(profile.profile_id for profile in profiles)

    assert profile_ids == (
        "speech_generic",
        "oven_stove",
        "sink_water",
        "door_knock",
        "footsteps_movement",
    )
    assert len(set(profile_ids)) == len(profile_ids)
    assert {profile.audio_asset_path for profile in profiles} <= {
        "generated://impulse",
        "generated://pulse",
    }
    assert default_object_profile_mappings(profiles)["oven"] == "oven_stove"
    assert default_object_profile_mappings(profiles)["sink"] == "sink_water"

    with pytest.raises(ValueError, match="audio_asset_path"):
        SoundProfile(
            profile_id="unsafe",
            display_label="Unsafe",
            object_label_aliases=("unsafe",),
            source_id_template="{object_slug}_source",
            class_label="Unsafe",
            audio_asset_path="/tmp/private.wav",
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        )

    with pytest.raises(ValueError, match="duration_s"):
        SoundProfile(
            profile_id="bad_duration",
            display_label="Bad Duration",
            object_label_aliases=("bad",),
            source_id_template="{object_slug}_source",
            class_label="Bad",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=0.0,
            gain_db=0.0,
        )


def test_extension_controller_manual_profile_apply_authors_source_metadata():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),
            _FakePrim("/World/Sink", "Xform", {"xformOp:translate": (1, 0, 0)}),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.source_prim_path = "/World/Sources/SinkSpeaker"
    controller.state.source_position_x_m = 1.5
    controller.state.source_position_y_m = 0.25
    controller.state.source_position_z_m = 0.0
    controller.state.object_prim_path = "/World/Sink"
    controller.state.object_label = "Sink"
    controller.state.selected_profile_id = "sink_water"

    authored = controller.apply_selected_profile(stage=stage)

    assert authored is not None
    assert authored.kind == "source_profile"
    assert controller.state.source_prim_path == "/World/Sources/SinkSpeaker"
    assert controller.state.source_attached_to_object is False
    assert controller.state.source_id == "sink_source"
    assert controller.state.source_class_label == "Water"
    assert controller.state.audio_asset_path == "generated://pulse"
    assert controller.state.source_gain_db == -2.0
    source = stage.GetPrimAtPath("/World/Sources/SinkSpeaker")
    assert source is not None
    assert source.attributes["filePath"] == "generated://pulse"
    assert source.attributes["ias:source_id"] == "sink_source"
    assert source.attributes["ias:class_label"] == "Water"
    assert source.attributes["ias:audio_asset_path"] == "generated://pulse"
    assert source.attributes["ias:start_time_s"] == 0.0
    assert source.attributes["ias:duration_s"] == 1.2
    assert source.attributes["ias:gain_db"] == -2.0
    assert source.attributes["ias:directivity"] == "omni"
    assert source.attributes["ias:sound_profile_id"] == "sink_water"
    assert source.attributes["xformOp:translate"] == (1.5, 0.25, 0.0)
    assert controller.state.applied_source_profile["profile_id"] == "sink_water"


def test_extension_controller_auto_profile_match_uses_object_labels_and_aliases():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),
            _FakePrim(
                "/World/Kitchen/FixtureA",
                "Mesh",
                {
                    "xformOp:translate": (0, 0, 0),
                    "semantic:class": "Sink",
                },
            ),
            _FakePrim(
                "/World/Kitchen/Countertop",
                "Mesh",
                {"xformOp:translate": (0, 1, 0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )

    matched = controller.auto_select_profile_from_object(
        stage=stage,
        selected_paths=("/World/Kitchen/FixtureA",),
    )
    assert matched is not None
    assert matched.profile_id == "sink_water"
    assert controller.state.selected_profile_id == "sink_water"
    assert "Auto-selected" in controller.state.status_message

    controller.state.object_prim_path = ""
    controller.state.object_label = "none"
    controller.state.attached_object_prim_path = ""
    no_match = controller.auto_select_profile_from_object(
        stage=stage,
        selected_paths=("/World/Kitchen/Countertop",),
    )
    assert no_match is None
    assert controller.state.error_message is not None
    assert "No sound profile matches object labels" in controller.state.error_message


def test_extension_controller_profile_apply_preserves_attachment_and_frame_metadata(
    tmp_path,
):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Oven",),
        )
        == "/World/Oven"
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    controller.state.selected_profile_id = "oven_stove"
    applied = controller.apply_selected_profile(stage=stage)

    assert applied is not None
    assert controller.state.source_prim_path == "/World/Oven/SpeakerA"
    assert controller.state.source_attached_to_object is True
    assert controller.state.attached_object_prim_path == "/World/Oven"
    assert controller.state.source_id == "oven_source"
    source = stage.GetPrimAtPath("/World/Oven/SpeakerA")
    assert source is not None
    assert source.attributes["filePath"] == "generated://pulse"
    assert source.attributes["ias:source_id"] == "oven_source"
    assert source.attributes["ias:class_label"] == "Appliance"
    assert source.attributes["ias:audio_asset_path"] == "generated://pulse"
    assert source.attributes["ias:attached_object_prim_path"] == "/World/Oven"
    assert source.attributes["ias:source_local_offset_m"] == (0.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (0.0, 0.0, 0.0)
    assert "ias:position_world" not in source.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    moved_frame = controller.update_sensor()

    assert first_frame is not None
    assert moved_frame is not None
    first_detection = first_frame.detections[0]
    moved_detection = moved_frame.detections[0]
    assert first_detection.source_id == "oven_source"
    assert first_detection.class_label == "Appliance"
    assert first_detection.audio_asset_path == "generated://pulse"
    assert first_detection.source_pose.position_m == (2.0, 0.0, 0.0)
    assert moved_detection.source_pose.position_m == (0.0, 2.0, 0.0)
    assert controller.state.latest_source_prim_path == "/World/Oven/SpeakerA"


def test_extension_controller_profile_config_roundtrip_legacy_and_errors(tmp_path):
    controller = ExtensionController()
    controller.state.config_export_path = str(tmp_path / "profiles_config.json")
    controller.state.object_prim_path = "/World/Oven"
    controller.state.object_label = "Oven"
    controller.state.source_prim_path = "/World/Oven/SpeakerA"
    controller.state.source_attached_to_object = True
    controller.state.attached_object_prim_path = "/World/Oven"
    controller.state.selected_profile_id = "oven_stove"
    controller.state.applied_source_profile = {
        "profile_id": "oven_stove",
        "source_id": "oven_source",
        "class_label": "Appliance",
        "audio_asset_path": "generated://pulse",
    }

    config_path = controller.export_config_summary()
    assert config_path == tmp_path / "profiles_config.json"
    summary = json.loads(config_path.read_text(encoding="utf-8"))
    assert summary["source"]["directivity"] == "omni"
    assert summary["sound_profiles"]["selected_profile_id"] == "oven_stove"
    assert summary["sound_profiles"]["object_profile_mappings"]["oven"] == (
        "oven_stove"
    )
    assert summary["sound_profiles"]["applied_source_profile"]["profile_id"] == (
        "oven_stove"
    )

    imported = ExtensionController()
    assert imported.import_config_summary(config_path) == config_path
    assert imported.state.selected_profile_id == "oven_stove"
    assert tuple(profile.profile_id for profile in imported.state.profile_library) == (
        "door_knock",
        "footsteps_movement",
        "oven_stove",
        "sink_water",
        "speech_generic",
    )
    assert imported.state.object_profile_mappings["oven"] == "oven_stove"
    assert imported.state.applied_source_profile["source_id"] == "oven_source"

    legacy = dict(summary)
    legacy.pop("sound_profiles")
    legacy_path = tmp_path / "legacy_config.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_imported = ExtensionController()
    assert legacy_imported.import_config_summary(legacy_path) == legacy_path
    assert legacy_imported.state.selected_profile_id == "speech_generic"

    unknown = dict(summary)
    unknown["sound_profiles"] = dict(summary["sound_profiles"])
    unknown["sound_profiles"]["selected_profile_id"] = "missing_profile"
    unknown_path = tmp_path / "unknown_profile.json"
    unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
    unknown_imported = ExtensionController()
    assert unknown_imported.import_config_summary(unknown_path) is None
    assert unknown_imported.state.error_message is not None
    assert "Unknown selected sound profile id" in unknown_imported.state.error_message

    missing_mapping = dict(summary)
    missing_mapping["sound_profiles"] = dict(summary["sound_profiles"])
    missing_mapping["sound_profiles"].pop("object_profile_mappings")
    missing_mapping_path = tmp_path / "missing_mapping.json"
    missing_mapping_path.write_text(json.dumps(missing_mapping), encoding="utf-8")
    missing_mapping_imported = ExtensionController()
    assert missing_mapping_imported.import_config_summary(missing_mapping_path) is None
    assert missing_mapping_imported.state.error_message is not None
    assert "object_profile_mappings is required" in (
        missing_mapping_imported.state.error_message
    )


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


def test_extension_controller_attaches_source_to_object_and_motion_updates_frame(
    tmp_path,
):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Oven",),
        )
        == "/World/Oven"
    )
    attached = controller.attach_source_to_object(stage=stage)

    assert attached is not None
    assert attached.prim_path == "/World/Oven/SpeakerA"
    source = stage.GetPrimAtPath("/World/Oven/SpeakerA")
    assert source is not None
    assert source.attributes["ias:source_id"] == "speaker_a"
    assert source.attributes["ias:class_label"] == "Speech"
    assert source.attributes["ias:audio_asset_path"] == "generated://impulse"
    assert source.attributes["ias:attached_object_prim_path"] == "/World/Oven"
    assert source.attributes["ias:source_local_offset_m"] == (0.0, 0.0, 0.0)
    assert source.attributes["xformOp:translate"] == (0.0, 0.0, 0.0)
    assert "ias:position_world" not in source.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    moved_frame = controller.update_sensor()

    assert first_frame is not None
    assert moved_frame is not None
    first_detection = first_frame.detections[0]
    moved_detection = moved_frame.detections[0]
    assert first_detection.source_pose.position_m == (2.0, 0.0, 0.0)
    assert first_detection.doa.bearing_sector == "straight"
    assert moved_detection.source_pose.position_m == (0.0, 2.0, 0.0)
    assert moved_detection.doa.estimated_bearing_deg == 90.0
    assert moved_detection.doa.bearing_sector == "right"
    assert moved_frame.aggregate_per_mic_rms != first_frame.aggregate_per_mic_rms
    assert controller.state.latest_source_prim_path == "/World/Oven/SpeakerA"
    assert controller.state.latest_source_position_m == (0.0, 2.0, 0.0)
    assert controller.state.latest_aggregate_rms == moved_frame.aggregate_per_mic_rms

    detached = controller.detach_source_from_object(stage=stage)
    assert detached is not None
    detached_source = stage.GetPrimAtPath("/World/Sources/SpeakerA")
    assert detached_source is not None
    assert stage.GetPrimAtPath("/World/Oven/SpeakerA") is None
    assert "ias:attached_object_prim_path" not in detached_source.attributes
    assert detached_source.attributes["ias:position_world"] == (0.0, 2.0, 0.0)
    assert detached_source.attributes["xformOp:translate"] == (0.0, 2.0, 0.0)

    oven.attributes["xformOp:translate"] = (5.0, 0.0, 0.0)
    after_detach_frame = controller.update_sensor()
    assert after_detach_frame is not None
    assert after_detach_frame.detections[0].source_pose.position_m == (
        0.0,
        2.0,
        0.0,
    )


def test_extension_controller_array_pose_read_apply_and_drag_update(tmp_path):
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (2.0, 0.0, 0.0),
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
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    front_frame = controller.update_sensor()
    assert front_frame is not None
    front_detection = front_frame.detections[0]
    assert abs(front_detection.doa.estimated_bearing_deg) <= 1e-6
    assert front_detection.doa.bearing_sector == "straight"
    assert controller.state.latest_array_position_m == (0.0, 0.0, 0.0)
    front_mics = dict(controller.state.latest_mic_world_positions)
    assert front_mics["front"] == pytest.approx((0.08, 0.0, 0.0))

    controller.state.array_yaw_deg = 90.0
    assert controller.apply_array_pose(stage=stage) is not None
    array_prim = stage.GetPrimAtPath("/World/Rig/AudioArray")
    assert array_prim is not None
    expected_quat = quaternion_from_yaw_deg(90.0)
    assert array_prim.attributes["ias:orientation_world_quat"] == pytest.approx(
        expected_quat
    )
    assert array_prim.attributes["xformOp:orient"] == pytest.approx(expected_quat)

    rotated_frame = controller.update_sensor()
    assert rotated_frame is not None
    rotated_detection = rotated_frame.detections[0]
    assert rotated_detection.doa.estimated_bearing_deg == pytest.approx(270.0)
    assert rotated_detection.doa.bearing_sector == "left"
    assert rotated_frame.aggregate_per_mic_rms != front_frame.aggregate_per_mic_rms
    assert rotated_frame.array_pose is not None
    assert rotated_frame.array_pose.orientation_xyzw == pytest.approx(expected_quat)
    assert controller.state.latest_array_orientation_xyzw == pytest.approx(
        expected_quat
    )
    assert controller.state.latest_mic_world_positions != front_mics
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (0.0, 0.08, 0.0),
        abs=1e-9,
    )

    array_prim.attributes["xformOp:translate"] = (1.0, 1.0, 0.0)
    array_prim.attributes["xformOp:orient"] = (0.0, 0.0, 0.0, 1.0)
    dragged_frame = controller.update_sensor()
    assert dragged_frame is not None
    assert dragged_frame.array_pose is not None
    assert dragged_frame.array_pose.position_m == (1.0, 1.0, 0.0)
    dragged_detection = dragged_frame.detections[0]
    assert dragged_detection.doa.estimated_bearing_deg == pytest.approx(315.0)
    assert dragged_detection.doa.bearing_sector == "straight_left"
    assert array_prim.attributes["ias:position_world"] == (0.0, 0.0, 0.0)
    assert controller.state.latest_array_position_m == (1.0, 1.0, 0.0)
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (1.08, 1.0, 0.0)
    )

    read_position = controller.read_selected_array_transform(
        stage=stage,
        selected_paths=("/World/Rig/AudioArray",),
    )
    assert read_position == (1.0, 1.0, 0.0)
    assert controller.state.array_position_x_m == 1.0
    assert controller.state.array_position_y_m == 1.0
    assert controller.state.array_yaw_deg == pytest.approx(0.0)


def test_extension_controller_attaches_array_to_object_and_motion_updates_frame(
    tmp_path,
):
    mount_link = _FakePrim(
        "/World/Robot/mount_link",
        "Xform",
        {"xformOp:translate": (0.0, 0.0, 1.0)},
    )
    source = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:duration_s": 10.0,
            "xformOp:translate": (2.0, 0.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            mount_link,
            source,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Robot/mount_link",),
        )
        == "/World/Robot/mount_link"
    )
    controller.state.array_local_offset_z_m = 0.1
    attached = controller.attach_array_to_object(stage=stage)

    assert attached is not None
    assert attached.prim_path == "/World/Robot/mount_link/AudioArray"
    assert controller.state.array_prim_path == "/World/Robot/mount_link/AudioArray"
    assert controller.state.array_attached_to_object is True
    array_prim = stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray")
    assert array_prim is not None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray") is None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/front") is None
    moved_mic = stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray/front")
    assert moved_mic is not None
    assert moved_mic.attributes["ias:microphone_id"] == "front"
    assert array_prim.attributes["ias:attached_object_prim_path"] == (
        "/World/Robot/mount_link"
    )
    assert array_prim.attributes["ias:array_local_offset_m"] == (0.0, 0.0, 0.1)
    assert array_prim.attributes["xformOp:translate"] == (0.0, 0.0, 0.1)
    assert "ias:position_world" not in array_prim.attributes

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    first_frame = controller.update_sensor()
    assert first_frame is not None
    assert first_frame.array_pose is not None
    assert first_frame.array_pose.position_m == pytest.approx((0.0, 0.0, 1.1))
    first_detection = first_frame.detections[0]
    assert first_detection.doa.bearing_sector == "straight"
    first_mics = dict(controller.state.latest_mic_world_positions)
    assert first_mics["front"] == pytest.approx((0.08, 0.0, 1.1))

    mount_link.attributes["xformOp:translate"] = (0.0, 2.0, 1.0)
    moved_frame = controller.update_sensor()
    assert moved_frame is not None
    assert moved_frame.array_pose is not None
    assert moved_frame.array_pose.position_m == pytest.approx((0.0, 2.0, 1.1))
    moved_detection = moved_frame.detections[0]
    assert moved_detection.doa.estimated_bearing_deg == pytest.approx(315.0)
    assert moved_detection.doa.bearing_sector == "straight_left"
    assert moved_frame.aggregate_per_mic_rms != first_frame.aggregate_per_mic_rms
    assert controller.state.latest_array_position_m == pytest.approx((0.0, 2.0, 1.1))
    assert controller.state.latest_mic_world_positions != first_mics
    assert controller.state.latest_mic_world_positions["front"] == pytest.approx(
        (0.08, 2.0, 1.1)
    )

    mount_link.attributes["xformOp:orient"] = quaternion_from_yaw_deg(90.0)
    rotated_frame = controller.update_sensor()
    assert rotated_frame is not None
    assert rotated_frame.array_pose is not None
    assert rotated_frame.array_pose.orientation_xyzw == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )
    rotated_detection = rotated_frame.detections[0]
    assert rotated_detection.doa.estimated_bearing_deg == pytest.approx(225.0)
    assert rotated_detection.doa.bearing_sector == "behind_left"

    detached = controller.detach_array_from_object(stage=stage)
    assert detached is not None
    detached_prim = stage.GetPrimAtPath("/World/AudioArrays/AudioArray")
    assert detached_prim is not None
    assert stage.GetPrimAtPath("/World/Robot/mount_link/AudioArray") is None
    assert stage.GetPrimAtPath("/World/AudioArrays/AudioArray/front") is not None
    assert "ias:attached_object_prim_path" not in detached_prim.attributes
    assert detached_prim.attributes["ias:position_world"] == pytest.approx(
        (0.0, 2.0, 1.1)
    )
    assert detached_prim.attributes["xformOp:orient"] == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )
    assert controller.state.array_attached_to_object is False
    assert controller.state.array_prim_path == "/World/AudioArrays/AudioArray"

    mount_link.attributes["xformOp:translate"] = (5.0, 0.0, 1.0)
    after_detach_frame = controller.update_sensor()
    assert after_detach_frame is not None
    assert after_detach_frame.array_pose is not None
    assert after_detach_frame.array_pose.position_m == pytest.approx(
        (0.0, 2.0, 1.1)
    )


def test_extension_controller_rig_profile_select_apply_and_config_roundtrip(
    tmp_path,
):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.config_export_path = str(tmp_path / "binding.json")

    assert controller.author_array(stage=stage) is not None
    profile = controller.select_rig_profile("quad_cross_120mm")
    assert profile is not None
    assert controller.apply_selected_rig_profile(stage=stage) is not None
    array_prim = stage.GetPrimAtPath("/World/Rig/AudioArray")
    assert array_prim is not None
    assert array_prim.attributes["ias:rig_profile_id"] == "quad_cross_120mm"
    assert array_prim.attributes["ias:layout_name"] == "quad_cross"
    assert array_prim.attributes["ias:sample_rate_hz"] == 48_000
    assert array_prim.attributes["ias:microphone_ids"] == (
        "front",
        "right",
        "rear",
        "left",
    )
    assert array_prim.attributes["ias:microphone_relative_offsets_m"][0] == (
        0.06,
        0.0,
        0.0,
    )
    front_mic = stage.GetPrimAtPath("/World/Rig/AudioArray/front")
    assert front_mic is not None
    assert front_mic.attributes["ias:gain_db"] == 0.0
    assert front_mic.attributes["ias:relative_position_m"] == (0.06, 0.0, 0.0)
    assert controller.state.applied_array_rig_profile["profile_id"] == (
        "quad_cross_120mm"
    )
    assert controller.state.array_local_offset_z_m == pytest.approx(0.0)
    assert controller.state.layout_name == "quad_cross"

    assert controller.select_rig_profile("stereo_y_100mm") is not None
    assert controller.apply_selected_rig_profile(stage=stage) is not None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/front") is None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/rear") is None
    left_mic = stage.GetPrimAtPath("/World/Rig/AudioArray/left")
    assert left_mic is not None
    assert left_mic.attributes["ias:relative_position_m"] == (0.0, -0.05, 0.0)
    assert controller.state.array_local_offset_x_m == pytest.approx(0.0)

    controller.state.array_position_x_m = 1.0
    controller.state.array_position_y_m = 2.0
    controller.state.array_yaw_deg = 90.0
    path = controller.export_config_summary()
    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["array"]["position_world"] == [1.0, 2.0, 0.0]
    rig_section = payload["microphone_rig_profiles"]
    assert rig_section["selected_rig_profile_id"] == "stereo_y_100mm"
    assert len(rig_section["rig_library"]) == 2
    assert payload["array_binding"]["attached"] is False
    assert payload["array_binding"]["array_local_offset_m"] == [0.0, 0.0, 0.0]

    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert imported.state.selected_rig_profile_id == "stereo_y_100mm"
    assert {
        item.profile_id for item in imported.state.rig_profile_library
    } == {
        "quad_cross_120mm",
        "stereo_y_100mm",
    }
    assert imported.state.array_position_x_m == pytest.approx(1.0)
    assert imported.state.array_position_y_m == pytest.approx(2.0)
    assert imported.state.array_yaw_deg == pytest.approx(90.0)
    assert imported.state.array_local_offset_x_m == pytest.approx(0.0)
    assert imported.state.applied_array_rig_profile["profile_id"] == (
        "stereo_y_100mm"
    )

    legacy_payload = {
        "schema_version": "ias.omni_extension_binding.v1",
        "backend": "geometry_only",
        "array": {"prim_path": "/World/Rig/AudioArray", "array_id": "legacy_rig"},
        "source": {"prim_path": "/World/Sources/SpeakerA"},
    }
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    legacy = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert legacy.import_config_summary(legacy_path) == legacy_path
    assert legacy.state.error_message is None
    assert legacy.state.array_id == "legacy_rig"
    assert legacy.state.array_attached_to_object is False
    assert [item.profile_id for item in legacy.state.rig_profile_library] == [
        item.profile_id for item in default_microphone_rig_profiles()
    ]


def test_extension_controller_auto_update_refreshes_live_frame_state_and_rms(
    monkeypatch,
    tmp_path,
):
    omni = ModuleType("omni")
    omni.__path__ = []
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    stream = _install_fake_kit_update_stream(monkeypatch)
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "tdoa_synthetic"
    controller.state.update_period_s = 0.01
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    window._float_fields["source_position_x_m"].model.set_value("typing")

    stream.trigger()
    first_position = controller.state.latest_source_position_m
    first_bearing = controller.state.latest_bearing_deg
    first_sector = controller.state.latest_sector
    first_rms = dict(controller.state.latest_aggregate_rms)

    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    stream.trigger()

    assert first_position == (2.0, 0.0, 0.0)
    assert first_sector == "straight"
    assert controller.state.latest_source_position_m == (0.0, 2.0, 0.0)
    assert controller.state.latest_bearing_deg != first_bearing
    assert controller.state.latest_sector == "right"
    assert controller.state.latest_aggregate_rms != first_rms
    assert window._float_fields["source_position_x_m"].model.value == "typing"
    assert "Frame: " in window._labels["latest"].text
    visible_meters = [
        row for row in window._instruments["meters"] if row["row"].visible
    ]
    assert visible_meters
    assert all(
        "dB" in row["label"].text or "silent" in row["label"].text
        for row in visible_meters
    )
    assert controller.state.detection_history
    assert any(label.visible for label in window._instruments["timeline"])


def test_extension_controller_auto_update_skips_duplicate_replicator_writes(
    monkeypatch,
    tmp_path,
):
    _install_fake_replicator(monkeypatch)
    stream = _install_fake_kit_update_stream(monkeypatch, timeline_time_s=0.0)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "tdoa_synthetic"
    controller.state.update_period_s = 10.0
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    assert controller.start_replicator() is not None

    stream.trigger()
    stream.trigger()

    assert controller.state.replicator_write_count == 1

    source = stage.GetPrimAtPath("/World/Sources/SpeakerA")
    assert source is not None
    source.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    forced = controller.update_sensor()

    assert forced is not None
    assert controller.state.latest_sector == "right"
    assert controller.state.replicator_write_count == 2


def test_sensor_update_stream_subscription_respects_update_period(monkeypatch):
    stream = _install_fake_kit_update_stream(monkeypatch, timeline_time_s=0.0)
    config = load_audio_config("examples/configs/isaac_audio_sensors_demo.toml")
    sensor = IsaacAudioArraySensor.from_config(
        config=config,
        array_id=next(iter(config.arrays)),
        update_period_s=0.05,
    )
    sensor.start(subscribe_to_update_stream=True)

    stream.trigger()
    first_frame = sensor.latest_frame
    assert first_frame is not None
    assert first_frame.frame_index == 0

    for time_s in (0.01, 0.02, 0.03):
        stream.timeline_clock.time_s = time_s
        stream.trigger()

    assert sensor.latest_frame is first_frame

    stream.timeline_clock.time_s = 0.06
    stream.trigger()

    assert sensor.latest_frame is not first_frame
    assert sensor.latest_frame.frame_index == 1
    sensor.close()


def test_extension_controller_create_demo_object_authors_visible_cube():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )

    assert controller.create_demo_object(stage=stage) == "/World/Oven"

    oven = stage.GetPrimAtPath("/World/Oven")
    assert oven is not None
    assert oven.type_name == "Cube"
    assert oven.attributes["xformOp:translate"] == (2.0, 0.0, 0.0)
    assert oven.attributes["size"] == 0.9
    assert oven.attributes["displayColor"] == (0.95, 0.48, 0.08)
    assert oven.attributes["displayOpacity"] == 1.0
    assert oven.attributes["doubleSided"] is True
    assert controller.state.object_prim_path == "/World/Oven"
    assert controller.state.object_label == "Oven"
    assert stage.GetPrimAtPath("/World/KeyLight") is not None
    assert stage.GetPrimAtPath("/World/DemoObjectDomeLight") is not None
    assert stage.GetPrimAtPath("/World/DemoObjectFillLight") is not None


def test_extension_controller_attached_source_outside_world_is_captured(tmp_path):
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/Kitchen",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/Kitchen/Refrigerator",
                "Xform",
                {"xformOp:translate": (2.0, 0.0, 0.0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/Kitchen/Refrigerator",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.state.source_prim_path == "/Kitchen/Refrigerator/SpeakerA"

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()

    assert frame is not None
    assert frame.detections[0].source_id == "speaker_a"
    assert frame.detections[0].source_pose.position_m == (2.0, 0.0, 0.0)


def test_extension_controller_object_local_offset_and_config_roundtrip(tmp_path):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (1.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.config_export_path = str(tmp_path / "binding.json")
    controller.state.source_local_offset_x_m = 0.0
    controller.state.source_local_offset_y_m = 1.0
    controller.state.source_local_offset_z_m = 0.25

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()
    assert frame is not None
    assert frame.detections[0].source_pose.position_m == (1.0, 1.0, 0.25)

    path = controller.export_config_summary()
    assert path == tmp_path / "binding.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["object_binding"] == {
        "attached": True,
        "attached_object_prim_path": "/World/Oven",
        "selected_object_label": "Oven",
        "selected_object_prim_path": "/World/Oven",
        "source_local_offset_m": [0.0, 1.0, 0.25],
    }
    assert summary["source"]["prim_path"] == "/World/Oven/SpeakerA"
    assert summary["source"]["local_offset_m"] == [0.0, 1.0, 0.25]
    assert any(
        item["prim_path"] == "/World/Oven/SpeakerA"
        for item in summary["authored_metadata"]
    )

    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert imported.state.object_prim_path == "/World/Oven"
    assert imported.state.object_label == "Oven"
    assert imported.state.source_attached_to_object is True
    assert imported.state.attached_object_prim_path == "/World/Oven"
    assert imported.state.source_prim_path == "/World/Oven/SpeakerA"
    assert imported.state.source_local_offset_x_m == 0.0
    assert imported.state.source_local_offset_y_m == 1.0
    assert imported.state.source_local_offset_z_m == 0.25
    assert imported.state.error_message is None


def test_extension_controller_missing_attached_object_is_readable(tmp_path):
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Oven",
                "Xform",
                {"xformOp:translate": (2.0, 0.0, 0.0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.config_export_path = str(tmp_path / "binding.json")

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    path = controller.export_config_summary()

    missing_stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(missing_stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert "attached object is missing" in str(imported.state.error_message)
    assert "/World/Oven" in str(imported.state.error_message)

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    assert controller.update_sensor() is not None
    stage.RemovePrim("/World/Oven")
    assert controller.update_sensor() is None
    assert "Attached object no longer exists: /World/Oven" in str(
        controller.state.error_message
    )


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


def test_kit_builds_against_fake_omni_ui(monkeypatch):
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
        "room_out_of_bounds",
        "waveform_mode",
    }
    assert set(controller._ui_window._int_fields) == {
        "max_events",
        "sample_rate_hz",
    }
    assert set(controller._ui_window._float_fields) == {
        "array_position_x_m",
        "array_position_y_m",
        "array_position_z_m",
        "array_yaw_deg",
        "array_pitch_deg",
        "array_roll_deg",
        "array_local_offset_x_m",
        "array_local_offset_y_m",
        "array_local_offset_z_m",
        "array_local_yaw_deg",
        "array_local_pitch_deg",
        "array_local_roll_deg",
        "source_local_offset_x_m",
        "source_local_offset_y_m",
        "source_local_offset_z_m",
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
        "follow_viewport_selection",
        "live_sync_array_pose",
        "live_sync_source_pose",
        "occlusion_enabled",
        "replicator_enabled",
        "trace_enabled",
        "usd_debug_enabled",
        "waveform_enabled",
    }
    assert "replicator_enabled" in controller._ui_window._bool_fields
    assert "replicator_output_dir" in controller._ui_window._string_fields
    assert "array_prim_path" in controller._ui_window._string_fields
    assert "source_prim_path" in controller._ui_window._string_fields
    assert "source_directivity" in controller._ui_window._string_fields
    assert "selected_profile_id" in controller._ui_window._string_fields
    assert "selected_rig_profile_id" in controller._ui_window._string_fields
    assert "object_prim_path" in controller._ui_window._string_fields
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
        "Room",
        "Instruments",
        "Audio Output",
        "Replicator",
        "Export",
    ]

    scrolling_frames = [
        widget for widget in omni_ui.created if widget.kind == "ScrollingFrame"
    ]
    assert len(scrolling_frames) == 2
    collapsable_frames = [
        widget for widget in omni_ui.created if widget.kind == "CollapsableFrame"
    ]
    assert [widget.text for widget in collapsable_frames] == [
        "Stage",
        "Author Array",
        "Author Source",
        "Sensor",
        "Room",
        "Instruments",
        "Audio Output",
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
        "Use Object",
        "Use Base",
        "Create Demo Object",
        "Discover",
        "Create/Attach Array",
        "Select Rig Profile",
        "Apply Rig Profile",
        "Read Array Transform",
        "Apply Array Pose",
        "Attach Array To Object",
        "Detach Array",
        "Read Selected Transform",
        "Apply Position",
        "Select Profile",
        "Auto From Object",
        "Apply Profile",
        "Front",
        "Right",
        "Left",
        "Behind",
        "Create/Attach Source",
        "Attach Source To Object",
        "Detach Source",
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
        "Use Object",
        "Use Base",
        "Create Demo Object",
        "Discover",
        "Create/Attach Array",
        "Select Rig Profile",
        "Apply Rig Profile",
        "Read Array Transform",
        "Apply Array Pose",
        "Attach Array To Object",
        "Detach Array",
        "Read Selected Transform",
        "Apply Position",
        "Select Profile",
        "Auto From Object",
        "Apply Profile",
        "Front",
        "Right",
        "Left",
        "Behind",
        "Create/Attach Source",
        "Attach Source To Object",
        "Detach Source",
        "Start",
        "Stop",
        "Update",
        "Flush",
        "Export Latest",
        "Export Config",
        "Load Config",
    } <= set(controller._ui_window._buttons)


def test_kit_instruments_show_compass_meters_and_timeline(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    controller.state.latest_frame_id = "frame_001"
    controller.state.latest_detection_count = 1
    controller.state.latest_backend = "tdoa_synthetic"
    controller.state.latest_source_prim_path = "/World/Sources/SpeakerA"
    controller.state.latest_source_position_m = (1.0, 2.0, 0.0)
    controller.state.latest_bearing_deg = 90.0
    controller.state.latest_sector = "right"
    controller.state.latest_bearing_confidence = 0.8
    controller.state.latest_occluded = False
    controller.state.latest_aggregate_rms = {
        "left": 0.2,
        "front": 0.24,
        "rear": 0.18,
        "right": 0.22,
    }
    controller.state.detection_history = [
        {
            "frame_id": "frame_001",
            "timestamp_ms": 1500,
            "source_id": "speaker_a",
            "class_label": "speech_generic",
            "bearing_deg": 90.0,
            "sector": "right",
            "occluded": False,
        }
    ]

    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None
    window.refresh_labels()

    latest = window._labels["latest"].text
    assert "Frame: frame_001" in latest
    assert "detections=1" in latest

    compass = window._labels["compass"].text
    assert "bearing 90.0 deg" in compass
    assert "sector right" in compass
    assert "confidence 0.80" in compass
    assert "clear" in compass
    provider = window._instruments["compass_provider"]
    assert provider.size == [192, 192]
    assert len(provider.data) == 192 * 192 * 4

    visible_meters = [
        row for row in window._instruments["meters"] if row["row"].visible
    ]
    assert [row["label"].text.split(":")[0] for row in visible_meters] == [
        "front",
        "right",
        "rear",
        "left",
    ]
    fractions = [row["bar"].model.value for row in visible_meters]
    assert all(0.0 < fraction <= 1.0 for fraction in fractions)
    assert fractions[0] == max(fractions)
    hidden_meters = [
        row for row in window._instruments["meters"] if not row["row"].visible
    ]
    assert hidden_meters

    timeline = [
        label.text for label in window._instruments["timeline"] if label.visible
    ]
    assert len(timeline) == 1
    assert "speech_generic" in timeline[0]
    assert "90.0 deg" in timeline[0]
    assert "clear" in timeline[0]


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


def test_extension_controller_follows_viewport_selection_via_stage_events(
    monkeypatch,
):
    from isaac_audio_sensors.kit import DiscoveredPrimSummary

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
    controller.state.follow_viewport_selection = True
    controller.state.discovered_arrays = (
        DiscoveredPrimSummary(
            id="rig_front",
            prim_path="/World/Rig/AudioArray",
            reasons=("name",),
        ),
    )
    controller.on_startup("isaac_audio_sensors.omni")
    assert controller._stage_event_subscription is not None

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
    controller.state.follow_viewport_selection = False
    stream.trigger(_FakeStageEventStream.SELECTION_CHANGED)
    assert controller.state.object_prim_path == "/World/Oven"
    controller.on_shutdown()
    assert controller._stage_event_subscription is None


def test_extension_controller_polling_fallback_follows_selection():
    from isaac_audio_sensors.kit import DiscoveredPrimSummary

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
    assert controller._stage_event_subscription is None

    selection[:] = ["/World/Sources/SpeakerA"]
    controller._viewport_follow_tick()
    assert controller.state.source_prim_path == "/World/Sources/SpeakerA"
    assert "adopted as source" in controller.state.status_message


def test_extension_controller_live_sync_pose_follows_prim_moves(monkeypatch):
    omni = ModuleType("omni")
    omni.__path__ = []
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
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
    assert controller.build_ui_if_available() is not None
    window = controller._ui_window

    controller._viewport_follow_tick()
    assert controller.state.source_position_x_m == 2.0
    assert controller.state.array_position_z_m == 1.0

    source_prim.attributes["xformOp:translate"] = (3.5, -1.0, 0.5)
    array_prim.attributes["xformOp:translate"] = (0.0, 2.0, 1.5)
    controller._viewport_follow_tick()
    assert controller.state.source_position_x_m == 3.5
    assert controller.state.source_position_y_m == -1.0
    assert controller.state.array_position_y_m == 2.0
    assert window._float_fields["source_position_x_m"].model.value == "3.5"

    # Disabled sync stops mirroring.
    controller.state.live_sync_source_pose = False
    source_prim.attributes["xformOp:translate"] = (9.0, 9.0, 9.0)
    controller._viewport_follow_tick()
    assert controller.state.source_position_x_m == 3.5


def test_extension_controller_authors_persistent_usd_debug_geometry(tmp_path):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "tdoa_synthetic"
    controller.state.usd_debug_enabled = True
    controller.state.trace_enabled = False

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    assert controller.update_sensor(force=True) is not None

    paths = controller.state.latest_usd_debug_prim_paths
    assert paths
    assert all(path.startswith("/World/IasAudioDebug/") for path in paths)
    kinds = {stage.GetPrimAtPath(path).type_name for path in paths}
    assert "Sphere" in kinds
    assert "BasisCurves" in kinds
    assert stage.GetPrimAtPath("/World/IasAudioDebug") is not None

    controller.state.usd_debug_enabled = False
    assert controller.update_sensor(force=True) is not None
    assert controller.state.latest_usd_debug_prim_paths == ()
    assert stage.GetPrimAtPath("/World/IasAudioDebug") is None


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


def test_extension_controller_waveform_settings_flow_to_sensor_and_config(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(tmp_path))
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "tdoa_synthetic"
    controller.state.waveform_enabled = True
    controller.state.waveform_dir = "wavs"
    controller.state.waveform_mode = "session"

    assert controller.author_array(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    sensor = controller.sensor
    assert sensor is not None
    assert str(sensor.waveform_dir) == str(tmp_path / "wavs")
    assert sensor.waveform_mode == "session"

    assert sensor.room is None  # default shoebox only applies to room_acoustics

    controller.state.config_export_path = str(tmp_path / "config.json")
    assert controller.export_config_summary() is not None

    restored = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    restored.state.config_import_path = str(tmp_path / "config.json")
    assert restored.import_config_summary() is not None
    assert restored.state.waveform_enabled is True
    assert restored.state.waveform_dir == "wavs"
    assert restored.state.waveform_mode == "session"


def test_extension_controller_room_backend_gets_default_shoebox(tmp_path):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "room_acoustics"
    assert controller.author_array(stage=stage) is not None
    assert controller.configure_sensor(stage=stage) is not None
    room = controller.sensor.room
    assert room is not None
    assert room.room_id == "ias_gui_default_room"
    assert room.dimensions_m == (6.0, 6.0, 3.0)
    # Without an anchor prim, the default room is explicitly centered on the
    # array (authored at the origin) instead of refitting per frame.
    assert room.origin_m == (-3.0, -3.0, -1.5)
    assert room.anchor_prim_path is None
    summary = controller.state.latest_room_summary
    assert summary is not None
    assert summary["origin_m"] == (-3.0, -3.0, -1.5)
    assert summary["absorption_provenance"] == "config"


def test_extension_controller_room_anchors_to_designated_prim():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Room",
                "Xform",
                {
                    "ias:room_min_world": (-2.0, -3.0, 0.0),
                    "ias:room_max_world": (6.0, 3.0, 3.0),
                    "ias:material": "carpet",
                },
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "room_acoustics"
    controller.state.room_anchor_prim_path = "/World/Room"
    controller.state.room_out_of_bounds = "clamp"
    assert controller.author_array(stage=stage) is not None
    assert controller.configure_sensor(stage=stage) is not None
    room = controller.sensor.room
    assert room is not None
    assert room.dimensions_m == (8.0, 6.0, 3.0)
    assert room.origin_m == (-2.0, -3.0, 0.0)
    assert room.anchor_prim_path == "/World/Room"
    assert room.absorption == 0.30  # carpet via the default semantic table
    assert room.out_of_bounds == "clamp"
    summary = controller.state.latest_room_summary
    assert summary is not None
    assert summary["absorption_provenance"] == "semantic:carpet"


def test_extension_controller_room_anchor_missing_prim_records_error():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "room_acoustics"
    controller.state.room_anchor_prim_path = "/World/MissingRoom"
    assert controller.author_array(stage=stage) is not None

    assert controller.configure_sensor(stage=stage) is None

    assert controller.sensor is None
    assert controller.state.error_message is not None
    assert "/World/MissingRoom" in controller.state.error_message


def test_kit_audio_panel_renders_waveform_preview(monkeypatch, tmp_path):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()
    wav_path = tmp_path / "frame_000001.wav"
    wav_path.write_bytes(_float32_wav_bytes())
    controller.state.latest_waveform_paths = (str(wav_path),)

    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None
    window.refresh_labels()

    label = window._labels["waveform"].text
    assert "frame_000001.wav" in label
    assert "1 ch" in label
    assert "8000 Hz" in label
    panel = window._audio_panel
    assert panel["rendered_path"] == str(wav_path)
    assert panel["waveform_provider"].size == [420, 96]
    assert panel["spectrogram_provider"].size == [420, 128]
    assert window._labels["audition"].text == "Audition idle."


def test_kit_audio_panel_reports_missing_waveform(monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()

    assert controller.build_ui_if_available() is not None
    window = controller._ui_window
    assert window is not None
    window.refresh_labels()

    assert "No waveform yet" in window._labels["waveform"].text


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



def test_kit_config_roundtrips_edited_widget_state(tmp_path, monkeypatch):
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
    window._string_fields["object_prim_path"].model.set_value("/World/EditedObject")
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
    window._float_fields["source_local_offset_x_m"].model.set_value("0.25")
    window._float_fields["source_local_offset_y_m"].model.set_value("0.5")
    window._float_fields["source_local_offset_z_m"].model.set_value("0.75")
    window._int_fields["sample_rate_hz"].model.set_value("44100")
    backend_widget, backend_choices = window._combo_fields["backend"]
    backend_widget.model.set_value(backend_choices.index("geometry_only"))
    layout_widget, layout_choices = window._combo_fields["layout_name"]
    layout_widget.model.set_value(layout_choices.index("mono"))
    ambiguity_widget, ambiguity_choices = window._combo_fields["ambiguity_policy"]
    ambiguity_widget.model.set_value(len(ambiguity_choices) - 1)
    window._bool_fields["debug_overlay_enabled"].model.set_value(False)
    window._bool_fields["occlusion_enabled"].model.set_value(True)
    window._bool_fields["trace_enabled"].model.set_value(True)
    window._bool_fields["replicator_enabled"].model.set_value(True)
    window.sync_state_from_widgets()

    assert controller.state.source_id == "edited_source"
    assert controller.state.source_duration_s == 60.0
    assert controller.state.source_position_y_m == 2.0
    assert controller.state.source_local_offset_z_m == 0.75
    assert controller.state.object_prim_path == "/World/EditedObject"
    assert controller.state.sample_rate_hz == 44100
    assert controller.state.backend == "geometry_only"
    assert controller.state.layout_name == "mono"
    assert controller.state.debug_overlay_enabled is False
    assert controller.state.occlusion_enabled is True
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
    assert summary["source"]["local_offset_m"] == [0.25, 0.5, 0.75]
    assert summary["object_binding"]["selected_object_prim_path"] == (
        "/World/EditedObject"
    )
    assert summary["object_binding"]["source_local_offset_m"] == [0.25, 0.5, 0.75]
    assert summary["backend"] == "geometry_only"
    assert summary["lifecycle"]["debug_overlay_enabled"] is False
    assert summary["lifecycle"]["occlusion_enabled"] is True
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
    assert imported.state.source_local_offset_x_m == 0.25
    assert imported.state.source_local_offset_y_m == 0.5
    assert imported.state.source_local_offset_z_m == 0.75
    assert imported.state.sample_rate_hz == 44100
    assert imported.state.array_prim_path == "/World/EditedArray"
    assert imported.state.source_prim_path == "/World/EditedSource"
    assert imported.state.object_prim_path == "/World/EditedObject"
    assert imported.state.debug_overlay_enabled is False
    assert imported.state.occlusion_enabled is True
    assert imported.state.trace_enabled is True
    assert imported.state.replicator_enabled is True
    imported_backend_widget, _ = imported_window._combo_fields["backend"]
    imported_layout_widget, _ = imported_window._combo_fields["layout_name"]
    assert imported_backend_widget.model.value == backend_choices.index("geometry_only")
    assert imported_layout_widget.model.value == layout_choices.index("mono")


def test_kit_invalid_numeric_input_is_readable(monkeypatch):
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


def test_extension_controller_writer_and_replicator_paths_use_output_root_env(
    monkeypatch,
    tmp_path,
):
    output_root = tmp_path / "ias_outputs"
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(output_root))
    _install_fake_replicator(monkeypatch)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = "manual/frames.jsonl"
    controller.state.replicator_output_dir = "manual/replicator"

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    status = controller.start_replicator()
    frame = controller.update_sensor()

    assert status is not None
    assert status["output_dir"] == str(output_root / "manual" / "replicator")
    assert frame is not None
    assert (output_root / "manual" / "frames.jsonl").exists()
    assert (
        output_root / "manual" / "replicator" / "audio_sensor_frames.jsonl"
    ).exists()


def test_extension_controller_replicator_missing_runtime_is_readable(tmp_path):
    controller = ExtensionController()
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    status = controller.start_replicator()

    assert status is None
    assert controller.state.error_message is not None
    assert "Replicator start failed" in controller.state.error_message
    assert "omni.replicator.core" in controller.state.error_message
