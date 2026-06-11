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

## Shared Amplitude Conventions

Since `1.1.0` the synthetic L0/L1 RMS values and the L2 waveform pipeline share
one pressure-like reference convention:

- `AudioSourceSpec.gain_db` is the source level re 1 m: an omnidirectional
  source emits an RMS amplitude of `10 ** (gain_db / 20)` at one meter.
- RMS falls off as `1 / distance` (pressure), with distance clamped at 0.1 m.
  At L2 the same convention is inherited from the pyroomacoustics image-source
  attenuation.
- `aggregate_per_mic_rms` is an incoherent power sum over scheduled sources:
  `sqrt(sum(rms ** 2))` per microphone in all three backends.
- `MicrophoneSpec.self_noise_db` adds a per-microphone noise-floor power
  `(10 ** (self_noise_db / 20)) ** 2` to the aggregate at L0/L1. Per-detection
  `per_mic_rms` stays signal-only.
- `AudioSourceSpec.directivity` is modeled at L0/L1 with a first-order factor:
  `omni` is unity and `cardioid` applies `(1 + cos(theta)) / 2` toward each
  microphone using the source's world orientation. Unknown directivity values,
  and `cardioid` sources without `orientation_world_quat`, behave as `omni`;
  the detection diagnostic `directivity_applied` records what was modeled.
  Both `self_noise_db` and source directivity remain metadata-only at L2.

## Shared Occlusion Consumption

Since `1.3.0` backends consume optional producer-computed occlusion (the
Isaac layer's raycast occlusion, the first shipped L3 capability) without
computing any occlusion themselves. Since `1.4.0` consumption is
per-microphone and band-aware. When `AudioSceneSnapshot.occlusion` carries a
`SourceOcclusion` record for a source/array pair:

- `geometry_only` and `tdoa_synthetic` apply `per_mic_attenuation_db` as
  extra gain per microphone (falling back to the uniform `attenuation_db`
  when the per-mic map is absent), so blocked microphones lose level
  independently; per-microphone delays and DOA estimates are unchanged.
- `room_acoustics` attenuates the per-source/per-microphone simulation
  premix before summing - zero-phase per-band rFFT filtering when
  `per_mic_band_attenuation_db` is present, a broadband scale otherwise - so
  the mixture, per-source premix RMS, aggregate RMS, GCC-PHAT diagnostics,
  and exported waveforms stay mutually consistent. For uniform records this
  is mathematically identical to scaling the source input signal.
- Affected detections set the optional `occluded` flag (occlusion factor at
  or above 0.5) and an `occlusion` diagnostics namespace with the factor,
  applied attenuation, per-microphone blocked map and attenuation, band data
  when present, hit prim paths, resolved hit materials, and the
  `occlusion_model` label.

Without occlusion records, behavior is byte-for-byte unchanged.

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

It does not simulate propagation, waveforms, reverberation, or physical
microphone response, and computes no occlusion itself; it only applies
producer-supplied occlusion attenuation as described above.

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

Bearing confidence derives only from observable quantities: the least-squares
residual, the array geometry, and the configured stress settings. The
ground-truth bearing never feeds confidence; the comparison against ground
truth is reported separately as the detection diagnostic
`oracle_bearing_error_deg`.

`noise_std_s`, `clock_jitter_s`, and `gain_mismatch_db` are deterministic
stress controls for L1 tests and examples, not calibrated hardware noise.
`noise_std_s` and `clock_jitter_s` are standard deviations of seeded Gaussian
per-mic delay draws, deterministic per `(seed, frame_id, mic_id)`, and reduce
confidence. `gain_mismatch_db` is the standard deviation of a static seeded
Gaussian per-mic RMS gain offset, deterministic per `(seed, mic_id)`, and
reduces confidence. The optional `seed` constructor argument selects the noise
stream; the default seed is fixed, so replays of the same scene, window, and
settings stay bit-identical, and zero-noise settings draw nothing. This
deterministic stress layer does not model stochastic sensor drift, frequency
response, clipping, automatic gain control, correlated electronics noise, or
hardware clock recovery.

`air_absorption_db_per_m` (default `0.0`) optionally applies a broadband
air-absorption factor `10 ** (-air_absorption_db_per_m * distance / 20)` to
the L1 RMS. It is a single broadband coefficient, not a frequency-dependent
atmospheric model.

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
`max_events` truncation. All scheduled sources share one room per frame, so
microphone signals are true mixtures with sample-accurate start offsets;
per-source diagnostics come from the simulation premix, and each scheduled
source is emitted as one detection. This is not mixed-source separation of
unknown signals. With a configured waveform sink the backend also writes the
mixture and populates `waveform_paths` (see
[Room Acoustics](room_acoustics.md#waveform-export)).

Frames from this backend use provenance `room_acoustics` and include stable L2
diagnostic keys for `room_config`, `pyroomacoustics_version`,
`scheduled_source_ids`, `per_source_rir_summary`, `estimated_tdoa_matrix_s`,
`gcc_phat_peaks`, `direct_path_delay_s`, `per_mic_rms`, `rir_length_samples`,
`rir_peak_delay_s`, `waveform_sample_count`, `room_source_position_m`, and
`room_microphone_positions_m`.

Use it for approximate shoebox-room experiments, not as a calibrated acoustic
twin. It does not provide realistic occlusion, material behavior, directivity,
calibrated microphone response, production beamforming, or sim-real transfer.
`MicrophoneSpec.self_noise_db` and `AudioSourceSpec.directivity` are
metadata-only at L2: they pass through frames unchanged but are not applied to
the simulated waveforms.
