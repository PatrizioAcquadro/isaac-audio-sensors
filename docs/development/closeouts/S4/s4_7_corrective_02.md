# S4.7 corrective_02 closeout

## Verdict

**S4.7 corrective_02 PASS — ready for independent review before S4.8.**

This closes the additive corrective contract and its blind, synthetic
preregistration evidence. It does not authorize holdout opening, create or
consume an S4.8 grant, or start S4.8 or any later phase.

## Effective correction

The authoritative contract is
`configs/s4_7_holdout_acceptance.corrective_02.v3.json`. It preserves all 23
readiness and six stretch thresholds, the claimed envelope, scientific
eligibility, and the same unopened 47-take amendment-03 holdout and seal.

The evaluator now derives every real sim-real value from the matching
authenticated keyed take observations. Target, estimate, reported bearing
error, sector result, candidate result, failure status, TDOA error, abstention
counts, confidence, and AV residual cannot contradict their structured source
observations. Sector and candidate condition indicators are exactly 0 or 1.

The maximum clip run remains an independent maximum over 188 raw-channel
take records with the unchanged readiness threshold of eight samples.
Sustained clipping begins only at 4,000 consecutive samples and is counted over
exactly 47 takes.

## Evidence identity

Canonical package:

`outputs/isaac_audio_sensors/S4/S4.7_corrective_02/`

- source commit:
  `dec2f31d4868a79f3484da3e0d2d424ae14efd5f`;
- package `SHA256SUMS` SHA-256:
  `79ce288bd60c38b25b611ce7921c5dcbb9462427dba2be13e71fbacc86f1b6a1`;
- evidence-index SHA-256:
  `ba37750b212554623e47690e8bb4fbc1def8afa40b596b80856ad277e6ef227e`;
- canonical prerequisite SHA-256:
  `5409d10b456e002816889b27a6a4aadcf7b524e18e954075aabe6cdbbfd749ed`;
- effective criteria-register SHA-256:
  `eaf756d6100fe7ce8cd4f9df2b59932e05d2ee00ec877420fc1d2e93bf5999c0`;
- final-validation SHA-256:
  `94c871a68740ba3e96e9cd252d3c7354a1439bd064d78a5efe4235172d58b017`.

The evidence commit is resolved semantically by the prerequisite authenticator
as the Git commit containing the exact package bytes. The grant binding includes
that derived commit, the source commit, package-manifest hash, evidence-index
hash, and corrective contract identities without introducing a self-referential
commit hash into package bytes.

## Semantic authentication and replay

All 18 package files are exact-set checked. Every JSON report has a fixed v3
schema and exact required field set. Every passing prerequisite requires every
inner report to be semantically passing and cross-consistent for source, seal,
holdout, counts, phase state, and zero holdout access.

Tests reject wrong inner schemas, failed statuses, nonzero holdout access,
contradictory source/seal/count/phase data, and checksum-consistent committed
tampering. Clean-source replay from the bound source commit is byte-identical
across the complete package; a non-byte-identical package is rejected.

## Historical preservation

- S4.7 v1 remains exactly 16 files with `SHA256SUMS` SHA-256
  `795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53`.
- S4.7_corrective_01 remains exactly 18 files with `SHA256SUMS` SHA-256
  `de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676`.

Both manifests verify every listed file byte-for-byte.

## Phase boundary

- Holdout observations accessed: **0**.
- Holdout access grant created or consumed: **no**.
- S4.8, S4.9, S5, or S6 started: **no**.
- Push performed: **no**.
- Tag created: **no**.
