# Phase R9 — Geometry Acoustics Provider Selection

Status: R9.1 and R9.1.1 completed on 2026-09-01; R9.1.2 completed on 2026-09-02; R9.2 and R9.3 are planned.

The remaining R9.2/R9.3 execution order is referenced by [[implementation_phases/01-geometry-provider-qualification|Implementation Plan 01]]. That plan adds no technical requirements: this page is the sole authority for provider qualification, comparison, selection, evidence, limitations, and acceptance semantics.

## Objective

Select the existing acoustic engine that can satisfy the passive-audio requirements before building a maintained Isaac integration. This phase owns provider qualification and the final provider decision; R10 owns product integration.

R9 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: temporary candidate work may exist during qualification, but the completed decision retains no unselected provider integration or other surface without a current qualification or product role.

## Subphase R9.1 — Required Provider Contract

#### Implementation

R9.1 is implemented as the repository-internal
`tools/qualification/geometry_acoustics_contract.py` validator. It accepts one
JSON report with exact `r9.1` contract version, candidate identity and version,
the evaluated Isaac Sim/Kit runtime, and one result for every canonical
criterion. It does not register a backend, change package configuration, or
claim that a provider exists.

Each result uses `pass`, `fail`, or `blocked`, a non-empty explanation, and one
or more typed evidence references. Behavioral passes require a runtime probe or
measurement; phase coherence, propagation, relative amplitude, assembly,
transmission, and performance require measurements. Packaging requires a
packaging probe and licensing requires the official license. Documentation can
support a result but cannot by itself pass a behavioral gate.

The blocking contract requires the provider to support:

- passive audible sources with arbitrary file-backed or generated content;
- separate phase-coherent raw output for every physical microphone;
- relevant scene geometry, materials, static objects, and dynamic objects;
- direct occlusion, reflections, transmission, indirect pathing, and approximate around-edge or around-corner propagation;
- connected rooms, corridors, doors, and openings without clamping remote sources into the array's room;
- physically coherent relative amplitudes without requiring universal dB SPL calibration;
- acoustic-partition or assembly semantics that do not multiply loss merely because one physical barrier uses several meshes or colliders;
- authored frequency-dependent assembly transmission without undocumented total-loss clipping;
- a viable Isaac runtime, packaging, licensing, and performance path.

Bounded provider-native path or ray diagnostics are recorded as the one
non-blocking criterion. Their absence remains an explicit limitation but does
not reject an otherwise qualified provider or add path data to public sensor
state.

The validator derives the outcome: any failed gate is `rejected`; otherwise any
blocked gate is `incomplete`; otherwise the candidate is `qualified`. A report
cannot declare or override its outcome. Human-listener, binaural,
device-speaker-mix, metadata-only, or active-ultrasound-only output does not
satisfy the microphone-array contract.

#### Key Decisions

- Raw multichannel microphone output and passive audible content are non-negotiable gates.
- Approximate pathing/diffraction is required; a complete wave solver is not.
- The maintained product should select one primary passive provider.
- Native provider capabilities take precedence over repository-owned reimplementations when they satisfy the sensor contract and maintenance boundary.
- `qualified` means only that the R9.1 gates have evidence; R9.3 still owns provider selection.

#### Problems / Limitations

No provider is selected by R9.1. The validator checks report completeness,
evidence classes, and outcome semantics; it cannot establish that referenced
evidence is true. R9.2 must produce the runtime measurements. Provider
marketing or a plausible rendered signal remains insufficient. A provider that
cannot represent one acoustic assembly across fragmented geometry, or that
silently changes authored transmission values, does not satisfy the material
contract.

## Subphase R9.1.1 — Core Capture Contract Cleanup

#### Implementation

R9.1.1 is a breaking repository-wide migration of the Core capture contract,
completed before provider qualification. `AudioTimeWindow` now contains only
required `start_time_s`, `end_time_s`, and `frame_index` fields.
`MicrophoneArraySpec.sample_rate_hz` is the sole runtime sample-rate authority;
the selected array determines render length and the projected frame sample
rate. Scene snapshots, time windows, and detections no longer carry
`timestamp_ms`. `AudioSensorFrame.timestamp_ms` remains serialized but is
derived exclusively from `int(round(start_time_s * 1000.0))`.

