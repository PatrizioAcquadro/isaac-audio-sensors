from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics.environments import (
    environment_to_world_point,
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
    surface_set_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.effects.validation import UnsupportedEffectError
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AcousticSurfaceSpec,
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneSignalBlock,
    SourceOcclusion,
)
from tests.helpers import CaptureSink, FakeMaterial, FakeMicrophoneArray, FakeShoeBox

SAMPLE_RATE_HZ = 48_000
WINDOW = AudioTimeWindow(
    start_time_s=0.0,
    end_time_s=0.1,
    frame_index=0,
)


def _array(
    position_world=(0.0, 0.0, 1.0),
    orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=position_world,
        orientation_world_quat=orientation_world_quat,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _source(position_world=(2.0, 0.0, 1.0)) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position_world,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _scene(environment, *, array=None, source=None) -> AudioSceneSnapshot:
    array = _array() if array is None else array
    source = _source() if source is None else source
    return AudioSceneSnapshot(
        stage_id="analytic_test",
        sources=(source,),
        arrays=(array,),
        environment=environment,
    )


def _occlusion(
    array,
    *,
    attenuation_db: float = 20.0,
    band_attenuation_db: tuple[float, ...] | None = None,
) -> SourceOcclusion:
    mic_ids = tuple(microphone.mic_id for microphone in array.microphones)
    return SourceOcclusion(
        array_id=array.array_id,
        source_id="speaker",
        per_mic_blocked={mic_id: attenuation_db > 0.0 for mic_id in mic_ids},
        per_mic_attenuation_db={mic_id: attenuation_db for mic_id in mic_ids},
        per_mic_band_attenuation_db=(
            {mic_id: band_attenuation_db for mic_id in mic_ids}
            if band_attenuation_db is not None
            else {}
        ),
        band_centers_hz=(
            OCCLUSION_BAND_CENTERS_HZ
            if band_attenuation_db is not None
            else ()
        ),
    )


def _waveform(backend, scene) -> tuple[object, np.ndarray]:
    sink = CaptureSink()
    backend.waveform_writer = sink
    frame = backend.simulate(scene, "rig", WINDOW)
    return frame, np.asarray(sink.calls[0]["mixture"], dtype=float)


def _pad_samples(waveform: np.ndarray, sample_count: int) -> np.ndarray:
    if waveform.shape[1] == sample_count:
        return waveform
    padded = np.zeros((waveform.shape[0], sample_count), dtype=waveform.dtype)
    padded[:, : waveform.shape[1]] = waveform
    return padded


def test_propagate_emits_only_the_exact_final_microphone_mixture() -> None:
    scene = _scene(free_field_environment(environment_id="free"))
    sink = CaptureSink()
    backend = AnalyticAcoustics(waveform_writer=sink)

    block = backend.propagate(scene, "rig", WINDOW)

    assert isinstance(block, MicrophoneSignalBlock)
    assert block.samples.shape == (4, 4_800)
    assert block.microphone_ids == ("front", "right", "rear", "left")
    assert block.array_id == "rig"
    assert block.sample_rate_hz == SAMPLE_RATE_HZ
    assert block.time_window is WINDOW
    assert block.channel_validity == (True, True, True, True)
    assert block.producer_id == "analytic_acoustics"
    assert block.provenance == "synthetic/core"
    assert block.diagnostics["analytic_solver"] == {
        "solver_id": "free_field_direct",
        "provider": "core",
        "provider_version": "core",
        "environment_kind": "free_field",
    }
    assert sink.calls == []
    assert block.samples.ndim == 2
    assert not hasattr(block, "detections")
    assert not hasattr(block, "waveform_paths")

    frame = backend.simulate(scene, "rig", WINDOW)
    legacy_mixture = np.asarray(sink.calls[0]["mixture"])
    np.testing.assert_allclose(
        block.samples,
        legacy_mixture[:, : block.samples.shape[1]],
        rtol=1e-6,
        atol=1e-7,
    )
    assert frame.observations == ()


def test_propagate_supports_silent_and_mono_signal_windows() -> None:
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="mono",
        position_world=(0.0, 0.0, 1.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    scene = AudioSceneSnapshot(
        stage_id="mono",
        sources=(),
        arrays=(array,),
        environment=free_field_environment(environment_id="free"),
    )
    backend = AnalyticAcoustics()

    block = backend.propagate(scene, "rig", WINDOW)

    assert block.samples.shape == (1, 4_800)
    assert block.microphone_ids == ("center",)
    assert block.channel_validity == (True,)
    assert np.all(block.samples == 0.0)
    frame = backend.simulate(scene, "rig", WINDOW)
    assert frame.observations == ()
    assert frame.channel_validity == {"center": True}


def test_propagate_combines_sources_without_exposing_a_source_axis() -> None:
    environment = free_field_environment(environment_id="free")
    array = _array()
    first = _source()
    second = replace(
        first,
        source_id="speaker_two",
        prim_path="/World/SpeakerTwo",
        position_world=(0.0, 2.0, 1.0),
    )
    backend = AnalyticAcoustics()

    first_block = backend.propagate(
        _scene(environment, array=array, source=first),
        "rig",
        WINDOW,
    )
    second_block = backend.propagate(
        _scene(environment, array=array, source=second),
        "rig",
        WINDOW,
    )
    combined = backend.propagate(
        AudioSceneSnapshot(
            stage_id="analytic_test",
            sources=(first, second),
            arrays=(array,),
            environment=environment,
        ),
        "rig",
        WINDOW,
    )

    assert combined.samples.ndim == 2
    np.testing.assert_allclose(
        combined.samples,
        first_block.samples + second_block.samples,
        rtol=1e-6,
        atol=1e-7,
    )


def test_free_field_uses_core_without_importing_pyroom(monkeypatch) -> None:
    import isaac_audio_sensors.core.backends.analytic as analytic_module

    def blocked_import(name: str):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(analytic_module.importlib, "import_module", blocked_import)
    scene = _scene(free_field_environment(environment_id="free"))
    sink = CaptureSink()
    backend = AnalyticAcoustics(waveform_writer=sink)

    first = backend.simulate(scene, "rig", WINDOW)
    second = backend.simulate(scene, "rig", WINDOW)

    assert first == second
    assert first.producer_id == "analytic_acoustics"
    assert first.provenance == "synthetic/core"
    assert first.diagnostics["analytic_solver"] == {
        "solver_id": "free_field_direct",
        "provider": "core",
        "environment_kind": "free_field",
    }
    assert "pyroomacoustics_version" not in first.diagnostics
    assert first.waveform_paths == (f"stub://{first.frame_id}.wav",)
    assert sink.calls[0]["mixture"].shape[0] == 4
    assert sink.calls[0]["window_sample_count"] == scene.arrays[0].sample_rate_hz // 10
    assert first.observations == ()
    assert all(value > 0.0 for value in first.aggregate_per_mic_rms.values())


def test_half_space_uses_rotated_local_plane_and_one_floor_reflection() -> None:
    root_half = 2.0**-0.5
    orientation = (root_half, 0.0, 0.0, root_half)
    environment = half_space_environment(
        environment_id="tilted_floor",
        absorption=0.0,
        position_world=(1.0, -2.0, 0.5),
        orientation_world_quat=orientation,
    )
    array = _array(
        environment_to_world_point(environment, (1.0, 2.0, 1.0)),
        orientation,
    )
    source = _source(environment_to_world_point(environment, (3.0, 2.0, 1.0)))
    scene = _scene(environment, array=array, source=source)

    direct = AnalyticAcoustics(max_order=0).simulate(scene, "rig", WINDOW)
    reflected = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)

    assert reflected.diagnostics["analytic_solver"]["solver_id"] == (
        "half_space_image_source"
    )
    assert reflected.aggregate_per_mic_rms["front"] > (
        direct.aggregate_per_mic_rms["front"]
    )
    assert direct.observations == reflected.observations == ()


def test_half_space_material_and_containment_are_fail_closed() -> None:
    fully_absorbing = half_space_environment(
        environment_id="floor",
        absorption=1.0,
    )
    scene = _scene(fully_absorbing)
    direct = AnalyticAcoustics(max_order=0).simulate(scene, "rig", WINDOW)
    reflected = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)
    assert reflected.aggregate_per_mic_rms == pytest.approx(
        direct.aggregate_per_mic_rms
    )

    below = _scene(
        fully_absorbing,
        source=_source((2.0, 0.0, -0.01)),
    )
    with pytest.raises(ValueError, match="below half_space"):
        AnalyticAcoustics(max_order=1).simulate(below, "rig", WINDOW)

    named_material = half_space_environment(
        environment_id="material_floor",
        absorption="pra.rough_concrete",
    )
    material_frame = AnalyticAcoustics(max_order=1).simulate(
        _scene(named_material),
        "rig",
        WINDOW,
    )
    assert material_frame.diagnostics["acoustics_state"]["material_evidence"]


