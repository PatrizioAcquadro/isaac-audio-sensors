# S2.1 closeout - Session and shard layout

Status: **passed** (2026-07-17). Entry revision `d8cee69` (spec freeze commit)
on `main`; predecessor closeout `docs/development/closeouts/S1_closeout.md`
(S1 exit gate met at `465b3eb`, v1.8.0).

## Scope delivered

Specification `docs/development/specs/s2_session_shard_layout.md` (frozen
after three user review rounds resolving 20 findings) and its implementation:

- `src/isaac_audio_sensors/core/dataset/` (new import-safe subpackage):
  `layout.py` with identity derivation (`episode_id`/`shard_id`, five-digit,
  explicit overflow), `ShardPlanner`/`plan_shards` (§3 aligned streaming
  whole-episode packing with group alignment and oversized exclusive chunks;
  unaligned frame-cap mode; bounded staging inventory accounting),
  `ias.dataset_frame_record.v1` build/serialize/parse with canonical-bytes
  enforcement and located errors, `ias.shard_completion.v1` marker
  build/verify covering all six §5 invariant groups with pure-stdlib
  WAV/FLAC header decoding, `episode_seed` (§4.3 known formula),
  `canonical_configuration_bytes`/`configuration_sha256`,
  `validate_trace_projection` (§4.5 gate; zero rewrites; diagnostics
  warning-only), `classify_session_lifecycle` (§7 three signatures),
  `validate_session_layout` (root whitelist, symlink rejection, episode
  correspondence, shard tiling, split-group safety, boundary-policy replan
  agreement, mid-episode-rotation tail check, calibration reference
  verification, config-bytes hash check).
- `scripts/regenerate_reference_dataset.py` + Makefile
  `regenerate-reference-dataset`: deterministic promise-B fixture generator
  with a local pure-stdlib IEEE-float32 RIFF writer (no soundfile
  dependency).
- `examples/datasets/reference_session_v1/`: committed fixture — 2 scenes /
  3 episodes / 2 shards (`shard_max_frames=4`, aligned), 4-channel 48 kHz
  float32, overlapping windows, one empty range, nonzero tails, grouped by
  `scene_id` with train/test splits. `.gitignore` negations added so fixture
  WAVs are tracked.
- `tests/test_dataset_layout.py`: 38 tests implementing spec §11 positive
  checks 1-4 and adversarial checks 5-16 at the layout level.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.1/{layout_gate.json,
fixture_hashes.txt, relocation_check.json}` (machine-local).

- Full pure suite: 560 passed, 67 skipped (optional-dependency skips), 0
  failed; ruff clean.
- Double regeneration byte-identical (promise B) and the committed fixture
  byte-identical to a fresh regeneration.
- Relocated fixture copy validates as `complete` with 2 shards / 7 records
  and zero warnings or differences.
- Manifest round-trips unchanged; stored frames revalidate as unmodified
  frame v1.

## Execution notes and deviations

- Implemented by one Codex CLI run (gpt-5.6-sol, reasoning high,
  workspace-write) against the frozen spec; Claude reviewed the complete
  diff line-by-line against baseline `d8cee69`, then independently reran all
  gates. A first launch failed on a CLI config incompatibility
  (`agents.max_depth=0` rejected; rerun with `=1`, multi-agent still
  disabled) with zero repository changes.
- Codex stayed exactly in scope; no out-of-scope writes.
- Interpretations recorded by the implementer and ratified on review:
  an episode of exactly `shard_max_frames` frames takes exclusive occupancy
  (literal §3 eager-flush semantics); configuration keys `path`/`*_path`/
  `*_paths` are treated as path-valued for §4.3 normalization checks (the
  spec does not enumerate them); renderer carry-transfer behavior of §11.16
  is S2.2-owned — S2.1 tests cover the boundary/cut and concatenation
  primitives and mark the deferral.
- The fixture pins `writer_tool_version` and manifest provenance at 1.8.0
  values by design (promise B); the S2.1d version bump does not regenerate
  the fixture.

## Input contract for S2.2

`core.dataset.layout` is the sole authority for ids, packing decisions,
record/marker formats, and session validation. The S2.2 atomic writer must:
drive `ShardPlanner` (or equal semantics) for boundaries; stage in
`_staging/` per §1/§7; emit markers via `build_shard_completion` semantics
atomically last; enforce the §4.5 projection at write time; and freeze the
memory specification in `docs/development/specs/s2_atomic_writers.md`
before any telemetry is generated or viewed.
