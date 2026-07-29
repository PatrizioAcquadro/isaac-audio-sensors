# S4.8 four-take preliminary workflow

## Active path and authority

This is the active S4.8 preparation and engineering path. It replaces the
former requirement to complete a 47-take engineering campaign before
collecting a second 47-take official campaign. The v9 engineering campaign,
its worktree, manifests, attempts, and evidence remain preserved historical
material and are not rewritten or deleted.

The active sequence is:

1. collect exactly four preliminary engineering takes;
2. validate and run the complete stack on those takes;
3. correct technical or implementation failures and record whether raw takes
   remain valid;
4. reprocess valid raw takes or replace only invalidated takes;
5. establish preliminary readiness with every required gate passing;
6. later freeze the final official protocol;
7. later collect one new 47-take Recovery Amendment 02 unseen holdout;
8. hash, seal, bind, pre-open validate, explicitly authorize, and evaluate it
   once.

Physical collection is operator-triggered under
`s4_8_operator_triggered_acquisition.md`. One explicit command starts at most
one take. No preliminary take starts automatically after another take, and all
prior attempts remain retained. A fresh one-take authorization is required for
every later attempt.

This preparation has no authority to record a take, freeze the final protocol,
start official acquisition, create or consume a grant, open a holdout, run the
official state machine, or publish official evidence.

## Four preliminary cases

The cases, in order, are:

| Case | Frozen representative |
|---|---|
| nominal reference | first B center nominal-level cell |
| low-level reference | first C center low-level cell |
| silence | first D silence cell |
| audio/video impact with ZED | first E impact/ZED cell |

The selection reuses only frozen design metadata. It does not reuse a consumed
observation. The preliminary identities use the `s48prelim_` prefix and a
separate operational root. All four takes are engineering-only, uncounted,
excluded from the official holdout, safe to inspect, and ineligible as
official evidence.

No detector, threshold, criterion, reference WAV, playback gain, geometry,
device profile, channel map, or other scientific protocol element changes in
this workflow.

## Acquisition and complete-stack processing

The existing authenticated v9 acquisition controllers and gates are used with
a four-case preliminary manifest. Each attempt retains its raw WAV, process
journal, technical report, clearance, candidate seal, and ZED artifacts when
applicable. Every gate emits an explicit PASS or FAIL/RETRY_REQUIRED result.

Processing is repeatable without reacquisition. It authenticates the raw
inputs, reruns technical checks, current detector and synchronization
processing, metric derivation, the current evaluator, and diagnostic package
generation. To exercise the exact 47-input evaluator contract, the four
preliminary derived records replace their matching records in the existing
deterministic synthetic payload. The remaining records stay synthetic. The
result is diagnostic-only and cannot be cited as S4.8 evidence or as an S4.8
PASS.

Failures are classified as acquisition, detector, synchronization, metric,
evaluator, or packaging failures so correction scope is explicit.

## Raw-take validity and reuse

Reuse and reprocess a raw take when it remains technically valid and
representative and the correction affects only downstream code.

Replace the affected take when the correction changes or invalidates physical
acquisition conditions, playback path, reference signal, playback gain,
geometry, device profile, channel map, synchronization assumptions, or raw
recording validity.

For detector or processing changes, a valid recording may be reused for
diagnosis and regression. Before preliminary readiness, record an explicit,
evidence-based decision stating whether fresh physical confirmation is
required. If it is required, readiness stays blocked until that confirmation
passes. A change that cannot affect existing raw validity must not
automatically trigger four new recordings.

Every correction has an append-only reuse/reacquisition decision with its
change class, affected cases, raw hashes, decision, technical justification,
and physical-confirmation disposition.

An uncontrolled physical interruption such as unrelated people making noise
may invalidate only the affected take. A retained `RETRY_REQUIRED` attempt may
be followed by another monotonic operator-authorized attempt without a fixed
retry count. The authorization is exact to one take, one attempt number, and
the current ledger head. It cannot authorize a batch or silently replace a
passed take.

## Preliminary readiness and official boundary

Final protocol freeze is permitted only when:

- exactly four current preliminary cases are present and none is labeled
  official;
- acquisition, technical validation, detector processing, synchronization,
  metric calculation, diagnostic evaluator, and diagnostic packaging gates
  all PASS;
- the diagnostic evaluator completes and all current readiness criteria pass
  in the explicitly synthetic-completed diagnostic payload;
- every correction has a valid reuse/reacquisition decision;
- any required fresh physical confirmation has passed;
- no unresolved preliminary failure remains.

Readiness permits a later final-protocol freeze; it does not perform that
freeze.

After the later freeze, Recovery Amendment 02 may collect exactly one new
47-take unseen holdout. During acquisition, only preregistered technical QA may
be observed. The complete dataset must then be hashed, sealed unopened, and
bound to the frozen evaluator. Official evaluation remains blocked until
pre-open validation passes and explicit authorization is supplied.