@pytest.mark.parametrize(
    ("environment", "kwargs", "message"),
    (
        (
            free_field_environment(environment_id="free"),
            {"max_order": 1},
            "requires max_order=0",
        ),
        (
            half_space_environment(environment_id="half"),
            {"max_order": 2},
            "supports max_order 0 or 1",
        ),
        (
            free_field_environment(environment_id="free"),
            {"air_absorption": True},
            "only for PyRoom",
        ),
        (
            half_space_environment(environment_id="half"),
            {"ray_tracing": True},
            "only for PyRoom",
        ),
    ),
)
def test_core_solver_options_fail_closed(environment, kwargs, message) -> None:
    with pytest.raises(UnsupportedEffectError, match=message):
        AnalyticAcoustics(**kwargs).simulate(_scene(environment), "rig", WINDOW)


def test_surface_set_is_rejected() -> None:
    surface = AcousticSurfaceSpec(
        surface_id="panel",
        role="wall",
        vertices_local_m=((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
        absorption=0.2,
    )
    environment = surface_set_environment(
        environment_id="panels",
        surfaces=(surface,),
    )
    with pytest.raises(UnsupportedEffectError, match="GeometryAcoustics"):
        AnalyticAcoustics().simulate(_scene(environment), "rig", WINDOW)


def test_free_field_occlusion_attenuates_direct_path_once() -> None:
    array = _array()
    scene = _scene(free_field_environment(environment_id="free"), array=array)
    _baseline_frame, baseline = _waveform(AnalyticAcoustics(), scene)
    occluded_scene = replace(scene, occlusion=(_occlusion(array),))
    occluded_frame, occluded = _waveform(AnalyticAcoustics(), occluded_scene)

    np.testing.assert_allclose(occluded, baseline * 0.1, rtol=0.0, atol=1e-15)
    assert occluded_frame.observations == ()


def test_half_space_occlusion_recombines_attenuated_direct_and_reflection() -> None:
    array = _array()
    scene = _scene(
        half_space_environment(environment_id="floor", absorption=0.0),
        array=array,
    )
    _direct_frame, direct = _waveform(AnalyticAcoustics(max_order=0), scene)
    _full_frame, full = _waveform(AnalyticAcoustics(max_order=1), scene)
    occluded_scene = replace(scene, occlusion=(_occlusion(array),))
    _occluded_frame, occluded = _waveform(
        AnalyticAcoustics(max_order=1), occluded_scene
    )

    sample_count = max(direct.shape[1], full.shape[1], occluded.shape[1])
    direct = _pad_samples(direct, sample_count)
    full = _pad_samples(full, sample_count)
    occluded = _pad_samples(occluded, sample_count)
    np.testing.assert_allclose(
        occluded,
        0.1 * direct + (full - direct),
        rtol=0.0,
        atol=1e-15,
    )


def test_zero_occlusion_preserves_complete_premix_bytes(monkeypatch) -> None:
    _install_closed_room_fake(monkeypatch)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.2,
    )
    array = _array((1.0, 1.0, 1.0))
    scene = _scene(environment, array=array, source=_source((3.0, 1.0, 1.0)))
    _baseline_frame, baseline = _waveform(AnalyticAcoustics(max_order=1), scene)
    zero_bands = (0.0,) * len(OCCLUSION_BAND_CENTERS_HZ)
    clear = _occlusion(
        array,
        attenuation_db=0.0,
        band_attenuation_db=zero_bands,
    )
    _clear_frame, observed = _waveform(
        AnalyticAcoustics(max_order=1),
        replace(scene, occlusion=(clear,)),
    )

    assert observed.tobytes() == baseline.tobytes()


@pytest.mark.parametrize("environment_kind", ("shoebox", "polygon_prism"))
def test_pyroom_occlusion_recombines_direct_and_indirect_stems(
    monkeypatch,
    environment_kind,
) -> None:
    _install_closed_room_fake(monkeypatch)
    if environment_kind == "shoebox":
        environment = shoebox_environment(
            environment_id="room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.2,
        )
    else:
        environment = polygon_prism_environment(
            environment_id="prism",
            floor_vertices_local_m=(
                (0.0, 0.0, 0.0),
                (6.0, 0.0, 0.0),
                (6.0, 5.0, 0.0),
                (0.0, 5.0, 0.0),
            ),
            height_m=3.0,
            absorption=0.2,
        )
    array = _array((1.0, 1.0, 1.0))
    scene = _scene(environment, array=array, source=_source((3.0, 1.0, 1.0)))
    _direct_frame, direct = _waveform(AnalyticAcoustics(max_order=0), scene)
    _full_frame, full = _waveform(AnalyticAcoustics(max_order=1), scene)
    _occluded_frame, occluded = _waveform(
        AnalyticAcoustics(max_order=1),
        replace(scene, occlusion=(_occlusion(array),)),
    )

    sample_count = max(direct.shape[1], full.shape[1], occluded.shape[1])
    direct = _pad_samples(direct, sample_count)
    full = _pad_samples(full, sample_count)
    occluded = _pad_samples(occluded, sample_count)
    np.testing.assert_allclose(
        occluded,
        0.1 * direct + (full - direct),
        rtol=0.0,
        atol=1e-15,
    )


def test_pyroom_band_occlusion_filters_only_the_direct_stem(monkeypatch) -> None:
    _install_closed_room_fake(monkeypatch)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.2,
    )
    array = _array((1.0, 1.0, 1.0))
    scene = _scene(environment, array=array, source=_source((3.0, 1.0, 1.0)))
    _direct_frame, direct = _waveform(AnalyticAcoustics(max_order=0), scene)
    _full_frame, full = _waveform(AnalyticAcoustics(max_order=1), scene)
    bands = (3.0, 6.0, 9.0, 12.0, 15.0, 18.0)
    _occluded_frame, occluded = _waveform(
        AnalyticAcoustics(max_order=1),
        replace(
            scene,
            occlusion=(
                _occlusion(
                    array,
                    attenuation_db=sum(bands) / len(bands),
                    band_attenuation_db=bands,
                ),
            ),
        ),
    )

    sample_count = max(direct.shape[1], full.shape[1], occluded.shape[1])
    direct = _pad_samples(direct, sample_count)
    full = _pad_samples(full, sample_count)
    occluded = _pad_samples(occluded, sample_count)
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / SAMPLE_RATE_HZ)
    direct_spectrum = np.fft.rfft(direct, axis=1)
    full_spectrum = np.fft.rfft(full, axis=1)
    occluded_spectrum = np.fft.rfft(occluded, axis=1)
    centers = np.asarray(OCCLUSION_BAND_CENTERS_HZ)
    for center_hz in centers:
        bin_index = int(np.argmin(np.abs(frequencies - center_hz)))
        frequency_hz = frequencies[bin_index]
        expected_loss_db = np.interp(
            np.log2(frequency_hz), np.log2(centers), bands
        )
        expected = (
            direct_spectrum[:, bin_index] * 10.0 ** (-expected_loss_db / 20.0)
            + full_spectrum[:, bin_index]
            - direct_spectrum[:, bin_index]
        )
        np.testing.assert_allclose(
            occluded_spectrum[:, bin_index], expected, rtol=1e-12, atol=1e-12
        )


