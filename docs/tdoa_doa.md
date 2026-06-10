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

For two-mic TDOA configs, select `audio.tdoa_ambiguity_policy` explicitly.
Use `none` when no prior is available. Use `front_hemisphere` only when the
caller has an external reason to prefer the local front hemisphere.

## Four Microphones

Four non-collinear microphones provide multiple baselines and are recommended
for DOA examples. The bundled `quad_front` layout is intended for simple robot
front/right/rear/left demonstrations.

## Deterministic Stress Controls

The L1 `tdoa_synthetic` backend accepts three deterministic stress controls
plus an optional `seed`:

- `noise_std_s` is the standard deviation of a seeded Gaussian delay draw per
  microphone, deterministic per `(seed, frame_id, mic_id)`.
- `clock_jitter_s` is the standard deviation of a second independent seeded
  Gaussian delay draw per microphone.
- `gain_mismatch_db` is the standard deviation of a static seeded Gaussian
  per-microphone RMS gain offset, deterministic per `(seed, mic_id)` and
  constant across frames.

These controls are useful for verifying that downstream code handles imperfect
delay/RMS/confidence values, but they are not calibrated hardware noise.
`noise_std_s` and `clock_jitter_s` affect per-mic delays and confidence.
`gain_mismatch_db` affects per-mic RMS and confidence. Replays with the same
scene, window, settings, and seed are bit-identical (deterministic stress),
and zero-valued settings draw nothing. Bearing confidence never reads the
ground-truth bearing; the comparison against ground truth is reported only as
the `oracle_bearing_error_deg` detection diagnostic. None of these knobs
models stochastic sensor drift, reverberation, occlusion, microphone frequency
response, clipping, automatic gain control, or estimator failure modes beyond
the seeded perturbations reported in frame diagnostics.

## GCC-PHAT Helpers

`isaac_audio_sensors.core.doa.gcc_phat` includes small helpers for estimating
relative delays from waveforms. They are used by the optional room-acoustics
backend and are part of the core utility surface. A positive pairwise delay
means the left-hand signal in a `mic_a->mic_b` key arrived later than the
right-hand reference. `RoomAcousticsBackend` converts that matrix into
reference-relative per-microphone delays before DOA estimation and keeps
direct-path delays only as diagnostics.
