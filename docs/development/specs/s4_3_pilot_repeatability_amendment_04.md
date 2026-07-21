# S4.3 Interactive-Stimulus Amendment 04

Status: frozen before the voice confirmation recording on 2026-07-21.

The first voice attempt remains immutable with lifecycle state `accepted`, but
it cannot support the required voice claim. Retained clocks prove the stimulus
trigger occurred 12.5095 seconds after producer readiness in a 15-second take,
leaving only 2.4758 seconds before recorder completion. All 103 analysis windows
abstained and the recorded level was silence-like. The diagnostic is frozen at
`outputs/isaac_audio_sensors/S4/S4.3/diagnostics/voice_interactive_timing_failure_20260721T201200Z.json`.

This is an orchestration failure, not detector evidence and not grounds to
delete or rewrite the accepted lifecycle. Under the frozen
`uncovered_required_claim` expansion trigger, exactly one confirmation is added:
`s4_3_rob_voice_01_confirm_timing_01`. It is the first and only confirmation for
the voice parent cell and the third/final added trial allowed by the original
matrix contract.

## Corrected interactive protocol

For voice, overlap, and impact trials, operator readiness is received before any
producer starts. Only then are required producers launched and verified ready.
After the frozen two-second settle interval, the orchestrator writes the
stimulus-trigger record and emits `stimulus_now` without waiting for further
input. Operator interaction therefore does not consume the bounded capture
duration.

The voice confirmation retains the same viewpoint-first placement, phrase,
repetition count, duration, room, rig, and analysis thresholds. From the
operator's viewpoint while facing the ZED, the voice source is on the left at
`F_operator_facing_zed (0.00,-0.90,-0.135) m`, bearing `270 deg` (canonical
`F_project (0.00,+0.90,-0.135) m`, bearing `90 deg`). The exact phrase remains
“Audio pilot check, one two three, direction test,” spoken twice after the cue.

No scientific threshold, estimator, version/power policy, or earlier trial is
changed. No further matrix expansion is permitted after this confirmation. If
the confirmation still does not provide usable voice evidence, the voice claim
is Unsupported for S4.3. S4.4 remains untouched.
