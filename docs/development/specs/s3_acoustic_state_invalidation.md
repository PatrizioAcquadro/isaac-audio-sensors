# S3.7 acoustic-state invalidation

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | Frozen prospective `S3.7` design, protocols, fixtures, and tolerances |
| Design date | 2026-07-18 |
| Entry revision | `7e29d4f1763ba1eac1f2b412223a6248456152a5` (`7e29d4f`) |
| Governing gate | `S3.7` materials, dynamic rooms, and occlusion |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Passed predecessors | `S3.2` time gaps and intra-window motion; `S3.6` waveform directivity |
| Evidence root | `outputs/isaac_audio_sensors/S3/S3.7/` |
| Required closeout | `docs/development/closeouts/S3/s3_7_dynamic_rooms.md` |

This specification freezes the complete `S3.7` material-provenance,
acoustic-state refresh, cross-output consistency, fixture, tolerance, and
evidence contract prospectively, before implementation or acceptance
evidence. It is documentation only and makes no implementation or passing
claim.

The acceptance sentence “caches never return stale acoustics” has a narrow,
code-accurate meaning at the entry revision. There is no cached RIR, rendered
waveform, or occlusion result. The room backend constructs a new shoebox and
calls `compute_rir()` on every `simulate()` call (once per segment in the
already-passed piecewise path), and the live Isaac layer calls
`compute_scene_occlusion()` on every capture. Recompute-always is therefore
the required compliant baseline. `S3.7` does not add acoustic-result
memoization.

## 1. Problem definition and responsibility boundary

`S3.7` must prove that one acoustic state produces one mutually consistent
set of waveform, RMS, occlusion metadata, diagnostics, and exported WAV
observables, and that changing an acoustically relevant part of the state
cannot replay the preceding state's observables.

The implementation deliverable is limited to (a) proving that consistency
under the frozen state changes, (b) extending stage-cache reason tracking for
acoustically relevant discovery/refresh state, and (c) adding and wiring the
pure material table. It is not an acoustic-result-cache project.

Responsibilities are frozen as follows:

1. the new pure material module owns immutable octave-band coefficients,
   evidence tags, citations, exact id resolution, and fail-closed validation;
2. `RoomAcousticsSpec` and the room backend own selection and application of
   room absorption from that table;
3. the Isaac occlusion resolver owns selection of transmission loss from the
   same table, explicit USD override precedence, and per-capture raycasts;
4. `StageAudioCache` owns discovery-state invalidation and a reason record of
   acoustic refresh reasons, but never caches an RIR or occlusion result;
5. the stage/room integration owns re-resolving an anchored room after a
   relevant notice and must not reuse an invalid anchor-derived spec;
6. the room backend continues to apply per-source/per-microphone occlusion to
   the premix before source summation, RMS, estimator diagnostics, and export;
   and
7. the evidence gate owns planted state mutations that would fail if an old
   room, material, raycast result, waveform, RMS value, diagnostic, or WAV
   were reused.

`SourceOcclusion` remains a read-only pure-core consumption contract. `S3.7`
does not add stage queries, material lookup, or mutable caching to that type.
It may add provenance to frame diagnostics, not to the frozen record merely
to make a test convenient.

The inherited `S3.2` contract remains authoritative for per-segment midpoint
geometry, exact segment accounting, RIR overlap-add, and session gap
preservation. The inherited `S3.6` contract remains authoritative for
per-pair-before-sum directivity, signed response, deterministic ordering, and
the `per_pair_direct_path` limitation. Material and occlusion processing does
not reinterpret either predecessor.

## 2. Entry-revision reality and compliant baseline

### 2.1 Discovery cache versus acoustic results

At `7e29d4f`, `StageAudioCache` caches audio discovery decisions and prim
handles. On a steady-state tick it re-resolves source and array poses and
audio attributes without `stage.Traverse()`. It deliberately ignores
pose-only `xformOp:*` notices. Structural resyncs and discovery-relevant
`ias:*`/audio-alias changes dirty discovery and record reasons; explicit
`rediscover()` and `rediscover_each_update` remain supported.

That cache is not an acoustic-result cache. A cache hit can coexist with a
fresh source/array pose, a fresh PhysX raycast, a newly built shoebox, a fresh
RIR, and a new waveform. A `StageAudioCache` hit is never evidence that a
room waveform or occlusion result was reused.

### 2.2 Recompute-always rules

The following rules are mandatory and exact:

- every successful `RoomAcousticsBackend.simulate()` with at least one active
  source and one motion segment returns one constructed room and calls
  `room.compute_rir()` exactly once;
- an already-supported active-source `P>1` piecewise call returns and computes
  exactly one room per segment, as required by `S3.2`;
- every live capture with occlusion enabled attempts exactly one whole-scene
  `compute_scene_occlusion()` call after current source and array poses have
  been resolved;
- each such call casts the current source-to-current-microphone rays through
  the current PhysX state and resolves hit material state during that call;
  and
- no path may retain and replay an earlier RIR, premix, mixture, band-filtered
  waveform, `SourceOcclusion`, or exported WAV payload.

An unavailable PhysX or room dependency remains an explicit blocked or
unavailable state under the existing capability policy. Dependency absence
does not permit a stale result, a zero-filled substitute described as
computed, or a passing acceptance row.

### 2.3 Future memoization boundary

RIR or acoustic-result memoization is outside `S3.7`. Any later proposal must
be separately designed and must key on the complete canonical simulation
input tuple, at minimum:

```text
(
  backend id and every propagation/effects option that changes samples,
  dependency implementation/version and speed of sound,
  sample rate and exact AudioTimeWindow/sample lattice,
  resolved room geometry, anchor, boundary policy, and material coefficients,
  ordered active source ids, poses, velocities, schedules, gains, assets/signals,
  ordered array/microphone poses, layouts, orientations, and responses,
  complete ordered SourceOcclusion records after caps and material resolution,
  directivity/channel/noise/electronics configuration and deterministic seeds,
  complete WindowMotionPlan when P > 1,
)
```

Omitting any sample-affecting member is non-compliant. The tuple excludes
output paths and diagnostic counters that do not change samples. Designing or
implementing that future key/cache is not an `S3.7` deliverable.

## 3. Pure material table and evidence contract

### 3.1 Module, grid, and immutable records

Implementation adds the import-safe pure module
`src/isaac_audio_sensors/core/acoustics/materials.py`. It may depend on the
standard library and pure core validation helpers only. It must not import
NumPy, pyroomacoustics, Isaac, Omniverse, `pxr`, a backend, or an effects
stage. Importing the base package must not require the optional room pack.

The shared canonical octave-band centers are exactly:

```text
(125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0) Hz
```

