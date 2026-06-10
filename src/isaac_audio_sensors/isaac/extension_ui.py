"""Import-safe Omniverse extension controller and UI model."""

from __future__ import annotations

import importlib
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    KNOWN_BACKENDS,
    TDOA_AMBIGUITY_POLICIES,
)
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import write_frame_trace
from isaac_audio_sensors.core.math_utils import (
    euler_deg_from_quaternion,
    quaternion_from_euler_deg,
)
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.microphone_rig_profiles import (
    MicrophoneRigProfile,
    default_microphone_rig_profiles,
    microphone_rig_profile_from_mapping,
    validate_microphone_rig_profile_library,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    prim_path,
    quat_from_any,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.replicator import (
    DEFAULT_REPLICATOR_ANNOTATOR_NAME,
    DEFAULT_REPLICATOR_WRITER_NAME,
    AudioSensorReplicatorRecorder,
)
from isaac_audio_sensors.isaac.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
    match_sound_profile_id,
    normalize_object_label,
    sound_profile_from_mapping,
    validate_sound_profile_library,
)
from isaac_audio_sensors.isaac.stage_audio import (
    attach_array_object_binding_attrs,
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    attach_source_object_binding_attrs,
    clear_array_object_binding_attrs,
    clear_prim_attrs,
    clear_source_object_binding_attrs,
    create_sound_prim,
    get_or_define_prim,
    move_prim_to_path,
    remove_prim,
    set_prim_xform_pose,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
    debug_primitives_to_dicts,
)

BACKEND_CHOICES = tuple(
    backend
    for backend in ("geometry_only", "tdoa_synthetic", "room_acoustics")
    if backend in KNOWN_BACKENDS
)
AMBIGUITY_POLICY_CHOICES = tuple(sorted(TDOA_AMBIGUITY_POLICIES))
LAYOUT_CHOICES = ("quad_front", "quad_cross", "stereo_y", "two_mic_y", "mono")
SOURCE_POSITION_PRESETS: Mapping[str, tuple[float, float, float]] = {
    "front": (2.0, 0.0, 0.0),
    "right": (0.0, 2.0, 0.0),
    "left": (0.0, -2.0, 0.0),
    "behind": (-2.0, 0.0, 0.0),
}
OUTPUT_ROOT_ENV_VAR = "ISAAC_AUDIO_SENSORS_OUTPUT_ROOT"
PROJECT_NAME = "isaac-audio-sensors"
DEFAULT_OUTPUT_ROOT = Path("outputs/isaac_audio_sensors")
DEFAULT_TRACE_FILENAME = "extension_trace.frames.jsonl"
DEFAULT_LATEST_FRAME_FILENAME = "extension_latest_frame.json"
DEFAULT_CONFIG_FILENAME = "extension_binding.json"
DEFAULT_REPLICATOR_DIRNAME = "replicator"
OMNI_WINDOW_TITLE = "Isaac Audio Sensors"
OMNI_MENU_GROUP = "Window"
OMNI_ACTION_TOGGLE_WINDOW = "toggle_window"
OMNI_DEFAULT_HOTKEY = "CTRL + ALT + A"
OMNI_DEFAULT_HOTKEY_DISPLAY = "Ctrl+Alt+A"


