# S4.5 supported functional fitting specification

## Status and authority

| Field | Frozen value |
| --- | --- |
| Phase | `S4.5` only |
| Contract | `ias.s4_5.fitting_contract.v1` |
| Entry branch | `main` |
| Entry revision | `45ec248296370de9be90a90cc01b74a484667380` |
| Configuration | `configs/s4_5_fitting.v1.json` |
| Fit evidence | Inherited amendment-02 Fit A and completed amendment-03 Fit B only |
| Holdout | Sealed; scientific access forbidden |
| Profile contract | Existing `ias.audio_calibration_profile.v1`, unchanged |

This specification freezes S4.5 before any real fit evidence is opened. It is
subordinate to `docs/final_sensor_development_plan.md`,
`docs/development/specs/s0_squadbot_readiness_acceptance.md`, and the sealed
S4.4 amendment-03 closeout. A contradiction fails closed.

S4.5 fits supported functional corrections. It does not apply a profile, freeze
acceptance criteria, open a holdout, evaluate a holdout, or package S4.8
results. S4.6 through S4.9 remain unstarted.

## Evidence and access boundary

The only scientific inputs are valid completed attempts belonging to:

- amendment-02 session `fit_a`, inherited in place by amendment-03; and
- amendment-03 session `fit_b`.

Access must pass the repository S4.5 accessor with purpose `S4.5_fit` or
`S4.5_validation`. The accessor validates the exact configured manifest hash,
planned identity, fit partition, session, leakage group, attempt outcome,
attempt path containment, attempt-local checksum set, manifest binding,
six-channel WAV identity, and WAV hash before returning a fit record.

Unknown or malformed purposes, identities, sessions, groups, paths, records,
hashes, or provenance fail closed. Prospective-holdout identities and paths
always fail for S4.5. Holdout validation is limited to byte size and SHA-256
and returns no media, metrics, fitted values, or content-derived result. No
S4.8 grant may exist.

The repository-tooling boundary cannot prevent direct reads by the filesystem
owner. S4.5 makes a repository-tooling enforcement claim only.

## Signal and coordinate conventions

- WAV capture is native six-channel, 16 kHz, signed 16-bit little-endian PCM.
- Channels 0 and 1 (`Conference`, `ASR`) are excluded from fitting.
- Raw channels 2 through 5 map in order to profile ids `ch0` through `ch3`.
- `ch0` (native raw microphone 0) is the relative reference channel.
- Gain is amplitude dB. A positive fitted correction increases a channel.
- Delay uses the S3.3 signed-lag convention. A positive observed lag means the
  candidate channel is later than `ch0`; the fitted correction is the negative
  grouped median observed lag.
- Polarity is a discrete multiplier. `-1` means invert the channel; `+1` means
  preserve it.
- Bearings are clockwise degrees from project `+X` toward `+Y` in
  `x_forward_y_right_z_up`.
- A positive bearing correction is added to an unadjusted bearing and wrapped
  to `[0, 360)`.
- Relative audio-video timing is audio time minus visible-impact time. A
  positive correction is added to audio timestamps.
- Microphone geometry is not fitted. Nominal public geometry, if carried into
  the partial profile, remains `nominal_not_measured`.

## Candidate parameters and identifiability

### Relative per-channel gain

For each non-reference raw channel, compute its robust active-signal RMS level
relative to `ch0` per authorized controlled/reference-WAV attempt. The
candidate is identifiable only with at least 12 usable observations, six
leakage groups, both Fit A and Fit B, and at least four distinct planned
bearing conditions. Silence, audio-video impacts, clipped windows, and
non-finite or effectively silent measurements are excluded with counts.

Fit on complete Fit A groups and validate on complete Fit B groups. If retained,
refit the final correction on all complete fit groups.

### Relative per-channel delay

Use the S3 GCC-PHAT signed-delay estimator against `ch0` on the same active raw
signals. Search is constrained to plus or minus 16 samples (1 ms at 16 kHz).
Identifiability counts are the same as relative gain. This parameter is a
functional relative correction and includes the tested acoustic/source/room
path; it is not isolated electronics delay or microphone geometry.