They are identical to `OCCLUSION_BAND_CENTERS_HZ`. Every coefficient vector
is an immutable six-float tuple aligned to that order. Absorption values are
finite probabilities in `[0, 1]`; transmission values are finite,
non-negative dB losses. Ids are nonempty, case-sensitive canonical strings.
Legacy aliases are resolved case-insensitively only through the explicit
alias map in §3.4; substring matching is not canonical id resolution.

The conceptual record is:

```text
MaterialEntry(
    material_id: str,
    description: str,
    absorption: tuple[float, ...] | None,
    transmission_db: tuple[float, ...] | None,
    evidence: Literal["measured", "nominal"],
    citation: str | None,
)
```

`evidence="measured"` requires a nonempty citation. `evidence="nominal"`
requires `citation is None`. Every table entry is evidence-homogeneous: all
coefficient families present on that entry share its tag. The verified source
supplies measured absorption but no transmission data, so its measured entries
leave transmission absent. The separate compatibility entries are nominal;
their similarly named transmission values are never merged into a measured
entry.

An absent family is not an inferred zero, a flat copy of the other family,
or permission to use a similarly named material. Resolution of a requested
but absent family fails closed before room construction, raycast output,
frame publication, or export.

If implementation later supplies a plausible substitute for missing measured
data, it must live on a `nominal` entry until an exact measured source and
citation are frozen. Absence stays explicit in this table; it is never
silently promoted or hidden by the nominal compatibility rows.

### 3.2 Verified pyroomacoustics source decision

The design probe used installed pyroomacoustics `0.10.1` from the recorded
Isaac runtime. `pyroomacoustics.parameters` loads
`pyroomacoustics/data/materials.json`, whose SHA-256 at design time is
`1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0`.
The database top-level keys are exactly `absorption`, `center_freqs`, and
`scattering`; it has no transmission table. The module attributes all listed
material values to this citation, frozen verbatim as the repository citation
string:

```text
Michael Vorländer, Auralization: Fundamentals of Acoustics, Modelling,
Simulation, Algorithms, and Acoustic Virtual Reality, Springer, 1st edition,
2008; coefficients distributed by pyroomacoustics 0.10.1.
```

The pyroomacoustics records expose centers through 8 kHz. `S3.7` retains the
exact first six coefficients, 125 Hz through 4 kHz, to share the existing
six-band occlusion grid. The source 8 kHz coefficient is recorded below for
audit but is not applied or silently folded into 4 kHz.

| Frozen material id | pyroomacoustics key and description | Absorption at 125, 250, 500, 1k, 2k, 4k Hz | Source 8k value | Transmission | Evidence |
| --- | --- | --- | --- | --- | --- |
| `pra.rough_concrete` | `rough_concrete`; Rough concrete | `(0.02, 0.03, 0.03, 0.03, 0.04, 0.07)` | `0.07` | absent | absorption `measured`, citation above |
| `pra.brickwork` | `brickwork`; Walls, rendered brickwork | `(0.01, 0.02, 0.02, 0.03, 0.03, 0.04)` | `0.04` | absent | absorption `measured`, citation above |
| `pra.plasterboard` | `plasterboard`; 2 × 13 mm plasterboard on steel frame, 50 mm mineral wool in cavity, surface painted | `(0.15, 0.10, 0.06, 0.04, 0.04, 0.05)` | `0.05` | absent | absorption `measured`, citation above |
| `pra.glass_3mm` | `glass_3mm`; Single pane of glass, 3 mm | `(0.08, 0.04, 0.03, 0.03, 0.02, 0.02)` | `0.02` | absent | absorption `measured`, citation above |
| `pra.wood_1_6cm` | `wood_1.6cm`; Wood, 1.6 cm thick, on 4 cm wooden planks | `(0.18, 0.12, 0.10, 0.09, 0.08, 0.07)` | `0.07` | absent | absorption `measured`, citation above |
| `pra.carpet_cotton` | `carpet_cotton`; Cotton carpet | `(0.07, 0.31, 0.49, 0.81, 0.66, 0.54)` | `0.48` | absent | absorption `measured`, citation above |
| `pra.curtains_cotton_0_5` | `curtains_cotton_0.5`; Cotton curtains (0.5 kg/m²), draped to approximately 3/4 area, approximately 130 mm from wall | `(0.30, 0.45, 0.65, 0.56, 0.59, 0.71)` | `0.71` | absent | absorption `measured`, citation above |

These seven entries are the complete measured seed set for `S3.7`. Adding a
different pyroomacoustics entry, changing a coefficient, or taking an 8 kHz
value into the shared grid requires a dated design amendment and affected
evidence regeneration.

### 3.3 Nominal compatibility entries

The entry-revision `DEFAULT_MATERIAL_TRANSMISSION_DB` values are retained
exactly but moved/resolved through the pure table. Their absorption columns
retain the corresponding entry-revision broadband semantic defaults repeated
over all six bands. Both families are tagged `nominal`; no citation is
allowed.

| Frozen material id | Absorption at 125, 250, 500, 1k, 2k, 4k Hz | Transmission dB at the same centers | Evidence |
| --- | --- | --- | --- |
| `nominal.concrete` | `(0.05, 0.05, 0.05, 0.05, 0.05, 0.05)` | `(33.0, 36.0, 40.0, 44.0, 50.0, 55.0)` | both `nominal`; no citation |
| `nominal.brick` | `(0.04, 0.04, 0.04, 0.04, 0.04, 0.04)` | `(30.0, 33.0, 37.0, 42.0, 48.0, 52.0)` | both `nominal`; no citation |
| `nominal.metal` | `(0.05, 0.05, 0.05, 0.05, 0.05, 0.05)` | `(20.0, 25.0, 30.0, 35.0, 39.0, 42.0)` | both `nominal`; no citation |
| `nominal.drywall` | `(0.10, 0.10, 0.10, 0.10, 0.10, 0.10)` | `(15.0, 22.0, 29.0, 34.0, 39.0, 44.0)` | both `nominal`; no citation |
| `nominal.plaster` | `(0.10, 0.10, 0.10, 0.10, 0.10, 0.10)` | `(15.0, 22.0, 29.0, 34.0, 39.0, 44.0)` | both `nominal`; no citation |
| `nominal.glass` | `(0.05, 0.05, 0.05, 0.05, 0.05, 0.05)` | `(18.0, 22.0, 26.0, 30.0, 33.0, 36.0)` | both `nominal`; no citation |
| `nominal.wood` | `(0.10, 0.10, 0.10, 0.10, 0.10, 0.10)` | `(15.0, 19.0, 23.0, 26.0, 29.0, 32.0)` | both `nominal`; no citation |
| `nominal.fabric` | `(0.40, 0.40, 0.40, 0.40, 0.40, 0.40)` | `(3.0, 4.0, 6.0, 9.0, 12.0, 15.0)` | both `nominal`; no citation |
| `nominal.curtain` | `(0.40, 0.40, 0.40, 0.40, 0.40, 0.40)` | `(3.0, 4.0, 6.0, 9.0, 12.0, 15.0)` | both `nominal`; no citation |