def _gui_output_root() -> Path:
    """Return the absolute output root used by GUI file fields."""

    override = os.environ.get(OUTPUT_ROOT_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    repo_root = _find_project_root_from_module()
    if repo_root is not None:
        return (repo_root / DEFAULT_OUTPUT_ROOT).resolve()
    return (Path.cwd() / DEFAULT_OUTPUT_ROOT).resolve()


def _resolve_gui_output_path(path: str | Path) -> Path:
    """Resolve a GUI file field relative to the package output root."""

    raw = os.fspath(path).strip()
    if not raw:
        raise ExtensionActionError("Output path is empty.")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return _gui_output_root() / _strip_legacy_output_prefix(candidate)


def _find_project_root_from_module() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        with suppress(OSError, UnicodeDecodeError):
            text = pyproject.read_text(encoding="utf-8")
            if f'name = "{PROJECT_NAME}"' in text or f"name = '{PROJECT_NAME}'" in text:
                return parent
    return None


def _strip_legacy_output_prefix(path: Path) -> Path:
    parts = path.parts
    prefix = DEFAULT_OUTPUT_ROOT.parts
    if len(parts) >= len(prefix) and parts[: len(prefix)] == prefix:
        stripped = parts[len(prefix) :]
        return Path(*stripped) if stripped else Path(".")
    return path


class ExtensionActionError(RuntimeError):
    """User-facing extension action failure."""


@dataclass(frozen=True, slots=True)
class CurrentStageContext:
    """Current Omni stage and selected prim paths."""

    stage: Any | None
    selected_prim_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveredPrimSummary:
    """Compact discovered array/source record for UI and export."""

    id: str
    prim_path: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredMetadataSummary:
    """Record of metadata authored through the extension UI."""

    kind: str
    prim_path: str
    id: str
    attributes: Mapping[str, Any]


@dataclass(slots=True)
class ExtensionUiState:
    """Pure-Python state backing the reference extension UX."""

    selected_prim_paths: tuple[str, ...] = ()
    stage_status: str = "No stage checked."
    status_message: str = "Ready."
    error_message: str | None = None

    array_prim_path: str = "/World/Rig/AudioArray"
    array_id: str = "rig_front"
    layout_name: str = "quad_front"
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    author_child_microphones: bool = True
    array_position_x_m: float = 0.0
    array_position_y_m: float = 0.0
    array_position_z_m: float = 0.0
    array_yaw_deg: float = 0.0
    array_pitch_deg: float = 0.0
    array_roll_deg: float = 0.0
    array_attached_to_object: bool = False
    attached_array_object_prim_path: str = ""
    array_local_offset_x_m: float = 0.0
    array_local_offset_y_m: float = 0.0
    array_local_offset_z_m: float = 0.0
    array_local_yaw_deg: float = 0.0
    array_local_pitch_deg: float = 0.0
    array_local_roll_deg: float = 0.0

    rig_profile_library: tuple[MicrophoneRigProfile, ...] = field(
        default_factory=default_microphone_rig_profiles
    )
    selected_rig_profile_id: str = "alex_head_quad"
    applied_array_rig_profile: dict[str, Any] = field(default_factory=dict)

    source_prim_path: str = "/World/Sources/SpeakerA"
    source_id: str = "speaker_a"
    source_class_label: str = "Speech"
    audio_asset_path: str = "generated://impulse"
    source_position_x_m: float = 2.0
    source_position_y_m: float = 0.0
    source_position_z_m: float = 0.0
    source_start_time_s: float = 0.0
    source_duration_s: float = 1.0
    source_gain_db: float = 0.0
    source_directivity: str = "omni"

    profile_library: tuple[SoundProfile, ...] = field(
        default_factory=default_sound_profiles
    )
    selected_profile_id: str = "speech_generic"
    object_profile_mappings: dict[str, str] = field(
        default_factory=default_object_profile_mappings
    )
    applied_source_profile: dict[str, Any] = field(default_factory=dict)

    object_prim_path: str = ""
    object_label: str = "none"
    source_attached_to_object: bool = False
    attached_object_prim_path: str = ""
    source_local_offset_x_m: float = 0.0
    source_local_offset_y_m: float = 0.0
    source_local_offset_z_m: float = 0.0

    robot_base_prim_path: str = ""
    discovery_roots_text: str = "/World"
    backend: str = "tdoa_synthetic"
    ambiguity_policy: str = "none"
    update_period_s: float = 0.05
    max_events: int = 8
    debug_overlay_enabled: bool = True
    trace_enabled: bool = True
    jsonl_trace_path: str = DEFAULT_TRACE_FILENAME
    latest_frame_export_path: str = DEFAULT_LATEST_FRAME_FILENAME
    config_export_path: str = DEFAULT_CONFIG_FILENAME
    config_import_path: str = DEFAULT_CONFIG_FILENAME

    replicator_enabled: bool = False
    replicator_output_dir: str = DEFAULT_REPLICATOR_DIRNAME
    replicator_writer_name: str = DEFAULT_REPLICATOR_WRITER_NAME
    replicator_annotator_name: str = DEFAULT_REPLICATOR_ANNOTATOR_NAME
    replicator_recording: bool = False
    replicator_status_message: str = "Replicator idle."
    replicator_write_count: int = 0
    replicator_flush_count: int = 0
    replicator_latest_write_path: str | None = None
    replicator_latest_jsonl_path: str | None = None
    replicator_latest_error: str | None = None
    replicator_output_artifacts: tuple[str, ...] = ()

    discovered_arrays: tuple[DiscoveredPrimSummary, ...] = ()
    discovered_sources: tuple[DiscoveredPrimSummary, ...] = ()
    discovered_objects: tuple[DiscoveredPrimSummary, ...] = ()
    authored_metadata: tuple[AuthoredMetadataSummary, ...] = ()

    sensor_running: bool = False
    latest_frame_id: str | None = None
    latest_detection_count: int = 0
    latest_backend: str | None = None
    latest_source_prim_path: str | None = None
    latest_source_position_m: tuple[float, float, float] | None = None
    latest_bearing_deg: float | None = None
    latest_sector: str | None = None
    latest_array_prim_path: str | None = None
    latest_array_position_m: tuple[float, float, float] | None = None
    latest_array_orientation_xyzw: tuple[float, float, float, float] | None = None
    latest_mic_world_positions: dict[str, tuple[float, float, float]] = field(
        default_factory=dict
    )
    latest_aggregate_rms: dict[str, float] = field(default_factory=dict)
    latest_overlay_primitive_count: int = 0
    latest_overlay_labels: tuple[str, ...] = ()
    latest_overlay_status: str = "none"
    latest_overlay_error: str | None = None


class ExtensionController:
    """Stateful controller for the Isaac Audio Sensors reference extension."""

    def __init__(
        self,
        *,
        state: ExtensionUiState | None = None,
        stage_context_provider: Callable[[], CurrentStageContext] | None = None,
    ) -> None:
        self.state = state or ExtensionUiState()
        self.stage_context_provider = stage_context_provider
        self.sensor: IsaacAudioArraySensor | None = None
        self.replicator_recorder: AudioSensorReplicatorRecorder | None = None
        self.ext_id: str | None = None
        self.window: Any | None = None
        self.ui_available = False
        self._ui_window: OmniReferenceWindow | None = None
        self.action_status = "Kit action not registered."
        self.menu_status = "Kit menu not registered."
        self.hotkey_status = "Kit hotkey not registered."
        self._registered_action: Any | None = None
        self._registered_hotkey: Any | None = None
        self._registered_hotkey_key: str | None = None
        self._controller_update_subscription: Any | None = None
        self._menu_items: list[Any] = []

    def on_startup(self, ext_id: str) -> None:
        """Initialize the import-safe controller and lazily build Kit UI."""

        self.ext_id = ext_id
        self._set_status(f"Loaded {ext_id}.")
        self.build_ui_if_available()
        self.register_kit_integrations()

    def on_shutdown(self) -> None:
        """Stop live work and release UI/debug resources."""

        self.unregister_kit_integrations()
        self.stop_replicator()
        self.close_sensor()
        self._ui_window = None
        self.window = None
        self.ui_available = False
        self.ext_id = None
        self._set_status("Shutdown complete.")

    def build_ui_if_available(self) -> Any | None:
        """Build the Omniverse UI only when ``omni.ui`` imports."""

        if self.window is not None:
            self.ui_available = True
            return self.window
        try:
            ui = importlib.import_module("omni.ui")
        except ImportError:
            self.ui_available = False
            return None
        try:
            self._ui_window = OmniReferenceWindow(self, ui)
            self.window = self._ui_window.build()
            self.ui_available = True
            return self.window
        except Exception as exc:
            self.ui_available = False
            self._record_error("UI build failed", exc)
            return None

    def show_window(self) -> Any | None:
        """Show or rebuild the Kit window from menu/action/hotkey entrypoints."""

        window = self.build_ui_if_available()
        if window is None:
            self._set_status("Window unavailable: omni.ui could not be loaded.")
            return None
        if not _set_window_visible(window, True):
            self._set_status("Window shown; this Kit build did not expose visibility.")
            return window
        _focus_window(window)
        self._refresh_menu()
        self._set_status("Window shown.")
        return window

    def hide_window(self) -> None:
        """Hide the Kit window without destroying controller state."""

        if self.window is None:
            return
        _set_window_visible(self.window, False)
        self._refresh_menu()
        self._set_status("Window hidden.")

    def toggle_window(self) -> Any | None:
        """Toggle the Kit window, rebuilding it if the user closed it with X."""

        if self.is_window_visible():
            self.hide_window()
            return self.window
        return self.show_window()

    def is_window_visible(self) -> bool:
        """Return whether the Kit window is currently visible."""

        return _window_visible(self.window)

    def register_kit_integrations(self) -> None:
        """Register action, menu, and optional hotkey integrations when Kit exists."""

        self._register_action()
        self._register_menu()
        self._register_hotkey()

    def unregister_kit_integrations(self) -> None:
        """Best-effort cleanup of Kit action/menu/hotkey registrations."""

        self._unregister_hotkey()
        self._unregister_menu()
        self._unregister_action()

    def _register_action(self) -> None:
        if not self.ext_id:
            self.action_status = "Kit action unavailable: extension id is unset."
            return
        try:
            actions_core = importlib.import_module("omni.kit.actions.core")
        except ImportError as exc:
            self.action_status = (
                f"Kit action unavailable: omni.kit.actions.core ({exc})."
            )
            return
        get_registry = getattr(actions_core, "get_action_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "register_action"):
            self.action_status = "Kit action unavailable: action registry missing."
            return

        if hasattr(registry, "deregister_action"):
            with suppress(Exception):
                registry.deregister_action(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
        try:
            self._registered_action = registry.register_action(
                self.ext_id,
                OMNI_ACTION_TOGGLE_WINDOW,
                self.toggle_window,
                display_name="Toggle Isaac Audio Sensors Window",
                description="Show or hide the Isaac Audio Sensors Kit window.",
                tag="Isaac Audio Sensors",
            )
        except Exception as exc:
            self.action_status = f"Kit action registration failed: {exc}"
            return
        self.action_status = (
            f"Kit action registered: {self.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}."
        )

    def _unregister_action(self) -> None:
        if not self.ext_id:
            return
        try:
            actions_core = importlib.import_module("omni.kit.actions.core")
        except ImportError:
            self._registered_action = None
            return
        get_registry = getattr(actions_core, "get_action_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "deregister_action"):
            self._registered_action = None
            return
        try:
            if self._registered_action is not None:
                registry.deregister_action(self._registered_action)
            else:
                registry.deregister_action(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW)
            self.action_status = "Kit action deregistered."
        except Exception as exc:
            self.action_status = f"Kit action cleanup failed: {exc}"
        self._registered_action = None

    def _register_menu(self) -> None:
        if not self.ext_id:
            self.menu_status = "Kit menu unavailable: extension id is unset."
            return
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError as exc:
            self.menu_status = f"Kit menu unavailable: omni.kit.menu.utils ({exc})."
            return
        menu_item_type = getattr(menu_utils, "MenuItemDescription", None)
        add_menu_items = getattr(menu_utils, "add_menu_items", None)
        if menu_item_type is None or not callable(add_menu_items):
            self.menu_status = "Kit menu unavailable: menu utils API missing."
            return
        try:
            self._menu_items = [
                menu_item_type(
                    name=OMNI_WINDOW_TITLE,
                    ticked=True,
                    ticked_fn=lambda _value=False: self.is_window_visible(),
                    onclick_action=(self.ext_id, OMNI_ACTION_TOGGLE_WINDOW),
                )
            ]
            add_menu_items(self._menu_items, name=OMNI_MENU_GROUP)
        except Exception as exc:
            self.menu_status = f"Kit menu registration failed: {exc}"
            self._menu_items = []
            return
        self.menu_status = (
            f"Kit menu registered: {OMNI_MENU_GROUP} -> {OMNI_WINDOW_TITLE}."
        )

    def _unregister_menu(self) -> None:
        if not self._menu_items:
            return
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError:
            self._menu_items = []
            return
        remove_menu_items = getattr(menu_utils, "remove_menu_items", None)
        if callable(remove_menu_items):
            try:
                remove_menu_items(self._menu_items, name=OMNI_MENU_GROUP)
                self.menu_status = "Kit menu deregistered."
            except Exception as exc:
                self.menu_status = f"Kit menu cleanup failed: {exc}"
        self._menu_items = []

    def _register_hotkey(self) -> None:
        if not self.ext_id:
            self.hotkey_status = "Kit hotkey unavailable: extension id is unset."
            return
        hotkey = self._configured_hotkey()
        if not hotkey:
            self.hotkey_status = "Kit hotkey disabled by configuration."
            return
        try:
            hotkeys_core = importlib.import_module("omni.kit.hotkeys.core")
        except ImportError as exc:
            self.hotkey_status = (
                "Kit hotkey unavailable: omni.kit.hotkeys.core "
                f"({exc}); menu/action remain registered."
            )
            return
        get_registry = getattr(hotkeys_core, "get_hotkey_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None or not hasattr(registry, "register_hotkey"):
            self.hotkey_status = (
                "Kit hotkey unavailable: hotkey registry missing; "
                "menu/action remain registered."
            )
            return
        if hasattr(registry, "deregister_hotkeys"):
            with suppress(Exception):
                registry.deregister_hotkeys(self.ext_id, hotkey)
        try:
            self._registered_hotkey = registry.register_hotkey(
                self.ext_id,
                hotkey,
                self.ext_id,
                OMNI_ACTION_TOGGLE_WINDOW,
                filter=None,
            )
        except Exception as exc:
            self.hotkey_status = (
                f"Kit hotkey registration failed for {hotkey}: {exc}; "
                "menu/action remain registered."
            )
            return
        if self._registered_hotkey is None:
            last_error = getattr(registry, "last_error", "unknown error")
            self.hotkey_status = (
                f"Kit hotkey unavailable for {hotkey}: {last_error}; "
                "menu/action remain registered."
            )
            return
        self._registered_hotkey_key = hotkey
        self.hotkey_status = (
            f"Kit hotkey registered: {OMNI_DEFAULT_HOTKEY_DISPLAY} "
            f"({hotkey}) -> {self.ext_id}::{OMNI_ACTION_TOGGLE_WINDOW}."
        )

    def _unregister_hotkey(self) -> None:
        if not self.ext_id or self._registered_hotkey_key is None:
            self._registered_hotkey = None
            return
        try:
            hotkeys_core = importlib.import_module("omni.kit.hotkeys.core")
        except ImportError:
            self._registered_hotkey = None
            self._registered_hotkey_key = None
            return
        get_registry = getattr(hotkeys_core, "get_hotkey_registry", None)
        registry = get_registry() if callable(get_registry) else None
        if registry is None:
            self._registered_hotkey = None
            self._registered_hotkey_key = None
            return
        try:
            if self._registered_hotkey is not None and hasattr(
                registry, "deregister_hotkey"
            ):
                registry.deregister_hotkey(self._registered_hotkey)
            elif hasattr(registry, "deregister_hotkeys"):
                registry.deregister_hotkeys(self.ext_id, self._registered_hotkey_key)
            self.hotkey_status = "Kit hotkey deregistered."
        except Exception as exc:
            self.hotkey_status = f"Kit hotkey cleanup failed: {exc}"
        self._registered_hotkey = None
        self._registered_hotkey_key = None

    def _configured_hotkey(self) -> str:
        try:
            carb_settings = importlib.import_module("carb.settings")
        except ImportError:
            return OMNI_DEFAULT_HOTKEY
        get_settings = getattr(carb_settings, "get_settings", None)
        settings = get_settings() if callable(get_settings) else None
        if settings is None or not hasattr(settings, "get"):
            return OMNI_DEFAULT_HOTKEY
        ext_ids = tuple(
            dict.fromkeys(
                (
                    self.ext_id or "isaac_audio_sensors.omni",
                    "isaac_audio_sensors.omni",
                )
            )
        )
        for ext_id in ext_ids:
            for path in (
                f"/persistent/exts/{ext_id}/shortcut",
                f"/exts/{ext_id}/shortcut",
            ):
                value = settings.get(path)
                if value is not None:
                    return _normalize_hotkey_setting(str(value))
        return OMNI_DEFAULT_HOTKEY

    def _on_window_visibility_changed(self, _visible: bool) -> None:
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        try:
            menu_utils = importlib.import_module("omni.kit.menu.utils")
        except ImportError:
            return
        refresh_menu_items = getattr(menu_utils, "refresh_menu_items", None)
        if callable(refresh_menu_items):
            with suppress(Exception):
                refresh_menu_items(OMNI_MENU_GROUP)

    def refresh_stage_selection(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        """Refresh current selected prim paths from explicit args or Omni."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            if context.stage is None:
                raise ExtensionActionError("No USD stage is open.")
            self.state.selected_prim_paths = context.selected_prim_paths
            selected = ", ".join(context.selected_prim_paths) or "none"
            self.state.stage_status = f"Stage ready. Selected: {selected}"
            self._set_status("Stage selection refreshed.")
            return context.selected_prim_paths
        except Exception as exc:
            self._record_error("Stage selection failed", exc)
            return ()

    def use_selected_as_array(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the array target."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.array_prim_path = path
        self._set_status(f"Array target set to {path}.")
        return path

    def use_selected_as_source(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the source target."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.source_prim_path = path
        self._set_status(f"Source target set to {path}.")
        return path

    def use_selected_as_object(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the scene object target."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            if context.stage is None:
                raise ExtensionActionError("No USD stage is open.")
            self.state.selected_prim_paths = context.selected_prim_paths
            if not context.selected_prim_paths:
                raise ExtensionActionError("No prim is selected.")
            path = context.selected_prim_paths[0]
            _validate_abs_path(path, "object_prim_path")
            if not _stage_has_prim(context.stage, path):
                raise ExtensionActionError(f"Selected object does not exist: {path}.")
            if path == self.state.source_prim_path:
                raise ExtensionActionError("Cannot attach a source to itself.")
            self.state.object_prim_path = path
            self.state.object_label = _path_name(path)
            self._set_status(f"Object target set to {_path_name(path)} at {path}.")
            return path
        except Exception as exc:
            self._record_error("Object selection failed", exc)
            return None

    def create_demo_object(
        self,
        *,
        stage: Any | None = None,
        prim_path: str = "/World/Oven",
        position_world: tuple[float, float, float] = (2.0, 0.0, 0.0),
    ) -> str | None:
        """Create a minimal procedural object prim for attach workflow demos."""

        try:
            stage_obj = self._stage_or_error(stage)
            _validate_abs_path(prim_path, "object_prim_path")
            parent = prim_path.rstrip("/").rsplit("/", 1)[0]
            if parent and parent != prim_path:
                get_or_define_prim(stage_obj, prim_path=parent, prim_type="Xform")
            prim = _get_or_define_demo_object_prim(stage_obj, prim_path)
            if not _prim_has_xform_pose(prim):
                set_prim_xform_pose(prim, position=position_world)
            _style_demo_object_prim(stage_obj, prim=prim, position_world=position_world)
            self.state.object_prim_path = prim_path
            self.state.object_label = _path_name(prim_path)
            self._set_status(
                f"Created demo object {_path_name(prim_path)} at {prim_path}."
            )
            return prim_path
        except Exception as exc:
            self._record_error("Demo object creation failed", exc)
            return None

    def read_selected_source_transform(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[float, float, float] | None:
        """Read the selected source prim's current world position into UI state."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            if context.stage is None:
                raise ExtensionActionError("No USD stage is open.")
            self.state.selected_prim_paths = context.selected_prim_paths
            selected_path = (
                context.selected_prim_paths[0]
                if context.selected_prim_paths
                else self.state.source_prim_path
            )
            _validate_abs_path(selected_path, "source_prim_path")
            pose = IsaacStagePoseResolver(context.stage).resolve_world_pose(
                selected_path,
                field_name="selected source",
            )
            self.state.source_prim_path = selected_path
            self._set_source_position_state(pose.position_world)
            self._set_status(
                "Read source transform "
                f"{_format_vec3(pose.position_world)} from {selected_path}."
            )
            return pose.position_world
        except Exception as exc:
            self._record_error("Source transform read failed", exc)
            return None

    def read_selected_array_transform(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> tuple[float, float, float] | None:
        """Read the selected array prim's current world pose into UI state."""

        try:
            context = self._context(stage=stage, selected_paths=selected_paths)
            if context.stage is None:
                raise ExtensionActionError("No USD stage is open.")
            self.state.selected_prim_paths = context.selected_prim_paths
            selected_path = (
                context.selected_prim_paths[0]
                if context.selected_prim_paths
                else self.state.array_prim_path
            )
            _validate_abs_path(selected_path, "array_prim_path")
            pose = IsaacStagePoseResolver(context.stage).resolve_world_pose(
                selected_path,
                field_name="selected array",
            )
            self.state.array_prim_path = selected_path
            self._set_array_pose_state(
                pose.position_world,
                pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0),
            )
            self._set_status(
                "Read array transform "
                f"{_format_vec3(pose.position_world)} / "
                f"yaw={self.state.array_yaw_deg:.1f} deg from {selected_path}."
            )
            return pose.position_world
        except Exception as exc:
            self._record_error("Array transform read failed", exc)
            return None

    def use_selected_as_robot_base(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> str | None:
        """Bind the first selected prim path as the robot/base frame."""

        path = self._first_selected_path(stage=stage, selected_paths=selected_paths)
        if path is None:
            return None
        self.state.robot_base_prim_path = path
        self._set_status(f"Robot/base target set to {path}.")
        return path

    def author_array(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Create or configure array metadata on the current target prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            _validate_abs_path(state.array_prim_path, "array_prim_path")
            prim = get_or_define_prim(
                stage_obj,
                prim_path=state.array_prim_path,
                prim_type="Xform",
            )
            record = self._author_array_on_stage(
                stage_obj,
                position_world=_author_position_arg(
                    prim,
                    default=(0.0, 0.0, 0.0),
                ),
                orientation_world_quat=_author_orientation_arg(
                    prim,
                    default=(0.0, 0.0, 0.0, 1.0),
                ),
            )
            self._append_authored_record(record)
            self._set_status(f"Authored array {record.id} at {state.array_prim_path}.")
            return record
        except Exception as exc:
            self._record_error("Array authoring failed", exc)
            return None

    def apply_array_pose(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the current array pose fields to the target prim and metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            if self.state.array_attached_to_object:
                raise ExtensionActionError(
                    "Array is attached to an object; edit the local offset "
                    "or detach the array first."
                )
            position = self._array_position_from_state()
            orientation = self._array_orientation_from_state()
            record = self._author_array_on_stage(
                stage_obj,
                position_world=position,
                orientation_world_quat=orientation,
                kind="array_pose",
            )
            self._append_authored_record(record)
            self._set_status(
                "Applied array pose "
                f"{_format_vec3(position)} / yaw={self.state.array_yaw_deg:g} deg "
                f"to {self.state.array_prim_path}."
            )
            return record
        except Exception as exc:
            self._record_error("Array pose apply failed", exc)
            return None

    def _author_array_on_stage(
        self,
        stage_obj: Any,
        *,
        position_world: tuple[float, float, float] | None,
        orientation_world_quat: tuple[float, float, float, float] | None,
        microphones: tuple[Any, ...] | None = None,
        kind: str = "array",
        extra_attrs: Mapping[str, Any] | None = None,
    ) -> AuthoredMetadataSummary:
        """Create/update the array prim with metadata and an explicit pose."""

        state = self.state
        _validate_abs_path(state.array_prim_path, "array_prim_path")
        if state.layout_name not in LAYOUT_CHOICES:
            raise ExtensionActionError(f"Unknown array layout {state.layout_name!r}.")
        if int(state.sample_rate_hz) <= 0:
            raise ExtensionActionError("sample_rate_hz must be positive.")

        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.array_prim_path,
            prim_type="Xform",
        )
        mics = (
            tuple(microphones)
            if microphones is not None
            else microphone_layout(state.layout_name)
        )
        attrs: dict[str, Any] = dict(
            attach_microphone_array_attrs(
                prim,
                array_id=state.array_id.strip() or _path_name(state.array_prim_path),
                sample_rate_hz=int(state.sample_rate_hz),
                coordinate_convention=state.coordinate_convention,
                layout_name=state.layout_name,
                position_world=position_world,
                orientation_world_quat=orientation_world_quat,
                microphone_relative_offsets_m=tuple(
                    microphone.relative_position_m for microphone in mics
                ),
                microphone_ids=tuple(microphone.mic_id for microphone in mics),
            )
        )
        for name, value in dict(extra_attrs or {}).items():
            _set_prim_attr(prim, name, value)
            attrs[name] = value
        if state.author_child_microphones:
            self._remove_stale_child_microphones(
                stage_obj,
                array_path=state.array_prim_path,
                keep_mic_ids=tuple(microphone.mic_id for microphone in mics),
            )
            self._author_child_microphones(
                stage_obj,
                array_path=state.array_prim_path,
                microphones=mics,
            )
        return AuthoredMetadataSummary(
            kind=kind,
            prim_path=state.array_prim_path,
            id=str(attrs["ias:array_id"]),
            attributes=_jsonable_mapping(attrs),
        )

    def apply_source_position(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the current source XYZ fields to the target prim and metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            authored = self._author_source_on_stage(
                stage_obj,
                position_world=self._source_position_from_state(),
            )
            self._set_status(
                "Applied source position "
                f"{_format_vec3(self._source_position_from_state())} "
                f"to {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source position apply failed", exc)
            return None

    def apply_source_position_preset(
        self,
        preset: str,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply a deterministic source placement preset."""

        try:
            key = preset.strip().lower()
            if key not in SOURCE_POSITION_PRESETS:
                raise ExtensionActionError(
                    f"Unknown source position preset {preset!r}."
                )
            self._set_source_position_state(SOURCE_POSITION_PRESETS[key])
            authored = self.apply_source_position(stage=stage)
            if authored is not None:
                self._set_status(
                    f"Applied {key} source preset "
                    f"{_format_vec3(SOURCE_POSITION_PRESETS[key])} "
                    f"to {self.state.source_prim_path}."
                )
            return authored
        except Exception as exc:
            self._record_error("Source preset failed", exc)
            return None

    def select_sound_profile(
        self, profile_id: str | None = None
    ) -> SoundProfile | None:
        """Select a profile manually by id without authoring source metadata."""

        try:
            profile = self._sound_profile_by_id(
                profile_id or self.state.selected_profile_id
            )
            self.state.selected_profile_id = profile.profile_id
            self._set_status(
                f"Selected sound profile {profile.display_label} "
                f"({profile.profile_id})."
            )
            return profile
        except Exception as exc:
            self._record_error("Sound profile selection failed", exc)
            return None

    def auto_select_profile_from_object(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> SoundProfile | None:
        """Select the best profile from selected or attached object labels."""

        try:
            labels = self._object_label_candidates(
                stage=stage,
                selected_paths=selected_paths,
            )
            if not labels:
                raise ExtensionActionError(
                    "No selected or attached object label is available."
                )
            selected_object_path = self._selected_object_candidate_path(
                stage=stage,
                selected_paths=selected_paths,
            )
            if selected_object_path is not None:
                self.state.object_prim_path = selected_object_path
                self.state.object_label = labels[0]
            library = self._validated_sound_profiles()
            profile_id = match_sound_profile_id(
                labels=labels,
                profiles=library,
                object_profile_mappings=self.state.object_profile_mappings,
            )
            if profile_id is None:
                raise ExtensionActionError(
                    "No sound profile matches object labels: " + ", ".join(labels) + "."
                )
            profile = self._sound_profile_by_id(profile_id)
            self.state.selected_profile_id = profile.profile_id
            self._set_status(
                f"Auto-selected {profile.display_label} from object labels: "
                f"{', '.join(labels)}."
            )
            return profile
        except Exception as exc:
            self._record_error("Sound profile auto-match failed", exc)
            return None

    def apply_selected_profile(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the selected profile to the current source prim metadata."""

        try:
            stage_obj = self._stage_or_error(stage)
            profile = self._sound_profile_by_id(self.state.selected_profile_id)
            authored = self._author_profile_on_current_source(stage_obj, profile)
            self._set_status(
                f"Applied sound profile {profile.display_label} "
                f"to {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Sound profile apply failed", exc)
            return None

    def select_rig_profile(
        self, profile_id: str | None = None
    ) -> MicrophoneRigProfile | None:
        """Select a microphone rig profile by id without authoring metadata."""

        try:
            profile = self._rig_profile_by_id(
                profile_id or self.state.selected_rig_profile_id
            )
            self.state.selected_rig_profile_id = profile.profile_id
            self._set_status(
                f"Selected rig profile {profile.display_label} "
                f"({profile.profile_id})."
            )
            return profile
        except Exception as exc:
            self._record_error("Rig profile selection failed", exc)
            return None

    def apply_selected_rig_profile(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Apply the selected rig profile to the current array prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            profile = self._rig_profile_by_id(self.state.selected_rig_profile_id)
            authored = self._author_rig_on_current_array(stage_obj, profile)
            hint = ""
            mount_path = profile.recommended_mount_prim_path
            if (
                mount_path
                and not self.state.array_attached_to_object
                and _stage_has_prim(stage_obj, mount_path)
            ):
                hint = f" Recommended mount available: {mount_path}."
            self._set_status(
                f"Applied rig profile {profile.display_label} "
                f"to {self.state.array_prim_path}.{hint}"
            )
            return authored
        except Exception as exc:
            self._record_error("Rig profile apply failed", exc)
            return None

    def author_source(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Create or configure source metadata on the current target prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            authored = self._author_source_on_stage(
                stage_obj,
                position_world=self._source_position_from_state(),
            )
            self._set_status(
                f"Authored source {authored.id} at {self.state.source_prim_path}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source authoring failed", exc)
            return None

    def attach_source_to_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Attach the current source under the selected object with local offset."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            object_path = state.object_prim_path or state.attached_object_prim_path
            _validate_abs_path(object_path, "object_prim_path")
            _validate_abs_path(state.source_prim_path, "source_prim_path")
            self._validate_source_metadata_state()
            if not _stage_has_prim(stage_obj, object_path):
                raise ExtensionActionError(
                    f"Selected object no longer exists: {object_path}."
                )
            source_name = _path_name(state.source_prim_path)
            attached_path = f"{object_path.rstrip('/')}/{source_name}"
            offset = self._source_local_offset_from_state()
            move_prim_to_path(
                stage_obj,
                source_path=state.source_prim_path,
                dest_path=attached_path,
                prim_type="Sound",
            )
            state.source_prim_path = attached_path
            record = create_sound_prim(
                stage_obj,
                prim_path=attached_path,
                audio_asset_path=state.audio_asset_path,
                spatial=True,
                loop=False,
                start_time_s=state.source_start_time_s,
                gain_db=state.source_gain_db,
            )
            prim = get_or_define_prim(
                stage_obj,
                prim_path=attached_path,
                prim_type=record.prim_type,
            )
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id.strip() or _path_name(attached_path),
                class_label=state.source_class_label.strip() or "Sound",
                position_world=None,
                orientation_world_quat=None,
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            binding_attrs = attach_source_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=offset,
            )
            profile_attrs = _refresh_applied_profile_binding_snapshot(
                prim,
                state,
                object_path=object_path,
                local_offset_m=offset,
            )
            state.source_attached_to_object = True
            state.attached_object_prim_path = object_path
            state.object_prim_path = object_path
            state.object_label = _path_name(object_path)
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    attached_path,
                    field_name="attached source",
                )
                self._set_source_position_state(pose.position_world)
            authored = AuthoredMetadataSummary(
                kind="source_object_attachment",
                prim_path=attached_path,
                id=str(attrs["ias:source_id"]),
                attributes=_jsonable_mapping(
                    {**record.attributes, **attrs, **binding_attrs, **profile_attrs}
                ),
            )
            self._append_authored_record(authored)
            self._set_status(
                "Attached source "
                f"{authored.id} to {_path_name(object_path)} at {object_path} "
                f"with local offset {_format_vec3(offset)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source attach failed", exc)
            return None

    def detach_source_from_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Detach the current source to a standalone source path."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            _validate_abs_path(state.source_prim_path, "source_prim_path")
            self._validate_source_metadata_state()
            source_path = state.source_prim_path
            pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                source_path,
                field_name="attached source",
            )
            standalone_path = f"/World/Sources/{_path_name(source_path)}"
            get_or_define_prim(stage_obj, prim_path="/World/Sources", prim_type="Xform")
            prim = move_prim_to_path(
                stage_obj,
                source_path=source_path,
                dest_path=standalone_path,
                prim_type="Sound",
            )
            state.source_prim_path = standalone_path
            record = create_sound_prim(
                stage_obj,
                prim_path=standalone_path,
                audio_asset_path=state.audio_asset_path,
                spatial=True,
                loop=False,
                start_time_s=state.source_start_time_s,
                gain_db=state.source_gain_db,
            )
            prim = get_or_define_prim(
                stage_obj,
                prim_path=standalone_path,
                prim_type=record.prim_type,
            )
            clear_source_object_binding_attrs(prim)
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id.strip() or _path_name(standalone_path),
                class_label=state.source_class_label.strip() or "Sound",
                position_world=pose.position_world,
                orientation_world_quat=pose.orientation_world_quat
                or (0.0, 0.0, 0.0, 1.0),
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            state.source_attached_to_object = False
            state.attached_object_prim_path = ""
            self._set_source_position_state(pose.position_world)
            authored = AuthoredMetadataSummary(
                kind="source_object_detach",
                prim_path=standalone_path,
                id=str(attrs["ias:source_id"]),
                attributes=_jsonable_mapping({**record.attributes, **attrs}),
            )
            self._append_authored_record(authored)
            self._set_status(
                "Detached source "
                f"{authored.id} to {standalone_path} at "
                f"{_format_vec3(pose.position_world)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Source detach failed", exc)
            return None

    def attach_array_to_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Mount the current array under the selected object/robot prim."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            object_path = (
                state.object_prim_path
                or state.attached_array_object_prim_path
                or state.robot_base_prim_path
            )
            _validate_abs_path(object_path, "object_prim_path")
            _validate_abs_path(state.array_prim_path, "array_prim_path")
            if object_path == state.array_prim_path:
                raise ExtensionActionError("Cannot attach an array to itself.")
            if not _stage_has_prim(stage_obj, object_path):
                raise ExtensionActionError(
                    f"Selected mount prim no longer exists: {object_path}."
                )
            array_name = _path_name(state.array_prim_path)
            attached_path = f"{object_path.rstrip('/')}/{array_name}"
            offset = self._array_local_offset_from_state()
            local_orientation = self._array_local_orientation_from_state()
            move_prim_to_path(
                stage_obj,
                source_path=state.array_prim_path,
                dest_path=attached_path,
                prim_type="Xform",
                include_children=True,
            )
            state.array_prim_path = attached_path
            prim = get_or_define_prim(
                stage_obj,
                prim_path=attached_path,
                prim_type="Xform",
            )
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            binding_attrs = attach_array_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=offset,
                local_orientation_quat=local_orientation,
            )
            state.array_attached_to_object = True
            state.attached_array_object_prim_path = object_path
            state.object_prim_path = object_path
            state.object_label = _path_name(object_path)
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    attached_path,
                    field_name="attached array",
                )
                self._set_array_pose_state(
                    pose.position_world,
                    pose.orientation_world_quat,
                )
            authored = AuthoredMetadataSummary(
                kind="array_object_attachment",
                prim_path=attached_path,
                id=state.array_id.strip() or array_name,
                attributes=_jsonable_mapping(binding_attrs),
            )
            self._append_authored_record(authored)
            self._set_status(
                "Attached array "
                f"{authored.id} to {_path_name(object_path)} at {object_path} "
                f"with local offset {_format_vec3(offset)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Array attach failed", exc)
            return None

    def detach_array_from_object(
        self,
        *,
        stage: Any | None = None,
    ) -> AuthoredMetadataSummary | None:
        """Detach the current array to a standalone path, keeping its world pose."""

        try:
            stage_obj = self._stage_or_error(stage)
            state = self.state
            _validate_abs_path(state.array_prim_path, "array_prim_path")
            array_path = state.array_prim_path
            pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                array_path,
                field_name="attached array",
            )
            standalone_path = f"/World/AudioArrays/{_path_name(array_path)}"
            get_or_define_prim(
                stage_obj,
                prim_path="/World/AudioArrays",
                prim_type="Xform",
            )
            prim = move_prim_to_path(
                stage_obj,
                source_path=array_path,
                dest_path=standalone_path,
                prim_type="Xform",
                include_children=True,
            )
            state.array_prim_path = standalone_path
            clear_array_object_binding_attrs(prim)
            orientation = pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
            attrs = attach_microphone_array_attrs(
                prim,
                array_id=state.array_id.strip() or _path_name(standalone_path),
                sample_rate_hz=int(state.sample_rate_hz),
                coordinate_convention=state.coordinate_convention,
                layout_name=state.layout_name,
                position_world=pose.position_world,
                orientation_world_quat=orientation,
            )
            state.array_attached_to_object = False
            state.attached_array_object_prim_path = ""
            self._set_array_pose_state(pose.position_world, orientation)
            authored = AuthoredMetadataSummary(
                kind="array_object_detach",
                prim_path=standalone_path,
                id=str(attrs["ias:array_id"]),
                attributes=_jsonable_mapping(attrs),
            )
            self._append_authored_record(authored)
            self._set_status(
                "Detached array "
                f"{authored.id} to {standalone_path} at "
                f"{_format_vec3(pose.position_world)}."
            )
            return authored
        except Exception as exc:
            self._record_error("Array detach failed", exc)
            return None

    def _author_source_on_stage(
        self,
        stage_obj: Any,
        *,
        position_world: tuple[float, float, float],
    ) -> AuthoredMetadataSummary:
        """Create/update the source prim with metadata and explicit position."""

        state = self.state
        _validate_abs_path(state.source_prim_path, "source_prim_path")
        self._validate_source_metadata_state()

        record = create_sound_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            audio_asset_path=state.audio_asset_path,
            spatial=True,
            loop=False,
            start_time_s=state.source_start_time_s,
            gain_db=state.source_gain_db,
        )
        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            prim_type=record.prim_type,
        )
        attrs = attach_sound_source_attrs(
            prim,
            source_id=state.source_id.strip() or _path_name(state.source_prim_path),
            class_label=state.source_class_label.strip() or "Sound",
            position_world=position_world,
            orientation_world_quat=_author_orientation_arg(
                prim,
                default=(0.0, 0.0, 0.0, 1.0),
            ),
            audio_asset_path=state.audio_asset_path,
            start_time_s=state.source_start_time_s,
            duration_s=state.source_duration_s,
            gain_db=state.source_gain_db,
            directivity=state.source_directivity,
        )
        authored = AuthoredMetadataSummary(
            kind="source",
            prim_path=state.source_prim_path,
            id=str(attrs["ias:source_id"]),
            attributes=_jsonable_mapping({**record.attributes, **attrs}),
        )
        self._append_authored_record(authored)
        return authored

    def _author_profile_on_current_source(
        self,
        stage_obj: Any,
        profile: SoundProfile,
    ) -> AuthoredMetadataSummary:
        state = self.state
        _validate_abs_path(state.source_prim_path, "source_prim_path")
        attached = state.source_attached_to_object
        object_path = state.attached_object_prim_path or state.object_prim_path
        object_label = self._profile_object_label(stage_obj)
        if attached:
            _validate_abs_path(object_path, "object_prim_path")
            self._validate_attached_object_available(stage_obj)
            position_world = None
        else:
            position_world = self._current_source_world_position(stage_obj)
            self._set_source_position_state(position_world)

        state.source_id = profile.source_id_for(
            object_label=object_label,
            current_source_id=state.source_id.strip()
            or _path_name(state.source_prim_path),
            source_prim_path=state.source_prim_path,
        )
        state.source_class_label = profile.class_label
        state.audio_asset_path = profile.audio_asset_path
        state.source_start_time_s = float(profile.start_time_s)
        state.source_duration_s = float(profile.duration_s)
        state.source_gain_db = float(profile.gain_db)
        state.source_directivity = profile.directivity
        self._validate_source_metadata_state()

        record = create_sound_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            audio_asset_path=state.audio_asset_path,
            spatial=True,
            loop=False,
            start_time_s=state.source_start_time_s,
            gain_db=state.source_gain_db,
        )
        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.source_prim_path,
            prim_type=record.prim_type,
        )
        _set_prim_attr(prim, "ias:sound_profile_id", profile.profile_id)
        _set_prim_attr(prim, "ias:sound_profile_label", profile.display_label)

        binding_attrs: Mapping[str, object] = {}
        if attached:
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id,
                class_label=state.source_class_label,
                position_world=None,
                orientation_world_quat=None,
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )
            binding_attrs = attach_source_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=self._source_local_offset_from_state(),
            )
        else:
            attrs = attach_sound_source_attrs(
                prim,
                source_id=state.source_id,
                class_label=state.source_class_label,
                position_world=position_world,
                orientation_world_quat=_author_orientation_arg(
                    prim,
                    default=(0.0, 0.0, 0.0, 1.0),
                ),
                audio_asset_path=state.audio_asset_path,
                start_time_s=state.source_start_time_s,
                duration_s=state.source_duration_s,
                gain_db=state.source_gain_db,
                directivity=state.source_directivity,
            )

        snapshot = self._applied_profile_snapshot(
            profile,
            source_position_world=position_world,
        )
        state.applied_source_profile = snapshot
        authored = AuthoredMetadataSummary(
            kind="source_profile",
            prim_path=state.source_prim_path,
            id=state.source_id,
            attributes=_jsonable_mapping(
                {
                    **record.attributes,
                    **attrs,
                    **binding_attrs,
                    "ias:sound_profile_id": profile.profile_id,
                    "ias:sound_profile_label": profile.display_label,
                    "applied_source_profile": snapshot,
                }
            ),
        )
        self._append_authored_record(authored)
        return authored

    def _current_source_world_position(
        self,
        stage_obj: Any,
    ) -> tuple[float, float, float]:
        if self.state.source_prim_path.strip() and _stage_has_prim(
            stage_obj,
            self.state.source_prim_path,
        ):
            with suppress(Exception):
                pose = IsaacStagePoseResolver(stage_obj).resolve_world_pose(
                    self.state.source_prim_path,
                    field_name="source",
                )
                return pose.position_world
        return self._source_position_from_state()

    def _applied_profile_snapshot(
        self,
        profile: SoundProfile,
        *,
        source_position_world: tuple[float, float, float] | None,
    ) -> dict[str, Any]:
        state = self.state
        return _json_ready(
            {
                "profile_id": profile.profile_id,
                "display_label": profile.display_label,
                "source_prim_path": state.source_prim_path,
                "source_id": state.source_id,
                "class_label": state.source_class_label,
                "audio_asset_path": state.audio_asset_path,
                "start_time_s": state.source_start_time_s,
                "duration_s": state.source_duration_s,
                "gain_db": state.source_gain_db,
                "directivity": state.source_directivity,
                "source_attached_to_object": state.source_attached_to_object,
                "object_prim_path": state.object_prim_path or None,
                "object_label": state.object_label,
                "attached_object_prim_path": state.attached_object_prim_path or None,
                "source_local_offset_m": self._source_local_offset_from_state(),
                "source_position_world": source_position_world,
            }
        )

    def _author_rig_on_current_array(
        self,
        stage_obj: Any,
        profile: MicrophoneRigProfile,
    ) -> AuthoredMetadataSummary:
        state = self.state
        _validate_abs_path(state.array_prim_path, "array_prim_path")
        attached = state.array_attached_to_object
        object_path = state.attached_array_object_prim_path or state.object_prim_path
        if attached:
            _validate_abs_path(object_path, "object_prim_path")
            self._validate_attached_array_available(stage_obj)

        state.layout_name = profile.layout_name
        state.sample_rate_hz = int(profile.sample_rate_hz)
        (
            state.array_local_offset_x_m,
            state.array_local_offset_y_m,
            state.array_local_offset_z_m,
        ) = profile.mount_local_offset_m
        (
            state.array_local_roll_deg,
            state.array_local_pitch_deg,
            state.array_local_yaw_deg,
        ) = euler_deg_from_quaternion(profile.mount_local_orientation_quat)

        prim = get_or_define_prim(
            stage_obj,
            prim_path=state.array_prim_path,
            prim_type="Xform",
        )
        if attached:
            position_world = None
            orientation_world = None
        else:
            position_world = _author_position_arg(
                prim,
                default=self._array_position_from_state(),
            )
            orientation_world = _author_orientation_arg(
                prim,
                default=self._array_orientation_from_state(),
            )
        record = self._author_array_on_stage(
            stage_obj,
            position_world=position_world,
            orientation_world_quat=orientation_world,
            microphones=profile.microphones(),
            kind="array_rig_profile",
            extra_attrs={
                "ias:rig_profile_id": profile.profile_id,
                "ias:rig_profile_label": profile.display_label,
            },
        )
        binding_attrs: Mapping[str, object] = {}
        if attached:
            clear_prim_attrs(
                prim,
                (
                    "ias:position_world",
                    "ias:orientation_world_quat",
                ),
            )
            binding_attrs = attach_array_object_binding_attrs(
                prim,
                object_prim_path=object_path,
                local_offset_m=profile.mount_local_offset_m,
                local_orientation_quat=profile.mount_local_orientation_quat,
            )
        snapshot = self._applied_rig_profile_snapshot(profile)
        state.applied_array_rig_profile = snapshot
        authored = AuthoredMetadataSummary(
            kind="array_rig_profile",
            prim_path=state.array_prim_path,
            id=record.id,
            attributes=_jsonable_mapping(
                {
                    **dict(record.attributes),
                    **binding_attrs,
                    "applied_array_rig_profile": snapshot,
                }
            ),
        )
        self._append_authored_record(authored)
        return authored

    def _applied_rig_profile_snapshot(
        self,
        profile: MicrophoneRigProfile,
    ) -> dict[str, Any]:
        state = self.state
        return _json_ready(
            {
                "profile_id": profile.profile_id,
                "display_label": profile.display_label,
                "array_prim_path": state.array_prim_path,
                "array_id": state.array_id,
                "layout_name": state.layout_name,
                "sample_rate_hz": state.sample_rate_hz,
                "microphone_ids": profile.microphone_ids,
                "microphone_relative_offsets_m": (
                    profile.microphone_relative_offsets_m
                ),
                "microphone_gains_db": profile.microphone_gains_db,
                "mount_local_offset_m": profile.mount_local_offset_m,
                "mount_local_orientation_quat": profile.mount_local_orientation_quat,
                "recommended_mount_prim_path": profile.recommended_mount_prim_path,
                "array_attached_to_object": state.array_attached_to_object,
                "attached_object_prim_path": state.attached_array_object_prim_path
                or None,
            }
        )

    def _validate_source_metadata_state(self) -> None:
        state = self.state
        if state.audio_asset_path.strip() == "":
            raise ExtensionActionError("audio_asset_path must be non-empty.")
        if state.source_directivity.strip() == "":
            raise ExtensionActionError("source_directivity must be non-empty.")
        for field_name, value in (
            ("source_start_time_s", state.source_start_time_s),
            ("source_duration_s", state.source_duration_s),
            ("source_gain_db", state.source_gain_db),
        ):
            if not math.isfinite(float(value)):
                raise ExtensionActionError(f"{field_name} must be finite.")
        if state.source_duration_s <= 0.0:
            raise ExtensionActionError("source_duration_s must be positive.")

    def _source_position_from_state(self) -> tuple[float, float, float]:
        position = (
            float(self.state.source_position_x_m),
            float(self.state.source_position_y_m),
            float(self.state.source_position_z_m),
        )
        if not all(math.isfinite(component) for component in position):
            raise ExtensionActionError("source position values must be finite.")
        return position

    def _source_local_offset_from_state(self) -> tuple[float, float, float]:
        offset = (
            float(self.state.source_local_offset_x_m),
            float(self.state.source_local_offset_y_m),
            float(self.state.source_local_offset_z_m),
        )
        if not all(math.isfinite(component) for component in offset):
            raise ExtensionActionError("source local offset values must be finite.")
        return offset

    def _set_source_position_state(self, position: Iterable[float]) -> None:
        x, y, z = vec3_from_any(position)
        self.state.source_position_x_m = x
        self.state.source_position_y_m = y
        self.state.source_position_z_m = z

    def _array_position_from_state(self) -> tuple[float, float, float]:
        position = (
            float(self.state.array_position_x_m),
            float(self.state.array_position_y_m),
            float(self.state.array_position_z_m),
        )
        if not all(math.isfinite(component) for component in position):
            raise ExtensionActionError("array position values must be finite.")
        return position

    def _array_orientation_from_state(self) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_roll_deg),
            float(self.state.array_pitch_deg),
            float(self.state.array_yaw_deg),
        )
        if not all(math.isfinite(angle) for angle in angles):
            raise ExtensionActionError("array orientation angles must be finite.")
        return quaternion_from_euler_deg(
            roll_deg=angles[0],
            pitch_deg=angles[1],
            yaw_deg=angles[2],
        )

    def _array_local_offset_from_state(self) -> tuple[float, float, float]:
        offset = (
            float(self.state.array_local_offset_x_m),
            float(self.state.array_local_offset_y_m),
            float(self.state.array_local_offset_z_m),
        )
        if not all(math.isfinite(component) for component in offset):
            raise ExtensionActionError("array local offset values must be finite.")
        return offset

    def _array_local_orientation_from_state(
        self,
    ) -> tuple[float, float, float, float]:
        angles = (
            float(self.state.array_local_roll_deg),
            float(self.state.array_local_pitch_deg),
            float(self.state.array_local_yaw_deg),
        )
        if not all(math.isfinite(angle) for angle in angles):
            raise ExtensionActionError(
                "array local orientation angles must be finite."
            )
        return quaternion_from_euler_deg(
            roll_deg=angles[0],
            pitch_deg=angles[1],
            yaw_deg=angles[2],
        )

    def _set_array_pose_state(
        self,
        position: Iterable[float],
        orientation_quat: Iterable[float] | None = None,
    ) -> None:
        x, y, z = vec3_from_any(position)
        self.state.array_position_x_m = x
        self.state.array_position_y_m = y
        self.state.array_position_z_m = z
        if orientation_quat is not None:
            (
                self.state.array_roll_deg,
                self.state.array_pitch_deg,
                self.state.array_yaw_deg,
            ) = euler_deg_from_quaternion(quat_from_any(orientation_quat))

    def refresh_discovery(
        self,
        *,
        stage: Any | None = None,
    ) -> tuple[DiscoveredPrimSummary, ...]:
        """Discover array/source metadata on the current stage."""

        try:
            stage_obj = self._stage_or_error(stage)
            result = discover_stage_audio(
                stage_obj,
                cfg=self._discovery_cfg(required_arrays=False, required_sources=False),
            )
            self.state.discovered_arrays = tuple(
                DiscoveredPrimSummary(
                    id=array.spec.array_id,
                    prim_path=array.spec.prim_path or "",
                    reasons=tuple(array.reasons),
                )
                for array in result.arrays
            )
            self.state.discovered_sources = tuple(
                DiscoveredPrimSummary(
                    id=source.spec.source_id,
                    prim_path=source.spec.prim_path or "",
                    reasons=tuple(source.reasons),
                )
                for source in result.sources
            )
            self.state.discovered_objects = _discover_scene_objects(
                stage_obj,
                roots=self._discovery_roots(),
                excluded_paths=(
                    self.state.array_prim_path,
                    self.state.source_prim_path,
                    self.state.robot_base_prim_path,
                ),
            )
            self._set_status(
                "Discovery found "
                f"{len(result.arrays)} array(s), {len(result.sources)} source(s), "
                f"{len(self.state.discovered_objects)} object(s)."
            )
            return (
                *self.state.discovered_arrays,
                *self.state.discovered_sources,
                *self.state.discovered_objects,
            )
        except Exception as exc:
            self._record_error("Discovery failed", exc)
            return ()

    def configure_sensor(
        self,
        *,
        stage: Any | None = None,
        array_prim_path: str | None = None,
        backend: str | None = None,
        update_period_s: float | None = None,
        max_events: int | None = None,
        debug_draw: bool | None = None,
        writer_path: str | Path | None = None,
    ) -> IsaacAudioArraySensor | None:
        """Create or replace the live sensor from the current UI state."""

        try:
            if array_prim_path is not None:
                self.state.array_prim_path = str(array_prim_path)
            if backend is not None:
                self.state.backend = str(backend)
            if update_period_s is not None:
                self.state.update_period_s = float(update_period_s)
            if max_events is not None:
                self.state.max_events = int(max_events)
            if debug_draw is not None:
                self.state.debug_overlay_enabled = bool(debug_draw)
            if writer_path is not None:
                self.state.trace_enabled = True
                self.state.jsonl_trace_path = str(writer_path)

            stage_obj = self._stage_or_error(stage)
            sensor = self._build_sensor(stage_obj)
            self.close_sensor()
            self.sensor = sensor
            self.state.sensor_running = False
            self._set_status(
                f"Configured {sensor.backend} sensor for array {sensor.array_id}."
            )
            return sensor
        except Exception as exc:
            self._record_error("Sensor configure failed", exc)
            return None

    def start_sensor(
        self,
        *,
        stage: Any | None = None,
        subscribe_to_update_stream: bool = True,
    ) -> IsaacAudioArraySensor | None:
        """Configure if needed, then start the live sensor."""

        try:
            if self.sensor is None and self.configure_sensor(stage=stage) is None:
                return None
            assert self.sensor is not None
            self._stop_controller_update_subscription()
            self.sensor.start(subscribe_to_update_stream=False)
            try:
                if subscribe_to_update_stream:
                    self._start_controller_update_subscription()
            except IsaacIntegrationUnavailable as exc:
                self._set_status(
                    "Started without Kit update subscription: " + str(exc),
                    error=False,
                )
            else:
                self._set_status("Sensor started.")
            self.state.sensor_running = True
            return self.sensor
        except Exception as exc:
            self._record_error("Sensor start failed", exc)
            return None

    def stop_sensor(self) -> None:
        """Stop the live sensor without dropping the latest frame."""

        try:
            self._stop_controller_update_subscription()
            if self.sensor is not None:
                self.sensor.stop()
            self.state.sensor_running = False
            self._set_status("Sensor stopped.")
        except Exception as exc:
            self._record_error("Sensor stop failed", exc)

    def update_sensor(self, *, force: bool = True) -> Any | None:
        """Force one frame and update UI/export state."""

        try:
            if self.sensor is None:
                raise ExtensionActionError("Sensor is not configured.")
            previous_frame = self.sensor.latest_frame
            self._validate_attached_object_available(self.sensor.stage)
            self._validate_attached_array_available(self.sensor.stage)
            if self.state.array_prim_path.strip():
                self.sensor.array_prim_path = self.state.array_prim_path
            self.sensor.source_prim_path = (
                self.state.source_prim_path
                if self.state.source_attached_to_object
                and self.state.source_prim_path.strip()
                else None
            )
            frame = self.sensor.update(force=force)
            self._record_latest_frame(frame)
            if self.state.replicator_enabled and (
                force or _frame_is_new(previous_frame, frame)
            ):
                self._write_replicator_frame(frame)
            return frame
        except Exception as exc:
            self._record_error("Sensor update failed", exc)
            return None

    def export_latest_frame(self, path: str | Path | None = None) -> Path | None:
        """Write the latest frame using deterministic v1 trace serialization."""

        try:
            if self.sensor is None or self.sensor.latest_frame is None:
                raise ExtensionActionError("No latest frame is available to export.")
            output_path = _resolve_gui_output_path(
                path or self.state.latest_frame_export_path
            )
            output = write_frame_trace(
                self.sensor.latest_frame,
                output_path,
            )
            self._set_status(f"Exported latest frame to {output}.")
            return output
        except Exception as exc:
            self._record_error("Latest-frame export failed", exc)
            return None

    def export_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Write a reusable stage-binding/config summary."""

        try:
            output = _resolve_gui_output_path(path or self.state.config_export_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    self.config_summary_dict(),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._set_status(f"Exported config summary to {output}.")
            return output
        except Exception as exc:
            self._record_error("Config export failed", exc)
            return None

    def import_config_summary(self, path: str | Path | None = None) -> Path | None:
        """Load a deterministic extension config summary into UI state."""

        try:
            requested_path = path or self.state.config_import_path
            input_path = _resolve_gui_output_path(requested_path)
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "ias.omni_extension_binding.v1":
                raise ExtensionActionError(
                    "Config import requires schema_version "
                    "'ias.omni_extension_binding.v1'."
                )
            self._apply_config_summary(payload)
            self.state.config_import_path = str(requested_path)
            missing_attachment = self._attachment_status_for_current_stage()
            if missing_attachment:
                self._set_status(
                    f"Imported config summary from {input_path}; "
                    f"{missing_attachment}",
                    error=True,
                )
            else:
                self._set_status(f"Imported config summary from {input_path}.")
            return input_path
        except Exception as exc:
            self._record_error("Config import failed", exc)
            return None

    def config_summary_dict(self) -> dict[str, Any]:
        """Return a JSON-ready stage-binding summary for evidence/reuse."""

        state = self.state
        primitives = (
            () if self.sensor is None else tuple(self.sensor.latest_debug_primitives)
        )
        writer_path = (
            str(_resolve_gui_output_path(state.jsonl_trace_path))
            if state.trace_enabled
            else None
        )
        return _json_ready(
            {
                "schema_version": "ias.omni_extension_binding.v1",
                "backend": state.backend,
                "array": {
                    "prim_path": state.array_prim_path,
                    "array_id": state.array_id,
                    "layout_name": state.layout_name,
                    "sample_rate_hz": state.sample_rate_hz,
                    "coordinate_convention": state.coordinate_convention,
                    "position_world": self._array_position_from_state(),
                    "orientation_world_quat": self._array_orientation_from_state(),
                    "orientation_euler_deg": (
                        state.array_roll_deg,
                        state.array_pitch_deg,
                        state.array_yaw_deg,
                    ),
                },
                "source": {
                    "prim_path": state.source_prim_path,
                    "source_id": state.source_id,
                    "class_label": state.source_class_label,
                    "audio_asset_path": state.audio_asset_path,
                    "position_world": self._source_position_from_state(),
                    "local_offset_m": self._source_local_offset_from_state(),
                    "start_time_s": state.source_start_time_s,
                    "duration_s": state.source_duration_s,
                    "gain_db": state.source_gain_db,
                    "directivity": state.source_directivity,
                },
                "sound_profiles": {
                    "profile_library": [
                        profile.to_dict() for profile in state.profile_library
                    ],
                    "selected_profile_id": state.selected_profile_id or None,
                    "object_profile_mappings": dict(
                        sorted(state.object_profile_mappings.items())
                    ),
                    "applied_source_profile": state.applied_source_profile or None,
                },
                "object_binding": {
                    "selected_object_prim_path": state.object_prim_path or None,
                    "selected_object_label": state.object_label,
                    "attached": state.source_attached_to_object,
                    "attached_object_prim_path": state.attached_object_prim_path
                    or None,
                    "source_local_offset_m": self._source_local_offset_from_state(),
                },
                "array_binding": {
                    "attached": state.array_attached_to_object,
                    "attached_object_prim_path": (
                        state.attached_array_object_prim_path or None
                    ),
                    "array_local_offset_m": self._array_local_offset_from_state(),
                    "array_local_orientation_quat": (
                        self._array_local_orientation_from_state()
                    ),
                    "array_local_euler_deg": (
                        state.array_local_roll_deg,
                        state.array_local_pitch_deg,
                        state.array_local_yaw_deg,
                    ),
                },
                "microphone_rig_profiles": {
                    "rig_library": [
                        profile.to_dict() for profile in state.rig_profile_library
                    ],
                    "selected_rig_profile_id": state.selected_rig_profile_id or None,
                    "applied_array_rig_profile": (
                        state.applied_array_rig_profile or None
                    ),
                },
                "stage_binding": {
                    "robot_base_prim_path": state.robot_base_prim_path or None,
                    "discovery_roots": self._discovery_roots(),
                    "preferred_source": state.source_id or None,
                    "selected_prim_paths": state.selected_prim_paths,
                    "discovered_arrays": state.discovered_arrays,
                    "discovered_sources": state.discovered_sources,
                    "discovered_objects": state.discovered_objects,
                },
                "lifecycle": {
                    "update_period_s": state.update_period_s,
                    "max_events": state.max_events,
                    "ambiguity_policy": state.ambiguity_policy,
                    "debug_overlay_enabled": state.debug_overlay_enabled,
                    "writer_enabled": state.trace_enabled,
                    "writer_path": writer_path,
                    "runtime_options": {
                        "subscribe_to_update_stream_default": True,
                        "import_safe_outside_isaac": True,
                    },
                },
                "recording": {
                    "package_jsonl": {
                        "enabled": state.trace_enabled,
                        "path": writer_path,
                    },
                    "replicator": self._replicator_status_dict(),
                },
                "authored_metadata": state.authored_metadata,
                "latest_frame": {
                    "frame_id": state.latest_frame_id,
                    "backend": state.latest_backend,
                    "detection_count": state.latest_detection_count,
                    "source_prim_path": state.latest_source_prim_path,
                    "source_position_m": state.latest_source_position_m,
                    "bearing_deg": state.latest_bearing_deg,
                    "sector": state.latest_sector,
                    "array_prim_path": state.latest_array_prim_path,
                    "array_position_m": state.latest_array_position_m,
                    "array_orientation_xyzw": state.latest_array_orientation_xyzw,
                    "mic_world_positions": dict(
                        sorted(state.latest_mic_world_positions.items())
                    ),
                },
                "overlay": {
                    "primitive_count": state.latest_overlay_primitive_count,
                    "labels": state.latest_overlay_labels,
                    "status": state.latest_overlay_status,
                    "error": state.latest_overlay_error,
                    "primitives": debug_primitives_to_dicts(primitives),
                },
            }
        )

    def start_replicator(self) -> dict[str, Any] | None:
        """Start the Omniverse-native Replicator writer path."""

        try:
            self.state.replicator_enabled = True
            if self.replicator_recorder is not None:
                self.replicator_recorder.stop()
            output_dir = _resolve_gui_output_path(self.state.replicator_output_dir)
            recorder = AudioSensorReplicatorRecorder(
                output_dir=output_dir,
                writer_name=self.state.replicator_writer_name,
                annotator_name=self.state.replicator_annotator_name,
            )
            self.replicator_recorder = recorder
            status = recorder.start()
            self._apply_replicator_status(status.to_dict())
            self._set_status("Replicator recording started at " f"{output_dir}.")
            return self._replicator_status_dict()
        except Exception as exc:
            self.replicator_recorder = None
            self._record_error("Replicator start failed", exc)
            return None

    def flush_replicator(self) -> dict[str, Any] | None:
        """Flush Replicator writer output."""

        try:
            if self.replicator_recorder is None:
                raise ExtensionActionError("Replicator recording is not started.")
            status = self.replicator_recorder.flush()
            self._apply_replicator_status(status.to_dict())
            self._set_status("Replicator recording flushed.")
            return self._replicator_status_dict()
        except Exception as exc:
            self._record_error("Replicator flush failed", exc)
            return None

    def stop_replicator(self) -> dict[str, Any] | None:
        """Stop Replicator recording without disabling configured settings."""

        try:
            if self.replicator_recorder is None:
                self.state.replicator_recording = False
                self.state.replicator_status_message = "Replicator idle."
                return self._replicator_status_dict()
            status = self.replicator_recorder.stop()
            self._apply_replicator_status(status.to_dict())
            self._set_status("Replicator recording stopped.")
            return self._replicator_status_dict()
        except Exception as exc:
            self._record_error("Replicator stop failed", exc)
            return None

    def close_sensor(self) -> None:
        """Close the live sensor and writer/debug handles."""

        self._stop_controller_update_subscription()
        if self.sensor is not None:
            self.sensor.close()
        self.sensor = None
        self.state.sensor_running = False

    def _start_controller_update_subscription(self) -> None:
        try:
            import omni.kit.app  # type: ignore
        except ImportError as exc:
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires omni.kit.app inside "
                "an Isaac Sim Python environment."
            ) from exc
        app = omni.kit.app.get_app()
        get_stream = getattr(app, "get_update_event_stream", None)
        if not callable(get_stream):
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires get_update_event_stream."
            )
        stream = get_stream()
        subscribe = getattr(stream, "create_subscription_to_pop", None)
        if not callable(subscribe):
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires "
                "create_subscription_to_pop."
            )

        def _on_update(_event: Any) -> None:
            if self.sensor is None or not self.state.sensor_running:
                return
            frame = self.update_sensor(force=False)
            if frame is not None and self._ui_window is not None:
                self._ui_window.refresh_labels()

        self._controller_update_subscription = subscribe(
            _on_update,
            name="isaac_audio_sensors.extension_ui.update",
        )

    def _stop_controller_update_subscription(self) -> None:
        self._controller_update_subscription = None

    def _build_sensor(self, stage: Any) -> IsaacAudioArraySensor:
        state = self.state
        self._validate_runtime_state()
        writer_path = (
            _resolve_gui_output_path(state.jsonl_trace_path)
            if state.trace_enabled
            else None
        )
        explicit_array_available = bool(
            state.array_prim_path.strip()
        ) and _stage_has_prim(stage, state.array_prim_path)
        if explicit_array_available:
            explicit_source = (
                state.source_prim_path
                if state.source_attached_to_object and state.source_prim_path.strip()
                else None
            )
            return IsaacAudioArraySensor.from_stage(
                stage=stage,
                array_prim_path=state.array_prim_path,
                source_prim_path=explicit_source,
                robot_base_prim_path=state.robot_base_prim_path or None,
                backend=state.backend,
                update_period_s=state.update_period_s,
                max_events=state.max_events,
                ambiguity_policy=state.ambiguity_policy,
                debug_draw=state.debug_overlay_enabled,
                writer_path=writer_path,
            )

        binding_cfg = IsaacAudioSceneBindingCfg(
            discovery_roots=self._discovery_roots(),
            robot_base_prim_path=state.robot_base_prim_path or None,
            required_arrays=True,
            required_sources=False,
            preferred_array=self._preferred_discovered_array(),
            preferred_source=None,
        )
        sensor = IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            binding_cfg=binding_cfg,
            backend=state.backend,
            update_period_s=state.update_period_s,
            max_events=state.max_events,
            ambiguity_policy=state.ambiguity_policy,
            debug_draw=state.debug_overlay_enabled,
            writer_path=writer_path,
        )
        if sensor.stage_snapshot is not None:
            selected = sensor.stage_snapshot.array_by_id(sensor.array_id)
            if selected.prim_path:
                state.array_prim_path = selected.prim_path
            state.array_id = sensor.array_id
        return sensor

    def _validate_runtime_state(self) -> None:
        state = self.state
        if state.backend not in BACKEND_CHOICES:
            raise ExtensionActionError(
                f"Backend {state.backend!r} is not an implemented v1 backend."
            )
        if state.ambiguity_policy not in AMBIGUITY_POLICY_CHOICES:
            raise ExtensionActionError(
                f"Ambiguity policy {state.ambiguity_policy!r} is not supported."
            )
        if state.update_period_s <= 0.0 or not math.isfinite(state.update_period_s):
            raise ExtensionActionError("update_period_s must be positive and finite.")
        if state.max_events < 0:
            raise ExtensionActionError("max_events must be non-negative.")
        if state.array_prim_path.strip():
            _validate_abs_path(state.array_prim_path, "array_prim_path")
        if state.robot_base_prim_path.strip():
            _validate_abs_path(state.robot_base_prim_path, "robot_base_prim_path")

    def _author_child_microphones(
        self,
        stage: Any,
        *,
        array_path: str,
        microphones: Iterable[Any],
    ) -> None:
        for microphone in microphones:
            child_path = f"{array_path.rstrip('/')}/{microphone.mic_id}"
            child = get_or_define_prim(
                stage,
                prim_path=child_path,
                prim_type="Microphone",
            )
            attach_microphone_attrs(
                child,
                mic_id=microphone.mic_id,
                relative_position_m=microphone.relative_position_m,
                relative_orientation_quat=microphone.relative_orientation_quat,
                gain_db=microphone.gain_db,
                self_noise_db=microphone.self_noise_db,
            )

    def _remove_stale_child_microphones(
        self,
        stage: Any,
        *,
        array_path: str,
        keep_mic_ids: tuple[str, ...],
    ) -> None:
        if not hasattr(stage, "Traverse"):
            return
        prefix = array_path.rstrip("/") + "/"
        keep = set(keep_mic_ids)
        for prim in tuple(stage.Traverse()):
            path = prim_path(prim)
            if not path.startswith(prefix) or "/" in path[len(prefix) :]:
                continue
            attrs = _prim_attrs(prim)
            is_microphone = (
                _prim_type_name(prim) == "Microphone" or "ias:microphone_id" in attrs
            )
            if not is_microphone:
                continue
            mic_id = str(attrs.get("ias:microphone_id", _path_name(path)))
            if mic_id not in keep:
                remove_prim(stage, path)

    def _discovery_cfg(
        self,
        *,
        required_arrays: bool,
        required_sources: bool,
    ) -> IsaacAudioDiscoveryCfg:
        return IsaacAudioDiscoveryCfg(
            discovery_roots=self._discovery_roots(),
            robot_base_prim_path=self.state.robot_base_prim_path or None,
            required_arrays=required_arrays,
            required_sources=required_sources,
            default_microphone_layout=self.state.layout_name,
            default_sample_rate_hz=self.state.sample_rate_hz,
            coordinate_convention=self.state.coordinate_convention,
            default_source_duration_s=self.state.source_duration_s,
        )

    def _discovery_roots(self) -> tuple[str, ...]:
        roots = tuple(
            root.strip()
            for root in self.state.discovery_roots_text.replace(";", ",").split(",")
            if root.strip()
        )
        return roots or ("/World",)

    def _preferred_discovered_array(self) -> str | None:
        if not self.state.array_id:
            return None
        for item in self.state.discovered_arrays:
            if item.id == self.state.array_id:
                return self.state.array_id
        return None

    def _validated_sound_profiles(self) -> tuple[SoundProfile, ...]:
        profiles = validate_sound_profile_library(self.state.profile_library)
        self.state.profile_library = profiles
        profile_ids = {profile.profile_id for profile in profiles}
        bad_mappings = {
            label: profile_id
            for label, profile_id in self.state.object_profile_mappings.items()
            if profile_id not in profile_ids
        }
        if bad_mappings:
            label, profile_id = next(iter(sorted(bad_mappings.items())))
            raise ExtensionActionError(
                "Object profile mapping "
                f"{label!r} references unknown profile {profile_id!r}."
            )
        return profiles

    def _sound_profile_by_id(self, profile_id: str) -> SoundProfile:
        requested = profile_id.strip()
        if not requested:
            raise ExtensionActionError("selected_profile_id must be non-empty.")
        for profile in self._validated_sound_profiles():
            if profile.profile_id == requested:
                return profile
        raise ExtensionActionError(f"Unknown sound profile id {requested!r}.")

    def _validated_rig_profiles(self) -> tuple[MicrophoneRigProfile, ...]:
        profiles = validate_microphone_rig_profile_library(
            self.state.rig_profile_library
        )
        self.state.rig_profile_library = profiles
        return profiles

    def _rig_profile_by_id(self, profile_id: str) -> MicrophoneRigProfile:
        requested = profile_id.strip()
        if not requested:
            raise ExtensionActionError("selected_rig_profile_id must be non-empty.")
        for profile in self._validated_rig_profiles():
            if profile.profile_id == requested:
                return profile
        raise ExtensionActionError(f"Unknown rig profile id {requested!r}.")

    def _profile_object_label(self, stage_obj: Any | None) -> str:
        labels = self._object_label_candidates(stage=stage_obj, selected_paths=None)
        return labels[0] if labels else _path_name(self.state.source_prim_path)

    def _object_label_candidates(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> tuple[str, ...]:
        candidates: list[str] = []
        context_stage = stage
        if selected_paths is not None:
            context = self._context(stage=stage, selected_paths=selected_paths)
            context_stage = context.stage or stage
            for path in context.selected_prim_paths:
                candidates.extend(
                    _object_label_candidates_for_path(context_stage, path)
                )
        for label in (self.state.object_label,):
            if label and label != "none":
                candidates.append(label)
        for path in (
            self.state.object_prim_path,
            self.state.attached_object_prim_path,
        ):
            if path:
                candidates.extend(
                    _object_label_candidates_for_path(context_stage, path)
                )
        if self.state.source_attached_to_object and self.state.source_prim_path:
            parent_path = self.state.source_prim_path.rstrip("/").rsplit("/", 1)[0]
            candidates.extend(
                _object_label_candidates_for_path(context_stage, parent_path)
            )
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = str(candidate).strip()
            if not text or text.lower() == "none":
                continue
            key = normalize_object_label(text)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return tuple(normalized)

    def _selected_object_candidate_path(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> str | None:
        if selected_paths is None:
            return None
        context = self._context(stage=stage, selected_paths=selected_paths)
        for path in context.selected_prim_paths:
            if path in {self.state.array_prim_path, self.state.source_prim_path}:
                continue
            if context.stage is None or _stage_has_prim(context.stage, path):
                return path
        return None

    def _stage_or_error(self, stage: Any | None) -> Any:
        context = self._context(stage=stage)
        if context.stage is None:
            raise ExtensionActionError("No USD stage is open.")
        self.state.selected_prim_paths = context.selected_prim_paths
        return context.stage

    def _validate_attached_object_available(self, stage: Any | None) -> None:
        if not self.state.source_attached_to_object:
            return
        object_path = (
            self.state.attached_object_prim_path or self.state.object_prim_path
        )
        if not object_path:
            raise ExtensionActionError(
                "Source is marked attached but no object path is configured."
            )
        if stage is None:
            return
        if not _stage_has_prim(stage, object_path):
            raise ExtensionActionError(
                f"Attached object no longer exists: {object_path}. "
                "Select another object or detach the source."
            )

    def _validate_attached_array_available(self, stage: Any | None) -> None:
        if not self.state.array_attached_to_object:
            return
        object_path = (
            self.state.attached_array_object_prim_path or self.state.object_prim_path
        )
        if not object_path:
            raise ExtensionActionError(
                "Array is marked attached but no mount path is configured."
            )
        if stage is None:
            return
        if not _stage_has_prim(stage, object_path):
            raise ExtensionActionError(
                f"Attached array mount no longer exists: {object_path}. "
                "Select another mount or detach the array."
            )

    def _attachment_status_for_current_stage(self) -> str | None:
        if not self.state.source_attached_to_object:
            return None
        object_path = (
            self.state.attached_object_prim_path or self.state.object_prim_path
        )
        if not object_path:
            return "attached object path is missing"
        try:
            stage = self._context().stage
        except Exception:
            return None
        if stage is None:
            return None
        if not _stage_has_prim(stage, object_path):
            return f"attached object is missing from the current stage: {object_path}"
        return None

    def _context(
        self,
        *,
        stage: Any | None = None,
        selected_paths: Iterable[str] | None = None,
    ) -> CurrentStageContext:
        if stage is not None:
            return CurrentStageContext(
                stage=stage,
                selected_prim_paths=_normalize_paths(selected_paths or ()),
            )
        if selected_paths is not None:
            return CurrentStageContext(
                stage=None,
                selected_prim_paths=_normalize_paths(selected_paths),
            )
        if self.stage_context_provider is not None:
            return self.stage_context_provider()
        return current_omni_stage_context()

    def _first_selected_path(
        self,
        *,
        stage: Any | None,
        selected_paths: Iterable[str] | None,
    ) -> str | None:
        try:
            paths = self.refresh_stage_selection(
                stage=stage,
                selected_paths=selected_paths,
            )
            if not paths:
                raise ExtensionActionError("No prim is selected.")
            return paths[0]
        except Exception as exc:
            self._record_error("Selection binding failed", exc)
            return None

    def _append_authored_record(self, record: AuthoredMetadataSummary) -> None:
        self.state.authored_metadata = (*self.state.authored_metadata, record)

    def _record_latest_frame(self, frame: Any) -> None:
        detections = tuple(frame.detections)
        first = detections[0] if detections else None
        self.state.latest_frame_id = frame.frame_id
        self.state.latest_detection_count = len(detections)
        self.state.latest_backend = frame.backend_id
        self.state.latest_source_prim_path = self._latest_source_prim_path(first)
        self.state.latest_source_position_m = (
            None
            if first is None or first.source_pose is None
            else vec3_from_any(first.source_pose.position_m)
        )
        self.state.latest_bearing_deg = (
            None if first is None else first.doa.estimated_bearing_deg
        )
        self.state.latest_sector = None if first is None else first.doa.bearing_sector
        array_pose = getattr(frame, "array_pose", None)
        self.state.latest_array_prim_path = (
            None
            if self.sensor is None
            else getattr(self.sensor, "array_prim_path", None)
        ) or (self.state.array_prim_path or None)
        self.state.latest_array_position_m = (
            None if array_pose is None else vec3_from_any(array_pose.position_m)
        )
        array_orientation = (
            None
            if array_pose is None
            else getattr(array_pose, "orientation_xyzw", None)
        )
        self.state.latest_array_orientation_xyzw = (
            None if array_orientation is None else quat_from_any(array_orientation)
        )
        self.state.latest_mic_world_positions = self._latest_mic_world_positions()
        self.state.latest_aggregate_rms = _aggregate_rms_from_frame(frame)
        primitives: tuple[DebugPrimitive, ...] = (
            () if self.sensor is None else tuple(self.sensor.latest_debug_primitives)
        )
        self.state.latest_overlay_primitive_count = len(primitives)
        self.state.latest_overlay_labels = tuple(
            primitive.label for primitive in primitives
        )
        self._record_overlay_status()
        self._set_status(
            f"Updated {frame.frame_id}: {len(detections)} detection(s), "
            f"{len(primitives)} overlay primitive(s)."
        )

    def _latest_mic_world_positions(self) -> dict[str, tuple[float, float, float]]:
        if self.sensor is None:
            return {}
        sensor_spec = getattr(self.sensor, "_latest_sensor", None)
        if sensor_spec is None:
            return {}
        try:
            return dict(microphone_world_positions(sensor_spec))
        except Exception:
            return {}

    def _latest_source_prim_path(self, detection: Any | None) -> str | None:
        if detection is None:
            return None
        scene = (
            None if self.sensor is None else getattr(self.sensor, "_latest_scene", None)
        )
        if scene is not None and detection.source_id is not None:
            for source in scene.sources:
                if source.source_id == detection.source_id and source.prim_path:
                    return source.prim_path
        return self.state.source_prim_path or None

    def _record_overlay_status(self) -> None:
        if self.sensor is None or self.sensor.debug_drawer is None:
            self.state.latest_overlay_status = (
                "disabled"
                if not self.state.debug_overlay_enabled
                else "serialized_without_debug_drawer"
            )
            self.state.latest_overlay_error = None
            return
        drawer = self.sensor.debug_drawer
        self.state.latest_overlay_status = str(
            getattr(drawer, "last_status", "serialized")
        )
        latest_error = getattr(drawer, "last_error", None)
        self.state.latest_overlay_error = (
            None if latest_error is None else str(latest_error)
        )

    def _write_replicator_frame(self, frame: Any) -> None:
        if self.replicator_recorder is None:
            raise ExtensionActionError(
                "Replicator recording is enabled but not started."
            )
        result = self.replicator_recorder.write_frame(
            frame,
            metadata=self._replicator_frame_metadata(frame),
        )
        self._apply_replicator_status(
            self.replicator_recorder.status.to_dict(),
        )
        self._set_status(
            f"Updated {frame.frame_id}; Replicator wrote {result.json_path}."
        )

    def _replicator_frame_metadata(self, frame: Any) -> dict[str, Any]:
        writer_path = (
            str(_resolve_gui_output_path(self.state.jsonl_trace_path))
            if self.state.trace_enabled
            else None
        )
        return _json_ready(
            {
                "extension_id": self.ext_id,
                "extension_state": {
                    "backend": self.state.backend,
                    "array_prim_path": self.state.array_prim_path,
                    "source_prim_path": self.state.source_prim_path,
                    "source_position_m": self._source_position_from_state(),
                    "selected_profile_id": self.state.selected_profile_id or None,
                    "applied_source_profile": self.state.applied_source_profile or None,
                    "source_attached_to_object": self.state.source_attached_to_object,
                    "attached_object_prim_path": self.state.attached_object_prim_path
                    or None,
                    "source_local_offset_m": self._source_local_offset_from_state(),
                    "latest_source_position_m": self.state.latest_source_position_m,
                    "array_position_m": self._array_position_from_state(),
                    "array_attached_to_object": self.state.array_attached_to_object,
                    "attached_array_object_prim_path": (
                        self.state.attached_array_object_prim_path or None
                    ),
                    "array_local_offset_m": self._array_local_offset_from_state(),
                    "selected_rig_profile_id": (
                        self.state.selected_rig_profile_id or None
                    ),
                    "robot_base_prim_path": self.state.robot_base_prim_path or None,
                    "discovery_roots": self._discovery_roots(),
                    "selected_prim_paths": self.state.selected_prim_paths,
                    "update_period_s": self.state.update_period_s,
                    "max_events": self.state.max_events,
                    "ambiguity_policy": self.state.ambiguity_policy,
                    "debug_overlay_enabled": self.state.debug_overlay_enabled,
                },
                "package_recording": {
                    "jsonl_enabled": self.state.trace_enabled,
                    "jsonl_trace_path": writer_path,
                    "latest_frame_export_path": str(
                        _resolve_gui_output_path(self.state.latest_frame_export_path)
                    ),
                    "config_export_path": str(
                        _resolve_gui_output_path(self.state.config_export_path)
                    ),
                },
                "overlay": {
                    "primitive_count": self.state.latest_overlay_primitive_count,
                    "labels": self.state.latest_overlay_labels,
                    "status": self.state.latest_overlay_status,
                    "error": self.state.latest_overlay_error,
                },
                "frame": {
                    "frame_id": frame.frame_id,
                    "backend_id": frame.backend_id,
                    "array_id": frame.array_id,
                    "timestamp_ms": frame.timestamp_ms,
                },
            }
        )

    def _apply_replicator_status(self, status: Mapping[str, Any]) -> None:
        self.state.replicator_recording = bool(status.get("started"))
        self.state.replicator_write_count = int(status.get("write_count", 0))
        self.state.replicator_flush_count = int(status.get("flush_count", 0))
        self.state.replicator_latest_write_path = status.get("latest_write_path")
        self.state.replicator_latest_jsonl_path = status.get("latest_jsonl_path")
        self.state.replicator_latest_error = status.get("latest_error")
        self.state.replicator_output_artifacts = tuple(
            str(item) for item in status.get("output_artifacts", ())
        )
        self.state.replicator_status_message = (
            f"Replicator started={status.get('started')} "
            f"writer_registered={status.get('writer_registered')} "
            f"writes={status.get('write_count', 0)} "
            f"flushes={status.get('flush_count', 0)}"
        )

    def _replicator_status_dict(self) -> dict[str, Any]:
        state = self.state
        if self.replicator_recorder is not None:
            status = self.replicator_recorder.status.to_dict()
            status["enabled"] = state.replicator_enabled
            return status
        output_dir = state.replicator_output_dir
        if output_dir.strip():
            with suppress(Exception):
                output_dir = str(_resolve_gui_output_path(output_dir))
        return {
            "enabled": state.replicator_enabled,
            "writer_name": state.replicator_writer_name,
            "annotator_name": state.replicator_annotator_name,
            "output_dir": output_dir,
            "started": state.replicator_recording,
            "write_count": state.replicator_write_count,
            "flush_count": state.replicator_flush_count,
            "latest_write_path": state.replicator_latest_write_path,
            "latest_jsonl_path": state.replicator_latest_jsonl_path,
            "latest_error": state.replicator_latest_error,
            "output_artifacts": list(state.replicator_output_artifacts),
            "status_message": state.replicator_status_message,
        }

    def _apply_config_summary(self, payload: Mapping[str, Any]) -> None:
        array = dict(payload.get("array", {}))
        source = dict(payload.get("source", {}))
        sound_profiles = payload.get("sound_profiles")
        rig_profiles = payload.get("microphone_rig_profiles")
        object_binding = dict(payload.get("object_binding", {}))
        array_binding = dict(payload.get("array_binding", {}))
        binding = dict(payload.get("stage_binding", {}))
        lifecycle = dict(payload.get("lifecycle", {}))
        recording = dict(payload.get("recording", {}))
        package_recording = dict(recording.get("package_jsonl", {}))
        replicator = dict(recording.get("replicator", {}))

        self.state.backend = str(payload.get("backend", self.state.backend))
        self.state.array_prim_path = str(
            array.get("prim_path", self.state.array_prim_path)
        )
        self.state.array_id = str(array.get("array_id", self.state.array_id))
        self.state.layout_name = str(array.get("layout_name", self.state.layout_name))
        self.state.sample_rate_hz = int(
            array.get("sample_rate_hz", self.state.sample_rate_hz)
        )
        self.state.coordinate_convention = str(
            array.get("coordinate_convention", self.state.coordinate_convention)
        )
        if array.get("position_world") is not None:
            self._set_array_pose_state(array["position_world"], None)
        if array.get("orientation_world_quat") is not None:
            (
                self.state.array_roll_deg,
                self.state.array_pitch_deg,
                self.state.array_yaw_deg,
            ) = euler_deg_from_quaternion(
                quat_from_any(array["orientation_world_quat"])
            )
        self.state.array_attached_to_object = bool(
            array_binding.get("attached", self.state.array_attached_to_object)
        )
        attached_array_path = array_binding.get("attached_object_prim_path")
        if attached_array_path is not None:
            self.state.attached_array_object_prim_path = str(attached_array_path)
        elif not self.state.array_attached_to_object:
            self.state.attached_array_object_prim_path = ""
        array_local_offset = array_binding.get("array_local_offset_m")
        if array_local_offset is not None:
            (
                self.state.array_local_offset_x_m,
                self.state.array_local_offset_y_m,
                self.state.array_local_offset_z_m,
            ) = vec3_from_any(array_local_offset)
        array_local_quat = array_binding.get("array_local_orientation_quat")
        if array_local_quat is not None:
            (
                self.state.array_local_roll_deg,
                self.state.array_local_pitch_deg,
                self.state.array_local_yaw_deg,
            ) = euler_deg_from_quaternion(quat_from_any(array_local_quat))
        if rig_profiles is not None:
            self._apply_rig_profile_config(rig_profiles)
        self.state.source_prim_path = str(
            source.get("prim_path", self.state.source_prim_path)
        )
        self.state.source_id = str(source.get("source_id", self.state.source_id))
        self.state.source_class_label = str(
            source.get("class_label", self.state.source_class_label)
        )
        self.state.audio_asset_path = str(
            source.get("audio_asset_path", self.state.audio_asset_path)
        )
        if source.get("position_world") is not None:
            self._set_source_position_state(source["position_world"])
        local_offset = object_binding.get(
            "source_local_offset_m",
            source.get("local_offset_m"),
        )
        if local_offset is not None:
            (
                self.state.source_local_offset_x_m,
                self.state.source_local_offset_y_m,
                self.state.source_local_offset_z_m,
            ) = vec3_from_any(local_offset)
        self.state.source_start_time_s = float(
            source.get("start_time_s", self.state.source_start_time_s)
        )
        self.state.source_duration_s = float(
            source.get("duration_s", self.state.source_duration_s)
        )
        self.state.source_gain_db = float(
            source.get("gain_db", self.state.source_gain_db)
        )
        self.state.source_directivity = str(
            source.get("directivity", self.state.source_directivity)
        )
        if sound_profiles is not None:
            self._apply_profile_config(sound_profiles)
        self.state.robot_base_prim_path = str(binding.get("robot_base_prim_path") or "")
        self.state.object_prim_path = str(
            object_binding.get("selected_object_prim_path")
            or self.state.object_prim_path
            or ""
        )
        self.state.object_label = str(
            object_binding.get("selected_object_label")
            or (
                _path_name(self.state.object_prim_path)
                if self.state.object_prim_path
                else "none"
            )
        )
        self.state.source_attached_to_object = bool(
            object_binding.get("attached", self.state.source_attached_to_object)
        )
        self.state.attached_object_prim_path = str(
            object_binding.get("attached_object_prim_path")
            or (
                self.state.object_prim_path
                if self.state.source_attached_to_object
                else ""
            )
        )
        roots = binding.get("discovery_roots", self._discovery_roots())
        self.state.discovery_roots_text = ", ".join(str(root) for root in roots)
        self.state.selected_prim_paths = _normalize_paths(
            binding.get("selected_prim_paths", ())
        )
        self.state.discovered_objects = tuple(
            _discovered_summary_from_dict(item)
            for item in binding.get("discovered_objects", ())
        )
        self.state.update_period_s = float(
            lifecycle.get("update_period_s", self.state.update_period_s)
        )
        self.state.max_events = int(lifecycle.get("max_events", self.state.max_events))
        self.state.ambiguity_policy = str(
            lifecycle.get("ambiguity_policy", self.state.ambiguity_policy)
        )
        self.state.debug_overlay_enabled = bool(
            lifecycle.get(
                "debug_overlay_enabled",
                self.state.debug_overlay_enabled,
            )
        )
        self.state.trace_enabled = bool(
            package_recording.get(
                "enabled",
                lifecycle.get("writer_enabled", self.state.trace_enabled),
            )
        )
        self.state.jsonl_trace_path = str(
            package_recording.get(
                "path",
                lifecycle.get("writer_path", self.state.jsonl_trace_path),
            )
            or self.state.jsonl_trace_path
        )
        self.state.replicator_enabled = bool(
            replicator.get("enabled", self.state.replicator_enabled)
        )
        self.state.replicator_output_dir = str(
            replicator.get("output_dir", self.state.replicator_output_dir)
        )
        self.state.replicator_writer_name = str(
            replicator.get("writer_name", self.state.replicator_writer_name)
        )
        self.state.replicator_annotator_name = str(
            replicator.get("annotator_name", self.state.replicator_annotator_name)
        )
        self.state.authored_metadata = tuple(
            _authored_metadata_from_dict(item)
            for item in payload.get("authored_metadata", ())
        )

    def _apply_profile_config(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            raise ExtensionActionError("sound_profiles config must be an object.")
        raw_library = payload.get("profile_library")
        if raw_library is None:
            raise ExtensionActionError(
                "sound_profiles.profile_library is required when profiles are present."
            )
        raw_mappings = payload.get("object_profile_mappings")
        if raw_mappings is None:
            raise ExtensionActionError(
                "sound_profiles.object_profile_mappings is required when "
                "profiles are present."
            )
        if not isinstance(raw_mappings, Mapping):
            raise ExtensionActionError(
                "sound_profiles.object_profile_mappings must be an object."
            )
        if not isinstance(raw_library, list | tuple):
            raise ExtensionActionError(
                "sound_profiles.profile_library must be a list of profile objects."
            )
        profiles = validate_sound_profile_library(
            sound_profile_from_mapping(item) for item in raw_library
        )
        profile_ids = {profile.profile_id for profile in profiles}
        mappings = {
            normalize_object_label(str(label)): str(profile_id).strip()
            for label, profile_id in raw_mappings.items()
            if normalize_object_label(str(label))
        }
        if not mappings:
            raise ExtensionActionError(
                "sound_profiles.object_profile_mappings must not be empty."
            )
        for label, profile_id in sorted(mappings.items()):
            if profile_id not in profile_ids:
                raise ExtensionActionError(
                    "sound_profiles.object_profile_mappings "
                    f"{label!r} references unknown profile {profile_id!r}."
                )
        selected_profile_id = payload.get("selected_profile_id")
        selected_profile_id = (
            "" if selected_profile_id is None else str(selected_profile_id).strip()
        )
        if selected_profile_id and selected_profile_id not in profile_ids:
            raise ExtensionActionError(
                f"Unknown selected sound profile id {selected_profile_id!r}."
            )
        self.state.profile_library = profiles
        self.state.object_profile_mappings = dict(sorted(mappings.items()))
        if selected_profile_id:
            self.state.selected_profile_id = selected_profile_id
        applied = payload.get("applied_source_profile")
        self.state.applied_source_profile = (
            dict(applied) if isinstance(applied, Mapping) else {}
        )

    def _apply_rig_profile_config(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            raise ExtensionActionError(
                "microphone_rig_profiles config must be an object."
            )
        raw_library = payload.get("rig_library")
        if raw_library is None:
            raise ExtensionActionError(
                "microphone_rig_profiles.rig_library is required when rig "
                "profiles are present."
            )
        if not isinstance(raw_library, list | tuple):
            raise ExtensionActionError(
                "microphone_rig_profiles.rig_library must be a list of "
                "profile objects."
            )
        profiles = validate_microphone_rig_profile_library(
            microphone_rig_profile_from_mapping(item) for item in raw_library
        )
        profile_ids = {profile.profile_id for profile in profiles}
        selected_rig_id = payload.get("selected_rig_profile_id")
        selected_rig_id = (
            "" if selected_rig_id is None else str(selected_rig_id).strip()
        )
        if selected_rig_id and selected_rig_id not in profile_ids:
            raise ExtensionActionError(
                f"Unknown selected rig profile id {selected_rig_id!r}."
            )
        self.state.rig_profile_library = profiles
        if selected_rig_id:
            self.state.selected_rig_profile_id = selected_rig_id
        applied = payload.get("applied_array_rig_profile")
        self.state.applied_array_rig_profile = (
            dict(applied) if isinstance(applied, Mapping) else {}
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.state.status_message = message
        self.state.error_message = message if error else None
        if self._ui_window is not None:
            self._ui_window.refresh_labels()

    def _record_error(self, action: str, exc: BaseException) -> None:
        self._set_status(f"{action}: {exc}", error=True)


class OmniReferenceWindow:
    """Small adapter from ``ExtensionUiState`` to ``omni.ui`` widgets."""

    def __init__(self, controller: ExtensionController, ui: Any) -> None:
        self.controller = controller
        self.ui = ui
        self.window: Any | None = None
        self._string_fields: dict[str, Any] = {}
        self._float_fields: dict[str, Any] = {}
        self._int_fields: dict[str, Any] = {}
        self._bool_fields: dict[str, Any] = {}
        self._combo_fields: dict[str, tuple[Any, tuple[str, ...]]] = {}
        self._labels: dict[str, Any] = {}
        self._model_change_subscriptions: list[Any] = []
        self._sections: list[str] = []
        self._buttons: list[str] = []

    def build(self) -> Any:
        """Build a compact task-oriented Kit window."""

        ui = self.ui
        self.window = ui.Window(OMNI_WINDOW_TITLE, width=620, height=760)
        _set_window_visibility_changed_fn(
            self.window,
            self.controller._on_window_visibility_changed,
        )
        with self.window.frame:
            scrolling_frame = getattr(ui, "ScrollingFrame", None)
            if scrolling_frame is None:
                with ui.VStack(spacing=6):
                    self._build_body()
            else:
                with scrolling_frame(), ui.VStack(spacing=6, height=0):
                    self._build_body()
        self.refresh_labels()
        return self.window

    def _build_body(self) -> None:
        self._build_stage_section()
        self._build_array_section()
        self._build_source_section()
        self._build_control_section()
        self._build_replicator_section()
        self._build_export_section()
        self._labels["status"] = self.ui.Label(
            self.controller.state.status_message,
            word_wrap=True,
        )

    def refresh_labels(self) -> None:
        """Push current state summaries to visible labels."""

        state = self.controller.state
        self._set_label("stage", state.stage_status)
        self._set_label(
            "discovery",
            f"Arrays: {_summary_ids(state.discovered_arrays)} | "
            f"Sources: {_summary_ids(state.discovered_sources)} | "
            f"Objects: {_summary_ids(state.discovered_objects)}",
        )
        self._set_label(
            "object",
            "Object: "
            f"{state.object_label or 'none'} | "
            f"path={state.object_prim_path or 'none'} | "
            f"attached={state.source_attached_to_object} | "
            f"offset={_format_vec3(self.controller._source_local_offset_from_state())}",
        )
        self._set_label("profile", _profile_summary_text(state))
        self._set_label("rig_profile", _rig_profile_summary_text(state))
        self._set_label(
            "array_latest",
            "Array: "
            f"{state.latest_array_prim_path or state.array_prim_path} | "
            f"pos={_optional_vec3_text(state.latest_array_position_m)} | "
            f"quat={_optional_quat_text(state.latest_array_orientation_xyzw)} | "
            f"attached={state.array_attached_to_object} | "
            f"mics={_format_mic_positions_summary(state.latest_mic_world_positions)}",
        )
        self._set_label(
            "latest",
            "Frame: "
            f"{state.latest_frame_id or 'none'} | "
            f"detections={state.latest_detection_count} | "
            f"backend={state.latest_backend or state.backend} | "
            f"source={state.latest_source_prim_path or state.source_prim_path} | "
            f"pos={_optional_vec3_text(state.latest_source_position_m)} | "
            f"bearing={_optional_float_text(state.latest_bearing_deg)} | "
            f"sector={state.latest_sector or 'none'} | "
            f"rms={_format_rms_summary(state.latest_aggregate_rms)}",
        )
        self._set_label(
            "overlay",
            "Overlay: "
            f"{state.latest_overlay_primitive_count} primitive(s) | "
            f"{', '.join(state.latest_overlay_labels) or 'none'} | "
            f"{state.latest_overlay_status}",
        )
        self._set_label(
            "replicator",
            f"{state.replicator_status_message} | "
            f"latest={state.replicator_latest_write_path or 'none'}",
        )
        self._set_label("status", state.status_message)

    def sync_state_from_widgets(self) -> None:
        """Read widget models into the pure state before actions."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            setattr(state, attr_name, _model_string(widget.model))
        for attr_name, widget in self._float_fields.items():
            setattr(state, attr_name, _model_float(widget.model))
        for attr_name, widget in self._int_fields.items():
            setattr(state, attr_name, _model_int(widget.model))
        for attr_name, widget in self._bool_fields.items():
            setattr(state, attr_name, _model_bool(widget.model))
        for attr_name, (widget, choices) in self._combo_fields.items():
            index = _combo_index(widget.model)
            if 0 <= index < len(choices):
                setattr(state, attr_name, choices[index])

    def push_state_to_widgets(self) -> None:
        """Push state values into editable widgets after action-side updates."""

        state = self.controller.state
        for attr_name, widget in self._string_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, widget in self._float_fields.items():
            _set_model_value(
                widget.model, _format_edit_value(getattr(state, attr_name))
            )
        for attr_name, widget in self._int_fields.items():
            _set_model_value(
                widget.model, _format_edit_value(getattr(state, attr_name))
            )
        for attr_name, widget in self._bool_fields.items():
            _set_model_value(widget.model, getattr(state, attr_name))
        for attr_name, (widget, choices) in self._combo_fields.items():
            current = getattr(state, attr_name)
            if current in choices:
                _set_combo_index(widget.model, choices.index(current))

    def _build_stage_section(self) -> None:
        ui = self.ui
        with self._section("Stage"):
            self._labels["stage"] = ui.Label("", word_wrap=True)
            with ui.HStack(spacing=4):
                self._button(
                    "Refresh",
                    self.controller.refresh_stage_selection,
                )
                self._button(
                    "Use Array",
                    self.controller.use_selected_as_array,
                )
                self._button(
                    "Use Source",
                    self.controller.use_selected_as_source,
                )
                self._button(
                    "Use Object",
                    self.controller.use_selected_as_object,
                )
                self._button(
                    "Use Base",
                    self.controller.use_selected_as_robot_base,
                )
            self._string_row("Discovery Roots", "discovery_roots_text")
            self._string_row("Robot/Base", "robot_base_prim_path")
            self._string_row("Object", "object_prim_path")
            with self.ui.HStack(spacing=4):
                self._button(
                    "Create Demo Object",
                    self.controller.create_demo_object,
                )
            self._labels["object"] = ui.Label("", word_wrap=True)
            self._button(
                "Discover",
                self.controller.refresh_discovery,
            )
            self._labels["discovery"] = ui.Label("", word_wrap=True)

    def _build_array_section(self) -> None:
        ui = self.ui
        with self._section("Author Array"):
            self._string_row("Target Prim", "array_prim_path")
            self._string_row("Array ID", "array_id")
            self._combo_row("Layout", "layout_name", LAYOUT_CHOICES)
            self._int_row("Sample Rate", "sample_rate_hz")
            ui.Label(f"Convention: {self.controller.state.coordinate_convention}")
            self._bool_row("Child Mics", "author_child_microphones")
            self._button(
                "Create/Attach Array",
                self.controller.author_array,
            )
            self._string_row("Rig Profile ID", "selected_rig_profile_id")
            self._labels["rig_profile"] = ui.Label("", word_wrap=True)
            with ui.HStack(spacing=4):
                self._button(
                    "Select Rig Profile",
                    self.controller.select_rig_profile,
                )
                self._button(
                    "Apply Rig Profile",
                    self.controller.apply_selected_rig_profile,
                )
            self._float_row("Array Pos X", "array_position_x_m")
            self._float_row("Array Pos Y", "array_position_y_m")
            self._float_row("Array Pos Z", "array_position_z_m")
            self._float_row("Array Yaw", "array_yaw_deg")
            self._float_row("Array Pitch", "array_pitch_deg")
            self._float_row("Array Roll", "array_roll_deg")
            with ui.HStack(spacing=4):
                self._button(
                    "Read Array Transform",
                    self.controller.read_selected_array_transform,
                )
                self._button(
                    "Apply Array Pose",
                    self.controller.apply_array_pose,
                )
            self._float_row("Array Offset X", "array_local_offset_x_m")
            self._float_row("Array Offset Y", "array_local_offset_y_m")
            self._float_row("Array Offset Z", "array_local_offset_z_m")
            self._float_row("Array Local Yaw", "array_local_yaw_deg")
            self._float_row("Array Local Pitch", "array_local_pitch_deg")
            self._float_row("Array Local Roll", "array_local_roll_deg")
            with ui.HStack(spacing=4):
                self._button(
                    "Attach Array To Object",
                    self.controller.attach_array_to_object,
                )
                self._button(
                    "Detach Array",
                    self.controller.detach_array_from_object,
                )
            self._labels["array_latest"] = ui.Label("", word_wrap=True)

    def _build_source_section(self) -> None:
        with self._section("Author Source"):
            self._string_row("Target Prim", "source_prim_path")
            self._string_row("Source ID", "source_id")
            self._string_row("Class", "source_class_label")
            self._string_row("Audio URI", "audio_asset_path")
            self._string_row("Directivity", "source_directivity")
            self._string_row("Profile ID", "selected_profile_id")
            self._labels["profile"] = self.ui.Label("", word_wrap=True)
            with self.ui.HStack(spacing=4):
                self._button(
                    "Select Profile",
                    self.controller.select_sound_profile,
                )
                self._button(
                    "Auto From Object",
                    self.controller.auto_select_profile_from_object,
                )
                self._button(
                    "Apply Profile",
                    self.controller.apply_selected_profile,
                )
            self._float_row("Position X", "source_position_x_m")
            self._float_row("Position Y", "source_position_y_m")
            self._float_row("Position Z", "source_position_z_m")
            self._float_row("Local Offset X", "source_local_offset_x_m")
            self._float_row("Local Offset Y", "source_local_offset_y_m")
            self._float_row("Local Offset Z", "source_local_offset_z_m")
            with self.ui.HStack(spacing=4):
                self._button(
                    "Read Selected Transform",
                    self.controller.read_selected_source_transform,
                )
                self._button(
                    "Apply Position",
                    self.controller.apply_source_position,
                )
            with self.ui.HStack(spacing=4):
                self._button(
                    "Front",
                    lambda: self.controller.apply_source_position_preset("front"),
                )
                self._button(
                    "Right",
                    lambda: self.controller.apply_source_position_preset("right"),
                )
                self._button(
                    "Left",
                    lambda: self.controller.apply_source_position_preset("left"),
                )
                self._button(
                    "Behind",
                    lambda: self.controller.apply_source_position_preset("behind"),
                )
            self._float_row("Start", "source_start_time_s")
            self._float_row("Duration", "source_duration_s")
            self._float_row("Gain dB", "source_gain_db")
            self._button(
                "Create/Attach Source",
                self.controller.author_source,
            )
            with self.ui.HStack(spacing=4):
                self._button(
                    "Attach Source To Object",
                    self.controller.attach_source_to_object,
                )
                self._button(
                    "Detach Source",
                    self.controller.detach_source_from_object,
                )

    def _build_control_section(self) -> None:
        ui = self.ui
        with self._section("Sensor"):
            self._combo_row("Backend", "backend", BACKEND_CHOICES)
            self._combo_row("Ambiguity", "ambiguity_policy", AMBIGUITY_POLICY_CHOICES)
            self._float_row("Period s", "update_period_s")
            self._int_row("Max Events", "max_events")
            self._bool_row("Overlay", "debug_overlay_enabled")
            self._bool_row("JSONL", "trace_enabled")
            self._string_row("Writer Path", "jsonl_trace_path")
            with ui.HStack(spacing=4):
                self._button(
                    "Start",
                    self.controller.start_sensor,
                )
                self._button("Stop", self.controller.stop_sensor)
                self._button(
                    "Update",
                    self.controller.update_sensor,
                )
            self._labels["latest"] = ui.Label("", word_wrap=True)
            self._labels["overlay"] = ui.Label("", word_wrap=True)

    def _build_replicator_section(self) -> None:
        ui = self.ui
        with self._section("Replicator"):
            self._bool_row("Enable", "replicator_enabled")
            self._string_row("Output Dir", "replicator_output_dir")
            self._string_row("Writer", "replicator_writer_name")
            self._string_row("Annotator", "replicator_annotator_name")
            with ui.HStack(spacing=4):
                self._button(
                    "Start",
                    self.controller.start_replicator,
                )
                self._button(
                    "Flush",
                    self.controller.flush_replicator,
                )
                self._button(
                    "Stop",
                    self.controller.stop_replicator,
                )
            self._labels["replicator"] = ui.Label("", word_wrap=True)

    def _build_export_section(self) -> None:
        ui = self.ui
        with self._section("Export"):
            self._string_row("Latest JSON", "latest_frame_export_path")
            self._string_row("Config JSON", "config_export_path")
            self._string_row("Load Config", "config_import_path")
            with ui.HStack(spacing=4):
                self._button(
                    "Export Latest",
                    self.controller.export_latest_frame,
                )
                self._button(
                    "Export Config",
                    self.controller.export_config_summary,
                )
                self._button(
                    "Load Config",
                    self.controller.import_config_summary,
                )

    @contextmanager
    def _section(self, title: str) -> Any:
        self._sections.append(title)
        frame_type = getattr(self.ui, "CollapsableFrame", None)
        if frame_type is None:
            with self.ui.VStack(spacing=4) as stack:
                yield stack
            return
        frame = frame_type(title, collapsed=False, height=0)
        with frame, self.ui.VStack(spacing=4, height=0) as stack:
            yield stack

    def _string_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                str(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_string(model),
                ),
            )
            self._string_fields[attr_name] = widget

    def _float_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                _format_edit_value(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_float_state(
                    name,
                    model,
                ),
            )
            self._float_fields[attr_name] = widget

    def _int_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "string",
                _format_edit_value(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.StringField(
                model=model,
                width=_ui_fraction(self.ui, 1),
                height=0,
                read_only=False,
            )
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: self._try_update_int_state(name, model),
            )
            self._int_fields[attr_name] = widget

    def _bool_row(self, label: str, attr_name: str) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            model = _new_simple_model(
                self.ui,
                "bool",
                bool(getattr(self.controller.state, attr_name)),
            )
            widget = self.ui.CheckBox(model=model)
            self._bind_model_change(
                widget.model,
                lambda model, name=attr_name: setattr(
                    self.controller.state,
                    name,
                    _model_bool(model),
                ),
            )
            self._bool_fields[attr_name] = widget

    def _combo_row(
        self,
        label: str,
        attr_name: str,
        choices: tuple[str, ...],
    ) -> None:
        with self.ui.HStack(spacing=4):
            self.ui.Label(label, width=120)
            current = getattr(self.controller.state, attr_name)
            index = choices.index(current) if current in choices else 0
            widget = self.ui.ComboBox(index, *choices, width=220)
            self._combo_fields[attr_name] = (widget, choices)

            def _on_changed(model: Any, _item: Any = None) -> None:
                selected = _combo_index(model)
                if 0 <= selected < len(choices):
                    setattr(self.controller.state, attr_name, choices[selected])

            if hasattr(widget.model, "add_item_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_item_changed_fn(_on_changed)
                )
            if hasattr(widget.model, "add_value_changed_fn"):
                self._model_change_subscriptions.append(
                    widget.model.add_value_changed_fn(_on_changed)
                )

    def _button(self, label: str, callback: Callable[..., Any]) -> Any:
        self._buttons.append(label)
        return self.ui.Button(label, clicked_fn=self._action(callback))

    def _action(self, callback: Callable[..., Any]) -> Callable[[], None]:
        def _wrapped() -> None:
            try:
                self.sync_state_from_widgets()
            except Exception as exc:
                self.controller._record_error("UI input failed", exc)
                self.refresh_labels()
                return
            callback()
            self.push_state_to_widgets()
            self.refresh_labels()

        return _wrapped

    def _bind_model_change(
        self,
        model: Any,
        callback: Callable[[Any], None],
    ) -> None:
        if hasattr(model, "add_value_changed_fn"):
            self._model_change_subscriptions.append(
                model.add_value_changed_fn(callback)
            )

    def _try_update_float_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_float(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)

    def _try_update_int_state(self, attr_name: str, model: Any) -> None:
        try:
            value = _model_int(model)
        except (TypeError, ValueError):
            return
        setattr(self.controller.state, attr_name, value)

    def _set_label(self, name: str, text: str) -> None:
        label = self._labels.get(name)
        if label is None:
            return
        if hasattr(label, "text"):
            label.text = text
            return
        if hasattr(label, "model"):
            _set_model_value(label.model, text)


