# S4.4 amendment 03 prospective-holdout closeout

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

The machine-local access ledger remains separate from the original S4.4,
amendment_02, Fit A, and Fit B access histories. Blindness claims and access
histories were not merged. Repository tooling is fail-closed but does not
provide OS-level protection against direct filesystem-owner reads.

## Scope boundary

Amendment_01, amendment_02, amendment_03 v1-v5, inherited Fit A, and completed
Fit B remain immutable. This closeout is additive within amendment_03; it is
not amendment_04 or a v6 precollection package. S4.5, S4.6, S4.7, and S4.8
remain unstarted. No push is authorized.

## Final acceptance

The final gate report is recorded separately after the additive closeout
evidence commit. Amendment PASS requires every repository gate to pass while
the final amendment_03 census remains 149 valid cells and the prospective
holdout remains sealed and scientifically unopened.
