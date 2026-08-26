from __future__ import annotations

import math
from dataclasses import replace

import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.tdoa import (
    TdoaSyntheticBackend,
    estimate_doa_from_delays,
)
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    FRAME_SCHEMA_VERSION,
    SECTOR_ORDER,
)
from isaac_audio_sensors.core.doa import two_mic_candidate_bearings
from isaac_audio_sensors.core.doa.sector_mapping import (
    bearing_deg_to_sector_name,
    sector_bounds_deg,
)
from isaac_audio_sensors.core.effects.directivity import pattern_coefficient
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    dot,
    norm,
    quaternion_from_yaw_deg,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSpec,
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
CANONICAL_SECTOR_ORDER = (
    "straight",
    "straight_right",
    "right",
    "behind_right",
    "behind",
    "behind_left",
    "left",
    "straight_left",
)


def test_sector_mapping_matches_locked_boundary_table() -> None:
    assert SECTOR_ORDER == CANONICAL_SECTOR_ORDER

    for bearing_deg, expected_sector in SECTOR_BOUNDARY_CASES:
        assert bearing_deg_to_sector_name(bearing_deg) == expected_sector

    for bearing_deg, expected_sector in SECTOR_CENTER_CASES:
        assert bearing_deg_to_sector_name(bearing_deg) == expected_sector


def test_sector_bounds_are_lower_inclusive_upper_exclusive_clockwise_bins() -> None:
    epsilon = 1e-6
    for index, sector_name in enumerate(CANONICAL_SECTOR_ORDER):
        lower, upper = sector_bounds_deg(sector_name)
        center = index * 45.0
        next_sector = CANONICAL_SECTOR_ORDER[(index + 1) % len(CANONICAL_SECTOR_ORDER)]

        assert lower == pytest.approx((center - 22.5) % 360.0)
        assert upper == pytest.approx((center + 22.5) % 360.0)
        assert bearing_deg_to_sector_name(center) == sector_name
        assert bearing_deg_to_sector_name(lower) == sector_name
        assert bearing_deg_to_sector_name(upper - epsilon) == sector_name
        assert bearing_deg_to_sector_name(upper) == next_sector


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
        assert doa.candidate_bearing_deg == pytest.approx((doa.estimated_bearing_deg,))


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


def test_geometry_backend_clamps_coplanar_confidence() -> None:
    array = _array("stereo_y")
    frame = GeometryBackend().simulate(
        _scene(_source("speaker", (3.0, 2.2, 0.0)), array=array),
        array,
        _window(array),
    )
    doa = frame.detections[0].doa

    assert doa.estimated_bearing_deg == pytest.approx(36.25383773744479)
    assert doa.bearing_sector == "straight_right"
    assert doa.bearing_confidence == 1.0
    assert doa.candidate_bearing_deg == pytest.approx((doa.estimated_bearing_deg,))


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
    assert by_source_id["local_forward"].doa.estimated_bearing_deg == pytest.approx(0.0)
    assert by_source_id["local_forward"].doa.bearing_sector == "straight"
    assert by_source_id["local_left"].doa.estimated_bearing_deg == pytest.approx(270.0)
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


@pytest.mark.parametrize(
    ("baseline_unit_xy", "projection", "expected_bearing"),
    (
        ((0.0, 1.0), 1.0 - 4 * math.ulp(1.0), 90.0),
        ((0.0, 1.0), -(1.0 - 4 * math.ulp(1.0)), 270.0),
        ((0.0, 1.0), 1.0 - 8 * math.ulp(1.0), 90.0),
        ((3.0, 4.0), 1.0 - 4 * math.ulp(1.0), 53.13010235415598),
        ((3.0, 4.0), -(1.0 - 4 * math.ulp(1.0)), 233.13010235415598),
    ),
)
def test_tdoa_two_mic_projection_endpoint_collapses_to_one_candidate(
    baseline_unit_xy: tuple[float, float],
    projection: float,
    expected_bearing: float,
) -> None:
    candidates = two_mic_candidate_bearings(
        baseline_unit_xy=baseline_unit_xy,
        projection=projection,
    )

    assert candidates == pytest.approx((expected_bearing,))