def test_pyroom_uses_requested_sound_speed_and_fails_closed(monkeypatch) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.2,
    )
    scene = _scene(
        environment,
        array=_array((1.0, 1.0, 1.0)),
        source=_source((3.0, 1.0, 1.0)),
    )
    frame = AnalyticAcoustics(
        max_order=1,
        speed_of_sound_mps=300.0,
    ).simulate(scene, "rig", WINDOW)

    assert module.ShoeBox.instances[-1].c == 300.0
    assert frame.diagnostics["speed_of_sound_mps"] == 300.0

    class ConstructorOnlySoundSpeedShoeBox(FakeShoeBox):
        set_sound_speed = None

    module.ShoeBox = ConstructorOnlySoundSpeedShoeBox
    frame = AnalyticAcoustics(
        max_order=1,
        speed_of_sound_mps=300.0,
    ).simulate(scene, "rig", WINDOW)
    assert module.ShoeBox.instances[-1].c == 300.0
    assert frame.diagnostics["speed_of_sound_mps"] == 300.0

    class IgnoredSoundSpeedShoeBox(FakeShoeBox):
        set_sound_speed = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.c = 343.0

    module.ShoeBox = IgnoredSoundSpeedShoeBox
    with pytest.raises(ValueError, match="cannot apply speed_of_sound_mps"):
        AnalyticAcoustics(
            max_order=1,
            speed_of_sound_mps=300.0,
        ).simulate(scene, "rig", WINDOW)


