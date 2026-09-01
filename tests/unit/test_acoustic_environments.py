from __future__ import annotations

from dataclasses import replace

import pytest

from isaac_audio_sensors.core.acoustics import (
    environment_to_world_point,
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
    shoebox_environment_from_bounds,
    surface_set_environment,
    world_to_environment_point,
)
from isaac_audio_sensors.core.math_utils import quaternion_from_euler_deg
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AcousticSurfaceSpec,
    Pose3D,
)


def test_five_public_builders_produce_canonical_topologies() -> None:
    free_field = free_field_environment(environment_id="free")
    half_space = half_space_environment(
        environment_id="half",
        absorption="pra.rough_concrete",
    )
    shoebox = shoebox_environment(
        environment_id="box",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.25,
    )
    prism = polygon_prism_environment(
        environment_id="l_room",
        floor_vertices_local_m=(
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 2.0, 0.0),
            (2.0, 2.0, 0.0),
            (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ),
        height_m=3.0,
    )
    surface_set = surface_set_environment(
        environment_id="open",
        surfaces=(
            AcousticSurfaceSpec(
                surface_id="floor_patch",
                role="floor",
                vertices_local_m=(
                    (0.0, 0.0, 0.0),
                    (2.0, 0.0, 0.0),
                    (2.0, 2.0, 0.0),
                    (0.0, 2.0, 0.0),
                ),
            ),
        ),
    )

    assert free_field.kind == "free_field" and not free_field.surfaces
    assert half_space.kind == "half_space"
    assert half_space.surfaces[0].infinite is True
    assert shoebox.kind == "shoebox" and shoebox.dimensions_m == (6.0, 5.0, 3.0)
    assert {surface.surface_id for surface in shoebox.surfaces} == {
        "floor",
        "ceiling",
        "wall_x_min",
        "wall_x_max",
        "wall_y_min",
        "wall_y_max",
    }
    assert prism.kind == "polygon_prism" and len(prism.surfaces) == 8
    assert surface_set.kind == "surface_set" and len(surface_set.surfaces) == 1


def test_shoebox_from_bounds_sets_world_pose_and_local_dimensions() -> None:
    environment = shoebox_environment_from_bounds(
        min_world=(2.0, 1.0, -0.5),
        max_world=(8.0, 5.0, 2.5),
        environment_id="bounded",
    )

    assert environment.world_pose.position_m == (2.0, 1.0, -0.5)
    assert environment.world_pose.orientation_xyzw == (0.0, 0.0, 0.0, 1.0)
    assert environment.dimensions_m == (6.0, 4.0, 3.0)


@pytest.mark.parametrize(
    "orientation",
    (
        quaternion_from_euler_deg(yaw_deg=90.0),
        quaternion_from_euler_deg(roll_deg=25.0, pitch_deg=-15.0, yaw_deg=40.0),
    ),
)
def test_world_environment_transform_round_trip_for_rotated_and_inclined_pose(
    orientation,
) -> None:
    environment = shoebox_environment(
        environment_id="posed",
        dimensions_m=(4.0, 3.0, 2.0),
        position_world=(1.0, -2.0, 0.5),
        orientation_world_quat=orientation,
    )
    local = (2.25, 1.25, 0.75)

    world = environment_to_world_point(environment, local)

    assert world_to_environment_point(environment, world) == pytest.approx(local)


def test_environment_and_surface_invariants_fail_closed() -> None:
    with pytest.raises(ValueError, match="positive"):
        shoebox_environment(environment_id="flat", dimensions_m=(4.0, 3.0, 0.0))
    with pytest.raises(ValueError, match="simple polygon"):
        AcousticSurfaceSpec(
            surface_id="bowtie",
            role="floor",
            vertices_local_m=(
                (0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
                (2.0, 0.0, 0.0),
            ),
        )
    with pytest.raises(ValueError, match="coplanar"):
        AcousticSurfaceSpec(
            surface_id="warped",
            role="wall",
            vertices_local_m=(
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.1),
            ),
        )
    with pytest.raises(ValueError, match="at least one bounded"):
        surface_set_environment(environment_id="empty", surfaces=())
    with pytest.raises(ValueError, match="canonical six"):
        replace(
            shoebox_environment(environment_id="box", dimensions_m=(4.0, 3.0, 2.0)),
            dimensions_m=(5.0, 3.0, 2.0),
        )
    with pytest.raises(ValueError, match="orientation_xyzw is required"):
        AcousticEnvironmentSpec(
            environment_id="incomplete",
            kind="free_field",
            world_pose=Pose3D(position_m=(0.0, 0.0, 0.0)),
        )


@pytest.mark.parametrize("absorption", (-0.1, 1.1, True, {}, {"125": False}))
def test_surface_absorption_rejects_invalid_values(absorption) -> None:
    with pytest.raises(ValueError, match="absorption"):
        AcousticSurfaceSpec(
            surface_id="surface",
            role="floor",
            vertices_local_m=(
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ),
            absorption=absorption,
        )


def test_polygon_prism_rejects_non_simple_or_non_local_floor() -> None:
    with pytest.raises(ValueError, match="self-intersect|simple polygon"):
        polygon_prism_environment(
            environment_id="bowtie",
            floor_vertices_local_m=(
                (0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
                (2.0, 0.0, 0.0),
            ),
            height_m=2.0,
        )
    with pytest.raises(ValueError, match="local z=0"):
        polygon_prism_environment(
            environment_id="raised",
            floor_vertices_local_m=(
                (0.0, 0.0, 1.0),
                (2.0, 0.0, 1.0),
                (0.0, 2.0, 1.0),
            ),
            height_m=2.0,
        )
