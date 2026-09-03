from __future__ import annotations

from dataclasses import replace

import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.types import AudioSceneSnapshot, SourceOcclusion
from tests.helpers import quad_array, run_frame_pipeline, source, time_window


def _scene(*, occlusion=None) -> AudioSceneSnapshot:
    array = quad_array()
    return AudioSceneSnapshot(
        stage_id="occlusion_unit",
        sources=(source("speaker", (4.0, 0.0, 0.0)),),
        arrays=(array,),
        environment=free_field_environment(environment_id="occlusion_free_field"),
        occlusion=occlusion,
    )


def _record() -> SourceOcclusion:
    per_mic_db = {mic.mic_id: 0.0 for mic in quad_array().microphones}
    per_mic_db["front"] = 20.0
    return SourceOcclusion(
        array_id="rig",
        source_id="speaker",
        per_mic_blocked={
            mic_id: loss_db > 0.0 for mic_id, loss_db in per_mic_db.items()
        },
        per_mic_attenuation_db=per_mic_db,
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"per_mic_attenuation_db": {"front": -1.0}}, "non-negative"),
        ({"per_mic_attenuation_db": {"rear": 0.0}}, "exactly"),
        (
            {
                "per_mic_band_attenuation_db": {"front": (1.0, 2.0)},
                "band_centers_hz": OCCLUSION_BAND_CENTERS_HZ,
            },
            "band_centers_hz length",
        ),
        (
            {
                "per_mic_blocked": {"front": False},
                "per_mic_attenuation_db": {"front": 1.0},
            },
            "unblocked microphones",
        ),
    ],
)
def test_source_occlusion_rejects_invalid_values(kwargs, message):
    values = {
        "per_mic_blocked": {"front": True},
        "per_mic_attenuation_db": {"front": 1.0},
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        SourceOcclusion(array_id="rig", source_id="speaker", **values)


def test_source_occlusion_requires_per_microphone_contract() -> None:
    with pytest.raises(TypeError, match="per_mic_blocked"):
        SourceOcclusion(array_id="rig", source_id="speaker")


@pytest.mark.parametrize(
    "removed_field",
    ["occlusion_model", "per_mic_hit_prim_paths", "hit_materials"],
)
def test_source_occlusion_removed_fields_have_no_alias(removed_field) -> None:
    values = {
        "array_id": "rig",
        "source_id": "speaker",
        "per_mic_blocked": {"front": True},
        "per_mic_attenuation_db": {"front": 1.0},
        removed_field: "removed",
    }
    with pytest.raises(TypeError, match=removed_field):
        SourceOcclusion(**values)


def test_scene_rejects_duplicate_occlusion_records_and_resolves_valid_pair():
    record = _record()
    scene = _scene(occlusion=(record,))

    assert scene.occlusion_for("rig", "speaker") is record
    assert scene.occlusion_for("rig", "unknown") is None
    with pytest.raises(ValueError, match="occlusion record id"):
        replace(scene, occlusion=(record, record))

    mismatched = replace(
        record,
        per_mic_blocked={"front": True},
        per_mic_attenuation_db={"front": 20.0},
    )
    with pytest.raises(ValueError, match="microphone ids"):
        _scene(occlusion=(mismatched,))


def test_analytic_backend_applies_per_mic_attenuation_independently():
    array = quad_array()
    baseline = AnalyticAcoustics().propagate(
        _scene(), array.array_id, time_window()
    )
    attenuated = AnalyticAcoustics().propagate(
        _scene(occlusion=(_record(),)), array.array_id, time_window()
    )

    baseline_rms = {
        mic_id: float((baseline.samples[index] ** 2).mean() ** 0.5)
        for index, mic_id in enumerate(baseline.microphone_ids)
    }
    attenuated_rms = {
        mic_id: float((attenuated.samples[index] ** 2).mean() ** 0.5)
        for index, mic_id in enumerate(attenuated.microphone_ids)
    }
    assert attenuated_rms["front"] == pytest.approx(0.1 * baseline_rms["front"])
    for mic_id in set(baseline_rms) - {"front"}:
        assert attenuated_rms[mic_id] == pytest.approx(baseline_rms[mic_id])


def test_analytic_backend_attenuates_rms_without_oracle_observations():
    array = quad_array()
    backend = AnalyticAcoustics()
    baseline, _ = run_frame_pipeline(
        backend, _scene(), array.array_id, time_window()
    )
    attenuated, _ = run_frame_pipeline(
        backend,
        _scene(occlusion=(_record(),)), array.array_id, time_window()
    )

    assert attenuated.aggregate_per_mic_rms["front"] == pytest.approx(
        0.1 * baseline.aggregate_per_mic_rms["front"]
    )
    assert baseline.observations == attenuated.observations == ()
