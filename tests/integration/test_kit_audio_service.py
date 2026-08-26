"""Kit listener and qualitative device-mix capture service tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.kit_audio import KitAudioService
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import _FakePrim, _FakeStage, _float32_wav_bytes


class _SessionStage(_FakeStage):
    def __init__(self, prims=()):
        super().__init__(prims)
        self.session_layer = object()

    def GetSessionLayer(self):
        return self.session_layer


class _FakeAudio:
    def __init__(
        self,
        *,
        active=None,
        activation_failures: int = 0,
        start_ok: bool = True,
        wait_ok: bool = True,
        write_wav: bool = True,
    ) -> None:
        self.active = active
        self.activation_failures = activation_failures
        self.start_ok = start_ok
        self.wait_ok = wait_ok
        self.write_wav = write_wav
        self.capture_path: Path | None = None
        self.calls: list[tuple] = []

    def has_audio(self):
        return True

    def get_active_listener(self):
        return self.active

    def set_active_listener(self, prim):
        self.calls.append(("set_active_listener", _path(prim)))
        if self.activation_failures > 0:
            self.activation_failures -= 1
            return False
        self.active = prim
        return True

    def get_sound_asset_status(self, _prim):
        return "DONE"

    def create_capture_streamer(self):
        self.calls.append(("create_capture_streamer",))
        return 7

    def start_capture(self, streamer_id, filename):
        self.calls.append(("start_capture", streamer_id, filename))
        self.capture_path = Path(filename)
        return self.start_ok

    def stop_capture(self, streamer_id):
        self.calls.append(("stop_capture", streamer_id))
        if self.write_wav and self.capture_path is not None:
            self.capture_path.write_bytes(_float32_wav_bytes())
        return True

    def wait_for_capture(self, streamer_id, timeout_ms):
        self.calls.append(("wait_for_capture", streamer_id, timeout_ms))
        return self.wait_ok

    def destroy_capture_streamer(self, streamer_id):
        self.calls.append(("destroy_capture_streamer", streamer_id))


def _controller(stage, audio, *, next_update_async=None):
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller._kit_audio = KitAudioService(
        controller,
        audio_interface_provider=lambda: audio,
        next_update_async=next_update_async,
    )
    return controller


def _stage(*, listener=None, file_source=True):
    prims = [
        _FakePrim(
            "/World/Rig/AudioArray",
            "Xform",
            {"ias:array_id": "rig_front"},
        )
    ]
    if listener is not None:
        prims.append(listener)
    attributes = (
        {"filePath": "audio/speech.wav"}
        if file_source
        else {"ias:audio_asset_path": "generated://impulse"}
    )
    prims.append(_FakePrim("/World/Speaker", "OmniSound", attributes))
    return _SessionStage(tuple(prims))


def test_listener_creation_uses_session_child_retries_and_restores(
    monkeypatch,
):
    edits: list[tuple[str, object]] = []

    class _EditContext:
        def __init__(self, _stage, layer):
            self.layer = layer

        def __enter__(self):
            edits.append(("enter", self.layer))

        def __exit__(self, *_exc):
            edits.append(("exit", self.layer))

    pxr = ModuleType("pxr")
    pxr.Usd = SimpleNamespace(EditContext=_EditContext)
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    stage = _stage(listener=previous)
    audio = _FakeAudio(active=previous, activation_failures=1)
    updates: list[str] = []

    async def _next_update():
        updates.append("update")

    controller = _controller(stage, audio, next_update_async=_next_update)

    path = controller.activate_kit_listener(stage=stage)

    assert path == "/World/Rig/AudioArray/IasKitAudioListener"
    assert updates == ["update"]
    assert stage.GetPrimAtPath(path).type_name == "OmniListener"
    assert audio.active is stage.GetPrimAtPath(path)
    assert controller.restore_previous_kit_listener() is True
    assert audio.active is previous
    assert stage.GetPrimAtPath(path) is None
    assert [entry[0] for entry in edits] == ["enter", "exit", "enter", "exit"]


@pytest.mark.parametrize(
    "attributes",
    (
        {"orientationFromView": False},
        {"ias:array_id": "rig_front", "orientationFromView": False},
    ),
)
def test_listener_reuses_compatible_array_child_and_preserves_manual_override(
    attributes,
):
    listener = _FakePrim(
        "/World/Rig/AudioArray/ExistingListener",
        "OmniListener",
        attributes,
    )
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    manual = _FakePrim("/World/ManualListener", "OmniListener")
    stage = _stage(listener=listener)
    audio = _FakeAudio(active=previous)
    controller = _controller(stage, audio)

    assert controller.activate_kit_listener(stage=stage) == listener.path
    audio.active = manual

    assert controller.restore_previous_kit_listener() is False
    assert audio.active is manual
    assert stage.GetPrimAtPath(listener.path) is listener
    assert "user selection was preserved" in controller.state.kit_listener_status


def test_listener_ignores_external_array_id_match_and_removes_fallback():
    listener = _FakePrim(
        "/World/RobotListener",
        "OmniListener",
        {
            "ias:array_id": "rig_front",
            "orientationFromView": False,
        },
    )
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    stage = _stage(listener=listener)
    audio = _FakeAudio(active=previous)
    controller = _controller(stage, audio)

    path = controller.activate_kit_listener(stage=stage)

    assert path == "/World/Rig/AudioArray/IasKitAudioListener"
    assert audio.active is stage.GetPrimAtPath(path)
    assert stage.GetPrimAtPath(listener.path) is listener
    assert controller.restore_previous_kit_listener() is True
    assert audio.active is previous
    assert stage.GetPrimAtPath(path) is None
    assert stage.GetPrimAtPath(listener.path) is listener


@pytest.mark.parametrize(
    "attributes",
    (
        {"ias:array_id": "rig_front", "orientationFromView": True},
        {
            "ias:array_id": "rig_front",
            "orientationFromView": False,
            "xformOp:translate": (0.1, 0.0, 0.0),
        },
        {"ias:array_id": "other_array", "orientationFromView": False},
    ),
)
def test_listener_ignores_incompatible_array_child(attributes):
    listener = _FakePrim(
        "/World/Rig/AudioArray/ExistingListener",
        "OmniListener",
        attributes,
    )
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    stage = _stage(listener=listener)
    audio = _FakeAudio(active=previous)
    controller = _controller(stage, audio)

    path = controller.activate_kit_listener(stage=stage)

    assert path == "/World/Rig/AudioArray/IasKitAudioListener"
    fallback = stage.GetPrimAtPath(path)
    assert fallback is audio.active
    assert fallback.attributes == {
        "ias:array_id": "rig_front",
        "orientationFromView": False,
    }
    assert controller.restore_previous_kit_listener() is True
    assert audio.active is previous
    assert stage.GetPrimAtPath(path) is None
    assert stage.GetPrimAtPath(listener.path) is listener


def test_mix_capture_stop_wait_destroy_verifies_real_wav_and_releases_listener():
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    stage = _stage(listener=previous)
    audio = _FakeAudio(active=previous)
    controller = _controller(stage, audio)

    path = controller.start_kit_mix_capture(stage=stage)

    assert path is not None
    assert path.parent.name == "kit_audio_captures"
    assert controller.state.kit_mix_capture_running is True

    summary = controller.stop_kit_mix_capture()

    assert summary is not None
    assert summary.path == path
    assert summary.channel_count == 1
    assert summary.sample_rate_hz == 8000
    assert summary.duration_s > 0.0
    assert summary.peak > 0.0
    capture_calls = [call[0] for call in audio.calls if "capture" in call[0]]
    assert capture_calls == [
        "create_capture_streamer",
        "start_capture",
        "stop_capture",
        "wait_for_capture",
        "destroy_capture_streamer",
    ]
    assert controller.state.kit_mix_capture_running is False
    assert controller.state.latest_kit_mix_path == str(path)
    assert audio.active is previous
    assert controller.stop_kit_mix_capture() is None


def test_mix_capture_rejects_generated_only_stage_and_cleans_listener():
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    stage = _stage(listener=previous, file_source=False)
    audio = _FakeAudio(active=previous)
    controller = _controller(stage, audio)

    assert controller.start_kit_mix_capture(stage=stage) is None

    assert "No file-backed playable OmniSound" in controller.state.error_message
    assert not any(call[0] == "create_capture_streamer" for call in audio.calls)
    assert audio.active is previous
    assert controller.state.kit_listener_prim_path is None


def test_capture_start_and_wait_failures_destroy_owned_streamer():
    previous = _FakePrim("/World/PreviousListener", "OmniListener")
    start_stage = _stage(listener=previous)
    start_audio = _FakeAudio(active=previous, start_ok=False)
    start_controller = _controller(start_stage, start_audio)

    assert start_controller.start_kit_mix_capture(stage=start_stage) is None
    assert [call[0] for call in start_audio.calls if "capture" in call[0]][-2:] == [
        "start_capture",
        "destroy_capture_streamer",
    ]
    assert start_audio.active is previous

    wait_stage = _stage(listener=previous)
    wait_audio = _FakeAudio(active=previous, wait_ok=False)
    wait_controller = _controller(wait_stage, wait_audio)
    assert wait_controller.start_kit_mix_capture(stage=wait_stage) is not None

    assert wait_controller.stop_kit_mix_capture() is None
    assert [call[0] for call in wait_audio.calls if "capture" in call[0]][-3:] == [
        "stop_capture",
        "wait_for_capture",
        "destroy_capture_streamer",
    ]
    assert "Timed out" in wait_controller.state.error_message
    assert wait_audio.active is previous


def test_cleanup_is_idempotent_with_no_owned_resources():
    stage = _stage()
    audio = _FakeAudio()
    controller = _controller(stage, audio)

    controller.cleanup_kit_audio(reason="stage reset")
    controller.cleanup_kit_audio(reason="shutdown")

    assert controller.state.kit_mix_capture_running is False
    assert controller.state.kit_listener_prim_path is None
    assert audio.calls == []


def _path(prim) -> str | None:
    return None if prim is None else str(prim.path)
