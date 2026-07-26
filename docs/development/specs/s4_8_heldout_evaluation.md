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

It is consumed exactly once by
`isaac_audio_sensors.acquisition.s4_4.consume_s4_8_grant`, using the append-only
ledger:

`dataset/S4.8/access/access_ledger.jsonl`

Grant consumption and observation opening run serially and are never
automatically retried. Raw data, grant, and ledger remain ignored under
`dataset/`.

## Exact real-observation contract

Every planned take maps to its tracked corrective_03 identity. The analyzer
reads only the seal-declared attempt root matching that planned identity and
verifies every accessed file against the seal before interpreting it.

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