def test_tdoa_two_mic_projection_outside_endpoint_tolerance_stays_ambiguous() -> None:
    candidates = two_mic_candidate_bearings(
        baseline_unit_xy=(0.0, 1.0),
        projection=1.0 - 9 * math.ulp(1.0),
    )

    assert len(candidates) == 2
    assert candidates[0] < 90.0 < candidates[1]


@pytest.mark.parametrize("ambiguity_policy", ("none", "front_hemisphere"))
@pytest.mark.parametrize("sign", (-1.0, 1.0))
def test_tdoa_two_mic_ulp_scale_projection_overflow_is_tolerated(
    ambiguity_policy: str,
    sign: float,
) -> None:
    array = _array("stereo_y")
    spacing_m = 0.16
    projection = sign * (1.0 + 8 * math.ulp(1.0))
    delta_s = -projection * spacing_m / 343.0

    doa = estimate_doa_from_delays(
        sensor=array,
        per_mic_delay_s={"left": 0.0, "right": delta_s},
        ambiguity_policy=ambiguity_policy,
    )

    expected_bearing = 90.0 if sign > 0.0 else 270.0
    assert doa.estimated_bearing_deg == pytest.approx(expected_bearing)
    assert doa.candidate_bearing_deg == pytest.approx((expected_bearing,))
    assert doa.bearing_confidence == 0.9
    assert doa.ambiguity_class is None


@pytest.mark.parametrize("ambiguity_policy", ("none", "front_hemisphere"))
@pytest.mark.parametrize("sign", (-1.0, 1.0))
@pytest.mark.parametrize(
    "magnitude",
    (1.0 + 9 * math.ulp(1.0), 1.01, 2.0),
    ids=("first_float_outside_tolerance", "one_percent_impossible", "twice_impossible"),
)
def test_tdoa_two_mic_physically_impossible_delay_fails_closed(
    ambiguity_policy: str,
    sign: float,
    magnitude: float,
) -> None:
    array = _array("stereo_y")
    spacing_m = 0.16
    delta_s = -(sign * magnitude) * spacing_m / 343.0

    doa = estimate_doa_from_delays(
        sensor=array,
        per_mic_delay_s={"left": 0.0, "right": delta_s},
        ambiguity_policy=ambiguity_policy,
    )

    assert doa.estimated_bearing_deg is None
    assert doa.candidate_bearing_deg == ()
    assert doa.bearing_sector is None
    assert doa.bearing_confidence == 0.0
    assert doa.ambiguity_class == "invalid_tdoa_delay"
    assert "physical two-microphone aperture" in (doa.ambiguity_reason or "")


@pytest.mark.parametrize("ambiguity_policy", ("none", "front_hemisphere"))
@pytest.mark.parametrize("position", ((0.0, 3.0, 0.0), (0.0, -3.0, 0.0)))
def test_tdoa_two_mic_noisy_endpoint_fails_closed(
    ambiguity_policy: str,
    position: tuple[float, float, float],
) -> None:
    array = _array("stereo_y")
    doa = (
        TdoaSyntheticBackend(
            ambiguity_policy=ambiguity_policy,
            noise_std_s=1e-3,
            seed=1,
        )
        .simulate(
            _scene(_source("speaker", position), array=array),
            array,
            _window(array),
        )
        .detections[0]
        .doa
    )

    assert doa.estimated_bearing_deg is None
    assert doa.candidate_bearing_deg == ()
    assert doa.bearing_confidence == 0.0
    assert doa.ambiguity_class == "invalid_tdoa_delay"


