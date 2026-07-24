# S4.5 corrective 01: fit-only channel-position binding and semantic validation

## Authority and immutable boundary

This additive corrective supersedes the scientific interpretation of the
original S4.5 package without changing or deleting any original S4.4 or S4.5
artifact. Its machine contract is
`configs/s4_5_corrective_01.v1.json`, schema
`ias.s4_5.corrective_contract.v1`.

The additive serialization-only amendment
`configs/s4_5_corrective_01_profile_frame_amendment.v1.json` assigns the
distinct public profile array-frame id `xvf3800_array_corrective_01`, whose
axes are functionally aligned to source frame `F_project` under the selected
binding. This is required by the unchanged public profile contract and changes
no hypothesis, coordinate value, threshold, decision rule, or scientific
result.

The additive package-location amendment
`configs/s4_5_corrective_01_package_location_amendment.v1.json` places the
superseding package at
`outputs/isaac_audio_sensors/S4/S4.5_corrective_01/`. Keeping it outside the
immutable original `S4.5/` root preserves the original validator's exact
non-recursive tracked-file contract. This changes no scientific content.

Only the already authorized Fit A and Fit B evidence may be opened through the
existing S4.5 accessor. Fit A is the development and hypothesis-selection
partition. Fit B is locked validation and cannot select a hypothesis, tune a
threshold, or become development data. Leakage groups remain indivisible.
Scientific holdout access is forbidden. S4.6 through S4.9, S5, and S6 remain
unstarted.

The original S4.5 PASS remains a packaging-valid historical record, but it is
scientifically superseded because it used nominal microphone positions
directly, omitted a required physical binding reconciliation, reported an
ambiguous observation count, lacked clipping eligibility, omitted bearing
uncertainty and sensitivity, overstated confidence synthetic recovery, and
validated duplicated claims mainly through schema and checksums.

## Falsifiable physical diagnosis

S4.1 verifies the native six-channel order as Conference, ASR, and raw
microphones 0 through 3. It records the four official nominal positions but
does not physically trace raw channel ids to acoustic inlets or measure the
array axes. S4.3 retained a limited diagnostic and authorized a proper
180-degree `F_array_nominal -> F_project` rotation. S4.5 then used the original
nominal positions directly.

Corrective 01 freezes four physically interpretable possibilities before
corrective implementation:

1. retain the original direct nominal binding;
2. apply only the authorized S4.3 180-degree proper rotation;
3. correct a front/back raw-channel-to-position assignment using the frozen X
   reflection of nominal inlet positions; or
4. reflect Y as the frozen handedness/mirroring alternative.

Arbitrary angles, unconstrained permutations, Fit B selection, post-hoc
thresholds, generic fitted reflections, scalar bearing offsets, and empirical
output formulas are forbidden.

Fit A alone selects hypothesis 3. It yields 5.5-degree median and 15-degree
nearest-rank p95/worst group error, while the original, 180-degree-only, and
handedness alternatives yield 81.5, 98.5, and 174.5-degree median errors. The
selected physical representation is the exact `ch0..ch3 -> F_project`
position binding in the machine contract. `F_project` remains right-handed;
the correction is not a mirrored project frame and not fitted microphone
geometry. The limited S4.3 record remains immutable historical evidence.

After this selection is frozen, the exact binding is evaluated unchanged on
Fit B. Reports must keep Fit A and Fit B separate and include group count,
median, p95, worst case, each bearing, front/back behavior, selected and
rejected hypotheses, and residual limitations.

## Inputs, counts, and fitting window

The canonical census is:

- 51 valid Fit A cells and 51 valid Fit B cells;
- 102 valid authorized cells;
- 85 eligible attempt-level measurements before leakage-group aggregation;
- 32 indivisible scientific groups, 16 Fit A and 16 Fit B; and
- zero holdout observations.

