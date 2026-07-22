# S4.4 data-expansion amendment 01 closeout

## Current verdict

**INCOMPLETE / NO PASS DECLARATION. S4.5 and all later S4 phases remain unstarted.**

The prospective matrix, schemas, access controls, validators, and precollection
evidence are implemented. Physical collection has not begun. The exact source
checkpoint was committed after explicit user authorization; operator capture
remains prohibited until the generated evidence package is delivered in the
separate authorized local evidence commit and every commit-bound gate passes.

## Precollection checkpoint

The precollection implementation was committed on branch `main` as source
checkpoint `f1a45cf` (`f1a45cfcbfe991cf92de605270004c93b08fbeb2`) from starting
commit `63f321a0bfdd0a828650388d2586cf1900bebfa4`. The package is bound
to that exact checkpoint, truthfully declares `committed` and
`collection_allowed: true`, and is delivered alongside this document in the
separate evidence-delivery commit. No push was authorized or performed.

Exact preregistered counts are 102 fit, 47 prospective holdout, and 149 total.
Fit A and Fit B each contain 32 controlled, 12 confidence, 3 silence, and 4
audio-video cells. The holdout contains 24 controlled, 16 confidence, 3
silence, and 4 audio-video cells. Session dates remain null until the operator
records the three actual distinct calendar days.

Current deterministic hashes are:

- original historical SplitPlan payload SHA-256:
  `1569c00cbaec57e5625e0876fd243e17a2a67b287b3edf9865e41bb7ce8c0ce3`;
- fit partition manifest payload SHA-256:
  `239edcc25dc08adfb6a15de619d836d7a4776f5c0390f42a4cc03de7f6eb11f2`;
- prospective-holdout partition manifest payload SHA-256:
  `2306264d3d1258ec86d73883e87d1c1ac841d1e15c7d5d4301660a8d28fec5e8`;
- aggregate-index payload SHA-256:
  `b88079b4a60e273d96ce7156bd0c78105c243f2d7ae78ff59c7d131c6dbc8bed`;
- precollection-seal file SHA-256:
  `bec44c6c4968c7043f03e3fdc15771e979e2ae6a6534eb71a577797ac76434a2`;
- source-checkpoint file SHA-256:
  `42bffca6c19ab0e69ca7825a57f3a9524310689ddf893058fa1e46d1ce6806dd`.

Two isolated builds produced byte-identical trees and summaries. The amendment
clean-checkout validator passed 25 indexed artifacts twice. Focused amendment
tests pass 27/27; combined amendment/original S4.4/grouped-split tests pass
64/64; the original final tracked S4.4 validator still passes 20 artifacts with
`holdout_opened: false`. Repository results are `make test`: 1,342 passed and
80 expected optional/hardware skips; `make lint`: PASS; `make check-version`:
PASS at 1.10.0; `make build`: PASS; `make audit-dist`: PASS for a 426-file sdist
and 136-file wheel; `git diff --check`: PASS.

After evidence delivery, committed-provenance and tracked amendment validation
passed 26 indexed artifacts, and the original final S4.4 validator passed its
20 historical artifacts. Focused amendment/original/grouped-split tests passed
64/64. `make check-release-source`, `make check-version`, `git diff --check`,
`make test` (1,342 passed and 80 expected optional/hardware skips), `make lint`,
`make build`, and `make audit-dist` all passed. The final distribution contains
a 426-file sdist and a 136-file wheel. The required post-build artifact order
also passed: `make build-kit`/`make audit-kit` validated 137 files, and
`make build-pack WHEELHOUSE=/tmp/ias-s4-3-wheelhouse-Yqs1Oh`/`make audit-pack`
validated the 8-file locked acoustic pack. No raw/private file is tracked, the
original S4.4 byte set remains unchanged, the prospective holdout is
scientifically unopened, and no S4.5, S4.6, S4.7, or S4.8
directory/workflow/grant exists.

## Required completion evidence

PASS requires two distinct-day fit sessions containing 102 valid planned cells,
a separate third-day prospective-holdout session containing 47 valid planned
cells, all attempts and failures retained, no cell exceeding one replacement,
no second-failure NO-GO, passing clean-checkout and machine-local validation,
the prospective holdout technically sealed and scientifically unopened, a
valid separate access ledger, unchanged original S4.4 bytes, and every required
repository gate.

Until those conditions are met, this document is a truthful checkpoint and not
a completed S4.4 amendment closeout.
