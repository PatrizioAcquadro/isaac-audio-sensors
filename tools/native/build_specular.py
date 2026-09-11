"""Build the optional PRA specular bridge without modifying installed packages.

Requires PRA 0.10.1 native sources, Eigen and nanoflann headers. No downloads.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


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
            # ISM needs reflecting polygons, not an enclosing volume. RT is not exposed.
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
        path.write_text(code)
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
