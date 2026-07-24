# S4.4 amendment 03 prospective-holdout closeout

## Final status

Fit B is complete. The prospective holdout is complete, technically sealed,
and scientifically unopened. Acquisition is closed; no recollection is
required. The corrective software source is committed at
`ea043e962a54bdec8cc87e6913ff4162a1ee1dc5`; the additive corrective index,
source checkpoint, checksum manifest, and final-gate record bind that source
without rewriting the frozen v1-v5 packages or `SHA256SUMS.closeout`. S4.4
Amendment 03 is complete. S4.5-S4.8 remain unstarted.

## Acquisition and seal

The frozen amendment_03 prospective-holdout manifest was collected in its
original 47-cell order under session ID `prospective_holdout`. The completed
logical census is 51 inherited Fit A cells, 51 Fit B cells, and 47 prospective
holdout cells: 149 valid logical cells in 152 retained attempts.

Cell 27 attempt 01 is retained as the one holdout technical/protocol failure
after the operator reported extraneous-person entry and noise contamination.
Cell 27 attempt 02 is its valid replacement. Together with the immutable Fit A
and Fit B histories, the final aggregate contains three failures and three
replacements, with no second failure in any logical cell.

All 152 attempt-local `SHA256SUMS` sets pass when `sha256sum -c SHA256SUMS`
is executed from the corresponding attempt directory: 52 Fit A, 52 Fit B, and
48 holdout attempts.

The prospective holdout is sealed and scientifically unopened. Only allowlisted
technical QA and hash-only integrity were used. No holdout media was played
back for scientific review, no scientific metric or outcome was exposed, and
no opening workflow was implemented.

The tracked additive closeout records are:

- `holdout_seal.v1.json`, SHA-256
  `dff1a520fd35bff4bdd0b9e1023d474544b7685360d087a32498757f8269528c`;
- `holdout_evidence_index.v1.json`, SHA-256
  `64eb73923f6f4d0e7f1bdeac9a03400c7b488062dacd67587ccc411806c5160c`;
- `holdout_closeout.v1.json`, SHA-256
  `70f7b762c4d131533403d18fae1a1e2cc32db6ba79701740532d88b3781b38fc`;
- `holdout_hash_only_integrity.v1.json`, SHA-256
  `687ef2b35b377249b3010a2229f8c4377aaba893209740d78fbfd087a4108e06`;
- `immutable_predecessor_proof.v1.json`, SHA-256
  `91e058b84695928da5610600d8351e83a013703f1ca96addbf2898b359c5ad10`.

The current corrected bytes are bound separately by
`corrective_01/source_checkpoint.v1.json`,
`corrective_01/corrective_index.v1.json`, `corrective_01/SHA256SUMS`, and
`validation/final_closeout_corrective_01.v1.json`. These records are additive;
they do not replace or reinterpret any historical checksum manifest.

The machine-local access ledger remains separate from the original S4.4,
amendment_02, Fit A, and Fit B access histories. Blindness claims and access
histories were not merged. Repository tooling is fail-closed but does not
provide OS-level protection against direct filesystem-owner reads.

## Scope boundary

Amendment_01, amendment_02, amendment_03 v1-v5, inherited Fit A, and completed
Fit B remain immutable. This closeout is additive within amendment_03; it is
not amendment_04 or a v6 precollection package. S4.5, S4.6, S4.7, and S4.8
remain unstarted. The corrective does not authorize capture, recollection,
scientific holdout opening, or later-phase work.

## Final acceptance

**PASS.** The exact active amendment_03 validator passes against the frozen v5
package with 55 tracked artifacts and the completed machine-local census: 152
retained attempts, 149 valid logical cells, three failures, three
replacements, zero incomplete cells, and no second failure. Amendment_02 and
both original S4.4 final validators pass without exposing scientific outcomes
or opening a holdout.

The outcome-blind final-closeout validator passes all 152 attempt-local
checksum sets (52 Fit A, 52 Fit B, and 48 holdout), all 47 holdout
technical-QA records, both holdout seals and their bindings, the access-ledger
hash chain, all 360 evidence-index records, closeout records, immutable
predecessors, and the exact final census. Its 20 focused tamper tests pass.
Historical Git-blob verification passes 230 v1-v5 and closeout checksum
records. The additive corrective checksum/index binds corrected current files
separately; no frozen checksum manifest was rewritten.

The historical 85-valid-cell cutoff test uses an isolated fixture, while the
completed-state test verifies 149 valid cells and 152 retained attempts from
the explicit machine-local final gate. Full tests pass with 1,397 passed and 80
documented optional/hardware skips. Lint passes. Version 1.10.0 and
release-source checks pass at
`ea043e962a54bdec8cc87e6913ff4162a1ee1dc5`. Distribution audit passes for a
453-file sdist and 137-file wheel; Kit audit passes for 138 files. The
lock-matching `/tmp/ias-s4-3-wheelhouse-Yqs1Oh` acoustic-pack build and 8-file
audit pass.

`git diff --check`, ignore checks, raw-media tracking checks, and later-phase
absence checks pass. `dataset/` and `TODO.md` remain ignored, no dataset path is
tracked, no S4.4 raw media is tracked, and S4.5-S4.8 remain unstarted.
