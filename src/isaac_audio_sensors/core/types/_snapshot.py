"""Scene snapshot and source-array occlusion contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from isaac_audio_sensors.core.types._environment import AcousticEnvironmentSpec
from isaac_audio_sensors.core.types._scene import AudioSourceSpec, MicrophoneArraySpec
from isaac_audio_sensors.core.types._validation import (
    coerce_float_dict,
    require_finite,
    require_non_empty,
    require_unique_ids,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceOcclusion:
    """Per-source occlusion of the direct source-to-array paths.

    Computed outside the pure core (e.g. by Isaac-layer raycasts); backends
    only consume it. ``per_mic_attenuation_db`` carries broadband
    transmission loss for every microphone. Optional band rows replace the
    broadband value for that microphone and align with ``band_centers_hz``.
    Geometry paths, material resolution, and producing-model provenance stay
    outside this simulator-independent attenuation record.
    """

    array_id: str
    source_id: str
    per_mic_blocked: dict[str, bool]
    per_mic_attenuation_db: dict[str, float]
    per_mic_band_attenuation_db: dict[str, tuple[float, ...]] = field(
        default_factory=dict
    )
    band_centers_hz: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.array_id, "SourceOcclusion.array_id")
        require_non_empty(self.source_id, "SourceOcclusion.source_id")
        blocked = {
            str(mic_id): bool(value)
            for mic_id, value in dict(self.per_mic_blocked).items()
        }
        if not blocked:
            raise ValueError("SourceOcclusion.per_mic_blocked must not be empty.")
        for mic_id in blocked:
            require_non_empty(mic_id, "SourceOcclusion microphone id")
        object.__setattr__(
            self,
            "per_mic_blocked",
            blocked,
        )
        attenuation = coerce_float_dict(
            self.per_mic_attenuation_db,
            "SourceOcclusion.per_mic_attenuation_db",
            non_negative=True,
        )
        if set(attenuation) != set(blocked):
            raise ValueError(
                "SourceOcclusion.per_mic_attenuation_db must contain exactly "
                "the per_mic_blocked microphone ids."
            )
        object.__setattr__(
            self,
            "per_mic_attenuation_db",
            attenuation,
        )
        band_centers = tuple(float(center) for center in self.band_centers_hz)
        for center in band_centers:
            require_finite(center, "SourceOcclusion.band_centers_hz value")
            if center <= 0.0:
                raise ValueError(
                    "SourceOcclusion.band_centers_hz values must be positive."
                )
        if any(
            right <= left
            for left, right in zip(band_centers, band_centers[1:], strict=False)
        ):
            raise ValueError(
                "SourceOcclusion.band_centers_hz must be strictly increasing."
            )
        object.__setattr__(self, "band_centers_hz", band_centers)
        per_mic_bands: dict[str, tuple[float, ...]] = {}
        for mic_id, bands in dict(self.per_mic_band_attenuation_db).items():
            values = tuple(float(value) for value in bands)
            if len(values) != len(band_centers):
                raise ValueError(
                    "SourceOcclusion.per_mic_band_attenuation_db rows must "
                    "match band_centers_hz length."
                )
            for value in values:
                require_finite(
                    value, "SourceOcclusion.per_mic_band_attenuation_db value"
                )
                if value < 0.0:
                    raise ValueError(
                        "SourceOcclusion.per_mic_band_attenuation_db values "
                        "must be non-negative."
                    )
            per_mic_bands[str(mic_id)] = values
        if bool(per_mic_bands) != bool(band_centers):
            raise ValueError(
                "SourceOcclusion.band_centers_hz and "
                "per_mic_band_attenuation_db must be provided together."
            )
        if per_mic_bands and set(per_mic_bands) != set(blocked):
            raise ValueError(
                "SourceOcclusion.per_mic_band_attenuation_db must contain "
                "exactly the per_mic_blocked microphone ids."
            )
        object.__setattr__(self, "per_mic_band_attenuation_db", per_mic_bands)
        for mic_id, is_blocked in blocked.items():
            if is_blocked:
                continue
            if attenuation[mic_id] != 0.0:
                raise ValueError(
                    "SourceOcclusion unblocked microphones must have zero "
                    "broadband attenuation."
                )
            if any(per_mic_bands.get(mic_id, ())):
                raise ValueError(
                    "SourceOcclusion unblocked microphones must have zero "
                    "band attenuation."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSceneSnapshot:
    """Static scene state and canonical arrays consumed by simulation backends."""

    stage_id: str
    sources: tuple[AudioSourceSpec, ...]
    arrays: tuple[MicrophoneArraySpec, ...]
    environment: AcousticEnvironmentSpec
    occlusion: tuple[SourceOcclusion, ...] | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.stage_id, "AudioSceneSnapshot.stage_id")
        sources = tuple(self.sources)
        arrays = tuple(self.arrays)
        require_unique_ids([source.source_id for source in sources], "source id")
        require_unique_ids([array.array_id for array in arrays], "array id")
        if not isinstance(self.environment, AcousticEnvironmentSpec):
            raise ValueError(
                "AudioSceneSnapshot.environment must be an AcousticEnvironmentSpec."
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "arrays", arrays)
        if self.occlusion is not None:
            occlusion = tuple(self.occlusion)
            require_unique_ids(
                [f"{record.array_id}:{record.source_id}" for record in occlusion],
                "occlusion record id",
            )
            arrays_by_id = {array.array_id: array for array in arrays}
            source_ids = {source.source_id for source in sources}
            for record in occlusion:
                if record.array_id not in arrays_by_id:
                    raise ValueError(
                        "SourceOcclusion.array_id must reference a scene array."
                    )
                if record.source_id not in source_ids:
                    raise ValueError(
                        "SourceOcclusion.source_id must reference a scene source."
                    )
                expected_mic_ids = {
                    microphone.mic_id
                    for microphone in arrays_by_id[record.array_id].microphones
                }
                if set(record.per_mic_blocked) != expected_mic_ids:
                    raise ValueError(
                        "SourceOcclusion microphone ids must match the referenced "
                        "array."
                    )
            object.__setattr__(self, "occlusion", occlusion)

    def array_by_id(self, array_id: str) -> MicrophoneArraySpec:
        """Return the canonical array by id or raise a clear error."""

        for array in self.arrays:
            if array.array_id == array_id:
                return array
        raise KeyError(f"AudioSceneSnapshot has no array {array_id!r}.")

    def occlusion_for(
        self,
        array_id: str,
        source_id: str,
    ) -> SourceOcclusion | None:
        """Return the occlusion record for one array/source pair, if any."""

        if self.occlusion is None:
            return None
        for record in self.occlusion:
            if record.array_id == array_id and record.source_id == source_id:
                return record
        return None
