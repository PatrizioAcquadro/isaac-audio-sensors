# S4.8 held-out functional sim-to-real evaluation

## Authority and phase boundary

This specification implements only S4.8. It consumes the canonical S4.7
corrective_03 prerequisite and the amendment-03 prospective holdout without
changing any S4.1-S4.7 artifact or scientific decision. S4.7 v1 and
corrective_01 through corrective_03 remain immutable.

S4.8 does not implement S4.9, S5, or S6. A passing S4.8 result leaves S4
incomplete until S4.9 independently passes. A failed readiness criterion keeps
S4.8 and S4 failed for the claimed envelope; it cannot be repaired by tuning,
threshold changes, denominator changes, selective removal, or post-hoc
envelope narrowing.

## Frozen inputs

The only scientific prerequisite is:

`outputs/isaac_audio_sensors/S4/S4.7_corrective_03/holdout_acceptance.json`

It must authenticate its complete 18-file package, exact scientific-semantics
register, source and evidence commits, seal, partition and session manifests,
and deterministic replay. Older S4.7 prerequisites are stale for the active
consumer.

The partition-manifest file SHA and its embedded canonical split-plan SHA are
distinct authenticated identities. The grant binds `split_plan_sha256` to the
embedded canonical value; it does not relabel the manifest file SHA as the
split-plan identity.

The only holdout is the 47-take, 15-group
`s4_4_data_expansion_amendment_03_prospective_holdout` sealed by:

`outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03/holdout_seal.v1.json`

The planned denominator is always 47. Missing, rejected, corrupt, or failed
takes remain in the inventory and can never improve a rate by removal.

## Irreversible access

Before explicit user authorization, tooling may authenticate tracked
contracts, inspect already-tracked technical identities, and verify only the
sealed artifact sizes and hashes. It may not create or consume the real grant,
read raw recordings, read technical QA content, read operator event content,
read ZED frame content, or derive a held-out scientific observation.

After explicit authorization, tooling creates exactly one purpose-bound,
corrective_03-prerequisite-bound, seal-bound, partition-plan-bound,
source-commit-identified, single-use grant at:

`dataset/S4.8/access/holdout_access_grant.corrective_03.v1.json`

Grant creation stages the grant and complete authorization record together in
a private same-filesystem directory, validates their exact schemas and mutual
bindings, fsyncs both files and the staging directory, and publishes the pair
with one atomic directory rename followed by a parent-directory fsync.
Creation is serialized by the persistent
`dataset/.s4_8_grant_creation.lock`, acquired before `dataset/S4.8` is
created. Concurrent identical creation requests return the same authenticated
pair; a mismatched request or existing tampered state fails closed.
Before any file is written into a newly created one-shot state directory, that
directory entry is made durable by fsyncing its containing directory. This
applies recursively when `dataset/S4.8` is initially absent: creation of
`dataset/S4.8` is followed by an fsync of `dataset` before `access`, grant
staging, or any dependent state is published. The same containing-directory
rule applies to opening-transition staging, progress and quarantine roots,
derived state, provisional evidence, evidence-package staging, and replay or
canonical output directories. Restart re-anchors a directory that may have
survived a process crash between `mkdir` and the containing-directory fsync
before treating dependent state as published.
Interrupted private stages are deterministically cleaned on retry. A
grant-only residue from the earlier non-atomic creator is retryable only when
the grant exactly matches the requested source and frozen contract; malformed,
mismatched, or already-consumed state is never replaced.

It is consumed exactly once by
`isaac_audio_sensors.acquisition.s4_4.consume_s4_8_grant`, using the append-only
ledger:

`dataset/S4.8/access/opening_transition.v1/access_ledger.jsonl`

Grant consumption and observation opening run serially and are never
automatically retried. Raw data, grant, and ledger remain ignored under
`dataset/`.

The complete authorized execution is guarded by the persistent advisory lock
`dataset/.s4_8_authorized_execution.lock`. The lock file is outside
`dataset/S4.8` and every directory that the one-shot protocol atomically
replaces. An executor acquires the kernel-backed exclusive lock, without
waiting, before it inspects any journal, derived result, recovery state, or
output. It holds the same lock through grant consumption, observation access,
evaluation, progress persistence, recovery, downgrade, evidence publication,
journal finalization, and terminal validation. Contention fails immediately
without inspecting or changing one-shot state, consuming the grant, opening an
observation, entering recovery, publishing output, or terminalizing the live
owner. The persistent lock file is never unlinked. Process termination closes
the owning descriptor and releases the kernel lock, after which exactly one
later executor may acquire it and perform journal-authoritative recovery.
Grant consumption and real-observation derivation are private implementation
steps that require the active process-and-context-bound execution-lock scope;
calling either step outside that scope fails before ledger or holdout access.

The S4.8 consumer serializes grant claim, canonical ledger append, first-run
journal initialization, and observation-opening authorization under one
machine-local exclusive transition lock. The canonical consumer writes the
ledger and matching two-event journal prefix into a same-filesystem staging
directory, then one atomic directory rename publishes the complete
`opening_transition.v1` state. Observation code requires both records from
that finalized directory. A concurrent caller can never acquire a second
successful claim. An incomplete staged transition is never eligible to open
observations.

The journal has exactly one terminal event after the first package is
finalized. It never records scientific completion before package finalization.
Input rejection, failed readiness, or an evidence-construction failure
produces a terminal failed record and forbids retry. Package files are written
in a same-filesystem staging directory, validated there, and atomically renamed
to the canonical output only when complete; partial canonical output is never
valid.

