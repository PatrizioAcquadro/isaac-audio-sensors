# S2.2 Atomic bounded-memory writers

## Status and scope

This note specifies the S2.2 session writer mechanics and **freezes the
memory specification before any telemetry evidence exists**, as required by
the acceptance contract (`s0_squadbot_readiness_acceptance.md` §S2.2: the
representative workload, sample rule, and memory limit are selected before
acceptance evidence is viewed and are not adjusted afterwards). The on-disk
contract it must produce is frozen in
`docs/development/specs/s2_session_shard_layout.md` (S2.1); this note adds
only writer behavior. Implementation lands in
`src/isaac_audio_sensors/core/dataset/` (`atomic.py`, `audio_shards.py`,
`recorder.py`).

## 1. Writer mechanics contract

- **Staging.** All in-flight output lives under
  `<session_root>/_staging/`: the disk-backed episode buffer of aligned
  packing (S2.1 §3) and the open shard's partial `frames.jsonl` and audio
  file. Nothing is ever written directly into `shards/` or at the session
  root except by promotion.
- **Promotion.** A shard is published by: flushing and `fsync`ing every
  staged file; `os.replace` of each file into `shards/<shard_id>/`;
  `fsync` of the shard directory; then building, writing (temp +
  `os.replace`), and `fsync`ing `shard.complete.json` **last**; then
  `fsync` of the shard directory again and removal of the shard's staging
  remnants. The S2.1 marker invariant ("complete iff marker verifies") is
  therefore structural at every instant.
- **Finalization.** `manifest.json` is written (temp + `os.replace` +
  directory `fsync`) only after every published shard's marker verifies and
  `_staging/` has been removed. Finalize-as-incomplete follows the same
  sequence with `completion_state: "incomplete"` and only the truly
  published shards listed.
- **Checksums.** Rolling SHA-256 is maintained while streaming; promotion
  never re-reads staged payloads to hash them (bounded I/O), but marker
  verification after promotion may.
- **Cancellation.** A cooperative cancellation token is checked at least
  once per frame; on cancellation the writer either promotes the open shard
  (if it can complete a consistent boundary) or abandons its staging, then
  finalizes-as-incomplete. Cancellation must never publish an unverifiable
  shard.
- **Resume.** Resume scans `_staging/`, discards partial artifacts,
  verifies the published tail (last shard marker + tiling), and continues
  writing from the next `dataset_frame_index`. A resumed session must be
  indistinguishable, byte-level where promise B applies, from an
  uninterrupted one (S2.1 §8), except explicitly recorded drop accounting.
- **Fault injection seams.** Disk-full and slow-writer behavior is tested
  through an injectable filesystem seam in `atomic.py` (no tmpfs/sudo);
  interruption through subprocess kill. On `ENOSPC` or any write error the
  writer must fail the shard explicitly, leave no marker, preserve prior
  published shards, and surface a located error.
- **Audio.** WAV float32 streaming per the S2.1 §6 policy, with mid-episode
  rotation carry per S2.1 §4.1 (carry transfers to the next shard's stream;
  never flushed into the closing shard). FLAC support in S2.2 is limited to
  the export-transcode path contract; the recorder itself always writes WAV.

## 2. Frozen memory specification

Frozen at commit time of this document, before any S2.2 telemetry was
generated or viewed. Rationale: structurally, the writer holds only
per-window numpy buffers (~tens of KB), overlap/reverb carry, rolling hash
state, and bounded bookkeeping; the aligned episode buffer is disk-backed by
contract (S2.1 §3). The limit is set far above that structural need but
strictly below the in-memory size of one representative shard
(≈ 230 MiB of float32 audio), so whole-shard in-memory buffering — the
failure mode this gate exists to catch — cannot pass. The growth bound
separately catches accumulation across shards.

### 2.1 Representative workload (frozen)

Deterministic synthetic frame stream, no Isaac dependency, produced by
`scripts/measure_writer_memory.py`:

| Parameter | Value |
| --- | --- |
| Channels / rate / dtype | 4 / 48000 Hz / float32 |
| Window / hop | 1024 / 512 samples |
| Shard policy W1 | unaligned, `shard_max_frames = 28125` (exactly 300 s of audio per shard) |
| Run W1a | 11 simulated minutes → 2 published shards + 1 in-flight staged shard at sampling end |
| Run W1b | 16 simulated minutes → 3 published shards + 1 in-flight staged shard |
| Shard policy W2 | aligned, 6 episodes x 30 s (2 split groups), `shard_max_frames = 5625` |
| Frame payload | representative frame v1 dict with 2 detections and small diagnostics |

### 2.2 Sampling rule (frozen)

- A monitor thread samples `VmRSS` from `/proc/self/status` and the open
  file-descriptor count (`/proc/self/fd`) every **0.5 s wall-clock**, plus
  one forced sample immediately after every shard promotion.
- Baseline = the mean of 3 samples taken after imports and workload
  construction, before the first frame is written.
- Reported statistic per run: `peak_rss_delta = max(samples) - baseline`,
  `peak_fd_delta`, and the full sample series in the evidence JSON.

### 2.3 Limits (frozen)

1. `peak_rss_delta <= 128 MiB` for W1a, W1b, and W2 individually.
2. Session-length independence: `peak_rss_delta(W1b) - peak_rss_delta(W1a)
   <= 32 MiB`.
3. `peak_fd_delta <= 16` for every run.

Any breach fails S2.2; the limits are not renegotiable after telemetry
exists. If a breach is found, the writer is fixed and the full workload is
rerun.

## 3. Acceptance gates (S2.2)

1. Fault matrix — for each of: subprocess-kill interruption (at >= 3
   distinct phases: mid-JSONL-line, post-audio pre-marker, mid-promotion),
   injected `ENOSPC` (staging write, promotion, marker write), partial
   final line, slow writer (throttled seam), and write-retry: afterwards no
   shard without a verifying marker is discoverable as complete,
   `validate_session_layout` classifies the session per S2.1 §7, and
   resume then produces a session whose canonical validator result is
   identical to an uninterrupted run's.
2. Rotation carry — the S2.1 §11.16 concatenation-equivalence test runs
   against the real recorder (single-shard vs multi-shard bit-identical
   concatenation, `tail_samples == 0` on mid-episode-rotated shards).
3. Memory — §2 workloads pass all three frozen limits.
4. Cancellation — cancelling at random frames (seeded) never yields a
   false-complete shard and always leaves a resumable or
   finalized-incomplete session.

Evidence: `outputs/isaac_audio_sensors/S2/S2.2/{writer_gate.json,
fault_matrix.json, memory_telemetry.json, staged_vs_final_listing.txt}`;
closeout `docs/development/closeouts/S2/s2_2_atomic_writers.md`.
