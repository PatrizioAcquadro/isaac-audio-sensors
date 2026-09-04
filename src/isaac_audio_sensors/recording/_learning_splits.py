"""Corpus grouping by transitive, explicitly declared acquisition identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from isaac_audio_sensors.recording.loader import SessionDataset
from isaac_audio_sensors.recording.splits import (
    DatasetSplitError,
    SplitKind,
    _assign_groups,
    _group_score,
    _validated_ratios,
)


def build_corpus_split(
    datasets: tuple[SessionDataset, ...],
    *,
    ratios: Mapping[str, float],
    seed: int,
    isolate_by: Sequence[str],
    kind: SplitKind,
) -> dict[str, tuple[str, ...]]:
    if kind not in ("train_validation_test", "fit_holdout"):
        raise DatasetSplitError(f"unsupported split kind: {kind!r}")
    ratios = _validated_ratios(kind, ratios)
    if type(seed) is not int:
        raise DatasetSplitError("split seed must be an integer.")
    if (
        isinstance(isolate_by, str)
        or any(axis not in ("scene", "trajectory", "asset") for axis in isolate_by)
        or len(set(isolate_by)) != len(isolate_by)
    ):
        raise DatasetSplitError(
            "isolate_by must select unique scene, trajectory, asset axes."
        )
    axes = tuple(sorted(isolate_by))
    manifests = {d.manifest.dataset_id: d.manifest for d in datasets}
    parents = {name: name for name in manifests}
    owners: dict[tuple[str, str], str] = {}

    def find(name):
        while parents[name] != name:
            parents[name] = parents[parents[name]]
            name = parents[name]
        return name

    def join(name, axis, value):
        key = (axis, value)
        owner = owners.setdefault(key, name)
        a, b = sorted((find(owner), find(name)))
        parents[b] = a

    for name, manifest in sorted(manifests.items()):
        join(name, "session", manifest.session_id)
        if not manifest.episodes:
            raise DatasetSplitError(f"dataset {name}: no episodes to split.")
        for episode in manifest.episodes:
            identities = {
                "scene": (episode.scene_id,),
                "trajectory": None
                if episode.trajectory_id is None
                else (episode.trajectory_id,),
                "asset": episode.source_asset_ids,
            }
            for axis in axes:
                values = identities[axis]
                if values is None:
                    raise DatasetSplitError(
                        f"dataset {name} episode {episode.episode_id}: missing {axis} "
                        "identity; supply metadata or explicitly exclude this axis."
                    )
                for value in values:
                    join(name, axis, value)

    members: dict[str, list[str]] = {}
    weights: dict[str, int] = {}
    for name, manifest in sorted(manifests.items()):
        group = find(name)
        members.setdefault(group, []).append(name)
        weights[group] = weights.get(group, 0) + sum(
            e.end_frame - e.start_frame + 1 for e in manifest.episodes
        )
    if len(members) < len(ratios):
        raise DatasetSplitError(
            f"isolation axes {('session', *axes)} produce only {len(members)} "
            f"independent groups for {len(ratios)} requested partitions; "
            f"connected artifacts: {list(members.values())}."
        )
    # Verify the canonical records before installing an assignment. No audio decode.
    for dataset in datasets:
        for _ in dataset.iter_records():
            pass
    order = sorted(
        weights,
        key=lambda name: (
            _group_score("learning", seed, ",".join(axes), name),
            name,
        ),
    )
    assignment = _assign_groups(weights, ratios, order)
    return {
        partition: tuple(sorted(name for g in groups for name in members[g]))
        for partition, groups in assignment.items()
    }


__all__: list[str] = []
