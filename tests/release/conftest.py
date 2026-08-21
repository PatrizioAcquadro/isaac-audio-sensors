from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def write_zip():
    def write(path: Path, entries: dict[str, bytes | str]) -> Path:
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)
        return path

    return write


@pytest.fixture
def wheel_bytes():
    def build(
        package: str = "sample",
        source: str = "VALUE = 1\n",
        *,
        metadata: str | None = None,
        extra_entries: dict[str, bytes | str] | None = None,
    ) -> bytes:
        dist_info = f"{package}-1.0.0.dist-info"
        payloads = {
            f"{package}/__init__.py": source.encode(),
            f"{dist_info}/METADATA": (
                metadata
                or f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0.0\n"
            ).encode(),
            f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
            f"{dist_info}/top_level.txt": f"{package}\n".encode(),
        }
        for name, raw in (extra_entries or {}).items():
            payloads[name] = raw.encode() if isinstance(raw, str) else raw
        record_name = f"{dist_info}/RECORD"
        rows = []
        for name, payload in payloads.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            rows.append((name, f"sha256={digest.decode().rstrip('=')}", len(payload)))
        rows.append((record_name, "", ""))
        stream = io.StringIO()
        csv.writer(stream, lineterminator="\n").writerows(rows)
        payloads[record_name] = stream.getvalue().encode()
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as archive:
            for name, payload in payloads.items():
                archive.writestr(name, payload)
        return result.getvalue()

    return build
