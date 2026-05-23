"""Hardening tests for stable L0/L1 backend semantics."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    FRAME_SCHEMA_VERSION,
    SECTOR_ORDER,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    quaternion_from_yaw_deg,
)
from isaac_audio_sensors.core.microphone_array import (
    arbitrary_microphone_array,
    create_microphone_array,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
)

SECTOR_BOUNDARY_CASES = (
    (-1.0, "straight"),
    (0.0, "straight"),
    (22.4999, "straight"),
    (22.5, "straight_right"),
    (67.4999, "straight_right"),
    (67.5, "right"),
    (112.5, "behind_right"),
    (157.5, "behind"),
    (202.5, "behind_left"),
    (247.5, "left"),
    (292.5, "straight_left"),
    (337.4999, "straight_left"),
    (337.5, "straight"),
    (360.0, "straight"),
)

SECTOR_CENTER_CASES = tuple(
    (index * 45.0, sector_name) for index, sector_name in enumerate(SECTOR_ORDER)
)


def test_sector_mapping_matches_locked_boundary_table() -> None:
    for bearing_deg, expected_sector in SECTOR_BOUNDARY_CASES:
        assert bearing_deg_to_sector_name(bearing_deg) == expected_sector

    for bearing_deg, expected_sector in SECTOR_CENTER_CASES:
        assert bearing_deg_to_sector_name(bearing_deg) == expected_sector


def test_geometry_backend_covers_all_sector_centers_and_boundaries() -> None:
    array = _array("quad_front")

    for bearing_deg, expected_sector in SECTOR_CENTER_CASES + SECTOR_BOUNDARY_CASES:
        frame = GeometryBackend().simulate(
            _scene(
                _source("speaker", _position_for_bearing(bearing_deg)),
                array=array,
            ),
            array,
            _window(array),
        )
        doa = frame.detections[0].doa

        assert doa.estimated_bearing_deg is not None
        assert angular_error_deg(doa.estimated_bearing_deg, bearing_deg) < 1e-6
        assert doa.bearing_sector == expected_sector
        assert doa.candidate_bearing_deg == pytest.approx(
            (doa.estimated_bearing_deg,)
        )


def test_geometry_backend_zero_horizontal_vectors_have_no_fake_bearing() -> None:
    array = _array("quad_front")
    frame = GeometryBackend().simulate(
        _scene(
            _source("same", (0.0, 0.0, 0.0)),
            _source("above", (0.0, 0.0, 3.0)),
            array=array,
        ),
        array,
        _window(array),
    )

    by_source_id = {detection.source_id: detection for detection in frame.detections}
    assert by_source_id["same"].source_distance_m == 0.0
    assert by_source_id["above"].source_distance_m == 3.0
    for detection in by_source_id.values():
        assert detection.doa.estimated_bearing_deg is None
        assert detection.doa.bearing_sector is None
        assert detection.doa.bearing_confidence == 0.0
        assert detection.doa.candidate_bearing_deg == ()


def test_geometry_backend_respects_rotated_array_forward_right_basis() -> None:
    array = create_microphone_array(
        array_id="rotated",
        prim_path="/World/Rig/RotatedArray",
        layout_name="quad_front",
        orientation_world_quat=quaternion_from_yaw_deg(90.0),
    )
    frame = GeometryBackend().simulate(
        _scene(
            _source("local_forward", (0.0, 5.0, 0.0)),
            _source("local_left", (5.0, 0.0, 0.0)),
            array=array,
        ),
        array,
        _window(array),
    )

    by_source_id = {detection.source_id: detection for detection in frame.detections}
    assert by_source_id["local_forward"].doa.estimated_bearing_deg == pytest.approx(
        0.0
    )
    assert by_source_id["local_forward"].doa.bearing_sector == "straight"
    assert by_source_id["local_left"].doa.estimated_bearing_deg == pytest.approx(
        270.0
    )
    assert by_source_id["local_left"].doa.bearing_sector == "left"


def test_geometry_backend_v1_frame_is_deterministic_and_non_physical() -> None:
    array = _array("quad_front")
    scene = _scene(
        _source("b_second", (0.0, 5.0, 0.0)),
        _source("a_first", (5.0, 0.0, 0.0)),
        _source("c_third", (0.0, -5.0, 0.0)),
        array=array,
    )
    window = _window(array, max_events=2)

    first = GeometryBackend().simulate(scene, array, window)
    second = GeometryBackend().simulate(scene, array, window)

    assert first == second
    assert first.schema_version == FRAME_SCHEMA_VERSION
    assert first.backend_id == "geometry_only"
    assert first.coordinate_convention == COORDINATE_CONVENTION
    assert first.waveform_paths == ()
    assert tuple(detection.source_id for detection in first.detections) == (
        "a_first",
        "b_second",
    )
    for detection in first.detections:
        assert detection.per_mic_delay_s == {}
        assert detection.diagnostics["physical_waveform"] is False


@pytest.mark.parametrize("layout_name", ("stereo_y", "two_mic_y"))
def test_tdoa_two_mic_layouts_expose_front_back_ambiguity(
    layout_name: str,
) -> None:
    array = _array(layout_name)
    frame = TdoaSyntheticBackend(ambiguity_policy="none").simulate(
        _scene(_source("front", (8.0, 0.0, 0.0)), array=array),
        array,
        _window(array),
    )
    detection = frame.detections[0]
    doa = detection.doa

    assert doa.estimated_bearing_deg is None
    assert doa.bearing_sector is None
    assert doa.candidate_bearing_deg == pytest.approx((0.0, 180.0))
    assert doa.ambiguity_class == "ambiguous_front_back"
    assert "without an explicit prior" in (doa.ambiguity_reason or "")
    assert set(detection.per_mic_delay_s) == {"left", "right"}
    assert set(detection.per_mic_rms) == {"left", "right"}
    assert detection.diagnostics["array_geometry_rank_xy"] == 1


def test_tdoa_two_mic_front_prior_stays_lower_than_clean_four_mic() -> None:
    stereo = _array("stereo_y")
    quad = _array("quad_front")
    source = _source("front", (8.0, 0.0, 0.0))
    two_mic = TdoaSyntheticBackend(ambiguity_policy="front_hemisphere").simulate(
        _scene(source, array=stereo),
        stereo,
        _window(stereo),
    )
    four_mic = TdoaSyntheticBackend().simulate(
        _scene(source, array=quad),
        quad,
        _window(quad),
    )
    two_mic_doa = two_mic.detections[0].doa
    four_mic_doa = four_mic.detections[0].doa

    assert two_mic_doa.estimated_bearing_deg == pytest.approx(0.0)
    assert two_mic_doa.ambiguity_class == "front_hemisphere_prior"
    assert two_mic_doa.bearing_confidence < four_mic_doa.bearing_confidence
    assert four_mic_doa.ambiguity_class is None


@pytest.mark.parametrize("layout_name", ("quad_front", "quad_cross"))
def test_tdoa_four_mic_layouts_recover_all_sector_centers(
    layout_name: str,
) -> None:
    array = _array(layout_name)

    for bearing_deg, expected_sector in SECTOR_CENTER_CASES:
        frame = TdoaSyntheticBackend().simulate(
            _scene(
                _source("speaker", _position_for_bearing(bearing_deg, distance=8.0)),
                array=array,
            ),
            array,
            _window(array),
        )
        detection = frame.detections[0]
        doa = detection.doa

        assert doa.estimated_bearing_deg is not None
        assert angular_error_deg(doa.estimated_bearing_deg, bearing_deg) < 1.0
        assert doa.bearing_sector == expected_sector
        assert set(detection.per_mic_delay_s) == {"front", "right", "rear", "left"}
        assert set(detection.per_mic_rms) == {"front", "right", "rear", "left"}
        assert doa.ambiguity_class is None
        assert doa.ambiguity_reason is None
        assert doa.bearing_confidence > 0.9


def test_tdoa_rejects_invalid_and_degenerate_mic_counts() -> None:
    mono = _array("mono")
    with pytest.raises(ValueError, match="at least two microphones"):
        TdoaSyntheticBackend().simulate(
            _scene(_source("speaker", (5.0, 0.0, 0.0)), array=mono),
            mono,
            _window(mono),
        )

    degenerate = arbitrary_microphone_array(
        array_id="degenerate",
        prim_path="/World/Rig/Degenerate",
        relative_positions_m=(
            ("a", (0.0, 0.0, 0.0)),
            ("b", (0.0, 0.0, 0.0)),
        ),
    )
    with pytest.raises(ValueError, match="degenerate"):
        TdoaSyntheticBackend().simulate(
            _scene(_source("speaker", (5.0, 0.0, 0.0)), array=degenerate),
            degenerate,
            _window(degenerate),
        )


def test_tdoa_stress_knobs_are_deterministic_and_diagnosed() -> None:
    array = _array("stereo_y")
    scene = _scene(_source("front", (8.0, 0.0, 0.0)), array=array)
    clean = TdoaSyntheticBackend(ambiguity_policy="none").simulate(
        scene,
        array,
        _window(array),
    )
    backend = TdoaSyntheticBackend(
        noise_std_s=1e-5,
        clock_jitter_s=2e-5,
        gain_mismatch_db=6.0,
        ambiguity_policy="none",
    )
    stressed = backend.simulate(scene, array, _window(array))

    assert stressed == backend.simulate(scene, array, _window(array))
    clean_detection = clean.detections[0]
    stressed_detection = stressed.detections[0]
    assert stressed_detection.per_mic_delay_s != clean_detection.per_mic_delay_s
    assert stressed_detection.per_mic_rms["left"] < (
        stressed_detection.per_mic_rms["right"]
    )
    assert stressed_detection.doa.bearing_confidence < (
        clean_detection.doa.bearing_confidence
    )
    assert stressed.diagnostics["stress_controls_deterministic"] is True
    assert stressed.diagnostics["noise_std_s"] == pytest.approx(1e-5)
    assert stressed.diagnostics["clock_jitter_s"] == pytest.approx(2e-5)
    assert stressed.diagnostics["gain_mismatch_db"] == pytest.approx(6.0)
    assert stressed_detection.diagnostics["per_mic_gain_offset_db"] == {
        "left": -3.0,
        "right": 3.0,
    }


def test_l1_noise_jitter_gain_mismatch_controls_are_documented() -> None:
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("docs/backends.md"),
            Path("docs/tdoa_doa.md"),
            Path("docs/limitations.md"),
        )
    )

    for phrase in (
        "`noise_std_s`",
        "`clock_jitter_s`",
        "`gain_mismatch_db`",
        "deterministic stress",
        "not calibrated hardware noise",
        "does not model",
        "stochastic sensor drift",
    ):
        assert phrase in docs


def _array(layout_name: str) -> MicrophoneArraySpec:
    return create_microphone_array(
        array_id=layout_name,
        prim_path=f"/World/Rig/{layout_name}",
        layout_name=layout_name,
    )


def _scene(
    *sources: AudioSourceSpec,
    array: MicrophoneArraySpec,
) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="l0_l1_hardening",
        timestamp_ms=1_775_496_559_292,
        sources=sources,
        arrays=(array,),
    )


def _source(
    source_id: str,
    position: tuple[float, float, float],
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _position_for_bearing(
    bearing_deg: float,
    *,
    distance: float = 5.0,
) -> tuple[float, float, float]:
    radians = math.radians(bearing_deg)
    return (distance * math.cos(radians), distance * math.sin(radians), 0.0)


def _window(
    array: MicrophoneArraySpec,
    *,
    max_events: int | None = None,
) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=1_775_496_559_292,
        sample_rate_hz=array.sample_rate_hz,
        frame_index=0,
        max_events=max_events,
    )
