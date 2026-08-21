"""Shared support for internal Kit services."""

from __future__ import annotations

from typing import Any

from .state import ExtensionActionError
from .validation import ValidationReport


def _raise_first(report: ValidationReport) -> None:
    for finding in report.findings:
        if finding.severity == "error":
            raise ExtensionActionError(finding.message)


class ControllerService:
    """Resolve coordinator state and private sibling operations."""

    def __init__(self, host: object) -> None:
        self._host = host

    @property
    def _guided_last_run_frame_id(self) -> str | None:
        recording = vars(self._host).get("_recording")
        if recording is None or recording is self:
            return vars(self).get("_guided_last_run_frame_id_value")
        return recording._guided_last_run_frame_id

    @_guided_last_run_frame_id.setter
    def _guided_last_run_frame_id(self, value: str | None) -> None:
        recording = vars(self._host).get("_recording")
        if recording is None or recording is self:
            vars(self)["_guided_last_run_frame_id_value"] = value
        else:
            recording._guided_last_run_frame_id = value

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._host._set_status(message, error=error)

    def _record_error(self, context: str, exc: BaseException) -> None:
        self._host._record_error(context, exc)

    def __getattr__(self, name: str) -> Any:
        host = object.__getattribute__(self, "_host")
        host_vars = vars(host)
        if name in host_vars:
            return host_vars[name]
        descriptor = _descriptor(type(host), name)
        if descriptor is not None:
            return descriptor.__get__(host, type(host))
        for key in (
            "_recording",
            "_lifecycle",
            "_authoring",
            "_sensor_session",
            "_configuration",
            "_replicator",
        ):
            service = host_vars.get(key)
            if service is None or service is self:
                continue
            service_vars = vars(service)
            if name in service_vars:
                return service_vars[name]
            descriptor = _descriptor(type(service), name)
            if descriptor is not None:
                return descriptor.__get__(service, type(service))
        raise AttributeError(name)


def _descriptor(owner: type[object], name: str) -> Any | None:
    for base in owner.__mro__:
        if name in vars(base):
            return vars(base)[name]
    return None