### Persistent major polarity anomalies

After compensating the fitted relative delay, use the signed normalized
cross-correlation peak against `ch0`. A channel is identifiable only when at
least 12 observations and six groups exist in both sessions, at least 90% of
eligible group medians have the same sign, and every leave-one-group-out fit
has that sign. A negative persistent sign yields correction `-1`; a persistent
positive sign yields `+1`. Otherwise polarity is omitted.

### Constant bearing or supported frame correction

Evaluate only if the fit evidence produces at least 24 labeled, non-abstained
observations across 12 leakage groups, both sessions, and at least six
distinct bearings, using the unchanged S3 estimator and a fixed pre-fit
microphone geometry. Retention additionally requires circular stability and
fit-only residual improvement. The value must be named a functional bearing
correction, never microphone geometry.

### Confidence behavior or calibration

Evaluate only if at least 40 labeled estimator observations across 20 groups
cover both correct and incorrect/abstained outcomes and the unchanged S3
confidence is available. A deterministic monotonic calibration may be retained
only if grouped Fit B Brier score improves without worse calibration error.
No data are manufactured to satisfy outcome diversity.

### Supported relative timing correction

Evaluate only from fit audio-video impact attempts with independently retained
audio and visible event timestamps. At least 12 impacts across six groups and
both sessions are required. Repository command time is not synchronization.

### Geometry and other fields

Microphone positions or optical/acoustic extrinsics require an independently
identified full-rank model, adequate pose diversity, condition number at most
100, and uncertainty smaller than the S4.1 physical measurement uncertainty.
The present contract does not authorize such a model, so geometry is omitted
from fitting and remains nominal/unmeasured.

Absolute SPL, absolute microphone sensitivity, isolated speaker response,
isolated microphone response, certified room acoustics, traceable acoustic
calibration, universal hardware/room transfer, and unsupported precision
extrinsics are always unsupported.

## Leakage-aware validation

The S4.4 `group_id` is indivisible. Repeated windows and attempts from one
group never cross a fitting/validation boundary. Fit A is the internal fitting
partition and Fit B is the internal validation partition. Failed attempts are
retained in the census but not used as measurements; only the final valid
attempt for a planned cell is eligible.

Final retained values use Fit A plus Fit B only after the Fit B decision is
complete. No later threshold or retention decision may use the final combined
residual to override a failed Fit B decision.

## Deterministic synthetic recovery

Every implemented candidate must pass known-truth recovery before real fitting:

| Candidate | Frozen fixture | Recovery tolerance |
| --- | --- | --- |
| Gain | 16 kHz bin-centred deterministic multitone, corrections `-6`, `-1.5`, `+3` dB | maximum absolute error `<= 0.05 dB` |
| Delay | 16,384-sample band-limited probe, delays `-3.25`, `-0.5`, `+0.5`, `+2.75` samples | maximum absolute error `<= 0.10 sample` (`6.25 us`) |
| Polarity | asymmetric finite probe with exact `+1` and `-1` multipliers | exact sign recovery |
| Bearing correction | wrapped labeled bearings with `+17.5 deg` truth | circular absolute error `<= 0.10 deg` |
| Confidence | fixed labeled probabilities with known monotonic distortion | deterministic coefficients and Brier improvement |
| Relative timing | fixed impact timestamps with `+12.5 ms` truth | absolute error `<= 0.10 ms` |

A candidate without an implemented passing synthetic fixture cannot be
retained.

## Residual, uncertainty, stability, and sensitivity criteria

For each continuous channel correction, compare Fit B residuals before and
after the Fit A correction.

- Median absolute residual must improve by at least 10%.
- Gain p95 absolute residual may worsen by at most `0.05 dB`.
- Delay p95 absolute residual may worsen by at most `0.10 sample`.
- The signed median residual after correction must be no farther from zero.
- Fit A and Fit B independently fitted estimates must differ by at most
  `0.75 dB` for gain or `0.75 sample` for delay.
