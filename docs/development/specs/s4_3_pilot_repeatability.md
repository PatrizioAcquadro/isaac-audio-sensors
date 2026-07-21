# S4.3 pilot repeatability and functional characterization specification

Status: **frozen before S4.3 trial collection** on 2026-07-21. The
machine-readable authority is `configs/s4_3_pilot.v1.json`; immutable hashes
for this document, that configuration, and its embedded matrix are recorded in
`outputs/isaac_audio_sensors/S4/S4.3/freeze/preregistration.json` before any
S4.3 recorder is started or result is accepted.

Two pre-capture freezes were superseded and retained on 2026-07-21 while the
operator/project viewpoints were reconciled. The operator confirmed the S4.2
MacBook was physically on the operator's left while facing the ZED:
`F_operator_facing_zed (0,-0.90,-0.135) m`, bearing `270 deg`, which converts
to canonical `F_project (0,+0.90,-0.135) m`, bearing `90 deg`. The current
authority is `s4_2_dual_frame_coordinate_reconciliation.v1.json`; no S4.3
recording existed when either freeze was superseded.

This specification implements only S4.3 from
`s0_squadbot_readiness_acceptance.md`. It reuses the passed S4.2 acquisition,
timing, integrity, privacy, and machine-local retention contracts. It does not
select development/held-out groups, seal data, fit a calibration profile, or
start S4.4.

## 1. Claim boundary and evidence vocabulary

S4.3 is functional engineering characterization of the exact installed
`S4_TEMP_DESKTOP_FIXTURE_REV0`, ReSpeaker serial `114993701261100454`, MacBook
source, practical placements, and WANG 2022 workstation area. Controlled
results support only the frozen positions and range. Robustness results are
descriptive observations and do not enlarge the controlled envelope.

Every quantity is labeled **Verified**, **Measured**, **CAD-derived**,
**Nominal**, **Approximate**, **Unmeasured**, or **Unsupported**. In this phase:

- device identities, the six-channel format, and the documented channel map
  may be Verified;
- waveform-domain relative quantities and replay runtimes may be Measured;
- manufacturer microphone coordinates and 343 m/s sound speed are Nominal;
- practical source pose and angle references are Approximate;
- array acoustic-axis alignment uncertainty is Unmeasured; and
- absolute SPL, absolute microphone sensitivity, isolated speaker or
  microphone response, certified reverberation, traceable calibration,
  precision optical/acoustic extrinsics, live end-to-end latency, and universal
  transfer are Unsupported.

No functional result may be relabeled as metrology evidence. Combined spectral
and decay observations contain the source, room, fixture, ReSpeaker, firmware,
and analysis path together.

## 2. Frozen rig, acquisition, and analysis contract

All trials retain six-channel ReSpeaker audio at 16 kHz PCM S16_LE with channel
order Conference, ASR, raw microphone 0, 1, 2, 3. Raw-microphone analysis uses
channels 2-5 and the manufacturer-reported coordinates `(0.033,-0.033,0)`,
`(0.033,0.033,0)`, `(-0.033,0.033,0)`, and `(-0.033,-0.033,0)` m as Nominal.
The enclosure is practically aligned to `F_project`; its acoustic axes and
angular uncertainty are not physically measured, so bearing results retain
that limitation.

`F_project` uses the package and S4.1 convention: `+X` is ZED-forward, `+Y` is
right as viewed from the ZED (operator-left while facing the camera), and `+Z`
is up. Positive bearing is clockwise from `+X` toward `+Y` viewed from above.
Every physical instruction leads with `F_operator_facing_zed`: while standing
in front of and facing the ZED, +X is behind the operator/in front of the ZED,
-X is in front of the operator/behind the ZED, +Y is right, -Y is left, +Z is
ceiling/up, and -Z is floor/down. Convert by
`(x,y,z)_project=(x,-y,z)_operator` and
`bearing_project=(-bearing_operator) mod 360`. Machine-readable analysis uses
only the declared canonical `source_*` fields in `F_project`; the paired
`operator_source_*` fields are required and validated placement metadata.

Reference trials use the S4.2 deterministic WAV with SHA-256
`27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468`,
MacBookPro18,1 built-in speakers, `afplay -v 1.0`, system volume 40%, open lid,
and the unchanged room/fixture. A read-only dynamic preflight must confirm the
selected device, volume, mute, and power state before each reference capture.
No helper may change Mac audio, Focus, notification, privacy, firmware, device,
or other operator-controlled state.

Each retained attempt has an immutable unique directory below
`dataset/S4.3/attempts/`, normalized trial definition, lifecycle, recorder
readiness, stimulus record, raw/finalized files, semantic validation, analysis,
manifest, and checksums. A planned trial is never removed from inventory.
Rejected, interrupted, failed, unfavorable, and accepted attempts remain
listed. Raw/privacy-sensitive media remain gitignored and machine-local.

## 3. Frozen compact matrix

The exact matrix is embedded in `configs/s4_3_pilot.v1.json`. Counts below are
planned trials, not passing results.

