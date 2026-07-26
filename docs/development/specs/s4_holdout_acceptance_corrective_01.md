# S4.7 corrective functional acceptance preregistration

## Authority and phase boundary

This additive corrective supersedes the S4.7 v1 *execution contract* while
preserving the v1 configuration, specification, implementation commit, and
16-file evidence package byte-for-byte. It changes no threshold, claimed
envelope, or scientific eligibility rule. It remains bound to the same
unopened 47-take amendment-03 prospective holdout and the same preserved
S4.1-S4.6 provenance.

The machine-readable authority is
`configs/s4_7_holdout_acceptance.corrective_01.v2.json`. The freeze time is
`2026-07-26T15:24:12Z`, after the v1 closeout commit and before this corrective
contract is committed. The corrective validator verifies that ordering from
Git commit objects. No S4.8 grant is created or consumed, no holdout
observation is accessed, and no later phase starts.

Historical v1 validation is replayed from its bound implementation commit
`e4be6b1ff610b0353f7301d3da98c946f052caa6`; current corrective sources are
not compared to the historical source tree.

## Exact input identity

The only identity source is the tracked technical session manifest at
`outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03/manifests/sessions/prospective_holdout.json`,
bound by SHA-256. The evaluator projects all 47 planned take IDs, strata,
leakage groups, bearing cells, repetitions, and B/C paired counterparts from
that manifest. Payload identity is checked against that projection exactly.

A missing, duplicate, unknown, mis-stratified, mis-grouped, wrong-repetition,
or mismatched-pair record fails the whole evaluation. The four analysis
channels are exactly `raw_microphone_0..3`; the six unordered microphone pairs
are frozen in the corrective configuration. Stratum A must contain three
repetitions for every one of eight bearing cells. Strata B and C must contain
two repetitions at each of four bearing cells and identical B/C counterpart
keys.

## Window and denominator semantics

Each take carries a structured window summary with its source window count,
abstained count, and below-floor direction-emission count. The expected source
count is derived from the tracked 15 s or 20 s take duration and the already
frozen 16 kHz, 250 ms, 50% overlap analysis contract:

`1 + floor((duration_samples - window_samples) / hop_samples)`.

This yields exactly 119 windows for a 15 s take and 159 windows for a 20 s
take. One record can therefore never stand in for an entire stratum. Every
rate denominator is derived from authenticated keyed records or from these
validated per-take source counts; no caller-supplied aggregate scalar is
trusted.

Latency is defined consistently as one
`frame_to_adapter_round_trip_ms` summary and one
`capture_to_frame_offline_ms` summary for each of all 47 planned takes.

Channel-health, polarity, clipping, and failure counts are derived from keyed
take/channel records. The maximum clip-run statistic is the maximum over the
188 four-raw-microphone take records; it is not a total.

## Sim-versus-real registry

Exactly seven comparison records are required. The configuration, never the
payload, supplies metric, unit, direction, preserve band, aggregation,
applicable strata, condition kind, and expected count. Each payload comparison
supplies only its `comparison_id` and keyed real/unadjusted/adjusted values.
All three paths therefore have the identical expected condition set.

| Comparison | Conditions | Count |
| --- | --- | ---: |
| bearing absolute error | A+B takes | 32 |
| sector accuracy | B takes | 8 |
| candidate coverage | A+B takes | 32 |
| absolute TDOA error | A take × microphone pair | 144 |
| abstention rate | A+B+D takes | 35 |
| confidence | B+C takes | 16 |
| coarse AV residual | E takes | 4 |

For the mixed active/silence abstention comparison, each condition is a
decision-error fraction: abstained fraction for active A+B takes and
non-abstained fraction for silence D takes. Lower is therefore consistently
better without reversing the meaning of silence.

The bearing sim-real readiness criterion uses 32 A+B takes. There are 40
bearing-referenced takes only when C is included for the confidence comparison;
C is not silently added to the bearing-error criterion.

An omitted, duplicated, unknown, or conflicting comparison record fails
closed. Payload fields such as `lower_is_better` or `band_key` are forbidden,
so a caller cannot reverse an unfavorable result or borrow another metric's
tolerance. No condition can be removed.

## Physical domains

All numeric inputs must be finite. Absolute bearing errors are in `[0, 180]`;
bearings are in `[0, 360)`; confidence and rate-valued observations are in
`[0, 1]`; latencies, absolute residuals, absolute TDOA errors, sample counts,
and clipping-run lengths are non-negative. Counts and clipping runs are
integers.

Raw TDOA is limited to the existing nominal direct-path contract:
`[-272.1227262875343, 272.1227262875343] µs`, derived from the maximum
0.09333809511662428 m spacing of the frozen four-microphone geometry divided
by the frozen 343 m/s propagation speed. No unsupported SPL, frequency,
reverberation, or wider-environment limit is introduced.

## Unchanged scientific criteria

All 23 readiness and six stretch thresholds, the controlled-source single-room
single-mount envelope, failure logic, not-evaluable declarations, and
unsupported quantities are inherited hash-exactly from S4.7 v1. The
corrective changes only identity, completeness, domain, comparison, evidence,
and prerequisite authentication semantics.

The readiness gate still passes only if all 23 readiness criteria pass.
Stretch criteria are reported and remain non-gating.

## Evidence and S4.8 interlock

The corrective package lives at
`outputs/isaac_audio_sensors/S4/S4.7_corrective_01/`. Its canonical
`holdout_acceptance.json` binds the complete package identity: evidence index
and SHA-256 manifest, criteria/config/spec hashes, source commit, holdout ID,
seal file and payload hashes, planned count, and passing status.

The S4.8 grant consumer accepts only that repository-relative canonical path.
It verifies the complete corrective artifact schema, the complete committed
package, source provenance, Git tracking/commit state, every bound hash, and
the equality of grant-seal and prerequisite-seal bindings. A two-field stub,
copied file, stale hash, wrong path, wrong seal, incomplete package,
uncommitted package, or tampered package is rejected.
