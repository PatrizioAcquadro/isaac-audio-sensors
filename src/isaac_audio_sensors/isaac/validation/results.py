"""Dependency-free validation result types shared by Isaac interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One stable, user-facing validation result."""

    check_id: str
    severity: Literal["error", "warning"]
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Ordered findings from one validation workflow."""

    findings: tuple[ValidationFinding, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the report contains no error finding."""

        return not any(finding.severity == "error" for finding in self.findings)


__all__ = ["ValidationFinding", "ValidationReport"]
