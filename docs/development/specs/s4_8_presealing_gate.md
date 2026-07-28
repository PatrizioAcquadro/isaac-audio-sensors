# S4.8 pre-sealing useful-stimulus gate

## Status and authority

This is a **separately versioned** forward-only engineering method for future
continuous-reference captures. The legacy detector remains reproducible in
`s4_8_useful_sound_diagnostic.py`; its v1 payloads and the historical FAILED
S4.8 packages are not reinterpreted or regenerated.

The new gate is run before a candidate take is sealed. It returns `PASS` or
`RETRY_REQUIRED`, but it does not seal a take. Its **dry-run** mode creates
**no grant**, consumes no grant, publishes no official evidence, and performs
**no official state-machine** run. It receives no take identity, cell, target
bearing, bearing error, sector result, TDOA result, final confidence,
criterion value, or acceptance outcome.

This gate applies to the continuous-reference acquisition protocol. It does
not infer scientific strata from data. A future collection controller invokes
it only for captures whose preregistered technical protocol requires the
continuous reference; silence and impact protocols retain their own frozen
technical QA.

## Measured legacy defect

The capture-wide lower-50% coherence estimator assumes background occupies at
least half the capture. A deterministic 160-window regression with 16
background windows and 144 useful windows (90% useful occupancy) measures:

- lower-half background median: `0.06`;
- threshold: `0.06`;
- useful windows selected: `0/160`.

The active population becomes the alleged background. Because the legacy rule
uses strict greater-than comparison, stable useful coherence equal to the
inflated threshold is completely rejected. Occupancy sweeps therefore had to
precede the correction.

## Version 1 detector rule

The tracked configuration is
`configs/s4_8_presealing_gate.v1.json`. Its canonical configuration and
detector hashes are emitted in every report.

1. Authenticate the capture bytes, exact reference bytes, and hash-bound
   process record before interpreting timing.
2. Require 16 kHz, six signed-16-bit channels, a `20.0 +/- 0.05 s` capture,
   and microphone channels 2 through 5.
3. Derive background only from authenticated pre-roll and post-roll intervals:
   capture start through the authenticated playback start, and authenticated
   playback stop through capture stop. Never estimate background from the
   active evaluation interval.
4. Define the evaluation interval as `+1.25 s` through `+18.75 s` and divide
   it into exact non-overlapping 2,000-sample (`125 ms`) blocks.
5. For every block, construct the **exact looped reference** at the
   authenticated playback phase.
6. Compute calibrated per-channel RMS, the median microphone RMS, signed
   normalized reference correlation with up to 16 samples of propagation
   lag, and median absolute pair coherence with up to 32 samples of pair lag.
7. Set the energy threshold to the greater of the unchanged `0.002` basic RMS
   floor and authenticated-background median RMS plus
   `5.0 * 1.4826 * MAD`.
8. A raw block is useful only when:
   - median RMS is strictly above both energy floors;
   - median signed reference correlation is at least `0.20`;
   - at least three of four channels have signed reference correlation at
     least `0.20`; and
   - median absolute pair coherence is at least `0.10`.
9. Exclude coherent runs shorter than eight blocks (`1.0 s`) as transient
   events. Retain longer runs without requiring inactive blocks elsewhere in
   the capture.

The correlation/coherence bounds are technical playback-presence controls,
not S4 scientific performance thresholds. They are fixed in this version and
must be validated with the physical non-holdout rehearsal before an official
capture. They must not be adjusted using holdout accuracy, confidence, or
criterion outcomes.

## Pre-sealing decision

`PASS` requires all of the following:

- recorder start succeeded, producer status is `complete`, and recorder exit
  status is zero;
- playback started at `+1.0 s +/- 0.1 s`;
- the process record planned stop is exactly `+19.0 s`, playback did not stop
  before it, continuous looping is confirmed, and exit status is zero;
- the process record authenticates the exact capture and reference hashes;
- waveform evidence contains the authenticated reference stimulus;
- useful-sound coverage is at least **90%** of the evaluation interval;
- the longest continuous useful interval is at least **16.0 s**;
- no non-applicable gap is longer than **0.5 s**;
- no microphone has a full-scale clipping run longer than eight samples;
- calibrated evaluation-interval channel RMS spread is no more than `6.0 dB`;
- no channel has stable signed reference correlation at or below `-0.20`;
- sample rate, channel count, duration, process timing, producer status, and
  waveform evidence are mutually consistent.

Any failed condition produces `RETRY_REQUIRED` with structured reason records,
counts, intervals, metrics, exact input provenance, the full detector
configuration, and both configuration hashes. Retry decisions use only
integrity, playback presence, continuity, coverage, clipping, and channel
health.

## Process-record authentication

The process record has an exact schema and a canonical SHA-256 over every
field except its own digest. It binds capture/reference hashes, recorder and
producer results, loop status, process exit statuses, and monotonic start/stop
events. This is tamper-evident candidate-seal material, not a digital
signature. Before official acquisition, the exact record, configuration,
reference WAV, environment, and candidate source must be frozen in the
precollection manifest. Missing, altered, reordered, or inconsistent fields
fail closed.

## Engineering rehearsal and remaining physical gate

The deterministic synthetic **non-holdout** rehearsal exercises acquisition,
record authentication, a valid pre-sealing decision, retry behavior, the
corrective_03 producer fixture, schema/payload construction, all 29 criteria,
all 23 mandatory criteria, and deterministic regeneration. It persists no
recording or evidence and never uses the consumed holdout.

Synthetic success is not a physical rehearsal. Before a new official holdout
may begin, execute the same protocol using the installed ReSpeaker, playback
host and exact frozen reference WAV, ZED path where applicable, and real
process-event recorder. A complete 47-take engineering/non-holdout run must
verify the correct per-stratum acquisition paths, all 29 criteria, all 23
mandatory criteria where physical inputs apply, no manual output edits,
determinism, and retry behavior. If the physical rehearsal has not occurred,
the acquisition verdict remains NO-GO.