@pytest.mark.parametrize(
    ("position", "expected_bearing", "expected_sector"),
    (
        ((0.0, 3.0, 0.0), 90.0, "right"),
        ((0.0, -3.0, 0.0), 270.0, "left"),
    ),
)
@pytest.mark.parametrize("ambiguity_policy", ("none", "front_hemisphere"))
def test_tdoa_two_mic_baseline_axis_is_unambiguous(
    position: tuple[float, float, float],
    expected_bearing: float,
    expected_sector: str,
    ambiguity_policy: str,
) -> None:
    array = _array("stereo_y")
    detection = (
        TdoaSyntheticBackend(ambiguity_policy=ambiguity_policy)
        .simulate(
            _scene(_source("speaker", position), array=array),
            array,
            _window(array),
        )
        .detections[0]
    )
    doa = detection.doa
    direct_estimate = estimate_doa_from_delays(
        sensor=array,
        per_mic_delay_s=detection.per_mic_delay_s,
        ambiguity_policy=ambiguity_policy,
    )

    assert doa.estimated_bearing_deg == pytest.approx(expected_bearing, abs=1e-5)
    assert doa.bearing_sector == expected_sector
    assert doa.candidate_bearing_deg == pytest.approx((expected_bearing,), abs=1e-5)
    assert doa.bearing_confidence == 0.9
    assert doa.ambiguity_class is None
    assert doa.ambiguity_reason is None
    assert direct_estimate == doa


@pytest.mark.parametrize(
    "position",
    (
        (3.0, 0.0, 0.0),
        (-3.0, 0.0, 0.0),
        (3.0, 2.2, 0.0),
        (
            3.0 * math.cos(math.radians(89.99975)),
            3.0 * math.sin(math.radians(89.99975)),
            0.0,
        ),
        (
            3.0 * math.cos(math.radians(89.999)),
            3.0 * math.sin(math.radians(89.999)),
            0.0,
        ),
    ),
)
def test_tdoa_two_mic_non_axis_sources_remain_front_back_ambiguous(
    position: tuple[float, float, float],
) -> None:
    array = _array("stereo_y")
    doa = (
        TdoaSyntheticBackend(ambiguity_policy="none")
        .simulate(
            _scene(_source("speaker", position), array=array),
            array,
            _window(array),
        )
        .detections[0]
        .doa
    )

    assert doa.estimated_bearing_deg is None
    assert doa.bearing_sector is None
    assert len(doa.candidate_bearing_deg) == 2
    assert doa.ambiguity_class == "ambiguous_front_back"


def test_tdoa_two_mic_front_prior_preserves_behind_limitation() -> None:
    array = _array("stereo_y")
    doa = (
        TdoaSyntheticBackend(ambiguity_policy="front_hemisphere")
        .simulate(
            _scene(_source("behind", (-3.0, 0.0, 0.0)), array=array),
            array,
            _window(array),
        )
        .detections[0]
        .doa
    )

    assert doa.estimated_bearing_deg == pytest.approx(0.0)
    assert doa.bearing_sector == "straight"
    assert doa.candidate_bearing_deg == pytest.approx((0.0, 180.0))
    assert doa.bearing_confidence == 0.65
    assert doa.ambiguity_class == "front_hemisphere_prior"


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

    degenerate = MicrophoneArraySpec(
        array_id="degenerate",
        prim_path="/World/Rig/Degenerate",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="a", relative_position_m=(0.0, 0.0, 0.0)),
            MicrophoneSpec(mic_id="b", relative_position_m=(0.0, 0.0, 0.0)),
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
    assert (
        stressed_detection.per_mic_rms["left"]
        < (stressed_detection.per_mic_rms["right"])
    )
    assert stressed_detection.doa.bearing_confidence < (
        clean_detection.doa.bearing_confidence
    )
    assert stressed.diagnostics["stress_controls_deterministic"] is True
    assert stressed.diagnostics["noise_std_s"] == pytest.approx(1e-5)
    assert stressed.diagnostics["clock_jitter_s"] == pytest.approx(2e-5)
    assert stressed.diagnostics["gain_mismatch_db"] == pytest.approx(6.0)
    gain_offsets = stressed_detection.diagnostics["per_mic_gain_offset_db"]
    assert set(gain_offsets) == {"left", "right"}
    assert gain_offsets["left"] != gain_offsets["right"]

    reseeded = TdoaSyntheticBackend(
        noise_std_s=1e-5,
        clock_jitter_s=2e-5,
        gain_mismatch_db=6.0,
        ambiguity_policy="none",
        seed=99,
    ).simulate(scene, array, _window(array))
    reseeded_offsets = reseeded.detections[0].diagnostics["per_mic_gain_offset_db"]
    assert reseeded_offsets != gain_offsets
    assert reseeded.diagnostics["noise_seed"] == 99
    assert stressed.diagnostics["noise_seed"] is None


