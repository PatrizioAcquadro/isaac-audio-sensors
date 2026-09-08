# 04.4 simulation qualification

This is an active, isolated qualification tool, not a public plugin. Candidate
code receives only mixture samples, ordered valid-channel geometry and sample
rate. Truth, source assets, propagation and matching belong to the evaluator.
The canonical protocol and rationale are in the
[04.4 experiment](../../../knowledge/wiki/experiments/04-4-multisource-localization.md).

From the repository root, with the existing `.[dev,room]` environment:

```bash
.venv/bin/python tools/qualification/doa_04_4/bootstrap.py
OPENBLAS_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.evaluate --split evaluation --output final-evaluation.json
.venv/bin/python -m pytest -q tests/integration/test_multisource_qualification.py
```

Bootstrap downloads evaluation assets and builds ODAS locally under
`build/qualification/doa/04_4/`. It does not install system packages. This bootstrap
targets Ubuntu x86_64; development dependencies are extracted from downloaded
`.deb` archives. Other platforms need a separate native build setup. Network
access is needed for bootstrap only. Generated audio, native dependencies and
reports are ignored and excluded from the package.

`final_protocol.json` records the criteria and settings fixed before evaluation.
The runner refuses to overwrite an output report. Never tune on `evaluation`;
use `development`, and reserve `confirmation` for a later correction informed by
final failures. New independent speech assets are needed after those partitions
are consumed. Reported RT60 is the image-source generator's target, not a
measured physical decay time. No current result qualifies real recordings.

ODAS is locally patched to remove per-instance `fftwf_cleanup()`: its global
cleanup invalidates plans still owned by other live modules. Individual plans
are still destroyed. The regression test exercises repeated windows and teardown
in a subprocess. Earlier native reports preceding this repair are superseded.

Use `--protocol tools/qualification/doa_04_4/confirmation_protocol.json` with
`--split confirmation` for the reserved confirmation protocol. The `diagnostics`
module accepts the same protocol and output arguments (split comes from the
protocol); `--controls-only` reports coherent and near-coincident stress inputs.
`--candidate NAME` restricts either runner to a protocol candidate without
changing its thresholds. Reports are never overwritten.

Current outcome is **NO-GO for integration**. Static `quality_status` alone is
insufficient: idle, compute and every transition must also pass. A missing
transition response is a failure. See the canonical experiment for measured
results and the next corrective work; the public perceiver remains unchanged.


The continued `verification` partition uses two new LibriSpeech test-clean
utterances (OpenSLR 12, CC BY 4.0; Panayotov et al.). Archive members and hashes
are recorded in `verification_assets.json`; bootstrap streams only the required
members. Use `verification_protocol.json` with `--split verification` to test
the regularized covariance-MUSIC correction. These inputs are never development
assets. Its rejection statistic is not a calibrated event confidence.


The later `validation`, `qualification`, and `assessment` protocols record
successive corrections on disjoint assets/cases. Every opened partition is now
consumed evidence. The latest assessment passes by itself; known-case regression
still blocks promotion. Review `promotion-decision.json` under the working
output directory. `admission` combines quality/idle/response gates and accepts
`--regression` to include previously observed failures. Its single-run result
alone must not be used as a general promotion decision.