def test_closed_room_import_error_is_actionable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyroomacoustics", None)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
    )

    with pytest.raises(OptionalDependencyUnavailable, match="optional 'room' extra"):
        AnalyticAcoustics().simulate(_scene(environment), "rig", WINDOW)


def test_shoebox_routes_to_pyroom_with_per_surface_materials(monkeypatch) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.2,
    )
    environment = replace(
        environment,
        surfaces=tuple(
            replace(surface, absorption=0.1 + index * 0.1)
            for index, surface in enumerate(environment.surfaces)
        ),
    )

    frame = AnalyticAcoustics(max_order=1).simulate(
        _scene(
            environment,
            array=_array((1.0, 1.0, 1.0)),
            source=_source((3.0, 1.0, 1.0)),
        ),
        "rig",
        WINDOW,
    )

    assert frame.provenance == "room_acoustics"
    assert frame.diagnostics["analytic_solver"] == {
        "solver_id": "pyroom_shoebox",
        "provider": "pyroomacoustics",
        "environment_kind": "shoebox",
    }
    assert frame.diagnostics["pyroomacoustics_version"] == "fake-analytic"
    assert set(frame.diagnostics["environment_config"]["absorption"]) == {
        surface.surface_id for surface in environment.surfaces
    }
    assert set(module.ShoeBox.instances[-1].kwargs["materials"]) == {
        "west",
        "east",
        "south",
        "north",
        "floor",
        "ceiling",
    }