def current_omni_stage_context() -> CurrentStageContext:
    """Return the live Omni stage and selected prims through lazy imports."""

    try:
        omni_usd = importlib.import_module("omni.usd")
    except ImportError as exc:
        raise ExtensionActionError(
            "omni.usd is unavailable; load this extension inside Isaac Sim "
            "or pass an explicit stage in tests."
        ) from exc
    if not hasattr(omni_usd, "get_context"):
        raise ExtensionActionError("omni.usd.get_context is unavailable.")
    context = omni_usd.get_context()
    stage = context.get_stage() if hasattr(context, "get_stage") else None
    selected_paths: tuple[str, ...] = ()
    if hasattr(context, "get_selection"):
        selection = context.get_selection()
        if hasattr(selection, "get_selected_prim_paths"):
            selected_paths = _normalize_paths(selection.get_selected_prim_paths())
    return CurrentStageContext(stage=stage, selected_prim_paths=selected_paths)


def _stage_has_prim(stage: Any, path: str) -> bool:
    if not path:
        return False
    if hasattr(stage, "GetPrimAtPath"):
        for candidate_path in (_usd_path(path), path):
            try:
                prim = stage.GetPrimAtPath(candidate_path)
            except TypeError:
                continue
            if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
                return True
    if hasattr(stage, "Traverse"):
        return any(prim_path(prim) == path for prim in stage.Traverse())
    return False


