"""Validated capability declarations for public audio plugins."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from isaac_audio_sensors.core.constants import RUNTIME_PROFILES
from isaac_audio_sensors.core.exceptions import ConfigValidationError

PLUGIN_KINDS = (
    "propagation_backend",
    "activity_detector",
    "doa_estimator",
    "audio_feature_extractor",
)
SUPPORTED_PLUGIN_DEVICES = frozenset({"cpu", "cuda"})
_FIDELITY_LEVELS = frozenset({"L0", "L1", "L2", "L3", "L4"})
_IMPORT_NAME_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


@dataclass(frozen=True, slots=True)
class PluginDeclaration:
    """Fail-closed, immutable declaration of one plugin's capabilities.

    ``output_contract`` always documents ``shape`` and ``dtype``. Propagation
    backends use the symbolic shape ``"MicrophoneSignalBlock"``. Activity
    detectors and DOA estimators use scalar shape ``()`` with their public
    result type. Feature extractors use a tuple of non-negative dimensions and
    a NumPy-compatible dtype name.
    """

    plugin_id: str
    kind: str
    fidelity_level: str | None
    required_dependencies: tuple[str, ...]
    supported_devices: tuple[str, ...]
    supported_profiles: tuple[str, ...]
    deterministic: bool
    output_contract: Mapping[str, object]
    description: str
    provenance: str

    def __post_init__(self) -> None:
        _require_identifier(self.plugin_id, "plugin_id")
        if self.kind not in PLUGIN_KINDS:
            raise ConfigValidationError(
                f"PluginDeclaration.kind must be one of {list(PLUGIN_KINDS)}."
            )
        if self.fidelity_level is not None:
            fidelity_level = getattr(self.fidelity_level, "value", self.fidelity_level)
            if fidelity_level not in _FIDELITY_LEVELS:
                raise ConfigValidationError(
                    "PluginDeclaration.fidelity_level must be one of "
                    f"{sorted(_FIDELITY_LEVELS)} or None."
                )
            object.__setattr__(self, "fidelity_level", fidelity_level)

        dependencies = _validated_tuple(
            self.required_dependencies,
            "required_dependencies",
            allowed=None,
            allow_empty=True,
        )
        for dependency in dependencies:
            if not _IMPORT_NAME_RE.fullmatch(dependency):
                raise ConfigValidationError(
                    "PluginDeclaration.required_dependencies entries must be "
                    f"valid import names; received {dependency!r}."
                )
        object.__setattr__(self, "required_dependencies", dependencies)

        devices = _validated_tuple(
            self.supported_devices,
            "supported_devices",
            allowed=SUPPORTED_PLUGIN_DEVICES,
            allow_empty=False,
        )
        object.__setattr__(self, "supported_devices", devices)
        profiles = _validated_tuple(
            self.supported_profiles,
            "supported_profiles",
            allowed=frozenset(RUNTIME_PROFILES),
            allow_empty=False,
        )
        object.__setattr__(self, "supported_profiles", profiles)

        if type(self.deterministic) is not bool:
            raise ConfigValidationError(
                "PluginDeclaration.deterministic must be a bool."
            )
        if not isinstance(self.output_contract, Mapping):
            raise ConfigValidationError(
                "PluginDeclaration.output_contract must be a mapping."
            )
        contract = dict(self.output_contract)
        missing_contract_fields = {"shape", "dtype"} - contract.keys()
        if missing_contract_fields:
            raise ConfigValidationError(
                "PluginDeclaration.output_contract is missing required fields: "
                f"{sorted(missing_contract_fields)}."
            )
        _validate_output_contract(self.kind, contract)
        object.__setattr__(self, "output_contract", MappingProxyType(contract))

        _require_text(self.description, "description")
        _require_text(self.provenance, "provenance")
        if not _IMPORT_NAME_RE.fullmatch(self.provenance):
            raise ConfigValidationError(
                "PluginDeclaration.provenance must be a Python module path."
            )


def _require_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} must be a non-empty string without "
            "whitespace."
        )


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} must be a non-empty string."
        )


def _validated_tuple(
    value: object,
    field_name: str,
    *,
    allowed: frozenset[str] | None,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} must be a tuple of strings."
        )
    normalized = tuple(value)
    if not allow_empty and not normalized:
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} must not be empty."
        )
    if any(not isinstance(item, str) or not item for item in normalized):
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} entries must be non-empty strings."
        )
    if len(set(normalized)) != len(normalized):
        raise ConfigValidationError(
            f"PluginDeclaration.{field_name} entries must be unique."
        )
    if allowed is not None:
        unsupported = sorted(set(normalized) - allowed)
        if unsupported:
            raise ConfigValidationError(
                f"PluginDeclaration.{field_name} contains unsupported values "
                f"{unsupported}; expected a subset of {sorted(allowed)}."
            )
    return normalized


def _validate_output_contract(kind: str, contract: dict[str, object]) -> None:
    shape = contract["shape"]
    dtype = contract["dtype"]
    if not isinstance(dtype, str) or not dtype.strip():
        raise ConfigValidationError(
            "PluginDeclaration.output_contract dtype must be a non-empty string."
        )
    if kind == "propagation_backend":
        if shape != "MicrophoneSignalBlock":
            raise ConfigValidationError(
                "Propagation backend output_contract shape must be "
                "'MicrophoneSignalBlock'."
            )
        if dtype != "MicrophoneSignalBlock":
            raise ConfigValidationError(
                "Propagation backend output_contract dtype must be "
                "'MicrophoneSignalBlock'."
            )
    elif kind in {"activity_detector", "doa_estimator"}:
        if shape not in ((), []):
            raise ConfigValidationError(
                f"{kind} output_contract shape must be scalar ()."
            )
        contract["shape"] = ()
        expected_dtype = (
            "ActivityDecision" if kind == "activity_detector" else "DoaEstimate"
        )
        if dtype != expected_dtype:
            raise ConfigValidationError(
                f"{kind} output_contract dtype must be {expected_dtype!r}."
            )
    else:
        if not isinstance(shape, (tuple, list)):
            raise ConfigValidationError(
                "Audio feature output_contract shape must be a fixed tuple."
            )
        normalized_shape = tuple(shape)
        if any(
            type(dimension) is not int or dimension < 0
            for dimension in normalized_shape
        ):
            raise ConfigValidationError(
                "Audio feature output_contract dimensions must be non-negative "
                "integers."
            )
        contract["shape"] = normalized_shape
        try:
            contract["dtype"] = np.dtype(dtype).name
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError(
                "Audio feature output_contract dtype must be NumPy-compatible."
            ) from exc


__all__ = [
    "PLUGIN_KINDS",
    "SUPPORTED_PLUGIN_DEVICES",
    "PluginDeclaration",
]
