# S4.4 data-expansion amendment 03 checkpoint

## Current verdict

**PRECOMMIT IMPLEMENTATION COMPLETE / SOURCE-COMMIT AUTHORIZATION REQUIRED /
CAPTURE PROHIBITED. S4.5 and later phases remain unstarted.**

Amendment 03 prospectively permits same-calendar-date sessions and removes any
protocol-only restart/reconnection requirement while retaining truthful
dates/timestamps, distinct session IDs, separate Fit B/holdout preflight and
readiness gates, and all live device, identity, format, storage, privacy,
clock, path, and access checks.

The logical matrix is 51 immutable inherited amendment_02 Fit A cells, 51 new
amendment_03 Fit B cells, and 47 new amendment_03 prospective-holdout cells,
for 149 total. The inherited Fit A census is 52 retained attempts, 51 valid
cells, one invalid protocol-quality attempt, and one valid replacement. The
failed and replacement attempts remain retained and no inherited replacement
allowance is reset.

This checkpoint is not a PASS. It becomes capture-eligible only after explicit
authorization for the separate local source and precollection-evidence
commits, successful post-commit gates, a real no-media Fit B readiness pass
outside the restricted sandbox, and physical operator confirmation. No push
is authorized. Removing day separation reduces protection against day and
environment confounding and must remain a reported scientific limitation.

## Precommit validation checkpoint

The focused amendment_03 suite passes 19 tests. The full repository suite
passes 1,370 tests with 80 expected optional/hardware skips. Lint, version
sync, deterministic double-generation, JSON Schema instance validation,
amendment_03 live inherited-inventory validation, frozen amendment_01 and
amendment_02 validation, original final S4.4 validation, distribution build
and audit, and whitespace checks pass. The built distribution contains a
446-file sdist and 137-file wheel.

Readiness, attempt allocation, and execution additionally require the complete
precollection package validator to pass with the evidence index and
`SHA256SUMS` tracked and byte-identical to `HEAD`. This keeps capture locked
between the source commit and the separately authorized evidence commit and
rejects altered future manifests before any network or attempt action.

The clean release-source check remains intentionally fail-closed because the
new amendment_03 sources have not been committed. The Kit and acoustic-pack
builders enforce the same clean-source boundary; after the distribution build
cleared `dist/`, their audits truthfully report that no post-build archives
exist. Those gates must be rerun only after explicit source-commit
authorization. No readiness command, device state change, recorder, playback,
ZED capture, scientific media, attempt allocation, commit, or push occurred.
