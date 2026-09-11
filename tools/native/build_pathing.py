"""Build the experimental Steam 4.8.1 selected-route interface on Linux.

Requires its existing CMake Makefiles build with CPU/Embree dependencies. Reuses
unchanged native objects; only path_simulator.cpp changes, with no C++ ABI change.
Does not download dependencies or modify the source SDK, build, or installed PCM
provider. This interface alone does not qualify complete R10 propagation.
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
        subprocess.run(
            [
                link[0],
                *flags["CXX_DEFINES"],
                *flags["CXX_INCLUDES"],
                *flags["CXX_FLAGS"],
                "-I" + str(source / "src/core"),
                "-c",
                str(path),
                "-o",
                str(obj),
            ],
            check=True,
        )
        library = work / "libphonon.so"
        link[link.index("-o") + 1] = str(library)
        link[link.index(object_name)] = str(obj)
        subprocess.run(link, cwd=build, check=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(library, output)
    print(output)


if __name__ == "__main__":
    main()
