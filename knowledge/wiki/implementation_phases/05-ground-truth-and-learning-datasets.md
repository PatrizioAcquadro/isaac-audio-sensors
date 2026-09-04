# Implementation Plan 05 — Ground Truth and Learning Datasets

Status: Subphases 05.1–05.3 implemented.

## Objective

Store observations and simulation truth as aligned but independent dataset information. Prevent privileged scene state from leaking into robot-policy inputs while preserving supervision for training, evaluation, and diagnosis.

Plan 05 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: one clear observation, truth, annotation, and recording model replaces overlapping dataset paths.

## Subphase 05.1 — Truth and Observation Boundary

#### Implementation

`recording.FrameTruth`, `TruthEvent`, and `AnnotationRecord` define supervision beside the observed frame. Truth identifies the frame, array, exact window, and sample rate. `None` means unavailable truth; an empty `truth_events` sequence means a known empty scene. Annotations carry a caller-authored label and provenance with optional explicit source and observation references.

`recording.simulate_dataset_frame()` returns `(frame, block, truth)` from one private analytic render, sharing perception and waveform-sink composition with `simulate_frame()`. It emits one truth event per snapshot source, including inactive sources. Snapshot world pose, array-relative bearing/elevation and distance, authored class, prim, and asset reference stay outside observations. A coincident source has no direction; a vertical source has no azimuth.

Schedule overlap and full-window source emission RMS are distinct from received RMS. Received evidence uses per-source private stems after propagation, directivity, occlusion, gains, and linear microphone response, cropped to the public window. Mixture residual RMS compares the final float32 block with the summed linear stems; it includes mixture noise, electronics, and float32 conversion, not a pure-noise or SNR estimate. Existing occlusion maps are copied only when supplied by the snapshot. No audibility threshold, matching, or positive-target decision is made here.

`SessionRecorder.append_frame(frame, signal_block, *, is_reset=False, truth=None, annotations=())` validates supervision before advancing frame, audio, or shard state. Invalid supervision follows existing drop accounting. It stores the observed frame, optional truth, and annotations together in each canonical `ias.dataset_frame_record.v2` JSONL row. Existing episode buffering, overlap carry, time-gap insertion, resets, atomic shard promotion, and crash/finalization recovery preserve the same alignment.

`LoadedFrame.truth` and `LoadedFrame.annotations` expose supervision separately from `LoadedFrame.frame`. Replay carries that loaded record; FLAC export copies frame records unchanged while transcoding only the audio. Truth remains optional for metadata-only, real-capture, and existing scalar consumers.

`ias.audio_dataset_manifest.v2` removes `EpisodeRecord.source_truth` and the old `SourceTruth` model. Necessary schema resources, release audits, manifest examples, and the deterministic session fixture are migrated; fixture audio is byte-identical. Old manifest and frame-record versions and legacy truth fields are rejected without compatibility readers. Frame v3, calibration v1, and unreleased package version 3.0.0 remain unchanged. This is the minimum migration needed for one truth authority; learning adapters and the remaining consumer cleanup stay in 05.2/05.3. No public `GroundTruthAssembler`, stem output, or waveform duplication is introduced.

#### Key Decisions

- Ground truth is beside the frame, never inside `AudioObservation`.
- Observation and truth cardinality are independent.
- Private stems and scene state may support supervision but never policy observations.
- Unmatched observations and truth events are valid evaluation outcomes.
- Emission is derived from full-window source RMS, not merely schedule overlap. `TruthEvent.emitting` is derived, not a second serialized authority.
- Annotations have unique frame-local IDs and explicit provenance. References to observations must resolve in the frame; references to sources resolve when truth is available.
- Version only the two changed dataset contracts; keep one canonical serializer and no legacy readers.

#### Problems / Limitations

Simulation truth describes only the implemented producer model. Geometry describes the supplied snapshot while RMS integrates the rendered window, including supported motion. The producer renders window-local emission; cross-window arrivals and reverberation are not added by truth extraction. Audibility thresholds and observation-to-truth matching remain evaluator-owned. Automatic production currently supports only `AnalyticAcoustics`.

