# S2.1 Session and shard layout

## Status and scope

This note freezes the on-disk layout, identity, determinism, and completion
contract for every recorded audio dataset session produced in S2 and consumed
by S2.2-S2.9, S3, S4, and P1. It builds on the frozen
`ias.audio_dataset_manifest.v1` and `ias.audio_sensor_frame.v1` contracts
(S1.2/S1.7) and changes neither schema; every new structure here is a *dataset
layer* wrapped around unmodified contract objects. Writer mechanics (staging,
fsync, cancellation, resume, memory limits) are assigned to S2.2
(`docs/development/specs/s2_atomic_writers.md`); this note defines what a
finished or in-progress session looks like and what is promised about it.

Implementation lands in a new import-safe subpackage
`src/isaac_audio_sensors/core/dataset/` (module `layout.py` for this
subphase). Existing `core/io/` primitives remain the serialization building
blocks and are not modified.

**Profile restriction.** This layout covers `waveform_fidelity` sessions
only. A configuration or manifest with `runtime_profile:
"training_features"` is rejected explicitly by the S2 recorder, loader, and
validator (`unsupported runtime profile for dataset layout v1`). A
feature-only shard layout is a deliberate deferral to P1 (training-scale
dataset production), recorded here so its absence is never a silent gap.

## 1. Session root layout

A *session* is one dataset capture rooted at a caller-chosen directory. All
contract paths are POSIX-relative to the session root; nothing inside a
session may reference the root's absolute location. No entry anywhere under
the session root may be a symbolic link; loader and validator reject
symlinks.

```
<session_root>/
  manifest.json                     # ias.audio_dataset_manifest.v1, written last
  config/
    session_config.json             # canonical configuration bytes (§4.3)
  calibration/<profile_id>.json     # optional; referenced by the manifest
  shards/
    <shard_id>/
      frames.jsonl                  # frame_trace_jsonl asset (§4.1 records)
      audio.wav | audio.flac        # lossless audio asset (§6)
      shard.complete.json           # completion marker, written last per shard
  _staging/                         # transient writer workspace (S2.2);
                                    # MUST be absent from a finalized session
```

Rules:

- `manifest.json` is the only file directly at the root; the only root
  directories are `config/`, `calibration/`, `shards/`, and (transiently)
  `_staging/`. Unknown entries are a validator finding.
- `manifest.json` is written exactly once, atomically, after finalization
  (§7). Its `completion_state` is the sole session-level publication signal.
- Asset filenames inside a shard directory are fixed (`frames.jsonl`, and
  `audio.wav` or `audio.flac`); variability lives only in `<shard_id>`. The
  canonical trace suffix is `.jsonl` (the manifest schema also accepts
  `.ndjson` for imported assets; S2 writers always emit `.jsonl`).
- `visual_sync` assets (S3+) will live at `shards/<shard_id>/visual/…`;
  reserved, not produced in S2.

## 2. Identity: producer identity vs dataset identity

`ias.audio_sensor_frame.v1` is produced by the sensor engine; its `frame_id`
(free-form non-empty string) and optional `frame_index` are **producer
identity** and are preserved byte-verbatim inside stored records — the
dataset layer never rewrites, renumbers, or requires global uniqueness of
producer fields. **Dataset identity** is assigned by the recorder and is the
only identity the layout, joins, and manifest ranges use:

| Identity | Rule |
| --- | --- |
| `dataset_id` | Caller-supplied stable id from configuration; never derived from wall-clock time. |
| `episode_id` | `episode_<NNNNN>`, zero-padded decimal ordinal of the episode within the session, starting at `00000`. |
| `shard_id` | `shard_<NNNNN>`, zero-padded decimal ordinal of the shard within the session, starting at `00000`. |
| `dataset_frame_index` | Zero-based, session-global, strictly contiguous ordinal over frames *actually written*, in write order. No holes ever: a producer drop consumes no index (drops are accounted in the marker, §5). |
| `asset_id` | `<shard_id>.frames` for the JSONL asset; `<shard_id>.audio` for the audio asset. |

Cross-contract reconciliation:

- Manifest `EpisodeRecord.start_frame`/`end_frame` are inclusive
  `dataset_frame_index` bounds; `start_step`/`end_step` carry producer step
  counters when available, else mirror the frame bounds.