- Deterministic grouped-bootstrap 95% uncertainty half-width must be at most
  `1.0 dB` for gain or `1.0 sample` for delay.
- Maximum leave-one-group-out shift must be at most `0.75 dB` for gain or
  `0.75 sample` for delay.
- At least 1,024 grouped bootstrap resamples use PCG64 seed `20260724`.

For polarity, at least 90% group-sign agreement and exact leave-one-group-out
sign stability are required. The uncertainty report is the disagreeing-group
fraction.

Bearing requires at least 10% median circular-error improvement, p95 worsening
no greater than `0.5 deg`, Fit A/Fit B correction difference at most `5 deg`,
95% grouped-bootstrap half-width at most `7.5 deg`, and leave-one-group-out
shift at most `5 deg`.

Relative timing requires at least 10% median absolute residual improvement,
p95 worsening no greater than `0.10 ms`, Fit A/Fit B difference at most
`2 ms`, uncertainty half-width at most `2 ms`, and leave-one-group-out shift
at most `2 ms`.

Confidence requires strictly better grouped Fit B Brier score, expected
calibration error no worse by more than `0.005`, deterministic coefficients,
and unchanged abstention semantics.

## Parameter decisions and omission

Each candidate decision records eligibility counts, groups, sessions,
constraints, synthetic status, Fit B residuals, grouped uncertainty,
leave-one-group sensitivity, stability, retained/omitted status, and a reason.
Every requirement must pass. A failure omits the parameter; S4.5 does not
weaken criteria after viewing fit results.

S4.5 is NO-GO if no scientifically useful non-reference continuous correction
or functional bearing/timing/confidence parameter is retained. Confirming only
the reference convention or unity polarity is not sufficient by itself.

## Partial calibration profile

The output must round-trip byte-identically through the existing reader/writer
and validate against the checked-in generated schema.

- Only retained per-channel gain, delay, and polarity values are `measured`.
- The reference zero gain/delay is `nominal_not_measured` because it is a
  convention.
- Unsupported channel fields have null/empty values as required by schema.
- Nominal public microphone geometry remains `nominal_not_measured` and is
  never described as fitted or measured.
- `fit_metrics` contains fit-only metrics.
- `holdout_metrics` is exactly empty.
- `raw_measurements` references authorized fit WAV paths and SHA-256 values;
  raw media remains ignored and untracked.
- Omitted candidate fields are absent from `fitted_model_parameters` and named
  in the limitations/unmeasured ledger.

## Determinism and provenance

Canonical JSON uses sorted keys, two-space indentation, UTF-8, one trailing
newline, finite numbers only, stable record ordering, fixed seeds, and a
frozen creation timestamp from the configuration. Identical configuration,
source commit, input paths, and hashes must reproduce byte-identical profile
and evidence files.

The evidence index binds the configuration, this specification, source commit,
input hashes, output hashes, tool version, environment, and reproduction
commands. `SHA256SUMS` covers every S4.5 evidence file except itself.

## Acceptance and stop conditions

PASS requires:

1. the pre-S4.5 authoritative S4.4 final validator passed;
2. frozen S4.4 bytes remain unchanged;
3. fit-only access and all negative cases pass;
4. every retained parameter passes synthetic recovery and grouped Fit B
   residual, uncertainty, stability, and sensitivity criteria;
5. at least one scientifically useful parameter is retained;
6. the partial profile round-trips and validates with empty holdout metrics;
7. deterministic evidence regeneration and checksum validation pass;
8. focused and repository-wide gates pass;
9. the holdout remains scientifically unopened, no S4.8 grant exists, raw
   media remains untracked, and S4.6 through S4.9 remain unstarted.

Otherwise S4.5 is NO-GO with exact blockers. A NO-GO does not authorize new
evidence, contract changes, holdout access, or later-phase work.