## Subphase 05.2 — Robot-Learning Sample Boundary

#### Implementation

`recording.LearningDataset.open()` composes checked `SessionDataset` readers for a corpus of complete artifacts. `iter_samples()` preserves caller session order and recorded frame order. Each `LearningSample` separates numerical `policy_inputs`, the complete `AudioSensorFrame`, optional truth and annotations, and alignment context. Supervision is exposed only with `with_supervision=True`; `with_audio=False` avoids waveform decoding. Context retains dataset/session/episode identities, dataset frame index, authoritative shard sample bounds, sample rate, channel order, episode start, and explicit reset. The shared loader rejects duplicate or incorrectly timed resets, frame sample-rate/channel mismatches, and disagreement between manifest and capture configuration before exposing records. The recorder rejects mismatched channel IDs even when no waveform is supplied.

The policy projection selects waveform, channel validity, observed RMS, detection scores, and estimated/candidate DOA angles and confidence. Poses, IDs, provenance, free-form diagnostics, truth, and annotations never enter this projection. Waveform reads use the existing half-open shard reference, including shorter references at shard boundaries. WAV stays float32; PCM16 and left-aligned PCM24 decode to float32 full-scale amplitude without peak normalization. Missing audio remains unavailable rather than silent, and decoded non-finite audio is rejected.

`collate_learning_samples()` pads individual frames without truncation. Boolean masks preserve audio lengths, observation counts, candidate counts, and unavailable scalar features independently of microphone validity. Candidate bearing and elevation axes remain independent. Frame metadata, truth, and annotations stay in separate ordered tuples; observation and truth cardinalities are never matched. Mixed sample rates or channel orders fail rather than triggering implicit conversion. These rules belong to the learning adapter; serialized observations do not change. The exact NumPy fields and shapes are documented in [[topics/public-contracts-and-recording|Public Contracts and Recording]].

Manifest v3 adds stable acquisition `session_id`, independent of artifact `dataset_id`. The recorder accepts it in configuration and defaults to the initial dataset ID; exports preserve it. `begin_episode()` accepts optional `trajectory_id` and `source_asset_ids`, persisted through recorder state v2, crash resume, and finalization recovery. Unknown asset inventory is null; known empty inventory is an empty array. These are caller-declared global identities, not inferred from truth, paths, poses, or seed. Previous manifest and recorder-state versions are rejected without compatibility readers; frame-record v2, frame v3, and package 3.0.0 remain unchanged. Required schemas, examples, release references, and the fixture manifest are migrated; fixture audio, frame records, and markers are byte-identical to the 05.1 baseline.

`LearningDataset.build_split()` accepts explicit ratios and seed, installs an in-memory corpus assignment, and returns artifact IDs per partition. `iter_samples(split=...)` uses this assignment without rewriting manifest splits. Artifacts sharing a session always stay together. By default, shared scenes, trajectories, and source assets also connect acquisitions transitively; `isolate_by` explicitly selects optional isolation axes. Missing selected identities, duplicate artifacts, and insufficient independent groups fail with actionable errors. A failed request clears the previous assignment. Canonical records are checked before accepting an assignment. Whole connected groups are assigned to frame-weighted targets using the existing deterministic allocation algorithm; input path order, ratio mapping order, and isolation-axis order do not affect the result. Existing single-session split APIs retain their distinct physical-shard role and reuse that allocation helper.

#### Key Decisions

- Only `policy_inputs` is intended for policy consumption; full frames and supervision remain explicit separate outputs.
- Keep samples and batches NumPy-only, with no new dependency or persisted waveform copy.
- Preserve acquisition identity across artifact transformations, including FLAC export.
- Declare grouping identities during recording. Reusing a sound under a different ID does not make it independent.
- Always isolate sessions; relax optional scene/trajectory/asset constraints only through explicit experiment-owned choices.
- Pad single-frame records only; temporal sequence construction and target matching remain consumer-owned.

#### Problems / Limitations