The superseding profile must use the explicit metric names and units frozen in
the machine contract. It must not call 102 an attempt count. The ambiguous
historical `fit_observation_count` is omitted from the superseding profile; its
historical meaning is documented as valid authorized fit cells.

The active fitting window remains start plus 2.25 seconds through the smaller
of capture end and start plus 7.25 seconds. On raw channels 2 through 5, any
decoded signed-16-bit endpoint code (`-32768` or `+32767`) excludes the entire
attempt before group aggregation. `-32767` and `+32766` remain eligible. The
threshold is representation-derived and may not be tuned from outcomes.
Exclusions are reported by split and reason.

## Candidate decisions and scientific gates

Relative gain, delay, and polarity reuse the original frozen grouped
Fit-A-development/Fit-B-validation gates. They are recomputed after clipping
eligibility. A positive scalar gain correction is not claimed to improve
SRP-PHAT bearing or confidence because PHAT normalization cancels positive
scalar amplitude.

The selected channel-position binding must have enough eligible groups and
bearings in both splits, improve the locked Fit B median by at least 10
percent, avoid p95 regression, keep the Fit A/Fit B median-error difference at
most 5 degrees, have deterministic grouped-bootstrap 95-percent half-width at
most 7.5 degrees, and have maximum leave-one-group-out median-error shift at
most 5 degrees. Bootstrap uses 1,024 PCG64 resamples and seed 20260724.
Missing or failed uncertainty or sensitivity omits the bearing binding.

Constant bearing correction is reevaluated only after applying the selected
binding and is omitted unless every original gate passes. Confidence
calibration requires at least 40 eligible labeled observations across 20
groups and both correct and incorrect/abstained outcomes. Timing requires
independent synchronized visible-event timestamps. Geometry requires an
independent full-rank model. Unsupported candidates record exact eligibility
counts and failed requirements; they do not receive fabricated numeric
uncertainty.

Noise/self-noise, frequency-dependent response, playback linearity,
AGC/compression, abstention thresholds, sector thresholds/confusion matrices,
absolute SPL/sensitivity, component-isolated response, certified room
quantities, precision extrinsics, and universal transfer remain outside S4.5.

## Synthetic and adversarial requirements

Synthetic recovery covers implemented gain, delay, polarity, bearing-binding,
and relative-timing estimators. Confidence synthetic evidence is an
ordering/smoke test only; it cannot claim calibration-model recovery. A
separate omission-gate test must prove that insufficient confidence outcome
diversity deterministically omits calibration. Clipped endpoint input must be
excluded and valid near-endpoint input retained.

The superseding validator must regenerate the canonical scientific package
from authorized evidence and compare it byte-for-byte before trusting its
checksums. Tests must mutate and re-checksum each of these and still fail:

- a retained gain, including `+99 dB`;
- a median residual or improvement;
- an observation or group count;
- a retained/omitted decision;
- missing bearing uncertainty;
- missing or failing bearing leave-one-group stability;
- the selected channel/frame mapping; and
- an unsupported candidate changed to supported.

## Additive outputs and acceptance

The package root is
`outputs/isaac_audio_sensors/S4/S4.5_corrective_01/`.
It contains the corrective contract record, authorized census, corrected
measurements and groups, physical hypothesis comparison, decisions,
uncertainty/sensitivity, clipping results, semantic validation report,
superseding `ias.audio_calibration_profile.v1` profile with identity/version
`respeaker_xvf3800_s4_5_functional_corrective_01`/`v2`, limitations,
preservation validation, provenance, deterministic reproduction, evidence
index, checksums, and closeout.

PASS requires the corrected binding, Fit B validation without Fit B selection,
all retained-parameter gates, semantic regeneration, deterministic replay,
complete provenance, byte-for-byte S4.4 and original S4.5 preservation, zero
holdout access, no later-phase artifact, and all applicable repository gates.
Gain-only partial profiles remain valid in principle, but do not cure a wrong
bearing binding. S4 is not SquadBot-ready until later preregistered application
and holdout phases pass.