def test_l0_l1_per_mic_rms_follows_pressure_law_with_source_gain() -> None:
    array = _array("quad_front")
    source = _source("speaker", (4.0, 3.0, 0.0), gain_db=-6.0)
    scene = _scene(source, array=array)
    expected = {
        mic_id: 10.0 ** (-6.0 / 20.0) / norm(subtract(source.position_world, position))
        for mic_id, position in microphone_world_positions(array).items()
    }

    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        detection = backend.simulate(scene, array, _window(array)).detections[0]
        assert detection.per_mic_rms == pytest.approx(expected)


def test_l0_l1_aggregate_rms_is_power_sum_of_detections() -> None:
    array = _array("quad_front")
    scene = _scene(
        _source("near", (2.0, 1.0, 0.0)),
        _source("far", (-5.0, 3.0, 0.0), gain_db=6.0),
        array=array,
    )

    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        frame = backend.simulate(scene, array, _window(array))
        for microphone in array.microphones:
            power = sum(
                detection.per_mic_rms[microphone.mic_id] ** 2
                for detection in frame.detections
            )
            assert frame.aggregate_per_mic_rms[microphone.mic_id] == pytest.approx(
                math.sqrt(power)
            )


def test_l0_l1_mic_self_noise_floor_contributes_to_aggregate_rms() -> None:
    base = _array("quad_front")
    array = replace(
        base,
        microphones=tuple(
            replace(mic, self_noise_db=-20.0) if mic.mic_id == "front" else mic
            for mic in base.microphones
        ),
    )
    scene = _scene(_source("speaker", (3.0, 0.0, 0.0)), array=array)
    silent_scene = _scene(array=array)

    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        frame = backend.simulate(scene, array, _window(array))
        signal_rms = frame.detections[0].per_mic_rms["front"]
        assert frame.aggregate_per_mic_rms["front"] == pytest.approx(
            math.sqrt(signal_rms**2 + 0.1**2)
        )

        silent = backend.simulate(silent_scene, array, _window(array))
        assert silent.aggregate_per_mic_rms["front"] == pytest.approx(0.1)
        assert silent.aggregate_per_mic_rms["rear"] == 0.0


def test_l0_l1_cardioid_directivity_attenuates_off_axis() -> None:
    array = _array("quad_front")
    position = (5.0, 0.0, 0.0)
    facing = _source(
        "facing",
        position,
        directivity="cardioid",
        orientation_world_quat=quaternion_from_yaw_deg(180.0),
    )
    away = _source(
        "away",
        position,
        directivity="cardioid",
        orientation_world_quat=quaternion_from_yaw_deg(0.0),
    )
    positions = microphone_world_positions(array)

    def _expected_rms(yaw_deg: float, mic_id: str) -> float:
        forward = (
            math.cos(math.radians(yaw_deg)),
            math.sin(math.radians(yaw_deg)),
            0.0,
        )
        to_mic = subtract(positions[mic_id], position)
        distance = norm(to_mic)
        cos_theta = dot(forward, to_mic) / distance
        return ((1.0 + cos_theta) / 2.0) / distance

    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        facing_detection = backend.simulate(
            _scene(facing, array=array), array, _window(array)
        ).detections[0]
        away_detection = backend.simulate(
            _scene(away, array=array), array, _window(array)
        ).detections[0]

        assert facing_detection.diagnostics["directivity_applied"] == "cardioid"
        for mic_id in positions:
            assert facing_detection.per_mic_rms[mic_id] == pytest.approx(
                _expected_rms(180.0, mic_id)
            )
            assert away_detection.per_mic_rms[mic_id] == pytest.approx(
                _expected_rms(0.0, mic_id)
            )
            assert (
                away_detection.per_mic_rms[mic_id]
                < facing_detection.per_mic_rms[mic_id]
            )


