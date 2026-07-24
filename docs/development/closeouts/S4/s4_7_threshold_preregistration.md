# S4.7 functional acceptance preregistration closeout

## Final status

**PASS.** The held-out acceptance criteria are frozen, hash-bound to the only
unopened sealed holdout, and executable. Twenty-three readiness criteria gate
S4.8 and S4; six stretch criteria are frozen and reported without gating. No
held-out observation was opened, read, or summarised, and no access grant or
holdout-opening workflow was created.

The criteria are not prose alone. `core/acceptance_criteria.py` executes them
against a metrics payload and emits one deterministic verdict per criterion, so
S4.8 has no interpretive latitude over statistics, denominators, exclusions, or
failure logic.

`outputs/isaac_audio_sensors/S4/S4.7/holdout_acceptance.json` is the interlock
artifact. `acquisition/s4_4.py::consume_s4_8_grant` refuses to authorize any
holdout opening unless a grant is hash-bound to a file whose top level is
exactly `{"schema": "ias.s4_7.holdout_acceptance.v1", "status": "passed"}`.
That artifact records `authorizes_holdout_opening: false` and
`grant_still_required_for_s4_8: true`: it satisfies the prerequisite, it does
not open anything.

## Bound holdout and excluded holdout

| Binding | Value |
| --- | --- |
| bound holdout | `s4_4_data_expansion_amendment_03` prospective holdout, 47 takes, 15 groups |
| seal file SHA-256 | `dff1a520fd35bff4bdd0b9e1023d474544b7685360d087a32498757f8269528c` |
| seal payload SHA-256 | `e83e2a0c392850d581f7487423afa9a8844e1e4e595c47020f9b5b9bf3231024` |
| state at freeze | `scientifically_opened: false`, `technical_qa_only: true` |

The original six-cell S4.4 holdout
(`e0758b9820dac2f8ba0d07e2a17ad14a107abf1a11d408e813b034cfa03c13ec`) is
**excluded from gating** and retained as archived diagnostic evidence. Its own
policy records `historical_s4_3_outcomes_already_analyzed: true`, so it is not
blind and cannot support a held-out claim.

Blindness is attested and hash-bound, not physically enforced. The seal records
`filesystem_owner_reads_prevented_or_detected: false` and enforcement is
repository tooling only. What is claimed is that no S4.7 tool, test, or evidence
artifact reads a held-out observation, and that every threshold came from S4.3
pilot and S4.5 development-fit evidence.

## Envelope and strata

The claimed envelope is `controlled_source_single_room_single_mount`: one room
(`WANG_2022_DESK_NEAR_ENTRANCE`), one mount (`S4_TEMP_DESKTOP_FIXTURE_REV0`),
one controlled source at 0.8 m. Five disjoint strata cover exactly the 47
planned takes.

| Stratum | Takes | Geometry | Gates |
| --- | ---: | --- | --- |
| `A_controlled_boundary_sweep` | 24 | 8 bearings of the 22.5° family × 3, gain 0.75 | bearing error, candidate coverage, TDOA and bearing repeatability |
| `B_center_nominal_level` | 8 | 4 bearings of the 45° family × 2, gain 0.75 | sector accuracy, bearing error, confidence |
| `C_center_low_level` | 8 | same bearings × 2, gain 0.35 | confidence behavior relative to `B` |
| `D_silence` | 3 | ambient room silence | abstention |
| `E_impact_audio_video` | 4 | paper-roll impacts, no bearing reference | coarse audio-video association |

The primary gating statistic is the per-take median, so takes with unequal
window counts carry equal weight.

### Sector accuracy is gated only on stratum B

`core/doa/sector_mapping.py` centers the eight sectors on multiples of 45° with
±22.5° bounds. The 24 stratum-`A` bearings therefore fall exactly on sector
boundaries, where a sub-degree bearing error flips the reported sector by
construction; sector accuracy measured there would score estimator noise rather
than display correctness. The 45° family sits at sector centers with a full
22.5° margin and is the only geometry in this holdout where sector accuracy is
a meaningful decision. Stratum `A` still carries the continuous bearing-error
criteria, so no bearing evidence is lost.

## Threshold provenance

Every threshold came from development/fit and pilot evidence:

- S4.5 corrective closeout — adjusted Fit-B bearing median **3.79°** / p95
  **11.0°**; Fit-A median **5.5°** / p95 **15.0°**;
- S4.3 pilot controlled — median 2.0°, p95 8.0°, worst 82.0°; latency p95
  ≈ 0.05 ms; confidence median 0.0297; coarse AV uncertainty 37.3 ms;
- the already-frozen S4.3 gates in `configs/s4_3_pilot.v1.json` — reused
  unchanged for repeatability (20°), pair TDOA (125 µs), silence abstention
  (0.95), polarity anomalies (0), channel health failures (0), clip run (8).

Representative readiness thresholds: bearing median ≤ 15.0°, p95 ≤ 30.0°, worst
≤ 60.0° on `A`; sector accuracy ≥ 0.75 on `B`; candidate coverage ≥ 0.75;
take failure rate ≤ 0.10 against the **planned** denominator of 47; adjusted-sim
vs real median bearing difference ≤ 20.0°; and zero gating metrics classified
`worsens` by the S4.6 adjustment. The full register with one written decision
rationale per criterion is `criteria_register.json`.