Every authorization record must contain exactly the versioned schema,
nonempty authorization ID, source commit, grant ID, grant path, grant hash,
ledger path, and irreversible-scientific-action acknowledgement. Those values
must match the active contract, grant, and consumed ledger event exactly.
Authorization is authenticated before grant consumption and again during
evidence construction, validation, and replay; empty, partial, mismatched, or
tampered records fail closed.

Post-consumption recovery distinguishes `not_evaluated`, `evaluation_failed`,
and `evaluation_completed`. A completed evaluation includes the exact
scientific payload, payload hash, evaluation, evaluation hash, PASS/FAIL
decision, and failed-criteria list. It is durably published before runtime
provenance, derived-state persistence, packaging, evidence publication, or
journal finalization begins. A later operational failure makes the overall run
terminal FAILED without replacing or relabeling that scientific result.
Failures before evaluation do not claim input rejection; input rejection is a
completed scientific FAIL only when the frozen evaluator actually returned it.

Observation progress and every completed post-consumption stage are stored in
content-addressed snapshots. Each snapshot is source-bound, hash-bound to the
atomic opening-journal head and prior progress state, and anchored by a
monotonic journal transition. Recovery uses only the highest authenticated
stage. The journal is authoritative: a structurally valid next snapshot that
was durably written but never acquired its journal event is quarantined as a
crash residue and never promoted. If no progress event exists, recovery uses
the authenticated pre-consumption recovery context. Altered, stale,
source-mismatched, rolled-back, reordered, replaced, or malformed progress
fails closed. Recovery never reopens an observation or reconsumes the grant.

## Exact real-observation contract

Every planned take maps to its tracked corrective_03 identity. The analyzer
reads only the seal-declared attempt root matching that planned identity and
verifies every accessed file against the seal before interpreting it.

If a planned take has multiple sealed attempts, the unique selected attempt is
fixed before opening by hash identity with the amendment-03 machine-local
`access/technical_qa/<planned_take_id>.json` projection. Every sealed attempt
remains archived in the evidence inventory; selecting the projected attempt
does not remove the planned take from the denominator.

The analyzer reuses the frozen S4.3 waveform implementation with the S4.6
functional channel-position association and supported channel response. It
emits exactly 119 windows for a 15-second take and 159 windows for a 20-second
take, with 4,000-sample windows, 2,000-sample hops, contiguous zero-based
indices, `window_NNN` identifiers, and exact start samples.

The corrective_03 evaluator remains authoritative for:

- median absolute window bearing error per take;
- linear median valid-window bearing followed by frozen circular
  repetition range;
- unique valid-window sector majority;
- candidate coverage at 20 degrees;
- six pair-TDOA observations per A take;
- confidence, abstention, sub-floor emissions, latency, raw-channel health,
  clipping, failure, and audio-video association;
- all thresholds, denominators, exclusions, aggregation rules, preserve
  bands, and fail-closed behavior.

Missing, duplicate, unknown, altered, inconsistent, non-finite,
out-of-domain, wrong-identity, wrong-profile, wrong-mode, wrong-condition,
incomplete-window, or denominator-mismatched inputs reject the evaluation or
fail the applicable take/criterion exactly as frozen.

For stratum E, the frozen S4.3 corrective-02 transient detector supplies audio
event candidates. Exactly three ordered events are selected by minimum
deviation from the prospectively scheduled five-second spacing. Each event is
associated with the maximum mean absolute finite depth-grid change inside the
frozen one-second UTC search half-width. Audio producer UTC and ZED host UTC
are the comparison clock basis. All audio candidates, visual candidates, and
the three associations are retained; the per-take value is the worst absolute
residual.

## Simulation contract

The harness executes the same 47 technical identities and the exact comparison
registry twice. The unadjusted path uses the S4.6 application in `mode=off`;
the adjusted path uses `mode=apply`. The two paths share condition identity,
source pose, duration, sample rate, estimator, thresholds, and aggregation.
Only the seven supported S4.6 components may differ.

Every comparison condition is archived. The corrective_03 evaluator derives
the real values and classifies adjusted versus unadjusted as `improves`,
`preserves`, or `worsens` with the frozen inclusive bands. No caller-supplied
real value, direction, band, threshold, or condition set is accepted.

## Result and evidence

All 23 readiness criteria must pass for S4.8 PASS. The six stretch criteria are
reported but never gate. Robustness has a zero denominator and is always
reported as `not_evaluable`; no robustness value is manufactured.

The tracked versioned package is:

`outputs/isaac_audio_sensors/S4/S4.8/`

It contains the complete take/window/repetition/scenario/failure inventory,
corrective_03 evaluation, sim-versus-real condition records and classifications,
criteria and stretch results, robustness and unsupported declarations,
authorization/grant/ledger provenance without raw content, source and input
hashes, preservation proof, deterministic reproduction information, evidence
index, and SHA-256 manifest. Deterministic regeneration from the preserved
derived input must reproduce all applicable package bytes.

The first opened result is immutable. If a result-affecting implementation
defect is discovered after opening, the original run is preserved and work
stops for explicit direction; no silent patch or rerun is permitted.

The candidate source commit binds the complete tracked result dependency
inventory: all package implementation modules, frozen configuration and schema
inputs, authenticated S4 evidence dependencies, CLI entry points, and project
dependency declaration. Candidate validation rejects any dependency whose
worktree bytes differ from the commit, any untracked Python code, and any
repository file that shadows a runtime import.

Package construction, package validation, and replay independently run the
corrective_03 evaluator from the preserved derived payload. The recomputed
evaluation must exactly equal the preserved criteria, pass flags, comparison
classifications, and terminal scientific status. Validation also regenerates
the complete package in a temporary directory and compares every file byte for
byte, so a checksum-consistent alteration to observations or any derived
report remains invalid.
