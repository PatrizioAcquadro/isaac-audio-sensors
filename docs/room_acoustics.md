# Room Acoustics

L2 `room_acoustics` is a supported optional v1 backend. Install the optional
room extra before using it:

```bash
python -m pip install -e ".[room]"
python examples/core/room_acoustics_demo.py
```

If `pyroomacoustics` is absent, core package import still succeeds and
`RoomAcousticsBackend.is_available()` returns `False`. Calling
`RoomAcousticsBackend.simulate(...)` without the dependency raises
`OptionalDependencyUnavailable` with an install hint for the `room` extra.
Tests that need the real dependency skip cleanly when it is unavailable.

The v1 scope for L2 is defined in [V1 Public Scope](v1_scope.md): dependency
gated, cleanly skipped or explicitly unavailable when the dependency is absent,
and diagnostic-rich when present. It is not a release promise for realistic
occlusion, material acoustics, sim-real calibration, or real hardware
benchmarks.

`RoomAcousticsBackend` uses `pyroomacoustics.ShoeBox` when available. It differs
from the synthetic TDOA backend in four ways:

- it creates approximate room impulse responses for a shoebox room;
- it generates per-microphone waveforms through `compute_rir()` and
  `simulate()`;
- it estimates TDOA from those microphone waveforms with GCC-PHAT;
- it keeps direct-path delay only as diagnostic comparison data.

The backend reads `RoomAcousticsSpec` fields for room dimensions, absorption,
`max_order`, `air_absorption`, and `ray_tracing`. It passes speed of sound and
sample rate to `pyroomacoustics` where the installed version supports those
arguments. Source waveforms are deterministic for generated `generated://...`
sources. File-backed `audio_asset_path` loading is limited to relative files
inside the checkout; mono files are loaded directly, multichannel files are
downmixed, and mismatched sample rates are resampled to the frame sample rate
with `scipy.signal.resample_poly`. The `soundfile` dependency is used for
file-backed assets and waveform export, not generated waveforms. See
[Audio Assets](audio_assets.md) for asset rules and external-corpus usage.

Multiple active sources are scheduled with the shared half-open
`AudioTimeWindow` behavior. Sources are ordered deterministically and truncated
by `max_events`. All scheduled sources share one `pyroomacoustics` room per
frame, so microphone signals are true mixtures; per-source diagnostics
(GCC-PHAT TDOA, per-mic RMS, RIR lengths and peak delays) come from the
per-source simulation premix, and each scheduled source still gets one
deterministic detection. The backend does not claim mixed-source separation of
unknown signals; per-source diagnostics are available because the simulator
knows each source's contribution.

Scheduling is sample-accurate: a source starting mid-window is zero-padded to
its exact start offset, a source that started before the window resumes from
its elapsed offset, and content is truncated at whichever comes first of the
source end and the window end. Generated sources emit a deterministic,
phase-continuous two-tone signal (a seeded fundamental plus a golden-ratio
overtone that keeps GCC-PHAT correlation aperiodic) over their whole active
interval, so consecutive windows concatenate without discontinuities.

## Waveform export

`RoomAcousticsBackend(waveform_writer=...)` accepts a waveform sink from
`isaac_audio_sensors.core.io.waveforms`. When configured, every frame's
microphone mixture is written and `AudioSensorFrame.waveform_paths` is
populated; without a sink, `waveform_paths` stays empty exactly as before.

- `FrameWaveformWriter(output_dir)` writes one deterministic multichannel WAV
  per frame named `{frame_id}.wav`.
- `ContinuousWaveformWriter(path)` appends window-exact chunks to one growing
  session WAV across ticks, overlap-adding reverb tails carried past each
  window; frames reference their half-open `[start_sample, end_sample)` slice
  through the `waveform` diagnostics namespace, and `close()` flushes the
  final tail.

WAVs use the `FLOAT` subtype with raw, non-normalized simulation values, and
channels follow the `MicrophoneArraySpec.microphones` order (recorded in the
`waveform.channel_mic_ids` diagnostic). Frames with no active source still
write a window-length silent mixture so session streams stay gapless.
`IsaacAudioArraySensor` exposes this through `waveform_dir` and
`waveform_mode` (`"per_frame"` or `"session"`); the Isaac Lab sensor through
`write_waveforms`/`waveform_dir` (per-frame mode with per-env subdirectories);
TOML configs through `audio.write_waveforms` and `audio.waveform_dir`.
Doppler from per-tick source motion is not modeled yet and is deferred to the
Block 8 roadmap item.

Supported optional v1 diagnostics include these stable names.

Frame diagnostics:

- `backend`;
- `physical_waveform`;
- `room_id`;
- `room_config`;
- `pyroomacoustics_version`;
- `speed_of_sound_mps`;
- `sample_rate_hz`;
- `ambiguity_policy`;
- `active_source_count`;
- `scheduled_source_ids`;
- `max_events`;
- `time_window_s`;
- `window_sample_count`;
- `per_source_rir_summary`;
- `per_source_rir_length_samples`;
- `waveform` (only when a waveform sink is configured).

Detection diagnostics:

- `backend`;
- `physical_waveform`;
- `room_id`;
- `room_config`;
- `pyroomacoustics_version`;
- `speed_of_sound_mps`;
- `sample_rate_hz`;
- `array_geometry_rank_xy`;
- `estimated_tdoa_matrix_s`;
- `gcc_phat_peaks`;
- `direct_path_delay_s`;
- `per_mic_rms`;
- `rir_length_samples`;
- `rir_peak_delay_s`;
- `waveform_sample_count`;
- `source_waveform_mode`;
- `scheduled_start_offset_samples`;
- `scheduled_content_sample_count`;
- `room_source_position_m`;
- `room_microphone_positions_m`.

The room model is still approximate. Absorption, room dimensions, source
directivity, microphone response, occlusion, material behavior, production
beamforming, and sim-real transfer should be treated as out of scope for v1 L2,
not measured truth.
