"""Kit Audio listener audition and qualitative device-mix capture."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.isaac.pose_resolver import prim_path, prim_type_name
from isaac_audio_sensors.isaac.stage_audio import (
    create_listener_prim,
    remove_prim,
)

from ._service import ControllerService
from .constants import DEFAULT_KIT_AUDIO_CAPTURE_DIRNAME
from .paths import _resolve_gui_output_path
from .state import ExtensionActionError

_ACTIVATION_ATTEMPTS = 3
_CAPTURE_WAIT_MS = 3_000
_TEMP_LISTENER_NAME = "IasKitAudioListener"


@dataclass(frozen=True, slots=True)
class KitMixCaptureSummary:
    """Verified facts read back from one captured Kit device-mix WAV."""

    path: Path
    channel_count: int
    sample_rate_hz: int
    duration_s: float
    peak: float


class KitAudioService(ControllerService):
    """Own one optional Kit listener bridge and one capture streamer."""

    def __init__(
        self,
        host: object,
        *,
        audio_interface_provider: Callable[[], Any] | None = None,
        next_update_async: Callable[[], Awaitable[Any]] | None = None,
        invalid_streamer_id: int | None = None,
    ) -> None:
        super().__init__(host)
        self._audio_interface_provider = (
            audio_interface_provider or _default_audio_interface
        )
        self._next_update_async = next_update_async or _default_next_update
        self._invalid_streamer_id = (
            (2**64) - 1 if invalid_streamer_id is None else invalid_streamer_id
        )
        self._stage = None
        self._audio = None
        self._listener = None
        self._previous_listener = None
        self._created_listener_path = None
        self._streamer_id = None
        self._capture_path = None
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._operation_pending = False

    def activate_listener(self, *, stage: Any | None = None) -> Any:
        """Activate the array listener without controlling the timeline."""

        return self._run_async_action(
            self.activate_listener_async(stage=stage),
            pending_status="Kit listener activation pending.",
        )

    async def activate_listener_async(self, *, stage: Any | None = None) -> str | None:
        if self._operation_pending:
            self._record_error(
                "Kit listener activation failed",
                ExtensionActionError("Another Kit Audio action is still pending."),
            )
            return None
        self._operation_pending = True
        try:
            listener = await self._activate_listener(stage=stage)
            path = prim_path(listener)
            self.state.kit_listener_prim_path = path
            self.state.kit_listener_status = f"Kit listener active at {path}."
            self._set_status(self.state.kit_listener_status)
            return path
        except Exception as exc:
            self.state.kit_listener_status = f"Kit listener activation failed: {exc}"
            self._record_error("Kit listener activation failed", exc)
            return None
        finally:
            self._operation_pending = False

    def restore_listener(self) -> bool:
        """Restore the previous listener unless the user selected another one."""

        self._cancel_pending_tasks()
        if self.state.kit_mix_capture_running:
            exc = ExtensionActionError(
                "Stop Kit Mix Capture before restoring listener."
            )
            self._record_error("Kit listener restore failed", exc)
            return False
        try:
            restored = self._restore_listener(remove_created=True)
            self._set_status(self.state.kit_listener_status)
            return restored
        except Exception as exc:
            self._record_error("Kit listener restore failed", exc)
            return False

    def start_mix_capture(self, *, stage: Any | None = None) -> Any:
        """Start one owned Kit listener/device-mix capture streamer."""

        return self._run_async_action(
            self.start_mix_capture_async(stage=stage),
            pending_status="Kit mix capture start pending.",
        )

    async def start_mix_capture_async(self, *, stage: Any | None = None) -> Path | None:
        if self._operation_pending:
            self._record_error(
                "Kit mix capture start failed",
                ExtensionActionError("Another Kit Audio action is still pending."),
            )
            return None
        self._operation_pending = True
        try:
            if self._streamer_id is not None:
                raise ExtensionActionError("Kit Mix Capture is already running.")
            stage_obj = self._resolve_stage(stage)
            listener = await self._activate_listener(stage=stage_obj)
            audio = self._audio
            if audio is None or not bool(audio.has_audio()):
                raise ExtensionActionError("Kit Audio is unavailable or disabled.")
            sounds = await self._wait_for_playable_file_sounds(stage_obj, audio)
            if not sounds:
                raise ExtensionActionError(
                    "No file-backed playable OmniSound exists; generated:// and "
                    "non-file sources cannot drive Kit Mix Capture."
                )
            output_dir = _resolve_gui_output_path(DEFAULT_KIT_AUDIO_CAPTURE_DIRNAME)
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / _capture_filename()
            streamer_id = audio.create_capture_streamer()
            if streamer_id in (None, self._invalid_streamer_id):
                raise ExtensionActionError(
                    "Kit Audio could not create a capture streamer."
                )
            if not bool(audio.start_capture(streamer_id, str(path))):
                with suppress(Exception):
                    audio.destroy_capture_streamer(streamer_id)
                raise ExtensionActionError("Kit Audio could not start mix capture.")
            self._stage = stage_obj
            self._listener = listener
            self._streamer_id = streamer_id
            self._capture_path = path
            self.state.kit_listener_prim_path = prim_path(listener)
            self.state.kit_mix_capture_running = True
            self.state.kit_mix_capture_status = f"Kit mix capture running: {path}"
            self._set_status(self.state.kit_mix_capture_status)
            return path
        except Exception as exc:
            self._cleanup_after_start_failure()
            self.state.kit_mix_capture_status = f"Kit mix capture failed: {exc}"
            self._record_error("Kit mix capture start failed", exc)
            return None
        finally:
            self._operation_pending = False

    def stop_mix_capture(self) -> KitMixCaptureSummary | None:
        """Stop, wait for, destroy, and verify the owned capture streamer."""

        self._cancel_pending_tasks()
        try:
            summary = self._stop_capture(verify=True)
            if summary is None:
                self.state.kit_mix_capture_status = "Kit mix capture idle."
            else:
                self._store_capture_summary(summary)
            return summary
        except Exception as exc:
            self.state.kit_mix_capture_status = f"Kit mix capture failed: {exc}"
            self._record_error("Kit mix capture stop failed", exc)
            return None
        finally:
            with suppress(Exception):
                self._restore_listener(remove_created=True)

    def cleanup(self, *, reason: str = "cleanup") -> None:
        """Idempotently release capture, listener, and temporary session prim."""

        self._cancel_pending_tasks()
        with suppress(Exception):
            self._stop_capture(verify=False)
        with suppress(Exception):
            self._restore_listener(remove_created=True)
        self.state.kit_mix_capture_running = False
        self.state.kit_mix_capture_status = f"Kit mix capture released ({reason})."

    async def _activate_listener(self, *, stage: Any | None) -> Any:
        stage_obj = self._resolve_stage(stage)
        if self._stage is not None and self._stage is not stage_obj:
            self._cleanup_for_stage_switch()
        audio = self._audio_interface_provider()
        if audio is None or not bool(audio.has_audio()):
            raise ExtensionActionError("Kit Audio is unavailable or disabled.")
        listener, created_path = _listener_for_array(
            stage_obj,
            array_prim_path=self.state.array_prim_path,
            array_id=self.state.array_id,
        )
        same_managed_listener = self._listener is not None and _same_prim(
            self._listener, listener
        )
        if self._listener is not None and not same_managed_listener:
            self._cleanup_for_stage_switch()
        previous = audio.get_active_listener()
        if same_managed_listener and _same_prim(previous, listener):
            return listener
        self._stage = stage_obj
        self._audio = audio
        self._listener = listener
        self._previous_listener = previous
        self._created_listener_path = (
            self._created_listener_path if same_managed_listener else created_path
        )
        try:
            for attempt in range(_ACTIVATION_ATTEMPTS):
                if bool(audio.set_active_listener(listener)):
                    return listener
                if attempt + 1 < _ACTIVATION_ATTEMPTS:
                    await self._next_update_async()
        except BaseException:
            with suppress(Exception):
                self._restore_listener(remove_created=True)
            raise
        self._restore_listener(remove_created=True)
        raise ExtensionActionError(
            "Kit Audio did not register the array listener with Hydra after "
            f"{_ACTIVATION_ATTEMPTS} attempts."
        )

    async def _wait_for_playable_file_sounds(
        self,
        stage: Any,
        audio: Any,
    ) -> tuple[Any, ...]:
        file_sounds = _file_backed_sounds(stage)
        if not file_sounds:
            return ()
        for attempt in range(_ACTIVATION_ATTEMPTS):
            ready = tuple(sound for sound in file_sounds if _sound_ready(audio, sound))
            if ready:
                return ready
            if attempt + 1 < _ACTIVATION_ATTEMPTS:
                await self._next_update_async()
        return ()

    def _stop_capture(self, *, verify: bool) -> KitMixCaptureSummary | None:
        streamer_id = self._streamer_id
        audio = self._audio
        path = self._capture_path
        if streamer_id is None or audio is None:
            self.state.kit_mix_capture_running = False
            return None
        stop_error: BaseException | None = None
        wait_ok = False
        try:
            if not bool(audio.stop_capture(streamer_id)):
                stop_error = ExtensionActionError("Kit Audio could not stop capture.")
        except Exception as exc:
            stop_error = exc
        try:
            wait_ok = bool(audio.wait_for_capture(streamer_id, _CAPTURE_WAIT_MS))
        finally:
            try:
                audio.destroy_capture_streamer(streamer_id)
            finally:
                self._streamer_id = None
                self._capture_path = None
                self.state.kit_mix_capture_running = False
        if not verify:
            return None
        if stop_error is not None:
            raise stop_error
        if not wait_ok:
            raise ExtensionActionError("Timed out while finalizing Kit mix capture.")
        if path is None or not path.is_file():
            raise ExtensionActionError("Kit mix capture produced no WAV file.")
        data = read_wav(path)
        peak = float(np.max(np.abs(data.samples))) if data.samples.size else 0.0
        if data.frame_count <= 0:
            raise ExtensionActionError("Kit mix capture WAV contains no audio frames.")
        if peak <= 0.0:
            raise ExtensionActionError("Kit mix capture WAV is silent.")
        return KitMixCaptureSummary(
            path=path,
            channel_count=data.channel_count,
            sample_rate_hz=data.sample_rate_hz,
            duration_s=data.duration_s,
            peak=peak,
        )

    def _restore_listener(self, *, remove_created: bool) -> bool:
        audio = self._audio
        listener = self._listener
        previous = self._previous_listener
        restored = False
        if audio is not None and listener is not None:
            active = audio.get_active_listener()
            if _same_prim(active, listener):
                restored = bool(audio.set_active_listener(previous))
                self.state.kit_listener_status = (
                    "Previous Kit listener restored."
                    if restored
                    else "Previous Kit listener could not be restored."
                )
            else:
                self.state.kit_listener_status = (
                    "Kit listener changed manually; the user selection was preserved."
                )
        else:
            self.state.kit_listener_status = "Kit listener idle."
        if remove_created and self._stage is not None and self._created_listener_path:
            _remove_session_listener(self._stage, self._created_listener_path)
        self._stage = None
        self._audio = None
        self._listener = None
        self._previous_listener = None
        self._created_listener_path = None
        self.state.kit_listener_prim_path = None
        return restored

    def _cleanup_after_start_failure(self) -> None:
        if self._streamer_id is not None:
            with suppress(Exception):
                self._stop_capture(verify=False)
        with suppress(Exception):
            self._restore_listener(remove_created=True)

    def _cleanup_for_stage_switch(self) -> None:
        with suppress(Exception):
            self._stop_capture(verify=False)
        with suppress(Exception):
            self._restore_listener(remove_created=True)

    def _store_capture_summary(self, summary: KitMixCaptureSummary) -> None:
        state = self.state
        state.latest_kit_mix_path = str(summary.path)
        state.latest_kit_mix_channels = summary.channel_count
        state.latest_kit_mix_sample_rate_hz = summary.sample_rate_hz
        state.latest_kit_mix_duration_s = summary.duration_s
        state.latest_kit_mix_peak = summary.peak
        state.kit_mix_capture_status = (
            f"Kit mix captured: {summary.path} | {summary.channel_count} ch | "
            f"{summary.sample_rate_hz} Hz | {summary.duration_s:.2f} s"
        )
        self._set_status(state.kit_mix_capture_status)

    def _resolve_stage(self, stage: Any | None) -> Any:
        stage_obj = stage
        if stage_obj is None:
            stage_obj = self._host.current_stage_context().stage
        if stage_obj is None:
            raise ExtensionActionError("No open USD stage is available.")
        return stage_obj

    def _run_async_action(self, action: Awaitable[Any], *, pending_status: str) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(action)
        task = loop.create_task(action)
        self._pending_tasks.add(task)
        task.add_done_callback(self._async_action_done)
        self._set_status(pending_status)
        return task

    def _cancel_pending_tasks(self) -> None:
        for task in tuple(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()

    def _async_action_done(self, task: asyncio.Task[Any]) -> None:
        self._pending_tasks.discard(task)
        with suppress(asyncio.CancelledError, Exception):
            task.result()
        with suppress(Exception):
            self._host.refresh_window()


def _default_audio_interface() -> Any:
    try:
        module = importlib.import_module("omni.usd.audio")
    except ImportError as exc:
        raise ExtensionActionError(
            "omni.usd.audio is unavailable; use Kit scene audition inside Isaac Sim."
        ) from exc
    return module.get_stage_audio_interface()


async def _default_next_update() -> None:
    try:
        app = importlib.import_module("omni.kit.app").get_app()
    except (AttributeError, ImportError):
        await asyncio.sleep(0)
        return
    await app.next_update_async()


def _listener_for_array(
    stage: Any,
    *,
    array_prim_path: str,
    array_id: str,
) -> tuple[Any, str | None]:
    array = _stage_prim(stage, array_prim_path)
    if array is None:
        raise ExtensionActionError(
            f"Microphone array prim does not exist at {array_prim_path!r}."
        )
    listeners = tuple(
        prim
        for prim in _stage_prims(stage)
        if prim_type_name(prim).lower() in {"omnilistener", "listener"}
    )
    descendants = tuple(
        listener
        for listener in listeners
        if prim_path(listener).startswith(f"{array_prim_path.rstrip('/')}/")
    )
    associated = tuple(
        listener
        for listener in listeners
        if str(_prim_attribute(listener, "ias:array_id") or "") == array_id
    )
    matches = descendants or associated
    if matches:
        return sorted(matches, key=prim_path)[0], None
    listener_path = _available_listener_path(stage, array_prim_path)
    with _session_edit_context(stage):
        create_listener_prim(
            stage,
            prim_path=listener_path,
            array_id=array_id,
            orientation_from_view=False,
        )
    listener = _stage_prim(stage, listener_path)
    if listener is None:
        raise ExtensionActionError("Temporary Kit listener could not be authored.")
    return listener, listener_path


def _available_listener_path(stage: Any, array_prim_path: str) -> str:
    base = f"{array_prim_path.rstrip('/')}/{_TEMP_LISTENER_NAME}"
    if _stage_prim(stage, base) is None:
        return base
    suffix = 1
    while _stage_prim(stage, f"{base}_{suffix}") is not None:
        suffix += 1
    return f"{base}_{suffix}"


def _remove_session_listener(stage: Any, path: str) -> None:
    with _session_edit_context(stage):
        remove_prim(stage, path)


def _session_edit_context(stage: Any) -> Any:
    try:
        from pxr import Usd  # type: ignore

        session = stage.GetSessionLayer()
        if session is not None:
            return Usd.EditContext(stage, session)
    except (AttributeError, ImportError, RuntimeError, TypeError):
        pass
    return nullcontext()


def _file_backed_sounds(stage: Any) -> tuple[Any, ...]:
    return tuple(
        prim
        for prim in _stage_prims(stage)
        if prim_type_name(prim).lower() in {"omnisound", "sound"}
        and _file_asset_path(_prim_attribute(prim, "filePath"))
    )


def _sound_ready(audio: Any, sound: Any) -> bool:
    method = getattr(audio, "get_sound_asset_status", None)
    if not callable(method):
        return True
    try:
        status = method(sound)
    except Exception:
        return False
    name = str(getattr(status, "name", status)).rsplit(".", 1)[-1].upper()
    return name == "DONE"


def _file_asset_path(value: Any) -> str:
    if value is None:
        return ""
    path = getattr(value, "path", value)
    resolved = str(path).strip()
    if not resolved or resolved.startswith("generated://"):
        return ""
    return resolved


def _prim_attribute(prim: Any, name: str) -> Any:
    attributes = getattr(prim, "attributes", None)
    if isinstance(attributes, dict):
        return attributes.get(name)
    getter = getattr(prim, "GetAttribute", None)
    if callable(getter):
        try:
            attribute = getter(name)
            if attribute is not None and hasattr(attribute, "Get"):
                return attribute.Get()
        except Exception:
            return None
    return None


def _stage_prims(stage: Any) -> tuple[Any, ...]:
    if not hasattr(stage, "Traverse"):
        return ()
    return tuple(stage.Traverse())


def _stage_prim(stage: Any, path: str) -> Any | None:
    if hasattr(stage, "GetPrimAtPath"):
        try:
            prim = stage.GetPrimAtPath(path)
            if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
                return prim
        except Exception:
            pass
    return next((prim for prim in _stage_prims(stage) if prim_path(prim) == path), None)


def _same_prim(first: Any | None, second: Any | None) -> bool:
    if first is None or second is None:
        return first is second
    return prim_path(first) == prim_path(second)


def _capture_filename() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    return f"kit_mix_{timestamp}.wav"
