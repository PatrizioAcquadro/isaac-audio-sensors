"""Build the optional PRA specular/transport bridge without changing installed PRA.

Requires PRA 0.10.1 native sources, Eigen and nanoflann headers. No downloads.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def patch_transport(code):
    """Capture native traversal with disjoint Monte Carlo receiver ownership."""
    changes = {
        '#include "room.hpp"': (
            '#include "room.hpp"\n#include "random.hpp"\n#include "pra_diffuse.h"'
        ),
        "if (temp_dist > libroom_eps && temp_dist < hit_dist) {": (
            "if (temp_dist > libroom_eps && temp_dist < hit_dist &&\n"
            "            (!ias_pra::capture ||\n"
            "             (temp_hit - start).dot(end - start) > 0.f)) {"
        ),
        "      Wall<D> &w = scattered_ray ? walls[obstructing_walls[i]] : walls[i];": (
            "      Wall<D> &w = scattered_ray "
            "? walls[obstructing_walls[i]] : walls[i];\n"
            "      if (ias_pra::capture && ias_pra::capture->parent >= 0) {\n"
            "        const auto& last = walls[ias_pra::capture->events[\n"
            "            ias_pra::capture->parent].surface];\n"
            "        if (std::abs(w.normal.dot(last.normal)) > 1.f - libroom_eps &&\n"
            "            std::abs(w.normal.dot(start - w.origin)) <= libroom_eps)\n"
            "          continue;  // A departing ray cannot re-hit its own plane.\n"
            "      }"
        ),
        "  Vectorf<D> start = source_pos;": (
            "  Vectorf<D> start = source_pos;\n"
            "  if (ias_pra::capture) ias_pra::capture->begin(ray_direction);"
        ),
        "    if (next_wall_index == -1) break;\n\n"
        "    // Intersected wall\n"
        "    Wall<D> &wall = walls[next_wall_index];": (
            "    if (next_wall_index == -1) {\n"
            "      if (!ias_pra::capture) break;\n"
            "      hit_distance = std::max(0.f, distance_thres - travel_dist);\n"
            "      hit_point = start + dir * hit_distance;\n"
            "    }"
        ),
        "if (!(is_hybrid_sim && specular_counter < ism_order)) {": (
            "if (ias_pra::capture\n"
            "        ? (ias_pra::capture->diffuse_bounces > 0 ||\n"
            "           specular_counter > ism_order)\n"
            "        : !(is_hybrid_sim && specular_counter < ism_order)) {"
        ),
        "          microphones[k].log_histogram(travel_dist_at_mic, energy, start);": (
            "          if (ias_pra::capture) {\n"
            "            if (travel_dist_at_mic <= distance_thres)\n"
            "              ias_pra::capture->append(1, -1, int(k),\n"
            "                  microphones[k].get_loc(), dir,\n"
            "                  travel_dist_at_mic, energy);\n"
            "          }\n"
            "          else\n"
            "            microphones[k].log_histogram(\n"
            "                travel_dist_at_mic, energy, start);"
        ),
        "    // Update the characteristics\n    travel_dist += hit_distance;": (
            "    if (next_wall_index == -1) break;\n"
            "    Wall<D> &wall = walls[next_wall_index];\n"
            "    // Update the characteristics\n    travel_dist += hit_distance;"
        ),
        "    transmitted *= wall.get_energy_reflection();": (
            "    transmitted *= wall.get_energy_reflection();\n"
            "    if (ias_pra::capture && travel_dist <= distance_thres)\n"
            "      ias_pra::capture->surface(next_wall_index, wall, hit_point, dir,\n"
            "                                travel_dist, transmitted);"
        ),
        "    if (wall.does_scatter) {": (
            "    if (wall.does_scatter && !ias_pra::capture) {"
        ),
        "      Vectorf<D> scat_dir = -wall.sample_lambertian_reflection();\n"
        "      dir = wall.average_scatter * scat_dir "
        "+ (1.f - wall.average_scatter) * dir;\n"
        "      dir = dir.normalized();": """      if (ias_pra::capture) {
        const float p = wall.average_scatter;
        const bool scattered = p >= 1.f || (p > 0.f && rng::uniform(0.f, 1.f) < p);
        ias_pra::capture->branch(scattered);
        if (scattered) {
          dir = wall.sample_lambertian_reflection();
          if (wall.normal.dot(dir) * wall.normal.dot(start - hit_point) < 0)
            dir = -dir;
          transmitted *= wall.scatter / p;
        } else {
          transmitted *= (1.f - wall.scatter) / (1.f - p);
        }
      } else {
        Vectorf<D> scat_dir = -wall.sample_lambertian_reflection();
        dir = wall.average_scatter * scat_dir + (1.f - wall.average_scatter) * dir;
        dir = dir.normalized();
      }""",
    }
    for old, new in changes.items():
        if code.count(old) != 1:
            raise ValueError("Unsupported PRA transport source: " + old)
        code = code.replace(old, new)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="PRA 0.10.1 libroom_src"
    )
    parser.add_argument(
        "--eigen", type=Path, required=True, help="Directory containing Eigen/"
    )
    parser.add_argument(
        "--nanoflann",
        type=Path,
        required=True,
        help="Directory containing nanoflann.hpp",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ias-specular-") as directory:
        target = Path(directory) / "libroom_src"
        shutil.copytree(args.source, target)
        path = target / "room.cpp"
        code = path.read_text()
        changes = {
            # Native traversal also supports bounded open polygon fixtures.
            "if (walls.size() > D) {": "if (!walls.empty()) {",
            # Opposite sides of one surface must not create a zero-length double bounce.
            "if (ret >= 0)\n      // Check visibility": (
                "if (ret >= 0 && (intersection - p).norm() > libroom_eps)\n"
                "      // Check visibility"
            ),
            "if (img_side != intersection_side && intersection_side != 0)": (
                "if ((intersection_side != 0 && img_side != intersection_side) ||\n"
                "              (intersection_side == 0 &&\n"
                "               std::abs(walls[wall_id].normal.dot(\n"
                "                   walls[gen_wall_id].normal)) < 1.f - libroom_eps))"
            ),
        }
        changes[
            "    int ret = walls[wall_id].intersection(p, is.loc, intersection);"
        ] = """
    int ret = walls[wall_id].intersection(p, is.loc, intersection);
    // Shared coplanar polygon boundaries own a reflected path exactly once.
    if (ret == Wall<D>::Isect::BNDRY) {
      for (int other = 0; other < wall_id; ++other) {
        if (walls[other].normal.dot(walls[wall_id].normal) < 1.f - libroom_eps ||
            std::abs(walls[other].normal.dot(
                walls[wall_id].origin - walls[other].origin)) > libroom_eps)
          continue;
        Vectorf<D> candidate;
        if (walls[other].intersection(p, is.loc, candidate) >= 0 &&
            (candidate - intersection).norm() <= libroom_eps)
          return false;
      }
    }"""
        for old, new in changes.items():
            if code.count(old) != 1:
                raise ValueError("Unsupported or already modified PRA source: " + old)
            code = code.replace(old, new)
        path.write_text(patch_transport(code))
        shutil.copy2(Path(__file__).with_name("pra_diffuse.h"), target)
        random_path = target / "random.hpp"
        random_code = random_path.read_text()
        old = "static std::mt19937_64 engine;"
        if random_code.count(old) != 1:
            raise ValueError("Unsupported PRA random source.")
        random_path.write_text(
            random_code.replace(old, "static thread_local std::mt19937_64 engine;")
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "c++",
                "-std=c++17",
                "-O3",
                "-shared",
                "-fPIC",
                "-pthread",
                "-DEIGEN_MPL2_ONLY",
                "-DEIGEN_NO_DEBUG",
                "-I" + str(target),
                "-I" + str(args.eigen),
                "-I" + str(args.nanoflann),
                str(Path(__file__).with_name("specular.cpp")),
                "-o",
                str(args.output),
            ],
            check=True,
        )
    print(args.output)


if __name__ == "__main__":
    main()