The configurable flat `occlusion_max_attenuation_db` fallback remains a
nominal untagged-collider fallback, not a material entry and not measured
truth. Its diagnostic evidence is `nominal`. It cannot satisfy a caller that
authored an unknown material id.

### 3.4 Exact ids, aliases, and resolution precedence

The only legacy aliases are frozen as:

```text
concrete -> nominal.concrete    brick   -> nominal.brick
metal    -> nominal.metal       drywall -> nominal.drywall
plaster  -> nominal.plaster     glass   -> nominal.glass
wood     -> nominal.wood        fabric  -> nominal.fabric
curtain  -> nominal.curtain
```

For room absorption, `RoomAcousticsSpec.absorption` expands prospectively to
`float | dict[str, float] | str`. A string is an exact material id or legacy
alias. It resolves in pure code before `_build_shoebox_room`; the backend
passes pyroomacoustics an explicit `{description, coeffs, center_freqs}`
absorption record and never asks a runtime-installed database to reinterpret
the id. Existing scalar and dictionary behavior stays supported and is
diagnosed as `nominal` unless a future explicit measured-input contract with
a citation is separately added.

The exact new USD table-reference attribute is
`ias:acoustic_material_id`. For an anchored room, resolution precedence is:
explicit numeric `ias:absorption` (nominal), exact
`ias:acoustic_material_id`, exact id/legacy alias in `ias:material`, existing
USD semantic-label alias lookup, then the configured room value. An unknown
explicit id fails closed at its step and never falls through.

For Isaac transmission, precedence is:

1. explicit `ias:transmission_loss_db_bands` with exactly six finite,
   non-negative values;
2. explicit finite, non-negative `ias:transmission_loss_db`, expanded flat to
   six bands for the shared downstream representation;
3. an exact `ias:acoustic_material_id`, followed by an exact id/legacy alias
   in `ias:material`, on the hit/bound material, resolved from the pure table;
4. the existing case-insensitive legacy token match, resolved only through
   the alias map above; then
5. the configured flat nominal fallback when no material id was authored and
   no legacy token matched.

Explicit USD numeric overrides are `nominal` because they have no measurement
citation in the current contract. An explicit unknown material id or a known
id without transmission values fails closed at step 3; it does not continue
to token matching or the flat fallback. Bound-material lookup remains
best-effort only when no exact acoustic id is authored.

Material table mappings and coefficient tuples are immutable. Duplicate ids,
duplicate aliases, an alias cycle, unknown alias target, wrong band count,
non-finite value, out-of-range absorption, negative transmission, measured
data without a citation, or nominal data with a citation fails at module
self-validation/import in focused tests and before any runtime output.

### 3.5 Material diagnostics and no-promotion rule

When a room material or occlusion material is applied, diagnostics identify
the exact id, coefficient family, evidence tag, and citation only when
measured. The conceptual records are:

```text
material_evidence["room"] = {
  "material_id": "pra.rough_concrete",
  "coefficient": "absorption",
  "evidence": "measured",
  "citation": "...frozen citation...",
}

material_evidence["occluder:/World/Wall"] = {
  "material_id": "nominal.concrete",
  "coefficient": "transmission_db",
  "evidence": "nominal",
}
```

Keys are sorted lexicographically after the distinguished `room` key. A
multi-hit path has one record per distinct hit prim. Explicit USD overrides
use material ids `usd_attribute:<prim-path>` and evidence `nominal`; the flat
fallback uses `configured_fallback:<value-db>` and evidence `nominal`.
Existing scalar and dictionary room absorption use diagnostic ids
`inline_room_absorption:scalar` and `inline_room_absorption:mapping`,
respectively, with evidence `nominal`; their exact scalar or sorted mapping is
also included in the room hash.

The following promotion paths are forbidden:

- a measured absorption citation does not make a nominal transmission vector
  measured;
- a shared colloquial label does not join two independent physical samples;
- an exact pyroomacoustics absorption record does not imply transmission;
- interpolation, averaging, flat expansion, or unit conversion does not
  create measured provenance; and
- missing citation or missing coefficient data is never repaired from a
  plausible-looking preset.

## 4. Acoustic-state refresh and reason taxonomy

### 4.1 Reason records and actions

`StageAudioCache` gains a reason-tracked acoustic refresh surface while
preserving its existing discovery counters and reasons. Each observed reason
has one of two actions:

- `rediscover`: set the existing dirty flag; on the next capture perform one
  full discovery and refresh the dependent room/material discovery state;
- `recompute_only`: keep audio discovery cached; the already-mandatory live
  raycast and/or room simulation uses current state.

The new frozen reasons are:

| Exact reason | Trigger | Action | Required effect |
| --- | --- | --- | --- |
| `room_geometry_changed` | Dimensions/bounds attribute, geometry resync, or `xformOp:*` on the configured room anchor or an ancestor that changes its world-aligned bounds/origin | `rediscover` | Recompute the anchor bounds and build a new `RoomAcousticsSpec`; never reuse the old origin/dimensions |
| `material_changed` | `ias:acoustic_material_id`, `ias:material`, bound-material relationship, `ias:absorption`, `ias:transmission_loss_db`, or `ias:transmission_loss_db_bands` changes on a relevant room/occluder | `rediscover` | Re-resolve coefficients and evidence before the next backend/raycast output |
| `occluder_moved` | A non-source/non-array pose notice is pending and the next fresh raycast changes at least one source-array pair's canonical occlusion result | `recompute_only` | Record the causal refresh; use the new raycast record without a needless audio discovery traversal |

The exact state surfaces are:

```text
StageAudioCache.invalidation_reasons       # existing cumulative list
StageAudioCache.acoustic_refresh_reasons   # new cumulative list
```

`room_geometry_changed` and `material_changed` are appended to both lists and
dirty discovery through `invalidate()`. `occluder_moved` is appended only to
`acoustic_refresh_reasons` through a non-dirty
`record_acoustic_refresh()` seam after the changed raycast is known.
`_cache_diagnostics()` adds the cumulative tuple under exact key
`acoustic_refresh_reasons`; it does not relabel the refresh-only event as a
discovery invalidation. The current frame's deduplicated subset is separately
reported by `acoustics_state.refresh_reasons`.