Isolation guarantees apply to declared identities. The SDK cannot discover undisclosed asset reuse or infer trajectory identity. Existing producers that omit trajectory/asset metadata can still record and load samples, but strict corpus splitting requires those identities or explicit axis exclusion. Connected groups may prevent requested partitions or make achieved frame ratios differ from targets; no constraint is silently weakened. Acoustically equivalent assets with different declared IDs remain the producer's responsibility.

The full frame can contain pose and arbitrary diagnostics and is not itself a policy-safe tensor. NumPy arrays are exposed read-only to avoid accidental edits; this is an API boundary, not a security sandbox. No PyTorch adapter, temporal sequence builder, automatic Kit/Lab truth capture, new learning model, or Phase 07 tensor projection is introduced.

## Subphase 05.3 — Dataset Migration and Cleanup

#### Implementation

Manifest v4 removes unused episode `array_poses`, `labels`, and `visual_sync_asset_ids`, the `ManifestPose` model, and `visual_sync` assets. The recorder never populated these metadata paths. Their parser, schema, validation, and statistics support is removed, including `Statistics.label_counts`, `Statistics.visual_sync_count`, JSON `labels`, and `modalities.visual_sync_count`. Frame annotations remain the label authority; no automatic conversion is introduced.

Recorder, loader, replay, validation, FLAC, learning, manifest examples, the deterministic fixture manifest, and packaged schema consumers use v4. Manifest v1–v3 and removed fields are rejected without compatibility readers. Frame v3, frame-record v2, recorder-state v2, calibration v1, and package 3.0.0 remain unchanged. Fixture audio, JSONL rows, configuration, and markers are unchanged.

Loader and validation call the canonical frame-record parser directly; the duplicate JSON/version wrapper is removed. Replay emits events from the checked loader stream without repeating timestamp, reset, or frame-count validation. Corruption remains located and machine-readable across validation, loading, replay, and learning. Validation of independently verified shards also preserves separate truth and annotations in its loaded records. The shared manifest/truth serializer, maintained learning example, and distinct session-shard and corpus split responsibilities remain. No public `GroundTruthAssembler`, duplicate waveform storage, or test-only dataset fields are introduced.

#### Key Decisions

- Keep one canonical observation, truth, annotation, and recording model.
- Preserve required historical evidence without retaining obsolete active APIs.
- Version only the changed manifest contract; remove unused metadata and statistics without substitute fields.

#### Problems / Limitations

Existing v1–v3 artifacts require explicit external migration before loading; there is no automatic migration of local datasets or protected evidence. This dataset-only cleanup adds no live Isaac, GPU, training, or downstream qualification claim.

## Artifacts

Implemented artifacts are dataset truth and annotation contracts, a single-render analytic composition, atomic frame-record v2 persistence, and current manifest v4 resources/examples. Subphase 05.2 adds NumPy learning samples/collation, corpus splitting, acquisition identities, and a maintained end-to-end example at `examples/core/learning_samples.py`. Matching remains evaluator-owned.

Focused tests cover empty/inactive/silent/partial/multiple sources, propagation outside the captured window, rotated and coincident geometry, motion semantics, occlusion/reflections, noise and nonlinear electronics, actual PyRoom shoebox/prism routes, immutable supervision, canonical round-trips, invalid alignment, resets, shard boundaries, metadata-only sessions, time gaps, crash/finalization recovery, replay, and FLAC preservation. The 05.3 host gate passes 581 unit/contract, 277 integration, and 58 release tests; optional audio, the learning example, schema regeneration, and fixture validation pass. All seven non-manifest fixture files are byte-identical to 8d7a71e. Detailed closeout evidence is recorded in the log.

## Files

Main implementation: `src/isaac_audio_sensors/recording/truth.py`, `src/isaac_audio_sensors/recording/simulation.py`, `src/isaac_audio_sensors/recording/recorder.py`, and `src/isaac_audio_sensors/recording/learning.py`; corpus grouping is internal to the same recording subsystem. Frame-record parsing and loading remain in the same recording subsystem; manifest v4 generation remains in the schemas subsystem. Contracts and usage are documented in [[topics/public-contracts-and-recording|Public Contracts and Recording]].
