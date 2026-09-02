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

The propagation backend may use individual source signals and private stems internally because distinct positions require distinct propagation. Its public result contains only the combined microphone channels. Private stems remain optional truth or diagnostic material and are never an input to ordinary perception.

Real hardware capture must be able to produce the same signal-block meaning without simulator or scene dependencies.

#### Key Decisions

- Individual source signals are necessary inside propagation; exposing them to perception is not.
- Public signal channels represent microphones, never sources.
- The final observed block includes the effects that a physical detector would receive.
- The backend owns propagation only and does not emit observations.

#### Problems / Limitations

Some providers may expose no source-separated output. The public contract must not require it. Simulator-specific path diagnostics also remain outside ordinary sensor observations.

## Subphase 02.2 — Perception-Owned Frame Construction

#### Implementation

Make `AudioPerceptionPipeline` the owner of activity detection, optional DOA estimation, and creation of the corresponding `AudioSensorFrame`. Do not introduce a public `FrameAssembler` class whose only responsibility is object construction; a small internal composition function is sufficient if it improves readability.

Retain `AudioSensorFrame` as the unit of one sensor update. A frame is required even when no activity is detected, may contain zero or several observations, carries shared time and array metadata once, anchors waveform and dataset joins, and maps naturally to one robot-learning step. Folding the frame into `AudioObservation` would duplicate shared metadata, lose silent windows, and incorrectly require one observation per sensor update.

Persistence remains the responsibility of recording services. Constructing a stable frame is not itself persistence.

#### Key Decisions

- Keep `AudioSensorFrame`; remove a standalone public `FrameAssembler` abstraction.
- A frame contains observations but is not an observation.
- Silent and invalid windows remain representable.
- Frame-wide metadata is never repeated inside every observation.

#### Problems / Limitations

The current serialized frame shape mixes privileged source information with observations. This plan requires an explicit schema migration rather than an in-place semantic reinterpretation.

## Subphase 02.3 — Minimal Observation Contract

#### Implementation

Replace the overloaded detection record with a compact `AudioObservation` that represents only evidence produced from an observed signal or an external system. Its initial meaning covers observation identity, origin, detector identity, a clearly defined detector score when available, an optional `DoaEstimate`, and concise diagnostics.

The initial public contract contains only:

- `observation_id`, identifying this observation rather than a true source;
- `origin`, represented by an `ObservationOrigin` enum with exactly `signal_derived` and `external_system` values;
- `detector_id`, a non-empty string identifying the activity detector or external producer;
- optional `detection_score`, whose unit and interpretation belong to the identified detector;
- optional `doa`, containing a `DoaEstimate` only when localization was attempted;
- concise diagnostics that remain observable or operational rather than privileged scene state.

Do not reserve classifier or tracker fields before those components exist. Scene source identity, source pose, oracle geometry, asset references, occlusion truth, and per-source stem measurements leave the observation contract.

After truth separation, observation origin needs only signal-derived and external-system values. Scheduled simulation activity and manual annotations belong to dataset truth or annotation records rather than the runtime origin enum.

Migrate the four former `detection_mode` meanings directly:

| Former `detection_mode` | New ownership |
|---|---|
| `signal_energy` | Replace with `origin=signal_derived`; `detector_id` names the selected signal activity detector. |
| `external_metadata` | Replace with `origin=external_system`; `detector_id` names the external producer. |
| `scheduled_known_source` | Remove from runtime observations; scheduled emission and source state belong to dataset ground truth. |
| `manual_annotation` | Remove from runtime observations; manual labels belong to dataset annotation provenance. |

Remove the `detection_mode` field and its closed enum after migrating consumers. Do not retain aliases that allow the old and new meanings to coexist.

#### Key Decisions

- `DoaEstimate` is optional because detection and localization are separate stages.
- `None` means localization was not run; an unresolved `DoaEstimate` means it ran but could not select a unique valid direction.
- `origin` identifies the evidence path, while `detector_id` identifies the concrete producer; neither field identifies a true source.
- Detector identity remains extensible as a string without expanding a closed mode enum for every algorithm.
- A score is not called confidence unless its semantics are calibrated and comparable.

#### Problems / Limitations

External observations may have different evidence semantics from signal-derived observations. Their origin and producer identity must remain visible without turning the observation into a generic unvalidated dictionary.

## Subphase 02.4 — Orchestration and Lifecycle

#### Implementation

Use one thin sensor orchestration path to obtain a signal block, run perception, return the frame, and pass the original block to recording when requested. Perception owns explicit state and reset behavior for rolling context, noise estimation, and discontinuities. The architecture must not require a new public packet, assembler, or manager type unless a demonstrated consumer needs it.

#### Key Decisions

- Prefer a direct tuple or existing service boundary over a ceremonial wrapper object.
- Signal production and perception have independent lifecycle and capability reporting.
- Array geometry is bound once to the perception pipeline or supplied explicitly; it is never inferred from source truth.

#### Problems / Limitations

Changing the propagation protocol affects Core, CLI, Isaac, Kit, recording, replay, and Isaac Lab reference consumers. The migration must remain one coherent contract change without parallel legacy paths.

## Subphase 02.5 — Consumer Migration and Legacy Removal

#### Implementation

Migrate every maintained consumer to the new signal and observation contracts. Then remove the superseded `AudioDetection`, `DetectionMode`, source-conditioned detection paths, and their unused schema, configuration, adapter, dependency, test, and documentation surfaces. Do not retain production paths only for obsolete tests.

#### Key Decisions

- Leave one maintained signal-to-observation path, without legacy aliases or parallel implementations.
- Tests follow the active production contract and do not justify unused production functionality.

#### Problems / Limitations

Verify consumer, package, and protected-evidence boundaries before removal.

## Artifacts

This plan should result in the new signal, observation, and frame contracts, one shared orchestration flow, directly migrated consumers, and removal of the superseded detection architecture. It does not itself select activity or DOA algorithms.

## Files

Exact source files and schemas are deferred to implementation. Current contract ownership is described by [[topics/public-contracts-and-recording|Public Contracts and Recording]].
