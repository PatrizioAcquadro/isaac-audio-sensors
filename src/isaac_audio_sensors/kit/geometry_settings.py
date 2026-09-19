"""Serializable operating settings mapped to the existing native configurations."""

from dataclasses import dataclass, fields

from isaac_audio_sensors.isaac.acoustic_scene import (
    GeometryAcousticsConfig,
    PRADiffuseConfig,
    SteamNLOSConfig,
)


@dataclass(slots=True)
class GeometrySettings:
    geometry_roots: str = ""
    geometry_library_path: str = ""
    geometry_specular_library_path: str = ""
    geometry_frame_samples: int = 128
    geometry_reflection_order: int = 3
    geometry_max_image_candidates: int = 1_000_000
    geometry_max_delay_s: float = 1.0
    geometry_transition_samples: int = 32
    geometry_diagnostics: bool = False
    geometry_nlos_enabled: bool = False
    geometry_nlos_probe_spacing_m: float = 1.0
    geometry_nlos_probe_height_m: float = 1.2
    geometry_nlos_max_probes: int = 4096
    geometry_nlos_update_hz: int = 100
    geometry_diffuse_enabled: bool = False
    geometry_diffuse_seed: int = 0
    geometry_diffuse_rays: int = 16384
    geometry_diffuse_surface_spacing_m: float = 0.25
    geometry_diffuse_tail_spacing_m: float = 1.0
    geometry_diffuse_time_bin_s: float = 0.004
    geometry_diffuse_direction_modes: int = 64
    geometry_diffuse_specular_concentration: float = 64.0
    geometry_diffuse_max_events: int = 8_000_000
    geometry_diffuse_max_nodes: int = 100_000


def geometry_settings(state):
    return {
        f.name.removeprefix("geometry_"): getattr(state, f.name)
        for f in fields(GeometrySettings)
    }


def parse_geometry_settings(payload):
    """Validate before changing UI state, including inactive saved options."""
    if not isinstance(payload, dict):
        raise ValueError("geometry_acoustics must be an object.")
    defaults = GeometrySettings()
    known = geometry_settings(defaults)
    if extra := payload.keys() - known.keys():
        raise ValueError(f"Unknown geometry settings: {sorted(extra)}")
    for name, value in payload.items():
        expected = type(known[name])
        if expected is float:
            valid = type(value) in (float, int)
        else:
            valid = type(value) is expected
        if not valid:
            raise ValueError(f"Geometry {name} must be {expected.__name__}.")
        setattr(defaults, "geometry_" + name, value)
    roots = defaults.geometry_roots.split()
    if any(not p.startswith("/") for p in roots):
        raise ValueError("Geometry roots must be absolute USD prim paths.")
    # Incomplete library paths are saveable; configuration requires real paths.
    config_from_state(defaults, allow_incomplete=True)
    for cls, prefix in ((SteamNLOSConfig, "nlos_"), (PRADiffuseConfig, "diffuse_")):
        cls(
            **{
                f.name: getattr(defaults, "geometry_" + prefix + f.name)
                for f in fields(cls)
            }
        )
    return defaults


def config_from_state(state, *, allow_incomplete=False):
    values = {
        f.name: getattr(state, "geometry_" + f.name)
        for f in fields(GeometryAcousticsConfig)
        if f.name not in {"nlos", "diffuse", "air_absorption"}
    }
    if allow_incomplete:
        for name in ("library_path", "specular_library_path"):
            values[name] = values[name] or "unconfigured"
    for name, cls in (("nlos", SteamNLOSConfig), ("diffuse", PRADiffuseConfig)):
        values[name] = (
            cls(
                **{
                    f.name: getattr(state, f"geometry_{name}_{f.name}")
                    for f in fields(cls)
                }
            )
            if getattr(state, f"geometry_{name}_enabled")
            else None
        )
    return GeometryAcousticsConfig(**values)
