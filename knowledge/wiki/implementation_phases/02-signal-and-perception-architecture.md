# Implementation Plan 02 — Signal and Perception Architecture

Status: In progress. Subphases 02.1 and 02.2 and the bounded intervening R9.4
qualification are complete. Subphase 02.3 remains planned.

## Objective

Separate acoustic signal production from perception so the same activity detector and DOA estimator consume simulated and real microphone-array signals. Remove source-conditioned detection from propagation while retaining the minimum stable frame and dataset boundaries needed by runtime consumers.

This breaking migration applies the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision directly: consumer migration and removal of the superseded architecture are part of Plan 02 completion.

## Target Flow

```text
Simulated propagation or real capture
                |
                v
      MicrophoneSignalBlock
                |
                v
   AudioPerceptionPipeline
      activity -> DOA
                |
                v
       AudioSensorFrame
        observations[]
```

The signal block remains separately available to recording and feature extraction. Simulation truth follows a separate dataset-only path.

## Subphase 02.1 — Signal Producer Boundary

#### Implementation

Propagation now has a public scene-to-signal operation: `PropagationBackend.propagate(scene, array_id, time_window) -> MicrophoneSignalBlock`. The frozen block owns a copied, C-contiguous, read-only `float32` sample matrix shaped `[microphone, sample]`, ordered microphone identifiers, array identity, array-authoritative sample rate, the exact requested time window, per-channel validity, producer identity, provenance, and concise operational diagnostics. Its sample count is exactly `max(1, round(window_duration * sample_rate_hz))`.

`AnalyticAcoustics` renders source signals, private stems, occlusion, directivity, gain, and effects through one shared internal path. `propagate()` projects only the final combined mixture into the exact public window. It does not estimate DOA, construct detections or frames, or invoke a `WaveformSink`; analytic channels are all valid and follow `MicrophoneArraySpec` order. Propagation therefore supports mono arrays independently from the geometry constraints enforced by individual perception estimators.

The existing `AnalyticAcoustics.simulate() -> AudioSensorFrame` behavior remains temporarily available through one explicitly legacy internal helper used by Core, CLI, Isaac, Lab, and Kit. It consumes the same private render and preserves current frames, diagnostics, waveform output, and full rendered tails until Subphases 02.2 and 02.3 migrate those consumers. No frame-v2 field, schema, CLI output, package version, or consumer-facing observation changed in this subphase.

#### Key Decisions

- Public signal channels represent microphones, never sources.
- The exact-window block contains the final mixture after propagation and enabled physical effects.
- The propagation plugin contract produces signals only; DOA, detections, frames, and persistence remain outside `propagate()`.
- Private stems and source detail remain internal and are never required by the public contract or future ordinary perception.
- The signal contract is a Python runtime boundary, not a new serialized schema.

#### Problems / Limitations

The public block intentionally omits a rendered tail beyond the requested window; the temporary legacy waveform writer still receives the complete render. Cross-window orchestration, perception ownership, recording migration, and removal of the legacy frame bridge remain unresolved until Subphases 02.2 and 02.3. No physical-capture producer or Geometry Acoustics producer exists yet.

The completed 02.1 boundary remained unchanged through R9.4. That qualification
was independent of perception and introduced no production geometry backend.
Plan 02 now resumes directly at 02.2; no 02.1 commit was reverted or replayed.

## Subphase 02.2 — Perception, Frame, and Observation Contracts

#### Implementation

`AudioPerceptionPipeline` now owns activity detection, optional DOA estimation, and construction of `AudioSensorFrame`. Its injected activity-detector callable receives only valid channels in microphone order. No valid channel skips perception; inactive output emits no signal-derived observation; active output creates exactly one. Optional DOA runs only with at least two valid channels, and an unresolved `DoaEstimate` is retained unchanged. The pipeline verifies block/array identity, sample rate, microphone order, and array-owned geometry, computes aggregate RMS only from the observed block, performs no file IO, and initializes `waveform_paths=()`.

The public `AudioObservation` contains only:

- `observation_id`;
- `origin: ObservationOrigin`, with exactly `signal_derived` and `external_system`;
- non-empty `detector_id`;
- optional `detection_score` with detector-defined semantics;
- optional `doa: DoaEstimate`;
- concise non-privileged diagnostics.

Scene source identity, source pose, oracle geometry, asset references, occlusion truth, and per-source measurements have left the observation contract. No classifier or tracker fields are reserved. `None` DOA means localization was not run; an unresolved `DoaEstimate` means it ran without a unique valid direction.

