# S2.3 closeout - Checked loader and replay

Status: **passed** (2026-07-17). Entry revision `47943cd`; predecessor
closeout `docs/development/closeouts/S2/s2_2_atomic_writers.md`.

## Scope delivered

- `core/dataset/loader.py`: `SessionDataset.open` (metadata-only open with
  lifecycle classification, exact manifest-projection check rejecting
  silent coercion, config-hash and calibration-reference verification,
  unknown-version rejection naming file and value), `iter_records` /
  `iter_episodes` (exact dataset order, O(1) record retention, per-shard
  streaming verification on first entry, drained shared-stream episode
  iterators), `read_frame_audio` / `read_shard_audio` (bounded seek reads
  of half-open sample ranges directly from the float32 WAV payload; empty
  range yields `(channels, 0)`; range checks against marker sample_count).
  `verify_checksums=False` fast path skips hashes only, keeping all
  structural checks.
- `core/dataset/replay.py`: `replay_session` yielding ordered
  `episode_start` / `frame` (optional audio) / `reset` / `episode_end`
  events; read-only guarantee asserted via inventory/mtime snapshot.
- `tests/test_dataset_loader_replay.py`: 22 tests — recorder round-trips
  (aligned + multi-shard unaligned) with exact preservation of order,
  types, units, timestamps, detections, boundaries, and bit-equal audio;
  committed reference fixture replay; 14-case corruption matrix with
  located-error assertions; boundedness; read-only.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.3/{replay_gate.json,
failure_report_matrix.md}`.

- Full suite 619 passed / 0 failed / 67 optional-dependency skips; ruff
  clean.
- Reference fixture replays as 3 episode_start + 3 reset + 7 frame +
  3 episode_end events; the empty-range frame reads `(4, 0)` audio
  (independently re-executed by the orchestrator).
- Every planted corruption class (missing assets, flipped bytes in WAV and
  JSONL, truncation, non-monotonic time, index gap, unknown
  record/marker/manifest versions, range violations, manifest/marker
  checksum disagreement) fails with a located error naming the offending
  shard, file, line, or episode; no silent coercion or reordering path
  exists.

## Execution notes

One Codex run (gpt-5.6-sol, high), exactly in scope, no deviations; diff
reviewed line-by-line; gates rerun independently by Claude.

## Input contract for S2.4

The validator consumes `SessionDataset` iteration (streaming, bounded by
the frozen S2.2 limits) and the layout streaming verification. It must
report counts, duration, missingness, channel/sample-rate consistency,
timestamps, ranges, labels, modalities, and asset integrity; zero
violations on valid fixtures; every planted corruption from the S2.3
matrix must map to a distinct machine-readable finding.

<!-- BEGIN GENERATED S2 REVIEW REMEDIATION -->

## S2 review remediation (regenerated)

The documented export-only FLAC path now passes int16 and int24 export/replay, exact
declared-type decoded comparisons, corruption location, and missing-dependency behavior.
Evidence: `outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json`.

<!-- END GENERATED S2 REVIEW REMEDIATION -->
