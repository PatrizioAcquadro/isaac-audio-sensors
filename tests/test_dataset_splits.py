"""Acceptance coverage for S2.5 deterministic grouped splits."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from isaac_audio_sensors.cli import main as cli_main
from isaac_audio_sensors.core.dataset import (
    DatasetSplitError,
    apply_split_plan,
    build_split_plan,
    read_split_plan,
    validate_dataset,
    verify_no_leakage,
    verify_plan_against_manifest,
    write_json_atomic,
    write_split_plan,
)
from isaac_audio_sensors.core.dataset_manifest import (
    AssetRecord,
    AudioDatasetManifest,
    ShardRecord,
)
from isaac_audio_sensors.core.io.manifests import (
    manifest_to_dict,
    read_dataset_manifest,
)

REFERENCE = Path("examples/datasets/reference_session_v1")
TVT_RATIOS = {"train": 0.6, "validation": 0.2, "test": 0.2}


def _multi_group_manifest(group_count: int = 6) -> AudioDatasetManifest:
    base = read_dataset_manifest(REFERENCE / "manifest.json")
    template = base.episodes[0]
    episodes = []
    shards = []
    start_frame = 0
    for index in range(group_count):
        frame_count = index + 1
        episode_id = f"episode_{index:05d}"
        group_id = f"scene_{index:02d}"
        episodes.append(
            replace(
                template,
                episode_id=episode_id,
                scene_id=group_id,
                environment_id=f"environment_{index:02d}",
                seed=index,
                start_step=0,
                end_step=frame_count - 1,
                start_frame=start_frame,
                end_frame=start_frame + frame_count - 1,
                timestamps_ms=tuple(range(frame_count)),
                split_group=group_id,
                reset_markers=(),
                array_poses=(),
                source_truth=(),
                visual_sync_asset_ids=(),
            )
        )
        shard_id = f"shard_{index:05d}"
        shards.append(
            ShardRecord(
                shard_id=shard_id,
                episode_ids=(episode_id,),
                assets=(
                    AssetRecord(
                        asset_id=f"{shard_id}.frames",
                        path=f"shards/{shard_id}/frames.jsonl",
                        kind="frame_trace_jsonl",
                        sha256="0" * 64,
                    ),
                ),
                completion_state="complete",
            )
        )
        start_frame += frame_count
    return replace(base, episodes=tuple(episodes), shards=tuple(shards), splits=())


def _write_pretty_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_same_seed_is_identical_and_different_seed_reshuffles_groups():
    manifest = _multi_group_manifest()
    first = build_split_plan(
        manifest, kind="train_validation_test", ratios=TVT_RATIOS, seed=7
    )
    repeated = build_split_plan(
        manifest, kind="train_validation_test", ratios=TVT_RATIOS, seed=7
    )
    changed = build_split_plan(
        manifest, kind="train_validation_test", ratios=TVT_RATIOS, seed=8
    )

    assert first.plan_sha256 == repeated.plan_sha256
    assert first.serialize() == repeated.serialize()
    assert first.assignments == repeated.assignments
    assert changed.plan_sha256 != first.plan_sha256
    assert changed.assignments != first.assignments


def test_groups_are_a_disjoint_cover_and_weighted_ratios_obey_greedy_bound():
    manifest = _multi_group_manifest()
    plan = build_split_plan(
        manifest, kind="train_validation_test", ratios=TVT_RATIOS, seed=19
    )

    assert verify_no_leakage(plan)
    assert verify_plan_against_manifest(manifest, plan)
    assigned = [group for values in plan.assignments.values() for group in values]
    assert len(assigned) == len(set(assigned)) == len(plan.group_weights)
    total_weight = sum(plan.group_weights.values())
    max_group_weight = max(plan.group_weights.values())
    for partition, ratio in plan.ratios.items():
        actual = sum(plan.group_weights[group] for group in plan.assignments[partition])
        assert abs(actual - ratio * total_weight) <= max_group_weight


@pytest.mark.parametrize(
    ("ratios", "message"),
    [
        ({"train": 0.7, "test": 0.2}, "sum to 1.0"),
        ({"train": 1.0, "test": 0.0}, "must be positive"),
        ({"train": 1.1, "test": -0.1}, "must be positive"),
    ],
)
def test_invalid_ratios_fail_with_location(ratios, message):
    with pytest.raises(DatasetSplitError, match=message):
        build_split_plan(
            _multi_group_manifest(),
            kind="train_validation_test",
            ratios=ratios,
            seed=1,
        )


def test_more_partitions_than_groups_is_impossible():
    with pytest.raises(DatasetSplitError, match="impossible ratios.*3.*2"):
        build_split_plan(
            _multi_group_manifest(2),
            kind="train_validation_test",
            ratios={"train": 0.8, "validation": 0.1, "test": 0.1},
            seed=1,
        )


def test_unknown_and_non_string_grouping_metadata_fail_located():
    manifest = _multi_group_manifest()
    with pytest.raises(
        DatasetSplitError, match=r"episode episode_00000 field room_id.*missing"
    ):
        build_split_plan(
            manifest,
            kind="train_validation_test",
            ratios=TVT_RATIOS,
            seed=1,
            grouping_key="room_id",
        )
    with pytest.raises(
        DatasetSplitError, match=r"episode episode_00000 field labels.*string id"
    ):
        build_split_plan(
            manifest,
            kind="train_validation_test",
            ratios=TVT_RATIOS,
            seed=1,
            grouping_key="labels",
        )


def test_materialized_custom_grouping_key_is_supported():
    manifest = replace(_multi_group_manifest(), split_grouping_key="room_id")
    plan = build_split_plan(
        manifest, kind="train_validation_test", ratios=TVT_RATIOS, seed=3
    )
    assert plan.grouping_key == "room_id"
    assert set(plan.group_weights) == {f"scene_{index:02d}" for index in range(6)}


def test_failed_root_validation_blocks_planning(tmp_path):
    root = tmp_path / "corrupt"
    shutil.copytree(REFERENCE, root)
    audio_path = root / "shards/shard_00000/audio.wav"
    data = bytearray(audio_path.read_bytes())
    data[-1] ^= 1
    audio_path.write_bytes(data)

    with pytest.raises(DatasetSplitError, match="validation failed.*checksum_mismatch"):
        build_split_plan(
            root,
            kind="train_validation_test",
            ratios={"train": 0.5, "test": 0.5},
            seed=1,
        )


def test_group_crossing_shard_requires_physical_resharding(tmp_path):
    root = tmp_path / "crossing"
    shutil.copytree(REFERENCE, root)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["episodes"][1]["scene_id"] = "scene_c"
    payload["episodes"][1]["split_group"] = "scene_c"
    _write_pretty_json(manifest_path, payload)

    with pytest.raises(
        DatasetSplitError, match=r"shard_00000.*physical resharding.*required"
    ):
        build_split_plan(
            root,
            kind="train_validation_test",
            ratios={"train": 0.5, "test": 0.5},
            seed=1,
        )


def test_direct_manifest_group_crossing_also_requires_resharding():
    manifest = _multi_group_manifest()
    crossing = replace(
        manifest,
        shards=(
            replace(
                manifest.shards[0],
                episode_ids=(
                    manifest.episodes[0].episode_id,
                    manifest.episodes[1].episode_id,
                ),
            ),
            *manifest.shards[2:],
        ),
    )
    with pytest.raises(DatasetSplitError, match="crosses.*physical shard.*resharding"):
        build_split_plan(
            crossing,
            kind="train_validation_test",
            ratios=TVT_RATIOS,
            seed=1,
        )


def test_fit_holdout_round_trip_refuses_apply_and_detects_tamper(tmp_path):
    manifest = _multi_group_manifest()
    plan = build_split_plan(
        manifest,
        kind="fit_holdout",
        ratios={"fit": 0.8, "holdout": 0.2},
        seed=41,
    )
    output = write_split_plan(plan, tmp_path / "fit_holdout.json")

    restored = read_split_plan(output)
    assert restored == plan
    assert restored.serialize() == plan.serialize()
    with pytest.raises(DatasetSplitError, match="plan-level artifact"):
        apply_split_plan(manifest, plan)

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["seed"] = 42
    _write_pretty_json(output, payload)
    with pytest.raises(DatasetSplitError, match="hash mismatch"):
        read_split_plan(output)


def test_apply_reference_copy_revalidates_and_only_changes_manifest(tmp_path):
    root = tmp_path / "reference"
    shutil.copytree(REFERENCE, root)
    before = _tree_bytes(root)
    manifest = read_dataset_manifest(root / "manifest.json")
    plan = build_split_plan(
        root,
        kind="train_validation_test",
        ratios={"train": 0.5, "test": 0.5},
        seed=0,
    )
    updated = apply_split_plan(manifest, plan)
    write_json_atomic(root / "manifest.json", manifest_to_dict(updated))

    report = validate_dataset(root)
    after = _tree_bytes(root)
    assert report.status == "passed"
    assert report.error_count == 0
    assert {split.name for split in updated.splits} == {"train", "test"}
    assert before["manifest.json"] != after["manifest.json"]
    assert {
        name: content for name, content in before.items() if name != "manifest.json"
    } == {name: content for name, content in after.items() if name != "manifest.json"}


def test_cli_plan_output_apply_and_failures(tmp_path, capsys):
    root = tmp_path / "cli_reference"
    shutil.copytree(REFERENCE, root)
    output = tmp_path / "plan.json"
    args = [
        "dataset",
        "split",
        str(root),
        "--kind",
        "tvt",
        "--ratios",
        "train=0.5,test=0.5",
        "--seed",
        "7",
        "--out",
        str(output),
    ]
    assert cli_main(args) == 0
    plan = read_split_plan(output)
    assert capsys.readouterr().out.strip() == plan.plan_sha256

    assert cli_main([*args[:-2], "--apply"]) == 0
    assert validate_dataset(root).status == "passed"
    assert read_dataset_manifest(root / "manifest.json").splits
    assert capsys.readouterr().out.strip() == plan.plan_sha256

    assert (
        cli_main(
            [
                "dataset",
                "split",
                str(root),
                "--kind",
                "tvt",
                "--ratios",
                "train=0.7,test=0.2",
                "--seed",
                "7",
            ]
        )
        == 1
    )
    assert "sum to 1.0" in capsys.readouterr().err

    assert (
        cli_main(
            [
                "dataset",
                "split",
                str(root),
                "--kind",
                "fit-holdout",
                "--ratios",
                "fit=0.8,holdout=0.2",
                "--seed",
                "7",
                "--apply",
            ]
        )
        == 1
    )
    assert "plan-level artifact" in capsys.readouterr().err


def test_plan_file_is_canonical_and_hash_is_sha256(tmp_path):
    plan = build_split_plan(
        _multi_group_manifest(),
        kind="train_validation_test",
        ratios=TVT_RATIOS,
        seed=101,
    )
    output = write_split_plan(plan, tmp_path / "plan.json")
    assert output.read_text(encoding="utf-8") == plan.serialize() + "\n"
    assert len(plan.plan_sha256) == 64
    assert bytes.fromhex(plan.plan_sha256)
    payload = plan.to_dict()
    embedded = payload.pop("plan_sha256")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert embedded == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