| Category | Frozen trials | Purpose |
| --- | ---: | --- |
| Within-configuration repeatability | 3 | From the operator's viewpoint: same Mac on the operator's left at `(0.00,-0.90,-0.135) m`, 270 deg; canonical analysis `(0.00,+0.90,-0.135) m`, 90 deg; same WAV/40% volume, room, rig, mount, and settings. |
| Controlled variation | 2 | From the operator's viewpoint: move behind the operator/in front of the ZED at 0 deg, then to the operator's right at 90 deg; paired canonical bearings are 0 deg and 270 deg at 0.91 m practical radial distance. |
| Robustness | 6 | Silence; baseline reference with a declared rigid occluder; standardized unaided voice; voice overlapping the Mac reference; near-rear reference at the boundary-limited 0.40 m position; and one front visible/audible ordinary-object impact with ZED. |

The rear source is robustness evidence because the documented rear boundary
prevents the 0.91 m controlled distance. Voice wording must contain no name,
identifier, private information, or third-party copyrighted content. The
visible-impact scene must contain no person, hand, screen, private label, or
identifier in retained frames.

Recordings are reused across compatible metrics. There is no separate take per
metric. ZED capture is required only for the coarse audio-video association
trial. Absence of ZED from audio-only cells is declared not applicable, not a
missing pass.

## 4. Frozen metrics and detection policy

The configuration is normative for each metric's method, reference, units,
uncertainty, aggregation, exclusions, missing-data behavior, applicability,
and limitation. All applicable reports include sample/trial counts, median,
spread (MAD or range), p95 where meaningful, and worst case. With fewer than
20 samples, p95 is the deterministic nearest-rank observation and is labeled
small-sample, not a population percentile.

DOA uses existing SRP-PHAT over nominal four-microphone geometry on frozen
250 ms windows with 50% overlap and a 2 deg azimuth grid. GCC-PHAT provides
pair TDOA and the existing least-squares estimator provides a comparison.
Reference-active windows come from correlation with the deterministic WAV;
voice/impact windows use preregistered energy/transient selection; silence
uses the full central interval. A frame is signal-present only when raw-channel
median RMS exceeds 0.002 full-scale and SRP confidence is at least 0.015.
Otherwise it abstains. Confidence is an uncalibrated ordering, never a
probability. Confidence below 0.05 is reported as low-confidence ambiguity.

Capture-to-frame latency is the Measured offline replay path: frozen window
duration plus measured analysis runtime after the window is available.
Frame-to-adapter latency is deterministic frame-result JSON serialization and
round-trip time. Neither is live sensor/network/robot latency. Absolute capture
latency remains Unsupported.

## 5. Quality and repeatability acceptance

An attempt is quality-valid only if its declared modalities exist; hashes and
schemas pass; the exact device/channel/sample contract passes; duration is
within 0.25 s; required timestamps are monotonic; no raw channel is missing;
no unintended reference trial is silent; no channel has sustained clipping;
and reference trials contain the complete WAV with normalized correlation at
least 0.03 on at least two raw channels. Intended silence is not rejected for
being silent. ZED/SVO2 replay, frame correspondence, modality freshness, and a
50 ms maximum association uncertainty apply to the impact-AV trial only.

S4.3 repeatability passes only when all three planned baseline trials are
quality-valid and, over eligible reference-active windows:

- median SRP absolute bearing error is at most 30 deg and worst trial-median
  error is at most 45 deg;
- baseline exact eight-sector accuracy and 20 deg candidate coverage are each
  at least 2/3 by trial-median result;
- the circular range of baseline trial-median SRP bearings is at most 20 deg;
- each raw pair's trial-median GCC-PHAT TDOA range is at most 125 us;
- each raw channel's trial-median relative RMS range is at most 3 dB;
- each frozen spectral band's trial-median relative-energy range is at most
  6 dB;
- no raw channel is absent, persistently silent, sustained-clipped, or marked
  with a major polarity anomaly; and
- the silence trial abstains on at least 95% of analysis windows.

Controlled and robustness results are reported even when unfavorable. They do
not receive post-hoc thresholds. An acquisition or analysis failure never
vanishes from denominators or inventory.

## 6. Expansion, stopping, and failure handling

Expansion is permitted only for a quality failure, excessive baseline
variance, unresolved bearing/sector decision, analysis contradiction, or a
required claim left uncovered. Before any added capture, create a numbered
freeze amendment that defines its trial id, category, single reason, changed
fields, applicable metrics, and stopping effect; hash the amendment and updated
matrix. At most one confirmation trial may be added per triggered cell and at
most three added trials total. Exceeding that cap, needing an unplanned device
or room change, or being unable to resolve integrity is S4.3 NO-GO or a
narrowed claim requiring operator approval.

Stop after the base matrix when all planned trials have terminal outcomes,
quality/repeatability criteria pass, every required metric is reported with an
honest applicability/status, no expansion trigger remains unresolved, and an
added compatible trial would only duplicate an already stable result. If a
criterion fails, retain the evidence, correct only a proven setup/protocol bug
or narrow the claim, freeze the response before rerunning, and never tune a
threshold from the observed pilot.

## 7. S4.3 and S4.4 gate boundary

S4.3 PASS requires complete inventory, real hardware evidence, separated
repeatability/controlled/robustness reports, failures, checksums, evidence
index, deterministic replay, evidence coverage, machine-local validation,
applicable raw-independent validation, and passing repository gates. S4.4 is
GO only when S4.3 passes and no repeatability, integrity, applicability, or
claim-coverage decision remains unresolved. S4.4 is not begun by creating this
specification or by collecting/analyzing this pilot.
