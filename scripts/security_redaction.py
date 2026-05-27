"""Shared redaction helpers for diagnostic and discovery tooling."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTION_MARKER = "<redacted>"

SENSITIVE_KEY_PARTS = (
    "TOKEN",
    "SECRET",
    "KEY",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
    "AUTH",
    "BEARER",
)

_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[\w.-]*(?:TOKEN|SECRET|KEY|PASSWORD|PASS|CREDENTIAL|AUTH|BEARER)"
    r"[\w.-]*\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")
_URL_PASSWORD_RE = re.compile(r"(://[^:/\s]+:)([^@\s/]+)(@)")


def is_sensitive_key(name: str) -> bool:
    """Return True when an environment or config key is secret-like."""

    upper_name = name.upper()
    return any(part in upper_name for part in SENSITIVE_KEY_PARTS)


def redact_text(value: Any) -> str:
    """Redact token-like content from arbitrary diagnostic text."""

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)

    text = _BEARER_RE.sub(r"\1" + REDACTION_MARKER, text)
    text = _ASSIGNMENT_RE.sub(r"\1" + REDACTION_MARKER, text)
    return _URL_PASSWORD_RE.sub(r"\1" + REDACTION_MARKER + r"\3", text)


def redact_value_for_key(name: str, value: Any) -> str | None:
    """Redact a value when the key is sensitive, otherwise scan the value."""

    if value is None:
        return None
    if is_sensitive_key(name):
        return REDACTION_MARKER
    return redact_text(value)


def redact_mapping_values(mapping: Mapping[str, Any]) -> dict[str, str | None]:
    """Return a copy with sensitive values redacted by key and content."""

    return {key: redact_value_for_key(key, value) for key, value in mapping.items()}
