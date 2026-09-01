"""Public acoustic fidelity ladder metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AcousticFidelityLevel(str, Enum):
    """Package acoustic fidelity ladder levels."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


@dataclass(frozen=True, slots=True)
class AcousticFidelityMetadata:
    """Compatibility metadata for one acoustic fidelity ladder level."""

    level: AcousticFidelityLevel
    public_name: str
    lifecycle_status: str
    backend_ids: tuple[str, ...]
    backend_family: str
    models: tuple[str, ...]
    does_not_model: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    frame_contract: str
    runtime_selectable_v1: bool


ACOUSTIC_FIDELITY_LADDER = (
    AcousticFidelityMetadata(
        level=AcousticFidelityLevel.L2,
        public_name="analytic_acoustics",
        lifecycle_status="supported_optional_v1",
        backend_ids=("analytic_acoustics",),
        backend_family="analytic_acoustics",
        models=(
            "Core direct-path free-field propagation",
            "Core half-space image-source floor reflection",
            "optional PyRoom shoebox and polygon-prism room responses",
            "environment-local coordinates and per-surface materials",
            "generated per-microphone waveforms",
            "asset-amplitude source gain and post-propagation microphone gain",
            "signed first-order omni, cardioid, supercardioid, and figure_eight "
            "source and microphone directivity on complete pair stems",
            "GCC-PHAT delay diagnostics",
            "SRP-PHAT steered-response DOA over the L2 waveforms",
        ),
        does_not_model=(
            "calibrated acoustic twins",
            "arbitrary open surface-set propagation",
            "diffraction or a complete wave solver",
            "reflected-path angular directivity (per_pair_direct_path uses the "
            "direct-path angle for the full convolved pair stem)",
            "diffuse-field noise coherence",
            "measured material transmission (measured materials cover absorption "
            "only; transmission presets are nominal)",
            "calibrated microphone response",
            "production beamforming",
        ),
        optional_dependencies=("room", "pyroomacoustics", "scipy", "soundfile"),
        frame_contract=(
            "emits AudioSensorFrame v1 records when optional dependencies are "
            "installed"
        ),
        runtime_selectable_v1=True,
    ),
    AcousticFidelityMetadata(
        level=AcousticFidelityLevel.L3,
        public_name="advanced_realism",
        lifecycle_status="provisional_v1",
        backend_ids=(),
        backend_family="advanced_realism",
        models=(
            "opt-in Isaac-layer raycast occlusion attenuation "
            "(first shipped L3 capability)",
            "future richer wave and RIR diagnostics",
            "future material, directivity, noise, and estimator realism",
        ),
        does_not_model=(
            "a complete v1 runtime backend",
            "diffraction, edge bending, reflected-path occlusion, or a complete "
            "wave solver",
            "reflected-path angular directivity (per_pair_direct_path uses the "
            "direct-path angle for the full convolved pair stem)",
            "diffuse-field noise coherence",
            "measured material transmission (measured materials cover absorption "
            "only; transmission presets are nominal)",
            "calibrated sim-real acoustic behavior",
            "production perception or speech recognition",
        ),
        optional_dependencies=("future advanced-acoustics extras",),
        frame_contract=(
            "future implementations must emit AudioSensorFrame v1-compatible "
            "records until a new schema version is introduced"
        ),
        runtime_selectable_v1=False,
    ),
    AcousticFidelityMetadata(
        level=AcousticFidelityLevel.L4,
        public_name="sim_real_calibration",
        lifecycle_status="experimental_tooling_v1",
        backend_ids=(),
        backend_family="sim_real_calibration",
        models=(
            "future measured array pose, gain, time-offset, and noise calibration",
            "future validation artifacts and sim-vs-real comparison tooling",
        ),
        does_not_model=(
            "a stable v1 runtime backend",
            "automatic hardware calibration",
            "guaranteed transfer to a physical robot",
        ),
        optional_dependencies=("future calibration-tooling extras",),
        frame_contract=(
            "future artifacts and diagnostics must stay optional for "
            "AudioSensorFrame v1 readers"
        ),
        runtime_selectable_v1=False,
    ),
)

_FIDELITY_BY_BACKEND = {
    backend_id: metadata
    for metadata in ACOUSTIC_FIDELITY_LADDER
    for backend_id in metadata.backend_ids
}


def fidelity_level_for_backend(backend_id: str) -> AcousticFidelityMetadata:
    """Return acoustic fidelity metadata for an implemented v1 backend id."""

    try:
        return _FIDELITY_BY_BACKEND[backend_id]
    except KeyError as exc:
        known = ", ".join(sorted(_FIDELITY_BY_BACKEND))
        raise ValueError(
            f"Unknown implemented v1 audio backend {backend_id!r}; "
            f"expected one of: {known}."
        ) from exc


__all__ = [
    "ACOUSTIC_FIDELITY_LADDER",
    "AcousticFidelityLevel",
    "AcousticFidelityMetadata",
    "fidelity_level_for_backend",
]
