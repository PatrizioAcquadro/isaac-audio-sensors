"""Live USD debug, OmniGraph, Sensor WAV and Kit Audio checks."""

from __future__ import annotations

import math
import struct
import time
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any

from kit_capture import (
    _settle_kit_ui,
)
from kit_common import (
    _require_stage_prim,
    _stage_has_prim,
)
from kit_ui import (
    _reference_ui_window,
)

from isaac_audio_sensors.isaac.pose_resolver import (
    prim_path,
)
from isaac_audio_sensors.kit import ExtensionController


def _collect_omnigraph_evidence(controller: ExtensionController) -> dict[str, Any]:
    """Record the OmniGraph node registration outcome honestly."""

    message = str(controller.state.omnigraph_status)
    record: dict[str, Any] = {"status_message": message}
    try:
        from isaac_audio_sensors_omni.graph_node import NODE_TYPE_NAME

        record["node_type_name"] = NODE_TYPE_NAME
    except Exception:  # noqa: BLE001 - name lookup is diagnostic only.
        record["node_type_name"] = None
    try:
        import omni.graph.core as og  # type: ignore

        get_node_type = getattr(og, "get_node_type", None)
        if callable(get_node_type) and record["node_type_name"]:
            node_type = get_node_type(record["node_type_name"])
            record["registry_lookup"] = bool(node_type)
    except Exception as exc:  # noqa: BLE001 - lookup is diagnostic only.
        record["registry_lookup_error"] = str(exc)
    duplicate_registered = (
        "Attempted to register Python node type" in message
        and "twice" in message
        and bool(record.get("registry_lookup"))
    )
    if (
        "registered:" in message
        or message.startswith("OmniGraph node registered")
        or message.startswith("OmniGraph node already registered")
        or duplicate_registered
    ):
        record["status"] = "passed"
    elif "unavailable" in message:
        record["status"] = "skipped"
    else:
        record["status"] = "failed"
    return record


def _collect_usd_debug_evidence(
    controller: ExtensionController,
    *,
    stage: Any,
) -> dict[str, Any]:
    """Prove the debug subtree is authored as real prims on the live stage."""

    paths = list(controller.state.latest_usd_debug_prim_paths)
    exists = {path: bool(_stage_has_prim(stage, path)) for path in paths}
    record: dict[str, Any] = {
        "root": controller.state.usd_debug_root,
        "enabled": controller.state.usd_debug_enabled,
        "prim_paths": paths,
        "prims_exist": exists,
        "root_exists": bool(_stage_has_prim(stage, controller.state.usd_debug_root)),
    }
    passed = bool(paths) and all(exists.values()) and record["root_exists"]
    record["status"] = "passed" if passed else "failed"
    return record