`AudioSensorFrame` now uses `ias.audio_sensor_frame.v3`: `producer_id`, `channel_validity`, `max_observations`, and `observations` replace the backend/detection surface while timing, array pose, aggregate RMS, provenance, diagnostics, and recorder-managed waveform references remain. Readers reject frame v2, and the checked schema and v3 JSON/NDJSON fixtures regenerate byte-identically. Dataset-manifest v1 and calibration-profile v1 remain unchanged while dataset records embed frame v3.

External observations must already be typed with `origin=external_system`. IDs are checked for uniqueness before the cap; the signal-derived observation precedes external observations deterministically; and `max_observations` truncates only that final order without comparing scores from different producers.

The temporary `simulate()` bridge now emits valid frame-v3 records with zero observations. Core, CLI, recording/replay, Replicator, Isaac, Lab, Kit, examples, and statistics use the new names. Until Phase 03 provides a concrete activity detector, all maintained default consumers intentionally produce waveform/RMS/frame output with zero observations and no oracle substitute.

Migrate the former modes directly:

| Former `detection_mode` | New ownership |
|---|---|
| `signal_energy` | `origin=signal_derived`; `detector_id` identifies the selected signal detector. |
| `external_metadata` | `origin=external_system`; `detector_id` identifies the external producer. |
| `scheduled_known_source` | Dataset ground truth, never a runtime observation by itself. |
| `manual_annotation` | Dataset annotation provenance, never an observation origin. |

#### Key Decisions

- A frame contains zero or more observations but is not itself an observation.
- Persistence belongs to recording services, not frame construction.
- `origin` identifies the evidence path; `detector_id` identifies the producer; neither identifies a true source.
- Detection score and DOA confidence remain separate and are meaningful only with their producer semantics.

#### Problems / Limitations

The temporary scene-to-frame bridge still owns rendering and legacy waveform persistence. Subphase 02.3 must replace that orchestration with signal-block-to-perception composition and remove the bridge. No concrete activity detector is registered yet, so zero default observations are expected rather than a missing capability fallback.

## Subphase 02.3 — Orchestration, Migration, and Cleanup

#### Implementation

Use one thin orchestration path to obtain a signal block, run perception, return the frame, and pass the original block to recording when requested. Perception owns state and reset behavior; array geometry is explicit and never inferred from source truth.

Replace the temporary frame-v3 `simulate()` bridge in Core, CLI, Isaac, Lab, and Kit without reintroducing the removed source-conditioned detection architecture. Remove only the bridge-specific assembly and waveform-tail path after every maintained consumer uses the signal block directly.

#### Key Decisions

- Leave one maintained signal-to-observation path without compatibility aliases.
- Prefer direct composition over additional packet, assembler, or manager abstractions without a consumer.
- Tests follow the active production contract and do not justify unused functionality.

#### Problems / Limitations

The breaking migration spans Core, CLI, recording/replay, Isaac Sim, Isaac Lab, Kit, OmniGraph, Replicator, schemas, and packaging. Verify consumers and protected evidence before removal.

## Artifacts

Subphase 02.1 produced the public `MicrophoneSignalBlock`, scene-to-signal propagation protocol, analytic producer, and temporary bridge. Subphase 02.2 produced `ObservationOrigin`, `AudioObservation`, `AudioPerceptionPipeline`, frame v3, the migrated consumers, and removal of source-conditioned detection assembly. Subphase 02.3 still owns shared signal-to-frame orchestration and final bridge removal. This plan does not select activity or DOA algorithms.

## Files

- `src/isaac_audio_sensors/core/types/_signal.py`
- `src/isaac_audio_sensors/core/types/_frame.py`
- `src/isaac_audio_sensors/core/perception.py`
- `src/isaac_audio_sensors/core/plugins/protocols.py`
- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/schemas/audio_sensor_frame.v3.schema.json`

Current cross-cutting contract ownership is described by [[topics/public-contracts-and-recording|Public Contracts and Recording]].

## Version Notes

- 2026-09-03: Implemented Subphase 02.1 with the exact-window microphone-signal contract and analytic producer while retaining one temporary legacy frame bridge.
- 2026-09-03: Sequenced the bounded R9.4 selected-provider qualification after the completed 02.1 boundary and before 02.2 without changing executable behavior.
- 2026-09-03: Completed R9.4 without changing the Plan 02 signal boundary; Plan 02 resumes at 02.2.
- 2026-09-03: Implemented Subphase 02.2 with perception-owned observed-only frames, frame schema v3, migrated consumers, and intentional zero default observations until Phase 03; Subphase 02.3 remains planned.
