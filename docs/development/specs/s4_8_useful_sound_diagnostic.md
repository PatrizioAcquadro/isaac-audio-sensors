# S4.8 reused-holdout useful-sound diagnostic

## Status and scientific boundary

This is a **reused holdout**, **diagnostic only** development lane. It is not
an unseen-holdout result, does not alter the historical terminal S4.8
packages, cannot grant S4 readiness, and does not authorize S4.9 or a later
phase.

The unchanged full-capture producer and frozen corrective_03 evaluator remain
the historical semantic path. The isolated lane keeps all 29 numerical
thresholds and comparison directions but changes the A/B applicability
denominator explicitly: only windows with demonstrably sustained directional
acoustic activity are performance-applicable.

## Useful-directional-sound applicability

For every A/B capture independently:

1. analyze the same calibrated 4,000-sample windows on 2,000-sample hops at
   16 kHz;
2. require calibrated median microphone RMS greater than the existing `0.002`
   basic energy floor;
3. compute absolute SRP coherence as positive SRP peak power divided by the
   six microphone-pair count;
4. sort the capture's coherence values and use the lower 50% as a robust
   background population;
5. set the coherence threshold to lower-half median plus
   `5.0 * 1.4826 * MAD`;
6. require at least eight consecutive candidate windows.

Eight consecutive 125 ms hops cover at least 1.125 s from the first window
start through the last window end. Short isolated coherent events are excluded
as insufficient directional continuity. Windows above the energy floor but
below the robust coherence threshold are excluded as generic background,
non-directional energy, playback gaps, or insufficient coherence. Windows at
or below the energy floor are excluded as insufficient acoustic energy.

The detector does not receive take identity, target bearing, emitted bearing,
final confidence, bearing correctness, criterion values, or acceptance
outcomes. Unsealed `playback.json` timestamps are not detector inputs. The
sealed waveform and producer-status files are authenticated before analysis.
Confidence and target bearing are used only after applicability is fixed, for
performance aggregation.

## Diagnostic result

The isolated 47-take rerun evaluated all 29 criteria and passed all 23
mandatory readiness criteria. A/B applicability selected 1,356 of 5,088
windows. The other 3,732 windows were explicitly non-applicable: 3,458 lacked
sufficient directional coherence and 274 were coherent only in runs shorter
than the minimum continuity requirement. No selected useful-sound window
abstained.

This PASS describes only the reused-holdout diagnostic lane. The unchanged
full-capture diagnostic remains FAILED on active abstention and B confidence,
and the historical frozen terminal packages remain FAILED.

## Future continuous-useful-sound capture protocol

This section is preparation only. Collect **no new holdout** under this task.

For every future A/B take:

- Record for 20.0 s. Retain a 1.0 s pre-roll before acoustic playback begins
  and a 1.0 s post-roll after playback ends.
- Start playback at capture time `+1.0 s`, after the recorder reports a
  successful start. Stop at `+19.0 s`.
- Use a hash-bound broadband directional stimulus whose validated content has
  no internal silence or low-coherence gaps. Playback **loops continuously**
  with gapless looping for the full 18.0 s playback interval.
- Define the intended evaluation interval as `+1.25 s` through `+18.75 s`, so
  every retained 250 ms analysis window is fully inside playback and away from
  start/stop boundaries.
- Require **minimum useful-sound coverage** of 90% of intended evaluation
  windows, one continuous useful interval of at least 16.0 s, and no
  non-applicable gap longer than 0.5 s.
- Perform **automated playback-presence verification** before a take can be
  sealed: authenticate the exact reference hash; seal capture-side playback
  start/stop/exit records; verify successful continuous-loop process status;
  measure normalized correlation to the exact reference or its loop sequence;
  and run this outcome-independent energy/coherence/continuity detector.
  Reference-correlation thresholds must be fixed from non-holdout calibration
  before collection.
- Trigger a technical retry before sealing if playback did not start by
  `+1.0 s` within the preregistered clock tolerance, stopped before `+19.0 s`,
  returned nonzero, used the wrong reference hash, missed the correlation
  presence gate, fell below 90% useful coverage, had a gap longer than 0.5 s,
  lacked a 16.0 s continuous useful interval, clipped, or failed channel
  health.
- Make retry decisions from technical presence, continuity, integrity,
  clipping, and channel-health evidence only. Do not inspect bearing error,
  sector correctness, final confidence, TDOA accuracy, or any acceptance
  result before sealing or retrying.

This protocol prevents another nominal 20 s capture from being dominated by
inactive reference lead-in, internal gaps, early playback termination, or
post-playback background while retaining independent performance assessment.