Existing reasons such as `usd_objects_changed_resync`,
`usd_info_only_discovery_attr`, `explicit_rediscover`, missing prim, cached-tick
failure, and policy rediscovery remain valid. A single USD notice can record
more than one new reason, but each exact reason is deduplicated within one
capture and emitted in table order. Cumulative counters may exist internally;
per-frame reason lists contain only reasons consumed by that frame so repeated
equivalent pure frames remain deterministic.

### 4.2 Targeted pose-only handling

The entry rule “pose-only changes do not invalidate discovery” remains true
for sources and arrays. Their current poses and child microphone world
positions are already re-resolved on every cached tick. A source or array move
therefore causes no full stage traversal merely to make acoustics fresh; the
fresh pose flows into the per-capture raycasts and recompute-always room call.

Room-anchor pose changes are a targeted exception because the anchor-derived
`RoomAcousticsSpec` is discovery state held outside the room backend. The
listener compares notice paths against the configured anchor path and its
ancestors, records `room_geometry_changed`, and dirties discovery. After
rediscovery, the stage/room owner must call `world_aligned_bbox()` and
`room_spec_from_bounds()` again before simulation. Refresh failure is fatal;
the previous room spec is not retained as fallback.

Occluder pose changes do not require discovery invalidation for acoustic
freshness. The actual freshness mechanism is the raycast that already runs on
every capture. To assign the reason honestly without trying to predict PhysX
from a USD notice, the listener retains bounded pending non-audio pose paths;
after the next raycast, the extension compares the canonical previous/current
occlusion record for every source-array pair. It emits `occluder_moved` only
for changed pairs and then clears the pending paths. A clear-to-blocked move is
observable even though the occluder did not occur in the preceding hit list.
The pending path buffer is cleared on reset, stage replacement, and close.

The compared canonical pair value is the ordered serialization of
`array_id`, `source_id`, microphone-order blocked flags, factor, record and
per-mic broadband losses, band centers and per-mic band rows, ordered hit
paths/per-mic hit paths, sorted hit-material mapping, and model id. Diagnostic
formatting and unrelated stage state are excluded. Thus a material/loss change
is observable even when the blocked flags stay the same.

Structural creation/deletion/resync of an occluder continues to record
`usd_objects_changed_resync`; if its fresh raycast result changes, diagnostics
also identify the changed pair. `occluder_moved` is reserved for pose-only
motion and is not fabricated for unchanged raycast output.

### 4.3 Room and material refresh details

The configured room anchor path becomes watched acoustic discovery state. A
full cached discovery stores only enough immutable provenance to rebuild it;
the authoritative room for a capture is the successfully refreshed spec, not
the constructor-time `self.room` after an anchor notice. The room state
includes:

```text
(
  room_id, dimensions_m, origin_m, out_of_bounds, anchor_prim_path,
  resolved six-band absorption values, material id/evidence/citation,
  max_order, air_absorption, ray_tracing,
)
```

`room_state_hash` is lowercase SHA-256 of UTF-8 canonical JSON for that tuple:
JSON arrays preserve tuple order, object keys are lexicographically sorted,
separators are `(',', ':')`, `ensure_ascii=True`, and non-finite numbers are
rejected. The material id and evidence are part of the hash; changing an id
to a numerically identical but differently evidenced entry changes the hash.

Material resolvers may cache the immutable module table itself. They must not
cache a prim's chosen material id or explicit attribute result across a
`material_changed` notice. Changing only the Python source table requires a
new package/revision and process restart; runtime mutation of the module table
is unsupported.

### 4.4 Source, array, room, and lifecycle rules

| Event | Required behavior |
| --- | --- |
| Source pose changes | Cached discovery may hit; re-resolve pose/motion, raycast current source-to-mic segments, and recompute room output |
| Array or microphone-child pose changes | Cached discovery may hit; re-resolve array/mic world poses, raycast current segments, and recompute room output |
| Room anchor translates/rotates/scales | Record `room_geometry_changed`, refresh world-aligned bounds/spec, hash new room, then recompute |
| Room dimension/bounds attribute changes | Same as anchor geometry change; apply existing out-of-bounds policy to the refreshed room |
| Room/occluder material reference or numeric acoustic attribute changes | Record `material_changed`, re-resolve values/evidence, then recompute |
| Occluder pose changes across a pair | Fresh raycast is authoritative; record `occluder_moved` on changed pair without requiring a discovery traversal |
| Anchor prim is deleted or invalid | Fail closed before backend call and frame/export; name the missing anchor and `room_geometry_changed` context |
| Sensor reset or timeline reset | Clear previous occlusion comparison state, pending pose paths, per-frame reasons, and recompute counters |
| Stage replacement/close | Revoke listener and clear all discovery, room, material-resolution, pending-pose, and comparison state |

## 5. Additive acoustics-state diagnostics

Only when room material resolution, room acoustics, or live occlusion is
active, each emitted frame adds:

```text
frame.diagnostics["acoustics_state"] = {
  "room_state_hash": <64 lowercase hex chars>,       # room active only
  "material_evidence": {<application>: <record>, ...},
  "occlusion_recompute_count": 1,                   # successful live call
  "refresh_reasons": [<current-frame reasons>],
  "changed_occlusion_pairs": ["<array-id>:<source-id>", ...],
}
```

Absent subfeatures omit their fields; they do not emit `null`, empty hashes,
or fake counts. `material_evidence` is present only when at least one material
or numeric/fallback coefficient was applied. `occlusion_recompute_count` is a
per-frame count, not a lifetime count: it is exactly `1` after one successful
whole-scene live recomputation and `0` with the existing explicit unavailable
status when the attempt failed. This choice keeps identical input frames
diagnostically identical. Piecewise room `compute_rir()` counts remain
observable in focused gate evidence rather than being mislabeled as
occlusion recomputes.

`refresh_reasons` and `changed_occlusion_pairs` are deterministically ordered.
The latter uses source order within array order and is emitted only when a
previous comparable live capture exists. Existing
`frame.diagnostics["stage_snapshot"]["discovery_cache"]` counters/reasons and
per-detection `diagnostics["occlusion"]` remain present and must reconcile
with the new namespace. The new namespace does not replace them.

When all relevant features are off—no room material reference, no room
backend, and occlusion disabled—no `acoustics_state` key is emitted and no new
hash, reason bookkeeping, or material lookup changes the entry-revision frame
or waveform bytes.

## 6. Frozen consistency criteria and tolerances

All errors are maximum absolute errors, never means or percentiles. One band,
microphone, source-array pair, frame, state mutation, decoded sample, reason,
or evidence tag outside its bound fails `S3.7`.

