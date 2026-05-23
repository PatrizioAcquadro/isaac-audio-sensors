# Acoustic Fidelity Ladder

The package uses a five-level acoustic fidelity ladder to separate stable
runtime behavior from future realism work. The ladder is public API through
`isaac_audio_sensors.ACOUSTIC_FIDELITY_LADDER`,
`isaac_audio_sensors.AcousticFidelityLevel`, and
`isaac_audio_sensors.fidelity_level_for_backend(...)`.

`KNOWN_BACKENDS` and `get_backend(...)` remain the runtime backend registry.
Only L0, L1, and L2 are selectable runtime backend levels in v1. L3 and L4 are
documented so future config, diagnostics, artifacts, and optional dependencies
can be added without changing L0-L2 backend ids or required
`AudioSensorFrame` v1 fields.

All levels emit, or future implementations must emit, records compatible with
`AudioSensorFrame` v1 until a future schema version is introduced. New
diagnostics, artifact references, calibration files, and dependency-specific
metadata must be optional so existing v1 readers can ignore them.

AudioSensorFrame v1 compatibility is part of the ladder contract.

| Level | Public name | v1 lifecycle | Backend id or family | Optional dependencies | `AudioSensorFrame` v1 compatibility |
| --- | --- | --- | --- | --- | --- |
| L0 | `geometry_only` | Stable v1 | backend id `geometry_only` | None | Emits v1 frames |
| L1 | `tdoa_synthetic` | Stable v1 | backend id `tdoa_synthetic` | None | Emits v1 frames |
| L2 | `room_acoustics` | Supported optional v1 | backend id `room_acoustics` | `room` extra with `pyroomacoustics`, `scipy`, and `soundfile` | Emits v1 frames when installed |
| L3 | `advanced_realism` | Provisional v1 direction | future backend family, no selectable v1 backend id | Future advanced-acoustics extras | Must remain v1-compatible until a new schema exists |
| L4 | `sim_real_calibration` | Experimental/tooling v1 direction | future tooling family, no stable v1 runtime backend id | Future calibration-tooling extras | Artifacts and diagnostics must stay optional for v1 readers |

## L0 `geometry_only`

L0 is the stable deterministic geometry baseline. It computes source bearing,
source distance, and sector labels from known scene and array poses.

It does not model acoustic propagation, per-microphone time delay as a physical
measurement, waveforms, reverberation, occlusion, diffraction, scattering,
background noise, or physical microphone response.

Use L0 for coordinate-policy checks, UI plumbing, deterministic trace tests,
and ground-truth-style supervision records.

## L1 `tdoa_synthetic`

L1 is the stable direct-path synthetic TDOA backend. It computes
per-microphone delay and RMS diagnostics from source and microphone geometry.
Two-microphone front/back ambiguity is represented explicitly through DOA
candidate bearings and ambiguity fields.

It does not model a reverberant room, hardware microphone response, calibrated
noise, speech recognition, learned sound-event detection, or production
beamforming.

Use L1 when downstream code needs per-microphone delay/RMS fields while staying
fully deterministic and import-safe in the pure Python core.

## L2 `room_acoustics`

L2 is the supported optional room-acoustics path. When `pyroomacoustics` is
installed through the `room` extra, the backend can build an approximate
shoebox-room response, generate per-microphone waveforms, and estimate delays
with GCC-PHAT diagnostics from those waveforms. RIR length, RIR peak delay,
waveform sample count, per-mic RMS, room config, speed of sound,
`pyroomacoustics` version, source/microphone room positions, and direct-path
delay comparison data are recorded in additive diagnostics.

Multiple active sources use the same half-open window and `max_events`
scheduling policy as L0/L1. In v1, L2 simulates scheduled sources
independently and emits one detection per source; it does not claim mixture
separation.

It is not a calibrated acoustic twin. It does not claim full material
realism, occlusion realism, directivity realism, calibrated hardware
microphone response, production beamforming, or sim-real transfer.

The pure package import and L0/L1 usage must not require L2 dependencies. If
the optional dependency is missing, L2 fails lazily when the backend is used.

## L3 `advanced_realism`

L3 is provisional in v1. It names the future direction for richer wave/RIR,
occlusion, material, directivity, noise, and estimator realism. It is not a
complete v1 runtime backend and is not included in `KNOWN_BACKENDS`.

Future L3 work should be additive:

- use optional config sections instead of changing existing L0-L2 required
  config;
- place backend-specific evidence in optional diagnostics;
- reference optional artifacts such as RIRs or waveform captures through
  optional fields or diagnostics;
- require advanced dependencies only through optional extras.

L3 must not require new `AudioSensorFrame` v1 fields. If richer realism needs a
breaking trace shape, it should introduce a future schema version instead.

## L4 `sim_real_calibration`

L4 is experimental/tooling in v1. It names the future direction for measured
microphone-array pose, gain, time-offset, noise calibration, validation
artifacts, and sim-vs-real comparison tooling. It is not a stable v1 runtime
backend and is not included in `KNOWN_BACKENDS`.

Future L4 work should be additive:

- keep calibration files and measured datasets outside required core imports;
- attach calibration provenance through optional diagnostics;
- reference validation artifacts without making them required frame fields;
- expose tooling dependencies through optional extras.

L4 should improve evidence and calibration workflows without implying that the
package provides automatic hardware calibration or guaranteed physical-system
transfer in v1.

## Compatibility Rules

- L0 and L1 backend ids are stable v1 API.
- L2 backend id and frame shape are supported optional v1 API; detailed room
  diagnostics may grow additively.
- L3 and L4 names, statuses, and future backend families may evolve
  additively during v1, but they must not be presented as implemented stable
  runtime backends until implementations and tests exist.
- `AudioSensorFrame` v1 required fields remain unchanged across the ladder.
- Optional diagnostics, optional config, optional artifacts, and optional
  dependency extras are the extension path for L3/L4.
