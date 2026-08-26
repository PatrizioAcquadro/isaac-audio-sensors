"""Shared JSON Schema fragments."""

from __future__ import annotations

from typing import Any


def _stable_id_schema() -> dict[str, str]:
    return {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    }


def _sha256_schema() -> dict[str, str]:
    return {"type": "string", "pattern": "^[0-9a-f]{64}$"}


def _relative_path_schema() -> dict[str, str | int]:
    return {
        "type": "string",
        "minLength": 1,
        "pattern": "^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\\.\\.(?:/|$))[^\\\\]+$",
    }


def _fixed_number_array(length: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": length,
        "maxItems": length,
        "items": {"type": "number"},
    }


def _constant_units_schema(units: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(units),
        "properties": {
            key: {"type": "string", "const": value}
            for key, value in sorted(units.items())
        },
    }