### 6.1 Acceptance table

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Band attenuation versus metadata | At every exact center in `(125, 250, 500, 1000, 2000, 4000) Hz`, every microphone with nonzero clear energy satisfies `abs(A_observed_db - A_metadata_db) <= 0.05 dB`; unblocked/zero-loss rows use the same bound around `0 dB` | `_apply_band_attenuation` multiplies each rFFT bin by the exact zero-phase interpolated gain; a design probe on a 48 kHz/48,000-sample six-tone fixture had maximum error `7.105427357601002e-15 dB`; `0.05 dB` gives platform/FFT headroom without allowing a material-sized error |
| Broadband attenuation versus metadata | For flat fixtures, `abs(20*log10(rms_clear/rms_changed) - configured_db) <= 1e-6 dB` per affected microphone | The waveform is multiplied by `10**(-dB/20)` before all RMS/export observables; this is float64 arithmetic headroom |
| RMS versus in-memory waveform | `abs(frame.aggregate_per_mic_rms[m] - sqrt(mean(Y_m**2))) <= 1e-12` for every microphone; in each single-source fixture the detection RMS obeys the same bound against its premix channel | Existing S3 electronics consistency style; RMS is computed from the exact post-occlusion arrays |
| Occlusion metadata exactness | `per_mic_blocked`, `occlusion_factor`, hit paths/material ids, band centers, per-mic broadband/band rows, cap result, model id, and evidence tags equal the configured/synthetic expected values with exact Python equality | These values are copied or computed from deterministic integer counts/ordered sums; tolerance would hide record drift |
| FLOAT WAV versus memory | Decoded channel order/rate/count are exact and every decoded sample is exactly equal to `np.asarray(in_memory_mixture.T, dtype=np.float32)`; WAV subtype is exactly `FLOAT` | The writer deliberately stores IEEE float32 WAV samples; comparison is against the format conversion, not impossible float64 byte identity |
| Repeated-state determinism | Two fresh runs of an identical scene, window, dependency/version, writer config, and seed have byte-identical float64 mixture `.tobytes()`, frame JSON, and raw WAV bytes; all SHA-256 values match | The backend, source ordering, zero-phase filter, diagnostics, and writer are deterministic under pinned versions |
| Planted occluder/material mutation | Same window and signal, changed occlusion/material state: at least one affected waveform/WAV byte and RMS value differs; metadata equals the new state; `changed_occlusion_pairs` names the pair; `occluder_moved` or `material_changed` is recorded as applicable | A direct stale-result detector; merely incrementing a counter cannot pass |
| Planted room mutation | Same window and signal, changed anchor origin/dimensions or absorption: `room_state_hash` differs, `compute_rir()` is called for the new state, at least one RIR/premix/waveform/RMS value differs, and `room_geometry_changed` or `material_changed` is exact | Proves both discovery-state refresh and recompute-always propagation |
| Source/array motion freshness | Current snapshot pose equals authored pose exactly; current ray endpoints and room positions use it; one or more geometry-dependent outputs differ while full discovery need not increase | Pose resolution already runs each cached tick; no invented pose-cache invalidation is required |
| Recompute counts | With at least one active source, `P=1`: exactly one successfully returned room/`compute_rir()` per `simulate()` and one whole-scene occlusion recomputation per successful live capture; active-source `P>1`: exactly `P` returned rooms/RIR calls, preserving S3.2 | Direct call-spy proof of the actual no-result-cache baseline; compatibility constructor retries are attempts, not cached acoustic results |
| Material evidence | Every applied coefficient family reports its exact frozen tag; every measured record reports the frozen citation; nominal/missing data is never reported measured | Governing S0 honesty requirement |
| Hard off-state | L0/L1 with no room/material resolution and occlusion disabled: pinned `7e29d4f` frame JSON is exact and `acoustics_state` is absent. Existing scalar-absorption room fixture with no material id: mixture/WAV and all pre-existing frame fields are exact; only the required additive `acoustics_state` room record may differ | Separates a true feature-off path from an active room path that must expose the new state diagnostic |

For band measurement, let `X_m[k]` and `Y_m[k]` be the rFFT bins of the clear
and changed in-memory microphone waveforms. The one-second fixture makes every
center an exact integer bin (`k=f` at 48 kHz and `N=48,000`). For each bin
whose clear magnitude exceeds `1e-10`, measure:

```text
A_observed_db = -20 * log10(abs(Y_m[k]) / abs(X_m[k]))
```

No Welch window, neighboring-bin maximum, octave integration, smoothing, or
post-hoc fitted offset may replace this known-answer measurement. A separate
real-pyroomacoustics row may report band-integrated behavior, but it cannot
weaken the exact insertion-path criterion.

### 6.2 Exact metadata arithmetic

Per-microphone broadband loss is the capped sum of non-negative per-distinct-
prim hit losses in ray order. Per-band loss is the independently capped sum at
each band. The record-level `attenuation_db` is the ordered arithmetic mean of
the per-microphone broadband values, and `occlusion_factor` is blocked-ray
count divided by microphone count. Tests construct expected floats through
the same explicitly stated arithmetic order and then require exact equality;
they do not use a rounded display string.

An octave-band record always drives the band filter, even if its arithmetic
mean equals a broadband preset. Broadband multiplication is used only when no
valid band row exists for that microphone. A malformed band row fails closed;
it never falls back to broadband.

## 7. Frozen fixtures

### 7.1 Common pure room/backend fixture

All pure cross-output fixtures use:

```text
sample rate R = 48,000 Hz
window [0.0, 1.0) s, N = 48,000 samples, frame index 0
room id = "s3_7_room"
room origin = (-1.0, -3.0, 0.0) m
room dimensions = (6.0, 6.0, 3.0) m
room absorption material = "pra.rough_concrete"
room max_order = 1; air_absorption = false; ray_tracing = false
source id = "tone", position = (4.0, 0.0, 1.0) m, omni, gain 0 dB
array id = "rig_front", position = (0.0, 0.0, 1.0) m, identity orientation
microphones, in order:
  front ( 0.08,  0.00, 0.00) m
  right ( 0.00,  0.08, 0.00) m
  rear  (-0.08,  0.00, 0.00) m
  left  ( 0.00, -0.08, 0.00) m
```

The deterministic pre-occlusion premix channel is the float64 six-tone
known-answer signal

```text
x[n] = sum_f 0.1*sin(2*pi*f*n/48000),
f in (125, 250, 500, 1000, 2000, 4000), n=0..47999.
```

The focused insertion test supplies this premix through the room backend's
existing simulation seam and spies on room construction/RIR calls. A separate
dependency-capable test runs the same scene through real pyroomacoustics
`0.10.1`; availability alone is not a pass. Directivity, channel response,
noise, electronics, Doppler, and piecewise motion are disabled for the
isolated `S3.7` fixture. Their passed predecessor tests are rerun as regressions
rather than mixed into the known-answer attenuation measurement.

