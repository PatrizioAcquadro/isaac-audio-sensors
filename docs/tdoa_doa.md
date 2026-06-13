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

## 3D DOA And Elevation

Since `1.7.0` the multi-microphone least-squares solver works in full 3D when
the layout has 3D rank 3 (microphones not all in one plane), gated by
`layout_rank_xyz` and reported in the `array_geometry_rank_xyz` diagnostic.
Rank-3 layouts such as the bundled `tetrahedral` preset populate the additive
optional `DoaEstimate` fields:

- `estimated_elevation_deg`: degrees up from the array's forward/right plane,
  positive toward array up, in `[-90, +90]`;
- `candidate_elevation_deg`: candidate elevations in the same convention.

Planar layouts (`quad_front`, `stereo_y`, custom coplanar arrays) keep the
exact pre-1.7.0 azimuth-only behavior and leave the elevation fields
`None`/empty: a planar array cannot resolve the elevation sign (cone
ambiguity), so the package does not guess. `bearing_confidence` covers the
full estimated direction, including elevation when present, and elevation
accuracy against ground truth is reported through the
`oracle_elevation_error_deg` detection diagnostic alongside the optional
`ground_truth_elevation_deg` detection field. `geometry_only` (L0) emits
exact geometric elevation for every detection.

## SRP-PHAT

`isaac_audio_sensors.core.doa.srp_phat` provides a steered-response-power
estimator with PHAT weighting over L2 waveforms. It steers the pairwise
cross-correlations across a deterministic azimuth grid (2 degrees by
default), plus an elevation grid (5 degrees by default) when the array has
3D rank 3. Select it end-to-end with the `room_acoustics_srp` backend id or
`RoomAcousticsBackend(doa_estimator="srp_phat")`; see
[Backends](backends.md). The waveform-domain estimator family is dispatched
by estimator id so future estimators (e.g. MUSIC) can join without breaking
the backend contract.

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
