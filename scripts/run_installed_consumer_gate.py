"""Run an external consumer's contract fixtures against the installed wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE_NAME = "isaac_audio_sensors"
CONSUMER_TEST = "tests/test_squadbot_audio_contract_freeze.py"
CONSUMER_DEPENDENCIES = (
    "numpy",
    "protobuf>=3.20,<6",
    "pytest>=8,<9",
)
FORBIDDEN_BOUNDARY_TOKENS = (
    "AuditoryCue",
    "auditory_cue",
    "MiniSceneGraph",
    "scene_graph",
    "ontology",
    "Squad" + "Bot",
)


class ConsumerGateError(RuntimeError):
    """Raised when an installed-consumer gate invariant fails."""


class ConsumerGateBlocked(ConsumerGateError):
    """Raised when the external consumer or its runtime is unavailable."""


@dataclass(frozen=True, slots=True)
class ConsumerSnapshot:
    """Identity and byte-preserving Git status for the consumer checkout."""

    revision: str
    status_porcelain: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured subprocess result and elapsed wall time."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


def utc_now() -> str:
    """Return an evidence-friendly UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sums(path: str | Path) -> dict[str, str]:
    """Parse a GNU-style checksum inventory and reject unsafe ambiguity."""

    checksum_path = Path(path)
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConsumerGateError(f"cannot read {checksum_path}: {exc}") from exc
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ConsumerGateError(
                f"{checksum_path}:{line_number}: malformed checksum entry"
            )
        digest, raw_name = parts
        name = raw_name.lstrip("*")
        if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ConsumerGateError(
                f"{checksum_path}:{line_number}: invalid SHA-256 digest"
            )
        pure_name = PurePosixPath(name)
        if pure_name.is_absolute() or ".." in pure_name.parts or name in {"", "."}:
            raise ConsumerGateError(
                f"{checksum_path}:{line_number}: unsafe artifact path {name!r}"
            )
        normalized = pure_name.as_posix()
        if normalized in entries:
            raise ConsumerGateError(
                f"{checksum_path}:{line_number}: duplicate artifact {normalized!r}"
            )
        entries[normalized] = digest.lower()
    if not entries:
        raise ConsumerGateError(f"no checksums found in {checksum_path}")
    return entries


def verify_wheel(dist_dir: str | Path) -> dict[str, Any]:
    """Select and verify the one sensor wheel named by ``SHA256SUMS``."""

    root = Path(dist_dir).expanduser().resolve()
    checksums_path = root / "SHA256SUMS"
    checksums = parse_sha256sums(checksums_path)
    prefix = f"{PACKAGE_NAME}-"
    matches = [
        name
        for name in checksums
        if PurePosixPath(name).name.startswith(prefix) and name.endswith(".whl")
    ]
    if len(matches) != 1:
        raise ConsumerGateError(
            "SHA256SUMS must name exactly one isaac_audio_sensors wheel; "
            f"found {len(matches)}"
        )
    relative = matches[0]
    wheel = (root / relative).resolve()
    _assert_inside(wheel, root, "wheel")
    if not wheel.is_file():
        raise ConsumerGateError(f"wheel is missing: {wheel}")
    actual = sha256_file(wheel)
    expected = checksums[relative]
    if actual != expected:
        raise ConsumerGateError(
            f"SHA-256 mismatch for {wheel}: expected {expected}, got {actual}"
        )
    return {
        "path": str(wheel),
        "relative_path": relative,
        "sha256": actual,
        "size_bytes": wheel.stat().st_size,
        "checksums_path": str(checksums_path),
    }