### 7.2 Synthetic `SourceOcclusion` cases

All records use model id `raycast_transmission_v1`, the six frozen band
centers, deterministic microphone order, and pair `rig_front:tone`.

| Fixture | Exact synthetic record and expected effect |
| --- | --- |
| Clear | All four `per_mic_blocked=false`; factor `0.0`; all broadband and band rows zero; empty hit paths/materials; every measured drop `0 +/- 0.05 dB`, `occluded=false` |
| Blocked concrete | All four blocked; factor `1.0`; every band row equals `nominal.concrete` transmission; every broadband row and record mean equal `43.0 dB`; hit `/World/Wall`; material `nominal.concrete`; all channels meet the six band targets, `occluded=true` |
| Partial wood | Only `right` blocked; factor `0.25`; `right` band row `(15,19,23,26,29,32) dB`, other rows zero; per-mic broadband `(front=0,right=24,rear=0,left=0) dB`; record mean `6.0 dB`; `occluded=false` |
| Material swap | Geometry and blocked map fixed at all four blocked; run once with `nominal.wood`, then `nominal.glass`; exact new band rows/means are required and the waveform, RMS, WAV, material evidence, and state trace must change |

The blocked concrete fixture deliberately uses the arithmetic mean `43.0 dB`
only for broadband metadata. Its waveform follows the six distinct band
values, not a flat 43 dB multiplier.

### 7.3 Moving-occluder sequence

The pure and live sequences share one exact geometry. A cube wall has center
`x=2.0 m`, `z=1.0 m`, scale `(0.2, 0.11, 3.0)`, and translates in `y` across
the source-array rays over exactly five retained frames:

```text
y center (m):       +0.25, +0.08,  0.00, -0.08, -0.25
blocked mic ids:        (), (right), (front,right,rear,left), (left), ()
occlusion factor:      0.0,   0.25,  1.0,  0.25, 0.0
```

At the wall center plane, the source-to-microphone rays have `y=0.0` for
front/rear, `+0.04` for right, and `-0.04` for left. The wall half-width is
`0.055 m`, giving nonzero margin around all declared intersections. The wall
uses an explicit flat `12.0 dB` transmission attribute in the live fixture,
tagged nominal. The pure fixture supplies equivalent synthetic records.

For the pure planted-staleness sequence, every run uses the identical scene
window/signal; only the wall state changes. Expected affected-channel drops
are exactly `12.0 dB` within the broadband bound. States 0 and 4 have
byte-identical in-memory waveform and raw WAV plus identical occlusion
metadata; their full frame diagnostics intentionally differ because state 4
records the causal transition. States 1 and 3 differ in which channel is
attenuated; state 2 attenuates all channels. Every transition after the
initial state records fresh output, and each pose-only transition whose pair
record changes records `occluder_moved`. Full-frame byte identity is measured
by the separate two-fresh-run fixture in §6.1, where reason history is reset
identically.

### 7.4 Dynamic room, material, source, and array mutations

Starting from the common fixture, apply one mutation at a time and always
compare against a fresh identical baseline:

| Mutation | Exact change | Required reason/result |
| --- | --- | --- |
| Anchor translation | origin changes from `(-1.0,-3.0,0.0)` to `(-0.75,-3.0,0.0)` with dimensions unchanged | `room_geometry_changed`; new hash/RIR/output |
| Room dimension | dimensions change from `(6.0,6.0,3.0)` to `(7.0,6.0,3.0)` with origin unchanged | `room_geometry_changed`; new hash/RIR/output |
| Measured room material | absorption changes from `pra.rough_concrete` to `pra.carpet_cotton` | `material_changed`; measured citations exact; new hash/RIR/output |
| Source motion | source changes from `(4.0,0.0,1.0)` to `(3.5,0.0,1.0)` m | no full-discovery requirement; current pose/ray/room position exact; output changes |
| Array motion | array changes from `(0.0,0.0,1.0)` to `(0.0,0.25,1.0)` m | no full-discovery requirement; current array/mic poses/rays exact; output changes |

Real-pyroomacoustics dynamic-room/material rows run with the recorded
dependency-capable interpreter. The fake room used by pure call-count tests
must make its deterministic RIR/premix a function of every supplied room
dimension, origin-relative source/mic position, and absorption vector so a
naive stale reuse fails. The real row, not the fake alone, supports the
propagation claim.

### 7.5 Stage-cache fixtures

Fake-`pxr`/duck-stage tests retain the existing source and quad-array prims and
add `/World/Room` plus `/World/Wall`. They inject notice paths directly and
assert:

- source/array `xformOp:*` changes keep discovery cached while their current
  poses change;
- `/World/Room.xformOp:translate`, room bounds/size changes, and room geometry
  resync record `room_geometry_changed` and cause exactly one next-capture full
  discovery;
- room and wall material/reference/absorption/transmission attributes record
  `material_changed` and cause exactly one next-capture full discovery;
- `/World/Wall.xformOp:translate` alone does not dirty audio discovery; a
  changed fresh synthetic raycast records `occluder_moved` and a same-result
  move does not;
- simultaneous room/material notices record both exact reasons in frozen
  order but perform one rediscovery; and
- removal of `/World/Room` rejects before backend/writer calls and never
  exposes the preceding room spec.

## 8. Mandatory edge and failure cases

- A collider touching only the source or microphone segment endpoint, within
  the existing `endpoint_epsilon_m` exclusion, is clear. If its geometry
  extends beyond that exclusion into the open segment, the interior hit is
  blocking. Source/array prims and their descendants remain excluded.
- A zero-length ray, or any ray of total length
  `<= 2*endpoint_epsilon_m`, is clear and performs no PhysX cast. This is the
  entry behavior and must not divide by zero or fabricate an occluder.
- An explicitly authored unknown material id fails closed and names the id,
  prim/application, requested coefficient family, and known-id surface. A
  known `pra.*` id requested for transmission fails as missing transmission,
  not as unknown and not via nominal fallback.
- Any coefficient vector whose band count is not exactly six fails closed.
  In particular, an authored 7-value pyroomacoustics row or malformed USD band
  attribute is not truncated at runtime; only the seven design-frozen
  measured rows have an audited 8 kHz-to-six-band projection.
- Non-finite or negative transmission, absorption outside `[0,1]`, empty id,
  invalid evidence tag, missing measured citation, and nominal citation all
  fail before partial output or state mutation.
- If the anchor prim is deleted, becomes invalid, has a degenerate world
  bound, or cannot be resolved at the requested time code, capture fails
  before room construction, RIR, frame, JSONL, screenshot, or WAV. The old
  room is never used.
