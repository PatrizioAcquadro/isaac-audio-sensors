# S2.5 closeout - Deterministic grouped splits

Status: **passed** (2026-07-17). Entry revision `affd0d7`; predecessor
closeout `docs/development/closeouts/S2/s2_4_validator_statistics.md`.

## Scope delivered

- `core/dataset/splits.py`: `build_split_plan` (train/validation/test and
  fit/holdout kinds) with a documented deterministic algorithm — per-group
  64-bit `sha256(dataset_id:seed:grouping_key:group_id)` scores, sort by
  `(score, group_id)`, largest-remainder frame-weight targets, greedy
  whole-group assignment (groups never split); pre-planning validation via
  the canonical S2.4 validator, with group-crossing shards failing
  explicitly with a physical-resharding requirement (layout spec §9);
  impossible ratios, non-unit sums, and missing/unknown grouping metadata
  fail with located errors. `SplitPlan` artifact
  (`ias.dataset_split_plan.v1`) with self-verifying `plan_sha256`;
  `apply_split_plan` embeds TVT plans as manifest `SplitRecord`s (the
  frozen contract restricts split names, so fit/holdout stays plan-level
  and `apply` refuses it); `verify_no_leakage` /
  `verify_plan_against_manifest`.
- CLI `dataset split` with `--kind`, `--ratios`, `--seed`,
  `--grouping-key`, `--out`, and atomic `--apply`.
- `tests/test_dataset_splits.py`: 15 tests — repeated-seed hash identity,
  seed reshuffle, leakage disjoint-cover, greedy weight bound, all failure
  classes, fit/holdout round-trip with tamper detection, atomic apply with
  revalidation, CLI behavior.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.5/split_hashes_leakage.json`.

- Full suite 657 passed / 0 failed; ruff clean.
- Orchestrator-independent determinism check: seed 7 three times ->
  identical `plan_sha256`
  (`c973013c…9240`); seed 13 -> different hash; fit/holdout plan
  deterministic; `verify_no_leakage` passes on both kinds; no group
  crosses partitions (fixture: scene_a -> train, scene_b -> test).
- Applying a plan to a fixture copy revalidates with zero errors.

## Execution notes

One Codex run (gpt-5.6-sol, high), exactly in scope. Design decision
ratified on review: fit/holdout is a plan-level artifact because the
frozen `ias.audio_dataset_manifest.v1` restricts `SplitRecord.name` to
train/validation/test — no manifest contract change was made.

## Input contract for S2.6+

The dataset chain S2.1-S2.5 is complete: layout, atomic recording, checked
replay, canonical validation, and deterministic splits. S2.6 (shared
validation controller) is independent of this chain and consumes
S1.2/S1.3 contracts; S2.7 recording UI drives `SessionRecorder` and
surfaces validator findings; S4.4 fit/holdout freezing uses `SplitPlan`
artifacts.
