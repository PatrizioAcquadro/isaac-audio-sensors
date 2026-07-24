"""Atomic S4.6 application of the authoritative active calibration bundle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from isaac_audio_sensors.core.config import AudioSensorConfig
from isaac_audio_sensors.core.effects.config import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    validate_effects_config,
)
from isaac_audio_sensors.core.io.calibration import calibration_profile_from_dict
from isaac_audio_sensors.core.schema import audio_calibration_profile_json_schema

APPLICATION_CONFIG_PATH = Path("configs/s4_6_profile_application.v1.json")
APPLICATION_CONFIG_SHA256 = (
    "82db6a2222765abddaed4a89d540ff99b586aa926534641833608330e7e45c52"
)
APPLICATION_SCHEMA_PATH = Path(
    "docs/schemas/s4_6_profile_application.v1.schema.json"
)
ACTIVE_POINTER_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json"
)
HISTORICAL_PROFILE_PATH = (
    "outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json"
)
EXPECTED_PROFILE_PATH = (
    "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
)
EXPECTED_PROFILE_SHA256 = (
    "944dda1df3a2de720ab86a3f07f0ea545aa9abca676a003423b29221ca0d47c8"
)
EXPECTED_HANDOFF_PATH = (
    "outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json"
)
EXPECTED_HANDOFF_SHA256 = (
    "8f0731b3cde2e699b73f3832d9c70d97614b772be43ceff8922e20cf2462e0e6"
)
EXPECTED_SUPPORTED_FIELDS = (
    "channels.ch1.gain_db",
    "channels.ch2.gain_db",
    "channels.ch3.gain_db",
    "channels.ch1.polarity",
    "channels.ch2.polarity",
    "channels.ch3.polarity",
    "functional_channel_position_association",
)
EXPECTED_UNSUPPORTED_FIELDS = (
    "relative_delay",
    "scalar_bearing_correction",
    "confidence_calibration",
    "relative_audio_video_timing",
    "functional_noise_or_self_noise",
    "frequency_dependent_channel_response",
    "playback_level_linearity",
    "agc_or_compression",
    "sector_thresholds_or_confusion_matrices",
    "abstention_thresholds",
    "absolute_spl",
    "absolute_microphone_sensitivity",
    "precision_optical_acoustic_extrinsics",
)


class ProfileApplicationError(ValueError):
    """Raised before use when the S4.6 bundle or context is invalid."""


@dataclass(frozen=True, slots=True)
class ProfileApplicationResult:
    """An adjusted configuration plus its complete immutable decision record."""

    config: AudioSensorConfig
    application_plan: tuple[dict[str, Any], ...]
    field_status: tuple[dict[str, Any], ...]
    mode: str
    bundle_identity: dict[str, Any] | None

    def report(self) -> dict[str, Any]:
        """Return a deterministic JSON-ready application report."""

        return {
            "schema": "ias.s4_6.profile_application_result.v1",
            "status": "passed",
            "mode": self.mode,
            "applied_field_count": sum(
                row["status"] == "applied" for row in self.field_status
            ),
            "application_plan": [dict(row) for row in self.application_plan],
            "field_status": [dict(row) for row in self.field_status],
            "bundle_identity": self.bundle_identity,
            "atomic": True,
            "partial_application": False,
        }


def apply_profile_application(
    config: AudioSensorConfig,
    *,
    repo_root: str | Path,
    mode: str,
    application_config_path: str | Path = APPLICATION_CONFIG_PATH,
) -> ProfileApplicationResult:
    """Apply the complete active bundle, or preserve exact behavior in off mode."""

    if mode == "off":
        return ProfileApplicationResult(
            config=config,
            application_plan=(),
            field_status=(
                _status(
                    "profile_application",
                    "skipped",
                    "application mode is off; no bundle was resolved",
                ),
            ),
            mode="off",
            bundle_identity=None,
        )
    if mode != "apply":
        raise ProfileApplicationError(
            "profile application mode must be 'apply' or 'off'"
        )

    root = Path(repo_root).resolve()
    contract_path = _resolve_repo_file(root, application_config_path)
    expected_contract_path = (root / APPLICATION_CONFIG_PATH).resolve()
    if contract_path != expected_contract_path:
        raise ProfileApplicationError(
            "only the frozen S4.6 application configuration is authorized"
        )
    if _sha256(contract_path) != APPLICATION_CONFIG_SHA256:
        raise ProfileApplicationError("S4.6 application configuration hash mismatch")
    contract = _load_json(contract_path, "S4.6 application configuration")
    _validate_json_schema(
        contract,
        _load_json(
            _resolve_repo_file(root, APPLICATION_SCHEMA_PATH),
            "S4.6 application schema",
        ),
        "S4.6 application configuration",
    )
    if contract.get("status") != "frozen" or contract.get("mode") != "apply":
        raise ProfileApplicationError(
            "S4.6 application configuration is inactive or incompatible"
        )
    if contract.get("active_pointer_path") != ACTIVE_POINTER_PATH.as_posix():
        raise ProfileApplicationError(
            "historical or alternate profile selection rejected"
        )

    pointer_path = _resolve_repo_file(root, contract["active_pointer_path"])
    if pointer_path != (root / ACTIVE_POINTER_PATH).resolve():
        raise ProfileApplicationError("active pointer identity bypass rejected")
    pointer = _load_json(pointer_path, "active profile pointer")
    _validate_pointer(pointer)

    handoff_path = _resolve_repo_file(root, pointer["active_handoff_path"])
    profile_path = _resolve_repo_file(root, pointer["active_profile_path"])
    if _sha256(handoff_path) != pointer["active_handoff_sha256"]:
        raise ProfileApplicationError("active handoff hash mismatch")
    if _sha256(profile_path) != pointer["active_profile_sha256"]:
        raise ProfileApplicationError("active profile hash mismatch")
    handoff = _load_json(handoff_path, "active profile handoff")
    profile_payload = _load_json(profile_path, "active v2 profile")
    _validate_json_schema(
        profile_payload,
        audio_calibration_profile_json_schema(),
        "active v2 profile",
    )
    try:
        profile = calibration_profile_from_dict(profile_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileApplicationError(f"active v2 profile is malformed: {exc}") from exc

    context = contract["application_context"]
    _validate_complete_bundle(pointer, handoff, profile_payload, context)
    _validate_runtime_context(config, context)
    plan, statuses = _compute_plan(profile_payload, handoff)

    target_array = config.arrays[context["array_id"]]
    mapping = {
        row["channel_id"]: tuple(float(value) for value in row["position_m"])
        for row in handoff["functional_channel_position_association"]["mapping"]
    }
    adjusted_microphones = tuple(
        replace(microphone, relative_position_m=mapping[microphone.mic_id])
        for microphone in target_array.microphones
    )
    adjusted_array = replace(target_array, microphones=adjusted_microphones)
    channels = {row["channel_id"]: row for row in profile_payload["channels"]}
    response = ChannelResponseConfig(
        enabled=True,
        microphones={
            channel_id: ChannelResponseMicConfig(
                gain_db=float(channels[channel_id]["gain_db"]["value"]),
                polarity=int(channels[channel_id]["polarity"]["value"]),
            )
            for channel_id in ("ch1", "ch2", "ch3")
        },
    )
    effects = replace(config.effects, channel_response=response)
    arrays = dict(config.arrays)
    arrays[target_array.array_id] = adjusted_array
    adjusted = replace(config, arrays=arrays, effects=effects)
    validate_effects_config(
        adjusted.effects,
        microphone_orders=(
            tuple(mic.mic_id for mic in adjusted_array.microphones),
        ),
        sample_rate_hz=adjusted.sample_rate_hz,
        backend_id=adjusted.default_backend,
        runtime_profile=adjusted.runtime_profile,
        microphone_self_noise_db={
            mic.mic_id: mic.self_noise_db for mic in adjusted_array.microphones
        },
        source_ids=tuple(source.source_id for source in adjusted.sources),
        source_orientations={
            source.source_id: source.orientation_world_quat
            for source in adjusted.sources
        },
        microphone_orientations={
            mic.mic_id: mic.relative_orientation_quat
            for mic in adjusted_array.microphones
        },
    )
    return ProfileApplicationResult(
        config=adjusted,
        application_plan=plan,
        field_status=statuses,
        mode="apply",
        bundle_identity={
            "active_pointer_path": ACTIVE_POINTER_PATH.as_posix(),
            "active_pointer_sha256": _sha256(pointer_path),
            "active_handoff_path": EXPECTED_HANDOFF_PATH,
            "active_handoff_sha256": EXPECTED_HANDOFF_SHA256,
            "active_profile_path": EXPECTED_PROFILE_PATH,
            "active_profile_sha256": EXPECTED_PROFILE_SHA256,
            "active_profile_id": profile.profile_id,
            "active_profile_version": profile.profile_version,
        },
    )


def _validate_pointer(pointer: Mapping[str, Any]) -> None:
    expected = {
        "schema": "ias.s4_5.active_profile_pointer.v1",
        "status": "active",
        "active_profile_count": 1,
        "active_profile_path": EXPECTED_PROFILE_PATH,
        "active_profile_sha256": EXPECTED_PROFILE_SHA256,
        "active_profile_id": "respeaker_xvf3800_s4_5_functional_corrective_01",
        "active_profile_version": "v2",
        "active_handoff_path": EXPECTED_HANDOFF_PATH,
        "active_handoff_sha256": EXPECTED_HANDOFF_SHA256,
        "historical_v1_active": False,
        "s4_6_input_policy": "profile_and_handoff_required_together_fail_closed",
    }
    if dict(pointer) != expected:
        raise ProfileApplicationError(
            "active pointer is malformed, stale, inactive, or superseded"
        )


def _validate_complete_bundle(
    pointer: Mapping[str, Any],
    handoff: Mapping[str, Any],
    profile: Mapping[str, Any],
    context: Mapping[str, Any],
) -> None:
    if handoff.get("schema") != "ias.s4_5.active_profile_handoff.v1":
        raise ProfileApplicationError("active handoff schema mismatch")
    if handoff.get("status") != "active":
        raise ProfileApplicationError("active handoff is inactive or stale")
    active = handoff.get("active_profile")
    if not isinstance(active, Mapping):
        raise ProfileApplicationError("active handoff profile identity is missing")
    for field in (
        "profile_id",
        "profile_version",
        "device_id",
        "device_model",
        "array_id",
        "sample_rate_hz",
        "channel_order",
        "array_frame",
        "source_frame",
    ):
        if active.get(field) != profile.get(field):
            raise ProfileApplicationError(f"profile/handoff mismatch: {field}")
    if active.get("path") != EXPECTED_PROFILE_PATH:
        raise ProfileApplicationError("active handoff profile path is stale")
    if active.get("sha256") != EXPECTED_PROFILE_SHA256:
        raise ProfileApplicationError("active handoff profile hash is stale")
    if pointer["active_profile_id"] != profile.get("profile_id"):
        raise ProfileApplicationError("active pointer profile identity mismatch")
    if profile.get("profile_version") != "v2":
        raise ProfileApplicationError("historical v1 selection rejected")

    expected_context = {
        "device_id": profile.get("device_id"),
        "device_model": profile.get("device_model"),
        "array_id": profile.get("array_id"),
        "sample_rate_hz": profile.get("sample_rate_hz"),
        "channel_order": profile.get("channel_order"),
        "array_frame": profile.get("array_frame"),
        "source_frame": profile.get("source_frame"),
        "coordinate_convention": profile.get("coordinate_convention"),
        "mount_fixture_id": "S4_TEMP_DESKTOP_FIXTURE_REV0",
        "environment_tags": profile.get("applicability_limits", {}).get(
            "environment_tags"
        ),
        "functional_association_id": (
            "H2_x_reflection_front_back_position_binding"
        ),
        "functional_association_frame": "F_project",
        "functional_association_sha256": (
            "32ef116f6603639292569a53b590bd56a9ee871363e6a928ea59f5aed6d8db50"
        ),
        "geometry_measurement_status": "nominal_not_measured",
    }
    if dict(context) != expected_context:
        raise ProfileApplicationError(
            "application context is incomplete, incompatible, or stale"
        )
    guards = handoff.get("application_guards")
    if not isinstance(guards, Mapping) or dict(guards) != {
        "match_policy": (
            "exact_profile_hash_device_array_sample_rate_channel_order_"
            "frames_environment"
        ),
        "environment_tags": context["environment_tags"],
        "mismatch_disposition": "reject_before_partial_use",
    }:
        raise ProfileApplicationError("active handoff application guards mismatch")
    if tuple(handoff.get("supported_for_later_application", ())) != (
        EXPECTED_SUPPORTED_FIELDS
    ):
        raise ProfileApplicationError("supported-field declarations changed")
    if tuple(handoff.get("unsupported_or_omitted", ())) != (
        EXPECTED_UNSUPPORTED_FIELDS
    ):
        raise ProfileApplicationError("unsupported-field declarations changed")
    counts = handoff.get("retained_count_semantics")
    if not isinstance(counts, Mapping) or dict(counts) != {
        "legacy_profile_metric_name": "retained_parameter_count",
        "legacy_profile_metric_status": "superseded_ambiguous_total_do_not_apply",
        "legacy_profile_metric_value": 7,
        "retained_functional_association_count": 1,
        "retained_scalar_profile_parameter_count": 6,
        "retained_scientific_component_count": 7,
    }:
        raise ProfileApplicationError("retained-count semantics are incompatible")
    if handoff.get("holdout_observations_accessed") != 0:
        raise ProfileApplicationError("bundle reports forbidden holdout access")
    if handoff.get("later_phases_started") != []:
        raise ProfileApplicationError("bundle reports forbidden later-phase work")
    association = handoff.get("functional_channel_position_association")
    if not isinstance(association, Mapping):
        raise ProfileApplicationError("functional association is missing or malformed")
    _validate_association(association, context)
    _validate_profile_fields(profile)


def _validate_association(
    association: Mapping[str, Any], context: Mapping[str, Any]
) -> None:
    required = {
        "association_kind": "retained_functional_channel_position_association",
        "evidence_status": "supported_fitted_functional_evidence",
        "frame": context["functional_association_frame"],
        "geometry_measurement_status": "nominal_not_measured",
        "not_measured_geometry": True,
        "not_mirrored_f_project": True,
        "not_physically_traced_wiring": True,
        "not_scalar_bearing_correction": True,
        "selected_hypothesis_id": context["functional_association_id"],
        "selection_partition": "fit_a",
        "validation_partition": "fit_b",
    }
    for key, value in required.items():
        if association.get(key) != value:
            raise ProfileApplicationError(f"functional association mismatch: {key}")
    mapping = association.get("mapping")
    if not isinstance(mapping, list):
        raise ProfileApplicationError("functional association mapping is malformed")
    digest = hashlib.sha256(
        json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != context["functional_association_sha256"]:
        raise ProfileApplicationError(
            "functional association geometry identity changed"
        )


def _validate_profile_fields(profile: Mapping[str, Any]) -> None:
    channels = profile.get("channels")
    if not isinstance(channels, list) or len(channels) != 4:
        raise ProfileApplicationError("profile channels are missing or partial")
    if [row.get("channel_id") for row in channels] != ["ch0", "ch1", "ch2", "ch3"]:
        raise ProfileApplicationError("profile channel order is malformed")
    expected_scalars = []
    for index, channel in enumerate(channels):
        expected_status = "nominal_not_measured" if index == 0 else "measured"
        for field in ("gain_db", "polarity"):
            scalar = channel.get(field)
            if (
                not isinstance(scalar, Mapping)
                or scalar.get("status") != expected_status
            ):
                raise ProfileApplicationError(
                    f"profile supported field is partial or ambiguous: "
                    f"channels.ch{index}.{field}"
                )
        if index > 0:
            expected_scalars.extend(
                (
                    (
                        f"relative_gain_db.ch{index}",
                        "dB",
                        channel["gain_db"]["value"],
                    ),
                    (
                        f"polarity.ch{index}",
                        "multiplier",
                        channel["polarity"]["value"],
                    ),
                )
            )
        if channel["delay_s"]["status"] not in {
            "nominal_not_measured",
            "unmeasured",
        }:
            raise ProfileApplicationError(
                "unsupported relative delay became applicable"
            )
        if channel["frequency_response"]["status"] != "unsupported":
            raise ProfileApplicationError(
                "unsupported frequency response became applicable"
            )
    fitted = profile.get("fitted_model_parameters")
    if not isinstance(fitted, list) or len(fitted) != 6:
        raise ProfileApplicationError(
            "unknown, missing, or partial fitted parameters rejected"
        )
    actual_scalars = [
        (row.get("name"), row.get("unit"), row.get("estimate", {}).get("value"))
        for row in fitted
    ]
    if actual_scalars != expected_scalars:
        raise ProfileApplicationError("fitted parameter declarations are inconsistent")
    if profile.get("holdout_metrics") != []:
        raise ProfileApplicationError("holdout metrics must remain unopened and empty")
    metric = next(
        (
            row
            for row in profile.get("fit_metrics", ())
            if row.get("name") == "retained_parameter_count"
        ),
        None,
    )
    if metric != {
        "name": "retained_parameter_count",
        "unit": "parameter",
        "value": 7.0,
    }:
        raise ProfileApplicationError("legacy retained-count metric changed")


def _validate_runtime_context(
    config: AudioSensorConfig, context: Mapping[str, Any]
) -> None:
    if set(config.arrays) != {context["array_id"]}:
        raise ProfileApplicationError(
            "S4.6 requires exactly the compatible target array"
        )
    array = config.arrays[context["array_id"]]
    order = tuple(mic.mic_id for mic in array.microphones)
    if order != tuple(context["channel_order"]):
        label = (
            "channel count"
            if len(order) != len(context["channel_order"])
            else "channel order"
        )
        raise ProfileApplicationError(f"runtime {label} mismatch")
    if array.array_id != context["array_id"]:
        raise ProfileApplicationError("runtime array identity mismatch")
    if array.sample_rate_hz != context["sample_rate_hz"]:
        raise ProfileApplicationError("runtime sample rate mismatch")
    if config.sample_rate_hz != context["sample_rate_hz"]:
        raise ProfileApplicationError("global sample rate mismatch")
    if array.coordinate_convention != context["coordinate_convention"]:
        raise ProfileApplicationError("runtime coordinate convention mismatch")
    if config.runtime_profile != "waveform_fidelity":
        raise ProfileApplicationError(
            "S4.6 application requires scalar waveform_fidelity runtime"
        )
    if config.lab.get("enabled") is True:
        raise ProfileApplicationError(
            "S4.6 active channel response is unsupported by Isaac Lab batched mode"
        )
    response = config.effects.channel_response
    if response.enabled or response.microphones:
        raise ProfileApplicationError(
            "channel response is already active; double application rejected"
        )


def _compute_plan(
    profile: Mapping[str, Any], handoff: Mapping[str, Any]
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    channels = {row["channel_id"]: row for row in profile["channels"]}
    plan: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for channel_id in ("ch1", "ch2", "ch3"):
        gain_field = f"channels.{channel_id}.gain_db"
        polarity_field = f"channels.{channel_id}.polarity"
        plan.extend(
            (
                {
                    "field": gain_field,
                    "operation": "set_channel_response_gain_db",
                    "value": channels[channel_id]["gain_db"]["value"],
                    "unit": "dB",
                },
                {
                    "field": polarity_field,
                    "operation": "set_channel_response_polarity",
                    "value": int(channels[channel_id]["polarity"]["value"]),
                    "unit": "multiplier",
                },
            )
        )
        statuses.extend(
            (
                _status(gain_field, "applied", "measured supported S4.5 correction"),
                _status(
                    polarity_field,
                    "applied",
                    "measured supported S4.5 unity polarity",
                ),
            )
        )
    association = handoff["functional_channel_position_association"]
    plan.append(
        {
            "field": "functional_channel_position_association",
            "operation": "replace_runtime_functional_positions",
            "frame": association["frame"],
            "mapping": association["mapping"],
            "geometry_measurement_status": association[
                "geometry_measurement_status"
            ],
        }
    )
    statuses.append(
        _status(
            "functional_channel_position_association",
            "applied",
            "fitted functional association; coordinates remain nominal",
        )
    )
    for field in (
        "channels.ch0.gain_db",
        "channels.ch0.delay_s",
        "channels.ch0.polarity",
        "microphone_geometry.*.position_m",
    ):
        statuses.append(
            _status(field, "nominal", "reference or nominal value is not a correction")
        )
    for field in (
        "channels.ch1.delay_s",
        "channels.ch2.delay_s",
        "channels.ch3.delay_s",
        "microphone_geometry.*.uncertainty_m",
        "temperature_c",
    ):
        statuses.append(
            _status(field, "unmeasured", "no measured value is authorized to apply")
        )
    for field in EXPECTED_UNSUPPORTED_FIELDS:
        statuses.append(
            _status(field, "unsupported", "S4.5 handoff forbids application")
        )
    return tuple(plan), tuple(statuses)


def _status(field: str, status: str, reason: str) -> dict[str, Any]:
    return {"field": field, "status": status, "reason": reason}


def _resolve_repo_file(repo_root: Path, value: str | Path) -> Path:
    text = str(value)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or "\\" in text
    ):
        raise ProfileApplicationError(f"unsafe repository-relative path: {text!r}")
    candidate = (repo_root / posix).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ProfileApplicationError(
            f"path escapes repository root: {text!r}"
        ) from exc
    if not candidate.is_file():
        raise ProfileApplicationError(f"required bundle member is missing: {text!r}")
    return candidate


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileApplicationError(f"{label} is malformed: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileApplicationError(f"{label} must be a JSON object")
    return value


def _validate_json_schema(
    instance: Mapping[str, Any], schema: Mapping[str, Any], label: str
) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ProfileApplicationError(
            "jsonschema is required for S4.6 application validation"
        ) from exc
    try:
        jsonschema.validate(dict(instance), dict(schema))
    except jsonschema.ValidationError as exc:
        raise ProfileApplicationError(
            f"{label} schema validation failed: {exc.message}"
        ) from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "APPLICATION_CONFIG_PATH",
    "ACTIVE_POINTER_PATH",
    "ProfileApplicationError",
    "ProfileApplicationResult",
    "apply_profile_application",
]
