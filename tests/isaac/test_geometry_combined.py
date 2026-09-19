"""Combined native pressure, persistent stream lifecycle and environment isolation."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("pxr")
from pxr import Sdf, UsdGeom  # noqa: E402

from isaac_audio_sensors.core.effects import (  # noqa: E402
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    ElectronicsConfig,
)
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain  # noqa: E402
from isaac_audio_sensors.isaac.acoustic_scene import (  # noqa: E402
    AcousticSceneSession,
    GeometryAcoustics,
    GeometryAcousticsConfig,
    PRADiffuseConfig,
    SteamNLOSConfig,
)
from tests.isaac.geometry_helpers import SPECULAR_LIBRARY, window  # noqa: E402
from tests.isaac.test_geometry_nlos import LIBRARY, fixture_scene  # noqa: E402

RATE = 16000


@pytest.fixture
def combined_factory(tmp_path, monkeypatch):
    if not LIBRARY.exists() or not SPECULAR_LIBRARY.exists():
        pytest.skip("Optional qualified native providers are unavailable.")
    from scipy.io.wavfile import write

    asset = tmp_path / "emission.wav"
    write(
        asset, RATE, np.random.default_rng(71).normal(0, 0.1, RATE).astype(np.float32)
    )
    monkeypatch.chdir(tmp_path)
    resources = []

    def create(*, nlos=True, diffuse=True, opened=False, effects=None, **kwargs):
        stage, snapshot = fixture_scene()
        # A rear wall provides visible reflection/scattering around the screen.
        wall = UsdGeom.Mesh.Define(stage, "/RearWall")
        wall.GetSubdivisionSchemeAttr().Set("none")
        wall.GetPointsAttr().Set([(-3, 2, 0), (3, 2, 0), (3, 2, 3), (-3, 2, 3)])
        wall.GetFaceVertexCountsAttr().Set([4])
        wall.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
        for path in ("/Floor", "/Screen", "/RearWall"):
            prim = stage.GetPrimAtPath(path)
            prim.CreateAttribute("ias:absorption", Sdf.ValueTypeNames.Float).Set(0.4)
            prim.CreateAttribute("ias:scattering", Sdf.ValueTypeNames.Float).Set(0.35)
        if opened:
            stage.GetPrimAtPath("/Screen").GetAttribute("xformOp:translate").Set(
                (0, 5, 1.5)
            )
        snapshot = replace(
            snapshot,
            sources=(replace(snapshot.sources[0], audio_asset_path=asset.name),),
        )
        session = AcousticSceneSession(stage)
        config = dict(
            library_path=str(LIBRARY),
            specular_library_path=str(SPECULAR_LIBRARY),
            reflection_order=1,
            max_delay_s=0.1,
            nlos=SteamNLOSConfig(probe_spacing_m=0.5) if nlos else None,
            diffuse=PRADiffuseConfig(rays=4096, surface_spacing_m=0.5)
            if diffuse
            else None,
            diagnostics=True,
        )
        config.update(kwargs)
        producer = GeometryAcoustics(
            acoustic_scene=session,
            geometry_config=GeometryAcousticsConfig(**config),
            effects=effects,
        )
        resources.append((producer, session))
        return producer, session, snapshot

    yield create
    for producer, session in reversed(resources):
        producer.close()
        session.close()


def render(producer, snapshot, cuts=(0, 1600)):
    return np.concatenate(
        [
            producer.propagate(
                snapshot, snapshot.arrays[0].array_id, window(a / RATE, b / RATE)
            ).samples
            for a, b in zip(cuts[:-1], cuts[1:], strict=True)
        ],
        axis=1,
    )


@pytest.mark.parametrize("opened", [False, True])
def test_combined_composition_and_disjoint_los(combined_factory, opened):
    outputs = {}
    for nlos, diffuse in ((False, False), (True, False), (False, True), (True, True)):
        producer, _, snapshot = combined_factory(
            nlos=nlos, diffuse=diffuse, opened=opened
        )
        block = producer.propagate(snapshot, "array", window())
        outputs[nlos, diffuse] = block.samples
        assert np.isfinite(block.samples).all()
        if nlos and diffuse:
            diagnostic = block.diagnostics["geometry"]
            assert diagnostic["domain"] == "direct+specular+diffuse+nlos"
            assert diagnostic["diffuse"]["qualification"] == "step3_pass_with_limits"
            assert set(diagnostic["nlos"]["coverage"]["tone"]) == (
                {"los"} if opened else {"selected"}
            )
    intermediate = outputs[False, False]
    assert np.linalg.norm(intermediate) > 1e-4  # Reflections survive the closed screen.
    assert np.linalg.norm(outputs[False, True] - intermediate) > 1e-4
    np.testing.assert_allclose(
        outputs[True, True],
        outputs[True, False] + outputs[False, True] - intermediate,
        atol=2e-7,
        rtol=2e-6,
    )
    if opened:
        np.testing.assert_array_equal(outputs[True, False], intermediate)
        np.testing.assert_array_equal(outputs[True, True], outputs[False, True])
    else:
        assert np.linalg.norm(outputs[True, False] - intermediate) > 1e-4
        dry, _, dry_scene = combined_factory(
            nlos=False, diffuse=False, reflection_order=0
        )
        np.testing.assert_allclose(render(dry, dry_scene), 0, atol=1e-7)


def test_combined_partition_tail_reset_and_clock(combined_factory):
    producer, _, snapshot = combined_factory()
    snapshot = replace(
        snapshot, sources=(replace(snapshot.sources[0], duration_s=0.003),)
    )
    whole = render(producer, snapshot, (0, 8000))
    # No path can beat the 4 m straight-line travel time (allow native FIR support).
    np.testing.assert_allclose(whole[:, :140], 0, atol=1e-7)
    assert np.linalg.norm(whole[:, 240:800]) > 1e-4
    np.testing.assert_allclose(whole[:, 6400:], 0, atol=1e-7)
    producer.reset()
    parts = render(producer, snapshot, (0, 17, 97, 501, 1600, 3203, 8000))
    np.testing.assert_allclose(parts, whole, atol=2e-7, rtol=2e-6)
    with pytest.raises(ValueError, match="backwards"):
        render(producer, snapshot)
    producer.reset()
    np.testing.assert_array_equal(render(producer, snapshot, (0, 8000)), whole)
    gap = producer.propagate(snapshot, "array", window(0.6, 0.7))
    assert gap.discontinuity
    np.testing.assert_allclose(gap.samples, 0, atol=1e-7)


def test_combined_motion_door_and_rebake_partitioning(combined_factory):
    from isaac_audio_sensors.core.motion.window_motion import (
        SegmentEntityMotion,
        WindowMotionPlan,
        WindowMotionSegment,
    )

    producer, session, snapshot = combined_factory()
    door = session.stage.GetPrimAtPath("/Screen").GetAttribute("xformOp:translate")

    def run(fragmented):
        chunks = []
        for tick in range(6):
            start = tick * 160
            door.Set((0, 5 if 2 <= tick < 4 else 0, 1.5))
            if tick == 3:
                marker = UsdGeom.Cube.Define(session.stage, "/Outside")
                marker.CreateSizeAttr(0.2)
                marker.AddTranslateOp().Set((4, 0, 1.5))
            angle = tick * 0.02
            current = replace(
                snapshot,
                sources=(
                    replace(snapshot.sources[0], position_world=(2, tick * 0.005, 1.2)),
                ),
                arrays=(
                    replace(
                        snapshot.arrays[0],
                        position_world=(-2, tick * 0.003, 1.2),
                        orientation_world_quat=(
                            0,
                            0,
                            np.sin(angle / 2),
                            np.cos(angle / 2),
                        ),
                    ),
                ),
            )
            # Identical timestamped motion, independent of extra PCM read cuts.
            entities = {}
            for key, entity, velocity in (
                ("tone", current.sources[0], (0, 0.5, 0)),
                ("array", current.arrays[0], (0, 0.3, 0)),
            ):
                p, v = np.array(entity.position_world), np.array(velocity)
                entities[key] = SegmentEntityMotion(
                    start_position_world_m=tuple(p),
                    end_position_world_m=tuple(p + 0.01 * v),
                    midpoint_position_world_m=tuple(p + 0.005 * v),
                    velocity_world_mps=velocity,
                    velocity_source="authored",
                    start_orientation_world_xyzw=entity.orientation_world_quat,
                    end_orientation_world_xyzw=(
                        (0, 0, np.sin((angle + 0.02) / 2), np.cos((angle + 0.02) / 2))
                        if key == "array"
                        else entity.orientation_world_quat
                    ),
                )
            producer.window_motion = WindowMotionPlan(
                sample_rate_hz=RATE,
                window_sample_count=160,
                segments=(
                    WindowMotionSegment(
                        index=0,
                        start_sample=0,
                        end_sample=160,
                        start_time_s=start / RATE,
                        end_time_s=(start + 160) / RATE,
                        entities=entities,
                    ),
                ),
            )
            offsets = (0, 17, 51, 160) if fragmented else (0, 160)
            chunks.append(render(producer, current, tuple(start + o for o in offsets)))
        assert producer.nlos.bakes == 2
        return np.concatenate(chunks, axis=1)

    whole = run(False)
    producer.reset()
    session.stage.RemovePrim("/Outside")
    split = run(True)
    np.testing.assert_allclose(split, whole, atol=2e-7, rtol=2e-6)


def test_combined_source_array_and_environment_isolation(combined_factory):
    producer, _, snapshot = combined_factory()
    solo = render(producer, snapshot)
    producer.reset()
    two = replace(
        snapshot,
        sources=(
            snapshot.sources[0],
            replace(snapshot.sources[0], source_id="second", gain_db=-6),
        ),
    )
    np.testing.assert_allclose(
        render(producer, two), solo * (1 + 10 ** (-6 / 20)), atol=2e-7, rtol=2e-6
    )
    producer.reset()
    groups = ((2, 0), (3, 1))
    original = snapshot.arrays[0]
    arrays = tuple(
        replace(
            original,
            array_id=f"group-{i}",
            microphones=tuple(original.microphones[j] for j in indices),
        )
        for i, indices in enumerate(groups)
    )
    for i in (1, 0):
        current = replace(snapshot, arrays=(arrays[i],))
        np.testing.assert_allclose(
            render(producer, current), solo[list(groups[i])], atol=2e-7
        )
    quiet, _, quiet_scene = combined_factory()
    loud, _, loud_scene = combined_factory()
    loud_scene = replace(
        loud_scene, sources=(replace(loud_scene.sources[0], gain_db=60),)
    )
    for a, b in ((0, 501), (501, 1600)):
        render(loud, loud_scene, (a, b))
        part = render(quiet, quiet_scene, (a, b))
        np.testing.assert_allclose(part, solo[:, a:b], atol=2e-7)
        loud.reset()  # A neighbour reset cannot change quiet's pending arrivals.
    quiet.reset()
    np.testing.assert_array_equal(render(quiet, quiet_scene), solo)


def test_combined_microphone_response_and_mixture_effects_once(combined_factory):
    producer, _, snapshot = combined_factory()
    plain = render(producer, snapshot, (0, 3200))
    mic = snapshot.arrays[0].microphones[0].mic_id
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                mic: ChannelResponseMicConfig(gain_db=6, polarity=-1, delay_s=2 / RATE)
            },
        )
    )
    changed, _, current = combined_factory(effects=effects)
    result = render(changed, current, (0, 97, 501, 3200))
    np.testing.assert_allclose(
        result[0, 2:], -(10**0.3) * plain[0, :-2], atol=2e-7, rtol=2e-6
    )
    np.testing.assert_allclose(result[0, :2], 0, atol=1e-7)
    np.testing.assert_allclose(result[1:], plain[1:], atol=2e-7)
    clipped_effects = EffectsConfig(
        electronics=ElectronicsConfig(enabled=True, full_scale=0.001, bit_depth=16)
    )
    clipped, _, current = combined_factory(effects=clipped_effects)
    actual = render(clipped, current, (0, 3200))
    expected, _ = ChannelEffectsChain(clipped_effects).apply_mixture(
        plain,
        mic_ids=[m.mic_id for m in current.arrays[0].microphones],
        sample_rate_hz=RATE,
        frame_id=f"{current.stage_id}:array",
        backend_id=producer.backend_id,
        runtime_profile="waveform_fidelity",
        nominal_window_start_sample=0,
    )
    np.testing.assert_array_equal(actual, expected.astype(np.float32))


@pytest.mark.parametrize("failure", ["response", "emission", "mixture"])
def test_failed_combined_read_discards_all_partial_state(
    combined_factory, monkeypatch, failure
):
    producer, _, snapshot = combined_factory()
    reference = render(producer, snapshot)
    producer.reset()
    import isaac_audio_sensors.isaac.acoustic_scene.propagation as module

    owner, attribute = {
        "response": (producer, "_responses"),
        "emission": (module, "_scheduled_window_signal"),
        "mixture": (producer.chain, "apply_mixture"),
    }[failure]
    original = getattr(owner, attribute)

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure after state advancement")

    with monkeypatch.context() as patch:
        patch.setattr(owner, attribute, fail)
        with pytest.raises(RuntimeError, match="injected failure"):
            render(producer, snapshot)
    assert (
        not producer.streams and not producer.diffuse_fields and producer.nlos is None
    )
    block = producer.propagate(snapshot, "array", window())
    assert block.discontinuity
    np.testing.assert_array_equal(block.samples, reference)


def test_combined_native_capacity_failure_is_explicit(combined_factory):
    producer, _, snapshot = combined_factory()
    producer.config = replace(producer.config, diffuse=PRADiffuseConfig(max_nodes=1))
    with pytest.raises(ValueError, match="node budget"):
        render(producer, snapshot)
    assert (
        not producer.streams and not producer.diffuse_fields and producer.nlos is None
    )


def test_combined_reconfiguration_provider_replacement_and_close(combined_factory):
    producer, session, snapshot = combined_factory()
    reference = render(producer, snapshot)
    old_fields = list(producer.diffuse_fields.values())
    session.verify_provider(str(LIBRARY))
    # Replacing the provider releases all prior streams even at the same clock.
    assert producer.propagate(snapshot, "array", window()).discontinuity
    for field in old_fields:
        assert not field.scene.handle
    changed = replace(
        snapshot,
        arrays=(
            replace(snapshot.arrays[0], microphones=snapshot.arrays[0].microphones[:2]),
        ),
    )
    block = producer.propagate(changed, "array", window(0.1, 0.2))
    assert block.discontinuity and block.samples.shape == (2, 1600)
    producer.reset()
    np.testing.assert_array_equal(render(producer, snapshot), reference)
    producer.close()
    assert (
        not producer.streams and not producer.diffuse_fields and producer.nlos is None
    )
    assert not session.closed  # The prepared session is caller-owned.
    with pytest.raises(RuntimeError, match="closed"):
        render(producer, snapshot)


@pytest.mark.parametrize("entity", ["source", "microphones"])
def test_combined_signed_directivity_is_applied_once(combined_factory, entity):
    producer, _, snapshot = combined_factory()

    def orient(quat):
        if entity == "source":
            return replace(
                snapshot,
                sources=(
                    replace(
                        snapshot.sources[0],
                        directivity="figure_eight",
                        orientation_world_quat=quat,
                    ),
                ),
            )
        array = snapshot.arrays[0]
        return replace(
            snapshot,
            arrays=(
                replace(
                    array,
                    microphones=tuple(
                        replace(
                            m,
                            directivity="figure_eight",
                            relative_orientation_quat=quat,
                        )
                        for m in array.microphones
                    ),
                ),
            ),
        )

    forward = render(producer, orient((0, 0, 0, 1)))
    producer.reset()
    backward = render(producer, orient((0, 0, 1, 0)))
    assert np.linalg.norm(forward) > 1e-4
    np.testing.assert_allclose(backward, -forward, atol=2e-7, rtol=2e-6)
