"""Backend interface and registry."""

from __future__ import annotations

from typing import cast

from isaac_audio_sensors.core.plugins.protocols import PropagationBackend


def get_backend(backend_id: str, **kwargs: object) -> PropagationBackend:
    """Instantiate a backend by public id."""

    from isaac_audio_sensors.core.exceptions import ConfigValidationError
    from isaac_audio_sensors.core.plugins.registry import get_default_registry

    try:
        backend = get_default_registry().instantiate_registered(
            "propagation_backend",
            backend_id,
            **kwargs,
        )
    except ConfigValidationError as exc:
        raise ValueError(f"Unknown audio simulation backend {backend_id!r}.") from exc
    return cast(PropagationBackend, backend)