The former source limit was removed. Every source overlapping the time window
is rendered and localized in deterministic `(start_time_s, source_id)` order,
independent of any output bound. `max_detections` is applied only after
localization by descending array RMS, computed as
`sqrt(mean(per_mic_rms^2))`, with deterministic source-id and detection-id
tie-breaking. A zero limit therefore produces a complete waveform and
aggregate RMS with no detections. The Isaac Lab tensor path applies the same
acoustic priority while retaining fixed-size padded observations.

The incompatible frame contract is `ias.audio_sensor_frame.v2`. Current trace
readers require its exact shape and reject a serialized timestamp that differs
from the derived value. The frame v1 schema, generator resource, and current
trace fixtures were removed; dataset-manifest, calibration-profile, and
dataset-wrapper versions remain v1 because their own contracts did not change.
Core, CLI, Isaac Sim, Isaac Lab, Kit, OmniGraph, Replicator, recording/replay,
examples, smoke tests, and fixtures migrated directly without aliases or
fallback parsers.

#### Key Decisions

- Array configuration owns sample rate; a frame only projects the selected value.
- Output capacity never changes the simulated soundscape or aggregate measurements.
- Deterministic render order exists only for reproducibility and is not an exclusion priority.
- Acoustic RMS is a practical detection priority without adding a more complex salience model.

#### Problems / Limitations

Frame v1 traces are intentionally not accepted by the current frame reader.
`max_detections` controls reported detections, not detectability, audibility, or
physical source contribution. R9.1.1 does not qualify a provider, add a new
backend, or begin R10 integration.

## Subphase R9.1.2 — Physically Honest DOA Ambiguity

#### Implementation

R9.1.2 removes `front_hemisphere` and the complete ambiguity-policy surface from Core, propagation construction, plugins, Isaac Sim, Isaac Lab, Kit state/UI, and TOML. Removed Python arguments have no aliases; old TOML and Kit keys fail explicitly. The Kit binding advances directly to `ias.omni_extension_binding.v5`, and v4 has no compatibility reader.

Exactly two microphones remain supported for `tdoa_least_squares`. The estimate returns every normalized, deduplicated azimuth compatible with the delay, leaves bearing, sector, and elevation unset, reports zero confidence, and records purely geometric front/back ambiguity. When the delay lies at the physical endpoint and both candidates coincide on the baseline axis, the single candidate becomes the unique estimate.

Least-squares with three or more microphones and all SRP-PHAT estimation require at least three microphones whose centered XY positions have rank two. Configuration, runtime binding, and public estimation fail on collinear geometry instead of selecting a symmetric peak or adding a special linear-array model. Four non-collinear microphones are documented as the practical recommendation for redundancy and robustness.

The v2 frame contract remains unchanged: `candidate_bearing_deg`, `ambiguity_class`, and `ambiguity_reason` preserve the evidence needed by downstream consumers, and Isaac Lab retains `ambiguity_mask`. No learning, motion-based resolution, tracking, privileged geometry, or multimodal fusion enters Core. The active SquadBot adapter owns its explicit front-hemisphere context and does not mutate the source `DoaEstimate`; historical Phase 6A/6B fixtures remain immutable.

#### Key Decisions

- Sensor output represents what the array geometry can observe, not a contextual guess.
- Three rank-2 microphones are the minimum for unique 360-degree azimuth; four are recommended but not required.
- Consumer priors may select among candidates only outside the SDK and must preserve their decision origin.
- Frame v2 already carries sufficient ambiguity evidence, so no schema change or new representation is needed.

#### Problems / Limitations

The two-microphone contract represents the compatible azimuths in the public 2D model, not the continuous 3D cone. A geometrically unique estimate can still be degraded by noise, reverberation, finite sampling, or spatial aliasing. R9.1.2 does not add an advanced disambiguation technique, qualify a provider, or begin R10 integration.

## Subphase R9.2 — Candidate Qualification

#### Implementation

Build only the temporary adapters needed to exercise each serious candidate in the intended Isaac runtime. Qualify provider behavior rather than recreating its propagation algorithms. Record runtime availability, license and distribution constraints, raw per-microphone output semantics, phase coherence, dynamic-scene update behavior, material inputs, and performance with diagnostics disabled and enabled.

Qualification must establish that the provider can supply the final, separate, phase-coherent microphone signals later represented by the common `MicrophoneSignalBlock` boundary. Temporary adapters may expose those native signals for measurement, but they do not perform activity detection, DOA estimation, observation construction, learning-label generation, or maintained product integration.

