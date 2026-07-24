# S4 held-out functional acceptance preregistration

## Status and authority

This specification freezes the S4.7 acceptance criteria that S4.8 will be
judged against. It is written and frozen **before any held-out observation is
opened**, and it is additive: it changes no S4.1-S4.6 artifact, no S4.5
scientific decision, and no `ias.audio_calibration_profile.v1` field.

The machine-readable criteria are `configs/s4_7_holdout_acceptance.v1.json`,
validated by `docs/schemas/s4_7_holdout_acceptance.v1.schema.json`. Where this
prose and the configuration could be read differently, the configuration is
authoritative, because the configuration is what the frozen evaluator executes.

S4.7 writes criteria only. It does not open, read, analyse, or summarise any
held-out observation; it does not create an access grant; and it does not
implement a holdout-opening workflow. Opening the holdout is S4.8 work and
still requires an explicitly authorized single-use grant validated by
`isaac_audio_sensors.acquisition.s4_4.consume_s4_8_grant`, which refuses to
proceed unless it is hash-bound to an S4.7 artifact whose top level is exactly
`{"schema": "ias.s4_7.holdout_acceptance.v1", "status": "passed"}`.

## Sealed holdout binding and blindness

The criteria are bound to exactly one sealed set: the
`s4_4_data_expansion_amendment_03` **prospective holdout** of 47 planned takes
in 15 leakage groups.

| Binding | Value |
| --- | --- |
| seal | `outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03/holdout_seal.v1.json` |
| seal file SHA-256 | `dff1a520fd35bff4bdd0b9e1023d474544b7685360d087a32498757f8269528c` |
| seal payload SHA-256 | `e83e2a0c392850d581f7487423afa9a8844e1e4e595c47020f9b5b9bf3231024` |
| partition manifest SHA-256 | `377c53d868dea4a89329a925763734da6a38920c7246821c902807c1667e0320` |
| session manifest SHA-256 | `587c7ff093f086f304e12a7e55459bf8b19d326132cd0550c7218b6cf38c84d3` |
| state at freeze | `scientifically_opened: false`, `technical_qa_only: true` |

The original six-cell S4.4 holdout
(`outputs/isaac_audio_sensors/S4/S4.4/holdout_seal.json`, file SHA-256
`e0758b9820dac2f8ba0d07e2a17ad14a107abf1a11d408e813b034cfa03c13ec`) is
**excluded from gating**. Its own access policy records
`historical_s4_3_outcomes_already_analyzed: true`, so it is not blind and
cannot support a held-out claim. It is retained as archived diagnostic
evidence with no gating power.

Blindness limitations are stated rather than overclaimed. Enforcement is
repository tooling only; the seal itself records
`filesystem_owner_reads_prevented_or_detected: false`. What is claimed is that
no S4.7 tool, test, or evidence artifact reads a held-out observation, and that
every threshold below was chosen from development/fit and pilot evidence alone.

## Envelope

The claimed envelope is `controlled_source_single_room_single_mount`, which is
exactly what the sealed holdout contains:

- room `WANG_2022_DESK_NEAR_ENTRANCE`; mount `S4_TEMP_DESKTOP_FIXTURE_REV0`;
- device `respeaker_xvf3800_114993701261100454` at 16 kHz, raw channel order
  `raw_microphone_0..3`; source frame `F_project`;
- controlled source: `MacBookPro18,1` built-in speakers playing the frozen
  reference WAV at playback gain `0.75` or `0.35`, at radius `0.8 m`;
- four visible-audible `plain_paper_roll` impacts and three ambient-silence
  takes.

**Every gating criterion is a controlled-source criterion.** The sealed holdout
contains no robustness cell, so S4.8 produces, claims, and gates no robustness
result. This narrows the S4 claim and is stated as such rather than papered
over.

## Strata and denominators

Five disjoint strata cover exactly the 47 planned takes. The primary gating
statistic is the **per-take median**, so that takes with unequal window counts
carry equal weight; window-level `count`, `median`, `p95`, and `worst` are
reported alongside every criterion.

