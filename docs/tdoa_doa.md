# TDOA And DOA

Time difference of arrival (TDOA) estimates compare relative arrival times
between microphones. Direction of arrival (DOA) estimates convert those
differences into a bearing when the array geometry has enough information.

## Two Microphones

A two-microphone array can estimate a delay across one baseline, but a symmetric
front/back source pair can produce the same delay. `isaac-audio-sensors`
represents that explicitly:

- `estimated_bearing_deg` can be `None`;
- `candidate_bearing_deg` contains the plausible bearings;
- `ambiguity_class` records the ambiguity;
- `ambiguity_reason` explains the policy.

If a caller chooses `front_hemisphere`, the backend records that the result used
a prior rather than pretending the ambiguity disappeared.

## Four Microphones

Four non-collinear microphones provide multiple baselines and are recommended
for DOA examples. The bundled `quad_front` layout is intended for simple robot
front/right/rear/left demonstrations.

## GCC-PHAT Helpers

`isaac_audio_sensors.core.doa.gcc_phat` includes small helpers for estimating
relative delays from waveforms. They are used by the optional room-acoustics
backend and are part of the core utility surface.