Use a common fixture matrix. One acoustic partition represented by one mesh and by several meshes must produce equivalent transmission. Two independent sequential partitions must compound transmission. A double-leaf construction must accept one authored whole-assembly frequency curve without requiring the SDK to simulate structural coupling. Door and opening cases must preserve alternative propagation rather than forcing all energy through the blocking wall. Moving doors, sources, arrays, and large objects must update bounded state without rebuilding unrelated static geometry.

Verify that the candidate either exposes native path diagnostics or permits a thin optional adapter to the existing `DebugPrimitive` representation. Diagnostic absence is recorded explicitly and weighed against the complete provider contract; path data is never required in `AudioSensorFrame` or ordinary datasets. Reject hidden attenuation clamps, listener-only rendering, mixed-device output, non-phase-coherent channels, and any candidate that requires a permanent duplicate propagation implementation in this repository.

#### Key Decisions

- Qualification uses shared semantic fixtures and measurable outputs, not subjective audition or marketing claims.
- Existing provider geometry, pathing, transmission, reflection, scattering, and diffraction facilities are reused through the thinnest maintainable adapter.
- Temporary comparison adapters are deleted after the final provider decision unless they are part of the selected integration.
- Whole-assembly transmission data is preferred over a repository-owned double-leaf or structural wall solver.
- Provider qualification concerns signal production and propagation behavior, not backend-specific perception.

#### Problems / Limitations

A provider may meet propagation requirements while lacking a useful diagnostic API; that limitation must remain visible in the decision rather than causing path reconstruction in Core. Nominal provider material tables do not establish measured truth for a specific construction, and qualification does not add real-world calibration scope. Simulation evidence alone does not establish physical calibration or sim-to-real validity; later practical-realism work must bound those claims through domain randomization and comparison with physical signals.

## Subphase R9.3 — Candidate Decision

#### Implementation

Treat Steam Audio as the principal existing-engine candidate for passive geometry-aware propagation. Evaluate NVIDIA RTX Acoustic in the installed Isaac runtime, but select it for this role only if it supports arbitrary audible source content and raw per-microphone output rather than only active chirp or ultrasonic operation.

PyRoom remains the analytic provider and is not treated as the general arbitrary-geometry engine. Active acoustics, if added later, remains a separate backend.

Temporary candidate adapters may coexist during qualification, but the phase concludes with one documented primary provider or an explicit no-provider result. It must not leave multiple redundant experimental backends as permanent public surface.

Compare only candidates that satisfy the blocking contract. The decision weighs measured behavior, native capability coverage, maintenance burden, distribution viability, licensing, and intended-runtime performance against the practical-realism objective. Ecosystem preference or a successful availability probe is not sufficient evidence for selection.

After the decision, remove unselected candidate code and its unused configuration, dependencies, tests, and packaging surfaces. Preserve reports and only the tooling needed to revalidate the selected provider; comparison or test convenience does not justify candidate production code.

#### Key Decisions

- Provider research and provider integration are separate phases.
- The selected engine owns the mathematically complex propagation algorithms; the repository does not recreate them.
- One maintainable primary geometry provider is preferred to several partial permanent backends.
- The selected provider supplies microphone signals; it does not own activity detection, DOA semantics, observations, or learning labels.
- Selection follows complete qualification evidence and is not predetermined by ecosystem preference.

#### Problems / Limitations

If no candidate meets passive, per-microphone, dynamic-geometry, and distribution requirements, R10 remains blocked rather than weakening the sensor semantics. A qualified provider may also remain unsuitable for mass-parallel Isaac Lab execution; high-fidelity geometry propagation and scalable policy training are intentionally separate operating regimes.

## Artifacts

R9.1 provides the internal qualification validator and its deterministic unit
and CLI tests. R9.1.1 provides the simplified Core capture contract and v2
frame artifacts. R9.1.2 provides physically honest DOA ambiguity, rank-2 array
validation, and Kit binding v5 without changing frame v2. No candidate report
or provider decision exists yet.

## Files

- `tools/qualification/geometry_acoustics_contract.py`
- `tests/unit/test_geometry_acoustics_contract.py`
- `src/isaac_audio_sensors/core/types/`
- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/core/doa/ambiguity.py`
- `src/isaac_audio_sensors/core/doa/srp_phat.py`
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`
- `src/isaac_audio_sensors/kit/configuration.py`
- `src/isaac_audio_sensors/schemas/audio_sensor_frame.v2.schema.json`
