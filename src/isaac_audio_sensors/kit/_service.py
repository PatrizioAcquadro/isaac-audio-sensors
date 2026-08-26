"""Shared support for internal Kit services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .state import ExtensionActionError, ExtensionUiState
from .validation import ValidationController, ValidationReport

if TYPE_CHECKING:
    from .controller import ExtensionController


def _raise_first(report: ValidationReport) -> None:
    for finding in report.findings:
        if finding.severity == "error":
            raise ExtensionActionError(finding.message)


class ControllerService:
    """Share controller state, validation, and status reporting."""

    def __init__(self, host: ExtensionController) -> None:
        self._host = host

    @property
    def state(self) -> ExtensionUiState:
        return self._host.state

    @property
    def _validation(self) -> ValidationController:
        return self._host._validation

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._host._set_status(message, error=error)

    def _record_error(self, context: str, exc: BaseException) -> None:
        self._host._record_error(context, exc)
