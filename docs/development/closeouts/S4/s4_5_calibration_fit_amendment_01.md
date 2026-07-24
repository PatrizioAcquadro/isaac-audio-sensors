# S4.5 active handoff and provenance closeout amendment 01

This additive amendment is the authoritative S4.5 handoff. It preserves the
original S4.5 closeout and both existing evidence packages as historical
records while correcting their downstream routing and serialization
semantics.

The only profile authorized as input to S4.6 is
`outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json`,
and it is authorized only together with
`outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json` through
the fixed pointer
`outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json`.

The original
`outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json` remains
immutable historical evidence but is scientifically superseded and is not an
active S4.6 input.

The retained association is a fitted, functional channel-position binding in
`F_project`. Its channel mapping is machine-readable in the handoff. The
acoustic-center coordinate values remain nominal and unmeasured; the binding
is not measured geometry, a scalar bearing correction, physically traced
wiring, or a mirrored project frame.

The v2 profile serializes six scalar fitted parameters: three relative gains
and three unity polarities. The handoff separately serializes one retained
functional association. The immutable legacy metric with value seven is
superseded as an application count; it means six scalar profile parameters
plus one non-scalar functional association.

Relative delay, scalar bearing correction, confidence calibration, relative
audio-video timing, functional noise/self-noise, frequency-dependent
response, playback linearity, AGC/compression, sector/confusion thresholds,
abstention thresholds, absolute SPL/sensitivity, and precision
optical/acoustic extrinsics remain omitted or unsupported. Their application
or later-phase evaluation is not part of this amendment.

The handoff is valid only for the exact device, array, 16 kHz sample rate,
channel order, array/source frames, temporary fixture, WANG 2022 environment,
and source-path tags recorded in the bundle. Any mismatch fails closed.

Zero holdout observations were accessed. S4.6 has not started. S4 is not
SquadBot-ready and cannot pass until S4.8 and S4.9 pass. Nothing in this
amendment authorizes profile application or later-phase artifacts.
