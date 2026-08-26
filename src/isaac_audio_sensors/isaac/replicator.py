"""Lazy Omniverse Replicator recording for audio sensor frames."""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.types import AudioSensorFrame

PAYLOAD_SCHEMA_VERSION = "ias.omni_replicator_audio_frame.v1"
DEFAULT_REPLICATOR_WRITER_NAME = "IsaacAudioSensorFrameWriter"
DEFAULT_REPLICATOR_ANNOTATOR_NAME = "IsaacAudioSensorFrameAnnotator"


class ReplicatorIntegrationError(RuntimeError):
    """User-facing Replicator integration failure."""


@dataclass(frozen=True, slots=True)
class ReplicatorWriteResult:
    """Result of one Replicator audio frame write."""

    frame_id: str
    record_index: int
    json_path: Path
    jsonl_path: Path


@dataclass(slots=True)
class ReplicatorRecorderStatus:
    """JSON-ready lifecycle status for the Replicator recorder."""

    enabled: bool = False
    runtime_available: bool = False
    runtime_module: str | None = None
    writer_name: str = DEFAULT_REPLICATOR_WRITER_NAME
    annotator_name: str = DEFAULT_REPLICATOR_ANNOTATOR_NAME
    output_dir: str = ""
    writer_registered: bool = False
    annotator_registered: bool = False
    annotator_status: str = "metadata_only"
    attach_status: str = "not_started"
    started: bool = False
    flushed: bool = False
    stopped: bool = False
    write_count: int = 0
    flush_count: int = 0
    latest_write_path: str | None = None
    latest_jsonl_path: str | None = None
    latest_error: str | None = None
    output_artifacts: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-ready status."""

        return {
            "enabled": self.enabled,
            "runtime_available": self.runtime_available,
            "runtime_module": self.runtime_module,
            "writer_name": self.writer_name,
            "annotator_name": self.annotator_name,
            "output_dir": self.output_dir,
            "writer_registered": self.writer_registered,
            "annotator_registered": self.annotator_registered,
            "annotator_status": self.annotator_status,
            "attach_status": self.attach_status,
            "started": self.started,
            "flushed": self.flushed,
            "stopped": self.stopped,
            "write_count": self.write_count,
            "flush_count": self.flush_count,
            "latest_write_path": self.latest_write_path,
            "latest_jsonl_path": self.latest_jsonl_path,
            "latest_error": self.latest_error,
            "output_artifacts": list(self.output_artifacts),
        }


class AudioSensorReplicatorRecorder:
    """Replicator writer facade for ``AudioSensorFrame`` data."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        writer_name: str = DEFAULT_REPLICATOR_WRITER_NAME,
        annotator_name: str = DEFAULT_REPLICATOR_ANNOTATOR_NAME,
        replicator_core: Any | None = None,
        render_products: tuple[Any, ...] = (),
    ) -> None:
        self._raw_output_dir = str(output_dir)
        self.output_dir = Path(output_dir)
        self.writer_name = writer_name
        self.annotator_name = annotator_name
        self.replicator_core = replicator_core
        self.render_products = tuple(render_products)
        self.status = ReplicatorRecorderStatus(
            enabled=True,
            writer_name=writer_name,
            annotator_name=annotator_name,
            output_dir=str(self.output_dir),
        )
        self._writer: Any | None = None
        self._writer_class: type[Any] | None = None
        self._started = False

    def start(self) -> ReplicatorRecorderStatus:
        """Register and initialize the lazy Omniverse Replicator writer."""

        try:
            self._validate_output_dir()
            rep = self.replicator_core or require_replicator_core()
            self.replicator_core = rep
            self.status.runtime_available = True
            self.status.runtime_module = getattr(rep, "__name__", type(rep).__name__)
            writer_base = getattr(rep, "Writer", object)
            self._writer_class = _make_writer_class(
                self.writer_name,
                base=writer_base if isinstance(writer_base, type) else object,
            )
            self._register_writer(rep, self._writer_class)
            self.status.writer_registered = True
            self._writer = self._instantiate_writer(rep)
            self.status.attach_status = self._attach_writer()
            self._started = True
            self.status.started = True
            self.status.stopped = False
            self.status.latest_error = None
            self._write_manifest()
            return self.status
        except Exception as exc:
            self.status.latest_error = f"{type(exc).__name__}: {exc}"
            raise

    def write_frame(
        self,
        frame: AudioSensorFrame,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ReplicatorWriteResult:
        """Write one frame through the registered Replicator writer."""

        if not self._started or self._writer is None:
            raise ReplicatorIntegrationError("Replicator recording is not started.")
        payload = audio_sensor_frame_replicator_payload(
            frame,
            metadata=metadata or {},
            writer_name=self.writer_name,
            annotator_name=self.annotator_name,
            record_index=self.status.write_count,
        )
        try:
            raw_result = _writer_write(self._writer, payload)
            json_path = Path(
                raw_result
                or getattr(self._writer, "latest_json_path", "")
                or self.output_dir
                / _frame_payload_filename(frame.frame_id, self.status.write_count)
            )
            jsonl_path = Path(
                getattr(self._writer, "latest_jsonl_path", "")
                or self.output_dir / "audio_sensor_frames.jsonl"
            )
            self.status.write_count += 1
            self.status.latest_write_path = str(json_path)
            self.status.latest_jsonl_path = str(jsonl_path)
            self.status.output_artifacts = _existing_artifacts(self.output_dir)
            self.status.latest_error = None
            self._write_manifest()
            return ReplicatorWriteResult(
                frame_id=frame.frame_id,
                record_index=self.status.write_count - 1,
                json_path=json_path,
                jsonl_path=jsonl_path,
            )
        except Exception as exc:
            self.status.latest_error = f"{type(exc).__name__}: {exc}"
            raise ReplicatorIntegrationError(f"Replicator write failed: {exc}") from exc

    def flush(self) -> ReplicatorRecorderStatus:
        """Flush the writer if it exposes a flush method and update manifest."""

        if not self._started or self._writer is None:
            raise ReplicatorIntegrationError("Replicator recording is not started.")
        try:
            flush = getattr(self._writer, "flush", None)
            if callable(flush):
                flush()
            self.status.flushed = True
            self.status.flush_count += 1
            self.status.output_artifacts = _existing_artifacts(self.output_dir)
            self.status.latest_error = None
            self._write_manifest()
            return self.status
        except Exception as exc:
            self.status.latest_error = f"{type(exc).__name__}: {exc}"
            raise ReplicatorIntegrationError(f"Replicator flush failed: {exc}") from exc

    def stop(self) -> ReplicatorRecorderStatus:
        """Stop recording and detach/flush when supported."""

        if self._writer is not None:
            detach = getattr(self._writer, "detach", None)
            if callable(detach):
                try:
                    detach()
                except Exception as exc:  # noqa: BLE001 - recorded for UI status.
                    self.status.latest_error = f"{type(exc).__name__}: {exc}"
        self._started = False
        self.status.started = False
        self.status.stopped = True
        self.status.output_artifacts = _existing_artifacts(self.output_dir)
        self._write_manifest()
        return self.status

    def _validate_output_dir(self) -> None:
        if self._raw_output_dir.strip() == "":
            raise ReplicatorIntegrationError("Replicator output directory is empty.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.is_dir():
            raise ReplicatorIntegrationError(
                f"Replicator output path is not a directory: {self.output_dir}"
            )

    def _register_writer(self, rep: Any, writer_class: type[Any]) -> None:
        registry = getattr(rep, "WriterRegistry", None)
        if registry is None:
            raise ReplicatorIntegrationError(
                "omni.replicator.core.WriterRegistry is unavailable; cannot "
                "register the Isaac Audio Sensors writer."
            )
        register = getattr(registry, "register", None)
        if not callable(register):
            raise ReplicatorIntegrationError(
                "omni.replicator.core.WriterRegistry.register is unavailable."
            )
        try:
            register(writer_class)
        except Exception as exc:
            message = str(exc).lower()
            if "already" not in message and "exists" not in message:
                raise ReplicatorIntegrationError(
                    f"Replicator writer registration failed: {exc}"
                ) from exc

    def _instantiate_writer(self, rep: Any) -> Any:
        registry = getattr(rep, "WriterRegistry", None)
        writer: Any | None = None
        get = getattr(registry, "get", None)
        if callable(get):
            try:
                writer = get(self.writer_name)
            except Exception as exc:
                raise ReplicatorIntegrationError(
                    f"Replicator writer lookup failed: {exc}"
                ) from exc
        if isinstance(writer, type):
            writer = writer()
        if writer is None:
            writer = self._writer_class() if self._writer_class is not None else None
        if writer is None:
            raise ReplicatorIntegrationError(
                f"Replicator writer {self.writer_name!r} could not be created."
            )
        initialize = getattr(writer, "initialize", None)
        if callable(initialize):
            initialize(
                output_dir=str(self.output_dir),
                writer_name=self.writer_name,
                annotator_name=self.annotator_name,
            )
        else:
            writer.output_dir = str(self.output_dir)
        return writer

    def _attach_writer(self) -> str:
        if self._writer is None:
            return "not_attached: writer unavailable"
        attach = getattr(self._writer, "attach", None)
        if not callable(attach):
            return "not_required: writer has no attach method"
        if not self.render_products:
            return "not_required: audio frame writer uses direct extension updates"
        try:
            attach(list(self.render_products))
        except Exception as exc:
            raise ReplicatorIntegrationError(
                f"Replicator writer attach failed: {exc}"
            ) from exc
        return "attached"

    def _write_manifest(self) -> None:
        manifest = self.output_dir / "audio_sensor_replicator_manifest.json"
        manifest.write_text(
            json.dumps(self.status.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.status.output_artifacts = _existing_artifacts(self.output_dir)


def require_replicator_core() -> Any:
    """Import ``omni.replicator.core`` or raise a readable optional error."""

    try:
        return importlib.import_module("omni.replicator.core")
    except ImportError as exc:
        raise IsaacIntegrationUnavailable(
            "Omniverse Replicator requires omni.replicator.core inside an "
            "Isaac Sim/Kit Python environment."
        ) from exc


def audio_sensor_frame_replicator_payload(
    frame: AudioSensorFrame,
    *,
    metadata: dict[str, Any],
    writer_name: str,
    annotator_name: str,
    record_index: int,
) -> dict[str, Any]:
    """Return the full recoverable payload written by the Replicator writer."""

    frame_payload = frame_to_trace_dict(frame)
    detections = frame_payload.get("detections", [])
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "record_index": int(record_index),
        "replicator": {
            "writer_name": writer_name,
            "annotator_name": annotator_name,
            "source": "isaac_audio_sensors.omni",
        },
        "summary": {
            "frame_id": frame.frame_id,
            "timestamp_ms": frame.timestamp_ms,
            "backend_id": frame.backend_id,
            "array_id": frame.array_id,
            "detection_count": len(frame.detections),
            "source_ids": [
                item.get("source_id")
                for item in detections
                if item.get("source_id") is not None
            ],
            "bearing_deg": [
                item.get("doa", {}).get("estimated_bearing_deg") for item in detections
            ],
            "bearing_sectors": [
                item.get("doa", {}).get("bearing_sector") for item in detections
            ],
            "diagnostics_namespaces": sorted(frame.diagnostics),
        },
        "metadata": _json_ready(metadata),
        "frame": frame_payload,
    }


def _make_writer_class(writer_name: str, *, base: type[Any] = object) -> type[Any]:
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.output_dir = ""
        self.write_count = 0
        self.latest_json_path = None
        self.latest_jsonl_path = None
        self.annotators = []

    def initialize(self: Any, **kwargs: Any) -> None:
        self.output_dir = str(kwargs.get("output_dir") or "")
        self.writer_name = str(kwargs.get("writer_name") or writer_name)
        self.annotator_name = str(
            kwargs.get("annotator_name") or DEFAULT_REPLICATOR_ANNOTATOR_NAME
        )
        if not hasattr(self, "write_count"):
            self.write_count = 0
        if not hasattr(self, "latest_json_path"):
            self.latest_json_path = None
        if not hasattr(self, "latest_jsonl_path"):
            self.latest_jsonl_path = None
        if not hasattr(self, "annotators"):
            self.annotators = []

    def write(self: Any, data: dict[str, Any]) -> Path:
        output_dir = Path(self.output_dir)
        record_index = int(data.get("record_index", self.write_count))
        frame_id = str(data.get("summary", {}).get("frame_id", "frame"))
        json_path = output_dir / _frame_payload_filename(frame_id, record_index)
        jsonl_path = output_dir / "audio_sensor_frames.jsonl"
        _write_payload_files(data, json_path=json_path, jsonl_path=jsonl_path)
        self.write_count += 1
        self.latest_json_path = str(json_path)
        self.latest_jsonl_path = str(jsonl_path)
        return json_path

    def flush(self: Any) -> None:
        return None

    def detach(self: Any) -> None:
        return None

    class_name = re.sub(r"[^0-9A-Za-z_]", "_", writer_name) or (
        DEFAULT_REPLICATOR_WRITER_NAME
    )
    return type(
        class_name,
        (base,),
        {
            "__init__": __init__,
            "initialize": initialize,
            "write": write,
            "flush": flush,
            "detach": detach,
            "__module__": __name__,
        },
    )


def _writer_write(writer: Any, payload: dict[str, Any]) -> Any:
    write_audio = getattr(writer, "write_audio_sensor_frame", None)
    if callable(write_audio):
        return write_audio(payload)
    write = getattr(writer, "write", None)
    if callable(write):
        return write(payload)
    raise ReplicatorIntegrationError("Replicator writer has no write method.")


def _write_payload_files(
    payload: dict[str, Any],
    *,
    json_path: Path,
    jsonl_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with jsonl_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        output.write("\n")


def _frame_payload_filename(frame_id: str, record_index: int) -> str:
    safe_frame_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", frame_id).strip("._")
    if not safe_frame_id:
        safe_frame_id = "frame"
    return f"audio_sensor_frame_{record_index:06d}_{safe_frame_id}.json"


def _existing_artifacts(output_dir: Path) -> tuple[str, ...]:
    if not output_dir.exists():
        return ()
    return tuple(str(path) for path in sorted(output_dir.iterdir()) if path.is_file())


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(value[key]) for key in sorted(value)}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


__all__ = [
    "DEFAULT_REPLICATOR_ANNOTATOR_NAME",
    "DEFAULT_REPLICATOR_WRITER_NAME",
    "PAYLOAD_SCHEMA_VERSION",
    "AudioSensorReplicatorRecorder",
    "ReplicatorIntegrationError",
    "ReplicatorRecorderStatus",
    "ReplicatorWriteResult",
    "audio_sensor_frame_replicator_payload",
    "require_replicator_core",
]
