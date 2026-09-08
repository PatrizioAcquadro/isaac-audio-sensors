# 04.4 simulation qualification

This is an active qualification tool. The selected MUSIC computation is shared with the optional common event localizer; experimental alternatives remain isolated. Candidate
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

The original broad-domain outcome remains **NO-GO**. The prospective `reference_protocol.json` passes for bounded direct-path scalar integration and enables 07.2 after the consumer/GPU checks. Static `quality_status` alone is
insufficient: idle, compute and every transition must also pass. A missing
transition response is a failure. See the canonical experiment for measured
results and the next corrective work; the public opt-in 16 kHz perceiver now returns actual event sequences within the documented scope.


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

The `reference` partition uses 16 new speakers in `reference_assets.json` and eight repetitions. Its 1,728-case report, independent diagnostics and applicable known-case regression pass all four geometries without changing the algorithm or numerical gates. Combined reverberant failures remain characterized outside this bounded integration domain; original reports are unchanged. `reference-admission.json` admits the candidate scope, while `phase04_4_lab_live_smoke.json` under `build/validation/isaac_audio_sensors/` verifies actual GPU consumers. All partitions are now consumed evidence.

For the subsequent paired indoor-utility development study:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.progressive --output progressive-baseline.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.progressive --output progressive-loading.json --loading 0.0001 --loading 0.001 --loading 0.003 --loading 0.01 --stage direct --stage room_030 --stage combined
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.progressive --output progressive-distance.json --stage direct --stage room_030 --distance 0.5 --distance 1
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.progressive --output progressive-power.json --stage direct --stage room_030 --stage combined --refit-statistic mean --threshold 0.005
```

Existing reports are preserved; use a new output name when rerunning. Every
report records the actual comparison settings. Counts and stage variations of an
episode belong to the same development partition. Measured T20 and direct/reflected
energy supplement the target RT60; none is a physical validation. The unchanged
reference remains available, but room-only failures prevent a general indoor
claim. No tested correction is promoted. Rejected selection and NARA-WPE probes
are preserved beside their ignored reports, not installed into the SDK.

The subsequent project-level comparison tests longer causal dereverberation
history while retaining the exact current 250 ms mixture. Its optional dependency
stays outside the SDK/environment:

```bash
.venv/bin/python -m pip install --no-deps --target build/qualification/doa/04_4/wpe_deps nara-wpe==0.0.11 click==8.1.6
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.dereverberation --output progressive-wpe-history.json
```

This explicitly tests the NumPy implementation on CPU. The report includes the
500/750 ms history settings and composed compute; direction estimation still
uses only the trailing 250 ms. None of these settings is currently admitted.
The project-level priority is further indoor sensing work before 07.2, despite
the already available bounded scalar reference.

For the next isolated indoor comparison, use the recorded candidate parameters
and joint conditions in `indoor_protocol.json`:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src .venv/bin/python -m tools.qualification.doa_04_4.indoor --output indoor-comparison-new.json --repetitions 1 --stage direct --stage room_030_level_0 --stage room_030_level_6
```

Omitting the restrictions runs the complete development protocol. This consumes
existing development assets; it is not an independent confirmation. The DP-RTF
and SRP implementations contain explicit adaptations described in the canonical
experiment. Neither is currently admitted into common perception.
