# System Architecture

## Data flow

A source configuration, a live USD stage, or Lab entities supply source and microphone-array state. Propagation renders multichannel pressure samples for a selected array and time window. Perception consumes that mixture and array geometry to produce observations. Recording can store both stages of the computation.

```text
scene + array + time window → propagation → microphone signal block
                                                  ↓
                                     activity and optional direction
                                                  ↓
                                            observed frame
```

`core.simulation.simulate_frame()` calls the backend once and hands the same signal block to perception and any waveform sink. A recorder can pair the resulting frame with that block. An explicit supervision path can attach truth to a recording for evaluation or learning. Source identities, schedules and isolated stems stay outside observed perception. [Signals, frames and datasets](public-contracts-and-recording.md)

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| Core | Defines the scene, geometry, timing and signal types, parses configuration, models propagation and sensor effects, and runs causal activity and optional direction estimation. The default Analytic backend selects its solver by environment topology. Direction-of-arrival code resolves observed delays and ambiguity independently of the producer. [Acoustic modeling](acoustic-modeling.md) |
| Recording | `SessionRecorder` owns shards, durable writes, recovery and manifest construction. `SessionDataset` provides streaming reads for validation, replay, FLAC conversion, and learning splits. [Recording contracts](public-contracts-and-recording.md) |
| Schemas | Generates the public frame, dataset-manifest and calibration-profile schemas. The Python generators own the definitions and the wheel ships their JSON representations. [Public contracts](public-contracts-and-recording.md) |
| Isaac Sim | Discovers stage entities and transforms, resolves environments, builds snapshots, drives the sensor lifecycle, and publishes frames to Replicator or visualization. An Analytic sensor can attach PhysX direct-path occlusion. The optional Geometry backend uses a prepared scene and owns its transmission, reflection and optional propagation components. [Geometry ownership and setup](geometry-acoustics.md) |
| Isaac Lab | The entity binding reads robot and source pose tensors. It uses CUDA analytic acquisition or per-environment native Geometry acquisition and CUDA perception. The reference binding runs scalar pipelines. Both project results into the same masked observation contract and support selected-environment reset. [Lab integration](isaac-lab-integration.md) |
| Kit | `ExtensionController` owns application state and composes authoring, sensor, recording, validation, and lifecycle services. The window renders state and invokes controller actions. Headless workflows use the same controller. The extension entry point manages startup, shutdown and optional OmniGraph registration. [Isaac Sim and Kit](isaac-sim-and-kit.md) |
| CLI | The parser selects an operation. Command handlers delegate to Core, recording, schema or guided services. [Getting started](getting-started.md) |

## Runtime dependencies

Core types and package imports work in the base Python environment. Optional solvers and simulator integrations load when selected. Selecting Geometry explicitly resolves the Isaac adapter and its configured native libraries. A missing dependency or invalid configuration produces an error at that boundary.

The installed Kit archive provides the SDK and locked audio dependencies. Kit supplies NumPy and its own runtime. The universal Python wheel uses the dependencies declared in package metadata. [Validation and release](validation-and-release.md)

Robot-specific mounting, task policies, training campaigns, and their acceptance criteria belong to downstream projects. The SDK owns reusable acquisition, observation, and recording interfaces. [Compatibility and migration](../decisions/product-boundary-and-compatibility.md)
