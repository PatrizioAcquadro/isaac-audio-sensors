# S4.3 Pilot Repeatability and Functional Characterization Closeout

## Verdict

**S4.3: FAIL. S4.4 readiness: NO-GO.** S4.4 was not started.

The retained pilot's scientific acceptance and corrected evidence validation
pass, but the final repository gate is fail-closed because the review
remediation is intentionally uncommitted and `make check-release-source`, the
Kit build, and the acoustic-pack build cannot validate a dirty source tree.
One local provenance commit and clean-source rerun are required before S4.3 can
return to PASS or S4.4 can return to GO. This remains functional engineering
characterization of the installed reference rig, not acoustic metrology.

The remediation baseline is clean commit
`91baa3a03742f4efd21e0a145e59774c18952c1c` on `main`; the corrected working
tree is not committed. The active immutable preregistration remains
`outputs/isaac_audio_sensors/S4/S4.3/freeze/preregistration_amendment_04.json`
(SHA-256
`6a2012e6bc22608d5495877c38068963f9c9b816c51d4fbc25b5765521f356ba`).
The frozen matrix SHA-256 is
`3872b3ebd7aa6f29d2fe48e60b38e75b8014f598b0b814e3f2f1439bbb7901e8`.
The post-trial provenance-only review record is
`outputs/isaac_audio_sensors/S4/S4.3/freeze/review_remediation_manifest.json`.
It binds the corrected implementation while recording that the matrix,
scientific thresholds, retained raw evidence, and S4.4 boundary did not change.

## Review remediation

The prior 22-contract count-only coverage check was replaced by metric-specific
validation. Every metric now verifies concrete required outputs, counts,
applicability, complete accepted-trial coverage, and exact raw-channel,
spectral-band, directed-pair, unique-pair, and relative-delay cardinalities.
The reports now include candidate-count and nearest-candidate-error
distributions; per-attempt channel presence/order/health and per-channel RMS,
peak, and clipping summaries; explicit noise-threshold-exceedance results; and
the complete coarse audio-video association plus full SVO2 replay.

Abstained windows are excluded from numeric bearing-error, TDOA, TDOA-error,
relative-delay, candidate-count, and nearest-candidate-error distributions.
They remain in sector and candidate denominators as incorrect/uncovered. Four
non-abstained voice-confirmation windows had explicit null least-squares
solutions; these are now counted as missing solver results rather than silently
dropped or treated as absent evidence. The SRP-PHAT primary estimates remain
numeric for those windows. The repeatability gate now enforces the frozen
`raw_channel_health_failure_count_max = 0`; the observed count is 0.

Regression coverage includes a positive complete 22-metric fixture and one
negative missing-output case for every metric, plus dedicated abstention,
partial-pair, raw-channel-health, noise-transient, immutable-freeze, and
provenance-manifest tests. No scientific threshold was changed.

## Coordinate and analysis frames

Every operator instruction used `F_operator_facing_zed` first. While the
operator stands in front of and faces the ZED, +X is behind the operator/in
front of the ZED, +Y is operator-right, and +Z is up. The canonical software
frame remains `F_project`, with
`x_project=x_operator`, `y_project=-y_operator`, `z_project=z_operator`, and
`bearing_project=(-bearing_operator) mod 360`.

The baseline MacBook was therefore on the operator's left at
`F_operator_facing_zed (0.00,-0.90,-0.135) m`, bearing 270 degrees, represented
canonically as `F_project (0.00,+0.90,-0.135) m`, bearing 90 degrees. All
contradictory and superseded S4.2/S4.3 correction records remain retained. The
additional 180 degree `F_array_nominal` to `F_project` bearing correction is
classified **Measured functional correction** with unmeasured acoustic-axis
uncertainty; it is not precision extrinsic calibration.

## Frozen matrix and actual outcomes

| Category | Frozen cells | Terminal cells | Accepted analyses | Failed attempts |
| --- | ---: | ---: | ---: | ---: |
| Repeatability | 4 | 4 | 4 | 1 preflight failure before accepted retry |
| Controlled | 2 | 2 | 2 | 0 |
| Robustness | 8 | 8 | 7 | 1 failed occlusion confirmation |
| **Total** | **14** | **14** | **13** | **2** |

There were 15 physical acquisition attempts. Every planned, accepted, failed,
unfavorable, and superseded record remains in the inventory. No result was
removed because it was inconvenient. The three allowed expansions were the
array-frame confirmation, one occlusion confirmation, and one voice-timing
confirmation. Expansion capacity is exhausted and the stopping rule is
terminal.

## Main results

### Within-configuration repeatability

