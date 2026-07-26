# S4.7 corrective preregistration closeout

## Verdict

**S4.7 corrective PASS — ready to proceed to S4.8.**

This verdict means the additive corrective preregistration is complete,
identity-bound, deterministic, committed-evidence-ready, and still blind. It
does not authorize or start S4.8 and it does not assert a held-out scientific
result.

## Scope and unchanged scientific claims

The corrective is `s4_7_corrective_01`. It supersedes the S4.7 v1 execution
contract without modifying the frozen v1 configuration, specification, or
16-file evidence package. All 23 readiness thresholds, six stretch
thresholds, the controlled-source single-room single-mount envelope,
not-evaluable declarations, and scientific eligibility rules are unchanged.

The freeze is bound to the same unopened amendment-03 prospective holdout:

- holdout ID:
  `s4_4_data_expansion_amendment_03_prospective_holdout`;
- seal file SHA-256:
  `dff1a520fd35bff4bdd0b9e1023d474544b7685360d087a32498757f8269528c`;
- seal payload SHA-256:
  `e83e2a0c392850d581f7487423afa9a8844e1e4e595c47020f9b5b9bf3231024`;
- planned take count: 47; leakage-group count: 15;
- holdout observations accessed: 0.

## Corrective contract

The authoritative files are:

- `configs/s4_7_holdout_acceptance.corrective_01.v2.json`
  (`0a6a28b096f98ffd14ecb6332ed32e2a9b1f6aa632eb157230b6269f448244c3`);
- `docs/schemas/s4_7_holdout_acceptance.corrective_01.v2.schema.json`
  (`01e726a0d418399e715118109d5fdf1f39d38344af9fcebda6818ba4ad1b8d34`);
- `docs/development/specs/s4_holdout_acceptance_corrective_01.md`
  (`10f91d3bd411582669e9a9640952665e3015a2244cdb7cb115b87b6f27c31e9e`).

The truthful freeze time is `2026-07-26T15:24:12Z`. Git ordering validation
proves:

`f223012` v1 closeout < freeze time ≤ `ae66e2f` corrective contract
≤ `5b8f43b` evaluator hardening ≤ `cbcf656` authenticated source.

## Input completeness and physical domains

The evaluator projects the exact 47 take identities from the tracked technical
session manifest. Every payload record must carry the exact take, stratum,
leakage group, bearing cell, repetition, condition, and B/C counterpart
identity. The accepted registry contains:

- 24 A takes: eight bearing cells × three repetitions;
- eight B takes and eight C takes: four cells × two repetitions, paired with
  identical counterpart keys;
- three D silence takes and four E audio-video takes;
- four raw microphone records per take (188 total);
- six microphone-pair records per A take (144 total).

Window coverage is exact per take: 119 source windows for each 15 s take and
159 for each 20 s take under the frozen 250 ms / 50% overlap contract. Latency
is one summary per metric per each of 47 takes. Maximum clip run is the maximum
over 188 keyed channel records, not a sum.

Finite physical-domain checks reject negative absolute errors, latencies,
absolute residuals, sample counts, TDOA absolute errors, or clip runs;
non-integer counts; bearings outside `[0, 360)`; confidence/rates outside
`[0, 1]`; and raw TDOA outside the nominal four-microphone direct-path domain.

## Sim-versus-real semantics

Exactly seven comparison records are mandatory. Metric, unit, direction,
preserve band, applicability, aggregation, and expected condition count come
only from the frozen config. Payload-supplied direction or band fields are
forbidden.

The bearing criterion uses exactly 32 A+B take conditions. The 40
bearing-referenced takes are stated only where C is applicable to confidence.
The three real/unadjusted/adjusted paths share one exact condition set for
every comparison, so an unfavorable condition cannot be removed.

## S4.8 prerequisite authentication

`consume_s4_8_grant` accepts only the canonical corrective artifact:

`outputs/isaac_audio_sensors/S4/S4.7_corrective_01/holdout_acceptance.json`.

Before any grant can be consumed, it independently verifies:

- the complete 18-file package and exact file set;
- evidence index closure and every SHA-256 manifest record;
- the complete corrective artifact schema and passing status;
- config, schema, corrective spec, inherited criteria, and inherited spec
  hashes at a real ancestor source commit;
- holdout ID, seal file/payload hashes, and planned count;
- exact agreement between grant-seal and prerequisite-seal bindings;
- Git tracking, committed bytes, and absence of staged or worktree tampering.

Negative tests reject a fabricated two-field prerequisite, v1 artifact, wrong
or copied path, wrong grant/prerequisite seal, stale identity hash, incomplete
package, uncommitted package, and tampered report.

## Evidence and reproduction

Canonical corrective evidence:

`outputs/isaac_audio_sensors/S4/S4.7_corrective_01/`

Key identities:

- source commit: `cbcf656f4550875d8937d909197f7efb67a53820`;
- package SHA-256 manifest:
  `de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676`;
- evidence index:
  `213f4f3fba446383d84c7315f7c48257540af8a60f75d4d89dbce7722d044bf0`;
- canonical prerequisite:
  `7e3f670f18817d8d33612f45efc3fb0c551be926194b870cc7b05e1ced09245c`.

Clean source-archive replay is byte-identical for:

- historical v1: 16 files from
  `e4be6b1ff610b0353f7301d3da98c946f052caa6`;
- corrective: 18 files from
  `cbcf656f4550875d8937d909197f7efb67a53820`.

The historical v1 `SHA256SUMS` file remains
`795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53`,
and all its listed bytes verify.

## Intermediate commits

- `ae66e2f` — Define S4.7 corrective acceptance contract.
- `5b8f43b` — Harden S4.7 acceptance evaluation.
- `cbcf656` — Authenticate S4.8 prerequisite.
- `Close out S4.7 corrective preregistration` — canonical evidence and this
  closeout.

## Phase boundary

- Holdout observations accessed: **0**.
- Holdout access grant created or consumed: **no**.
- S4.8, S4.9, S5, or S6 started: **no**.
- Threshold, envelope, or eligibility changed from holdout results: **no**.
- Push performed: **no**.
- Tag created: **no**.
