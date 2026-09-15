"""Build the experimental Steam 4.8.1 selected-route interface on Linux.

Reuses an existing CPU/Embree CMake build without modifying its sources or binary.
Adds route capture and segment queries; does not qualify complete R10 propagation.
"""

import argparse
import hashlib
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Steam SDK core/")
    parser.add_argument(
        "--build", type=Path, required=True, help="Existing CMake build"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    build = args.build.resolve(strict=True) / "src/core"
    output = args.output.resolve()
    if output.is_relative_to(source) or output.is_relative_to(args.build.resolve()):
        parser.error("Output must be outside the preserved SDK and CMake build.")
    native_source = source / "src/core/path_simulator.cpp"
    # A zero-context patch requires exact input, not approximate hunk matching.
    expected = "5fa159d6b1a00393adc76fb4d112639130a1d5861173a7fba7c1fb029ce3ca18"
    if hashlib.sha256(native_source.read_bytes()).hexdigest() != expected:
        parser.error("Expected unchanged Steam 4.8.1 path_simulator.cpp.")
    flags = {}
    for line in (build / "CMakeFiles/core.dir/flags.make").read_text().splitlines():
        if line.startswith(("CXX_DEFINES =", "CXX_INCLUDES =", "CXX_FLAGS =")):
            name, value = line.split("=", 1)
            flags[name.strip()] = shlex.split(value)
    link = shlex.split((build / "CMakeFiles/phonon.dir/link.txt").read_text())
    object_name = "CMakeFiles/core.dir/path_simulator.cpp.o"
    if link.count(object_name) != 1 or link.count("-o") != 1:
        parser.error("Unsupported Steam link command.")
    with tempfile.TemporaryDirectory(prefix="ias-pathing-") as temporary:
        work = Path(temporary)
        path = work / "path_simulator.cpp"
        shutil.copyfile(native_source, path)
        subprocess.run(
            [
                "patch",
                "--batch",
                "--forward",
                "--fuzz=0",
                "-p1",
                "-i",
                str(Path(__file__).with_name("steam_paths.patch").resolve()),
            ],
            cwd=work,
            check=True,
        )
        obj = work / "path_simulator.cpp.o"
        visibility = source / "src/core/path_visibility.cpp"
        expected_visibility = (
            "79bbc3042603803059d62883c5f6c4a01225c023c383107cae7d8515105b2c76"
        )
        if hashlib.sha256(visibility.read_bytes()).hexdigest() != expected_visibility:
            parser.error("Expected unchanged Steam 4.8.1 path_visibility.cpp.")
        shutil.copyfile(visibility, work / visibility.name)
        subprocess.run(
            [
                "patch",
                "--batch",
                "--forward",
                "--fuzz=0",
                "-p1",
                "-i",
                str(Path(__file__).with_name("steam_path_visibility.patch").resolve()),
            ],
            cwd=work,
            check=True,
        )
        additions = [
            (Path(__file__).with_name(name + ".cpp").resolve(), work / (name + ".o"))
            for name in ("steam_visibility", "steam_probes")
        ]
        visibility_obj = work / "path_visibility.cpp.o"
        for source_file, object_file in [
            (path, obj),
            (work / visibility.name, visibility_obj),
            *additions,
        ]:
            subprocess.run(
                [
                    link[0],
                    *flags["CXX_DEFINES"],
                    *flags["CXX_INCLUDES"],
                    *flags["CXX_FLAGS"],
                    "-ffile-prefix-map=" + str(work) + "=ias-steam-build",
                    "-I" + str(source / "src/core"),
                    "-I" + str(Path(__file__).parent.resolve()),
                    "-c",
                    str(source_file),
                    "-o",
                    str(object_file),
                ],
                check=True,
            )
        link.extend(str(object_file) for _, object_file in additions)
        library = work / "libphonon.so"
        link[link.index("-o") + 1] = str(library)
        link[link.index(object_name)] = str(obj)
        link[link.index("CMakeFiles/core.dir/path_visibility.cpp.o")] = str(
            visibility_obj
        )
        subprocess.run(link, cwd=build, check=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Replacing the inode keeps already loaded native libraries intact.
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as target:
            pending = Path(target.name)
        try:
            shutil.copyfile(library, pending)
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)
    print(output)


if __name__ == "__main__":
    main()
