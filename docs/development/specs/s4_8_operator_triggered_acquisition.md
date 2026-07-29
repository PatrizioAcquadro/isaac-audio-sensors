# S4.8 operator-triggered acquisition amendment

## Scope

This additive amendment governs physical acquisition scheduling for the active
four-take preliminary workflow and the future 47-take Recovery Amendment 02
holdout. It does not change any scientific cell, reference signal, playback
gain, geometry, device profile, channel map, detector, metric, criterion,
threshold, sealing rule, grant rule, or holdout-opening rule.

Every physical take starts only after one explicit operator request. One
invocation may acquire exactly one take and can never continue automatically
to another take. A batch or implicit series is forbidden. The operator may
later request a series, but each take in that series still requires its own
one-take authorization and retained ledger record.

This amendment creates no authority to freeze the official protocol, collect
the official holdout before its later freeze, create or consume a grant, open
a holdout, run the official state machine, or publish official evidence.

## Operator authorization

Before a recorder starts, the controller must authenticate one authorization
bound to:

- the exact frozen campaign-manifest hash;
- the current retained attempt-ledger head;
- the exact take id and take-definition hash;
- the exact next monotonic attempt number;
- the implementation Git head executing the controller;
- one reason code and a non-empty technical justification;
- `scientific_outcomes_inspected: false`;
- `one_take_only: true`;
- `automatic_batch: false`;
- `all_prior_attempts_retained: true`.

An authorization is stale after any ledger append and cannot authorize a
different take or attempt. Altered authorizations fail closed.

## Attempts and retention

The historical two-attempt policy remains valid for its original records.
This amendment does not edit, remove, renumber, reinterpret, or replace those
records. A later operator-authorized retry appends a versioned ledger record
to the existing hash chain.

There is no fixed retry count for a take that continues to return
`RETRY_REQUIRED`, because physical collection can be interrupted by people,
noise, device availability, or other acquisition conditions. Every additional
attempt must:

1. follow the retained `RETRY_REQUIRED` record for the same take;
2. use the next integer attempt number;
3. have a fresh authorization bound to the current ledger head;
4. retain every earlier raw file, report, journal, clearance, result, and seal;
5. preserve the frozen scientific configuration.

A `PASS` advances the planned sequence. The next take still waits for another
operator authorization. A passed take cannot be replaced merely because its
scientific result is undesirable. Replacing a passed take requires a separate
versioned physical-invalidation amendment created before scientific outcomes
are inspected.

## Preliminary continuation

The accepted nominal preliminary take remains valid. The two low-level
attempts remain retained `RETRY_REQUIRED` evidence. The operator may authorize
attempt 3 for only `s48prelim_002_low_level_reference`, citing the observed
uncontrolled human noise as a physical acquisition invalidator. No other
preliminary case starts until the low-level case passes.

Once all four current cases pass, processing selects the PASS attempt for each
case while retaining all failed attempts and their reacquisition decisions.

## Future 47-take acquisition

The later official 47-take manifest must embed the operator-triggered policy.
Each official acquisition command may start one take only. During collection,
authorization and replacement decisions may use preregistered technical QA and
operator-observed physical invalidators only. Scientific detector, bearing,
confidence, criterion, or evaluation outcomes remain unopened until the full
holdout is complete, hashed, sealed, bound, reviewed, and explicitly
authorized for one evaluation.

The 47 takes need not be acquired continuously or in one session. Sequence,
group, geometry, and device-profile requirements remain frozen even when
takes are collected across multiple operator-triggered sessions.

## Acceptance criteria

- legacy two-attempt manifests and ledgers still authenticate byte-for-byte;
- a legacy retry after attempt 2 requires an additive operator authorization;
- a new operator-policy manifest requires an authorization for attempt 1 and
  every later attempt;
- one authorization is exact to one take, one attempt, and one ledger head;
- retry attempt numbers are strictly monotonic;
- no retry follows a `PASS` without a separate passed-take invalidation
  amendment;
- every prior attempt remains in the ledger and on disk;
- no CLI operation implicitly records more than one take;
- scientific outcomes cannot appear in an authorization or retry decision;
- preliminary and official authority boundaries remain disabled until their
  existing independent gates pass.