def test_directivity_families_use_frozen_coefficients() -> None:
    expected = {
        "omni": 1.0,
        "cardioid": 0.5,
        "figure_eight": 0.0,
        "supercardioid": 0.37,
    }
    assert {family: pattern_coefficient(family) for family in expected} == expected


def test_l0_l1_unmodeled_directivity_falls_back_to_omni() -> None:
    array = _array("quad_front")
    position = (4.0, 1.0, 0.0)
    omni = _source("omni", position)
    unmodeled = _source(
        "unmodeled",
        position,
        directivity="hypercardioid",
        orientation_world_quat=quaternion_from_yaw_deg(90.0),
    )
    unoriented = _source("unoriented", position, directivity="cardioid")

    for backend in (GeometryBackend(), TdoaSyntheticBackend()):
        base = backend.simulate(
            _scene(omni, array=array), array, _window(array)
        ).detections[0]
        for source in (unmodeled, unoriented):
            detection = backend.simulate(
                _scene(source, array=array), array, _window(array)
            ).detections[0]
            assert detection.per_mic_rms == pytest.approx(base.per_mic_rms)
            assert detection.diagnostics["directivity"] == source.directivity
            assert detection.diagnostics["directivity_applied"] == "omni"


def test_l1_air_absorption_toggle_attenuates_rms_with_distance() -> None:
    array = _array("quad_front")
    source = _source("speaker", (8.0, 0.0, 0.0))
    scene = _scene(source, array=array)
    base = TdoaSyntheticBackend().simulate(scene, array, _window(array)).detections[0]
    damped = (
        TdoaSyntheticBackend(air_absorption_db_per_m=0.25)
        .simulate(scene, array, _window(array))
        .detections[0]
    )
    positions = microphone_world_positions(array)

    assert damped.per_mic_delay_s == base.per_mic_delay_s
    for mic_id, rms in damped.per_mic_rms.items():
        distance = norm(subtract(source.position_world, positions[mic_id]))
        assert rms == pytest.approx(
            base.per_mic_rms[mic_id] * 10.0 ** (-0.25 * distance / 20.0)
        )
        assert rms < base.per_mic_rms[mic_id]


def test_seeded_noise_is_deterministic_per_seed_frame_and_mic() -> None:
    array = _array("quad_front")
    scene = _scene(_source("speaker", (5.0, 2.0, 0.0)), array=array)

    def _window_at(timestamp_ms: int) -> AudioTimeWindow:
        return AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            timestamp_ms=timestamp_ms,
            sample_rate_hz=array.sample_rate_hz,
            frame_index=0,
        )

    backend = TdoaSyntheticBackend(
        noise_std_s=1e-5,
        clock_jitter_s=2e-5,
        gain_mismatch_db=3.0,
        seed=7,
    )
    first = backend.simulate(scene, array, _window_at(1_000))
    assert backend.simulate(scene, array, _window_at(1_000)) == first

    other_frame = backend.simulate(scene, array, _window_at(2_000))
    assert (
        other_frame.detections[0].per_mic_delay_s != first.detections[0].per_mic_delay_s
    )
    assert (
        other_frame.detections[0].diagnostics["per_mic_gain_offset_db"]
        == first.detections[0].diagnostics["per_mic_gain_offset_db"]
    )

    other_seed = TdoaSyntheticBackend(
        noise_std_s=1e-5,
        clock_jitter_s=2e-5,
        gain_mismatch_db=3.0,
        seed=8,
    ).simulate(scene, array, _window_at(1_000))
    assert (
        other_seed.detections[0].per_mic_delay_s != first.detections[0].per_mic_delay_s
    )


def test_zero_noise_seeded_backend_matches_default_bit_exactly() -> None:
    array = _array("quad_front")
    scene = _scene(_source("speaker", (5.0, 2.0, 0.0)), array=array)
    default_frame = TdoaSyntheticBackend().simulate(scene, array, _window(array))
    seeded_frame = TdoaSyntheticBackend(seed=12_345).simulate(
        scene,
        array,
        _window(array),
    )

    default_detection = default_frame.detections[0]
    seeded_detection = seeded_frame.detections[0]
    assert default_detection.per_mic_delay_s == seeded_detection.per_mic_delay_s
    assert default_detection.per_mic_rms == seeded_detection.per_mic_rms
    assert default_frame.aggregate_per_mic_rms == seeded_frame.aggregate_per_mic_rms
    assert default_frame.diagnostics["noise_seed"] is None
    assert seeded_frame.diagnostics["noise_seed"] == 12_345


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
    *,
    gain_db: float = 0.0,
    directivity: str = "omni",
    orientation_world_quat: tuple[float, float, float, float] | None = None,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=orientation_world_quat,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=gain_db,
        directivity=directivity,
    )


