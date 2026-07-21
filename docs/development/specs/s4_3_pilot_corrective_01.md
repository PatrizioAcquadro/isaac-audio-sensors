# S4.3 Corrective Contract 01: Sustained Clipping and Noise Events

Status: corrective contract to be frozen before the single prospective silence
capture. This record does not rewrite any original S4.3 configuration,
preregistration, result, failure, or unfavorable observation.

## Preservation boundary

The original `configs/s4_3_pilot.v1.json` and every preregistration through
`preregistration_amendment_04.json` remain immutable. Their hashes are retained
in the machine-readable corrective records. The original value
`maximum_sustained_clip_run_samples = 8` is preserved as a superseded mistake,
not edited in place. Existing raw attempts are immutable. In particular, the
15-sample conference-channel run in `s4_3_rob_overlap_01` remains a descriptive
diagnostic and does not invalidate or trigger recollection of that trial.

## Sustained clipping correction

S4.2 defines sustained clipping as at least 250 ms continuously at or above
0.999 full scale. At 16,000 samples/s this is 4,000 consecutive samples. The
corrected effective S4.3 threshold is therefore 4,000 samples, with failure for
`run >= 4,000`. The effective configuration is the sole threshold source for
S4.3 waveform analysis, channel-health evidence, repeatability evaluation, and
coverage validation. Every declared channel is checked. Shorter runs remain in
the per-channel report and are not classified as sustained clipping.

Classification: the threshold definition is Verified against the inherited
S4.2 contract. Observed per-channel maximum runs are Measured digital-waveform
diagnostics. They are not evidence of absolute SPL or analog saturation.

## Legacy noise result

The inspected S4.3 result previously named a transient rate counts overlapping
250 ms analysis windows whose median raw-channel RMS exceeds the frozen signal
threshold. It is retained and relabeled
`legacy_overlapping_window_rms_exceedance_rate`. Because overlapping windows
are correlated, it is not a count or rate of distinct physical transient
events. The distinct-event transient rate for all already-inspected S4.3 data
is `Unmeasured`; those recordings cannot confirm the prospective detector.

## Prospective transient-event contract

The machine-readable contract is
`outputs/isaac_audio_sensors/S4/S4.3/freeze/transient_event_contract_01.json`.
It is frozen and hashed before the new trial begins and cannot be tuned after
new results are viewed.

The detector operates on the four declared raw channels at 16 kHz and is
independent of the reporting-window duration and overlap. Per-channel 20 ms
(320-sample) moving RMS envelopes are compared with the larger of 0.002 full
scale or the channel median plus eight robust standard deviations, where the
robust deviation is `1.4826 * MAD`. At least two raw channels must exceed their
threshold concurrently. Bounded gaps no longer than 1,600 samples (100 ms) are
bridged once. Each resulting connected excursion is classified exactly once:

- durations below 160 samples are short diagnostics, not events;
- durations from 160 through 16,000 samples are one transient event;
- durations above 16,000 samples are stationary excursions, reported but not
  counted as transient events;
- excursions touching either interval boundary are censored, reported, and not
  counted.

The denominator is the complete inspected intended-silence interval in
seconds. Event rate is `event_count / interval_duration_s`. Events are retained
with start, exclusive stop, duration, and peak sample. No analysis-window
overlap parameter participates in event formation, so changing reporting
overlap cannot change the event count.

Uncertainty includes the 20 ms energy envelope, 100 ms gap bridge, fixed
channel-concurrence rule, uncontrolled room sources, finite 15 s denominator,
and lack of calibrated SPL. The result is functional room-fixture-sensor
characterization only.

## Prospective evidence and stopping rule

All 22 S4.3 metric contracts require the corrected noise metric to be covered.
Because inspected data cannot confirm the prospective detector, exactly one
new 15 s intended-silence trial is required:
`s4_3_rob_silence_02_prospective_events_01`. The operator removes or silences
all deliberate sources; no physical source coordinate applies in either
`F_operator_facing_zed` or `F_project`. No overlap or unrelated trial may be
repeated. Every attempt is retained. One terminal attempt completes this
corrective cell; a failed attempt remains a failure and leaves prospective
event-rate coverage unavailable unless a separately authorized, prospectively
frozen failure-handling record permits another capture.

## Gate semantics

The corrective provenance fails closed if any original binding, corrective
record, prospective detector hash, effective threshold, new-trial definition,
implementation hash, inventory relationship, or required prospective result is
missing or inconsistent. Reports must separately expose the legacy overlapping
RMS-exceedance result, the `Unmeasured` legacy distinct-event rate, and the
prospectively measured de-duplicated event rate.

S4.4 is outside this contract and remains unstarted.