def _stage_prim_at_path(stage: Any | None, path: str) -> Any | None:
    if stage is None or not path:
        return None
    if hasattr(stage, "GetPrimAtPath"):
        for candidate_path in (_usd_path(path), path):
            try:
                prim = stage.GetPrimAtPath(candidate_path)
            except TypeError:
                continue
            if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
                return prim
    if hasattr(stage, "Traverse"):
        for prim in stage.Traverse():
            if prim_path(prim) == path:
                return prim
    return None


def _usd_path(path: str) -> Any:
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return path
    try:
        return Sdf.Path(path)
    except Exception:
        return path


def _prim_has_pose(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(
        key in attrs
        for key in (
            "ias:position_world",
            "xformOp:translate",
            "usd_world_position",
        )
    )


def _author_position_arg(
    prim: Any,
    *,
    default: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    attrs = _prim_attrs(prim)
    if _prim_has_xform_pose(prim):
        return None
    if "ias:position_world" in attrs:
        try:
            return vec3_from_any(attrs["ias:position_world"])
        except (TypeError, ValueError):
            pass
    return default


def _author_orientation_arg(
    prim: Any,
    *,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    attrs = _prim_attrs(prim)
    if _prim_has_xform_orientation(prim):
        return None
    if "ias:orientation_world_quat" in attrs:
        try:
            return quat_from_any(attrs["ias:orientation_world_quat"])
        except (TypeError, ValueError):
            pass
    return default


def _prim_has_xform_pose(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(key in attrs for key in ("xformOp:translate", "usd_world_position"))


def _prim_has_xform_orientation(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(key in attrs for key in ("xformOp:orient", "usd_world_orientation"))


def _prim_has_orientation(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(
        key in attrs
        for key in (
            "ias:orientation_world_quat",
            "xformOp:orient",
            "usd_world_orientation",
        )
    )


def _prim_attrs(prim: Any) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = attr.Get()
    return attrs


def _set_prim_attr(prim: Any, name: str, value: Any) -> None:
    if hasattr(prim, "attributes"):
        prim.attributes[name] = value
        return
    if not hasattr(prim, "CreateAttribute"):
        return
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return
    value_type = getattr(Sdf.ValueTypeNames, "String", None)
    if isinstance(value, bool):
        value_type = getattr(Sdf.ValueTypeNames, "Bool", value_type)
    elif isinstance(value, float):
        value_type = getattr(Sdf.ValueTypeNames, "Double", value_type)
    try:
        attr = prim.CreateAttribute(name, value_type)
        if hasattr(attr, "Set"):
            attr.Set(value)
    except Exception:
        return


def _refresh_applied_profile_binding_snapshot(
    prim: Any,
    state: ExtensionUiState,
    *,
    object_path: str,
    local_offset_m: tuple[float, float, float],
) -> dict[str, object]:
    if not state.applied_source_profile:
        return {}
    profile_id = str(state.applied_source_profile.get("profile_id") or "")
    display_label = str(state.applied_source_profile.get("display_label") or "")
    attrs: dict[str, object] = {}
    if profile_id:
        _set_prim_attr(prim, "ias:sound_profile_id", profile_id)
        attrs["ias:sound_profile_id"] = profile_id
    if display_label:
        _set_prim_attr(prim, "ias:sound_profile_label", display_label)
        attrs["ias:sound_profile_label"] = display_label
    state.applied_source_profile = _json_ready(
        {
            **state.applied_source_profile,
            "source_prim_path": state.source_prim_path,
            "source_id": state.source_id,
            "class_label": state.source_class_label,
            "audio_asset_path": state.audio_asset_path,
            "start_time_s": state.source_start_time_s,
            "duration_s": state.source_duration_s,
            "gain_db": state.source_gain_db,
            "directivity": state.source_directivity,
            "source_attached_to_object": True,
            "object_prim_path": object_path,
            "object_label": state.object_label,
            "attached_object_prim_path": object_path,
            "source_local_offset_m": local_offset_m,
        }
    )
    attrs["applied_source_profile"] = state.applied_source_profile
    return attrs


def _object_label_candidates_for_path(stage: Any | None, path: str) -> tuple[str, ...]:
    if not path:
        return ()
    labels: list[str] = []
    prim = _stage_prim_at_path(stage, path)
    attrs = {} if prim is None else _prim_attrs(prim)
    for attr_name in (
        "ias:object_label",
        "semantic:class",
        "semantics:class",
        "semantics:semanticType",
        "primvars:displayName",
        "displayName",
        "label",
    ):
        value = attrs.get(attr_name)
        if value is not None:
            labels.append(str(value))
    labels.append(_path_name(path))
    return tuple(labels)


def _normalize_paths(paths: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for path in paths:
        path_string = getattr(path, "pathString", None)
        normalized.append(str(path_string if path_string is not None else path))
    return tuple(path for path in normalized if path)


def _validate_abs_path(path: str, field_name: str) -> None:
    if not path.strip() or not path.startswith("/"):
        raise ExtensionActionError(f"{field_name} must be an absolute USD prim path.")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _jsonable_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_ready(value) for key, value in sorted(mapping.items())}


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(value[key]) for key in sorted(value)}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _authored_metadata_from_dict(value: Any) -> AuthoredMetadataSummary:
    if not isinstance(value, Mapping):
        raise ExtensionActionError("authored_metadata entries must be objects.")
    return AuthoredMetadataSummary(
        kind=str(value.get("kind", "")),
        prim_path=str(value.get("prim_path", "")),
        id=str(value.get("id", "")),
        attributes=_jsonable_mapping(dict(value.get("attributes", {}))),
    )


def _discovered_summary_from_dict(value: Any) -> DiscoveredPrimSummary:
    if not isinstance(value, Mapping):
        raise ExtensionActionError("discovered object entries must be objects.")
    return DiscoveredPrimSummary(
        id=str(value.get("id", "")),
        prim_path=str(value.get("prim_path", "")),
        reasons=tuple(str(reason) for reason in value.get("reasons", ())),
    )


def _discover_scene_objects(
    stage: Any,
    *,
    roots: tuple[str, ...],
    excluded_paths: tuple[str, ...],
) -> tuple[DiscoveredPrimSummary, ...]:
    if not hasattr(stage, "Traverse"):
        return ()
    normalized_roots = tuple(root.rstrip("/") for root in roots if root.strip())
    excluded = tuple(path.rstrip("/") for path in excluded_paths if path.strip())
    objects: list[DiscoveredPrimSummary] = []
    for prim in sorted(stage.Traverse(), key=prim_path):
        path = prim_path(prim)
        if not path or path == "/World":
            continue
        if normalized_roots and not any(
            path == root or path.startswith(f"{root}/") for root in normalized_roots
        ):
            continue
        if any(path == item or path.startswith(f"{item}/") for item in excluded):
            continue
        attrs = _prim_attrs(prim)
        type_name = _prim_type_name(prim)
        if _is_audio_metadata_prim(type_name, attrs):
            continue
        if not _looks_like_scene_object(path, type_name, attrs):
            continue
        objects.append(
            DiscoveredPrimSummary(
                id=_path_name(path),
                prim_path=path,
                reasons=(f"type:{type_name or 'unknown'}",),
            )
        )
    return tuple(objects)


def _get_or_define_demo_object_prim(stage: Any, prim_path: str) -> Any:
    prim = get_or_define_prim(stage, prim_path=prim_path, prim_type="Cube")
    if hasattr(prim, "type_name"):
        prim.type_name = "Cube"
        return prim
    set_type_name = getattr(prim, "SetTypeName", None)
    if callable(set_type_name):
        with suppress(Exception):
            set_type_name("Cube")
    return prim


def _style_demo_object_prim(
    stage: Any,
    *,
    prim: Any,
    position_world: tuple[float, float, float],
) -> None:
    if hasattr(prim, "attributes"):
        prim.attributes.setdefault("xformOp:translate", position_world)
        prim.attributes["size"] = 0.9
        prim.attributes["displayColor"] = (0.95, 0.48, 0.08)
        prim.attributes["displayOpacity"] = 1.0
        prim.attributes["doubleSided"] = True
        light = get_or_define_prim(
            stage,
            prim_path="/World/KeyLight",
            prim_type="DistantLight",
        )
        if hasattr(light, "attributes"):
            light.attributes["inputs:intensity"] = 750.0
            light.attributes["inputs:angle"] = 0.35
        dome = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectDomeLight",
            prim_type="DomeLight",
        )
        if hasattr(dome, "attributes"):
            dome.attributes["inputs:intensity"] = 450.0
            dome.attributes["inputs:color"] = (1.0, 0.92, 0.82)
        fill = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectFillLight",
            prim_type="SphereLight",
        )
        if hasattr(fill, "attributes"):
            fill.attributes["inputs:intensity"] = 1800.0
            fill.attributes["inputs:radius"] = 3.0
            fill.attributes["xformOp:translate"] = (-3.0, -4.0, 3.0)
        return
    try:
        from pxr import Gf, UsdGeom, UsdLux  # type: ignore

        cube = UsdGeom.Cube(prim)
        cube.CreateSizeAttr(0.9)
        gprim = UsdGeom.Gprim(prim)
        gprim.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.48, 0.08)])
        gprim.CreateDisplayOpacityAttr([1.0])
        gprim.CreateDoubleSidedAttr(True)
        light_prim = get_or_define_prim(
            stage,
            prim_path="/World/KeyLight",
            prim_type="DistantLight",
        )
        light = UsdLux.DistantLight(light_prim)
        light.CreateIntensityAttr(750.0)
        light.CreateAngleAttr(0.35)
        set_prim_xform_pose(light_prim, position=(0.0, -3.0, 5.0))
        dome_prim = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectDomeLight",
            prim_type="DomeLight",
        )
        dome = UsdLux.DomeLight(dome_prim)
        dome.CreateIntensityAttr(450.0)
        dome.CreateColorAttr(Gf.Vec3f(1.0, 0.92, 0.82))
        fill_prim = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectFillLight",
            prim_type="SphereLight",
        )
        fill = UsdLux.SphereLight(fill_prim)
        fill.CreateIntensityAttr(1800.0)
        fill.CreateRadiusAttr(3.0)
        set_prim_xform_pose(fill_prim, position=(-3.0, -4.0, 3.0))
    except Exception:
        return