Four identical installed-rig reference trials produced trial median canonical
bearings of 100, 92, 90, and 90 degrees against the 90 degree reference. Trial
median absolute errors were 10, 2, 0, and 0 degrees; the trial-median circular
range was 10 degrees. Sector accuracy and candidate coverage were 100 percent
for each trial, with no abstentions or major polarity anomalies. Frozen gates
also passed for TDOA trial-median range, relative raw-channel RMS range, and all
spectral-band trial-median ranges. These are **Measured** within-configuration
results for this exact Mac/WAV/volume/pose/room/rig/mount setup.

### Controlled directions

- Front: 39 windows, median error 0 degrees, p95/worst 2 degrees, 100 percent
  sector accuracy and candidate coverage, no abstention.
- Opposite side: 39 windows, 38 non-abstained, median bearing 264 degrees
  against 270 degrees, median error 6 degrees, p95 8 degrees, and worst 82
  degrees. The prior 84 degree numeric worst belonged to the abstained window
  and is now excluded from the numeric distribution. Sector and candidate
  coverage were 94.87 percent with one abstention. The poor tail is retained
  and limits any claim based only on central error.

### Robustness

- Silence: all 103 windows abstained. Median/p95/worst raw RMS were
  0.00450/0.00516/0.00576 full scale. This is room-plus-fixture-plus-sensor
  functional noise, not microphone self-noise SPL.
- Occlusion: the accepted two-box take had 39 windows, 2 degree median error,
  76 degree p95/worst error, 56.41 percent sector/candidate coverage, one
  abstention, and median confidence 0.0179. The operator reported possible
  extraneous noise. The single frozen confirmation then failed quality because
  only one raw channel contained the complete reference at correlation at
  least 0.03, where two were required. The failure is retained. This supports
  only one-object/one-placement sensitivity evidence, not a repeatable or
  universal occlusion transfer claim.
- Voice: the first accepted lifecycle was operationally uninformative because
  the cue arrived 12.51 seconds into a 15 second capture; all 103 windows
  abstained. The frozen timing confirmation detected 25 of 103 windows, with
  median detected bearing 90 degrees, 75.73 percent overall abstention, and
  corrected 23.30 percent overall sector/candidate coverage because all 78
  abstentions are now incorrect/uncovered even when legacy analysis retained a
  candidate. Numeric detected-window bearing error was 2 degree median, 4
  degree p95, and 30 degree worst. Voice localization is intermittent in this
  tested condition.
- Overlap: 39 windows, median error 2 degrees, worst 4 degrees, 100 percent
  sector/candidate coverage, and no abstention for the deterministic reference
  in the tested overlap.
- Rear-near: 39 windows, median error 0 degrees, worst 2 degrees, 100 percent
  sector/candidate coverage, and no abstention.
- Impact: 15 windows, 7 detections and 8 abstentions; detected-window
  median/p95/worst error was corrected to 18/64/64 degrees. Overall sector
  accuracy was corrected to 40 percent and candidate coverage to 26.67 percent
  because every abstention is incorrect/uncovered. Relative decay reached -10
  dB in 125 ms and did not reach -20 dB within the 875 ms observation. This is
  combined event-room-fixture-sensor decay, not RT60.
- Coarse audio-video association: the unique audible impact peak at audio
  sample 180783 was associated with reviewed ZED frame 286. The measured
  elapsed-origin offset was -1.7652525 s with 37.311 ms RSS uncertainty, below
  the frozen 50 ms maximum. Full 602-frame SVO2 replay passed. This supports
  coarse association only, not clock synchronization, absolute capture
  latency, or acoustic time of flight.

Across accepted trials, trial-median offline capture-to-frame values were about
254.07 to 255.14 ms and the worst retained window was 263.61 ms. Trial-median
frame-to-adapter round trips were about 0.0218 to 0.0310 ms and the worst was
0.0604 ms. These are local offline functional measurements. Six-channel format,
declared order, device identity, raw-channel presence/health, channel-relative
RMS/delay, TDOA, spectra, confidence, ambiguity, abstention, and polarity data
are reported with complete counts, medians, MAD, nearest-rank p95, and worst
cases in the category reports. All 14 captured attempts had complete passing
six-channel evidence; the retained pre-recorder failure is explicitly not
applicable. Captured raw-channel health failures were 0 and the largest clip
run was 15 samples, below the existing 4,000-sample sustained-clipping rule. No
major persistent polarity anomaly was observed.

The intended-silence raw interval had 119 complete frozen windows and all 119
exceeded the already frozen 0.002 full-scale median-RMS detector threshold,
while all 103 central SRP analysis windows still abstained on confidence. This
is an unfavorable but retained result: the threshold-exceedance rate was 7.933
windows/s for this overlapping-window definition. It is not an event count,
absolute self-noise, or SPL measurement.

## Evidence classification and claim boundary