- A room dimension change between frames can put a source or microphone out
  of bounds. The refreshed room applies the existing exact policy: `error`
  rejects with entity/world/bounds/anchor context; `clamp` moves it by the
  existing `ROOM_CLAMP_MARGIN_M` and reports it. Neither policy uses the old
  dimensions.
- Simultaneous distinct occluders accumulate loss once per distinct prim in
  ray order, cap broadband and each band independently at the configured
  `60.0 dB` default, preserve all hit paths/material evidence, and do not count
  entry/exit faces of one thick collider twice.
- Two overlapping occluders with the same nominal material therefore produce
  the exact component-wise capped sum; moving one away removes only its
  contribution on the next capture.
- A material and room mutation in one notice records both reasons, resolves
  both new states, and publishes either one wholly new frame or no frame.
- A material notice between raycast and publication cannot publish mixed old
  metadata/new waveform state. Existing capture atomicity must retry from one
  coherent state or fail before output.
- No active source still permits room diagnostics/silence under existing
  behavior, but it cannot be used to pass attenuation or mutation-difference
  rows because the observables have no acoustic energy.
- Attenuation at the cap, exact occlusion flag threshold `0.5`, a one-mic
  partial state, all-mic blocked state, duplicate hit path, and empty hit set
  are all retained boundary cases.

## 9. Verification map and evidence

Implementation is expected to add focused tests in
`tests/test_acoustic_materials.py` and
`tests/test_acoustic_state_invalidation.py`, and extend
`tests/test_isaac_occlusion.py`, `tests/test_isaac_stage_cache.py`, and
`tests/test_room_anchor.py`. Exact function names may follow repository style,
but every row below is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.7/` |
| --- | --- | --- |
| Material source/provenance | Pure table self-test plus installed `0.10.1` probe; exact seven measured rows, nine nominal rows, source hashes, tags, and citations | `material_table_provenance.json`, `material_table_rows.json` |
| Material resolution/fail closed | Pure parameter matrix; exact ids/aliases/precedence, absent-family and invalid-vector failures, empty partial-output listing | `material_resolution_matrix.json`, `material_failure_matrix.json`, `partial_output_listing.txt` |
| Clear/blocked/partial/material | Room-backend synthetic-record integration; exact metadata and six per-band bounds for every mic | `occlusion_consistency_results.json`, `occlusion_band_trace.csv`, `occlusion_fixture_waveforms.npz` |
| RMS/waveform/export | Capture sink plus FLOAT WAV decode; `1e-12` RMS bound, exact float32 decode, channel/rate/count/subtype | `waveform_rms_export_results.json`, `export_waveform_sha256.json`, `fixture_audio.wav` |
| Determinism | Two fresh runs; exact mixture/frame/WAV bytes and hashes; clear sequence endpoints separately require sample/WAV and occlusion-metadata identity while retaining the causal end-transition diagnostic | `acoustic_determinism_sha256.json`, `identical_frame_results.json` |
| Recompute-always baseline | Room/raycast call spies at `P=1` and inherited `P=8`; exact call counts and no result-cache object/path | `recompute_baseline_results.json`, `recompute_call_trace.csv` |
| Dynamic room/material | Fake-stage reason tracking plus real-pyroomacoustics changed RIR/output/hash rows | `dynamic_room_results.json`, `room_state_trace.jsonl`, `room_rir_sha256.json` |
| Moving source/array | Cached-stage integration; exact new poses/endpoints/room coordinates, output difference, no forced full discovery | `moving_endpoint_results.json`, `moving_endpoint_trace.csv` |
| Moving occluder/staleness | Five-state pure sequence; exact blocked maps/factors/channel changes/reasons and planted stale-result rejection | `moving_occluder_results.json`, `moving_occluder_trace.jsonl`, `staleness_detector_results.json` |
| Stage-cache taxonomy | Fake-`pxr` notice matrix; exact action/reason/order, one rediscovery where required, refresh-only occluder motion | `cache_invalidation_results.json`, `cache_invalidation_trace.jsonl` |
| Edge/failure matrix | Endpoint, degenerate ray, unknown/missing material, band mismatch, anchor deletion, OOB policy, multi-hit/cap | `acoustic_edge_case_matrix.json` |
| Off-state/predecessor regressions | Pinned `7e29d4f` exact L0/L1 frame plus scalar-room sample/WAV and pre-existing-field identity; focused S3.2/S3.6 reruns | `acoustics_off_state_sha256.json`, `s3_2_s3_6_regression.json` |
| Real dependency | Execute material and dynamic-room rows with recorded pyroomacoustics `0.10.1`; null/availability-only rows forbidden | `real_room_material_results.json`, `evidence_environment.json` |
| Live moving occluder | Extended gate from §9.1 through `make live-isaac-occlusion`; waveform/RMS/occlusion/diagnostics/reasons appear and disappear coherently | `live_moving_occluder_summary.json`, `live_moving_occluder_frames.jsonl`, `live_moving_occluder_wavs/observed_00.wav` through `observed_04.wav`, `live_moving_occluder_wavs/reference_00.wav` through `reference_04.wav`, `live_moving_occluder_wav_sha256.json`, `live_moving_occluder_stage.usda`, `live_moving_occluder_environment.json`, `live_moving_occluder.log`, `live_moving_occluder_viewport.png` |

The focused pure/integration command is expected to be:

```text
python -m pytest -q \
  tests/test_acoustic_materials.py \
  tests/test_acoustic_state_invalidation.py \
  tests/test_isaac_occlusion.py \
  tests/test_isaac_stage_cache.py \
  tests/test_room_anchor.py
