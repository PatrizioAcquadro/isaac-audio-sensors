"""Backend tests for geometry, synthetic TDOA, and optional room acoustics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    estimate_tdoa_matrix,
    gcc_phat_delay,
    relative_delays_from_tdoa_matrix,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from tests.helpers import (
    FakeShoeBox as _FakeShoeBox,
)
from tests.helpers import (
    install_fake_pyroom as _install_fake_pyroom,
)


def _source(
    source_id: str,
    position: tuple[float, float, float],
    *,
    audio_asset_path: str | None = "generated://impulse",
    start_time_s: float = 0.0,
    duration_s: float | None = 1.0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=None,
        start_time_s=start_time_s,
        duration_s=duration_s,
        gain_db=0.0,
    )


def _scene_with_sources(*sources: AudioSourceSpec, array):
    return AudioSceneSnapshot(
        stage_id="backend_test",
        timestamp_ms=0,
        sources=sources,
        arrays=(array,),
    )


def _room_scene_with_sources(*sources: AudioSourceSpec, array):
    return AudioSceneSnapshot(
        stage_id="room_backend_test",
        timestamp_ms=0,
        sources=sources,
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            max_order=1,
            # Explicit world placement: sources sit at x/y <= 3 around an
            # array at the origin, so the room must straddle the origin.
            origin_m=(-1.5, -1.0, -1.5),
        ),
    )


def _window(
    *,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_events: int | None = None,
) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        timestamp_ms=0,
        sample_rate_hz=48_000,
        max_events=max_events,
    )


@pytest.mark.parametrize(
    ("position", "sector"),
    [
        ((5.0, 0.0, 0.0), "straight"),
        ((5.0, 5.0, 0.0), "straight_right"),
        ((0.0, 5.0, 0.0), "right"),
        ((-5.0, 0.0, 0.0), "behind"),
        ((0.0, -5.0, 0.0), "left"),
    ],
)
def test_geometry_backend_maps_canonical_sectors(position, sector):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    frame = GeometryBackend().simulate(
        _scene_with_sources(_source("speaker", position), array=array),
        array,
        _window(),
    )

    assert frame.detections[0].doa.bearing_sector == sector


def test_geometry_backend_boundary_cases():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    frame = GeometryBackend().simulate(
        _scene_with_sources(_source("same", (0.0, 0.0, 0.0)), array=array),
        array,
        _window(),
    )

    assert frame.detections[0].doa.estimated_bearing_deg is None
    assert frame.detections[0].doa.bearing_confidence == 0.0


@pytest.mark.parametrize(
    ("position", "expected_bearing"),
    [
        ((5.0, 0.0, 0.0), 0.0),
        ((0.0, 5.0, 0.0), 90.0),
        ((-5.0, 0.0, 0.0), 180.0),
        ((0.0, -5.0, 0.0), 270.0),
    ],
)
def test_tdoa_four_mic_clean_azimuth_cases(position, expected_bearing):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    frame = TdoaSyntheticBackend().simulate(
        _scene_with_sources(_source("speaker", position), array=array),
        array,
        _window(),
    )

    detection = frame.detections[0]
    assert detection.doa.estimated_bearing_deg == pytest.approx(
        expected_bearing,
        abs=2.0,
    )
    assert set(detection.per_mic_delay_s) == {"front", "right", "rear", "left"}
    assert detection.doa.bearing_confidence > 0.7


def _position_from_bearing_elevation(
    bearing_deg: float,
    elevation_deg: float,
    *,
    distance_m: float = 5.0,
) -> tuple[float, float, float]:
    bearing = math.radians(bearing_deg)
    elevation = math.radians(elevation_deg)
    return (
        distance_m * math.cos(elevation) * math.cos(bearing),
        distance_m * math.cos(elevation) * math.sin(bearing),
        distance_m * math.sin(elevation),
    )


@pytest.mark.parametrize(
    ("bearing_deg", "elevation_deg"),
    [
        (0.0, 0.0),
        (0.0, 45.0),
        (90.0, -30.0),
        (210.0, 20.0),
        (315.0, -45.0),
    ],
)
def test_tdoa_tetrahedral_clean_elevation_matches_ground_truth(
    bearing_deg, elevation_deg
):
    array = create_microphone_array(
        array_id="tetra",
        prim_path="/World/Rig/TetraArray",
        layout_name="tetrahedral",
    )
    position = _position_from_bearing_elevation(bearing_deg, elevation_deg)
    frame = TdoaSyntheticBackend().simulate(
        _scene_with_sources(_source("speaker", position), array=array),
        array,
        _window(),
    )

    detection = frame.detections[0]
    assert detection.ground_truth_elevation_deg == pytest.approx(
        elevation_deg, abs=1e-6
    )
    assert detection.doa.estimated_bearing_deg == pytest.approx(
        bearing_deg, abs=2.0
    )
    assert detection.doa.estimated_elevation_deg == pytest.approx(
        elevation_deg, abs=2.0
    )
    assert detection.doa.candidate_elevation_deg == pytest.approx(
        (detection.doa.estimated_elevation_deg,)
    )
    assert detection.diagnostics["array_geometry_rank_xyz"] == 3
    assert detection.diagnostics["oracle_elevation_error_deg"] < 2.0
    assert detection.doa.bearing_confidence > 0.7


def test_tdoa_planar_array_keeps_elevation_none_for_elevated_source():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    position = _position_from_bearing_elevation(90.0, 35.0)
    frame = TdoaSyntheticBackend().simulate(
        _scene_with_sources(_source("speaker", position), array=array),
        array,
        _window(),
    )

    detection = frame.detections[0]
    assert detection.doa.estimated_elevation_deg is None
    assert detection.doa.candidate_elevation_deg == ()
    assert detection.doa.estimated_bearing_deg == pytest.approx(90.0, abs=2.0)
    assert detection.ground_truth_elevation_deg == pytest.approx(35.0, abs=1e-6)
    assert detection.diagnostics["array_geometry_rank_xyz"] == 2
    assert detection.diagnostics["oracle_elevation_error_deg"] is None


def test_geometry_backend_emits_exact_elevation():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    frame = GeometryBackend().simulate(
        _scene_with_sources(_source("speaker", (3.0, 0.0, 4.0)), array=array),
        array,
        _window(),
    )

    detection = frame.detections[0]
    expected_elevation = math.degrees(math.asin(4.0 / 5.0))
    assert detection.doa.estimated_elevation_deg == pytest.approx(
        expected_elevation, abs=1e-9
    )
    assert detection.ground_truth_elevation_deg == pytest.approx(
        expected_elevation, abs=1e-9
    )
    assert detection.doa.candidate_elevation_deg == pytest.approx(
        (expected_elevation,)
    )


def test_tdoa_two_mic_front_back_ambiguity_is_explicit():
    array = create_microphone_array(
        array_id="stereo",
        prim_path="/World/Rig/StereoArray",
        layout_name="stereo_y",
    )
    frame = TdoaSyntheticBackend(ambiguity_policy="none").simulate(
        _scene_with_sources(_source("front", (5.0, 0.0, 0.0)), array=array),
        array,
        _window(),
    )

    doa = frame.detections[0].doa
    assert doa.estimated_bearing_deg is None
    assert doa.candidate_bearing_deg == pytest.approx((0.0, 180.0))
    assert doa.ambiguity_class == "ambiguous_front_back"
    assert doa.bearing_confidence < 0.5


def test_tdoa_two_mic_prior_is_recorded_when_used():
    array = create_microphone_array(
        array_id="stereo",
        prim_path="/World/Rig/StereoArray",
        layout_name="stereo_y",
    )
    frame = TdoaSyntheticBackend(ambiguity_policy="front_hemisphere").simulate(
        _scene_with_sources(_source("front", (5.0, 0.0, 0.0)), array=array),
        array,
        _window(),
    )

    doa = frame.detections[0].doa
    assert doa.estimated_bearing_deg == pytest.approx(0.0)
    assert doa.ambiguity_class == "front_hemisphere_prior"
    assert "front_hemisphere" in (doa.ambiguity_reason or "")


def test_tdoa_noisy_case_degrades_confidence():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _scene_with_sources(_source("speaker", (5.0, 2.0, 0.0)), array=array)
    clean = TdoaSyntheticBackend().simulate(scene, array, _window()).detections[0]
    noisy = (
        TdoaSyntheticBackend(noise_std_s=0.001)
        .simulate(
            scene,
            array,
            _window(),
        )
        .detections[0]
    )

    assert noisy.doa.bearing_confidence < clean.doa.bearing_confidence


def test_tdoa_deterministic_replay_for_fixed_scene():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _scene_with_sources(_source("speaker", (5.0, 2.0, 0.0)), array=array)
    backend = TdoaSyntheticBackend(noise_std_s=0.0001)
    first = backend.simulate(scene, array, _window())
    second = backend.simulate(scene, array, _window())

    assert first == second


def test_gcc_phat_delay_sign_and_relative_tdoa_matrix():
    sample_rate_hz = 8_000
    reference = np.zeros(256)
    delayed = np.zeros(256)
    reference[40] = 1.0
    delayed[45] = 1.0

    delay = gcc_phat_delay(
        delayed,
        reference,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=1,
    )
    matrix = estimate_tdoa_matrix(
        {"ref": reference, "late": delayed},
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=1,
    )

    assert delay.delay_s == pytest.approx(5.0 / sample_rate_hz)
    assert matrix["late->ref"] == pytest.approx(5.0 / sample_rate_hz)
    assert matrix["ref->late"] == pytest.approx(-5.0 / sample_rate_hz)
    assert relative_delays_from_tdoa_matrix(
        matrix,
        mic_ids=("ref", "late"),
        reference_mic_id="ref",
    ) == pytest.approx({"ref": 0.0, "late": 5.0 / sample_rate_hz})


def test_pairwise_gcc_phat_matches_per_pair_reference():
    sample_rate_hz = 8_000
    rng = np.random.default_rng(1234)
    waveforms = {
        "front": rng.standard_normal(512),
        "left": np.roll(rng.standard_normal(512), 3),
        "rear": rng.standard_normal(480),
        "right": rng.standard_normal(640),
    }

    delays, peaks = estimate_tdoa_diagnostics(
        waveforms,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=8,
    )
    matrix = estimate_tdoa_matrix(
        waveforms,
        sample_rate_hz=sample_rate_hz,
        max_delay_s=0.01,
        interp=8,
    )

    mic_ids = tuple(waveforms)
    expected_keys = {f"{left}->{right}" for left in mic_ids for right in mic_ids}
    assert set(delays) == expected_keys
    assert set(peaks) == expected_keys
    assert matrix == delays

    for left in mic_ids:
        for right in mic_ids:
            key = f"{left}->{right}"
            if left == right:
                assert delays[key] == 0.0
                assert peaks[key] == 1.0
                continue
            reference = gcc_phat_delay(
                waveforms[left],
                waveforms[right],
                sample_rate_hz=sample_rate_hz,
                max_delay_s=0.01,
                interp=8,
            )
            assert delays[key] == pytest.approx(reference.delay_s, abs=1e-12)
            assert peaks[key] == pytest.approx(reference.peak_value, abs=1e-12)


def test_pairwise_gcc_phat_mirrors_zero_delay_without_negative_zero():
    rng = np.random.default_rng(7)
    shared = rng.standard_normal(256)
    matrix = estimate_tdoa_matrix(
        {"a": shared, "b": shared.copy()},
        sample_rate_hz=8_000,
        max_delay_s=0.01,
        interp=1,
    )

    assert matrix["a->b"] == 0.0
    assert matrix["b->a"] == 0.0
    assert math.copysign(1.0, matrix["a->b"]) > 0.0
    assert math.copysign(1.0, matrix["b->a"]) > 0.0


def test_room_acoustics_fake_pyroom_path_uses_waveforms(monkeypatch):
    _install_fake_pyroom(monkeypatch)

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )
    frame = RoomAcousticsBackend().simulate(scene, array, _window())

    detection = frame.detections[0]
    assert frame.backend_id == "room_acoustics"
    assert frame.diagnostics["physical_waveform"] is True
    assert frame.diagnostics["pyroomacoustics_version"] == "fake-test"
    assert frame.diagnostics["scheduled_source_ids"] == ("speaker",)
    assert frame.diagnostics["room_config"] == {
        "room_id": "unit_room",
        "dimensions_m": (6.0, 5.0, 3.0),
        "absorption": 0.35,
        "max_order": 1,
        "air_absorption": False,
        "ray_tracing": False,
        "origin_m": (-1.5, -1.0, -1.5),
        "out_of_bounds": "error",
        "anchor_prim_path": None,
    }
    assert frame.diagnostics["room_clamped_position_ids"] == ()
    assert frame.diagnostics["per_source_rir_summary"]["speaker"][
        "rir_length_samples"
    ]
    assert detection.diagnostics["physical_waveform"] is True
    assert detection.diagnostics["pyroomacoustics_version"] == "fake-test"
    assert detection.diagnostics["room_config"] == frame.diagnostics["room_config"]
    assert detection.diagnostics["source_waveform_mode"] == "generated://impulse"
    assert set(detection.diagnostics["rir_length_samples"]) == {
        "front",
        "right",
        "rear",
        "left",
    }
    assert set(detection.diagnostics["gcc_phat_peaks"]) == set(
        detection.diagnostics["estimated_tdoa_matrix_s"]
    )
    assert detection.diagnostics["per_mic_rms"] == detection.per_mic_rms
    assert detection.diagnostics["estimated_tdoa_matrix_s"]["rear->front"] > 0.0
    assert (
        detection.diagnostics["direct_path_delay_s"]["rear"]
        > (detection.diagnostics["direct_path_delay_s"]["front"])
    )
    assert detection.doa.estimated_bearing_deg == pytest.approx(0.0, abs=15.0)
    assert all(value > 0.0 for value in frame.aggregate_per_mic_rms.values())
    assert _FakeShoeBox.instances[-1].fs == 48_000
    assert _FakeShoeBox.instances[-1].max_order == 1
    assert _FakeShoeBox.instances[-1].kwargs["air_absorption"] is False
    assert _FakeShoeBox.instances[-1].kwargs["ray_tracing"] is False


def test_room_acoustics_fake_pyroom_schedules_multiple_sources(monkeypatch):
    _install_fake_pyroom(monkeypatch)

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("ended", (4.0, 0.0, 0.0), start_time_s=-1.0, duration_s=1.0),
        _source("b_second", (0.0, 3.0, 0.0), start_time_s=0.1, duration_s=0.5),
        _source("a_first", (3.0, 0.0, 0.0), start_time_s=0.0, duration_s=0.5),
        _source("c_truncated", (-3.0, 0.0, 0.0), start_time_s=0.2, duration_s=0.5),
        _source("future", (0.0, -3.0, 0.0), start_time_s=1.0, duration_s=0.5),
        array=array,
    )
    backend = RoomAcousticsBackend()
    window = _window(max_events=2)

    first = backend.simulate(scene, array, window)
    second = backend.simulate(scene, array, window)

    assert first == second
    assert tuple(detection.source_id for detection in first.detections) == (
        "a_first",
        "b_second",
    )
    by_source_id = {detection.source_id: detection for detection in first.detections}
    assert by_source_id["a_first"].doa.estimated_bearing_deg == pytest.approx(
        0.0,
        abs=20.0,
    )
    assert by_source_id["b_second"].doa.estimated_bearing_deg == pytest.approx(
        90.0,
        abs=20.0,
    )
    assert first.diagnostics["active_source_count"] == 2
    assert first.diagnostics["scheduled_source_ids"] == ("a_first", "b_second")
    assert set(first.diagnostics["per_source_rir_summary"]) == {
        "a_first",
        "b_second",
    }
    assert len(first.detections) == first.max_events == 2
    assert first.detections[0].detection_id == (
        "room_acoustics_room_backend_test_rig_0_a_first_00"
    )
    assert first.detections[1].detection_id == (
        "room_acoustics_room_backend_test_rig_0_b_second_01"
    )
    assert (
        first.detections[0].diagnostics["room_microphone_positions_m"]
        == first.detections[1].diagnostics["room_microphone_positions_m"]
    )


def test_room_acoustics_rejects_unknown_doa_estimator():
    with pytest.raises(ValueError, match="doa_estimator"):
        RoomAcousticsBackend(doa_estimator="music")


def test_room_acoustics_srp_backend_pins_srp_phat_estimator():
    backend = RoomAcousticsSrpBackend()
    assert backend.backend_id == "room_acoustics_srp"
    assert backend.doa_estimator == "srp_phat"
    with pytest.raises(ValueError, match="pins doa_estimator"):
        RoomAcousticsSrpBackend(doa_estimator="tdoa_least_squares")


def test_room_acoustics_srp_fake_pyroom_emits_srp_frames(monkeypatch):
    _install_fake_pyroom(monkeypatch)

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )
    backend = RoomAcousticsSrpBackend()
    frame = backend.simulate(scene, array, _window())

    detection = frame.detections[0]
    assert frame.backend_id == "room_acoustics_srp"
    assert frame.provenance == "room_acoustics"
    assert frame.diagnostics["doa_estimator"] == "srp_phat"
    assert detection.diagnostics["doa_estimator"] == "srp_phat"
    srp_diagnostics = detection.diagnostics["srp_phat"]
    assert srp_diagnostics["pair_count"] == 6
    assert srp_diagnostics["grid_point_count"] == 180
    assert srp_diagnostics["elevation_step_deg"] is None
    assert srp_diagnostics["peak_power"] > srp_diagnostics["mean_power"]
    assert detection.doa.estimated_bearing_deg == pytest.approx(0.0, abs=15.0)
    assert detection.doa.estimated_elevation_deg is None
    # GCC-PHAT delay diagnostics stay emitted alongside the SRP estimate.
    assert detection.diagnostics["estimated_tdoa_matrix_s"]["rear->front"] > 0.0
    assert frame == backend.simulate(scene, array, _window())


def test_room_acoustics_rejects_non_public_file_asset_paths(monkeypatch, tmp_path):
    _install_fake_pyroom(monkeypatch)

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    source = _source(
        "speaker",
        (3.0, 0.0, 0.0),
        audio_asset_path=str(tmp_path / "private.wav"),
    )
    scene = _room_scene_with_sources(source, array=array)

    with pytest.raises(ValueError, match="relative public package path"):
        RoomAcousticsBackend().simulate(scene, array, _window())


def test_room_acoustics_rejects_malformed_pyroom_signals(monkeypatch):
    fake_pra = _install_fake_pyroom(monkeypatch)
    fake_pra.ShoeBox = _MalformedSignalShoeBox

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(_source("speaker", (3.0, 0.0, 0.0)), array=array)

    with pytest.raises(ValueError, match="unexpected mic signal shape"):
        RoomAcousticsBackend().simulate(scene, array, _window())


def test_room_acoustics_unavailable_error_is_clear(monkeypatch):
    import isaac_audio_sensors.core.backends.room_acoustics as room_module

    original_import = room_module.importlib.import_module

    def missing(name):
        if name == "pyroomacoustics":
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(room_module.importlib, "import_module", missing)

    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(_source("speaker", (3.0, 0.0, 0.0)), array=array)
    with pytest.raises(OptionalDependencyUnavailable, match="room"):
        RoomAcousticsBackend().simulate(scene, array, _window())


class _MalformedSignalShoeBox(_FakeShoeBox):
    def simulate(self, return_premix=False):
        self.mic_array.signals = np.zeros((1, 16))
        if return_premix:
            return np.zeros((1, 16))
        return None
