# Roadmap

This roadmap tracks package-level work for `isaac-audio-sensors`. Completed
items are listed separately so future work does not repeat v1 capabilities that
already exist.

[V1 Public Scope](v1_scope.md) is the release-scope source of truth. Future
items below are not v1 release gates unless they are promoted by a later scope
change.

## Completed In V1.0.0

- Standalone Apache-2.0 package boundary with public docs, examples, schemas,
  tests, and source distribution metadata.
- Stable `AudioSensorFrame` v1 trace contract with JSON Schema export, trace
  examples, explicit units, poses, provenance, and deterministic `max_events`.
- Public acoustic fidelity ladder that marks L0 `geometry_only` and L1
  `tdoa_synthetic` as stable v1, L2 `room_acoustics` as supported optional v1,
  and L3/L4 as future-compatible metadata directions.
- Pure Python core with geometry-only and synthetic TDOA backends that import
  without Isaac Sim, Isaac Lab, Omniverse, pyroomacoustics, protobuf, ROS 2,
  CUDA, or torch.
- Optional `room_acoustics` backend using `pyroomacoustics` when installed.
- Isaac Sim live sensor lifecycle with repeated stage snapshot capture, JSONL
  writer fallback, debug primitive generation, active windows, and latest-frame
  access.
- Live USD pose resolution for nested transform stacks, moving source/array
  prims, robot/base-mounted arrays, microphone child prims, and explicit USD
  time-code reads.
- Semantic Isaac Sim discovery for common audio array/source metadata, native
  sound attrs, type/name signals, child microphone prims, roots, filters, and
  preferred entity selection.
- Isaac Lab `SensorBaseCfg`/`SensorBase` wrapper recovery path with import-safe
  fallbacks outside initialized Lab runtimes.
- Isaac Lab fixed-shape observation buffers for multi-env RL use, including
  event masks, bearings, confidence, sector one-hot, per-mic RMS, ambiguity
  masks, selected-env reset/update, and GPU device validation.
- Isaac Lab cloned-stage binding with namespace templates, explicit or
  discovered arrays/sources, child microphones, live transform re-reads, and
  selected-env updates.
- Isaac Lab entity binding for common scene/entity tensor patterns, including
  root/body pose tensors, body-name lookup, robot/body-mounted arrays,
  env-origin handling, and per-env diagnostics.
- Reference Omniverse extension UX for selected-prim binding, array/source
  authoring, backend selection, live update/export, overlay state, reusable
  config import/export, and optional lazy Replicator recording for recoverable
  `AudioSensorFrame` v1 payloads when Kit exposes the needed APIs.
- Release hygiene docs, versioning notes, archive audit script, build-time
  distribution audit, and final `1.0.0` promotion notes.

## Completed In V1.2.0

- Room-backend microphone mixtures from one shared room per frame, with
  per-source diagnostics derived from the simulation premix and
  sample-accurate source scheduling.
- Multichannel waveform export through `core.io.waveforms`: per-frame WAVs
  and a continuous session renderer with overlap-added reverb tails and
  `[start_sample, end_sample)` frame slices; `waveform_paths` is populated
  when export is enabled.
- Automatic resampling of file-backed audio assets and a documented
  external-corpus workflow (see [Audio Assets](audio_assets.md)).

## Future Work

- Phases 9, 10, and 11 are planned after the `1.0.0` release and are not
  prerequisites for the final v1 package gate.
- Block 8: Doppler from per-tick source motion in the continuous renderer,
  together with source velocity tracking in the scene model (explicitly
  deferred from the 1.2.0 audio-output work), plus rendering sim-time gaps
  between throttled ticks.
- Automated Isaac Sim and Isaac Lab smoke CI on capable GPU runners.
- Optional USD geometry authoring for debug primitives.
- Broader Replicator annotator compatibility and richer dataset capture beyond
  the current extension writer path, including richer annotator integration
  where public APIs permit it.
- L3 advanced realism implementation for richer wave/RIR, material,
  directivity, noise, and estimator realism. Raycast occlusion attenuation
  shipped in 1.3.0 as the first L3 capability; frequency-dependent
  transmission, materials, and diffraction remain open.
- L4 sim-real calibration tooling for measured array pose, gain, time-offset,
  noise, validation artifacts, and sim-vs-real comparisons.
- GCC-PHAT and SRP-PHAT estimation paths as documented public backends.
- ROS 2 adapter as an optional downstream/project layer.
- Broader tested adapters for custom Isaac Lab task asset APIs beyond the
  common tensor/entity patterns documented for the v1 release.
- Pre-publish license, asset, and live-runtime evidence review before any PyPI
  release or git tag.