def build_sanitized_env(
    source: dict[str, str] | os._Environ[str],
    *,
    additions: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Remove Python/pip contamination and return the evidence delta."""

    clean = {
        key: value
        for key, value in source.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"} and not key.startswith("PIP_")
    }
    removed = sorted(set(source) - set(clean))
    clean["PYTHONNOUSERSITE"] = "1"
    if additions:
        clean.update(additions)
    return clean, {
        "removed": removed,
        "added_or_replaced": sorted(additions or {}),
    }


def run_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float,
) -> CommandResult:
    """Run one command with complete captured output and a hard timeout."""

    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ConsumerGateBlocked(f"command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConsumerGateError(
            f"command timed out after {timeout_s}s: {' '.join(command)}"
        ) from exc
    return CommandResult(
        command=tuple(str(part) for part in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_s=time.monotonic() - started,
    )


def snapshot_consumer(
    consumer_repo: str | Path,
    *,
    timeout_s: float = 30.0,
) -> ConsumerSnapshot:
    """Record the external checkout revision and verbatim porcelain status."""

    consumer = Path(consumer_repo).expanduser().resolve()
    if not consumer.is_dir():
        raise ConsumerGateBlocked(f"consumer repository is missing: {consumer}")
    git = shutil.which("git")
    if git is None:
        raise ConsumerGateBlocked("git is unavailable; cannot protect the consumer")
    clean_env, _delta = build_sanitized_env(
        os.environ, additions={"GIT_OPTIONAL_LOCKS": "0"}
    )
    head = run_command(
        [git, "-C", str(consumer), "rev-parse", "HEAD"],
        cwd=consumer,
        env=clean_env,
        timeout_s=timeout_s,
    )
    status = run_command(
        [git, "-C", str(consumer), "status", "--porcelain"],
        cwd=consumer,
        env=clean_env,
        timeout_s=timeout_s,
    )
    if head.returncode != 0 or status.returncode != 0:
        detail = (head.stderr + status.stderr).strip()
        raise ConsumerGateBlocked(
            f"consumer is not an available Git checkout: {consumer}: {detail}"
        )
    return ConsumerSnapshot(head.stdout.strip(), status.stdout)


def assert_consumer_unchanged(
    before: ConsumerSnapshot,
    after: ConsumerSnapshot,
) -> None:
    """Fail when consumer identity or porcelain bytes differ in any way."""

    if after.revision != before.revision:
        raise ConsumerGateError(
            "consumer repository revision changed during gate: "
            f"{before.revision} != {after.revision}"
        )
    if after.status_porcelain != before.status_porcelain:
        raise ConsumerGateError(
            "consumer repository was modified during gate; before/after "
            "git status --porcelain snapshots differ"
        )


def compare_determinism_outputs(
    first_path: str | Path,
    second_path: str | Path,
) -> dict[str, Any]:
    """Hash two canonical graph exports and report exact equality."""

    first = Path(first_path)
    second = Path(second_path)
    first_hash = sha256_file(first)
    second_hash = sha256_file(second)
    return {
        "first_path": str(first),
        "second_path": str(second),
        "first_sha256": first_hash,
        "second_sha256": second_hash,
        "identical": (
            first_hash == second_hash and first.read_bytes() == second.read_bytes()
        ),
    }


def scan_installed_boundary(package_dir: str | Path) -> dict[str, Any]:
    """Scan installed Python/JSON package content for downstream concepts."""

    root = Path(package_dir).resolve()
    if not root.is_dir():
        raise ConsumerGateError(f"installed package directory is missing: {root}")
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".json"}
    )
    hits: list[dict[str, Any]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ConsumerGateError(
                f"cannot scan installed file {path}: {exc}"
            ) from exc
        for line_number, line in enumerate(lines, start=1):
            for token in FORBIDDEN_BOUNDARY_TOKENS:
                if token in line:
                    hits.append(
                        {
                            "file": path.relative_to(root).as_posix(),
                            "line": line_number,
                            "token": token,
                            "text": line.strip(),
                        }
                    )
    return {
        "package_dir": str(root),
        "tokens": list(FORBIDDEN_BOUNDARY_TOKENS),
        "files_scanned": len(files),
        "hits": hits,
        "passed": not hits,
    }


def classify_exception(exc: BaseException) -> str:
    """Map explicit cross-repository blockers separately from gate failures."""

    return "blocked" if isinstance(exc, ConsumerGateBlocked) else "failed"


def _assert_inside(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ConsumerGateError(f"{label} resolves outside {root}: {path}") from exc


def _assert_not_inside(path: Path, protected: Path, label: str) -> None:
    try:
        path.relative_to(protected)
    except ValueError:
        return
    raise ConsumerGateError(
        f"{label} must not be inside the consumer repository: {path}"
    )


def _write_command_log(path: Path, result: CommandResult) -> None:
    content = (
        f"command: {list(result.command)!r}\n"
        f"returncode: {result.returncode}\n"
        f"duration_s: {result.duration_s:.6f}\n"
        "--- stdout ---\n"
        f"{result.stdout}"
        "\n--- stderr ---\n"
        f"{result.stderr}"
    )
    path.write_text(content, encoding="utf-8")


def _require_success(result: CommandResult, label: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ConsumerGateError(
            f"{label} failed with exit code {result.returncode}: {detail}"
        )


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _consumer_environment(
    *,
    consumer: Path,
    venv_dir: Path,
    scratch_dir: Path,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    path_value = os.environ.get("PATH", os.defpath)
    additions = {
        "PATH": f"{_venv_python(venv_dir).parent}{os.pathsep}{path_value}",
        "PYTHONPATH": str(consumer),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(scratch_dir / "tmp"),
        "VIRTUAL_ENV": str(venv_dir),
    }
    return build_sanitized_env(os.environ, additions=additions)


def _provenance_code() -> str:
    return "\n".join(
        (
            "import isaac_audio_sensors, json, pathlib, sysconfig",
            "package_file = pathlib.Path(isaac_audio_sensors.__file__).resolve()",
            "purelib = pathlib.Path(sysconfig.get_paths()['purelib']).resolve()",
            "print(json.dumps({'package_file': str(package_file), "
            "'package_dir': str(package_file.parent), 'purelib': str(purelib)}))",
        )
    )


def _assert_installed_provenance(
    payload: dict[str, str],
    *,
    sensor_repo: Path,
    consumer_repo: Path,
) -> None:
    package_file = Path(payload["package_file"]).resolve()
    purelib = Path(payload["purelib"]).resolve()
    _assert_inside(package_file, purelib, "installed package")
    # The scratch venv may itself live under the sensor repo (outputs/), so
    # the sibling-source rule targets the source trees, not the whole repos.
    for source_tree in (sensor_repo / "src", consumer_repo):
        try:
            package_file.relative_to(source_tree)
        except ValueError:
            continue
        raise ConsumerGateError(
            f"package provenance points into a repository checkout: {package_file}"
        )


def _determinism_driver_source() -> str:
    return '''from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from adapters.isaac_audio_squadbot_adapter import insert_frame_audio_events
from isaac_audio_sensors.core.io.traces import read_frame_trace
from scripts.phase0_demo_support import build_minimal_scene_graph, compiled_proto_module
from world_model.auditory_cue import AuditoryCueProvenance
from world_model.mini_scene_graph import GraphMode


trace_path = Path(sys.argv[1]).resolve()
output_path = Path(sys.argv[2]).resolve()
frame = read_frame_trace(trace_path)
graph = build_minimal_scene_graph(
    mode=GraphMode.SIMULATED,
    run_id="installed_consumer_gate",
    reference_sensor_id="zed_front",
)
with compiled_proto_module() as asn_pb2:
    insert_frame_audio_events(
        graph,
        frame,
        proto_module=asn_pb2,
        node_id="SIM_ISAAC_AUDIO",
        provenance=AuditoryCueProvenance.SIMULATED,
    )
canonical = json.dumps(
    graph.to_export_dict(),
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
) + "\\n"
output_path.write_text(canonical, encoding="utf-8")
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
'''


def _pytest_case_summary(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    root = ET.parse(path).getroot()
    cases: list[dict[str, str]] = []
    for case in root.iter("testcase"):
        outcome = "passed"
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        cases.append(
            {
                "case": case.attrib.get("name", ""),
                "classname": case.attrib.get("classname", ""),
                "outcome": outcome,
                "time_s": case.attrib.get("time", ""),
            }
        )
    return cases


def _safe_extract_pack(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            pure_name = PurePosixPath(member.name)
            if (
                pure_name.is_absolute()
                or ".." in pure_name.parts
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise ConsumerGateError(
                    f"unsafe acoustic-pack archive member: {member.name!r}"
                )
            target = (destination / pure_name.as_posix()).resolve()
            _assert_inside(target, destination.resolve(), "acoustic-pack member")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ConsumerGateError(
                    f"cannot read acoustic-pack member: {member.name}"
                )
            with source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)


def _verified_acoustic_pack(dist_dir: Path) -> Path:
    checksums = parse_sha256sums(dist_dir / "SHA256SUMS")
    matches = [
        name
        for name in checksums
        if name.startswith("packs/") and name.endswith(".tar.gz")
    ]
    if len(matches) != 1:
        raise ConsumerGateError(
            "SHA256SUMS must name exactly one acoustic-pack archive; "
            f"found {len(matches)}"
        )
    archive = (dist_dir / matches[0]).resolve()
    _assert_inside(archive, dist_dir, "acoustic pack")
    if not archive.is_file():
        raise ConsumerGateError(f"acoustic-pack archive is missing: {archive}")
    actual = sha256_file(archive)
    if actual != checksums[matches[0]]:
        raise ConsumerGateError(
            f"SHA-256 mismatch for acoustic pack {archive}: "
            f"expected {checksums[matches[0]]}, got {actual}"
        )
    return archive


def _install_optional_acoustic_pack(
    *,
    venv_python: Path,
    dist_dir: Path,
    scratch_dir: Path,
    env: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    host_result = run_command(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "numpy==2.5.0",
            "typing_extensions==4.12.2",
        ],
        cwd=scratch_dir,
        env=env,
        timeout_s=timeout_s,
    )
    _write_command_log(scratch_dir / "acoustic_host_install.txt", host_result)
    if host_result.returncode != 0:
        raise ConsumerGateBlocked(
            "optional acoustic-pack host requirements are unavailable; see "
            f"{scratch_dir / 'acoustic_host_install.txt'}"
        )
    archive = _verified_acoustic_pack(dist_dir)
    unpacked = scratch_dir / "acoustic-pack-unpacked"
    _safe_extract_pack(archive, unpacked)
    private_root = scratch_dir / "acoustic-pack-private-root"
    install_result = run_command(
        [
            str(venv_python),
            str(unpacked / "install_pack.py"),
            "--root",
            str(private_root),
        ],
        cwd=scratch_dir,
        env=env,
        timeout_s=timeout_s,
    )
    _write_command_log(scratch_dir / "acoustic_pack_install.txt", install_result)
    _require_success(install_result, "acoustic-pack installer")
    return {
        "status": "installed_presence_only",
        "archive": str(archive),
        "private_root": str(private_root),
        "activated": False,
    }


def _resolved_scratch_dir(out_dir: Path, requested: Path | None) -> Path:
    if requested is not None:
        path = requested.expanduser().resolve()
        if path.exists() and any(path.iterdir()):
            raise ConsumerGateError(
                f"explicit scratch directory must be empty: {path}"
            )
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="scratch-", dir=out_dir)).resolve()


def _status_payload(snapshot: ConsumerSnapshot | None) -> dict[str, str] | None:
    if snapshot is None:
        return None
    return {
        "revision": snapshot.revision,
        "status_porcelain": snapshot.status_porcelain,
    }


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the installed-artifact consumer gate and write its evidence."""

    started = time.monotonic()
    sensor_repo = Path(__file__).resolve().parents[1]
    consumer = Path(args.consumer_repo).expanduser().resolve()
    dist_dir = Path(args.dist_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    requested_scratch = (
        Path(args.scratch_dir) if args.scratch_dir is not None else None
    )
    _assert_not_inside(out_dir, consumer, "output directory")
    if requested_scratch is not None:
        _assert_not_inside(
            requested_scratch.expanduser().resolve(), consumer, "scratch directory"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = _resolved_scratch_dir(out_dir, requested_scratch)
    _assert_not_inside(scratch_dir, consumer, "scratch directory")
    (scratch_dir / "tmp").mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / "consumer_gate.json"
    record: dict[str, Any] = {
        "schema": "ias.installed_consumer_gate.v1",
        "status": "started",
        "started_at": utc_now(),
        "sensor_repo": str(sensor_repo),
        "consumer_repo": str(consumer),
        "consumer_test": CONSUMER_TEST,
        "consumer_dependencies": list(CONSUMER_DEPENDENCIES),
        "dist_dir": str(dist_dir),
        "out_dir": str(out_dir),
        "scratch_dir": str(scratch_dir),
        "with_acoustic_pack": bool(args.with_acoustic_pack),
        "consumer_before": None,
        "consumer_after": None,
        "timings_s": {},
    }
    before: ConsumerSnapshot | None = None
    primary_error: BaseException | None = None

    try:
        stage_started = time.monotonic()
        before = snapshot_consumer(consumer, timeout_s=args.timeout_s)
        record["consumer_before"] = _status_payload(before)
        record["consumer_revision"] = before.revision
        record["timings_s"]["consumer_snapshot_before"] = (
            time.monotonic() - stage_started
        )

        stage_started = time.monotonic()
        wheel = verify_wheel(dist_dir)
        record["wheel"] = wheel
        record["timings_s"]["wheel_verification"] = time.monotonic() - stage_started

        clean_env, venv_env_delta = build_sanitized_env(os.environ)
        venv_dir = scratch_dir / "venv"
        stage_started = time.monotonic()
        create_result = run_command(
            [sys.executable, "-m", "venv", str(venv_dir)],
            cwd=sensor_repo,
            env=clean_env,
            timeout_s=args.timeout_s,
        )
        _write_command_log(scratch_dir / "venv_create.txt", create_result)
        if create_result.returncode != 0:
            raise ConsumerGateBlocked(
                "isolated Python venv creation failed; see "
                f"{scratch_dir / 'venv_create.txt'}"
            )
        venv_python = _venv_python(venv_dir)
        install_env, install_delta = build_sanitized_env(
            os.environ,
            additions={
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "TMPDIR": str(scratch_dir / "tmp"),
                "VIRTUAL_ENV": str(venv_dir),
            },
        )
        wheel_result = run_command(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--no-deps",
                wheel["path"],
            ],
            cwd=scratch_dir,
            env=install_env,
            timeout_s=args.timeout_s,
        )
        _write_command_log(scratch_dir / "pip_install_wheel.txt", wheel_result)
        _require_success(wheel_result, "sensor wheel installation")
        deps_result = run_command(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                *CONSUMER_DEPENDENCIES,
            ],
            cwd=scratch_dir,
            env=install_env,
            timeout_s=args.timeout_s,
        )
        _write_command_log(scratch_dir / "pip_install_consumer_deps.txt", deps_result)
        if deps_result.returncode != 0:
            raise ConsumerGateBlocked(
                "consumer test dependencies are unavailable; see "
                f"{scratch_dir / 'pip_install_consumer_deps.txt'}"
            )
        record["environment_sanitization"] = {
            "venv_creation": venv_env_delta,
            "installation": install_delta,
        }
        record["timings_s"]["venv_and_install"] = time.monotonic() - stage_started

        if args.with_acoustic_pack:
            stage_started = time.monotonic()
            record["acoustic_pack"] = _install_optional_acoustic_pack(
                venv_python=venv_python,
                dist_dir=dist_dir,
                scratch_dir=scratch_dir,
                env=install_env,
                timeout_s=args.timeout_s,
            )
            record["timings_s"]["acoustic_pack"] = time.monotonic() - stage_started
        else:
            record["acoustic_pack"] = {
                "status": "not_requested",
                "activated": False,
            }

        freeze_path = scratch_dir / "pip-freeze.txt"
        freeze_result = run_command(
            [str(venv_python), "-m", "pip", "freeze", "--all"],
            cwd=scratch_dir,
            env=install_env,
            timeout_s=args.timeout_s,
        )
        _write_command_log(scratch_dir / "pip_freeze_command.txt", freeze_result)
        _require_success(freeze_result, "pip freeze")
        freeze_path.write_text(freeze_result.stdout, encoding="utf-8")
        record["venv_freeze_path"] = str(freeze_path)

        consumer_env, consumer_delta = _consumer_environment(
            consumer=consumer,
            venv_dir=venv_dir,
            scratch_dir=scratch_dir,
        )
        record["environment_sanitization"]["consumer"] = consumer_delta
        stage_started = time.monotonic()
        provenance_result = run_command(
            [str(venv_python), "-c", _provenance_code()],
            cwd=consumer,
            env=consumer_env,
            timeout_s=args.timeout_s,
        )
        _write_command_log(scratch_dir / "provenance_output.txt", provenance_result)
        _require_success(provenance_result, "installed-package provenance probe")
        try:
            provenance = json.loads(provenance_result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise ConsumerGateError("provenance probe did not emit valid JSON") from exc
        _assert_installed_provenance(
            provenance,
            sensor_repo=sensor_repo,
            consumer_repo=consumer,
        )
        record["provenance"] = provenance
        record["timings_s"]["provenance"] = time.monotonic() - stage_started

        stage_started = time.monotonic()
        junit_path = scratch_dir / "pytest-results.xml"
        pytest_result = run_command(
            [
                str(venv_python),
                "-m",
                "pytest",
                CONSUMER_TEST,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--basetemp={scratch_dir / 'pytest'}",
                f"--junitxml={junit_path}",
            ],
            cwd=consumer,
            env=consumer_env,
            timeout_s=args.timeout_s,
        )
        pytest_output_path = scratch_dir / "consumer_pytest_output.txt"
        _write_command_log(pytest_output_path, pytest_result)
        record["pytest"] = {
            "returncode": pytest_result.returncode,
            "output_path": str(pytest_output_path),
            "junit_path": str(junit_path),
            "cases": _pytest_case_summary(junit_path),
        }
        _require_success(pytest_result, "consumer fixture suite")
        record["timings_s"]["consumer_pytest"] = time.monotonic() - stage_started

        stage_started = time.monotonic()
        driver_path = scratch_dir / "determinism_driver.py"
        driver_path.write_text(_determinism_driver_source(), encoding="utf-8")
        trace_path = sensor_repo / "examples/traces/multi_detection_frame.v1.json"
        driver_outputs = (
            scratch_dir / "graph_run_1.json",
            scratch_dir / "graph_run_2.json",
        )
        printed_hashes: list[str] = []
        for index, output_path in enumerate(driver_outputs, start=1):
            result = run_command(
                [
                    str(venv_python),
                    str(driver_path),
                    str(trace_path),
                    str(output_path),
                ],
                cwd=consumer,
                env=consumer_env,
                timeout_s=args.timeout_s,
            )
            _write_command_log(scratch_dir / f"determinism_run_{index}.txt", result)
            _require_success(result, f"determinism driver run {index}")
            printed_hashes.append(result.stdout.strip().splitlines()[-1])
        determinism = compare_determinism_outputs(*driver_outputs)
        determinism.update(
            {
                "driver_printed_hashes": printed_hashes,
                "trace_path": str(trace_path),
                "normalization": {
                    "fields": [],
                    "policy": (
                        "exact canonical export; consumer replay normalizes nothing"
                    ),
                },
            }
        )
        if printed_hashes != [
            determinism["first_sha256"],
            determinism["second_sha256"],
        ]:
            raise ConsumerGateError(
                "determinism driver's printed hashes do not match output files"
            )
        if not determinism["identical"]:
            raise ConsumerGateError(
                "installed consumer graph export is not deterministic across two runs"
            )
        record["determinism"] = determinism
        record["timings_s"]["determinism"] = time.monotonic() - stage_started

        stage_started = time.monotonic()
        boundary_scan = scan_installed_boundary(provenance["package_dir"])
        record["boundary_scan"] = boundary_scan
        if not boundary_scan["passed"]:
            first_hit = boundary_scan["hits"][0]
            raise ConsumerGateError(
                "installed generic package contains a downstream boundary token: "
                f"{first_hit['file']}:{first_hit['line']} {first_hit['token']!r}"
            )
        record["timings_s"]["boundary_scan"] = time.monotonic() - stage_started
    except BaseException as exc:  # noqa: BLE001 - evidence records every gate failure.
        primary_error = exc
    finally:
        if before is not None:
            try:
                stage_started = time.monotonic()
                after = snapshot_consumer(consumer, timeout_s=args.timeout_s)
                record["consumer_after"] = _status_payload(after)
                record["timings_s"]["consumer_snapshot_after"] = (
                    time.monotonic() - stage_started
                )
                assert_consumer_unchanged(before, after)
                record["consumer_unchanged"] = True
            except BaseException as snapshot_error:  # noqa: BLE001
                record["consumer_unchanged"] = False
                if primary_error is None:
                    primary_error = snapshot_error
                else:
                    primary_error = ConsumerGateError(
                        f"{primary_error}; additionally, consumer protection failed: "
                        f"{snapshot_error}"
                    )

    if primary_error is None:
        record["status"] = "passed"
    else:
        record["status"] = classify_exception(primary_error)
        record["error"] = {
            "type": type(primary_error).__name__,
            "message": str(primary_error),
            "action": (
                "Provide the recorded consumer checkout/dependencies and rerun."
                if record["status"] == "blocked"
                else "Inspect the recorded stage evidence, fix the defect, and rerun."
            ),
        }
    record["finished_at"] = utc_now()
    record["timings_s"]["total"] = time.monotonic() - started
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consumer-repo",
        default="/home/" + "pacquadr/Desktop/squadbot-av-phase1",
        type=Path,
    )
    parser.add_argument("--dist-dir", default=Path("dist"), type=Path)
    parser.add_argument(
        "--out-dir",
        default=Path("outputs/isaac_audio_sensors/S1/S1.8"),
        type=Path,
    )
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        help="Persistent scratch directory (default: a new directory under --out-dir).",
    )
    parser.add_argument(
        "--with-acoustic-pack",
        action="store_true",
        help=(
            "Install the pack privately for presence-only evidence; do not activate it."
        ),
    )
    parser.add_argument("--timeout-s", default=600.0, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    try:
        record = run_gate(args)
    except Exception as exc:  # noqa: BLE001 - pre-evidence argument/path failure.
        print(f"[consumer-gate] FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"[consumer-gate] {record['status'].upper()} "
        f"{Path(args.out_dir) / 'consumer_gate.json'}"
    )
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