def _position_for_bearing(
    bearing_deg: float,
    *,
    distance: float = 5.0,
) -> tuple[float, float, float]:
    radians = math.radians(bearing_deg)
    return (distance * math.cos(radians), distance * math.sin(radians), 0.0)


def _position_for_bearing_elevation(
    bearing_deg: float,
    elevation_deg: float,
    *,
    distance: float = 5.0,
) -> tuple[float, float, float]:
    bearing = math.radians(bearing_deg)
    elevation = math.radians(elevation_deg)
    horizontal = distance * math.cos(elevation)
    return (
        horizontal * math.cos(bearing),
        horizontal * math.sin(bearing),
        distance * math.sin(elevation),
    )


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


@pytest.mark.parametrize(
    ("bearing_deg", "elevation_deg"),
    (
        (0.0, 0.0),
        (0.0, 45.0),
        (90.0, -30.0),
        (210.0, 20.0),
        (315.0, -45.0),
    ),
)
def test_tdoa_tetrahedral_clean_elevation_matches_ground_truth(
    bearing_deg: float,
    elevation_deg: float,
) -> None:
    array = _array("tetrahedral")
    source = _source(
        "speaker",
        _position_for_bearing_elevation(bearing_deg, elevation_deg),
    )
    frame = TdoaSyntheticBackend().simulate(
        _scene(source, array=array),
        array,
        _window(array),
    )

    detection = frame.detections[0]
    assert detection.ground_truth_elevation_deg == pytest.approx(
        elevation_deg, abs=1e-6
    )
    assert detection.doa.estimated_bearing_deg == pytest.approx(bearing_deg, abs=2.0)
    assert detection.doa.estimated_elevation_deg == pytest.approx(
        elevation_deg, abs=2.0
    )
    assert detection.doa.candidate_elevation_deg == pytest.approx(
        (detection.doa.estimated_elevation_deg,)
    )
    assert detection.diagnostics["array_geometry_rank_xyz"] == 3
    assert detection.diagnostics["oracle_elevation_error_deg"] < 2.0
    assert detection.doa.bearing_confidence > 0.7


def test_tdoa_planar_array_keeps_elevation_none() -> None:
    array = _array("quad_front")
    source = _source(
        "speaker",
        _position_for_bearing_elevation(90.0, 35.0),
    )
    detection = (
        TdoaSyntheticBackend()
        .simulate(
            _scene(source, array=array),
            array,
            _window(array),
        )
        .detections[0]
    )

    assert detection.doa.estimated_elevation_deg is None
    assert detection.doa.candidate_elevation_deg == ()
    assert detection.doa.estimated_bearing_deg == pytest.approx(90.0, abs=2.0)
    assert detection.ground_truth_elevation_deg == pytest.approx(35.0, abs=1e-6)
    assert detection.diagnostics["array_geometry_rank_xyz"] == 2
    assert detection.diagnostics["oracle_elevation_error_deg"] is None


def test_geometry_backend_emits_exact_elevation() -> None:
    array = _array("quad_front")
    detection = (
        GeometryBackend()
        .simulate(
            _scene(_source("speaker", (3.0, 0.0, 4.0)), array=array),
            array,
            _window(array),
        )
        .detections[0]
    )

    expected_elevation = math.degrees(math.asin(4.0 / 5.0))
    assert detection.doa.estimated_elevation_deg == pytest.approx(
        expected_elevation, abs=1e-9
    )
    assert detection.ground_truth_elevation_deg == pytest.approx(
        expected_elevation, abs=1e-9
    )
    assert detection.doa.candidate_elevation_deg == pytest.approx((expected_elevation,))
