"""Shared native geometry fixtures."""

from pathlib import Path

from pxr import Usd, UsdGeom

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import AudioSceneSnapshot, AudioTimeWindow
from isaac_audio_sensors.isaac.acoustic_scene.propagation import (
    GeometryAcoustics,
    GeometryAcousticsConfig,
)
from tests.helpers import source

LIBRARY = (
    Path(__file__).resolve().parents[2]
    / "build/qualification/r9/steam-audio/core/build/r9-release/src/core/libphonon.so"
)
SPECULAR_LIBRARY = (
    Path(__file__).resolve().parents[2] / "build/native/libias_specular.so"
)


def window(start=0, end=0.1, index=0):
    return AudioTimeWindow(start_time_s=start, end_time_s=end, frame_index=index)


def stage():
    result = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(result, 1)
    UsdGeom.SetStageUpAxis(result, "Z")
    return result


def scene():
    array = create_microphone_array(
        array_id="array",
        prim_path="/Array",
        layout_name="quad_cross",
        sample_rate_hz=16000,
    )
    return AudioSceneSnapshot(
        stage_id="geometry-test",
        arrays=(array,),
        sources=(source("tone", (2, 0, 0), audio_asset_path="generated://tone"),),
        environment=free_field_environment(environment_id="free"),
    )


def backend(prepared, **kwargs):
    return GeometryAcoustics(
        acoustic_scene=prepared,
        geometry_config=GeometryAcousticsConfig(
            library_path=str(LIBRARY),
            specular_library_path=str(SPECULAR_LIBRARY),
            **kwargs,
        ),
    )
