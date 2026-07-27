# S4.8 recovery amendment 01

## Scope and immutable original

The first authorized S4.8 run at source
`b0d5575feded9f37316bff8ed4b62483084587bd` is permanently terminal
`FAILED/NOT_EVALUATED`. Its grant was consumed and the opening transition was
authorized, but the evaluator failed before reading any attempt or deriving an
observation because `_require_consumed_ledger()` incorrectly required the
opening ledger hash on the later `post_consumption_started` journal record.

This amendment never retries, relabels, removes, overwrites, or repairs that
run. The original grant, authorization, ledger, journal, recovery context,
derived terminal state, terminal manifest, final validation, and complete
terminal package remain at their original paths and hashes.

## Eligibility

The recovery gate fails closed unless all versioned artifact hashes match, the
grant and authorization bind the original source and ledger, the ledger is one
valid consumed event, the journal is one valid terminal chain, and the
terminal package manifest and evidence index authenticate every package file.
The derived state must remain `not_evaluated`, with an empty scientific payload,
zero completed or derived observations, no partial progress, and no progress,
quarantine, or provisional state. The only eligible failure is exactly:

`S4.8 opening transition ledger binding mismatch`

Any original artifact drift, other failure, scientific observation opening,
derived observation, analysis completion, progress snapshot, or provisional
state makes recovery ineligible.

The gate authenticates metadata, hashes, derived terminal state, and the
already-produced terminal package only. It does not read raw holdout content or
derive a scientific value.

## Forward-only candidate

A possible future attempt uses the unchanged S4.8 evaluator and durable
state machine through the recovery contract context. It has a new
source-identified grant ID:

`s4_8_recovery_amendment_01_corrective_03_{source_commit}`

and separate versioned grant, ledger, journal, derived-state, and output paths
under `dataset/S4.8/recovery_amendment_01/` and
`outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_01`.

The pre-open gate does not authorize grant creation or consumption. Before
either action, a future independent review record must approve the exact
candidate source commit and the operator must provide a new explicit
authorization identity different from the original run. The recovery wrapper
then delegates grant creation, consumption, observation analysis, evaluation,
recovery, finalization, and evidence publication to the existing S4.8
implementation; it does not duplicate scientific logic or the state machine.

This amendment remains S4.8-only. It does not start S4.9, S5, or S6 and does
not authorize a push, tag, or release.
