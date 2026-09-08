"""Download evaluation inputs and build isolated native dependencies on Ubuntu."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[2] / "build/qualification/doa/04_4"
REVISION = "bcb845434495e293df3d48f1203b7a86e1852449"


def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def verification_assets(assets, records=None):
    if records is None:
        records = [
            record
            for name in ("verification_assets.json", "reference_assets.json")
            for record in json.loads((SOURCE / name).read_text())
        ]
    for url in sorted({r["url"] for r in records}):
        group = [r for r in records if r["url"] == url]
        missing = {
            r["archive_path"]: r for r in group if not (assets / r["name"]).exists()
        }
        if missing:
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                tarfile.open(fileobj=response, mode="r|gz") as archive,
            ):
                for member in archive:
                    record = missing.pop(member.name, None)
                    if record is None:
                        continue
                    data = archive.extractfile(member).read()
                    if hashlib.sha256(data).hexdigest() != record["sha256"]:
                        raise ValueError(f"Upstream asset changed: {record['name']}")
                    if Path(record["name"]).name != record["name"]:
                        raise ValueError("Asset name must be a filename")
                    (assets / record["name"]).write_bytes(data)
                    if not missing:
                        break
            if missing:
                raise ValueError("Verification assets missing from LibriSpeech archive")
    for record in records:
        data = (assets / record["name"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"Local asset changed: {record['name']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indoor-protocol", type=Path)
    args = parser.parse_args()
    if args.indoor_protocol:
        protocol = json.loads(args.indoor_protocol.read_text())
        assets = ROOT / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        verification_assets(
            assets,
            [
                r
                for block in protocol["blocks"].values()
                for r in block["speech_assets"]
            ],
        )
        print("Indoor confirmation assets verified.")
        return
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
    verification_assets(assets)
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
    # ODAS calls global FFTW cleanup while other FFT plans are still alive.
    # Keep per-plan destruction; process exit releases FFTW's global cache.
    fft_source = odas / "src/utils/fft.c"
    fft_source.write_text(
        fft_source.read_text().replace("        fftwf_cleanup();", "")
    )
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
            str(ROOT / "native_ssl.so.new"),
        ]
    )
    (ROOT / "native_ssl.so.new").replace(ROOT / "native_ssl.so")
    print("Evaluation inputs verified; isolated ODAS SSL binding built.")


if __name__ == "__main__":
    main()