- JSONL line `k` (zero-based) of shard `s` holds exactly the record with
  `dataset_frame_index = s.start_frame + k`; line count equals
  `s.frame_count` exactly (§5). No blank, comment, or trailing lines.
- Within one episode, producer `frame.frame_id` values must be unique;
  duplicates are a validator error (they would make replay-to-producer
  correlation ambiguous). Across episodes no producer-id constraint exists.
- Fixed id width is five digits; a session that would exceed 100000 episodes
  or shards fails explicitly rather than widening.

**Episode correspondence invariants.** For every `EpisodeRecord`:

- the episode's dataset frame records are **contiguous** in
  `dataset_frame_index` and exactly cover the inclusive range
  `[start_frame, end_frame]` — no missing, extra, duplicated, or misordered
  record, and no record of another episode interleaved within the range;
- episodes tile the session in ordinal order:
  `episode_<n+1>.start_frame == episode_<n>.end_frame + 1`, with
  `episode_00000.start_frame == 0` and the last episode ending at the
  session's final written frame;
- `len(timestamps_ms) == end_frame - start_frame + 1`, and entry `k` equals
  the `frame.timestamp_ms` of the record at `start_frame + k`.

Any violation is a hard loader/validator error naming the episode and the
first offending frame index.

## 3. Shard boundary policy

Boundaries are a pure function of the written frame stream and two
configured values; two runs over the same stream produce identical
boundaries.

- `shard_max_frames` (positive int, required).
- `shard_episode_aligned` (bool, default `true`).

**Aligned mode (`true`) — whole-episode packing, group-aligned, streaming:**

The packing decision is made without knowing an episode's final frame count
in advance. Frames of the current episode stream into a **disk-backed
episode buffer** in `_staging/` (S2.2 mechanics), never held in memory
beyond O(1) per-frame state, and the buffer is bounded to at most
`shard_max_frames` frames:

```
open shard S (empty)
for each episode E (dataset order):
    buffer = 0 frames (disk-backed)
    for each written frame of E:
        stage frame into buffer
        if buffer == shard_max_frames and E is still open:
            # E is oversized: exclusive occupancy, eager flush
            if S is non-empty: close S; open new S
            emit buffer as one full exclusive shard; buffer = 0
            mark E oversized
    # episode end; |E_remainder| = buffer <= shard_max_frames
    if E was marked oversized:
        if buffer > 0: emit buffer as E's final exclusive shard
        open new S (empty)
    else:
        if S is non-empty and (frames_in(S) + buffer > shard_max_frames
                               or split_group(E) != split_group(S)):
            close S; open new S
        append buffer to S
close S at end of stream if non-empty
```

Consequences: episodes never span shards except the oversized case; a shard
never contains episodes from more than one `split_group` (§9); packing is
greedy in dataset order and therefore deterministic for a given stream; and
resource use is bounded — disk staging never exceeds one
`shard_max_frames`-sized episode buffer plus the open shard, and memory
stays within the S2.2 limit regardless of episode length. Oversized-episode
chunk boundaries fall at exact multiples of `shard_max_frames` within the
episode.

**Unaligned mode (`false`) — long-capture:** ignore episode and group
boundaries; close the shard after exactly `shard_max_frames` frames. Used by
the S2.9 endurance capture. Sessions recorded in this mode are ineligible
for grouped splits until physically resharded (§9).

Every shard holds at least one frame; a session with zero written frames can
only finalize as `completion_state: "incomplete"` with zero shards.

## 4. Records, joins, configuration, and provenance

### 4.1 Dataset frame records and audio joins

Each `frames.jsonl` line is one **dataset frame record**, format id
`ias.dataset_frame_record.v1`, serialized compact
(`sort_keys=True, separators=(",", ":")`, one line, `\n`-terminated):

```json
{
  "record_version": "ias.dataset_frame_record.v1",
  "dataset_frame_index": 17,
  "episode_id": "episode_00001",
  "audio_start_sample": 81920,
  "audio_end_sample": 90112,
  "frame": { …unmodified ias.audio_sensor_frame.v1 trace dict… }
}
```

`[audio_start_sample, audio_end_sample)` is a **half-open sample range into
the shard's own audio asset** (frame-major sample indices, all channels
implied). It is *authoritative writer output* — recorded from the samples
the writer actually committed, never re-derived from timestamps by readers.
Rules:

- Bounds: `0 <= audio_start_sample <= audio_end_sample <=
  audio.sample_count` (of the containing shard's marker, §5). Ranges never
  reference another shard.
- Empty range (`start == end`) means "no audio attributed to this frame"
  (e.g. frame captured while audio rendering was disabled or dropped
  windows); it is legal and explicit, never inferred.
- Ordering: within a shard, `audio_start_sample` is non-decreasing in line
  order, and `audio_end_sample[k] >= audio_end_sample[k-1]` for overlapping
  windows produced by overlap-add capture. Overlap between consecutive
  ranges is permitted up to the configured window/hop overlap recorded in
  `session_config.json`; larger overlap is a validator error.
- Gaps: samples between `audio_end_sample[k-1]` and `audio_start_sample[k]`
  belong to no frame; they represent inter-window audio (e.g. simulation
  pauses rendered as silence). Gap preservation semantics beyond S2 (exact
  pause reproduction) are S3.2's contract; the layout only requires gaps be
  representable and never silently collapsed.
- Resets: across a `ResetMarker` boundary, ranges must not overlap
  (`audio_start_sample[k] >= audio_end_sample[k-1]`): renderer overlap-add
  state never blends across a reset.
- Rounding: none exists in the contract. Producers compute sample counts
  however they like (the existing `ContinuousWaveformWriter` accounting is
  the reference); the stored integers are the truth readers must obey.
- Reverb/overlap tail: samples after the last frame's `audio_end_sample` up
  to `sample_count` are the shard's **tail**, owned by the shard (not any
  frame), with `tail_samples = sample_count - max(audio_end_sample over the
  shard's records, defaulting to 0 when no record attributes audio)`
  recorded in the marker. In particular, when every range in a shard is
  empty, `tail_samples == sample_count` (all samples unattributed); a shard
  whose audio asset was written with no samples has `sample_count == 0` and
  `tail_samples == 0`. On an episode-aligned boundary the tail is the
  flushed overlap-add remainder; a reader reconstructing continuous audio
  concatenates shard streams including tails.
- **Mid-episode shard rotation (oversized and unaligned modes).** An
  episode's audio is conceptually one continuous unsharded stream; rotation
  splits that stream at a **cut sample**: the stream position where the
  first frame window assigned to the next shard begins (its hop boundary).
  The closing shard's audio contains exactly the stream samples before the
  cut (`sample_count == cut − shard stream origin`). All renderer carry
  state — overlap-add remainders and reverb-tail contributions from
  committed windows extending past the cut — **transfers into the next
  shard's stream and is never flushed into the closing shard.** Tail
  flushing happens only at an episode end (aligned mode and the final
  oversized chunk) or at session finalization (unaligned mode); a
  mid-episode-rotated shard therefore has `tail_samples == 0`. A frame in
  the closing shard whose window crosses the cut stores
  `audio_end_sample` clamped to `sample_count`; its remaining window
  samples are the leading samples of the next shard, so reconstructing
  that single frame requires concatenating the two adjacent shards
  (documented property of long-capture modes). Invariant: for the same
  frame stream and configuration differing only in `shard_max_frames`,
  concatenating a session's shard audio in order is **bit-identical and
  duration-identical** to the equivalent single-shard continuous
  recording — no duplicated samples, no inserted silence, no
  discontinuity, and the sum of shard `sample_count`s equals the
  unsharded `sample_count`.
- Dropped frames: a producer frame that the writer could not commit is
  **reported, never silently skipped**: it consumes no
  `dataset_frame_index`, and the shard marker's `dropped_frames` block
  (§5) records the count and producer identities. S2.9's "no unreported
  drop" gate reconciles writer counters against these records.

### 4.2 Timestamps

