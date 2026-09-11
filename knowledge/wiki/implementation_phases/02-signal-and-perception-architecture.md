# Implementation Plan 02 — Signal and Perception Architecture

Status: 02.1–02.3 complete; current frame contract is v4.

## Objective

Separate propagation from observed-only perception: producer → `MicrophoneSignalBlock` → `AudioPerceptionPipeline` → frame observations. Recording consumes the same PCM; truth follows a separate supervision path.

## Subphase 02.1 — Signal Producer Boundary

#### Implementation

Introduced immutable exact-window `[microphone, sample]` float32 blocks and `propagate(scene, array_id, time_window)`. Analytic renders the final mixture without detection or persistence.

#### Key Decisions

Microphone channels are never source channels. Private stems remain provider-owned.

#### Problems / Limitations

The temporary scene-to-frame bridge was removed in 02.3; no compatibility runtime remains.

## Subphase 02.2 — Perception, Frame, and Observation Contracts

#### Implementation

Introduced observed-only frames, explicit observation origins, optional activity score/DOA and external observations. Frame v3 replaced source-conditioned detection; the later confidence correction introduced v4.

#### Key Decisions

No schedules, source IDs/poses, oracle audibility or occlusion truth in observations. Confidence null differs from measured zero; ambiguity differs from unexecuted localization.

#### Problems / Limitations

This phase selected no detector/localizer; its deliberately empty defaults were superseded by Phases 03/04, not a fallback.

## Subphase 02.3 — Orchestration, Migration, and Cleanup

#### Implementation

`simulate_frame()` invokes propagation once, passes the same block to perception and optional recording, and returns frame/block. Consumers migrated; state/reset belongs to sensor or per-environment lifecycle owners.

#### Key Decisions

One composition path, no legacy `simulate()` bridge or backend-owned waveform writer. Keep recording and waveform export independent.

#### Problems / Limitations

Current common continuity is extended by Phase 06 and Lab behavior by Phase 07; historical empty tensors are not current behavior.

## Artifacts

Host, actual RTX Sim/Lab/Kit and downstream migration passed at closeout. [[topics/public-contracts-and-recording|Public Contracts]] owns current fields/versions and recorder validation.

## Files

`core/types/_signal.py`, `core/types/_frame.py`, `core/perception.py`, `core/simulation.py` under `src/isaac_audio_sensors/`.
