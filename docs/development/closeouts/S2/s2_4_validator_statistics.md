# S2.4 closeout - Validator and statistics

Status: **passed** (2026-07-17). Entry revision `3f3748e`; predecessor
closeout `docs/development/closeouts/S2/s2_3_checked_replay.md`.

**This is the canonical dataset validator** referenced by S2.9, S4, and S5:
`isaac_audio_sensors.core.dataset.validate_dataset` /
`isaac-audio-sensors dataset validate`.

## Scope delivered

- `core/dataset/validate.py`: `validate_dataset` — single streaming pass
  converting every located failure of the layout/loader stack into a
  machine-readable `Finding` (38 stable snake_case codes; complete
  inventory in the gate evidence) with severity and location; continues
  where structurally possible; report statuses
  `passed`/`passed_with_warnings`/`failed`; unsupported input (nonexistent
  path, `training_features`) raises explicitly instead of producing
  findings. Optional `deep_audio` mode streams WAV payloads in bounded
  chunks for finiteness checking.
- `core/dataset/statistics.py`: same-pass statistics — counts, per-shard
  and total durations, attributed vs tail samples, label vocabulary,
  modality presence, missingness, consistency, dropped frames, asset
  bytes; deterministic `to_dict()`.
- CLI `dataset validate` / `dataset stats` subcommands (exit 1 on failed
  validation; `--json` full report); Makefile `dataset-validate-fixture`.
- `tests/test_dataset_validator.py`: 23 tests — reference-fixture exact
  statistics, per-corruption intended-finding-and-no-false-finding matrix,
  split-group crossing, portability warning, deep-audio NaN (re-hashed so
  only finiteness catches it), unsupported input, CLI behavior,
  boundedness.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.4/{validator_gate.json,
validator_report_reference.json}`.

- Full suite 642 passed / 0 failed; ruff clean;
  `make dataset-validate-fixture` passes.
- Reference fixture: zero violations (status `passed`, 0 findings),
  statistics independently re-derived (3/2/7, 2080 samples = 1920
  attributed + 160 tail).
- Every planted corruption yields exactly the intended finding code.
- Streaming/bounded: a 28125-frame, ~230 MB-WAV session validated with
  `deep_audio` at a 6 MiB process RSS delta against the frozen 128 MiB
  S2.2 limit (orchestrator-measured via `/usr/bin/time -v`).

## Execution notes

One Codex run (gpt-5.6-sol, high), exactly in scope; diff reviewed
line-by-line (existing CLI subcommands untouched); gates rerun
independently, including the large-session boundedness measurement.

## Input contract for S2.5

Grouped splits consume S2.4-clean manifests: the splitter must require a
passing validation, fail on `split_group_crossing_shard` findings (physical
resharding required), and emit `SplitRecord`s whose reproducibility is
provable by repeated-seed hash identity.
