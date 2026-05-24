# Roadmap

This roadmap tracks package-level work for `isaac-audio-sensors`. Completed
items are listed separately so future work does not repeat release-candidate
capabilities that already exist.

[V1 Public Scope](v1_scope.md) is the release-scope source of truth. Future
items below are not v1 release gates unless they are promoted by a later scope
change.

## Completed In Current Release Candidate

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
- Release-candidate hygiene docs, versioning notes, archive audit script, and
  build-time distribution audit.

## Future Work

- Automated Isaac Sim and Isaac Lab smoke CI on capable GPU runners.
- Optional USD geometry authoring for debug primitives.
- Broader Replicator annotator compatibility and richer dataset capture beyond
  the current extension writer path, including richer annotator integration
  where public APIs permit it.
- L3 advanced realism implementation for richer wave/RIR, material,
  occlusion, directivity, noise, and estimator realism.
- L4 sim-real calibration tooling for measured array pose, gain, time-offset,
  noise, validation artifacts, and sim-vs-real comparisons.
- GCC-PHAT and SRP-PHAT estimation paths as documented public backends.
- ROS 2 adapter as an optional downstream/project layer.
- Broader tested adapters for custom Isaac Lab task asset APIs beyond the
  common tensor/entity patterns documented for the v1 release candidate.
- Pre-publish license, asset, and live-runtime evidence review before any PyPI
  release or git tag.