| Stratum | Takes | Geometry | Gates |
| --- | ---: | --- | --- |
| `A_controlled_boundary_sweep` | 24 | 8 bearings of the 22.5° family × 3 reps, gain 0.75 | bearing error, candidate coverage, TDOA and bearing repeatability |
| `B_center_nominal_level` | 8 | 4 bearings of the 45° family × 2, gain 0.75 | sector accuracy, bearing error, confidence |
| `C_center_low_level` | 8 | same 4 bearings × 2, gain 0.35 | confidence behavior relative to `B` |
| `D_silence` | 3 | ambient room silence | abstention |
| `E_impact_audio_video` | 4 | paper-roll impacts, no bearing reference | coarse audio-video association |

### Why sector accuracy is gated only on stratum B

`core/doa/sector_mapping.py` centers the eight sectors on multiples of 45° with
±22.5° bounds. The 24 stratum-`A` bearings therefore fall **exactly on sector
boundaries**, where a sub-degree bearing error flips the reported sector by
construction. Sector accuracy measured there would score estimator noise rather
than display correctness. The 45° family in strata `B` and `C` sits at sector
centers with a full 22.5° margin, and is the only geometry in this holdout
where sector accuracy is a meaningful decision. Stratum `A` still carries the
continuous bearing-error criteria, so nothing is lost by this split.

## Statistics

Frozen definitions, reused from the existing S4.3 conventions so that no new
estimator semantics enter at acceptance time:

- **median** — arithmetic median of the finite values; the mean of the two
  central values when the count is even.
- **p95** — deterministic nearest rank: the ascending value at one-indexed
  position `max(1, ceil(0.95 * n))`.
- **worst** — maximum of the finite values. **range** — maximum minus minimum.
- **rate** — numerator over denominator, where the denominator must equal the
  frozen expected count whenever one is declared.
- **circular range** — the S4.3 largest-gap convention on bearings modulo 360.
- Any statistic computed from fewer than eight samples is labeled
  `small_sample` in the report. The threshold comparison is unchanged; the
  label exists so a small denominator is never mistaken for a strong result.

## Readiness tier — binding

S4.8 passes for the claimed envelope only when **every** criterion below
passes. Thresholds were chosen from the S4.3 pilot and the S4.5 development
fit; the adjusted Fit-B development bearing was median 3.79° / p95 11.0°, and
the weaker Fit-A was median 5.5° / p95 15.0°.

| Criterion | Stratum | Rule |
| --- | --- | ---: |
| median absolute bearing error | A | ≤ 15.0° |
| p95 absolute bearing error | A | ≤ 30.0° |
| worst absolute bearing error | A | ≤ 60.0° |
| median absolute bearing error | B | ≤ 15.0° |
| sector accuracy | B | ≥ 0.75 |
| candidate coverage at 20° tolerance | A+B | ≥ 0.75 |
| within-cell bearing circular range | A, 8 cells | ≤ 20.0° |
| within-cell pair-TDOA range | A, 48 cell-pair groups | ≤ 125 µs |
| `frame_to_adapter_round_trip_ms` p95 | all | ≤ 5.0 ms |
| `capture_to_frame_offline_ms` spread | all | ≤ 25.0 ms |
| raw channel health failures | all, 188 records | = 0 |
| major polarity anomalies | all, 188 records | = 0 |
| takes with sustained clipping | all | = 0 |
| maximum clip run | all | ≤ 8 samples |
| take failure rate | all, denominator 47 **planned** | ≤ 0.10 |
| silence abstention rate | D | ≥ 0.95 |
| active abstention rate | A+B | ≤ 0.10 |
| median SRP confidence | B | ≥ 0.015 |
| directions emitted below the 0.015 floor | all | = 0 |
| median confidence(C) − median confidence(B) | C vs B | ≤ 0.0 |
| worst coarse AV association residual | E | ≤ 50.0 ms |
| adjusted-sim vs real median bearing difference | A+B | ≤ 20.0° |
| gating metrics worsened by the adjustment | all | = 0 |

Each threshold carries a written decision rationale in the configuration. The
recurring justification is that SquadBot needs a bearing good enough to turn
toward the correct half-plane and an eight-sector display decision that is
right more often than not, and that Alex needs the same sector decision to
drive a visible turn. Absolute SPL, metrological frequency response, certified
reverberation, traceable calibration, and precision extrinsic thresholds are
not required and are not set.