def _is_audio_metadata_prim(type_name: str, attrs: Mapping[str, Any]) -> bool:
    if type_name in {
        "Sound",
        "AudioSource",
        "OmniAudioSource",
        "Microphone",
        "Listener",
    }:
        return True
    return any(
        key in attrs
        for key in (
            "ias:source_id",
            "ias:class_label",
            "ias:array_id",
            "ias:microphone_id",
            "filePath",
            "inputs:file",
            "inputs:audio",
        )
    )


def _looks_like_scene_object(
    path: str,
    type_name: str,
    attrs: Mapping[str, Any],
) -> bool:
    name = _path_name(path)
    if name in {"World", "Rig", "Sources"}:
        return False
    if type_name in {"Xform", "Mesh", "Cube", "Sphere", "Cylinder", "Capsule"}:
        return True
    return any(key.startswith("xformOp:") for key in attrs)


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))


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
    library_ids = ", ".join(
        profile.profile_id for profile in state.rig_profile_library
    )
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


def _optional_float_text(value: float | None) -> str:
    return "none" if value is None else f"{value:.2f}"


def _optional_vec3_text(value: tuple[float, float, float] | None) -> str:
    return "none" if value is None else _format_vec3(value)


def _format_rms_summary(values: Mapping[str, float]) -> str:
    if not values:
        return "none"
    order = {"front": 0, "right": 1, "rear": 2, "left": 3}
    items = sorted(values.items(), key=lambda item: (order.get(item[0], 99), item[0]))
    return ", ".join(f"{mic_id}:{_format_rms_value(value)}" for mic_id, value in items)


