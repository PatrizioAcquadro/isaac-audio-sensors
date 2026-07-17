"""Deterministic, frame-weighted grouped dataset splitting.

The planner first collects group identifiers in lexical order.  It scores each
group with the first 64 bits of
``sha256(f"{dataset_id}:{seed}:{grouping_key}:{group_id}")`` and sorts by
``(score, group_id)``.  Integer frame targets are derived with the
largest-remainder method, then whole groups are greedily assigned to the
partition with the greatest remaining target.  The last unassigned groups are
reserved for empty partitions so every requested positive partition is
satisfiable.  No process-global randomness or input mapping order participates
in the result.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from isaac_audio_sensors.core.dataset.validate import validate_dataset
from isaac_audio_sensors.core.dataset_manifest import (
    AudioDatasetManifest,
    SplitRecord,
)
from isaac_audio_sensors.core.io.manifests import read_dataset_manifest

SplitKind = Literal["train_validation_test", "fit_holdout"]
SPLIT_PLAN_SCHEMA = "ias.dataset_split_plan.v1"
_PARTITIONS: dict[SplitKind, tuple[str, ...]] = {
    "train_validation_test": ("train", "validation", "test"),
    "fit_holdout": ("fit", "holdout"),
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class DatasetSplitError(ValueError):
    """A located split-planning, integrity, or leakage failure."""


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """Frozen deterministic assignment artifact independent of the manifest."""

    dataset_id: str
    grouping_key: str
    kind: SplitKind
    seed: int
    ratios: Mapping[str, float]
    assignments: Mapping[str, tuple[str, ...]]
    group_weights: Mapping[str, int]
    manifest_configuration_sha256: str
    plan_sha256: str = ""
    schema: str = SPLIT_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SPLIT_PLAN_SCHEMA:
            raise DatasetSplitError(
                f"split plan field schema: expected {SPLIT_PLAN_SCHEMA!r}."
            )
        if not isinstance(self.dataset_id, str) or not self.dataset_id:
            raise DatasetSplitError("split plan field dataset_id: must be a string id.")
        if not isinstance(self.grouping_key, str) or not self.grouping_key:
            raise DatasetSplitError(
                "split plan field grouping_key: must be a string id."
            )
        if self.kind not in _PARTITIONS:
            raise DatasetSplitError(
                f"split plan field kind: unsupported split kind {self.kind!r}."
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise DatasetSplitError("split plan field seed: must be an integer.")
        ratios = _validated_ratios(self.kind, self.ratios)
        assignments = _validated_assignments(self.kind, self.assignments, ratios)
        weights = _validated_weights(self.group_weights)
        if (
            not isinstance(self.manifest_configuration_sha256, str)
            or _SHA256_RE.fullmatch(self.manifest_configuration_sha256) is None
        ):
            raise DatasetSplitError(
                "split plan field manifest_configuration_sha256: must be 64 "
                "lowercase hexadecimal characters."
            )
        object.__setattr__(self, "ratios", ratios)
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "group_weights", weights)
        verify_no_leakage(self)
        expected = _plan_digest(self)
        if self.plan_sha256 and self.plan_sha256 != expected:
            raise DatasetSplitError(
                "split plan field plan_sha256: hash mismatch; "
                f"expected {expected}, found {self.plan_sha256}."
            )
        object.__setattr__(self, "plan_sha256", expected)

    def to_dict(self) -> dict[str, Any]:
        """Return the complete JSON-ready v1 split-plan payload."""

        return {
            **self._hash_payload(),
            "plan_sha256": self.plan_sha256,
        }

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "assignments": {
                partition: list(self.assignments[partition])
                for partition in self.assignments
            },
            "dataset_id": self.dataset_id,
            "group_weights": dict(self.group_weights),
            "grouping_key": self.grouping_key,
            "kind": self.kind,
            "manifest_configuration_sha256": self.manifest_configuration_sha256,
            "ratios": dict(self.ratios),
            "schema": self.schema,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SplitPlan:
        """Parse and verify a complete v1 split-plan payload."""

        required = {
            "assignments",
            "dataset_id",
            "group_weights",
            "grouping_key",
            "kind",
            "manifest_configuration_sha256",
            "plan_sha256",
            "ratios",
            "schema",
            "seed",
        }
        missing = required - set(payload)
        extra = set(payload) - required
        if missing or extra:
            raise DatasetSplitError(
                "split plan root: fields do not match schema; "
                f"missing={sorted(missing)}, extra={sorted(extra)}."
            )
        supplied_hash = payload["plan_sha256"]
        hash_payload = {
            key: payload[key] for key in required if key != "plan_sha256"
        }
        try:
            canonical = json.dumps(
                hash_payload, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError) as exc:
            raise DatasetSplitError(
                f"split plan root: fields are not canonical JSON values: {exc}."
            ) from exc
        expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
        if supplied_hash != expected_hash:
            raise DatasetSplitError(
                "split plan field plan_sha256: hash mismatch; "
                f"expected {expected_hash}, found {supplied_hash}."
            )
        try:
            kind = payload["kind"]
            if not isinstance(kind, str):
                raise TypeError("kind is not a string")
            return cls(
                dataset_id=payload["dataset_id"],
                grouping_key=payload["grouping_key"],
                kind=kind,  # type: ignore[arg-type]
                seed=payload["seed"],
                ratios=payload["ratios"],
                assignments=payload["assignments"],
                group_weights=payload["group_weights"],
                manifest_configuration_sha256=payload[
                    "manifest_configuration_sha256"
                ],
                plan_sha256=payload["plan_sha256"],
                schema=payload["schema"],
            )
        except (TypeError, KeyError) as exc:
            raise DatasetSplitError(
                f"split plan root: invalid field type: {exc}."
            ) from exc

    def serialize(self) -> str:
        """Serialize as canonical compact JSON without a trailing newline."""

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def build_split_plan(
    manifest_or_session_root: AudioDatasetManifest | str | Path,
    *,
    kind: SplitKind,
    ratios: Mapping[str, float],
    seed: int,
    grouping_key: str | None = None,
) -> SplitPlan:
    """Build one validation-gated, whole-group deterministic split plan."""

    if kind not in _PARTITIONS:
        raise DatasetSplitError(f"split request field kind: unsupported {kind!r}.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise DatasetSplitError("split request field seed: must be an integer.")
    normalized_ratios = _validated_ratios(kind, ratios)
    manifest = _validated_manifest_input(manifest_or_session_root)
    selected_key = manifest.split_grouping_key if grouping_key is None else grouping_key
    if not isinstance(selected_key, str) or not selected_key:
        raise DatasetSplitError(
            "manifest.json field split_grouping_key: missing grouping metadata."
        )
    group_by_episode = _resolve_episode_groups(manifest, selected_key)
    _require_group_aligned_shards(manifest, group_by_episode)
    weights = _group_frame_weights(manifest, group_by_episode)
    if len(weights) < len(normalized_ratios):
        raise DatasetSplitError(
            "manifest.json field episodes: impossible ratios; "
            f"{len(normalized_ratios)} positive partitions require at least that "
            f"many groups, but only {len(weights)} grouping values are available."
        )

    targets = _largest_remainder_targets(normalized_ratios, sum(weights.values()))
    ordered_groups = sorted(
        sorted(weights),
        key=lambda group_id: (
            _group_score(manifest.dataset_id, seed, selected_key, group_id),
            group_id,
        ),
    )
    partition_order = tuple(
        name for name in _PARTITIONS[kind] if name in normalized_ratios
    )
    assigned_weights = {name: 0 for name in partition_order}
    assigned_groups: dict[str, list[str]] = {name: [] for name in partition_order}
    for index, group_id in enumerate(ordered_groups):
        empty = tuple(name for name in partition_order if not assigned_groups[name])
        groups_remaining = len(ordered_groups) - index
        candidates = empty if groups_remaining == len(empty) else partition_order
        partition = max(
            candidates,
            key=lambda name: (
                targets[name] - assigned_weights[name],
                normalized_ratios[name],
                -partition_order.index(name),
            ),
        )
        assigned_groups[partition].append(group_id)
        assigned_weights[partition] += weights[group_id]

    plan = SplitPlan(
        dataset_id=manifest.dataset_id,
        grouping_key=selected_key,
        kind=kind,
        seed=seed,
        ratios=normalized_ratios,
        assignments={
            name: tuple(sorted(group_ids))
            for name, group_ids in assigned_groups.items()
        },
        group_weights=weights,
        manifest_configuration_sha256=manifest.configuration_sha256,
    )
    verify_plan_against_manifest(manifest, plan)
    return plan


def verify_no_leakage(plan: SplitPlan) -> bool:
    """Assert that plan assignments are a disjoint cover of all known groups."""

    seen: set[str] = set()
    for partition, group_ids in plan.assignments.items():
        overlap = seen.intersection(group_ids)
        if overlap:
            raise DatasetSplitError(
                f"split plan assignments.{partition}: group leakage across "
                f"partitions: {sorted(overlap)}."
            )
        seen.update(group_ids)
    expected = set(plan.group_weights)
    if seen != expected:
        raise DatasetSplitError(
            "split plan assignments: groups must form a disjoint cover; "
            f"missing={sorted(expected - seen)}, unknown={sorted(seen - expected)}."
        )
    return True


def verify_plan_against_manifest(
    manifest: AudioDatasetManifest, plan: SplitPlan
) -> bool:
    """Re-derive grouping and weights and assert a plan matches the manifest."""

    if plan.dataset_id != manifest.dataset_id:
        raise DatasetSplitError(
            "split plan field dataset_id: does not match manifest.json dataset_id."
        )
    if plan.manifest_configuration_sha256 != manifest.configuration_sha256:
        raise DatasetSplitError(
            "split plan field manifest_configuration_sha256: does not match "
            "manifest.json configuration_sha256."
        )
    groups = _resolve_episode_groups(manifest, plan.grouping_key)
    _require_group_aligned_shards(manifest, groups)
    expected_weights = _group_frame_weights(manifest, groups)
    if dict(plan.group_weights) != expected_weights:
        raise DatasetSplitError(
            "split plan field group_weights: does not match manifest.json episode "
            "frame counts."
        )
    verify_no_leakage(plan)
    return True


def apply_split_plan(
    manifest: AudioDatasetManifest, plan: SplitPlan
) -> AudioDatasetManifest:
    """Return a manifest with a verified TVT plan embedded as SplitRecords."""

    if plan.kind == "fit_holdout":
        raise DatasetSplitError(
            "fit_holdout is a plan-level artifact and cannot be embedded as "
            "manifest SplitRecords; only train_validation_test plans can be applied."
        )
    verify_plan_against_manifest(manifest, plan)
    splits = tuple(
        SplitRecord(name=name, group_ids=tuple(plan.assignments[name]))
        for name in _PARTITIONS["train_validation_test"]
        if name in plan.assignments
    )
    try:
        return replace(manifest, splits=splits)
    except ValueError as exc:
        raise DatasetSplitError(
            "manifest.json field splits: plan grouping is not materialized in "
            f"EpisodeRecord.split_group: {exc}"
        ) from exc


def serialize_split_plan(plan: SplitPlan) -> str:
    """Serialize a split plan as canonical compact JSON."""

    return plan.serialize()


def write_split_plan(plan: SplitPlan, path: str | Path) -> Path:
    """Write canonical split-plan JSON with one trailing newline."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(plan.serialize() + "\n", encoding="utf-8")
    return output


