# Implementation Plan 02 — Signal and Perception Architecture

Status: Planned breaking architecture change after provider qualification and before new observed perception is added.

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

Change propagation from a scene-to-frame operation into a scene-to-microphone-signal operation. A `MicrophoneSignalBlock` represents one time-aligned multichannel array block with ordered microphone channels, array identity, sample rate, time window, channel validity, and concise signal provenance.

The propagation backend may use individual source signals and private stems internally because distinct positions require distinct propagation. Its public result contains only the combined microphone channels. Private stems remain optional truth or diagnostic material and are never an input to ordinary perception. Real hardware capture must be able to produce the same signal-block meaning without simulator or scene dependencies.

#### Key Decisions

- Public signal channels represent microphones, never sources.
- The final observed block includes the effects that a physical detector would receive.
- The backend owns propagation only and does not emit observations.
- Private stems are never required by the public contract or ordinary perception.

#### Problems / Limitations

Some providers expose no source-separated output, so the public contract cannot require it. Simulator-specific path diagnostics remain outside ordinary sensor observations.

## Subphase 02.2 — Perception, Frame, and Observation Contracts

#### Implementation

Make `AudioPerceptionPipeline` own activity detection, optional DOA estimation, and construction of `AudioSensorFrame`. Keep the frame as one sensor update even when it has no observations: it carries shared time and array metadata once, preserves silent or invalid windows, anchors recording and dataset joins, and maps to one robot-learning step. Do not add a public `FrameAssembler`; a small private composition function is sufficient if useful.

Replace the overloaded detection record with `AudioObservation`, containing only:

- `observation_id`;
- `origin: ObservationOrigin`, with exactly `signal_derived` and `external_system`;
- non-empty `detector_id`;
- optional `detection_score` with detector-defined semantics;
- optional `doa: DoaEstimate`;
- concise non-privileged diagnostics.

Scene source identity, source pose, oracle geometry, asset references, occlusion truth, and per-source measurements leave the observation contract. Do not reserve classifier or tracker fields before those components exist. `None` DOA means localization was not run; an unresolved `DoaEstimate` means it ran without a unique valid direction.

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

External and signal-derived observations can have different evidence semantics. The schema migration must preserve that distinction without becoming a generic unvalidated dictionary.

## Subphase 02.3 — Orchestration, Migration, and Cleanup

#### Implementation

Use one thin orchestration path to obtain a signal block, run perception, return the frame, and pass the original block to recording when requested. Perception owns state and reset behavior; array geometry is explicit and never inferred from source truth.

Migrate all maintained consumers together. Then remove `AudioDetection`, `DetectionMode`, `detection_mode`, source-conditioned detection, the public `FrameAssembler` concept, parallel legacy paths, and their unused schema, configuration, adapter, dependency, test, and documentation surfaces. Do not retain production paths only for obsolete tests.

#### Key Decisions

- Leave one maintained signal-to-observation path without compatibility aliases.
- Prefer direct composition over additional packet, assembler, or manager abstractions without a consumer.
- Tests follow the active production contract and do not justify unused functionality.

#### Problems / Limitations

The breaking migration spans Core, CLI, recording/replay, Isaac Sim, Isaac Lab, Kit, OmniGraph, Replicator, schemas, and packaging. Verify consumers and protected evidence before removal.

## Artifacts

Expected artifacts are the signal, observation, and frame contracts, one shared orchestration flow, migrated consumers, and removal of the superseded detection architecture. This plan does not select activity or DOA algorithms.

## Files

Exact source files and schemas are deferred to implementation. Current contract ownership is described by [[topics/public-contracts-and-recording|Public Contracts and Recording]].
