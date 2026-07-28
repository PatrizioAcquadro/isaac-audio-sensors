# S4.8 automatic engineering acquisition and pre-sealing gate v2

## Scope and authority

This is a forward-only engineering method for a future non-holdout physical
rehearsal. It does not reinterpret v1 reports, modify either consumed S4.8
package, create or consume a grant, run the official state machine, publish
official evidence, or seal an official take. The legacy v1 gate remains fully
reproducible from its original module, configuration, and schemas.

The v2 decision is technical and outcome-independent. It receives no take ID,
cell, timestamp-derived scientific identity, target bearing, confidence,
accuracy, TDOA result, criterion result, or other scientific outcome. The
consumed holdout may be replayed only to prove compatibility and deterministic
non-regression; no v2 limit is selected from its performance.

## Frozen configuration and unchanged limits

`configs/s4_8_presealing_gate.v2.json` and its JSON schema freeze every v2
limit and identity. The v1 values below are copied without change:

- 16 kHz, six channels, microphone channels 2 through 5;
- 20.0 second capture with 0.05 second duration tolerance;
- planned playback from +1.0 through +19.0 seconds;
- scientific evaluation interval from +1.25 through +18.75 seconds;
- 2,000-sample blocks, RMS floor 0.002, background rule
  `median + 5.0 * 1.4826 * MAD`;
- reference correlation 0.20, pair coherence 0.10, three correlated channels,
  and per-channel propagation search of 16 samples;
- eight-block continuity, 90% coverage, 16.0 second continuous useful sound,
  0.5 second maximum gap, eight-sample maximum clipping run, 6.0 dB channel
  RMS spread, and -0.20 polarity-inversion limit.

No scientific threshold, denominator, evaluation interval, or acceptance
criterion changes in v2.

## Waveform-derived alignment

Authenticated process playback timing is a coarse permitted boundary, not
proof of acoustic phase.

1. From the process-reported playback command/start sample, search the next
   3,200 samples (200 ms) of every authenticated microphone waveform.
2. Match a 2,000-sample (125 ms) prefix of the exact frozen reference. The
   earliest strong per-channel peak defines the acoustic wavefront; the median
   peak correlation must retain the unchanged 0.20 minimum.
3. The acoustic onset must be no later than 2,000 samples (125 ms) after the
   process start. The wider 200 ms search exists only to identify and report a
   late onset rather than silently treating it as background.
4. For each 2,000-sample evaluation block, predict phase from the acoustic
   onset and the previous accepted correction, then search a local ±16-sample
   common phase correction. A correction may move at most four samples per
   block.
5. Fit the accepted common correction against elapsed recording samples. The
   absolute recorder/player drift may not exceed 1,000 ppm.
6. If local tracking fails, search ±512 samples only to classify the failure.
   A strong peak at least 64 samples from the prior phase is a discontinuous
   jump and is rejected; this wider search never permits reacquisition.
7. Missing correlation without a strong far peak is loss of reference.
   Initial-alignment failure, discontinuity, implausible step/drift, or
   reference loss is fail-closed.

The 125 ms onset allowance, 1,000 ppm total drift allowance, four-sample
per-block step, and discontinuity classifier are broad engineering limits for
USB buffering, acoustic propagation, independent recorder/player clocks, and
minor resampling. They were selected without holdout fitting and require
confirmation or tightening from future physical non-holdout measurements.

## Full-playback waveform sentinels

The frozen scientific interval remains exactly +1.25 through +18.75 seconds.
Two separate technical sentinels cover the playback edges:

- Start sentinel: matched waveform onset must be established no later than
  +1.125 seconds. Missing only +1.0 through +1.25 seconds, a silent successful
  player, or a whole-reference-loop delay therefore returns
  `acoustic_playback_started_late`.
- Stop sentinel: the final 2,000 samples ending exactly at +19.0 seconds must
  retain the aligned reference, unchanged RMS floor, unchanged 0.20 reference
  correlation, and at least three correlated microphones. Missing only
  +18.75 through +19.0 seconds returns
  `acoustic_playback_stopped_early`.

These checks compare process timing with acoustic evidence. A live player
process, zero exit status, or reported on-time start/stop cannot substitute for
the sentinels.

## Remaining controls

The supported v2 engineering controller additionally requires an anchored,
hash-chained process journal, exact PCM16 WAV validation, authenticated device
profile and channel map, frozen/repeated-buffer checks, duplicate/crosstalk
checks, total clipping controls, and a single-use exact-input candidate
clearance before the engineering candidate seal API can write. Those controls
are engineering/tamper-evident only: a SHA-256 chain is not a digital
signature and does not establish a human or hardware identity.

## Physical gate

Software and synthetic success can clear only readiness to start a physical
engineering rehearsal. A new official holdout remains NO-GO until one complete
47-take physical, explicitly non-holdout rehearsal on the intended ReSpeaker,
playback path, reference WAV, device/channel profile, environment, and ZED path
where applicable passes all preregistered technical and scientific readiness
conditions without manual output editing.
