"""Physical Pi/ReSpeaker, Mac playback, and local ZED engineering backend."""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import subprocess
import sys
import time
import wave
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256


class S48PhysicalBackendError(RuntimeError):
    """Physical backend command, media, or transfer failure."""


def evaluate_mac_preflight_acceptance(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate only frozen Mac identity, output, volume, and reference."""

    checks = report.get("frozen_checks")
    required_checks = {
        "model_identifier_matches",
        "os_build_matches",
        "os_version_matches",
        "output_channels_match",
        "output_device_matches",
        "output_sample_rate_matches",
        "reference_format_matches",
        "reference_hash_matches",
        "unmuted",
        "volume_matches",
    }
    if (
        not isinstance(checks, Mapping)
        or any(checks.get(key) is not True for key in required_checks)
    ):
        raise S48PhysicalBackendError(
            "Mac identity, output, volume, or reference preflight failed"
        )
    power = report.get("power")
    if not isinstance(power, Mapping):
        power = {}
    focus = report.get("focus_and_notifications")
    if not isinstance(focus, Mapping):
        focus = {}
    return {
        "schema": "ias.s4_8.mac_preflight_acceptance.v2",
        "status": "passed",
        "power_requirement": "none",
        "work_focus_requirement": "none",
        "collector_facts": {
            "ac_power": checks.get("ac_power"),
            "work_focus_active": checks.get("work_focus_active"),
            "notifications_suppressed": checks.get(
                "notifications_suppressed"
            ),
            "battery_percent": power.get("battery_percent"),
            "power_source": power.get("source"),
            "collector_focus_status": focus.get("status"),
        },
    }


def build_continuous_playback_asset(
    *,
    reference_path: Path,
    output_path: Path,
    duration_s: float,
    source_start_s: float = 0.0,
    source_stop_s: float | None = None,
) -> dict[str, Any]:
    """Tile a frozen exact-frame interval into one gapless playback asset."""

    if output_path.exists():
        raise S48PhysicalBackendError(
            "refusing to overwrite continuous playback asset"
        )
    if (
        isinstance(duration_s, bool)
        or not isinstance(duration_s, (int, float))
        or duration_s <= 0.0
        or isinstance(source_start_s, bool)
        or not isinstance(source_start_s, (int, float))
        or source_start_s < 0.0
        or (
            source_stop_s is not None
            and (
                isinstance(source_stop_s, bool)
                or not isinstance(source_stop_s, (int, float))
                or source_stop_s <= source_start_s
            )
        )
    ):
        raise S48PhysicalBackendError("continuous playback duration is invalid")
    try:
        with wave.open(str(reference_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            frame_count = source.getnframes()
            frames = source.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise S48PhysicalBackendError(
            f"reference WAV read failure: {exc}"
        ) from exc
    block_align = channels * sample_width
    if (
        channels <= 0
        or sample_width != 2
        or sample_rate <= 0
        or compression != "NONE"
        or frame_count <= 0
        or len(frames) != frame_count * block_align
    ):
        raise S48PhysicalBackendError(
            "reference must be complete signed 16-bit uncompressed PCM"
        )
    active_start_frame = round(float(source_start_s) * sample_rate)
    active_stop_frame = (
        frame_count
        if source_stop_s is None
        else round(float(source_stop_s) * sample_rate)
    )
    if (
        active_start_frame < 0
        or active_stop_frame > frame_count
        or active_stop_frame <= active_start_frame
    ):
        raise S48PhysicalBackendError(
            "continuous playback source interval is invalid"
        )
    active_frames = frames[
        active_start_frame * block_align : active_stop_frame * block_align
    ]
    output_frames = round(float(duration_s) * sample_rate)
    if output_frames <= 0:
        raise S48PhysicalBackendError("continuous playback has no output frames")
    required_bytes = output_frames * block_align
    repetitions, remainder = divmod(required_bytes, len(active_frames))
    payload = active_frames * repetitions + active_frames[:remainder]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            output_path.open("xb") as raw,
            wave.open(raw, "wb") as destination,
        ):
            destination.setnchannels(channels)
            destination.setsampwidth(sample_width)
            destination.setframerate(sample_rate)
            destination.writeframes(payload)
    except (OSError, wave.Error) as exc:
        raise S48PhysicalBackendError(
            f"continuous playback asset write failure: {exc}"
        ) from exc
    return {
        "schema": "ias.s4_8.continuous_playback_asset.v1",
        "source_sha256": _sha256_file(reference_path),
        "asset_sha256": _sha256_file(output_path),
        "sample_rate_hz": sample_rate,
        "channel_count": channels,
        "sample_format": "PCM_S16_LE",
        "source_frame_count": frame_count,
        "source_active_start_frame": active_start_frame,
        "source_active_stop_frame": active_stop_frame,
        "source_active_duration_s": (
            active_stop_frame - active_start_frame
        )
        / sample_rate,
        "asset_frame_count": output_frames,
        "duration_s": output_frames / sample_rate,
        "construction": (
            "exact_pcm_frame_tiling"
            if active_start_frame == 0 and active_stop_frame == frame_count
            else "exact_active_pcm_frame_tiling"
        ),
        "gap_samples_inserted": 0,
    }


class RemotePhysicalEngineeringBackend:
    """Backend used by the supported A/B/C and D/E controllers.

    Prefixes contain an explicit ``ssh`` argument vector through the target.
    No shell interpolation is used locally.  All operational roots must be
    unique per attempt.
    """

    def __init__(
        self,
        *,
        pi_ssh_prefix: Sequence[str],
        pi_scp_prefix: Sequence[str],
        pi_scp_target: str,
        pi_helper_path: str,
        pi_remote_attempt: str,
        pi_device: str,
        capture_duration_s: float,
        mac_ssh_prefix: Sequence[str],
        mac_playback_helper_path: str,
        mac_continuous_asset_path: str,
        mac_continuous_asset_sha256: str,
        playback_gain: float | None,
        zed_helper_path: Path,
        zed_replay_path: Path,
        expected_zed_serial: str,
        expected_zed_sdk: str,
        expected_zed_camera_firmware: str,
        expected_zed_sensor_firmware: str,
        termination_timeout_s: float = 5.0,
    ) -> None:
        values = (
            pi_helper_path,
            pi_remote_attempt,
            pi_device,
            pi_scp_target,
            mac_playback_helper_path,
            mac_continuous_asset_path,
            mac_continuous_asset_sha256,
            expected_zed_serial,
            expected_zed_sdk,
            expected_zed_camera_firmware,
            expected_zed_sensor_firmware,
        )
        if (
            not pi_ssh_prefix
            or not pi_scp_prefix
            or not mac_ssh_prefix
            or not all(isinstance(value, str) and value for value in values)
            or any(character.isspace() for character in pi_remote_attempt)
            or capture_duration_s not in {15, 20}
            or (
                playback_gain is not None
                and (
                    isinstance(playback_gain, bool)
                    or not isinstance(playback_gain, (int, float))
                    or playback_gain <= 0.0
                )
            )
            or termination_timeout_s <= 0.0
        ):
            raise S48PhysicalBackendError("physical backend configuration is invalid")
        self._pi_ssh_prefix = list(pi_ssh_prefix)
        self._pi_scp_prefix = list(pi_scp_prefix)
        self._pi_scp_target = pi_scp_target
        self._pi_helper_path = pi_helper_path
        self._pi_remote_attempt = pi_remote_attempt
        self._pi_device = pi_device
        self._capture_duration_s = float(capture_duration_s)
        self._mac_ssh_prefix = list(mac_ssh_prefix)
        self._mac_helper_path = mac_playback_helper_path
        self._mac_asset_path = mac_continuous_asset_path
        self._mac_asset_sha256 = mac_continuous_asset_sha256
        self._playback_gain = (
            None if playback_gain is None else float(playback_gain)
        )
        self._zed_helper_path = zed_helper_path.resolve()
        self._zed_replay_path = zed_replay_path.resolve()
        self._expected_zed_serial = expected_zed_serial
        self._expected_zed_sdk = expected_zed_sdk
        self._expected_zed_camera_firmware = expected_zed_camera_firmware
        self._expected_zed_sensor_firmware = expected_zed_sensor_firmware
        self._termination_timeout_s = termination_timeout_s
        self._capture_path: Path | None = None
        self._recorder_process: subprocess.Popen[str] | None = None
        self._playback_process: subprocess.Popen[str] | None = None
        self._zed_process: subprocess.Popen[str] | None = None
        self._zed_root: Path | None = None
        self._playback_command: list[str] | None = None
        self._playback_termination_observed_ns: int | None = None
        self._recorder_termination_observed_ns: int | None = None
        self._recorder_ready_observed_ns: int | None = None
        self._mac_clock_sync_local_sent_ns: int | None = None
        self._mac_clock_sync_local_received_ns: int | None = None
        self._mac_clock_sync_remote_received_ns: int | None = None
        self._mac_output_presentation_latency_ns: int | None = None

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def start_recorder(
        self,
        capture_path: Path,
        *,
        duration_s: float | None = None,
    ) -> dict[str, Any]:
        if self._recorder_process is not None:
            raise S48PhysicalBackendError("recorder already started")
        requested_duration = (
            self._capture_duration_s if duration_s is None else float(duration_s)
        )
        if requested_duration != self._capture_duration_s:
            raise S48PhysicalBackendError(
                "recorder duration contradicts the frozen take"
            )
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        self._capture_path = capture_path
        command = [
            *self._pi_ssh_prefix,
            "/usr/bin/python3",
            self._pi_helper_path,
            "record",
            "--attempt",
            self._pi_remote_attempt,
            "--device",
            self._pi_device,
            "--duration",
            str(int(requested_duration)),
            "--minimum-free-bytes",
            "1073741824",
        ]
        self._recorder_process = _start_process(command)
        return {
            "pid": self._recorder_process.pid,
            "process_identity": "ssh_pi_respeaker_capture",
            "command_sha256": canonical_sha256(command),
        }

    def wait_recorder_ready(self, recorder: object) -> bool:
        del recorder
        if self._recorder_process is None:
            raise S48PhysicalBackendError("recorder was not started")
        event = _wait_json_event(
            self._recorder_process,
            expected_event="ready",
            timeout_s=20.0,
        )
        self._recorder_ready_observed_ns = time.monotonic_ns()
        capture_format = event.get("capture_format", {})
        return (
            event.get("event") == "ready"
            and capture_format.get("sample_rate_hz") == 16000
            and capture_format.get("channel_count") == 6
            and capture_format.get("encoding") == "PCM_S16_LE"
        )

    def prepare_playback(self, reference_path: Path) -> dict[str, Any]:
        if self._playback_gain is None:
            raise S48PhysicalBackendError(
                "playback is unavailable for this non-reference take"
            )
        if self._playback_command is not None:
            raise S48PhysicalBackendError("playback already prepared")
        self._playback_command = [
            *self._mac_ssh_prefix,
            "/usr/bin/swift",
            self._mac_helper_path,
            "--asset",
            self._mac_asset_path,
            "--expected-sha256",
            self._mac_asset_sha256,
            "--gain",
            str(self._playback_gain),
        ]
        self._playback_process = _start_process(
            self._playback_command,
            stdin_pipe=True,
        )
        armed = _wait_json_event(
            self._playback_process,
            expected_event="armed",
            timeout_s=20.0,
        )
        if armed.get("asset_sha256") != self._mac_asset_sha256:
            raise S48PhysicalBackendError(
                "armed Mac helper authenticated a different playback asset"
            )
        output_presentation_latency_ns = armed.get(
            "output_presentation_latency_ns"
        )
        if (
            armed.get("start_observation")
            != "coreaudio_first_nonzero_presented_frame"
            or isinstance(output_presentation_latency_ns, bool)
            or not isinstance(output_presentation_latency_ns, int)
            or output_presentation_latency_ns < 0
        ):
            raise S48PhysicalBackendError(
                "Mac helper did not arm the CoreAudio render observation"
            )
        if self._playback_process.stdin is None:
            raise S48PhysicalBackendError(
                "Mac playback command stream is unavailable"
            )
        local_sent_ns = time.monotonic_ns()
        self._playback_process.stdin.write("SYNC\n")
        self._playback_process.stdin.flush()
        sync = _wait_json_event(
            self._playback_process,
            expected_event="clock_sync",
            timeout_s=5.0,
        )
        local_received_ns = time.monotonic_ns()
        remote_received_ns = sync.get("helper_monotonic_ns")
        if (
            isinstance(remote_received_ns, bool)
            or not isinstance(remote_received_ns, int)
            or remote_received_ns < 0
            or local_received_ns < local_sent_ns
        ):
            raise S48PhysicalBackendError(
                "Mac helper clock synchronization is invalid"
            )
        self._mac_clock_sync_local_sent_ns = local_sent_ns
        self._mac_clock_sync_local_received_ns = local_received_ns
        self._mac_clock_sync_remote_received_ns = remote_received_ns
        self._mac_output_presentation_latency_ns = (
            output_presentation_latency_ns
        )
        return {
            "command_sha256": canonical_sha256(self._playback_command),
            "authenticated_reference_sha256": _sha256_file(reference_path),
            "continuous_asset_path": self._mac_asset_path,
            "continuous_asset_sha256": self._mac_asset_sha256,
            "helper_path": self._mac_helper_path,
            "armed": True,
            "start_observation": armed["start_observation"],
            "clock_sync_local_sent_monotonic_ns": local_sent_ns,
            "clock_sync_local_received_monotonic_ns": local_received_ns,
            "clock_sync_remote_received_monotonic_ns": remote_received_ns,
            "clock_sync_round_trip_ns": local_received_ns - local_sent_ns,
            "output_presentation_latency_ns": (
                output_presentation_latency_ns
            ),
        }

    def start_playback(self, command: object) -> dict[str, Any]:
        del command
        if self._playback_command is None or self._playback_process is None:
            raise S48PhysicalBackendError("playback command was not prepared")
        if self._playback_process.stdin is None:
            raise S48PhysicalBackendError("Mac playback command stream is unavailable")
        self._playback_process.stdin.write("START\n")
        self._playback_process.stdin.flush()
        started = _wait_json_event(
            self._playback_process,
            expected_event="playback_started",
            timeout_s=5.0,
        )
        remote_start_ns = started.get("presentation_start_monotonic_ns")
        local_sent_ns = self._mac_clock_sync_local_sent_ns
        local_received_ns = self._mac_clock_sync_local_received_ns
        remote_sync_ns = self._mac_clock_sync_remote_received_ns
        output_presentation_latency_ns = (
            self._mac_output_presentation_latency_ns
        )
        if (
            isinstance(remote_start_ns, bool)
            or not isinstance(remote_start_ns, int)
            or local_sent_ns is None
            or local_received_ns is None
            or remote_sync_ns is None
            or remote_start_ns < remote_sync_ns
            or started.get("output_presentation_latency_ns")
            != output_presentation_latency_ns
            or started.get("start_observation")
            != "coreaudio_first_nonzero_presented_frame"
        ):
            raise S48PhysicalBackendError(
                "Mac CoreAudio playback-start observation is invalid"
            )
        remote_elapsed_ns = remote_start_ns - remote_sync_ns
        lower_bound_ns = local_sent_ns + remote_elapsed_ns
        upper_bound_ns = local_received_ns + remote_elapsed_ns
        return {
            "pid": self._playback_process.pid,
            "process_identity": "ssh_mac_coreaudio",
            "start_observation": started["start_observation"],
            "remote_presentation_start_monotonic_ns": remote_start_ns,
            "first_nonzero_frame_offset": started.get(
                "first_nonzero_frame_offset"
            ),
            "render_host_time_valid": started.get("render_host_time_valid"),
            "clock_sync_round_trip_ns": local_received_ns - local_sent_ns,
            "output_presentation_latency_ns": (
                output_presentation_latency_ns
            ),
            "presentation_start_upper_bound_monotonic_ns": upper_bound_ns,
            "observed_start_monotonic_ns": lower_bound_ns,
        }

    def wait_until(self, monotonic_ns: int) -> None:
        while True:
            observed = time.monotonic_ns()
            if (
                self._playback_process is not None
                and self._playback_termination_observed_ns is None
                and self._playback_process.poll() is not None
            ):
                self._playback_termination_observed_ns = observed
            if (
                self._recorder_process is not None
                and self._recorder_termination_observed_ns is None
                and self._recorder_process.poll() is not None
            ):
                self._recorder_termination_observed_ns = observed
            remaining_ns = monotonic_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                return
            time.sleep(min(remaining_ns / 1_000_000_000.0, 0.025))

    def stop_playback(self, playback: object) -> dict[str, Any]:
        del playback
        process = self._playback_process
        if process is None:
            raise S48PhysicalBackendError("playback was not started")
        requested = False
        try:
            process.wait(timeout=0.75)
        except subprocess.TimeoutExpired:
            requested = True
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=self._termination_timeout_s)
        remote_completed: dict[str, Any] | None = None
        if not requested and process.returncode == 0:
            remote_completed = _wait_json_event(
                process,
                expected_event="playback_completed",
                timeout_s=1.0,
            )
        observed = self._playback_termination_observed_ns or time.monotonic_ns()
        return {
            "pid": process.pid,
            "exit_status": process.returncode,
            "remote_playback_exit_status": (
                None
                if remote_completed is None
                else remote_completed.get("playback_exit_status")
            ),
            "remote_helper_monotonic_ns": (
                None
                if remote_completed is None
                else remote_completed.get("helper_monotonic_ns")
            ),
            "remote_stderr": (
                None
                if remote_completed is None
                else remote_completed.get("stderr")
            ),
            "completion_observation": (
                None
                if remote_completed is None
                else remote_completed.get("completion_observation")
            ),
            "controller_requested_termination": requested,
            "controller_requested_signal": signal.SIGTERM if requested else None,
            "observed_termination_monotonic_ns": observed,
        }

    def stop_recorder(self, recorder: object) -> dict[str, Any]:
        del recorder
        process = self._recorder_process
        capture_path = self._capture_path
        if process is None or capture_path is None:
            raise S48PhysicalBackendError("recorder was not started")
        requested = False
        try:
            process.wait(timeout=self._termination_timeout_s)
        except subprocess.TimeoutExpired:
            requested = True
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=self._termination_timeout_s)
        observed = self._recorder_termination_observed_ns or time.monotonic_ns()
        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ""
            raise S48PhysicalBackendError(
                f"Pi recorder failed ({process.returncode}): {stderr.strip()}"
            )
        status_path = capture_path.with_name("pi_producer_status.json")
        for remote_name, local_path in (
            ("producer_status.json", status_path),
            ("respeaker_audio.wav", capture_path),
        ):
            command = [
                *self._pi_scp_prefix,
                (
                    f"{self._pi_scp_target}:"
                    f"{self._pi_remote_attempt}/{remote_name}"
                ),
                str(local_path),
            ]
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                raise S48PhysicalBackendError(
                    f"Pi transfer failed for {remote_name}: {result.stderr.strip()}"
                )
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise S48PhysicalBackendError(
                f"Pi producer status read failure: {exc}"
            ) from exc
        if (
            status.get("status") != "complete"
            or status.get("sha256") != _sha256_file(capture_path)
        ):
            raise S48PhysicalBackendError(
                "transferred capture contradicts Pi producer status"
            )
        producer_started = status.get("started_monotonic_ns")
        producer_completed = status.get("completed_monotonic_ns")
        if (
            isinstance(producer_started, bool)
            or not isinstance(producer_started, int)
            or isinstance(producer_completed, bool)
            or not isinstance(producer_completed, int)
            or producer_completed <= producer_started
            or self._recorder_ready_observed_ns is None
        ):
            raise S48PhysicalBackendError(
                "Pi producer timing evidence is incomplete"
            )
        producer_duration_ns = producer_completed - producer_started
        observed = self._recorder_ready_observed_ns + producer_duration_ns
        return {
            "pid": process.pid,
            "exit_status": process.returncode,
            "controller_requested_termination": requested,
            "controller_requested_signal": signal.SIGTERM if requested else None,
            "observed_termination_monotonic_ns": observed,
            "producer_status_sha256": _sha256_file(status_path),
            "producer_started_monotonic_ns": producer_started,
            "producer_completed_monotonic_ns": producer_completed,
            "producer_capture_duration_ns": producer_duration_ns,
        }

    def begin_silence_interval(self) -> dict[str, Any]:
        event = {
            "event": "silence_interval_started",
            "stimulus": "ambient_room_silence",
        }
        print(json.dumps(event, sort_keys=True), flush=True)
        return event

    def complete_silence_interval(self) -> dict[str, Any]:
        event = {
            "event": "silence_interval_completed",
            "stimulus": "ambient_room_silence",
        }
        print(json.dumps(event, sort_keys=True), flush=True)
        return event

    def start_zed(
        self,
        artifact_root: Path,
        *,
        duration_s: float,
    ) -> dict[str, Any]:
        if self._zed_process is not None:
            raise S48PhysicalBackendError("ZED recorder already started")
        artifact_root.mkdir(parents=True, exist_ok=False)
        self._zed_root = artifact_root
        command = [
            sys.executable,
            str(self._zed_helper_path),
            "--duration",
            str(duration_s),
            "--output-dir",
            str(artifact_root),
            "--expected-serial",
            self._expected_zed_serial,
            "--expected-sdk",
            self._expected_zed_sdk,
            "--expected-camera-firmware",
            self._expected_zed_camera_firmware,
            "--expected-sensor-firmware",
            self._expected_zed_sensor_firmware,
            "--version-policy",
            "metadata",
            "--resolution",
            "HD720",
            "--fps",
            "30",
            "--depth-mode",
            "PERFORMANCE",
            "--minimum-usb-speed-mbps",
            "5000",
        ]
        self._zed_process = _start_process(command)
        return {
            "pid": self._zed_process.pid,
            "process_identity": "local_zed_svo2_capture",
            "command_sha256": canonical_sha256(command),
        }

    def wait_zed_ready(self, zed: object) -> bool:
        del zed
        if self._zed_process is None:
            raise S48PhysicalBackendError("ZED recorder was not started")
        event = _wait_json_event(
            self._zed_process,
            expected_event="ready",
            timeout_s=20.0,
        )
        return event.get("event") == "ready"

    def record_impact_cue(self, cue_index: int) -> dict[str, Any]:
        event = {"event": "impact_now", "cue_index": cue_index}
        print(json.dumps(event, sort_keys=True), flush=True)
        return event

    def stop_zed(self, zed: object) -> dict[str, Any]:
        del zed
        process = self._zed_process
        root = self._zed_root
        if process is None or root is None:
            raise S48PhysicalBackendError("ZED recorder was not started")
        try:
            process.wait(timeout=self._termination_timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=self._termination_timeout_s)
        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ""
            raise S48PhysicalBackendError(
                f"ZED recorder failed ({process.returncode}): {stderr.strip()}"
            )
        replay_path = root / "zed_svo_replay.json"
        command = [
            sys.executable,
            str(self._zed_replay_path),
            str(root / "capture.svo2"),
            "--output",
            str(replay_path),
            "--expected-serial",
            self._expected_zed_serial,
            "--resolution",
            "HD720",
            "--fps",
            "30",
            "--depth-mode",
            "PERFORMANCE",
        ]
        replay = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if replay.returncode != 0:
            raise S48PhysicalBackendError(
                f"ZED full replay failed: {replay.stderr.strip()}"
            )
        try:
            producer = json.loads(
                (root / "producer_summary.json").read_text(encoding="utf-8")
            )
            replay_report = json.loads(replay_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise S48PhysicalBackendError(
                f"ZED evidence read failure: {exc}"
            ) from exc
        return {
            "pid": process.pid,
            "exit_status": process.returncode,
            "artifacts": {
                "producer_summary": producer,
                "replay_report": replay_report,
                "svo2_sha256": _sha256_file(root / "capture.svo2"),
                "frames_sha256": _sha256_file(root / "frames.jsonl"),
            },
        }

    def abort(self) -> dict[str, Any]:
        """Fail closed, stop live producers, and retain every artifact."""

        cleanup: dict[str, Any] = {}
        for name, process in (
            ("playback", self._playback_process),
            ("zed", self._zed_process),
            ("recorder_ssh", self._recorder_process),
        ):
            if process is None:
                continue
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=self._termination_timeout_s)
                    action = "sigterm"
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=self._termination_timeout_s)
                        action = "sigkill"
                    except (OSError, subprocess.TimeoutExpired):
                        action = "stop_failed"
            else:
                action = "already_exited"
            cleanup[name] = {
                "action": action,
                "return_code": process.returncode,
            }
        remote_stop = subprocess.run(
            [
                *self._pi_ssh_prefix,
                "/usr/bin/python3",
                self._pi_helper_path,
                "stop",
                "--attempt",
                self._pi_remote_attempt,
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        cleanup["pi_remote_stop"] = {
            "return_code": remote_stop.returncode,
            "stdout": remote_stop.stdout,
            "stderr": remote_stop.stderr,
        }
        return cleanup


def _wait_json_event(
    process: subprocess.Popen[str],
    *,
    expected_event: str,
    timeout_s: float,
) -> dict[str, Any]:
    if process.stdout is None:
        raise S48PhysicalBackendError("producer readiness stream is unavailable")
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise S48PhysicalBackendError(
                f"producer readiness timeout waiting for {expected_event}"
            )
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr else ""
            raise S48PhysicalBackendError(
                f"producer exited before readiness: {stderr.strip()}"
            )
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise S48PhysicalBackendError(
                "producer emitted non-JSON readiness output"
            ) from exc
        if event.get("event") == "failed":
            raise S48PhysicalBackendError(f"producer readiness failed: {event}")
        if event.get("event") == expected_event:
            return event


def _start_process(
    command: Sequence[str],
    *,
    stdin_pipe: bool = False,
) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise S48PhysicalBackendError(f"process start failure: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise S48PhysicalBackendError(f"file hash failure: {exc}") from exc
    return digest.hexdigest()
