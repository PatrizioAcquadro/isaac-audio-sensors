# S4.4 data-expansion amendment 03 historical v5 checkpoint

This document is a superseded pre-take-35 checkpoint. It is retained for
historical accuracy and does not state current phase status. Fit B is complete;
the prospective holdout is complete, technically sealed, and scientifically
unopened. The authoritative current closeout is
`docs/development/closeouts/S4/s4_4_data_expansion_amendment_03_holdout.md`.
S4.5-S4.8 remain unstarted.

## Historical verdict at the v5 checkpoint

**FIT B IN PROGRESS / TAKE 35 NOT ALLOCATED / CAPTURE PROHIBITED UNTIL THE
PROSPECTIVE BATTERY-POWER CORRECTION AND ADDITIVE V5 EVIDENCE PACKAGE ARE
COMMITTED, VALIDATED, AND READINESS PASSES. S4.5 and later phases remain
unstarted.**

Amendment 03 prospectively permits same-calendar-date sessions and permits the
same Fit A, Fit B, or holdout session/group to continue across multiple
truthful local-date segments without creating a new session/group. It removes
any protocol-only restart/reconnection requirement. Each active date segment
still requires a separate truthful preflight and hash-bound no-media readiness
record. Fit B and holdout retain distinct session IDs, separate
preflight/readiness histories, and all live device, identity, format, storage,
privacy, clock, path, and access checks.

The committed v1 through v4 packages and Fit B takes 1-34 remain immutable.
This correction stays within `s4_4_data_expansion_amendment_03`: additive v5
binds every prior package and the exact first-34-attempt cutoff. That cutoff is
based on the 34 retained Fit B attempts and includes every Fit B date-segment,
preflight, readiness, and retained readiness-failure record present before
take 35; these records remain part of the single `fit_b` session/group. No
amendment_04, planned identity, scientific condition, or replacement rule is
created or changed.

The retained 2026-07-23 readiness failure consumed no attempt because its Pi
probe incorrectly targeted the already-used session capture root while Mac
SSH also timed out. The corrected no-media gate probes only
`S4.4/amendments/s4_4_data_expansion_amendment_03/captures/s44a03_fit_b_035_conf__attempt_01`
and binds the passed readiness hash to that exact next attempt. Attempt 35
remains absent and cannot be allocated from a stale or differently bound
readiness record.

Mac battery operation is now permitted prospectively, while readiness still
requires and retains the truthful power source, charging state, and battery
percentage. Missing or malformed power metadata remains fail-closed. The
operator explicitly authorized this narrow change after the v4 readiness
truthfully reported battery operation. Output volume was set to and verified
at the unchanged required 40%.

The logical matrix is 51 immutable inherited amendment_02 Fit A cells, 51 new
amendment_03 Fit B cells, and 47 new amendment_03 prospective-holdout cells,
for 149 total. The inherited Fit A census is 52 retained attempts, 51 valid
cells, one invalid protocol-quality attempt, and one valid replacement. The
failed and replacement attempts remain retained and no inherited replacement
allowance is reset.

This checkpoint is not a PASS. It becomes capture-eligible only after the
already-authorized local source and precollection-evidence commits, successful
post-commit gates, a real no-media Fit B readiness pass outside the restricted
sandbox, and physical operator confirmation. No push is authorized. Removing
day separation reduces protection against day and environment confounding and
must remain a reported scientific limitation.

## Precommit validation checkpoint

The focused amendment_03 suite passes 24 tests and focused lint passes before
the v4 source commit. Full repository, predecessor, build, release-source,
distribution, Kit, pack, ignore, raw-tracking, and deterministic v4 generation
gates must be rerun after the source and evidence commits.

Readiness, attempt allocation, and execution additionally require the complete
precollection package validator to pass with the evidence index and
`SHA256SUMS` tracked and byte-identical to `HEAD`. This keeps capture locked
between the source commit and the separately authorized evidence commit and
rejects altered future manifests before any network or attempt action.

No recorder, playback, ZED capture, scientific media, new attempt allocation,
restart, reconnect, or push occurred during this correction.