def _collect_audio_output_evidence(
    controller: ExtensionController,
    *,
    stage: Any,
    flac_destination: Path,
    source_wav_path: Path,
) -> dict[str, Any]:
    """Exercise analytic closed-room audio, panel preview, and FLAC replay."""

    record: dict[str, Any] = {"requested_backend": "analytic_acoustics"}
    try:
        import pyroomacoustics  # type: ignore # noqa: F401
        import soundfile  # type: ignore # noqa: F401
    except ImportError as exc:
        record["status"] = "skipped"
        record["reason"] = f"room extra unavailable: {exc}"
        return record
    previous_backend = controller.state.backend
    previous_environment_mode = controller.state.environment_resolution_mode
    previous_environment_anchor = controller.state.environment_anchor_prim_path
    try:
        controller.stop_sensor()
        if controller.state.source_attached_to_object:
            # The attach scenario's object may be gone; unbind for this leg.
            with suppress(Exception):
                controller.detach_source_from_object(stage=stage)
            controller.state.source_attached_to_object = False
            controller.state.attached_object_prim_path = ""
        controller.state.backend = "analytic_acoustics"
        controller.state.environment_resolution_mode = "anchor"
        controller.state.environment_anchor_prim_path = "/World/IasAcousticEnvironment"
        controller.state.replicator_enabled = False
        controller.state.waveform_enabled = True
        controller.state.waveform_dir = "live_waveforms_gui"
        controller.state.waveform_mode = "per_frame"
        if controller.configure_sensor(stage=stage) is None:
            raise RuntimeError(
                controller.state.error_message or "analytic sensor configure failed"
            )
        if controller.start_sensor(stage=stage) is None:
            raise RuntimeError(
                controller.state.error_message or "analytic sensor start failed"
            )
        if controller.update_sensor(force=True) is None:
            raise RuntimeError(
                controller.state.error_message or "analytic sensor update failed"
            )
        paths = controller.state.latest_waveform_paths
        record["waveform_paths"] = list(paths)
        if not paths:
            raise RuntimeError("analytic_acoustics update produced no waveform_paths")
        from isaac_audio_sensors.core.io.wave_read import read_wav

        data = read_wav(paths[-1])
        record["waveform"] = {
            "channels": data.channel_count,
            "sample_rate_hz": data.sample_rate_hz,
            "frames": data.frame_count,
            "duration_s": data.duration_s,
        }
        window = _reference_ui_window(controller)
        if window is not None:
            record["panel_label"] = getattr(
                window._labels.get("waveform"), "text", None
            )
            panel = getattr(window, "_audio_panel", {}) or {}
            record["panel_rendered_path"] = panel.get("rendered_path")
        record["audition_status"] = (
            controller.play_latest_waveform() or controller.state.error_message
        )
        record["audition_stop_status"] = controller.stop_audition()

        from isaac_audio_sensors.recording import export_session_flac, replay_session

        source_session = (
            Path(__file__).resolve().parents[2] / "tests/fixtures/recording/session"
        )
        exported = export_session_flac(
            source_session,
            flac_destination,
            dataset_id="kit_flac_runtime",
            creation_timestamp_ms=0,
        )
        replay_events = tuple(replay_session(exported, with_audio=True))
        replay_frames = tuple(
            event
            for event in replay_events
            if event.kind == "frame" and event.audio is not None
        )
        if not replay_frames:
            raise RuntimeError("FLAC replay produced no audio frames")
        record["flac"] = {
            "session_path": str(exported),
            "event_count": len(replay_events),
            "audio_frame_count": len(replay_frames),
            "first_audio_shape": list(replay_frames[0].audio.shape),
        }
        record["kit_audio_mix"] = _collect_kit_audio_mix_evidence(
            controller, stage=stage, source_wav_path=source_wav_path
        )
        record["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - evidence records the exact error.
        record["status"] = "failed"
        record["error_type"] = type(exc).__name__
        record["error"] = str(exc)
    finally:
        with suppress(Exception):
            controller.stop_sensor()
        with suppress(Exception):
            controller.close_sensor()
        controller.state.backend = previous_backend
        controller.state.environment_resolution_mode = previous_environment_mode
        controller.state.environment_anchor_prim_path = previous_environment_anchor
        controller.state.waveform_enabled = False
    return record


def _collect_kit_audio_mix_evidence(
    controller: ExtensionController,
    *,
    stage: Any,
    source_wav_path: Path,
) -> dict[str, Any]:
    """Prove listener placement, device-mix capture, cleanup, and sensor isolation."""

    import omni.usd.audio  # type: ignore

    from isaac_audio_sensors.core.io.wave_read import read_wav
    from isaac_audio_sensors.isaac.stage_audio import create_sound_prim, remove_prim

    source_path = "/World/IasKitAudioCaptureProbe"
    record: dict[str, Any] = {
        "array_prim_path": controller.state.array_prim_path,
        "source_prim_path": source_path,
    }
    audio = omni.usd.audio.get_stage_audio_interface()
    previous_listener = audio.get_active_listener()
    record["previous_listener_path"] = (
        None if previous_listener is None else prim_path(previous_listener)
    )
    sensor_channels_before = len(controller.state.latest_aggregate_rms)
    record["sensor_channels_before"] = sensor_channels_before
    _write_pcm16_tone(source_wav_path)
    create_sound_prim(
        stage,
        prim_path=source_path,
        audio_asset_path=str(source_wav_path),
        spatial=True,
        loop_count=0,
        duration_s=1.0,
        gain_db=-6.0,
    )
    _settle_kit_ui(updates=4)
    try:
        capture_path = controller.start_kit_mix_capture(stage=stage)
        if not isinstance(capture_path, Path):
            raise RuntimeError(
                controller.state.error_message or "Kit mix capture did not start"
            )
        listener_path = str(controller.state.kit_listener_prim_path or "")
        record["listener_path"] = listener_path
        record["listener_under_array"] = listener_path.startswith(
            f"{controller.state.array_prim_path.rstrip('/')}/"
        )
        listener = _require_stage_prim(stage, listener_path)
        session_layer = stage.GetSessionLayer()
        record["listener_in_session_layer"] = any(
            spec.layer == session_layer for spec in listener.GetPrimStack()
        )
        sound = _require_stage_prim(stage, source_path)
        audio.play_sound(sound)
        time.sleep(0.4)
        summary = controller.stop_kit_mix_capture()
        audio.stop_sound(sound)
        if summary is None:
            raise RuntimeError(
                controller.state.error_message or "Kit mix capture did not finalize"
            )
        captured = read_wav(summary.path)
        record["capture"] = {
            "path": str(summary.path),
            "channels": captured.channel_count,
            "sample_rate_hz": captured.sample_rate_hz,
            "frames": captured.frame_count,
            "duration_s": captured.duration_s,
            "peak": summary.peak,
            "readable": True,
            "non_silent": summary.peak > 0.0,
        }
        sensor_channels_after = len(controller.state.latest_aggregate_rms)
        record["sensor_channels_after"] = sensor_channels_after
        record["sensor_channel_count_unchanged"] = (
            sensor_channels_before > 0
            and sensor_channels_before == sensor_channels_after
        )
        active_listener = audio.get_active_listener()
        record["active_listener_after"] = (
            None if active_listener is None else prim_path(active_listener)
        )
        record["listener_removed"] = not _stage_has_prim(stage, listener_path)
        record["capture_released"] = not controller.state.kit_mix_capture_running
        record["listener_state_released"] = (
            controller.state.kit_listener_prim_path is None
        )
        passed = (
            record["listener_under_array"]
            and record["listener_in_session_layer"]
            and record["capture"]["readable"]
            and record["capture"]["non_silent"]
            and record["sensor_channel_count_unchanged"]
            and record["listener_removed"]
            and record["capture_released"]
            and record["listener_state_released"]
            and record["active_listener_after"] == record["previous_listener_path"]
        )
        record["status"] = "passed" if passed else "failed"
        return record
    finally:
        with suppress(Exception):
            controller.cleanup_kit_audio(reason="live gate cleanup")
        with suppress(Exception):
            remove_prim(stage, source_path)


def _write_pcm16_tone(path: Path) -> None:
    sample_rate_hz = 48_000
    frame_count = sample_rate_hz // 2
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = b"".join(
        struct.pack(
            "<h",
            int(0.25 * 32767 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate_hz)),
        )
        for i in range(frame_count)
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(samples)
