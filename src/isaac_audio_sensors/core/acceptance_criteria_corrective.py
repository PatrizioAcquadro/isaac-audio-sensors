"""Identity-complete evaluation for the additive S4.7 corrective contract.

Only tracked technical manifests are read. Scientific observations are supplied
by the caller after a future authorized S4.8 opening; this module has no dataset
or grant-opening code path.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any

CONFIG_PATH = Path("configs/s4_7_holdout_acceptance.corrective_01.v2.json")
SCHEMA_PATH = Path(
    "docs/schemas/s4_7_holdout_acceptance.corrective_01.v2.schema.json"
)
V1_CONFIG_PATH = Path("configs/s4_7_holdout_acceptance.v1.json")
PAYLOAD_SCHEMA = "ias.s4_7.corrective_metrics.v2"
RESULT_SCHEMA = "ias.s4_7.criteria_evaluation_result.v2"
SMALL_SAMPLE_THRESHOLD = 8

_PAYLOAD_FIELDS = frozenset({"schema", "contract", "takes", "sim_vs_real"})
_CONTRACT_FIELDS = frozenset(
    {
        "config_sha256",
        "bound_holdout_id",
        "seal_payload_sha256",
        "planned_take_count",
    }
)
_TAKE_FIELDS = frozenset(
    {
        "identity",
        "failed",
        "latency",
        "window_summary",
        "channels",
        "bearing_absolute_error_deg",
        "estimated_bearing_deg_f_project",
        "sector_correct",
        "candidate_covered",
        "confidence",
        "tdoa",
        "av_absolute_residual_ms",
    }
)
_IDENTITY_FIELDS = frozenset(
    {
        "planned_take_id",
        "stratum_id",
        "group_id",
        "bearing_cell_id",
        "repetition",
        "condition_id",
        "paired_counterpart_take_id",
    }
)
_LATENCY_FIELDS = frozenset(
    {"frame_to_adapter_round_trip_ms", "capture_to_frame_offline_ms"}
)
_WINDOW_FIELDS = frozenset(
    {
        "source_window_count",
        "abstained_window_count",
        "sub_floor_direction_emission_count",
    }
)
_CHANNEL_FIELDS = frozenset(
    {
        "microphone_id",
        "health_failure",
        "major_polarity_anomaly",
        "maximum_clip_run_samples",
    }
)
_TDOA_FIELDS = frozenset({"pair_id", "tdoa_us", "absolute_error_us"})
_COMPARISON_FIELDS = frozenset({"comparison_id", "conditions"})
_CONDITION_FIELDS = frozenset(
    {"condition_id", "real", "unadjusted_simulation", "adjusted_simulation"}
)


class CorrectiveAcceptanceError(ValueError):
    """Raised when contract, identity, or observations fail closed."""


@dataclass(frozen=True, slots=True)
class TakeIdentity:
    """One exact planned-take identity projected from the technical manifest."""

    planned_take_id: str
    stratum_id: str
    group_id: str
    bearing_cell_id: str | None
    repetition: int
    condition_id: str
    paired_counterpart_take_id: str | None
    duration_s: int

    def payload_identity(self) -> dict[str, Any]:
        return {
            "planned_take_id": self.planned_take_id,
            "stratum_id": self.stratum_id,
            "group_id": self.group_id,
            "bearing_cell_id": self.bearing_cell_id,
            "repetition": self.repetition,
            "condition_id": self.condition_id,
            "paired_counterpart_take_id": self.paired_counterpart_take_id,
        }


@dataclass(frozen=True, slots=True)
class CriterionOutcome:
    """One threshold result."""

    criterion_id: str
    tier: str
    gating: bool
    metric: str
    statistic: str
    comparator: str
    threshold: float
    observed: float
    sample_count: int
    passed: bool

    def report(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "gating": self.gating,
            "metric": self.metric,
            "observed": self.observed,
            "passed": self.passed,
            "sample_count": self.sample_count,
            "small_sample": self.sample_count < SMALL_SAMPLE_THRESHOLD,
            "statistic": self.statistic,
            "status": "evaluated",
            "threshold": self.threshold,
            "tier": self.tier,
        }


@dataclass(frozen=True, slots=True)
class CorrectiveAcceptanceResult:
    """Complete identity and criteria result."""

    outcomes: tuple[CriterionOutcome, ...]
    comparisons: tuple[dict[str, Any], ...]
    identity_summary: dict[str, Any]
    config_identity: dict[str, Any]

    @property
    def readiness_passed(self) -> bool:
        return all(item.passed for item in self.outcomes if item.gating)

    def report(self) -> dict[str, Any]:
        failed = [
            item.criterion_id
            for item in self.outcomes
            if item.gating and not item.passed
        ]
        return {
            "schema": RESULT_SCHEMA,
            "status": "passed" if self.readiness_passed else "failed",
            "readiness_passed": self.readiness_passed,
            "failed_gating_criteria": failed,
            "criteria": [item.report() for item in self.outcomes],
            "comparison_classifications": list(self.comparisons),
            "identity_summary": self.identity_summary,
            "config_identity": self.config_identity,
            "holdout_observations_accessed_by_evaluator": 0,
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corrective_config(repo_root: Path) -> dict[str, Any]:
    """Load the corrective and every hash-bound inherited contract."""

    root = repo_root.resolve()
    config_path = _repo_file(root, CONFIG_PATH)
    config = _load_json(config_path)
    schema = _load_json(_repo_file(root, SCHEMA_PATH))
    import jsonschema

    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise CorrectiveAcceptanceError(
            f"corrective config schema validation failed: {exc.message}"
        ) from exc
    if config["schema"] != "ias.s4_7.holdout_acceptance_corrective_config.v2":
        raise CorrectiveAcceptanceError("corrective config schema mismatch")
    if config["status"] != "frozen":
        raise CorrectiveAcceptanceError("corrective config is not frozen")

    bindings = [
        (
            config["supersedes"]["config_path"],
            config["supersedes"]["config_sha256"],
        ),
        (config["supersedes"]["spec_path"], config["supersedes"]["spec_sha256"]),
        (
            config["holdout_binding"]["seal_path"],
            config["holdout_binding"]["seal_file_sha256"],
        ),
        (
            config["holdout_binding"]["partition_manifest_path"],
            config["holdout_binding"]["partition_manifest_sha256"],
        ),
        (
            config["holdout_binding"]["session_manifest_path"],
            config["holdout_binding"]["session_manifest_sha256"],
        ),
        (
            config["window_contract"]["source_config_path"],
            config["window_contract"]["source_config_sha256"],
        ),
    ]
    for relative, expected in bindings:
        path = _repo_file(root, Path(relative))
        if sha256_file(path) != expected:
            raise CorrectiveAcceptanceError(f"hash binding mismatch: {relative}")
    v1 = _load_json(_repo_file(root, V1_CONFIG_PATH))
    if v1.get("status") != "frozen" or len(v1.get("criteria", [])) != 29:
        raise CorrectiveAcceptanceError("inherited v1 criteria are not frozen")
    return config


def build_identity_registry(
    repo_root: Path, config: Mapping[str, Any] | None = None
) -> dict[str, TakeIdentity]:
    """Project the exact take registry from the tracked technical manifest."""

    loaded = dict(config or load_corrective_config(repo_root))
    path = _repo_file(
        repo_root.resolve(),
        Path(loaded["holdout_binding"]["session_manifest_path"]),
    )
    manifest = _load_json(path)
    takes = manifest.get("takes")
    if not isinstance(takes, list) or len(takes) != 47:
        raise CorrectiveAcceptanceError("technical manifest must contain 47 takes")

    preliminary: dict[str, dict[str, Any]] = {}
    pair_lookup: dict[tuple[str, float, int], str] = {}
    for item in takes:
        if not isinstance(item, Mapping):
            raise CorrectiveAcceptanceError("technical take must be an object")
        take_id = _required_string(item, "planned_take_id")
        if take_id in preliminary:
            raise CorrectiveAcceptanceError(f"duplicate technical take: {take_id}")
        category = _required_string(item, "category")
        gain = item.get("playback_gain")
        stratum = _stratum_for(category, gain)
        bearing = item.get("target_bearing_deg_f_project")
        repetition = _integer(item.get("repetition"), f"{take_id}.repetition", 1)
        group_id = _required_string(item, "group_id")
        duration_s = _integer(item.get("duration_s"), f"{take_id}.duration_s", 1)
        cell_id = None if bearing is None else f"{stratum}|{float(bearing):.1f}"
        preliminary[take_id] = {
            "stratum_id": stratum,
            "group_id": group_id,
            "bearing_cell_id": cell_id,
            "repetition": repetition,
            "duration_s": duration_s,
            "bearing": None if bearing is None else float(bearing),
        }
        if stratum in {"B_center_nominal_level", "C_center_low_level"}:
            key = (stratum, float(bearing), repetition)
            if key in pair_lookup:
                raise CorrectiveAcceptanceError(f"duplicate B/C pair key: {key}")
            pair_lookup[key] = take_id

    registry: dict[str, TakeIdentity] = {}
    for take_id, item in preliminary.items():
        stratum = item["stratum_id"]
        counterpart = None
        if stratum in {"B_center_nominal_level", "C_center_low_level"}:
            other = (
                "C_center_low_level"
                if stratum == "B_center_nominal_level"
                else "B_center_nominal_level"
            )
            key = (other, item["bearing"], item["repetition"])
            counterpart = pair_lookup.get(key)
            if counterpart is None:
                raise CorrectiveAcceptanceError(
                    f"missing B/C counterpart for {take_id}"
                )
        registry[take_id] = TakeIdentity(
            planned_take_id=take_id,
            stratum_id=stratum,
            group_id=item["group_id"],
            bearing_cell_id=item["bearing_cell_id"],
            repetition=item["repetition"],
            condition_id=take_id,
            paired_counterpart_take_id=counterpart,
            duration_s=item["duration_s"],
        )
    _validate_registry_counts(registry, loaded)
    return registry


def evaluate_corrective(
    payload: Mapping[str, Any], *, repo_root: Path
) -> CorrectiveAcceptanceResult:
    """Authenticate identities, validate domains, and execute all 29 criteria."""

    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
        raise CorrectiveAcceptanceError(
            f"payload fields must be exactly {sorted(_PAYLOAD_FIELDS)}"
        )
    if payload["schema"] != PAYLOAD_SCHEMA:
        raise CorrectiveAcceptanceError("metrics payload schema mismatch")
    config = load_corrective_config(repo_root)
    registry = build_identity_registry(repo_root, config)
    _validate_contract_identity(payload["contract"], config, repo_root)
    takes = _validate_take_records(payload["takes"], registry, config)
    comparisons = _validate_comparisons(
        payload["sim_vs_real"], registry, config
    )
    values = _derive_criterion_values(takes, registry, comparisons, config)
    v1 = _load_json(_repo_file(repo_root.resolve(), V1_CONFIG_PATH))
    outcomes = tuple(
        _evaluate_threshold(item, values[item["criterion_id"]])
        for item in v1["criteria"]
    )
    stratum_counts = Counter(item.stratum_id for item in registry.values())
    return CorrectiveAcceptanceResult(
        outcomes=outcomes,
        comparisons=tuple(comparisons),
        identity_summary={
            "take_count": len(takes),
            "take_ids_sha256": _canonical_sha256(sorted(takes)),
            "stratum_counts": dict(sorted(stratum_counts.items())),
            "group_count": len({item.group_id for item in registry.values()}),
            "raw_channel_record_count": sum(
                len(item["channels"]) for item in takes.values()
            ),
            "tdoa_record_count": sum(len(item["tdoa"]) for item in takes.values()),
            "window_source_count": sum(
                item["window_summary"]["source_window_count"]
                for item in takes.values()
            ),
            "comparison_record_count": len(comparisons),
        },
        config_identity={
            "schema": config["schema"],
            "corrective_id": config["corrective_id"],
            "config_sha256": sha256_file(repo_root / CONFIG_PATH),
            "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
            "seal_payload_sha256": config["holdout_binding"][
                "seal_payload_sha256"
            ],
            "planned_take_count": 47,
            "frozen_at_utc": config["frozen_at_utc"],
        },
    )


def build_synthetic_payload(repo_root: Path, *, passing: bool = True) -> dict[str, Any]:
    """Build a deterministic identity-complete synthetic fixture."""

    config = load_corrective_config(repo_root)
    registry = build_identity_registry(repo_root, config)
    microphones = config["identity_contract"]["raw_microphone_ids"]
    pair_ids = config["identity_contract"]["microphone_pair_ids"]
    takes: list[dict[str, Any]] = []
    for take_id in sorted(registry):
        identity = registry[take_id]
        expected_windows = config["window_contract"]["expected_count_by_duration_s"][
            str(identity.duration_s)
        ]
        is_a = identity.stratum_id == "A_controlled_boundary_sweep"
        is_b = identity.stratum_id == "B_center_nominal_level"
        is_c = identity.stratum_id == "C_center_low_level"
        is_d = identity.stratum_id == "D_silence"
        is_e = identity.stratum_id == "E_impact_audio_video"
        abstained = expected_windows if is_d else 0
        takes.append(
            {
                "identity": identity.payload_identity(),
                "failed": False,
                "latency": {
                    "frame_to_adapter_round_trip_ms": 1.0,
                    "capture_to_frame_offline_ms": 10.0,
                },
                "window_summary": {
                    "source_window_count": expected_windows,
                    "abstained_window_count": abstained,
                    "sub_floor_direction_emission_count": 0,
                },
                "channels": [
                    {
                        "microphone_id": microphone,
                        "health_failure": False,
                        "major_polarity_anomaly": False,
                        "maximum_clip_run_samples": 0,
                    }
                    for microphone in microphones
                ],
                "bearing_absolute_error_deg": 4.0 if (is_a or is_b) else None,
                "estimated_bearing_deg_f_project": (
                    float(identity.bearing_cell_id.rsplit("|", 1)[1]) + 4.0
                    if is_a or is_b
                    else None
                ),
                "sector_correct": True if is_b else None,
                "candidate_covered": True if (is_a or is_b) else None,
                "confidence": 0.04 if is_b else (0.02 if is_c else None),
                "tdoa": (
                    [
                        {
                            "pair_id": pair_id,
                            "tdoa_us": 10.0,
                            "absolute_error_us": 5.0,
                        }
                        for pair_id in pair_ids
                    ]
                    if is_a
                    else []
                ),
                "av_absolute_residual_ms": 20.0 if is_e else None,
            }
        )
    comparisons = []
    for entry in config["sim_vs_real"]["comparison_registry"]:
        conditions = sorted(_expected_comparison_conditions(entry, registry, config))
        base = 0.02 if entry["unit"] in {"fraction", "dimensionless"} else 5.0
        comparisons.append(
            {
                "comparison_id": entry["comparison_id"],
                "conditions": [
                    {
                        "condition_id": condition_id,
                        "real": base,
                        "unadjusted_simulation": base,
                        "adjusted_simulation": base,
                    }
                    for condition_id in conditions
                ],
            }
        )
    if not passing:
        takes[0]["latency"]["frame_to_adapter_round_trip_ms"] = 50.0
        bearing = next(
            item
            for item in comparisons
            if item["comparison_id"] == "bearing_doa_error_ab"
        )
        for condition in bearing["conditions"]:
            condition["adjusted_simulation"] = 80.0
    return {
        "schema": PAYLOAD_SCHEMA,
        "contract": {
            "config_sha256": sha256_file(repo_root / CONFIG_PATH),
            "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
            "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
            "planned_take_count": 47,
        },
        "takes": takes,
        "sim_vs_real": comparisons,
    }


def _validate_contract_identity(
    value: Any, config: Mapping[str, Any], repo_root: Path
) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONTRACT_FIELDS:
        raise CorrectiveAcceptanceError(
            f"payload contract fields must be exactly {sorted(_CONTRACT_FIELDS)}"
        )
    expected = {
        "config_sha256": sha256_file(repo_root / CONFIG_PATH),
        "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
        "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
        "planned_take_count": 47,
    }
    if dict(value) != expected:
        raise CorrectiveAcceptanceError("payload contract identity mismatch")


def _validate_take_records(
    value: Any,
    registry: Mapping[str, TakeIdentity],
    config: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CorrectiveAcceptanceError("takes must be a sequence")
    records: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value):
        label = f"takes[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _TAKE_FIELDS:
            raise CorrectiveAcceptanceError(
                f"{label} fields must be exactly {sorted(_TAKE_FIELDS)}"
            )
        identity = raw["identity"]
        if not isinstance(identity, Mapping) or set(identity) != _IDENTITY_FIELDS:
            raise CorrectiveAcceptanceError(f"{label} identity fields are incomplete")
        take_id = _required_string(identity, "planned_take_id")
        if take_id in records:
            raise CorrectiveAcceptanceError(f"duplicate take identity: {take_id}")
        expected = registry.get(take_id)
        if expected is None:
            raise CorrectiveAcceptanceError(f"unknown take identity: {take_id}")
        if dict(identity) != expected.payload_identity():
            raise CorrectiveAcceptanceError(f"take identity mismatch: {take_id}")
        record = dict(raw)
        _validate_take_values(record, expected, config)
        records[take_id] = record
    if set(records) != set(registry):
        missing = sorted(set(registry) - set(records))
        extra = sorted(set(records) - set(registry))
        raise CorrectiveAcceptanceError(
            f"exact take set mismatch: missing={missing}, extra={extra}"
        )
    return records


def _validate_take_values(
    record: Mapping[str, Any],
    identity: TakeIdentity,
    config: Mapping[str, Any],
) -> None:
    take_id = identity.planned_take_id
    if not isinstance(record["failed"], bool):
        raise CorrectiveAcceptanceError(f"{take_id}.failed must be boolean")
    latency = record["latency"]
    if not isinstance(latency, Mapping) or set(latency) != _LATENCY_FIELDS:
        raise CorrectiveAcceptanceError(f"{take_id}.latency fields mismatch")
    for field in sorted(_LATENCY_FIELDS):
        _number(latency[field], f"{take_id}.{field}", minimum=0.0)

    windows = record["window_summary"]
    if not isinstance(windows, Mapping) or set(windows) != _WINDOW_FIELDS:
        raise CorrectiveAcceptanceError(f"{take_id}.window_summary fields mismatch")
    expected_windows = config["window_contract"]["expected_count_by_duration_s"][
        str(identity.duration_s)
    ]
    source_count = _integer(
        windows["source_window_count"], f"{take_id}.source_window_count", 0
    )
    if source_count != expected_windows:
        raise CorrectiveAcceptanceError(
            f"{take_id} window coverage mismatch: expected {expected_windows}, "
            f"found {source_count}"
        )
    for field in ("abstained_window_count", "sub_floor_direction_emission_count"):
        count = _integer(windows[field], f"{take_id}.{field}", 0)
        if count > source_count:
            raise CorrectiveAcceptanceError(
                f"{take_id}.{field} exceeds source_window_count"
            )

    channels = record["channels"]
    expected_mics = set(config["identity_contract"]["raw_microphone_ids"])
    if not isinstance(channels, Sequence) or isinstance(channels, (str, bytes)):
        raise CorrectiveAcceptanceError(f"{take_id}.channels must be a sequence")
    seen_mics: set[str] = set()
    for channel in channels:
        if not isinstance(channel, Mapping) or set(channel) != _CHANNEL_FIELDS:
            raise CorrectiveAcceptanceError(f"{take_id} channel fields mismatch")
        microphone = _required_string(channel, "microphone_id")
        if microphone in seen_mics:
            raise CorrectiveAcceptanceError(
                f"{take_id} duplicate microphone: {microphone}"
            )
        seen_mics.add(microphone)
        if not isinstance(channel["health_failure"], bool):
            raise CorrectiveAcceptanceError(
                f"{take_id}.{microphone}.health_failure must be boolean"
            )
        if not isinstance(channel["major_polarity_anomaly"], bool):
            raise CorrectiveAcceptanceError(
                f"{take_id}.{microphone}.major_polarity_anomaly must be boolean"
            )
        _integer(
            channel["maximum_clip_run_samples"],
            f"{take_id}.{microphone}.maximum_clip_run_samples",
            0,
        )
    if seen_mics != expected_mics:
        raise CorrectiveAcceptanceError(
            f"{take_id} microphone identity mismatch: {sorted(seen_mics)}"
        )

    stratum = identity.stratum_id
    is_a = stratum == "A_controlled_boundary_sweep"
    is_b = stratum == "B_center_nominal_level"
    is_c = stratum == "C_center_low_level"
    is_e = stratum == "E_impact_audio_video"
    _optional_number(
        record["bearing_absolute_error_deg"],
        f"{take_id}.bearing_absolute_error_deg",
        required=is_a or is_b,
        minimum=0.0,
        maximum=180.0,
    )
    bearing = _optional_number(
        record["estimated_bearing_deg_f_project"],
        f"{take_id}.estimated_bearing_deg_f_project",
        required=is_a or is_b,
        minimum=0.0,
        maximum=360.0,
        maximum_exclusive=True,
    )
    if bearing is not None and not 0.0 <= bearing < 360.0:  # pragma: no cover
        raise CorrectiveAcceptanceError(f"{take_id} bearing outside [0, 360)")
    _optional_bool(
        record["sector_correct"], f"{take_id}.sector_correct", required=is_b
    )
    _optional_bool(
        record["candidate_covered"],
        f"{take_id}.candidate_covered",
        required=is_a or is_b,
    )
    _optional_number(
        record["confidence"],
        f"{take_id}.confidence",
        required=is_b or is_c,
        minimum=0.0,
        maximum=1.0,
    )
    _optional_number(
        record["av_absolute_residual_ms"],
        f"{take_id}.av_absolute_residual_ms",
        required=is_e,
        minimum=0.0,
    )
    _validate_tdoa(record["tdoa"], identity, config)


def _validate_tdoa(
    value: Any, identity: TakeIdentity, config: Mapping[str, Any]
) -> None:
    take_id = identity.planned_take_id
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CorrectiveAcceptanceError(f"{take_id}.tdoa must be a sequence")
    expected = (
        set(config["identity_contract"]["microphone_pair_ids"])
        if identity.stratum_id == "A_controlled_boundary_sweep"
        else set()
    )
    seen: set[str] = set()
    domain = config["physical_domains"]["tdoa_us"]
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _TDOA_FIELDS:
            raise CorrectiveAcceptanceError(f"{take_id} TDOA fields mismatch")
        pair_id = _required_string(item, "pair_id")
        if pair_id in seen:
            raise CorrectiveAcceptanceError(f"{take_id} duplicate TDOA pair: {pair_id}")
        seen.add(pair_id)
        _number(
            item["tdoa_us"],
            f"{take_id}.{pair_id}.tdoa_us",
            minimum=domain["minimum"],
            maximum=domain["maximum"],
        )
        _number(
            item["absolute_error_us"],
            f"{take_id}.{pair_id}.absolute_error_us",
            minimum=0.0,
        )
    if seen != expected:
        raise CorrectiveAcceptanceError(
            f"{take_id} TDOA pair identity mismatch: expected={sorted(expected)}, "
            f"found={sorted(seen)}"
        )


def _validate_comparisons(
    value: Any,
    registry: Mapping[str, TakeIdentity],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CorrectiveAcceptanceError("sim_vs_real must be a sequence")
    frozen = {
        item["comparison_id"]: item
        for item in config["sim_vs_real"]["comparison_registry"]
    }
    supplied: dict[str, Mapping[str, Any]] = {}
    classified: list[dict[str, Any]] = []
    for index, record in enumerate(value):
        if not isinstance(record, Mapping) or set(record) != _COMPARISON_FIELDS:
            raise CorrectiveAcceptanceError(
                f"sim_vs_real[{index}] fields must be exactly "
                f"{sorted(_COMPARISON_FIELDS)}"
            )
        comparison_id = _required_string(record, "comparison_id")
        if comparison_id in supplied:
            raise CorrectiveAcceptanceError(
                f"duplicate sim-real comparison: {comparison_id}"
            )
        entry = frozen.get(comparison_id)
        if entry is None:
            raise CorrectiveAcceptanceError(
                f"unknown sim-real comparison: {comparison_id}"
            )
        supplied[comparison_id] = record
        expected = _expected_comparison_conditions(entry, registry, config)
        conditions = record["conditions"]
        if not isinstance(conditions, Sequence) or isinstance(
            conditions, (str, bytes)
        ):
            raise CorrectiveAcceptanceError(
                f"{comparison_id}.conditions must be a sequence"
            )
        keyed: dict[str, dict[str, float]] = {}
        for condition in conditions:
            if (
                not isinstance(condition, Mapping)
                or set(condition) != _CONDITION_FIELDS
            ):
                raise CorrectiveAcceptanceError(
                    f"{comparison_id} condition fields must be exactly "
                    f"{sorted(_CONDITION_FIELDS)}"
                )
            condition_id = _required_string(condition, "condition_id")
            if condition_id in keyed:
                raise CorrectiveAcceptanceError(
                    f"{comparison_id} duplicate condition: {condition_id}"
                )
            values = {
                path: _comparison_number(
                    condition[path],
                    f"{comparison_id}.{condition_id}.{path}",
                    entry,
                )
                for path in config["sim_vs_real"]["paths"]
            }
            keyed[condition_id] = values
        if set(keyed) != expected:
            raise CorrectiveAcceptanceError(
                f"{comparison_id} condition identity mismatch: "
                f"missing={sorted(expected - set(keyed))}, "
                f"extra={sorted(set(keyed) - expected)}"
            )
        aggregates = {
            path: _aggregate(
                entry["aggregation"], [keyed[key][path] for key in sorted(keyed)]
            )
            for path in config["sim_vs_real"]["paths"]
        }
        raw_change = (
            aggregates["adjusted_simulation"]
            - aggregates["unadjusted_simulation"]
        )
        signed_change = (
            raw_change
            if entry["direction"] == "lower_is_better"
            else -raw_change
        )
        band = float(entry["preserve_band"])
        if abs(raw_change) <= band:
            classification = "preserves"
        elif signed_change < 0.0:
            classification = "improves"
        else:
            classification = "worsens"
        classified.append(
            {
                **entry,
                "condition_count": len(keyed),
                "condition_ids_sha256": _canonical_sha256(sorted(keyed)),
                "real": aggregates["real"],
                "unadjusted_simulation": aggregates["unadjusted_simulation"],
                "adjusted_simulation": aggregates["adjusted_simulation"],
                "raw_change": raw_change,
                "signed_change": signed_change,
                "classification": classification,
            }
        )
    if set(supplied) != set(frozen):
        raise CorrectiveAcceptanceError(
            "exact sim-real registry mismatch: "
            f"missing={sorted(set(frozen) - set(supplied))}, "
            f"extra={sorted(set(supplied) - set(frozen))}"
        )
    classified.sort(key=lambda item: item["comparison_id"])
    return classified


def _expected_comparison_conditions(
    entry: Mapping[str, Any],
    registry: Mapping[str, TakeIdentity],
    config: Mapping[str, Any],
) -> set[str]:
    strata = set(entry["applicable_strata"])
    take_ids = sorted(
        take_id
        for take_id, identity in registry.items()
        if identity.stratum_id in strata
    )
    if entry["condition_kind"] == "take":
        expected = set(take_ids)
    else:
        expected = {
            f"{take_id}|{pair_id}"
            for take_id in take_ids
            for pair_id in config["identity_contract"]["microphone_pair_ids"]
        }
    if len(expected) != entry["expected_count"]:
        raise CorrectiveAcceptanceError(
            f"frozen comparison registry count mismatch: {entry['comparison_id']}"
        )
    return expected


def _derive_criterion_values(
    takes: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, TakeIdentity],
    comparisons: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, tuple[float, int]]:
    by_stratum: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for take_id in sorted(takes):
        by_stratum[registry[take_id].stratum_id].append(takes[take_id])
    a = by_stratum["A_controlled_boundary_sweep"]
    b = by_stratum["B_center_nominal_level"]
    c = by_stratum["C_center_low_level"]
    d = by_stratum["D_silence"]
    e = by_stratum["E_impact_audio_video"]
    all_takes = [takes[key] for key in sorted(takes)]
    ab = a + b

    a_errors = [float(item["bearing_absolute_error_deg"]) for item in a]
    b_errors = [float(item["bearing_absolute_error_deg"]) for item in b]
    a_cells: dict[str, list[float]] = defaultdict(list)
    tdoa_groups: dict[str, list[float]] = defaultdict(list)
    for take_id in sorted(takes):
        identity = registry[take_id]
        if identity.stratum_id != "A_controlled_boundary_sweep":
            continue
        take = takes[take_id]
        a_cells[identity.bearing_cell_id].append(
            float(take["estimated_bearing_deg_f_project"])
        )
        for item in take["tdoa"]:
            tdoa_groups[f"{identity.bearing_cell_id}|{item['pair_id']}"].append(
                float(item["tdoa_us"])
            )
    if len(a_cells) != 8 or any(len(values) != 3 for values in a_cells.values()):
        raise CorrectiveAcceptanceError("A bearing cells require exactly 3 repetitions")
    if len(tdoa_groups) != 48 or any(
        len(values) != 3 for values in tdoa_groups.values()
    ):
        raise CorrectiveAcceptanceError("A TDOA groups require exactly 3 repetitions")

    b_by_pair = {
        _pair_key(registry[item["identity"]["planned_take_id"]]): float(
            item["confidence"]
        )
        for item in b
    }
    c_by_pair = {
        _pair_key(registry[item["identity"]["planned_take_id"]]): float(
            item["confidence"]
        )
        for item in c
    }
    if set(b_by_pair) != set(c_by_pair) or len(b_by_pair) != 8:
        raise CorrectiveAcceptanceError(
            "B/C paired series must have identical expected key sets"
        )

    channels = [channel for take in all_takes for channel in take["channels"]]
    window_count_d = sum(
        item["window_summary"]["source_window_count"] for item in d
    )
    window_count_ab = sum(
        item["window_summary"]["source_window_count"] for item in ab
    )
    abstained_d = sum(
        item["window_summary"]["abstained_window_count"] for item in d
    )
    abstained_ab = sum(
        item["window_summary"]["abstained_window_count"] for item in ab
    )
    comparison_map = {item["comparison_id"]: item for item in comparisons}
    bearing_comparison = comparison_map["bearing_doa_error_ab"]
    worsened = sum(item["classification"] == "worsens" for item in comparisons)
    frame_latency = [
        float(item["latency"]["frame_to_adapter_round_trip_ms"])
        for item in all_takes
    ]
    capture_latency = [
        float(item["latency"]["capture_to_frame_offline_ms"])
        for item in all_takes
    ]
    max_clip = max(int(item["maximum_clip_run_samples"]) for item in channels)
    clip_take_count = sum(
        any(
            int(channel["maximum_clip_run_samples"])
            > int(config["physical_domains"]["clip_run_samples"]["minimum"]) + 8
            for channel in take["channels"]
        )
        for take in all_takes
    )
    values = {
        "bearing_median_absolute_error_stratum_a": (float(median(a_errors)), 24),
        "bearing_p95_absolute_error_stratum_a": (_nearest_rank(a_errors), 24),
        "bearing_worst_absolute_error_stratum_a": (max(a_errors), 24),
        "bearing_median_absolute_error_stratum_b": (float(median(b_errors)), 8),
        "sector_accuracy_stratum_b": (
            sum(bool(item["sector_correct"]) for item in b) / 8,
            8,
        ),
        "candidate_coverage_strata_ab": (
            sum(bool(item["candidate_covered"]) for item in ab) / 32,
            32,
        ),
        "within_cell_bearing_circular_range_stratum_a": (
            max(_circular_range(values) for values in a_cells.values()),
            8,
        ),
        "within_cell_pair_tdoa_range_stratum_a": (
            max(max(values) - min(values) for values in tdoa_groups.values()),
            48,
        ),
        "frame_to_adapter_latency_p95": (_nearest_rank(frame_latency), 47),
        "capture_to_frame_offline_spread": (
            max(capture_latency) - min(capture_latency),
            47,
        ),
        "raw_channel_health_failure_count": (
            float(sum(item["health_failure"] for item in channels)),
            188,
        ),
        "major_polarity_anomaly_count": (
            float(sum(item["major_polarity_anomaly"] for item in channels)),
            188,
        ),
        "sustained_clipping_take_count": (float(clip_take_count), 47),
        "maximum_clip_run_samples": (float(max_clip), 188),
        "take_failure_rate": (
            sum(bool(item["failed"]) for item in all_takes) / 47,
            47,
        ),
        "silence_abstention_rate_stratum_d": (
            abstained_d / window_count_d,
            window_count_d,
        ),
        "active_abstention_rate_strata_ab": (
            abstained_ab / window_count_ab,
            window_count_ab,
        ),
        "confidence_median_stratum_b": (
            float(median(b_by_pair.values())),
            8,
        ),
        "sub_floor_direction_emission_count": (
            float(
                sum(
                    item["window_summary"][
                        "sub_floor_direction_emission_count"
                    ]
                    for item in all_takes
                )
            ),
            sum(
                item["window_summary"]["source_window_count"] for item in all_takes
            ),
        ),
        "low_level_confidence_monotonicity": (
            float(median(c_by_pair.values())) - float(median(b_by_pair.values())),
            8,
        ),
        "coarse_av_association_residual_stratum_e": (
            max(float(item["av_absolute_residual_ms"]) for item in e),
            4,
        ),
        "sim_adjusted_bearing_median_delta_vs_real": (
            abs(
                float(bearing_comparison["adjusted_simulation"])
                - float(bearing_comparison["real"])
            ),
            32,
        ),
        "sim_adjustment_worsened_gating_metric_count": (float(worsened), 7),
    }
    values.update(
        {
            "bearing_median_absolute_error_stratum_a_stretch": values[
                "bearing_median_absolute_error_stratum_a"
            ],
            "bearing_p95_absolute_error_stratum_a_stretch": values[
                "bearing_p95_absolute_error_stratum_a"
            ],
            "sector_accuracy_stratum_b_stretch": values["sector_accuracy_stratum_b"],
            "candidate_coverage_strata_ab_stretch": values[
                "candidate_coverage_strata_ab"
            ],
            "active_abstention_rate_strata_ab_stretch": values[
                "active_abstention_rate_strata_ab"
            ],
            "sim_adjusted_bearing_median_delta_vs_real_stretch": values[
                "sim_adjusted_bearing_median_delta_vs_real"
            ],
        }
    )
    return values


def _evaluate_threshold(
    criterion: Mapping[str, Any], value: tuple[float, int]
) -> CriterionOutcome:
    observed, count = value
    threshold = float(criterion["threshold"])
    comparator = criterion["comparator"]
    if comparator == "less_than_or_equal":
        passed = observed <= threshold
    elif comparator == "greater_than_or_equal":
        passed = observed >= threshold
    elif comparator == "equal":
        passed = observed == threshold
    else:  # pragma: no cover - v1 schema freezes comparator values
        raise CorrectiveAcceptanceError(f"unknown comparator: {comparator}")
    return CriterionOutcome(
        criterion_id=criterion["criterion_id"],
        tier=criterion["tier"],
        gating=bool(criterion["gating"]),
        metric=criterion["metric"],
        statistic=criterion["statistic"],
        comparator=comparator,
        threshold=threshold,
        observed=observed,
        sample_count=count,
        passed=passed,
    )


def _validate_registry_counts(
    registry: Mapping[str, TakeIdentity], config: Mapping[str, Any]
) -> None:
    expected = {
        item["stratum_id"]: item["take_count"]
        for item in config["identity_contract"]["stratum_rules"]
    }
    observed = Counter(item.stratum_id for item in registry.values())
    if dict(observed) != expected:
        raise CorrectiveAcceptanceError(
            f"technical manifest stratum counts mismatch: {dict(observed)}"
        )
    if len({item.group_id for item in registry.values()}) != 15:
        raise CorrectiveAcceptanceError("technical manifest group count mismatch")
    a_cells: dict[str, set[int]] = defaultdict(set)
    for item in registry.values():
        if item.stratum_id == "A_controlled_boundary_sweep":
            a_cells[item.bearing_cell_id].add(item.repetition)
    if len(a_cells) != 8 or any(values != {1, 2, 3} for values in a_cells.values()):
        raise CorrectiveAcceptanceError("A registry requires repetitions 1, 2, 3")


def _stratum_for(category: str, gain: Any) -> str:
    if category == "controlled" and gain == 0.75:
        return "A_controlled_boundary_sweep"
    if category == "confidence" and gain == 0.75:
        return "B_center_nominal_level"
    if category == "confidence" and gain == 0.35:
        return "C_center_low_level"
    if category == "silence" and gain is None:
        return "D_silence"
    if category == "audio_video" and gain is None:
        return "E_impact_audio_video"
    raise CorrectiveAcceptanceError(
        f"technical manifest stratum is unsupported: category={category}, gain={gain}"
    )


def _comparison_number(value: Any, label: str, entry: Mapping[str, Any]) -> float:
    unit = entry["unit"]
    if unit == "deg":
        return _number(value, label, minimum=0.0, maximum=180.0)
    if unit in {"fraction", "dimensionless"}:
        return _number(value, label, minimum=0.0, maximum=1.0)
    if unit in {"us_absolute_error", "ms_absolute_residual"}:
        return _number(value, label, minimum=0.0)
    raise CorrectiveAcceptanceError(f"unknown comparison unit: {unit}")


def _aggregate(kind: str, values: Sequence[float]) -> float:
    if kind == "median":
        return float(median(values))
    if kind == "mean":
        return float(fmean(values))
    if kind == "worst":
        return float(max(values))
    raise CorrectiveAcceptanceError(f"unknown aggregation: {kind}")


def _pair_key(identity: TakeIdentity) -> str:
    if identity.bearing_cell_id is None:
        raise CorrectiveAcceptanceError("paired identity lacks bearing cell")
    bearing = identity.bearing_cell_id.rsplit("|", 1)[1]
    return f"{bearing}|rep_{identity.repetition}"


def _nearest_rank(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    return ordered[max(1, math.ceil(0.95 * len(ordered))) - 1]


def _circular_range(values: Sequence[float]) -> float:
    ordered = sorted(float(value) % 360.0 for value in values)
    gaps = [
        later - earlier
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    ]
    gaps.append(ordered[0] + 360.0 - ordered[-1])
    return 360.0 - max(gaps)


def _optional_bool(value: Any, label: str, *, required: bool) -> bool | None:
    if required:
        if not isinstance(value, bool):
            raise CorrectiveAcceptanceError(f"{label} must be boolean")
        return value
    if value is not None:
        raise CorrectiveAcceptanceError(f"{label} is not applicable and must be null")
    return None


def _optional_number(
    value: Any,
    label: str,
    *,
    required: bool,
    minimum: float | None = None,
    maximum: float | None = None,
    maximum_exclusive: bool = False,
) -> float | None:
    if required:
        return _number(
            value,
            label,
            minimum=minimum,
            maximum=maximum,
            maximum_exclusive=maximum_exclusive,
        )
    if value is not None:
        raise CorrectiveAcceptanceError(f"{label} is not applicable and must be null")
    return None


def _number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    maximum_exclusive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CorrectiveAcceptanceError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise CorrectiveAcceptanceError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise CorrectiveAcceptanceError(f"{label} must be >= {minimum}")
    if maximum is not None:
        if maximum_exclusive and number >= maximum:
            raise CorrectiveAcceptanceError(f"{label} must be < {maximum}")
        if not maximum_exclusive and number > maximum:
            raise CorrectiveAcceptanceError(f"{label} must be <= {maximum}")
    return number


def _integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorrectiveAcceptanceError(f"{label} must be an integer")
    if value < minimum:
        raise CorrectiveAcceptanceError(f"{label} must be >= {minimum}")
    return value


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise CorrectiveAcceptanceError(f"{key} must be a non-empty string")
    return item


def _repo_file(root: Path, relative: Path) -> Path:
    if relative.is_absolute():
        raise CorrectiveAcceptanceError(f"path must be repository relative: {relative}")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise CorrectiveAcceptanceError(f"missing repository file: {relative}")
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorrectiveAcceptanceError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CorrectiveAcceptanceError(f"expected JSON object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CONFIG_PATH",
    "PAYLOAD_SCHEMA",
    "RESULT_SCHEMA",
    "CorrectiveAcceptanceError",
    "CorrectiveAcceptanceResult",
    "build_identity_registry",
    "build_synthetic_payload",
    "evaluate_corrective",
    "load_corrective_config",
    "sha256_file",
]
