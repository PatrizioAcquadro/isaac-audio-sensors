# S4.3 amendment 01 - installed-array analysis-frame correction

Status: **frozen before additional S4.3 capture** on 2026-07-21.

This amendment supplements, and does not rewrite,
`docs/development/specs/s4_3_pilot_repeatability.md` and
`configs/s4_3_pilot.v1.json`. Their initial freeze, the failed preflight, the
quality-valid unfavorable analysis, and all raw evidence remain immutable.
The effective amended configuration is the strict overlay
`configs/s4_3_pilot_amendment_01.v1.json`.

## Trigger and evidence

The first quality-valid baseline recording returned a median SRP-PHAT bearing
of `280 deg` in the identity-applied nominal microphone coordinates versus the
frozen canonical `F_project` reference of `90 deg`. Median absolute error was
`170 deg`; sector accuracy and candidate coverage were zero. This activates
the frozen `analysis_contradiction` and `unresolved_bearing_or_sector_decision`
triggers. No threshold, raw waveform, physical source pose, or acceptance
criterion was changed.

The retained diagnostic at
`outputs/isaac_audio_sensors/S4/S4.3/diagnostics/bearing_frame_contradiction_20260721T185522Z.json`
shows that rotating the nominal microphone coordinates `180 deg` about `+Z`
maps the S4.3 baseline median to `100 deg` with `10 deg` median and `14 deg`
worst error. The same transform independently maps the previously retained
S4.2 front impact from `194 deg` to `14 deg`. Synthetic known-direction tests
for the estimator pass, while pre-S4.3 rig records explicitly classified the
physical raw-channel/inlet and acoustic-axis mapping as unmeasured.

## Frozen correction

The functional analysis correction is:

```text
p_project = Rz(180 deg) * p_array_nominal
bearing_project = (bearing_array_nominal + 180 deg) mod 360
```

It is classified **Measured functional correction** for this exact installed
fixture. Acoustic-axis uncertainty remains **Unmeasured**. This is not a
precision extrinsic, calibrated channel-to-inlet survey, or transferable
ReSpeaker orientation claim. `F_operator_facing_zed` and `F_project`, their
origin, and their operator-to-project conversion are unchanged.

The original `analysis.json` remains the authoritative record of the v1
analysis. A separate immutable `analysis_amendment_01.json`, provenance record,
and checksum manifest may be produced from the same raw WAV under the amended
configuration. Reanalysis must not alter the original file, raw evidence,
thresholds, or attempt lifecycle.

## Frozen expansion

Exactly one confirmation trial is added:
`s4_3_rpt_baseline_01_confirm_array_frame_01`. From the operator's viewpoint
while standing in front of and facing the ZED, the Mac remains on the
operator's left at `F_operator_facing_zed (0.00,-0.90,-0.135) m`, bearing
`270 deg` (canonical `F_project (0.00,+0.90,-0.135) m`, bearing `90 deg`).
Every capture variable remains identical to the baseline; only the declared
analysis-frame correction changes.

This is one confirmation for one triggered cell, within the original maximum
of one confirmation per cell and three added trials total. If the confirmation
does not satisfy the original bearing, sector, candidate, quality, and
repeatability criteria, the contradiction becomes terminal and S4.3 narrows
or fails; no further orientation tuning is permitted from these results.

The effective matrix therefore contains 12 trials: four repeatability, two
controlled, and six robustness. S4.4 remains unstarted.
