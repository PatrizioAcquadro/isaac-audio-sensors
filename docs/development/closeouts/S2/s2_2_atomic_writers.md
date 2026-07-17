# S2.2 closeout - Atomic bounded-memory writers

Status: **passed** (2026-07-17). Entry revision `9046420` (frozen memory
spec); predecessor closeout
`docs/development/closeouts/S2/s2_1_session_shard_layout.md`.

## Scope delivered

Spec `docs/development/specs/s2_atomic_writers.md` (memory section frozen
pre-telemetry at `9046420`; checksum rule amended pre-implementation at
`05af2fb` after a correct Codex BLOCKED report showed the original blanket
no-re-read wording was impossible for a size-patched RIFF container).

- `core/dataset/atomic.py` (commit `a2b326b`): `FilesystemSeam` fault
  boundary (ENOSPC/delay/short-write hooks), `StagedFile` with rolling
  SHA-256, atomic publication (`fsync` + `os.replace` + parent-directory
  `fsync`), `write_json_atomic`, `CancellationToken`/`CancelledWrite`,
  bounded transient retry (ENOSPC never retried), `JsonlShardFile`.
- `core/dataset/audio_shards.py` (`a2b326b`): `StreamingWavShardWriter`
  (placeholder header, finalize-time size patch, single bounded sequential
  re-read hash) and `CarryState` with explicit take/replace transfer so
  mid-episode rotation carry is never flushed into the closing shard.
- `core/dataset/recorder.py` (`4102c83` + memory-fix commit):
  `SessionRecorder` — canonical config write, planner-driven aligned
  episode buffering (disk-backed) and unaligned streaming, spec-ordered
  promotion with the marker atomically last, durable carry checkpoints,
  drop accounting into the next promoted marker, resume from the verified
  published tail (producers replay from the last published boundary),
  `finalize`/`finalize_incomplete` producing validating manifests.
- `scripts/measure_writer_memory.py` + `make measure-writer-memory`: the
  frozen W1a/W1b/W2 workloads and 0.5 s RSS/fd sampling rule; sampling
  window covers exactly the writer workload (post-run validation excluded).
- Tests: 18 primitive fault-matrix tests, 10 recorder integration tests,
  streaming-vs-retained verification equivalence tests, and an RSS
  regression guard. Full suite 597 passed / 0 failed; ruff clean.

## Memory gate: failure, fix, rerun

The first full-scale acceptance run **failed** the frozen limits exactly as
the gate was designed to catch: W1a 666 MiB / W1b 860 MiB / W2 131 MiB peak
RSS delta (limit 128 MiB) with 194 MiB session-length growth (limit
32 MiB). Root cause: the recorder retained every parsed record of every
published shard (`VerifiedShard.records`), and promotion-time verification
materialized whole shards. Fix: streaming `retain_records=False`
verification in `layout.py` (identical checks and located error strings,
proven by equivalence tests), marker-only published state, and incremental
episode accounting; pre-fix and post-fix manifests are byte-identical.
Failed telemetry preserved at
`outputs/isaac_audio_sensors/S2/S2.2/memory_telemetry_failed_prefix_run.json`.

Full-scale rerun after the fix (limits unchanged): W1a 8.5 MiB, W1b
2.3 MiB, W2 1.9 MiB peak RSS delta; growth <= 0; max fd delta 5. All three
frozen limits pass with wide margins;
`outputs/isaac_audio_sensors/S2/S2.2/memory_telemetry.json`.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.2/{writer_gate.json,
fault_matrix_tests.txt, memory_telemetry.json,
memory_telemetry_failed_prefix_run.json, staged_vs_final_listing.txt}`.

- Fault matrix (29 test nodes): no injected failure ever exposes a shard
  without a verifying marker as complete; resume yields validator-identical
  sessions; prior published shards survive promotion failures.
- Rotation carry: bit- and duration-identical concatenation across shard
  configurations; `tail_samples == 0` on mid-episode-rotated shards.
- Memory: all frozen limits pass (above).
- Cancellation: seeded cancellation never yields a false-complete shard.

## Execution notes

Three Codex runs (gpt-5.6-sol, high): Run A blocked correctly once on the
impossible checksum wording (resolved by spec amendment before any
implementation), then landed clean; Run B landed clean but breached the
frozen memory gate at full scale; the fix run landed clean with
no existing test assertions modified. All diffs reviewed line-by-line;
all gates rerun by Claude; the full workload was rerun, never shortened.

## Input contract for S2.3

Published sessions from `SessionRecorder` are the loader's input. S2.3 must
load incrementally (streaming, bounded by the frozen S2.2 limits), preserve
order/types/units/timestamps/episode boundaries, and fail with location
context on missing assets, corruption, checksum mismatch, non-monotonic
time, and unknown versions. `layout.verify_shard_completion(...,
retain_records=False)` and the internal streaming record generator are the
building blocks.
