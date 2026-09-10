"""Selection and coefficient editing shared by the Kit preparation controls."""

from isaac_audio_sensors.core.acoustics.materials import resample_coefficients
from isaac_audio_sensors.isaac.acoustic_scene.materials import ATTRS


def selected_objects(session, paths):
    """Include imported descendants when the viewport selects a component root."""
    return tuple(
        obj
        for path, obj in session.objects.items()
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in paths)
    )


def selection_curves(objects):
    """Return a common effective curve per family, or 'mixed' across faces/objects."""
    result = {}
    for family, key in ATTRS.items():
        curves = [getattr(m, family) for obj in objects for m in obj.materials]
        if not curves:
            result[key] = None
            continue
        signatures = {(c.values, c.frequencies) if c else None for c in curves}
        result[key] = curves[0] if len(signatures) == 1 else "mixed"
    return result


def coefficient_changes(fields, frequencies, dirty):
    """Validate the entire pending edit before authoring any USD property."""
    if not dirty:
        raise ValueError("Change at least one coefficient or its frequencies first")
    values = {}
    for key in dirty:
        text = fields[key].strip()
        if not text or text == "Mixed":
            raise ValueError(
                "Enter coefficients; use Reset override to restore automatic values"
            )
        numbers = tuple(float(v) for v in text.split())
        centers = (
            (1000.0,)
            if len(numbers) == 1
            else tuple(float(v) for v in frequencies[key].split())
        )
        resample_coefficients(numbers, centers, centers)
        if any(v < 0 or (key != ATTRS["transmission_db"] and v > 1) for v in numbers):
            raise ValueError(
                "Absorption/scattering must be in [0, 1]; loss must be nonnegative"
            )
        values[key] = numbers[0] if len(numbers) == 1 else None
        values[key + "_bands"] = numbers if len(numbers) > 1 else None
        values[key + "_frequencies_hz"] = centers if len(numbers) > 1 else None
    return values


def coefficient_reset(key):
    values = dict.fromkeys((key, key + "_bands", key + "_frequencies_hz"))
    if key == ATTRS["scattering"]:
        values["ias:scattering_material_id"] = None
    return values