| Quantity | Classification | Boundary |
| --- | --- | --- |
| Device serials, channel contract, formats, hashes, complete SVO2 replay | Verified | Applies to retained evidence and declared hardware only. |
| DOA/TDOA, relative level/spectrum/delay, confidence, abstention, latency, noise, decay, and coarse AV results | Measured | Functional results in the tested pilot; no calibrated absolute reference. |
| Array-to-project 180 degree correction | Measured functional correction | Supported by retained directional evidence; acoustic-axis uncertainty remains Unmeasured. |
| Rig frame geometry inherited from S4.1 | CAD-derived or Measured as labeled in the frame lock | Not precision optical/acoustic extrinsics. |
| Nominal microphone geometry and 343 m/s propagation speed | Nominal | Used only for functional expected-TDOA comparison. |
| Absolute SPL, sensitivity, isolated responses, certified reverberation, traceable calibration | Unmeasured/Unsupported | No claim is made. |
| Transfer beyond the tested sources, room, poses, distances, mount, and devices | Unsupported | Requires later grouped development and held-out evidence. |

Nearest-rank p95 values have small denominators and are descriptive pilot tails,
not population estimates. Firmware and SDK versions in S4.3 impact evidence are
provenance metadata; serial, capture configuration, timestamps, USB operation,
producer integrity, corruption checks, and complete replay remained hard gates.
Mac AC/battery and the dynamic-preflight aggregate status are metadata only;
output device, channels, sample rate, volume, mute, reference integrity,
placement, audio quality, hardware identity, and privacy remained hard gates.

## Retained failures

1. `s4_3_rpt_baseline_01_20260721T185113Z_b8ad55a0` failed before recording
   because the restricted process could not resolve the existing Pi helper
   host. Read-only elevated SSH verified the frozen helper and the accepted
   retry; the original failure remains inventoried.
2. `s4_3_rob_occluded_01_confirm_noise_01_20260721T200909Z_2825cefe` failed
   analysis because only one raw channel contained the complete reference above
   the frozen correlation threshold; two were required. No third take was
   collected.

The original unfavorable pre-amendment 280 degree baseline analysis, the voice
timing failure, the operator's possible-noise report, every amendment, and all
superseded coordinate records are preserved.

## Validation

The corrected uncommitted working tree produced:

- targeted S4.3 tests: 62 passed;
- S4.3 evidence build: 14/14 terminal, 13 accepted analyses, 2 retained failed
  attempts, repeatability PASS;
- deterministic replay: 13/13 accepted analyses passed;
- machine-local validation: 15/15 attempts passed;
- raw-independent validation and metric-specific 22-metric evidence coverage:
  PASS;
- pre-closeout integrity: 289 indexed artifacts, including 245 machine-local
  records, with zero issues;
- `make test`: 1269 passed, 80 expected optional-dependency/hardware skips;
- `make lint`, `make build`, `make check-version`, `make audit-dist`, targeted
  S4.3 integrity, and `git diff --check`: PASS;
- `make check-release-source`, `make build-kit`, and controlled-wheelhouse
  `make build-pack`: correctly FAILED because the remediation is uncommitted;
- `make audit-kit` and `make audit-pack`: FAILED because the dirty-source
  builders correctly produced no new archives;
- final `--require-final` integrity: FAIL until the repository gate and
  repository validation can pass on a clean committed source.

The blocker outcomes are retained in
`outputs/isaac_audio_sensors/S4/S4.3/validation/repository_validation.json`;
they must be replaced by clean-source passes after an authorized local commit.

## Evidence and retention

- Evidence index:
  `outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json`
- Repository gate:
  `outputs/isaac_audio_sensors/S4/S4.3/repository_gate.json`
- Trial inventory:
  `outputs/isaac_audio_sensors/S4/S4.3/trial_inventory.json`
- Failures:
  `outputs/isaac_audio_sensors/S4/S4.3/failures.json`
- Repeatability, controlled, robustness, and repeatability gate:
  `outputs/isaac_audio_sensors/S4/S4.3/reports/`
- Deterministic, machine-local, raw-independent, coverage, integrity, and
  repository validation:
  `outputs/isaac_audio_sensors/S4/S4.3/validation/`

All 245 raw/privacy-sensitive files (185 MiB at closeout) remain machine-local
under gitignored `dataset/S4.3/`; `git ls-files dataset/S4.3` is empty. The
tracked evidence contains manifests, results, hashes, validation records, and
reports, not raw WAV or SVO2 media. The machine-local dataset is the only copy
confirmed by this closeout; no independent backup or durability guarantee is
claimed.

S4.4 remains untouched and is NO-GO while the remediation provenance blocker
remains. After a clean-source finalization, any restored GO remains conditional
on preserving these limitations, using leakage-relevant grouping, and freezing
development/fit and held-out conditions before final tuning.
