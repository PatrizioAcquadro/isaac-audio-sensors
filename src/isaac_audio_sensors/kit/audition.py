"""Best-effort audio audition of exported WAVs inside Kit.

Playback backends are tried lazily in order: ``omni.audioplayer`` (the Kit
audio player extension), then the system default player via a ``file://``
URL. Every outcome is reported as a human-readable status string so the GUI
and live-gate evidence stay honest about what actually played.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any


class AuditionPlayer:
    """Stateful adapter so Stop can target whatever backend played last."""

    def __init__(self) -> None:
        self._player: Any | None = None
        self._backend: str | None = None

    def play(self, path: str | Path) -> str:
        wav_path = Path(path)
        if not wav_path.is_file():
            return f"Audition failed: no WAV at {wav_path}."
        status = self._play_with_omni_audioplayer(wav_path)
        if status is not None:
            return status
        status = self._play_with_system_player(wav_path)
        if status is not None:
            return status
        return (
            "Audition unavailable: no omni.audioplayer and no system opener; "
            f"WAV is at {wav_path}."
        )

    def stop(self) -> str:
        player = self._player
        backend = self._backend
        self._player = None
        self._backend = None
        if player is None:
            return "Audition stop: nothing is playing."
        for method_name in ("stop_sound", "stop"):
            method = getattr(player, method_name, None)
            if callable(method):
                with suppress(Exception):
                    method()
                return f"Audition stopped ({backend})."
        return f"Audition stop: {backend} player has no stop method."

    def _play_with_omni_audioplayer(self, path: Path) -> str | None:
        try:
            import omni.audioplayer  # type: ignore
        except ImportError:
            return None
        try:
            player_cls = getattr(omni.audioplayer, "AudioPlayer", None)
            if player_cls is None:
                return None
            player = player_cls()
            for method_name in ("play_sound", "play"):
                method = getattr(player, method_name, None)
                if callable(method):
                    method(str(path))
                    self._player = player
                    self._backend = "omni.audioplayer"
                    return f"Playing {path.name} via omni.audioplayer."
            return None
        except Exception as exc:  # noqa: BLE001 - report the exact error.
            return f"Audition failed via omni.audioplayer: {exc}"

    def _play_with_system_player(self, path: Path) -> str | None:
        try:
            import webbrowser

            if webbrowser.open(path.resolve().as_uri()):
                self._player = None
                self._backend = "system"
                return f"Opened {path.name} in the system audio player."
        except Exception:  # noqa: BLE001 - fall through to unavailable.
            return None
        return None
