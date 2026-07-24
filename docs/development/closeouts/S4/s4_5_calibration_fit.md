# S4.5 supported functional fitting closeout

## Authoritative active-profile routing amendment

<!-- S4.5_ACTIVE_HANDOFF_AUTHORITY: outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json -->

The historical closeout below is preserved, but its v1 profile routing is
scientifically superseded. The authoritative S4.5 closeout is
`docs/development/closeouts/S4/s4_5_calibration_fit_amendment_01.md`.
The only S4.6 input authorized by S4.5 is the v2 profile together with the
active handoff resolved through
`outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json`. S4.6 has not
started.
That pointer binds
`outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json`.

## Final status

**PASS.** S4.5 retained three scientifically useful relative channel-gain
corrections and three supported no-anomaly polarity states. Every retained
decision passed the frozen deterministic synthetic-recovery, grouped Fit B
residual, stability, sensitivity, and uncertainty requirements. The resulting
partial `ias.audio_calibration_profile.v1` validates and round-trips through the
unchanged public reader/writer and schema.

S4.4 remains byte-for-byte preserved. The prospective holdout remains
scientifically unopened, no S4.8 grant exists, and no S4.6-S4.9 implementation
or artifact was created. S4.6 profile application was not started.

## Entry revision and environment

Work began from clean `main` at
`45ec248296370de9be90a90cc01b74a484667380`, synchronized with `origin/main`.
There were no pre-existing user changes. Ignored `TODO.md` was the first
repository modification and remained the local progress tracker.

The deterministic evidence was generated on Linux
`6.8.0-136-generic-x86_64`, Python 3.12.3, NumPy 2.5.1, using the repository
virtual environment and `ias_s4_5_fitter/1.0.0`. The fitting implementation,
tests, specification, and configuration are bound to source commit
`32fedd1991df650606fc0b44b35d906fc28fe330`.

## Frozen contract and fit-only provenance

The fitting contract was committed before any real fit at
`189ab3e`. It freezes the reference-channel convention, signs, units,
coordinate frames, constraints, leakage groups, synthetic cases, residual
criteria, grouped uncertainty, stability and sensitivity limits, omission
rules, and deterministic provenance requirements. No threshold was derived
from holdout results.

The workflow accepted only `S4.5_fit` and `S4.5_validation`. It authorized 51
inherited Fit A cells and 51 completed Fit B cells, represented by 104 retained
attempts including two retained failures and two replacements. It accessed
zero holdout attempts. The input bindings include:

- Fit A manifest SHA-256
  `f938c46b6ad6ad002c7da6c556d3eb0b555a24499f8da63d15b83664a423e35f`;
- Fit B manifest SHA-256
  `5f06c4b51583516a4a96d96d7230231f2437c784d253d158d6c061387194a74a`;
- inherited Fit A record SHA-256
  `2b9cb2a91a7c0a9a7af208631b9d3370e8cee887f842769e77fae417e3db9212`;
- holdout seal SHA-256
  `dff1a520fd35bff4bdd0b9e1023d474544b7685360d087a32498757f8269528c`;
- holdout closeout SHA-256
  `70f7b762c4d131533403d18fae1a1e2cc32db6ba79701740532d88b3781b38fc`.

Every WAV path was authorized, provenance-checked, and rehashed through the
fail-closed accessor before repository scientific tooling opened it. Unknown
purposes, identities, paths, groups, malformed records, altered hashes,
provenance mismatches, and holdout attempts fail closed. Repository tooling is
not an operating-system access boundary.

Repeated observations remained within their leakage groups. The scientific
fit used 32 indivisible controlled/reference group observations: 16 Fit A and
16 Fit B groups across eight bearings. Fit A was the fitting partition and Fit
B the grouped validation partition; combined Fit A and Fit B estimates were
produced only after the frozen Fit B decision.

## Retained parameters

Channel `ch0` remains the nominal reference with 0 dB relative gain, zero
relative delay, and positive polarity. The supported fitted corrections are:

