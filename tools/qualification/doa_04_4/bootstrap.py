"""Download evaluation inputs and build isolated native dependencies on Ubuntu."""

import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[2] / "build/qualification/doa/04_4"
REVISION = "bcb845434495e293df3d48f1203b7a86e1852449"


def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    vendor = ROOT / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    expected = json.loads((SOURCE / "assets.json").read_text())
    base = "https://raw.githubusercontent.com/LCAV/pyroomacoustics/master/examples/input_samples/"
    for name, digest in expected.items():
        target = assets / name
        if not target.exists():
            with urllib.request.urlopen(base + name, timeout=30) as response:
                value = response.read()
            if hashlib.sha256(value).hexdigest() != digest:
                raise ValueError(f"Upstream asset changed: {name}")
            target.write_bytes(value)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Local asset changed: {name}")
    odas = vendor / "odas"
    if not odas.exists():
        run(
            [
                "git",
                "clone",
                "--no-checkout",
                "https://github.com/introlab/odas.git",
                str(odas),
            ]
        )
        run(["git", "-C", str(odas), "checkout", "--detach", REVISION])
    actual = subprocess.check_output(
        ["git", "-C", str(odas), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != REVISION:
        raise ValueError(f"ODAS revision mismatch: {actual}")
    prefix = vendor / "deps"
    packages = vendor / "debs"
    packages.mkdir(exist_ok=True)
    if not (prefix / "usr/include/libconfig.h").exists():
        run(
            [
                "apt-get",
                "download",
                "libfftw3-dev",
                "libconfig-dev",
                "libconfig9",
                "libasound2-dev",
                "libpulse-dev",
            ],
            cwd=packages,
        )
        for archive in packages.glob("*.deb"):
            run(["dpkg-deb", "-x", str(archive), str(prefix)])
        for pc in prefix.rglob("*.pc"):
            pc.write_text(pc.read_text().replace("prefix=/usr", f"prefix={prefix}/usr"))
        for link in (prefix / "usr/lib/x86_64-linux-gnu").glob("*.so"):
            if link.is_symlink() and not link.exists():
                target = Path("/usr/lib/x86_64-linux-gnu") / link.readlink().name
                if target.exists():
                    link.unlink()
                    link.symlink_to(target)
    lib = prefix / "usr/lib/x86_64-linux-gnu"
    include = prefix / "usr/include"
    env = dict(os.environ, PKG_CONFIG_PATH=str(lib / "pkgconfig"))
    link_flags = f"-L{lib} -Wl,-rpath,{lib}"
    run(
        [
            "cmake",
            "-S",
            str(odas),
            "-B",
            str(odas / "build"),
            f"-DCMAKE_C_FLAGS=-I{include}",
            f"-DCMAKE_SHARED_LINKER_FLAGS={link_flags}",
            f"-DCMAKE_EXE_LINKER_FLAGS={link_flags}",
        ],
        env=env,
    )
    run(["cmake", "--build", str(odas / "build"), "-j", "6"])
    native_lib = odas / "build/lib"
    run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-O2",
            f"-I{odas}/include",
            f"-I{odas}/include/odas",
            f"-I{odas}/demo/odaslive",
            f"-I{include}",
            str(SOURCE / "native_ssl.c"),
            str(odas / "demo/odaslive/configs.c"),
            str(odas / "demo/odaslive/parameters.c"),
            f"-L{native_lib}",
            f"-L{lib}",
            f"-Wl,-rpath,{native_lib}",
            f"-Wl,-rpath,{lib}",
            "-lodas",
            "-lconfig",
            "-lm",
            "-o",
            str(ROOT / "native_ssl.so"),
        ]
    )
    print("Evaluation inputs verified; isolated ODAS SSL binding built.")


if __name__ == "__main__":
    main()
