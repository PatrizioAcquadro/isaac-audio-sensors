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
downmixed, and sample rates must already match the frame sample rate. The
`soundfile` dependency is used only for file-backed assets, not generated
waveforms.

Multiple active sources are scheduled with the shared half-open
`AudioTimeWindow` behavior. Sources are ordered deterministically and truncated
by `max_events`. In v1, each scheduled source is simulated independently and
gets one deterministic detection. The backend does not claim mixed-source
separation.

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
- `per_source_rir_summary`;
- `per_source_rir_length_samples`.

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
- `room_source_position_m`;
- `room_microphone_positions_m`.

The room model is still approximate. Absorption, room dimensions, source
directivity, microphone response, occlusion, material behavior, production
beamforming, and sim-real transfer should be treated as out of scope for v1 L2,
not measured truth.