def _format_rms_value(value: float) -> str:
    if value != 0.0 and abs(value) < 0.01:
        return f"{value:.2e}"
    return f"{value:.2f}"


def _format_vec3(value: Iterable[float]) -> str:
    x, y, z = vec3_from_any(value)
    return f"({x:.2f}, {y:.2f}, {z:.2f})"


def _new_simple_model(ui: Any, kind: str, value: Any) -> Any:
    model_type_name = {
        "bool": "SimpleBoolModel",
        "float": "SimpleFloatModel",
        "int": "SimpleIntModel",
        "string": "SimpleStringModel",
    }[kind]
    model_type = getattr(ui, model_type_name, None)
    if model_type is None:
        return None
    try:
        return model_type(value)
    except TypeError:
        model = model_type()
        _set_model_value(model, value)
        return model


def _ui_fraction(ui: Any, value: int) -> Any:
    fraction = getattr(ui, "Fraction", None)
    if fraction is None:
        return value
    try:
        return fraction(value)
    except Exception:
        return value


def _format_edit_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _set_model_value(model: Any, value: Any) -> None:
    if model is None:
        return
    if hasattr(model, "set_value"):
        model.set_value(value)


def _set_combo_index(model: Any, index: int) -> None:
    if model is None:
        return
    if hasattr(model, "get_item_value_model"):
        item_model = model.get_item_value_model()
        if item_model is not None:
            _set_model_value(item_model, index)
            return
    _set_model_value(model, index)