def test_concave_polygon_routes_through_from_corners_and_checks_containment(
    monkeypatch,
) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = polygon_prism_environment(
        environment_id="concave",
        floor_vertices_local_m=(
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 4.0, 0.0),
            (2.0, 2.0, 0.0),
            (0.0, 4.0, 0.0),
        ),
        height_m=3.0,
        absorption="pra.rough_concrete",
    )
    array = _array((1.0, 1.0, 1.0))
    scene = _scene(environment, array=array, source=_source((3.0, 1.0, 1.0)))

    frame = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)

    assert frame.diagnostics["analytic_solver"]["solver_id"] == (
        "pyroom_polygon_prism"
    )
    assert frame.observations == ()
    assert all(value > 0.0 for value in frame.aggregate_per_mic_rms.values())
    room = module.Room.instances[-1]
    assert room.extruded_height == 3.0
    assert len(room.kwargs["materials"]) == 5
    assert set(room.extrude_materials) == {"floor", "ceiling"}

    outside = _scene(
        environment,
        array=array,
        source=_source((2.0, 3.5, 1.0)),
    )
    with pytest.raises(ValueError, match="outside polygon-prism"):
        AnalyticAcoustics().simulate(outside, "rig", WINDOW)


def test_malformed_prism_fails_before_pyroom_room_construction(monkeypatch) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = polygon_prism_environment(
        environment_id="invalid_prism",
        floor_vertices_local_m=(
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ),
        height_m=2.5,
    )
    malformed_wall = replace(
        environment.surfaces[2],
        vertices_local_m=(
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.0, 2.5),
            (1.0, 0.0, 2.5),
        ),
    )
    environment = replace(
        environment,
        surfaces=(*environment.surfaces[:2], malformed_wall, *environment.surfaces[3:]),
    )

    with pytest.raises(ValueError, match="does not map uniquely"):
        AnalyticAcoustics().simulate(
            _scene(
                environment,
                array=_array((1.0, 1.0, 1.0)),
                source=_source((3.0, 1.0, 1.0)),
            ),
            "rig",
            WINDOW,
        )

    assert module.Room.instances == []


class _FakePolygonRoom(FakeShoeBox):
    def __init__(self, corners, **kwargs):
        xs, ys = np.asarray(corners, dtype=float)
        super().__init__(
            (float(np.ptp(xs)), float(np.ptp(ys)), 1.0),
            **kwargs,
        )
        self.corners = np.asarray(corners, dtype=float)
        self.extruded_height = 0.0
        self.extrude_materials = None

    def extrude(self, height, *, materials):
        self.extruded_height = float(height)
        self.extrude_materials = materials

    def is_inside(self, position) -> bool:
        x, y, z = (float(value) for value in position)
        if z < 0.0 or z > self.extruded_height:
            return False
        vertices = tuple(zip(self.corners[0], self.corners[1], strict=True))
        inside = False
        previous = vertices[-1]
        for current in vertices:
            if (current[1] > y) != (previous[1] > y):
                crossing = (previous[0] - current[0]) * (y - current[1]) / (
                    previous[1] - current[1]
                ) + current[0]
                if x < crossing:
                    inside = not inside
            previous = current
        return inside


class _FakeRoomApi:
    instances: list[_FakePolygonRoom] = []

    @classmethod
    def from_corners(cls, corners, **kwargs):
        room = _FakePolygonRoom(corners, **kwargs)
        cls.instances.append(room)
        return room


def _install_closed_room_fake(monkeypatch):
    import types

    module = types.ModuleType("pyroomacoustics")
    module.__version__ = "fake-analytic"
    module.Material = FakeMaterial
    module.MicrophoneArray = FakeMicrophoneArray
    module.ShoeBox = FakeShoeBox
    module.Room = _FakeRoomApi
    FakeShoeBox.instances = []
    _FakeRoomApi.instances = []
    monkeypatch.setitem(sys.modules, "pyroomacoustics", module)
    return module