`time_base` is `simulation_time` for simulator captures. `timestamp_ms`
values are non-negative and monotonic non-decreasing within an episode;
every reset boundary is an explicit `ResetMarker`; the loader never infers
resets. Sample rate, channel count, and channel order are constant per
session, declared once in the manifest; a mid-session change is a hard
error (consistent with `ContinuousWaveformWriter`'s parameter lock).

### 4.3 Configuration and seeds

- `config/session_config.json` stores the **canonical configuration
  bytes**: JSON, `sort_keys=True`, `separators=(",", ":")`, UTF-8, `\n`
  -terminated, all path-valued fields normalized to POSIX-relative form.
  `AudioDatasetManifest.configuration_sha256` is the SHA-256 of exactly this
  file's bytes, so the digest is verifiable offline from the session alone.
- The configuration contains `session_seed` (non-negative int). Per-episode
  seeds are derived deterministically for episode ordinal `n`:

  ```python
  episode_seed(n) = int.from_bytes(
      hashlib.sha256(
          f"{dataset_id}:{session_seed}:{n}".encode("utf-8")
      ).digest()[:8],
      "big",
  ) >> 1
  ```

  unless the producer supplies an explicit
  per-episode seed, which is stored verbatim in `EpisodeRecord.seed`. Either
  way the stored seed is reproducible from `session_config.json` plus the
  producer's own record; the derivation function ships in
  `core/dataset/layout.py`.

### 4.4 Provenance

`CreationProvenance` and `DeviceProvenance` are filled from the running tool
and host. `creation_timestamp_ms` is wall-clock and therefore excluded from
byte-identity promises (§7); fixture regeneration pins it.

### 4.5 Canonical trace projection (portability of stored frames)

Stored `frame` dicts are the existing canonical frame-trace serialization
(`frame_to_trace_dict`). The **projection is a validation gate, not a
rewrite: no field of any frame is ever modified by the dataset layer.** A
frame that violates the rules below is a write-time error the producer must
fix; an accepted frame is stored byte-identically to its canonical
serialization. Exactly two contract path fields are constrained:

- `frame.waveform_paths`: must be empty, or session-root-relative POSIX
  paths of files that exist inside the session. Continuous shard capture
  (this layout) writes it empty — the authoritative audio reference is the
  record's sample range. Absolute paths, `..`, backslashes, or paths
  escaping the session root are rejected at write time.
- `detections[*].audio_asset_path`: scheme URIs (`generated://…`) are
  accepted verbatim (host-independent); filesystem paths must satisfy the
  same session-relative rule as `waveform_paths`.

`frame.diagnostics` and nested detection `diagnostics` are **excluded from
the portability promise** (§8): they are free-form, preserved byte-verbatim,
never scrubbed, and never rejected for their content. The S2.4 validator
emits a non-fatal portability **warning** for diagnostic string values that
look like absolute filesystem paths; producers wanting portable diagnostics
must write relative paths themselves. All other frame fields pass through
untouched; frame v1 schema semantics are unchanged — the projection
constrains which *values* this dataset layer accepts, not the schema.

## 5. Completion markers

Marker format id `ias.shard_completion.v1`, file
`shards/<shard_id>/shard.complete.json`, serialized like all contract JSON
(`indent=2`, `sort_keys=True`, trailing newline). Formal schema:

| Field | Type | Constraint |
| --- | --- | --- |
| `marker_version` | str | exactly `"ias.shard_completion.v1"` |
| `shard_id` | str | id pattern; **must equal the containing directory name** |
| `start_frame` | int | >= 0; session-global `dataset_frame_index` of line 0 |
| `frame_count` | int | >= 1; the half-open frame range is `[start_frame, start_frame + frame_count)` |
| `episode_ids` | [str] | non-empty, unique, in first-appearance order; exactly the episodes of the contained frames |
| `files` | [obj] | each `{path, sha256, bytes}`; see invariants |
| `audio` | obj | `{path, container, subtype, channels, sample_rate_hz, dtype, sample_count}` |
| `tail_samples` | int | >= 0; `sample_count - max(audio_end_sample over contained records, default 0)`; equals `sample_count` when every range is empty |
| `dropped_frames` | obj | `{count, producer_frame_ids}`; `count` >= 0, ids may be truncated to first 100 with `count` authoritative |
| `writer_tool_version` | str | package version that wrote the shard |

Validation invariants (enforced by `layout.py` marker build/verify and by
the S2.3 loader and S2.4 validator):

1. `files[*].path` are relative to the shard directory, single-component
   (no `/`, no `..`, no backslash), unique, and drawn from the fixed names:
   exactly one `frames.jsonl` entry and exactly one audio entry
   (`audio.wav` xor `audio.flac`) — both required in this layout. The
   marker never lists itself.
2. Every listed file exists with exactly `bytes` size and matching
   lowercase SHA-256. **A shard is complete iff its marker exists, parses,
   and every invariant here verifies.**
3. `audio.path` equals the audio entry in `files`; `container` is
   `wav`/`flac` matching the suffix; `subtype`, `channels`,
   `sample_rate_hz`, `dtype`, and `sample_count` must equal the decoded
   audio header (and frame count where the container states it). `channels`
   equals `len(manifest.channel_order)`; `sample_rate_hz` and `dtype` equal
   the manifest values.
4. `frames.jsonl` contains exactly `frame_count` lines; line `k` parses as
   an `ias.dataset_frame_record.v1` with `dataset_frame_index ==
   start_frame + k`, `episode_id` in `episode_ids`, sample-range bounds
   within `[0, audio.sample_count]`, and a `frame` object that revalidates
   as frame v1 under the §4.5 projection rules.
5. Consecutive shards tile the session: shard `n+1`'s `start_frame` equals
   shard `n`'s `start_frame + frame_count`; shard `00000` starts at 0.
6. Manifest/marker agreement is exact: for every `ShardRecord`, its asset
   set corresponds one-to-one with the marker's `files` — same session-
   relative paths (`shards/<shard_id>/<name>`), asset `kind` consistent
   with the file name (`frame_trace_jsonl` for `frames.jsonl`, `audio_wav`/
   `audio_flac` for the audio file), and equal SHA-256 values. A manifest
   asset with no marker counterpart, a marker file absent from the
   manifest, a kind/suffix mismatch, or a checksum disagreement is
   corruption attributed to the specific shard and file.

**Complete-session validation** additionally requires, beyond every
per-shard invariant above: `config/session_config.json` exists and its
bytes hash to `AudioDatasetManifest.configuration_sha256`; when
`calibration_profile` is set, the referenced file exists at its relative
path with matching SHA-256 and parses as
`ias.audio_calibration_profile.v1`; and every shard directory under
`shards/` is listed in the manifest (an unlisted shard directory is a
finding).

## 6. Lossless audio policy (WAV vs FLAC)

- The canonical capture format is **WAV, 32-bit float** (soundfile subtype
  `FLOAT`), matching the existing `WAVEFORM_WAV_SUBTYPE` and the `float32`
  pipeline. Recording always writes WAV.
- **FLAC is an optional export/archival transcode only**, permitted iff the
  target `dtype` is `int16` or `int24` (FLAC is integer-PCM) and
  `len(channel_order) <= 8` (FLAC channel cap). Float→integer conversion is
  quantization and therefore must be an explicit user-requested export
  producing a *new* session with its own manifest, `dtype`, and checksums —
  never in-place, never labeled lossless relative to the float original.
- "Lossless" means: decoding the stored asset yields bit-exact samples for
  the declared manifest `dtype`.
- Both formats use the existing lazy-`soundfile`/`OptionalDependencyUnavailable`
  guard; absence of `soundfile` fails audio writing explicitly and can never
  yield a complete-marked shard missing its audio file (marker invariant 1
  makes this structural).

## 7. Session lifecycle and incomplete semantics

Four lifecycle states represented by three on-disk signatures (in-progress
and aborted deliberately share a signature; the distinction is operational,
not structural):

| State | On-disk signature | Loader behavior |
| --- | --- | --- |
| **in-progress** | `_staging/` present (live writer journal, S2.2), `manifest.json` absent | Not a loadable dataset; refused with "in-progress or aborted session". Resume (S2.2) may continue it. |
| **aborted** | Identical signature to in-progress (crash leaves the same shape) | Same refusal; recovery is S2.2 resume or explicit finalize-as-incomplete. The distinction is operational (no live writer), not structural — deliberately, so no heuristic can mistake a crash for a publishable dataset. |
| **finalized-incomplete** | `manifest.json` with `completion_state: "incomplete"`; `_staging/` removed; shards carry their true per-shard states | Loads as an explicitly incomplete dataset; complete shards are usable; never promoted to complete by any tool (existing manifest rule). |
| **complete** | `manifest.json` with `completion_state: "complete"`; `_staging/` absent; every shard's marker verifies | Full load. |

The manifest is written last and atomically, so no observer can see a
published manifest ahead of its shards ("false publication"). A
finalized-incomplete manifest lives at the same root path `manifest.json` —
location never encodes state; the field does. `ShardRecord`s for shards
whose staging was lost are listed as `incomplete` with their surviving
assets, or omitted if nothing was promoted.

## 8. Determinism promises

**Byte-identical (promise B).** With identical configuration, seed, frame
stream, and a pinned provenance block (fixed `creation_timestamp_ms`, tool
and runtime versions): `manifest.json`, `config/session_config.json`, every
`frames.jsonl`, every `shard.complete.json`, and every WAV asset produced by
the deterministic synthetic pipeline are byte-identical across regenerations
on the same platform and library set. The reference fixture (§10) is
regenerated under promise B and its hashes are committed.

**Logically deterministic (promise L).** Live captures promise: identical
episode/frame dataset identities, relative paths, shard boundaries, sample
ranges and counts, channel order, and join offsets; decoded-sample
bit-exactness wherever the producing backend declares determinism. FLAC
byte-identity is additionally per-`libsndfile`-version only.

**Portability.** A session remains fully valid after `mv`/`cp -r` of its
root to any path or machine. Absolute paths, symlinks, environment
references, and `\` separators are forbidden in `manifest.json`, in every
`shard.complete.json`, in `config/session_config.json`, and in the two
constrained contract path fields (`frame.waveform_paths` and filesystem
`detections[*].audio_asset_path`, §4.5). **Free-form diagnostics are
explicitly excluded from this promise**: absolute-path-shaped strings
inside `diagnostics` are permitted content, are never rejected or
rewritten, and may only produce the documented non-fatal S2.4 validator
warning. The gate proves portability by relocating the reference fixture
and re-running full validation.

## 9. Split-group safety

Grouped splits (S2.5) operate on `split_group` values, but assets are
shard-granular; a shard containing episodes from two groups would leak data
between splits at the file level. Therefore:

- Aligned-mode packing (§3) structurally prevents group-crossing shards.
- The S2.4 validator reports any shard whose episodes span multiple
  `split_group` values as a finding; the S2.5 splitter **fails** on such a
  session and requires physical resharding (a rewrite producing a new
  session with aligned shards) first. Resharding tooling, if needed beyond
  the fixture scale, is S2.5 scope.

## 10. Reference fixture

`examples/datasets/reference_session_v1/` — a tiny promise-B session,
committed with real (non-placeholder) checksums:

- 2 scenes / 3 episodes / 2 shards, `shard_episode_aligned: true`,
  `shard_max_frames: 4`: `episode_00000` (scene_a, 2 frames) and
  `episode_00001` (scene_a, 2 frames) pack into `shard_00000` (4 frames);
  `episode_00002` (scene_b, 3 frames) goes to `shard_00001` — consistent
  with the §3 algorithm (cap reached and group boundary coincide).
- 4-channel, 48 kHz, `float32` WAV; overlapping capture windows within an
  episode plus one empty-range frame and a nonzero tail, so §4.1's overlap,
  empty-range, and tail rules all appear in the fixture;
- `split_grouping_key: "scene_id"`; both groups assigned in `splits`;
- generated by the deterministic synthetic backend (no Isaac dependency)
  via `scripts/regenerate_reference_dataset.py` (pinned provenance),
  following the `regenerate_example_manifests.py` convention; Makefile
  target `regenerate-reference-dataset`;
- `.gitignore` gains `!examples/datasets/**` negations so fixture WAVs are
  tracked despite the global `*.wav` ignore;
- corrupt variants for S2.3/S2.4 are generated in tests, not committed,
  except tiny JSON-level invalid examples which may join the existing
  `examples/manifests/invalid/`-style corpus.

## 11. S2.1 acceptance gate

Positive checks:

1. Double regeneration of the reference fixture is byte-identical (promise
   B), proven by hashing every file across two runs.
2. A relocated copy of the fixture passes manifest load + full marker/file/
   checksum verification with zero differences (portability).
3. `manifest.json` round-trips through `read_dataset_manifest` /
   `write_dataset_manifest` unchanged; every stored `frame` revalidates as
   unmodified frame v1.
4. Layout functions (`core/dataset/layout.py`: id derivation and width
   overflow, shard packing both modes, record build/parse, marker
   build/verify, seed derivation, canonical-config hashing, trace
   projection) are pure, import-safe, and covered by
   `tests/test_dataset_layout.py`.

Adversarial checks (each must fail with a located error):

5. Joins: overlapping ranges beyond declared window overlap; overlap across
   a reset; `audio_end_sample > sample_count`; negative or inverted range;
   non-monotonic `audio_start_sample`; line count != `frame_count`;
   `dataset_frame_index` gap or duplicate; shard tiling break (shard n+1
   start != shard n end).
6. Marker: `shard_id` != directory name; missing/extra/duplicate `files`
   entry; multi-component or traversal path; both or neither audio
   container listed; `bytes` or sha256 mismatch; decoded audio header
   disagreeing with `audio.{channels,sample_rate_hz,dtype,sample_count}`;
   channel count != manifest channel order length.
7. Identity: duplicate producer `frame_id` within an episode; episode or
   shard ordinal overflow past 5 digits.
8. Projection/portability: absolute path in `waveform_paths` or filesystem
   `audio_asset_path`; backslash separator; symlink inside the session
   root; absolute-path-shaped diagnostic string yields exactly a warning,
   not an error.
9. Profile/lifecycle: `training_features` config or manifest rejected;
   `_staging/` present alongside `manifest.json` rejected; directory with
   no manifest refused as in-progress/aborted; finalized-incomplete loads
   but is never promoted.
10. Splits/config: shard spanning two `split_group`s flagged;
    `session_config.json` bytes not matching `configuration_sha256`;
    derived episode seed not reproducible from stored config.
11. Episode correspondence: missing, extra, duplicated, misordered, or
    interleaved records within an episode range; episode tiling break
    (`episode_<n+1>.start_frame != episode_<n>.end_frame + 1`);
    `len(timestamps_ms)` != frame count; `timestamps_ms[k]` disagreeing
    with the record's `frame.timestamp_ms`.
12. Complete-session validation: missing `config/session_config.json`;
    calibration reference to a missing file or mismatched hash; manifest
    asset with no marker counterpart; marker file absent from the
    manifest; asset `kind` inconsistent with its file name; unlisted shard
    directory under `shards/`.
13. Bounded packing: an oversized episode streamed through the aligned
    algorithm produces chunk boundaries at exact `shard_max_frames`
    multiples with disk staging never exceeding one episode buffer plus
    the open shard (asserted via the staging inventory), identically
    across two runs.
14. Tail/empty-range semantics: a shard whose ranges are all empty must
    carry `tail_samples == sample_count`; `sample_count == 0` must carry
    `tail_samples == 0`; any other combination fails.
15. Seed derivation: known-answer test vector for `episode_seed(n)`
    (fixed `dataset_id`, `session_seed`, `n` → expected 63-bit value) and
    a projection-identity test proving accepted frames are stored
    byte-identical to their canonical serialization.
16. Rotation/concatenation equivalence: record one deterministic stream
    twice, differing only in `shard_max_frames` (single-shard vs
    multi-shard, covering both oversized-aligned and unaligned rotation);
    per-session concatenated shard audio must be bit-identical and
    duration-identical to the single-shard recording, with the sum of
    shard `sample_count`s equal to the unsharded count,
    `tail_samples == 0` on every mid-episode-rotated shard, and clamped
    crossing-frame ranges resolving correctly across the boundary. Any
    duplicated sample, length shift, or discontinuity fails.

Evidence: `outputs/isaac_audio_sensors/S2/S2.1/{layout_gate.json,
fixture_hashes.txt, relocation_check.json}`; closeout
`docs/development/closeouts/S2/s2_1_session_shard_layout.md`.

## Appendix A - Draft S2.9 representative capture definition

Ratified (with the frozen memory rule from S2.2) at S2.9 entry, before
execution:

- Scene: headless variant of `configs/isaac_audio_sensors_demo.toml`
  (4-channel XVF3800-layout array, >= 2 active sources), backend
  `room_acoustics` if available on the runner, else `tdoa_synthetic`
  recorded as a documented substitution.
- Runtime profile `waveform_fidelity`; 48 kHz; `float32` WAV; capture
  window/hop per the demo config.
- Duration: >= 30 minutes wall-clock of continuous headless capture on Isaac
  Sim 6.0.1 (`/home/pacquadr/isaacsim/python.sh`).
- Sharding: `shard_episode_aligned: false`, `shard_max_frames` sized to
  ~5 simulated minutes per shard, so the run publishes >= 5 complete shards
  and ends with one deliberately in-flight shard to prove incomplete shards
  stay unpublished.
- Telemetry: RSS and open-file-descriptor count sampled every 5 s (final
  rule frozen in S2.2's memory specification).
- Pass: canonical S2.4 validator reports zero violations on the published
  session; telemetry stays within the S2.2-frozen limit; no unreported
  frame drop (writer counters equal `dropped_frames` records and validator
  counts).
