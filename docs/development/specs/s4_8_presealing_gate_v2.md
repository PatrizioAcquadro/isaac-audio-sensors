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
- the official six-channel firmware order: `Conference`, `ASR`, then raw
  microphones 0 through 3;
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

The exact authenticated reference WAV contains intentional silent lead-in,
separator, and tail regions. The acquisition path therefore selects the
already-preregistered +2.25 s through +7.25 s active fitting interval after
deterministic rate normalization, and the playback builder tiles those exact
PCM frames into the 18-second continuous asset. The complete source WAV hash,
selected frame bounds, and derived asset hash remain frozen. No silence is
removed based on a collected capture or outcome.

## Waveform-derived alignment

Authenticated process playback timing is a coarse permitted boundary, not
proof of acoustic phase.

1. From the process-reported playback command/start sample, search the next
   3,200 samples (200 ms) of every authenticated microphone waveform.
2. Match a 2,000-sample (125 ms) prefix of the exact frozen active reference
   interval. The earliest strong per-channel peak defines the acoustic
   wavefront; the median peak correlation must retain the unchanged 0.20
   minimum.
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

For the physical engineering controller, the process start is anchored to the
first nonzero CoreAudio mixer frame plus the output device's reported
presentation latency. A causal SSH clock-sync interval maps that remote host
time into the controller clock; the earlier bound is retained as the journal
time and both bounds remain in event data. This makes the process boundary a
genuine observed CoreAudio event without changing the 3,200-sample search,
2,000-sample maximum delay, or any detector/scientific configuration value.

## Remaining controls

### Strict capture integrity

The supported file path accepts only RIFF/WAVE audio-format 1, signed
little-endian 16-bit uncompressed PCM. It validates the RIFF length, complete
chunk headers and padding, one `fmt` and one `data` chunk, channel count,
sample rate, byte rate, block alignment, whole interleaved frames, and the
derived frame count. Unsupported width/compression, malformed/truncated
headers, incomplete frames, and inconsistent sizes fail before waveform
interpretation.

In addition to the unchanged v1 channel rules, v2 rejects:

- more than two consecutive bit-identical 2,000-sample microphone buffers;
- any microphone pair with absolute zero-lag correlation at or above 0.995,
  covering exact duplication and extreme crosstalk;
- more than 64 full-scale samples on any microphone or a full-scale rate over
  0.0002, in addition to the unchanged eight-sample consecutive run;
- a missing or non-exact
  `respeaker_usb_6ch_pcm16_v1` device/profile identity; and
- a missing or non-exact six-entry channel map. Channel order is never inferred
  from bearing correctness or any other scientific result.

These new integrity values are broad technical defect controls, not
scientific limits. They were not fitted to the consumed holdout and must be
checked on future physical non-holdout recordings.

### Anchored engineering process journal

Before collection, an external caller freezes
`ias.s4_8.engineering_precollection_manifest.v2`, containing code HEAD,
environment identity, exact reference-WAV SHA-256, gate and detector
configuration SHA-256 values, expected device/profile, exact channel map,
protocol identity, and controller identity/version. Its canonical SHA-256 is
the external anchor supplied separately to validation.

The controller then appends exactly this event sequence:

1. `capture_controller_started`;
2. `recorder_started`;
3. `recorder_ready`;
4. `playback_commanded`;
5. `playback_started`;
6. `playback_stop_planned`;
7. `playback_terminated`;
8. `recorder_terminated`;
9. `capture_authenticated`;
10. `gate_evaluated`;
11. `candidate_clearance_created`.

Every event records its sequence, observed monotonic time, stable process
identity/PID where available, event data, manifest anchor, previous event hash,
and canonical event hash. Capture authentication records exact capture,
reference, device/profile, channel-map, gate-configuration, and
detector-configuration hashes. The final two events record the exact gate
report and candidate-clearance hashes.

The raw recorder/player exit status is always retained. Status zero is a
normal success. Because the supported controller intentionally terminates the
continuous recorder and player at their planned boundaries, the tracked
configuration also permits only an explicitly recorded
`controller_requested_termination=true`, signal 15, raw status -15 tuple.
Unrequested signals, a different signal/status pair, or an early observed
termination still fail closed; the waveform sentinels remain mandatory.

Validation requires the separately supplied manifest anchor and the complete
ordered chain. Missing, reordered, duplicated, changed, independently
recomputed without the frozen anchor, or identity-inconsistent sequences fail
closed before timing is interpreted. This is tamper evidence only: SHA-256
hash chaining is not a digital signature, provides no signer identity, and
does not prevent a party that controls the external anchor from replacing the
entire history.

### Mandatory controller and seal interlock

`scripts/run_s4_8_engineering_acquisition.py` is the one supported future
engineering acquisition CLI. It calls
`run_supported_engineering_acquisition()` in this mandatory order:

`recorder start -> recorder ready -> playback command/start -> continuous
capture -> planned playback stop -> observed player status -> post-roll
capture -> observed recorder status -> capture/reference authentication ->
v2 pre-sealing gate -> PASS clearance -> engineering candidate seal`.

The controller writes the journal after every event with flush and `fsync`.
Operational capture, journal, retry report, clearance-use registry, and
candidate seal paths must be outside the repository. `RETRY_REQUIRED` writes
only the structured operational retry report; it creates no clearance or
candidate seal. Dry-run executes and validates the full path but writes no
candidate seal or clearance-consumption record.

`seal_engineering_candidate()` is the sole supported candidate-seal API. It
requires a schema-valid PASS report and clearance bound to the exact capture,
reference, precollection manifest, process-journal head, gate report, gate
configuration, and detector configuration hashes. The journal must contain
the matching clearance hash. A different capture/reference, stale or changed
report/configuration/journal, altered clearance, existing use record, or
second use fails closed. Its result is explicitly engineering-only and has
false authority for grants, official state-machine activity, official
evidence, and official take sealing.

## Physical gate

Software and synthetic success can clear only readiness to start a physical
engineering rehearsal. A new official holdout remains NO-GO until one complete
47-take physical, explicitly non-holdout rehearsal on the intended ReSpeaker,
playback path, reference WAV, device/channel profile, environment, and ZED path
where applicable passes all preregistered technical and scientific readiness
conditions without manual output editing.
