# S4.8 recovery amendment 02

## Status

This document preregisters a forward-only S4 recovery path after two consumed
S4.8 evaluations became permanently terminal `FAILED`.

It is an implementation and collection boundary, not authority to create a
grant, open a holdout, or execute an evaluation. The amendment remains
`NO-GO` until a new holdout has been collected after this preregistration,
sealed unopened, hash-bound through the declared binding schema, independently
reviewed against the exact candidate source, and explicitly authorized by the
operator.

## Immutable terminal history

The original `S4.8` package remains `FAILED/NOT_EVALUATED`. Recovery
amendment_01 remains `FAILED/EVALUATION_COMPLETED` because its complete
47-take payload was rejected by the scientific input contract before any of
the 29 criteria were evaluated.

Both grants were consumed. Neither run may be repaired, reinterpreted,
replayed, relabeled, retried, or used as evidence for an S4 PASS. Amendment_02
binds the exact grant, authorization, ledger, journal, recovery context,
progress where applicable, derived state, review where applicable, terminal
manifest, and final validation hashes for both histories. Package manifests
must continue to authenticate every terminal package file.

Validation of this history is metadata- and hash-only. It does not read raw
holdout observations or derive additional scientific knowledge.

## Frozen scientific preregistration

The producer correction is fixed at
`eea0059049ac780107394bb4edcf733def5a9bd1`. The corrective_03 criteria,
thresholds, exact-window semantics, 23 readiness criteria, six non-gating
stretch criteria, and `all_23_readiness_criteria_pass` rule are unchanged.
There is no post-hoc threshold, scenario, denominator, applicability, or
envelope change.

The new holdout repeats the exact hash-bound 47-take, 15-group technical design
as metadata only:

| Stratum | Takes |
|---|---:|
| `A_controlled_boundary_sweep` | 24 |
| `B_center_nominal_level` | 8 |
| `C_center_low_level` | 8 |
| `D_silence` | 3 |
| `E_impact_audio_video` | 4 |

The future precollection manifest must assign new planned-take identities
under `s48r02_unseen_holdout_`, preserve the template's exact scientific cell
order and pairing semantics, and be frozen before any new observation is
captured.

## New unseen holdout

All 47 observations must be newly captured after the amendment_02
preregistration commit. The observation root is
`dataset/S4.4/amendments/s4_4_data_expansion_amendment_04/attempts`.
It must be disjoint from the consumed amendment_03 observation root. No audio,
video, QA result, selected attempt, window result, or derived value from either
consumed evaluation may be copied or reused.

The precollection seal, technical manifests, and final unopened holdout seal
must live under the amendment_04 namespace declared in the machine-readable
amendment. The eventual binding file must validate against
`docs/schemas/s4_8_recovery_unseen_holdout_binding.v1.schema.json`, bind exact
paths and hashes, identify the preregistration commit, retain 47 takes and 15
groups, and state `scientifically_opened: false`.

The binding file does not exist in this preregistration commit. Its absence is
an expected execution blocker, not a failure of the preregistration validator.

## Future evaluation lane

After the new holdout is sealed and bound, a later additive implementation
must authenticate the new identity/seal binding in the corrective_03 evaluator
without weakening or rewriting the criteria. Only then may an independent
review approve an exact candidate source commit.

The separate future state roots are:

- grant and authorization:
  `dataset/S4.8/recovery_amendment_02/access/`;
- ledger and journal:
  `dataset/S4.8/recovery_amendment_02/access/opening_transition.v1/`;
- derived state:
  `dataset/S4.8/recovery_amendment_02/derived/`;
- terminal package:
  `outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_02`;
- independent review:
  `dataset/S4.8/recovery_amendment_02/review/independent_review.v1.json`.

Amendment_02 currently exposes only a preregistration/pre-open validator. It
deliberately exposes no grant-creation, grant-consumption, or evaluation
execution function. Those surfaces remain blocked until the unseen holdout
binding and evaluator rebinding are committed, reviewed, and separately
authorized.

This amendment is S4-only. It does not start S4.9, S5, or S6 and does not
authorize any push, tag, release, or publication.
