"""Backend interface and registry."""

from __future__ import annotations

from typing import cast

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.plugins.protocols import PropagationBackend
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
)


def get_backend(backend_id: str, **kwargs: object) -> PropagationBackend:
    """Instantiate a backend by public id."""

    from isaac_audio_sensors.core.plugins.registry import get_default_registry

    if backend_id not in registered_backend_ids():
        raise ValueError(f"Unknown audio simulation backend {backend_id!r}.")
    factory_kwargs = dict(kwargs)
    device = str(factory_kwargs.pop("device", "cpu"))
    runtime_profile = str(
        factory_kwargs.get("runtime_profile", DEFAULT_RUNTIME_PROFILE)
    )
    backend = get_default_registry().resolve(
        "propagation_backend",
        backend_id,
        device=device,
        runtime_profile=runtime_profile,
        factory_kwargs=factory_kwargs,
    )
    return cast(PropagationBackend, backend)


def registered_backend_ids() -> tuple[str, ...]:
    """Return registered propagation backend ids in fidelity order."""

    from isaac_audio_sensors.core.plugins.registry import get_default_registry

    declarations = get_default_registry().declarations("propagation_backend")
    return tuple(
        declaration.plugin_id
        for declaration in sorted(
            declarations,
            key=lambda item: (item.fidelity_level or "", item.plugin_id),
        )
    )


def _simulate_legacy_frame(
    backend: PropagationBackend,
    scene: AudioSceneSnapshot,
    array_id: str,
    time_window: AudioTimeWindow,
) -> AudioSensorFrame:
    """Run the temporary pre-02.1 scene-to-frame backend bridge."""

    simulate = getattr(backend, "simulate", None)
    if not callable(simulate):
        raise TypeError(
            "The selected propagation backend does not implement the temporary "
            "legacy frame bridge."
        )
    frame = simulate(scene, array_id, time_window)
    if not isinstance(frame, AudioSensorFrame):
        raise TypeError("The legacy backend bridge must return AudioSensorFrame.")
    return frame


__all__ = ["get_backend", "registered_backend_ids"]
