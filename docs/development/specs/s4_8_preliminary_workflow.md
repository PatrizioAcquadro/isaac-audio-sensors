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
7. collect one new 37-take Recovery Amendment 02 unseen holdout, one explicitly
   authorized attempt at a time;
8. hash, seal, bind, pre-open validate, explicitly authorize, and evaluate it
   once.

Acquire only one exact take and attempt explicitly confirmed by the operator.
Every retry and every subsequent take requires a fresh authorization, and
acquisition must stop after the one attempt.

The preliminary evidence itself has no acquisition authority. The separately
committed final precollection freeze permits official capture only after an
exact per-take authorization. It still cannot create or consume an evaluation
grant, open the holdout for evaluation, run the official evaluation state
machine, or publish evaluation evidence.

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
a four-case preliminary manifest. A technically invalid take may be retried
without a fixed limit, but only for a physical or technical invalidation; an
undesirable scientific result can never justify a retry. Every gate emits an
explicit PASS or FAIL/RETRY_REQUIRED result.

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
and physical-confirmation disposition. A later record with the same correction
ID supersedes only that correction's pending disposition, so a retained failed
attempt remains documented while a technically valid replacement can settle
the earlier reacquisition requirement.

When a retained acquisition historically ended `RETRY_REQUIRED` because of a
later-corrected detector or processing defect, the original retry report,
controller result, journal, attempt ledger, manifest, raw, and attempt
directory remain immutable. A separately versioned
`ias.s4_8.preliminary_reprocessing_record.v1` may bind those historical
artifacts, the corrective source commit, a current offline gate report, exact
corrected technical metrics, and a canonical `reuse` decision. Preliminary
processing may consume that authenticated additive `PASS`, but must expose the
historical `RETRY_REQUIRED` decision separately and may not synthesize an
original candidate seal or append to the historical acquisition journal. The
record authenticates the attempt-ledger prefix through the corrected retry;
later preliminary entries may append normally. Request validation may advance
past that retry only when it authenticates the additive record against the
same campaign manifest, ledger prefix, attempt identity, raw, corrected report,
and corrective source commit.

A whole-campaign relocation does not alter those authenticated payloads. The
physical runner accepts the frozen campaign root or its repository-local
`.local/s4_8/<campaign-name>` location, rebases every bound reprocessing path
as one unit, and then rechecks every SHA-256 and structural binding. Individual
path substitution, a different campaign name, an artifact outside the declared
campaign root, or an unbound manifest copy fails closed. Operators may use
`run-preliminary-take --validate-only` to exercise the complete request and
ledger checks without creating an attempt directory or starting hardware.

Keep each failed raw only until a technically valid replacement passes. Then
delete the failed attempt artifacts, remove their `RETRY_REQUIRED` records from
the active attempt ledger, and retain only a short note with the take ID,
attempt number, failure cause, replacement attempt number, and practical
prevention guidance. The replacement becomes one authenticated compacted
`PASS` ledger record that preserves its actual attempt number and binds each
remaining note by path and SHA-256. Never delete the newest valid raw. The
existing low-level attempts 1 and 2 remain in place until the replacement
passes; attempt 2 was invalidated by uncontrolled human noise.

These retries and software corrections remain within Recovery Amendment 02 and
the planned second holdout; they do not create another amendment. Once the
official protocol is frozen, accepted official data is immutable. A passed
take cannot be replaced, including in response to a scientific result.

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

After the final precollection freeze, Recovery Amendment 02 may collect exactly
one new 37-take unseen holdout. During acquisition, only preregistered technical QA may
be observed. The complete dataset must then be hashed, sealed unopened, and
bound to the frozen evaluator. Official evaluation remains blocked until
pre-open validation passes and explicit authorization is supplied.