The failure-rate denominator is the planned take count, so removing an
unfavorable take can never improve the rate.

## Not evaluable

The sealed holdout contains **zero robustness cells**. Alternate rooms and
mounts, phone and voice sources, occlusion, overlap, elevated noise, distance
and radius variation, moving sources, and endurance sessions all have a zero
denominator and are declared `not_evaluable`. Any robustness or wider-envelope
claim requires a new, previously unseen holdout under a new preregistration.

Absolute SPL, absolute microphone sensitivity, isolated speaker or microphone
response, certified reverberation, traceable calibration, precision
optical-acoustic extrinsics, live end-to-end capture latency, and universal
transfer remain unsupported and are never thresholded.

## Fail-closed coverage

`fail_closed_matrix.json` executes **30** cases at build time and records the
real rejection message for each; none is a stubbed assertion. They cover
missing, empty, non-finite, non-numeric, and malformed observables; counter
field-set, denominator, and range violations; grouped-series group-count and
type violations; a missing and an empty comparison set; undeclared observables;
malformed, unknown-band, non-boolean, and non-finite comparison records; eight
tampered-configuration cases including a configuration that declares the
holdout open, declares holdout access, or declares an opening workflow; and
three unsafe configuration paths.

A missing or malformed result is always a criterion failure or a rejected
evaluation. It is never a silent pass.

## Evidence and deterministic replay

The canonical package is `outputs/isaac_audio_sensors/S4/S4.7/`, 16 files, bound
to source commit `e4be6b1ff610b0353f7301d3da98c946f052caa6`.

```text
python3 scripts/replay_s4_7.py --canonical outputs/isaac_audio_sensors/S4/S4.7
```

A clean `git archive` checkout of the bound commit reproduces every byte. The
first replay attempt failed because the absolute-path fail-closed case recorded
this machine's repository root in its rejection message; that was fixed in
`e4be6b1` and is now guarded by
`test_no_evidence_file_embeds_a_machine_specific_path`.

The synthetic fixtures in `examples/s4_7/` prove the machinery executes. The
conforming payload passes all 23 readiness criteria while failing 4 of the 6
stretch criteria, which demonstrates the tiers are genuinely independent; the
violating payload fails 16 readiness criteria. Both are synthetic and contain
no held-out observation.

## Preservation and phase boundary

Tracked prior-phase trees are unchanged at the bound commit:

| Tree | SHA-256 |
| --- | --- |
| `S4.4` | `b079f2441f8c1a9c66d7d6fa9180b01a34ceb7a1be750c47db165afd2dc06caa` |
| `S4.5` family | `165c49b2f483a4ba9d258f86f368323ffbbee8389553b57b5cbe993f3b70b234` |
| `S4.6` | `3ce8e3075a2d7acd9dd78b380bb1af269cb7539d314131d2f62cd59d20320dc6` |
| public profile schema | `fb56c9024bfa16ce25a999ed8e2552ab19189459f44801f33edd9f0d75d1ff46` |

`dataset/` remains untracked and was not read.
`future_S4.7_or_S4.8_opening_workflow_implemented` remains `false` in the S4.4
amendment records, because the opening workflow is S4.8 work and S4.7
deliberately does not implement it. Nothing was created under the S4.4
amendment tree; the package lives at top level. No S4.8, S4.9, S5, or S6
artifact was created, and no push was performed.

## Validation results

```text
$ .venv/bin/python scripts/validate_s4_7.py --criteria-only
PASS: criterion_count=29, readiness_criterion_count=23,
      bound_holdout_id=s4_4_data_expansion_amendment_03_prospective_holdout,
      holdout_observations_accessed=0

$ .venv/bin/python scripts/validate_s4_7.py --require-tracked --require-committed
PASS: issues=[], file_count=16,
      source_commit=e4be6b1ff610b0353f7301d3da98c946f052caa6

$ .venv/bin/python scripts/replay_s4_7.py \
      --canonical outputs/isaac_audio_sensors/S4/S4.7
PASS: byte_identical=true, file_count=16, clean_source_archive=true

$ .venv/bin/python scripts/run_s4_7_preregistration.py \
      --metrics examples/s4_7/synthetic_pass_metrics.v1.json
PASS: readiness_passed=true, failed_gating_criteria=[]

$ .venv/bin/python scripts/run_s4_7_preregistration.py \
      --metrics examples/s4_7/synthetic_fail_metrics.v1.json
FAIL (expected): exit=1, 16 readiness criteria failed

$ .venv/bin/python scripts/validate_s4_6.py --require-tracked --require-committed
PASS: issues=[], S4.6 evidence unchanged

$ .venv/bin/python -m pytest tests/ -q
PASS: full suite green

$ .venv/bin/python -m ruff check .
PASS: All checks passed
```

## Local source commits

- `4d43f59` — Freeze S4.7 acceptance criteria
- `65aff63` — Implement S4.7 criteria evaluation
- `e4be6b1` — Keep S4.7 evidence machine independent

The closeout's own commit hash is reported outside this document, since the
document is part of that commit.

S4.7 is complete. S4 as a whole is not complete: S4.8 and S4.9 remain future,
separately gated work, and S4.8 still requires an explicitly authorized
single-use grant before any held-out observation may be opened.
