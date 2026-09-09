"""Observed tensor semantics independent of a live simulation."""

from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import torch

from isaac_audio_sensors.core.types import (
    AudioObservation,
    DoaEstimate,
    ObservationOrigin,
)
from isaac_audio_sensors.lab.audio_array_sensor_cfg import AudioArraySensorCfg
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData


def _observation(**kwargs):
    return AudioObservation(
        observation_id="event",
        origin=ObservationOrigin.SIGNAL_DERIVED,
        detector_id="observed",
        **kwargs,
    )


def _consumer():
    path = (
        Path(__file__).parents[2] / "examples/isaac_lab/isaac_lab_audio_observation.py"
    )
    spec = spec_from_file_location("lab_example", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_presence_missing_scores_and_optional_doa():
    data = AudioArraySensorData.from_observations(
        [
            [],
            [_observation()],
            [_observation(detection_score=0.0)],
            [
                _observation(
                    doa=DoaEstimate(estimated_bearing_deg=0.0, bearing_confidence=0.7)
                )
            ],
        ],
        device="cpu",
    )
    assert data.observation_mask.tolist() == [[False], [True], [True], [True]]
    assert data.doa_mask.tolist() == [[False], [False], [False], [True]]
    assert data.detection_score_mask.tolist() == [[False], [False], [True], [False]]
    assert data.bearing_deg_mask.tolist() == [[False], [False], [False], [True]]
    assert data.bearing_confidence_mask.tolist() == data.doa_mask.tolist()
    assert not data.elevation_deg_mask.any()
    assert data.bearing_confidence[3, 0].item() == pytest.approx(0.7)
    for name in data.__dataclass_fields__:
        assert torch.isfinite(getattr(data, name)).all()
        assert not getattr(data, name)[0].any()


def test_ambiguous_candidates_are_not_events_or_selected_directions():
    ambiguous = _observation(
        doa=DoaEstimate(
            estimated_bearing_deg=None,
            candidate_bearing_deg=(25.0, 155.0, -40.0),
            candidate_elevation_deg=(10.0,),
            ambiguity_class="front_back",
        )
    )
    data = AudioArraySensorData.from_observations(
        [[ambiguous, _observation(detection_score=3.0), _observation()]],
        max_observations=2,
        max_doa_candidates=2,
        device="cpu",
    )
    assert data.observation_mask.tolist() == [[True, True]]
    assert data.doa_mask.tolist() == [[True, False]]
    assert data.ambiguity_mask.tolist() == [[True, False]]
    assert not data.bearing_deg_mask.any()
    assert not data.elevation_deg_mask.any()
    assert data.candidate_bearing_deg.tolist() == [[[25.0, 155.0], [0.0, 0.0]]]
    assert data.candidate_elevation_deg_mask.tolist() == [
        [[True, False], [False, False]]
    ]
    assert data.candidate_bearings_truncated.tolist() == [[1, 0]]
    assert data.candidate_elevations_truncated.tolist() == [[0, 0]]
    assert data.observations_truncated.tolist() == [1]
    assert data.detection_score[0, 1].item() == 3.0
    assert not data.bearing_confidence_mask[0, 0]
    assert data.bearing_confidence[0, 0] == 0.0


@pytest.mark.parametrize(
    "reason", ["insufficient_context", "low_information", "temporal_instability"]
)
def test_unresolved_doa_preserves_availability_and_ambiguity(reason):
    data = AudioArraySensorData.from_observations(
        [
            [
                _observation(
                    doa=DoaEstimate(estimated_bearing_deg=None, ambiguity_class=reason)
                )
            ]
        ],
        device="cpu",
    )
    assert data.doa_mask.all() and data.ambiguity_mask.all()
    assert not data.bearing_deg_mask.any()
    assert not data.candidate_bearing_deg_mask.any()


def test_zero_capacities_and_empty_batches():
    observation = _observation(
        doa=DoaEstimate(
            estimated_bearing_deg=90.0,
            candidate_bearing_deg=(90.0,),
            candidate_elevation_deg=(20.0, 40.0),
        )
    )
    data = AudioArraySensorData.from_observations(
        [[observation], []],
        max_observations=0,
        device="cpu",
    )
    assert data.observation_mask.shape == (2, 0)
    assert data.observations_truncated.tolist() == [1, 0]
    data = AudioArraySensorData.from_observations(
        [[observation]],
        max_doa_candidates=0,
        device="cpu",
    )
    assert data.candidate_bearing_deg.shape == (1, 1, 0)
    assert data.bearing_deg[0, 0] == 90.0
    assert data.candidate_bearings_truncated.tolist() == [[1]]
    assert data.candidate_elevations_truncated.tolist() == [[2]]
    assert AudioArraySensorData.from_observations(
        [], device="cpu"
    ).observation_mask.shape == (0, 1)


@pytest.mark.parametrize("name", ["max_observations", "max_doa_candidates"])
@pytest.mark.parametrize(
    "value,error", [(True, TypeError), (1.5, TypeError), (-1, ValueError)]
)
def test_capacities_fail_explicitly(name, value, error):
    with pytest.raises(error, match=name):
        AudioArraySensorData.from_observations([], device="cpu", **{name: value})
    with pytest.raises(error, match=name):
        AudioArraySensorCfg(prim_path="/World/Audio", **{name: value}).validate()


def test_nonrepresentable_scores_and_non_observations_fail():
    with pytest.raises(ValueError, match="finite float32"):
        AudioArraySensorData.from_observations(
            [[_observation(detection_score=1e100)]],
            device="cpu",
        )
    with pytest.raises(TypeError, match="AudioObservation"):
        AudioArraySensorData.from_observations([[object()]], device="cpu")


def test_projection_ignores_metadata_and_preserves_order():
    first = _observation(detection_score=-2.0)
    second = _observation(detection_score=4.0)
    changed = replace(
        first,
        observation_id="other",
        detector_id="different",
        origin=ObservationOrigin.EXTERNAL_SYSTEM,
        diagnostics={"truth": {"source_id": "hidden", "bearing": 90}},
    )
    baseline = AudioArraySensorData.from_observations(
        [[first, second]], max_observations=3, device="cpu"
    )
    actual = AudioArraySensorData.from_observations(
        [[changed, second]], max_observations=3, device="cpu"
    )
    for name in baseline.__dataclass_fields__:
        torch.testing.assert_close(getattr(actual, name), getattr(baseline, name))
    assert actual.detection_score.tolist() == [[-2.0, 4.0, 0.0]]


def test_selected_write_and_reset_cover_values_masks_and_counts():
    source = AudioArraySensorData.from_observations(
        [[_observation(detection_score=2.0)] * 3, [_observation()]],
        device="cpu",
    )
    target = AudioArraySensorData.allocate(num_envs=3, device="cpu")
    target.write(torch.tensor([2, 0]), source)
    for name in source.__dataclass_fields__:
        torch.testing.assert_close(getattr(target, name)[[2, 0]], getattr(source, name))
    target.reset(torch.tensor([True, False, False]))
    for name in target.__dataclass_fields__:
        assert not getattr(target, name)[:2].any()
        torch.testing.assert_close(getattr(target, name)[2], getattr(source, name)[0])


def test_consumer_masks_angles_and_never_normalizes_other_features():
    data = AudioArraySensorData.from_observations(
        [
            [
                _observation(
                    detection_score=3.0,
                    doa=DoaEstimate(
                        estimated_bearing_deg=90.0,
                        estimated_elevation_deg=-45.0,
                        candidate_bearing_deg=(90.0, -90.0),
                        bearing_confidence=0.6,
                    ),
                )
            ],
            [],
        ],
        max_observations=2,
        device="cpu",
    )
    # Masking must work even if a caller's unused slots contain stale values.
    data.bearing_deg[~data.bearing_deg_mask] = 123.0
    data.candidate_elevation_deg[:] = 30.0
    inputs = _consumer().policy_inputs(data)
    assert inputs["audio/bearing_scaled"].tolist() == [[0.5, 0.0], [0.0, 0.0]]
    assert inputs["audio/elevation_scaled"].tolist() == [[-0.5, 0.0], [0.0, 0.0]]
    assert not inputs["audio/candidate_elevation_scaled"].any()
    assert inputs["audio/detection_score"][0, 0] == 3.0
    assert inputs["audio/observation_mask"].dtype == torch.bool
    assert inputs["audio/observations_truncated"].dtype == torch.int64
    for name in data.__dataclass_fields__:
        if "_deg" not in name:
            assert inputs["audio/" + name] is getattr(data, name)
    empty = _consumer().policy_inputs(
        AudioArraySensorData.allocate(num_envs=2, device="cpu")
    )
    assert all(
        torch.isfinite(value).all() and not value.any() for value in empty.values()
    )


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_confidence_availability_is_independent_of_direction(device):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    observations = [
        _observation(doa=DoaEstimate(estimated_bearing_deg=20, bearing_confidence=c))
        for c in (None, 0.0, 0.7)
    ]
    data = AudioArraySensorData.from_observations(
        [observations], max_observations=3, device=device
    )
    assert data.bearing_deg_mask.all()
    assert data.bearing_confidence_mask.tolist() == [[False, True, True]]
    assert data.bearing_confidence.tolist()[0] == pytest.approx([0, 0, 0.7])