The take failure-rate denominator is the **planned** count of 47. Removing an
unfavorable take can therefore never improve the rate.

## Stretch tier — reported, never gating

Frozen now so that a strong result can be claimed without a post-hoc
threshold: bearing median ≤ 5.0° and p95 ≤ 12.0° on `A`; sector accuracy
≥ 0.90 on `B`; candidate coverage ≥ 0.95 on `A+B`; active abstention ≤ 0.02;
adjusted-sim vs real median bearing difference ≤ 5.0°. A failed stretch
criterion changes nothing about the gate.

## Sim-versus-real criteria

S4.8 compares three paths over the identical geometric conditions: **real**
holdout audio, **unadjusted simulation** (the S4.6 application in mode `off`),
and **adjusted simulation** (mode `apply`).

Each comparison is classified `improves`, `preserves`, or `worsens` using the
frozen preserve bands — bearing ±2.0°, rates ±0.05, TDOA ±25 µs, confidence
±0.005, latency ±1.0 ms, association ±5.0 ms. A change smaller than the band is
`preserves`; a change beyond the band is `improves` or `worsens` by its sign.

Two criteria gate. The adjusted simulation must land within 20.0° of the real
median bearing error, and **no** gating metric may be classified `worsens`
relative to the unadjusted path. An adjustment that degrades a gating metric is
not readiness evidence, whatever it does to the others.

No sim-versus-real comparison harness exists in the repository at freeze time.
S4.8 builds it against these criteria; the criteria are not adjusted to fit
whatever the harness turns out to produce.

## Not evaluable, and unsupported

The following have a **zero holdout denominator**. S4.8 reports them as
`not_evaluable` and may not compute, threshold, or claim them for this
envelope: alternate rooms; alternate mount fixtures; phone and voice sources;
occlusion; source overlap; elevated background noise; distance and radius
variation; angle families other than the two frozen sweeps; moving sources or
a moving array; long-duration endurance sessions.

Any robustness or wider-envelope claim requires a new, previously unseen
holdout under a new preregistration. It may never be obtained by
reinterpreting this holdout.

Permanently unsupported and never thresholded: absolute SPL, absolute
microphone sensitivity, isolated speaker response, isolated microphone
response, certified reverberation, traceable calibration, precision
optical-acoustic extrinsics, live end-to-end capture latency, and universal
transfer.

## Missing and unsupported treatment

Evaluation fails closed. A missing observable, a non-finite value, or a
denominator that does not match its frozen expected count is a **criterion
failure**, never a pass and never a silent skip. An unexpected observable is a
configuration error that rejects the whole evaluation. A `not_evaluable`
condition is reported as `not_evaluable` and is never counted as a pass.

## Failure logic and immutability

A failed readiness criterion keeps S4.8 and S4 **failed** for the claimed
envelope. The failed evidence is archived and remains useful for diagnosis.

After this freeze the following are prohibited: selecting or changing any
threshold from held-out results; refitting any S4.5 parameter; removing,
replacing, or reweighting a scenario or take; shrinking a denominator to the
successful count; reclassifying a failed criterion as `not_evaluable`; and
narrowing the envelope to convert a failure into a pass.

A narrower envelope proposed after a failure requires new preregistered
criteria and a new, previously unseen holdout. The original failed evidence is
retained.

## Evidence and phase boundary

The canonical package is generated under
`outputs/isaac_audio_sensors/S4/S4.7/` from the exact implementation commit. It
records the criteria register, strata and denominators, holdout binding, the
blindness attestation, the not-evaluable declaration, the sim-versus-real
criteria, the executed fail-closed matrix, preservation and phase boundaries,
provenance, the reproduction command, final validation, an evidence index, and
a SHA-256 manifest. It also emits `holdout_acceptance.json`, the interlock
artifact that a future S4.8 grant must bind to.

A clean checkout of the bound implementation commit must reproduce the package
byte-for-byte in a temporary directory.

S4.7 does not open holdout data, create an access grant, implement a holdout
opening workflow, run S4.8, package S4.9, or start S5/S6. S4 remains incomplete
until S4.8 and S4.9 pass.
