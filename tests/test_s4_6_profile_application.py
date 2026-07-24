"""Atomic, fail-closed, and runtime-path tests for S4.6."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from isaac_audio_sensors import cli
from isaac_audio_sensors.core.config import load_audio_config, validate_audio_config
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import (
    ChannelResponseConfig,
    EffectsConfig,
)
from isaac_audio_sensors.core.profile_application import (
    APPLICATION_CONFIG_PATH,
    ProfileApplicationError,
    apply_profile_application,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "examples/s4_6/compatible_runtime.toml"
POINTER = Path("outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json")
HANDOFF = Path(
    "outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json"
)
PROFILE = Path(
    "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
)
SCHEMA = Path("docs/schemas/audio_calibration_profile.v1.schema.json")
APPLICATION_SCHEMA = Path("docs/schemas/s4_6_profile_application.v1.schema.json")


def _raw_config() -> dict[str, Any]:
    return {
        "scene": {"scene_id": "s4_6_test"},
        "audio": {
            "sample_rate_hz": 16000,
            "default_backend": "tdoa_synthetic",
            "runtime_profile": "waveform_fidelity",
        },
        "sources": [
            {
                "source_id": "source",
                "prim_path": "/World/Source",
                "class_label": "Reference",
                "position_world": [1.0, 0.0, 0.0],
                "gain_db": 0.0,
            }
        ],
        "arrays": {
            "xvf3800_array": {
                "array_id": "xvf3800_array",
                "prim_path": "/World/Array",
                "sample_rate_hz": 16000,
                "coordinate_convention": (
                    "x_forward_y_right_z_up_clockwise_bearing"
                ),
                "microphones": [
                    {
                        "mic_id": "ch0",
                        "relative_position_m": [-0.02, -0.02, 0.0],
                    },
                    {
                        "mic_id": "ch1",
                        "relative_position_m": [-0.02, 0.02, 0.0],
                    },
                    {
                        "mic_id": "ch2",
                        "relative_position_m": [0.02, 0.02, 0.0],
                    },
                    {
                        "mic_id": "ch3",
                        "relative_position_m": [0.02, -0.02, 0.0],
                    },
                ],
            }
        },
    }


def _config():
    return validate_audio_config(_raw_config())


def _copy_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (
        APPLICATION_CONFIG_PATH,
        APPLICATION_SCHEMA,
        POINTER,
        HANDOFF,
        PROFILE,
        SCHEMA,
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return root


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def test_authoritative_bundle_applies_exact_seven_components() -> None:
    original = _config()
    result = apply_profile_application(original, repo_root=ROOT, mode="apply")
    adjusted = result.config
    response = adjusted.effects.channel_response

    assert result.report()["applied_field_count"] == 7
    assert response.enabled is True
    assert tuple(response.microphones or {}) == ("ch1", "ch2", "ch3")
    assert {
        mic_id: response.microphones[mic_id].gain_db
        for mic_id in response.microphones or {}
    } == {
        "ch1": -1.6020864972841506,
        "ch2": -1.2795753710282032,
        "ch3": -1.2135862725210074,
    }
    assert {
        mic_id: response.microphones[mic_id].polarity
        for mic_id in response.microphones or {}
    } == {"ch1": 1, "ch2": 1, "ch3": 1}
    assert [
        mic.relative_position_m
        for mic in adjusted.arrays["xvf3800_array"].microphones
    ] == [
        (-0.033, -0.033, 0.0),
        (-0.033, 0.033, 0.0),
        (0.033, 0.033, 0.0),
        (0.033, -0.033, 0.0),
    ]
    assert [mic.gain_db for mic in adjusted.arrays["xvf3800_array"].microphones] == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]
    assert original.effects == EffectsConfig()


def test_load_audio_config_integrates_application_into_real_runtime_path() -> None:
    config = load_audio_config(RUNTIME)
    assert config.effects.channel_response.enabled is True
    assert tuple(config.effects.channel_response.microphones or {}) == (
        "ch1",
        "ch2",
        "ch3",
    )


def test_applied_gain_and_polarity_reach_the_existing_waveform_runtime() -> None:
    config = apply_profile_application(_config(), repo_root=ROOT, mode="apply").config
    samples = np.ones((4, 8), dtype=np.float64)
    output, diagnostics = ChannelEffectsChain(config.effects).apply(
        samples,
        mic_ids=("ch0", "ch1", "ch2", "ch3"),
        sample_rate_hz=16000,
        frame_id="s4_6_runtime",
        backend_id="room_acoustics",
        runtime_profile="waveform_fidelity",
    )
    expected = [
        1.0,
        10.0 ** (-1.6020864972841506 / 20.0),
        10.0 ** (-1.2795753710282032 / 20.0),
        10.0 ** (-1.2135862725210074 / 20.0),
    ]
    assert np.allclose(output[:, 0], expected)
    assert diagnostics["channel_response"]["polarity"] == {
        "ch1": 1,
        "ch2": 1,
        "ch3": 1,
    }


def test_off_mode_returns_exact_input_object_without_bundle_io(tmp_path: Path) -> None:
    config = _config()
    result = apply_profile_application(config, repo_root=tmp_path, mode="off")
    assert result.config is config
    assert result.application_plan == ()
    assert result.bundle_identity is None
    assert result.report()["applied_field_count"] == 0


def test_repeated_application_fails_before_second_configuration() -> None:
    first = apply_profile_application(_config(), repo_root=ROOT, mode="apply")
    with pytest.raises(ProfileApplicationError, match="double application"):
        apply_profile_application(first.config, repo_root=ROOT, mode="apply")


@pytest.mark.parametrize(
    ("case", "mutate", "message"),
    (
        (
            "swapped_order",
            lambda raw: raw["arrays"]["xvf3800_array"].__setitem__(
                "microphones",
                list(reversed(raw["arrays"]["xvf3800_array"]["microphones"])),
            ),
            "channel order",
        ),
        (
            "wrong_count",
            lambda raw: raw["arrays"]["xvf3800_array"].__setitem__(
                "microphones",
                raw["arrays"]["xvf3800_array"]["microphones"][:3],
            ),
            "channel count",
        ),
        (
            "wrong_array",
            lambda raw: raw["arrays"]["xvf3800_array"].__setitem__(
                "array_id", "other_array"
            ),
            "target array",
        ),
        (
            "wrong_rate",
            lambda raw: raw["audio"].__setitem__("sample_rate_hz", 48000),
            "sample rate",
        ),
        (
            "multiple_arrays",
            lambda raw: raw["arrays"].__setitem__("other_array", {
                **copy.deepcopy(raw["arrays"]["xvf3800_array"]),
                "array_id": "other_array",
            }),
            "exactly",
        ),
        (
            "batched_lab",
            lambda raw: raw.__setitem__("lab", {"enabled": True}),
            "batched",
        ),
    ),
)
def test_runtime_compatibility_mismatches_fail_closed(
    case: str, mutate, message: str
) -> None:
    del case
    raw = _raw_config()
    mutate(raw)
    config = validate_audio_config(raw)
    before = copy.deepcopy(config)
    with pytest.raises(ProfileApplicationError, match=message):
        apply_profile_application(config, repo_root=ROOT, mode="apply")
    assert config == before
    assert config.effects.channel_response == ChannelResponseConfig()


def test_wrong_coordinate_convention_fails_in_base_config_before_application() -> None:
    raw = _raw_config()
    raw["arrays"]["xvf3800_array"]["coordinate_convention"] = "legacy"
    with pytest.raises(ValueError, match="coordinate_convention"):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("case", "mutator", "message"),
    (
        (
            "inactive_pointer",
            lambda value: value.__setitem__("status", "inactive"),
            "pointer|hash",
        ),
        (
            "historical_v1",
            lambda value: value.__setitem__(
                "active_profile_path",
                "outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json",
            ),
            "pointer|hash",
        ),
        (
            "unsafe_path",
            lambda value: value.__setitem__("active_profile_path", "../profile.json"),
            "pointer|hash",
        ),
        (
            "missing_member",
            lambda value: value.__setitem__(
                "active_profile_path",
                "outputs/isaac_audio_sensors/S4/missing.json",
            ),
            "pointer|hash",
        ),
        (
            "hash_mismatch",
            lambda value: value.__setitem__("active_profile_sha256", "0" * 64),
            "pointer|hash",
        ),
    ),
)
def test_pointer_tampering_is_stale_and_fails_before_application(
    tmp_path: Path, case: str, mutator, message: str
) -> None:
    del case
    root = _copy_bundle(tmp_path)
    pointer = _json(root / POINTER)
    mutator(pointer)
    _write(root / POINTER, pointer)
    config = _config()
    with pytest.raises(ProfileApplicationError, match=message):
        apply_profile_application(config, repo_root=root, mode="apply")
    assert config.effects.channel_response == ChannelResponseConfig()


@pytest.mark.parametrize(
    ("case", "relative", "payload"),
    (
        ("malformed_pointer", POINTER, "{"),
        ("malformed_handoff", HANDOFF, "[]\n"),
        ("malformed_profile", PROFILE, "{"),
    ),
)
def test_malformed_json_fails_closed(
    tmp_path: Path, case: str, relative: Path, payload: str
) -> None:
    del case
    root = _copy_bundle(tmp_path)
    (root / relative).write_text(payload)
    with pytest.raises(ProfileApplicationError):
        apply_profile_application(_config(), repo_root=root, mode="apply")


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        (
            "wrong_device",
            lambda value: value["application_context"].__setitem__(
                "device_id", "other_device"
            ),
        ),
        (
            "wrong_frame",
            lambda value: value["application_context"].__setitem__(
                "source_frame", "other_frame"
            ),
        ),
        (
            "wrong_mount",
            lambda value: value["application_context"].__setitem__(
                "mount_fixture_id", "other_fixture"
            ),
        ),
        (
            "wrong_environment",
            lambda value: value["application_context"].__setitem__(
                "environment_tags", ["other"]
            ),
        ),
        (
            "wrong_geometry",
            lambda value: value["application_context"].__setitem__(
                "functional_association_sha256", "0" * 64
            ),
        ),
    ),
)
def test_rechecksummed_configuration_identity_bypass_is_rejected(
    tmp_path: Path, case: str, mutate
) -> None:
    del case
    root = _copy_bundle(tmp_path)
    contract = _json(root / APPLICATION_CONFIG_PATH)
    mutate(contract)
    _write(root / APPLICATION_CONFIG_PATH, contract)
    with pytest.raises(ProfileApplicationError, match="configuration hash"):
        apply_profile_application(_config(), repo_root=root, mode="apply")


def test_rechecksummed_profile_tampering_and_unknown_parameter_fail(
    tmp_path: Path,
) -> None:
    root = _copy_bundle(tmp_path)
    profile = _json(root / PROFILE)
    profile["fitted_model_parameters"][0]["name"] = "unknown_parameter"
    _write(root / PROFILE, profile)
    digest = hashlib.sha256((root / PROFILE).read_bytes()).hexdigest()
    pointer = _json(root / POINTER)
    pointer["active_profile_sha256"] = digest
    _write(root / POINTER, pointer)
    handoff = _json(root / HANDOFF)
    handoff["active_profile"]["sha256"] = digest
    _write(root / HANDOFF, handoff)
    with pytest.raises(ProfileApplicationError, match="pointer|hash"):
        apply_profile_application(_config(), repo_root=root, mode="apply")


def test_rechecksummed_handoff_count_and_supported_field_tampering_fail(
    tmp_path: Path,
) -> None:
    root = _copy_bundle(tmp_path)
    handoff = _json(root / HANDOFF)
    handoff["retained_count_semantics"][
        "retained_scalar_profile_parameter_count"
    ] = 7
    handoff["supported_for_later_application"].append("channels.ch1.delay_s")
    _write(root / HANDOFF, handoff)
    digest = hashlib.sha256((root / HANDOFF).read_bytes()).hexdigest()
    pointer = _json(root / POINTER)
    pointer["active_handoff_sha256"] = digest
    _write(root / POINTER, pointer)
    with pytest.raises(ProfileApplicationError, match="pointer|hash"):
        apply_profile_application(_config(), repo_root=root, mode="apply")


@pytest.mark.parametrize(
    "unsafe",
    (
        "../configs/s4_6_profile_application.v1.json",
        "/tmp/s4_6_profile_application.v1.json",
        r"C:\temp\s4_6_profile_application.v1.json",
    ),
)
def test_unsafe_or_escaping_application_paths_fail(unsafe: str) -> None:
    with pytest.raises(ProfileApplicationError, match="unsafe|authorized"):
        apply_profile_application(
            _config(),
            repo_root=ROOT,
            mode="apply",
            application_config_path=unsafe,
        )


def test_missing_bundle_member_fails_closed(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    (root / PROFILE).unlink()
    with pytest.raises(ProfileApplicationError, match="missing"):
        apply_profile_application(_config(), repo_root=root, mode="apply")


def test_field_status_distinguishes_all_evidence_classes() -> None:
    result = apply_profile_application(_config(), repo_root=ROOT, mode="apply")
    statuses = {row["status"] for row in result.field_status}
    assert {"applied", "nominal", "unmeasured", "unsupported"} <= statuses
    assert all(row["reason"] for row in result.field_status)
    assert not any(
        row["field"].endswith("delay_s") and row["status"] == "applied"
        for row in result.field_status
    )


def test_application_and_report_are_deterministic() -> None:
    first = apply_profile_application(_config(), repo_root=ROOT, mode="apply")
    second = apply_profile_application(_config(), repo_root=ROOT, mode="apply")
    assert first.config == second.config
    assert first.report() == second.report()
    assert json.dumps(first.report(), sort_keys=True) == json.dumps(
        second.report(), sort_keys=True
    )


def test_cli_simulation_forwards_applied_effects_and_runtime_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = apply_profile_application(_config(), repo_root=ROOT, mode="apply").config
    captured: dict[str, Any] = {}

    class Backend:
        def simulate(self, scene, sensor, time_window):
            captured["sensor"] = sensor
            return "frame"

    def fake_backend(backend_id: str, **kwargs):
        captured["backend_id"] = backend_id
        captured["kwargs"] = kwargs
        return Backend()

    monkeypatch.setattr(cli, "load_audio_config", lambda path: config)
    monkeypatch.setattr(cli, "get_backend", fake_backend)
    args = SimpleNamespace(
        config=RUNTIME,
        backend=None,
        array_id=None,
        timestamp_ms=0,
        start_time_s=0.0,
        end_time_s=1.0,
        max_events=None,
    )
    assert cli._simulate_from_args(args) == "frame"
    assert captured["kwargs"]["effects"] == config.effects
    assert captured["kwargs"]["runtime_profile"] == "waveform_fidelity"