```

The complete `S3.2` and `S3.6` focused suites and `make test` must be rerun
after implementation. An optional-dependency skip may keep the ordinary base
suite healthy, but the real room/material acceptance row is `Blocked`, never
`Passed`, until executed under the recorded dependency-capable interpreter.

`dynamic_rooms_gate.json` is the mandatory machine-readable roll-up. It
records this design revision, implementation revision, package/runtime/
dependency versions and origins, material source hashes/citations, all frozen
ids/vectors/geometries/formulas/tolerances, normalized configurations,
fixture and output hashes, measured maxima, exact-equality results, room/RIR/
raycast call counts, reason/action traces, per-row pass/fail/blocked status,
commands, live environment identity, and SHA-256 for every artifact. A null
measurement, dependency-availability boolean, file-exists check, or reason
counter without the corresponding changed observable cannot pass a row.

### 9.1 Live Isaac moving-occluder scenario

Extend `scripts/live_isaac_occlusion_gate.py`; do not create a second,
unconnected acceptance path. `make live-isaac-occlusion` remains the public
command. Preserve the existing clear, fully blocked, explicit material,
cache-policy, and screenshot phases, then add the exact five-position wall
sequence from §7.3 using a continuously active deterministic generated tone.
The existing compatibility summary at
`outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json` remains so the
entry Make target's post-check continues to work. The new moving-phase files
are additionally written under the exact `S3/S3.7` names in §9 and ingested
by `dynamic_rooms_gate.json`; they are not left only at the legacy root.
After the existing phases, close their sensor, author the narrow wall at the
first `y=+0.25 m` state, let PhysX settle, and only then create/reset the
moving observed/reference sensors. Thus state 0 is the comparison anchor and
the four later translations, not setup residue from the earlier wide-wall
phase, own the moving-state reasons.

The moving phase uses the `room_acoustics` backend, 48 kHz, a static room that
contains every source/array/wall position, per-frame FLOAT WAV output, the
same source/quad-array geometry as §7, and explicit flat `12.0 dB` wall
transmission. Capture five non-overlapping 0.05 s windows after PhysX/Kit has
settled each authored wall position. At every identical time/window, a second
room sensor with occlusion disabled renders the time-aligned clear reference;
it shares the stage, room, source, array, dependency, and effects settings but
writes to the `reference_*` path. Separate observed/reference output
directories prevent their deterministic frame names from overwriting one
another. The phase must retain the stage before teardown and preserve all ten
WAV files.

For each frame assert the exact expected blocked map/factor from §7.3,
`raycast_transmission_v1`, nominal wall evidence, per-frame
`occlusion_recompute_count==1`, finite waveform/RMS, and waveform-derived RMS
within `1e-12` before float32 export. A gate-only tee sink retains the
pre-export mixture for that assertion while forwarding the unchanged array to
the production `FrameWaveformWriter`. For affected channels, measured
time-aligned reference-versus-observed attenuation is `12.0 +/- 0.5 dB`;
unaffected channels remain within `0.5 dB` of their time-aligned clear
reference. The live tolerance is wider than the pure bound because Kit
capture timing and finite-window/RIR numerics remain environment-sensitive;
it does not replace the pure exact insertion test.

The sequence must show clear -> partial -> fully blocked -> partial -> clear
coherently in per-detection metadata, in-memory waveform, aggregate and
per-source RMS, exported WAV, `changed_occlusion_pairs`, and
`occluder_moved`. `StageAudioCache.full_discovery_count` must not increase
merely for the wall's pose-only steps, while cached ticks and fresh occlusion
recompute evidence do increase as expected. A stale waveform with a new
reason, or a changed waveform with old metadata, fails.

Save the live artifacts under the exact names in the verification map. The
summary records the five wall transforms, capture times, expected and
observed blocked maps/factors, per-mic RMS/attenuation, waveform and WAV hashes,
refresh reasons, cache counters, recompute counts, screenshot status, and
every assertion. Missing Isaac, GPU/display, PhysX, soundfile, or
pyroomacoustics is `Blocked` under S0; it is not a skip or a geometry-only
substitute for this live row.

## 10. Non-goals and limitations

- No RIR, premix, waveform, occlusion, or acoustic-result memoization/cache is
  designed or implemented.
- No diffraction, edge bending, portal propagation, thickness-dependent
  transmission, phase-through-material model, or wave solver is added.
- No finite-element, boundary-element, FDTD, ray-to-wave hybrid, or complete
  room-acoustic solver is claimed.
- No new measured-material acquisition, lab coupon measurement, uncertainty
  campaign, or calibrated SquadBot/room material pack is part of `S3.7`;
  broader acquisition belongs to S4/P2.
- Pyroomacoustics absorption measurements are not transmission measurements.
  The existing transmission presets remain nominal simulation parameters.
- The shared six-band grid stops at 4 kHz. The source database's 8 kHz values
  are audit provenance only in this phase.
- Occlusion remains direct-ray/per-surface transmission. It does not alter RIR
  reflection paths or model reflected-path occlusion.
- Room acoustics remains an approximate shoebox/image-source path under the
  existing pyroomacoustics and out-of-bounds limitations.
- `S3.7` does not change the `S3.6` `per_pair_direct_path` directivity model or
  claim reflection-specific source/microphone angles.
- Multi-source/moving-mount scale, imbalance, endurance, and performance
  stress remain `S3.8`; this phase isolates one known source/pair for causal
  consistency.
- Passing simulation fixtures does not establish calibrated real-world or
  sim-to-real material fidelity.

## 11. Entry, closeout, and verification status

Implementation may begin only from the frozen material rows/provenance,
reason actions, diagnostic schema, fixture geometry, measurement methods,
tolerances, and evidence map above. Changing a coefficient, evidence tag,
citation, alias, reason/action, hash input, geometry, sample count,
measurement formula, or tolerance after acceptance evidence exists invalidates
the affected evidence and requires a reviewed dated design revision plus all
affected and predecessor regressions.

The closeout must reconcile every §9 row with `dynamic_rooms_gate.json`, list
the exact implementation and evidence revisions, retain blocked rows
honestly, report any gate-found defects/amendments, and carry the ray/
transmission, nominal-material, six-band, shoebox, and no-result-cache limits
into `S3.8` and `S3.9`.

This change is documentation only. Read-only code inspection and pure
dependency/material/filter probes informed the frozen design. No production
code, test, Isaac, GPU, or hardware verification was run or is claimed by
this specification.

## References

- `docs/final_sensor_development_plan.md`, §6.6 (`S3.7`).
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, §S3 (`S3.7`).
- `docs/development/specs/s3_motion_policies.md`, especially the `S3.2` contract.
- `docs/development/specs/s3_channel_effects_chain.md`, especially the `S3.6` contract.
- `docs/development/closeouts/S3/s3_2_time_motion.md`.
- `docs/development/closeouts/S3/s3_6_waveform_directivity.md`.
- `docs/room_acoustics.md`.
- `docs/acoustic_fidelity.md`.
- `src/isaac_audio_sensors/core/types.py`.
- `src/isaac_audio_sensors/core/room_anchor.py`.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py`.
- `src/isaac_audio_sensors/core/io/waveforms.py`.
- `src/isaac_audio_sensors/core/scene.py`.
- `src/isaac_audio_sensors/isaac/occlusion.py`.
- `src/isaac_audio_sensors/isaac/stage_cache.py`.
- `src/isaac_audio_sensors/isaac/stage_snapshot.py`.
- `src/isaac_audio_sensors/isaac/extension.py`.
- `src/isaac_audio_sensors/usd_bounds.py`.
- `scripts/live_isaac_occlusion_gate.py`.
- Michael Vorländer, *Auralization: Fundamentals of Acoustics, Modelling,
  Simulation, Algorithms, and Acoustic Virtual Reality*, Springer, 1st ed.,
  2008, as cited by pyroomacoustics `0.10.1` for its material database.