def _model_string(model: Any) -> str:
    if model is None:
        return ""
    if hasattr(model, "get_value_as_string"):
        return str(model.get_value_as_string())
    if hasattr(model, "as_string"):
        return str(model.as_string)
    return str(getattr(model, "value", ""))


def _model_float(model: Any) -> float:
    text = _model_string(model).strip()
    if text != "":
        return float(text)
    get_value = getattr(model, "get_value_as_float", None)
    if callable(get_value):
        try:
            return float(get_value())
        except (TypeError, ValueError):
            pass
    try:
        as_float = model.as_float
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        try:
            return float(as_float)
        except (TypeError, ValueError):
            pass
    raise ValueError("empty numeric value")


def _model_int(model: Any) -> int:
    text = _model_string(model).strip()
    if text != "":
        return int(float(text))
    get_value = getattr(model, "get_value_as_int", None)
    if callable(get_value):
        try:
            return int(get_value())
        except (TypeError, ValueError):
            pass
    try:
        as_int = model.as_int
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        try:
            return int(as_int)
        except (TypeError, ValueError):
            pass
    raise ValueError("empty integer value")


def _model_bool(model: Any) -> bool:
    if hasattr(model, "get_value_as_bool"):
        return bool(model.get_value_as_bool())
    if hasattr(model, "as_bool"):
        return bool(model.as_bool)
    return bool(getattr(model, "value", False))