def read_split_plan(path: str | Path) -> SplitPlan:
    """Read a split plan and verify its embedded canonical hash."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetSplitError(
            f"split plan file {source}: cannot read JSON: {exc}."
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetSplitError(f"split plan file {source}: root must be an object.")
    try:
        return SplitPlan.from_dict(payload)
    except DatasetSplitError as exc:
        raise DatasetSplitError(f"split plan file {source}: {exc}") from exc


def _validated_manifest_input(
    value: AudioDatasetManifest | str | Path,
) -> AudioDatasetManifest:
    if isinstance(value, AudioDatasetManifest):
        return value
    root = Path(value)
    report = validate_dataset(root)
    if report.status == "failed":
        crossing = next(
            (
                finding
                for finding in report.findings
                if finding.code == "split_group_crossing_shard"
            ),
            None,
        )
        if crossing is not None:
            raise DatasetSplitError(
                f"{crossing.location}: split_group crosses a physical shard; "
                "physical resharding is required before splitting."
            )
        details = "; ".join(
            f"{finding.code} at {finding.location}" for finding in report.findings
        )
        raise DatasetSplitError(
            f"session {root}: dataset validation failed before splitting: {details}."
        )
    try:
        return read_dataset_manifest(root / "manifest.json")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DatasetSplitError(
            f"session {root} file manifest.json: cannot read validated manifest: {exc}."
        ) from exc


def _validated_ratios(
    kind: SplitKind, ratios: Mapping[str, float]
) -> dict[str, float]:
    if not isinstance(ratios, Mapping) or not ratios:
        raise DatasetSplitError(
            "split request field ratios: must be a non-empty mapping."
        )
    allowed = _PARTITIONS[kind]
    unknown = set(ratios) - set(allowed)
    if unknown:
        raise DatasetSplitError(
            f"split request field ratios: partitions {sorted(unknown)} are invalid "
            f"for {kind}."
        )
    normalized: dict[str, float] = {}
    for name in allowed:
        if name not in ratios:
            continue
        value = ratios[name]
        if isinstance(value, bool):
            raise DatasetSplitError(
                f"split request field ratios.{name}: ratio must be positive."
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DatasetSplitError(
                f"split request field ratios.{name}: ratio must be numeric."
            ) from exc
        if not math.isfinite(number) or number <= 0.0:
            raise DatasetSplitError(
                f"split request field ratios.{name}: ratio must be positive."
            )
        normalized[name] = number
    if not math.isclose(sum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise DatasetSplitError(
            "split request field ratios: positive ratios must sum to 1.0 within 1e-9."
        )
    return normalized


def _validated_assignments(
    kind: SplitKind,
    assignments: Mapping[str, tuple[str, ...]],
    ratios: Mapping[str, float],
) -> dict[str, tuple[str, ...]]:
    if not isinstance(assignments, Mapping) or set(assignments) != set(ratios):
        raise DatasetSplitError(
            "split plan field assignments: partition keys must match ratios."
        )
    result: dict[str, tuple[str, ...]] = {}
    for name in _PARTITIONS[kind]:
        if name not in assignments:
            continue
        raw = assignments[name]
        if isinstance(raw, (str, bytes)):
            raise DatasetSplitError(
                f"split plan field assignments.{name}: must be a group-id sequence."
            )
        try:
            values = tuple(raw)
        except TypeError as exc:
            raise DatasetSplitError(
                f"split plan field assignments.{name}: must be a group-id sequence."
            ) from exc
        if not values or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise DatasetSplitError(
                f"split plan field assignments.{name}: requires string group ids."
            )
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise DatasetSplitError(
                f"split plan field assignments.{name}: group ids must be unique "
                "and sorted."
            )
        result[name] = values
    return result


def _validated_weights(weights: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(weights, Mapping) or not weights:
        raise DatasetSplitError(
            "split plan field group_weights: must be a non-empty mapping."
        )
    if any(not isinstance(group_id, str) or not group_id for group_id in weights):
        raise DatasetSplitError(
            "split plan field group_weights: keys must be string group ids."
        )
    result: dict[str, int] = {}
    for group_id in sorted(weights):
        value = weights[group_id]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise DatasetSplitError(
                f"split plan field group_weights.{group_id}: must be a positive "
                "integer."
            )
        result[group_id] = value
    return result


def _resolve_episode_groups(
    manifest: AudioDatasetManifest, grouping_key: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    for episode in manifest.episodes:
        if hasattr(episode, grouping_key):
            value = getattr(episode, grouping_key)
        elif grouping_key == manifest.split_grouping_key:
            value = episode.split_group
        else:
            raise DatasetSplitError(
                f"manifest.json episode {episode.episode_id} field {grouping_key}: "
                "missing grouping metadata."
            )
        if not isinstance(value, str) or not value:
            raise DatasetSplitError(
                f"manifest.json episode {episode.episode_id} field {grouping_key}: "
                "grouping metadata must be a string id."
            )
        result[episode.episode_id] = value
    if not result:
        raise DatasetSplitError(
            "manifest.json field episodes: missing grouping metadata for "
            f"{grouping_key}."
        )
    return result


def _require_group_aligned_shards(
    manifest: AudioDatasetManifest, group_by_episode: Mapping[str, str]
) -> None:
    for shard in manifest.shards:
        groups = {group_by_episode[episode_id] for episode_id in shard.episode_ids}
        if len(groups) > 1:
            raise DatasetSplitError(
                f"manifest.json shard {shard.shard_id}: grouping key crosses a "
                f"physical shard with values {sorted(groups)}; physical resharding "
                "is required before splitting."
            )


def _group_frame_weights(
    manifest: AudioDatasetManifest, group_by_episode: Mapping[str, str]
) -> dict[str, int]:
    weights: dict[str, int] = {}
    for episode in manifest.episodes:
        group_id = group_by_episode[episode.episode_id]
        frame_count = episode.end_frame - episode.start_frame + 1
        weights[group_id] = weights.get(group_id, 0) + frame_count
    return {group_id: weights[group_id] for group_id in sorted(weights)}


def _largest_remainder_targets(
    ratios: Mapping[str, float], total_weight: int
) -> dict[str, int]:
    raw = {name: ratios[name] * total_weight for name in ratios}
    targets = {name: math.floor(raw[name]) for name in ratios}
    remaining = total_weight - sum(targets.values())
    order = sorted(ratios, key=lambda name: (-(raw[name] - targets[name]), name))
    for name in order[:remaining]:
        targets[name] += 1
    return targets


def _group_score(
    dataset_id: str, seed: int, grouping_key: str, group_id: str
) -> int:
    payload = f"{dataset_id}:{seed}:{grouping_key}:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _plan_digest(plan: SplitPlan) -> str:
    canonical = json.dumps(plan._hash_payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "SPLIT_PLAN_SCHEMA",
    "DatasetSplitError",
    "SplitKind",
    "SplitPlan",
    "apply_split_plan",
    "build_split_plan",
    "read_split_plan",
    "serialize_split_plan",
    "verify_no_leakage",
    "verify_plan_against_manifest",
    "write_split_plan",
]
