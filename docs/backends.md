# Backends

Backends implement `AudioSimulationBackend.simulate(scene, sensor, window)` and
return an `AudioSensorFrame`.

The backend ids below are tied to the public
[Acoustic Fidelity Ladder](acoustic_fidelity.md): L0 `geometry_only` and L1
`tdoa_synthetic` are stable v1, and L2 `room_acoustics` is supported optional
v1. L3 advanced realism and L4 sim-real calibration are documented future
directions, not selectable v1 runtime backends.

The implemented backend ids `geometry_only`, `tdoa_synthetic`, and
`room_acoustics` are public v1 identifiers. Renaming them would break config,
trace, docs, and ladder compatibility; new backend families must be added under
new ids instead.

The canonical promise boundary is [V1 Public Scope](v1_scope.md). Backends do
not make sim-real calibration, real hardware benchmarks, complete L3/L4, or
realistic occlusion/material acoustics part of the v1 release.

All backends populate the v1 frame contract with the array pose, source poses
when known, explicit units, time-window fields, and provenance. `max_events` is
read from `AudioTimeWindow.max_events`; active sources are selected in a stable
order and truncated before detections are emitted.

## geometry_only

`GeometryBackend` computes direct geometric bearing, source distance, and an
eight-sector label from the source position relative to the microphone-array
frame. It is deterministic and useful for tests, UI plumbing, and ground-truth
style traces.

Bearings use the public `x_forward_y_right_z_up_clockwise_bearing`
convention: `0` is local forward, `90` is right, `180` is behind, `270` is
left, and values normalize into `[0, 360)`. Sector labels use eight
half-open bins centered every 45 degrees:
`straight`, `straight_right`, `right`, `behind_right`, `behind`,
`behind_left`, `left`, and `straight_left`.

The corrected v1 sector mapping is now frozen. Each sector includes its lower
boundary and excludes its upper boundary after bearing normalization. The
wraparound `straight` sector covers `337.5 <= bearing < 360.0` and
`0.0 <= bearing < 22.5`; `22.5` belongs to `straight_right`, `67.5` belongs to
`right`, and `337.5` belongs to `straight`. This was a compatibility-preserving
bug fix to align code and docs, not an opening to change sector meanings.

It does not simulate propagation, waveforms, reverberation, occlusion, or
physical microphone response.

## tdoa_synthetic

`TdoaSyntheticBackend` computes direct-path time-of-arrival differences from
source and microphone geometry. It reports per-microphone delays, synthetic RMS
diagnostics, candidate bearings, ambiguity metadata, and confidence.

Two-microphone arrays expose front/back ambiguity explicitly. With
`ambiguity_policy="none"`, ambiguous frames leave `estimated_bearing_deg` and
`bearing_sector` unset, include candidate bearings, and populate
`ambiguity_class` / `ambiguity_reason`. With
`ambiguity_policy="front_hemisphere"`, the frame records that an explicit prior
selected one candidate and keeps confidence lower than a clean non-collinear
four-mic solution.

Four or more non-collinear microphones are recommended for direction-of-arrival
examples. The built-in `quad_front` and `quad_cross` aliases use the same
front/right/rear/left cross layout.

`noise_std_s`, `clock_jitter_s`, and `gain_mismatch_db` are deterministic
stress controls for L1 tests and examples, not calibrated hardware noise.
`noise_std_s` and `clock_jitter_s` add a repeatable per-mic delay offset and
reduce confidence. `gain_mismatch_db` applies a repeatable per-mic RMS offset
and reduces confidence. This deterministic stress layer does not model
stochastic sensor drift, frequency response, clipping, automatic gain control,
correlated electronics noise, or hardware clock recovery.

## room_acoustics

`RoomAcousticsBackend` is optional. When `pyroomacoustics` is installed, it can
build an approximate shoebox room response, generate per-microphone waveforms
through `compute_rir()` / `simulate()`, and estimate TDOA from those waveforms
with GCC-PHAT. Direct-path delay is recorded only as diagnostic comparison
data.

Install it with:

```bash
python -m pip install -e ".[room]"
```

If the dependency is missing, core imports remain safe,
`RoomAcousticsBackend.is_available()` returns `False`, and `simulate(...)`
raises `OptionalDependencyUnavailable` with a clear install hint. `soundfile`
is used only when a real file-backed `audio_asset_path` is loaded; generated
waveforms do not require it.

Active sources use the shared half-open scheduling window and deterministic
`max_events` truncation. For v1, multiple active sources are simulated
independently and emitted as one detection per scheduled source. This is not
mixed-source separation.

Frames from this backend use provenance `room_acoustics` and include stable L2
diagnostic keys for `room_config`, `pyroomacoustics_version`,
`scheduled_source_ids`, `per_source_rir_summary`, `estimated_tdoa_matrix_s`,
`gcc_phat_peaks`, `direct_path_delay_s`, `per_mic_rms`, `rir_length_samples`,
`rir_peak_delay_s`, `waveform_sample_count`, `room_source_position_m`, and
`room_microphone_positions_m`.

Use it for approximate shoebox-room experiments, not as a calibrated acoustic
twin. It does not provide realistic occlusion, material behavior, directivity,
calibrated microphone response, production beamforming, or sim-real transfer.