def _combo_index(model: Any) -> int:
    if hasattr(model, "get_item_value_model"):
        value_model = model.get_item_value_model()
        try:
            as_int = value_model.as_int
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            return int(as_int)
        get_value = getattr(value_model, "get_value_as_int", None)
        if callable(get_value):
            return int(get_value())
    return _model_int(model)


def _window_visible(window: Any | None) -> bool:
    if window is None:
        return False
    visible = getattr(window, "visible", None)
    if visible is None:
        return True
    return bool(visible)


def _set_window_visible(window: Any, visible: bool) -> bool:
    try:
        window.visible = visible
        return True
    except Exception:
        pass
    method_name = "show" if visible else "hide"
    method = getattr(window, method_name, None)
    if callable(method):
        try:
            method()
            return True
        except Exception:
            return False
    return False


def _focus_window(window: Any) -> None:
    for method_name in ("focus", "bring_to_front"):
        method = getattr(window, method_name, None)
        if callable(method):
            with suppress(Exception):
                method()
            return


def _set_window_visibility_changed_fn(
    window: Any,
    callback: Callable[[bool], None],
) -> None:
    setter = getattr(window, "set_visibility_changed_fn", None)
    if not callable(setter):
        return
    with suppress(Exception):
        setter(callback)


def _normalize_hotkey_setting(value: str) -> str:
    normalized = value.strip()
    if normalized.lower() in {"", "none", "disabled", "off", "false"}:
        return ""
    return normalized


__all__ = [
    "AMBIGUITY_POLICY_CHOICES",
    "BACKEND_CHOICES",
    "LAYOUT_CHOICES",
    "SOURCE_POSITION_PRESETS",
    "AuthoredMetadataSummary",
    "CurrentStageContext",
    "DiscoveredPrimSummary",
    "ExtensionActionError",
    "ExtensionController",
    "ExtensionUiState",
    "OmniReferenceWindow",
    "current_omni_stage_context",
]