| Parameter | Estimate | Deterministic grouped 95% half-width | Fit B median absolute residual, before to after | Improvement | Fit A/Fit B difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ch1` relative gain | -1.602086 dB | 0.181513 dB | 1.732947 to 0.469106 dB | 72.93% | 0.191217 dB |
| `ch2` relative gain | -1.279575 dB | 0.248717 dB | 1.208664 to 0.512110 dB | 57.63% | 0.080558 dB |
| `ch3` relative gain | -1.213586 dB | 0.153432 dB | 1.185442 to 0.429908 dB | 63.73% | 0.110818 dB |

The gain synthetic fixture recovered known truth with maximum absolute error
`1.7763568394002505e-15` dB against the frozen 0.05 dB tolerance. Each retained
gain also passed Fit B p95 non-regression, signed-median, between-session,
leave-one-group, group-count, observation-count, and bearing-coverage checks.

Channels `ch1`, `ch2`, and `ch3` each retained polarity multiplier `+1`. All 32
groups agreed for every channel, the deterministic synthetic fixture recovered
both positive and negative polarity truth, and the disagreeing-group fraction
was zero. These decisions mean no persistent major polarity anomaly was found;
they do not manufacture a non-default correction.

## Omitted candidates

- Relative delay for `ch1`, `ch2`, and `ch3` passed synthetic recovery but
  produced zero median residual improvement. Their grouped 95% uncertainty
  half-widths were 1.796875, 2.921875, and 1.171875 samples, all above the
  frozen 1-sample bound. `ch2` also failed p95 and signed-median checks; `ch3`
  failed the signed-median check.
- Bearing correction was omitted. Its candidate value of -31.956977 degrees
  did not reduce the 85-degree median validation error and was unstable between
  Fit A and Fit B. It is not interpreted as microphone geometry.
- Confidence calibration was omitted because one confidence observation per
  leakage group did not establish an independently validated probability model
  with outcome-diverse grouped calibration evidence.
- Relative timing correction was omitted because the authorized fit manifests
  do not expose independently synchronized visible-impact timestamps.
- Microphone geometry was omitted because no independently identified
  full-rank geometry model is available. Geometry remains
  `nominal_not_measured`.

Absolute SPL, absolute microphone sensitivity, isolated speaker or microphone
response, certified room acoustics, traceable acoustic calibration, universal
hardware/room transfer, and precision optical/acoustic extrinsics remain
explicitly unsupported and contain no invented fitted values.

## Partial calibration profile

`outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json` is a
deterministic partial `ias.audio_calibration_profile.v1`. It contains only the
supported relative gains, polarity states, fit-only metrics, uncertainty,
provenance, raw-measurement references, and the applicability envelope.
`holdout_metrics` is empty. Unsupported fields are null, empty, nominal, or
unmeasured as required by the unchanged schema.

The profile applies only to ReSpeaker serial `114993701261100454` at 16 kHz,
fixture `S4_TEMP_DESKTOP_FIXTURE_REV0`, environment
`WANG_2022_DESK_NEAR_ENTRANCE`, and the MacBook source placements represented
by Fit A and Fit B. It is a functional correction for that tested
source-room-sensor path, not a traceable or universally transferable acoustic
calibration.

## Evidence and reproducibility

The package under `outputs/isaac_audio_sensors/S4/S4.5/` contains the fit
inventory and source hashes, frozen contract, authorized-attempt census,
synthetic recovery, grouped measurements and residuals, retained/omitted
decisions, uncertainty and sensitivity, limitations, partial profile,
preservation validation, provenance, reproduction record, evidence index, and
`SHA256SUMS`.

An independent regeneration into
`/tmp/ias-s4-5-replay-UCl63B` was byte-identical to the canonical package.
All 15 checksum-manifest records passed. The profile passed schema validation
and a reader/writer round-trip. The S4.5 validator passed both package and
preservation checks.

## Exact validation commands and results

Before creating S4.5 artifacts:

```text
.venv/bin/python scripts/validate_s4_4_amendment_03_final.py --repo-root . --require-tracked --require-committed --require-machine-local --require-corrective
PASS: 149 valid cells, 152 retained attempts, 3 failures, 3 replacements, 0 incomplete; holdout scientifically unopened
```

Generation and deterministic replay:

```text
.venv/bin/python scripts/run_s4_5_fitting.py --source-commit 32fedd1991df650606fc0b44b35d906fc28fe330 --output outputs/isaac_audio_sensors/S4/S4.5
.venv/bin/python scripts/run_s4_5_fitting.py --source-commit 32fedd1991df650606fc0b44b35d906fc28fe330 --output /tmp/ias-s4-5-replay-UCl63B
diff -rq outputs/isaac_audio_sensors/S4/S4.5 /tmp/ias-s4-5-replay-UCl63B
sha256sum -c SHA256SUMS
PASS: byte-identical replay; 15 of 15 checksum records OK
```

Validation and repository gates:

```text
.venv/bin/python scripts/validate_s4_5.py --evidence outputs/isaac_audio_sensors/S4/S4.5
PASS: package and S4.4 preservation; holdout unopened; S4.6 unstarted

PYTHONPATH=. .venv/bin/pytest -q tests/test_s4_5_fitting.py
PASS: 20 passed

make test
PASS: 1424 passed, 80 skipped

make lint
PASS: all checks passed

make check-version
PASS: version-sync 1.10.0

make build
PASS: sdist and wheel built; distribution audit passed

git diff --check
PASS
```

The 80 skips are the repository's documented optional dependency, Isaac,
hardware, and retained-fixture skips; no S4.5 test was skipped. Historical
S4.4 tests whose contract requires “S4.5 unstarted” run through a test-only
pre-S4.5 snapshot fixture. Production S4.4 validators were not weakened or
modified.

## Preservation and phase boundary

The S4.5 preservation validator re-ran the authoritative S4.4 final validator,
accepted only the expected legitimate S4.5-presence findings, and rejected all
other historical issues. It verified the frozen S4.4 census and bytes,
scientific holdout blindness, no scientific outcomes returned by the
historical validator, no S4.8 grant, no tracked `dataset/`, and no S4.6-S4.9
artifacts. Raw recordings and privacy-sensitive media remain untracked.

No evidence was collected, recollected, replaced, discarded, or rewritten.
Nothing was pushed. S4.6 was not started.
