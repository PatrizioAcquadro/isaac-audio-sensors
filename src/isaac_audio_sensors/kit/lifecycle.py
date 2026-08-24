"""Internal lifecycle service."""

from __future__ import annotations

import importlib
from contextlib import suppress
from typing import Any

from isaac_audio_sensors.isaac.lifecycle import subscribe_to_updates
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
)

from ._service import ControllerService
from .constants import (
    OMNI_ACTION_TOGGLE_WINDOW,
    OMNI_DEFAULT_HOTKEY,
    OMNI_DEFAULT_HOTKEY_DISPLAY,
    OMNI_MENU_GROUP,
    OMNI_WINDOW_TITLE,
)
from .formatting import (
    _vec_close,
)
from .ui_models import (
    _focus_window,
    _normalize_hotkey_setting,
    _set_window_visible,
    _window_visible,
)
from .window import OmniReferenceWindow


class LifecycleService(ControllerService):
    """Own lifecycle behavior."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self.ext_id = None
        self.window = None
        self.ui_available = False
        self._ui_window = None
        self.action_status = "Kit action not registered."
        self.menu_status = "Kit menu not registered."
        self.hotkey_status = "Kit hotkey not registered."
        self._registered_action = None
        self._registered_hotkey = None
        self._registered_hotkey_key = None
        self._controller_update_subscription = None
        self._menu_items = []
        self._stage_event_subscription = None
        self._simulation_reset_callback_id = None
        self._last_followed_selection = None

    def on_startup(self, ext_id: str) -> None:
        """Initialize the import-safe controller and lazily build Kit UI."""

        self._validation.invalidate("extension startup")
        self.ext_id = ext_id
        self._set_status(f"Loaded {ext_id}.")
        self.build_ui_if_available()
        self.register_kit_integrations()

    def on_shutdown(self) -> None:
        """Release every owned resource even when one cleanup fails."""

        failures: list[str] = []
        recording = vars(self._host._recording).get("_guided_recorder")
        workflow = vars(self._host._recording).get("_guided_workflow")
        cleanups = (
            ("recording", self.guided_cancel_recording if recording else None),
            ("Kit audio", self.cleanup_kit_audio),
            ("audition", self.stop_audition),
            ("Replicator", self.stop_replicator),
            ("USD debug", self.clear_usd_debug_geometry),
            ("sensor", self.close_sensor),
            ("reset callback", self._unregister_simulation_reset_callback),
            ("stage subscription", self._unregister_stage_event_subscription),
            ("update subscription", self._stop_controller_update_subscription),
            ("hotkey", self._unregister_hotkey),
            ("menu", self._unregister_menu),
            ("action", self._unregister_action),
            ("window", None if self._ui_window is None else self._ui_window.close),
        )
        if workflow is not None:
            workflow.on_change = None
        for name, cleanup in cleanups:
            if cleanup is None:
                continue
            try:
                cleanup()
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        self._ui_window = None
        self.window = None
        self.ui_available = False
        self.ext_id = None
        self._set_status(
            "Shutdown complete."
            if not failures
            else "Shutdown completed with cleanup errors: " + "; ".join(failures),
            error=bool(failures),
        )

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
            self._ui_window = OmniReferenceWindow(self._host, ui)
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
        self._register_stage_event_subscription()
        self._register_simulation_reset_callback()

    def unregister_kit_integrations(self) -> None:
        """Best-effort cleanup of Kit action/menu/hotkey registrations."""

        self._unregister_simulation_reset_callback()
        self._unregister_stage_event_subscription()
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

    def _start_controller_update_subscription(self) -> None:
        def _on_update(_event: Any) -> None:
            self._viewport_follow_tick()
            if self.sensor is None or not self.state.sensor_running:
                return
            frame = self.update_sensor(force=False)
            if frame is not None and self._ui_window is not None:
                self._ui_window.refresh_labels()

        self._controller_update_subscription = subscribe_to_updates(
            _on_update,
            name="isaac_audio_sensors.kit.update",
        )

    def _stop_controller_update_subscription(self) -> None:
        self._controller_update_subscription = None

    def _register_stage_event_subscription(self) -> None:
        """Follow viewport selection through omni.usd stage events when present."""

        try:
            import omni.usd  # type: ignore
        except ImportError:
            self._stage_event_subscription = None
            return
        try:
            context = omni.usd.get_context()
            stream = context.get_stage_event_stream()
            selection_changed = int(omni.usd.StageEventType.SELECTION_CHANGED)
            stage_change_types = {
                int(event_type): name.lower()
                for name in ("OPENING", "OPENED", "CLOSING", "CLOSED")
                if (event_type := getattr(omni.usd.StageEventType, name, None))
                is not None
            }

            def _on_stage_event(event: Any) -> None:
                event_type = int(getattr(event, "type", -1))
                stage_change = stage_change_types.get(event_type)
                if stage_change is not None:
                    self.cleanup_kit_audio(reason=f"USD stage {stage_change}")
                    self._validation.invalidate(f"USD stage {stage_change}")
                    return
                if event_type != selection_changed:
                    return
                self._handle_viewport_selection_changed()

            self._stage_event_subscription = stream.create_subscription_to_pop(
                _on_stage_event,
                name="isaac_audio_sensors.kit.stage_events",
            )
        except Exception:
            self._stage_event_subscription = None

    def _unregister_stage_event_subscription(self) -> None:
        self._stage_event_subscription = None

    def _register_simulation_reset_callback(self) -> None:
        """Subscribe to the Isaac World post-reset lifecycle when available."""

        self._unregister_simulation_reset_callback()
        try:
            simulation = importlib.import_module("isaacsim.core.simulation_manager")
            manager = simulation.SimulationManager
            event = simulation.IsaacEvents.POST_RESET
            self._simulation_reset_callback_id = manager.register_callback(
                self._handle_simulation_reset,
                event=event,
            )
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
            self._simulation_reset_callback_id = None

    def _unregister_simulation_reset_callback(self) -> None:
        callback_id = self._simulation_reset_callback_id
        self._simulation_reset_callback_id = None
        if callback_id is None:
            return
        try:
            simulation = importlib.import_module("isaacsim.core.simulation_manager")
            simulation.SimulationManager.deregister_callback(callback_id)
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
            pass

    def _viewport_follow_tick(self) -> None:
        """Per-tick fallback when stage events are unavailable, plus pose sync."""

        if (
            self._stage_event_subscription is None
            and self.state.follow_viewport_selection
        ):
            self._handle_viewport_selection_changed()
        self._live_sync_pose_tick()

    def _handle_viewport_selection_changed(self) -> None:
        try:
            context = self._context()
        except Exception:
            return
        selection = tuple(context.selected_prim_paths)
        if selection == self._last_followed_selection:
            return
        self._last_followed_selection = selection
        self.state.selected_prim_paths = selection
        if not self.state.follow_viewport_selection or not selection:
            return
        self._adopt_viewport_selection(selection[0], stage=context.stage)
        if self._ui_window is not None:
            self._ui_window.push_state_to_widgets()
            self._ui_window.refresh_labels()

    def _adopt_viewport_selection(self, path: str, *, stage: Any | None) -> None:
        """Route a selected prim to the matching target field via discovery."""

        if any(item.prim_path == path for item in self.state.discovered_arrays):
            self.state.array_prim_path = path
            self._set_status(f"Viewport selection adopted as array: {path}")
            return
        if any(item.prim_path == path for item in self.state.discovered_sources):
            self.state.source_prim_path = path
            self._set_status(f"Viewport selection adopted as source: {path}")
            return
        self.use_selected_as_object(stage=stage, selected_paths=(path,))

    def _live_sync_pose_tick(self) -> None:
        """Mirror manipulator-driven prim poses into the numeric fields."""

        state = self.state
        if not (state.live_sync_array_pose or state.live_sync_source_pose):
            return
        try:
            context = self._context()
        except Exception:
            return
        if context.stage is None:
            return
        changed = False
        if state.live_sync_source_pose and state.source_prim_path.strip():
            changed = self._sync_source_pose_from_prim(context.stage) or changed
        if state.live_sync_array_pose and state.array_prim_path.strip():
            changed = self._sync_array_pose_from_prim(context.stage) or changed
        if changed and self._ui_window is not None:
            self._ui_window.push_state_to_widgets()
            self._ui_window.refresh_labels()

    def _sync_source_pose_from_prim(self, stage: Any) -> bool:
        try:
            pose = IsaacStagePoseResolver(stage).resolve_world_pose(
                self.state.source_prim_path,
                field_name="live source",
            )
        except Exception:
            return False
        position = tuple(float(value) for value in pose.position_world)
        if _vec_close(self._source_position_from_state(), position):
            return False
        self._set_source_position_state(position)
        return True

    def _sync_array_pose_from_prim(self, stage: Any) -> bool:
        try:
            pose = IsaacStagePoseResolver(stage).resolve_world_pose(
                self.state.array_prim_path,
                field_name="live array",
            )
        except Exception:
            return False
        position = tuple(float(value) for value in pose.position_world)
        orientation = tuple(
            float(value)
            for value in (pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0))
        )
        if _vec_close(self._array_position_from_state(), position) and _vec_close(
            self._array_orientation_from_state(), orientation
        ):
            return False
        self._set_array_pose_state(position, orientation)
        return True
