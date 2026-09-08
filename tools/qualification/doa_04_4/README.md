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
`build/qualification/doa/04_4/`. It does not install system packages. On Ubuntu,
missing development dependencies are extracted from downloaded `.deb` archives;
other systems need the ODAS build prerequisites already available. Network
access is needed for bootstrap only. Generated audio, native dependencies and
reports are ignored and excluded from the package.

`final_protocol.json` records the criteria and settings fixed before evaluation.
The runner refuses to overwrite an output report. Never tune on `evaluation`;
use `development`, and reserve `confirmation` for a later correction informed by
final failures. New independent speech assets are needed after those partitions
are consumed. Reported RT60 is the image-source generator's target, not a
measured physical decay time. No current result qualifies real recordings.
